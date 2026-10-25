"""Synthetic temporary databases and loopback HTTP only; no live instance."""
from __future__ import annotations

import json
import sqlite3
import threading
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

from scripts import cloud_student_acceptance as qa


@pytest.fixture
def references():
    return {'manifest_id': 'synthetic-manifest-001', 'entries': {
        alias: 'synthetic-reference-' + str(index) for index, alias in enumerate(qa.ALIASES)}}


@pytest.fixture
def rig(tmp_path, monkeypatch):
    from src.rehab_affect import scenario_lab_server as server
    from src.rehab_affect.student_record_store import Demo2StudentRecordStore

    prefix = 'TEMPORARY-ANONYMOUS-QA-'
    monkeypatch.setenv('REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX', prefix)
    monkeypatch.setenv('REHAB_DEMO2_DOSSIER_KEY', Fernet.generate_key().decode())
    database = tmp_path / 'clone.sqlite3'
    records = Demo2StudentRecordStore(database, tmp_path / 'uploads')
    monkeypatch.setattr(server, 'get_demo2_student_store', lambda: records)
    credentials = [{'username': f'school_uploader_{index:02d}',
                    'password': prefix + f'school_uploader_{index:02d}'} for index in range(1, 5)]
    credentials.append({'username': 'company_admin', 'password': prefix + 'company_admin'})
    tokens = []
    for item in credentials[:4]:
        account = records.authenticate_account(item['username'], item['password'])
        token = records.create_account_session(account['account_id'])['token']
        tokens.append(token)
        records.save_account_school_context(token, {
            'city': 'SYNTHETIC city', 'district': 'SYNTHETIC district', 'school_name': 'SYNTHETIC school'})
    handler = server.create_handler(scenario_dir=tmp_path, model_path=tmp_path / 'unused', policy_name='rule')
    handler.log_message = lambda *args, **kwargs: None
    httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        clients = [qa.Client(f'http://127.0.0.1:{httpd.server_port}') for _ in credentials]
        accounts = [client.login(item, 'company_admin' if index == 4 else 'school_uploader')
                    for index, (client, item) in enumerate(zip(clients, credentials))]
        yield SimpleNamespace(db=database, records=records, clients=clients, accounts=accounts, tokens=tokens)
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(5)
        assert not thread.is_alive()


def test_http_negative_controls_idempotence_and_no_confirmation(rig, references, monkeypatch):
    requests = []
    responses = []
    original = qa.Client.request

    def spy(self, path, **kwargs):
        requests.append((path, kwargs.get('payload')))
        result = original(self, path, **kwargs)
        body = json.loads(result[2])
        responses.append((path.split('?')[0], result[0], body.get('error', {}).get('code')))
        return result

    monkeypatch.setattr(qa.Client, 'request', spy)
    for created, reused in ((3, 0), (0, 3)):
        report = qa.run_checks(rig.clients, rig.accounts, rig.db, references)
        assert report['status'] == 'partial', (report.get('code'), responses)
        assert report['test_records_created'] == created
        assert report['test_records_reused'] == reused
        assert report['unauthorized_rows_persisted'] == 0
        assert report['bindings_created'] == 0
        assert not report['real_students_enrolled']
        assert not report['guardian_authorization_confirmed']
        assert len(report['checks']) == 8
        output = json.dumps(report)
        for value in (references['manifest_id'], *references['entries'].values(),
                      *(account['account_id'] for account in rig.accounts),
                      *(client.cookie for client in rig.clients)):
            assert value not in output
    with qa.safe_db(rig.db) as connection:
        assert connection.execute('SELECT count(*) FROM demo2_identity_students').fetchone()[0] == 3
        assert connection.execute('SELECT count(*) FROM demo2_identity_bindings').fetchone()[0] == 0
    for path, payload in requests:
        if payload is not None:
            assert path != qa.API + '/school/context'
            assert '/binding' not in path
            assert payload.get('confirmed') is not True
            assert payload.get('reviewed') is not True


def test_wrong_database_session_proof_prevents_roster_creation(rig, references, tmp_path):
    other = tmp_path / 'unrelated.sqlite3'
    with sqlite3.connect(other) as connection:
        connection.execute('CREATE TABLE account_sessions(token_hash TEXT, account_id TEXT)')
    report = qa.run_checks(rig.clients, rig.accounts, other, references)
    assert report['status'] == 'blocked'
    assert report['code'] == 'api_clone_database_mismatch'
    assert report['test_records_created'] == 0
    assert qa.get(rig.clients[0], '/identity/roster')['roster']['students'] == []


