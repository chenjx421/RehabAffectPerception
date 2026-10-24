"""Activate the accepted cloud pilot with preserved credentials and a rollback DB."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import pwd
import shutil
import sqlite3
import subprocess


ROOT = Path('/opt/rehabaffect')
DATA = Path('/var/lib/rehabaffect/seewo_demo2')
STAGE = Path('/var/lib/rehabaffect-migration/preseed-20261020/linux/var/lib/rehabaffect/seewo_demo2')
CONFIG = Path('/etc/rehabaffect')


def require(value, code):
    if not value:
        raise RuntimeError(code)


def run(*command):
    result = subprocess.run(command, capture_output=True, timeout=90)
    require(result.returncode == 0, 'cloud_service_command_failed')


def private_write(path, text, mode=0o600):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
        output.write(text)
        output.flush()
        os.fsync(output.fileno())
    path.chmod(mode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gateway-source', type=Path, required=True)
    parser.add_argument('--activate-pilot', action='store_true')
    args = parser.parse_args()
    require(os.geteuid() == 0 and args.activate_pilot, 'explicit_root_activation_required')
    os.umask(0o077)
    for path in (DATA, STAGE, CONFIG, args.gateway_source):
        require(path.is_absolute() and path.exists() and not path.is_symlink(), 'deployment_path_invalid')
    gateway = json.loads(args.gateway_source.read_text(encoding='utf-8-sig'))
    require(gateway['upstream_port'] == 8793 and gateway['listen_port'] == 8796
            and gateway['expires_at'] == 1793980799, 'preserved_gateway_config_required')
    require(not (CONFIG / 'cloud.env').exists() and not (CONFIG / 'gateway.json').exists(),
            'existing_pilot_configuration_refused')
    database = DATA / 'rehab_affect_demo2.sqlite3'
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        require(db.execute("SELECT COUNT(*) FROM video_analysis_tasks WHERE analysis_status IN ('queued','processing')").fetchone()[0] == 0,
                'active_media_jobs_refused')
        require(db.execute('PRAGMA quick_check').fetchone() == ('ok',), 'database_check_failed')
        account_count = db.execute('SELECT COUNT(*) FROM platform_accounts').fetchone()[0]
        task_count = db.execute('SELECT COUNT(*) FROM video_analysis_tasks').fetchone()[0]
        require(account_count == 5 and task_count >= 44, 'preserved_baseline_required')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = Path('/var/lib/rehabaffect/cloud_backups') / ('before-pilot-' + stamp)
    backup.mkdir(mode=0o700, parents=True, exist_ok=False)
    run('systemctl', 'stop', 'rehabaffect-preview.service')
    activated = False
    try:
        with closing(sqlite3.connect(database)) as db, closing(sqlite3.connect(backup / 'database.sqlite3')) as target:
            db.backup(target)
        shutil.copyfile(CONFIG / 'preview.env', backup / 'preview.env')
        with closing(sqlite3.connect(database)) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('ATTACH DATABASE ? AS original', ((STAGE / database.name).as_uri() + '?mode=ro',))
            db.execute('BEGIN IMMEDIATE')
            # Restore pre-acceptance organization metadata, never placeholder schools.
            for table in ('school_contexts', 'school_selection_metadata'):
                current = db.execute('PRAGMA main.table_info(' + table + ')').fetchall()
                original = db.execute('PRAGMA original.table_info(' + table + ')').fetchall()
                require(current == original, 'organization_schema_changed')
                db.execute('DELETE FROM main.' + table)
                db.execute('INSERT INTO main.' + table + ' SELECT * FROM original.' + table)
            db.commit()
        values = {}
        for line in (CONFIG / 'preview.env').read_text().splitlines():
            if line and not line.startswith('#'):
                key, value = line.split('=', 1)
                values[key] = value
        values.update(TZ='Asia/Shanghai', REHAB_DEMO2_MEDIA_WORKER='1', CLOUD_MIGRATION_APPROVED='yes',
                      CLOUD_MIN_ACCOUNT_COUNT='5', CLOUD_MIN_TASK_COUNT='44', PYTHONDONTWRITEBYTECODE='1')
        values.pop('CLOUD_PREVIEW_ONLY', None)
        private_write(CONFIG / 'cloud.env', ''.join(key + '=' + value + '\n' for key, value in values.items()))
        try:
            identity = pwd.getpwnam('rehabaffect-gateway')
        except KeyError:
            run('useradd', '--system', '--no-create-home', '--shell', '/usr/sbin/nologin', 'rehabaffect-gateway')
            identity = pwd.getpwnam('rehabaffect-gateway')
        os.chown(CONFIG, 0, identity.pw_gid)
        CONFIG.chmod(0o710)
        private_write(CONFIG / 'gateway.json', json.dumps(gateway), mode=0o640)
        os.chown(CONFIG / 'gateway.json', 0, identity.pw_gid)
        for name in ('rehabaffect-app.service', 'rehabaffect-gateway.service'):
            shutil.copyfile(ROOT / 'deploy/cloud' / name, Path('/etc/systemd/system') / name)
        run('systemctl', 'daemon-reload')
        run('systemctl', 'disable', 'rehabaffect-preview.service')
        run('systemctl', 'enable', '--now', 'rehabaffect-app.service')
        run('systemctl', 'enable', '--now', 'rehabaffect-gateway.service')
        run('systemctl', 'is-active', 'rehabaffect-app.service', 'rehabaffect-gateway.service')
        activated = True
        print(json.dumps({'ok': True, 'accounts_preserved': account_count, 'tasks_preserved': task_count,
            'school_placeholders_removed': True, 'gateway_secret_preserved': True,
            'expires_at': gateway['expires_at'], 'backup': str(backup), 'public_ingress_switched': False}))
    finally:
        if not activated:
            # Keep new configuration private for diagnosis; resume the accepted preview.
            subprocess.run(['systemctl', 'stop', 'rehabaffect-gateway.service', 'rehabaffect-app.service'],
                           capture_output=True, timeout=90)
            subprocess.run(['systemctl', 'start', 'rehabaffect-preview.service'], capture_output=True, timeout=90)


if __name__ == '__main__':
    main()
