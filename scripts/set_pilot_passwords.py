"""Reset the five seeded pilot account passwords (t1-t4, admin) in an existing DB.

Local/cloud maintenance only. Passwords are read from a private JSON file such as
{"t1": "...", "t2": "...", "t3": "...", "t4": "...", "admin": "..."} that must
stay outside the repository. Existing sessions of these accounts are revoked.
Nothing about the passwords is printed or logged.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/set_pilot_passwords.py \
        --db /path/to/demo2.sqlite3 --passwords-file /private/pilot_passwords.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rehab_affect.student_record_store import Demo2StudentRecordStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="重置 t1-t4 与 admin 五个试点账号的登录密码")
    parser.add_argument("--db", type=Path, required=True, help="已存在的 demo2.sqlite3 路径")
    parser.add_argument("--passwords-file", type=Path, required=True, help="私有 JSON 密码文件（不要放进仓库）")
    args = parser.parse_args(argv)

    if not args.db.is_file():
        print(f"数据库不存在：{args.db}", file=sys.stderr)
        return 2
    try:
        passwords = json.loads(args.passwords_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"无法读取密码文件：{type(exc).__name__}", file=sys.stderr)
        return 2
    try:
        result = Demo2StudentRecordStore.set_seeded_pilot_passwords(args.db, passwords)
    except ValueError as exc:
        print(f"未修改：{exc}", file=sys.stderr)
        return 1
    print("已更新账号：" + "、".join(result["updated_accounts"]) + "（原有登录会话已失效）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
