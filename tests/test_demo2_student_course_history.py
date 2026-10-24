"""Disposable synthetic metadata/artifacts, not actual decoded video acceptance."""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace

import pytest

from rehab_affect.demo2_student_summary_store import Demo2StudentSummaryStore, StudentSummaryError
from rehab_affect.demo2_measurement_store import Demo2MeasurementStore
from rehab_affect.video_applicability import ApplicabilityStore
from test_demo2_identity_store import make_task, binding_payload, OWNER
from test_demo2_student_summary_store import env, authorize, measurement


def task(env, *, created_at='2026-10-16T11:00:00+00:00', bound=True):
    records, store, tokens, students, _ = env
    adapter = SimpleNamespace(record=records, identity=store.identities,
        sessions={OWNER: (records.account_from_session(tokens[0]), tokens[0])})
    result = make_task(adapter, set_school=False)
    with records._connect() as db:
        db.execute('UPDATE video_analysis_tasks SET created_at=? WHERE task_id=?', (created_at, result.task_id))
    if bound:
        result.binding = store.identities.save_binding(tokens[0], binding_payload(result, students[0]['student_id']))
    return result


def configure(env, work, enabled=True, include_existing=True, **updates):
    payload = dict(student_id=work['student']['student_id'], authorization_id=work['authorization']['authorization_id'],
                   enabled=enabled, include_existing=include_existing, confirmed=True)
    payload.update(updates)
    return env[1].set_automatic_archiving(env[2][0], payload)


def category(env, item, value):
    store = ApplicabilityStore(env[0])
    state = store.workspace(env[2][0], item.task_id)
    store.save(env[2][0], dict(task_id=item.task_id, version=state['version'], revision=state['revision'],
        category=value, goal='PRIVATE_TEACHER_GOAL', reason='PRIVATE_APPLICABILITY_REASON', confirmed=True))


def observe(env, item, **updates):
    return measurement(env, source_type='video_review', task_id=item.task_id, start_sec=0, end_sec=2, **updates)


def export(env, work):
    return env[1].admin_export(env[2][2], work['authorization']['public_id'])


def test_old_and_new_authorizations_never_implicitly_opt_in(env):
    work = authorize(env)
    task(env)
    assert work['authorization']['automatic_archiving'] == dict(enabled=False, include_existing=False, enabled_at=None)
    assert env[1].sync_automatic_history() == dict(created=0, updated=0, skipped=0, errors=0)
    assert export(env, work)['course_history'] == []
    restarted = Demo2StudentSummaryStore(env[0])
    assert restarted.student_workspace(env[2][0], env[3][0]['student_id'])['course_history'] == []


def test_explicit_enable_backfill_technical_entry_idempotency_and_no_pii(env):
    records, store, tokens, students, _ = env
    work = authorize(env)
    item = task(env)
    work = configure(env, work)
    entry = work['course_history'][0]
    assert set(entry) == {'entry_id', 'recorded_on', 'date_basis', 'revision', 'status', 'reviewed',
                          'media', 'measurements', 'provenance', 'created_at', 'updated_at'}
    assert entry['recorded_on'] == '2026-10-16' and entry['date_basis'] == 'upload_date'
    assert entry['status'] == 'pending_review' and entry['reviewed'] is False
    assert entry['measurements'] == [] and entry['revision'] == 1
    assert entry['media'] == dict(duration_sec=3, has_audio=False)
    provenance = entry['provenance']
    assert provenance['identity_scope'] == 'confirmed_sample_frame'
    assert provenance['whole_lesson_tracking'] is False
    assert provenance['scene_metrics_attributed_to_student'] is False
    assert '不代表整课跟踪' in provenance['source_note']
    repeated = configure(env, work)
    assert repeated['course_history'] == work['course_history']
    assert store.sync_automatic_history() == dict(created=0, updated=0, skipped=1, errors=0)
    output = export(env, work)
    assert output['course_history'] == work['course_history']
    text = json.dumps(output)
    for private in (item.task_id, students[0]['student_id'], item.binding['binding_id'], 'SYNTHETIC_NAME',
                    'school_uploader', 'fixture.mp4', 'PRIVATE_', '身份绑定测试课程', 'frame_key', 'task_id'):
        assert private not in text
    with records._connect() as db:
        blob = db.execute('SELECT body_blob FROM demo2_summary_course_history').fetchone()[0]
        assert b'confirmed_sample_frame' not in blob
    listing = store.admin_workspace(tokens[2])['items'][0]
    assert listing['course_count'] == 1 and listing['latest_course_at'] == '2026-10-16'


