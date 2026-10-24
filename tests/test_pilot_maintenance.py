"""All maintenance operations target synthetic temporary databases only."""
import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3

import pytest

from scripts import maintain_school_pilot as maintenance
from src.rehab_affect.student_record_store import Demo2StudentRecordStore


@pytest.fixture
def pilot(tmp_path):
    runtime = tmp_path / ".runtime"
    runtime.mkdir()
    db = tmp_path / "pilot.sqlite3"
    # Real schema and seed logic, but never use the application's default paths.
    store = Demo2StudentRecordStore(db_path=db, upload_dir=tmp_path / "uploads")
    config = runtime / "manager_share_config.json"
    state = runtime / "manager_share_state.json"
    config.write_text("\ufeff" + json.dumps({"invite_secret": "synthetic-invite", "cookie_secret": "synthetic-cookie",
                      "expires_at": maintenance.EXPIRY - 86400, "listen_port": 8796, "upstream_port": 8793,
                      "extra": {"retain": True}}), encoding="utf-8")
    state.write_text(json.dumps({"origin": "https://synthetic.example", "invite_url": "https://synthetic.example/invite#synthetic-invite",
                     "expires_at": maintenance.EXPIRY - 86400, "gateway_pid": 123, "tunnel_pid": 456}), encoding="utf-8")
    with closing(sqlite3.connect(db)) as connection, connection:
        rows = connection.execute("SELECT account_id FROM platform_accounts").fetchall()
        for i, (account_id,) in enumerate(rows):
            connection.execute("INSERT INTO account_sessions VALUES (?,?,?,?,?,?,?)",
                               (f"session-{i}", account_id, f"token-{i}", "2030-01-01", "", "2026-01-01", "2026-01-01"))
    return tmp_path, db, config, state, store


def run(pilot, command, *extra):
    root, db, _, _, _ = pilot
    return maintenance.main([command, "--root", str(root), "--db", str(db), *extra])


def add_task(db, upload="completed", analysis="evidence_ready"):
    with closing(sqlite3.connect(db)) as connection, connection:
        connection.execute("""INSERT INTO video_analysis_tasks
            (task_id,channel_id,session_id,uploader_name,course_name,original_filename,file_path,mime_type,
             byte_size,total_chunks,upload_status,analysis_status,retention_days,expires_at,created_at,updated_at)
            VALUES (hex(randomblob(16)),'channel_1','session','private-name','course','private.mp4','private/path',
                    'video/mp4',100,1,?,?,60,'2030-01-01','2026-01-01','2026-01-01')""", (upload, analysis))


def test_inspect_read_only_redacted(pilot, capsys):
    _, db, config, state, _ = pilot
    add_task(db)
    before = db.read_bytes(), config.read_bytes(), state.read_bytes()
    assert run(pilot, "inspect") == 0
    output = capsys.readouterr().out
    assert json.loads(output)["tasks"]["total"] == 1
    assert (db.read_bytes(), config.read_bytes(), state.read_bytes()) == before
    assert "synthetic-invite" not in output and "private-name" not in output
    assert not list(pilot[0].joinpath(".runtime").glob("maintenance_*"))


@pytest.mark.parametrize("command", ["extend-invite", "rotate-admin"])
def test_confirmation_required(pilot, command):
    before = pilot[1].read_bytes(), pilot[2].read_bytes(), pilot[3].read_bytes()
    assert run(pilot, command) == 1
    assert (pilot[1].read_bytes(), pilot[2].read_bytes(), pilot[3].read_bytes()) == before


@pytest.mark.parametrize("upload,analysis", [("created", "waiting_upload"), ("uploading", "waiting_upload"),
                          ("completed", "queued"), ("completed", "processing"), ("completed", "secret-unknown")])
@pytest.mark.parametrize("command", ["backup", "extend-invite", "rotate-admin"])
def test_refuse_activity(pilot, upload, analysis, command, capsys):
    add_task(pilot[1], upload, analysis)
    before = pilot[2].read_bytes(), pilot[3].read_bytes()
    assert run(pilot, command, "--confirm") == 1
    assert (pilot[2].read_bytes(), pilot[3].read_bytes()) == before
    assert not list(pilot[0].joinpath(".runtime").glob("maintenance_*"))
    assert "secret-unknown" not in capsys.readouterr().err


def test_backup_contains_wal_and_preserves_source(pilot):
    root, db, config, state, _ = pilot
    destination = root / ".runtime/backup"
    with sqlite3.connect(db) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE wal_marker (value TEXT)")
        writer.execute("INSERT INTO wal_marker VALUES ('committed WAL data')")
        writer.commit()
        assert Path(str(db) + "-wal").stat().st_size > 0
        assert run(pilot, "backup", "--backup-dir", str(destination)) == 0
        with sqlite3.connect(destination / "database.sqlite3") as copied:
            assert copied.execute("SELECT value FROM wal_marker").fetchone() == ("committed WAL data",)
            assert copied.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert (destination / config.name).read_bytes() == config.read_bytes()
    assert (destination / state.name).read_bytes() == state.read_bytes()
    assert run(pilot, "backup", "--backup-dir", str(destination)) == 1


