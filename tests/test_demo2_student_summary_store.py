"""Synthetic-only tests: no live accounts, media or student records."""
from datetime import datetime, timezone
import json

from cryptography.fernet import Fernet
import pytest

from rehab_affect import demo2_student_summary_store as module
from rehab_affect.demo2_student_summary_store import Demo2StudentSummaryStore, StudentSummaryError
from rehab_affect.demo2_measurement_store import Demo2MeasurementStore
from rehab_affect.student_record_store import Demo2StudentRecordStore


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX', 'SummarySynthetic-')
    monkeypatch.setenv('REHAB_DEMO2_DOSSIER_KEY', Fernet.generate_key().decode())
    clock = [datetime(2026, 10, 16, 12, tzinfo=timezone.utc)]
    monkeypatch.setattr(module, '_now', lambda: clock[0])
    records = Demo2StudentRecordStore(tmp_path / 'synthetic.sqlite3', tmp_path / 'uploads')
    tokens = []
    for name in ('school_uploader_01', 'school_uploader_02', 'company_admin'):
        account = records.authenticate_account(name, 'SummarySynthetic-' + name)
        tokens.append(records.create_account_session(account)['token'])
    store = Demo2StudentSummaryStore(records)
    students = []
    for index, token in enumerate(tokens[:2]):
        records.save_account_school_context(token, dict(city='SYNTHETIC CITY', district='SYNTHETIC DISTRICT',
                                                       school_name='SYNTHETIC SCHOOL ' + str(index)))
        students.append(store.identities.create_student(token, dict(display_name='SYNTHETIC_NAME_' + str(index),
                                                                    student_code='CODE_' + str(index))))
    return records, store, tokens, students, clock


def authorize(env, **updates):
    _, store, tokens, students, _ = env
    payload = dict(student_id=students[0]['student_id'], reference='PRIVATE_AUTH_REFERENCE',
                   valid_until='2026-11-15', confirmed=True)
    payload.update(updates)
    authorization = store.save_authorization(tokens[0], payload)
    work = store.student_workspace(tokens[0], payload['student_id'])
    assert authorization == work['authorization']
    return work


def snapshot_payload(work, **updates):
    payload = dict(student_id=work['student']['student_id'],
                   authorization_id=work['authorization']['authorization_id'], recorded_on='2026-10-15',
                   source_ref='PRIVATE_TEACHER_SOURCE_REFERENCE', learning_goals='Sort three classroom objects',
                   support_methods='Use picture prompts and allow a pause',
                   domains={k: 'with_support' for k in module.DOMAINS}, measurement_id='', reviewed=True)
    payload.update(updates)
    return payload


def saved(env, **updates):
    work = authorize(env)
    return env[1].save_snapshot(env[2][0], snapshot_payload(work, **updates))


def test_contract_encryption_export_minimization_and_append_only(env):
    records, store, tokens, students, _ = env
    work = saved(env)
    store.save_snapshot(tokens[0], snapshot_payload(work, learning_goals='Match two shapes'))
    listing = store.admin_workspace(tokens[2])
    assert set(listing) == {'items', 'pagination', 'policy'}
    assert listing['items'][0]['snapshot_count'] == 2
    public_id = listing['items'][0]['public_id']
    exported = store.admin_export(tokens[2], public_id)
    assert len(exported['snapshots']) == 2
    item = exported['snapshots'][0]
    assert set(item) == {'snapshot_id', 'recorded_on', 'learning_goals', 'support_methods', 'domains',
                         'measurement', 'provenance', 'reviewed'}
    assert item['measurement'] is None
    assert item['provenance']['source_status'] == 'manual_reviewed'
    assert exported['policy']['research'] is False
    assert exported['policy']['training'] is False
    assert exported['policy']['pseudonymous_not_anonymous'] is True
    text = json.dumps(exported)
    for forbidden in (students[0]['student_id'], 'SYNTHETIC_NAME', 'PRIVATE_AUTH', 'PRIVATE_TEACHER',
                      'source_ref', 'authorization_id', 'student_code', 'school_uploader'):
        assert forbidden not in text
    with records._connect() as db:
        auth_blob = db.execute('SELECT reference_blob FROM demo2_summary_authorizations').fetchone()[0]
        body_blob = db.execute('SELECT body_blob FROM demo2_summary_snapshots LIMIT 1').fetchone()[0]
    assert b'PRIVATE_AUTH' not in auth_blob
    assert b'Sort three' not in body_blob
    assert Demo2StudentSummaryStore(records).student_workspace(tokens[0], students[0]['student_id'])['authorization']['public_id'] == public_id


