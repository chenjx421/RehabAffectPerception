"""Channel administration against disposable databases and synthetic uploads."""

from __future__ import annotations

import base64
import json
import re
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from types import SimpleNamespace

import pytest

from rehab_affect import student_record_store as record_module
from rehab_affect.demo2_channel_admin_store import ChannelAdminError, Demo2ChannelAdminStore
from rehab_affect.student_record_store import Demo2StudentRecordStore


ADMIN = "company_admin"
OWNER = "school_uploader_01"
SCHOOL = {"city": "Fixture City", "district": "Fixture District", "school_name": "Synthetic School"}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "ChannelAdminTest-")
    monkeypatch.setenv("REHAB_DEMO2_COURSE_UPLOAD_LIMIT", "5")
    records = Demo2StudentRecordStore(tmp_path / "channels.sqlite3", tmp_path / "documents")
    return SimpleNamespace(records=records, store=Demo2ChannelAdminStore(records), sessions={})


def login(env, username=ADMIN):
    if username not in env.sessions:
        account = env.records.authenticate_account(username, "ChannelAdminTest-" + username)
        env.sessions[username] = env.records.create_account_session(account)["token"]
    return env.sessions[username]


def channel(env, channel_id="channel_1"):
    return next(row for row in env.store.list_channels(login(env))["channels"] if row["channel_id"] == channel_id)


def update_payload(row, **changes):
    return {"channel_id": row["channel_id"], "expected_version": row["version"],
            "channel_name": row["channel_name"], "owner_label": row["owner_label"], "status": row["status"],
            "course_upload_limit": row["course_upload_limit"], **changes}


def raises_channel(status, code, method, *args):
    with pytest.raises(ChannelAdminError) as error:
        method(*args)
    assert (error.value.status, error.value.code) == (status, code)
    assert error.value.message == str(error.value)
    return error.value


