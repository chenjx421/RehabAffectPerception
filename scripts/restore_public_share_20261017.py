"""Adopt a verified replacement tunnel without rotating secrets or touching accounts."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import urllib.request

from maintain_school_pilot import atomic_replace, encoded, private_write, protect


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'


def fingerprint():
    database = ROOT / 'outputs/seewo_demo2/rehab_affect_demo2.sqlite3'
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
        accounts = db.execute('SELECT * FROM platform_accounts ORDER BY account_id').fetchall()
        tasks = db.execute('SELECT task_id FROM video_analysis_tasks ORDER BY task_id').fetchall()
    return {
        'accounts_sha256': hashlib.sha256(encoded(accounts)).hexdigest(),
        'task_ids_sha256': hashlib.sha256(encoded(tasks)).hexdigest(),
        'tasks': len(tasks),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--origin', required=True)
    parser.add_argument('--tunnel-pid', type=int, required=True)
    parser.add_argument('--gateway-pid', type=int, required=True)
    parser.add_argument('--tunnel-log', required=True)
    parser.add_argument('--metrics-port', type=int, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'https://[a-z0-9-]+\.trycloudflare\.com', args.origin):
        raise SystemExit('Invalid public origin')
    config_path, state_path = RUNTIME/'manager_share_config.json', RUNTIME/'manager_share_state.json'
    raw_config, raw_state = config_path.read_bytes(), state_path.read_bytes()
    config = json.loads(raw_config.decode('utf-8-sig'))
    state = json.loads(raw_state.decode('utf-8-sig'))
    if state['invite_url'] != state['origin'] + '/invite#' + config['invite_secret']:
        raise SystemExit('Existing invitation mismatch; nothing changed')
    with urllib.request.urlopen(args.origin + '/invite', timeout=25) as response:
        if response.status != 200:
            raise SystemExit('Public invitation page unavailable')
    before = fingerprint()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup = RUNTIME / ('public_entry_recovery_' + stamp)
    backup.mkdir()
    protect(backup)
    private_write(backup/'manager_share_config.json', raw_config)
    private_write(backup/'manager_share_state.json', raw_state)
    private_write(backup/'preservation.json', encoded(before))
    state.update(
        previous_origin=state['origin'], origin=args.origin,
        invite_url=args.origin + '/invite#' + config['invite_secret'],
        gateway_pid=args.gateway_pid, tunnel_pid=args.tunnel_pid,
        expires_at=config['expires_at'], tunnel_log=args.tunnel_log,
        metrics_port=args.metrics_port, tunnel_protocol='quic', tunnel_ip_version='6',
        status='public_invite_available_acceptance_pending',
    )
    atomic_replace(state_path, encoded(state), raw_state)
    entry = RUNTIME / '新测试入口_20261017.txt'
    text = ('学校课堂分析平台完整测试入口\n' + state['invite_url'] + '\n\n'
            '邀请配置有效期至2026年11月6日23时59分59秒（北京时间）。\n'
            '原四个学校账号及公司管理员凭据不变，仍访问原数据库与视频。\n'
            '完整链接含私密邀请信息，仅转发给获准测试人员。\n'
            '临时隧道无可用性保证；电脑必须保持开机、联网、接电。\n')
    if entry.exists():
        atomic_replace(entry, text.encode('utf-8-sig'), entry.read_bytes())
    else:
        private_write(entry, text.encode('utf-8-sig'))
    after = fingerprint()
    if config_path.read_bytes() != raw_config or before != after:
        raise SystemExit('Preservation verification failed; investigate before sharing')
    print(json.dumps({'origin':args.origin, 'private_entry_file':str(entry),
        'config_and_invitation_unchanged':True, 'accounts_unchanged':True,
        'task_ids_unchanged':True, 'tasks':after['tasks'], 'expires_at':config['expires_at']}, ensure_ascii=True))


if __name__ == '__main__':
    main()
