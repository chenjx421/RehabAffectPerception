"""Temporary DBs/code and fake systemd only. Never connect to a real service."""
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace

import pytest

from scripts import cloud_update_v10 as qa
from test_cloud_upload_acceleration import (
    cloud as upload_backend, make_env as make_upload_env, _append, _create, _raw,
)


RELATIVE = 'src/rehab_affect/demo2_course_page.py'
OLD = b'VERSION = "before"\n'
NEW = b'VERSION = "v10"\n'


@pytest.fixture
def host(tmp_path, monkeypatch):
    app, backups, stages = tmp_path / 'app', tmp_path / 'backups', tmp_path / 'stages'
    for path in (app, backups, stages):
        path.mkdir(mode=0o700)
    live = app / RELATIVE
    live.parent.mkdir(parents=True)
    live.write_bytes(OLD)
    db_path = tmp_path / 'live.sqlite3'
    with sqlite3.connect(db_path) as db:
        db.executescript('''
            CREATE TABLE platform_accounts(account_id TEXT,role TEXT,status TEXT,bound_channel_id TEXT);
            INSERT INTO platform_accounts VALUES('opaque-account','school_uploader','active','channel_1');
            CREATE TABLE video_analysis_tasks(task_id TEXT,account_id TEXT,channel_id TEXT,sha256 TEXT,
                byte_size INTEGER,upload_status TEXT,analysis_status TEXT,updated_at TEXT);
            INSERT INTO video_analysis_tasks VALUES('opaque-task','opaque-account','channel_1','hash',
                128,'completed','evidence_ready','2000-01-01');
            CREATE TABLE demo2_observation_jobs(status TEXT);
            INSERT INTO demo2_observation_jobs VALUES('ready');
        ''')
    stage = stages / 'rehabaffect-candidate-v10-test'
    (stage / RELATIVE).parent.mkdir(parents=True)
    (stage / RELATIVE).write_bytes(NEW)
    manifest = stage / 'v10-update.json'
    manifest.write_text(json.dumps({'release': 'v10', 'agents_finished': True,
        'acceptance_passed': True, 'rollback_compatible': True,
        'files': {RELATIVE: qa.sha(NEW)}}))
    state = {unit: unit != qa.PREVIEW_UNIT for unit in qa.UNITS}
    calls, failures = [], {}
    monkeypatch.setattr(qa, 'APP', app)
    monkeypatch.setattr(qa, 'DB', db_path)
    monkeypatch.setattr(qa, 'BACKUPS', backups)
    monkeypatch.setattr(qa, 'STAGE_PARENT', stages)
    monkeypatch.setattr(qa, 'deployment_lock', lambda: nullcontext())
    monkeypatch.setattr(qa, 'drain_pause', lambda: None)
    monkeypatch.setattr(qa, 'app_healthy', lambda: True)
    monkeypatch.setattr(qa, 'network_state', lambda: {
        'app_active_connections': 0, 'gateway_active_connections': 0, 'pending_accepts': 0})
    # Fixtures simulate root-owned files without needing a privileged test runner.
    original_safe = qa.safe_path
    def safe(path, **kwargs):
        kwargs['root_owned'] = False
        return original_safe(path, **kwargs)
    monkeypatch.setattr(qa, 'safe_path', safe)
    if hasattr(os, 'chown'):
        monkeypatch.setattr(qa.os, 'chown', lambda *args: None)

    def service_state(unit):
        running = state[unit]
        return {'LoadState': 'loaded', 'ActiveState': 'active' if running else 'inactive',
                'MainPID': '123' if running else '0', 'ControlPID': '0', 'Job': '',
                'ControlGroup': '/test' if running else '', 'TasksCurrent': '2' if running else '0'}
    monkeypatch.setattr(qa, 'service_state', service_state)

    def run(*command, **kwargs):
        calls.append(command)
        key = command[1:]
        if failures.get(key, 0):
            failures[key] -= 1
            raise qa.UpdateError('service_command_failed')
        state[command[2]] = command[1] == 'start'
    monkeypatch.setattr(qa, 'run', run)
    return SimpleNamespace(app=app, live=live, db=db_path, backups=backups, stage=stage,
        manifest=manifest, state=state, calls=calls, failures=failures)