def test_extend_preserves_every_other_field_and_retention(pilot):
    _, db, config, state, _ = pilot
    add_task(db, analysis="uploaded_pending_worker")
    add_task(db, upload="cancelled", analysis="cancelled")
    old_config = maintenance.load_json(config)[1]
    old_state = maintenance.load_json(state)[1]
    with maintenance.connect(db) as connection:
        policies = maintenance.row_bytes(connection, "retention_policies")
        tasks = maintenance.row_bytes(connection, "video_analysis_tasks")
    assert run(pilot, "extend-invite", "--confirm") == 0
    assert maintenance.load_json(config)[1] == dict(old_config, expires_at=maintenance.EXPIRY)
    assert maintenance.load_json(state)[1] == dict(old_state, expires_at=maintenance.EXPIRY)
    assert maintenance.EXPIRY_LABEL == "2026-11-06T23:59:59+08:00"
    with maintenance.connect(db) as connection:
        assert maintenance.row_bytes(connection, "retention_policies") == policies
        assert maintenance.row_bytes(connection, "video_analysis_tasks") == tasks


def test_rotation_preserves_identity_schools_sessions_and_seed_guard(pilot, capsys):
    root, db, config, state, store = pilot
    before_files = config.read_bytes(), state.read_bytes()
    with maintenance.connect(db) as connection:
        connection.row_factory = sqlite3.Row
        admin_before = dict(connection.execute("SELECT * FROM platform_accounts WHERE role='company_admin'").fetchone())
        schools = maintenance.row_bytes(connection, "platform_accounts", "role != 'company_admin'")
        sessions = maintenance.row_bytes(connection, "account_sessions", "account_id != ?", (admin_before["account_id"],))
    assert run(pilot, "rotate-admin", "--confirm") == 0
    output = capsys.readouterr()
    credentials = json.loads((root / ".runtime/admin_credentials_20261016.json").read_text())
    assert set(credentials) == {"username", "password"}
    assert credentials["username"] not in output.out + output.err
    assert credentials["password"] not in output.out + output.err
    human = (root / ".runtime/admin_credentials_20261016.txt").read_text()
    assert credentials["password"] in human and credentials["username"] in human
    with maintenance.connect(db) as connection:
        connection.row_factory = sqlite3.Row
        admin = dict(connection.execute("SELECT * FROM platform_accounts WHERE role='company_admin'").fetchone())
        assert admin["account_id"] == admin_before["account_id"]
        for key in admin.keys() - {"username", "password_hash", "password_salt", "password_iterations", "updated_at"}:
            assert admin[key] == admin_before[key]
        assert admin["password_hash"] == hashlib.pbkdf2_hmac("sha256", credentials["password"].encode(),
                      bytes.fromhex(admin["password_salt"]), admin["password_iterations"]).hex()
        assert maintenance.row_bytes(connection, "platform_accounts", "role != 'company_admin'") == schools
        assert maintenance.row_bytes(connection, "account_sessions", "account_id != ?", (admin["account_id"],)) == sessions
        assert connection.execute("SELECT revoked_at FROM account_sessions WHERE account_id=?", (admin["account_id"],)).fetchone()[0]
    assert (config.read_bytes(), state.read_bytes()) == before_files
    # Exercise the main owner's guard without touching any live data.
    with sqlite3.connect(db) as connection:
        store._seed_initial_accounts(connection)
        assert connection.execute("SELECT count(*) FROM platform_accounts").fetchone()[0] == 5
        assert not connection.execute("SELECT 1 FROM platform_accounts WHERE username='company_admin'").fetchone()
    assert store.authenticate_account(credentials["username"], credentials["password"])["account_id"] == admin["account_id"]
    with pytest.raises(ValueError):
        store.authenticate_account("admin", credentials["password"])
    # Existing private output is never overwritten on repeat invocation.
    original = (root / ".runtime/admin_credentials_20261016.json").read_bytes()
    assert run(pilot, "rotate-admin", "--confirm") == 1
    assert (root / ".runtime/admin_credentials_20261016.json").read_bytes() == original


def test_atomic_failure_restores_state(pilot, monkeypatch):
    _, _, config, state, _ = pilot
    before = config.read_bytes(), state.read_bytes()
    replace = maintenance.os.replace
    def fail_config(source, destination):
        if destination == config:
            raise OSError("private synthetic secret must not be printed")
        return replace(source, destination)
    monkeypatch.setattr(maintenance.os, "replace", fail_config)
    assert run(pilot, "extend-invite", "--confirm") == 1
    assert (config.read_bytes(), state.read_bytes()) == before
    assert not list(config.parent.glob("*.tmp"))


def test_fail_closed_schema_and_missing_db(pilot):
    _, db, _, _, _ = pilot
    with sqlite3.connect(db) as connection:
        connection.execute("ALTER TABLE video_analysis_tasks RENAME COLUMN upload_status TO unexpected")
    assert run(pilot, "rotate-admin", "--confirm") == 1
    absent = db.with_name("absent.sqlite3")
    assert run(pilot, "inspect", "--db", str(absent)) == 1
    assert not absent.exists()


