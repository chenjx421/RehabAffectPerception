"""Offline/operator-controlled pilot maintenance; never initialize or seed a DB.

Run inspect first. Pause application uploads/workers before a confirmed change.
Each mutation takes a fresh private SQLite/config/state backup. Do not rerun the
share launcher: it replaces the secrets and public URL. Config/state replacement
is atomic per file, not a cross-file transaction; backups support crash recovery.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import sqlite3
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
# Shanghai uses UTC+08:00 on this date; no Windows tzdata installation required.
EXPIRY = int(datetime(2026, 11, 6, 23, 59, 59,
                      tzinfo=timezone(timedelta(hours=8), "Asia/Shanghai")).timestamp())
EXPIRY_LABEL = "2026-11-06T23:59:59+08:00"
ACTIVE = {"created", "uploading", "waiting_upload", "queued", "processing"}
INACTIVE = {"completed", "evidence_ready", "uploaded_pending_worker",
            "precheck_complete", "cancelled", "failed", "expired", "deleted"}


class Refused(RuntimeError):
    """Only fixed, non-secret operator messages belong in this exception."""


@contextmanager
def connect(db: Path, *, write: bool = False):
    connection = sqlite3.connect(db.resolve().as_uri() + ("?mode=rw" if write else "?mode=ro"),
                                 uri=True, timeout=5)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        if not write:
            connection.execute("PRAGMA query_only=ON")
        yield connection
    finally:
        connection.close()


def columns(connection, table):
    return [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]


def require_columns(connection, table, required):
    if not set(required) <= set(columns(connection, table)):
        raise Refused("Unsupported database schema; no maintenance performed.")


def activity(connection):
    require_columns(connection, "video_analysis_tasks", {"task_id", "upload_status", "analysis_status"})
    result = {"total": 0, "active": 0, "unknown": 0, "statuses": []}
    for upload, analysis, count in connection.execute(
            "SELECT upload_status, analysis_status, count(*) FROM video_analysis_tasks "
            "GROUP BY upload_status, analysis_status"):
        known = upload in ACTIVE | INACTIVE and analysis in ACTIVE | INACTIVE
        result["total"] += count
        result["active"] += count if upload in ACTIVE or analysis in ACTIVE else 0
        result["unknown"] += 0 if known else count
        # Never echo arbitrary database values, which may contain private data.
        result["statuses"].append({"upload": upload if upload in ACTIVE | INACTIVE else "unknown",
                                   "analysis": analysis if analysis in ACTIVE | INACTIVE else "unknown",
                                   "count": count})
    return result


def require_idle(connection):
    result = activity(connection)
    if result["active"] or result["unknown"]:
        raise Refused("Active or unrecognized tasks exist; pause work and inspect before retrying.")


def load_json(path):
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(value, dict):
        raise Refused("Expected a JSON object.")
    return raw, value


def invitation(config_path, state_path):
    config_raw, config = load_json(config_path)
    state_raw, state = load_json(state_path)
    if any(not isinstance(config.get(key), str) or not config[key]
           for key in ("invite_secret", "cookie_secret")):
        raise Refused("Invitation secrets are missing; refusing to regenerate them.")
    if (not isinstance(state.get("origin"), str) or not state["origin"].startswith("https://")
            or state.get("invite_url") != state["origin"].rstrip("/") + "/invite#" + config["invite_secret"]):
        raise Refused("Invitation state does not match config; refusing changes.")
    for value in (config, state):
        expiry = value.get("expires_at")
        if isinstance(expiry, bool) or not isinstance(expiry, (int, float)) or not math.isfinite(expiry):
            raise Refused("Invalid invitation expiry.")
    return config_raw, config, state_raw, state


def protect(path):
    """Restrict an empty output before any credentials or backup bytes are written."""
    if os.name == "nt":
        script = (
            "$ErrorActionPreference='Stop'; $p=$env:PILOT_PRIVATE_PATH; "
            "$sid=[System.Security.Principal.WindowsIdentity]::GetCurrent().User; "
            "$isDir=[System.IO.Directory]::Exists($p); "
            "$rights=if($isDir){':(OI)(CI)F'}else{':F'}; "
            "& icacls.exe $p /inheritance:r /grant:r ('*'+$sid.Value+$rights) | Out-Null; "
            "if($LASTEXITCODE -ne 0){exit 1}"
        )
        env = dict(os.environ, PILOT_PRIVATE_PATH=str(path.resolve()))
        process = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                 env=env, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if process.returncode:
            raise Refused("Cannot establish private Windows ACL; refusing to write secrets.")
    else:
        path.chmod(0o700 if path.is_dir() else 0o600)


def private_write(path, data):
    # O_EXCL also refuses existing files and symlinks.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            protect(path)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def atomic_replace(path, data, expected):
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        private_write(temporary, data)
        if path.read_bytes() != expected:
            raise Refused("Configuration changed concurrently; refusing overwrite.")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def private_location(path, root):
    runtime = (root / ".runtime").resolve()
    resolved = path.resolve()
    if not resolved.is_relative_to(runtime) or resolved == runtime or path.is_symlink():
        raise Refused("Private output must be a new path within .runtime.")
    return resolved


def backup(db, config_path, state_path, destination):
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    protect(destination)
    # SQLite's backup API includes committed WAL pages; copying the DB file does not.
    with connect(db) as source:
        target = sqlite3.connect(destination / "database.sqlite3")
        try:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise Refused("Backup integrity check failed.")
        finally:
            target.close()
    private_write(destination / "manager_share_config.json", config_path.read_bytes())
    private_write(destination / "manager_share_state.json", state_path.read_bytes())
    return destination


def row_bytes(connection, table, where="1", parameters=()):
    # Compare every column's storage type AND raw value, including future columns.
    names = columns(connection, table)
    projection = ",".join('typeof("{0}"),hex(CAST("{0}" AS BLOB))'.format(name.replace('"', '""'))
                          for name in names)
    return sorted(tuple(row) for row in connection.execute(
        f'SELECT {projection} FROM "{table}" WHERE {where}', parameters))


def rotate(connection, credentials):
    require_columns(connection, "platform_accounts", {"account_id", "username", "password_hash", "password_salt",
                    "password_iterations", "role", "updated_at", "status"})
    require_columns(connection, "account_sessions", {"account_id", "revoked_at"})
    admins = connection.execute("SELECT account_id FROM platform_accounts WHERE role='company_admin'").fetchall()
    if len(admins) != 1:
        raise Refused("Expected exactly one company administrator; refusing ambiguous rotation.")
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='trigger' AND "
                          "tbl_name IN ('platform_accounts','account_sessions')").fetchone():
        raise Refused("Account/session triggers require manual review before rotation.")
    account_id = admins[0][0]
    accounts_before = row_bytes(connection, "platform_accounts", "account_id != ?", (account_id,))
    sessions_before = row_bytes(connection, "account_sessions", "account_id != ?", (account_id,))
    username = "pilot_admin_" + secrets.token_hex(8)
    password = secrets.token_urlsafe(32)
    salt = secrets.token_bytes(16)
    iterations = 210_000
    password_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations).hex()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    text_path = credentials.with_suffix(".txt")
    if credentials.exists() or text_path.exists():
        raise Refused("Credential output already exists; choose new private filenames.")
    written = []
    try:
        private_write(credentials, encoded({"username": username, "password": password}))
        written.append(credentials)
        private_write(text_path, ("School pilot administrator\nUsername: " + username + "\nPassword: " + password + "\n").encode())
        written.append(text_path)
        cursor = connection.execute(
            "UPDATE platform_accounts SET username=?,password_hash=?,password_salt=?,password_iterations=?,updated_at=? "
            "WHERE account_id=? AND role='company_admin'",
            (username, password_hash, salt.hex(), iterations, now, account_id))
        if cursor.rowcount != 1:
            raise Refused("Administrator changed concurrently.")
        revoked = connection.execute("UPDATE account_sessions SET revoked_at=? WHERE account_id=? AND revoked_at=''",
                                     (now, account_id)).rowcount
        if (accounts_before != row_bytes(connection, "platform_accounts", "account_id != ?", (account_id,))
                or sessions_before != row_bytes(connection, "account_sessions", "account_id != ?", (account_id,))):
            raise Refused("Non-admin account/session bytes changed; rolling back.")
        connection.commit()
    except BaseException:
        connection.rollback()
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return {"admin_sessions_revoked": revoked, "school_accounts_byte_unchanged": True,
            "credentials_file": str(credentials), "credentials_text_file": str(text_path)}


def extend(config_path, state_path):
    config_raw, config, state_raw, state = invitation(config_path, state_path)
    if config["expires_at"] > EXPIRY or state["expires_at"] > EXPIRY:
        raise Refused("Existing expiry is later than target; refusing to shorten it.")
    config["expires_at"] = state["expires_at"] = EXPIRY
    new_config, new_state = encoded(config), encoded(state)
    atomic_replace(state_path, new_state, state_raw)
    try:
        atomic_replace(config_path, new_config, config_raw)
    except BaseException:
        atomic_replace(state_path, state_raw, new_state)
        raise
    return {"expires_at": EXPIRY, "expires_at_shanghai": EXPIRY_LABEL,
            "invitation_identity_preserved": True}


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=("inspect", "backup", "extend-invite", "rotate-admin"))
    result.add_argument("--root", type=Path, default=ROOT)
    result.add_argument("--db", type=Path, help="Existing database; defaults to REHAB_DEMO2_DB_PATH or repo database")
    result.add_argument("--config", type=Path)
    result.add_argument("--state", type=Path)
    result.add_argument("--backup-dir", type=Path, help="New .runtime directory; never overwrites an existing backup")
    result.add_argument("--credentials", type=Path, help="New .runtime JSON file; also creates a sibling .txt")
    result.add_argument("--confirm", action="store_true", help="Explicitly authorize an expiry/admin change")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        root = args.root.resolve()
        db = args.db or Path(os.environ.get("REHAB_DEMO2_DB_PATH", root / "outputs/seewo_demo2/rehab_affect_demo2.sqlite3"))
        config = args.config or root / ".runtime/manager_share_config.json"
        state = args.state or root / ".runtime/manager_share_state.json"
        if args.command == "inspect":
            with connect(db) as connection:
                connection.execute("BEGIN")
                report = activity(connection)
            _, cfg, _, _ = invitation(config, state)
            print(json.dumps({"tasks": report, "expires_at": cfg["expires_at"],
                              "safe_to_maintain": not (report["active"] or report["unknown"])}))
            return 0
        if args.command != "backup" and not args.confirm:
            raise Refused("Mutation requires --confirm after inspecting and pausing uploads/workers.")
        invitation(config, state)
        credentials = private_location(args.credentials or root / ".runtime/admin_credentials_20261016.json", root)
        if credentials.suffix.lower() != ".json":
            raise Refused("Credential output must have a .json suffix.")
        destination = private_location(args.backup_dir or root / ".runtime" /
                                       ("maintenance_" + datetime.now().strftime("%Y%m%d_%H%M%S_") + secrets.token_hex(4)), root)
        lock = root / ".runtime/pilot_maintenance.lock"
        try:
            lock_fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise Refused("Maintenance lock exists; verify no maintenance is running before removing it.") from None
        try:
            os.close(lock_fd)
            with connect(db, write=True) as connection:
                # Hold the writer reservation across activity check, backup and change.
                connection.execute("BEGIN IMMEDIATE")
                require_idle(connection)
                backup(db, config, state, destination)
                report = {"command": args.command, "backup_directory": str(destination)}
                if args.command == "extend-invite":
                    report.update(extend(config, state))
                elif args.command == "rotate-admin":
                    report.update(rotate(connection, credentials))
                connection.rollback()
            print(json.dumps(report))
            return 0
        finally:
            lock.unlink(missing_ok=True)
    except Refused as error:
        print(str(error), file=sys.stderr)
    except (OSError, ValueError, TypeError, sqlite3.Error):
        # Exceptions may contain SQL values, config contents or private paths.
        print("Maintenance failed; inspect private backup/files before retrying. No secret details logged.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
