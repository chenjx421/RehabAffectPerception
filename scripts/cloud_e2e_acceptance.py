"""Loopback HTTP acceptance using synthetic media, never real student recordings.

Isolated smoke (temporary DB, four synthetic schools, real FFmpeg/worker):
    .venv/bin/python scripts/cloud_e2e_acceptance.py --isolated-smoke

Add --require-automatic-report to require source-bound technical evidence and
the ready technical_summary report on each teacher's course-analysis route.
This does not assert student scoring, diagnoses, or teacher-reviewed conclusions.

Existing accounts (creates four synthetic tasks and login/audit records):
    .venv/bin/python scripts/cloud_e2e_acceptance.py \
        --base-url http://127.0.0.1:8765 --account-scope retained \
        --school-credentials-file /private/schools.md \
        --admin-credentials-file /private/admin.json --allow-synthetic-uploads

Schools: existing pilot Markdown rows (t1..t4), or a JSON array of four
{username,password} objects. Admin: separate {username,password} JSON only.
On POSIX credential files must be owned by the current user and mode 0600/0400.
No account creation/reset in existing-account mode. No remote URLs, redirects,
environment proxies, student binding, inference, or destructive server cleanup.
Uploads remain for review; temporary local files are removed. Exit 0 means all
listed checks passed; isolated success never verifies retained school accounts.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import http.client
from http.cookies import SimpleCookie
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlencode, urlsplit
import wave


API = '/api/v1/demo2'
CHUNK_SIZE = 4 * 1024 * 1024
MAX_RESPONSE = 8 * 1024 * 1024
ERRORS = frozenset({
    'invalid_arguments', 'unsafe_endpoint', 'unsafe_credentials', 'invalid_credentials',
    'missing_ffmpeg', 'generation_failed', 'network_error', 'response_too_large',
    'redirect_refused', 'invalid_response', 'http_failed', 'login_failed',
    'school_context_required', 'account_isolation_failed', 'upload_failed',
    'worker_failed', 'worker_timeout', 'evidence_failed', 'download_failed',
    'admin_listing_failed', 'automatic_report_failed', 'acceptance_failed', 'interrupted',
})


class AcceptanceError(Exception):
    def __init__(self, code):
        self.code = code if code in ERRORS else 'acceptance_failed'
        super().__init__(self.code)


def require(condition, code):
    if not condition:
        raise AcceptanceError(code)


def endpoint(value):
    try:
        parsed = urlsplit(value)
        require(parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', '::1'}
                and parsed.username is None and parsed.password is None
                and parsed.path in {'', '/'} and not parsed.query and not parsed.fragment,
                'unsafe_endpoint')
        port = parsed.port or 80
        require(1 <= port <= 65535, 'unsafe_endpoint')
        return parsed.hostname, port, 'http://' + parsed.netloc
    except ValueError:
        raise AcceptanceError('unsafe_endpoint') from None


def private_text(path):
    """Open without following a final symlink and validate the opened descriptor."""
    try:
        path = Path(path)
        require(not path.is_symlink(), 'unsafe_credentials')
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            require(stat.S_ISREG(info.st_mode) and info.st_size <= 128 * 1024,
                    'unsafe_credentials')
            if os.name == 'posix':
                require(info.st_uid == os.geteuid() and not info.st_mode & 0o077,
                        'unsafe_credentials')
            return stream.read(128 * 1024 + 1).decode('utf-8-sig')
    except (OSError, UnicodeError):
        raise AcceptanceError('unsafe_credentials') from None


def credential(value):
    require(isinstance(value, dict), 'invalid_credentials')
    for key in ('username', 'password'):
        require(isinstance(value.get(key), str) and 0 < len(value[key]) <= 512
                and not any(ord(c) < 32 for c in value[key]), 'invalid_credentials')
    return {key: value[key] for key in ('username', 'password')}


def load_credentials(school_path, admin_path):
    school_text = private_text(school_path)
    try:
        if school_text.lstrip().startswith('['):
            schools = json.loads(school_text)
        else:
            rows = [line.split('|') for line in school_text.splitlines()]
            schools = []
            for name in ('t1', 't2', 't3', 't4'):
                matches = [row for row in rows if len(row) > 3 and row[2].strip() == name]
                require(len(matches) == 1, 'invalid_credentials')
                schools.append({'username': name, 'password': matches[0][3].strip()})
        require(isinstance(schools, list) and len(schools) == 4, 'invalid_credentials')
        schools = [credential(value) for value in schools]
        admin = credential(json.loads(private_text(admin_path)))
        require(len({item['username'] for item in schools + [admin]}) == 5,
                'invalid_credentials')
        return schools, admin
    except (ValueError, TypeError):
        raise AcceptanceError('invalid_credentials') from None


class Client:
    """A fixed-origin client: no proxy support, redirects or cookie sharing."""
    def __init__(self, base_url):
        self.host, self.port, self.origin = endpoint(base_url)
        self.cookie = ''

    def request(self, path, *, payload=None, binary=None, headers=None, timeout=30):
        require(path.startswith(API + '/') and not any(ord(c) < 32 for c in path),
                'unsafe_endpoint')
        values = {'Origin': self.origin, 'Accept': 'application/json', 'Connection': 'close'}
        if self.cookie:
            values['Cookie'] = self.cookie
        body = None
        if payload is not None:
            body = json.dumps(payload).encode('utf-8')
            values['Content-Type'] = 'application/json'
        elif binary is not None:
            body = binary
            values['Content-Type'] = 'application/octet-stream'
        values.update(headers or {})
        connection = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        deadline = time.monotonic() + timeout
        try:
            connection.request('GET' if body is None else 'POST', path, body=body, headers=values)
            response = connection.getresponse()
            require(not 300 <= response.status < 400, 'redirect_refused')
            length = response.getheader('Content-Length')
            if length is not None:
                require(length.isdigit(), 'invalid_response')
                require(int(length) <= MAX_RESPONSE, 'response_too_large')
            chunks, total = [], 0
            while True:
                remaining = deadline - time.monotonic()
                require(remaining > 0, 'network_error')
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(65536, MAX_RESPONSE + 1 - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                require(total <= MAX_RESPONSE, 'response_too_large')
            require(length is None or total == int(length), 'invalid_response')
            return response.status, {k.lower(): v for k, v in response.getheaders()}, b''.join(chunks)
        except (OSError, http.client.HTTPException):
            raise AcceptanceError('network_error') from None
        finally:
            connection.close()

    def json(self, path, **kwargs):
        status, _, body = self.request(path, **kwargs)
        require(status == 200, 'http_failed')
        try:
            result = json.loads(body)
        except (ValueError, UnicodeError):
            raise AcceptanceError('invalid_response') from None
        require(isinstance(result, dict) and result.get('ok') is not False, 'invalid_response')
        return result

    def login(self, credentials, role):
        status, headers, body = self.request(API + '/auth/login', payload={**credentials, 'role': role})
        require(status == 200, 'login_failed')
        try:
            data = json.loads(body)
            cookie = SimpleCookie()
            cookie.load(headers.get('set-cookie', ''))
            token = cookie.get('rehab_demo2_session')
            require(data.get('ok') is True and token is not None and bool(token.value), 'login_failed')
            account = data['account']
            require(account['role'] == role, 'login_failed')
            self.cookie = token.OutputString(attrs=[])
            return account
        except (ValueError, KeyError, TypeError):
            raise AcceptanceError('login_failed') from None


def route(name, **query):
    return API + name + ('?' + urlencode(query) if query else '')


def smoke_module():
    spec = importlib.util.spec_from_file_location('_cloud_e2e_media_smoke',
                                                Path(__file__).with_name('cloud_media_smoke.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def generate(directory, ffmpeg):
    tool = ffmpeg or shutil.which('ffmpeg')
    require(bool(tool) and Path(tool).is_file(), 'missing_ffmpeg')
    directory = Path(directory)
    require(directory.is_dir() and not directory.is_symlink(), 'generation_failed')
    paths = [directory / name for name in ('audio.mp4', 'silent.mp4')]
    require(all(not path.exists() and not path.is_symlink() for path in paths), 'generation_failed')
    environment = os.environ.copy()
    environment.pop('FFREPORT', None)
    try:
        blobs = []
        for path, audio in zip(paths, (True, False)):
            # Browser fixtures are separate from the MPEG-4 decoder smoke.
            # Keep the evidence contract: 160x96, 10 fps, two seconds / 20 frames.
            command = [str(tool), '-v', 'error', '-nostdin', '-n', '-f', 'lavfi', '-i',
                       'testsrc2=size=160x96:rate=10:duration=2']
            if audio:
                command += ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=2']
            command += ['-map', '0:v:0', '-c:v', 'libx264', '-profile:v', 'baseline',
                        '-level:v', '3.0', '-pix_fmt', 'yuv420p', '-preset', 'veryfast',
                        '-crf', '20', '-threads', '1', '-tag:v', 'avc1']
            command += (['-map', '1:a:0', '-c:a', 'aac', '-profile:a', 'aac_low',
                         '-b:a', '96k', '-ac', '1', '-ar', '48000'] if audio else ['-an'])
            command += ['-map_metadata', '-1', '-movflags', '+faststart', '-f', 'mp4', str(path)]
            result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, shell=False, timeout=30, env=environment,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            require(result.returncode == 0, 'generation_failed')
            with path.open('rb') as source:
                blob = source.read(2 * 1024 * 1024 + 1)
            require(0 < len(blob) <= 2 * 1024 * 1024, 'generation_failed')
            blobs.append(blob)
        return blobs
    except Exception:
        raise AcceptanceError('generation_failed') from None


def upload(client, task, blob):
    task_id, course_id = task['task_id'], task['course_id']
    for index in range(math.ceil(len(blob) / CHUNK_SIZE)):
        chunk = blob[index * CHUNK_SIZE:(index + 1) * CHUNK_SIZE]
        for attempt in range(3):
            try:
                status, _, _ = client.request(route('/upload/chunks', task_id=task_id,
                    course_id=course_id, chunk_index=index), binary=chunk, timeout=180)
                if status == 200:
                    break
                require(status in {408, 429, 500, 502, 503, 504}, 'upload_failed')
            except AcceptanceError as exc:
                if exc.code != 'network_error':
                    raise
            # An acknowledgment may be lost after the server commits the chunk.
            current = client.json(route('/upload/task', id=task_id))['task']
            next_index = current['next_chunk_index']
            if next_index == index + 1:
                break
            require(next_index == index and attempt < 2, 'upload_failed')
            time.sleep(attempt + 1)
    current = client.json(route('/upload/task', id=task_id))['task']
    require(current['upload_status'] == 'completed' and current['received_bytes'] == len(blob)
            and current['sha256'] == hashlib.sha256(blob).hexdigest(), 'upload_failed')


def automatic_report(client, task_id):
    response = client.json(route('/course-analysis', task_id=task_id))
    workspace = response.get('workspace')
    require(isinstance(workspace, dict) and workspace.get('task_id') == task_id,
            'automatic_report_failed')
    technical = workspace.get('technical_evidence')
    report = workspace.get('automatic_report')
    require(isinstance(technical, dict) and technical.get('status') == 'available'
            and technical.get('source_bound') is True
            and isinstance(report, dict) and report.get('kind') == 'technical_summary'
            and report.get('ready') is True, 'automatic_report_failed')


def evidence(client, task_id, blob, audio, *, require_automatic_report=False):
    status, headers, body = client.request(route('/upload/result', id=task_id))
    require(status == 200 and 'attachment' in headers.get('content-disposition', ''), 'download_failed')
    result = json.loads(body)
    require(result['task_id'] == task_id and result['analysis_status'] == 'evidence_ready'
            and result['source_sha256'] == hashlib.sha256(blob).hexdigest(), 'evidence_failed')
    media, summary = result['media'], result['summary']
    require(abs(media['duration_sec'] - 2) < .1 and (media['width'], media['height']) == (160, 96)
            and summary['decoded_frames'] == 20 and summary['sampled_frames'] == 2
            and media['has_audio'] is audio and media['audio_status'] == ('extracted' if audio else 'absent')
            and result['provenance']['network_used'] is False
            and result['provenance']['models_downloaded'] is False, 'evidence_failed')
    status, _, source = client.request(route('/upload/media', id=task_id, asset='source'))
    require(status == 200 and source == blob, 'download_failed')
    status, headers, part = client.request(route('/upload/media', id=task_id, asset='source'),
                                          headers={'Range': 'bytes=0-127'})
    require(status == 206 and part == blob[:128]
            and headers.get('content-range') == f'bytes 0-127/{len(blob)}', 'download_failed')
    status, _, pcm = client.request(route('/upload/media', id=task_id, asset='audio'))
    if audio:
        require(status == 200, 'download_failed')
        with wave.open(io.BytesIO(pcm)) as wav:
            require((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 16000)
                    and abs(wav.getnframes() - 32000) <= 1, 'evidence_failed')
            samples = list(struct.iter_unpack('<h', wav.readframes(wav.getnframes())))
            require(any(abs(value[0]) > 100 for value in samples), 'evidence_failed')
    else:
        require(status == 404, 'evidence_failed')
    workspace = client.json(route('/identity/workspace', task_id=task_id))['workspace']
    require(len(workspace['frames']) == 2, 'evidence_failed')
    frames = []
    for frame in workspace['frames']:
        path = route('/identity/frame', task_id=task_id, frame_key=frame['frame_key'],
                     frame_revision=workspace['frame_revision'])
        status, headers, image = client.request(path)
        require(status == 200 and headers.get('content-type', '').startswith('image/')
                and (image.startswith(b'\xff\xd8\xff') or image.startswith(b'\x89PNG\r\n\x1a\n')),
                'evidence_failed')
        frames.append(path)
    if require_automatic_report:
        automatic_report(client, task_id)
    return frames


def run(base_url, schools, admin, blobs, *, scope, worker_timeout=300, poll_seconds=1,
        require_automatic_report=False, report=None):
    require(scope in {'isolated', 'retained'} and len(schools) == 4, 'invalid_arguments')
    require(1 <= worker_timeout <= 3600 and 0 < poll_seconds <= 10, 'invalid_arguments')
    report = report if report is not None else {}
    report.update(ok=False, account_scope=scope, retained_account_access_verified=False,
                  automatic_report_required=require_automatic_report,
                  checks={}, stage='preflight', synthetic_tasks_created=0,
                  not_verified=['public_tls_tunnel', 'large_video_slow_network',
                                'student_binding_or_scores', 'historical_data_preservation'])
    if not require_automatic_report:
        report['not_verified'].append('automatic_technical_report')
    clients = [Client(base_url) for _ in range(5)]
    anonymous = Client(base_url)
    tasks, channels, account_ids = [], [], []
    run_id = 'cloud-e2e-' + secrets.token_hex(8)
    try:
        for index, client in enumerate(clients):
            account = client.login(schools[index] if index < 4 else admin,
                                   'school_uploader' if index < 4 else 'company_admin')
            account_ids.append(account['account_id'])
            if index == 4:
                continue
            context = client.json(route('/school/context'))['context']
            require(all(context.get(key) for key in ('city', 'district', 'school_name')), 'school_context_required')
            workspace = client.json(route('/upload/workspace', course_id=run_id))['workspace']
            channel = workspace['channel']['channel_id']
            require(channel == account['bound_channel_id'] and not workspace['tasks']
                    and workspace['quota']['remaining_slots'] > 0, 'account_isolation_failed')
            channels.append(channel)
            require(client.request(route('/admin/summary'))[0] == 403, 'account_isolation_failed')
        require(len(set(account_ids)) == 5 and len(set(channels)) == 4, 'account_isolation_failed')
        require(anonymous.request(route('/admin/summary'))[0] == 401, 'account_isolation_failed')
        report['checks']['five_logins_and_roles'] = True
        report['stage'] = 'upload'
        for index, client in enumerate(clients[:4]):
            blob = blobs[index % 2]
            # Never retry ambiguous task creation: that could consume another slot.
            task = client.json(route('/upload/tasks'), payload={
                'channel_id': channels[index], 'course_id': run_id,
                'course_name': 'SYNTHETIC HTTP acceptance', 'session_id': run_id + '-' + str(index),
                'uploader_name': 'SYNTHETIC acceptance', 'filename': 'synthetic.mp4',
                'mime_type': 'video/mp4', 'byte_size': len(blob),
                'total_chunks': math.ceil(len(blob) / CHUNK_SIZE), 'security_confirmed': True,
                'allow_company_archive': False})['task']
            require(task['account_id'] == account_ids[index] and task['channel_id'] == channels[index]
                    and task['course_id'] == run_id, 'account_isolation_failed')
            tasks.append(task['task_id'])
            report['synthetic_tasks_created'] = len(tasks)
            upload(client, task, blob)
        report['checks']['binary_uploads'] = 4
        report['stage'] = 'worker'
        deadline = time.monotonic() + worker_timeout
        pending = set(range(4))
        while pending:
            for index in list(pending):
                task = clients[index].json(route('/upload/task', id=tasks[index]))['task']
                require(task['analysis_status'] not in {'failed', 'cancelled'}, 'worker_failed')
                if task['analysis_status'] == 'evidence_ready':
                    pending.remove(index)
            if pending:
                require(time.monotonic() < deadline, 'worker_timeout')
                time.sleep(poll_seconds)
        report['checks']['real_worker_evidence_ready'] = 4
        report['stage'] = 'evidence_and_isolation'
        denials = 0
        for index, task_id in enumerate(tasks):
            frames = evidence(clients[index], task_id, blobs[index % 2], index % 2 == 0,
                              require_automatic_report=require_automatic_report)
            paths = [route('/upload/task', id=task_id), route('/upload/result', id=task_id),
                     route('/upload/media', id=task_id, asset='source'),
                     route('/upload/media', id=task_id, asset='audio'),
                     route('/identity/workspace', task_id=task_id), *frames]
            for other, client in enumerate(clients[:4]):
                if other == index:
                    continue
                for path in paths:
                    require(client.request(path)[0] in {403, 404}, 'account_isolation_failed')
                    denials += 1
            for path in paths:
                require(anonymous.request(path)[0] == 401, 'account_isolation_failed')
            workspace = clients[index].json(route('/upload/workspace', course_id=run_id))['workspace']
            require({item['task_id'] for item in workspace['tasks']} == {task_id}, 'account_isolation_failed')
        report['checks'].update(peer_denials=denials, anonymous_denials=28,
                                teacher_reports_and_media=4, automatic_frame_downloads=8)
        if require_automatic_report:
            report['checks']['source_bound_technical_evidence'] = 4
            report['checks']['automatic_technical_reports'] = 4
        report['stage'] = 'admin'
        found = set()
        for page in range(1, 101):
            summary = clients[4].json(route('/admin/summary', upload_page=page))['summary']
            found.update(item['task_id'] for item in summary['recent_uploads'] if item['task_id'] in tasks)
            if found == set(tasks) or page >= summary['upload_pagination']['total_pages']:
                break
        require(found == set(tasks), 'admin_listing_failed')
        for index, task_id in enumerate(tasks):
            task = clients[4].json(route('/upload/task', id=task_id))['task']
            require(task['task_id'] == task_id, 'admin_listing_failed')
            evidence(clients[4], task_id, blobs[index % 2], index % 2 == 0)
        report['checks']['admin_query_reports_and_media'] = 4
        report.update(ok=True, stage='complete', retained_account_access_verified=scope == 'retained')
        return report
    finally:
        # Revoke only sessions created by this invocation; never other sessions.
        for client in clients:
            if client.cookie:
                try:
                    client.request(route('/auth/logout'), payload={})
                except Exception:
                    pass
                client.cookie = ''


@contextmanager
def isolated_server(directory):
    """Only called by explicit isolated smoke/tests; no production paths involved."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
    from rehab_affect import scenario_lab_server as server
    from rehab_affect.student_record_store import Demo2StudentRecordStore
    from rehab_affect.demo2_media_worker import VideoAnalysisWorker

    previous = os.environ.get('REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX')
    prefix = secrets.token_urlsafe(24) + '-'
    os.environ['REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX'] = prefix
    original = server.get_demo2_student_store
    httpd = worker = thread = None
    try:
        records = Demo2StudentRecordStore(directory / 'isolated.sqlite3', directory / 'uploads')
        schools = [{'username': f'school_uploader_{i:02d}', 'password': prefix + f'school_uploader_{i:02d}'}
                   for i in range(1, 5)]
        admin = {'username': 'company_admin', 'password': prefix + 'company_admin'}
        for item in schools:
            account = records.authenticate_account(item['username'], item['password'])
            token = records.create_account_session(account['account_id'])['token']
            records.save_account_school_context(token, {'city': 'SYNTHETIC city',
                'district': 'SYNTHETIC district', 'school_name': 'SYNTHETIC school'})
        server.get_demo2_student_store = lambda: records
        handler = server.create_handler(scenario_dir=directory, model_path=directory / 'unused', policy_name='rule')
        handler.log_message = lambda *args, **kwargs: None
        httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        worker = VideoAnalysisWorker(records, poll_seconds=.1)
        worker.start()
        yield f'http://127.0.0.1:{httpd.server_port}', schools, admin
    finally:
        if worker is not None:
            worker.stop()
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if thread is not None:
            thread.join(5)
        server.get_demo2_student_store = original
        if previous is None:
            os.environ.pop('REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX', None)
        else:
            os.environ['REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX'] = previous


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise AcceptanceError('invalid_arguments')