def test_permissions_account_scope_and_raw_identifier_admin_denial(env):
    records, store, tokens, students, _ = env
    work = saved(env)
    for operation in (lambda: store.student_workspace(tokens[1], students[0]['student_id']),
                      lambda: store.student_workspace(tokens[2], students[0]['student_id']),
                      lambda: store.admin_workspace(tokens[0]),
                      lambda: store.admin_export(tokens[2], students[0]['student_id']),
                      lambda: store.admin_workspace('invalid-token')):
        with pytest.raises(StudentSummaryError):
            operation()
    store.save_authorization(tokens[1], dict(student_id=students[1]['student_id'], reference='OTHER',
                                            valid_until='2026-11-15', confirmed=True))
    other = store.student_workspace(tokens[1], students[1]['student_id'])
    with pytest.raises(StudentSummaryError):
        store.save_snapshot(tokens[1], snapshot_payload(other, authorization_id=work['authorization']['authorization_id']))
    # Disposable fixture only: simulate an external account-school migration.
    with records._connect() as db:
        row = db.execute('SELECT owner_account_id FROM demo2_identity_students WHERE student_id=?', (students[0]['student_id'],)).fetchone()
        db.execute("UPDATE school_contexts SET school_name='MIGRATED SYNTHETIC SCHOOL' WHERE account_id=?", (row['owner_account_id'],))
    assert row is not None
    with pytest.raises(StudentSummaryError):
        store.admin_export(tokens[2], work['authorization']['public_id'])
    with pytest.raises(StudentSummaryError):
        store.student_workspace(tokens[0], students[0]['student_id'])


@pytest.mark.parametrize('until', ['2026-10-16', '2026-10-15', '2027-10-17', 'forever', None])
def test_validity_bounds(env, until):
    with pytest.raises(StudentSummaryError):
        authorize(env, valid_until=until)


@pytest.mark.parametrize('until', ['2026-10-17', '2027-10-16'])
def test_validity_endpoints(env, until):
    assert authorize(env, valid_until=until)['authorization']['active']


@pytest.mark.parametrize('updates', [dict(confirmed=False), dict(confirmed=1), dict(reference=''),
                                    dict(diagnosis='not permitted'), dict(purpose='research')])
def test_authorization_strict_payload(env, updates):
    with pytest.raises(StudentSummaryError):
        authorize(env, **updates)


@pytest.mark.parametrize('updates', [dict(reviewed=False), dict(reviewed=1), dict(source_ref=''),
    dict(recorded_on='2026-10-17'), dict(domains={'cognition': 'independent'}),
    dict(diagnosis='not permitted'), dict(full_iep='not permitted'), dict(scores={'accuracy': 10}),
    dict(professional_conclusion='not permitted'), dict(learning_goals='SYNTHETIC_NAME_0 observes'),
    dict(support_methods='contact private@example.test'), dict(learning_goals='clinical diagnosis text')])
def test_snapshot_validation_and_pii_rejection(env, updates):
    work = authorize(env)
    with pytest.raises(StudentSummaryError):
        env[1].save_snapshot(env[2][0], snapshot_payload(work, **updates))


def test_expiry_blocks_reads_before_cleanup_and_purges_blobs(env):
    records, store, tokens, students, clock = env
    work = saved(env)
    clock[0] = datetime(2026, 11, 15, tzinfo=timezone.utc)
    assert not store.student_workspace(tokens[0], students[0]['student_id'])['snapshots']
    assert store.admin_workspace(tokens[2])['items'] == []
    with pytest.raises(StudentSummaryError):
        store.admin_export(tokens[2], work['authorization']['public_id'])
    with pytest.raises(StudentSummaryError):
        store.save_snapshot(tokens[0], snapshot_payload(work, recorded_on='2026-11-15'))
    assert store.cleanup_expired() == dict(purged_snapshots=1, purged_references=1)
    assert store.cleanup_expired() == dict(purged_snapshots=0, purged_references=0)
    with records._connect() as db:
        assert db.execute('SELECT body_blob FROM demo2_summary_snapshots').fetchone()[0] is None
        assert db.execute('SELECT reference_blob FROM demo2_summary_authorizations').fetchone()[0] is None


