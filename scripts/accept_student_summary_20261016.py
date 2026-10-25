"""Exercise student summary pages with disposable synthetic records only."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import threading
import time

from rehab_affect import scenario_lab_server as server
from rehab_affect.demo2_identity_store import Demo2IdentityStore
from rehab_affect.demo2_manager_gateway import make_server
from rehab_affect.student_record_store import Demo2StudentRecordStore


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / 'output' / 'playwright' / 'student-summary-20261016'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rehab-summary-synthetic-') as temp:
        directory = Path(temp)
        prefix = secrets.token_urlsafe(24)
        os.environ['REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX'] = prefix
        records = Demo2StudentRecordStore(directory / 'synthetic.sqlite3', directory / 'uploads')
        tokens = {}
        for name, alias in [('school_uploader_01', 'teacher'), ('company_admin', 'admin')]:
            account = records.authenticate_account(name, prefix + name)
            tokens[alias] = records.create_account_session(account['account_id'])['token']
        records.save_account_school_context(tokens['teacher'], {
            'city': 'SYNTHETIC CITY', 'district': 'SYNTHETIC DISTRICT', 'school_name': 'SYNTHETIC SCHOOL'})
        pupil = Demo2IdentityStore(records).create_student(tokens['teacher'], {
            'display_name': '合成测试学生', 'student_code': 'SYNTHETIC-001', 'class_name': '测试班'})
        server.get_demo2_student_store = lambda: records
        httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.create_handler(
            scenario_dir=directory, model_path=directory / 'unused', policy_name='rule'))
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        invite = secrets.token_urlsafe(48)
        gateway = make_server({'invite_secret': invite, 'cookie_secret': secrets.token_urlsafe(48),
                              'expires_at': int(time.time()) + 600,
                              'upstream_port': httpd.server_port, 'listen_port': 0}, port=0)
        gateway_worker = threading.Thread(target=gateway.serve_forever, daemon=True)
        gateway_worker.start()
        env = dict(os.environ, SUMMARY_ACCEPTANCE_BASE=f'http://127.0.0.1:{gateway.server_port}',
                   SUMMARY_ACCEPTANCE_INVITE=invite,
                   SUMMARY_ACCEPTANCE_TEACHER=tokens['teacher'], SUMMARY_ACCEPTANCE_ADMIN=tokens['admin'],
                   SUMMARY_ACCEPTANCE_STUDENT=pupil['student_id'], SUMMARY_ACCEPTANCE_OUTPUT=str(output))
        try:
            process = subprocess.run(['node', str(root / 'scripts' / 'accept_student_summary_20261016.js')],
                                     env=env, timeout=180)
            if process.returncode:
                raise SystemExit(process.returncode)
            with records._connect() as db:
                assert db.execute('SELECT body_blob FROM demo2_summary_snapshots').fetchone()[0] is None
            print(json.dumps({'browser_acceptance': 'passed', 'revocation_blob_cleanup': 'passed',
                              'synthetic_only': True, 'output': str(output)}))
        finally:
            gateway.shutdown()
            gateway.server_close()
            gateway_worker.join(5)
            httpd.shutdown()
            httpd.server_close()
            worker.join(5)


if __name__ == '__main__':
    main()
