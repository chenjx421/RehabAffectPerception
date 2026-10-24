"""Automatic archive HTTP contracts on disposable synthetic records only."""
from __future__ import annotations

from datetime import datetime, timedelta
import http.client
import json
import threading
from types import SimpleNamespace
from urllib.parse import urlencode
from uuid import uuid4

from cryptography.fernet import Fernet
import pytest

from rehab_affect import demo2_student_summary_store as summary_module
from rehab_affect import scenario_lab_server as server
from rehab_affect import student_record_store as records_module
from test_demo2_identity_store import (
    ADMIN, OTHER, OWNER, binding_payload, env as identity_env, login,
    make_task, persist_result, school, student,
)


PREFIX = '/api/v1/demo2/student-summaries'


@pytest.fixture
def archive_api(identity_env, monkeypatch):
    env = identity_env
    monkeypatch.setenv('REHAB_DEMO2_DOSSIER_KEY', Fernet.generate_key().decode())
    clock = [datetime.now().astimezone().replace(microsecond=0)]
    monkeypatch.setattr(summary_module, '_now', lambda: clock[0])
    monkeypatch.setattr(records_module, '_now', lambda: clock[0])
    for username in (OWNER, OTHER):
        school(env, username, context=dict(city='Synthetic city', district='Synthetic district',
                                          school_name='Synthetic school ' + username))
    pupils = {
        'teacher': student(env, display_name='Synthetic learner alpha'),
        'peer': student(env, display_name='Synthetic learner beta'),
        'other': student(env, OTHER, display_name='Synthetic learner gamma'),
    }
    tokens = {alias: login(env, username)[1] for alias, username in
              (('teacher', OWNER), ('other', OTHER), ('admin', ADMIN))}
    monkeypatch.setattr(server, 'get_demo2_student_store', lambda: env.record)
    handler = server.create_handler(scenario_dir=env.tmp, model_path=env.tmp / 'unused', policy_name='rule')
    httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host = f'127.0.0.1:{httpd.server_port}'

    def call(path, *, who='teacher', payload=None, headers=None):
        values = {'Origin': 'http://' + host, 'Content-Type': 'application/json'}
        if who is not None:
            values['Cookie'] = 'rehab_demo2_session=' + tokens[who]
        values.update(headers or {})
        client = http.client.HTTPConnection('127.0.0.1', httpd.server_port, timeout=10)
        try:
            client.request('GET' if payload is None else 'POST', path,
                           body=None if payload is None else json.dumps(payload), headers=values)
            response = client.getresponse()
            raw = response.read()
            try:
                body = json.loads(raw)
            except ValueError:
                body = raw.decode('utf-8', errors='replace')
            return response.status, body
        finally:
            client.close()

    def tick():
        clock[0] += timedelta(seconds=2)

    def refresh_sessions():
        for alias, username in (('teacher', OWNER), ('other', OTHER), ('admin', ADMIN)):
            account = login(env, username)[0]
            tokens[alias] = env.record.create_account_session(account)['token']

    fixture = SimpleNamespace(env=env, records=env.record, call=call, pupils=pupils,
                              clock=clock, tick=tick, handler=handler,
                              refresh_sessions=refresh_sessions)
    try:
        yield fixture
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(5)
        assert not thread.is_alive()


def _ok(api, suffix, **kwargs):
    status, body = api.call(PREFIX + suffix, **kwargs)
    assert status == 200, (suffix, status, body)
    assert body.get('ok') is not False, body
    return body


def _authorize(api, pupil='teacher', who='teacher'):
    body = _ok(api, '/authorization', who=who, payload={
        'student_id': api.pupils[pupil]['student_id'],
        'reference': 'Synthetic permission only; not real consent',
        'valid_until': (api.clock[0].date() + timedelta(days=30)).isoformat(),
        'confirmed': True,
    })
    return body['authorization']


def _automatic(api, auth, *, pupil='teacher', enabled=True, include_existing=False, who='teacher'):
    body = _ok(api, '/automatic', who=who, payload={
        'student_id': api.pupils[pupil]['student_id'],
        'authorization_id': auth['authorization_id'], 'enabled': enabled,
        'confirmed': True, 'include_existing': include_existing,
    })
    assert body['ok'] is True
    config = body['workspace']['authorization']['automatic_archiving']
    assert config['enabled'] is enabled
    assert config['include_existing'] is include_existing
    if enabled:
        assert datetime.fromisoformat(config['enabled_at']) <= api.clock[0]
    return body['workspace']


def _workspace(api, pupil='teacher', who='teacher'):
    return _ok(api, '/student?' + urlencode({'student_id': api.pupils[pupil]['student_id']}), who=who)['workspace']


