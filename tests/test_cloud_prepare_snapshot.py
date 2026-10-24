"""Synthetic offline package tests, with no app/server/store initialization."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import stat
from types import SimpleNamespace

from cryptography.fernet import Fernet
import pytest

from scripts import cloud_prepare_snapshot as snapshot


PRIVATE = 'SYNTHETIC_PRIVATE_account_student_source_text'


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    monkeypatch.delenv(snapshot.KEY_ENV, raising=False)
    root = tmp_path / 'source'
    data = root / 'outputs/seewo_demo2'
    uploads = data / 'student_documents'
    video = data / 'video_tasks'
    dossier = data / 'scoped_dossier_v1'
    summary = data / 'student_summary_v1'
    key_dir = data / '.demo2_dossier_keys'
    for path in (uploads, video / 'uploads', video / 'results', video / 'analysis', dossier, summary, key_dir):
        path.mkdir(parents=True, exist_ok=True)
    source = video / 'uploads' / (PRIVATE + '.mp4')
    source.write_bytes(b'SYNTHETIC VIDEO TRANSPORT ONLY')
    doc = uploads / (PRIVATE + '.txt')
    doc.write_bytes(b'SYNTHETIC DOCUMENT ONLY')
    result = video / 'results/task.json'
    raw_json = '{ "source_sha256" : "synthetic", "private" : "' + PRIVATE + '" }\n'
    result.write_text(raw_json, encoding='utf-8')
    db_path = data / 'source.sqlite3'
    identity = 'a' * 32
    keys = {domain: Fernet.generate_key() for domain in ('dossier', 'summary')}
    ciphers = {domain: Fernet(key) for domain, key in keys.items()}
    plaintext = b'{"SYNTHETIC":"private content kept only in memory"}'
    columns = {}
    with sqlite3.connect(db_path) as db:
        db.executescript('''
            CREATE TABLE platform_accounts(account_id TEXT PRIMARY KEY, password_hash TEXT, role TEXT);
            CREATE TABLE video_analysis_tasks(task_id TEXT PRIMARY KEY, file_path TEXT, result_path TEXT,
                upload_status TEXT, analysis_status TEXT, processing_result_json TEXT, account_id TEXT REFERENCES platform_accounts(account_id));
            CREATE TABLE student_documents(document_id TEXT PRIMARY KEY, file_path TEXT);
            CREATE TABLE demo2_dossier_storage_identity(singleton INTEGER PRIMARY KEY, database_id TEXT);
        ''')
        db.execute('INSERT INTO platform_accounts VALUES (?,?,?)', (PRIVATE, PRIVATE, 'school_uploader'))
        db.execute('INSERT INTO video_analysis_tasks VALUES (?,?,?,?,?,?,?)',
                   ('task', str(source), str(result), 'completed', 'evidence_ready', raw_json, PRIVATE))
        db.execute('INSERT INTO student_documents VALUES (?,?)', ('doc', str(doc)))
        db.execute('INSERT INTO demo2_dossier_storage_identity VALUES (1,?)', (identity,))
        for table, (column, domain) in snapshot.VAULT_COLUMNS.items():
            db.execute(f'CREATE TABLE {table}(id TEXT PRIMARY KEY,{column} BLOB,other_value TEXT)')
            blob = ciphers[domain].encrypt(plaintext)
            db.execute(f'INSERT INTO {table} VALUES (?,?,?)', ('fixture', blob, PRIVATE))
            db.execute(f'INSERT INTO {table} VALUES (?,?,?)', ('null-fixture', None, PRIVATE))
            columns[table] = blob
    marker = dict(version=1, database_id=identity,
        database_path_sha256=hashlib.sha256(os.path.normcase(str(db_path)).encode()).hexdigest())
    (dossier / '.dossier-owner.json').write_bytes(snapshot.encoded(marker))
    (dossier / ('b' * 32 + '.enc')).write_bytes(ciphers['dossier'].encrypt(plaintext))
    for domain, path in (('dossier', dossier), ('summary', summary)):
        name = hashlib.sha256(os.path.normcase(str(path)).encode()).hexdigest() + '.dpapi'
        (key_dir / name).write_bytes(b'SYNTHETIC DPAPI WRAPPER ' + domain.encode())
    def resolve(path):
        domain = 'dossier' if path == dossier else 'summary'
        return ciphers[domain], keys[domain], 'dpapi'
    monkeypatch.setattr(snapshot, 'source_cipher', resolve)
    return SimpleNamespace(root=root, data=data, uploads=uploads, source=source, db=db_path,
        output=root / '.runtime/cloud_deploy_20261020', ciphers=ciphers, keys=keys,
        columns=columns, plaintext=plaintext, raw_json=raw_json, dossier=dossier, summary=summary)


def build(dataset, **kwargs):
    return snapshot.build(root=dataset.root, source_db=dataset.db, uploads=dataset.uploads,
                          output_base=dataset.output, **kwargs)


def tree_bytes(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()}


def read_key(package):
    environment = (package / 'linux/etc/rehabaffect/runtime.env').read_text(encoding='ascii')
    return dict(line.split('=', 1) for line in environment.splitlines())[snapshot.KEY_ENV].encode()


def test_deferred_package_preserves_every_other_value_and_originals(dataset):
    before = tree_bytes(dataset.data)
    report = build(dataset)
    assert report['status'] == 'prepared_preliminary', report.get('code')
    assert not report['historical_media_complete']
    assert not report['services_started'] and not report['consistent_backup']
    assert report['nonmigration_columns_identical'] and report['processing_result_json_preserved']
    assert report['rewritten_path_values'] == 3
    assert PRIVATE not in json.dumps(report)
    package = dataset.output / report['run_id']
    linux_data = package / 'linux/var/lib/rehabaffect/seewo_demo2'
    with sqlite3.connect(linux_data / 'rehab_affect_demo2.sqlite3') as db:
        task = db.execute('SELECT * FROM video_analysis_tasks').fetchone()
        assert task[1] == '/var/lib/rehabaffect/seewo_demo2/video_tasks/uploads/' + dataset.source.name
        assert task[5] == dataset.raw_json
        assert task[6] == PRIVATE
        assert db.execute('SELECT * FROM platform_accounts').fetchone() == (PRIVATE, PRIVATE, 'school_uploader')
        cipher = Fernet(read_key(package))
        for table, (column, domain) in snapshot.VAULT_COLUMNS.items():
            blob = db.execute(f'SELECT {column} FROM {table} WHERE id=?', ('fixture',)).fetchone()[0]
            assert blob != dataset.columns[table] and cipher.decrypt(blob) == dataset.plaintext
            assert db.execute(f'SELECT {column} FROM {table} WHERE id=?', ('null-fixture',)).fetchone()[0] is None
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    keyring = json.loads(cipher.decrypt((package / 'rollback/source_keyring.fernet').read_bytes()))
    assert {key: value.encode() for key, value in keyring.items()} == dataset.keys
    original_ciphertext = (package / 'rollback/vault_files/dossier' / ('b' * 32 + '.enc')).read_bytes()
    assert dataset.ciphers['dossier'].decrypt(original_ciphertext) == dataset.plaintext
    assert cipher.decrypt((linux_data / 'scoped_dossier_v1' / ('b' * 32 + '.enc')).read_bytes()) == dataset.plaintext
    assert not (linux_data / 'video_tasks/uploads').exists()
    marker = json.loads((linux_data / 'scoped_dossier_v1/.dossier-owner.json').read_bytes())
    assert marker['database_path_sha256'] == hashlib.sha256(b'/var/lib/rehabaffect/seewo_demo2/rehab_affect_demo2.sqlite3').hexdigest()
    with sqlite3.connect(package / 'rollback/source.sqlite3') as original:
        assert original.execute('SELECT file_path,processing_result_json FROM video_analysis_tasks').fetchone() == (str(dataset.source), dataset.raw_json)
    assert tree_bytes(dataset.data) == before


def test_deferred_never_reads_or_hashes_historical_video(dataset, monkeypatch):
    original = Path.open
    def checked(path, *args, **kwargs):
        assert not path.is_relative_to(dataset.data / 'video_tasks'), 'Deferred media must not be opened'
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', checked)
    assert build(dataset)['status'] == 'prepared_preliminary'


def test_full_mode_copies_and_verifies_synthetic_media(dataset):
    report = build(dataset, media_mode='full')
    assert report['status'] == 'prepared_preliminary'
    assert report['historical_media_complete'] and report['copied_media']['files'] == 2
    copied = dataset.output / report['run_id'] / 'linux/var/lib/rehabaffect/seewo_demo2/video_tasks/uploads' / dataset.source.name
    assert copied.read_bytes() == dataset.source.read_bytes()


def test_wrong_owner_marker_refuses_without_changing_source(dataset):
    marker = dataset.dossier / '.dossier-owner.json'
    marker.write_bytes(b'{"untrusted":"' + PRIVATE.encode() + b'"}')
    before = tree_bytes(dataset.data)
    report = build(dataset)
    assert report['status'] == 'failed' and report['code'] == 'dossier_owner_marker_mismatch'
    assert PRIVATE not in json.dumps(report)
    assert tree_bytes(dataset.data) == before


def test_missing_owner_marker_on_populated_root_refuses(dataset):
    (dataset.dossier / '.dossier-owner.json').unlink()
    report = build(dataset)
    assert report['code'] == 'dossier_owner_marker_missing'


def test_active_clone_requires_explicit_preliminary_flag(dataset):
    with sqlite3.connect(dataset.db) as db:
        db.execute("UPDATE video_analysis_tasks SET analysis_status='processing'")
    assert build(dataset)['code'] == 'active_tasks_require_explicit_preliminary_mode'
    report = build(dataset, allow_active=True)
    assert report['status'] == 'prepared_preliminary' and report['active_tasks_at_snapshot'] == 1
    with sqlite3.connect(dataset.output / report['run_id'] / 'linux/var/lib/rehabaffect/seewo_demo2/rehab_affect_demo2.sqlite3') as db:
        assert db.execute('SELECT analysis_status FROM video_analysis_tasks').fetchone()[0] == 'processing'


def test_unmapped_path_fails_closed(dataset):
    with sqlite3.connect(dataset.db) as db:
        db.execute('UPDATE video_analysis_tasks SET file_path=?', ('Z:\\private\\' + PRIVATE,))
    report = build(dataset)
    assert report['code'] == 'stored_path_outside_mapping'
    assert PRIVATE not in json.dumps(report)


def test_windows_path_mapping_on_any_host():
    mapped = snapshot.relocate('D:\\Source\\video_tasks\\uploads\\task.mp4',
        [('d:\\source\\video_tasks\\uploads', PurePosixPath('/var/lib/rehabaffect/seewo_demo2/video_tasks/uploads'))])
    assert mapped == '/var/lib/rehabaffect/seewo_demo2/video_tasks/uploads/task.mp4'


def test_bad_ciphertext_is_not_silently_dropped(dataset):
    with sqlite3.connect(dataset.db) as db:
        db.execute('UPDATE demo2_summary_snapshots SET body_blob=? WHERE id=?', (PRIVATE.encode(), 'fixture'))
    report = build(dataset)
    assert report['code'] == 'vault_source_decrypt_failed'
    assert PRIVATE not in json.dumps(report)


def test_unknown_encrypted_schema_blocks_package(dataset):
    with sqlite3.connect(dataset.db) as db:
        db.execute('CREATE TABLE future_vault(id TEXT,body_blob BLOB)')
    assert build(dataset)['code'] == 'unknown_vault_column_requires_review'


@pytest.mark.parametrize('domain', ['safety', 'materials'])
def test_unsupported_vault_files_fail_before_creating_package(dataset, domain):
    name, _ = snapshot.UNSUPPORTED_VAULTS[domain]
    folder = dataset.data / name
    folder.mkdir()
    (folder / 'synthetic').write_bytes(b'no silent omission')
    plan = snapshot.plan(dataset.root, dataset.db, dataset.uploads, 'deferred', dataset.output)
    assert plan['vault_filesystem_blockers'] == [domain]
    with pytest.raises(snapshot.Refused, match='unsupported_vault_files_or_keys'):
        build(dataset)
    assert not dataset.output.exists()


@pytest.mark.parametrize('table,column', [('demo2_safety_events', 'body'),
    ('demo2_material_batches', 'metadata_ciphertext'), ('demo2_material_documents', 'content_ciphertext')])
def test_database_only_unsupported_vaults_are_not_silently_omitted(dataset, table, column):
    with sqlite3.connect(dataset.db) as db:
        db.execute(f'CREATE TABLE {table}(id TEXT,{column} BLOB)')
        db.execute(f'INSERT INTO {table} VALUES (?,?)', ('synthetic', b'encrypted placeholder'))
    report = build(dataset)
    assert report['status'] == 'failed'
    assert report['code'] == 'unsupported_vault_database_data_requires_migration'


def test_empty_unsupported_schema_can_be_preserved(dataset):
    with sqlite3.connect(dataset.db) as db:
        db.execute('CREATE TABLE demo2_material_documents(id TEXT,content_ciphertext BLOB,metadata_ciphertext BLOB)')
    assert build(dataset)['status'] == 'prepared_preliminary'


def test_trigger_cannot_change_accounts_during_copy_updates(dataset):
    with sqlite3.connect(dataset.db) as db:
        db.execute("CREATE TRIGGER unsafe AFTER UPDATE ON video_analysis_tasks BEGIN DELETE FROM platform_accounts; END")
    assert build(dataset)['code'] == 'triggers_require_manual_review'
    with sqlite3.connect(dataset.db) as db:
        assert db.execute('SELECT COUNT(*) FROM platform_accounts').fetchone()[0] == 1


def test_backup_includes_committed_wal_without_source_sql_writes(dataset):
    writer = sqlite3.connect(dataset.db)
    try:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('INSERT INTO platform_accounts VALUES (?,?,?)', ('second', PRIVATE, 'company_admin'))
        writer.commit()
        report = build(dataset)
        assert report['status'] == 'prepared_preliminary'
        with sqlite3.connect(dataset.output / report['run_id'] / 'rollback/source.sqlite3') as db:
            assert db.execute('SELECT COUNT(*) FROM platform_accounts').fetchone()[0] == 2
        assert writer.execute('SELECT COUNT(*) FROM platform_accounts').fetchone()[0] == 2
    finally:
        writer.close()


def test_no_directory_or_db_created_for_missing_source(tmp_path):
    with pytest.raises(snapshot.Refused, match='source_database_missing'):
        snapshot.build(root=tmp_path, source_db=tmp_path / 'missing.sqlite3', uploads=tmp_path / 'uploads',
                       output_base=tmp_path / '.runtime/cloud_deploy_20261020')
    assert list(tmp_path.iterdir()) == []


def test_stat_link_rejection_without_platform_privilege(dataset, monkeypatch):
    original = Path.lstat
    def checked(path, *args, **kwargs):
        if path == dataset.source:
            return SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'lstat', checked)
    with pytest.raises(snapshot.Refused, match='link_or_reparse_point_rejected'):
        build(dataset)


def test_cli_errors_and_plan_do_not_print_private_values(dataset, capsys):
    assert snapshot.main(['--root', str(dataset.root), '--db', str(dataset.db)]) == 0
    output = capsys.readouterr()
    assert PRIVATE not in output.out + output.err
    assert json.loads(output.out)['status'] == 'plan'
    assert not dataset.output.exists()
    assert snapshot.main(['--root', str(dataset.root), '--unknown-' + PRIVATE]) == 2
    assert PRIVATE not in capsys.readouterr().out


def test_source_cipher_actual_windows_dpapi_reads_only(tmp_path, monkeypatch):
    if os.name != 'nt':
        pytest.skip('DPAPI roundtrip requires Windows; distinct-domain conversion is covered everywhere')
    monkeypatch.delenv(snapshot.KEY_ENV, raising=False)
    spec = importlib.util.spec_from_file_location('synthetic_dpapi_primitives', snapshot.ROOT / 'src/rehab_affect/demo2_dossier_vault.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / 'scoped_dossier_v1'
    root.mkdir()
    keys = tmp_path / '.demo2_dossier_keys'
    keys.mkdir()
    key = Fernet.generate_key()
    name = hashlib.sha256(os.path.normcase(str(root)).encode()).hexdigest() + '.dpapi'
    wrapped = module._KEY_MAGIC + module._dpapi(key, decrypt=False)
    (keys / name).write_bytes(wrapped)
    before = tree_bytes(tmp_path)
    cipher, recovered, mode = snapshot.source_cipher(root)
    assert recovered == key and mode == 'dpapi'
    assert cipher.decrypt(Fernet(key).encrypt(b'synthetic')) == b'synthetic'
    assert tree_bytes(tmp_path) == before