def test_cutoff_and_explicit_include_existing(env):
    work = authorize(env)
    old = task(env)
    work = configure(env, work, include_existing=False)
    assert work['course_history'] == []
    fresh = task(env, created_at='2026-10-16T12:00:00+00:00')
    assert env[1].sync_automatic_history()['created'] == 1
    assert len(export(env, work)['course_history']) == 1
    enabled_at = work['authorization']['automatic_archiving']['enabled_at']
    work = configure(env, work, include_existing=True)
    assert len(work['course_history']) == 2
    assert work['authorization']['automatic_archiving']['enabled_at'] == enabled_at
    assert old.task_id != fresh.task_id


def test_measurement_post_commit_read_sync_and_multiple_goals(env):
    work = authorize(env)
    item = task(env)
    category(env, item, 'special')
    work = configure(env, work)
    initial = work['course_history'][0]
    observe(env, item)
    entry = export(env, work)['course_history'][0]
    assert entry['status'] == 'reviewed' and entry['reviewed'] is True
    assert entry['entry_id'] == initial['entry_id'] and entry['revision'] == initial['revision'] + 1
    assert entry['date_basis'] == 'lesson_date' and entry['recorded_on'] == '2026-10-15'
    assert entry['measurements'][0]['measurement']['scores']['accuracy'] == 8
    observe(env, item, record_id='SYNTHETIC-goal-two', goal_id='goal-two', reviewed=False)
    pending = export(env, work)['course_history'][0]
    assert pending['status'] == 'pending_review' and pending['measurements'] == []
    observe(env, item, record_id='SYNTHETIC-goal-two', goal_id='goal-two', expected_version=1)
    current = export(env, work)['course_history'][0]
    assert current['status'] == 'reviewed' and len(current['measurements']) == 2
    assert env[1].sync_automatic_history()['updated'] == 0
    assert 'PRIVATE_' not in json.dumps(export(env, work))


@pytest.mark.parametrize('value', ['general', 'irrelevant', 'uncertain', 'insufficient'])
def test_non_special_categories_never_show_scores_even_previously_reviewed(env, value):
    work = authorize(env)
    item = task(env)
    category(env, item, 'special')
    observe(env, item)
    work = configure(env, work)
    assert work['course_history'][0]['status'] == 'reviewed'
    category(env, item, value)
    entry = export(env, work)['course_history'][0]
    assert entry['status'] == 'pending_review' and entry['reviewed'] is False
    assert entry['measurements'] == []
    assert entry['provenance']['source_status'] == 'technical_only'


@pytest.mark.parametrize('paused', [False, True])
@pytest.mark.parametrize('failure', ['identity', 'media_expired', 'frame_missing', 'source_revision',
                                   'measurement_withdrawn', 'measurement_expired', 'measurement_deleted',
                                   'time_range', 'range_end', 'binding_time', 'binding_role', 'binding_scope'])
