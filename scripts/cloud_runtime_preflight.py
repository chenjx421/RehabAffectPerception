"""Fail-closed service checks. No seeding, migrations, downloads or secret output.

These checks do not replace a restored-data acceptance run or migration approval.
Only the prepared Linux systemd units use this entry point; Windows is unchanged.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import importlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import time
from typing import Mapping


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path('/var/lib/rehabaffect/seewo_demo2')
GATEWAY_CONFIG = Path('/etc/rehabaffect/gateway.json')


class PreflightError(RuntimeError):
    """Only internal fixed codes, never paths or provider messages."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise PreflightError(code)


def local_path(path: Path, *, directory: bool = False) -> Path:
    require(path.is_absolute() and '..' not in path.parts
            and not str(path).startswith(('\\\\', '//')), 'local_absolute_path_required')
    for parent in reversed((path, *path.parents)):
        info = parent.lstat()
        require(not stat.S_ISLNK(info.st_mode)
                and not getattr(info, 'st_file_attributes', 0) & 0x400,
                'symlink_or_reparse_point_refused')
        is_dir = parent != path or directory
        require(stat.S_ISDIR(info.st_mode) if is_dir else stat.S_ISREG(info.st_mode),
                'regular_local_path_required')
    return path


def _positive_count(env: Mapping[str, str], key: str) -> int:
    value = env.get(key, '')
    require(value.isascii() and value.isdecimal() and 0 < len(value) <= 12,
            'preserved_database_baseline_required')
    count = int(value)
    require(count > 0, 'preserved_database_baseline_required')
    return count


def check_database(env: Mapping[str, str], *, data_root: Path = DATA_ROOT) -> dict:
    require(env.get('CLOUD_MIGRATION_APPROVED') == 'yes', 'migration_not_approved')
    db = Path(env.get('REHAB_DEMO2_DB_PATH', ''))
    uploads = Path(env.get('REHAB_DEMO2_UPLOAD_DIR', ''))
    require(db == data_root / 'rehab_affect_demo2.sqlite3', 'database_root_mismatch')
    require(uploads == data_root / 'student_documents', 'upload_root_mismatch')
    local_path(db)
    local_path(uploads, directory=True)
    require(db.stat().st_size > 0, 'preserved_database_required')
    minimum_accounts = _positive_count(env, 'CLOUD_MIN_ACCOUNT_COUNT')
    minimum_tasks = _positive_count(env, 'CLOUD_MIN_TASK_COUNT')
    # Never use a store constructor here: it can create tables and seed accounts.
    with closing(sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=5)) as conn:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        require(conn.execute('PRAGMA quick_check').fetchone() == ('ok',),
                'database_integrity_failed')
        require(conn.execute('PRAGMA foreign_key_check').fetchone() is None,
                'database_foreign_keys_failed')
        accounts = conn.execute('SELECT COUNT(*) FROM platform_accounts').fetchone()[0]
        tasks = conn.execute('SELECT COUNT(*) FROM video_analysis_tasks').fetchone()[0]
        require(accounts >= minimum_accounts, 'account_baseline_failed')
        require(tasks >= minimum_tasks, 'task_baseline_failed')
    return {'database_checked_read_only': True, 'accounts': accounts, 'tasks': tasks}


def check_runtime(env: Mapping[str, str], *, project_root: Path = ROOT) -> dict:
    require(env.get('TZ') == 'Asia/Shanghai', 'timezone_required')
    require(env.get('REHAB_DEMO2_MEDIA_WORKER') == '1', 'single_media_worker_required')
    try:
        numpy = importlib.import_module('numpy')
        cv2 = importlib.import_module('cv2')
        fernet = importlib.import_module('cryptography.fernet')
        require(hasattr(numpy, 'frombuffer') and hasattr(cv2, 'FaceDetectorYN_create'),
                'runtime_dependency_incompatible')
    except (ImportError, OSError):
        raise PreflightError('runtime_dependency_unavailable') from None
    try:
        key = env.get('REHAB_DEMO2_DOSSIER_KEY', '').encode('ascii')
        fernet.Fernet(key)
    except (ValueError, TypeError, UnicodeError):
        raise PreflightError('migrated_vault_key_required') from None
    for name in ('REHAB_FFMPEG', 'REHAB_FFPROBE'):
        executable = Path(env.get(name, ''))
        require(executable.is_absolute() and executable.is_file()
                and os.access(executable, os.X_OK), 'media_tool_unavailable')
    # The face module's validator is pure; importing it never initializes a DB.
    from src.rehab_affect.demo2_face_detection import MODEL_NAME, _validate_model
    model = project_root / 'models' / MODEL_NAME
    local_path(model)
    require(_validate_model(model) is None, 'face_model_integrity_failed')
    return {'dependencies_available': True, 'face_model_integrity_checked': True,
            'vault_key_format_checked': True, 'media_binaries_present': True,
            'media_decode_requires_smoke_test': True,
            'existing_vault_decryption_requires_migration_acceptance': True}


def check_gateway(env: Mapping[str, str], *, config: Path = GATEWAY_CONFIG,
                  now: float | None = None) -> dict:
    require(env.get('CLOUD_MIGRATION_APPROVED') == 'yes', 'migration_not_approved')
    local_path(config)
    require(0 < config.stat().st_size <= 32768, 'gateway_config_size_invalid')
    if os.name == 'posix':
        mode = stat.S_IMODE(config.stat().st_mode)
        require(mode in (0o600, 0o640) and config.stat().st_uid == 0,
                'gateway_config_permissions_invalid')
    from src.rehab_affect.demo2_manager_gateway import load_config
    try:
        value = load_config(config)
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise PreflightError('gateway_config_invalid') from None
    require(value.upstream_port == 8793 and value.listen_port == 8796,
            'gateway_ports_mismatch')
    require(value.expires_at > (time.time() if now is None else now), 'invitation_expired')
    return {'gateway_config_checked': True, 'invitation_not_expired': True,
            'public_tls_requires_separate_acceptance': True}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('service', choices=('app', 'gateway'))
    args = parser.parse_args(argv)
    try:
        if args.service == 'app':
            report = check_database(os.environ)
            report.update(check_runtime(os.environ))
        else:
            report = check_gateway(os.environ)
        print(json.dumps({'ok': True, **report}, sort_keys=True))
        return 0
    except PreflightError as exc:
        code = str(exc)
    except sqlite3.Error:
        code = 'database_unavailable_or_schema_invalid'
    except (OSError, ValueError, TypeError, ImportError):
        code = 'required_runtime_resource_unavailable'
    except Exception:
        code = 'unexpected_preflight_failure'
    print(json.dumps({'ok': False, 'code': code}), file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main())
