"""Locate permitted samples in retained accounts; never change school ownership."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import cloud_e2e_acceptance as base

HASHES = (
    "e92cba448b64c0ecd3b1447db5f3087a5d3b74c6c87b133625e8ab41fccc9079",
    "9aa93145d891a397c3e404cb40a99a04d233c3adfdd1dbdee0bb931669604eaf",
)


def main():
    private = Path("/var/lib/rehabaffect/acceptance-private")
    schools, _ = base.load_credentials(private / "schools.private.md", private / "admin.private.json")
    database = Path("/var/lib/rehabaffect/seewo_demo2/rehab_affect_demo2.sqlite3")
    output = []
    for index, credentials in enumerate(schools):
        client = base.Client("http://127.0.0.1:8793")
        account = client.login(credentials, "school_uploader")
        try:
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
                rows = db.execute(
                    """SELECT task_id,sha256,course_name FROM video_analysis_tasks
                    WHERE account_id=? AND analysis_status='evidence_ready'
                    AND (sha256 IN (?,?) OR course_name='111') ORDER BY created_at DESC LIMIT 15""",
                    (account["account_id"], *HASHES)).fetchall()
            for task_id, source, course in rows:
                status, _, raw = client.request(base.route("/observations", task_id=task_id))
                payload = json.loads(raw)
                workspace = payload.get("workspace", {})
                output.append({
                    "account_index": index, "task_id": task_id,
                    "permitted_sample": source in HASHES, "source_sha256": source,
                    "user_named_111": course == "111", "http_status": status,
                    "observation_status": workspace.get("status"),
                    "error_code": payload.get("error", {}).get("code") if isinstance(payload.get("error"), dict) else None,
                })
        finally:
            client.request(base.route("/auth/logout"), payload={})
    print(json.dumps({"tasks": output}), flush=True)


if __name__ == "__main__":
    main()