def test_source_failures_withhold_scores_even_while_paused(env, paused, failure):
    records, store, tokens, students, _ = env
    work = authorize(env)
    item = task(env)
    category(env, item, 'special')
    observe(env, item)
    work = configure(env, work)
    before = work['course_history'][0]
    if paused:
        work = configure(env, work, enabled=False)
        assert work['course_history'] == [before]
    with records._connect() as db:
        if failure == 'identity':
            db.execute("UPDATE demo2_identity_bindings SET status='revoked' WHERE binding_id=?", (item.binding['binding_id'],))
        elif failure == 'media_expired':
            db.execute("UPDATE video_analysis_tasks SET expires_at='2026-10-15T00:00:00+00:00' WHERE task_id=?", (item.task_id,))
        elif failure == 'frame_missing':
            item.paths['s0_f0'].unlink()
        elif failure == 'source_revision':
            raw = dict(item.result, synthetic_revision=2)
            db.execute('UPDATE video_analysis_tasks SET processing_result_json=? WHERE task_id=?', (json.dumps(raw), item.task_id))
        elif failure == 'measurement_withdrawn':
            db.execute("UPDATE demo2_measurements SET status='withdrawn'")
        elif failure == 'measurement_expired':
            db.execute("UPDATE demo2_measurements SET expires_at='2026-10-15T00:00:00+00:00'")
        elif failure == 'measurement_deleted':
            db.execute('DELETE FROM demo2_measurements')
        elif failure == 'binding_time':
            db.execute('UPDATE demo2_identity_bindings SET time_sec=1 WHERE binding_id=?', (item.binding['binding_id'],))
        elif failure == 'binding_role':
            db.execute("UPDATE demo2_identity_bindings SET role='teacher',student_id=NULL WHERE binding_id=?", (item.binding['binding_id'],))
        elif failure == 'binding_scope':
            # Non-student binding permits a foreign scope in this disposable corruption fixture.
            db.execute("UPDATE demo2_identity_bindings SET role='unknown',student_id=NULL,scope_key='foreign-scope' WHERE binding_id=?", (item.binding['binding_id'],))
        else:
            data = json.loads(db.execute('SELECT payload_json FROM demo2_measurements').fetchone()[0])
            if failure == 'range_end':
                data['end_sec'] = 4
            else:
                data['start_sec'] = 1
            db.execute('UPDATE demo2_measurements SET payload_json=?', (json.dumps(data),))
    entry = export(env, work)['course_history'][0]
    assert entry['status'] == 'source_withheld'
    assert entry['reviewed'] is False and entry['measurements'] == []
    assert entry['entry_id'] == before['entry_id'] and entry['revision'] > before['revision']
    assert entry['provenance']['source_status'] == 'withheld'
    assert store.sync_automatic_history()['updated'] == 0


def test_pause_preserves_history_does_not_import_new_courses_or_revised_scores(env):
    work = authorize(env)
    item = task(env)
    category(env, item, 'special')
    observe(env, item)
    work = configure(env, work)
    before = work['course_history'][0]
    work = configure(env, work, enabled=False)
    task(env, created_at='2026-10-16T13:00:00+00:00')
    observe(env, item, expected_version=1)
    courses = export(env, work)['course_history']
    assert len(courses) == 1 and courses[0]['entry_id'] == before['entry_id']
    assert courses[0]['measurements'] == [] and courses[0]['status'] == 'source_withheld'


@pytest.mark.parametrize('end', ['expire', 'revoke'])
def test_authorization_end_cleans_courses_and_new_authorization_stays_disabled(env, end):
    records, store, tokens, students, clock = env
    work = authorize(env)
    task(env)
    work = configure(env, work)
    if end == 'expire':
        clock[0] = datetime(2026, 11, 15, tzinfo=timezone.utc)
    else:
        store.revoke_authorization(tokens[0], dict(student_id=students[0]['student_id'],
            authorization_id=work['authorization']['authorization_id'], confirmed=True))
    assert store.student_workspace(tokens[0], students[0]['student_id'])['course_history'] == []
    with pytest.raises(StudentSummaryError):
        export(env, work)
    store.cleanup_expired()
    with records._connect() as db:
        assert db.execute('SELECT body_blob FROM demo2_summary_course_history').fetchone()[0] is None
    fresh = authorize(env, valid_until='2026-12-01')
    assert fresh['authorization']['automatic_archiving']['enabled'] is False
    assert fresh['course_history'] == []


def test_no_binding_no_course_and_owner_isolation(env):
    work = authorize(env)
    item = task(env, bound=False)
    work = configure(env, work)
    assert work['course_history'] == []
    with pytest.raises(StudentSummaryError):
        env[1].set_automatic_archiving(env[2][1], dict(student_id=env[3][0]['student_id'],
            authorization_id=work['authorization']['authorization_id'], enabled=True, include_existing=True, confirmed=True))
    with pytest.raises(StudentSummaryError):
        env[1].set_automatic_archiving(env[2][2], dict(student_id=env[3][0]['student_id'],
            authorization_id=work['authorization']['authorization_id'], enabled=True, include_existing=True, confirmed=True))
    assert item.task_id


