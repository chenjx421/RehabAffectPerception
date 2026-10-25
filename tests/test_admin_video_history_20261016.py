import pytest

from rehab_affect.student_record_store import Demo2StudentRecordStore


@pytest.fixture
def history(tmp_path, monkeypatch):
    monkeypatch.setenv('REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX', 'HistoryTest-')
    store = Demo2StudentRecordStore(tmp_path / 'db.sqlite3', tmp_path / 'documents')
    admin = store.authenticate_account('company_admin', 'HistoryTest-company_admin')
    owner = store.authenticate_account('school_uploader_01', 'HistoryTest-school_uploader_01')
    token = store.create_account_session(admin['account_id'])['token']
    owner_token = store.create_account_session(owner['account_id'])['token']
    return store, token, owner_token, owner


def test_all_history_pages_and_new_upload_are_visible(history):
    store, token, _, owner = history
    def add(index):
        return store.create_video_task({
            'account_id': owner['account_id'], 'channel_id': 'channel_1',
            'course_id': f'synthetic-{index}', 'course_name': 'Synthetic test',
            'session_id': f'synthetic-{index}', 'uploader_name': 'Synthetic school',
            'filename': f'clip-{index}.mp4', 'byte_size': 1, 'total_chunks': 1,
        })
    ids = {add(i)['task_id'] for i in range(23)}
    first = store.admin_platform_summary(token)
    second = store.admin_platform_summary(token, upload_page=2)
    assert first['upload_pagination'] == {'page': 1, 'page_size': 20, 'total': 23, 'total_pages': 2}
    assert len(first['recent_uploads']) == 20
    assert len(second['recent_uploads']) == 3
    assert {t['task_id'] for t in first['recent_uploads'] + second['recent_uploads']} == ids
    latest = add(24)['task_id']
    refreshed = store.admin_platform_summary(token)
    assert refreshed['recent_uploads'][0]['task_id'] == latest
    assert refreshed['upload_pagination']['total'] == 24
    assert store.admin_platform_summary(token, upload_page=999)['upload_pagination']['page'] == 2
    assert all('file_path' not in item for item in refreshed['recent_uploads'])


def test_school_cannot_read_admin_history(history):
    store, _, token, _ = history
    with pytest.raises(ValueError, match='company_admin'):
        store.admin_platform_summary(token, upload_page=2)


@pytest.mark.parametrize('page', [0, -1, True, '1', 1.5, 1_000_001])
def test_invalid_history_page(history, page):
    store, token, _, _ = history
    with pytest.raises(ValueError, match='页码'):
        store.admin_platform_summary(token, upload_page=page)


def test_empty_history(history):
    store, token, _, _ = history
    summary = store.admin_platform_summary(token)
    assert summary['recent_uploads'] == []
    assert summary['upload_pagination']['total_pages'] == 1
