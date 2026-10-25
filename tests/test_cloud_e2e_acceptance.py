"""Only synthetic temporary records; never retained-account acceptance."""

import importlib.util
from contextlib import contextmanager
import json
import os
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


SPEC = importlib.util.spec_from_file_location('cloud_e2e_acceptance',
    Path(__file__).resolve().parents[1] / 'scripts' / 'cloud_e2e_acceptance.py')
e2e = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(e2e)


def private_file(path, value):
    path.write_text(value, encoding='utf-8')
    path.chmod(0o600)
    return path


@pytest.mark.parametrize('url', [
    'https://127.0.0.1:80', 'http://example.com', 'http://localhost',
    'http://127.0.0.1.evil', 'http://127.1', 'http://0.0.0.0',
    'http://user:private@127.0.0.1', 'http://127.0.0.1/private',
    'http://127.0.0.1?secret=value', 'http://127.0.0.1#fragment',
    'http://127.0.0.1:99999', '//127.0.0.1',
])
def test_remote_or_ambiguous_urls_rejected(url):
    with pytest.raises(e2e.AcceptanceError, match='unsafe_endpoint'):
        e2e.endpoint(url)


def test_local_literal_urls():
    assert e2e.endpoint('http://127.0.0.1:8765/') == ('127.0.0.1', 8765, 'http://127.0.0.1:8765')
    assert e2e.endpoint('http://[::1]:8765')[0] == '::1'


def test_private_legacy_schools_separate_rotated_admin(tmp_path):
    schools = private_file(tmp_path / 'schools.md', '\n'.join(
        f'| School {i} | t{i} | school-private-{i} |' for i in range(1, 5))
        + '\n| Old admin | old-admin | DO-NOT-USE |')
    admin = private_file(tmp_path / 'admin.json', json.dumps({'username': 'rotated', 'password': 'private-current'}))
    values, current = e2e.load_credentials(schools, admin)
    assert [value['username'] for value in values] == ['t1', 't2', 't3', 't4']
    assert current['username'] == 'rotated'
    admin.unlink()
    with pytest.raises(e2e.AcceptanceError, match='unsafe_credentials'):
        e2e.load_credentials(schools, admin)


def test_json_schools_duplicate_accounts_rejected(tmp_path):
    schools = private_file(tmp_path / 'schools.json', json.dumps([
        {'username': 'same', 'password': 'PRIVATE'} for _ in range(4)]))
    admin = private_file(tmp_path / 'admin.json', '{"username":"admin","password":"PRIVATE"}')
    with pytest.raises(e2e.AcceptanceError, match='invalid_credentials'):
        e2e.load_credentials(schools, admin)


@pytest.mark.skipif(os.name != 'posix', reason='POSIX owner/mode check; Windows uses existing private ACLs')
def test_world_readable_credentials_rejected(tmp_path):
    path = private_file(tmp_path / 'secret', 'PRIVATE')
    path.chmod(0o644)
    with pytest.raises(e2e.AcceptanceError, match='unsafe_credentials'):
        e2e.private_text(path)


def test_symlink_credentials_rejected(tmp_path):
    target = private_file(tmp_path / 'target', 'PRIVATE')
    link = tmp_path / 'link'
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip('Symlink creation unavailable')
    with pytest.raises(e2e.AcceptanceError, match='unsafe_credentials'):
        e2e.private_text(link)


@pytest.fixture
def http_stub():
    state = {'mode': 'ok', 'paths': [], 'body': b'{"ok":true}'}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state['paths'].append(self.path)
            mode = state['mode']
            self.send_response(302 if mode == 'redirect' else 200)
            if mode == 'redirect':
                self.send_header('Location', 'https://never-send-credentials.example/secret')
            if mode == 'oversize':
                self.send_header('Content-Length', str(e2e.MAX_RESPONSE + 1))
            elif mode == 'truncated':
                self.send_header('Content-Length', '100')
            else:
                self.send_header('Content-Length', str(len(state['body'])))
            self.end_headers()
            self.wfile.write(state['body'])

    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield e2e.Client(f'http://127.0.0.1:{httpd.server_port}'), state
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(5)


@pytest.mark.parametrize('mode,code', [('redirect', 'redirect_refused'),
                                      ('oversize', 'response_too_large'),
                                      ('truncated', 'invalid_response')])