@pytest.mark.parametrize('updates', [dict(enabled=1), dict(include_existing=1), dict(confirmed=1),
                                    dict(full_iep='PRIVATE'), dict(authorization_id='missing')])
def test_optin_validation(env, updates):
    work = authorize(env)
    with pytest.raises(StudentSummaryError):
        configure(env, work, **updates)


def test_background_encryption_error_is_sanitized_and_rolls_back(env, monkeypatch):
    work = authorize(env)
    configure(env, work)
    task(env)
    monkeypatch.setenv('REHAB_DEMO2_DOSSIER_KEY', 'invalid')
    assert env[1].sync_automatic_history() == dict(created=0, updated=0, skipped=0, errors=1)
    with pytest.raises(StudentSummaryError):
        export(env, work)


def test_ciphertext_swap_fails_closed(env):
    records, store, _, _, _ = env
    work = authorize(env)
    task(env)
    task(env, created_at='2026-10-16T13:00:00+00:00')
    work = configure(env, work)
    with records._connect() as db:
        rows = db.execute('SELECT * FROM demo2_summary_course_history').fetchall()
        db.execute('UPDATE demo2_summary_course_history SET body_blob=? WHERE entry_id=?', (rows[0]['body_blob'], rows[1]['entry_id']))
    with pytest.raises(StudentSummaryError):
        export(env, work)
    assert store.sync_automatic_history()['errors'] == 1


def test_withdrawn_old_record_does_not_block_reviewed_replacement_for_same_goal(env):
    work = authorize(env)
    item = task(env)
    category(env, item, 'special')
    original = observe(env, item)
    work = configure(env, work)
    before = work['course_history'][0]
    Demo2MeasurementStore(env[0]).withdraw(env[2][0], dict(record_id=original['record_id'],
        expected_version=1, reason='SYNTHETIC replacement'))
    withdrawn = export(env, work)['course_history'][0]
    assert withdrawn['status'] == 'source_withheld' and withdrawn['measurements'] == []
    replacement = observe(env, item, record_id='SYNTHETIC-replacement',
        scores=dict(accuracy=3, independence=4, consistency=5, transfer=6))
    current = export(env, work)['course_history'][0]
    assert current['entry_id'] == before['entry_id']
    assert current['revision'] > withdrawn['revision']
    assert current['status'] == 'reviewed' and len(current['measurements']) == 1
    assert current['measurements'][0]['measurement']['scores'] == replacement['scores']
    assert env[1].sync_automatic_history()['updated'] == 0
    observe(env, item, record_id='SYNTHETIC-active-draft', goal_id='other-goal', reviewed=False)
    assert export(env, work)['course_history'][0]['status'] == 'pending_review'
    assert export(env, work)['course_history'][0]['measurements'] == []


def test_reviewed_incomplete_observation_does_not_invent_total_or_participation(env):
    work = authorize(env)
    item = task(env)
    category(env, item, 'special')
    observe(env, item, scores=dict(accuracy=8, independence=None, consistency=None, transfer=None))
    work = configure(env, work)
    entry = work['course_history'][0]
    assert entry['measurements'][0]['measurement']['assessment']['overall_score'] is None
    assert entry['measurements'][0]['measurement']['assessment']['insufficient_evidence'] is True
    assert 'participation' not in json.dumps(entry)


def test_concurrent_background_sync_is_unique_and_revision_stable(env):
    work = authorize(env)
    configure(env, work)
    task(env)
    with ThreadPoolExecutor(max_workers=2) as pool:
        counts = list(pool.map(lambda _: env[1].sync_automatic_history(), range(2)))
    assert sum(c['created'] for c in counts) == 1
    assert sum(c['errors'] for c in counts) == 0
    entries = export(env, work)['course_history']
    assert len(entries) == 1 and entries[0]['revision'] == 1