def accepted(host):
    return qa.stage_plan(host.stage, host.manifest, qa.sha(host.manifest.read_bytes()))


def resumable(host, monkeypatch):
    partial = host.db.parent / 'video_tasks/uploads/private-synthetic.mp4.part'
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b'x' * qa.UPLOAD_CHUNK_BYTES)
    with sqlite3.connect(host.db) as db:
        for name, kind in (('received_bytes', 'INTEGER'), ('next_chunk_index', 'INTEGER'),
                           ('total_chunks', 'INTEGER'), ('file_path', 'TEXT'),
                           ('expires_at', 'TEXT'), ('raw_media_deleted_at', 'TEXT')):
            db.execute(f'ALTER TABLE video_analysis_tasks ADD COLUMN {name} {kind}')
        db.execute("""UPDATE video_analysis_tasks SET upload_status='uploading',
            analysis_status='waiting_upload',updated_at=datetime('now','-15 minutes'),
            received_bytes=?,byte_size=?,next_chunk_index=1,total_chunks=2,
            file_path=?,expires_at=datetime('now','+30 days'),raw_media_deleted_at=''""",
            (qa.UPLOAD_CHUNK_BYTES, qa.UPLOAD_CHUNK_BYTES + 123, str(partial)[:-5]))
    # File creation changes ctime even when mtime is set back. Advance only the
    # helper's file-age clock; SQLite continues using real UTC for task age.
    monkeypatch.setattr(qa, 'time', SimpleNamespace(time=lambda: time.time() + 600))
    return partial


def test_inspection_is_read_only_and_has_no_service_actions(host):
    before = host.db.read_bytes()
    result = qa.inspect()
    assert result['read_only'] and result['idle']
    assert result['counts']['tasks'] == 1
    assert host.db.read_bytes() == before and host.calls == []
    assert not list(host.backups.iterdir())


@pytest.mark.parametrize('work', ['recent_upload', 'invalid_upload_timestamp', 'queued_media', 'pending_observation', 'running_observation'])
def test_active_or_unverifiable_work_blocks_before_stopping_services(host, work):
    with sqlite3.connect(host.db) as db:
        if work == 'recent_upload':
            db.execute("UPDATE video_analysis_tasks SET upload_status='uploading',updated_at=datetime('now','-30 minutes')")
        elif work == 'invalid_upload_timestamp':
            db.execute("UPDATE video_analysis_tasks SET upload_status='uploading',updated_at='INVALID-PRIVATE'")
        elif work == 'queued_media':
            db.execute("UPDATE video_analysis_tasks SET analysis_status='queued'")
        else:
            db.execute('UPDATE demo2_observation_jobs SET status=?',
                       ('pending' if work == 'pending_observation' else 'running',))
    with pytest.raises(qa.UpdateError, match='cloud_work_not_idle'):
        qa.update(accepted(host))
    assert host.calls == [] and host.live.read_bytes() == OLD


def test_update_creates_consistent_db_backup_but_never_modifies_live_db(host):
    before = host.db.read_bytes()
    result = qa.update(accepted(host), recheck=lambda: accepted(host))
    assert result['ok'] and result['database_restored'] is False
    assert result['resume_verification'] == 'not_requested'
    assert host.live.read_bytes() == NEW and host.db.read_bytes() == before
    directory = host.backups / result['backup_id']
    with sqlite3.connect(directory / 'database.sqlite3') as db:
        assert db.execute('SELECT COUNT(*) FROM video_analysis_tasks').fetchone()[0] == 1
    assert (directory / RELATIVE).read_bytes() == OLD
    assert all(host.state[unit] for unit in (qa.APP_UNIT, qa.OBS_UNIT, qa.GATE_UNIT))
    assert not host.state[qa.PREVIEW_UNIT]


def test_historical_incomplete_upload_is_diagnostic_only_and_not_cancelled(host):
    with sqlite3.connect(host.db) as db:
        db.execute("UPDATE video_analysis_tasks SET upload_status='uploading'")
    before = host.db.read_bytes()
    diagnostic = qa.inspect()
    assert diagnostic['counts']['uploads_incomplete'] == 1
    assert diagnostic['counts']['uploads_historical_incomplete'] == 1
    assert diagnostic['counts']['uploads_recent_active'] == 0
    assert diagnostic['upload_activity_window_seconds'] >= 3600
    assert diagnostic['idle'] and diagnostic['request_counters_available'] is False
    assert diagnostic['uploads_latest_updated_utc'] == '2000-01-01T00:00:00Z'
    assert qa.update(accepted(host))['ok']
    assert host.db.read_bytes() == before
    with sqlite3.connect(host.db) as db:
        assert db.execute('SELECT upload_status FROM video_analysis_tasks').fetchone()[0] == 'uploading'


