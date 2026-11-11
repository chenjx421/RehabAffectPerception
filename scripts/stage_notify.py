#!/usr/bin/env python3
"""Send due 1/2/4/8-week stages to an operator-configured webhook.

No URL or credentials are printed. If REHAB_REMINDER_WEBHOOK_URL is unset the
scheduled job exits 0 so the timer stays healthy until a channel is provided.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cloud_pilot_ops import _stages  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--today", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = _stages(args.db, args.today)
    url = os.environ.get("REHAB_REMINDER_WEBHOOK_URL", "").strip()
    if args.dry_run or not url:
        print(json.dumps({"dry_run": args.dry_run, "configured": bool(url), **report}, ensure_ascii=False))
        return 0
    payload = json.dumps({"text": f"阶段复测提醒：{report['due_count']} 个阶段已到期",
                          "due_count": report["due_count"], "due": report["due"]}, ensure_ascii=False).encode()
    req = urllib.request.Request(url, data=payload, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            status = response.status
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__}, ensure_ascii=False))
        return 1
    print(json.dumps({"sent": True, "status": status, "due_count": report["due_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