def test_two_students_in_one_course_have_separate_authorized_histories(env):
    records, store, tokens, students, _ = env
    first = authorize(env)
    item = task(env)
    second_student = store.identities.create_student(tokens[0], dict(display_name='SYNTHETIC_SECOND_PUPIL'))
    store.identities.save_binding(tokens[0], binding_payload(item, second_student['student_id'], frame_key='s0_f1'))
    store.save_authorization(tokens[0], dict(student_id=second_student['student_id'], reference='PRIVATE_SECOND_AUTH',
                                           valid_until='2026-11-15', confirmed=True))
    second = store.student_workspace(tokens[0], second_student['student_id'])
    category(env, item, 'special')
    observe(env, item)
    observe(env, item, student_id=second_student['student_id'], record_id='SYNTHETIC-second-pupil',
            scores=dict(accuracy=2, independence=3, consistency=4, transfer=5))
    first, second = configure(env, first), configure(env, second)
    first_course, second_course = export(env, first)['course_history'][0], export(env, second)['course_history'][0]
    assert first_course['entry_id'] != second_course['entry_id']
    assert len(first_course['measurements']) == len(second_course['measurements']) == 1
    assert first_course['measurements'][0]['measurement']['scores']['accuracy'] == 8
    assert second_course['measurements'][0]['measurement']['scores']['accuracy'] == 2
    assert first_course['measurements'][0]['goal_key'] != second_course['measurements'][0]['goal_key']
    assert first_course['measurements'][0]['context_key'] != second_course['measurements'][0]['context_key']
    for public in (export(env, first), export(env, second)):
        assert students[0]['student_id'] not in json.dumps(public)
        assert second_student['student_id'] not in json.dumps(public)


def test_join_keys_stable_across_courses_and_separate_goals_and_contexts(env):
    work = authorize(env)
    first, second = task(env), task(env)
    category(env, first, 'special')
    category(env, second, 'special')
    goal, context = 'PRIVATE_GOAL_FOR_JOIN', 'PRIVATE_CONTEXT_FOR_JOIN'
    observe(env, first, goal_id=goal, measurement_context=context)
    observe(env, second, record_id='SYNTHETIC-same', lesson_id='lesson-two', goal_id=goal, measurement_context=context)
    observe(env, second, record_id='SYNTHETIC-other-goal', lesson_id='lesson-two',
            goal_id='PRIVATE_OTHER_GOAL', measurement_context=context)
    observe(env, second, record_id='SYNTHETIC-other-context', lesson_id='lesson-two',
            goal_id=goal, measurement_context='PRIVATE_OTHER_CONTEXT')
    work = configure(env, work)
    courses = work['course_history']
    single = next(course for course in courses if len(course['measurements']) == 1)['measurements'][0]
    multiple = next(course for course in courses if len(course['measurements']) == 3)['measurements']
    assert set(single) == {'measurement', 'provenance', 'goal_key', 'context_key'}
    assert single['goal_key'].startswith('goal_') and len(single['goal_key']) == 69
    assert single['context_key'].startswith('ctx_') and len(single['context_key']) == 68
    assert int(single['goal_key'][5:], 16) >= 0 and int(single['context_key'][4:], 16) >= 0
    pairs = {(item['goal_key'], item['context_key']) for item in multiple}
    assert (single['goal_key'], single['context_key']) in pairs
    assert len(pairs) == 3
    assert len({item['goal_key'] for item in multiple}) == 2
    assert len({item['context_key'] for item in multiple}) == 2
    serialized = json.dumps(export(env, work))
    assert 'PRIVATE_' not in serialized
    assert env[3][0]['student_id'] not in serialized
    assert env[1].sync_automatic_history()['updated'] == 0


def test_paused_legacy_entries_get_only_join_key_backfill(env):
    records, store, _, _, _ = env
    work = authorize(env)
    item = task(env)
    category(env, item, 'special')
    observe(env, item)
    work = configure(env, work)
    expected = work['course_history'][0]['measurements']
    work = configure(env, work, enabled=False)
    with records._connect() as db:
        student = db.execute('SELECT * FROM demo2_summary_students').fetchone()
        auth = db.execute('SELECT * FROM demo2_summary_authorizations').fetchone()
        row = db.execute('SELECT * FROM demo2_summary_course_history').fetchone()
        binding = store.automatic_history._binding(student, auth, row['task_id'], row['entry_id'])
        state = store._open(binding, row['body_blob'])
        for measured in state['entry']['measurements']:
            measured.pop('goal_key')
            measured.pop('context_key')
        import hashlib
        fingerprint = hashlib.sha256(json.dumps(state, sort_keys=True, allow_nan=False).encode()).hexdigest()
        db.execute('UPDATE demo2_summary_course_history SET body_blob=?,fingerprint=?',
                   (store._seal(binding, state), fingerprint))
    output = export(env, work)['course_history'][0]
    assert output['measurements'] == expected
    assert output['revision'] == row['revision'] + 1
    assert store.sync_automatic_history()['updated'] == 0