@pytest.mark.parametrize('key', ['app_active_connections', 'gateway_active_connections', 'pending_accepts'])
def test_connections_block_even_when_only_historical_uploads_remain(host, monkeypatch, key):
    state = {'app_active_connections': 0, 'gateway_active_connections': 0, 'pending_accepts': 0}
    state[key] = 1
    monkeypatch.setattr(qa, 'network_state', lambda: state)
    with pytest.raises(qa.UpdateError, match='cloud_connections_not_idle'):
        qa.update(accepted(host))
    assert host.calls == []


def test_tcp_diagnostics_ignore_listen_capacity_timewait_and_unrelated_ports():
    result = qa.parse_connections('''LISTEN 0 128 127.0.0.1:8793 0.0.0.0:*
LISTEN 1 128 127.0.0.1:8796 0.0.0.0:*
TIME-WAIT 0 0 127.0.0.1:8793 127.0.0.1:12345
ESTAB 0 0 127.0.0.1:8793 127.0.0.1:12346
CLOSE-WAIT 0 0 [::1]:8796 [::1]:12347
ESTAB 0 0 127.0.0.1:22 127.0.0.1:12348''')
    assert result == {'app_active_connections': 1, 'gateway_active_connections': 1, 'pending_accepts': 1}


def test_unknown_socket_state_is_not_treated_as_idle():
    with pytest.raises(qa.UpdateError, match='connection_state_unavailable'):
        qa.parse_connections('UNKNOWN 0 0 127.0.0.1:8793 127.0.0.1:12345')


def test_additive_target_settings_table_is_rollback_compatible(host, monkeypatch):
    def healthy():
        with sqlite3.connect(host.db) as db:
            db.execute('CREATE TABLE IF NOT EXISTS demo2_observation_target_settings (student_id TEXT)')
        return True
    monkeypatch.setattr(qa, 'app_healthy', healthy)
    installed = qa.update(accepted(host))
    assert installed['ok']
    directory = host.backups / installed['backup_id']
    assert qa.update(qa.rollback_plan(directory))['ok']
    with sqlite3.connect(host.db) as db:
        assert db.execute("SELECT COUNT(*) FROM sqlite_schema WHERE name='demo2_observation_target_settings'").fetchone()[0] == 1


def test_altering_existing_table_fails_closed_without_database_restore(host, monkeypatch):
    calls = [0]
    def healthy():
        calls[0] += 1
        if calls[0] == 1:
            with sqlite3.connect(host.db) as db:
                db.execute('ALTER TABLE video_analysis_tasks ADD COLUMN unexpected TEXT')
        return True
    monkeypatch.setattr(qa, 'app_healthy', healthy)
    result = qa.update(accepted(host))
    assert not result['ok'] and not result['database_restored']
    assert result['cause'] == 'existing_table_schema_changed'
    assert result['ingress_verified_stopped'] and not host.state[qa.GATE_UNIT]
    with sqlite3.connect(host.db) as db:
        assert 'unexpected' in {row[1] for row in db.execute('PRAGMA table_info(video_analysis_tasks)')}


def test_failed_start_restores_previous_code_before_reopening_ingress(host):
    host.failures[('start', qa.APP_UNIT)] = 1
    before = host.db.read_bytes()
    result = qa.update(accepted(host))
    assert not result['ok'] and result['error'] == 'update_failed_previous_code_resumed'
    assert host.live.read_bytes() == OLD and host.db.read_bytes() == before
    assert host.state[qa.GATE_UNIT] and host.state[qa.APP_UNIT] and host.state[qa.OBS_UNIT]


