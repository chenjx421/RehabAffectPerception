"""Read-only operational status without student names, documents or credentials."""
from contextlib import closing
import argparse
import json
from pathlib import Path
import sqlite3
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", action="append", default=[])
    args = parser.parse_args()
    database = Path("/var/lib/rehabaffect/seewo_demo2/rehab_affect_demo2.sqlite3")
    report = {}
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        report["database_ok"] = db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        report["active_media_jobs"] = db.execute(
            "SELECT count(*) FROM video_analysis_tasks WHERE analysis_status IN ('queued','processing')"
        ).fetchone()[0]
        report["recent_uploads"] = db.execute(
            """SELECT count(*) FROM video_analysis_tasks WHERE upload_status='uploading'
            AND julianday(updated_at)>julianday('now','-2 minutes')"""
        ).fetchone()[0]
        exists = db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo2_observation_jobs'"
        ).fetchone()
        report["observation_tables_installed"] = bool(exists)
        if exists:
            report["observation_queue"] = dict(db.execute(
                "SELECT status,count(*) FROM demo2_observation_jobs GROUP BY status").fetchall())
            report["selected_jobs"] = []
            for task_id in args.task_id[:10]:
                rows = db.execute(
                    """SELECT task_id,status,error_code,model,source_sha256,created_at,updated_at
                    FROM demo2_observation_jobs WHERE task_id=? ORDER BY created_at DESC LIMIT 1""",
                    (task_id,)).fetchall()
                report["selected_jobs"].extend(dict(row) for row in rows)
    report["services"] = {}
    for service in ("rehabaffect-app", "rehabaffect-gateway", "rehabaffect-observations", "nginx"):
        result = subprocess.run(["systemctl", "is-active", service + ".service"],
                                capture_output=True, text=True, timeout=15)
        report["services"][service] = result.stdout.strip()
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
