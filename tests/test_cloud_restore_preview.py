"""Synthetic restore checks: no real credentials, service calls, or school data."""
from contextlib import closing
import ast
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/cloud_restore_preview.py'


@pytest.fixture
def restore():
    spec = importlib.util.spec_from_file_location('_synthetic_restore_preview', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode()


def file_bytes(root):
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob('*') if path.is_file()}


@pytest.fixture
def staged(tmp_path, monkeypatch, restore):
    stage = tmp_path / 'stage'
    target = tmp_path / 'target/seewo_demo2'
    source = stage / 'linux/var/lib/rehabaffect/seewo_demo2'
    media = stage / 'media/uploads/synthetic.mp4'
    media.parent.mkdir(parents=True)
    payload = b'SYNTHETIC transport bytes, not a student recording'
    media.write_bytes(payload)
    source.mkdir(parents=True)
    (source / 'scoped_dossier_v1').mkdir()
    (stage / 'media-complete').write_bytes(b'complete')
    env = stage / 'linux/etc/rehabaffect/runtime.env'
    env.parent.mkdir(parents=True)
    env.write_text('REHAB_DEMO2_MEDIA_WORKER=0\nSYNTHETIC_KEY=not-a-real-key\n')
    database = source / 'rehab_affect_demo2.sqlite3'
    raw_result = '{ "synthetic" : true, "revision_input" : 7 }\n'
    with closing(sqlite3.connect(database)) as db, db:
        db.executescript('''
            CREATE TABLE platform_accounts(account_id TEXT PRIMARY KEY);
            CREATE TABLE video_analysis_tasks(
                task_id TEXT PRIMARY KEY, file_path TEXT, sha256 TEXT, byte_size INTEGER,
                upload_status TEXT, analysis_status TEXT, raw_media_deleted_at TEXT,
                processing_result_json TEXT);
            CREATE TABLE demo2_dossier_storage_identity(singleton INTEGER PRIMARY KEY, database_id TEXT);
            CREATE TABLE demo2_identity_bindings(binding_id TEXT, owner_account_id TEXT,
                scope_key TEXT, frame_revision TEXT);
            CREATE TABLE future_table(id INTEGER PRIMARY KEY, payload BLOB);
            CREATE TABLE demo2_dossier_documents(metadata_ciphertext BLOB);
        ''')
        db.execute('INSERT INTO platform_accounts VALUES (?)', ('synthetic-owner',))
        db.execute('INSERT INTO video_analysis_tasks VALUES (?,?,?,?,?,?,?,?)',
                   ('completed', str(target / 'video_tasks/uploads/synthetic.mp4'),
                    hashlib.sha256(payload).hexdigest(), len(payload), 'completed',
                    'evidence_ready', None, raw_result))
        db.execute('INSERT INTO video_analysis_tasks VALUES (?,?,?,?,?,?,?,?)',
                   ('incomplete', str(target / 'video_tasks/uploads/pending.mp4'),
                    '', 100, 'uploading', 'not_started', None, None))
        db.execute('INSERT INTO demo2_dossier_storage_identity VALUES (1,?)', ('a' * 32,))
        db.execute('INSERT INTO demo2_identity_bindings VALUES (?,?,?,?)',
                   ('synthetic-binding', 'synthetic-owner', 'synthetic-scope',
                    hashlib.sha256(raw_result.encode()).hexdigest()))
        db.execute('INSERT INTO future_table VALUES (?,?)', (1, b'unchanged synthetic metadata'))
    marker = source / 'scoped_dossier_v1/.dossier-owner.json'
    owner = {'version': 1, 'database_id': 'a' * 32,
             'database_path_sha256': hashlib.sha256(str(target / database.name).encode()).hexdigest()}
    marker.write_bytes(canonical(owner))
    config_dir = tmp_path / 'etc/rehabaffect'
    config_dir.mkdir(parents=True)
    config = config_dir / 'preview.env'
    events = []

    # Redirect fixed configuration paths and isolate every OS/service operation.
    def local_path(value):
        if str(value) == '/etc/rehabaffect':
            return config_dir
        if str(value) == '/etc/rehabaffect/preview.env':
            return config
        return Path(value)

    nofollow = getattr(os, 'O_NOFOLLOW', 1 << 29)

    def private_open(path, flags, mode):
        assert path == config
        assert flags & os.O_EXCL and flags & nofollow
        assert flags & os.O_CREAT and mode == 0o600
        events.append('private_config')
        native_flags = flags if hasattr(os, 'O_NOFOLLOW') else flags & ~nofollow
        return os.open(path, native_flags, mode)

    def owned(path, uid, gid):
        assert path == target or path.is_relative_to(target)
        assert (uid, gid) == (12345, 12345)

    def copy_unit(source_path, target_path):
        assert source_path == '/opt/rehabaffect/deploy/cloud/rehabaffect-preview.service'
        assert target_path == '/etc/systemd/system/rehabaffect-preview.service'
        events.append('copy_unit')

    def command(args, *, check):
        assert check
        assert args in (['systemctl', 'daemon-reload'],
                        ['systemctl', 'start', 'rehabaffect-preview.service'])
        events.append(tuple(args))

    def connect(database_uri, **kwargs):
        assert database_uri == database.as_uri() + '?mode=ro'
        assert kwargs == {'uri': True}
        return sqlite3.connect(database_uri, **kwargs)

    # Use private proxies, never monkeypatch the process-wide os/subprocess modules.
    monkeypatch.setattr(restore, 'STAGE', stage)
    monkeypatch.setattr(restore, 'TARGET', target)
    monkeypatch.setattr(restore, 'Path', local_path)
    monkeypatch.setattr(restore, 'os', SimpleNamespace(
        umask=lambda mode: events.append(('umask', mode)), getuid=lambda: 0,
        chown=owned, open=private_open, fdopen=os.fdopen, O_WRONLY=os.O_WRONLY,
        O_CREAT=os.O_CREAT, O_EXCL=os.O_EXCL, O_NOFOLLOW=nofollow))
    monkeypatch.setitem(sys.modules, 'pwd', SimpleNamespace(
        getpwnam=lambda name: SimpleNamespace(pw_uid=12345, pw_gid=12345)))
    monkeypatch.setattr(restore, 'subprocess', SimpleNamespace(run=command))
    monkeypatch.setattr(restore, 'shutil', SimpleNamespace(
        copytree=restore.shutil.copytree, copyfile=copy_unit))
    monkeypatch.setattr(restore, 'sqlite3', SimpleNamespace(connect=connect, Row=sqlite3.Row))
    return SimpleNamespace(module=restore, stage=stage, target=target, source=source,
                           db=database, media=media, marker=marker, owner=owner,
                           config=config, events=events, raw_result=raw_result)