def test_revoke_purges_and_reauthorization_keeps_pseudonym_not_content(env):
    records, store, tokens, students, _ = env
    work = saved(env)
    payload = dict(student_id=students[0]['student_id'], authorization_id=work['authorization']['authorization_id'], confirmed=True)
    revoked = store.revoke_authorization(tokens[0], payload)
    assert revoked['authorization']['status'] == 'revoked'
    assert revoked['snapshots'] == []
    with pytest.raises(StudentSummaryError):
        store.admin_export(tokens[2], work['authorization']['public_id'])
    fresh = authorize(env)
    assert fresh['authorization']['public_id'] == work['authorization']['public_id']
    assert fresh['snapshots'] == []
    with records._connect() as db:
        assert db.execute('SELECT body_blob FROM demo2_summary_snapshots').fetchone()[0] is None


def test_ciphertext_swap_fails_closed(env):
    records, store, tokens, students, _ = env
    work = saved(env)
    store.save_snapshot(tokens[0], snapshot_payload(work, learning_goals='Match objects'))
    with records._connect() as db:
        rows = db.execute('SELECT snapshot_id,body_blob FROM demo2_summary_snapshots').fetchall()
        db.execute('UPDATE demo2_summary_snapshots SET body_blob=? WHERE snapshot_id=?', (rows[0]['body_blob'], rows[1]['snapshot_id']))
    with pytest.raises(StudentSummaryError) as exc:
        store.student_workspace(tokens[0], students[0]['student_id'])
    assert exc.value.code == 'summary_integrity'


def measurement(env, **updates):
    records, _, tokens, students, _ = env
    measurements = Demo2MeasurementStore(records)
    payload = dict(record_id='SYNTHETIC-measurement', expected_version=0, student_id=students[0]['student_id'],
                   lesson_date='2026-10-15', lesson_id='SYNTHETIC-lesson', course_name='PRIVATE_COURSE_NAME',
                   goal_id='sort', measurement_context='classroom', criterion='PRIVATE_CRITERION_TEXT',
                   scores=dict(accuracy=8, independence=7, consistency=6, transfer=5), opportunities=3, observed=2,
                   reviewed=True, evidence='PRIVATE_RAW_EVIDENCE SYNTHETIC_NAME_0', source_type='classroom_observation',
                   teacher_prompt='PRIVATE_TEACHER_PROMPT')
    payload.update(updates)
    return measurements.save(tokens[0], payload)


def test_measurement_import_minimization_and_version_drift(env):
    records, store, tokens, students, _ = env
    original = measurement(env)
    work = saved(env, measurement_id=original['record_id'])
    output = store.admin_export(tokens[2], work['authorization']['public_id'])
    imported = output['snapshots'][0]
    assert imported['measurement']['scores']['accuracy'] == 8
    assert imported['provenance']['source_version'] == 1
    assert imported['provenance']['rule_version'] == original['rubric_version']
    assert imported['provenance']['source_status'] == 'current'
    assert 'PRIVATE_' not in json.dumps(output)
    assert original['record_id'] not in json.dumps(output)
    measurement(env, expected_version=1)
    assert_withheld_summary(store.admin_export(tokens[2], work['authorization']['public_id'])['snapshots'], work['snapshots'][0])
    assert_withheld_summary(store.student_workspace(tokens[0], students[0]['student_id'])['snapshots'], work['snapshots'][0])


@pytest.mark.parametrize('change', ['unreviewed', 'expired', 'withdrawn', 'scope', 'student', 'video'])
def test_reject_unavailable_measurements(env, change):
    records, store, tokens, students, _ = env
    original = measurement(env, reviewed=change != 'unreviewed')
    with records._connect() as db:
        if change == 'expired':
            db.execute("UPDATE demo2_measurements SET expires_at='2026-10-15T00:00:00+00:00'")
        elif change == 'withdrawn':
            db.execute("UPDATE demo2_measurements SET status='withdrawn'")
        elif change in {'scope', 'student'}:
            # FK-consistent identity change in the isolated fixture.
            db.execute('UPDATE demo2_measurements SET owner_account_id=?,scope_key=?,student_id=?',
                       (students[1]['owner_account_id'], students[1]['scope_key'], students[1]['student_id']))
        elif change == 'video':
            data = dict(original, source_type='video_review', task_id='missing-task')
            db.execute('UPDATE demo2_measurements SET payload_json=?', (json.dumps(data),))
    work = authorize(env)
    with pytest.raises(StudentSummaryError):
        store.save_snapshot(tokens[0], snapshot_payload(work, measurement_id=original['record_id']))


