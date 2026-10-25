"""Read-only preservation checks; private entry handoff is never printed."""
import hashlib
import json
from pathlib import Path
import sqlite3
import urllib.request
import urllib.error

from scripts.maintain_school_pilot import private_write, row_bytes

ROOT = Path(__file__).resolve().parents[1]


def main():
    root = ROOT / '.runtime'
    before = sqlite3.connect((root / 'maintenance_20261016_backup/database.sqlite3').as_uri() + '?mode=ro', uri=True)
    after = sqlite3.connect((ROOT / 'outputs/seewo_demo2/rehab_affect_demo2.sqlite3').as_uri() + '?mode=ro', uri=True)
    report = {}
    report['school_accounts_unchanged'] = row_bytes(before, 'platform_accounts', "role='school_uploader'") == row_bytes(after, 'platform_accounts', "role='school_uploader'")
    old_id = before.execute("SELECT account_id FROM platform_accounts WHERE role='company_admin'").fetchone()[0]
    new_ids = after.execute("SELECT account_id FROM platform_accounts WHERE role='company_admin'").fetchall()
    report['same_single_admin'] = new_ids == [(old_id,)]
    old_sessions = [r[0] for r in before.execute('SELECT session_id FROM account_sessions WHERE account_id=?', (old_id,))]
    report['old_admin_sessions_revoked'] = all(after.execute('SELECT revoked_at FROM account_sessions WHERE session_id=?',(s,)).fetchone()[0] for s in old_sessions)
    previous = json.loads((root / 'maintenance_20261016_backup/manager_share_state.json').read_text(encoding='utf-8-sig'))
    current = json.loads((root / 'manager_share_state.json').read_text(encoding='utf-8-sig'))
    report['original_invitation_unchanged'] = previous['invite_url'] == current['invite_url'] and previous['origin'] == current['origin']
    report['retention_policies_unchanged'] = row_bytes(before,'retention_policies') == row_bytes(after,'retention_policies')
    preserved = 0
    sources = 0
    for task_id, file_path, digest in before.execute('SELECT task_id,file_path,sha256 FROM video_analysis_tasks'):
        assert after.execute('SELECT 1 FROM video_analysis_tasks WHERE task_id=?',(task_id,)).fetchone()
        assert row_bytes(before, 'video_analysis_tasks','task_id=?',(task_id,)) == row_bytes(after, 'video_analysis_tasks','task_id=?',(task_id,))
        preserved += 1
        if digest and Path(file_path).is_file():
            with Path(file_path).open('rb') as f:
                actual = hashlib.file_digest(f,'sha256').hexdigest()
            assert actual == digest
            sources += 1
    report['original_tasks_unchanged_count'] = preserved
    report['original_source_hashes_verified_count'] = sources
    old_row = next(line.split('|') for line in (root/'demo2_pilot_accounts_20260908.md').read_text(encoding='utf-8').splitlines() if len(line.split('|'))>3 and line.split('|')[2].strip()=='admin')
    request = urllib.request.Request('http://127.0.0.1:8793/api/v1/demo2/auth/login',data=json.dumps({'username':'admin','password':old_row[3].strip(),'role':'company_admin'}).encode(),headers={'Content-Type':'application/json'})
    try:
        urllib.request.urlopen(request,timeout=10)
        report['old_admin_login_rejected'] = False
    except urllib.error.HTTPError as e:
        report['old_admin_login_rejected'] = e.code in (401,403)
    assert all(v for v in report.values())
    handoff = root / 'pilot_entry_private_20261016.txt'
    if not handoff.exists():
        private_write(handoff, ('原测试邀请入口（仅转交指定测试人员）\n'+current['invite_url']+'\n邀请有效期：2026年11月6日23:59:59 北京时间\n临时隧道依赖本机开机、联网，非可用性保证。\n').encode('utf-8-sig'))
    (root / 'pilot_preservation_20261016.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
