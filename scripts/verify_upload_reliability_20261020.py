"""HTTP upload acceptance. Public writes require explicit authorization.

Examples (public commands ONLY after the coordinator authorizes that run):
  python scripts/verify_upload_reliability_20261020.py --public --authorize-public-writes --legacy --megabytes 16
  python scripts/verify_upload_reliability_20261020.py --public --authorize-public-writes --megabytes 16 --benchmark-only
  python scripts/verify_upload_reliability_20261020.py --public --authorize-public-writes --megabytes 670 --wait-worker
  python scripts/verify_upload_reliability_20261020.py --megabytes 16 --legacy

MiB is used for --megabytes. The six-second MP4 has a standards-valid free
atom containing random padding. This tests file transport, NOT lesson-length
decoding, the browser uploader, or automatic student scoring. --local-video
accepts an explicitly authorized original ONLY on disposable loopback servers.
It never copies its filename/path into reports or permits public forwarding.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
API = '/api/v1/demo2'
CHUNK = 4 * 1024 * 1024


class CheckFailed(Exception):
    pass


def require(value, code):
    if not value:
        raise CheckFailed(code)


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(CHUNK), b''):
            value.update(block)
    return value.hexdigest()


def private_local_run(folder, report):
    if os.name == 'nt':
        result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
            '[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value'],
            capture_output=True, text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        sid = result.stdout.strip()
        require(result.returncode == 0 and sid.startswith('S-1-'), 'private_acl_identity_failed')
        result = subprocess.run(['icacls', str(folder), '/inheritance:r', '/grant:r',
            f'*{sid}:(OI)(CI)F', '*S-1-5-18:(OI)(CI)F', '*S-1-5-32-544:(OI)(CI)F'],
            capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
        require(result.returncode == 0, 'private_acl_failed')
        report['private_acl'] = 'current_user_system_administrators_only'
    else:
        folder.chmod(0o700)
        report['private_acl'] = 'owner_only_0700'
    report['external_connections_blocked'] = 0

    def network_audit(event, values):
        if event == 'socket.connect':
            address = values[1]
            if not isinstance(address, tuple) or address[0] not in {'127.0.0.1', '::1'}:
                report['external_connections_blocked'] += 1
                raise CheckFailed('external_network_forbidden')

    sys.addaudithook(network_audit)


def retry_delay(response, attempt):
    from email.utils import parsedate_to_datetime
    raw = response.headers.get('Retry-After', '') if response is not None else ''
    try:
        delay = float(raw)
    except ValueError:
        try:
            delay = parsedate_to_datetime(raw).timestamp() - time.time()
        except (ValueError, TypeError, OverflowError):
            delay = min(2 ** attempt, 30)
    require(math.isfinite(delay) and delay <= 600, 'retry_after_exceeds_run_budget')
    return max(1, delay)


class Client:
    def __init__(self, origin, report, save, cookies=None):
        self.origin, self.report, self.save = origin, report, save
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({'Origin': origin, 'Connection': 'keep-alive' if report.get('keep_alive') else 'close'})
        if cookies is not None:
            self.session.cookies.update(cookies)

    def once(self, route, *, payload=None, body=None):
        return self.session.request('POST' if payload is not None or body is not None else 'GET',
            self.origin + route, json=payload, data=body,
            headers={'Content-Type': 'application/octet-stream'} if body is not None else None,
            timeout=(30, 180), allow_redirects=False)

    def api(self, route, payload=None, expected=(200,)):
        # Task creation is intentionally never blindly replayed after a network error.
        for attempt in range(6):
            response = self.once(route, payload=payload)
            if response.status_code == 429 or (payload is None and response.status_code in (502, 503, 504)):
                delay = retry_delay(response, attempt)
                response.close()
                self.report['retries'].append({'operation': 'api', 'wait_seconds': delay})
                self.save()
                time.sleep(delay)
                continue
            try:
                require(response.status_code in expected, 'api_http_' + str(response.status_code))
                return response.json() if response.content else {}
            finally:
                response.close()
        raise CheckFailed('api_retry_budget_exhausted')

    def task(self, task_id):
        return self.api(API + '/upload/task?' + urlencode({'id': task_id}))['task']

    def close(self):
        self.session.close()


def public_config():
    state = json.loads((ROOT / '.runtime/manager_share_state.json').read_text(encoding='utf-8-sig'))
    origin = state['origin'].rstrip('/')
    base, invite = urlsplit(origin), urlsplit(state['invite_url'])
    require(base.scheme == 'https' and base.netloc and not (base.username or base.password or base.query or base.fragment)
            and not base.path and invite.scheme == base.scheme and invite.netloc == base.netloc
            and invite.path == '/invite' and not invite.query, 'invalid_public_origin')
    secret = parse_qs(invite.fragment).get('secret', [''])[0] if invite.fragment.startswith('secret=') else invite.fragment
    require(bool(secret), 'invitation_missing')
    rows = (ROOT / '.runtime/demo2_pilot_accounts_20260908.md').read_text(encoding='utf-8-sig').splitlines()
    account = next((parts for line in rows if len(parts := [p.strip() for p in line.split('|')]) > 3 and parts[2] == 't1'), None)
    require(account is not None and account[3], 'credentials_missing')
    return origin, secret, 't1', account[3]


def fault_ingress(upstream_port):
    """Local-only HTTP fault injection; the actual gateway/app stay unmodified."""
    remaining = [503, 429]

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *args):
            pass

        def dispatch(self):
            length = int(self.headers.get('Content-Length', '0'))
            body = self.rfile.read(length)
            if len(body) != length:
                self.close_connection = True
                return
            query = parse_qs(urlsplit(self.path).query)
            if (self.command == 'POST' and urlsplit(self.path).path == API + '/upload/chunks'
                    and query.get('chunk_index') == ['0'] and remaining):
                self.send_response(remaining.pop(0))
                self.send_header('Retry-After', '1')
                self.send_header('Content-Length', '0')
                self.send_header('Connection', 'close')
                self.end_headers()
                self.close_connection = True
                return
            connection = http.client.HTTPConnection('127.0.0.1', upstream_port, timeout=180)
            headers = {key: value for key, value in self.headers.items()
                       if key.lower() not in {'host', 'origin', 'connection', 'content-length'}}
            headers.update(Origin=f'http://127.0.0.1:{upstream_port}', Connection='close')
            try:
                connection.request(self.command, self.path, body if length else None, headers)
                response = connection.getresponse()
                self.send_response(response.status)
                for key, value in response.getheaders():
                    if key.lower() not in {'connection', 'transfer-encoding'}:
                        self.send_header(key, value)
                self.send_header('Connection', 'close')
                self.end_headers()
                for block in iter(lambda: response.read(65536), b''):
                    self.wfile.write(block)
            except (ConnectionError, OSError, http.client.HTTPException):
                pass
            finally:
                self.close_connection = True
                connection.close()

        do_GET = dispatch
        do_POST = dispatch

    return ThreadingHTTPServer(('127.0.0.1', 0), Handler)


def isolated(folder, inject_faults, storage_folder=None):
    storage_folder = storage_folder or folder
    os.environ['REHAB_DEMO2_DB_PATH'] = str(storage_folder / 'database' / 'test.sqlite3')
    os.environ['REHAB_DEMO2_UPLOAD_DIR'] = str(storage_folder / 'uploads')
    password_prefix = secrets.token_urlsafe(24)
    os.environ['REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX'] = password_prefix
    from rehab_affect import scenario_lab_server as backend
    from rehab_affect.student_record_store import get_demo2_student_store
    from rehab_affect.demo2_manager_gateway import make_server
    store = get_demo2_student_store()
    for path in (store.db_path, store.upload_dir, store.video_task_dir):
        require(path.resolve().is_relative_to(storage_folder.resolve()), 'storage_not_isolated')
    if storage_folder != folder:
        passwords = {f't{i}': password_prefix + f'school_uploader_{i:02d}' for i in range(1, 5)}
        passwords['admin'] = password_prefix + 'company_admin'
        store.set_seeded_pilot_passwords(store.db_path, passwords)
    handler = backend.create_handler(scenario_dir=folder, model_path=folder / 'unused', policy_name='rule')

    class QuietHandler(handler):
        def log_message(self, *args):
            pass

    app = backend.ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
    secret = secrets.token_urlsafe(40)
    gateway = make_server(dict(invite_secret=secret, cookie_secret=secrets.token_urlsafe(40),
        expires_at=time.time() + 7200, upstream_port=app.server_port, listen_port=0), port=0)
    servers = [app, gateway]
    if inject_faults:
        servers.append(fault_ingress(gateway.server_port))
    threads = []
    for server in servers:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        threads.append(thread)
    return f'http://127.0.0.1:{servers[-1].server_port}', secret, 'school_uploader_01', password_prefix + 'school_uploader_01', store, servers, threads


def fixture(folder, mib):
    from rehab_affect.demo2_media_analysis import _resolve_tool
    path = folder / 'SYNTHETIC-six-seconds-transport.mp4'
    require(shutil.disk_usage(folder).free > mib * 1024 * 1024 * 3 + 256 * 1024 * 1024, 'insufficient_disk')
    subprocess.run([_resolve_tool('ffmpeg'), '-hide_banner', '-loglevel', 'error', '-nostdin', '-n',
        '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=25', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=16000',
        '-t', '6', '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p',
        '-c:a', 'aac', '-b:a', '64k', '-movflags', '+faststart', str(path)],
        check=True, capture_output=True, timeout=120)
    padding = mib * 1024 * 1024 - path.stat().st_size
    require(8 <= padding < 2 ** 32, 'invalid_free_atom_size')
    with path.open('ab') as stream:
        stream.write(struct.pack('>I4s', padding, b'free'))
        remaining = padding - 8
        while remaining:
            block = os.urandom(min(CHUNK, remaining))
            stream.write(block)
            remaining -= len(block)
    probe = subprocess.run([_resolve_tool('ffprobe'), '-v', 'error', '-show_entries',
        'format=duration:stream=codec_type', '-of', 'json', str(path)], check=True, capture_output=True, timeout=30)
    metadata = json.loads(probe.stdout)
    require(5.9 <= float(metadata['format']['duration']) <= 6.2, 'fixture_duration_mismatch')
    require({s['codec_type'] for s in metadata['streams']} >= {'video', 'audio'}, 'fixture_stream_missing')
    return path, digest(path)


def interrupt(client, route, block, *, partial):
    target = urlsplit(client.origin)
    connection_type = http.client.HTTPSConnection if target.scheme == 'https' else http.client.HTTPConnection
    conn = connection_type(target.hostname, target.port, timeout=30)
    prepared = client.session.prepare_request(requests.Request('POST', client.origin + route))
    try:
        conn.putrequest('POST', route)
        for key, value in {'Origin': client.origin, 'Content-Type': 'application/octet-stream',
                           'Content-Length': str(len(block)), 'Cookie': prepared.headers.get('Cookie', ''),
                           'Connection': 'close'}.items():
            conn.putheader(key, value)
        conn.endheaders()
        conn.send(block[:len(block) // 2] if partial else block)
        if partial:
            conn.sock.shutdown(socket.SHUT_WR)
        # Full-body case deliberately never reads the response: commit is unknown.
    finally:
        conn.close()


def slow_chunk(client, route, block, seconds):
    target = urlsplit(client.origin)
    require(target.scheme == 'http' and target.hostname == '127.0.0.1', 'slow_probe_isolated_only')
    conn = http.client.HTTPConnection(target.hostname, target.port, timeout=180)
    prepared = client.session.prepare_request(requests.Request('POST', client.origin + route))
    start = time.monotonic()
    try:
        conn.putrequest('POST', route)
        for key, value in {'Origin': client.origin, 'Content-Type': 'application/octet-stream',
                           'Content-Length': str(len(block)), 'Cookie': prepared.headers.get('Cookie', ''),
                           'Connection': 'close'}.items():
            conn.putheader(key, value)
        conn.endheaders()
        slices = math.ceil(len(block) / 65536)
        for index in range(slices):
            wait = start + seconds * index / (slices - 1) - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            conn.send(block[index * 65536:(index + 1) * 65536])
        response = conn.getresponse()
        raw = response.read()
        require(response.status == 200, 'slow_chunk_http_' + str(response.status))
        return json.loads(raw)['task'], time.monotonic() - start
    finally:
        conn.close()


def four_channel_flow():
    """Extend the existing real-worker harness; all identities/documents are synthetic."""
    from datetime import date, timedelta
    import http.cookiejar
    import urllib.request
    from types import SimpleNamespace
    from unittest.mock import patch
    from cryptography.fernet import Fernet
    import verify_first_use_isolated_20261016 as flow

    folder = ROOT / '.runtime/upload_reliability_20261020' / (
        time.strftime('four_channel_%Y%m%d_%H%M%S_') + secrets.token_hex(4))
    folder.mkdir(parents=True)
    report = dict(status='running', synthetic_only=True, live_instance_accessed=False,
                  automatic_assessment=False, channels_completed=0, channels=[])
    private_local_run(folder, report)
    original_verify = flow.verify_teacher_reports
    channels = []

    def save():
        temporary = folder / 'progress.tmp'
        temporary.write_text(json.dumps(report, indent=2), encoding='utf-8')
        for attempt in range(10):
            try:
                temporary.replace(folder / 'progress.json')
                return
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(.1 * (attempt + 1))

    def fresh_client():
        return urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def verify(call, client, root, number, task_id, course, student, binding, revision, sha256, school):
        checks = original_verify(call, client, root, number, task_id, course,
                                 student, binding, revision, sha256, school)
        endpoint = API + '/dossier'
        sid = student['student_id']
        today = date.today()
        authorization = call(client, endpoint + '/authorization', dict(
            student_id=sid, reference='SYNTHETIC QA authorization only',
            storage_mode='original_and_summary', confirmed=True,
            valid_until=(today + timedelta(days=30)).isoformat()))['authorization']
        content = b'SYNTHETIC IEP QA ONLY. Recognize a geometric rectangle with visual support. No clinical conclusion.'
        document = call(client, endpoint + '/documents', dict(
            student_id=sid, authorization_id=authorization['authorization_id'],
            document_type='iep', document_date=today.isoformat(),
            source_ref='SYNTHETIC QA document', retain_until=(today + timedelta(days=20)).isoformat(),
            summary=dict(learning_goals='SYNTHETIC: recognize a rectangle',
                         support_methods='SYNTHETIC: visual prompt',
                         safety_notes='SYNTHETIC: no real student data',
                         professional_conclusion='SYNTHETIC QA only; no clinical conclusion'),
            filename='SYNTHETIC-IEP.txt', content_base64=base64.b64encode(content).decode('ascii'),
            supersedes_id=''))['document']
        did = document['document_id']
        require(call(client, endpoint + '/document?' + urlencode({'document_id': did})) == content,
                'synthetic_iep_download_mismatch')
        reference = call(client, endpoint + '/references', dict(task_id=task_id, student_id=sid,
            frame_revision=revision, document_ids=[did], confirmed=True))['reference']
        rid = reference['reference_id']
        exported = call(client, endpoint + '/reference?' + urlencode({'reference_id': rid}))
        require(exported['task_id'] == task_id and exported['student_id'] == sid
                and exported['available'] and exported['document_versions'], 'dossier_reference_mismatch')
        workspace = call(client, endpoint + '/task?' + urlencode({'task_id': task_id}))['workspace']
        require(any(r['reference_id'] == rid for r in workspace['references']), 'dossier_reference_not_persisted')
        (root / f'SYNTHETIC-school-{number}-dossier-reference.json').write_text(
            json.dumps(exported, indent=2), encoding='utf-8')
        source = call(client, API + '/upload/media?' + urlencode({'id': task_id, 'asset': 'source'}))
        require(hashlib.sha256(source).hexdigest() == sha256, 'channel_source_hash_mismatch')
        channels.append(dict(client=client, task_id=task_id, document_id=did, reference_id=rid, sha256=sha256))
        checks.update(iep_authorization=True, encrypted_document_roundtrip=True,
                      confirmed_document_reference=True, reference_export_reloaded=True,
                      source_download_sha256=True)
        report['channels'].append(dict(channel=number, task_id=task_id, source_sha256=sha256, checks=checks))
        report['channels_completed'] = number
        save()
        print(json.dumps({'step': 'isolated_full_chain', 'channels_completed': number}), flush=True)
        if number == 4:
            admin = fresh_client()
            anonymous = fresh_client()
            call(admin, API + '/auth/login', dict(username='company_admin',
                password='SyntheticAcceptance-company_admin', role='company_admin'))
            for owner in channels:
                document_path = endpoint + '/document?' + urlencode({'document_id': owner['document_id']})
                reference_path = endpoint + '/reference?' + urlencode({'reference_id': owner['reference_id']})
                for other in channels:
                    if other is not owner:
                        call(other['client'], document_path, expected=404)
                        call(other['client'], reference_path, expected=404)
                call(admin, document_path, expected=403)
                call(anonymous, document_path, expected=401)
                media_path = API + '/upload/media?' + urlencode({'id': owner['task_id'], 'asset': 'source'})
                require(hashlib.sha256(call(admin, media_path)).hexdigest() == owner['sha256'],
                        'admin_source_hash_mismatch')
                result = call(admin, API + '/upload/result?' + urlencode({'id': owner['task_id']}))
                require(result['source_sha256'] == owner['sha256'], 'admin_result_hash_mismatch')
                call(anonymous, media_path, expected=401)
            summary = call(admin, endpoint + '/admin')['summary']
            require(summary['totals']['document_count'] == 4, 'admin_document_aggregate_mismatch')
            report.update(cross_owner_document_reference_denials=24, admin_raw_dossier_denials=4,
                          anonymous_document_media_denials=8, admin_source_result_hashes=4,
                          admin_document_count=4)
            save()
        return checks

    save()
    try:
        # Existing harness owns its loopback lifecycle. Only its temp root and
        # verification callback change; browser coverage remains explicitly out of scope.
        with patch.dict(os.environ, {'REHAB_DEMO2_DOSSIER_KEY': Fernet.generate_key().decode('ascii')}), \
             patch.object(flow, 'tempfile', SimpleNamespace(mkdtemp=lambda **kwargs: str(folder))), \
             patch.object(flow, 'verify_teacher_reports', verify), \
             patch.object(flow, 'browser_check', return_value='not run: HTTP/store integration scope'):
            flow.main()
        require(report['external_connections_blocked'] == 0, 'external_connection_attempted')
        report.update(status='passed', identity_measurement_course_isolation=True,
                      browser_tested=False, channel_count=4)
    except Exception as error:
        trace = error.__traceback__
        while trace and trace.tb_next:
            trace = trace.tb_next
        report.update(status='failed', failure_code=str(error) if isinstance(error, CheckFailed) else type(error).__name__,
            failure_site=dict(function=trace.tb_frame.f_code.co_name if trace else None,
                line=trace.tb_lineno if trace else None, errno=getattr(error, 'errno', None),
                winerror=getattr(error, 'winerror', None)))
    finally:
        save()
        (folder / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps({'status': report['status'], 'channels_completed': report['channels_completed'],
                          'failure_code': report.get('failure_code'), 'report': str(folder / 'report.json')}), flush=True)
    return 0 if report['status'] == 'passed' else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public', action='store_true')
    parser.add_argument('--authorize-public-writes', action='store_true')
    parser.add_argument('--legacy', action='store_true')
    parser.add_argument('--megabytes', type=int, default=670)
    parser.add_argument('--wait-worker', action='store_true')
    parser.add_argument('--keep-alive', action='store_true', help='Requests HTTP/1.1 pooling, not browser HTTP/2')
    parser.add_argument('--benchmark-only', action='store_true', help='No injected interruptions, retries, or client replacement')
    parser.add_argument('--slow-chunk-seconds', type=float, default=0, help='Isolated binary only; pace one chunk')
    parser.add_argument('--local-video', type=Path, help='Authorized original; isolated only, never public; full worker required')
    parser.add_argument('--resume-isolated', type=Path, help='Prior private report.json; reuse completed upload, retry interrupted worker')
    parser.add_argument('--four-channel-flow', action='store_true', help='Isolated synthetic identity/IEP/measurement/report HTTP integration')
    args = parser.parse_args()
    if args.four_channel_flow:
        require(not (args.public or args.authorize_public_writes or args.local_video or args.resume_isolated),
                'four_channel_flow_requires_isolated_synthetic_only')
        return four_channel_flow()
    require(not (args.public and args.local_video), 'real_material_public_upload_forbidden')
    require(not args.resume_isolated or (args.local_video and not args.public), 'resume_isolated_requires_private_local_video')
    require(not args.public or args.authorize_public_writes, 'public_writes_not_authorized')
    require(16 <= args.megabytes <= 2048, 'fixture_size_out_of_range')
    require(math.isfinite(args.slow_chunk_seconds) and 0 <= args.slow_chunk_seconds <= 120
            and (not args.slow_chunk_seconds or (not args.public and not args.legacy and not args.benchmark_only)), 'invalid_slow_chunk_options')
    sys.path.insert(0, str(ROOT / 'src'))
    folder = ROOT / '.runtime/upload_reliability_20261020' / (time.strftime('run_%Y%m%d_%H%M%S_') + secrets.token_hex(4))
    folder.mkdir(parents=True)
    args.wait_worker = args.wait_worker or args.local_video is not None
    report = {'status': 'running', 'step': 'fixture', 'synthetic_only': args.local_video is None,
              'public': args.public, 'protocol': 'legacy_json_base64' if args.legacy else 'binary_octet_stream',
              'fixture_type': 'authorized_provided_classroom' if args.local_video else 'six_second_mp4_with_random_free_atom_padding', 'chunk_bytes': CHUNK,
              'checks': [], 'chunks': [], 'retries': [], 'worker_requested': args.wait_worker,
              'keep_alive': args.keep_alive,
              'benchmark_only': args.benchmark_only, 'http_client_protocol': 'HTTP/1.1',
              'scope': ('Authorized provided classroom, isolated full decoder and byte persistence; no LLM, identities or scoring'
                        if args.local_video else 'HTTP transport and stored bytes; not browser UI or lesson-length analysis')}
    started = time.monotonic()
    clients, servers, threads = [], [], []
    store = worker = prior = None

    def save():
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        temporary = folder / 'progress.tmp'
        # Windows readers/AV can briefly deny replacement even on an owned file.
        for attempt in range(10):
            try:
                temporary.write_text(json.dumps(report, indent=2), encoding='utf-8')
                temporary.replace(folder / 'progress.json')
                break
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(.2 * (attempt + 1))

    def check(name, value):
        report['checks'].append({'name': name, 'passed': bool(value)})
        save()
        require(value, name)

    try:
        if args.local_video:
            private_local_run(folder, report)
        save()
        storage_folder = None
        if args.resume_isolated:
            previous_path = args.resume_isolated.resolve(strict=True)
            private_base = (ROOT / '.runtime/upload_reliability_20261020').resolve()
            require(previous_path.is_relative_to(private_base) and previous_path.name == 'report.json', 'invalid_private_resume_path')
            prior = json.loads(previous_path.read_text(encoding='utf-8'))
            require(prior.get('public') is False and prior.get('synthetic_only') is False
                    and prior.get('fixture_type') == 'authorized_provided_classroom'
                    and prior.get('status') == 'failed', 'invalid_private_resume_report')
            storage_folder = previous_path.parent
            require((storage_folder / 'database/test.sqlite3').is_file(), 'private_resume_database_missing')
            report['resumed_private_run'] = storage_folder.name
            report['prior_upload_seconds'] = prior.get('upload_seconds')
        if args.local_video:
            source = args.local_video.resolve(strict=True)
            require(source.is_file() and not str(source).startswith('\\\\'), 'local_video_required')
            initial_stat = source.stat()
            disk_budget = 512 * 1024 * 1024 if prior else initial_stat.st_size * 2 + 256 * 1024 * 1024
            require(initial_stat.st_size >= CHUNK * 4 and shutil.disk_usage(folder).free > disk_budget,
                    'local_video_size_or_disk_budget')
            sha = digest(source)
            if prior:
                require(prior['source_sha256'] == sha and prior['source_bytes'] == initial_stat.st_size, 'private_resume_source_mismatch')
            upload_name = 'AUTHORIZED-local-classroom.mp4'
        else:
            source, sha = fixture(folder, args.megabytes)
            upload_name = source.name
        size = source.stat().st_size
        report.update(source_sha256=sha, source_bytes=size, total_chunks=math.ceil(size / CHUNK))
        report['step'] = 'login'
        save()
        if args.public:
            origin, secret, username, password = public_config()
        else:
            inject_faults = not args.legacy and not args.benchmark_only and not prior
            origin, secret, username, password, store, servers, threads = isolated(folder, inject_faults, storage_folder)
            report['local_503_429_fault_injection'] = inject_faults
        report['origin'] = origin
        client = Client(origin, report, save)
        clients.append(client)
        client.api('/__manager/authorize', {'secret': secret}, expected=(303,))
        if not args.public:
            for cookie in client.session.cookies:
                cookie.secure = False  # This fixture's gateway is loopback HTTP only.
        client.api(API + '/auth/login', {'username': username, 'password': password, 'role': 'school_uploader'})
        secret = password = None
        if not args.public:
            for cookie in client.session.cookies:
                cookie.secure = False
        seeded_context = None
        if not args.public and not prior:
            token = client.session.cookies.get('rehab_demo2_session')
            require(token and not any(store.account_school_context(token)['context'].values()), 'isolated_school_not_empty')
            seeded_context = dict(city='SYNTHETIC QA CITY', district='SYNTHETIC QA DISTRICT', school_name='SYNTHETIC QA SCHOOL 1')
            saved_context = store.save_account_school_context(token, seeded_context)
            check('isolated_synthetic_school_seeded', saved_context['context'] == seeded_context)
        course = ('LOCAL-authorized-upload-' if args.local_video else 'SYNTHETIC-upload-reliability-') + secrets.token_hex(8)
        if prior:
            course = prior['course_id']
        workspace = client.api(API + '/upload/workspace?' + urlencode({'course_id': course}))['workspace']
        channel = workspace.get('channel') or workspace.get('upload_channel')
        require(channel and channel.get('channel_id'), 'channel_missing')
        # No school or roster mutation, even if the account has no school metadata.
        if prior:
            task = client.task(prior['task_id'])
            check('reused_completed_private_upload', task['sha256'] == sha and task['upload_status'] == 'completed'
                  and task['received_bytes'] == size and task['course_id'] == course)
            require(task['analysis_status'] == 'failed', 'private_resume_worker_not_failed')
            client.api(API + '/upload/tasks/retry', {'task_id': task['task_id']}, expected=(202,))
        else:
            task = client.api(API + '/upload/tasks', dict(course_id=course,
                course_name='LOCAL authorized transport acceptance' if args.local_video else 'SYNTHETIC transport acceptance',
                session_id=course, uploader_name='LOCAL QA TEST', channel_id=channel['channel_id'],
                filename=upload_name, mime_type='video/mp4', byte_size=size, total_chunks=math.ceil(size / CHUNK),
                security_confirmed=True, allow_company_archive=False))['task']
        task_id = task['task_id']
        if seeded_context is not None:
            check('task_captured_synthetic_school', task.get('school_context') == seeded_context)
        report.update(task_id=task_id, course_id=course, step='upload')
        save()
        upload_started = time.monotonic()
        with source.open('rb') as stream:
            for index in range(math.ceil(size / CHUNK) if prior else 0, math.ceil(size / CHUNK)):
                block = stream.read(CHUNK)
                route = API + '/upload/chunks?' + urlencode(dict(task_id=task_id, course_id=course, chunk_index=index))
                chunk_started = time.monotonic()
                if not args.legacy and not args.benchmark_only and index in (1, 2):
                    if not args.public and index == 1:
                        # Exercise truncation at the real gateway, not the test proxy.
                        direct = Client(f'http://127.0.0.1:{servers[1].server_port}', report, save,
                                        client.session.cookies.copy())
                        try:
                            interrupt(direct, route, block, partial=True)
                        finally:
                            direct.close()
                    else:
                        interrupt(client, route, block, partial=index == 1)
                    time.sleep(2)
                    state = client.task(task_id)
                    check('interrupted_body_atomic' if index == 1 else 'lost_response_reconcilable',
                          state['next_chunk_index'] in ((index,) if index == 1 else (index, index + 1))
                          and state['received_bytes'] == min(state['next_chunk_index'] * CHUNK, size))
                if not args.legacy and not args.benchmark_only and index == 3:
                    checkpoint = dict(task_id=task_id, course_id=course, source_sha256=sha, source_bytes=size)
                    (folder / 'resume.json').write_text(json.dumps(checkpoint), encoding='utf-8')
                    cookies = client.session.cookies.copy()
                    client.close()
                    client = Client(origin, report, save, cookies)
                    clients.append(client)
                    checkpoint = json.loads((folder / 'resume.json').read_text(encoding='utf-8'))
                    state = client.task(checkpoint['task_id'])
                    check('fresh_client_resume', state['next_chunk_index'] == index and state['received_bytes'] == index * CHUNK)
                    with source.open('rb') as confirmed:
                        hashes = [hashlib.sha256(confirmed.read(CHUNK)).hexdigest() for _ in range(index)]
                    resumed = client.api(API + '/upload/resume', dict(task_id=task_id, course_id=course,
                        byte_size=size, filename=upload_name, chunk_sha256=hashes))['task']
                    check('server_verified_resume_prefix', resumed['next_chunk_index'] == index and resumed['received_bytes'] == index * CHUNK)
                    if args.slow_chunk_seconds:
                        direct = Client(f'http://127.0.0.1:{servers[1].server_port}', report, save,
                                        client.session.cookies.copy())
                        try:
                            slow_state, seconds = slow_chunk(direct, route, block, args.slow_chunk_seconds)
                        finally:
                            direct.close()
                        report['slow_chunk_seconds'] = round(seconds, 3)
                        check('slow_gateway_body_complete', seconds >= args.slow_chunk_seconds
                              and slow_state['next_chunk_index'] == index + 1
                              and slow_state['received_bytes'] == min((index + 1) * CHUNK, size))
                attempts = 0
                for attempt in range(7):
                    if not args.legacy and (not args.benchmark_only or attempt > 0):
                        state = client.task(task_id)
                        if state['next_chunk_index'] == index + 1:
                            require(state['received_bytes'] == min((index + 1) * CHUNK, size), 'reconciled_offset_mismatch')
                            break
                        require(state['next_chunk_index'] == index and state['received_bytes'] == index * CHUNK, 'resume_offset_mismatch')
                    response = None
                    attempts += 1
                    try:
                        response = client.once(API + '/upload/chunks' if args.legacy else route,
                            payload=dict(task_id=task_id, course_id=course, chunk_index=index,
                                         content_base64=base64.b64encode(block).decode('ascii')) if args.legacy else None,
                            body=None if args.legacy else block)
                        if response.status_code == 200:
                            state = response.json()['task']
                            require(state['next_chunk_index'] == index + 1 and state['received_bytes'] == min((index + 1) * CHUNK, size), 'chunk_ack_mismatch')
                            break
                        require(response.status_code in (408, 409, 429, 500, 502, 503, 504), 'chunk_http_' + str(response.status_code))
                    except requests.RequestException:
                        pass
                    finally:
                        if response is not None:
                            response.close()
                    # Never retry unknown completion without first reading server state.
                    state = client.task(task_id)
                    if state['next_chunk_index'] == index + 1:
                        require(state['received_bytes'] == min((index + 1) * CHUNK, size), 'retry_offset_mismatch')
                        break
                    delay = retry_delay(response, attempt)
                    report['retries'].append({'chunk': index, 'status': response.status_code if response is not None else None,
                                              'wait_seconds': delay})
                    save()
                    time.sleep(delay)
                else:
                    raise CheckFailed('chunk_retry_budget_exhausted')
                report['chunks'].append({'index': index, 'bytes': len(block), 'attempts': attempts,
                                          'seconds': round(time.monotonic() - chunk_started, 3)})
                report['received_bytes'] = min((index + 1) * CHUNK, size)
                save()
                if index % 20 == 0:
                    print(json.dumps({'step': 'upload', 'chunks_done': index + 1, 'total_chunks': math.ceil(size / CHUNK)}), flush=True)
        report['upload_seconds'] = round(time.monotonic() - upload_started, 3)
        report['uploaded_bytes_this_run'] = 0 if prior else size
        report['upload_mib_per_second'] = round(report['uploaded_bytes_this_run'] / 1024 ** 2 / max(.001, report['upload_seconds']), 3)
        if not args.public and not args.legacy and not args.benchmark_only and not prior:
            check('http_503_429_recovered', {r.get('status') for r in report['retries']} >= {429, 503})
        task = client.task(task_id)
        check('persisted_task_sha256', task['sha256'] == sha and task['upload_status'] == 'completed'
              and task['received_bytes'] == size and task['next_chunk_index'] == math.ceil(size / CHUNK))
        if store is not None:
            with store._connect() as db:
                row = dict(db.execute('SELECT * FROM video_analysis_tasks WHERE task_id=?', (task_id,)).fetchone())
            check('isolated_database_and_file_sha256', row['sha256'] == sha and digest(Path(row['file_path'])) == sha)
        report['step'] = 'source_download'
        save()
        value, downloaded = hashlib.sha256(), 0
        with client.session.get(origin + API + '/upload/media?' + urlencode({'id': task_id, 'asset': 'source'}),
                                stream=True, timeout=(30, 180), allow_redirects=False) as response:
            require(response.status_code == 200, 'source_download_failed')
            for block in response.iter_content(CHUNK):
                value.update(block)
                downloaded += len(block)
        check('download_sha256', downloaded == size and value.hexdigest() == sha)
        if args.wait_worker:
            report['step'] = 'worker'
            save()
            if store is not None:
                from rehab_affect.demo2_media_worker import VideoAnalysisWorker
                worker = VideoAnalysisWorker(store)
                require(worker.start(), 'isolated_worker_did_not_start')
            worker_started = time.monotonic()
            deadline = worker_started + (3600 if args.local_video else 900)
            next_status = worker_started
            while time.monotonic() < deadline:
                task = client.task(task_id)
                report['analysis_status'] = task['analysis_status']
                report['processing_stage'] = task.get('processing_stage')
                report['processing_progress'] = task.get('processing_progress')
                report['worker_seconds'] = round(time.monotonic() - worker_started, 3)
                save()
                if time.monotonic() >= next_status:
                    print(json.dumps({key: report[key] for key in ('step', 'analysis_status', 'processing_progress', 'worker_seconds')}), flush=True)
                    next_status = time.monotonic() + 30
                if task['analysis_status'] in ('evidence_ready', 'completed', 'failed'):
                    break
                time.sleep(3)
            check('worker_ready', task['analysis_status'] in ('evidence_ready', 'completed'))
            result = client.api(API + '/upload/result?' + urlencode({'id': task_id}))
            check('worker_result_source_sha256', result.get('source_sha256') == sha and result.get('task_id') == task_id)
            provenance, summary = result.get('provenance', {}), result.get('summary', {})
            check('real_decoder_no_external_models', provenance.get('video') == 'ffmpeg_full_decode_and_fps_filter'
                  and provenance.get('network_used') is False and provenance.get('models_downloaded') is False
                  and summary.get('decoded_frames', 0) > 0)
            report['media_aggregate'] = dict(duration_sec=result['media']['duration_sec'], has_audio=result['media']['has_audio'],
                decoded_frames=summary['decoded_frames'], sampled_frames=summary.get('sampled_frames'))
            if store is not None:
                with store._connect() as db:
                    persisted = db.execute('SELECT processing_result_json FROM video_analysis_tasks WHERE task_id=?', (task_id,)).fetchone()
                check('persisted_worker_result_matches_api', json.loads(persisted[0]) == result)
        if args.local_video:
            final_stat = source.stat()
            check('original_unchanged', initial_stat.st_size == final_stat.st_size and initial_stat.st_mtime_ns == final_stat.st_mtime_ns
                  and digest(source) == sha)
            check('no_external_connections', report['external_connections_blocked'] == 0)
        report.update(status='passed', step='complete', large_file_verified=size >= 670 * 1024 ** 2)
    except Exception as error:
        report.update(status='failed', failure_code=str(error) if isinstance(error, CheckFailed) else type(error).__name__)
        trace = error.__traceback__
        while trace and trace.tb_next:
            trace = trace.tb_next
        report['failure_site'] = dict(function=trace.tb_frame.f_code.co_name if trace else None,
            line=trace.tb_lineno if trace else None, errno=getattr(error, 'errno', None), winerror=getattr(error, 'winerror', None))
    finally:
        if worker is not None:
            worker.stop(timeout=120)
            report['worker_stopped'] = worker.thread is None or not worker.thread.is_alive()
            if not report['worker_stopped']:
                report.update(status='failed', failure_code='worker_shutdown_timeout')
        for client in clients:
            client.close()
        for server in reversed(servers):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(10)
        save()
        (folder / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps({'status': report['status'], 'step': report['step'], 'failure_code': report.get('failure_code'),
            'upload_seconds': report.get('upload_seconds'), 'report': str(folder / 'report.json')}), flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'status': 'failed', 'code': str(error) if isinstance(error, CheckFailed) else type(error).__name__}))
        raise SystemExit(1)