def test_incomplete_measurement_has_no_invented_score(env):
    _, store, tokens, _, _ = env
    original = measurement(env, scores=dict(accuracy=8, independence=None, consistency=None, transfer=None))
    work = saved(env, measurement_id=original['record_id'])
    assessment = store.admin_export(tokens[2], work['authorization']['public_id'])['snapshots'][0]['measurement']['assessment']
    assert assessment['overall_score'] is None
    assert assessment['insufficient_evidence'] is True


def test_pagination_query_and_encryption_failure(env, monkeypatch):
    _, store, tokens, _, _ = env
    work = saved(env)
    assert store.admin_workspace(tokens[2], page=2)['items'] == []
    assert store.admin_workspace(tokens[2], query=work['authorization']['public_id'])['pagination']['total'] == 1
    for page in (0, -1, True, 10001, '1'):
        with pytest.raises(StudentSummaryError):
            store.admin_workspace(tokens[2], page=page)
    with pytest.raises(StudentSummaryError):
        store.admin_workspace(tokens[2], query='SYNTHETIC NAME')
    monkeypatch.setenv('REHAB_DEMO2_DOSSIER_KEY', 'invalid')
    with pytest.raises(StudentSummaryError):
        store.admin_export(tokens[2], work['authorization']['public_id'])


def assert_withheld_summary(snapshots, original):
    assert len(snapshots) == 1
    summary = snapshots[0]
    for key in ('snapshot_id', 'recorded_on', 'learning_goals', 'support_methods', 'domains', 'reviewed'):
        assert summary[key] == original[key]
    assert summary['measurement'] is None
    assert summary['provenance']['source_status'] == 'withheld'
    assert '不展示测量分数' in summary['provenance']['source_note']
    assert 'SYNTHETIC-measurement' not in json.dumps(summary)
    assert 'PRIVATE_' not in json.dumps(summary)


@pytest.mark.parametrize('change', ['expired', 'withdrawn', 'unreviewed', 'deleted'])
def test_imported_source_later_invalidation_retains_independent_summary(env, change):
    records, store, tokens, students, _ = env
    original = measurement(env)
    work = saved(env, measurement_id=original['record_id'])
    with records._connect() as db:
        if change == 'expired':
            db.execute("UPDATE demo2_measurements SET expires_at='2026-10-15T00:00:00+00:00'")
        elif change == 'withdrawn':
            db.execute("UPDATE demo2_measurements SET status='withdrawn'")
        elif change == 'deleted':
            db.execute('DELETE FROM demo2_measurements')
        else:
            original['reviewed'] = False
            db.execute('UPDATE demo2_measurements SET payload_json=?', (json.dumps(original),))
    assert_withheld_summary(store.admin_export(tokens[2], work['authorization']['public_id'])['snapshots'], work['snapshots'][0])
    assert_withheld_summary(store.student_workspace(tokens[0], students[0]['student_id'])['snapshots'], work['snapshots'][0])
    assert store.admin_workspace(tokens[2])['items'][0]['snapshot_count'] == 1
    assert store.cleanup_expired()['purged_snapshots'] == 0


@pytest.mark.parametrize('authorization_end', ['revoke', 'expire'])
def test_retained_summary_still_stops_at_independent_authorization_end(env, authorization_end):
    records, store, tokens, students, clock = env
    original = measurement(env)
    work = saved(env, measurement_id=original['record_id'])
    with records._connect() as db:
        db.execute("UPDATE demo2_measurements SET status='withdrawn'")
    assert_withheld_summary(store.admin_export(tokens[2], work['authorization']['public_id'])['snapshots'], work['snapshots'][0])
    if authorization_end == 'revoke':
        store.revoke_authorization(tokens[0], dict(student_id=students[0]['student_id'],
            authorization_id=work['authorization']['authorization_id'], confirmed=True))
    else:
        clock[0] = datetime(2026, 11, 15, tzinfo=timezone.utc)
    assert store.student_workspace(tokens[0], students[0]['student_id'])['snapshots'] == []
    with pytest.raises(StudentSummaryError):
        store.admin_export(tokens[2], work['authorization']['public_id'])
    store.cleanup_expired()
    with records._connect() as db:
        assert db.execute('SELECT body_blob FROM demo2_summary_snapshots').fetchone()[0] is None
        assert db.execute('SELECT reference_blob FROM demo2_summary_authorizations').fetchone()[0] is None


