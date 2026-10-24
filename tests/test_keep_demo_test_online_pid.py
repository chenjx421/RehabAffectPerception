import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts import keep_demo_test_online_20261014 as keeper


@pytest.fixture
def setup(tmp_path, monkeypatch):
    config = {'invite_secret': 'synthetic-invite', 'cookie_secret': 'synthetic-cookie',
              'listen_port': 8796, 'upstream_port': 8793, 'expires_at': 2000}
    state = {'gateway_pid': 10, 'origin': 'https://synthetic.example', 'expires_at': 2000,
             'invite_url': 'https://synthetic.example/invite#synthetic-invite',
             'tunnel_pid': 30, 'metrics_port': 20246, 'future_key': {'preserve': True}}
    for name, value in [('config', config), ('state', state)]:
        (tmp_path / f'manager_share_{name}.json').write_text(json.dumps(value), encoding='utf-8')
    monkeypatch.setattr(keeper.time, 'time', lambda: 1000)
    monkeypatch.setattr(keeper, 'healthy', lambda *args: True)
    monkeypatch.setattr(keeper, 'gateway_listener_pid', lambda port: 20)
    monkeypatch.setattr(keeper.maintenance, 'protect', lambda path: None)
    process = SimpleNamespace(pid=20, poll=Mock(return_value=None))
    return tmp_path, state, process, keeper.gateway_state_baseline(tmp_path)


def test_sync_changes_only_pid_and_protects_temporary_before_write(setup, monkeypatch):
    root, original, process, baseline = setup
    config_before = (root / 'manager_share_config.json').read_bytes()
    protected = []

    def protect(path):
        assert path.stat().st_size == 0
        protected.append(path)

    monkeypatch.setattr(keeper.maintenance, 'protect', protect)
    assert keeper.sync_gateway_pid(root, process, 8796, baseline) == 'synced'
    assert json.loads((root / 'manager_share_state.json').read_text()) == original | {'gateway_pid': 20}
    assert (root / 'manager_share_config.json').read_bytes() == config_before
    assert len(protected) == 1 and not list(root.glob('*.tmp'))
    assert keeper.sync_gateway_pid(root, process, 8796, baseline) == 'synced'
    assert len(protected) == 1


@pytest.mark.parametrize('condition,expected', [
    ('unhealthy', 'waiting_for_listener'), ('other_listener', 'waiting_for_listener'),
    ('exited', 'process_exited'), ('no_baseline', 'state_unavailable'),
    ('other_pid', 'state_changed'), ('other_origin', 'state_changed'),
    ('expired', 'state_changed'), ('other_port', 'state_changed'),
    ('invalid_json', 'state_update_refused'),
])
def test_refuses_unsafe_sync_without_writing(setup, monkeypatch, condition, expected):
    root, state, process, baseline = setup
    path = root / 'manager_share_state.json'
    if condition == 'unhealthy':
        monkeypatch.setattr(keeper, 'healthy', lambda *args: False)
    elif condition == 'other_listener':
        monkeypatch.setattr(keeper, 'gateway_listener_pid', lambda port: 99)
    elif condition == 'exited':
        process.poll.return_value = 1
    elif condition == 'no_baseline':
        baseline = None
    elif condition == 'other_pid':
        state['gateway_pid'] = 99
    elif condition == 'other_origin':
        state['origin'] = 'https://replacement.example'
        state['invite_url'] = state['origin'] + '/invite#synthetic-invite'
    elif condition == 'expired':
        state['expires_at'] = 999
    path.write_text(json.dumps(state), encoding='utf-8')
    if condition == 'invalid_json':
        path.write_text('{', encoding='utf-8')
    before = path.read_bytes()
    assert keeper.sync_gateway_pid(root, process, 9999 if condition == 'other_port' else 8796, baseline) == expected
    assert path.read_bytes() == before
    assert not list(root.glob('*.tmp'))


