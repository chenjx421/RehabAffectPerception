"""Synthetic configuration only; never contact the live share or read its files."""
import importlib.util
import json
import os
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location('share_watchdog', Path(__file__).resolve().parents[1] /
                                             'scripts/watch_public_share_20261017.py')
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)
NOW = 1792152000
SECRET = 'SYNTHETIC_SECRET_DO_NOT_EXPORT'


@pytest.fixture
def runtime(tmp_path):
    config = dict(expires_at=NOW + 1000, upstream_port=8792, listen_port=8793,
                  invite_secret=SECRET, cookie_secret=SECRET + '_COOKIE')
    state = dict(expires_at=NOW + 1000, origin='https://synthetic-only.trycloudflare.com',
                 invite_url='https://synthetic-only.trycloudflare.com/invite#' + SECRET,
                 tunnel_pid=123, gateway_pid=456, metrics_port=20246, secret=SECRET)
    for name, data in [('config', config), ('state', state)]:
        (tmp_path / f'manager_share_{name}.json').write_text(json.dumps(data), encoding='utf-8-sig')
    return tmp_path


def run(runtime, **kwargs):
    return watch.check(runtime, now=NOW, request=kwargs.pop('request', lambda *a, **kw: True),
                       alive=kwargs.pop('alive', lambda *a: True), **kwargs)


def update(runtime, name, **values):
    path = runtime / f'manager_share_{name}.json'
    data = watch.load_json(path)
    path.write_text(json.dumps(dict(data, **values)), encoding='utf-8')


def test_healthy_read_only_and_secret_never_exported(runtime):
    before = {p.name: p.read_bytes() for p in runtime.iterdir()}
    calls = []
    result = run(runtime, request=lambda *a, **kw: calls.append((a, kw)) or True)
    assert result['status'] == 'healthy' and result['consecutive_failures'] == 0
    assert all(result['health'].values())
    watch.write_health(runtime, result)
    raw = (runtime / 'public_entry_health.json').read_text()
    assert SECRET not in raw and 'invite_url' not in raw and 'cookie' not in raw
    assert all('#' not in str(call) and SECRET not in str(call) for call in calls)
    assert all((runtime / name).read_bytes() == data for name, data in before.items())
    assert not (runtime / 'public_entry_health.json.tmp').exists()


@pytest.mark.parametrize('failed', ['local_app', 'local_gateway', 'public_origin', 'public_invite', 'tunnel_ready'])
def test_each_failed_probe_needs_attention_and_recovers(runtime, failed):
    targets = {'local_app': (8792, '/demo2/login'), 'local_gateway': (8793, '/invite'),
               'public_origin': (443, None), 'public_invite': (443, '/invite'), 'tunnel_ready': (20246, '/ready')}
    def request(host, port, path, **kwargs):
        return (port, path) != targets[failed]
    first = run(runtime, request=request)
    assert first['status'] == 'needs_attention' and first['health'][failed] is False
    second = run(runtime, previous=first, request=request)
    assert second['consecutive_failures'] == 2
    assert run(runtime, previous=second)['consecutive_failures'] == 0


@pytest.mark.parametrize('pid,key', [(123, 'tunnel_process'), (456, 'gateway_process')])
def test_dead_process_not_hidden_by_healthy_http(runtime, pid, key):
    result = run(runtime, alive=lambda value, image: value != pid)
    assert result['needs_attention'] and not result['health'][key]


@pytest.mark.parametrize('file', ['config', 'state'])
def test_expiry_dynamic_no_network_after_expiry(runtime, file):
    assert run(runtime)['status'] == 'healthy'
    update(runtime, file, expires_at=NOW)
    def forbidden(*args, **kwargs):
        pytest.fail('No probes after expiry')
    result = run(runtime, request=forbidden, alive=forbidden)
    assert result['status'] == 'expired' and result['needs_attention']


def test_fixed_deadline_cannot_be_extended(runtime):
    update(runtime, 'config', expires_at=watch.DEADLINE + 1000)
    update(runtime, 'state', expires_at=watch.DEADLINE + 1000)
    result = watch.check(runtime, now=watch.DEADLINE)
    assert result['status'] == 'expired' and result['expires_at'] == watch.DEADLINE


def test_fixed_deadline_stops_even_if_configuration_missing(tmp_path):
    assert watch.check(tmp_path, now=watch.DEADLINE)['status'] == 'expired'


def test_windows_process_probe_uses_tasklist_without_command_line(monkeypatch):
    monkeypatch.setattr(watch.os, 'name', 'nt')
    calls = []
    def fake_run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return type('Result', (), {'returncode': 0, 'stdout': '"cloudflared.exe","123","Console","1","50 K"\n'})()
    monkeypatch.setattr(watch.subprocess, 'run', fake_run)
    assert watch.process_alive(123, 'cloudflared.exe')
    assert not watch.process_alive(123, 'python.exe')
    assert not watch.process_alive(True, 'cloudflared.exe')
    assert all(args == ['tasklist', '/FI', 'PID eq 123', '/FO', 'CSV', '/NH'] for args, _ in calls)
    assert all(kwargs['capture_output'] and kwargs['timeout'] == 5 for _, kwargs in calls)


@pytest.mark.parametrize('origin', ['https://evil.test', 'https://a.trycloudflare.com/#' + SECRET,
                                   'https://user:pass@a.trycloudflare.com', None])
def test_invalid_origin_not_exported_or_probed(runtime, origin):
    update(runtime, 'state', origin=origin)
    def forbidden(*args, **kwargs):
        pytest.fail('Invalid origin must not be probed')
    result = run(runtime, request=forbidden)
    assert result['needs_attention'] and result['origin'] is None
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize('bad', [None, 'never', True, float('nan')])
def test_invalid_expiry_fails_closed(runtime, bad):
    update(runtime, 'config', expires_at=bad)
    result = run(runtime)
    assert result['needs_attention'] and result['reason'] == 'configuration_unavailable'


def test_missing_or_broken_configuration_safe(runtime):
    (runtime / 'manager_share_config.json').write_text(SECRET, encoding='utf-8')
    assert SECRET not in json.dumps(run(runtime))
    (runtime / 'manager_share_state.json').unlink()
    assert run(runtime)['needs_attention']


def test_probe_does_not_follow_redirects_or_emit_exception(monkeypatch):
    class Connection:
        def __init__(self, *a, **kw): pass
        def connect(self): pass
        def request(self, *a, **kw): pass
        def getresponse(self): return type('Response', (), {'status': 302})()
        def close(self): pass
    monkeypatch.setattr(watch.http.client, 'HTTPSConnection', Connection)
    assert watch.probe('synthetic.test', 443, '/invite', tls=True) is False
    assert watch.probe('synthetic.test', 443, None, tls=True) is True
    def fail(*args, **kwargs):
        raise OSError(SECRET)
    monkeypatch.setattr(Connection, 'connect', fail)
    assert watch.probe('synthetic.test', 443, '/invite', tls=True) is False


@pytest.mark.skipif(os.name != 'nt', reason='Windows mutex and execution-state contract')
def test_real_windows_mutex_single_instance_and_release(runtime):
    with watch.WindowsGuard(runtime):
        with pytest.raises(RuntimeError, match='already running'):
            with watch.WindowsGuard(runtime):
                pytest.fail('Second instance acquired mutex')
    with watch.WindowsGuard(runtime):
        pass
