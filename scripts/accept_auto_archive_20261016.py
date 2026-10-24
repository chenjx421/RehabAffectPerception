"""Full automatic archiving acceptance using a generated non-student video."""
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
from rehab_affect.demo2_media_analysis import _resolve_tool
from rehab_affect.demo2_media_worker import VideoAnalysisWorker
from rehab_affect.student_record_store import Demo2StudentRecordStore


def main():
    root = Path(__file__).resolve().parents[1]
    output = root / 'output/playwright/automatic-archive-20261016'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rehab-auto-archive-synthetic-') as temp:
        directory = Path(temp)
        source = directory / 'synthetic-test-pattern.mp4'
        subprocess.run([_resolve_tool('ffmpeg'), '-v', 'error', '-nostdin', '-y',
                        '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=10', '-t', '4',
                        '-an', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(source)],
                       check=True, timeout=30, capture_output=True)
        prefix = secrets.token_urlsafe(24)
        os.environ['REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX'] = prefix
        records = Demo2StudentRecordStore(directory / 'synthetic.sqlite3', directory / 'uploads')
        tokens = {}
        for name, alias in [('school_uploader_01', 'teacher'), ('company_admin', 'admin')]:
            account = records.authenticate_account(name, prefix + name)
            tokens[alias] = records.create_account_session(account['account_id'])['token']
        records.save_account_school_context(tokens['teacher'], {
            'city': 'SYNTHETIC CITY', 'district': 'SYNTHETIC DISTRICT', 'school_name': 'SYNTHETIC SCHOOL'})
        identities = Demo2IdentityStore(records)
        pupil = identities.create_student(tokens['teacher'], {
            'display_name': '合成测试学生', 'student_code': 'SYNTHETIC-001', 'class_name': '测试班'})
        identities.create_student(tokens['teacher'], {'display_name': '未绑定合成学生', 'student_code': 'SYNTHETIC-002'})
        server.get_demo2_student_store = lambda: records
        handler = server.create_handler(scenario_dir=directory, model_path=directory / 'unused', policy_name='rule')
        httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        media_worker = VideoAnalysisWorker(records)
        assert media_worker.start()
        maintenance = server._DossierMaintenance(None, summary_cleanup=handler.cleanup_expired_student_summaries, interval=1)
        maintenance.start()
        invite = secrets.token_urlsafe(48)
        gateway = make_server({'invite_secret': invite, 'cookie_secret': secrets.token_urlsafe(48),
                              'expires_at': int(time.time()) + 600,
                              'upstream_port': httpd.server_port, 'listen_port': 0}, port=0)
        gateway_worker = threading.Thread(target=gateway.serve_forever, daemon=True)
        gateway_worker.start()
        env = dict(os.environ, SUMMARY_ACCEPTANCE_BASE=f'http://127.0.0.1:{gateway.server_port}',
                   SUMMARY_ACCEPTANCE_INVITE=invite, SUMMARY_ACCEPTANCE_TEACHER=tokens['teacher'],
                   SUMMARY_ACCEPTANCE_ADMIN=tokens['admin'], SUMMARY_ACCEPTANCE_STUDENT=pupil['student_id'],
                   SUMMARY_ACCEPTANCE_OUTPUT=str(output), SUMMARY_ACCEPTANCE_VIDEO=str(source))
        try:
            process = subprocess.run(['node', str(root / 'scripts/accept_auto_archive_20261016.js')],
                                     env=env, timeout=240)
            if process.returncode:
                raise SystemExit(process.returncode)
            print(json.dumps({'automatic_archive_browser': 'passed', 'synthetic_only': True, 'output': str(output)}))
        finally:
            gateway.shutdown()
            gateway.server_close()
            gateway_worker.join(5)
            maintenance.stop()
            media_worker.stop()
            httpd.shutdown()
            httpd.server_close()
            worker.join(5)


if __name__ == '__main__':
    main()
