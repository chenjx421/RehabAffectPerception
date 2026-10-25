"""Reload idle app/gateway/keeper, retaining the keeper environment and tunnel."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import time

import psutil

if __package__:
    from .maintain_school_pilot import backup
else:
    from maintain_school_pilot import backup

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'
DB = ROOT / 'outputs/seewo_demo2/rehab_affect_demo2.sqlite3'


class DeploymentRefused(RuntimeError):
    """Fixed, non-secret guard code."""


class DeploymentFailed(DeploymentRefused):
    def __init__(self, code, recovery):
        super().__init__(code)
        self.recovery = recovery


def require(value, code):
    if not value:
        raise DeploymentRefused(code)


def active_tasks():
    with sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True) as conn:
        return conn.execute("""SELECT COUNT(*) FROM video_analysis_tasks
            WHERE analysis_status IN ('queued','processing') OR
            (upload_status='uploading' AND julianday(updated_at)>julianday('now','-3 minutes'))""").fetchone()[0]


def find_keepers():
    keepers = []
    for process in psutil.process_iter(['pid', 'name', 'cmdline']):
        argv = process.info['cmdline'] or []
        if any(Path(arg).name == 'keep_demo_test_online_20261014.py' for arg in argv[1:]):
            keepers.append(process)
    return keepers


def idle_services(expected):
    connections = [c for c in psutil.net_connections(kind='tcp') if c.laddr and c.laddr.port in expected]
    require(not any(c.status == psutil.CONN_ESTABLISHED for c in connections), 'active_requests_refuse_restart')
    listeners = [c for c in connections if c.status == psutil.CONN_LISTEN]
    require(len(listeners) == len(expected) and {c.laddr.port for c in listeners} == set(expected),
            'listeners_missing_or_ambiguous')
    services = {}
    for connection in listeners:
        process = psutil.Process(connection.pid)
        require(expected[connection.laddr.port] in process.cmdline(), 'unexpected_service_process')
        services[connection.laddr.port] = process
    require(active_tasks() == 0, 'active_tasks_refuse_restart')
    return services


def require_same_services(current, original):
    require(all(current[port].pid == process.pid and current[port].create_time() == process.create_time()
                and process.is_running() for port, process in original.items()), 'service_changed_refuse_restart')


def start_keeper(executable, environment):
    with (RUNTIME / 'keeper_upload_repair_20261020.log').open('ab') as log:
        return subprocess.Popen([executable, str(ROOT / 'scripts/keep_demo_test_online_20261014.py')],
                                cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                                stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)


def recover_keeper(keeper, child, executable, environment):
    # Never duplicate a surviving keeper, and never stop another service to recover.
    try:
        if child is not None and child.poll() is None:
            return {'status': 'replacement_keeper_present', 'pid': child.pid}
        if keeper.is_running():
            return {'status': 'original_keeper_present', 'pid': keeper.pid}
        existing = find_keepers()
        if existing:
            return {'status': 'existing_keeper_present' if len(existing) == 1 else 'multiple_keepers_manual_recovery'}
        child = start_keeper(executable, environment)
        if child.poll() is not None:
            return {'status': 'keeper_exited_manual_recovery'}
        return {'status': 'keeper_recovery_dispatched', 'pid': child.pid}
    except Exception:
        return {'status': 'keeper_recovery_failed_manual_recovery'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    require(args.apply, 'explicit_apply_required')
    config = json.loads((RUNTIME / 'manager_share_config.json').read_text(encoding='utf-8-sig'))
    share = json.loads((RUNTIME / 'manager_share_state.json').read_text(encoding='utf-8-sig'))
    require(config['expires_at'] > time.time(), 'invitation_expired')
    expected = {config['upstream_port']: 'src.rehab_affect.scenario_lab_server',
                config['listen_port']: 'src.rehab_affect.demo2_manager_gateway'}
    keepers = find_keepers()
    require(len(keepers) == 1, 'keeper_not_unique')
    keeper = keepers[0]
    environment = keeper.environ()
    executable = keeper.exe()
    require(Path(executable).name.lower() == 'pythonw.exe', 'unexpected_keeper_runtime')
    services = {}
    for _ in range(3):
        current = idle_services(expected)
        if services:
            require_same_services(current, services)
        services = current
        time.sleep(2)
    tunnel = psutil.Process(share['tunnel_pid'])
    require(tunnel.name().lower() == 'cloudflared.exe' and tunnel.is_running(), 'tunnel_not_running')
    tunnel_started = tunnel.create_time()
    snapshot = RUNTIME / ('upload_predeploy_' + time.strftime('%Y%m%d_%H%M%S'))
    backup(DB, RUNTIME / 'manager_share_config.json', RUNTIME / 'manager_share_state.json', snapshot)
    require(active_tasks() == 0, 'new_active_task_refuse_restart')
    child = None
    try:
        keeper.terminate()
        keeper.wait(timeout=10)
        require(not find_keepers(), 'keeper_replaced_refuse_restart')
        require_same_services(idle_services(expected), services)
        gateway = services[config['listen_port']]
        gateway.terminate()
        gateway.wait(timeout=10)
        # Close public ingress first, then recheck work accepted during the final gate.
        require(not any(c.laddr and c.laddr.port == config['listen_port'] and c.status == psutil.CONN_LISTEN
                        for c in psutil.net_connections(kind='tcp')), 'gateway_replaced_refuse_restart')
        app_port = config['upstream_port']
        require_same_services(idle_services({app_port: expected[app_port]}), {app_port: services[app_port]})
        services[app_port].terminate()
        services[app_port].wait(timeout=10)
        require(not find_keepers(), 'keeper_replaced_refuse_restart')
        child = start_keeper(executable, environment)
        require(child.poll() is None, 'replacement_keeper_exited')
        require(tunnel.is_running() and tunnel.create_time() == tunnel_started, 'tunnel_changed')
    except Exception as exc:
        recovery = recover_keeper(keeper, child, executable, environment)
        code = str(exc) if isinstance(exc, DeploymentRefused) else 'deployment_step_failed'
        raise DeploymentFailed(code, recovery) from None
    print(json.dumps({'keeper_started': child.pid, 'tunnel_preserved': True,
                      'credentials_changed': False, 'backup': snapshot.name, 'health_verified': False}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Neither environment nor configuration values belong in an error log.
        print(json.dumps({'deployment': 'not_confirmed', 'error_type': type(exc).__name__,
                          'check': str(exc) if isinstance(exc, DeploymentRefused) else 'inspect_private_runtime',
                          'recovery': exc.recovery if isinstance(exc, DeploymentFailed) else None}))
        raise SystemExit(1)
