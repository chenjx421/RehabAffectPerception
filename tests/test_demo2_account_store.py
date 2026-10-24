from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from rehab_affect import student_record_store as store_module
from rehab_affect.student_record_store import (
    PILOT_ACCOUNT_ALIASES,
    Demo2StudentRecordStore,
    RegistrationRateLimitError,
)


PASSWORD_PREFIX = "AccountStoreTest-"


@pytest.fixture()
def account_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Demo2StudentRecordStore:
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", PASSWORD_PREFIX)
    return Demo2StudentRecordStore(tmp_path / "demo2.sqlite3", tmp_path / "student_documents")


def _password(username: str) -> str:
    return f"{PASSWORD_PREFIX}{username}"


def _video_payload(
    account_id: str,
    *,
    channel_id: str = "channel_1",
    course_id: str = "course_a",
    index: int = 1,
) -> dict[str, object]:
    return {
        "account_id": account_id,
        "channel_id": channel_id,
        "session_id": f"lesson-{course_id}",
        "uploader_name": "测试学校",
        "course_id": course_id,
        "course_name": "内测课程",
        "filename": f"clip-{index}.mp4",
        "byte_size": 1,
        "total_chunks": 1,
    }


def test_seeded_accounts_have_fixed_bindings_and_only_password_hashes(
    account_store: Demo2StudentRecordStore,
) -> None:
    with sqlite3.connect(account_store.db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT * FROM platform_accounts ORDER BY username"
        ).fetchall()

    assert len(rows) == 5
    uploaders = [row for row in rows if row["role"] == "school_uploader"]
    assert [row["username"] for row in uploaders] == [
        "school_uploader_01",
        "school_uploader_02",
        "school_uploader_03",
        "school_uploader_04",
    ]
    assert [row["bound_channel_id"] for row in uploaders] == [
        "channel_1",
        "channel_2",
        "channel_3",
        "channel_4",
    ]
    assert all(row["course_upload_limit"] == 5 for row in uploaders)
    admin = next(row for row in rows if row["username"] == "company_admin")
    assert admin["role"] == "company_admin"
    assert admin["bound_channel_id"] is None
    assert all(row["password_hash"] != _password(row["username"]) for row in rows)
    assert all(row["password_salt"] and row["password_iterations"] > 0 for row in rows)


def test_authentication_session_lookup_and_logout(account_store: Demo2StudentRecordStore) -> None:
    username = "school_uploader_01"
    account = account_store.authenticate_account(username, _password(username))
    assert account["bound_channel_id"] == "channel_1"
    assert "password_hash" not in account

    with pytest.raises(ValueError, match="账号或密码错误"):
        account_store.authenticate_account(username, "wrong-password")

    session = account_store.create_account_session(account)
    assert account_store.account_from_session(session["token"])["account_id"] == account["account_id"]
    with sqlite3.connect(account_store.db_path) as connection:
        stored = connection.execute(
            "SELECT token_hash FROM account_sessions WHERE session_id = ?",
            (session["session_id"],),
        ).fetchone()[0]
    assert stored == hashlib.sha256(session["token"].encode("utf-8")).hexdigest()
    assert stored != session["token"]

    assert account_store.revoke_account_session(session["token"])["revoked"] is True
    with pytest.raises(ValueError, match="会话无效"):
        account_store.account_from_session(session["token"])


def test_session_expiry_is_rejected_and_audited(account_store: Demo2StudentRecordStore) -> None:
    username = "school_uploader_02"
    account = account_store.authenticate_account(username, _password(username))
    session = account_store.create_account_session(account)
    with sqlite3.connect(account_store.db_path) as connection:
        connection.execute(
            "UPDATE account_sessions SET expires_at = '2000-01-01T00:00:00+00:00' WHERE session_id = ?",
            (session["session_id"],),
        )

    with pytest.raises(ValueError, match="会话已过期"):
        account_store.account_from_session(session["token"])
    with sqlite3.connect(account_store.db_path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE action = 'session_expired'"
        ).fetchone()[0]
    assert count == 1


