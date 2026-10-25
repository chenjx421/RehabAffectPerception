"""Clone-context initializer tests using synthetic accounts and temporary DB only."""
import copy
import importlib.util
import json
from pathlib import Path
import threading

import pytest


SPEC = importlib.util.spec_from_file_location('cloud_initialize_test_context',
    Path(__file__).resolve().parents[1] / 'scripts' / 'cloud_initialize_test_context.py')
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


@pytest.fixture
def fake_clients(monkeypatch):
    states = [{'context': {'city': '', 'district': '', 'school_name': ''}, 'details': {},
               'selection_enabled': True, 'context_change_allowed': True} for _ in range(4)]
    states[0]['context'] = {'city': 'PRIVATE CITY', 'district': 'PRIVATE DISTRICT', 'school_name': 'PRIVATE SCHOOL'}
    states[0]['details'] = {'selection_source': 'existing', 'source_status': 'pending'}
    calls = []
    created = []

    class Client:
        def __init__(self, url):
            self.index = len(created)
            self.cookie = ''
            created.append(self)

        def login(self, credential, role):
            self.cookie = 'PRIVATE COOKIE'
            return {'account_id': f'account-{self.index}'}

        def json(self, path, **kwargs):
            if 'payload' in kwargs:
                payload = kwargs['payload']
                calls.append((self.index, payload))
                assert payload['expected_context'] == states[self.index]['context']
                states[self.index]['context'] = {key: payload[key] for key in tool.FIELDS}
                states[self.index]['details'] = {'selection_source': 'other', 'source_status': 'pending', 'address_status': 'pending'}
            return copy.deepcopy(states[self.index])

        def request(self, path, **kwargs):
            assert path.endswith('/auth/logout')
            return 200, {}, b'{}'

    monkeypatch.setattr(tool.base, 'Client', Client)
    return states, calls, created


def test_inspect_saves_all_originals_without_posts(tmp_path, fake_clients):
    states, calls, _ = fake_clients
    backup = tmp_path / 'private.json'
    report = tool.initialize('http://127.0.0.1:1', [{}] * 4, backup)
    saved = json.loads(backup.read_text())
    assert report['ok'] and report['changed'] == 0 and not calls
    assert [row['context'] for row in saved['accounts']] == [row['context'] for row in states]
    assert 'PRIVATE COOKIE' not in backup.read_text()
    assert 'PRIVATE SCHOOL' not in json.dumps(report)


def test_apply_skips_complete_and_uses_other_compare_and_save(tmp_path, fake_clients):
    states, calls, clients = fake_clients
    original = copy.deepcopy(states[0])
    report = tool.initialize('http://127.0.0.1:1', [{}] * 4, tmp_path / 'private.json', apply=True)
    assert report['ok'] and report['changed'] == 3
    assert states[0] == original
    assert [index for index, _ in calls] == [1, 2, 3]
    assert all(payload['selection_source'] == 'other' and payload['confirmed'] is True for _, payload in calls)
    assert all(not client.cookie for client in clients)


def test_locked_incomplete_refuses_all_posts_after_backup(tmp_path, fake_clients):
    states, calls, _ = fake_clients
    states[3]['context_change_allowed'] = False
    backup = tmp_path / 'private.json'
    with pytest.raises(tool.Refused, match='locked'):
        tool.initialize('http://127.0.0.1:1', [{}] * 4, backup, apply=True)
    assert backup.is_file() and calls == []


def test_backup_cannot_overwrite_existing_file(tmp_path, fake_clients):
    _, calls, _ = fake_clients
    backup = tmp_path / 'private.json'
    backup.write_text('original')
    with pytest.raises(FileExistsError):
        tool.initialize('http://127.0.0.1:1', [{}] * 4, backup, apply=True)
    assert backup.read_text() == 'original' and calls == []


def test_cli_refuses_windows_and_masks_argument_values(monkeypatch, capsys):
    monkeypatch.setattr(tool.sys, 'platform', 'win32')
    assert tool.main(['--base-url', 'http://127.0.0.1:1', '--school-credentials-file', 'PRIVATE',
                      '--backup', 'PRIVATE-BACKUP', '--confirm-cloud-preview-clone', '--apply']) == 1
    captured = capsys.readouterr()
    assert 'PRIVATE' not in captured.out + captured.err
    assert json.loads(captured.out)['changed'] == 0


def test_real_http_other_selection_on_fresh_synthetic_store(tmp_path, monkeypatch):
    from rehab_affect import scenario_lab_server as server
    from rehab_affect.student_record_store import Demo2StudentRecordStore

    monkeypatch.setenv('REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX', 'ContextTest-')
    records = Demo2StudentRecordStore(tmp_path / 'synthetic.sqlite3', tmp_path / 'uploads')
    credentials = [{'username': f'school_uploader_{i:02d}', 'password': f'ContextTest-school_uploader_{i:02d}'}
                   for i in range(1, 5)]
    first = records.authenticate_account(credentials[0]['username'], credentials[0]['password'])
    token = records.create_account_session(first['account_id'])['token']
    original = {'city': 'SYNTHETIC CITY', 'district': 'SYNTHETIC DISTRICT', 'school_name': 'SYNTHETIC EXISTING SCHOOL'}
    records.save_account_school_context(token, original)
    monkeypatch.setattr(server, 'get_demo2_student_store', lambda: records)
    handler = server.create_handler(scenario_dir=tmp_path, model_path=tmp_path / 'unused', policy_name='rule')
    handler.log_message = lambda *args, **kwargs: None
    httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        backup = tmp_path / 'original-contexts.json'
        result = tool.initialize(f'http://127.0.0.1:{httpd.server_port}', credentials, backup, apply=True)
        assert result['ok'] and result['changed'] == 3
        assert records.account_school_context(token)['context'] == original
        saved = json.loads(backup.read_text())
        assert saved['accounts'][0]['context'] == original
        assert saved['accounts'][1]['context'] == {key: '' for key in tool.FIELDS}
        with records._connect() as connection:
            assert connection.execute('SELECT COUNT(*) FROM video_analysis_tasks').fetchone()[0] == 0
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(5)
