"""HTTP acceptance on fresh synthetic records; never the running pilot."""
import http.client
import json
import threading
from datetime import date, timedelta

import pytest

from rehab_affect import scenario_lab_server as server
from rehab_affect.demo2_identity_store import Demo2IdentityStore
from rehab_affect.student_record_store import Demo2StudentRecordStore


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setenv('REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX', 'SummaryApi-')
    records = Demo2StudentRecordStore(tmp_path / 'summary.sqlite3', tmp_path / 'uploads')
    identities = Demo2IdentityStore(records)
    tokens = {}
    for name, alias in [('school_uploader_01', 'teacher'), ('school_uploader_02', 'other'), ('company_admin', 'admin')]:
        account = records.authenticate_account(name, 'SummaryApi-' + name)
        tokens[alias] = records.create_account_session(account['account_id'])['token']
    records.save_account_school_context(tokens['teacher'], {'city': 'Synthetic city', 'district': 'Synthetic district', 'school_name': 'SYNTHETIC School'})
    records.save_account_school_context(tokens['other'], {'city': 'Synthetic city', 'district': 'Other district', 'school_name': 'SYNTHETIC Other School'})
    pupil = identities.create_student(tokens['teacher'], {'display_name': 'SYNTHETIC PRIVATE NAME', 'student_code': 'PRIVATE-CODE', 'class_name': 'Private class'})
    monkeypatch.setattr(server, 'get_demo2_student_store', lambda: records)
    httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.create_handler(
        scenario_dir=tmp_path, model_path=tmp_path / 'unused', policy_name='rule'))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    host = f'127.0.0.1:{httpd.server_port}'

    def call(path, *, who='teacher', payload=None, method=None, headers=None):
        values = {'Origin': 'http://' + host, 'Content-Type': 'application/json'}
        if who is not None:
            values['Cookie'] = 'rehab_demo2_session=' + tokens[who]
        values.update(headers or {})
        client = http.client.HTTPConnection('127.0.0.1', httpd.server_port, timeout=10)
        try:
            client.request(method or ('GET' if payload is None else 'POST'), path,
                           None if payload is None else json.dumps(payload), headers=values)
            result = client.getresponse()
            body = result.read()
            try:
                data = json.loads(body)
            except ValueError:
                data = body.decode('utf-8', errors='replace')
            return result.status, dict(result.getheaders()), data
        finally:
            client.close()

    yield call, pupil, records
    httpd.shutdown()
    httpd.server_close()
    thread.join(5)


PREFIX = '/api/v1/demo2/student-summaries'


def create_authorization(call, pupil):
    payload = {'student_id': pupil['student_id'], 'reference': 'SYNTHETIC permission record; not real school consent',
               'valid_until': (date.today() + timedelta(days=30)).isoformat(), 'confirmed': True}
    status, _, data = call(PREFIX + '/authorization', payload=payload)
    assert status == 200, data
    return data['authorization']


def test_teacher_summary_company_read_export_and_revoke(api):
    call, pupil, records = api
    auth = create_authorization(call, pupil)
    payload = {'student_id': pupil['student_id'], 'authorization_id': auth['authorization_id'],
               'recorded_on': date.today().isoformat(), 'source_ref': 'SYNTHETIC source; not an IEP',
               'learning_goals': 'Match two synthetic shapes', 'support_methods': 'Use visual cards',
               'domains': {key: 'unknown' for key in ('cognition', 'communication', 'motor', 'sensory', 'social_adaptation')},
               'measurement_id': '', 'reviewed': True}
    status, _, saved = call(PREFIX + '/snapshots', payload=payload)
    assert status == 200, saved
    status, _, data = call(PREFIX + '/student?student_id=' + pupil['student_id'])
    assert status == 200 and len(data['workspace']['snapshots']) == 1
    status, _, admin = call(PREFIX + '/admin?page=1', who='admin')
    assert status == 200 and len(admin['workspace']['items']) == 1
    item = admin['workspace']['items'][0]
    status, headers, export = call(PREFIX + '/export?public_id=' + item['public_id'], who='admin')
    assert status == 200 and 'attachment' in headers.get('Content-Disposition', '')
    assert export['snapshots'][0]['learning_goals'] == payload['learning_goals']
    serialized = json.dumps(export)
    assert all(private not in serialized for private in (pupil['student_id'], pupil['display_name'], pupil['student_code'], payload['source_ref'], 'SYNTHETIC permission'))
    status, _, _ = call(PREFIX + '/authorization/withdraw', payload={'student_id': pupil['student_id'], 'authorization_id': auth['authorization_id'], 'confirmed': True})
    assert status == 200
    status, _, admin = call(PREFIX + '/admin', who='admin')
    assert status == 200 and admin['workspace']['items'] == []
    status, _, _ = call(PREFIX + '/export?public_id=' + item['public_id'], who='admin')
    assert status in (404, 410)


def test_summary_is_opt_in_and_scoped(api):
    call, pupil, _ = api
    status, _, data = call(PREFIX + '/admin', who='admin')
    assert status == 200 and data['workspace']['items'] == []
    assert call(PREFIX + '/admin', who='teacher')[0] == 403
    assert call(PREFIX + '/student?student_id=' + pupil['student_id'], who='other')[0] in (403, 404)
    assert call(PREFIX + '/student?student_id=' + pupil['student_id'], who='admin')[0] == 403
    assert call(PREFIX + '/admin', who=None)[0] == 401
    assert call(PREFIX + '/admin?page=0', who='admin')[0] == 400
    assert call(PREFIX + '/admin?page=1&page=2', who='admin')[0] == 400


def test_summary_page_roles_and_write_origin(api):
    call, pupil, _ = api
    assert call('/demo2/student-summary?student_id=' + pupil['student_id'])[0] == 200
    assert call('/demo2/admin/student-summaries', who='admin')[0] == 200
    assert call('/demo2/admin/student-summaries', who='teacher')[0] == 403
    assert call(PREFIX + '/authorization', payload={}, headers={'Origin': 'https://untrusted.invalid'})[0] == 403
    assert call(PREFIX + '/authorization', payload={}, headers={'Content-Type': 'text/plain'})[0] == 415


def test_summary_maintenance_callbacks_run_independently():
    from types import SimpleNamespace

    calls = []

    def failed_cleanup():
        calls.append('dossier')
        raise RuntimeError('synthetic private material must not be logged')

    worker = server._DossierMaintenance(failed_cleanup, summary_cleanup=lambda: calls.append('summary'))
    turns = iter([False, True])
    worker.stopped = SimpleNamespace(is_set=lambda: next(turns), wait=lambda _: None)
    worker._run()
    assert calls == ['dossier', 'summary']


def test_automatic_partial_failure_is_reported_without_private_values(capsys):
    from types import SimpleNamespace

    report = {'automatic_history': {'errors': 2, 'private_detail': 'PRIVATE-SYNTHETIC-VALUE'}}
    worker = server._DossierMaintenance(None, summary_cleanup=lambda: report)
    turns = iter([False, True])
    worker.stopped = SimpleNamespace(is_set=lambda: next(turns), wait=lambda _: None)
    worker._run()
    stderr = capsys.readouterr().err
    assert 'pending retry (2)' in stderr
    assert 'PRIVATE-SYNTHETIC-VALUE' not in stderr