def test_selectable_channel_and_five_video_course_quota(account_store: Demo2StudentRecordStore) -> None:
    username = "school_uploader_01"
    account = account_store.authenticate_account(username, _password(username))
    session = account_store.create_account_session(account)

    selected = account_store.create_video_task(
        _video_payload(account["account_id"], channel_id="channel_2")
    )
    assert selected["channel_id"] == "channel_2"

    for index in range(2, 6):
        task = account_store.create_video_task(
            _video_payload(account["account_id"], index=index)
        )
        assert task["account_id"] == account["account_id"]

    with pytest.raises(ValueError, match="上传名额已满"):
        account_store.create_video_task(
            _video_payload(account["account_id"], index=6)
        )

    workspace = account_store.account_upload_workspace(session["token"], "course_a")
    assert workspace["used_slots"] == 5
    assert workspace["max_slots"] == 5
    assert workspace["remaining_slots"] == 0
    assert len(workspace["tasks"]) == 5
    assert {task["channel_id"] for task in workspace["tasks"]} == {"channel_1", "channel_2"}
    with sqlite3.connect(account_store.db_path) as connection:
        quota_rejections = connection.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE action = 'quota_rejected'"
        ).fetchone()[0]
    assert quota_rejections == 1


def test_cancelling_incomplete_upload_releases_quota_and_removes_part_file(
    account_store: Demo2StudentRecordStore,
) -> None:
    username = "school_uploader_01"
    account = account_store.authenticate_account(username, _password(username))
    session = account_store.create_account_session(account)
    tasks = [
        account_store.create_video_task(
            _video_payload(account["account_id"], index=index)
        )
        for index in range(1, 6)
    ]
    cancelled = account_store.cancel_video_task(session["token"], tasks[0]["task_id"])

    assert cancelled["upload_status"] == "cancelled"
    assert cancelled["analysis_status"] == "cancelled"
    workspace = account_store.account_upload_workspace(session["token"], "course_a")
    assert workspace["used_slots"] == 4
    assert workspace["remaining_slots"] == 1
    assert any(task["upload_status"] == "cancelled" for task in workspace["tasks"])
    replacement = account_store.create_video_task(
        _video_payload(account["account_id"], index=6)
    )
    assert replacement["upload_status"] == "uploading"

    with sqlite3.connect(account_store.db_path) as connection:
        row = connection.execute(
            "SELECT file_path FROM video_analysis_tasks WHERE task_id = ?",
            (tasks[0]["task_id"],),
        ).fetchone()
        audit_count = connection.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE action = 'upload_cancelled'"
        ).fetchone()[0]
    assert not Path(f"{row[0]}.part").exists()
    assert audit_count == 1


def test_incomplete_upload_progress_never_rounds_up_to_complete(
    account_store: Demo2StudentRecordStore,
) -> None:
    username = "school_uploader_02"
    account = account_store.authenticate_account(username, _password(username))
    byte_size = 4 * 1024 * 1024 + 1
    payload = _video_payload(account["account_id"], channel_id="channel_2")
    payload.update({"byte_size": byte_size, "total_chunks": 2})
    task = account_store.create_video_task(payload)

    first = account_store.append_video_chunk(
        {
            "task_id": task["task_id"],
            "chunk_index": 0,
            "content_base64": base64.b64encode(b"x" * (4 * 1024 * 1024)).decode("ascii"),
        }
    )
    assert first["upload_status"] == "uploading"
    assert first["progress_percent"] == 99

    completed = account_store.append_video_chunk(
        {
            "task_id": task["task_id"],
            "chunk_index": 1,
            "content_base64": base64.b64encode(b"y").decode("ascii"),
        }
    )
    assert completed["upload_status"] == "completed"
    assert completed["progress_percent"] == 100