def test_same_second_enable_boundary_excludes_old_tasks_but_not_new_tasks(env):
    work = authorize(env)
    env[4][0] = datetime(2026, 10, 16, 12, 0, 0, 700000, tzinfo=timezone.utc)
    timestamp = '2026-10-16T12:00:00+00:00'
    old = task(env, created_at=timestamp)
    work = configure(env, work, include_existing=False)
    assert work['course_history'] == []
    fresh = task(env, created_at=timestamp)
    # Repeating enabled=true must not recapture and exclude unseen new tasks.
    work = configure(env, work, include_existing=False)
    assert len(work['course_history']) == 1
    first_entry = work['course_history'][0]['entry_id']
    work = configure(env, work, enabled=False, include_existing=False)
    paused = task(env, created_at=timestamp)
    work = configure(env, work, include_existing=False)
    assert [entry['entry_id'] for entry in work['course_history']] == [first_entry]
    after_resume = task(env, created_at=timestamp)
    assert env[1].sync_automatic_history()['created'] == 1
    assert len(export(env, work)['course_history']) == 2
    with env[0]._connect() as db:
        excluded = {row[0] for row in db.execute('SELECT task_id FROM demo2_summary_auto_excluded_tasks')}
    assert {old.task_id, fresh.task_id, paused.task_id} <= excluded
    assert after_resume.task_id not in excluded
    work = configure(env, work, include_existing=True)
    assert len(work['course_history']) == 4


def retention_case(env, *, paused=False, reviewed=True, before_delete=None):
    records, _, _, _, clock = env
    work = authorize(env, valid_until='2027-03-01')
    item = task(env)
    category(env, item, 'special')
    observe(env, item, reviewed=reviewed)
    work = configure(env, work)
    if paused:
        work = configure(env, work, enabled=False)
    with records._connect() as db:
        expires = db.execute('SELECT expires_at FROM video_analysis_tasks WHERE task_id=?', (item.task_id,)).fetchone()[0]
    clock[0] = datetime.fromisoformat(expires) + timedelta(seconds=1)
    if before_delete:
        before_delete(work, item)
    outcome = records.enforce_raw_media_retention(now=clock[0])
    assert outcome['deleted_count'] == 1 and outcome['failed'] == []
    assert not item.source.exists() and not item.paths['s0_f0'].exists()
    return work, item


@pytest.mark.parametrize('paused', [False, True])
def test_actual_retention_preserves_only_previously_reviewed_numbers_without_media_reads(env, monkeypatch, paused):
    records, store, _, _, _ = env
    work, item = retention_case(env, paused=paused)
    previous = work['course_history'][0]
    def no_live_read(*args, **kwargs):
        raise AssertionError('Historical validation must not read live video or frame files')
    monkeypatch.setattr(store.identities, '_frame', no_live_read)
    monkeypatch.setattr(store.identities, '_require_media', no_live_read)
    output = export(env, work)
    entry = output['course_history'][0]
    assert entry['entry_id'] == previous['entry_id'] and entry['revision'] == previous['revision'] + 1
    assert entry['status'] == entry['provenance']['source_status'] == 'historical_reviewed'
    assert entry['reviewed'] is True and entry['live_evidence_available'] is False
    assert entry['provenance']['live_evidence_available'] is False
    assert '无法回查' in entry['provenance']['source_note']
    for new, old in zip(entry['measurements'], previous['measurements']):
        assert new['measurement'] == old['measurement']
        assert new['goal_key'] == old['goal_key'] and new['context_key'] == old['context_key']
        assert new['provenance']['source_status'] == 'historical_reviewed'
        assert new['provenance']['live_evidence_available'] is False
    assert store.sync_automatic_history() == dict(created=0, updated=0, skipped=1, errors=0)
    assert export(env, work)['course_history'] == output['course_history']
    assert 'PRIVATE_' not in json.dumps(output) and item.task_id not in json.dumps(output)