def test_work_arriving_during_gateway_drain_aborts_without_touching_code(host, monkeypatch):
    def arriving():
        with sqlite3.connect(host.db) as db:
            db.execute("UPDATE video_analysis_tasks SET upload_status='uploading',updated_at=datetime('now')")
    monkeypatch.setattr(qa, 'drain_pause', arriving)
    result = qa.update(accepted(host))
    assert not result['ok'] and result['blocked'] and result['cause'] == 'cloud_work_not_idle'
    assert host.live.read_bytes() == OLD and host.state[qa.GATE_UNIT]
    assert not list(host.backups.iterdir())


def test_failed_shutdown_never_restores_code_into_a_running_process(host, monkeypatch):
    host.failures[('start', qa.APP_UNIT)] = 1
    original_stop = qa.stop
    app_stops = [0]
    def unsafe_second_stop(unit):
        if unit == qa.APP_UNIT:
            app_stops[0] += 1
            if app_stops[0] == 2:
                host.state[unit] = True
                raise qa.UpdateError('service_processes_not_stopped')
        original_stop(unit)
    monkeypatch.setattr(qa, 'stop', unsafe_second_stop)
    result = qa.update(accepted(host))
    assert not result['ok'] and result['error'] == 'update_or_rollback_failed_operator_action_required'
    assert host.live.read_bytes() == NEW
    assert not host.state[qa.GATE_UNIT] and result['ingress_verified_stopped']


def test_manual_code_rollback_preserves_rows_added_after_deployment(host):
    installed = qa.update(accepted(host))
    directory = host.backups / installed['backup_id']
    with sqlite3.connect(host.db) as db:
        db.execute("INSERT INTO video_analysis_tasks VALUES('new-task','opaque-account','channel_1',"
                   "'newhash',256,'completed','evidence_ready','2026-10-21')")
    current = host.db.read_bytes()
    recheck = lambda: qa.rollback_plan(directory)
    metadata, _ = qa.json_file(directory / 'rollback.json')
    result = qa.update(recheck(), recheck=recheck, metadata=metadata['files'])
    assert result['ok'] and host.live.read_bytes() == OLD
    assert host.db.read_bytes() == current
    with sqlite3.connect(host.db) as db:
        assert db.execute('SELECT COUNT(*) FROM video_analysis_tasks').fetchone()[0] == 2


def test_stale_rollback_cannot_overwrite_another_release(host):
    installed = qa.update(accepted(host))
    host.live.write_bytes(b'VERSION = "another-release"\n')
    with pytest.raises(qa.UpdateError, match='live_code_changed_since_backup'):
        qa.rollback_plan(host.backups / installed['backup_id'])


def test_corrupt_backup_is_rejected_before_restoring_any_file(host):
    installed = qa.update(accepted(host))
    directory = host.backups / installed['backup_id']
    (directory / RELATIVE).write_bytes(b'VERSION = "tampered-backup"\n')
    with pytest.raises(qa.UpdateError, match='backup_code_checksum_mismatch'):
        qa.rollback_plan(directory)
    assert host.live.read_bytes() == NEW


def test_failed_update_never_restores_database_even_if_protected_rows_change(host, monkeypatch):
    calls = [0]
    def unhealthy_once():
        calls[0] += 1
        if calls[0] == 1:
            with sqlite3.connect(host.db) as db:
                db.execute("UPDATE video_analysis_tasks SET byte_size=999")
            return False
        return True
    monkeypatch.setattr(qa, 'app_healthy', unhealthy_once)
    result = qa.update(accepted(host))
    assert not result['ok'] and not result['database_restored']
    assert result['ingress_verified_stopped'] and not host.state[qa.GATE_UNIT]
    assert host.live.read_bytes() == OLD
    with sqlite3.connect(host.db) as db:
        assert db.execute('SELECT byte_size FROM video_analysis_tasks').fetchone()[0] == 999


def test_manual_recovery_can_restore_code_with_backends_already_stopped(host):
    installed = qa.update(accepted(host))
    directory = host.backups / installed['backup_id']
    host.state.update({qa.APP_UNIT: False, qa.OBS_UNIT: False, qa.GATE_UNIT: False})
    metadata, _ = qa.json_file(directory / 'rollback.json')
    result = qa.update(qa.rollback_plan(directory), metadata=metadata['files'], recovery=True)
    assert result['ok'] and host.live.read_bytes() == OLD
    assert host.state[qa.APP_UNIT] and host.state[qa.OBS_UNIT]
    assert not host.state[qa.GATE_UNIT] and not result['ingress_resumed']


