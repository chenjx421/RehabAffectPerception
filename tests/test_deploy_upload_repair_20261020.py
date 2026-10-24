import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import deploy_upload_repair_20261020 as deploy


@pytest.fixture
def rig(tmp_path, monkeypatch):
    events = []
    flags = {'connections': False, 'tasks': False}

    class Process:
        def __init__(self, pid, module):
            self.pid, self.module, self.alive = pid, module, True
            self.info = {'cmdline': ['pythonw.exe', module]}
            self.on_wait = lambda: None

        def cmdline(self):
            return ['pythonw.exe', self.module]

        def environ(self):
            return {'SYNTHETIC_SECRET': 'do-not-log'}

        def exe(self):
            return 'C:/synthetic/pythonw.exe'

        def name(self):
            return 'cloudflared.exe' if self.pid == 4 else 'pythonw.exe'

        def is_running(self):
            return self.alive

        def create_time(self):
            return self.pid * 100

        def terminate(self):
            events.append(('terminate', self.pid))
            self.alive = False

        def wait(self, timeout):
            events.append(('wait', self.pid))
            self.on_wait()

        def poll(self):
            return None if self.alive else 1

    keeper = Process(1, 'keep_demo_test_online_20261014.py')
    app = Process(2, 'src.rehab_affect.scenario_lab_server')
    gateway = Process(3, 'src.rehab_affect.demo2_manager_gateway')
    tunnel = Process(4, 'cloudflared')
    processes = {p.pid: p for p in (keeper, app, gateway, tunnel)}
    spawned = []

    def connections(**kwargs):
        events.append(('connections',))
        rows = [SimpleNamespace(laddr=SimpleNamespace(port=port), pid=p.pid, status=deploy.psutil.CONN_LISTEN)
                for port, p in ((8793, app), (8796, gateway)) if p.alive]
        if flags['connections']:
            rows.append(SimpleNamespace(laddr=SimpleNamespace(port=8793), pid=2,
                                        status=deploy.psutil.CONN_ESTABLISHED))
        return rows

    def tasks():
        events.append(('tasks',))
        return int(flags['tasks'])

    def spawn(command, **kwargs):
        assert kwargs['env'] == {'SYNTHETIC_SECRET': 'do-not-log'}
        assert command[0] == keeper.exe()
        assert command[1].endswith('keep_demo_test_online_20261014.py')
        child = Process(10 + len(spawned), 'keep_demo_test_online_20261014.py')
        spawned.append(child)
        processes[child.pid] = child
        events.append(('spawn', child.pid))
        return child

    monkeypatch.setattr(deploy, 'ROOT', tmp_path)
    monkeypatch.setattr(deploy, 'RUNTIME', tmp_path)
    monkeypatch.setattr(deploy, 'DB', tmp_path / 'unused.sqlite3')
    monkeypatch.setattr(deploy, 'active_tasks', tasks)
    monkeypatch.setattr(deploy, 'backup', Mock(side_effect=lambda *args: events.append(('backup',))))
    monkeypatch.setattr(deploy.psutil, 'net_connections', connections)
    monkeypatch.setattr(deploy.psutil, 'Process', lambda pid: processes[pid])
    monkeypatch.setattr(deploy.psutil, 'process_iter', lambda *args:
                        [p for p in processes.values() if p.alive and p.module.endswith('.py')])
    monkeypatch.setattr(deploy.subprocess, 'Popen', Mock(side_effect=spawn))
    monkeypatch.setattr(deploy.subprocess, 'CREATE_NO_WINDOW', 0, raising=False)
    monkeypatch.setattr(deploy.time, 'time', lambda: 1000)
    monkeypatch.setattr(deploy.time, 'sleep', lambda seconds: None)
    monkeypatch.setattr(sys, 'argv', ['deploy', '--apply'])
    config = {'expires_at': 2000, 'upstream_port': 8793, 'listen_port': 8796, 'secret': 'synthetic'}
    share = {'tunnel_pid': 4, 'gateway_pid': 3, 'origin': 'https://synthetic.example', 'expires_at': 2000}
    originals = {}
    for name, value in [('config', config), ('state', share)]:
        path = tmp_path / f'manager_share_{name}.json'
        path.write_text(json.dumps(value), encoding='utf-8')
        originals[path] = path.read_bytes()
    yield SimpleNamespace(keeper=keeper, app=app, gateway=gateway, tunnel=tunnel,
                          spawned=spawned, events=events, flags=flags, spawn=spawn)
    assert tunnel.alive
    assert ('terminate', 4) not in events
    assert all(path.read_bytes() == data for path, data in originals.items())


