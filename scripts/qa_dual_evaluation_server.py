"""Disposable localhost acceptance server. Never opens the production database."""
from pathlib import Path
from http.server import ThreadingHTTPServer
import json
import os
import secrets
import tempfile

from rehab_affect import scenario_lab_server as server
from rehab_affect.student_record_store import Demo2StudentRecordStore


def main():
    root=Path(tempfile.mkdtemp(prefix='rehab-dual-qa-'))
    os.environ['REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX']=secrets.token_urlsafe(24)
    records=Demo2StudentRecordStore(root/'qa.sqlite3',root/'documents')
    with records._connect() as db:
        teacher=dict(db.execute("SELECT * FROM platform_accounts WHERE username='school_uploader_01'").fetchone())
    token=records.create_account_session(teacher['account_id'])['token']
    records.save_account_school_context(token,dict(city='测试市',district='合成区',school_name='双轨验收学校'))
    server.get_demo2_student_store=lambda:records
    handler=server.create_handler(scenario_dir=Path('configs/scenarios'),model_path=server.DEFAULT_LEARNED_POLICY_PATH,policy_name='rule')
    http=ThreadingHTTPServer(('127.0.0.1',0),handler)
    out=Path('outputs/dual_evaluation_qa');out.mkdir(parents=True,exist_ok=True)
    (out/'connection.json').write_text(json.dumps(dict(url=f'http://127.0.0.1:{http.server_port}',token=token,fixture=str(root))),encoding='utf8')
    print(f'Isolated QA server listening on http://127.0.0.1:{http.server_port}',flush=True)
    try:http.serve_forever()
    finally:http.server_close()


if __name__=='__main__':main()