def update_task(fixture, clause, values=()):
    with closing(sqlite3.connect(fixture.db)) as db, db:
        db.execute('UPDATE video_analysis_tasks SET ' + clause + " WHERE task_id='completed'", values)


def rejected(fixture, code):
    before = file_bytes(fixture.stage)
    with pytest.raises((RuntimeError, ValueError), match=code):
        fixture.module.main()
    assert file_bytes(fixture.stage) == before
    assert not fixture.target.exists()
    assert not fixture.config.exists()
    assert not any(isinstance(event, tuple) and event[0] == 'systemctl'
                   for event in fixture.events)


def test_restore_preserves_database_unknown_tables_identity_and_uploading(staged, capsys):
    before = file_bytes(staged.stage)
    staged.module.main()
    assert file_bytes(staged.stage) == before
    assert (staged.target / staged.db.name).read_bytes() == staged.db.read_bytes()
    assert (staged.target / 'video_tasks/uploads/synthetic.mp4').read_bytes() == staged.media.read_bytes()
    assert (staged.target / 'scoped_dossier_v1/.dossier-owner.json').read_bytes() == canonical(staged.owner)
    with closing(sqlite3.connect(staged.target / staged.db.name)) as db:
        assert db.execute("SELECT upload_status,analysis_status FROM video_analysis_tasks WHERE task_id='incomplete'").fetchone() == ('uploading', 'not_started')
        assert db.execute('SELECT * FROM future_table').fetchone() == (1, b'unchanged synthetic metadata')
        assert db.execute('SELECT owner_account_id,scope_key,frame_revision FROM demo2_identity_bindings').fetchone() == (
            'synthetic-owner', 'synthetic-scope', hashlib.sha256(staged.raw_result.encode()).hexdigest())
        assert db.execute("SELECT processing_result_json FROM video_analysis_tasks WHERE task_id='completed'").fetchone()[0] == staged.raw_result
        assert db.execute('SELECT COUNT(*) FROM demo2_dossier_documents').fetchone()[0] == 0
    assert staged.events[0] == ('umask', 0o077)
    assert staged.events[-1] == ('systemctl', 'start', 'rehabaffect-preview.service')
    if os.name == 'posix':
        assert stat.S_IMODE(staged.config.stat().st_mode) == 0o600
        assert stat.S_IMODE(staged.target.stat().st_mode) == 0o700
    output = capsys.readouterr().out
    assert 'SYNTHETIC_KEY' not in output and 'not-a-real-key' not in output
    report = json.loads(output)
    assert report['source_videos_hash_verified'] == 1 and not report['public_cutover']