@pytest.mark.parametrize('change', ['audit_missing', 'audit_wrong_expiry', 'audit_wrong_actor', 'deleted_before_expiry',
    'binding_withdrawn', 'binding_time', 'measurement_withdrawn', 'measurement_expired', 'measurement_version',
    'measurement_digest', 'source_sha', 'source_revision', 'applicability_category', 'applicability_revision', 'audit_flags_missing'])
def test_retention_history_withholds_when_any_provenance_gate_fails(env, change):
    records, store, _, _, _ = env
    work, item = retention_case(env)
    assert export(env, work)['course_history'][0]['status'] == 'historical_reviewed'
    with records._connect() as db:
        if change == 'audit_missing':
            db.execute("DELETE FROM audit_logs WHERE action='retention_delete'")
        elif change == 'audit_wrong_expiry':
            db.execute("UPDATE audit_logs SET detail_json='{}' WHERE action='retention_delete'")
        elif change == 'audit_wrong_actor':
            db.execute("UPDATE audit_logs SET actor='not-system' WHERE action='retention_delete'")
        elif change == 'audit_flags_missing':
            row = db.execute("SELECT detail_json FROM audit_logs WHERE action='retention_delete'").fetchone()
            detail = json.loads(row['detail_json'])
            detail.pop('raw_media_present_before_delete')
            detail.pop('derived_media_present_before_delete')
            db.execute("UPDATE audit_logs SET detail_json=? WHERE action='retention_delete'", (json.dumps(detail),))
        elif change == 'deleted_before_expiry':
            db.execute("UPDATE video_analysis_tasks SET raw_media_deleted_at='2026-10-16T00:00:00+00:00'")
        elif change == 'binding_withdrawn':
            db.execute("UPDATE demo2_identity_bindings SET status='revoked'")
        elif change == 'binding_time':
            db.execute('UPDATE demo2_identity_bindings SET time_sec=1')
        elif change == 'measurement_withdrawn':
            db.execute("UPDATE demo2_measurements SET status='withdrawn'")
        elif change == 'measurement_expired':
            db.execute("UPDATE demo2_measurements SET expires_at='2026-10-15T00:00:00+00:00'")
        elif change == 'measurement_version':
            db.execute('UPDATE demo2_measurements SET version=version+1')
        elif change == 'measurement_digest':
            data = json.loads(db.execute('SELECT payload_json FROM demo2_measurements').fetchone()[0])
            data['reviewed'] = False
            db.execute('UPDATE demo2_measurements SET payload_json=?', (json.dumps(data),))
        elif change == 'source_sha':
            db.execute('UPDATE video_analysis_tasks SET sha256=?', ('0' * 64,))
        elif change == 'source_revision':
            db.execute("UPDATE video_analysis_tasks SET processing_result_json='{}'")
        elif change == 'applicability_category':
            db.execute("UPDATE demo2_video_applicability SET category='irrelevant'")
        else:
            db.execute("UPDATE demo2_video_applicability SET revision='changed'")
    entry = export(env, work)['course_history'][0]
    assert entry['status'] == 'source_withheld' and entry['measurements'] == []
    assert entry['reviewed'] is False
    assert store.sync_automatic_history()['updated'] == 0


def test_pending_archive_never_becomes_historical_after_retention(env):
    work, _ = retention_case(env, reviewed=False)
    assert work['course_history'][0]['status'] == 'pending_review'
    entry = export(env, work)['course_history'][0]
    assert entry['status'] == 'source_withheld' and entry['measurements'] == []