def _export(api, auth):
    return _ok(api, '/export?' + urlencode({'public_id': auth['public_id']}), who='admin')


def _task(api, pupil='teacher', *, bind=True):
    api.tick()
    username = OTHER if pupil == 'other' else OWNER
    task = make_task(api.env, username, count=3, set_school=False)
    if bind:
        api.env.identity.save_binding(task.token, binding_payload(task, api.pupils[pupil]['student_id']))
    return task


def _course_rows(api):
    # Inspect only disposable fixture schema; the public contract does not name its table.
    with api.records._connect() as db:
        tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'demo2_summary_%'")]
        rows = []
        for name in tables:
            columns = {r['name']: r['type'] for r in db.execute(f'PRAGMA table_info("{name}")')}
            if {'authorization_id', 'task_id'} <= columns.keys():
                rows.extend(dict(row) for row in db.execute(f'SELECT * FROM "{name}"'))
        return rows


def _assert_no_scores(entry):
    assert entry['measurements'] == [], entry
    assert entry.get('measurement') is None, entry
    for key in ('overall_score', 'provisional_score', 'score', 'scores', 'assessment'):
        assert entry.get(key) is None, entry


def _review_measurement(api, task, *, record_id=None, expected_version=0, accuracy=8, reviewed=True):
    applicability = '/api/v1/demo2/applicability'
    status, body = api.call(applicability + '?' + urlencode({'task_id': task.task_id}))
    assert status == 200, body
    # Applicability is a separate human confirmation, never inferred from ready media.
    work = body['result']
    status, body = api.call(applicability, payload=dict(
        task_id=task.task_id, version=work['version'], revision=work['revision'],
        category='special', goal='Synthetic sorting goal', reason='Synthetic teacher review', confirmed=True))
    assert status == 200, body
    record_id = record_id or 'auto-measurement-' + uuid4().hex
    status, body = api.call('/api/v1/demo2/measurements', payload={
        'record_id': record_id, 'expected_version': expected_version,
        'student_id': api.pupils['teacher']['student_id'],
        'lesson_date': api.clock[0].date().isoformat(), 'lesson_id': task.task_id,
        'course_name': 'Synthetic course', 'goal_id': 'synthetic-sort',
        'measurement_context': 'synthetic classroom', 'criterion': 'Observe three attempts',
        'scores': dict(accuracy=accuracy, independence=7, consistency=6, transfer=5),
        'opportunities': 3, 'observed': 2, 'reviewed': reviewed,
        'evidence': 'Synthetic teacher evidence', 'source_type': 'video_review',
        'task_id': task.task_id, 'start_sec': 0, 'end_sec': 2,
    })
    assert status == 200, body
    return record_id


def test_legacy_authorization_is_auto_off_and_get_does_not_backfill(archive_api):
    api = archive_api
    auth = _authorize(api)
    _task(api)
    work = _workspace(api)
    config = work['authorization']['automatic_archiving']
    assert config['enabled'] is False
    assert config['include_existing'] is False
    assert work['course_history'] == []
    assert _export(api, auth)['course_history'] == []


@pytest.mark.parametrize('include_existing', [False, True])
def test_http_enable_future_only_or_explicit_existing_backfill(archive_api, include_existing):
    api = archive_api
    auth = _authorize(api)
    _task(api)
    api.tick()
    _automatic(api, auth, include_existing=include_existing)
    assert len(_workspace(api)['course_history']) == int(include_existing)
    _task(api)
    history = _workspace(api)['course_history']
    assert len(history) == 1 + int(include_existing)
    assert all(entry['status'] == 'pending_review' for entry in history)
    for entry in history:
        _assert_no_scores(entry)
    assert len(_export(api, auth)['course_history']) == len(history)
    listing = _ok(api, '/admin', who='admin')['workspace']['items']
    item = next(row for row in listing if row['public_id'] == auth['public_id'])
    assert item['course_count'] == len(history)
    assert item['latest_course_at']


def test_periodic_maintenance_archives_without_a_browser_or_session(archive_api):
    api = archive_api
    auth = _authorize(api)
    _automatic(api, auth)
    _task(api)
    assert _course_rows(api) == []
    # This is the same sessionless callback installed on periodic summary maintenance.
    api.handler.cleanup_expired_student_summaries()
    assert len(_course_rows(api)) == 1
    api.handler.cleanup_expired_student_summaries()
    assert len(_course_rows(api)) == 1
    assert len(_workspace(api)['course_history']) == 1


