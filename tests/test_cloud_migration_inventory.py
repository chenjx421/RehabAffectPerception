"""Synthetic-only tests; never import application stores or inspect live data."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import cloud_migration_inventory as inventory


SCRIPT = Path(inventory.__file__).resolve()
SECRET = 'PRIVATE_SENTINEL_student_account_diagnosis_token'


@pytest.fixture
def fixture_db(tmp_path, monkeypatch):
    monkeypatch.delenv(inventory.KEY_ENV, raising=False)
    root = tmp_path / SECRET
    root.mkdir()
    db_path = root / 'database.sqlite3'
    uploads = root / 'student_documents'
    uploads.mkdir()
    video = root / 'video_tasks'
    (video / 'uploads').mkdir(parents=True)
    (video / 'results').mkdir()
    source = video / 'uploads' / (SECRET + '.mp4')
    source.write_bytes(b'synthetic transport bytes')
    result = video / 'results' / (SECRET + '.json')
    result.write_text(json.dumps({'private': SECRET}), encoding='utf-8')
    document = uploads / (SECRET + '.txt')
    document.write_text(SECRET, encoding='utf-8')
    with sqlite3.connect(db_path) as db:
        db.executescript('''
            CREATE TABLE platform_accounts(account_id TEXT, username TEXT, role TEXT, status TEXT);
            CREATE TABLE school_contexts(account_id TEXT, city TEXT, district TEXT, school_name TEXT);
            CREATE TABLE demo2_identity_students(student_id TEXT, owner_account_id TEXT, scope_key TEXT);
            CREATE TABLE student_documents(file_path TEXT, byte_size INTEGER, extracted_preview TEXT);
            CREATE TABLE video_analysis_tasks(file_path TEXT, result_path TEXT, byte_size INTEGER,
                upload_status TEXT, analysis_status TEXT);
            CREATE TABLE demo2_dossier_documents(encrypted_file_bytes INTEGER, metadata_ciphertext BLOB);
        ''')
        db.executemany('INSERT INTO platform_accounts VALUES (?,?,?,?)', [
            (SECRET, SECRET, 'school_uploader', 'active'),
            (SECRET + '2', SECRET, 'company_admin', 'active'),
            (SECRET + '3', SECRET, SECRET, 'disabled')])
        db.execute('INSERT INTO school_contexts VALUES (?,?,?,?)', (SECRET,) * 4)
        db.executemany('INSERT INTO demo2_identity_students VALUES (?,?,?)', [
            (SECRET, SECRET, SECRET), (SECRET + '2', SECRET, SECRET)])
        db.execute('INSERT INTO student_documents VALUES (?,?,?)', (str(document), document.stat().st_size, SECRET))
        db.executemany('INSERT INTO video_analysis_tasks VALUES (?,?,?,?,?)', [
            (str(source), str(result), source.stat().st_size, 'completed', 'evidence_ready'),
            (str(video / 'uploads' / 'pending.mp4'), '', 100, 'uploading', 'waiting_upload'),
            (str(video / 'uploads' / 'queued.mp4'), '', 100, 'completed', 'queued'),
            (str(video / 'uploads' / 'processing.mp4'), '', 100, 'completed', 'processing')])
        db.execute('INSERT INTO demo2_dossier_documents VALUES (?,?)', (99, SECRET.encode()))
        db.execute(f'CREATE TABLE "{SECRET}"("{SECRET}" TEXT)')
        db.execute(f'INSERT INTO "{SECRET}" VALUES (?)', (SECRET,))
    (video / 'uploads' / 'pending.mp4.part').write_bytes(b'prefix')
    return SimpleNamespace(root=root, db=db_path, uploads=uploads, source=source, result=result)


def run_inventory(env, **kwargs):
    return inventory.inventory(root=env.root, db=env.db, upload_dir=env.uploads, **kwargs)


def tree_snapshot(root):
    return {str(p.relative_to(root)): (p.stat().st_mtime_ns, p.stat().st_size,
            hashlib.sha256(p.read_bytes()).hexdigest()) for p in root.rglob('*') if p.is_file()}


def test_aggregate_counts_without_records_or_paths(fixture_db):
    before = tree_snapshot(fixture_db.root)
    report = run_inventory(fixture_db)
    assert report['status'] == 'ok'
    assert report['consistent_backup'] is False and report['migration_ready'] is False
    assert report['table_rows']['video_analysis_tasks'] == 4
    assert report['schema']['unrecognized_tables'] == 1
    assert SECRET not in json.dumps(report)
    assert str(fixture_db.root) not in json.dumps(report)
    assert report['account_scope_counts'] == dict(active_accounts=2,
        role_school_uploader=1, role_company_admin=1, role_registered_member=0,
        other_roles=1, complete_school_contexts=1, identity_owners=1, identity_scopes=1)
    assert report['activity'] == dict(active_uploads=1, queued=1, processing=1)
    paths = report['path_samples']['video_analysis_tasks.file_path']
    assert paths['regular_files'] == 1 and paths['missing'] == 3
    assert paths['pending_parts_present'] == 1 and paths['controlled'] == 4
    assert report['disk_free_bytes'] > 0
    assert before == tree_snapshot(fixture_db.root)


def test_nonexistent_database_never_created(tmp_path, capsys):
    missing = tmp_path / SECRET / 'missing.sqlite3'
    assert inventory.main(['--root', str(tmp_path), '--db', str(missing)]) == 2
    assert not missing.exists() and not missing.parent.exists()
    output = capsys.readouterr()
    assert json.loads(output.out)['code'] == 'database_missing'
    assert SECRET not in output.out + output.err


def test_invalid_database_errors_are_sanitized(tmp_path, capsys):
    database = tmp_path / (SECRET + '.sqlite3')
    database.write_text(SECRET, encoding='utf-8')
    before = database.read_bytes()
    assert inventory.main(['--root', str(tmp_path), '--db', str(database)]) == 2
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err
    assert json.loads(output.out)['code'] == 'sqlite_read_failed_or_budget_exceeded'
    assert database.read_bytes() == before


@pytest.mark.parametrize('args', [[], ['--private-' + SECRET], ['--root', SECRET, '--max-paths', SECRET]])
def test_argument_errors_never_echo_values(args, capsys):
    assert inventory.main(args) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out)['code'] == 'invalid_arguments'
    assert SECRET not in captured.out + captured.err


def test_no_env_file_loading_and_no_key_reads(fixture_db, monkeypatch):
    (fixture_db.root / '.env').write_text(inventory.KEY_ENV + '=' + SECRET, encoding='utf-8')
    dossier = fixture_db.uploads.parent / 'scoped_dossier_v1'
    summary = fixture_db.uploads.parent / 'student_summary_v1'
    keys = fixture_db.uploads.parent / '.demo2_dossier_keys'
    keys.mkdir()
    for path in (dossier, summary):
        path.mkdir()
        identifier = hashlib.sha256(os.path.normcase(str(path)).encode()).hexdigest()
        (keys / (identifier + '.dpapi')).write_bytes(SECRET.encode())
    (dossier / '.dossier-owner.json').write_text(SECRET, encoding='utf-8')
    def forbidden(*args, **kwargs):
        pytest.fail('Inventory must not read file contents')
    monkeypatch.setattr(Path, 'read_bytes', forbidden)
    monkeypatch.setattr(Path, 'read_text', forbidden)
    report = run_inventory(fixture_db)
    assert report['vault']['environment_variable_set'] is False
    assert report['vault']['mode_hint'] == 'dpapi_marker_present_unvalidated'
    assert report['vault']['dpapi_markers'] == dict(dossier=True, summary=True)
    assert report['migration_gates']['separate_vault_keys_possible']
    assert report['migration_gates']['owner_marker_rebinding_requires_verified_copy']
    monkeypatch.setenv(inventory.KEY_ENV, SECRET)
    report = run_inventory(fixture_db)
    assert report['vault']['mode_hint'] == 'environment_configured_unvalidated'
    assert SECRET not in json.dumps(report)


def test_empty_environment_value_is_not_claimed_valid(fixture_db, monkeypatch):
    monkeypatch.setenv(inventory.KEY_ENV, '')
    vault = run_inventory(fixture_db)['vault']
    assert vault['environment_variable_set'] and not vault['decrypt_tested']
    assert vault['mode_hint'] == 'environment_configured_unvalidated'


def test_sampling_is_bounded_without_directory_walks(fixture_db, monkeypatch):
    original_open = Path.open
    def header_only(path, *args, **kwargs):
        assert path == fixture_db.db, 'Only the fixed database header may be read'
        return original_open(path, *args, **kwargs)
    def forbidden(*args, **kwargs):
        pytest.fail('Recursive scans and media content reads are forbidden')
    monkeypatch.setattr(os, 'walk', forbidden)
    monkeypatch.setattr(os, 'scandir', forbidden)
    monkeypatch.setattr(Path, 'open', header_only)
    report = run_inventory(fixture_db, max_paths=1)
    sample = report['path_samples']['video_analysis_tasks.file_path']
    assert sample['sampled_references'] == 1 and sample['total_references'] == 4
    assert sample['truncated'] and report['migration_gates']['path_sampling_incomplete']


@pytest.mark.parametrize('limit', [-1, 10001])
def test_sample_limits(fixture_db, limit):
    with pytest.raises(inventory.InventoryError, match='invalid_sample_limit'):
        run_inventory(fixture_db, max_paths=limit)


def test_zero_sample_still_returns_counts(fixture_db):
    report = run_inventory(fixture_db, max_paths=0)
    sample = report['path_samples']['video_analysis_tasks.file_path']
    assert sample['sampled_references'] == 0 and sample['truncated']
    assert report['table_rows']['video_analysis_tasks'] == 4


def test_sqlite_uri_readonly_query_only_and_no_writes(fixture_db, monkeypatch):
    connect = sqlite3.connect
    observed = {}
    class ReadOnlyProbe:
        def __init__(self, connection):
            self.connection = connection
        def __getattr__(self, name):
            return getattr(self.connection, name)
        def close(self):
            observed['query_only'] = self.connection.execute('PRAGMA query_only').fetchone()[0]
            with pytest.raises(sqlite3.OperationalError):
                self.connection.execute('CREATE TABLE forbidden_write(value TEXT)')
            self.connection.close()
    def checked_connect(database, **kwargs):
        assert database.endswith('?mode=ro') and kwargs['uri'] is True
        observed['readonly_uri'] = True
        return ReadOnlyProbe(connect(database, **kwargs))
    monkeypatch.setattr(inventory.sqlite3, 'connect', checked_connect)
    run_inventory(fixture_db)
    assert observed == dict(readonly_uri=True, query_only=1)


def test_wal_committed_rows_are_not_ignored(fixture_db):
    writer = sqlite3.connect(fixture_db.db)
    try:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('INSERT INTO platform_accounts VALUES (?,?,?,?)', (SECRET, SECRET, 'school_uploader', 'active'))
        writer.commit()
        assert Path(str(fixture_db.db) + '-wal').stat().st_size > 0
        report = run_inventory(fixture_db)
        assert report['table_rows']['platform_accounts'] == 4
        assert report['roots']['wal']['exists']
    finally:
        writer.close()


def test_missing_wal_shm_is_not_created_or_recovered(fixture_db):
    writer = sqlite3.connect(fixture_db.db)
    destination = fixture_db.root / 'unrecovered.sqlite3'
    try:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('INSERT INTO platform_accounts VALUES (?,?,?,?)', (SECRET, SECRET, 'school_uploader', 'active'))
        writer.commit()
        shutil.copyfile(fixture_db.db, destination)
        shutil.copyfile(str(fixture_db.db) + '-wal', str(destination) + '-wal')
        with pytest.raises(inventory.InventoryError, match='wal_shared_memory_missing'):
            inventory.inventory(root=fixture_db.root, db=destination)
        assert not Path(str(destination) + '-shm').exists()
    finally:
        writer.close()


def test_wal_database_without_sidecars_does_not_initialize_them(fixture_db):
    connection = sqlite3.connect(fixture_db.db)
    connection.execute('PRAGMA journal_mode=WAL')
    connection.close()
    before = tree_snapshot(fixture_db.root)
    assert not Path(str(fixture_db.db) + '-wal').exists()
    with pytest.raises(inventory.InventoryError, match='wal_sidecars_missing'):
        run_inventory(fixture_db)
    assert before == tree_snapshot(fixture_db.root)


def test_rollback_journal_is_not_recovered(fixture_db):
    journal = Path(str(fixture_db.db) + '-journal')
    journal.write_bytes(b'synthetic pending journal')
    before = tree_snapshot(fixture_db.root)
    with pytest.raises(inventory.InventoryError, match='rollback_journal_present'):
        run_inventory(fixture_db)
    assert before == tree_snapshot(fixture_db.root)


@pytest.mark.parametrize('field', ['db', 'upload_dir'])
def test_outside_root_is_rejected_before_open(fixture_db, tmp_path, field):
    args = dict(root=fixture_db.root, db=fixture_db.db, upload_dir=fixture_db.uploads)
    args[field] = tmp_path / (SECRET + 'outside')
    with pytest.raises(inventory.InventoryError, match='outside_authorized_root'):
        inventory.inventory(**args)


def test_parent_traversal_is_rejected(fixture_db):
    with pytest.raises(inventory.InventoryError, match='parent_traversal_rejected'):
        inventory.inventory(root=fixture_db.root, db='../' + SECRET)


@pytest.mark.parametrize('target', ['database', 'ancestor'])
def test_real_symlinks_are_rejected(fixture_db, tmp_path, target):
    link = tmp_path / 'link'
    try:
        link.symlink_to(fixture_db.db if target == 'database' else fixture_db.root,
                        target_is_directory=target == 'ancestor')
    except OSError:
        pytest.skip('Local account cannot create symlinks; reparse rejection separately tested')
    with pytest.raises(inventory.InventoryError, match='link_or_reparse_point_rejected'):
        inventory.inventory(root=tmp_path, db=link if target == 'database' else link / fixture_db.db.name)


@pytest.mark.parametrize('mode,attributes', [(stat.S_IFDIR, 0x400), (stat.S_IFLNK, 0)])
def test_link_rejected_without_symlink_privileges(fixture_db, monkeypatch, mode, attributes):
    original = Path.lstat
    def lstat(path, *args, **kwargs):
        if path == fixture_db.root:
            return SimpleNamespace(st_mode=mode, st_file_attributes=attributes)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'lstat', lstat)
    with pytest.raises(inventory.InventoryError, match='link_or_reparse_point_rejected'):
        run_inventory(fixture_db)


def test_stored_unsafe_paths_are_counted_without_following(fixture_db, monkeypatch):
    with sqlite3.connect(fixture_db.db) as db:
        db.executemany('INSERT INTO student_documents VALUES (?,0,?)', [
            ('relative/' + SECRET, SECRET),
            (str(fixture_db.root.parent / SECRET / 'outside.txt'), SECRET),
            ('Z:\\' + SECRET + '\\file.mp4', SECRET)])
    original = inventory._checked_stat
    def checked(path):
        if path == fixture_db.source:
            raise inventory.InventoryError('link_or_reparse_point_rejected')
        return original(path)
    monkeypatch.setattr(inventory, '_checked_stat', checked)
    report = run_inventory(fixture_db)
    assert report['path_samples']['video_analysis_tasks.file_path']['links_rejected'] == 1
    sample = report['path_samples']['student_documents.file_path']
    assert sample['invalid'] == 1
    assert sample['outside_root'] >= 1
    assert sample['windows_absolute'] >= 1
    assert SECRET not in json.dumps(report)


def test_unknown_views_and_tables_do_not_expose_names_or_execute(fixture_db):
    with sqlite3.connect(fixture_db.db) as db:
        db.execute(f'CREATE VIEW "view_{SECRET}" AS SELECT unavailable_function()')
    report = run_inventory(fixture_db)
    assert report['schema']['views'] == 1 and report['migration_gates']['unknown_schema_requires_review']
    assert SECRET not in json.dumps(report)


def test_explicit_root_defaults_and_partial_schema(tmp_path):
    parent = tmp_path / 'outputs' / 'seewo_demo2'
    parent.mkdir(parents=True)
    db_path = parent / 'rehab_affect_demo2.sqlite3'
    with sqlite3.connect(db_path) as db:
        db.execute('CREATE TABLE platform_accounts(account_id TEXT)')
    report = inventory.inventory(root=tmp_path)
    assert report['table_rows'] == {'platform_accounts': 0}
    assert report['activity']['active_uploads'] is None
    assert report['migration_gates']['activity_schema_incomplete']
    assert report['roots']['upload_root']['exists'] is False
    assert not (parent / 'student_documents').exists()


def test_unexpected_exception_has_no_path_or_error_message(fixture_db, monkeypatch, capsys):
    def fail(*args):
        raise PermissionError(SECRET)
    monkeypatch.setattr(inventory.shutil, 'disk_usage', fail)
    assert inventory.main(['--root', str(fixture_db.root), '--db', str(fixture_db.db)]) == 2
    output = capsys.readouterr()
    assert SECRET not in output.out + output.err
    assert json.loads(output.out)['code'] == 'inventory_unavailable'


def test_cli_no_application_imports_or_sensitive_output(fixture_db):
    code = '''import runpy, sys
def guard(event, args):
    if event == 'import' and ('rehab_affect' in args[0] or args[0] == 'dotenv'):
        raise RuntimeError('application_import_forbidden')
sys.addaudithook(guard)
script = sys.argv.pop(1)
runpy.run_path(script, run_name='__main__')
'''
    result = subprocess.run([sys.executable, '-c', code, str(SCRIPT), '--root', str(fixture_db.root),
        '--db', str(fixture_db.db), '--upload-dir', str(fixture_db.uploads)],
        text=True, capture_output=True, timeout=30)
    assert result.returncode == 0
    assert json.loads(result.stdout)['status'] == 'ok'
    assert SECRET not in result.stdout + result.stderr
    assert result.stderr == ''