def test_rollback_removes_only_a_newly_introduced_module(host):
    relative = 'src/rehab_affect/demo2_observation_model.py'
    (host.stage / relative).write_bytes(NEW)
    data = json.loads(host.manifest.read_text())
    data['files'][relative] = qa.sha(NEW)
    host.manifest.write_text(json.dumps(data))
    installed = qa.update(accepted(host))
    assert (host.app / relative).exists()
    directory = host.backups / installed['backup_id']
    result = qa.update(qa.rollback_plan(directory))
    assert result['ok'] and not (host.app / relative).exists()
    assert host.live.read_bytes() == OLD


@pytest.mark.parametrize('mutation,code', [
    ('unfinished', 'accepted_backward_compatible_release_required'),
    ('wrong_hash', 'candidate_checksum_mismatch'), ('scope', 'file_outside_update_scope'),
])
def test_stage_acceptance_and_file_scope_fail_closed(host, mutation, code):
    data = json.loads(host.manifest.read_text())
    if mutation == 'unfinished':
        data['agents_finished'] = False
    elif mutation == 'wrong_hash':
        data['files'][RELATIVE] = '0' * 64
    else:
        data['files'] = {'../Windows-original.py': '0' * 64}
    host.manifest.write_text(json.dumps(data))
    with pytest.raises(qa.UpdateError, match=code):
        accepted(host)
    assert host.calls == []


def test_changing_candidate_after_validation_never_installs_it(host):
    plan = accepted(host)
    (host.stage / RELATIVE).write_bytes(b'VERSION = "unapproved"\n')
    result = qa.update(plan, recheck=lambda: accepted(host))
    assert not result['ok'] and host.live.read_bytes() == OLD
    assert host.state[qa.GATE_UNIT]


def test_missing_or_corrupt_observation_schema_cannot_be_called_idle(host):
    with sqlite3.connect(host.db) as db:
        db.execute('DROP TABLE demo2_observation_jobs')
    with pytest.raises(qa.UpdateError, match='database_or_observation_schema_unavailable'):
        qa.database_state()


