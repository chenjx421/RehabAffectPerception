"""Build a PRIVATE, reversible pre-migration copy. Never start or upload services.

Default action is an aggregate plan. --build creates a unique private package;
historical media are deferred unless --media-mode full is explicitly supplied.
The package is NOT a final consistent cutover backup, even when no tasks are busy.
No application stores or .env files are imported. Never print exceptions/rows/keys.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import secrets
import shutil
import sqlite3
import stat
import struct
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
KEY_ENV = 'REHAB_DEMO2_DOSSIER_KEY'
PATH_COLUMNS = {'student_documents': ('file_path',),
                'video_analysis_tasks': ('file_path', 'result_path')}
VAULT_COLUMNS = {
    'demo2_dossier_authorizations': ('metadata_ciphertext', 'dossier'),
    'demo2_dossier_documents': ('metadata_ciphertext', 'dossier'),
    'demo2_dossier_references': ('metadata_ciphertext', 'dossier'),
    'demo2_summary_authorizations': ('reference_blob', 'summary'),
    'demo2_summary_snapshots': ('body_blob', 'summary'),
    'demo2_summary_course_history': ('body_blob', 'summary'),
}
UNSUPPORTED_VAULTS = {
    'safety': ('safety_review_v1', ('demo2_safety_events',)),
    'materials': ('school_material_intake', ('demo2_material_batches', 'demo2_material_documents')),
}


class Refused(Exception):
    pass


def require(condition, code):
    if not condition:
        raise Refused(code)


def safe_path(value):
    path = Path(value)
    require('..' not in path.parts and not str(path).startswith(('\\\\', '//')), 'unsafe_path')
    path = Path(os.path.abspath(path))
    current = Path(path.anchor)
    for part in (None, *path.parts[1:]):
        if part is not None:
            current /= part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                'link_or_reparse_point_rejected')
        require(current == path or stat.S_ISDIR(info.st_mode), 'invalid_path_ancestor')
    return path


def private_directory(path):
    safe_path(path)
    path.mkdir(mode=0o700, parents=False, exist_ok=False)
    if os.name == 'nt':
        result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
            '[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value'],
            capture_output=True, text=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
        sid = result.stdout.strip()
        require(result.returncode == 0 and re.fullmatch(r'S-1-[0-9-]+', sid), 'private_acl_failed')
        result = subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r',
            f'*{sid}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F'],
            capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
        require(result.returncode == 0, 'private_acl_failed')
    else:
        path.chmod(0o700)


def write_private(path, data):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)
    if os.name != 'nt':
        path.chmod(0o600)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def identifier(name):
    return '"' + name.replace('"', '""') + '"'


def read_db(path):
    safe_path(path)
    require(path.is_file(), 'source_database_missing')
    for suffix in ('-wal', '-shm', '-journal'):
        safe_path(Path(str(path) + suffix))
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
    connection.execute('PRAGMA query_only=ON')
    connection.execute('PRAGMA trusted_schema=OFF')
    return connection


def backup_database(source, destination):
    deadline = time.monotonic() + 120
    def progress(status, remaining, total):
        require(time.monotonic() < deadline, 'sqlite_backup_timeout')
    source_connection = read_db(source)
    target = None
    try:
        target = sqlite3.connect(destination)
        source_connection.backup(target, pages=256, progress=progress, sleep=.05)
        require(target.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'snapshot_integrity_failed')
        require(not target.execute('PRAGMA foreign_key_check').fetchall(), 'snapshot_foreign_keys_failed')
        target.execute('PRAGMA journal_mode=DELETE')
    finally:
        if target is not None:
            target.close()
        source_connection.close()


def schema(db):
    rows = db.execute('SELECT name,type,sql FROM sqlite_schema').fetchall()
    require(not any(kind == 'trigger' for _, kind, _ in rows), 'triggers_require_manual_review')
    require(not any((sql or '').lstrip().upper().startswith('CREATE VIRTUAL TABLE') for _, _, sql in rows),
            'virtual_tables_require_manual_review')
    result = {name: db.execute(f'PRAGMA table_info({identifier(name)})').fetchall()
              for name, kind, _ in rows if kind == 'table'}
    for table, columns in result.items():
        if any(table in value[1] for value in UNSUPPORTED_VAULTS.values()):
            require(db.execute(f'SELECT COUNT(*) FROM {identifier(table)}').fetchone()[0] == 0,
                    'unsupported_vault_database_data_requires_migration')
            continue
        for column in columns:
            if column[1] in {'metadata_ciphertext', 'content_ciphertext', 'reference_blob', 'body_blob'}:
                require(table in VAULT_COLUMNS and VAULT_COLUMNS[table][0] == column[1],
                        'unknown_vault_column_requires_review')
    return result


def unchanged_digest(db, tables):
    """Hash every non-migration value byte-for-byte, including raw result JSON."""
    aggregate = hashlib.sha256()
    counts = {}
    for table in sorted(tables):
        excluded = set(PATH_COLUMNS.get(table, ()))
        if table in VAULT_COLUMNS:
            excluded.add(VAULT_COLUMNS[table][0])
        columns = [row[1] for row in tables[table] if row[1] not in excluded]
        require(bool(columns), 'unsupported_table_without_preserved_columns')
        row_hashes = []
        for row in db.execute('SELECT ' + ','.join(map(identifier, columns)) + ' FROM ' + identifier(table)):
            digest = hashlib.sha256()
            for value in row:
                if value is None:
                    tag, data = b'n', b''
                elif isinstance(value, bytes):
                    tag, data = b'b', value
                elif isinstance(value, str):
                    tag, data = b's', value.encode('utf-8')
                elif isinstance(value, float):
                    tag, data = b'f', struct.pack('!d', value)
                else:
                    tag, data = b'i', str(value).encode('ascii')
                digest.update(tag + struct.pack('!Q', len(data)) + data)
            row_hashes.append(digest.digest())
        counts[table] = len(row_hashes)
        aggregate.update(table.encode('utf-8') + b'\0' + b''.join(sorted(row_hashes)))
    return aggregate.digest(), counts


def activity(db, tables):
    columns = {row[1] for row in tables.get('video_analysis_tasks', [])}
    require({'upload_status', 'analysis_status'} <= columns, 'task_activity_schema_missing')
    return int(db.execute("SELECT COUNT(*) FROM video_analysis_tasks WHERE upload_status IN ('created','uploading') OR analysis_status IN ('queued','processing')").fetchone()[0])


def relocate(value, mappings):
    if not value:
        return value
    require(isinstance(value, str) and '\0' not in value, 'invalid_stored_path')
    windows = bool(PureWindowsPath(value).drive)
    path_type = PureWindowsPath if windows else PurePosixPath
    source = path_type(value)
    require(source.is_absolute() and '..' not in source.parts, 'invalid_stored_path')
    for old, new in mappings:
        boundary = path_type(str(old))
        try:
            relative = source.relative_to(boundary)
        except ValueError:
            continue
        require(relative.parts and all(part not in ('', '.', '..') and '\\' not in part and ':' not in part
                                       for part in relative.parts), 'invalid_stored_path')
        return str(new.joinpath(*relative.parts))
    raise Refused('stored_path_outside_mapping')


def rewrite_paths(db, tables, source_db, uploads, target_data):
    changed = 0
    mappings = {
        ('student_documents', 'file_path'): [(uploads, target_data / 'student_documents')],
        ('video_analysis_tasks', 'file_path'): [(source_db.parent / 'video_tasks/uploads', target_data / 'video_tasks/uploads')],
        ('video_analysis_tasks', 'result_path'): [(source_db.parent / 'video_tasks/results', target_data / 'video_tasks/results')],
    }
    for (table, column), roots in mappings.items():
        if table not in tables or column not in {row[1] for row in tables[table]}:
            continue
        for rowid, value in db.execute(f'SELECT rowid,{identifier(column)} FROM {identifier(table)}').fetchall():
            mapped = relocate(value, roots)
            if mapped != value:
                db.execute(f'UPDATE {identifier(table)} SET {identifier(column)}=? WHERE rowid=?', (mapped, rowid))
                changed += 1
    return changed


def files_under(root):
    root = safe_path(root)
    if not root.exists():
        return
    require(root.is_dir(), 'source_root_not_directory')
    for directory, children, files in os.walk(root, followlinks=False):
        for name in children:
            safe_path(Path(directory) / name)
        for name in files:
            path = safe_path(Path(directory) / name)
            require(path.is_file(), 'unsupported_source_file')
            yield path


def copy_file(source, destination):
    source = safe_path(source)
    before = source.stat()
    digest = hashlib.sha256()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with source.open('rb') as incoming, destination.open('xb') as outgoing:
        opened = os.fstat(incoming.fileno())
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
                (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns), 'source_changed_during_copy')
        for block in iter(lambda: incoming.read(4 * 1024 * 1024), b''):
            digest.update(block)
            outgoing.write(block)
    after = safe_path(source).stat()
    require((before.st_size, before.st_mtime_ns, before.st_ino) ==
            (after.st_size, after.st_mtime_ns, after.st_ino), 'source_changed_during_copy')
    verification = hashlib.sha256()
    with destination.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            verification.update(block)
    require(verification.digest() == digest.digest() and destination.stat().st_size == before.st_size,
            'copied_file_hash_mismatch')
    return before.st_size


def copy_tree(source, destination):
    count = size = 0
    if source.exists():
        destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    for path in files_under(source):
        size += copy_file(path, destination / path.relative_to(source))
        count += 1
    return {'files': count, 'bytes': size}


def source_cipher(vault_root):
    from cryptography.fernet import Fernet
    if KEY_ENV in os.environ:
        return Fernet(os.environ[KEY_ENV].encode('ascii')), os.environ[KEY_ENV].encode('ascii'), 'environment'
    name = hashlib.sha256(os.path.normcase(str(vault_root)).encode('utf-8')).hexdigest() + '.dpapi'
    path = safe_path(vault_root.parent / '.demo2_dossier_keys' / name)
    if not path.exists():
        return None, None, 'absent'
    require(os.name == 'nt', 'dpapi_requires_original_windows_identity')
    # Load encryption primitives only, never a store or DossierVault._cipher().
    specification = importlib.util.spec_from_file_location('_migration_vault_primitives',
        ROOT / 'src/rehab_affect/demo2_dossier_vault.py')
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    key = module._dpapi(module._read_key_file(path), decrypt=True)
    return Fernet(key), key, 'dpapi'


def owner_marker(db, tables, source_db, dossier_root, target_db):
    marker = safe_path(dossier_root / '.dossier-owner.json')
    nonempty = dossier_root.exists() and any(dossier_root.iterdir())
    if 'demo2_dossier_storage_identity' not in tables:
        require(not nonempty, 'dossier_identity_missing')
        return None
    identities = db.execute('SELECT singleton,database_id FROM demo2_dossier_storage_identity').fetchall()
    require(len(identities) == 1 and identities[0][0] == 1 and
            re.fullmatch('[0-9a-f]{32}', identities[0][1] or ''), 'dossier_identity_invalid')
    expected = dict(version=1, database_id=identities[0][1],
        database_path_sha256=hashlib.sha256(os.path.normcase(str(source_db)).encode('utf-8')).hexdigest())
    if not marker.exists():
        require(not nonempty, 'dossier_owner_marker_missing')
        return None
    require(marker.is_file() and marker.stat().st_size <= 4096, 'dossier_owner_marker_invalid')
    require(marker.read_bytes() == encoded(expected), 'dossier_owner_marker_mismatch')
    expected['database_path_sha256'] = hashlib.sha256(str(target_db).encode('utf-8')).hexdigest()
    return encoded(expected)


def transform_vaults(db, tables, roots, rollback, linux_data, new_cipher):
    from cryptography.fernet import InvalidToken
    keys, ciphers, modes = {}, {}, {}
    for domain, root in roots.items():
        cipher, key, mode = source_cipher(root)
        ciphers[domain], modes[domain] = cipher, mode
        if key is not None:
            keys[domain] = key.decode('ascii')
    transformed = 0
    for table, (column, domain) in VAULT_COLUMNS.items():
        if table not in tables:
            continue
        require(column in {row[1] for row in tables[table]}, 'vault_schema_missing')
        rows = db.execute(f'SELECT rowid,{identifier(column)} FROM {identifier(table)} WHERE {identifier(column)} IS NOT NULL').fetchall()
        require(not rows or ciphers[domain] is not None, 'vault_source_key_missing')
        for rowid, blob in rows:
            try:
                plaintext = ciphers[domain].decrypt(bytes(blob))
                ciphertext = new_cipher.encrypt(plaintext)
                require(new_cipher.decrypt(ciphertext) == plaintext, 'vault_roundtrip_failed')
            except (InvalidToken, TypeError, ValueError):
                raise Refused('vault_source_decrypt_failed') from None
            db.execute(f'UPDATE {identifier(table)} SET {identifier(column)}=? WHERE rowid=?', (ciphertext, rowid))
            transformed += 1
    originals = rollback / 'vault_files'
    for domain, root in roots.items():
        copy_tree(root, originals / domain)
    for source in files_under(originals / 'dossier'):
        if source.name == '.dossier-owner.json':
            continue
        require(re.fullmatch('[0-9a-f]{32}\\.enc', source.name) and source.parent == originals / 'dossier',
                'uncommitted_or_unknown_dossier_file')
        require(ciphers['dossier'] is not None, 'vault_source_key_missing')
        require(source.stat().st_size <= 16 * 1024 * 1024, 'vault_file_exceeds_budget')
        try:
            plaintext = ciphers['dossier'].decrypt(source.read_bytes())
            ciphertext = new_cipher.encrypt(plaintext)
            require(new_cipher.decrypt(ciphertext) == plaintext, 'vault_roundtrip_failed')
        except InvalidToken:
            raise Refused('vault_source_decrypt_failed') from None
        write_private(linux_data / 'scoped_dossier_v1' / source.name, ciphertext)
        transformed += 1
    require(not list(files_under(originals / 'summary')), 'unknown_summary_vault_file')
    copy_tree(roots['dossier'].parent / '.demo2_dossier_keys', rollback / 'dpapi_wrappers')
    write_private(rollback / 'source_keyring.fernet', new_cipher.encrypt(encoded(keys)))
    return {'source_modes': modes, 'reencrypted_values_and_files': transformed,
            'original_ciphertexts_preserved': True, 'original_keyring_sealed': True}


def plan(root, source_db, uploads, media_mode, output_base):
    require(media_mode in {'deferred', 'full'}, 'invalid_media_mode')
    for path in (source_db, uploads):
        require(path.is_relative_to(root), 'source_outside_root')
        safe_path(path)
    require(source_db.is_file(), 'source_database_missing')
    categories = {}
    roots = {'media': source_db.parent / 'video_tasks', 'documents': uploads,
             'dossier': uploads.parent / 'scoped_dossier_v1', 'summary': uploads.parent / 'student_summary_v1',
             'key_wrappers': uploads.parent / '.demo2_dossier_keys',
             'reports': root / 'outputs/seewo_demo2/reports'}
    for name, path in roots.items():
        require(not output_base.is_relative_to(path) and not path.is_relative_to(output_base), 'output_overlaps_source')
        count = size = 0
        for file in files_under(path):
            count += 1
            size += file.stat().st_size
        categories[name] = dict(files=count, bytes=size)
    unsupported = {}
    for domain, (name, _) in UNSUPPORTED_VAULTS.items():
        path = safe_path(uploads.parent / name)
        marker_name = hashlib.sha256(os.path.normcase(str(path)).encode('utf-8')).hexdigest() + '.dpapi'
        marker = safe_path(uploads.parent / '.demo2_dossier_keys' / marker_name)
        unsupported[domain] = dict(root_nonempty=path.exists() and any(path.iterdir()),
                                   expected_dpapi_marker_present=marker.exists(),
                                   database_rows_checked_after_backup_only=True)
    needed = source_db.stat().st_size * 3 + sum(item['bytes'] * (2 if key in {'dossier', 'summary', 'key_wrappers'} else 1)
        for key, item in categories.items() if media_mode == 'full' or key not in {'media', 'reports'})
    parent = output_base
    while not parent.exists():
        parent = parent.parent
    free = shutil.disk_usage(parent).free
    return dict(status='plan', media_mode=media_mode, database_bytes=source_db.stat().st_size,
        categories=categories, estimated_required_bytes=needed, disk_free_bytes=free,
        enough_space=free >= needed + 256 * 1024 ** 2, consistent_backup=False,
        unsupported_vault_status=unsupported,
        vault_filesystem_blockers=[name for name, value in unsupported.items()
                                  if value['root_nonempty'] or value['expected_dpapi_marker_present']],
        final_delta_required=True, background_services_must_remain_disabled=True)


def build(*, root, source_db, uploads, output_base, target_data='/var/lib/rehabaffect/seewo_demo2',
          target_app='/opt/rehabaffect', media_mode='deferred', allow_active=False):
    from cryptography.fernet import Fernet
    root, source_db, uploads, output_base = map(safe_path, (root, source_db, uploads, output_base))
    data, app = PurePosixPath(target_data), PurePosixPath(target_app)
    require(data.is_absolute() and app.is_absolute() and '..' not in data.parts + app.parts
            and str(data).startswith('/var/lib/rehabaffect/') and str(app) == '/opt/rehabaffect', 'invalid_linux_target')
    require(output_base.is_relative_to(root / '.runtime/cloud_deploy_20261020'), 'output_outside_private_deploy_root')
    report = plan(root, source_db, uploads, media_mode, output_base)
    require(not report['vault_filesystem_blockers'], 'unsupported_vault_files_or_keys_require_migration')
    require(report['enough_space'], 'insufficient_snapshot_space')
    output_base.mkdir(parents=True, exist_ok=True, mode=0o700)
    run_id = time.strftime('snapshot_%Y%m%d_%H%M%S_') + secrets.token_hex(4)
    package = output_base / run_id
    private_directory(package)
    report.update(status='building', run_id=run_id, phase='sqlite_backup')
    rollback = package / 'rollback'
    rollback.mkdir(mode=0o700)
    linux = package / 'linux'
    linux_data = linux.joinpath(*data.parts[1:])
    linux_data.mkdir(parents=True, mode=0o700)
    original = rollback / 'source.sqlite3'
    target_db = linux_data / 'rehab_affect_demo2.sqlite3'
    connection = None
    try:
        backup_database(source_db, original)
        backup_database(original, target_db)
        connection = sqlite3.connect(target_db)
        connection.execute('PRAGMA trusted_schema=OFF')
        connection.execute('PRAGMA foreign_keys=ON')
        tables = schema(connection)
        before, counts = unchanged_digest(connection, tables)
        report['database_tables'] = len(counts)
        report['database_rows'] = sum(counts.values())
        report['active_tasks_at_snapshot'] = activity(connection, tables)
        require(allow_active or report['active_tasks_at_snapshot'] == 0, 'active_tasks_require_explicit_preliminary_mode')
        dossier = uploads.parent / 'scoped_dossier_v1'
        summary = uploads.parent / 'student_summary_v1'
        marker = owner_marker(connection, tables, source_db, dossier, data / target_db.name)
        report['phase'] = 'path_and_vault_conversion'
        report['rewritten_path_values'] = rewrite_paths(connection, tables, source_db, uploads, data)
        new_key = Fernet.generate_key()
        new_cipher = Fernet(new_key)
        report['vault'] = transform_vaults(connection, tables, {'dossier': dossier, 'summary': summary},
                                          rollback, linux_data, new_cipher)
        require(owner_marker(connection, tables, source_db, rollback / 'vault_files/dossier',
                             data / target_db.name) == marker, 'source_owner_marker_changed_during_copy')
        after, after_counts = unchanged_digest(connection, tables)
        require(before == after and counts == after_counts, 'nonmigration_database_values_changed')
        require(not connection.execute('PRAGMA foreign_key_check').fetchall(), 'converted_foreign_keys_failed')
        connection.commit()
        require(connection.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'converted_integrity_failed')
        connection.close()
        connection = None
        if marker is not None:
            write_private(linux_data / 'scoped_dossier_v1/.dossier-owner.json', marker)
        for name in ('student_documents', 'scoped_dossier_v1', 'student_summary_v1', 'video_tasks'):
            (linux_data / name).mkdir(exist_ok=True, mode=0o700)
        report['phase'] = 'copy_files'
        report['copied_documents'] = copy_tree(uploads, linux_data / 'student_documents')
        report['historical_media_complete'] = False
        if media_mode == 'full':
            report['copied_media'] = copy_tree(source_db.parent / 'video_tasks', linux_data / 'video_tasks')
            report['copied_reports'] = copy_tree(root / 'outputs/seewo_demo2/reports',
                linux.joinpath(*app.parts[1:]) / 'outputs/seewo_demo2/reports')
            report['historical_media_complete'] = True
        report['phase'] = 'private_runtime_configuration'
        environment = (f'REHAB_DEMO2_DB_PATH={data}/{target_db.name}\n'
                       f'REHAB_DEMO2_UPLOAD_DIR={data}/student_documents\n'
                       'REHAB_DEMO2_MEDIA_WORKER=0\n'
                       'HF_HUB_OFFLINE=1\nTRANSFORMERS_OFFLINE=1\n'
                       f'{KEY_ENV}={new_key.decode("ascii")}\n')
        write_private(linux / 'etc/rehabaffect/runtime.env', environment.encode('ascii'))
        write_private(package / 'READ_BEFORE_START.txt', (
            'PRIVATE PRE-MIGRATION PACKAGE. Not a consistent cutover backup.\n'
            'Do NOT launch scenario_lab_server.run_server against this clone: retention starts unconditionally.\n'
            'MEDIA_WORKER=0 disables only analysis, not retention or read-triggered cleanup.\n'
            'Use a separately reviewed no-background cloud entrypoint; never expose raw directories.\n'
            'Historical media may be absent: consult report.json before acceptance.\n'
            'Install linux/ under matching absolute paths with owner-only permissions.\n'
            'runtime.env contains a SECRET; never print it or put it into logs/version control.\n'
            'Rollback materials retain original DB/ciphertexts/DPAPI wrappers. source_keyring.fernet\n'
            'is sealed with the target runtime key. Restore only into an isolated original-layout copy.\n'
            'No account IDs, permissions, school metadata or raw processing_result_json are rewritten.\n'
            'Final cutover still requires writer fencing, a fresh database backup, and file delta verification.\n'
        ).encode('ascii'))
        report.update(status='prepared_preliminary', phase='complete', nonmigration_columns_identical=True,
                      processing_result_json_preserved=True, services_started=False, source_sql_writes=False,
                      owner_marker_rebound=marker is not None, cloud_acceptance_complete=False)
    except Exception as error:
        report.update(status='failed', code=str(error) if isinstance(error, Refused) else 'snapshot_failed')
    finally:
        if connection is not None:
            connection.close()
        write_private(package / 'report.json', encoded(report))
    return report


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Refused('invalid_arguments')


def main(argv=None):
    try:
        parser = Parser(description=__doc__)
        parser.add_argument('--root', type=Path, required=True)
        parser.add_argument('--db', type=Path)
        parser.add_argument('--upload-dir', type=Path)
        parser.add_argument('--output-base', type=Path)
        parser.add_argument('--target-data', default='/var/lib/rehabaffect/seewo_demo2')
        parser.add_argument('--target-app', default='/opt/rehabaffect')
        parser.add_argument('--media-mode', choices=['deferred', 'full'], default='deferred')
        parser.add_argument('--build', action='store_true')
        parser.add_argument('--allow-active', action='store_true', help='Explicitly permit a preliminary clone of active tasks; never auto-start workers')
        args = parser.parse_args(argv)
        root = safe_path(args.root)
        def under_root(value, default):
            return safe_path((value if value.is_absolute() else root / value) if value else default)
        source_db = under_root(args.db, root / 'outputs/seewo_demo2/rehab_affect_demo2.sqlite3')
        uploads = under_root(args.upload_dir, source_db.parent / 'student_documents')
        output = under_root(args.output_base, root / '.runtime/cloud_deploy_20261020')
        if args.build:
            report = build(root=root, source_db=source_db, uploads=uploads, output_base=output,
                target_data=args.target_data, target_app=args.target_app, media_mode=args.media_mode,
                allow_active=args.allow_active)
        else:
            report = plan(root, source_db, uploads, args.media_mode, output)
    except Exception as error:
        report = {'status': 'failed', 'code': str(error) if isinstance(error, Refused) else 'snapshot_failed'}
    print(json.dumps(report, ensure_ascii=True, allow_nan=False, sort_keys=True))
    return 0 if report['status'] in {'plan', 'prepared_preliminary'} else 2


if __name__ == '__main__':
    raise SystemExit(main())