def test_alias_collision_never_overwrites_or_partially_creates(rig, references):
    status, _ = qa.call(rig.clients[0], '/identity/students', {
        'display_name': 'Student-C', 'student_code': 'EXISTING-TEST', 'class_name': 'OTHER', 'note': 'untouched'})
    assert status == 200
    before = qa.get(rig.clients[0], '/identity/roster')['roster']
    report = qa.run_checks(rig.clients, rig.accounts, rig.db, references)
    assert report['status'] == 'blocked'
    assert report['code'] == 'anonymous_alias_collision'
    assert report['test_records_created'] == 0
    assert qa.get(rig.clients[0], '/identity/roster')['roster'] == before


@pytest.mark.parametrize('change', ['extra', 'path', 'name', 'duplicate', 'missing'])
def test_manifest_only_accepts_minimal_opaque_projection(references, change):
    if change == 'extra':
        references['private_text'] = 'sensitive-content'
    elif change == 'path':
        references['entries']['Student-A'] = 'C:/private/source.docx'
    elif change == 'name':
        references['entries']['Student-A'] = 'private person name'
    elif change == 'duplicate':
        references['entries']['Student-B'] = references['entries']['Student-A']
    else:
        del references['entries']['Student-C']
    with pytest.raises(qa.Stop) as error:
        qa.manifest_references(references)
    assert error.value.blocked
    assert 'sensitive' not in str(error.value)


def test_exact_record_required_for_reuse(references):
    expected = qa.template('Student-A', references, 'a' * 64)
    assert qa.find_existing({'students': [expected]}, expected) == expected
    with pytest.raises(qa.Stop, match='existing_test_record_conflict'):
        qa.find_existing({'students': [{**expected, 'note': 'different'}]}, expected)
    with pytest.raises(qa.Stop, match='duplicate_test_records'):
        qa.find_existing({'students': [expected, expected]}, expected)


def test_database_missing_is_not_created(tmp_path):
    missing = tmp_path / 'missing.sqlite3'
    with pytest.raises((qa.Stop, OSError)):
        qa.safe_db(missing)
    assert not missing.exists()


def test_database_is_query_only(tmp_path):
    database = tmp_path / 'readonly.sqlite3'
    sqlite3.connect(database).close()
    connection = qa.safe_db(database)
    try:
        assert connection.execute('PRAGMA query_only').fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            connection.execute('CREATE TABLE forbidden(value TEXT)')
    finally:
        connection.close()


def test_database_symlink_refused(tmp_path, monkeypatch):
    database = tmp_path / 'link.sqlite3'
    sqlite3.connect(database).close()
    original = qa.Path.lstat

    def fake_link(path, *args, **kwargs):
        if path == database:
            return SimpleNamespace(st_mode=qa.stat.S_IFLNK)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(qa.Path, 'lstat', fake_link)
    with pytest.raises(qa.Stop, match='unsafe_clone_database'):
        qa.safe_db(database)


@pytest.mark.parametrize('status,code', [(429, 'rate_limited_no_login_loop'), (503, 'service_unavailable')])
def test_retry_budget_is_not_bypassed(status, code):
    calls = []

    def request(*args, **kwargs):
        calls.append(1)
        return status, {}, b'{}'

    with pytest.raises(qa.Stop, match=code) as error:
        qa.call(SimpleNamespace(request=request), '/identity/roster')
    assert error.value.blocked and len(calls) == 1


def test_unexpected_unauthorized_success_is_failure():
    client = SimpleNamespace(request=lambda *args, **kwargs: (200, {}, b'{"ok":true}'))
    with pytest.raises(qa.Stop, match='negative_control_failed') as error:
        qa.deny(client, '/dossier/documents', 404, payload={'confirmed': False})
    assert not error.value.blocked


def test_missing_school_context_blocks():
    client = SimpleNamespace(request=lambda *args, **kwargs:
        (409, {}, b'{"error":{"code":"school_context_required"}}'))
    with pytest.raises(qa.Stop, match='school_context_required') as error:
        qa.get(client, '/identity/roster')
    assert error.value.blocked


def test_windows_cli_cannot_contact_any_server(monkeypatch, capsys):
    monkeypatch.setattr(qa.sys, 'platform', 'win32')
    monkeypatch.setattr(qa, 'Client', lambda *args: pytest.fail('No network allowed'))
    result = qa.main(['--execute-cloud-clone', '--base-url', 'http://127.0.0.1:9999',
        '--clone-db', '/private/SENSITIVE-db', '--manifest-reference-file', '/private/SENSITIVE-manifest',
        '--school-credentials-file', '/private/SENSITIVE-school', '--admin-credentials-file', '/private/SENSITIVE-admin'])
    output = capsys.readouterr().out
    assert result == 2 and 'SENSITIVE' not in output
    assert json.loads(output)['code'] == 'linux_cloud_clone_execution_required'
