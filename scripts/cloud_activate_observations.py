"""Install an accepted candidate with an idle check and a reversible code backup."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time


APP = Path("/opt/rehabaffect")
DB = Path("/var/lib/rehabaffect/seewo_demo2/rehab_affect_demo2.sqlite3")
MODULES = (
    "demo2_media_analysis.py", "demo2_observation_model.py", "demo2_observation_store.py",
    "demo2_course_page.py", "scenario_lab_server.py", "demo2_dossier.py", "demo2_identity.py",
    "demo2_portal.py",
)
SCRIPTS = ("cloud_observation_worker.py", "cloud_observation_frames.py", "cloud_observation_acceptance.py")


def run(*args, timeout=150):
    completed = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if completed.returncode:
        raise RuntimeError("service_command_failed")


def service_stopped(unit):
    """Fail closed unless systemd reports no processes and no pending job."""
    try:
        result = subprocess.run(
            ["systemctl", "show", unit,
             "--property=LoadState,ActiveState,MainPID,ControlPID,ControlGroup,TasksCurrent,Job"],
            capture_output=True, timeout=10, text=True)
        state = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        if state.get("LoadState") == "not-found":
            return (state.get("ActiveState") == "inactive"
                    and state.get("MainPID", "0") == "0" and state.get("ControlPID", "0") == "0"
                    and not state.get("ControlGroup") and state.get("Job", "0") in ("", "0"))
        return (result.returncode == 0 and state.get("ActiveState") in ("inactive", "failed")
                and state.get("MainPID") == "0" and state.get("ControlPID") == "0"
                and state.get("Job") in ("", "0")
                and (state.get("ControlGroup") == "" or state.get("TasksCurrent") == "0"))
    except (OSError, subprocess.SubprocessError, TypeError, ValueError, AttributeError):
        return False


def stop_for_restore(unit):
    # An unsuccessful kill is not proof of exit. Verify after every bounded step.
    for command, timeout in (
        (("systemctl", "stop", unit), 150),
        (("systemctl", "kill", "--kill-whom=all", "--signal=SIGKILL", unit), 20),
        (("systemctl", "stop", unit), 20),
    ):
        try:
            run(*command, timeout=timeout)
        except (OSError, subprocess.SubprocessError, RuntimeError):
            pass
        if service_stopped(unit):
            return True
    return False


def recover_gateway():
    for action in ("start", "restart"):
        try:
            run("systemctl", action, "rehabaffect-gateway.service", timeout=30)
            run("systemctl", "is-active", "rehabaffect-gateway.service", timeout=10)
            return
        except (OSError, subprocess.SubprocessError, RuntimeError):
            pass
    raise RuntimeError("gateway_recovery_failed") from None


def idle():
    with closing(sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True)) as connection:
        busy = connection.execute(
            "SELECT count(*) FROM video_analysis_tasks WHERE analysis_status IN ('queued','processing')"
        ).fetchone()[0]
        uploading = connection.execute(
            """SELECT count(*) FROM video_analysis_tasks
            WHERE upload_status='uploading' AND julianday(updated_at)>julianday('now','-2 minutes')"""
        ).fetchone()[0]
        return not (busy or uploading)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if os.geteuid() != 0 or args.stage.parent != Path("/opt") or not args.stage.name.startswith("rehabaffect-candidate-"):
        raise ValueError("Verified root-owned stage required")
    if not Path("/etc/rehabaffect/observations.env").is_file():
        raise ValueError("Private observation configuration required")
    if not service_stopped("rehabaffect-observations.service"):
        raise ValueError("An existing or unverifiable observation worker requires a separate upgrade")
    service = Path("/etc/systemd/system/rehabaffect-observations.service")
    staged_service = args.stage / "deploy/cloud/rehabaffect-observations.service"
    if not staged_service.is_file() or staged_service.is_symlink() or service.is_symlink():
        raise ValueError("Verified observation service required")
    paths = [Path("src/rehab_affect") / name for name in MODULES]
    paths += [Path("scripts") / name for name in SCRIPTS]
    for relative in paths:
        path = args.stage / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError("Candidate incomplete")
    with closing(sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True)) as connection:
        busy = connection.execute(
            "SELECT count(*) FROM video_analysis_tasks WHERE analysis_status IN ('queued','processing')"
        ).fetchone()[0]
        uploading = connection.execute(
            """SELECT count(*) FROM video_analysis_tasks
            WHERE upload_status='uploading' AND julianday(updated_at)>julianday('now','-2 minutes')"""
        ).fetchone()[0]
        if busy or uploading:
            print(json.dumps({"activated": False, "reason": "active_upload_or_analysis"}))
            return 2
        if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Database check failed")
    backup = DB.parent.parent / "cloud_backups" / ("before-observations-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    backup.mkdir(mode=0o700, parents=True)
    with closing(sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True)) as source:
        with closing(sqlite3.connect(backup / "database.sqlite3")) as target:
            source.backup(target)
    manifest = {}
    for relative in paths:
        live = APP / relative
        saved = backup / relative
        saved.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if live.exists():
            shutil.copy2(live, saved)
        manifest[str(relative)] = {"previous": live.exists(),
            "candidate_sha256": hashlib.sha256((args.stage / relative).read_bytes()).hexdigest()}
    (backup / "files.json").write_text(json.dumps(manifest, indent=2))
    previous_service = backup / "observations.service"
    if service.exists():
        shutil.copy2(service, previous_service)
    dropin = Path("/etc/systemd/system/rehabaffect-app.service.d/observations.conf")
    if dropin.exists():
        raise ValueError("Existing observation activation requires review")
    # Stop only the cloud ingress; the app can finish any in-flight work.
    # Restarting this gateway preserves its existing invitation configuration.
    gateway_safe = True
    try:
        run("systemctl", "stop", "rehabaffect-gateway.service")
        if not service_stopped("rehabaffect-gateway.service"):
            raise RuntimeError("ingress_not_stopped")
        time.sleep(2)
        if not idle():
            print(json.dumps({"activated": False, "reason": "work_arrived_during_preparation"}))
            return 2
        try:
            gateway_safe = False
            run("systemctl", "stop", "rehabaffect-app.service")
            if not service_stopped("rehabaffect-app.service") or not service_stopped("rehabaffect-observations.service"):
                raise RuntimeError("deployment_processes_not_stopped")
            if not idle():
                run("systemctl", "start", "rehabaffect-app.service")
                run("systemctl", "is-active", "rehabaffect-app.service", timeout=10)
                gateway_safe = True
                print(json.dumps({"activated": False, "reason": "work_remains_after_drain"}))
                return 2
            for relative in paths:
                live = APP / relative
                temporary = live.with_suffix(".deploy-new")
                shutil.copyfile(args.stage / relative, temporary)
                temporary.chmod(0o644)
                temporary.replace(live)
            dropin.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            dropin.write_text("[Service]\nEnvironmentFile=/etc/rehabaffect/observations.env\n")
            dropin.chmod(0o644)
            shutil.copyfile(staged_service, service)
            service.chmod(0o644)
            run("systemctl", "daemon-reload")
            run("systemctl", "start", "rehabaffect-app.service")
            run("systemctl", "is-active", "rehabaffect-app.service")
            run("systemctl", "enable", "--now", "rehabaffect-observations.service")
            run("systemctl", "is-active", "rehabaffect-observations.service")
            run("systemctl", "is-active", "rehabaffect-app.service", timeout=10)
            gateway_safe = True
        except Exception:
            gateway_safe = False
            stopped = [stop_for_restore(unit) for unit in (
                "rehabaffect-observations.service", "rehabaffect-app.service")]
            if not all(stopped):
                raise RuntimeError("activation_failed_processes_not_stopped_code_not_restored") from None
            disable_failed = False
            try:
                run("systemctl", "disable", "rehabaffect-observations.service", timeout=20)
            except (OSError, subprocess.SubprocessError, RuntimeError):
                disable_failed = True
            for relative in paths:
                saved, live = backup / relative, APP / relative
                if saved.exists():
                    shutil.copy2(saved, live)
                elif live.exists():
                    live.unlink()
            dropin.unlink(missing_ok=True)
            if previous_service.exists():
                shutil.copy2(previous_service, service)
            else:
                service.unlink(missing_ok=True)
            try:
                run("systemctl", "daemon-reload")
            finally:
                run("systemctl", "start", "rehabaffect-app.service")
            run("systemctl", "is-active", "rehabaffect-app.service", timeout=10)
            gateway_safe = True
            # Never restore a stale DB over work submitted after activation.
            reason = "activation_failed_code_restored_worker_disable_failed" if disable_failed else "activation_failed_code_restored"
            raise RuntimeError(reason) from None
    finally:
        if gateway_safe:
            recover_gateway()
        else:
            raise RuntimeError("activation_failed_ingress_left_stopped_app_or_code_unverified") from None
    print(json.dumps({"activated": True, "backup": str(backup), "original_accounts_preserved": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
