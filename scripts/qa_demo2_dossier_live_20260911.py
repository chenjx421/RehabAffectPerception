"""Explicit opt-in local smoke: only login writes, no student/content mutation."""

import argparse
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPCookieProcessor, Request


ROOT = Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:8792'
OUTPUT = ROOT / 'output/playwright/demo2_dossier_20260911_live/smoke.json'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--service-updated', action='store_true', required=True)
    parser.parse_args()
    report = {'complete': False, 'business_writes': 0, 'authentication_writes': 0, 'checks': []}
    for user, variable in [('t1', 'QA_DEMO2_TEACHER_PASSWORD'), ('admin', 'QA_DEMO2_ADMIN_PASSWORD')]:
        password = os.environ.get(variable)
        if not password:
            raise RuntimeError('Missing authorized QA credential environment')
        client = build_opener(HTTPCookieProcessor(CookieJar()))
        request = Request(BASE + '/api/v1/demo2/auth/login',
                          data=json.dumps({'username': user, 'password': password}).encode(),
                          headers={'Content-Type': 'application/json'}, method='POST')
        with client.open(request, timeout=20) as response:
            assert response.status == 200
            assert json.loads(response.read())['ok'] is True
        report['authentication_writes'] += 1
        paths = [('/demo2/upload', 200), ('/demo2/students', 200),
                 ('/api/v1/demo2/dossier/admin', 403)] if user == 't1' else [
                 ('/demo2/admin', 200), ('/demo2/admin/channels', 200),
                 ('/demo2/admin/dossiers', 200), ('/api/v1/demo2/dossier/admin', 200)]
        paths += [('/api/seewo_demo2/student_record?student_id=unmapped', 410),
                  ('/api/seewo_demo2/document_download?id=unmapped', 410)]
        for path, expected in paths:
            try:
                response = client.open(Request(BASE + path, method='GET'), timeout=25)
            except HTTPError as error:
                response = error
            with response:
                status, raw = response.code, response.read()
                assert status == expected, (user, path, status, expected)
                assert b'Traceback' not in raw
                if path == '/api/v1/demo2/dossier/admin' and expected == 200:
                    summary = json.loads(raw)['summary']
                    assert summary['vault']['available'] is True
                    assert summary['policy']['raw_documents_visible'] is False
                    assert summary['policy']['training_allowed'] is False
                    report['vault_mode'] = summary['vault']['mode']
                    operational_fields = json.dumps(summary).encode()
                    for secret in ['summary', 'professional_conclusion', 'source_ref', 'filename', 'display_name']:
                        assert ('"' + secret + '"').encode() not in operational_fields
                report['checks'].append({'role': user, 'path': path.split('?')[0], 'status': status})
    report['complete'] = True
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