@pytest.mark.parametrize('status', ['queued', 'processing'])
def test_preexisting_analysis_refused(staged, status):
    update_task(staged, 'analysis_status=?', (status,))
    rejected(staged, 'active_analysis_refused')


@pytest.mark.parametrize('change,code', [('missing', 'source_video_missing'),
                                        ('size', 'source_size_mismatch'),
                                        ('hash', 'source_hash_mismatch')])
def test_source_media_checks_fail_before_copy(staged, change, code):
    if change == 'missing':
        staged.media.unlink()
    elif change == 'size':
        staged.media.write_bytes(b'short')
    else:
        staged.media.write_bytes(b'x' * staged.media.stat().st_size)
    rejected(staged, code)


@pytest.mark.parametrize('field,value', [('version', 2), ('database_id', 'b' * 32),
    ('database_path_sha256', '0' * 64), ('unexpected', 'synthetic')])
def test_owner_metadata_mismatch_refused(staged, field, value):
    staged.marker.write_bytes(canonical({**staged.owner, field: value}))
    rejected(staged, 'storage_identity_mismatch')


def test_missing_storage_identity_refused(staged):
    with closing(sqlite3.connect(staged.db)) as db, db:
        db.execute('DELETE FROM demo2_dossier_storage_identity')
    rejected(staged, 'storage_identity_missing')


def test_foreign_key_violation_refused(staged):
    with closing(sqlite3.connect(staged.db)) as db, db:
        db.execute('CREATE TABLE bad_reference(owner TEXT REFERENCES platform_accounts(account_id))')
        db.execute("INSERT INTO bad_reference VALUES ('synthetic-missing-owner')")
    rejected(staged, 'foreign_keys_failed')


@pytest.mark.parametrize('kind', ['relative', 'parent', 'outside'])
def test_malicious_database_paths_refused(staged, kind):
    paths = {'relative': Path('relative.mp4'),
             'parent': staged.target / 'video_tasks/../../escape.mp4',
             'outside': staged.stage / 'outside.mp4'}
    update_task(staged, 'file_path=?', (str(paths[kind]),))
    rejected(staged, 'invalid_path|not in the subpath|not in the subpath of|not a subpath')


def test_missing_completion_marker_refused(staged):
    (staged.stage / 'media-complete').unlink()
    rejected(staged, 'Incomplete stage')


def test_existing_target_is_never_overwritten(staged):
    staged.target.mkdir(parents=True)
    sentinel = staged.target / 'synthetic-existing'
    sentinel.write_bytes(b'keep')
    with pytest.raises(RuntimeError, match='existing target'):
        staged.module.main()
    assert sentinel.read_bytes() == b'keep' and not staged.config.exists()


def test_existing_private_configuration_is_never_overwritten(staged):
    staged.config.write_bytes(b'SYNTHETIC existing configuration')
    with pytest.raises(FileExistsError):
        staged.module.main()
    assert staged.config.read_bytes() == b'SYNTHETIC existing configuration'
    assert 'copy_unit' not in staged.events