def test_retention_executor_deletes_raw_media_but_preserves_results_and_metadata(
    account_store: Demo2StudentRecordStore,
) -> None:
    username = "school_uploader_03"
    account = account_store.authenticate_account(username, _password(username))
    session = account_store.create_account_session(account)
    completed = account_store.create_video_task(
        _video_payload(
            account["account_id"],
            channel_id="channel_3",
            course_id="retention-course",
            index=1,
        )
    )
    incomplete = account_store.create_video_task(
        _video_payload(
            account["account_id"],
            channel_id="channel_3",
            course_id="retention-course",
            index=2,
        )
    )
    scan_time = datetime.now().astimezone()
    expired_at = (scan_time - timedelta(minutes=1)).isoformat(timespec="seconds")
    result_path = account_store.video_task_dir / "results" / f"{completed['task_id']}.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text('{"preserved": true}', encoding="utf-8")

    with sqlite3.connect(account_store.db_path) as connection:
        completed_file = Path(
            connection.execute(
                "SELECT file_path FROM video_analysis_tasks WHERE task_id = ?",
                (completed["task_id"],),
            ).fetchone()[0]
        )
        incomplete_file = Path(
            connection.execute(
                "SELECT file_path FROM video_analysis_tasks WHERE task_id = ?",
                (incomplete["task_id"],),
            ).fetchone()[0]
        )
        Path(f"{completed_file}.part").unlink()
        completed_file.write_bytes(b"raw-video")
        connection.execute(
            """
            UPDATE video_analysis_tasks
            SET upload_status = 'completed', analysis_status = 'precheck_complete',
                result_path = ?, expires_at = ? WHERE task_id = ?
            """,
            (str(result_path.resolve()), expired_at, completed["task_id"]),
        )
        connection.execute(
            "UPDATE video_analysis_tasks SET expires_at = ? WHERE task_id = ?",
            (expired_at, incomplete["task_id"]),
        )

    outcome = account_store.enforce_raw_media_retention(now=scan_time)
    assert outcome["deleted_count"] == 2
    assert outcome["failed"] == []
    assert not completed_file.exists()
    assert not Path(f"{incomplete_file}.part").exists()
    assert result_path.exists()

    workspace = account_store.account_upload_workspace(
        session["token"], "retention-course"
    )
    tasks = {task["task_id"]: task for task in workspace["tasks"]}
    assert tasks[completed["task_id"]]["upload_status"] == "completed"
    assert tasks[completed["task_id"]]["retention_state"] == "deleted"
    assert tasks[incomplete["task_id"]]["upload_status"] == "expired"
    assert workspace["used_slots"] == 1
    assert workspace["remaining_slots"] == 4
    assert account_store.enforce_raw_media_retention(now=scan_time)["deleted_count"] == 0
    with sqlite3.connect(account_store.db_path) as connection:
        audit_count = connection.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE action = 'retention_delete'"
        ).fetchone()[0]
    assert audit_count == 2


def test_upload_workspace_returns_students_and_latest_course_acceptance(
    account_store: Demo2StudentRecordStore,
) -> None:
    account_store.ensure_students(
        [
            {"student_id": "student_A", "display_name": "学生甲"},
            {"student_id": "student_B", "display_name": "学生乙"},
        ]
    )
    account_store.record_security_acceptance(
        {
            "course_id": "course_workspace",
            "course_name": "工作区课程",
            "confirmed_by": "测试教师",
            "security_confirmed": True,
        }
    )
    username = "school_uploader_01"
    account = account_store.authenticate_account(username, _password(username))
    session = account_store.create_account_session(account)

    workspace = account_store.account_upload_workspace(
        session["token"], "course_workspace"
    )
    assert workspace["students"] == [
        {"student_id": "student_A", "display_name": "学生甲"},
        {"student_id": "student_B", "display_name": "学生乙"},
    ]
    assert workspace["security_acceptance"]["course_id"] == "course_workspace"
    assert workspace["security_acceptance"]["confirmed_by"] == "测试教师"
    assert (
        account_store.account_upload_workspace(session["token"], "course_without_acceptance")[
            "security_acceptance"
        ]
        is None
    )


