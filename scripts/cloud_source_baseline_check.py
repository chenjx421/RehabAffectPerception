"""Compare the live Windows source to its preserved snapshot without row output."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3


def database_digest(path: Path) -> tuple[str, dict[str, int]]:
    if not path.is_file() or path.is_symlink():
        raise ValueError("source_unavailable")
    # A closed WAL database may have no sidecars; immutable avoids creating any.
    wal = Path(str(path) + "-wal")
    if wal.exists() and wal.stat().st_size:
        raise ValueError("source_busy_wal_requires_consistent_backup")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("source_integrity_failed")
        digest, counts = hashlib.sha256(), {}
        names = db.execute("SELECT name FROM sqlite_schema WHERE type='table' ORDER BY name").fetchall()
        for (name,) in names:
            safe = '"' + name.replace('"', '""') + '"'
            rows = db.execute("SELECT * FROM " + safe).fetchall()
            hashes = []
            for row in rows:
                cells = [({"blob": value.hex()} if isinstance(value, bytes) else value) for value in row]
                hashes.append(hashlib.sha256(json.dumps(cells, ensure_ascii=False, allow_nan=False,
                    separators=(",", ":")).encode()).digest())
            digest.update(name.encode() + b"\x00" + b"".join(sorted(hashes)))
            counts[name] = len(rows)
        return digest.hexdigest(), counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()
    try:
        first, counts = database_digest(args.source)
        baseline, baseline_counts = database_digest(args.snapshot)
        second, _ = database_digest(args.source)
        same = first == second == baseline and counts == baseline_counts
        print(json.dumps({"ok": same, "source_unchanged_during_check": first == second,
            "snapshot_rows_identical": same, "accounts": counts.get("platform_accounts"),
            "tasks": counts.get("video_analysis_tasks"), "tables": len(counts), "source_sql_writes": False}))
        return 0 if same else 1
    except ValueError as error:
        print(json.dumps({"ok": False, "code": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