def test_nonroot_operator_cannot_restore(staged):
    staged.module.os.getuid = lambda: 12345
    rejected(staged, 'Incomplete stage')


@pytest.mark.parametrize('boundary', ['stage', 'target_parent'])
def test_linked_restore_ancestor_refused_before_copy(staged, monkeypatch, boundary):
    staged.target.parent.mkdir(parents=True)
    linked = staged.stage if boundary == 'stage' else staged.target.parent
    original = Path.lstat

    def lstat(value, *args, **kwargs):
        return SimpleNamespace(st_mode=stat.S_IFLNK) if value == linked else original(value, *args, **kwargs)

    monkeypatch.setattr(Path, 'lstat', lstat)
    with pytest.raises(RuntimeError, match='linked_path_refused'):
        staged.module.main()
    assert not staged.target.exists() and not staged.config.exists()
    assert staged.events == [('umask', 0o077)]


@pytest.mark.parametrize('which', ['database', 'video'])
def test_destination_corruption_blocks_configuration_and_start(staged, which):
    original = staged.module.shutil.copytree

    def copy(source, destination, **kwargs):
        result = original(source, destination, **kwargs)
        if which == 'database' and source == staged.source:
            (staged.target / staged.db.name).write_bytes(b'corrupted synthetic database')
        if which == 'video' and source == staged.stage / 'media':
            (staged.target / 'video_tasks/uploads/synthetic.mp4').write_bytes(b'corrupted')
        return result

    staged.module.shutil.copytree = copy
    with pytest.raises(RuntimeError, match='restored_' + which + '_mismatch'):
        staged.module.main()
    assert not staged.config.exists()
    assert not any(isinstance(event, tuple) and event[0] == 'systemctl' for event in staged.events)


@pytest.mark.parametrize('kind', ['symlink', 'fifo', 'socket'])
def test_special_path_rejected_without_os_privileges(restore, tmp_path, monkeypatch, kind):
    path = tmp_path / 'synthetic-special'
    path.write_bytes(b'synthetic')
    original = Path.lstat
    modes = {'symlink': stat.S_IFLNK, 'fifo': stat.S_IFIFO, 'socket': stat.S_IFSOCK}

    def lstat(value, *args, **kwargs):
        return SimpleNamespace(st_mode=modes[kind]) if value == path else original(value, *args, **kwargs)

    monkeypatch.setattr(Path, 'lstat', lstat)
    with pytest.raises(RuntimeError, match='linked_path_refused|special_path_refused'):
        restore.safe_tree(tmp_path)


@pytest.mark.parametrize('kind', ['file', 'ancestor', 'dangling'])
def test_real_links_rejected_when_platform_supports_them(restore, tmp_path, kind):
    outside = tmp_path / 'synthetic-outside'
    outside.mkdir()
    (outside / 'payload').write_bytes(b'synthetic')
    root = tmp_path / 'tree'
    root.mkdir()
    link = root / 'linked'
    target = outside if kind == 'ancestor' else outside / ('missing' if kind == 'dangling' else 'payload')
    try:
        link.symlink_to(target, target_is_directory=kind == 'ancestor')
    except (OSError, NotImplementedError):
        pytest.skip('Host cannot create a synthetic symlink; mocked rejection is covered')
    with pytest.raises(RuntimeError, match='linked_path_refused'):
        restore.safe_path(link / 'payload' if kind == 'ancestor' else link)
    with pytest.raises(RuntimeError, match='linked_path_refused'):
        restore.safe_tree(root)


def test_optimization_cannot_remove_explicit_gate(restore):
    tree = ast.parse(SCRIPT.read_text(encoding='utf-8'))
    assert not any(isinstance(node, ast.Assert) for node in ast.walk(tree))
    namespace = {}
    exec(compile(inspect.getsource(restore.require), '<synthetic-gate>', 'exec', optimize=2), namespace)
    with pytest.raises(RuntimeError, match='synthetic_refused'):
        namespace['require'](False, 'synthetic_refused')


def test_noncanonical_owner_marker_must_not_be_accepted(staged):
    staged.marker.write_text(json.dumps(staged.owner, indent=2))
    rejected(staged, 'storage_identity_mismatch')