def test_rescan_is_idempotent_and_review_updates_the_same_entry(archive_api):
    api = archive_api
    auth = _authorize(api)
    _automatic(api, auth)
    task = _task(api)
    original = _workspace(api)['course_history'][0]
    assert original['status'] == 'pending_review'
    _assert_no_scores(original)
    for _ in range(3):
        rescanned = _workspace(api)['course_history']
        assert len(rescanned) == 1
        assert rescanned[0]['entry_id'] == original['entry_id']
        assert rescanned[0]['revision'] == original['revision']
    record_id = _review_measurement(api, task)
    reviewed = _workspace(api)['course_history']
    assert len(reviewed) == 1
    assert reviewed[0]['entry_id'] == original['entry_id']
    assert reviewed[0]['status'] == 'reviewed'
    assert reviewed[0]['revision'] > original['revision']
    assert len(reviewed[0]['measurements']) == 1
    assert reviewed[0]['measurements'][0]['measurement']['scores']['accuracy'] == 8
    _review_measurement(api, task, record_id=record_id, expected_version=1, accuracy=9)
    updated = _workspace(api)['course_history']
    assert len(updated) == 1 and updated[0]['entry_id'] == original['entry_id']
    assert updated[0]['revision'] > reviewed[0]['revision']
    assert len(updated[0]['measurements']) == 1
    assert updated[0]['measurements'][0]['measurement']['scores']['accuracy'] == 9
    assert len(_course_rows(api)) == 1


def test_pause_keeps_history_stops_new_entries_and_withholds_stale_scores(archive_api):
    api = archive_api
    auth = _authorize(api)
    _automatic(api, auth)
    task = _task(api)
    record_id = _review_measurement(api, task)
    original = _workspace(api)['course_history'][0]
    assert original['status'] == 'reviewed'
    _automatic(api, auth, enabled=False)
    _task(api)
    status, body = api.call('/api/v1/demo2/measurements/withdraw', payload={
        'record_id': record_id, 'expected_version': 1, 'reason': 'Synthetic correction'})
    assert status == 200, body
    for history in (_workspace(api)['course_history'], _export(api, auth)['course_history']):
        assert len(history) == 1 and history[0]['entry_id'] == original['entry_id']
        _assert_no_scores(history[0])


def test_unreviewed_measurement_never_turns_pending_course_into_a_rating(archive_api):
    api = archive_api
    auth = _authorize(api)
    _automatic(api, auth)
    task = _task(api)
    _review_measurement(api, task, reviewed=False)
    for history in (_workspace(api)['course_history'], _export(api, auth)['course_history']):
        assert len(history) == 1
        assert history[0]['status'] == 'pending_review'
        _assert_no_scores(history[0])


def test_reprocessed_source_requires_current_binding_without_duplicate_entry(archive_api):
    api = archive_api
    auth = _authorize(api)
    _automatic(api, auth)
    task = _task(api)
    _review_measurement(api, task)
    original = _workspace(api)['course_history'][0]
    assert original['status'] == 'reviewed'
    task.result['sampling']['window_sec'] = 10
    revision = persist_result(api.env, task.task_id, task.result)
    # The previous binding and reviewed measurement are now stale.
    for entry in _workspace(api)['course_history']:
        _assert_no_scores(entry)
    api.env.identity.save_binding(task.token, binding_payload(
        task, api.pupils['teacher']['student_id'], frame_revision=revision))
    refreshed = _workspace(api)['course_history']
    assert len(refreshed) == 1 and refreshed[0]['entry_id'] == original['entry_id']
    assert refreshed[0]['revision'] > original['revision']
    assert refreshed[0]['status'] == 'pending_review'
    _assert_no_scores(refreshed[0])
    assert len(_course_rows(api)) == 1


@pytest.mark.parametrize('analysis_status', ['queued', 'processing', 'failed', 'completed', 'uploaded_pending_worker'])
def test_only_exact_evidence_ready_tasks_are_automatically_archived(archive_api, analysis_status):
    api = archive_api
    auth = _authorize(api)
    _automatic(api, auth)
    task = _task(api)
    with api.records._connect() as db:
        db.execute('UPDATE video_analysis_tasks SET analysis_status=? WHERE task_id=?', (analysis_status, task.task_id))
    assert _workspace(api)['course_history'] == []
    assert _export(api, auth)['course_history'] == []


