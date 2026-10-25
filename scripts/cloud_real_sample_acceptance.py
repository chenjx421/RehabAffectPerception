"""Explicitly authorized real-media acceptance over loopback HTTP only.

Never creates/resets accounts, modifies original tasks, binds identities, uploads
IEPs, or asserts legal consent. The manifest selects private controlled cloud
copies, not desktop paths. No WAN throughput or face/clinical accuracy claims.

Manifest: {schema_version:1,samples:[{sample_id:"Sample01",relative_path:
"uploads/channel/opaque-task.mp4",size_bytes:123,sha256:"64 hex chars"}, ...]}.
Exactly Sample01..Sample04 are required. Paths are relative to --media-root;
missing paths and symlinks fail before login. A draft may use null paths for
unlocated samples, but cannot be executed until all four copies are present.

Run with private 0600 credential/manifest files and a new report destination:
  .venv/bin/python scripts/cloud_real_sample_acceptance.py \
    --base-url http://127.0.0.1:8765 --media-root /private/preseed/media \
    --manifest /private/cloud_samples.json --school-credentials-file /private/schools.md \
    --admin-credentials-file /private/admin.json --report /private/report.json \
    --allow-real-sample-uploads

Each invocation creates four new tasks under real-acceptance-20261020-<nonce>.
Server files/tasks remain for review. Stdout and report are anonymous allowlists.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import stat
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cloud_e2e_acceptance as base


class CheckError(Exception):
    pass


def check(condition, code):
    if not condition:
        raise CheckError(code)


def stamp(path):
    info = path.stat()
    return info.st_size, info.st_mtime_ns, info.st_ino


def digest_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(base.CHUNK_SIZE), b''):
            digest.update(block)
    return digest.hexdigest()


def controlled_path(root, relative):
    check(isinstance(relative, str) and bool(relative), 'sample_copy_unlocated')
    posix = PurePosixPath(relative)
    check(not posix.is_absolute() and not any(part in {'.', '..'} for part in relative.split('/'))
          and '\\' not in relative and ':' not in relative, 'unsafe_sample_path')
    path = root
    for part in posix.parts:
        path = path / part
        check(not path.is_symlink(), 'unsafe_sample_path')
    resolved = path.resolve(strict=True)
    check(resolved.is_relative_to(root) and resolved.is_file(), 'unsafe_sample_path')
    return resolved


def probe(path, ffprobe):
    tool = ffprobe or shutil.which('ffprobe')
    check(bool(tool), 'ffprobe_missing')
    result = subprocess.run([str(tool), '-v', 'error', '-show_entries',
        'format=duration:stream=codec_type,width,height', '-of', 'json', str(path)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60)
    check(result.returncode == 0, 'sample_probe_failed')
    value = json.loads(result.stdout)
    video = next((s for s in value.get('streams', []) if s.get('codec_type') == 'video'), None)
    check(video is not None, 'sample_video_missing')
    duration = float(value['format']['duration'])
    check(math.isfinite(duration) and duration > 0, 'sample_duration_invalid')
    return {'duration_sec': duration, 'width': video['width'], 'height': video['height'],
            'has_audio': any(s.get('codec_type') == 'audio' for s in value['streams'])}


def load_samples(manifest_path, media_root, ffprobe=None):
    manifest = json.loads(base.private_text(manifest_path))
    check(isinstance(manifest, dict) and manifest.get('schema_version') == 1, 'manifest_invalid')
    rows = manifest.get('samples')
    check(isinstance(rows, list) and len(rows) == 4 and all(isinstance(s, dict) for s in rows), 'manifest_invalid')
    check({s.get('sample_id') for s in rows} == {f'Sample{i:02d}' for i in range(1, 5)}, 'manifest_invalid')
    check(media_root.is_absolute() and not media_root.is_symlink(), 'unsafe_media_root')
    root = media_root.resolve(strict=True)
    check(root.is_dir() and root != Path(root.anchor), 'unsafe_media_root')
    samples = []
    for row in sorted(rows, key=lambda item: item['sample_id']):
        check(isinstance(row.get('sha256'), str) and re.fullmatch('[0-9a-f]{64}', row['sha256']), 'manifest_invalid')
        check(type(row.get('size_bytes')) is int and 0 < row['size_bytes'] <= 5 * 1024**3, 'manifest_invalid')
        path = controlled_path(root, row.get('relative_path'))
        before = stamp(path)
        check(before[0] == row['size_bytes'] and digest_file(path) == row['sha256'], 'sample_hash_mismatch')
        metadata = probe(path, ffprobe)
        check(stamp(path) == before, 'sample_changed')
        samples.append({key: row[key] for key in ('sample_id', 'size_bytes', 'sha256')} |
                       {'path': path, 'stamp': before, 'media': metadata})
    check(len({item['path'] for item in samples}) == 4, 'duplicate_sample_path')
    return samples


def upload_file(client, task, sample):
    size = sample['size_bytes']
    digest = hashlib.sha256()
    with sample['path'].open('rb') as source:
        info = os.fstat(source.fileno())
        check(stat.S_ISREG(info.st_mode) and (info.st_size, info.st_mtime_ns, info.st_ino) == sample['stamp'], 'sample_changed')
        for index in range(math.ceil(size / base.CHUNK_SIZE)):
            block = source.read(min(base.CHUNK_SIZE, size - index * base.CHUNK_SIZE))
            check(len(block) == min(base.CHUNK_SIZE, size - index * base.CHUNK_SIZE), 'sample_changed')
            digest.update(block)
            for attempt in range(3):
                try:
                    status, _, _ = client.request(base.route('/upload/chunks', task_id=task['task_id'],
                        course_id=task['course_id'], chunk_index=index), binary=block, timeout=180)
                    if status == 200:
                        break
                    check(status in {408, 429, 500, 502, 503, 504}, 'chunk_upload_rejected')
                except base.AcceptanceError as exc:
                    if exc.code != 'network_error':
                        raise
                current = client.json(base.route('/upload/task', id=task['task_id']))['task']
                acknowledged = current['next_chunk_index']
                if acknowledged == index + 1:
                    break
                check(acknowledged == index and attempt < 2, 'chunk_retries_exhausted')
                time.sleep(attempt + 1)
        check(not source.read(1) and digest.hexdigest() == sample['sha256']
              and stamp(sample['path']) == sample['stamp'], 'sample_changed')
    current = client.json(base.route('/upload/task', id=task['task_id']))['task']
    check(current['upload_status'] == 'completed' and current['received_bytes'] == size
          and current['sha256'] == sample['sha256'], 'uploaded_hash_mismatch')


def download_hash(client, task_id, sample, *, deadline_seconds=3600):
    connection = http.client.HTTPConnection(client.host, client.port, timeout=120)
    deadline = time.monotonic() + deadline_seconds
    try:
        connection.request('GET', base.route('/upload/media', id=task_id, asset='source'),
            headers={'Cookie': client.cookie, 'Origin': client.origin, 'Connection': 'close'})
        response = connection.getresponse()
        check(response.status == 200 and response.getheader('Content-Length') == str(sample['size_bytes']),
              'source_download_failed')
        digest, count = hashlib.sha256(), 0
        while True:
            check(time.monotonic() < deadline, 'download_timeout')
            block = response.read1(1024 * 1024)
            if not block:
                break
            count += len(block)
            check(count <= sample['size_bytes'], 'download_size_mismatch')
            digest.update(block)
        check(count == sample['size_bytes'] and digest.hexdigest() == sample['sha256'], 'download_hash_mismatch')
    finally:
        connection.close()


def verify(client, task_id, sample, *, teacher):
    result_path = base.route('/upload/result', id=task_id)
    status, headers, body = client.request(result_path, timeout=120)
    check(status == 200 and 'attachment' in headers.get('content-disposition', ''), 'report_download_failed')
    result = json.loads(body)
    check(result['task_id'] == task_id and result['source_sha256'] == sample['sha256']
          and result['analysis_status'] == 'evidence_ready', 'report_source_mismatch')
    media = result['media']
    expected = sample['media']
    check((media['width'], media['height'], media['has_audio']) ==
          (expected['width'], expected['height'], expected['has_audio'])
          and abs(media['duration_sec'] - expected['duration_sec']) <= max(1, expected['duration_sec'] * .005),
          'report_media_mismatch')
    check(result['summary']['decoded_frames'] > 0 and result['summary']['sampled_frames'] > 0
          and result['provenance']['network_used'] is False
          and result['provenance']['models_downloaded'] is False, 'worker_evidence_missing')
    download_hash(client, task_id, sample)
    status, headers, first = client.request(base.route('/upload/media', id=task_id, asset='source'),
                                           headers={'Range': 'bytes=0-127'}, timeout=120)
    with sample['path'].open('rb') as source:
        expected_first = source.read(128)
    check(status == 206 and first == expected_first
          and headers.get('content-range') == f"bytes 0-127/{sample['size_bytes']}", 'source_range_failed')
    if expected['has_audio']:
        status, _, audio = client.request(base.route('/upload/media', id=task_id, asset='audio'),
                                         headers={'Range': 'bytes=0-127'}, timeout=120)
        check(status == 206 and audio.startswith(b'RIFF') and audio[8:12] == b'WAVE', 'audio_range_failed')
    if teacher:
        base.automatic_report(client, task_id)
        # A second independent request verifies persisted results survive refresh.
        base.automatic_report(client, task_id)
    fresh = client.json(base.route('/upload/task', id=task_id))['task']
    check(fresh['task_id'] == task_id and fresh['sha256'] == sample['sha256']
          and fresh['analysis_status'] == 'evidence_ready', 'task_refresh_failed')


def run(args, report):
    base.endpoint(args.base_url)
    schools, admin = base.load_credentials(args.school_credentials_file, args.admin_credentials_file)
    report['stage'] = 'local_copy_preflight'
    samples = load_samples(args.manifest, args.media_root, args.ffprobe)
    clients = [base.Client(args.base_url) for _ in range(5)]
    anonymous = base.Client(args.base_url)
    course = 'real-acceptance-20261020-' + secrets.token_hex(8)
    accounts, tasks = [], []
    try:
        report['stage'] = 'account_preflight'
        for i, client in enumerate(clients):
            accounts.append(client.login(schools[i] if i < 4 else admin,
                                          'school_uploader' if i < 4 else 'company_admin'))
            if i < 4:
                context = client.json(base.route('/school/context'))['context']
                check(isinstance(context, dict) and all(context.get(k) for k in ('city', 'district', 'school_name')),
                      'school_context_missing_no_auto_fill')
                work = client.json(base.route('/upload/workspace', course_id=course))['workspace']
                check(work['channel']['channel_id'] == accounts[i]['bound_channel_id']
                      and not work['tasks'] and work['quota']['remaining_slots'] > 0, 'upload_scope_unavailable')
                check(client.request(base.route('/admin/summary'))[0] == 403, 'role_isolation_failed')
        check(len({a['account_id'] for a in accounts}) == 5, 'distinct_accounts_required')
        report['stage'] = 'upload_and_worker'
        for i, sample in enumerate(samples):
            client = clients[i]
            row = {key: sample[key] for key in ('sample_id', 'sha256', 'size_bytes')}
            row.update(duration_sec=round(sample['media']['duration_sec'], 3), passed=False)
            report['samples'].append(row)
            started = time.monotonic()
            task = client.json(base.route('/upload/tasks'), payload={
                'channel_id': accounts[i]['bound_channel_id'], 'course_id': course,
                'course_name': 'Authorized real sample acceptance', 'session_id': course + '-' + sample['sample_id'],
                'uploader_name': 'Authorized acceptance', 'filename': sample['sample_id'] + '.mp4',
                'mime_type': 'video/mp4', 'byte_size': sample['size_bytes'],
                'total_chunks': math.ceil(sample['size_bytes'] / base.CHUNK_SIZE),
                'security_confirmed': True, 'allow_company_archive': False}, timeout=120)['task']
            check(task['account_id'] == accounts[i]['account_id'] and task['course_id'] == course, 'task_scope_mismatch')
            tasks.append(task['task_id'])
            report['new_tasks_created'] = len(tasks)
            upload_file(client, task, sample)
            row['loopback_upload_seconds'] = round(time.monotonic() - started, 3)
            completed_upload = time.monotonic()
            while True:
                current = client.json(base.route('/upload/task', id=task['task_id']))['task']
                check(current['analysis_status'] not in {'failed', 'cancelled'}, 'worker_failed')
                if current['analysis_status'] == 'evidence_ready':
                    break
                check(time.monotonic() - completed_upload < args.worker_timeout, 'worker_timeout')
                time.sleep(5)
            row['worker_wait_seconds_including_queue'] = round(time.monotonic() - completed_upload, 3)
            verify(client, task['task_id'], sample, teacher=True)
            verify(clients[4], task['task_id'], sample, teacher=False)
            paths = [base.route('/upload/task', id=task['task_id']), base.route('/upload/result', id=task['task_id']),
                     base.route('/upload/media', id=task['task_id'], asset='source'),
                     base.route('/course-analysis', task_id=task['task_id'])]
            for other in range(4):
                if other != i:
                    for path in paths:
                        check(clients[other].request(path)[0] in {403, 404}, 'peer_isolation_failed')
            for path in paths:
                check(anonymous.request(path)[0] == 401, 'anonymous_isolation_failed')
            row['passed'] = True
        report['stage'] = 'admin_listing_refresh'
        for _ in range(2):
            found = set()
            for page in range(1, 101):
                summary = clients[4].json(base.route('/admin/summary', upload_page=page))['summary']
                found.update(item['task_id'] for item in summary['recent_uploads'] if item['task_id'] in tasks)
                if found == set(tasks) or page >= summary['upload_pagination']['total_pages']:
                    break
            check(found == set(tasks), 'admin_listing_missing')
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
    report = {'ok': False, 'stage': 'arguments', 'samples': [], 'new_tasks_created': 0,
              'scope': 'real_media_cloud_loopback_only_not_school_wan_speed',
              'legal_authorization_verified': False, 'identity_binding_verified': False,
              'dossier_imported': False, 'training_permission_granted': False,
              'not_verified': ['school_public_upload_speed', 'face_identity', 'student_scores',
                               'IEP_authorized_import_and_denial']}
    destination = None
    try:
        parser = base.Parser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
        for name in ('base-url', 'manifest', 'media-root', 'school-credentials-file', 'admin-credentials-file', 'report'):
            parser.add_argument('--' + name, required=True, type=str if name == 'base-url' else Path)
        parser.add_argument('--ffprobe')
        parser.add_argument('--worker-timeout', type=int, default=3600)
        parser.add_argument('--allow-real-sample-uploads', action='store_true')
        args = parser.parse_args(argv)
        check(args.allow_real_sample_uploads and 1 <= args.worker_timeout <= 14400, 'explicit_test_upload_consent_required')
        # Exclusive creation prevents overwriting credentials or an earlier report.
        fd = os.open(args.report, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        destination = os.fdopen(fd, 'w', encoding='utf-8')
        run(args, report)
    except KeyboardInterrupt:
        report.update(ok=False, error='interrupted')
    except Exception as exc:
        code = str(exc) if isinstance(exc, CheckError) else exc.code if isinstance(exc, base.AcceptanceError) else 'acceptance_failed'
        report.update(ok=False, error=code)
    finally:
        if destination is not None:
            with destination:
                json.dump(report, destination, ensure_ascii=True, indent=2)
    print(json.dumps(report, ensure_ascii=True, sort_keys=True))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