def test_success_rechecks_after_keeper_and_stops_gateway_before_app(rig, capsys):
    deploy.main()
    assert [event for event in rig.events if event[0] == 'terminate'] == [
        ('terminate', 1), ('terminate', 3), ('terminate', 2)]
    for first, second in [(('wait', 1), ('terminate', 3)), (('wait', 3), ('terminate', 2))]:
        between = rig.events[rig.events.index(first) + 1:rig.events.index(second)]
        assert ('tasks',) in between and ('connections',) in between
    output = json.loads(capsys.readouterr().out)
    assert output['health_verified'] is False and output['tunnel_preserved'] is True
    assert len(rig.spawned) == 1


@pytest.mark.parametrize('kind', ['connections', 'tasks'])
def test_new_activity_after_keeper_stop_aborts_before_service_stop_and_restores_keeper(rig, kind):
    rig.keeper.on_wait = lambda: rig.flags.__setitem__(kind, True)
    with pytest.raises(deploy.DeploymentFailed) as error:
        deploy.main()
    assert error.value.recovery['status'] == 'keeper_recovery_dispatched'
    assert rig.app.alive and rig.gateway.alive and len(rig.spawned) == 1


@pytest.mark.parametrize('kind', ['connections', 'tasks'])
def test_activity_after_gateway_stop_preserves_app_and_recovers_supervisor(rig, kind):
    rig.gateway.on_wait = lambda: rig.flags.__setitem__(kind, True)
    with pytest.raises(deploy.DeploymentFailed) as error:
        deploy.main()
    assert error.value.recovery['status'] == 'keeper_recovery_dispatched'
    assert rig.app.alive and not rig.gateway.alive and len(rig.spawned) == 1


@pytest.mark.parametrize('service', ['keeper', 'gateway', 'app'])
def test_wait_timeout_after_termination_restores_keeper(rig, service):
    def fail():
        raise deploy.psutil.TimeoutExpired(10)

    getattr(rig, service).on_wait = fail
    with pytest.raises(deploy.DeploymentFailed) as error:
        deploy.main()
    assert error.value.recovery['status'] == 'keeper_recovery_dispatched'
    assert len(rig.spawned) == 1


def test_keeper_termination_failure_does_not_start_duplicate_or_stop_services(rig, monkeypatch):
    monkeypatch.setattr(rig.keeper, 'terminate', Mock(side_effect=deploy.psutil.AccessDenied(1)))
    with pytest.raises(deploy.DeploymentFailed) as error:
        deploy.main()
    assert error.value.recovery['status'] == 'original_keeper_present'
    assert rig.app.alive and rig.gateway.alive and not rig.spawned


@pytest.mark.parametrize('recovery_succeeds', [True, False])
def test_start_failure_retries_once_and_reports_recovery_failure_safely(rig, monkeypatch, recovery_succeeds):
    calls = [0]

    def start(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 1 or not recovery_succeeds:
            raise OSError('synthetic-secret-must-not-escape')
        return rig.spawn(*args, **kwargs)

    monkeypatch.setattr(deploy.subprocess, 'Popen', start)
    with pytest.raises(deploy.DeploymentFailed) as error:
        deploy.main()
    assert calls[0] == 2
    assert str(error.value) == 'deployment_step_failed'
    assert error.value.recovery['status'] == (
        'keeper_recovery_dispatched' if recovery_succeeds else 'keeper_recovery_failed_manual_recovery')
    assert 'secret' not in json.dumps(error.value.recovery)


def test_service_replacement_after_backup_is_not_terminated(rig, monkeypatch):
    original = deploy.idle_services
    calls = [0]

    def changed(expected):
        current = original(expected)
        calls[0] += 1
        if calls[0] == 4:
            current[8796] = SimpleNamespace(pid=99)
        return current

    monkeypatch.setattr(deploy, 'idle_services', changed)
    with pytest.raises(deploy.DeploymentFailed, match='service_changed_refuse_restart'):
        deploy.main()
    assert rig.app.alive and rig.gateway.alive and len(rig.spawned) == 1


def test_active_tasks_after_backup_abort_without_stopping_keeper(rig, monkeypatch):
    monkeypatch.setattr(deploy, 'backup', lambda *args: rig.flags.__setitem__('tasks', True))
    with pytest.raises(deploy.DeploymentRefused, match='new_active_task_refuse_restart'):
        deploy.main()
    assert rig.keeper.alive and rig.app.alive and rig.gateway.alive and not rig.spawned


def test_apply_flag_required_before_runtime_reads_or_process_operations(rig, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['deploy'])
    with pytest.raises(deploy.DeploymentRefused, match='explicit_apply_required'):
        deploy.main()
    assert rig.events == []
