"""Synthetic files and local stubs only; never open real student material."""
import hashlib
import importlib.util
import json
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


SPEC = importlib.util.spec_from_file_location('cloud_real_sample_acceptance',
    Path(__file__).resolve().parents[1] / 'scripts/cloud_real_sample_acceptance.py')
real = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(real)


def sample_file(tmp_path, size=2 * 1024 * 1024 + 11):
    path = tmp_path / 'synthetic.mp4'
    path.write_bytes(b'x' * size)
    return {'sample_id': 'Sample01', 'path': path, 'size_bytes': size,
            'sha256': hashlib.sha256(b'x' * size).hexdigest(), 'stamp': real.stamp(path)}


@pytest.mark.parametrize('relative', [None, '', '../private.mp4', '/private.mp4',
    'C:/private.mp4', 'a\\b.mp4', 'folder/../private.mp4', './private.mp4'])
def test_unsafe_or_unresolved_manifest_path_refused(tmp_path, relative):
    with pytest.raises(real.CheckError):
        real.controlled_path(tmp_path, relative)


def test_stream_upload_four_mib_and_tail_lost_ack(tmp_path):
    sample = sample_file(tmp_path, real.base.CHUNK_SIZE + 7)
    lengths = []

    class Client:
        def request(self, path, **kwargs):
            lengths.append(len(kwargs['binary']))
            assert kwargs['timeout'] == 180
            if len(lengths) == 1:
                raise real.base.AcceptanceError('network_error')
            return 200, {}, b'PRIVATE RESPONSE MUST NOT PRINT'

        def json(self, path):
            return {'task': {'next_chunk_index': 1, 'upload_status': 'completed',
                             'received_bytes': sample['size_bytes'], 'sha256': sample['sha256']}}

    real.upload_file(Client(), {'task_id': 'test', 'course_id': 'test'}, sample)
    assert lengths == [4 * 1024 * 1024, 7]


def test_changed_copy_refused_before_upload(tmp_path):
    sample = sample_file(tmp_path, 10)
    sample['path'].write_bytes(b'changed')

    class Client:
        def request(self, *args, **kwargs):
            pytest.fail('must not send a changed source')

    with pytest.raises(real.CheckError, match='sample_changed'):
        real.upload_file(Client(), {'task_id': 'test', 'course_id': 'test'}, sample)


def test_chunk_retry_bounded_and_storage_failure_not_retried(tmp_path, monkeypatch):
    sample = sample_file(tmp_path, 10)
    monkeypatch.setattr(real.time, 'sleep', lambda _: None)

    class Client:
        calls = 0
        status = 503

        def request(self, *args, **kwargs):
            self.calls += 1
            return self.status, {}, b'private'

        def json(self, path):
            return {'task': {'next_chunk_index': 0}}

    client = Client()
    with pytest.raises(real.CheckError, match='chunk_retries_exhausted'):
        real.upload_file(client, {'task_id': 'test', 'course_id': 'test'}, sample)
    assert client.calls == 3
    client.status, client.calls = 507, 0
    with pytest.raises(real.CheckError, match='chunk_upload_rejected'):
        real.upload_file(client, {'task_id': 'test', 'course_id': 'test'}, sample)
    assert client.calls == 1


@pytest.fixture
def download_server():
    state = {'body': b'x' * (2 * 1024 * 1024 + 11), 'status': 200, 'requests': 0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            state['requests'] += 1
            self.send_response(state['status'])
            self.send_header('Content-Length', str(len(state['body'])))
            if state['status'] == 302:
                self.send_header('Location', 'https://must-not-follow.example')
            self.end_headers()
            try:
                for index in range(0, len(state['body']), 65536):
                    self.wfile.write(state['body'][index:index + 65536])
            except (ConnectionError, OSError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield real.base.Client(f'http://127.0.0.1:{server.server_port}'), state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)


def test_stream_download_hash_and_refuse_redirect(tmp_path, download_server):
    sample = sample_file(tmp_path)
    client, state = download_server
    real.download_hash(client, 'test', sample)
    state['status'] = 302
    with pytest.raises(real.CheckError, match='source_download_failed'):
        real.download_hash(client, 'test', sample)
    assert state['requests'] == 2


def test_stream_download_hash_mismatch(tmp_path, download_server):
    sample = sample_file(tmp_path)
    sample['sha256'] = '0' * 64
    client, _ = download_server
    with pytest.raises(real.CheckError, match='download_hash_mismatch'):
        real.download_hash(client, 'test', sample)


def test_manifest_rehashes_all_copies_without_network(tmp_path, monkeypatch):
    rows = []
    for index in range(1, 5):
        path = tmp_path / f'Sample{index:02d}.mp4'
        data = bytes([index]) * 10
        path.write_bytes(data)
        rows.append({'sample_id': path.stem, 'relative_path': path.name,
                     'size_bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'schema_version': 1, 'samples': rows}))
    manifest.chmod(0o600)
    monkeypatch.setattr(real, 'probe', lambda *args: {'duration_sec': 1, 'width': 1, 'height': 1, 'has_audio': False})
    result = real.load_samples(manifest, tmp_path)
    assert len(result) == 4
    (tmp_path / 'Sample04.mp4').write_bytes(b'corrupted!')
    with pytest.raises(real.CheckError, match='sample_hash_mismatch'):
        real.load_samples(manifest, tmp_path)


def test_cli_requires_explicit_real_upload_consent(capsys):
    assert real.main([]) == 1
    assert 'invalid_arguments' in capsys.readouterr().out


def test_cli_report_is_private_exclusive_and_exception_sanitized(tmp_path, monkeypatch, capsys):
    report = tmp_path / 'report.json'
    args = ['--base-url', 'http://127.0.0.1:1', '--manifest', 'private.json', '--media-root', str(tmp_path),
            '--school-credentials-file', 'private-school.json', '--admin-credentials-file', 'private-admin.json',
            '--report', str(report), '--allow-real-sample-uploads']

    def fail(*args):
        raise RuntimeError('PRIVATE student/password/response')

    monkeypatch.setattr(real, 'run', fail)
    assert real.main(args) == 1
    captured = capsys.readouterr()
    saved = report.read_text()
    assert 'PRIVATE' not in captured.out + captured.err + saved
    assert json.loads(saved)['error'] == 'acceptance_failed'
    assert json.loads(saved)['legal_authorization_verified'] is False
    assert real.main(args) == 1
    assert report.read_text() == saved
