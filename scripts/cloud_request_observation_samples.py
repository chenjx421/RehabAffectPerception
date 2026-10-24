"""Request observations through authenticated HTTP for two already-uploaded test samples."""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3

import cloud_e2e_acceptance as base


SOURCES = (
    "653edf349db570559d0d54594befb9025768e65ecef7a313f627dda24a9a6b21",
    "9aa93145d891a397c3e404cb40a99a04d233c3adfdd1dbdee0bb931669604eaf",
)


def main():
    private = Path("/var/lib/rehabaffect/acceptance-private")
    schools, _ = base.load_credentials(private / "schools.private.md", private / "admin.private.json")
    client = base.Client("http://127.0.0.1:8793")
    account = client.login(schools[0], "school_uploader")
    requested = []
    try:
        database = Path("/var/lib/rehabaffect/seewo_demo2/rehab_affect_demo2.sqlite3")
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
            for source in SOURCES:
                rows = connection.execute(
                    """SELECT task_id FROM video_analysis_tasks WHERE account_id=? AND sha256=?
                    AND analysis_status='evidence_ready' AND upload_status='completed'
                    ORDER BY created_at DESC LIMIT 8""", (account["account_id"], source)).fetchall()
                for row in rows:
                    status, _, raw = client.request(base.route("/observations"), payload={"task_id": row[0]})
                    if status == 200:
                        workspace = json.loads(raw)["workspace"]
                        requested.append({"task_id": row[0], "source_sha256": source, "status": workspace["status"]})
                        break
        print(json.dumps({"requested": requested, "complete": len(requested) == len(SOURCES)}), flush=True)
        return 0 if len(requested) == len(SOURCES) else 1
    finally:
        client.request(base.route("/auth/logout"), payload={})


if __name__ == "__main__":
    raise SystemExit(main())
