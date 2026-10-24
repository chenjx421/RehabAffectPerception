"""Four real accounts submit synthetic videos concurrently on loopback."""
import base64
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:8793/api/v1/demo2'


def main():
    private = ROOT / '.runtime/four_channel_acceptance'
    payload = base64.b64encode((private / 'synthetic_av.mp4').read_bytes()).decode()
    size = (private / 'synthetic_av.mp4').stat().st_size
    lines = (ROOT / '.runtime/demo2_pilot_accounts_20260908.md').read_text(encoding='utf-8').splitlines()
    credentials = {parts[2].strip(): parts[3].strip() for line in lines
                   if len(parts := line.split('|')) > 3 and parts[2].strip() in ('t1', 't2', 't3', 't4')}
    barrier = threading.Barrier(4, timeout=30)
    course = 'parallel-technical-' + str(int(time.time()))

    def run(user):
        session = requests.Session()
        def post(route, body):
            r = session.post(BASE + route, json=body, timeout=45)
            assert r.ok, (route, r.status_code)
            return r.json()
        post('/auth/login', {'username': user, 'password': credentials[user]})
        r = session.get(BASE + '/upload/workspace', params={'course_id': course}, timeout=30)
        r.raise_for_status()
        channel = r.json()['workspace']['channel']['channel_id']
        barrier.wait()
        task = post('/upload/tasks', {'channel_id': channel, 'uploader_name': user,
            'course_id': course, 'course_name': '四通道同时提交技术验收（合成素材）',
            'session_id': course, 'filename': user + '_synthetic.mp4', 'mime_type': 'video/mp4',
            'byte_size': size, 'total_chunks': 1, 'security_confirmed': True,
            'allow_company_archive': False})['task']
        tid = task['task_id']
        post('/upload/chunks', {'task_id': tid, 'course_id': course,
                               'chunk_index': 0, 'content_base64': payload})
        start = time.monotonic()
        while time.monotonic() - start < 180:
            r = session.get(BASE + '/upload/task', params={'id': tid}, timeout=30)
            r.raise_for_status()
            task = r.json()['task']
            if task['analysis_status'] in ('evidence_ready', 'failed', 'completed'):
                break
            time.sleep(1)
        assert task['analysis_status'] in ('evidence_ready', 'completed'), task['analysis_status']
        assert task['channel_id'] == channel
        r = session.get(BASE + '/upload/result', params={'id': tid}, timeout=30)
        r.raise_for_status()
        assert isinstance(r.json(), dict)
        print(user + ' concurrent submission and result passed', flush=True)
        return {'user': user, 'task_id': tid, 'channel': channel,
                'analysis_status': task['analysis_status'], 'download': True}

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, credentials))
    assert len(results) == 4 and len({r['task_id'] for r in results}) == 4
    assert len({r['channel'] for r in results}) == 4
    report = {'passed': True, 'synthetic_only': True, 'network': 'localhost',
              'simultaneous_submissions': 4, 'results': results}
    (private / 'concurrent.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('FOUR SIMULTANEOUS SUBMISSIONS PASSED', flush=True)


if __name__ == '__main__':
    main()
