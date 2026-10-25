"""Read-only share watchdog. Never authorize, rotate, restart, or stop services."""
import argparse
import csv
import ctypes
from datetime import datetime, timezone
import hashlib
import http.client
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time


ROOT = Path(__file__).resolve().parents[1]
DEADLINE = datetime(2026, 11, 6, 15, 59, 59, tzinfo=timezone.utc).timestamp()
INTERVAL = 60


def load_json(path):
    with path.open('r', encoding='utf-8-sig') as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError('invalid configuration')
    return value


def port(value):
    if type(value) is not int or not 1 <= value <= 65535:
        raise ValueError('invalid port')
    return value


def epoch(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError('invalid expiry')
    return value


def probe(host, port_number, path, *, tls=False):
    connection = None
    try:
        cls = http.client.HTTPSConnection if tls else http.client.HTTPConnection
        connection = cls(host, port_number, timeout=5)
        connection.connect()
        if path is None:
            return True
        connection.request('GET', path, headers={'User-Agent': 'PublicEntryWatchdog/1', 'Connection': 'close'})
        response = connection.getresponse()
        return response.status == 200
    except (OSError, http.client.HTTPException, ValueError):
        return False
    finally:
        if connection is not None:
            connection.close()


def process_alive(pid, image):
    if type(pid) is not int or pid <= 0 or os.name != 'nt':
        return False
    try:
        result = subprocess.run(
            ['tasklist', '/FI', f'PID eq {pid}', '/FO', 'CSV', '/NH'],
            capture_output=True, text=True, errors='replace', timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW, check=False)
        if result.returncode != 0:
            return False
        return any(len(row) >= 2 and row[1] == str(pid) and row[0].lower() == image
                   for row in csv.reader(io.StringIO(result.stdout)))
    except (OSError, subprocess.SubprocessError):
        return False


def check(runtime, previous=None, *, now=None, request=probe, alive=process_alive):
    """Return a fixed allowlist only; exceptions/configuration never reach output."""
    now = time.time() if now is None else now
    previous = previous or {}
    health = {key: False for key in ('local_app', 'local_gateway', 'public_origin',
                                    'public_invite', 'tunnel_ready', 'tunnel_process', 'gateway_process')}
    output = dict(checked_at=datetime.fromtimestamp(now, timezone.utc).isoformat(),
                  origin=None, expires_at=None, health=health, status='needs_attention',
                  needs_attention=True, reason='configuration_unavailable')
    try:
        if now >= DEADLINE:
            output.update(status='expired', reason='invitation_expired', expires_at=DEADLINE)
            output['consecutive_failures'] = 1
            return output
        config = load_json(runtime / 'manager_share_config.json')
        state = load_json(runtime / 'manager_share_state.json')
        origin = state.get('origin')
        if not isinstance(origin, str) or not re.fullmatch(r'https://[a-z0-9-]+\.trycloudflare\.com', origin):
            raise ValueError('invalid origin')
        output['origin'] = origin
        expiry = min(epoch(config['expires_at']), epoch(state['expires_at']), DEADLINE)
        output['expires_at'] = expiry
        if now >= expiry:
            output.update(status='expired', reason='invitation_expired')
        else:
            upstream = port(config.get('upstream_port', 8792))
            gateway = port(config['listen_port'])
            metrics = port(state['metrics_port'])
            health['local_app'] = request('127.0.0.1', upstream, '/demo2/login')
            health['local_gateway'] = request('127.0.0.1', gateway, '/invite')
            health['tunnel_ready'] = request('127.0.0.1', metrics, '/ready')
            health['tunnel_process'] = alive(state.get('tunnel_pid'), 'cloudflared.exe')
            health['gateway_process'] = (alive(state.get('gateway_pid'), 'python.exe') or
                                         alive(state.get('gateway_pid'), 'pythonw.exe'))
            host = origin[len('https://'):]
            health['public_origin'] = request(host, 443, None, tls=True)
            health['public_invite'] = request(host, 443, '/invite', tls=True)
            healthy = all(health.values())
            output.update(status='healthy' if healthy else 'needs_attention',
                          needs_attention=not healthy, reason='ok' if healthy else 'health_check_failed')
    except (OSError, ValueError, KeyError, TypeError):
        pass
    count = previous.get('consecutive_failures', 0)
    count = count if type(count) is int and count >= 0 else 0
    output['consecutive_failures'] = 0 if not output['needs_attention'] else count + 1
    return output


def write_health(runtime, result):
    # Only this health file is replaced; neither source configuration is written.
    target = runtime / 'public_entry_health.json'
    temporary = runtime / 'public_entry_health.json.tmp'
    try:
        with temporary.open('w', encoding='utf-8') as handle:
            json.dump(result, handle, ensure_ascii=True, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


class WindowsGuard:
    def __init__(self, runtime):
        self.name = 'Global\\RehabPublicShareWatch_' + hashlib.sha256(
            os.path.normcase(str(runtime.resolve())).encode()).hexdigest()[:32]
        self.handle = None
        self.kernel = None

    def __enter__(self):
        if os.name != 'nt':
            raise RuntimeError('Windows required')
        from ctypes import wintypes
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel.SetThreadExecutionState.argtypes = [wintypes.DWORD]
        self.kernel.SetThreadExecutionState.restype = wintypes.DWORD
        self.handle = self.kernel.CreateMutexW(None, False, self.name)
        error = ctypes.get_last_error()
        if not self.handle:
            raise RuntimeError('Watchdog mutex unavailable')
        if error == 183:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
            raise RuntimeError('Watchdog already running')
        if not self.kernel.SetThreadExecutionState(0x80000001):
            self.kernel.CloseHandle(self.handle)
            self.handle = None
            raise RuntimeError('Sleep prevention unavailable')
        return self

    def __exit__(self, *args):
        self.kernel.SetThreadExecutionState(0x80000000)
        self.kernel.CloseHandle(self.handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, default=ROOT / '.runtime')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    try:
        with WindowsGuard(args.runtime):
            previous = {}
            while True:
                started = time.monotonic()
                result = check(args.runtime, previous)
                write_health(args.runtime, result)
                previous = result
                if args.once or result['status'] == 'expired':
                    return 0
                time.sleep(max(0, INTERVAL - (time.monotonic() - started)))
    except (OSError, RuntimeError):
        # No configuration, request exception, or command output is echoed.
        print('Public entry watchdog could not run; check instance and runtime access.')
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
