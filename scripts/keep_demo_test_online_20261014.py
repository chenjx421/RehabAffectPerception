"""Bounded local service supervision; never replaces a public tunnel URL."""
import ctypes
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

if __package__:
    from . import maintain_school_pilot as maintenance
else:
    import maintain_school_pilot as maintenance

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'


def healthy(port, path):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=8) as response:
            return response.status == 200
    except Exception:
        return False


def gateway_listener_pid(port):
    try:
        result = subprocess.run(
            ['netstat', '-ano', '-p', 'tcp'], capture_output=True, text=True,
            errors='replace', timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            return None
        owners = set()
        for line in result.stdout.splitlines():
            fields = line.split()
            if (len(fields) == 5 and fields[0] == 'TCP'
                    and fields[1] == f'127.0.0.1:{port}' and fields[3] == 'LISTENING'):
                owners.add(int(fields[4]))
        return next(iter(owners)) if len(owners) == 1 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def gateway_state_baseline(runtime):
    try:
        _, value = maintenance.load_json(runtime / 'manager_share_state.json')
        if not isinstance(value.get('origin'), str) or not value['origin'].startswith('https://'):
            return None
        return value.get('gateway_pid'), value['origin']
    except (OSError, ValueError, maintenance.Refused):
        return None


def sync_gateway_pid(runtime, process, port, baseline):
    """Publish only our healthy listener; never adopt an external replacement."""
    if baseline is None:
        return 'state_unavailable'
    if process.poll() is not None:
        return 'process_exited'
    if not healthy(port, '/invite') or gateway_listener_pid(port) != process.pid:
        return 'waiting_for_listener'
    try:
        _, config, raw, state = maintenance.invitation(
            runtime / 'manager_share_config.json', runtime / 'manager_share_state.json')
        if (config.get('listen_port') != port or time.time() >= min(config['expires_at'], state['expires_at'])
                or state['origin'] != baseline[1]
                or state.get('gateway_pid') not in (baseline[0], process.pid)):
            return 'state_changed'
        if state.get('gateway_pid') == process.pid:
            return 'synced'
        if process.poll() is not None:
            return 'process_exited'
        state['gateway_pid'] = process.pid
        maintenance.atomic_replace(runtime / 'manager_share_state.json', maintenance.encoded(state), raw)
        return 'synced'
    except (OSError, ValueError, KeyError, TypeError, maintenance.Refused):
        return 'state_update_refused'


def main():
    config = json.loads((RUNTIME / 'manager_share_config.json').read_text(encoding='utf-8-sig'))
    expiry = config['expires_at']
    processes = {}
    gateway_baseline = None
    gateway_sync = None
    checks = 0
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    try:
        while True:
            try:
                updated = json.loads((RUNTIME / 'manager_share_config.json').read_text(encoding='utf-8-sig'))
                if (updated['upstream_port'], updated['listen_port']) == (config['upstream_port'], config['listen_port']):
                    expiry = float(updated['expires_at'])
            except (OSError, ValueError, KeyError):
                pass
            if time.time() >= expiry:
                break
            state = {'checked_at': time.time(), 'expires_at': expiry, 'checks': checks}
            for name, port, path, args in [
                ('app', config['upstream_port'], '/demo2/login', ['-m', 'src.rehab_affect.scenario_lab_server', '--host', '127.0.0.1', '--port', str(config['upstream_port']), '--policy', 'rule']),
                ('gateway', config['listen_port'], '/invite', ['-m', 'src.rehab_affect.demo2_manager_gateway', '--config', str(RUNTIME / 'manager_share_config.json')]),
            ]:
                state[name] = healthy(port, path)
                with socket.socket() as probe:
                    probe.settimeout(2)
                    listening = probe.connect_ex(('127.0.0.1', port)) == 0
                if not state[name] and not listening and (name not in processes or processes[name].poll() is not None):
                    if name == 'gateway':
                        gateway_baseline = gateway_state_baseline(RUNTIME)
                        gateway_sync = 'waiting_for_listener'
                    with (RUNTIME / ('keepalive_' + name + '.log')).open('ab') as log:
                        processes[name] = subprocess.Popen([sys.executable, *args], cwd=ROOT, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
                if name == 'gateway' and gateway_sync is not None and gateway_sync != 'synced':
                    gateway_sync = sync_gateway_pid(RUNTIME, processes[name], port, gateway_baseline)
                if name == 'gateway' and gateway_sync is not None:
                    state['gateway_pid_sync'] = gateway_sync
            (RUNTIME / 'keepalive_status.json').write_text(json.dumps(state), encoding='utf-8')
            checks += 1
            time.sleep(30)
    finally:
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


if __name__ == '__main__':
    main()