def test_windows_cli_refuses_without_reading_or_changing_anything(monkeypatch, capsys):
    monkeypatch.setattr(qa.sys, 'platform', 'win32')
    monkeypatch.setattr(qa, 'inspect', lambda: pytest.fail('No Windows deployment access'))
    assert qa.main([]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result['error'] == 'linux_cloud_only'


def test_cli_errors_never_print_external_exception_text(monkeypatch, capsys):
    monkeypatch.setattr(qa.sys, 'platform', 'linux')
    def fail(**kwargs):
        raise RuntimeError('PRIVATE key/password/student')
    monkeypatch.setattr(qa, 'inspect', fail)
    assert qa.main([]) == 1
    output = capsys.readouterr()
    assert 'PRIVATE' not in output.out + output.err
    assert json.loads(output.out)['error'] == 'cloud_update_error'


def test_recent_resumable_upload_requires_explicit_flag(host, monkeypatch):
    resumable(host, monkeypatch)
    with pytest.raises(qa.UpdateError, match='cloud_work_not_idle'):
        qa.update(accepted(host))
    assert host.calls == []


def test_resumable_flag_samples_twice_each_side_and_preserves_everything(host, monkeypatch):
    partial = resumable(host, monkeypatch)
    before_db, before_bytes, before_stat = host.db.read_bytes(), partial.read_bytes(), partial.stat()
    events = []
    original = qa.resumable_upload_state
    def sample():
        events.append(('sample', host.state[qa.GATE_UNIT]))
        return original()
    monkeypatch.setattr(qa, 'resumable_upload_state', sample)
    result = qa.update(accepted(host), allow_resumable_idle_uploads=True)
    assert result['ok'] and result['resumable_idle_uploads_preserved'] == 1
    assert result['live_resume_api_called'] is result['uploads_modified'] is False
    assert events == [('sample', True)] * 2 + [('sample', False)] * 4
    assert host.db.read_bytes() == before_db and partial.read_bytes() == before_bytes
    after = partial.stat()
    assert (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) == (
        before_stat.st_ino, before_stat.st_size, before_stat.st_mtime_ns, before_stat.st_ctime_ns)
    assert host.live.read_bytes() == NEW


@pytest.mark.parametrize('case,error', [
    ('task_recent', 'upload_activity_too_recent'),
    ('chunk_recent', 'upload_chunk_activity_too_recent'),
    ('offset', 'upload_offset_inconsistent'),
    ('missing', 'upload_chunk_state_inconsistent'),
    ('conflicting', 'upload_chunk_state_inconsistent'),
    ('expired', 'upload_not_resumable'),
    ('deleted', 'upload_not_resumable'),
    ('invalid_timestamp', 'cloud_work_not_idle'),
    ('queued', 'cloud_work_not_idle'),
    ('running', 'cloud_work_not_idle'),
    ('app_socket', 'cloud_connections_not_idle'),
    ('gateway_socket', 'cloud_connections_not_idle'),
    ('accept_queue', 'cloud_connections_not_idle'),
])
def test_resumable_flag_never_skips_busy_or_invalid_uploads(host, monkeypatch, case, error):
    partial = resumable(host, monkeypatch)
    statements = {
        'task_recent': "UPDATE video_analysis_tasks SET updated_at=datetime('now','-4 minutes')",
        'offset': 'UPDATE video_analysis_tasks SET received_bytes=3',
        'expired': "UPDATE video_analysis_tasks SET expires_at=datetime('now','-1 minute')",
        'deleted': "UPDATE video_analysis_tasks SET raw_media_deleted_at='deleted'",
        'invalid_timestamp': "UPDATE video_analysis_tasks SET updated_at='private-invalid-value'",
        'queued': "UPDATE video_analysis_tasks SET analysis_status='queued'",
        'running': "UPDATE demo2_observation_jobs SET status='running'",
    }
    if case in statements:
        with sqlite3.connect(host.db) as db:
            db.execute(statements[case])
    if case == 'chunk_recent':
        monkeypatch.setattr(qa, 'time', SimpleNamespace(time=time.time))
    elif case == 'missing':
        partial.unlink()
    elif case == 'conflicting':
        Path(str(partial)[:-5]).write_bytes(b'conflict')
    elif case.endswith('socket') or case == 'accept_queue':
        key = {'app_socket': 'app_active_connections', 'gateway_socket': 'gateway_active_connections',
               'accept_queue': 'pending_accepts'}[case]
        monkeypatch.setattr(qa, 'network_state', lambda: {key: 1})
    before_db = host.db.read_bytes()
    with pytest.raises(qa.UpdateError, match=error):
        qa.update(accepted(host), allow_resumable_idle_uploads=True)
    assert host.calls == [] and host.live.read_bytes() == OLD
    assert host.db.read_bytes() == before_db


@pytest.mark.parametrize('pause_number', [1, 2, 3])
@pytest.mark.parametrize('change', ['task', 'file_size', 'file_mtime'])
def test_changing_metadata_on_either_side_of_closure_aborts_and_never_cancels(
        host, monkeypatch, pause_number, change):
    partial = resumable(host, monkeypatch)
    pauses = [0]
    def during_pause():
        pauses[0] += 1
        if pauses[0] == pause_number:
            if change == 'task':
                with sqlite3.connect(host.db) as db:
                    db.execute("UPDATE video_analysis_tasks SET updated_at=datetime('now','-14 minutes')")
            elif change == 'file_size':
                with partial.open('ab') as stream:
                    stream.write(b'new')
            else:
                info = partial.stat()
                os.utime(partial, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000_000))
    monkeypatch.setattr(qa, 'drain_pause', during_pause)
    if pause_number == 1:
        with pytest.raises(qa.UpdateError, match='resumable_upload_metadata_changed'):
            qa.update(accepted(host), allow_resumable_idle_uploads=True)
        assert host.calls == []
    else:
        result = qa.update(accepted(host), allow_resumable_idle_uploads=True)
        assert not result['ok'] and result['cause'] == 'resumable_upload_metadata_changed'
        assert host.state[qa.GATE_UNIT]
        assert ('systemctl', 'stop', qa.APP_UNIT) not in host.calls
    assert host.live.read_bytes() == OLD and not list(host.backups.iterdir())
    with sqlite3.connect(host.db) as db:
        assert db.execute('SELECT upload_status,received_bytes FROM video_analysis_tasks').fetchone() == (
            'uploading', qa.UPLOAD_CHUNK_BYTES)
    assert partial.stat().st_size == qa.UPLOAD_CHUNK_BYTES + (3 if change == 'file_size' else 0)


