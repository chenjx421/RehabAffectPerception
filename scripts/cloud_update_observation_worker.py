"""Update only an idle observation worker; leave uploads and the web app running."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess


APP = Path("/opt/rehabaffect")
DB = Path("/var/lib/rehabaffect/seewo_demo2/rehab_affect_demo2.sqlite3")
ENV = Path("/etc/rehabaffect/observations.env")
FILES = ("scripts/cloud_observation_worker.py", "src/rehab_affect/demo2_observation_model.py")


def run(*args):
    result = subprocess.run(args, capture_output=True, timeout=150)
    if result.returncode:
        raise RuntimeError("worker_service_failed")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if os.geteuid() != 0 or args.stage.parent != Path("/opt") or not args.stage.name.startswith("rehabaffect-candidate-"):
        raise ValueError("Root and a verified release stage required")
    for relative in FILES:
        source = args.stage / relative
        if not source.is_file() or source.is_symlink():
            raise ValueError("Incomplete worker release")
        compile(source.read_text(encoding="utf-8"), str(source), "exec")
    with closing(sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True)) as db:
        if db.execute("SELECT count(*) FROM demo2_observation_jobs WHERE status IN ('pending','running')").fetchone()[0]:
            print(json.dumps({"updated": False, "reason": "observation_jobs_active"}))
            return 2
    backup = DB.parent.parent / "cloud_backups" / (
        "before-observation-batching-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    backup.mkdir(mode=0o700, parents=True)
    for relative in FILES:
        target = backup / relative
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        shutil.copy2(APP / relative, target)
    shutil.copy2(ENV, backup / "observations.env")
    run("systemctl", "stop", "rehabaffect-observations.service")
    try:
        for relative in FILES:
            target = APP / relative
            temporary = target.with_suffix(".deploy-new")
            shutil.copyfile(args.stage / relative, temporary)
            temporary.chmod(0o644)
            temporary.replace(target)
        lines = [line for line in ENV.read_text().splitlines()
                 if not line.startswith("REHAB_OBSERVATION_REASONING_EFFORT=")]
        temporary = ENV.with_suffix(".new")
        with temporary.open("x", encoding="utf-8") as stream:
            stream.write("\n".join(lines + ["REHAB_OBSERVATION_REASONING_EFFORT=low"]) + "\n")
        temporary.chmod(0o600)
        temporary.replace(ENV)
        run("systemctl", "start", "rehabaffect-observations.service")
        run("systemctl", "is-active", "rehabaffect-observations.service")
    except Exception:
        run("systemctl", "stop", "rehabaffect-observations.service")
        for relative in FILES:
            shutil.copy2(backup / relative, APP / relative)
        shutil.copy2(backup / "observations.env", ENV)
        run("systemctl", "start", "rehabaffect-observations.service")
        raise RuntimeError("worker_update_failed_restored") from None
    print(json.dumps({"updated": True, "web_app_restarted": False, "backup": str(backup)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
