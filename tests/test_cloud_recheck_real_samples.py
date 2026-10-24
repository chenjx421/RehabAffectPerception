"""Synthetic files and transport stubs only; never use the live cloud service."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from scripts import cloud_recheck_real_samples as qa


@pytest.fixture
def rig(tmp_path, monkeypatch):
    samples = []
    for index, alias in enumerate(qa.TASKS, 1):
        data = bytes([index]) * 256
        path = tmp_path / (alias + '.mp4')
        path.write_bytes(data)
        samples.append({'sample_id': alias, 'path': path, 'size_bytes': len(data),
                        'sha256': hashlib.sha256(data).hexdigest(), 'stamp': qa.real.stamp(path),
                        'media': {'has_audio': True}})
    credentials = [{'username': str(index), 'password': 'SYNTHETIC-PRIVATE-PASSWORD'}
                   for index in range(5)]
    monkeypatch.setattr(qa.real, 'load_samples', lambda *args: samples)
    monkeypatch.setattr(qa.base, 'load_credentials', lambda *args: (credentials[:4], credentials[4]))
    requests, verifications = [], []
    contexts = {index: {'city': 'SYNTHETIC', 'district': 'SYNTHETIC', 'school_name': 'PRIVATE SCHOOL'}
                for index in range(4)}
    tasks = {}
    for index, sample in enumerate(samples):
        task_id = qa.TASKS[sample['sample_id']]
        tasks[task_id] = {'task_id': task_id, 'account_id': str(index),
                          'channel_id': 'channel_' + str(index + 1),
                          'sha256': sample['sha256'], 'byte_size': sample['size_bytes'],
                          'upload_status': 'completed', 'analysis_status': 'evidence_ready',
                          'course_id': 'synthetic-course',
                          'course_name': 'Authorized real sample acceptance'}

    def transport(client, path, *, payload=None, binary=None, **kwargs):
        requests.append((path, payload))
        parsed = urlsplit(path)
        route = parsed.path.removeprefix(qa.base.API)
        query = parse_qs(parsed.query)
        headers = {}
        body = {'ok': True}
        status = 200
        if route == '/auth/login':
            client.index = int(payload['username'])
            body['account'] = {'account_id': str(client.index), 'role': payload['role'],
                               'bound_channel_id': 'channel_' + str(client.index + 1)}
            headers['set-cookie'] = 'rehab_demo2_session=SYNTHETIC-COOKIE-' + str(client.index)
        elif route == '/school/context':
            body['context'] = contexts[client.index]
        elif route == '/auth/logout':
            pass
        else:
            task = tasks[query.get('id', query.get('task_id'))[0]]
            owner = getattr(client, 'index', None)
            if owner is None:
                status = 401
            elif route == '/course-analysis' and owner == 4:
                status = 403
            elif str(owner) != task['account_id'] and owner != 4:
                status = 404
            elif route == '/upload/task':
                body['task'] = task
        return status, headers, json.dumps(body).encode()

    monkeypatch.setattr(qa.base.Client, 'request', transport)

    def verify(client, task_id, sample, *, teacher):
        verifications.append((client.index, task_id, sample['sample_id'], teacher))

    monkeypatch.setattr(qa.real, 'verify', verify)
    args = SimpleNamespace(base_url='http://127.0.0.1:8793', manifest=tmp_path / 'manifest.json',
                           media_root=tmp_path, school_credentials_file=tmp_path / 'schools.json',
                           admin_credentials_file=tmp_path / 'admin.json', ffprobe=None)
    return SimpleNamespace(args=args, samples=samples, requests=requests,
                           verifications=verifications, tasks=tasks, contexts=contexts)


def test_four_existing_tasks_teacher_admin_and_isolation_no_writes(rig):
    report = {'ok': False, 'samples': []}
    qa.run(rig.args, report)
    assert report['ok'] and report['stage'] == 'complete'
    assert len(report['samples']) == 4
    assert all(row['passed'] for row in report['samples'])
    assert len(rig.verifications) == 8
    assert sum(teacher for _, _, _, teacher in rig.verifications) == 4
    assert {task_id for _, task_id, _, _ in rig.verifications} == set(qa.TASKS.values())
    assert all(path.endswith(('/auth/login', '/auth/logout'))
               for path, payload in rig.requests if payload is not None)
    assert sum(path.endswith('/auth/login') for path, _ in rig.requests) == 5
    assert sum(path.endswith('/auth/logout') for path, _ in rig.requests) == 5
    for row in report['samples']:
        assert row['checks']['teacher']['source_bound_technical_summary_twice']
        assert row['checks']['admin']['full_media_download_hash']
        assert row['checks']['admin_classroom_analysis_denied']
        assert row['checks']['other_three_accounts_denied']
        assert row['checks']['anonymous_denied']
    output = json.dumps(report)
    assert 'PRIVATE' not in output and 'COOKIE' not in output
    assert not any(task_id in output for task_id in qa.TASKS.values())


@pytest.mark.parametrize('context', [{}, None, {'city': 'PRIVATE CITY'}])
def test_incomplete_context_is_only_an_anonymous_hint_and_never_filled(rig, context):
    for index in range(1, 4):
        rig.contexts[index] = context
    report = {'ok': False, 'samples': []}
    qa.run(rig.args, report)
    assert report['ok'] and len(rig.verifications) == 8
    assert report['school_context_completeness'] == {
        'Sample01': True, 'Sample02': False, 'Sample03': False, 'Sample04': False}
    assert 'PRIVATE' not in json.dumps(report)
    assert all(payload is None for path, payload in rig.requests if path.endswith('/school/context'))


def test_incomplete_context_does_not_bypass_real_task_api_denial(rig):
    rig.contexts[1] = {}
    rig.tasks[qa.TASKS['Sample02']]['account_id'] = 'another-account'
    report = {'ok': False, 'samples': []}
    with pytest.raises(qa.base.AcceptanceError, match='http_failed'):
        qa.run(rig.args, report)
    assert not report['ok']
    assert report['school_context_completeness']['Sample02'] is False
    assert rig.verifications == []
    assert sum(path.endswith('/auth/logout') for path, _ in rig.requests) == 5


@pytest.mark.parametrize('mutation,code', [
    ('sha256', 'task_source_mismatch'), ('channel_id', 'task_scope_mismatch'),
    ('analysis_status', 'task_not_ready'), ('course_id', 'task_course_mismatch'),
])
def test_preflight_blocks_wrong_sources_ownership_state_and_course(rig, mutation, code):
    first = next(iter(rig.tasks.values()))
    first[mutation] = 'SYNTHETIC-WRONG'
    with pytest.raises(qa.real.CheckError, match=code):
        qa.run(rig.args, {'ok': False, 'samples': []})
    assert rig.verifications == []
    assert sum(path.endswith('/auth/logout') for path, _ in rig.requests) == 5


@pytest.mark.parametrize('path,kwargs', [
    ('/upload/tasks', {'payload': {}}), ('/upload/chunks', {'binary': b'NOT SENT'}),
    ('/upload/reprocess', {'payload': {}}), ('/school/context', {'payload': {}}),
    ('/dossier/authorization', {'payload': {'confirmed': True}}),
    ('/upload/task?id=unknown', {}), ('/upload/media?id=unknown&asset=source', {}),
])
def test_transport_guard_blocks_all_mutating_or_unlisted_task_requests(monkeypatch, path, kwargs):
    def forbidden(*args, **kwargs):
        pytest.fail('Blocked request reached transport')
    monkeypatch.setattr(qa.base.Client, 'request', forbidden)
    client = qa.ReadOnlyClient('http://127.0.0.1:8793')
    with pytest.raises(qa.real.CheckError, match='request_not_read_only'):
        client.request(qa.base.API + path, **kwargs)


def cli_args(tmp_path):
    return ['--base-url', 'http://127.0.0.1:8793', '--manifest', 'NOT-OPENED.json',
            '--media-root', str(tmp_path), '--school-credentials-file', 'NOT-OPENED-school.json',
            '--admin-credentials-file', 'NOT-OPENED-admin.json', '--report', str(tmp_path / 'new-report.json')]


def test_private_exclusive_report_and_sanitized_failures(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(qa.sys, 'platform', 'linux')
    if qa.os.name == 'posix':
        tmp_path.chmod(0o700)
    def fail(*args):
        raise RuntimeError('PRIVATE credential/student/raw-result')
    monkeypatch.setattr(qa, 'run', fail)
    args = cli_args(tmp_path)
    assert qa.main(args) == 1
    report = tmp_path / 'new-report.json'
    saved = report.read_bytes()
    result = json.loads(saved)
    assert result['error'] == 'recheck_failed'
    assert result['new_tasks_created'] == result['uploads_attempted'] == 0
    assert not result['reprocessing_requested']
    assert 'PRIVATE' not in capsys.readouterr().out + saved.decode()
    assert qa.main(args) == 1
    assert json.loads(capsys.readouterr().out)['error'] == 'report_already_exists'
    assert report.read_bytes() == saved
    if qa.os.name == 'posix':
        assert report.stat().st_mode & 0o777 == 0o600


def test_windows_refused_before_report_files_credentials_or_network(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(qa.sys, 'platform', 'win32')
    monkeypatch.setattr(qa, 'run', lambda *args: pytest.fail('No service access allowed'))
    assert qa.main(cli_args(tmp_path)) == 1
    assert json.loads(capsys.readouterr().out)['error'] == 'linux_cloud_recheck_required'
    assert not (tmp_path / 'new-report.json').exists()
