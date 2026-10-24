"""Run browser acceptance against an isolated local database."""

from __future__ import annotations

import os
import subprocess
import tempfile
import threading
from pathlib import Path

from src.rehab_affect import scenario_lab_server as server
from src.rehab_affect.student_record_store import Demo2StudentRecordStore


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="demo2-entry-qa-") as temporary:
        temp = Path(temporary)
        store = Demo2StudentRecordStore(temp / "qa.sqlite3", temp / "documents")
        store.set_seeded_pilot_passwords(store.db_path, {
            **{f"t{index}": f"UITest0{index}" for index in range(1, 5)},
            "admin": "UIAdmin1",
        })
        server.get_demo2_student_store = lambda: store
        server.load_seewo_demo2 = lambda: {"students": []}
        handler = server.create_handler(scenario_dir=temp, model_path=temp / "unused.json", policy_name="rule")
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            env = dict(os.environ, DEMO2_ENTRY_URL=f"http://127.0.0.1:{httpd.server_port}")
            return subprocess.run(["node", str(ROOT / "scripts" / "qa_demo2_entry.js")], env=env, cwd=ROOT, check=False).returncode
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