@pytest.mark.parametrize('invalidation', ['withdraw', 'expire'])
def test_authorization_withdrawal_or_expiry_hides_and_purges_course_blobs(archive_api, invalidation):
    api = archive_api
    auth = _authorize(api)
    _automatic(api, auth)
    _task(api)
    assert len(_workspace(api)['course_history']) == 1
    if invalidation == 'withdraw':
        _ok(api, '/authorization/withdraw', payload={
            'student_id': api.pupils['teacher']['student_id'],
            'authorization_id': auth['authorization_id'], 'confirmed': True})
    else:
        api.clock[0] = datetime.fromisoformat(auth['valid_until']).replace(tzinfo=api.clock[0].tzinfo)
        # Isolate authorization expiry from ordinary eight-hour session expiry.
        api.refresh_sessions()
    assert _workspace(api)['course_history'] == []
    assert _ok(api, '/admin', who='admin')['workspace']['items'] == []
    status, _ = api.call(PREFIX + '/export?' + urlencode({'public_id': auth['public_id']}), who='admin')
    assert status in (404, 410)
    api.handler.cleanup_expired_student_summaries()
    rows = _course_rows(api)
    assert len(rows) == 1
    assert rows[0]['body_blob'] is None
    payload = dict(student_id=api.pupils['teacher']['student_id'], authorization_id=auth['authorization_id'],
                   enabled=True, confirmed=True, include_existing=True)
    assert api.call(PREFIX + '/automatic', payload=payload)[0] in (404, 409, 410)


def test_only_current_confirmed_binding_can_enter_its_student_archive(archive_api):
    api = archive_api
    auth = _authorize(api)
    peer_auth = _authorize(api, pupil='peer')
    _automatic(api, auth)
    _automatic(api, peer_auth, pupil='peer')
    task = _task(api, bind=False)
    assert _workspace(api)['course_history'] == []
    api.env.identity.save_binding(task.token, binding_payload(task, api.pupils['peer']['student_id']))
    assert _workspace(api)['course_history'] == []
    assert len(_workspace(api, pupil='peer')['course_history']) == 1
    assert _export(api, auth)['course_history'] == []
    # Both students belong to one school, but an authorization cannot be borrowed.
    payload = dict(student_id=api.pupils['peer']['student_id'], authorization_id=auth['authorization_id'],
                   enabled=True, confirmed=True, include_existing=True)
    assert api.call(PREFIX + '/automatic', payload=payload)[0] in (403, 404, 409, 410)


@pytest.mark.parametrize('change', ['school', 'disabled', 'channel'])
def test_scope_or_owner_change_blocks_company_history(archive_api, change):
    api = archive_api
    auth = _authorize(api)
    _automatic(api, auth)
    _task(api)
    assert len(_workspace(api)['course_history']) == 1
    owner = api.pupils['teacher']['owner_account_id']
    with api.records._connect() as db:
        if change == 'school':
            db.execute("UPDATE school_contexts SET school_name='Synthetic migrated school' WHERE account_id=?", (owner,))
        elif change == 'disabled':
            db.execute("UPDATE platform_accounts SET status='disabled' WHERE account_id=?", (owner,))
        else:
            db.execute('UPDATE platform_accounts SET bound_channel_id=NULL WHERE account_id=?', (owner,))
    assert _ok(api, '/admin', who='admin')['workspace']['items'] == []
    assert api.call(PREFIX + '/export?' + urlencode({'public_id': auth['public_id']}), who='admin')[0] in (403, 404, 410)


@pytest.mark.parametrize('who,expected', [(None, 401), ('admin', 403), ('other', 404)])
def test_configuration_requires_own_school_authority(archive_api, who, expected):
    api = archive_api
    auth = _authorize(api)
    payload = dict(student_id=api.pupils['teacher']['student_id'], authorization_id=auth['authorization_id'],
                   enabled=True, confirmed=True, include_existing=True)
    status, _ = api.call(PREFIX + '/automatic', who=who, payload=payload)
    assert status == expected


@pytest.mark.parametrize('updates', [dict(enabled=1), dict(include_existing=1), dict(confirmed=False),
                                    dict(confirmed=1), dict(unknown='not allowed')])
def test_automatic_configuration_rejects_unconfirmed_or_non_boolean_payloads(archive_api, updates):
    api = archive_api
    auth = _authorize(api)
    payload = dict(student_id=api.pupils['teacher']['student_id'], authorization_id=auth['authorization_id'],
                   enabled=True, confirmed=True, include_existing=False)
    payload.update(updates)
    assert api.call(PREFIX + '/automatic', payload=payload)[0] == 400
    assert _workspace(api)['authorization']['automatic_archiving']['enabled'] is False


def test_automatic_write_rejects_cross_origin(archive_api):
    api = archive_api
    auth = _authorize(api)
    payload = dict(student_id=api.pupils['teacher']['student_id'], authorization_id=auth['authorization_id'],
                   enabled=True, confirmed=True, include_existing=False)
    assert api.call(PREFIX + '/automatic', payload=payload, headers={'Origin': 'https://untrusted.invalid'})[0] == 403