def test_identifier_found_after_source_invalidation_still_hides_entire_summary(env):
    records, store, tokens, students, _ = env
    original = measurement(env)
    work = saved(env, measurement_id=original['record_id'])
    with records._connect() as db:
        db.execute("UPDATE demo2_measurements SET status='withdrawn'")
    # A new synthetic roster name now matches text in a previously valid summary.
    store.identities.create_student(tokens[0], dict(display_name=work['snapshots'][0]['learning_goals']))
    assert store.student_workspace(tokens[0], students[0]['student_id'])['snapshots'] == []
    assert store.admin_export(tokens[2], work['authorization']['public_id'])['snapshots'] == []


def test_no_plaintext_fallback_or_unauthorized_revocation(env, monkeypatch):
    _, store, tokens, students, _ = env
    work = saved(env)
    revoke = dict(student_id=students[0]['student_id'], authorization_id=work['authorization']['authorization_id'], confirmed=True)
    for token in (tokens[1], tokens[2]):
        with pytest.raises(StudentSummaryError):
            store.revoke_authorization(token, revoke)
    with pytest.raises(StudentSummaryError):
        store.revoke_authorization(tokens[0], dict(revoke, confirmed=1))
    store.revoke_authorization(tokens[0], revoke)
    monkeypatch.setenv('REHAB_DEMO2_DOSSIER_KEY', '')
    with pytest.raises(StudentSummaryError) as exc:
        authorize(env)
    assert exc.value.status == 503
    assert store.student_workspace(tokens[0], students[0]['student_id'])['authorization']['status'] == 'revoked'


def test_other_school_identifiers_cannot_hide_authorized_summary(env):
    _, store, tokens, students, _ = env
    work = saved(env)
    public_id = work['authorization']['public_id']
    store.identities.create_student(tokens[1], dict(display_name='classroom', student_code='OTHER-CLASSROOM'))
    assert len(store.student_workspace(tokens[0], students[0]['student_id'])['snapshots']) == 1
    assert len(store.admin_export(tokens[2], public_id)['snapshots']) == 1
    # The current school's own known identifiers are still screened.
    store.identities.create_student(tokens[0], dict(display_name='classroom', student_code='OWN-CLASSROOM'))
    assert store.admin_export(tokens[2], public_id)['snapshots'] == []


@pytest.mark.parametrize('change', ['disabled', 'role', 'channel'])
def test_owner_deactivation_or_reassignment_blocks_company_reads(env, change):
    records, store, tokens, students, _ = env
    work = saved(env)
    with records._connect() as db:
        if change == 'disabled':
            db.execute("UPDATE platform_accounts SET status='disabled' WHERE account_id=?", (students[0]['owner_account_id'],))
        elif change == 'role':
            db.execute("UPDATE platform_accounts SET role='registered_member' WHERE account_id=?", (students[0]['owner_account_id'],))
        else:
            db.execute('UPDATE platform_accounts SET bound_channel_id=NULL WHERE account_id=?', (students[0]['owner_account_id'],))
    assert store.admin_workspace(tokens[2])['items'] == []
    with pytest.raises(StudentSummaryError) as exc:
        store.admin_export(tokens[2], work['authorization']['public_id'])
    assert exc.value.status == 404


def test_summary_audit_has_no_body_names_or_raw_student_identifiers(env):
    records, store, tokens, students, _ = env
    work = saved(env)
    store.admin_export(tokens[2], work['authorization']['public_id'])
    store.revoke_authorization(tokens[0], dict(student_id=students[0]['student_id'],
        authorization_id=work['authorization']['authorization_id'], confirmed=True))
    with records._connect() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM audit_logs WHERE action LIKE 'student_summary_%'")]
    assert {r['action'] for r in rows} == {'student_summary_authorized', 'student_summary_saved',
                                          'student_summary_revoked', 'student_summary_exported'}
    text = json.dumps(rows)
    for forbidden in ('PRIVATE_AUTH', 'PRIVATE_TEACHER', 'SYNTHETIC_NAME', 'CODE_0', 'Sort three',
                      'Use picture', students[0]['student_id'], 'school_uploader'):
        assert forbidden not in text
