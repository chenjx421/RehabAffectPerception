"""Initialize ONLY incomplete school contexts in an explicitly selected cloud clone.

Linux + loopback HTTP only. Defaults to inspection and an exclusive private
backup, with no context POST. --apply enables compare-and-save via the real API.
Full existing contexts are skipped without rewriting metadata. Never updates
accounts, roles, bindings, historical tasks, student records, or the local DB.
The target must be preview.service, NOT the final production service.

  .venv/bin/python scripts/cloud_initialize_test_context.py \
    --base-url http://127.0.0.1:8765 --confirm-cloud-preview-clone \
    --school-credentials-file /private/schools.md \
    --backup /private/original-contexts.json --apply

Use a fresh backup destination for each invocation. Backup contains private
account IDs/context metadata, never passwords/cookies. Re-snapshot the original
source data at final cutover; do not promote these test placeholders as verified
school data. No guardian consent or school identity verification is asserted.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cloud_e2e_acceptance as base


FIELDS = ('city', 'district', 'school_name')
TEST_SELECTION = {
    'selection_source': 'other',
    'province': '\u5de5\u7a0b\u9a8c\u6536\u7701\u4efd \u5f85\u6838\u5b9e',
    'city': '\u5de5\u7a0b\u9a8c\u6536\u57ce\u5e02 \u5f85\u6838\u5b9e',
    'district': '\u5de5\u7a0b\u9a8c\u6536\u533a\u53bf \u5f85\u6838\u5b9e',
    'school_name': '\u5de5\u7a0b\u9a8c\u6536\u5b66\u6821 \u5f85\u6838\u5b9e',
    'street': '\u5de5\u7a0b\u9a8c\u6536\u8857\u9053 \u5f85\u6838\u5b9e',
    'address': '\u5de5\u7a0b\u9a8c\u6536\u5730\u5740 \u5f85\u6838\u5b9e\uff0c\u975e\u771f\u5b9e\u5b66\u6821\u5730\u5740',
}


class Refused(Exception):
    pass


def require(condition, code):
    if not condition:
        raise Refused(code)


def school_credentials(path):
    text = base.private_text(path)
    if text.lstrip().startswith('['):
        values = json.loads(text)
    else:
        rows = [[cell.strip() for cell in line.split('|')] for line in text.splitlines()]
        values = []
        for username in ('t1', 't2', 't3', 't4'):
            matches = [row for row in rows if len(row) > 3 and row[2] == username]
            require(len(matches) == 1, 'invalid_school_credentials')
            values.append({'username': username, 'password': matches[0][3]})
    require(isinstance(values, list) and len(values) == 4, 'four_school_accounts_required')
    result = [base.credential(value) for value in values]
    require(len({value['username'] for value in result}) == 4, 'distinct_accounts_required')
    return result


def snapshot(response):
    context = response.get('context')
    require(isinstance(context, dict) and set(context) == set(FIELDS)
            and all(isinstance(context[key], str) for key in FIELDS), 'invalid_context_response')
    require(isinstance(response.get('details'), dict), 'invalid_context_response')
    complete = all(context[key].strip() for key in FIELDS)
    return {'context': dict(context), 'details': response['details'], 'complete': complete,
            'change_allowed': response.get('context_change_allowed') is True,
            'selection_enabled': response.get('selection_enabled') is True}


def write_backup(path, rows):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        json.dump({'schema_version': 1, 'purpose': 'cloud_preview_only_before_test_context_initialization',
                   'created_at': datetime.now(timezone.utc).isoformat(),
                   'final_cutover_requires_fresh_source_snapshot': True, 'accounts': rows},
                  handle, ensure_ascii=True, indent=2)
        handle.flush()
        os.fsync(handle.fileno())


def initialize(base_url, credentials, backup, *, apply=False, report=None):
    base.endpoint(base_url)
    require(len(credentials) == 4, 'four_school_accounts_required')
    report = report if report is not None else {}
    report.update(ok=False, mode='apply' if apply else 'inspect', changed=0,
                  backup_saved=False, accounts=[], school_identity_verified=False,
                  scope='cloud_preview_clone_only', final_cutover_requires_fresh_source_snapshot=True)
    clients, originals = [], []
    try:
        for index, credential in enumerate(credentials, 1):
            client = base.Client(base_url)
            clients.append(client)
            account = client.login(credential, 'school_uploader')
            original = snapshot(client.json(base.route('/school/context')))
            originals.append({'alias': f'School{index:02d}', 'account_id': account['account_id'], **original})
            report['accounts'].append({'alias': f'School{index:02d}', 'status':
                'complete_untouched' if original['complete'] else 'incomplete_candidate'})
        require(len({row['account_id'] for row in originals}) == 4, 'distinct_accounts_required')
        # No context write is possible before all four originals are durably saved.
        write_backup(backup, originals)
        report['backup_saved'] = True
        if apply:
            require(all(row['complete'] or (row['change_allowed'] and row['selection_enabled'])
                        for row in originals), 'incomplete_context_locked_no_changes')
            for index, (client, original) in enumerate(zip(clients, originals)):
                if original['complete']:
                    continue
                fresh = snapshot(client.json(base.route('/school/context')))
                require(fresh == {key: original[key] for key in fresh}, 'context_changed_no_overwrite')
                payload = {**TEST_SELECTION, 'expected_context': original['context'], 'confirmed': True}
                # Do not retry an ambiguous POST. The original context is in the backup.
                report['accounts'][index]['status'] = 'post_pending_verification'
                client.json(base.route('/school/context'), payload=payload)
                saved = snapshot(client.json(base.route('/school/context')))
                require(saved['context'] == {key: TEST_SELECTION[key] for key in FIELDS}
                        and saved['details'].get('selection_source') == 'other'
                        and saved['details'].get('source_status') == 'pending'
                        and saved['details'].get('address_status') == 'pending', 'saved_test_context_unverified')
                report['accounts'][index]['status'] = 'test_context_saved_pending_verification'
                report['changed'] += 1
            for client, original in zip(clients, originals):
                if original['complete']:
                    fresh = snapshot(client.json(base.route('/school/context')))
                    require(fresh['context'] == original['context'] and fresh['details'] == original['details'],
                            'complete_context_changed_externally')
        report['ok'] = True
        return report
    finally:
        for client in clients:
            if client.cookie:
                try:
                    client.request(base.route('/auth/logout'), payload={})
                except Exception:
                    pass
                client.cookie = ''


def main(argv=None):
    report = {'ok': False, 'changed': 0, 'backup_saved': False}
    try:
        parser = base.Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
        parser.add_argument('--base-url', required=True)
        parser.add_argument('--school-credentials-file', type=Path, required=True)
        parser.add_argument('--backup', type=Path, required=True)
        parser.add_argument('--confirm-cloud-preview-clone', action='store_true')
        parser.add_argument('--apply', action='store_true')
        args = parser.parse_args(argv)
        require(sys.platform.startswith('linux') and args.confirm_cloud_preview_clone,
                'linux_cloud_preview_confirmation_required')
        base.endpoint(args.base_url)
        initialize(args.base_url, school_credentials(args.school_credentials_file), args.backup,
                   apply=args.apply, report=report)
    except KeyboardInterrupt:
        report.update(ok=False, error='interrupted')
    except Exception as exc:
        report.update(ok=False, error=str(exc) if isinstance(exc, Refused) else
                      exc.code if isinstance(exc, base.AcceptanceError) else 'context_initialization_failed')
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
