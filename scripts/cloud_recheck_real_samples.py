"""Recheck four existing cloud tasks; never create, upload or reprocess media.

Use the original acceptance's --manifest, --media-root and credential arguments,
plus --base-url http://127.0.0.1:8793 and a NEW --report absolute private path.
Linux only. Reports contain anonymous sample aliases and technical check flags.
Login/logout and request auditing are the only intentional server-side writes;
normal request-triggered expiration policies still apply. No database is opened.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import sys
import time
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cloud_real_sample_acceptance as real

base = real.base
TASKS = {
    'Sample01': '49a708e482534a75a9a9e31238d168c5',
    'Sample02': '7f047ce27fba4dc08c13c2c05fe98b2d',
    'Sample03': 'c56442be46e046ca9cd2056e9d4ed23a',
    'Sample04': 'e636f7c7f261460eae9e2a93e197eaf9',
}
ERRORS = frozenset({
    'linux_cloud_recheck_required', 'unsafe_report_destination', 'report_already_exists',
    'report_write_failed', 'request_not_read_only', 'manifest_invalid',
    'sample_copy_unlocated', 'unsafe_sample_path', 'unsafe_media_root',
    'sample_hash_mismatch', 'sample_probe_failed', 'sample_video_missing',
    'sample_duration_invalid', 'sample_changed', 'duplicate_sample_path', 'ffprobe_missing',
    'sample_set_mismatch', 'distinct_accounts_required',
    'account_role_mismatch', 'task_scope_mismatch', 'task_not_ready', 'task_source_mismatch',
    'task_course_mismatch', 'report_download_failed', 'report_source_mismatch',
    'report_media_mismatch', 'worker_evidence_missing', 'source_download_failed',
    'download_timeout', 'download_size_mismatch', 'download_hash_mismatch',
    'source_range_failed', 'audio_range_failed', 'task_refresh_failed',
    'role_isolation_failed', 'peer_isolation_failed', 'anonymous_isolation_failed',
    'interrupted', 'recheck_failed',
})


class ReadOnlyClient(base.Client):
    """Fail closed before sending any request outside the recheck allowlist."""

    def request(self, path, *, payload=None, binary=None, **kwargs):
        parsed = urlsplit(path)
        suffix = parsed.path.removeprefix(base.API)
        allowed = parsed.path.startswith(base.API + '/') and not parsed.fragment
        if payload is not None:
            allowed = allowed and suffix in {'/auth/login', '/auth/logout'} and not parsed.query
        else:
            query = parse_qs(parsed.query, keep_blank_values=True)
            key = 'task_id' if suffix == '/course-analysis' else 'id'
            if suffix == '/school/context':
                allowed = allowed and not parsed.query
            else:
                keys = {key, 'asset'} if suffix == '/upload/media' else {key}
                allowed = (allowed and suffix in {'/upload/task', '/upload/result',
                           '/upload/media', '/course-analysis'} and set(query) == keys
                           and len(query.get(key, [])) == 1 and query[key][0] in TASKS.values())
                if suffix == '/upload/media':
                    allowed = allowed and query.get('asset') in [['source'], ['audio']]
        real.check(allowed and binary is None, 'request_not_read_only')
        return super().request(path, payload=payload, binary=binary, **kwargs)


def private_report(path):
    real.check(path.is_absolute() and '..' not in path.parts, 'unsafe_report_destination')
    for parent in path.parents:
        real.check(not parent.is_symlink(), 'unsafe_report_destination')
    if os.name == 'posix':
        parent = path.parent.stat()
        real.check(parent.st_uid == os.geteuid() and not parent.st_mode & 0o077,
                   'unsafe_report_destination')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    except FileExistsError:
        raise real.CheckError('report_already_exists') from None
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or (os.name == 'posix' and info.st_mode & 0o077):
        os.close(fd)
        raise real.CheckError('unsafe_report_destination')
    return os.fdopen(fd, 'w', encoding='utf-8')


def run(args, report):
    base.endpoint(args.base_url)
    report['stage'] = 'local_copy_preflight'
    samples = real.load_samples(args.manifest, args.media_root, args.ffprobe)
    real.check([item['sample_id'] for item in samples] == list(TASKS), 'sample_set_mismatch')
    schools, admin = base.load_credentials(args.school_credentials_file, args.admin_credentials_file)
    clients = [ReadOnlyClient(args.base_url) for _ in range(5)]
    anonymous = ReadOnlyClient(args.base_url)
    accounts, tasks = [], []
    try:
        report['stage'] = 'account_preflight'
        for index, client in enumerate(clients):
            role = 'company_admin' if index == 4 else 'school_uploader'
            account = client.login(admin if index == 4 else schools[index], role)
            real.check(account.get('role') == role, 'account_role_mismatch')
            accounts.append(account)
            if index < 4:
                context = client.json(base.route('/school/context'))['context']
                report.setdefault('school_context_completeness', {})[list(TASKS)[index]] = (
                    isinstance(context, dict) and all(context.get(key)
                    for key in ('city', 'district', 'school_name')))
        real.check(len({account['account_id'] for account in accounts}) == 5, 'distinct_accounts_required')
        report['stage'] = 'existing_task_preflight'
        for index, sample in enumerate(samples):
            task_id = TASKS[sample['sample_id']]
            task = clients[index].json(base.route('/upload/task', id=task_id))['task']
            real.check(task['task_id'] == task_id and task['account_id'] == accounts[index]['account_id']
                       and task['channel_id'] == accounts[index]['bound_channel_id'], 'task_scope_mismatch')
            real.check(task['upload_status'] == 'completed' and task['analysis_status'] == 'evidence_ready',
                       'task_not_ready')
            real.check(task['sha256'] == sample['sha256'] and task['byte_size'] == sample['size_bytes'],
                       'task_source_mismatch')
            real.check(task['course_name'] == 'Authorized real sample acceptance', 'task_course_mismatch')
            tasks.append(task)
        real.check(len({task['course_id'] for task in tasks}) == 1, 'task_course_mismatch')
        report['stage'] = 'verify_existing_tasks'
        for index, sample in enumerate(samples):
            task_id = TASKS[sample['sample_id']]
            row = {'sample_id': sample['sample_id'], 'passed': False, 'checks': {}}
            report['samples'].append(row)
            started = time.monotonic()
            real.verify(clients[index], task_id, sample, teacher=True)
            row['checks']['teacher'] = {
                'source_bound_technical_summary_twice': True, 'downloaded_report_source_hash': True,
                'full_media_download_hash': True, 'source_range_128bytes': True,
                'audio_range_wave_header': True if sample['media']['has_audio'] else None,
                'task_refresh': True,
            }
            real.verify(clients[4], task_id, sample, teacher=False)
            row['checks']['admin'] = {
                'downloaded_report_source_hash': True, 'full_media_download_hash': True,
                'source_range_128bytes': True, 'task_refresh': True,
            }
            analysis_path = base.route('/course-analysis', task_id=task_id)
            real.check(clients[4].request(analysis_path)[0] == 403, 'role_isolation_failed')
            row['checks']['admin_classroom_analysis_denied'] = True
            paths = [base.route('/upload/task', id=task_id), base.route('/upload/result', id=task_id),
                     base.route('/upload/media', id=task_id, asset='source'), analysis_path]
            if sample['media']['has_audio']:
                paths.append(base.route('/upload/media', id=task_id, asset='audio'))
            for other in range(4):
                if other != index:
                    for path in paths:
                        headers = {'Range': 'bytes=0-127'} if '/upload/media?' in path else {}
                        real.check(clients[other].request(path, headers=headers)[0] in {403, 404},
                                   'peer_isolation_failed')
            for path in paths:
                headers = {'Range': 'bytes=0-127'} if '/upload/media?' in path else {}
                real.check(anonymous.request(path, headers=headers)[0] == 401, 'anonymous_isolation_failed')
            real.check(real.stamp(sample['path']) == sample['stamp'], 'sample_changed')
            row['checks']['other_three_accounts_denied'] = True
            row['checks']['anonymous_denied'] = True
            row['elapsed_seconds'] = round(time.monotonic() - started, 3)
            row['passed'] = True
        report.update(ok=True, stage='complete')
    finally:
        for client in clients:
            if client.cookie:
                try:
                    client.request(base.route('/auth/logout'), payload={})
                except Exception:
                    pass
                client.cookie = ''


def main(argv=None):
    report = {'ok': False, 'stage': 'arguments', 'samples': [], 'existing_tasks_expected': 4,
              'new_tasks_created': 0, 'uploads_attempted': 0, 'reprocessing_requested': False,
              'scope': 'existing_real_tasks_cloud_loopback_recheck_only',
              'legal_authorization_verified': False, 'identity_binding_verified': False,
              'dossier_imported': False, 'training_permission_granted': False}
    destination = None
    try:
        parser = base.Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
        for name in ('base-url', 'manifest', 'media-root', 'school-credentials-file',
                     'admin-credentials-file', 'report'):
            parser.add_argument('--' + name, required=True, type=str if name == 'base-url' else Path)
        parser.add_argument('--ffprobe')
        args = parser.parse_args(argv)
        real.check(sys.platform.startswith('linux'), 'linux_cloud_recheck_required')
        base.endpoint(args.base_url)
        report['stage'] = 'report_destination'
        destination = private_report(args.report)
        run(args, report)
    except KeyboardInterrupt:
        report.update(ok=False, error='interrupted')
    except Exception as exc:
        code = exc.code if isinstance(exc, base.AcceptanceError) else str(exc)
        report.update(ok=False, error=code if code in ERRORS or code in base.ERRORS else 'recheck_failed')
    finally:
        if destination is not None:
            try:
                with destination:
                    json.dump(report, destination, ensure_ascii=True, sort_keys=True, indent=2)
            except OSError:
                report.update(ok=False, error='report_write_failed')
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