def main(argv=None):
    report = {'ok': False, 'stage': 'arguments', 'retained_account_access_verified': False}
    try:
        parser = Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument('--isolated-smoke', action='store_true')
        parser.add_argument('--base-url')
        parser.add_argument('--account-scope', choices=['retained', 'isolated'])
        parser.add_argument('--school-credentials-file', type=Path)
        parser.add_argument('--admin-credentials-file', type=Path)
        parser.add_argument('--allow-synthetic-uploads', action='store_true')
        parser.add_argument('--require-automatic-report', action='store_true',
                            help='Require source-bound evidence and a ready technical summary for all four uploads.')
        parser.add_argument('--ffmpeg')
        parser.add_argument('--worker-timeout', type=int, default=300)
        args = parser.parse_args(argv)
        require(1 <= args.worker_timeout <= 3600, 'invalid_arguments')
        if args.isolated_smoke:
            require(not any((args.base_url, args.account_scope, args.school_credentials_file,
                             args.admin_credentials_file, args.allow_synthetic_uploads)), 'invalid_arguments')
        else:
            require(all((args.base_url, args.account_scope, args.school_credentials_file,
                         args.admin_credentials_file, args.allow_synthetic_uploads)), 'invalid_arguments')
            endpoint(args.base_url)
            schools, admin = load_credentials(args.school_credentials_file, args.admin_credentials_file)
        report['stage'] = 'generation'
        # Existing smoke suppression also covers native dependency diagnostics.
        with smoke_module()._quiet(), tempfile.TemporaryDirectory(prefix='rehab-cloud-e2e-') as temporary:
            directory = Path(temporary)
            blobs = generate(directory, args.ffmpeg)
            if args.isolated_smoke:
                with isolated_server(directory) as (base_url, schools, admin):
                    run(base_url, schools, admin, blobs, scope='isolated',
                        worker_timeout=args.worker_timeout,
                        require_automatic_report=args.require_automatic_report, report=report)
            else:
                run(args.base_url, schools, admin, blobs, scope=args.account_scope,
                    worker_timeout=args.worker_timeout,
                    require_automatic_report=args.require_automatic_report, report=report)
    except KeyboardInterrupt:
        report.update(ok=False, error='interrupted')
    except Exception as exc:
        report.update(ok=False, error=exc.code if isinstance(exc, AcceptanceError) else 'acceptance_failed')
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
