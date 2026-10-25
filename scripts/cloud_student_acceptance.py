"""Cloud-clone-only anonymous roster and missing-authorization acceptance.

Run on Linux beside the private clone's loopback server. Never run on the local
Windows deployment. Requires --execute-cloud-clone and a read-only DB/session
cross-check before creating Student-A/B/C. Existing schools are never changed.

The private reference JSON must contain exactly:
{"manifest_id":"opaque-manifest-id", "entries":
 {"Student-A":"opaque-entry-a","Student-B":"opaque-entry-b","Student-C":"opaque-entry-c"}}
It must NOT contain filenames, source paths, names, diagnoses or document text.
Use a projection prepared by the authorized manifest owner; do not scan originals.

Credentials use cloud_e2e_acceptance's four-school JSON/Markdown and admin JSON.
Exit 3 is expected partial coverage: anonymous records/negative controls may
pass, but real enrollment, authorization, IEP import and summaries remain blocked.
No authorization/review is ever confirmed and no video identity is assigned.
"""
from __future__ import annotations

import argparse
import base64
from datetime import date, timedelta
import hashlib
from http.cookies import SimpleCookie
import json
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import sys
from urllib.parse import urlencode

try:
    from scripts.cloud_e2e_acceptance import Client, load_credentials, private_text, endpoint
except ModuleNotFoundError:
    from cloud_e2e_acceptance import Client, load_credentials, private_text, endpoint


API = '/api/v1/demo2'
ALIASES = ('Student-A', 'Student-B', 'Student-C')
CLASS = 'CLOUD-ANONYMOUS-ACCEPTANCE'
DOMAINS = ('cognition', 'communication', 'motor', 'sensory', 'social_adaptation')
SUMMARY_METADATA = {'public_id', 'channel_id', 'snapshot_count', 'latest_recorded_on',
                    'course_count', 'latest_course_at', 'valid_until'}


class Stop(Exception):
    def __init__(self, code, *, blocked=False):
        self.code, self.blocked = code, blocked
        super().__init__(code)


def require(value, code, *, blocked=False):
    if not value:
        raise Stop(code, blocked=blocked)


def manifest_references(value):
    require(isinstance(value, dict) and set(value) == {'manifest_id', 'entries'},
            'private_reference_projection_required', blocked=True)
    entries = value['entries']
    require(isinstance(entries, dict) and set(entries) == set(ALIASES),
            'three_anonymous_references_required', blocked=True)
    for token in (value['manifest_id'], *entries.values()):
        require(isinstance(token, str) and re.fullmatch(r'[A-Za-z0-9_-]{8,128}', token),
                'opaque_reference_ids_required', blocked=True)
    require(len(set(entries.values())) == 3, 'distinct_reference_ids_required', blocked=True)
    return value


def safe_db(path):
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'unsafe_clone_database', blocked=True)
    for component in (path, *path.parents):
        info = component.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                'unsafe_clone_database', blocked=True)
    require(path.is_file(), 'clone_database_missing', blocked=True)
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
    connection.execute('PRAGMA query_only=ON')
    connection.execute('PRAGMA trusted_schema=OFF')
    return connection


def verify_session_database(client, account, database):
    cookie = SimpleCookie()
    cookie.load(client.cookie)
    require('rehab_demo2_session' in cookie, 'clone_session_proof_missing', blocked=True)
    digest = hashlib.sha256(cookie['rehab_demo2_session'].value.encode('utf-8')).hexdigest()
    connection = safe_db(database)
    try:
        row = connection.execute('SELECT account_id FROM account_sessions WHERE token_hash=?', (digest,)).fetchone()
        require(row is not None and row[0] == account.get('account_id'), 'api_clone_database_mismatch', blocked=True)
    finally:
        connection.close()


def call(client, path, payload=None):
    status, _, raw = client.request(API + path, payload=payload)
    if status == 429:
        raise Stop('rate_limited_no_login_loop', blocked=True)
    if status >= 500:
        raise Stop('service_unavailable', blocked=True)
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        raise Stop('invalid_api_response') from None
    require(isinstance(result, dict), 'invalid_api_response')
    return status, result


def get(client, path):
    status, result = call(client, path)
    if status == 409 and result.get('error', {}).get('code') == 'school_context_required':
        raise Stop('school_context_required', blocked=True)
    require(status == 200 and result.get('ok') is not False, 'api_read_failed')
    return result


def deny(client, path, status, *, payload=None, code=None):
    observed, result = call(client, path, payload)
    if observed == 409 and result.get('error', {}).get('code') == 'school_context_required':
        raise Stop('tenant_school_context_missing', blocked=True)
    require(observed == status and (code is None or result.get('error', {}).get('code') == code),
            'negative_control_failed')


def template(alias, references, scope):
    reference = references['entries'][alias]
    code = 'cloudqa-' + hashlib.sha256((references['manifest_id'] + '\0' + reference + '\0' + scope).encode()).hexdigest()[:24]
    note = json.dumps(dict(qa_only=True, identity_confirmed=False, manifest_id=references['manifest_id'],
                          manifest_reference=reference), sort_keys=True, separators=(',', ':'))
    return dict(display_name=alias, student_code=code, class_name=CLASS, note=note)