def test_company_admin_summary_covers_accounts_channels_usage_and_retention(
    account_store: Demo2StudentRecordStore,
) -> None:
    uploader_name = "school_uploader_03"
    uploader = account_store.authenticate_account(uploader_name, _password(uploader_name))
    account_store.create_video_task(
        _video_payload(
            uploader["account_id"],
            channel_id="channel_3",
            course_id="course_summary",
        )
    )
    account_store.record_security_acceptance(
        {
            "course_id": "course_summary",
            "course_name": "内测课程",
            "confirmed_by": "汇总教师",
            "security_confirmed": True,
        }
    )
    admin = account_store.authenticate_account("company_admin", _password("company_admin"))
    session = account_store.create_account_session(admin)
    summary = account_store.admin_platform_summary(session["token"])

    assert len(summary["upload_accounts"]) == 4
    assert len(summary["channels"]) == 4
    assert summary["task_status"]["total"] == 1
    assert summary["course_usage"][0]["course_id"] == "course_summary"
    assert summary["course_usage"][0]["used_slots"] == 1
    assert summary["recent_uploads"][0]["username"] == uploader_name
    assert summary["recent_uploads"][0]["channel_id"] == "channel_3"
    assert summary["recent_uploads"][0]["original_filename"] == "clip-1.mp4"
    assert summary["recent_uploads"][0]["byte_size"] == 1
    assert summary["recent_uploads"][0]["subject_id"] == ""
    assert "file_path" not in summary["recent_uploads"][0]
    assert "result_path" not in summary["recent_uploads"][0]
    assert summary["recent_security_acceptances"][0]["confirmed_by"] == "汇总教师"
    assert summary["retention"]["raw_media_retention_days"] == 60
    assert summary["retention"]["expiry_reminder_days"] == 15
    assert set(summary["storage"]) == {
        "database",
        "document_storage",
        "report_storage",
        "video_task_storage",
    }
    for section in summary["storage"].values():
        assert "location" not in section
        assert "file_path" not in section
        assert "result_path" not in section
        assert "byte_size" in section
    assert summary["storage"]["database"]["engine"] == "SQLite 3"
    assert summary["storage"]["database"]["sqlite_user_version"] == 6
    with sqlite3.connect(account_store.db_path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE action = 'view_summary'"
        ).fetchone()[0]
    assert count == 1


def test_account_result_download_enforces_task_ownership_and_keeps_legacy_url(
    account_store: Demo2StudentRecordStore,
) -> None:
    owner_name = "school_uploader_01"
    other_name = "school_uploader_02"
    owner = account_store.authenticate_account(owner_name, _password(owner_name))
    other = account_store.authenticate_account(other_name, _password(other_name))
    admin = account_store.authenticate_account("company_admin", _password("company_admin"))
    owner_session = account_store.create_account_session(owner)
    other_session = account_store.create_account_session(other)
    admin_session = account_store.create_account_session(admin)
    task = account_store.create_video_task(_video_payload(owner["account_id"]))
    completed = account_store.append_video_chunk(
        {
            "task_id": task["task_id"],
            "chunk_index": 0,
            "content_base64": base64.b64encode(b"x").decode("ascii"),
        }
    )
    assert completed["analysis_status"] == "queued"
    assert account_store.claim_next_video_analysis()["task_id"] == task["task_id"]
    completed = account_store.finish_video_analysis(
        task["task_id"], {"version": "fixture-v1", "content": {}}
    )

    assert completed["result_download_url"].startswith(
        "/api/seewo_demo2/video_result_download"
    )
    assert completed["secure_result_download_url"] == (
        f"/api/v1/demo2/upload/result?id={task['task_id']}"
    )
    owner_path, owner_filename = account_store.account_video_result_for_download(
        owner_session["token"], task["task_id"]
    )
    assert owner_path.is_file()
    assert owner_filename.endswith("视频证据记录.json")
    with pytest.raises(ValueError, match="无权下载"):
        account_store.account_video_result_for_download(
            other_session["token"], task["task_id"]
        )
    admin_path, _ = account_store.account_video_result_for_download(
        admin_session["token"], task["task_id"]
    )
    assert admin_path == owner_path


