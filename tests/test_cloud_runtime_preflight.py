"""Cloud gates use synthetic files only; never open the school's database."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from scripts import cloud_runtime_preflight as cloud


@pytest.fixture
def preserved(tmp_path):
    db = tmp_path / 'rehab_affect_demo2.sqlite3'
    uploads = tmp_path / 'student_documents'
    uploads.mkdir()
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute('CREATE TABLE platform_accounts (id INTEGER PRIMARY KEY, secret TEXT)')
        conn.execute("INSERT INTO platform_accounts VALUES (1, 'never-print-me')")
        conn.execute('CREATE TABLE video_analysis_tasks (id INTEGER PRIMARY KEY)')
        conn.execute('INSERT INTO video_analysis_tasks VALUES (1)')
    env = {'CLOUD_MIGRATION_APPROVED': 'yes', 'CLOUD_MIN_ACCOUNT_COUNT': '1',
           'CLOUD_MIN_TASK_COUNT': '1', 'REHAB_DEMO2_DB_PATH': str(db),
           'REHAB_DEMO2_UPLOAD_DIR': str(uploads)}
    return tmp_path, db, env


def test_database_gate_is_read_only(preserved):
    root, db, env = preserved
    before = db.read_bytes()
    result = cloud.check_database(env, data_root=root)
    assert result == {'database_checked_read_only': True, 'accounts': 1, 'tasks': 1}
    assert db.read_bytes() == before
    assert 'never-print-me' not in json.dumps(result)


def test_missing_db_never_creates_an_empty_site(preserved):
    root, db, env = preserved
    db.unlink()
    with pytest.raises(OSError):
        cloud.check_database(env, data_root=root)
    assert not db.exists()


@pytest.mark.parametrize('value', ['', '0', '-1', 'not-a-number', '1.0', '9' * 20])
def test_baseline_required(preserved, value):
    root, _, env = preserved
    env['CLOUD_MIN_ACCOUNT_COUNT'] = value
    with pytest.raises(cloud.PreflightError, match='preserved_database_baseline_required'):
        cloud.check_database(env, data_root=root)


def test_manual_approval_required_before_any_db_access():
    with pytest.raises(cloud.PreflightError, match='migration_not_approved'):
        cloud.check_database({})


def test_optimization_cannot_disable_gate():
    env = dict(os.environ, CLOUD_MIGRATION_APPROVED='no')
    result = subprocess.run([sys.executable, '-O', str(cloud.ROOT / 'scripts/cloud_runtime_preflight.py'),
                             'app'], env=env, capture_output=True, text=True, timeout=15)
    assert result.returncode == 1
    assert json.loads(result.stderr) == {'ok': False, 'code': 'migration_not_approved'}


@pytest.mark.parametrize('key,expected', [('CLOUD_MIN_ACCOUNT_COUNT', 'account_baseline_failed'),
                                         ('CLOUD_MIN_TASK_COUNT', 'task_baseline_failed')])
def test_incomplete_restore_refused(preserved, key, expected):
    root, _, env = preserved
    env[key] = '2'
    with pytest.raises(cloud.PreflightError, match=expected):
        cloud.check_database(env, data_root=root)


def test_foreign_key_corruption_refused(preserved):
    root, db, env = preserved
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute('CREATE TABLE reference (account_id INTEGER REFERENCES platform_accounts(id))')
        conn.execute('INSERT INTO reference VALUES (99)')
    with pytest.raises(cloud.PreflightError, match='database_foreign_keys_failed'):
        cloud.check_database(env, data_root=root)


def test_wrong_data_directory_refused(preserved):
    root, _, env = preserved
    env['REHAB_DEMO2_UPLOAD_DIR'] = str(root / 'other')
    with pytest.raises(cloud.PreflightError, match='upload_root_mismatch'):
        cloud.check_database(env, data_root=root)


def test_reparse_points_refused_without_needing_windows_link_privilege(monkeypatch, tmp_path):
    target = tmp_path / 'data'
    target.write_bytes(b'data')
    original = Path.lstat

    def pretend_link(path):
        info = original(path)
        if path == target:
            class Linked:
                st_mode = info.st_mode
                st_file_attributes = 0x400
            return Linked()
        return info

    monkeypatch.setattr(Path, 'lstat', pretend_link)
    with pytest.raises(cloud.PreflightError, match='symlink_or_reparse_point_refused'):
        cloud.local_path(target)


@pytest.fixture
def gateway(tmp_path):
    path = tmp_path / 'gateway.json'
    value = {'invite_secret': 'x' * 40, 'cookie_secret': 'y' * 40,
             'expires_at': 2000000000, 'upstream_port': 8793, 'listen_port': 8796}
    path.write_text(json.dumps(value), encoding='utf-8')
    path.chmod(0o600)
    return path, value


def _gateway_ownership(monkeypatch, path):
    # Real service files must be root-owned on Linux; unit fixtures need no sudo.
    if os.name != 'posix':
        return
    original = Path.stat

    def owned(p, *args, **kwargs):
        info = original(p, *args, **kwargs)
        if p == path:
            class Owned:
                st_mode, st_size, st_uid = info.st_mode, info.st_size, 0
            return Owned()
        return info

    monkeypatch.setattr(Path, 'stat', owned)


def test_gateway_preserves_secrets_and_expiry(gateway, monkeypatch):
    path, _ = gateway
    _gateway_ownership(monkeypatch, path)
    before = path.read_bytes()
    result = cloud.check_gateway({'CLOUD_MIGRATION_APPROVED': 'yes'}, config=path, now=1900000000)
    assert result['invitation_not_expired'] is True
    assert path.read_bytes() == before
    assert 'xxxxxxxx' not in json.dumps(result)


@pytest.mark.parametrize('field,value,code', [
    ('expires_at', 1, 'invitation_expired'),
    ('upstream_port', 8792, 'gateway_ports_mismatch'),
    ('invite_secret', 'short', 'gateway_config_invalid'),
])
def test_gateway_bad_configuration_refused(gateway, monkeypatch, field, value, code):
    path, config = gateway
    config[field] = value
    path.write_text(json.dumps(config), encoding='utf-8')
    _gateway_ownership(monkeypatch, path)
    with pytest.raises(cloud.PreflightError, match=code):
        cloud.check_gateway({'CLOUD_MIGRATION_APPROVED': 'yes'}, config=path, now=1900000000)


def test_cli_error_never_echoes_exception_payload(monkeypatch, capsys):
    def bad(_):
        raise OSError('sensitive-student-record-or-credential')
    monkeypatch.setattr(cloud, 'check_database', bad)
    assert cloud.main(['app']) == 1
    assert json.loads(capsys.readouterr().err) == {
        'ok': False, 'code': 'required_runtime_resource_unavailable'}


def test_service_templates_use_tested_entrypoint():
    app = (cloud.ROOT / 'deploy/cloud/rehabaffect-app.service').read_text()
    gateway = (cloud.ROOT / 'deploy/cloud/rehabaffect-gateway.service').read_text()
    assert 'scripts/cloud_runtime_preflight.py app' in app
    assert 'scripts/cloud_runtime_preflight.py gateway' in gateway
    assert 'python -c' not in app + gateway
    assert 'assert ' not in app + gateway