def find_existing(roster, expected):
    matches = [row for row in roster['students'] if row.get('student_code') == expected['student_code']]
    require(len(matches) <= 1, 'duplicate_test_records', blocked=True)
    if matches:
        require(all(matches[0].get(key) == value for key, value in expected.items()),
                'existing_test_record_conflict', blocked=True)
        return matches[0]
    require(not any(row.get('display_name') == expected['display_name'] for row in roster['students']),
            'anonymous_alias_collision', blocked=True)
    return None


def persisted_counts(database, students):
    tables = {'demo2_dossier_authorizations': 'student_id', 'demo2_dossier_documents': 'student_id',
              'demo2_summary_authorizations': 'student_id', 'demo2_summary_students': 'student_id',
              'demo2_identity_bindings': 'student_id'}
    connection = safe_db(database)
    try:
        existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        result = {}
        for table, column in tables.items():
            result[table] = sum(connection.execute(f'SELECT COUNT(*) FROM {table} WHERE {column}=?',
                (student['student_id'],)).fetchone()[0] for student in students) if table in existing else 0
        return result
    finally:
        connection.close()


def run_checks(clients, accounts, database, references, *, channel=1):
    report = dict(status='blocked', anonymous_test_records_only=True, real_students_enrolled=False,
        real_materials_imported=False, guardian_authorization_confirmed=False, teacher_review_confirmed=False,
        bindings_created=0, test_records_created=0, test_records_reused=0, checks=[],
        remaining_blockers=['real_authorization_not_supplied', 'teacher_review_not_supplied',
                            'positive_iep_import_not_tested', 'positive_summary_save_not_tested'])
    students = []
    try:
        require(len(clients) == len(accounts) == 5 and 1 <= channel <= 4, 'invalid_accounts', blocked=True)
        references = manifest_references(references)
        for index, (client, account) in enumerate(zip(clients, accounts)):
            require(account.get('role') == ('company_admin' if index == 4 else 'school_uploader'),
                    'account_role_mismatch', blocked=True)
            verify_session_database(client, account, database)
        require(len({account['account_id'] for account in accounts}) == 5, 'distinct_accounts_required', blocked=True)
        owner, admin = clients[channel - 1], clients[4]
        other_clients = [client for index, client in enumerate(clients[:4]) if index != channel - 1]
        school = get(owner, '/school/context')['context']
        require(all(isinstance(school.get(key), str) and school[key].strip()
                    for key in ('city', 'district', 'school_name')), 'school_context_required', blocked=True)
        roster = get(owner, '/identity/roster')['roster']
        scope = roster.get('scope_key')
        require(isinstance(scope, str) and re.fullmatch('[0-9a-f]{64}', scope), 'scope_missing', blocked=True)
        expected = [template(alias, references, scope) for alias in ALIASES]
        # Validate the entire set before creating any record; never adopt real rows.
        for item in expected:
            find_existing(roster, item)
        for item in expected:
            roster = get(owner, '/identity/roster')['roster']
            require(roster.get('scope_key') == scope, 'school_scope_changed', blocked=True)
            student = find_existing(roster, item)
            if student is None:
                status, result = call(owner, '/identity/students', item)
                if status == 409:
                    student = find_existing(get(owner, '/identity/roster')['roster'], item)
                    require(student is not None, 'concurrent_creation_unresolved', blocked=True)
                    report['test_records_reused'] += 1
                else:
                    require(status == 200, 'student_creation_failed')
                    student = result['student']
                    require(all(student.get(key) == value for key, value in item.items()), 'student_response_mismatch')
                    report['test_records_created'] += 1
            else:
                report['test_records_reused'] += 1
            require(student.get('scope_key') == scope, 'student_scope_mismatch')
            students.append(student)
        report['anonymous_records_available'] = len(students)
        require(all(count == 0 for count in persisted_counts(database, students).values()),
                'test_records_have_existing_authorization_or_binding', blocked=True)
        report['checks'].append('three_anonymous_records_scoped_and_reloaded')
        today = date.today()
        for student in students:
            sid = student['student_id']
            query = '?' + urlencode({'student_id': sid})
            authorization = dict(student_id=sid, reference='', valid_until=(today + timedelta(days=7)).isoformat(), confirmed=False)
            deny(owner, '/dossier/authorization', 400, payload={**authorization, 'storage_mode': 'original_and_summary'}, code='confirmation_required')
            missing = 'qa_missing_' + secrets.token_hex(16)
            document = dict(student_id=sid, authorization_id=missing, document_type='iep',
                document_date=today.isoformat(), source_ref='SYNTHETIC DENIAL PROBE ONLY',
                retain_until=(today + timedelta(days=3)).isoformat(),
                summary={key: '' for key in ('learning_goals', 'support_methods', 'safety_notes', 'professional_conclusion')},
                filename='SYNTHETIC-NO-AUTH.txt', content_base64=base64.b64encode(b'SYNTHETIC NEGATIVE PROBE; NOT A REAL IEP').decode(), supersedes_id='')
            deny(owner, '/dossier/documents', 404, payload=document, code='authorization_unavailable')
            deny(owner, '/dossier/documents', 404, payload={**document, 'filename': '', 'content_base64': '',
                'summary': {**document['summary'], 'learning_goals': 'SYNTHETIC DENIAL PROBE ONLY'}}, code='authorization_unavailable')
            workspace = get(owner, '/dossier/student' + query)['workspace']
            require(not workspace['documents'] and workspace['authorization'] is None, 'unauthorized_dossier_persisted')
            deny(owner, '/student-summaries/authorization', 400, payload=authorization, code='confirmation_required')
            deny(owner, '/student-summaries/snapshots', 400, payload=dict(student_id=sid,
                authorization_id=missing, recorded_on=today.isoformat(), source_ref='', learning_goals='',
                support_methods='', domains={key: 'unknown' for key in DOMAINS}, measurement_id='', reviewed=False), code='review_required')
            summary = get(owner, '/student-summaries/student' + query)['workspace']
            require(summary['authorization'] is None and not summary['snapshots'], 'unauthorized_summary_persisted')
            # No document exists, so this verifies the admin route's role gate,
            # not an authorized original-file download or fabricated authorization.
            deny(admin, '/dossier/document?' + urlencode({'document_id': '0' * 32}), 403)
            for other in other_clients:
                deny(other, '/dossier/student' + query, 404)
                deny(other, '/student-summaries/student' + query, 404)
                require(sid not in {row['student_id'] for row in get(other, '/identity/roster')['roster']['students']},
                        'roster_tenant_leak')
        report['checks'].extend(['unconfirmed_authorizations_rejected', 'iep_original_and_summary_without_authorization_rejected',
            'unreviewed_summary_rejected', 'admin_raw_document_route_forbidden', 'three_other_tenants_cannot_read_test_students'])
        final_counts = persisted_counts(database, students)
        require(all(value == 0 for value in final_counts.values()), 'unauthorized_state_persisted')
        report['unauthorized_rows_persisted'] = sum(final_counts.values())
        admin_summary = get(admin, '/student-summaries/admin')['workspace']
        require(all(set(item) <= SUMMARY_METADATA for item in admin_summary['items']), 'admin_summary_metadata_leak')
        dossier_summary = get(admin, '/dossier/admin')['summary']
        require(dossier_summary['policy']['raw_documents_visible'] is False, 'admin_raw_dossier_policy_invalid')
        require(set(dossier_summary) <= {'totals', 'channels', 'policy', 'vault'}, 'admin_dossier_metadata_leak')
        report['admin_summary_metadata_available'] = True
        report['admin_summary_items_count'] = len(admin_summary['items'])
        report['checks'].extend(['unauthorized_rows_absent_in_clone_database', 'admin_summary_metadata_only'])
        report['status'] = 'partial'
    except Stop as error:
        report.update(status='blocked' if error.blocked else 'failed', code=error.code)
    except Exception:
        report.update(status='failed', code='acceptance_error')
    return report


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Stop('invalid_arguments', blocked=True)


