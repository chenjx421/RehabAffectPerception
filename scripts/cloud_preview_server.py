"""Private restored-copy acceptance server. Never used for final public cutover.

The regular retention lifecycle is intentionally not started for this preliminary
copy. Authentication and request-level data authorization remain unchanged.
"""
from pathlib import Path
import os
import signal
import sqlite3
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    if os.environ.get("CLOUD_PREVIEW_ONLY") != "yes":
        raise RuntimeError("Private preview approval required")
    database = Path(os.environ["REHAB_DEMO2_DB_PATH"])
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as conn:
        if conn.execute("SELECT COUNT(*) FROM platform_accounts").fetchone()[0] < 5:
            raise RuntimeError("Preserved accounts required")
    from src.rehab_affect.scenario_lab_server import create_handler, ThreadingHTTPServer
    from src.rehab_affect.student_record_store import get_demo2_student_store
    from src.rehab_affect.demo2_media_worker import VideoAnalysisWorker

    handler = create_handler(scenario_dir=ROOT / "configs/scenarios",
                             model_path=ROOT / "models/unused", policy_name="rule")
    server = ThreadingHTTPServer(("127.0.0.1", 8793), handler)
    worker = VideoAnalysisWorker(get_demo2_student_store())
    stopped = threading.Event()

    def stop(_signum, _frame):
        if not stopped.is_set():
            stopped.set()
            threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        if os.environ.get("REHAB_DEMO2_MEDIA_WORKER") == "1":
            if not worker.start():
                raise RuntimeError("Preview worker lock unavailable")
        print("Private cloud acceptance server on loopback; public cutover is not enabled", flush=True)
        server.serve_forever()
    finally:
        worker.stop()
        server.server_close()


if __name__ == "__main__":
    main()