def test_acl_failure_rolls_back_rotation(pilot, monkeypatch, capsys):
    root, db, _, _, _ = pilot
    with maintenance.connect(db) as connection:
        before = maintenance.row_bytes(connection, "platform_accounts")
    original = maintenance.protect
    def fail_credentials(path):
        if path.name.startswith("admin_credentials"):
            raise maintenance.Refused("Private ACL unavailable.")
        original(path)
    monkeypatch.setattr(maintenance, "protect", fail_credentials)
    assert run(pilot, "rotate-admin", "--confirm") == 1
    with maintenance.connect(db) as connection:
        assert maintenance.row_bytes(connection, "platform_accounts") == before
    assert not list((root / ".runtime").glob("admin_credentials*"))
    assert "synthetic" not in capsys.readouterr().err


def test_private_file_permissions(tmp_path):
    path = tmp_path / "private.json"
    maintenance.private_write(path, b"synthetic data")
    if os.name == "nt":
        result = maintenance.subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
            "$a=[System.IO.File]::GetAccessControl($env:PILOT_PRIVATE_PATH); "
            "$a.AreAccessRulesProtected; $a.Access.Count; "
            "$a.Access[0].IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value; "
            "[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value"],
            env=dict(os.environ, PILOT_PRIVATE_PATH=str(path)), capture_output=True, text=True,
            creationflags=maintenance.subprocess.CREATE_NO_WINDOW)
        lines = result.stdout.splitlines()
        assert result.returncode == 0
        assert lines[:2] == ["True", "1"] and lines[2] == lines[3]
    else:
        assert path.stat().st_mode & 0o777 == 0o600


def test_atomic_replace_detects_concurrent_edit(tmp_path):
    path = tmp_path / "config.json"
    path.write_bytes(b"concurrent contents")
    with pytest.raises(maintenance.Refused, match="concurrently"):
        maintenance.atomic_replace(path, b"replacement", b"old contents")
    assert path.read_bytes() == b"concurrent contents"
    assert not list(tmp_path.glob("*.tmp"))


def test_rotation_rollback_on_school_invariant_failure(pilot, monkeypatch):
    root, db, _, _, _ = pilot
    original = maintenance.row_bytes
    with maintenance.connect(db) as connection:
        accounts = original(connection, "platform_accounts")
        sessions = original(connection, "account_sessions")
    calls = 0
    def changed_snapshot(connection, table, where="1", parameters=()):
        nonlocal calls
        snapshot = original(connection, table, where, parameters)
        if table == "platform_accounts":
            calls += 1
            if calls == 2:
                return []
        return snapshot
    monkeypatch.setattr(maintenance, "row_bytes", changed_snapshot)
    # No backup needed here: exercise only the transaction against the fixture.
    with maintenance.connect(db, write=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        with pytest.raises(maintenance.Refused, match="bytes changed"):
            maintenance.rotate(connection, root / ".runtime/admin_credentials_20261016.json")
    with maintenance.connect(db) as connection:
        assert original(connection, "platform_accounts") == accounts
        assert original(connection, "account_sessions") == sessions
    assert not list((root / ".runtime").glob("admin_credentials*"))


@pytest.mark.parametrize("count", [0, 2])
def test_rotation_requires_one_admin(pilot, count):
    root, db, _, _, _ = pilot
    with maintenance.connect(db, write=True) as connection:
        connection.execute("BEGIN IMMEDIATE")
        if count == 0:
            connection.execute("UPDATE platform_accounts SET role='school_uploader' WHERE role='company_admin'")
        else:
            connection.execute("UPDATE platform_accounts SET role='company_admin' WHERE username='school_uploader_01'")
        with pytest.raises(maintenance.Refused, match="exactly one"):
            maintenance.rotate(connection, root / ".runtime/admin_credentials_20261016.json")


def test_no_expiry_shortening(pilot):
    _, _, config, state, _ = pilot
    cfg = maintenance.load_json(config)[1]
    cfg["expires_at"] = maintenance.EXPIRY + 86400
    config.write_bytes(maintenance.encoded(cfg))
    before = config.read_bytes(), state.read_bytes()
    with pytest.raises(maintenance.Refused, match="shorten"):
        maintenance.extend(config, state)
    assert (config.read_bytes(), state.read_bytes()) == before


def test_maintenance_lock_and_private_path_boundary(pilot):
    root, _, _, _, _ = pilot
    lock = root / ".runtime/pilot_maintenance.lock"
    lock.write_bytes(b"")
    assert run(pilot, "rotate-admin", "--confirm") == 1
    assert lock.exists()
    assert run(pilot, "inspect") == 0
    with pytest.raises(maintenance.Refused, match="within .runtime"):
        maintenance.private_location(root / "public.json", root)


def test_backup_guard_holds_writer_lock(pilot, monkeypatch):
    _, db, _, _, _ = pilot
    original = maintenance.backup
    def check_lock(*args):
        with closing(sqlite3.connect(db, timeout=0)) as contender:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                contender.execute("BEGIN IMMEDIATE")
        return original(*args)
    monkeypatch.setattr(maintenance, "backup", check_lock)
    assert run(pilot, "backup") == 0