def main(argv=None):
    try:
        parser = Parser(description=__doc__)
        parser.add_argument('--execute-cloud-clone', action='store_true')
        parser.add_argument('--base-url', required=True)
        parser.add_argument('--clone-db', type=Path, required=True)
        parser.add_argument('--manifest-reference-file', type=Path, required=True)
        parser.add_argument('--school-credentials-file', type=Path, required=True)
        parser.add_argument('--admin-credentials-file', type=Path, required=True)
        parser.add_argument('--channel', type=int, choices=(1, 2, 3, 4), default=1)
        args = parser.parse_args(argv)
        require(args.execute_cloud_clone and sys.platform.startswith('linux'), 'linux_cloud_clone_execution_required', blocked=True)
        endpoint(args.base_url)
        require(args.clone_db.is_relative_to('/var/lib/rehabaffect') or args.clone_db.is_relative_to('/opt/rehabaffect'),
                'clone_database_outside_deployment_root', blocked=True)
        connection = safe_db(args.clone_db)
        connection.close()
        refs = manifest_references(json.loads(private_text(args.manifest_reference_file)))
        schools, admin = load_credentials(args.school_credentials_file, args.admin_credentials_file)
        clients = [Client(args.base_url) for _ in range(5)]
        accounts = []
        # One login per account; no retry or rate-budget bypass.
        for index, (client, credentials) in enumerate(zip(clients, [*schools, admin])):
            accounts.append(client.login(credentials, 'company_admin' if index == 4 else 'school_uploader'))
        report = run_checks(clients, accounts, args.clone_db, refs, channel=args.channel)
    except Stop as error:
        report = dict(status='blocked' if error.blocked else 'failed', code=error.code, real_students_enrolled=False)
    except Exception:
        report = dict(status='blocked', code='credentials_service_or_clone_unavailable', real_students_enrolled=False)
    print(json.dumps(report, sort_keys=True, ensure_ascii=True))
    return 3 if report['status'] == 'partial' else 2 if report['status'] == 'blocked' else 1


if __name__ == '__main__':
    raise SystemExit(main())