def test_concurrent_update_is_not_overwritten(setup, monkeypatch):
    root, state, process, baseline = setup
    target = root / 'manager_share_state.json'
    original_write = keeper.maintenance.private_write
    changed = state | {'gateway_pid': 99, 'future_key': {'updated': True}}

    def competing_write(path, data):
        original_write(path, data)
        target.write_text(json.dumps(changed), encoding='utf-8')

    monkeypatch.setattr(keeper.maintenance, 'private_write', competing_write)
    assert keeper.sync_gateway_pid(root, process, 8796, baseline) == 'state_update_refused'
    assert json.loads(target.read_text()) == changed
    assert not list(root.glob('*.tmp'))


def test_private_acl_failure_never_writes_state_or_logs_secrets(setup, monkeypatch, capsys):
    root, state, process, baseline = setup
    before = (root / 'manager_share_state.json').read_bytes()

    def refuse(path):
        raise keeper.maintenance.Refused('synthetic-sensitive-error')

    monkeypatch.setattr(keeper.maintenance, 'protect', refuse)
    assert keeper.sync_gateway_pid(root, process, 8796, baseline) == 'state_update_refused'
    assert (root / 'manager_share_state.json').read_bytes() == before
    assert not list(root.glob('*.tmp'))
    captured = capsys.readouterr()
    assert captured.out == captured.err == ''


def test_listener_parser_requires_exact_loopback_port(monkeypatch):
    monkeypatch.setattr(keeper.subprocess, 'CREATE_NO_WINDOW', 0, raising=False)
    monkeypatch.setattr(keeper.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(
        returncode=0, stdout='\n'.join([
            'TCP 127.0.0.1:8796 0.0.0.0:0 LISTENING 20',
            'TCP 127.0.0.1:18796 0.0.0.0:0 LISTENING 99',
            'TCP 127.0.0.1:8796 127.0.0.1:123 ESTABLISHED 99'])))
    assert keeper.gateway_listener_pid(8796) == 20


@pytest.mark.parametrize('gateway_already_running', [False, True])
def test_keeper_syncs_only_spawned_gateway_without_stopping_children(setup, monkeypatch, gateway_already_running):
    root, original, process, baseline = setup
    iteration = [0]
    launched = []
    monkeypatch.setattr(keeper, 'RUNTIME', root)
    monkeypatch.setattr(keeper.ctypes, 'windll', SimpleNamespace(
        kernel32=SimpleNamespace(SetThreadExecutionState=lambda value: None)), raising=False)
    monkeypatch.setattr(keeper.subprocess, 'CREATE_NO_WINDOW', 0, raising=False)
    monkeypatch.setattr(keeper.time, 'time', lambda: 1000 if iteration[0] < 2 else 2001)
    monkeypatch.setattr(keeper.time, 'sleep', lambda seconds: iteration.__setitem__(0, iteration[0] + 1))
    monkeypatch.setattr(keeper, 'healthy', lambda port, path:
                        port == 8793 or gateway_already_running or iteration[0] > 0)

    class Socket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def settimeout(self, seconds):
            pass

        def connect_ex(self, address):
            return 0 if keeper.healthy(address[1], '') else 1

    def spawn(command, **kwargs):
        launched.append(command)
        return process

    monkeypatch.setattr(keeper.socket, 'socket', Socket)
    monkeypatch.setattr(keeper.subprocess, 'Popen', spawn)
    keeper.main()
    assert len(launched) == (0 if gateway_already_running else 1)
    expected = original if gateway_already_running else original | {'gateway_pid': 20}
    assert json.loads((root / 'manager_share_state.json').read_text()) == expected
    status = json.loads((root / 'keepalive_status.json').read_text())
    assert status['app'] and status['gateway']
    assert status.get('gateway_pid_sync') == (None if gateway_already_running else 'synced')
    if launched:
        assert 'src.rehab_affect.demo2_manager_gateway' in launched[0]