def test_post_start_changed_chunks_leave_ingress_closed_and_restore_code_only(host, monkeypatch):
    partial = resumable(host, monkeypatch)
    before_db = host.db.read_bytes()
    calls = [0]
    def healthy():
        calls[0] += 1
        if calls[0] == 1:
            with partial.open('ab') as stream:
                stream.write(b'new')
        return True
    monkeypatch.setattr(qa, 'app_healthy', healthy)
    result = qa.update(accepted(host), allow_resumable_idle_uploads=True)
    assert not result['ok'] and result['cause'] == 'resumable_upload_metadata_changed'
    assert result['ingress_verified_stopped'] and not host.state[qa.GATE_UNIT]
    assert host.live.read_bytes() == OLD and host.db.read_bytes() == before_db
    assert partial.stat().st_size == qa.UPLOAD_CHUNK_BYTES + 3


def test_resumable_inspection_is_metadata_only_and_sanitized(host, monkeypatch):
    partial = resumable(host, monkeypatch)
    before = host.db.read_bytes()
    original_open = Path.open
    def open_without_media_reads(path, *args, **kwargs):
        assert path != partial, 'Inspection must only stat retained media'
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', open_without_media_reads)
    result = qa.inspect(allow_resumable_idle_uploads=True)
    assert result['idle'] and result['minimum_upload_quiet_seconds'] == 300
    assert result['stable_checks_required_before_apply'] and host.calls == []
    assert 'private-synthetic' not in json.dumps(result) and str(host.db.parent) not in json.dumps(result)
    assert result['resumable_uploads'][0]['received_bytes'] == qa.UPLOAD_CHUNK_BYTES
    assert host.db.read_bytes() == before


def test_cli_forwards_explicit_resumable_inspection_flag(host, monkeypatch, capsys):
    resumable(host, monkeypatch)
    monkeypatch.setattr(qa.sys, 'platform', 'linux')
    assert qa.main(['--allow-resumable-idle-uploads']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['allow_resumable_idle_uploads'] and result['idle'] and result['read_only']
    assert host.calls == [] and not list(host.backups.iterdir())


def test_real_resume_validation_survives_update_and_manual_rollback(
        host, monkeypatch, upload_backend, make_upload_env):
    env = make_upload_env(upload_backend, name='resume-integration')
    chunk = b's' * qa.UPLOAD_CHUNK_BYTES
    task = _create(env, byte_size=len(chunk) + 123)
    _append(env, task, 0, chunk)
    raw = _raw(env, task)
    partial = Path(raw['file_path'] + '.part')
    with env.store._connect() as db:
        db.execute("UPDATE video_analysis_tasks SET updated_at=datetime('now','-15 minutes')")
        db.execute('CREATE TABLE IF NOT EXISTS demo2_observation_jobs(status TEXT)')
    monkeypatch.setattr(qa, 'DB', env.store.db_path)
    monkeypatch.setattr(qa, 'time', SimpleNamespace(time=lambda: time.time() + 600))
    payload = {key: raw[key] for key in ('task_id', 'course_id', 'byte_size')}
    payload.update(filename='synthetic.mp4', chunk_sha256=[hashlib.sha256(chunk).hexdigest()])
    token = env.tokens['school_uploader_01']
    def verify_resume():
        result = env.store.resume_video_upload(token, payload)
        assert (result['upload_status'], result['received_bytes'], result['next_chunk_index']) == (
            'uploading', len(chunk), 1)
        assert partial.read_bytes() == chunk
    verify_resume()
    before = qa.resumable_upload_state()
    installed = qa.update(accepted(host), allow_resumable_idle_uploads=True)
    assert installed['ok']
    verify_resume()
    qa.require_uploads_unchanged(before)
    directory = host.backups / installed['backup_id']
    metadata, _ = qa.json_file(directory / 'rollback.json')
    rolled_back = qa.update(qa.rollback_plan(directory), metadata=metadata['files'],
                            allow_resumable_idle_uploads=True)
    assert rolled_back['ok'] and host.live.read_bytes() == OLD
    verify_resume()
    qa.require_uploads_unchanged(before)