def test_v2_database_upgrades_without_losing_video_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", PASSWORD_PREFIX)
    db_path = tmp_path / "v2.sqlite3"
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE video_analysis_tasks (
                task_id TEXT PRIMARY KEY,
                channel_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                uploader_name TEXT NOT NULL,
                course_id TEXT NOT NULL DEFAULT '',
                course_name TEXT NOT NULL,
                subject_id TEXT NOT NULL DEFAULT '',
                original_filename TEXT NOT NULL,
                file_path TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                received_bytes INTEGER NOT NULL DEFAULT 0,
                total_chunks INTEGER NOT NULL,
                next_chunk_index INTEGER NOT NULL DEFAULT 0,
                sha256 TEXT NOT NULL DEFAULT '',
                upload_status TEXT NOT NULL DEFAULT 'created',
                analysis_status TEXT NOT NULL DEFAULT 'waiting_upload',
                result_path TEXT NOT NULL DEFAULT '',
                retention_days INTEGER NOT NULL,
                reminder_days INTEGER NOT NULL DEFAULT 15,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO video_analysis_tasks VALUES (
                'legacy-task', 'channel_1', 'legacy-session', 'legacy-uploader',
                'legacy-course', '旧课程', '', 'legacy.mp4', 'legacy.mp4',
                'video/mp4', 10, 10, 1, 1, '', 'completed', 'precheck_complete',
                '', 60, 15, '2026-12-01T00:00:00+08:00',
                '2026-08-01T00:00:00+08:00', '2026-08-01T00:00:00+08:00'
            );
            PRAGMA user_version = 2;
            """
        )

    store = Demo2StudentRecordStore(db_path, tmp_path / "documents")
    with sqlite3.connect(store.db_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(video_analysis_tasks)")
        }
        legacy = connection.execute(
            "SELECT task_id, account_id FROM video_analysis_tasks WHERE task_id = 'legacy-task'"
        ).fetchone()
        account_count = connection.execute("SELECT COUNT(*) FROM platform_accounts").fetchone()[0]

    assert version == 6
    assert "account_id" in columns
    assert "raw_media_deleted_at" in columns
    assert "school_context_json" in columns
    assert "processing_config_json" in columns
    assert "processing_progress" in columns
    assert legacy == ("legacy-task", None)
    assert account_count == 5


@pytest.mark.parametrize("alias,username", PILOT_ACCOUNT_ALIASES.items())
def test_short_aliases_keep_existing_identity_and_password(account_store, alias, username) -> None:
    original = account_store.authenticate_account(username, _password(username))
    via_alias = account_store.authenticate_account(f" {alias} ", _password(username))
    assert original == via_alias
    assert via_alias["username"] == username
    assert via_alias["login_alias"] == alias


def _pilot_passwords() -> dict[str, str]:
    return {alias: f"Pilot{index:03d}" for index, alias in enumerate(PILOT_ACCOUNT_ALIASES)}


def test_pilot_password_update_is_explicit_hashed_persistent_and_revokes_sessions(account_store) -> None:
    passwords = _pilot_passwords()
    account = account_store.authenticate_account("t1", _password("school_uploader_01"))
    token = account_store.create_account_session(account)["token"]
    with sqlite3.connect(account_store.db_path) as connection:
        before = connection.execute(
            "SELECT account_id, username, role, bound_channel_id, status FROM platform_accounts ORDER BY username"
        ).fetchall()
    result = Demo2StudentRecordStore.set_seeded_pilot_passwords(account_store.db_path, passwords)
    assert result == {"updated_accounts": list(PILOT_ACCOUNT_ALIASES.values())}
    reopened = Demo2StudentRecordStore(account_store.db_path, account_store.upload_dir)
    for alias, password in passwords.items():
        assert reopened.authenticate_account(alias, password)["username"] == PILOT_ACCOUNT_ALIASES[alias]
        with pytest.raises(ValueError):
            reopened.authenticate_account(alias, _password(PILOT_ACCOUNT_ALIASES[alias]))
    with pytest.raises(ValueError):
        reopened.account_from_session(token)
    with sqlite3.connect(account_store.db_path) as connection:
        after = connection.execute(
            "SELECT account_id, username, role, bound_channel_id, status FROM platform_accounts ORDER BY username"
        ).fetchall()
        hashes = connection.execute("SELECT password_hash, password_salt FROM platform_accounts").fetchall()
        audits = connection.execute("SELECT detail_json FROM audit_logs WHERE action = 'pilot_password_set'").fetchall()
    assert before == after
    assert len(audits) == 5
    assert len({row[1] for row in hashes}) == 5
    assert all(password not in json.dumps([hashes, audits, result]) for password in passwords.values())


def test_pilot_password_update_rejects_invalid_maps_and_missing_seeds_atomically(account_store, tmp_path) -> None:
    passwords = _pilot_passwords()
    with sqlite3.connect(account_store.db_path) as connection:
        before = connection.execute("SELECT username, password_hash FROM platform_accounts ORDER BY username").fetchall()
    for invalid in (
        {}, {**passwords, "new_user": "Unused-99"},
        {**passwords, "t1": "short"}, {**passwords, "t1": None},
        {**passwords, "admin": passwords["t1"]}, {**passwords, "t1": "x" * 129},
    ):
        with pytest.raises(ValueError):
            Demo2StudentRecordStore.set_seeded_pilot_passwords(account_store.db_path, invalid)
    with sqlite3.connect(account_store.db_path) as connection:
        assert before == connection.execute("SELECT username, password_hash FROM platform_accounts ORDER BY username").fetchall()
        connection.execute("DELETE FROM platform_accounts WHERE username = 'company_admin'")
    with pytest.raises(ValueError):
        Demo2StudentRecordStore.set_seeded_pilot_passwords(account_store.db_path, passwords)
    with sqlite3.connect(account_store.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM platform_accounts").fetchone()[0] == 4
        assert connection.execute("SELECT username, password_hash FROM platform_accounts ORDER BY username").fetchall() == before[1:]
        assert connection.execute("SELECT COUNT(*) FROM audit_logs WHERE action = 'pilot_password_set'").fetchone()[0] == 0
    missing = tmp_path / "must-not-create.sqlite3"
    with pytest.raises(sqlite3.OperationalError):
        Demo2StudentRecordStore.set_seeded_pilot_passwords(missing, passwords)
    assert not missing.exists()


def _school_context() -> dict[str, str]:
    return {"city": "Test City", "district": "Test District", "school_name": "Test School"}


def _account_session(store, alias="t1") -> str:
    account = store.authenticate_account(alias, _password(PILOT_ACCOUNT_ALIASES[alias]))
    return store.create_account_session(account)["token"]


def test_school_context_is_account_metadata_and_task_snapshot_ignores_payload(account_store) -> None:
    owner_token = _account_session(account_store)
    other_token = _account_session(account_store, "t2")
    empty = {"context": {key: "" for key in _school_context()}, "options": []}
    initial = account_store.account_school_context(owner_token)
    assert {key: initial[key] for key in empty} == empty
    assert initial['selection_enabled'] and initial['directory']['coverage']['complete'] is False
    context = _school_context()
    saved = account_store.save_account_school_context(owner_token, context)
    assert saved['context'] == context and saved['options'] == [context]
    assert saved['details']['source_status'] == 'pending'
    other = account_store.account_school_context(other_token)
    assert {key: other[key] for key in empty} == empty
    account = account_store.account_from_session(owner_token)
    assert account["role"] == "school_uploader" and account["bound_channel_id"] == "channel_1"
    with pytest.raises(ValueError):
        account_store.admin_platform_summary(owner_token)
    payload = {**_video_payload(account["account_id"]), "school_context": {"school_name": "Forged"}}
    task = account_store.create_video_task(payload)
    assert task["school_context"] == context
    account_store.save_account_school_context(owner_token, {**context, "school_name": "Updated School"})
    workspace = account_store.account_upload_workspace(owner_token, "course_a")
    assert workspace["tasks"][0]["school_context"] == context
    reopened = Demo2StudentRecordStore(account_store.db_path, account_store.upload_dir)
    assert reopened.account_school_context(owner_token)["context"]["school_name"] == "Updated School"
    admin_token = _account_session(reopened, "admin")
    for method, args in ((reopened.account_school_context, (admin_token,)),
                         (reopened.save_account_school_context, (admin_token, context))):
        with pytest.raises(ValueError):
            method(*args)
    summary = reopened.admin_platform_summary(admin_token)
    assert len(summary["school_contexts"]) == 1
    assert summary["school_contexts"][0]["account_id"] == account["account_id"]
    assert summary["registration_requests"] == []


def test_school_context_validation_does_not_change_saved_context(account_store) -> None:
    token = _account_session(account_store)
    context = _school_context()
    account_store.save_account_school_context(token, context)
    for invalid in (
        {}, {**context, "account_id": "other"}, {**context, "role": "company_admin"},
        {**context, "city": " "}, {**context, "district": None},
        {**context, "city": "x" * 81}, {**context, "district": "x" * 81},
        {**context, "school_name": "x" * 201}, {**context, "school_name": "bad\nname"},
    ):
        with pytest.raises(ValueError):
            account_store.save_account_school_context(token, invalid)
    assert account_store.account_school_context(token)["context"] == context
    with pytest.raises(ValueError, match="城市须填写 1 至 80 个字符"):
        account_store.save_account_school_context(token, {**context, "city": ""})


def _registration_application() -> dict[str, object]:
    return {"name": "Test Applicant", "contact": "test@example.invalid", **_school_context(),
            "agreement_version": "2026-09-08", "accepted": True}


def test_registration_is_pending_private_and_does_not_grant_access(account_store) -> None:
    application = _registration_application()
    request = account_store.submit_registration_application(application)
    assert set(request) == {"request_id", "status", "created_at"}
    assert request["status"] == "pending"
    with sqlite3.connect(account_store.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM platform_accounts").fetchone()[0] == 5
        assert connection.execute("SELECT COUNT(*) FROM account_sessions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM school_contexts").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM data_security_acceptances").fetchone()[0] == 0
        audit = connection.execute("SELECT detail_json FROM audit_logs WHERE action = 'registration_submitted'").fetchone()[0]
        assert application["contact"] not in audit and application["name"] not in audit
    reopened = Demo2StudentRecordStore(account_store.db_path, account_store.upload_dir)
    admin_token = _account_session(reopened, "admin")
    assert reopened.admin_platform_summary(admin_token)["registration_requests"] == [{**application, **request}]


def test_registration_requires_current_explicit_consent_and_bounded_fields(account_store) -> None:
    valid = _registration_application()
    invalid_payloads = [{key: value for key, value in valid.items() if key != "accepted"}]
    invalid_payloads += [{**valid, "accepted": value} for value in (False, None, 1, "true", [], {})]
    invalid_payloads += [
        {**valid, "agreement_version": "2026-09-07"}, {**valid, "role": "company_admin"},
        {**valid, "password": "NeverCreateAnAccount"}, {**valid, "name": " "},
        {**valid, "name": "x" * 81}, {**valid, "contact": "x" * 161},
        {**valid, "city": "x" * 81}, {**valid, "district": []},
        {**valid, "school_name": "x" * 201}, {**valid, "contact": "bad\x00contact"},
    ]
    for payload in invalid_payloads:
        with pytest.raises(ValueError):
            account_store.submit_registration_application(payload)
    with sqlite3.connect(account_store.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM registration_requests").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM audit_logs WHERE action = 'registration_rejected'").fetchone()[0] == len(invalid_payloads)
    with pytest.raises(ValueError, match="请填写有效的手机号或邮箱"):
        account_store.submit_registration_application({**valid, "contact": "not-a-contact"})


def test_registration_limits_persist_expire_and_bound_global_sources(account_store, monkeypatch) -> None:
    monkeypatch.setattr(store_module, "REGISTRATION_GLOBAL_LIMIT", 6)
    for _ in range(5):
        account_store.check_registration_rate_limit("192.0.2.1")
    reopened = Demo2StudentRecordStore(account_store.db_path, account_store.upload_dir)
    with pytest.raises(RegistrationRateLimitError):
        reopened.check_registration_rate_limit("192.0.2.1")
    reopened.check_registration_rate_limit("192.0.2.2")
    with pytest.raises(RegistrationRateLimitError):
        reopened.check_registration_rate_limit("192.0.2.3")
    with sqlite3.connect(account_store.db_path) as connection:
        sources = connection.execute("SELECT source_hash FROM registration_rate_limits").fetchall()
        assert len(sources) == 2 and all(len(row[0]) == 64 for row in sources)
        connection.execute("UPDATE registration_rate_limits SET window_started_at = 0")
    reopened.check_registration_rate_limit("192.0.2.1")
    with sqlite3.connect(account_store.db_path) as connection:
        assert connection.execute("SELECT SUM(attempts) FROM registration_rate_limits").fetchone()[0] == 1


def test_pilot_cli_accepts_hidden_input_and_keeps_nonseed_accounts_unchanged(
    account_store, monkeypatch, capsys
) -> None:
    import getpass
    import sys

    with sqlite3.connect(account_store.db_path) as connection:
        connection.execute(
            """INSERT INTO platform_accounts
               SELECT 'nonseed-account', 'nonseed-user', password_hash, password_salt,
                      password_iterations, role, NULL, course_upload_limit, status, created_at, updated_at
               FROM platform_accounts WHERE username = 'company_admin'"""
        )
        nonseed_before = connection.execute("SELECT * FROM platform_accounts WHERE username = 'nonseed-user'").fetchone()
    passwords = _pilot_passwords()
    answers = iter(value for password in passwords.values() for value in (password, password))
    monkeypatch.setattr(getpass, "getpass", lambda prompt: next(answers))
    monkeypatch.setattr(sys, "argv", ["student_record_store", "set-pilot-passwords", "--db", str(account_store.db_path)])
    store_module.main()
    output = capsys.readouterr()
    assert "Updated 5 seeded accounts" in output.out
    assert all(password not in output.out + output.err for password in passwords.values())
    with sqlite3.connect(account_store.db_path) as connection:
        assert connection.execute("SELECT * FROM platform_accounts WHERE username = 'nonseed-user'").fetchone() == nonseed_before


def test_registration_budget_is_atomic_under_concurrent_requests(account_store) -> None:
    from concurrent.futures import ThreadPoolExecutor

    def attempt(_):
        try:
            account_store.check_registration_rate_limit("192.0.2.4")
            return True
        except RegistrationRateLimitError:
            return False

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(attempt, range(8))) == 5


@pytest.mark.parametrize("contact,valid", [
    ("13800138000", True), ("+86 138-0013-8000", True), ("+1 202-555-0123", True),
    ("teacher+pilot@example.invalid", True), ("teacher@school.example.invalid", True),
    ("not-a-contact", False), ("12345", False), ("12800138000", False),
    ("+86 12345", False), ("@example.invalid", False), ("teacher@localhost", False),
    ("teacher..name@example.invalid", False), ("teacher@example..invalid", False),
    ("teacher@-school.invalid", False), ("teacher name@example.invalid", False),
])
def test_registration_contact_basic_format(contact, valid) -> None:
    assert store_module._valid_registration_contact(contact) is valid


def test_connection_context_commits_rolls_back_and_always_closes(account_store) -> None:
    with account_store._connect() as committed:
        committed.execute("UPDATE platform_accounts SET course_upload_limit = 3 WHERE username = 'school_uploader_01'")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        committed.execute("SELECT 1")
    with pytest.raises(RuntimeError, match="abort transaction"):
        with account_store._connect() as rolled_back:
            rolled_back.execute("UPDATE platform_accounts SET course_upload_limit = 4 WHERE username = 'school_uploader_01'")
            raise RuntimeError("abort transaction")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        rolled_back.execute("SELECT 1")
    with account_store._connect() as connection:
        assert connection.execute(
            "SELECT course_upload_limit FROM platform_accounts WHERE username = 'school_uploader_01'"
        ).fetchone()[0] == 3


@pytest.mark.parametrize("failure_stage", ["setup", "commit"])
def test_connection_context_closes_when_setup_or_commit_fails(account_store, monkeypatch, failure_stage) -> None:
    class FailingConnection(sqlite3.Connection):
        def execute(self, statement, *args, **kwargs):
            if failure_stage == "setup" and statement == "PRAGMA journal_mode = WAL":
                raise sqlite3.OperationalError("simulated setup failure")
            return super().execute(statement, *args, **kwargs)

        def __exit__(self, *args):
            if failure_stage == "commit":
                raise sqlite3.OperationalError("simulated commit failure")
            return super().__exit__(*args)

    connection = sqlite3.connect(account_store.db_path, factory=FailingConnection)
    monkeypatch.setattr(store_module.sqlite3, "connect", lambda *args, **kwargs: connection)
    with pytest.raises(sqlite3.OperationalError, match=f"simulated {failure_stage} failure"):
        with account_store._connect() as opened:
            opened.execute("UPDATE platform_accounts SET course_upload_limit = 3")
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_store_connections_close_without_gc_and_release_windows_database_file(tmp_path, monkeypatch) -> None:
    connect = sqlite3.connect
    connections = []

    def tracked_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", PASSWORD_PREFIX)
    monkeypatch.setattr(store_module.sqlite3, "connect", tracked_connect)
    store = Demo2StudentRecordStore(tmp_path / "cleanup.sqlite3", tmp_path / "documents")
    school_token = _account_session(store)
    admin_token = _account_session(store, "admin")
    for _ in range(3):
        store.save_account_school_context(school_token, _school_context())
        store.account_school_context(school_token)
        store.admin_platform_summary(admin_token)
    # Retain every connection so garbage collection cannot hide an open handle.
    assert len(connections) > 20
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")
    assert not Path(f"{store.db_path}-wal").exists()
    assert not Path(f"{store.db_path}-shm").exists()
    store.db_path.unlink()
    assert not store.db_path.exists()
