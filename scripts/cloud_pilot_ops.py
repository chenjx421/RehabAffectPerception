#!/usr/bin/env python3
"""Small production-pilot checks: SQLite backup, health, bounded concurrency.

No secrets are printed. This is a repeatable operator check, not a substitute for
a full disaster-recovery or load test.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
import urllib.request


def _backup(db: Path, out: Path, keep: int, dry_run: bool) -> dict:
    if not db.is_file():
        raise SystemExit("database_not_found")
    out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    target = out / f"rehab_affect_demo2_{stamp}.sqlite3.gz"
    manifest = out / f"rehab_affect_demo2_{stamp}.json"
    if dry_run:
        return {"dry_run": True, "source": str(db), "target": str(target), "keep": keep}
    tmp = out / f".backup_{stamp}.sqlite3"
    with sqlite3.connect(str(db)) as src, sqlite3.connect(str(tmp)) as dst:
        src.backup(dst)
        dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    raw = tmp.read_bytes()
    with gzip.open(target, "wb", compresslevel=6) as fh:
        fh.write(raw)
    tmp.unlink(missing_ok=True)
    digest = hashlib.sha256(raw).hexdigest()
    payload = {"created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "source": db.name,
               "backup": target.name, "bytes": len(raw), "sha256": digest, "keep": keep}
    manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    backups = sorted(out.glob("rehab_affect_demo2_*.sqlite3.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = []
    for old in backups[keep:]:
        old.unlink(missing_ok=True)
        old_manifest = old.with_suffix("").with_suffix(".json")
        old_manifest.unlink(missing_ok=True)
        removed.append(old.name)
    payload["removed"] = removed
    return payload


def _health(url: str, db: Path, min_free_gb: float) -> dict:
    result = {"url": url, "db_integrity": None, "http_status": None, "free_gb": None, "ok": False}
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            result["db_integrity"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            result["http_status"] = resp.status
        result["free_gb"] = round(shutil.disk_usage(db.parent).free / 1024**3, 2)
        result["ok"] = result["db_integrity"] == "ok" and result["http_status"] == 200 and result["free_gb"] >= min_free_gb
    except Exception as exc:
        result["error"] = type(exc).__name__
    return result


def _restore_check(backup: Path) -> dict:
    import tempfile
    if not backup.is_file():
        return {"ok": False, "error": "backup_not_found"}
    with tempfile.TemporaryDirectory(prefix="rx-restore-") as folder:
        raw_path = Path(folder) / "restore.sqlite3"
        try:
            with gzip.open(backup, "rb") as src:
                raw_path.write_bytes(src.read())
            with sqlite3.connect(f"file:{raw_path}?mode=ro", uri=True) as conn:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                tables = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
                accounts = conn.execute("SELECT count(*) FROM platform_accounts").fetchone()[0] if tables else 0
            return {"ok": integrity == "ok" and tables > 0, "integrity": integrity,
                    "tables": tables, "accounts": accounts, "bytes": raw_path.stat().st_size}
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__}


def _stages(db: Path, today: str) -> dict:
    from datetime import date, timedelta
    try:
        current = date.fromisoformat(today)
    except ValueError:
        current = date.today()
    rows = []
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        try:
            plans = conn.execute("SELECT student_id, subject, status, confirmed_at, updated_at FROM demo2_goal_plans").fetchall()
        except sqlite3.Error:
            plans = []
    for student_id, subject, status, confirmed_at, updated_at in plans:
        base = str(confirmed_at or updated_at or "")[:10]
        try:
            start = date.fromisoformat(base)
        except ValueError:
            continue
        for week in (1, 2, 4, 8):
            when = start + timedelta(weeks=week)
            if when <= current:
                rows.append({"student_id": student_id, "subject": subject, "week": week,
                             "due_date": when.isoformat(), "days_overdue": (current - when).days,
                             "status": status})
    rows.sort(key=lambda row: (row["due_date"], row["student_id"], row["week"]))
    return {"today": current.isoformat(), "due_count": len(rows), "due": rows}


def _security(db: Path, url: str) -> dict:
    """Non-invasive production checks; missing headers are reported, not hidden."""
    import stat
    checks = {}
    try:
        mode = stat.S_IMODE(db.stat().st_mode)
        checks["db_private"] = (mode & 0o077) == 0
        checks["db_mode"] = oct(mode)
        parent_mode = stat.S_IMODE(db.parent.stat().st_mode)
        checks["db_parent_private"] = (parent_mode & 0o007) == 0
    except OSError:
        checks["db_private"] = False
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
            checks["journal_mode"] = conn.execute("PRAGMA journal_mode").fetchone()[0]
            checks["integrity"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
    except sqlite3.Error:
        checks["integrity"] = "error"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
        checks["https"] = url.startswith("https://")
        checks["headers"] = {name: bool(headers.get(name)) for name in (
            "x-content-type-options", "x-frame-options", "content-security-policy", "referrer-policy")}
    except Exception as exc:
        checks["http_error"] = type(exc).__name__
    checks["ok"] = bool(checks.get("db_private") and checks.get("integrity") == "ok"
                        and checks.get("db_parent_private"))
    return checks


def _concurrency(base: str, workers: int, count: int) -> dict:
    username = os.environ.get("REHAB_PILOT_USER", "")
    password = os.environ.get("REHAB_PILOT_PASSWORD", "")
    if not username or not password:
        return {"ok": False, "error": "missing_pilot_credentials"}
    login = json.dumps({"username": username, "password": password}).encode()
    def one(_: int) -> int:
        req = urllib.request.Request(base + "/api/v1/demo2/auth/login", data=login, method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            cookie = resp.headers.get("Set-Cookie", "").split(";", 1)[0]
            if not cookie:
                return resp.status
            me = urllib.request.Request(base + "/api/v1/demo2/auth/me", headers={"Cookie": cookie})
            with urllib.request.urlopen(me, timeout=15) as me_resp:
                return me_resp.status
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        statuses = list(pool.map(one, range(count)))
    elapsed = time.monotonic() - started
    return {"ok": all(s == 200 for s in statuses), "workers": workers, "requests": count,
            "status_counts": {str(s): statuses.count(s) for s in sorted(set(statuses))},
            "seconds": round(elapsed, 3)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Cloud pilot backup/health/concurrency checks")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backup")
    b.add_argument("--db", type=Path, required=True)
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--keep", type=int, default=14)
    b.add_argument("--dry-run", action="store_true")
    h = sub.add_parser("health")
    h.add_argument("--url", default="http://127.0.0.1:9184/demo2/login")
    h.add_argument("--db", type=Path, required=True)
    h.add_argument("--min-free-gb", type=float, default=5.0)
    st = sub.add_parser("stages")
    st.add_argument("--db", type=Path, required=True)
    st.add_argument("--today", default="")
    rs = sub.add_parser("restore-check")
    rs.add_argument("--backup", type=Path, required=True)
    sec = sub.add_parser("security")
    sec.add_argument("--db", type=Path, required=True)
    sec.add_argument("--url", default="http://127.0.0.1:9184/demo2/login")
    c = sub.add_parser("concurrency")
    c.add_argument("--base", default="http://127.0.0.1:9184")
    c.add_argument("--workers", type=int, default=5)
    c.add_argument("--requests", type=int, default=10)
    args = parser.parse_args()
    if args.command == "backup":
        print(json.dumps(_backup(args.db, args.out, max(1, args.keep), args.dry_run), ensure_ascii=False))
    elif args.command == "stages":
        print(json.dumps(_stages(args.db, args.today), ensure_ascii=False))
    elif args.command == "restore-check":
        result = _restore_check(args.backup)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["ok"] else 1
    elif args.command == "security":
        result = _security(args.db, args.url)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["ok"] else 1
    elif args.command == "health":
        result = _health(args.url, args.db, args.min_free_gb)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["ok"] else 1
    else:
        result = _concurrency(args.base, max(1, args.workers), max(1, args.requests))
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["ok"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
