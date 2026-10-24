"""Local 32-minute synthetic upload and worker acceptance; no school data."""
import base64
import json
import math
from pathlib import Path
import subprocess
import sys
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.rehab_affect.demo2_media_analysis import _resolve_tool


def main():
    folder = ROOT / '.runtime' / 'lesson_length_acceptance'
    folder.mkdir(parents=True, exist_ok=True)
    media = folder / 'synthetic_32_minutes.mp4'
    subprocess.run([_resolve_tool('ffmpeg'), '-hide_banner', '-loglevel', 'error', '-y',
                    '-f', 'lavfi', '-i', 'testsrc=size=320x180:rate=5', '-f', 'lavfi',
                    '-i', 'sine=frequency=440:sample_rate=16000', '-t', '1920',
                    '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '35',
                    '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '16k', str(media)],
                   check=True, timeout=180)
    rows = (ROOT / '.runtime/demo2_pilot_accounts_20260908.md').read_text(encoding='utf-8').splitlines()
    password = next(line.split('|')[3].strip() for line in rows if len(line.split('|')) > 3 and line.split('|')[2].strip() == 't1')
    session = requests.Session()
    base = 'http://127.0.0.1:8793/api/v1/demo2'
    def post(route, payload):
        r = session.post(base + route, json=payload, timeout=60)
        if not r.ok:
            raise RuntimeError(f'{route}: HTTP {r.status_code}')
        return r.json()
    post('/auth/login', {'username': 't1', 'password': password})
    course = 'duration-test-' + str(int(time.time()))
    w = session.get(base + '/upload/workspace', params={'course_id': course}, timeout=30)
    w.raise_for_status()
    workspace = w.json()['workspace']
    chunk_size = 4 * 1024 * 1024
    size = media.stat().st_size
    task = post('/upload/tasks', {'channel_id': workspace['channel']['channel_id'],
        'uploader_name': 't1', 'course_id': course, 'course_name': '32分钟技术验收（合成素材）',
        'session_id': course, 'filename': media.name, 'mime_type': 'video/mp4',
        'byte_size': size, 'total_chunks': math.ceil(size / chunk_size),
        'security_confirmed': True, 'allow_company_archive': False})['task']
    tid = task['task_id']
    with media.open('rb') as stream:
        for index in range(math.ceil(size / chunk_size)):
            post('/upload/chunks', {'task_id': tid, 'course_id': course, 'chunk_index': index,
                                   'content_base64': base64.b64encode(stream.read(chunk_size)).decode()})
    print('32-minute synthetic upload completed; waiting for worker', flush=True)
    start = time.monotonic()
    while time.monotonic() - start < 600:
        r = session.get(base + '/upload/task', params={'id': tid}, timeout=30)
        r.raise_for_status()
        status = r.json()['task']['analysis_status']
        if status in ('evidence_ready', 'completed', 'failed'):
            break
        time.sleep(3)
    assert status in ('evidence_ready', 'completed'), status
    result = session.get(base + '/upload/result', params={'id': tid}, timeout=30)
    result.raise_for_status()
    body = result.json()
    report = {'task_id': tid, 'synthetic_only': True, 'duration_seconds': 1920,
              'upload_bytes': size, 'analysis_status': status,
              'processing_wait_seconds': round(time.monotonic() - start, 2),
              'result_download': True, 'media': body.get('media'), 'network': 'localhost'}
    (folder / 'acceptance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=True), flush=True)


if __name__ == '__main__':
    main()