def snapshot(env):
    with env.records._connect() as connection:
        return {table: [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                for table in ("video_upload_channels", "platform_accounts", "video_analysis_tasks", "school_contexts")}


def audits(env):
    with env.records._connect() as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM audit_logs WHERE action = 'channel_admin_updated' ORDER BY audit_id")]


def create_task(env, course_id="fixture-course", *, content=b"synthetic", complete=False, legacy=False):
    token = login(env, OWNER) if not legacy else None
    size = record_module.MAX_VIDEO_CHUNK_BYTES
    payload = {"channel_id": "channel_1", "session_id": "fixture-lesson", "uploader_name": "Fixture Teacher",
               "course_id": course_id, "course_name": "Synthetic Course", "filename": "fixture.mp4",
               "byte_size": len(content), "total_chunks": (len(content) + size - 1) // size}
    if token:
        payload["account_session_token"] = token
    task = env.records.create_video_task(payload)
    if complete:
        for index, offset in enumerate(range(0, len(content), size)):
            task = append_chunk(env, task["task_id"], index, content[offset:offset + size], token=token)
    return task


def append_chunk(env, task_id, index, content, *, token=None):
    payload = {"task_id": task_id, "chunk_index": index, "content_base64": base64.b64encode(content).decode("ascii")}
    if token:
        payload["account_session_token"] = token
    return env.records.append_video_chunk(payload)


def test_list_existing_four_channels_is_complete_and_excludes_credentials(env):
    env.records.save_account_school_context(login(env, OWNER), SCHOOL)
    before = snapshot(env)
    result = env.store.list_channels(login(env))
    assert set(result) == {"channels"} and len(result["channels"]) == 4
    for index, row in enumerate(result["channels"], 1):
        assert row["channel_id"] == f"channel_{index}" and row["channel_no"] == index
        assert row["username"] == f"school_uploader_{index:02d}"
        assert row["account_id"] and row["account_status"] == "active" and row["status"] == "active"
        assert row["course_upload_limit"] == 5 and re.fullmatch(r"[0-9a-f]{64}", row["version"])
        assert row["task_count"] == row["active_task_count"] == row["max_course_used_slots"] == 0
        assert row["course_usage"] == []
        assert row["school_context"] == (SCHOOL if index == 1 else {key: "" for key in SCHOOL})
    serialized = json.dumps(result)
    assert all(value not in serialized for value in ("password_hash", "password_salt", "token_hash", login(env), str(env.records.db_path)))
    assert snapshot(env) == before and audits(env) == []


def test_update_changes_only_config_audits_actual_rows_and_survives_reopen(env, monkeypatch):
    token = login(env)
    task = create_task(env)
    before = snapshot(env)
    old = channel(env)
    updated = env.store.update_channel(token, update_payload(old, channel_name="  Custom Channel  ", owner_label="  School Liaison  ",
                                                           status="paused", course_upload_limit=3))
    assert updated == channel(env)
    assert updated["channel_name"] == "Custom Channel" and updated["owner_label"] == "School Liaison"
    assert updated["status"] == "paused" and updated["course_upload_limit"] == 3 and updated["version"] != old["version"]
    after = snapshot(env)
    assert after["video_analysis_tasks"] == before["video_analysis_tasks"]
    assert after["school_contexts"] == before["school_contexts"]
    assert after["video_upload_channels"][1:] == before["video_upload_channels"][1:]
    for original, current in zip(before["platform_accounts"], after["platform_accounts"]):
        if original["account_id"] == old["account_id"]:
            assert {key: value for key, value in current.items() if key not in {"course_upload_limit", "updated_at"}} == {
                key: value for key, value in original.items() if key not in {"course_upload_limit", "updated_at"}}
        else:
            assert current == original
    log = audits(env)
    assert len(log) == 1 and log[0]["actor"] == ADMIN and log[0]["object_type"] == "video_upload_channel"
    assert log[0]["object_id"] == "channel_1" and json.loads(log[0]["detail_json"]) == {"before": old, "after": updated}
    assert token not in json.dumps(log) and "password_hash" not in json.dumps(log)
    monkeypatch.setenv("REHAB_DEMO2_COURSE_UPLOAD_LIMIT", "4")
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "DifferentSeed-")
    reopened = Demo2StudentRecordStore(env.records.db_path, env.records.upload_dir)
    assert Demo2ChannelAdminStore(reopened).list_channels(token)["channels"][0] == updated
    assert snapshot(env) == after
    assert reopened.authenticate_account(OWNER, "ChannelAdminTest-" + OWNER)["account_id"] == old["account_id"]
    assert reopened.account_video_task(login(env, OWNER), task["task_id"])["task_id"] == task["task_id"]


@pytest.mark.parametrize("username", [OWNER, "school_uploader_02", "school_uploader_03"])
def test_non_admin_cannot_list_or_update_even_with_malformed_payload(env, username):
    token = login(env, username)
    if username.endswith("03"):
        with env.records._connect() as connection:
            connection.execute("UPDATE platform_accounts SET role = 'registered_member', bound_channel_id = NULL WHERE username = ?", (username,))
    before = snapshot(env)
    raises_channel(403, "channel_admin_forbidden", env.store.list_channels, token)
    raises_channel(403, "channel_admin_forbidden", env.store.update_channel, token, {})
    assert snapshot(env) == before and audits(env) == []


@pytest.mark.parametrize("state", ["unknown", "revoked", "expired", "inactive", "role_changed"])
def test_admin_session_and_role_are_not_cached(env, state):
    token = login(env)
    payload = update_payload(channel(env), status="paused")
    with env.records._connect() as connection:
        if state == "unknown":
            token = "not-a-session"
        elif state == "revoked":
            connection.execute("UPDATE account_sessions SET revoked_at = 'revoked'")
        elif state == "expired":
            connection.execute("UPDATE account_sessions SET expires_at = '2000-01-01T00:00:00+00:00'")
        elif state == "inactive":
            connection.execute("UPDATE platform_accounts SET status = 'disabled' WHERE username = ?", (ADMIN,))
        else:
            connection.execute("UPDATE platform_accounts SET role = 'registered_member' WHERE username = ?", (ADMIN,))
    expected = (403, "channel_admin_forbidden") if state == "role_changed" else (401, "authentication_required")
    before = snapshot(env)
    raises_channel(*expected, env.store.list_channels, token)
    raises_channel(*expected, env.store.update_channel, token, payload)
    assert snapshot(env) == before and audits(env) == []


@pytest.mark.parametrize("method", ["list", "update"])
@pytest.mark.parametrize("change", ["role", "disabled", "revoked", "expired", "naive_expiry"])
def test_admin_is_rechecked_inside_transaction_after_initial_authentication(env, monkeypatch, method, change):
    token = login(env)
    payload = update_payload(channel(env), channel_name="Must Not Save")
    authenticate = env.records.account_from_session

    def authenticate_then_change(session_token):
        account = authenticate(session_token)
        with env.records._connect() as connection:
            if change == "role":
                connection.execute("UPDATE platform_accounts SET role = 'registered_member' WHERE account_id = ?", (account["account_id"],))
            elif change == "disabled":
                connection.execute("UPDATE platform_accounts SET status = 'disabled' WHERE account_id = ?", (account["account_id"],))
            elif change == "revoked":
                connection.execute("UPDATE account_sessions SET revoked_at = 'revoked' WHERE session_id = ?", (account["session_id"],))
            else:
                expiry = "2000-01-01T00:00:00+00:00" if change == "expired" else "2999-01-01T00:00:00"
                connection.execute("UPDATE account_sessions SET expires_at = ? WHERE session_id = ?", (expiry, account["session_id"]))
        return account

    monkeypatch.setattr(env.records, "account_from_session", authenticate_then_change)
    expected = (403, "channel_admin_forbidden") if change == "role" else (401, "authentication_required")
    if method == "list":
        raises_channel(*expected, env.store.list_channels, token)
    else:
        raises_channel(*expected, env.store.update_channel, token, payload)
    assert snapshot(env)["video_upload_channels"][0]["channel_name"] != "Must Not Save"
    assert audits(env) == []


@pytest.mark.parametrize("changes", [
    {"channel_id": "../channel_1"}, {"channel_id": []}, {"expected_version": None}, {"expected_version": "invalid"},
    {"channel_name": ""}, {"channel_name": " "}, {"channel_name": None}, {"channel_name": "a" * 121},
    {"channel_name": "a\n"}, {"owner_label": "a\x00"}, {"owner_label": "a\u202e"}, {"owner_label": "\ud800"},
    {"owner_label": "a" * 121}, {"owner_label": []}, {"status": "disabled"}, {"status": "ACTIVE"}, {"status": []},
    {"account_id": "forged"}, {"username": "forged"}, {"channel_no": 5}, {"school_context": SCHOOL}, {"version": "forged"},
])
def test_update_rejects_invalid_fields_or_client_owned_metadata(env, changes):
    payload = update_payload(channel(env), **changes)
    before = snapshot(env)
    raises_channel(400, "invalid_channel_update", env.store.update_channel, login(env), payload)
    assert snapshot(env) == before and audits(env) == []


@pytest.mark.parametrize("limit", [True, False, 2, 6, 3.0, "3", None, float("nan"), []])
def test_quota_is_strict_integer_three_to_five(env, limit):
    payload = update_payload(channel(env), course_upload_limit=limit)
    raises_channel(400, "invalid_course_upload_limit", env.store.update_channel, login(env), payload)
    assert channel(env)["course_upload_limit"] == 5 and audits(env) == []


@pytest.mark.parametrize("missing", ["channel_id", "expected_version", "channel_name", "owner_label", "status", "course_upload_limit"])
def test_update_requires_exact_payload_fields(env, missing):
    payload = update_payload(channel(env))
    payload.pop(missing)
    raises_channel(400, "invalid_channel_update", env.store.update_channel, login(env), payload)


@pytest.mark.parametrize("payload", [None, [], "channel_1"])
def test_update_requires_object_payload(env, payload):
    raises_channel(400, "invalid_channel_update", env.store.update_channel, login(env), payload)


@pytest.mark.parametrize("field,value", [("channel_name", "Renamed"), ("owner_label", "New Owner"),
                                         ("status", "paused"), ("course_upload_limit", 4)])
def test_version_detects_each_config_change_even_with_unchanged_timestamp(env, field, value):
    old = channel(env)
    with env.records._connect() as connection:
        if field == "course_upload_limit":
            connection.execute("UPDATE platform_accounts SET course_upload_limit = ? WHERE account_id = ?", (value, old["account_id"]))
        else:
            connection.execute(f"UPDATE video_upload_channels SET {field} = ? WHERE channel_id = ?", (value, old["channel_id"]))
    assert channel(env)["version"] != old["version"]
    before = snapshot(env)
    raises_channel(409, "channel_version_conflict", env.store.update_channel, login(env), update_payload(old))
    assert snapshot(env) == before and audits(env) == []


def test_live_school_and_task_counts_do_not_invalidate_config_version_and_audit_reads_real_before(env):
    old = channel(env)
    create_task(env)
    env.records.save_account_school_context(login(env, OWNER), SCHOOL)
    current = channel(env)
    assert current["version"] == old["version"] and current["task_count"] == 1
    result = env.store.update_channel(login(env), update_payload(old, owner_label="Current Liaison"))
    detail = json.loads(audits(env)[0]["detail_json"])
    assert detail == {"before": current, "after": result}
    assert detail["before"]["school_context"] == SCHOOL


def test_unknown_or_unbound_channel_never_creates_or_reassigns_accounts(env):
    original = channel(env)
    raises_channel(404, "channel_unavailable", env.store.update_channel, login(env), update_payload(original, channel_id="unknown"))
    with env.records._connect() as connection:
        connection.execute("UPDATE platform_accounts SET bound_channel_id = NULL WHERE account_id = ?", (original["account_id"],))
    missing = channel(env)
    assert missing["account_id"] is None and missing["course_upload_limit"] is None
    before = snapshot(env)
    raises_channel(409, "channel_account_unavailable", env.store.update_channel, login(env), update_payload(missing, course_upload_limit=3))
    assert snapshot(env) == before and len(env.store.list_channels(login(env))["channels"]) == 4


@pytest.mark.parametrize("last_status", ["uploading", "completed", "failed", "cancelled", "expired"])
def test_lower_limit_matches_existing_per_course_reservation_rules_without_deleting_history(env, last_status):
    tasks = [create_task(env) for _ in range(4)]
    with env.records._connect() as connection:
        connection.execute("UPDATE video_analysis_tasks SET upload_status = ? WHERE task_id = ?", (last_status, tasks[-1]["task_id"]))
    old = channel(env)
    before = snapshot(env)
    if last_status in {"cancelled", "expired"}:
        result = env.store.update_channel(login(env), update_payload(old, course_upload_limit=3))
        assert result["task_count"] == 4 and result["active_task_count"] == result["max_course_used_slots"] == 3
    else:
        error = raises_channel(409, "channel_quota_in_use", env.store.update_channel, login(env), update_payload(old, course_upload_limit=3))
        assert "4" in error.message and "3" in error.message and "历史任务不会删除" in error.message
        assert snapshot(env) == before and audits(env) == []
    assert snapshot(env)["video_analysis_tasks"] == before["video_analysis_tasks"]


def test_lowering_uses_peak_per_course_not_channel_total(env):
    for course in ("course-a", "course-b"):
        for _ in range(3):
            create_task(env, course)
    before = snapshot(env)["video_analysis_tasks"]
    result = env.store.update_channel(login(env), update_payload(channel(env), course_upload_limit=3))
    assert result["task_count"] == 6 and result["max_course_used_slots"] == 3
    assert result["course_usage"] == [{"course_id": "course-a", "used_slots": 3}, {"course_id": "course-b", "used_slots": 3}]
    with pytest.raises(ValueError, match="最多 3"):
        create_task(env, "course-a")
    assert snapshot(env)["video_analysis_tasks"] == before
    assert create_task(env, "course-c")["course_id"] == "course-c"


@pytest.mark.parametrize("legacy", [False, True])
def test_pause_prevents_new_uploads_and_resume_restores_them_without_touching_account(env, legacy):
    original = channel(env)
    paused = env.store.update_channel(login(env), update_payload(original, status="paused"))
    before = snapshot(env)
    with pytest.raises(ValueError, match="已暂停"):
        create_task(env, legacy=legacy)
    assert snapshot(env) == before
    assert env.records.account_from_session(login(env, OWNER))["status"] == "active"
    restored = env.store.update_channel(login(env), update_payload(paused, status="active"))
    assert restored["account_id"] == original["account_id"] and restored["username"] == original["username"]
    assert create_task(env, legacy=legacy)["channel_id"] == "channel_1"


def test_pause_preserves_existing_media_analysis_and_partial_upload(env, monkeypatch):
    monkeypatch.setattr(record_module, "MAX_VIDEO_CHUNK_BYTES", 4)
    uploaded = create_task(env, content=b"old", complete=True)
    partial = create_task(env, content=b"12345")
    token = login(env, OWNER)
    append_chunk(env, partial["task_id"], 0, b"1234", token=token)
    accounts = snapshot(env)["platform_accounts"]
    env.store.update_channel(login(env), update_payload(channel(env), status="paused"))
    assert snapshot(env)["platform_accounts"] == accounts
    assert env.records.account_video_media(token, uploaded["task_id"])[0].read_bytes() == b"old"
    assert env.records.account_upload_workspace(token, "fixture-course")["channel"]["status"] == "paused"
    resumed = append_chunk(env, partial["task_id"], 1, b"5", token=token)
    assert resumed["upload_status"] == "completed"
    assert env.records.account_video_media(token, partial["task_id"])[0].read_bytes() == b"12345"
    for task in (uploaded, resumed):
        claim = env.records.claim_next_video_analysis()
        assert claim["task_id"] == task["task_id"]
        env.records.update_video_analysis_progress(task["task_id"], "synthetic", 50)
        result = {"version": "synthetic-channel-test-v1", "task_id": task["task_id"], "content": {"fixture": True}}
        assert env.records.finish_video_analysis(task["task_id"], result)["analysis_status"] == "evidence_ready"
        assert env.records.account_video_task(token, task["task_id"])["analysis_status"] == "evidence_ready"
    assert channel(env)["status"] == "paused" and channel(env)["task_count"] == 2


def test_audit_failure_rolls_back_channel_and_account_quota_together(env, monkeypatch):
    token = login(env)
    payload = update_payload(channel(env), status="paused", course_upload_limit=3)
    before = snapshot(env)
    audit = env.records._audit

    def audit_then_fail(*args):
        audit(*args)
        if args[2] == "channel_admin_updated":
            raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(env.records, "_audit", audit_then_fail)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        env.store.update_channel(token, payload)
    assert snapshot(env) == before and audits(env) == []


def test_concurrent_updates_only_one_version_can_commit(env):
    token, old = login(env), channel(env)
    gate = Barrier(3)

    def update(index):
        gate.wait(timeout=10)
        try:
            Demo2ChannelAdminStore(env.records).update_channel(token, update_payload(old, channel_name=f"Concurrent {index}"))
            return "saved"
        except ChannelAdminError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(update, range(3)))
    assert results.count("saved") == 1 and results.count("channel_version_conflict") == 2
    assert len(audits(env)) == 1


