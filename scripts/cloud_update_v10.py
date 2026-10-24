"""V10 cloud code update/rollback. Default is a read-only service/idle inspection.

Never runs on Windows, changes credentials/units, imports the app or restores a
database. --apply-v10 requires --maintenance-approved, a private accepted stage
manifest and its independently supplied --manifest-sha256. Manifest schema:
{"release":"v10","agents_finished":true,"acceptance_passed":true,
 "rollback_compatible":true,"files":{"src/rehab_affect/demo2_course_page.py":"SHA256"}}
These declarations are operator attestations, not an automatically granted approval.
Only accepted backward-compatible code is supported. New tables may be additive;
changing or removing an existing table fails the post-start schema guard.
Incomplete uploads active within one hour, unknown timestamps, live TCP sockets
and workers block updates. Older incomplete uploads are retained, never cancelled;
gateway closure, drain and verified backend shutdown precede any code replacement.
--allow-resumable-idle-uploads permits an incomplete upload only after its task
and retained file have been idle for at least five minutes, with zero sockets or
queued/running work and identical metadata sampled twice on each side of ingress
closure. Statuses/chunks are never changed. Post-start offset/file invariants are
verified without calling the live resume API or reading retained media bytes.
--rollback-v10 --backup DIR uses the same idle gates and preserves the current DB,
including work committed after the update. It also backs up the code being replaced.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time


APP = Path('/opt/rehabaffect')
DB = Path('/var/lib/rehabaffect/seewo_demo2/rehab_affect_demo2.sqlite3')
# Keep deployment backups outside the application-owned data directory.
BACKUPS = Path('/var/lib/rehabaffect-cloud-backups')
STAGE_PARENT = Path('/opt')
APP_UNIT = 'rehabaffect-app.service'
OBS_UNIT = 'rehabaffect-observations.service'
GATE_UNIT = 'rehabaffect-gateway.service'
PREVIEW_UNIT = 'rehabaffect-preview.service'
UNITS = (APP_UNIT, OBS_UNIT, GATE_UNIT, PREVIEW_UNIT)
ALLOWED = frozenset('src/rehab_affect/' + name + '.py' for name in (
    'demo2_observation_store', 'demo2_observation_model', 'demo2_course_page', 'demo2_simple_result',
    'demo2_media_analysis', 'demo2_student_tracking', 'demo2_media_worker',
    'demo2_course_analysis', 'demo2_identity', 'demo2_dossier', 'demo2_portal',
    'demo2_entry', 'demo2_help_page', 'scenario_lab_server', 'student_record_store', 'demo2_student_course_history',
    'demo2_student_summary_page')) | frozenset({
        'scripts/cloud_observation_worker.py', 'scripts/cloud_observation_frames.py'})
MAX_FILE = 10 * 1024 * 1024
UPLOAD_ACTIVITY_SECONDS = 3600
RESUMABLE_IDLE_SECONDS = 300
UPLOAD_CHUNK_BYTES = 4 * 1024 * 1024


class UpdateError(Exception):
    def __init__(self, code, *, blocked=False):
        self.code, self.blocked = code, blocked
        super().__init__(code)


def require(value, code, *, blocked=False):
    if not value:
        raise UpdateError(code, blocked=blocked)


def sha(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def safe_path(path, *, regular=False, private=False, root_owned=True, size_limit=MAX_FILE):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'unsafe_path', blocked=True)
    for component in (path, *path.parents):
        info = component.lstat()
        require(not stat.S_ISLNK(info.st_mode), 'linked_path_refused', blocked=True)
        if os.name == 'posix' and root_owned:
            require(info.st_uid == 0 and not info.st_mode & 0o022,
                    'unsafe_owner_or_mode', blocked=True)
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) if regular else stat.S_ISDIR(info.st_mode),
            'unexpected_path_type', blocked=True)
    if regular:
        require(info.st_nlink == 1 and (size_limit is None or info.st_size <= size_limit),
                'unsafe_file', blocked=True)
    if os.name == 'posix':
        require((not root_owned or info.st_uid == 0)
                and not info.st_mode & (0o077 if private else 0o022),
                'unsafe_owner_or_mode', blocked=True)
    return path


def code_bytes(path):
    path = safe_path(path, regular=True)
    raw = path.read_bytes()
    require(len(raw) <= MAX_FILE, 'unsafe_file', blocked=True)
    try:
        compile(raw, '<verified-cloud-module>', 'exec')
    except (SyntaxError, ValueError, TypeError):
        raise UpdateError('candidate_syntax_invalid', blocked=True) from None
    return raw


def json_file(path):
    raw = safe_path(path, regular=True).read_bytes()
    require(len(raw) <= 256 * 1024, 'manifest_too_large', blocked=True)
    try:
        def unique(pairs):
            result = {}
            for key, value in pairs:
                require(key not in result, 'invalid_manifest', blocked=True)
                result[key] = value
            return result
        return json.loads(raw, object_pairs_hook=unique), raw
    except (ValueError, UnicodeError, RecursionError):
        raise UpdateError('invalid_manifest', blocked=True) from None


def stage_plan(stage, manifest, expected_hash):
    require(stage.parent == STAGE_PARENT and stage.name.startswith('rehabaffect-candidate-'),
            'invalid_stage', blocked=True)
    safe_path(stage)
    require(manifest.parent == stage, 'manifest_outside_stage', blocked=True)
    data, raw = json_file(manifest)
    require(isinstance(expected_hash, str) and re.fullmatch('[0-9a-f]{64}', expected_hash)
            and sha(raw) == expected_hash, 'manifest_checksum_mismatch', blocked=True)
    require(isinstance(data, dict) and set(data) == {
        'release', 'agents_finished', 'acceptance_passed', 'rollback_compatible', 'files'}
        and data['release'] == 'v10'
        and all(data[key] is True for key in ('agents_finished', 'acceptance_passed', 'rollback_compatible')),
        'accepted_backward_compatible_release_required', blocked=True)
    files = data['files']
    require(isinstance(files, dict) and files and set(files) <= ALLOWED,
            'file_outside_update_scope', blocked=True)
    result = {}
    for relative, digest in files.items():
        require(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest),
                'invalid_manifest', blocked=True)
        raw_code = code_bytes(stage / relative)
        require(sha(raw_code) == digest, 'candidate_checksum_mismatch', blocked=True)
        result[relative] = raw_code
        safe_path((APP / relative).parent)
        if (APP / relative).exists() or (APP / relative).is_symlink():
            safe_path(APP / relative, regular=True)
    return result


def run(*command, timeout=150):
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout)
        require(result.returncode == 0, 'service_command_failed')
    except (OSError, subprocess.SubprocessError):
        raise UpdateError('service_command_failed') from None


def service_state(unit):
    try:
        result = subprocess.run(['systemctl', 'show', unit,
            '--property=LoadState,ActiveState,MainPID,ControlPID,ControlGroup,TasksCurrent,Job'],
            capture_output=True, text=True, timeout=10)
        require(result.returncode == 0, 'service_state_unavailable', blocked=True)
        return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    except (OSError, subprocess.SubprocessError):
        raise UpdateError('service_state_unavailable', blocked=True) from None


def stopped(unit):
    state = service_state(unit)
    return (state.get('ActiveState') in {'inactive', 'failed'}
            and state.get('MainPID') == state.get('ControlPID') == '0'
            and state.get('Job') in {'', '0'}
            and (state.get('ControlGroup') == '' or state.get('TasksCurrent') == '0'))


def active(unit):
    state = service_state(unit)
    return (state.get('LoadState') == 'loaded' and state.get('ActiveState') == 'active'
            and state.get('MainPID', '').isdigit() and int(state['MainPID']) > 0
            and state.get('ControlPID') == '0' and state.get('Job') in {'', '0'})


def stop(unit):
    run('systemctl', 'stop', unit)
    require(stopped(unit), 'service_processes_not_stopped')


def start(unit):
    run('systemctl', 'start', unit)
    require(active(unit), 'service_not_active')


def database_state():
    safe_path(DB, regular=True, root_owned=False, size_limit=None)
    for suffix in ('-wal', '-shm', '-journal'):
        sidecar = DB.with_name(DB.name + suffix)
        if sidecar.exists() or sidecar.is_symlink():
            safe_path(sidecar, regular=True, root_owned=False, size_limit=None)
    try:
        with closing(sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA trusted_schema=OFF')
            require(db.execute('PRAGMA quick_check').fetchone() == ('ok',), 'database_integrity_failed')
            counts = {
                'accounts': db.execute('SELECT COUNT(*) FROM platform_accounts').fetchone()[0],
                'tasks': db.execute('SELECT COUNT(*) FROM video_analysis_tasks').fetchone()[0],
                'media_busy': db.execute("SELECT COUNT(*) FROM video_analysis_tasks WHERE analysis_status IN ('queued','processing')").fetchone()[0],
                'observation_busy': db.execute("SELECT COUNT(*) FROM demo2_observation_jobs WHERE status NOT IN ('ready','failed')").fetchone()[0],
            }
            uploads = db.execute('''SELECT COUNT(*),
                COALESCE(SUM(julianday(updated_at)>=julianday('now')-?/86400.0),0),
                COALESCE(SUM(julianday(updated_at) IS NULL),0),
                strftime('%Y-%m-%dT%H:%M:%SZ',MIN(julianday(updated_at))),
                strftime('%Y-%m-%dT%H:%M:%SZ',MAX(julianday(updated_at)))
                FROM video_analysis_tasks WHERE upload_status IS NULL
                OR upload_status NOT IN ('completed','cancelled','expired')''',
                (UPLOAD_ACTIVITY_SECONDS,)).fetchone()
            counts.update(uploads_incomplete=uploads[0], uploads_recent_active=uploads[1],
                          uploads_invalid_timestamp=uploads[2],
                          uploads_historical_incomplete=uploads[0]-uploads[1]-uploads[2])
            schemas = {name: sha(sql.encode('utf-8')) for name, sql in db.execute(
                "SELECT name,sql FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            digest = hashlib.sha256()
            for query in (
                'SELECT account_id,role,status,bound_channel_id FROM platform_accounts ORDER BY account_id',
                'SELECT task_id,account_id,channel_id,sha256,byte_size FROM video_analysis_tasks ORDER BY task_id',
            ):
                for row in db.execute(query):
                    digest.update(json.dumps(row, separators=(',', ':')).encode('utf-8') + b'\n')
            return {'counts': counts, 'protected_hash': digest.hexdigest(), 'table_schemas': schemas,
                    'upload_activity_window_seconds': UPLOAD_ACTIVITY_SECONDS,
                    'uploads_oldest_updated_utc': uploads[3], 'uploads_latest_updated_utc': uploads[4]}
    except sqlite3.Error:
        raise UpdateError('database_or_observation_schema_unavailable', blocked=True) from None


def parse_connections(output):
    result = {'app_active_connections': 0, 'gateway_active_connections': 0, 'pending_accepts': 0}
    known = {'LISTEN', 'ESTAB', 'SYN-SENT', 'SYN-RECV', 'FIN-WAIT-1', 'FIN-WAIT-2',
             'TIME-WAIT', 'CLOSE-WAIT', 'CLOSED', 'CLOSING', 'LAST-ACK'}
    for line in output.splitlines():
        fields = line.split()
        require(len(fields) >= 5, 'connection_state_unavailable', blocked=True)
        port = fields[3].rsplit(':', 1)[-1]
        if port not in {'8793', '8796'}:
            continue
        require(fields[0] in known and fields[1].isdigit() and fields[2].isdigit(),
                'connection_state_unavailable', blocked=True)
        if fields[0] == 'LISTEN':
            result['pending_accepts'] += int(fields[1])
        elif fields[0] not in {'TIME-WAIT', 'CLOSED'}:
            key = 'app_active_connections' if port == '8793' else 'gateway_active_connections'
            result[key] += 1
    return result


def network_state():
    try:
        completed = subprocess.run(['ss', '-H', '-n', '-t', '-a'],
                                   capture_output=True, text=True, timeout=10)
        require(completed.returncode == 0, 'connection_state_unavailable', blocked=True)
        return parse_connections(completed.stdout)
    except (OSError, subprocess.SubprocessError):
        raise UpdateError('connection_state_unavailable', blocked=True) from None


def require_idle(state, connections=None, *, allow_resumable_idle_uploads=False):
    keys = ('media_busy', 'uploads_invalid_timestamp', 'observation_busy')
    if not allow_resumable_idle_uploads:
        keys += ('uploads_recent_active',)
    require(not any(state['counts'][key] for key in keys),
            'cloud_work_not_idle', blocked=True)
    if connections is not None:
        require(not any(connections.values()), 'cloud_connections_not_idle', blocked=True)


def resumable_upload_state():
    root = DB.parent / 'video_tasks/uploads'
    now = time.time()
    rows = []
    try:
        with closing(sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA trusted_schema=OFF')
            db.row_factory = sqlite3.Row
            result = db.execute('''SELECT task_id,upload_status,analysis_status,received_bytes,
                byte_size,next_chunk_index,total_chunks,file_path,updated_at,expires_at,raw_media_deleted_at,
                (julianday('now')-julianday(updated_at))*86400.0 AS idle_seconds,
                julianday(expires_at)>julianday('now') AS unexpired,
                strftime('%Y-%m-%dT%H:%M:%SZ',julianday(updated_at)) AS updated_utc
                FROM video_analysis_tasks WHERE upload_status IS NULL
                OR upload_status NOT IN ('completed','cancelled','expired') ORDER BY task_id''')
            rows = [dict(row) for row in result]
    except sqlite3.Error:
        raise UpdateError('resume_metadata_unavailable', blocked=True) from None
    fingerprint, diagnostics = [], []
    for row in rows:
        require(row['upload_status'] == 'uploading' and row['analysis_status'] == 'waiting_upload'
                and row['unexpired'] == 1 and not row['raw_media_deleted_at'],
                'upload_not_resumable', blocked=True)
        require(isinstance(row['idle_seconds'], (int, float))
                and row['idle_seconds'] >= RESUMABLE_IDLE_SECONDS,
                'upload_activity_too_recent', blocked=True)
        size, received, index, total = (row[key] for key in
            ('byte_size', 'received_bytes', 'next_chunk_index', 'total_chunks'))
        require(all(type(value) is int for value in (size, received, index, total))
                and size > 0 and total == (size + UPLOAD_CHUNK_BYTES - 1) // UPLOAD_CHUNK_BYTES
                and 0 <= index < total and received == index * UPLOAD_CHUNK_BYTES,
                'upload_offset_inconsistent', blocked=True)
        final = Path(row['file_path'])
        require(final.is_absolute() and final.is_relative_to(root), 'upload_path_unverifiable', blocked=True)
        safe_path(final.parent, root_owned=False)
        paths = [final, Path(str(final) + '.part')]
        retained, files, signature = [], [], []
        for role, path in zip(('registered', 'partial'), paths):
            path_token = sha(str(path.relative_to(root)).encode('utf-8'))
            exists = path.exists() or path.is_symlink()
            record = {'role': role, 'path_token': path_token, 'exists': exists}
            metadata = None
            if exists:
                safe_path(path, regular=True, root_owned=False, size_limit=None)
                info = path.stat()
                require(now-max(info.st_mtime, info.st_ctime) >= RESUMABLE_IDLE_SECONDS,
                        'upload_chunk_activity_too_recent', blocked=True)
                metadata = [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
                            info.st_ctime_ns, info.st_mode, info.st_uid, info.st_gid]
                record.update(size_bytes=info.st_size, mtime_ns=info.st_mtime_ns)
                retained.append(info)
            signature.append([role, path_token, metadata])
            files.append(record)
        require(len(retained) == 1 and received <= retained[0].st_size <= size,
                'upload_chunk_state_inconsistent', blocked=True)
        stable = {key: value for key, value in row.items()
                  if key not in {'idle_seconds', 'unexpired', 'updated_utc', 'file_path'}}
        stable['path_token'] = sha(str(final.relative_to(root)).encode('utf-8'))
        fingerprint.append([stable, signature])
        diagnostics.append({key: row[key] for key in ('task_id', 'upload_status', 'analysis_status',
            'received_bytes', 'byte_size', 'next_chunk_index', 'total_chunks', 'updated_utc')})
        diagnostics[-1]['files'] = files
    return {'fingerprint': sha(json.dumps(fingerprint, sort_keys=True).encode('utf-8')),
            'tasks': diagnostics}


def idle_snapshot(allow_resumable_idle_uploads):
    state = database_state()
    require_idle(state, network_state(), allow_resumable_idle_uploads=allow_resumable_idle_uploads)
    uploads = resumable_upload_state() if allow_resumable_idle_uploads else None
    return state, uploads


def require_uploads_unchanged(expected, observed=None):
    if expected is not None:
        observed = observed if observed is not None else resumable_upload_state()
        require(observed['fingerprint'] == expected['fingerprint'],
                'resumable_upload_metadata_changed', blocked=True)


def app_healthy():
    for _ in range(10):
        connection = http.client.HTTPConnection('127.0.0.1', 8793, timeout=2)
        try:
            connection.request('GET', '/demo2/login', headers={'Connection': 'close'})
            response = connection.getresponse()
            if response.status == 200 and 'text/html' in response.getheader('Content-Type', ''):
                return True
        except (OSError, http.client.HTTPException):
            pass
        finally:
            connection.close()
        time.sleep(1)
    return False


def drain_pause():
    time.sleep(2)


def sync_directory(path):
    if os.name == 'posix':
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def atomic_file(target, raw, *, mode=0o644, uid=0, gid=0):
    safe_path(target.parent)
    if target.exists() or target.is_symlink():
        safe_path(target, regular=True)
    if raw is None:
        target.unlink(missing_ok=True)
        sync_directory(target.parent)
        return
    fd, name = tempfile.mkstemp(prefix='.v10-', dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == 'posix':
            os.chown(temporary, uid, gid)
        temporary.chmod(mode)
        os.replace(temporary, target)
        sync_directory(target.parent)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def deployment_lock():
    import fcntl
    BACKUPS.mkdir(mode=0o700, parents=True, exist_ok=True)
    safe_path(BACKUPS, private=True)
    path = BACKUPS / '.v10-update.lock'
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and info.st_uid == 0 and not info.st_mode & 0o077, 'unsafe_lock')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise UpdateError('deployment_already_running', blocked=True) from None
        yield
    finally:
        os.close(fd)


def backup_code_and_db(plan, before):
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory = BACKUPS / ('v10-' + stamp + '-' + secrets.token_hex(4))
    directory.mkdir(mode=0o700)
    sync_directory(BACKUPS)
    descriptor = os.open(directory / 'database.sqlite3', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    with closing(sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect((directory / 'database.sqlite3').as_uri() + '?mode=rw', uri=True)) as target:
            source.backup(target)
            require(target.execute('PRAGMA quick_check').fetchone() == ('ok',), 'database_backup_invalid')
    files = {}
    for relative, desired in plan.items():
        live = APP / relative
        previous = code_bytes(live) if live.exists() else None
        info = live.stat() if previous is not None else None
        files[relative] = {'previous_sha256': sha(previous), 'candidate_sha256': sha(desired),
                          'mode': stat.S_IMODE(info.st_mode) if info and os.name == 'posix' else 0o644,
                          'uid': 0, 'gid': info.st_gid if info else 0}
        if previous is not None:
            saved = directory / relative
            saved.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            atomic_file(saved, previous, mode=0o600)
    atomic_file(directory / 'rollback.json', json.dumps({
        'release': 'v10', 'rollback_compatible': True, 'files': files,
        'protected_hash_before': before['protected_hash'], 'database_restore_automatic': False,
        'existing_table_schemas_before': before['table_schemas'],
    }, sort_keys=True).encode(), mode=0o600)
    return directory


def rollback_plan(directory, *, partial=False):
    require(directory.parent == BACKUPS and directory.name.startswith('v10-'), 'invalid_backup', blocked=True)
    safe_path(directory, private=True)
    data, _ = json_file(directory / 'rollback.json')
    require(isinstance(data, dict) and data.get('release') == 'v10'
            and data.get('rollback_compatible') is True and data.get('database_restore_automatic') is False
            and isinstance(data.get('files'), dict) and data['files'] and set(data['files']) <= ALLOWED,
            'invalid_backup_manifest', blocked=True)
    plan = {}
    for relative, entry in data['files'].items():
        require(isinstance(entry, dict), 'invalid_backup_manifest', blocked=True)
        require(type(entry.get('mode')) is int and 0 <= entry['mode'] <= 0o777
                and not entry['mode'] & 0o022 and entry.get('uid') == 0
                and type(entry.get('gid')) is int and entry['gid'] >= 0,
                'invalid_backup_manifest', blocked=True)
        previous_hash, candidate_hash = entry.get('previous_sha256'), entry.get('candidate_sha256')
        for value in (previous_hash, candidate_hash):
            require(value is None or isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value),
                    'invalid_backup_manifest', blocked=True)
        live = APP / relative
        current = code_bytes(live) if live.exists() or live.is_symlink() else None
        allowed = {candidate_hash, previous_hash} if partial else {candidate_hash}
        require(sha(current) in allowed, 'live_code_changed_since_backup', blocked=True)
        raw = code_bytes(directory / relative) if previous_hash is not None else None
        require(sha(raw) == previous_hash, 'backup_code_checksum_mismatch', blocked=True)
        plan[relative] = raw
    return plan


def install_plan(plan, metadata=None):
    for relative, raw in plan.items():
        entry = metadata[relative] if metadata else {}
        atomic_file(APP / relative, raw, mode=entry.get('mode', 0o644),
                    uid=entry.get('uid', 0), gid=entry.get('gid', 0))


def verified_stopped(unit):
    try:
        return stopped(unit)
    except Exception:
        return False


def resume_backend(before, preserved_uploads=None):
    start(APP_UNIT)
    require(app_healthy(), 'app_health_failed')
    start(OBS_UNIT)
    after = database_state()
    require(after['protected_hash'] == before['protected_hash'], 'protected_database_rows_changed')
    require(all(after['table_schemas'].get(name) == digest
                for name, digest in before['table_schemas'].items()), 'existing_table_schema_changed')
    require_uploads_unchanged(preserved_uploads)


def update(plan, *, recheck=None, metadata=None, recovery=False, allow_resumable_idle_uploads=False):
    require(stopped(PREVIEW_UNIT), 'preview_must_remain_stopped', blocked=True)
    require(all(active(unit) or recovery and stopped(unit) for unit in (APP_UNIT, OBS_UNIT))
            and (active(GATE_UNIT) or stopped(GATE_UNIT)),
            'cloud_service_state_unexpected', blocked=True)
    _, preserved_uploads = idle_snapshot(allow_resumable_idle_uploads)
    if allow_resumable_idle_uploads:
        drain_pause()
        _, observed = idle_snapshot(True)
        require_uploads_unchanged(preserved_uploads, observed)
    gateway_was_active = active(GATE_UNIT)
    before = None
    backup = None
    touched = False
    try:
        stop(GATE_UNIT)
        drain_pause()
        _, observed = idle_snapshot(allow_resumable_idle_uploads)
        require_uploads_unchanged(preserved_uploads, observed)
        if allow_resumable_idle_uploads:
            drain_pause()
            _, observed = idle_snapshot(True)
            require_uploads_unchanged(preserved_uploads, observed)
        stop(OBS_UNIT)
        stop(APP_UNIT)
        require(stopped(APP_UNIT) and stopped(OBS_UNIT) and stopped(GATE_UNIT)
                and stopped(PREVIEW_UNIT), 'deployment_processes_not_stopped')
        before = database_state()
        require_idle(before, network_state(), allow_resumable_idle_uploads=allow_resumable_idle_uploads)
        require_uploads_unchanged(preserved_uploads)
        if recheck is not None:
            require(recheck() == plan, 'candidate_changed_after_approval', blocked=True)
        backup = backup_code_and_db(plan, before)
        touched = True
        install_plan(plan, metadata)
        resume_backend(before, preserved_uploads)
        if gateway_was_active:
            start(GATE_UNIT)
        return {'ok': True, 'updated': True, 'backup_id': backup.name,
                'database_restored': False, 'windows_touched': False,
                'ingress_resumed': gateway_was_active,
                'resumable_idle_uploads_preserved': len(preserved_uploads['tasks']) if preserved_uploads else 0,
                'resume_verification': ('committed_offsets_and_file_metadata_unchanged'
                                        if preserved_uploads is not None else 'not_requested'),
                'live_resume_api_called': False, 'uploads_modified': False}
    except Exception as cause:
        cause_code = cause.code if isinstance(cause, UpdateError) else 'update_failed'
        try:
            stop(GATE_UNIT)
            if touched:
                stop(OBS_UNIT)
                stop(APP_UNIT)
                require(stopped(APP_UNIT) and stopped(OBS_UNIT), 'rollback_processes_not_stopped')
                old = rollback_plan(backup, partial=True)
                previous_metadata, _ = json_file(backup / 'rollback.json')
                install_plan(old, previous_metadata['files'])
                resume_backend(before, preserved_uploads)
            else:
                start(APP_UNIT)
                require(app_healthy(), 'app_health_failed')
                start(OBS_UNIT)
            if gateway_was_active:
                start(GATE_UNIT)
        except Exception:
            # Do not reopen ingress when service shutdown, code or DB preservation is uncertain.
            try:
                stop(GATE_UNIT)
            except Exception:
                pass
            return {'ok': False, 'error': 'update_or_rollback_failed_operator_action_required',
                    'cause': cause_code, 'ingress_verified_stopped': verified_stopped(GATE_UNIT),
                    'database_restored': False, 'backup_id': backup.name if backup else None}
        return {'ok': False, 'error': 'update_failed_previous_code_resumed', 'cause': cause_code,
                'blocked': isinstance(cause, UpdateError) and cause.blocked,
                'database_restored': False, 'backup_id': backup.name if backup else None}


def inspect(*, allow_resumable_idle_uploads=False):
    state = database_state()
    connections = network_state()
    services = {}
    for unit in UNITS:
        values = service_state(unit)
        services[unit] = {key: values.get(key) for key in ('LoadState', 'ActiveState', 'MainPID')}
    try:
        require_idle(state, connections, allow_resumable_idle_uploads=allow_resumable_idle_uploads)
        uploads = resumable_upload_state() if allow_resumable_idle_uploads else None
        idle = True
        diagnostic_error = None
    except UpdateError as error:
        idle = False
        uploads = None
        diagnostic_error = error.code
    return {'ok': True, 'read_only': True, 'counts': state['counts'], 'services': services,
            'connections': connections, 'idle': idle, 'request_counters_available': False,
            'upload_activity_window_seconds': state['upload_activity_window_seconds'],
            'uploads_oldest_updated_utc': state['uploads_oldest_updated_utc'],
            'uploads_latest_updated_utc': state['uploads_latest_updated_utc'],
            'existing_table_count': len(state['table_schemas']),
            'allow_resumable_idle_uploads': allow_resumable_idle_uploads,
            'minimum_upload_quiet_seconds': RESUMABLE_IDLE_SECONDS,
            'resumable_uploads': uploads['tasks'] if uploads else [],
            'resume_check_error': diagnostic_error,
            'stable_checks_required_before_apply': allow_resumable_idle_uploads}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UpdateError('invalid_arguments', blocked=True)


def main(argv=None):
    try:
        parser = Parser(description=__doc__)
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument('--apply-v10', action='store_true')
        mode.add_argument('--rollback-v10', action='store_true')
        parser.add_argument('--maintenance-approved', action='store_true')
        parser.add_argument('--allow-resumable-idle-uploads', action='store_true')
        parser.add_argument('--stage', type=Path)
        parser.add_argument('--manifest', type=Path)
        parser.add_argument('--manifest-sha256')
        parser.add_argument('--backup', type=Path)
        args = parser.parse_args(argv)
        require(sys.platform.startswith('linux'), 'linux_cloud_only', blocked=True)
        if not args.apply_v10 and not args.rollback_v10:
            result = inspect(allow_resumable_idle_uploads=args.allow_resumable_idle_uploads)
        else:
            require(args.maintenance_approved and os.geteuid() == 0,
                    'explicit_root_maintenance_approval_required', blocked=True)
            os.umask(0o077)
            with deployment_lock():
                if args.apply_v10:
                    require(args.stage is not None and args.manifest is not None
                            and args.backup is None, 'invalid_arguments', blocked=True)
                    recheck = lambda: stage_plan(args.stage, args.manifest, args.manifest_sha256)
                    result = update(recheck(), recheck=recheck,
                                    allow_resumable_idle_uploads=args.allow_resumable_idle_uploads)
                else:
                    require(args.backup is not None and args.stage is None and args.manifest is None,
                            'invalid_arguments', blocked=True)
                    recheck = lambda: rollback_plan(args.backup)
                    previous_metadata, _ = json_file(args.backup / 'rollback.json')
                    result = update(recheck(), recheck=recheck, metadata=previous_metadata['files'], recovery=True,
                                    allow_resumable_idle_uploads=args.allow_resumable_idle_uploads)
                    result['rollback_requested'] = True
    except UpdateError as error:
        result = {'ok': False, 'error': error.code, 'blocked': error.blocked, 'database_restored': False}
    except Exception:
        result = {'ok': False, 'error': 'cloud_update_error', 'database_restored': False}
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0 if result['ok'] else 2 if result.get('blocked') else 1


if __name__ == '__main__':
    raise SystemExit(main())