@pytest.mark.parametrize('end', ['revoke', 'expire'])
def test_historical_authorization_end_clears_all_course_content(env, end):
    records, store, tokens, students, clock = env
    work, _ = retention_case(env)
    assert export(env, work)['course_history'][0]['status'] == 'historical_reviewed'
    if end == 'revoke':
        store.revoke_authorization(tokens[0], dict(student_id=students[0]['student_id'],
            authorization_id=work['authorization']['authorization_id'], confirmed=True))
    else:
        clock[0] = datetime(2027, 3, 1, tzinfo=timezone.utc)
    assert store.student_workspace(tokens[0], students[0]['student_id'])['course_history'] == []
    with pytest.raises(StudentSummaryError):
        export(env, work)
    store.cleanup_expired()
    with records._connect() as db:
        assert db.execute('SELECT body_blob FROM demo2_summary_course_history').fetchone()[0] is None


@pytest.mark.parametrize('paused', [False, True])
def test_expiry_sync_before_retention_keeps_private_checkpoint_for_later_historical(env, paused):
    records, store, _, _, _ = env
    def interim(work, item):
        output = export(env, work)
        entry = output['course_history'][0]
        assert entry['status'] == 'source_withheld' and entry['measurements'] == []
        assert 'last_approved' not in json.dumps(output)
        assert 'PRIVATE_' not in json.dumps(output)
        with records._connect() as db:
            row = db.execute('SELECT * FROM demo2_summary_course_history').fetchone()
            student = db.execute('SELECT * FROM demo2_summary_students').fetchone()
            auth = db.execute('SELECT * FROM demo2_summary_authorizations').fetchone()
            state = store._open(store.automatic_history._binding(student, auth, row['task_id'], row['entry_id']), row['body_blob'])
            assert state['last_approved']['entry']['status'] == 'reviewed'
        assert store.sync_automatic_history()['updated'] == 0
    work, _ = retention_case(env, paused=paused, before_delete=interim)
    final = export(env, work)['course_history'][0]
    assert final['status'] == 'historical_reviewed'
    assert final['measurements'][0]['measurement'] == work['course_history'][0]['measurements'][0]['measurement']
    assert store.sync_automatic_history()['updated'] == 0


@pytest.mark.parametrize('missing', ['raw_media', 'one_frame'])
def test_actual_retention_audit_rejects_media_missing_before_deletion(env, missing):
    records, _, _, _, _ = env
    def remove_early(work, item):
        (item.source if missing == 'raw_media' else item.paths['s0_f1']).unlink()
    work, _ = retention_case(env, before_delete=remove_early)
    entry = export(env, work)['course_history'][0]
    assert entry['status'] == 'source_withheld' and entry['measurements'] == []
    with records._connect() as db:
        detail = json.loads(db.execute("SELECT detail_json FROM audit_logs WHERE action='retention_delete'").fetchone()[0])
    key = 'raw_media_present_before_delete' if missing == 'raw_media' else 'derived_media_present_before_delete'
    assert detail[key] is False


@pytest.mark.parametrize('changed', ['identity', 'measurement'])
def test_checkpoint_invalidated_before_retention_cannot_restore_old_scores(env, changed):
    records, store, _, _, _ = env
    def invalidate_and_restore(work, item):
        assert export(env, work)['course_history'][0]['status'] == 'source_withheld'
        with records._connect() as db:
            if changed == 'identity':
                db.execute("UPDATE demo2_identity_bindings SET status='revoked'")
            else:
                db.execute("UPDATE demo2_measurements SET status='withdrawn'")
        assert export(env, work)['course_history'][0]['measurements'] == []
        with records._connect() as db:
            row = db.execute('SELECT * FROM demo2_summary_course_history').fetchone()
            student = db.execute('SELECT * FROM demo2_summary_students').fetchone()
            auth = db.execute('SELECT * FROM demo2_summary_authorizations').fetchone()
            state = store._open(store.automatic_history._binding(student, auth, row['task_id'], row['entry_id']), row['body_blob'])
            assert 'last_approved' not in state
            if changed == 'identity':
                db.execute("UPDATE demo2_identity_bindings SET status='confirmed'")
            else:
                db.execute("UPDATE demo2_measurements SET status='active'")
    work, _ = retention_case(env, before_delete=invalidate_and_restore)
    entry = export(env, work)['course_history'][0]
    assert entry['status'] == 'source_withheld' and entry['measurements'] == []
