import json

import pytest

from rehab_affect.student_record_store import Demo2StudentRecordStore
from rehab_affect.demo2_identity_store import Demo2IdentityStore
from rehab_affect.school_directory import SchoolSelectionError, school_directory


@pytest.fixture
def env(tmp_path):
    store = Demo2StudentRecordStore(tmp_path / 'db.sqlite3', tmp_path / 'documents')
    identity = Demo2IdentityStore(store)
    account = store.authenticate_account('t1', 'RehabDemo2-school_uploader_01')
    token = store.create_account_session(account['account_id'])['token']
    return store, identity, account, token


def test_directory_is_server_derived_and_old_snapshot_unchanged(env):
    store, identity, account, token = env
    before = store.account_school_context(token)
    entry = school_directory()['entries'][0]
    after = store.save_account_school_context(token, {'selection_source': 'directory', 'directory_id': entry['directory_id'],
        'expected_context': before['context'], 'confirmed': True})
    assert after['context']['school_name'] == entry['school_name']
    assert after['details']['source_url'] == entry['source_url']
    assert set(after['context']) == {'city', 'district', 'school_name'}
    with store._connect() as c:
        assert c.execute('select bound_channel_id from platform_accounts where account_id=?', (account['account_id'],)).fetchone()[0] == 'channel_1'


def test_student_context_change_is_blocked_on_both_payload_paths(env):
    store, identity, account, token = env
    original = {'city': 'Original city', 'district': 'District', 'school_name': 'Original school'}
    store.save_account_school_context(token, original)
    identity.create_student(token, {'display_name': 'Synthetic student', 'student_code': 'test', 'class_name': 'Test', 'note': ''})
    entry = school_directory()['entries'][0]
    with pytest.raises(SchoolSelectionError, match='管理员迁移'):
        store.save_account_school_context(token, {'selection_source': 'directory', 'directory_id': entry['directory_id'], 'expected_context': original, 'confirmed': True})
    with pytest.raises(ValueError, match='管理员迁移'):
        store.save_account_school_context(token, {**original, 'school_name': 'New'})
    assert store.account_school_context(token)['context'] == original
    assert len(identity.roster(token)['students']) == 1


def test_stale_school_selection_rejected(env):
    store, _, _, token = env
    initial = store.account_school_context(token)['context']
    store.save_account_school_context(token, {'city': 'A', 'district': 'B', 'school_name': 'C'})
    with pytest.raises(SchoolSelectionError, match='刷新'):
        store.save_account_school_context(token, {'selection_source': 'directory', 'directory_id': school_directory()['entries'][0]['directory_id'], 'expected_context': initial, 'confirmed': True})