def test_quota_lowering_and_new_reservation_cannot_race_past_each_other(env):
    for _ in range(3):
        create_task(env)
    token, old = login(env), channel(env)
    gate = Barrier(2)

    def compete(kind):
        gate.wait(timeout=10)
        try:
            if kind == "lower":
                env.store.update_channel(token, update_payload(old, course_upload_limit=3))
            else:
                create_task(env)
            return kind
        except ChannelAdminError as error:
            assert error.code == "channel_quota_in_use"
            return "rejected"
        except ValueError as error:
            assert "名额已满" in str(error)
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(compete, ["lower", "upload"]))
    assert results.count("rejected") == 1
    row = channel(env)
    assert (row["course_upload_limit"], row["max_course_used_slots"]) in {(3, 3), (5, 4)}


def test_legacy_create_locks_before_channel_state_check(env, monkeypatch):
    connect, statements = env.records._connect, []

    @contextmanager
    def traced():
        with connect() as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(env.records, "_connect", traced)
    create_task(env, legacy=True)
    begin = statements.index("BEGIN IMMEDIATE")
    check = next(index for index, sql in enumerate(statements) if "SELECT status FROM video_upload_channels" in sql)
    insert = next(index for index, sql in enumerate(statements) if "INSERT INTO video_analysis_tasks" in sql)
    assert begin < check < insert
