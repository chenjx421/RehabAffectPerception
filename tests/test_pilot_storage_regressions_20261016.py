from rehab_affect import student_record_store as module


def test_renamed_admin_is_not_recreated(tmp_path):
    store = module.Demo2StudentRecordStore(tmp_path / 'data.sqlite3', tmp_path / 'documents')
    with store._connect() as connection:
        before = connection.execute("SELECT account_id FROM platform_accounts WHERE role='company_admin'").fetchone()[0]
        connection.execute("UPDATE platform_accounts SET username='renamed-admin' WHERE account_id=?", (before,))
    module.Demo2StudentRecordStore(store.db_path, store.upload_dir)
    with store._connect() as connection:
        rows = connection.execute("SELECT account_id,username FROM platform_accounts WHERE role='company_admin'").fetchall()
    assert [tuple(row) for row in rows] == [(before, 'renamed-admin')]


def test_custom_database_gets_independent_upload_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(module, '_DEFAULT_STORE', None)
    monkeypatch.setenv('REHAB_DEMO2_DB_PATH', str(tmp_path / 'isolated' / 'database.sqlite3'))
    monkeypatch.delenv('REHAB_DEMO2_UPLOAD_DIR', raising=False)
    store = module.get_demo2_student_store()
    assert store.upload_dir == tmp_path / 'isolated' / 'student_documents'


def test_custom_database_cannot_reuse_live_upload_directory(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr(module, '_DEFAULT_STORE', None)
    monkeypatch.setenv('REHAB_DEMO2_DB_PATH', str(tmp_path / 'database.sqlite3'))
    monkeypatch.setenv('REHAB_DEMO2_UPLOAD_DIR', str(module.DEFAULT_UPLOAD_DIR))
    with pytest.raises(ValueError, match='live default'):
        module.get_demo2_student_store()