def test_http_framing_size_and_redirects(http_stub, mode, code):
    client, state = http_stub
    state['mode'] = mode
    client.cookie = 'rehab_demo2_session=PRIVATE'
    with pytest.raises(e2e.AcceptanceError, match=code):
        client.request(e2e.route('/upload/task', id='synthetic'))
    assert len(state['paths']) == 1


def test_proxy_environment_ignored_and_cookie_jars_separate(http_stub, monkeypatch):
    client, _ = http_stub
    for variable in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy'):
        monkeypatch.setenv(variable, 'http://127.0.0.1:1')
    client.cookie = 'rehab_demo2_session=PRIVATE'
    assert client.json(e2e.route('/upload/task', id='synthetic')) == {'ok': True}
    assert e2e.Client(client.origin).cookie == ''


def test_upload_lost_ack_reconciles_without_duplicate(monkeypatch):
    blob = b'synthetic'

    class Client:
        count = 0

        def request(self, path, **kwargs):
            self.count += 1
            assert kwargs['binary'] == blob and kwargs['timeout'] == 180
            raise e2e.AcceptanceError('network_error')

        def json(self, path):
            return {'task': {'next_chunk_index': 1, 'upload_status': 'completed',
                'received_bytes': len(blob), 'sha256': e2e.hashlib.sha256(blob).hexdigest()}}

    client = Client()
    e2e.upload(client, {'task_id': 'synthetic', 'course_id': 'synthetic'}, blob)
    assert client.count == 1


def test_upload_uses_four_mib_and_bounded_retries(monkeypatch):
    monkeypatch.setattr(e2e.time, 'sleep', lambda _: None)
    calls = []

    class Client:
        def request(self, path, **kwargs):
            calls.append(kwargs['binary'])
            return 503, {}, b'PRIVATE backend error'

        def json(self, path):
            return {'task': {'next_chunk_index': 0}}

    with pytest.raises(e2e.AcceptanceError, match='upload_failed'):
        e2e.upload(Client(), {'task_id': 'synthetic', 'course_id': 'synthetic'}, b'x' * (e2e.CHUNK_SIZE + 1))
    assert len(calls) == 3 and all(len(value) == 4 * 1024 * 1024 for value in calls)


@pytest.mark.parametrize('args', [[], ['--password', 'NEVER-PRINT-THIS'],
    ['--isolated-smoke', '--base-url', 'http://127.0.0.1'],
    ['--base-url', 'http://127.0.0.1', '--account-scope', 'retained'],
    ['--isolated-smoke', '--worker-timeout', '0']])
def test_cli_requires_explicit_scope_and_consent_no_secret_errors(args, capsys):
    assert e2e.main(args) == 1
    output = capsys.readouterr()
    assert output.err == '' and 'NEVER-PRINT-THIS' not in output.out
    assert json.loads(output.out)['error'] == 'invalid_arguments'


def test_cli_masks_dependency_exception(monkeypatch, capsys):
    def fail(*args):
        raise RuntimeError('PRIVATE password/session/student')
    monkeypatch.setattr(e2e, 'smoke_module', fail)
    assert e2e.main(['--isolated-smoke']) == 1
    output = capsys.readouterr()
    assert 'PRIVATE' not in output.out + output.err
    assert json.loads(output.out)['error'] == 'acceptance_failed'


def automatic_workspace():
    return {'task_id': 'synthetic-task',
            'technical_evidence': {'status': 'available', 'source_bound': True},
            'automatic_report': {'kind': 'technical_summary', 'ready': True}}


def test_automatic_report_http_contract(http_stub):
    client, state = http_stub
    state['body'] = json.dumps({'ok': True, 'workspace': automatic_workspace()}).encode()
    e2e.automatic_report(client, 'synthetic-task')
    assert state['paths'] == ['/api/v1/demo2/course-analysis?task_id=synthetic-task']


@pytest.mark.parametrize('field,value', [
    ('task_id', 'another-task'), ('technical_evidence', None), ('technical_evidence', []),
    ('automatic_report', None), ('automatic_report', 'PRIVATE-RAW-ERROR'),
    ('technical_evidence.status', 'unavailable'), ('technical_evidence.status', None),
    ('technical_evidence.source_bound', False), ('technical_evidence.source_bound', 1),
    ('technical_evidence.source_bound', 'true'), ('automatic_report.kind', 'student_score'),
    ('automatic_report.ready', False), ('automatic_report.ready', 1),
    ('automatic_report.ready', 'true'),
])
def test_automatic_report_rejects_unavailable_unbound_wrong_kind_and_truthy(field, value):
    workspace = automatic_workspace()
    parts = field.split('.')
    target = workspace if len(parts) == 1 else workspace[parts[0]]
    target[parts[-1]] = value

    class Client:
        def json(self, path):
            return {'ok': True, 'workspace': workspace}

    with pytest.raises(e2e.AcceptanceError, match='^automatic_report_failed$'):
        e2e.automatic_report(Client(), 'synthetic-task')


