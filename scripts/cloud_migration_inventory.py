"""Read-only, aggregate migration inventory. This is NOT a consistent backup.

Use --root for the explicitly authorized deployment boundary. --db defaults to
root/outputs/seewo_demo2/rehab_affect_demo2.sqlite3; --upload-dir defaults to the
database parent's student_documents. No .env, application imports, media tree
walks, content hashing, key reads, decryption, or service operations are used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import sqlite3
import stat
import time


KEY_ENV = 'REHAB_DEMO2_DOSSIER_KEY'
# Only fixed schema identifiers may appear in output or generated SQL.
TABLES = tuple('''students student_documents student_support_profiles retention_policies
audit_logs video_upload_channels platform_accounts account_sessions school_contexts
school_selection_metadata registration_requests registration_rate_limits
video_analysis_tasks data_security_acceptances long_term_resource_records
demo2_identity_students demo2_identity_bindings demo2_classroom_evaluations
demo2_classroom_evaluation_versions demo2_measurements demo2_measurement_versions
demo2_batch_decisions demo2_batch_decision_versions demo2_teaching_plans
demo2_teaching_plan_versions demo2_memberships demo2_membership_otps
demo2_membership_rate_limits demo2_membership_orders demo2_dossier_authorizations
demo2_dossier_documents demo2_dossier_references demo2_dossier_reference_documents
demo2_dossier_file_cleanup demo2_dossier_storage_identity demo2_summary_students
demo2_summary_authorizations demo2_summary_snapshots demo2_summary_automatic_settings
demo2_summary_course_history demo2_summary_auto_excluded_tasks'''.split())


class InventoryError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _absolute(value, base=None):
    path = Path(value)
    if str(path).startswith(('\\\\', '//')):
        raise InventoryError('network_or_device_path_rejected')
    if '..' in path.parts:
        raise InventoryError('parent_traversal_rejected')
    if not path.is_absolute():
        path = (base or Path.cwd()) / path
    # Do not resolve links before inspecting every ancestor.
    return Path(os.path.abspath(path))


def _checked_stat(path):
    current = Path(path.anchor)
    parts = (current, *(current.joinpath(*path.parts[1:i + 1]) for i in range(1, len(path.parts))))
    result = None
    for item in parts:
        try:
            result = item.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(result.st_mode) or getattr(result, 'st_file_attributes', 0) & 0x400:
            raise InventoryError('link_or_reparse_point_rejected')
        if item != path and not stat.S_ISDIR(result.st_mode):
            raise InventoryError('invalid_path_ancestor')
    return result


def _within(path, root):
    if path != root and not path.is_relative_to(root):
        raise InventoryError('path_outside_authorized_root')


def _entry(path, *, directory=False):
    info = _checked_stat(path)
    if info is None:
        return {'exists': False, 'bytes': None}
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise InventoryError('unexpected_path_type')
    return {'exists': True, 'bytes': None if directory else info.st_size}


def _schema(db):
    rows = db.execute('SELECT name, type, sql FROM sqlite_schema').fetchall()
    known = {}
    for name, kind, sql in rows:
        if name in TABLES and kind == 'table' and not (sql or '').lstrip().upper().startswith('CREATE VIRTUAL TABLE'):
            known[name] = {row[1] for row in db.execute(f'PRAGMA table_info("{name}")')}
    return known, {
        'tables': sum(kind == 'table' for _, kind, _ in rows),
        'indexes': sum(kind == 'index' for _, kind, _ in rows),
        'views': sum(kind == 'view' for _, kind, _ in rows),
        'triggers': sum(kind == 'trigger' for _, kind, _ in rows),
        'virtual_tables': sum((sql or '').lstrip().upper().startswith('CREATE VIRTUAL TABLE') for _, _, sql in rows),
        'unrecognized_tables': sum(kind == 'table' and name not in TABLES and not name.startswith('sqlite_')
                                  for name, kind, _ in rows),
        'known_tables_present': len(known),
        'known_columns_total': sum(map(len, known.values())),
    }


def _has(schema, table, *columns):
    return table in schema and set(columns) <= schema[table]


def _scalar(db, sql):
    return int(db.execute(sql).fetchone()[0] or 0)


def _account_scopes(db, schema):
    counts = {}
    if _has(schema, 'platform_accounts', 'role', 'status'):
        counts['active_accounts'] = _scalar(db, "SELECT COUNT(*) FROM platform_accounts WHERE status='active'")
        for role in ('school_uploader', 'company_admin', 'registered_member'):
            counts['role_' + role] = _scalar(db, f"SELECT COUNT(*) FROM platform_accounts WHERE role='{role}'")
        counts['other_roles'] = _scalar(db, "SELECT COUNT(*) FROM platform_accounts WHERE role IS NULL OR role NOT IN ('school_uploader','company_admin','registered_member')")
    if _has(schema, 'school_contexts', 'city', 'district', 'school_name'):
        counts['complete_school_contexts'] = _scalar(db, "SELECT COUNT(*) FROM school_contexts WHERE length(trim(city))>0 AND length(trim(district))>0 AND length(trim(school_name))>0")
    if _has(schema, 'demo2_identity_students', 'owner_account_id', 'scope_key'):
        counts['identity_owners'] = _scalar(db, 'SELECT COUNT(DISTINCT owner_account_id) FROM demo2_identity_students')
        counts['identity_scopes'] = _scalar(db, 'SELECT COUNT(DISTINCT scope_key) FROM demo2_identity_students')
    return counts


def _activity(db, schema):
    result = {'active_uploads': None, 'processing': None, 'queued': None}
    if _has(schema, 'video_analysis_tasks', 'upload_status'):
        result['active_uploads'] = _scalar(db, "SELECT COUNT(*) FROM video_analysis_tasks WHERE upload_status IN ('created','uploading')")
    if _has(schema, 'video_analysis_tasks', 'analysis_status'):
        for status in ('processing', 'queued'):
            result[status] = _scalar(db, f"SELECT COUNT(*) FROM video_analysis_tasks WHERE analysis_status='{status}'")
    return result


def _path_sample(db, schema, table, column, expected_root, limit):
    if not _has(schema, table, column):
        return {'available': False}
    result = dict(available=True, total_references=_scalar(db, f'SELECT COUNT(*) FROM "{table}"'),
                  sampled_references=0, empty=0, invalid=0, windows_absolute=0,
                  controlled=0, outside_root=0, foreign_platform=0, links_rejected=0,
                  missing=0, regular_files=0, other_file_types=0, access_errors=0,
                  sampled_reference_bytes=0, pending_parts_present=0)
    for (value,) in db.execute(f'SELECT "{column}" FROM "{table}" LIMIT ?', (limit,)):
        result['sampled_references'] += 1
        if value is None or value == '':
            result['empty'] += 1
            continue
        if not isinstance(value, str) or '\0' in value or len(value) > 32768:
            result['invalid'] += 1
            continue
        windows = PureWindowsPath(value).is_absolute()
        result['windows_absolute'] += int(windows)
        if windows and os.name != 'nt':
            result['foreign_platform'] += 1
            continue
        path = Path(value)
        if not path.is_absolute() or '..' in path.parts:
            result['invalid'] += 1
            continue
        if not path.is_relative_to(expected_root) or path == expected_root:
            result['outside_root'] += 1
            continue
        try:
            info = _checked_stat(path)
            result['controlled'] += 1
            if info is None:
                result['missing'] += 1
                if table == 'video_analysis_tasks' and column == 'file_path':
                    part = _checked_stat(Path(str(path) + '.part'))
                    result['pending_parts_present'] += int(part is not None and stat.S_ISREG(part.st_mode))
            elif stat.S_ISREG(info.st_mode):
                result['regular_files'] += 1
                result['sampled_reference_bytes'] += info.st_size
            else:
                result['other_file_types'] += 1
        except InventoryError as error:
            result['links_rejected' if error.code == 'link_or_reparse_point_rejected' else 'invalid'] += 1
        except OSError:
            result['access_errors'] += 1
    result['truncated'] = result['sampled_references'] < result['total_references']
    return result


def inventory(*, root, db=None, upload_dir=None, max_paths=1000):
    if not isinstance(max_paths, int) or not 0 <= max_paths <= 10000:
        raise InventoryError('invalid_sample_limit')
    root = _absolute(root)
    if not _entry(root, directory=True)['exists']:
        raise InventoryError('root_missing')
    db_path = _absolute(db, root) if db is not None else root / 'outputs/seewo_demo2/rehab_affect_demo2.sqlite3'
    uploads = _absolute(upload_dir, root) if upload_dir is not None else db_path.parent / 'student_documents'
    _within(db_path, root)
    _within(uploads, root)
    paths = dict(database=db_path, wal=Path(str(db_path) + '-wal'), shm=Path(str(db_path) + '-shm'),
                 rollback_journal=Path(str(db_path) + '-journal'))
    entries = {name: _entry(path) for name, path in paths.items()}
    if not entries['database']['exists']:
        raise InventoryError('database_missing')
    # Read only the fixed SQLite header, never application rows or key files here.
    # SQLite mode=ro can still create WAL sidecars in a writable directory.
    with db_path.open('rb') as stream:
        header = stream.read(20)
    wal_mode = header.startswith(b'SQLite format 3\x00') and 2 in header[18:20]
    if wal_mode and not entries['wal']['exists']:
        raise InventoryError('wal_sidecars_missing_no_initialization_attempted')
    if entries['wal']['exists'] and not entries['shm']['exists']:
        raise InventoryError('wal_shared_memory_missing_no_recovery_attempted')
    if entries['rollback_journal']['exists'] and entries['rollback_journal']['bytes']:
        raise InventoryError('rollback_journal_present_no_recovery_attempted')
    video = db_path.parent / 'video_tasks'
    dossier = uploads.parent / 'scoped_dossier_v1'
    summary = uploads.parent / 'student_summary_v1'
    keys = uploads.parent / '.demo2_dossier_keys'
    directories = dict(upload_root=uploads, video_root=video, video_sources=video / 'uploads',
                       video_results=video / 'results', video_analysis=video / 'analysis',
                       dossier_root=dossier, summary_root=summary, key_root=keys,
                       legacy_reports=root / 'outputs/seewo_demo2/reports')
    for name, path in directories.items():
        _within(path, root)
        entries[name] = _entry(path, directory=True)
    entries['dossier_owner_marker'] = _entry(dossier / '.dossier-owner.json')
    markers = {}
    for name, path in (('dossier', dossier), ('summary', summary)):
        identifier = hashlib.sha256(os.path.normcase(str(path)).encode('utf-8')).hexdigest()
        markers[name] = _entry(keys / (identifier + '.dpapi'))['exists']
    env_set = KEY_ENV in os.environ
    report = dict(status='ok', consistent_backup=False, migration_ready=False,
        snapshot_scope='database_read_transaction_only_files_are_live',
        coverage='fixed_schema_counts_and_bounded_path_metadata_no_recursive_scan',
        roots=entries, vault=dict(environment_variable_set=env_set, dpapi_markers=markers,
            mode_hint='environment_configured_unvalidated' if env_set else
                      'dpapi_marker_present_unvalidated' if any(markers.values()) else 'unknown_or_unconfigured',
            key_read=False, decrypt_tested=False, relocated_dpapi_markers_not_searched=True),
        disk_free_bytes=shutil.disk_usage(root).free,
        disk_free_scope='authorized_root_only_not_a_sum_across_storage_roots')
    connection = None
    deadline = time.monotonic() + 20
    try:
        connection = sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True, timeout=2)
        connection.execute('PRAGMA query_only=ON')
        connection.execute('PRAGMA trusted_schema=OFF')
        connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 10000)
        connection.execute('BEGIN')
        schema, report['schema'] = _schema(connection)
        report['table_rows'] = {name: _scalar(connection, f'SELECT COUNT(*) FROM "{name}"') for name in TABLES if name in schema}
        report['account_scope_counts'] = _account_scopes(connection, schema)
        report['activity'] = _activity(connection, schema)
        report['recorded_sizes'] = {}
        for table, column in (('student_documents', 'byte_size'), ('video_analysis_tasks', 'byte_size'),
                              ('demo2_dossier_documents', 'encrypted_file_bytes'),
                              ('demo2_dossier_file_cleanup', 'encrypted_file_bytes')):
            if _has(schema, table, column):
                report['recorded_sizes'][table] = _scalar(connection, f'SELECT SUM("{column}") FROM "{table}"')
        report['path_samples'] = {}
        for table, column, boundary in (('student_documents', 'file_path', uploads),
                                        ('video_analysis_tasks', 'file_path', video / 'uploads'),
                                        ('video_analysis_tasks', 'result_path', video / 'results')):
            report['path_samples'][table + '.' + column] = _path_sample(connection, schema, table, column, boundary, max_paths)
    except sqlite3.Error:
        raise InventoryError('sqlite_read_failed_or_budget_exceeded') from None
    finally:
        if connection is not None:
            connection.close()
    report['migration_gates'] = {
        'explicit_target_path_mapping_required': True,
        'owner_marker_rebinding_requires_verified_copy': entries['dossier_owner_marker']['exists'],
        'owner_marker_contents_not_validated': True,
        'linux_cannot_use_dpapi_wrappers': any(markers.values()),
        'separate_vault_keys_possible': all(markers.values()),
        'key_portability_and_decryption_unverified': True,
        'active_work_observed': any(value and value > 0 for value in report['activity'].values()),
        'final_writer_fence_and_file_delta_required': True,
        'retention_and_read_triggered_writers_must_be_fenced': True,
        'windows_keeper_requires_linux_supervision': True,
        'unknown_schema_requires_review': bool(report['schema']['unrecognized_tables'] or report['schema']['virtual_tables'] or report['schema']['views'] or report['schema']['triggers']),
        'path_sampling_incomplete': any(item.get('truncated') for item in report['path_samples'].values()),
        'missing_or_uncontrolled_paths_observed': any(
            item.get(key, 0) > 0 for item in report['path_samples'].values()
            for key in ('invalid', 'outside_root', 'foreign_platform', 'links_rejected', 'missing', 'other_file_types', 'access_errors')),
        'dossier_rows_without_owner_marker': bool(report['table_rows'].get('demo2_dossier_documents', 0)
                                                 and not entries['dossier_owner_marker']['exists']),
        'activity_schema_incomplete': any(value is None for value in report['activity'].values()),
    }
    return report


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise InventoryError('invalid_arguments')


def main(argv=None):
    parser = _Parser(description=__doc__)
    parser.add_argument('--root', required=True, help='Explicit authorized deployment root')
    parser.add_argument('--db', help='Database path; relative paths are under root')
    parser.add_argument('--upload-dir', help='Document upload root; relative paths are under root')
    parser.add_argument('--max-paths', type=int, default=1000, help='Metadata samples per path column, 0..10000')
    try:
        args = parser.parse_args(argv)
        report = inventory(root=args.root, db=args.db, upload_dir=args.upload_dir, max_paths=args.max_paths)
    except InventoryError as error:
        report = {'status': 'error', 'code': error.code, 'consistent_backup': False}
    except Exception:
        report = {'status': 'error', 'code': 'inventory_unavailable', 'consistent_backup': False}
    print(json.dumps(report, ensure_ascii=True, allow_nan=False, sort_keys=True))
    return 0 if report['status'] == 'ok' else 2


if __name__ == '__main__':
    raise SystemExit(main())