@pytest.mark.parametrize('workspace', [None, [], {}, {'task_id': 'synthetic-task'},
    {'task_id': 'synthetic-task', 'report': {'ready': True}}])
def test_missing_new_fields_never_fall_back_to_teacher_report(workspace):
    class Client:
        def json(self, path):
            return {'ok': True, 'workspace': workspace}

    with pytest.raises(e2e.AcceptanceError, match='^automatic_report_failed$'):
        e2e.automatic_report(Client(), 'synthetic-task')


@pytest.mark.parametrize('isolated', [False, True])
@pytest.mark.parametrize('strict', [False, True])
def test_cli_forwards_optional_automatic_report_flag(tmp_path, monkeypatch, capsys, isolated, strict):
    schools = [{'username': f'synthetic-{i}', 'password': 'PRIVATE'} for i in range(4)]
    admin = {'username': 'synthetic-admin', 'password': 'PRIVATE'}
    calls = []

    @contextmanager
    def server(directory):
        yield 'http://127.0.0.1:12345', schools, admin

    def run(*args, **kwargs):
        calls.append(kwargs)
        kwargs['report'].update(ok=True, stage='complete')

    monkeypatch.setattr(e2e, 'isolated_server', server)
    monkeypatch.setattr(e2e, 'generate', lambda *args: [b'synthetic', b'synthetic'])
    monkeypatch.setattr(e2e, 'run', run)
    if isolated:
        args = ['--isolated-smoke']
    else:
        school_file = private_file(tmp_path / 'schools.json', json.dumps(schools))
        admin_file = private_file(tmp_path / 'admin.json', json.dumps(admin))
        args = ['--base-url', 'http://127.0.0.1:12345', '--account-scope', 'retained',
                '--school-credentials-file', str(school_file), '--admin-credentials-file', str(admin_file),
                '--allow-synthetic-uploads']
    if strict:
        args.append('--require-automatic-report')
    assert e2e.main(args) == 0
    assert len(calls) == 1 and calls[0]['require_automatic_report'] is strict
    output = capsys.readouterr()
    assert json.loads(output.out)['ok'] is True
    assert 'PRIVATE' not in output.out + output.err


def test_real_http_four_synthetic_accounts_worker_evidence_admin(tmp_path, monkeypatch):
    media = e2e.smoke_module()._load_media()
    try:
        ffmpeg, ffprobe = (media._resolve_tool(name) for name in ('ffmpeg', 'ffprobe'))
    except Exception:
        pytest.skip('Real FFmpeg/ffprobe unavailable; not an acceptance pass')
    monkeypatch.setenv('REHAB_FFMPEG', str(ffmpeg))
    monkeypatch.setenv('REHAB_FFPROBE', str(ffprobe))
    blobs = e2e.generate(tmp_path, str(ffmpeg))
    with e2e.isolated_server(tmp_path) as (base_url, schools, admin):
        school_file = private_file(tmp_path / 'synthetic-schools.json', json.dumps(schools))
        admin_file = private_file(tmp_path / 'synthetic-admin.json', json.dumps(admin))
        schools, admin = e2e.load_credentials(school_file, admin_file)
        report = e2e.run(base_url, schools, admin, blobs, scope='isolated',
                         worker_timeout=90, poll_seconds=.1)
    assert report['ok'] and report['account_scope'] == 'isolated'
    assert report['retained_account_access_verified'] is False
    assert report['checks']['binary_uploads'] == 4
    assert report['checks']['real_worker_evidence_ready'] == 4
    assert report['checks']['peer_denials'] == 84
    assert report['checks']['admin_query_reports_and_media'] == 4
    assert report['automatic_report_required'] is False
    assert 'automatic_technical_report' in report['not_verified']
    assert 'automatic_technical_reports' not in report['checks']
    serialized = json.dumps(report)
    assert all(item['password'] not in serialized and item['username'] not in serialized
               for item in schools + [admin])
