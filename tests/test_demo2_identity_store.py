from __future__ import annotations

import base64
import copy
import hashlib
import json
import stat
import statistics
import time
import timeit
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest

from rehab_affect.demo2_identity_store import (
    MAX_FRAME_CACHE_ENTRIES,
    MAX_FRAME_CACHE_MANIFESTS,
    MAX_PROCESSING_RESULT_BYTES,
    Demo2IdentityStore,
    IdentityError,
)
from rehab_affect.student_record_store import Demo2StudentRecordStore


OWNER = "school_uploader_01"
OTHER = "school_uploader_02"
ADMIN = "company_admin"
MEMBER = "school_uploader_03"
CONTEXT = {"city": "测试市", "district": "测试区", "school_name": "测试学校"}
BOX = {"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.4}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Only disposable databases and synthetic bytes; no engine/service calls."""
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "IdentityTest-")
    monkeypatch.setenv("REHAB_DEMO2_COURSE_UPLOAD_LIMIT", "5")
    record = Demo2StudentRecordStore(tmp_path / "identity.sqlite3", tmp_path / "documents")
    with record._connect() as connection:
        connection.execute("UPDATE platform_accounts SET role = 'registered_member', bound_channel_id = NULL WHERE username = ?", (MEMBER,))
    return SimpleNamespace(record=record, identity=Demo2IdentityStore(record), sessions={}, tmp=tmp_path)


def login(env, username=OWNER):
    if username not in env.sessions:
        account = env.record.authenticate_account(username, f"IdentityTest-{username}")
        env.sessions[username] = (account, env.record.create_account_session(account)["token"])
    return env.sessions[username]


def school(env, username=OWNER, context=None):
    _, token = login(env, username)
    env.record.save_account_school_context(token, dict(CONTEXT if context is None else context))
    return token


def simulate_school_migration(env, context):
    """Simulate administrator migration in this test's disposable database only."""
    assert env.record.db_path.resolve().is_relative_to(env.tmp.resolve())
    account, _ = login(env)
    with env.record._connect() as connection:
        connection.execute(
            "UPDATE school_contexts SET city=?, district=?, school_name=? WHERE account_id=?",
            (context["city"], context["district"], context["school_name"], account["account_id"]),
        )


def student(env, username=OWNER, **fields):
    return env.identity.create_student(login(env, username)[1], {"display_name": "同名学生", **fields})


def task_row(env, task_id):
    with env.record._connect() as connection:
        return dict(connection.execute("SELECT * FROM video_analysis_tasks WHERE task_id = ?", (task_id,)).fetchone())


def persist_result(env, task_id, result=None, *, raw=None):
    text = raw if raw is not None else json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    with env.record._connect() as connection:
        connection.execute("UPDATE video_analysis_tasks SET processing_result_json = ? WHERE task_id = ?", (text, task_id))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_task(env, username=OWNER, *, count=3, set_school=True, materialize=None):
    account, token = login(env, username)
    if set_school:
        school(env, username)
    content = b"synthetic uploaded source, not real student media"
    task = env.record.create_video_task({
        "account_session_token": token, "channel_id": account["bound_channel_id"],
        "session_id": "identity-lesson", "uploader_name": username, "course_id": "identity-course",
        "course_name": "身份绑定测试课程", "filename": "fixture.mp4", "byte_size": len(content), "total_chunks": 1,
    })
    env.record.append_video_chunk({"account_session_token": token, "task_id": task["task_id"],
                                   "chunk_index": 0, "content_base64": base64.b64encode(content).decode("ascii")})
    claim = env.record.claim_next_video_analysis()
    assert claim["task_id"] == task["task_id"]
    directory = Path(claim["analysis_dir"])
    segments, paths = [], {}
    materialized = set(range(count)) if materialize is None else set(materialize)
    for index in range(count):
        segment_index, sample_index = divmod(index, 20)
        if sample_index == 0:
            segments.append({"segment_id": f"segment_{segment_index:04d}", "start_sec": segment_index * 20,
                             "end_sec": min((segment_index + 1) * 20, count), "visual": {"samples": []}})
        relative = f"media_fixture/frames/frame_{index:06d}.jpg"
        segments[-1]["visual"]["samples"].append({"timestamp_sec": index, "image_path": relative,
                                                  "brightness": 80, "sharpness": 1, "scene_motion": 0.1})
        path = directory / relative
        paths[f"s{segment_index}_f{sample_index}"] = path
        if index in materialized:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic JPEG sample " + str(index).encode("ascii"))
    result = {"analysis_version": "demo2_media_evidence_v1.1", "task_id": task["task_id"],
              "analysis_status": "evidence_ready", "source_sha256": hashlib.sha256(content).hexdigest(),
              "media": {"duration_sec": count, "has_video": True, "has_audio": False},
              "sampling": {"fps": 1, "window_sec": 20}, "segments": segments,
              "artifacts": {"frames": "media_fixture/frames", "result": "media_fixture/analysis.json"}}
    env.record.finish_video_analysis(task["task_id"], result)
    row = task_row(env, task["task_id"])
    return SimpleNamespace(task_id=task["task_id"], token=token, result=result, paths=paths,
                           raw=row["processing_result_json"], source=Path(row["file_path"]),
                           revision=hashlib.sha256(row["processing_result_json"].encode("utf-8")).hexdigest())


def binding_payload(task, student_id=None, **changes):
    payload = {"task_id": task.task_id, "frame_key": "s0_f0", "frame_revision": task.revision,
               "role": "student" if student_id is not None else "unknown", "bbox": dict(BOX)}
    if student_id is not None:
        payload["student_id"] = student_id
    return {**payload, **changes}


def raises_identity(status, code, function, *args):
    with pytest.raises(IdentityError) as error:
        function(*args)
    assert error.value.status == status
    assert error.value.code == code
    assert error.value.message == str(error.value)
    return error.value


def test_roster_missing_school_is_readable_and_create_requires_complete_context(env):
    _, token = login(env)
    roster = env.identity.roster(token)
    assert roster == {"school_context": {key: "" for key in CONTEXT}, "scope_key": "", "students": [],
                      "can_edit": False, "needs_school_context": True}
    raises_identity(409, "school_context_required", env.identity.create_student, token, {"display_name": "新生"})
    school(env)
    assert env.identity.roster(token)["can_edit"] is True
    assert env.identity.roster(token)["needs_school_context"] is False


def test_roster_owner_and_full_school_scope_are_isolated(env):
    first, second = school(env), school(env, OTHER)
    pupil = student(env, student_code="01", class_name="一班")
    other_pupil = student(env, OTHER, student_code="01", class_name="一班")
    first_roster, second_roster = env.identity.roster(first), env.identity.roster(second)
    assert first_roster["school_context"] == second_roster["school_context"] == CONTEXT
    assert first_roster["scope_key"] != second_roster["scope_key"]
    assert first_roster["students"] == [pupil] and second_roster["students"] == [other_pupil]
    assert pupil["student_id"] != other_pupil["student_id"]
    assert UUID(pupil["student_id"]).version == 4
    migrated = {**CONTEXT, "district": "另一区"}
    with pytest.raises(ValueError, match="管理员迁移"):
        school(env, context=migrated)
    assert env.identity.roster(first) == first_roster
    simulate_school_migration(env, migrated)
    assert env.identity.roster(first)["students"] == []
    simulate_school_migration(env, CONTEXT)
    assert env.identity.roster(first)["students"] == [pupil]


def test_task_snapshot_does_not_follow_later_school_edits(env):
    task = make_task(env)
    pupil = student(env, student_code="01")
    migrated = {**CONTEXT, "school_name": "新学校"}
    before = task_row(env, task.task_id)
    with pytest.raises(ValueError, match="管理员迁移"):
        school(env, context=migrated)
    assert env.identity.roster(task.token)["school_context"] == CONTEXT
    assert env.identity.roster(task.token)["students"] == [pupil]
    assert task_row(env, task.task_id) == before
    simulate_school_migration(env, migrated)
    new_pupil = student(env, student_code="01")
    assert env.identity.roster(task.token)["students"] == [new_pupil]
    workspace = env.identity.workspace(task.token, task.task_id)
    assert workspace["school_context"] == CONTEXT and workspace["students"] == [pupil]
    assert workspace["scope_key"] == pupil["scope_key"] != new_pupil["scope_key"]
    raises_identity(404, "student_unavailable", env.identity.save_binding, task.token, binding_payload(task, new_pupil["student_id"]))
    saved = env.identity.save_binding(task.token, binding_payload(task, pupil["student_id"]))
    assert saved["scope_key"] == pupil["scope_key"]


def test_same_name_is_allowed_and_nonempty_student_code_unique_per_class_and_scope(env):
    school(env)
    pupils = [student(env), student(env), student(env, student_code="01", class_name="一班"),
              student(env, student_code="01", class_name="二班")]
    assert len({pupil["student_id"] for pupil in pupils}) == 4
    raises_identity(409, "student_code_conflict", env.identity.create_student, login(env)[1],
                    {"display_name": "另一个姓名", "student_code": " 01 ", "class_name": "一班"})


@pytest.mark.parametrize("payload", [
    {}, {"display_name": "  "}, {"display_name": None}, {"display_name": "a" * 81},
    {"display_name": "学生\n"}, {"display_name": "学\u202e生"}, {"display_name": "学\x00生"},
    {"display_name": "学生", "student_code": "a" * 65}, {"display_name": "学生", "class_name": "a" * 121},
    {"display_name": "学生", "note": "a" * 1001}, {"display_name": "学生", "owner_account_id": "other"},
    {"display_name": "学生", "scope_key": "client"}, {"display_name": "学生", "school_context": CONTEXT},
    {"display_name": "学生", "created_at": "client-time"},
])
def test_student_fields_are_bounded_and_server_identity_cannot_be_forged(env, payload):
    token = school(env)
    with pytest.raises(IdentityError) as error:
        env.identity.create_student(token, payload)
    assert error.value.status == 400
    assert env.identity.roster(token)["students"] == []


def test_native_published_frames_timestamp_revision_and_secure_urls(env):
    task = make_task(env, count=23)
    assert "image_path" not in json.loads(task.raw)["segments"][0]["visual"]["samples"][0]
    workspace = env.identity.workspace(task.token, task.task_id)
    assert workspace["frame_revision"] == hashlib.sha256(task.raw.encode("utf-8")).hexdigest()
    assert workspace["media_available"] is True and workspace["can_edit"] is True
    frame = workspace["frames"][21]
    assert (frame["frame_key"], frame["time_sec"], frame["segment_start_sec"], frame["segment_end_sec"]) == ("s1_f1", 21, 20, 23)
    url = urlparse(frame["image_url"])
    assert url.path == "/api/v1/demo2/identity/frame"
    assert parse_qs(url.query) == {"task_id": [task.task_id], "frame_key": ["s1_f1"], "frame_revision": [task.revision]}
    path, mime = env.identity.frame_file(task.token, task.task_id, "s1_f1", task.revision)
    assert path == task.paths["s1_f1"] and mime == "image/jpeg"
    assert path.read_bytes().endswith(b"21")
    serialized = json.dumps(workspace, ensure_ascii=False)
    assert str(env.tmp) not in serialized and "relative_image" not in serialized and "media_fixture" not in serialized


def test_explicit_persisted_frame_path_supported_without_version_fallback(env):
    task = make_task(env)
    revision = persist_result(env, task.task_id, task.result)
    path, mime = env.identity.frame_file(task.token, task.task_id, "s0_f1", revision)
    assert path == task.paths["s0_f1"] and mime == "image/jpeg"


@pytest.mark.parametrize("username", [OTHER, MEMBER])
def test_other_account_or_registered_member_cannot_access_task(env, username):
    task = make_task(env)
    env.identity.frame_file(task.token, task.task_id, "s0_f0", task.revision)
    _, token = login(env, username)
    expected = (404, "task_unavailable") if username == OTHER else (403, "identity_forbidden")
    for method, args in ((env.identity.workspace, (task.task_id,)), (env.identity.export, (task.task_id,)),
                         (env.identity.frame_file, (task.task_id, "s0_f0", task.revision)),
                         (env.identity.preview_source, (task.task_id, "s0_f0", task.revision)),
                         (env.identity.save_binding, (binding_payload(task),)),
                         (env.identity.revoke_binding, ({"task_id": task.task_id, "binding_id": "none", "reason": "复核"},))):
        raises_identity(*expected, method, token, *args)


def test_admin_can_read_task_roster_bindings_frame_and_export_but_never_write(env):
    task = make_task(env)
    pupil = student(env)
    saved = env.identity.save_binding(task.token, binding_payload(task, pupil["student_id"]))
    _, admin = login(env, ADMIN)
    workspace = env.identity.workspace(admin, task.task_id)
    assert workspace["students"] == [pupil] and workspace["bindings"] == [saved]
    assert workspace["can_edit"] is False and workspace["media_available"] is True
    assert workspace["can_revoke"] is False
    assert env.identity.frame_file(admin, task.task_id, "s0_f0", task.revision)[0].is_file()
    assert env.identity.export(admin, task.task_id)["bindings"] == [saved]
    for method, args in ((env.identity.roster, ()), (env.identity.create_student, ({"display_name": "不允许"},)),
                         (env.identity.save_binding, (binding_payload(task),)),
                         (env.identity.revoke_binding, ({"task_id": task.task_id, "binding_id": saved["binding_id"], "reason": "不允许"},))):
        raises_identity(403, "identity_forbidden", method, admin, *args)


def test_registered_member_has_no_roster_or_create_permission(env):
    _, token = login(env, MEMBER)
    raises_identity(403, "identity_forbidden", env.identity.roster, token)
    raises_identity(403, "identity_forbidden", env.identity.create_student, token, {"display_name": "不允许"})


@pytest.mark.parametrize("state", ["bad_token", "revoked", "expired", "inactive"])
def test_session_and_account_state_are_checked_on_every_access(env, state):
    task = make_task(env)
    env.identity.preview_source(task.token, task.task_id, "s0_f0", task.revision)
    token = task.token
    account = login(env)[0]
    if state == "bad_token":
        token = "unknown"
    elif state == "revoked":
        env.record.revoke_account_session(token)
    else:
        with env.record._connect() as connection:
            if state == "inactive":
                connection.execute("UPDATE platform_accounts SET status = 'disabled' WHERE account_id = ?", (account["account_id"],))
            else:
                connection.execute("UPDATE account_sessions SET expires_at = ? WHERE account_id = ?",
                                   ((datetime.now().astimezone() - timedelta(seconds=1)).isoformat(), account["account_id"]))
    raises_identity(401, "authentication_required", env.identity.workspace, token, task.task_id)
    raises_identity(401, "authentication_required", env.identity.save_binding, token, binding_payload(task))
    raises_identity(401, "authentication_required", env.identity.frame_file, token, task.task_id, "s0_f0", task.revision)
    raises_identity(401, "authentication_required", env.identity.preview_source, token, task.task_id, "s0_f0", task.revision)


@pytest.mark.parametrize("task_id", ["unknown", "../../outside", "", None])
def test_unknown_task_never_reveals_task_or_filesystem_details(env, task_id):
    _, token = login(env)
    error = raises_identity(404, "task_unavailable", env.identity.workspace, token, task_id)
    assert str(env.tmp) not in str(error)
    error = raises_identity(404, "task_unavailable", env.identity.preview_source, token, task_id, "s0_f0", "old")
    assert str(env.tmp) not in str(error)


@pytest.mark.parametrize("box", [
    {**BOX, "x": float("nan")}, {**BOX, "y": float("inf")}, {**BOX, "width": float("-inf")},
    {**BOX, "height": True}, {**BOX, "x": "0.2"}, {**BOX, "y": -0.01}, {**BOX, "width": 0},
    {**BOX, "height": -1}, {**BOX, "x": 0.9}, {**BOX, "y": 0.8}, {**BOX, "width": 101},
    {**BOX, "x": 10 ** 400}, {"x": 0, "y": 0, "width": 1e-300, "height": 1e-300},
    {"x": 1, "y": 0, "width": 1e-20, "height": 1}, {"x": 0, "y": 1, "width": 1, "height": 1e-20},
    {"x": 0, "y": 0, "width": 0.1}, {**BOX, "confidence": 1}, None,
])
def test_bbox_is_finite_normalized_nonempty_and_within_frame(env, box):
    task = make_task(env)
    raises_identity(400, "invalid_bbox", env.identity.save_binding, task.token, binding_payload(task, bbox=box))
    assert env.identity.workspace(task.token, task.task_id)["bindings"] == []


@pytest.mark.parametrize("role", ["teacher", "unknown"])
def test_teacher_unknown_have_no_student_or_fabricated_tracking(env, role):
    task = make_task(env)
    saved = env.identity.save_binding(task.token, binding_payload(task, role=role, bbox={"x": 0, "y": 0, "width": 1, "height": 1}))
    assert saved["student_id"] is None and saved["role"] == role
    assert saved["identity_scope"] == "single_sample_frame"
    assert saved["confirmed_by"] == OWNER and saved["time_sec"] == 0
    for field in ("track_id", "confidence", "emotion", "learning_mastery", "audio", "scene_motion"):
        assert field not in saved
    raises_identity(400, "unexpected_student", env.identity.save_binding, task.token, {**binding_payload(task, role=role), "student_id": ""})
    saved_null = env.identity.save_binding(task.token, {**binding_payload(task, role=role, frame_key="s0_f1"), "student_id": None})
    assert saved_null["student_id"] is None


@pytest.mark.parametrize("extra", [{"role": "observer"}, {"role": "student"}, {"confirmed_by": "forged"},
                                  {"time_sec": 12}, {"created_at": "forged"}, {"scope_key": "forged"},
                                  {"image_path": "outside.jpg"}, {"owner_account_id": "forged"}])
def test_role_and_server_owned_binding_fields_rejected(env, extra):
    task = make_task(env)
    with pytest.raises(IdentityError) as error:
        env.identity.save_binding(task.token, {**binding_payload(task), **extra})
    assert error.value.status == 400


def test_same_student_and_high_iou_duplicates_rejected_revocation_allows_replacement(env):
    task = make_task(env)
    first, second = student(env), student(env)
    saved = env.identity.save_binding(task.token, binding_payload(task, first["student_id"]))
    raises_identity(409, "duplicate_student_binding", env.identity.save_binding, task.token,
                    binding_payload(task, first["student_id"], bbox={**BOX, "x": 0.5}))
    raises_identity(409, "overlapping_student_binding", env.identity.save_binding, task.token,
                    binding_payload(task, second["student_id"], bbox={**BOX, "x": 0.11}))
    nonoverlap = env.identity.save_binding(task.token, binding_payload(task, second["student_id"], bbox={**BOX, "x": 0.6}))
    assert nonoverlap["student_id"] == second["student_id"]
    env.identity.revoke_binding(task.token, {"task_id": task.task_id, "binding_id": saved["binding_id"], "reason": "框位置需要修正"})
    replacement = env.identity.save_binding(task.token, binding_payload(task, first["student_id"]))
    assert replacement["binding_id"] != saved["binding_id"]
    assert env.identity.save_binding(task.token, binding_payload(task, first["student_id"], frame_key="s0_f1"))


def test_iou_exactly_threshold_is_allowed(env):
    task = make_task(env)
    first, second = student(env), student(env)
    env.identity.save_binding(task.token, binding_payload(task, first["student_id"], bbox={"x": 0, "y": 0, "width": 1, "height": 1}))
    assert env.identity.save_binding(task.token, binding_payload(task, second["student_id"], bbox={"x": 0, "y": 0, "width": 0.7, "height": 1}))


@pytest.mark.parametrize("status", ["queued", "processing", "failed", "completed", "precheck_complete", "uploaded_pending_worker"])
def test_only_exact_evidence_ready_permits_new_binding_or_frame(env, status):
    task = make_task(env)
    env.identity.preview_source(task.token, task.task_id, "s0_f0", task.revision)
    with env.record._connect() as connection:
        connection.execute("UPDATE video_analysis_tasks SET analysis_status = ? WHERE task_id = ?", (status, task.task_id))
    raises_identity(409, "evidence_not_ready", env.identity.save_binding, task.token, binding_payload(task))
    raises_identity(409, "evidence_not_ready", env.identity.frame_file, task.token, task.task_id, "s0_f0", task.revision)
    raises_identity(409, "evidence_not_ready", env.identity.preview_source, task.token, task.task_id, "s0_f0", task.revision)
    workspace = env.identity.workspace(task.token, task.task_id)
    assert not workspace["can_edit"] and not workspace["media_available"]
    assert workspace["can_revoke"] is True


@pytest.mark.parametrize("state", ["expired", "deleted", "missing", "incomplete"])
def test_unavailable_source_blocks_new_work_but_history_and_revocation_persist(env, state):
    task = make_task(env)
    pupil = student(env)
    saved = env.identity.save_binding(task.token, binding_payload(task, pupil["student_id"]))
    if state == "missing":
        task.source.unlink()
    else:
        with env.record._connect() as connection:
            if state == "expired":
                connection.execute("UPDATE video_analysis_tasks SET expires_at = ? WHERE task_id = ?",
                                   ((datetime.now().astimezone() - timedelta(seconds=1)).isoformat(), task.task_id))
            elif state == "deleted":
                connection.execute("UPDATE video_analysis_tasks SET raw_media_deleted_at = ? WHERE task_id = ?",
                                   (datetime.now().astimezone().isoformat(), task.task_id))
            else:
                connection.execute("UPDATE video_analysis_tasks SET upload_status = 'uploading' WHERE task_id = ?", (task.task_id,))
    raises_identity(410, "media_unavailable", env.identity.save_binding, task.token, binding_payload(task))
    raises_identity(410, "media_unavailable", env.identity.frame_file, task.token, task.task_id, "s0_f0", task.revision)
    raises_identity(410, "media_unavailable", env.identity.preview_source, task.token, task.task_id, "s0_f0", task.revision)
    workspace = env.identity.workspace(task.token, task.task_id)
    assert not workspace["media_available"] and not workspace["can_edit"]
    assert workspace["can_revoke"] is True
    assert workspace["bindings"][0]["binding_id"] == saved["binding_id"]
    assert all(not frame["image_url"] for frame in workspace["frames"])
    revoked = env.identity.revoke_binding(task.token, {"task_id": task.task_id, "binding_id": saved["binding_id"], "reason": "历史复核撤销"})
    reopened = Demo2IdentityStore(Demo2StudentRecordStore(env.record.db_path, env.record.upload_dir))
    assert reopened.export(task.token, task.task_id)["bindings"][0] == revoked
    assert revoked["status"] == "revoked" and revoked["revoked_by"] == OWNER and revoked["revoked_at"]


def test_raw_json_whitespace_changes_revision_stales_history_and_revoke_remains_available(env):
    task = make_task(env)
    pupil = student(env)
    saved = env.identity.save_binding(task.token, binding_payload(task, pupil["student_id"]))
    new_revision = persist_result(env, task.task_id, raw=task.raw + "\n")
    assert new_revision != task.revision
    workspace = env.identity.workspace(task.token, task.task_id)
    historical = workspace["bindings"][0]
    assert historical["stale"] is True and historical["current_revision"] is False
    assert workspace["summary"]["current_confirmed_count"] == 0
    raises_identity(409, "stale_frame_revision", env.identity.frame_file, task.token, task.task_id, "s0_f0", task.revision)
    raises_identity(409, "stale_frame_revision", env.identity.preview_source, task.token, task.task_id, "s0_f0", task.revision)
    raises_identity(409, "stale_frame_revision", env.identity.save_binding, task.token, binding_payload(task, pupil["student_id"]))
    assert env.identity.save_binding(task.token, binding_payload(task, pupil["student_id"], frame_revision=new_revision))
    revoked = env.identity.revoke_binding(task.token, {"task_id": task.task_id, "binding_id": saved["binding_id"], "reason": "旧版本误认"})
    assert revoked["status"] == "revoked" and revoked["stale"] is True


@pytest.mark.parametrize("relative", ["../../outside.jpg", "../other_task/image.jpg", "/tmp/private.jpg", "C:/private.jpg",
                                      "C:private.jpg", "\\\\server\\share\\private.jpg", "media_fixture/frames/a.jpg:secret",
                                      "media_fixture/frames/a.txt", "media_fixture/frames/a\x00.jpg", "", None])
def test_malicious_explicit_frame_paths_fail_closed_without_fallback(env, relative):
    task = make_task(env)
    env.identity.frame_file(task.token, task.task_id, "s0_f0", task.revision)
    result = copy.deepcopy(task.result)
    result["segments"][0]["visual"]["samples"][0]["image_path"] = relative
    revision = persist_result(env, task.task_id, result)
    raises_identity(409, "invalid_frame_manifest", env.identity.frame_file, task.token, task.task_id, "s0_f0", revision)
    raises_identity(409, "invalid_frame_manifest", env.identity.preview_source, task.token, task.task_id, "s0_f0", revision)
    raises_identity(409, "invalid_frame_manifest", env.identity.save_binding, task.token, binding_payload(task, frame_revision=revision))
    assert env.identity.workspace(task.token, task.task_id)["media_available"] is False


@pytest.mark.parametrize("change", ["version", "fps", "window", "fractional_time", "shifted_time", "directory", "missing_directory", "missing_samples", "wrong_time_key"])
def test_legacy_filtered_manifest_fallback_is_version_and_sample_contract_specific(env, change):
    task = make_task(env)
    result = json.loads(task.raw)
    if change == "version":
        result["analysis_version"] = "unrecognized"
    elif change == "fps":
        result["sampling"]["fps"] = 2
    elif change == "window":
        result["sampling"]["window_sec"] = 30
    elif change == "fractional_time":
        result["segments"][0]["visual"]["samples"][0]["timestamp_sec"] = 0.5
    elif change == "shifted_time":
        result["segments"][0]["visual"]["samples"][0]["timestamp_sec"] = 1
    elif change == "directory":
        result["artifacts"]["frames"] = "../other/frames"
    elif change == "missing_directory":
        del result["artifacts"]["frames"]
    elif change == "missing_samples":
        result["segments"][0]["visual"].pop("samples")
    else:
        sample = result["segments"][0]["visual"]["samples"][0]
        sample["time_sec"] = sample.pop("timestamp_sec")
    revision = persist_result(env, task.task_id, result)
    raises_identity(409, "invalid_frame_manifest", env.identity.frame_file, task.token, task.task_id, "s0_f0", revision)


@pytest.mark.parametrize("value", ["wrong", "0" * 64, None])
def test_result_source_hash_must_match_persisted_upload_hash(env, value):
    task = make_task(env)
    env.identity.frame_file(task.token, task.task_id, "s0_f0", task.revision)
    result = json.loads(task.raw)
    result["source_sha256"] = value
    revision = persist_result(env, task.task_id, result)
    raises_identity(409, "source_hash_mismatch", env.identity.save_binding, task.token, binding_payload(task, frame_revision=revision))
    raises_identity(409, "source_hash_mismatch", env.identity.frame_file, task.token, task.task_id, "s0_f0", revision)
    raises_identity(409, "source_hash_mismatch", env.identity.preview_source, task.token, task.task_id, "s0_f0", revision)


@pytest.mark.parametrize("raw", ["{", "null", "[]", '{"task_id":"other"}', '{"segments":NaN}'])
def test_bad_json_cannot_create_frames_or_break_history_read(env, raw):
    task = make_task(env)
    saved = env.identity.save_binding(task.token, binding_payload(task))
    revision = persist_result(env, task.task_id, raw=raw)
    raises_identity(409, "invalid_frame_manifest", env.identity.frame_file, task.token, task.task_id, "s0_f0", revision)
    raises_identity(409, "invalid_frame_manifest", env.identity.preview_source, task.token, task.task_id, "s0_f0", revision)
    workspace = env.identity.workspace(task.token, task.task_id)
    assert workspace["bindings"][0]["binding_id"] == saved["binding_id"]
    assert workspace["bindings"][0]["stale"] is True
    assert not workspace["media_available"] and workspace["frames"] == []


def test_missing_frame_and_unknown_frame_are_checked_at_access_time(env):
    task = make_task(env)
    env.identity.preview_source(task.token, task.task_id, "s0_f0", task.revision)
    task.paths["s0_f0"].unlink()
    for key in ("s0_f0", "s99_f99", "../../outside"):
        raises_identity(404, "frame_unavailable", env.identity.frame_file, task.token, task.task_id, key, task.revision)
        raises_identity(404, "frame_unavailable", env.identity.preview_source, task.token, task.task_id, key, task.revision)
    raises_identity(404, "frame_unavailable", env.identity.save_binding, task.token, binding_payload(task))
    assert env.identity.workspace(task.token, task.task_id)["summary"]["frame_files_checked_on_access"] is True


def test_frame_symlink_cannot_escape_or_borrow_another_tasks_frame(env):
    task = make_task(env)
    outside = env.tmp / "outside.jpg"
    outside.write_bytes(b"must not be served")
    target = task.paths["s0_f0"]
    target.unlink()
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks is not permitted on this Windows host")
    raises_identity(409, "invalid_frame_manifest", env.identity.frame_file, task.token, task.task_id, "s0_f0", task.revision)
    assert outside.read_bytes() == b"must not be served"


def test_nonredirecting_reparse_frame_is_rejected(env, monkeypatch):
    task = make_task(env)
    env.identity.preview_source(task.token, task.task_id, "s0_f0", task.revision)
    target = task.paths["s0_f0"]
    original = Path.lstat

    def pretend_reparse(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == target:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return info

    monkeypatch.setattr(Path, "lstat", pretend_reparse)
    raises_identity(409, "invalid_frame_manifest", env.identity.frame_file, task.token, task.task_id, "s0_f0", task.revision)
    raises_identity(409, "invalid_frame_manifest", env.identity.preview_source, task.token, task.task_id, "s0_f0", task.revision)


def test_task_without_school_snapshot_cannot_borrow_current_roster(env):
    task = make_task(env, set_school=False)
    school(env)
    pupil = student(env)
    workspace = env.identity.workspace(task.token, task.task_id)
    assert workspace["students"] == [] and workspace["scope_key"] == "" and workspace["can_edit"] is False
    raises_identity(409, "school_context_required", env.identity.save_binding, task.token, binding_payload(task, pupil["student_id"]))


def test_identity_tables_are_additive_and_do_not_change_legacy_student_or_schema(env):
    env.record.ensure_students([{"student_id": "legacy", "display_name": "同名学生"}])
    with env.record._connect() as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        legacy = [tuple(row) for row in connection.execute("SELECT * FROM students")]
        schema = [tuple(row) for row in connection.execute("SELECT name, sql FROM sqlite_master WHERE name NOT LIKE '%demo2_identity%' ORDER BY name")]
    school(env)
    created = student(env)
    assert created["student_id"] != "legacy"
    Demo2IdentityStore(env.record)
    Demo2IdentityStore(env.record)
    with env.record._connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == version
        assert [tuple(row) for row in connection.execute("SELECT * FROM students")] == legacy
        assert [tuple(row) for row in connection.execute("SELECT name, sql FROM sqlite_master WHERE name NOT LIKE '%demo2_identity%' ORDER BY name")] == schema
        assert connection.execute("SELECT COUNT(*) FROM demo2_identity_students").fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_exports_and_audits_retain_manual_identity_and_revoke_is_idempotent(env):
    task = make_task(env)
    pupil = student(env)
    env.identity.roster(task.token)
    saved = env.identity.save_binding(task.token, binding_payload(task, pupil["student_id"]))
    env.identity.frame_file(task.token, task.task_id, "s0_f0", task.revision)
    env.identity.workspace(task.token, task.task_id)
    exported = env.identity.export(task.token, task.task_id)
    assert exported["schema_version"] == 1 and exported["exported_at"]
    assert exported["identity_scope"] == "single_sample_frame"
    assert exported["summary"]["tracking_performed"] is False
    assert exported["summary"]["global_motion_attributed_to_student"] is False
    assert exported["summary"]["global_audio_attributed_to_student"] is False
    assert exported["summary"]["bound_student_count"] == 1
    payload = {"task_id": task.task_id, "binding_id": saved["binding_id"], "reason": "教师复核撤销"}
    revoked = env.identity.revoke_binding(task.token, payload)
    assert env.identity.revoke_binding(task.token, {**payload, "reason": "不能覆盖原撤销"}) == revoked
    with env.record._connect() as connection:
        audits = [dict(row) for row in connection.execute("SELECT * FROM audit_logs WHERE object_type = 'demo2_identity'")]
    assert {row["action"] for row in audits} >= {"identity_roster_viewed", "identity_student_created", "identity_binding_confirmed",
                                                "identity_binding_revoked", "identity_frame_viewed", "identity_workspace_viewed", "identity_exported"}
    assert all(row["actor"] == OWNER for row in audits)
    assert sum(row["action"] == "identity_binding_revoked" for row in audits) == 1
    assert str(env.tmp) not in json.dumps(exported) and task.token not in json.dumps(audits)


def test_concurrent_bindings_serialize_duplicate_and_overlap_checks(env):
    task = make_task(env)
    pupil = student(env)
    stores = [Demo2IdentityStore(env.record) for _ in range(4)]

    def save(store):
        try:
            return store.save_binding(task.token, binding_payload(task, pupil["student_id"]))["status"]
        except IdentityError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=4) as executor:
        outcomes = list(executor.map(save, stores))
    assert outcomes.count("confirmed") == 1 and outcomes.count("duplicate_student_binding") == 3


def test_2258_sample_index_does_not_resolve_all_paths_on_frame_requests(env, monkeypatch):
    task = make_task(env, count=2258, materialize=[0, 2257])
    calls = []
    controlled = env.record._controlled_video_path

    def counted(path, subtree):
        calls.append((path, subtree))
        return controlled(path, subtree)

    monkeypatch.setattr(env.record, "_controlled_video_path", counted)
    started = time.perf_counter()
    workspace = env.identity.workspace(task.token, task.task_id)
    workspace_seconds = time.perf_counter() - started
    assert len(workspace["frames"]) == 2258 and len(calls) <= 2
    calls.clear()
    started = time.perf_counter()
    path, _ = env.identity.frame_file(task.token, task.task_id, "s112_f17", task.revision)
    frame_seconds = time.perf_counter() - started
    assert path == task.paths["s112_f17"] and len(calls) <= 4
    print(f"2258 samples: workspace={workspace_seconds:.4f}s frame={frame_seconds:.4f}s controlled_path_calls={len(calls)}")


def confirmation_payload(env, task, **changes):
    return {"task_id": task.task_id, "expected_scope_key": env.identity.roster(task.token)["scope_key"],
            "confirmed": True, **changes}


def test_confirm_task_school_uses_only_current_server_context_and_preserves_task(env):
    task = make_task(env, set_school=False)
    school(env)
    pupil = student(env)
    with env.record._connect() as connection:
        connection.execute("UPDATE video_analysis_tasks SET updated_at = '2000-01-01T00:00:00+00:00' WHERE task_id = ?", (task.task_id,))
    before = task_row(env, task.task_id)
    preview = env.identity.workspace(task.token, task.task_id)
    assert preview["needs_school_confirmation"] is True and preview["can_confirm_school"] is True
    assert preview["can_edit"] is False and preview["students"] == []
    assert env.identity.frame_file(task.token, task.task_id, "s0_f0", task.revision)[0].exists()
    raises_identity(409, "school_context_required", env.identity.save_binding, task.token, binding_payload(task, pupil["student_id"]))

    payload = confirmation_payload(env, task)
    workspace = env.identity.confirm_task_school(task.token, payload)
    assert workspace["school_context"] == CONTEXT
    assert workspace["scope_key"] == payload["expected_scope_key"] == pupil["scope_key"]
    assert workspace["students"] == [pupil] and workspace["can_edit"] is True
    assert workspace["needs_school_confirmation"] is False and workspace["can_confirm_school"] is False
    after = task_row(env, task.task_id)
    assert json.loads(after["school_context_json"]) == CONTEXT
    assert after["updated_at"] != before["updated_at"]
    assert {key: value for key, value in after.items() if key not in {"school_context_json", "updated_at"}} == {
        key: value for key, value in before.items() if key not in {"school_context_json", "updated_at"}}
    with env.record._connect() as connection:
        audits = [dict(row) for row in connection.execute("SELECT * FROM audit_logs WHERE action = 'identity_task_school_confirmed'")]
    assert len(audits) == 1 and audits[0]["actor"] == OWNER and audits[0]["object_id"] == task.task_id
    assert json.loads(audits[0]["detail_json"]) == {"old_scope_key": "", "new_scope_key": pupil["scope_key"], "confirmed_by": OWNER}
    assert env.identity.save_binding(task.token, binding_payload(task, pupil["student_id"]))["scope_key"] == pupil["scope_key"]
    raises_identity(409, "task_school_not_empty", env.identity.confirm_task_school, task.token, payload)
    migrated = {**CONTEXT, "school_name": "之后的新学校"}
    before_migration = task_row(env, task.task_id)
    with pytest.raises(ValueError, match="管理员迁移"):
        school(env, context=migrated)
    assert env.identity.roster(task.token)["school_context"] == CONTEXT
    assert env.identity.roster(task.token)["students"] == [pupil]
    assert task_row(env, task.task_id) == before_migration
    simulate_school_migration(env, migrated)
    reopened = Demo2IdentityStore(Demo2StudentRecordStore(env.record.db_path, env.record.upload_dir))
    assert reopened.workspace(task.token, task.task_id)["school_context"] == CONTEXT


@pytest.mark.parametrize("username", [OTHER, ADMIN, MEMBER])
def test_confirm_task_school_rejects_cross_owner_admin_and_member(env, username):
    task = make_task(env, set_school=False)
    school(env)
    payload = confirmation_payload(env, task)
    _, token = login(env, username)
    expected = (404, "task_unavailable") if username == OTHER else (403, "identity_forbidden")
    raises_identity(*expected, env.identity.confirm_task_school, token, payload)
    assert env.identity._empty_school_snapshot(task_row(env, task.task_id)["school_context_json"])
    if username == ADMIN:
        workspace = env.identity.workspace(token, task.task_id)
        assert workspace["needs_school_confirmation"] is False and workspace["can_confirm_school"] is False
        raises_identity(403, "identity_forbidden", env.identity.confirm_task_school, token, {})


@pytest.mark.parametrize("extra", [{"confirmed": False}, {"confirmed": 1}, {"confirmed": "true"},
                                   {"expected_scope_key": ""}, {"expected_scope_key": None},
                                   {"school_name": "客户端学校"}, {"school_context": CONTEXT},
                                   {"confirmed_by": "客户端确认人"}, {"updated_at": "客户端时间"}])
def test_confirm_task_school_rejects_implicit_confirmation_and_client_metadata(env, extra):
    task = make_task(env, set_school=False)
    school(env)
    before = task_row(env, task.task_id)
    raises_identity(400, "invalid_school_confirmation", env.identity.confirm_task_school, task.token,
                    confirmation_payload(env, task, **extra))
    assert task_row(env, task.task_id) == before


@pytest.mark.parametrize("snapshot", [CONTEXT, {"city": "已有城市", "district": "", "school_name": ""},
                                      {"city": "", "district": "已有区县", "school_name": ""},
                                      {"city": "", "district": "", "school_name": "已有学校"},
                                      {"city": " ", "district": "", "school_name": ""},
                                      {"city": None}, {"city": 0}, {"city": []}, {"city": "\x00"},
                                      {"unexpected": "metadata"}, None, []])
def test_confirm_task_school_never_overwrites_nonempty_or_invalid_snapshot(env, snapshot):
    task = make_task(env, set_school=False)
    school(env)
    raw = json.dumps(snapshot, ensure_ascii=False)
    with env.record._connect() as connection:
        connection.execute("UPDATE video_analysis_tasks SET school_context_json = ? WHERE task_id = ?", (raw, task.task_id))
    before = task_row(env, task.task_id)
    workspace = env.identity.workspace(task.token, task.task_id)
    assert workspace["needs_school_confirmation"] is False and workspace["can_confirm_school"] is False
    raises_identity(409, "task_school_not_empty", env.identity.confirm_task_school, task.token, confirmation_payload(env, task))
    assert task_row(env, task.task_id) == before


def test_confirm_task_school_allows_empty_legacy_object_but_not_malformed_json(env):
    task = make_task(env, set_school=False)
    school(env)
    payload = confirmation_payload(env, task)
    with env.record._connect() as connection:
        connection.execute("UPDATE video_analysis_tasks SET school_context_json = '{' WHERE task_id = ?", (task.task_id,))
    assert env.identity.workspace(task.token, task.task_id)["can_confirm_school"] is False
    raises_identity(409, "task_school_not_empty", env.identity.confirm_task_school, task.token, payload)
    with env.record._connect() as connection:
        connection.execute("UPDATE video_analysis_tasks SET school_context_json = '{}' WHERE task_id = ?", (task.task_id,))
    assert env.identity.confirm_task_school(task.token, payload)["school_context"] == CONTEXT


@pytest.mark.parametrize("raw", [
    '{"city":"已有城市","city":"","district":"","school_name":""}',
    '{"city":"","district":"","school_name":"已有学校","school_name":""}',
    '{"city":"已有城市","\\u0063ity":"","district":"","school_name":""}',
])
def test_confirm_task_school_rejects_duplicate_json_keys_that_hide_existing_school(env, raw):
    task = make_task(env, set_school=False)
    school(env)
    with env.record._connect() as connection:
        connection.execute("UPDATE video_analysis_tasks SET school_context_json = ? WHERE task_id = ?", (raw, task.task_id))
    workspace = env.identity.workspace(task.token, task.task_id)
    assert workspace["needs_school_confirmation"] is False and workspace["can_confirm_school"] is False
    raises_identity(409, "task_school_not_empty", env.identity.confirm_task_school, task.token, confirmation_payload(env, task))
    assert task_row(env, task.task_id)["school_context_json"] == raw


@pytest.mark.parametrize("binding_state", ["confirmed", "revoked", "other_owner"])
def test_confirm_task_school_refuses_any_binding_even_revoked_or_different_owner(env, binding_state):
    task = make_task(env)
    saved = env.identity.save_binding(task.token, binding_payload(task))
    if binding_state == "revoked":
        env.identity.revoke_binding(task.token, {"task_id": task.task_id, "binding_id": saved["binding_id"], "reason": "历史撤销"})
    other_account = login(env, OTHER)[0]
    with env.record._connect() as connection:
        # Reproduce a legacy inconsistent snapshot only in this disposable DB.
        connection.execute("UPDATE video_analysis_tasks SET school_context_json = '{}' WHERE task_id = ?", (task.task_id,))
        if binding_state == "other_owner":
            connection.execute("UPDATE demo2_identity_bindings SET owner_account_id = ? WHERE binding_id = ?",
                               (other_account["account_id"], saved["binding_id"]))
    workspace = env.identity.workspace(task.token, task.task_id)
    assert workspace["needs_school_confirmation"] is True and workspace["can_confirm_school"] is False
    raises_identity(409, "task_has_bindings", env.identity.confirm_task_school, task.token, confirmation_payload(env, task))
    assert task_row(env, task.task_id)["school_context_json"] == "{}"


def test_confirm_task_school_rechecks_current_scope_after_account_school_changes(env):
    task = make_task(env, set_school=False)
    school(env)
    old_payload = confirmation_payload(env, task)
    new_context = {**CONTEXT, "district": "新测试区", "school_name": "另一学校"}
    school(env, context=new_context)
    raises_identity(409, "school_scope_changed", env.identity.confirm_task_school, task.token, old_payload)
    assert env.identity._empty_school_snapshot(task_row(env, task.task_id)["school_context_json"])
    current = confirmation_payload(env, task)
    assert current["expected_scope_key"] != old_payload["expected_scope_key"]
    assert env.identity.confirm_task_school(task.token, current)["school_context"] == new_context


def test_confirm_task_school_without_complete_current_school_is_disabled(env):
    task = make_task(env, set_school=False)
    workspace = env.identity.workspace(task.token, task.task_id)
    assert workspace["needs_school_confirmation"] is True and workspace["can_confirm_school"] is False
    raises_identity(409, "school_context_required", env.identity.confirm_task_school, task.token,
                    {"task_id": task.task_id, "expected_scope_key": "0" * 64, "confirmed": True})


@pytest.mark.parametrize("state", ["expired", "deleted", "missing", "processing", "completed"])
def test_confirm_task_school_requires_live_source_and_exact_evidence_ready(env, state):
    task = make_task(env, set_school=False)
    school(env)
    if state == "missing":
        task.source.unlink()
    else:
        with env.record._connect() as connection:
            if state == "expired":
                connection.execute("UPDATE video_analysis_tasks SET expires_at = '2000-01-01T00:00:00+00:00' WHERE task_id = ?", (task.task_id,))
            elif state == "deleted":
                connection.execute("UPDATE video_analysis_tasks SET raw_media_deleted_at = 'deleted' WHERE task_id = ?", (task.task_id,))
            else:
                connection.execute("UPDATE video_analysis_tasks SET analysis_status = ? WHERE task_id = ?", (state, task.task_id))
    workspace = env.identity.workspace(task.token, task.task_id)
    assert workspace["needs_school_confirmation"] is True and workspace["can_confirm_school"] is False
    expected = (409, "evidence_not_ready") if state in {"processing", "completed"} else (410, "media_unavailable")
    raises_identity(*expected, env.identity.confirm_task_school, task.token, confirmation_payload(env, task))
    assert env.identity._empty_school_snapshot(task_row(env, task.task_id)["school_context_json"])


def test_confirm_task_school_audit_failure_rolls_back_snapshot_and_timestamp(env, monkeypatch):
    task = make_task(env, set_school=False)
    school(env)
    payload = confirmation_payload(env, task)
    before = task_row(env, task.task_id)
    audit = env.identity._audit

    def fail_confirmation_audit(connection, account, action, object_id, detail):
        if action == "identity_task_school_confirmed":
            raise RuntimeError("synthetic audit failure")
        return audit(connection, account, action, object_id, detail)

    monkeypatch.setattr(env.identity, "_audit", fail_confirmation_audit)
    with pytest.raises(RuntimeError, match="synthetic audit failure"):
        env.identity.confirm_task_school(task.token, payload)
    assert task_row(env, task.task_id) == before
    with env.record._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_logs WHERE action = 'identity_task_school_confirmed'").fetchone()[0] == 0


def test_confirm_task_school_concurrent_confirmations_only_one_can_commit(env):
    task = make_task(env, set_school=False)
    school(env)
    payload = confirmation_payload(env, task)
    stores = [Demo2IdentityStore(env.record) for _ in range(3)]

    def confirm(store):
        try:
            return store.confirm_task_school(task.token, payload)["scope_key"]
        except IdentityError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=3) as executor:
        outcomes = list(executor.map(confirm, stores))
    assert outcomes.count(payload["expected_scope_key"]) == 1
    assert outcomes.count("task_school_not_empty") == 2
    with env.record._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_logs WHERE action = 'identity_task_school_confirmed'").fetchone()[0] == 1


def synthetic_frame_task(task_id="synthetic-2258", count=2258):
    segments = []
    for index in range(count):
        segment_index, sample_index = divmod(index, 20)
        if sample_index == 0:
            segments.append({"start_sec": segment_index * 20, "end_sec": min((segment_index + 1) * 20, count),
                             "visual": {"samples": []}})
        segments[-1]["visual"]["samples"].append({"timestamp_sec": index, "brightness": 80,
                                                 "sharpness": 1, "scene_motion": 0.1})
    result = {"task_id": task_id, "source_sha256": "a" * 64, "analysis_version": "demo2_media_evidence_v1.1",
              "sampling": {"fps": 1, "window_sec": 20}, "artifacts": {"frames": "media_fixture/frames"},
              "segments": segments}
    return {"task_id": task_id, "sha256": result["source_sha256"],
            "processing_result_json": json.dumps(result, separators=(",", ":"))}


def test_frame_cache_reuses_json_and_returns_independent_nested_dicts(env, monkeypatch):
    task = make_task(env, count=2258, materialize=[0, 2257])
    row = task_row(env, task.task_id)
    loads, calls = json.loads, []

    def counted(raw, *args, **kwargs):
        if raw == row["processing_result_json"]:
            calls.append(1)
        return loads(raw, *args, **kwargs)

    monkeypatch.setattr(json, "loads", counted)
    frames = env.identity._frames(row)
    frames["s0_f0"]["relative_image"] = "../../outside.jpg"
    frames["s0_f0"]["time_sec"] = -1
    frames.pop("s112_f17")
    frames["forged"] = {}
    selected, _ = env.identity._frame(row, "s0_f0", task.revision)
    assert selected["time_sec"] == 0.0
    selected["relative_image"] = "another.jpg"
    workspace = env.identity.workspace(task.token, task.task_id)
    assert len(workspace["frames"]) == 2258
    assert env.identity.frame_file(task.token, task.task_id, "s112_f17", task.revision)[0] == task.paths["s112_f17"]
    assert env.identity.preview_source(task.token, task.task_id, "s0_f0", task.revision)["time_sec"] == 0.0
    assert calls == [1]
    assert env.identity._frame_cache_entries == 2258
    assert len(env.identity._frame_cache) == 1
    key, cached = next(iter(env.identity._frame_cache.items()))
    assert key == (task.task_id, task.revision, row["sha256"].lower())
    assert all(set(frame) == {"frame_key", "time_sec", "segment_start_sec", "segment_end_sec", "relative_image"}
               for frame in cached.values())
    assert all(isinstance(value, (str, float)) for frame in cached.values() for value in frame.values())


def test_frame_cache_is_isolated_by_store_task_and_exact_manifest(env):
    task = synthetic_frame_task(count=2)
    other_store = Demo2IdentityStore(env.record)
    assert len(env.identity._frames(task)) == 2
    assert not other_store._frame_cache
    assert len(other_store._frames(synthetic_frame_task(count=3))) == 3
    other_task = synthetic_frame_task("other-task", count=4)
    assert len(env.identity._frames(other_task)) == 4
    raises_identity(409, "invalid_frame_manifest", env.identity._frames, {**task, "task_id": "other-task"})
    assert len(env.identity._frames(task)) == 2
    assert len(env.identity._frame_cache) == 2 and len(other_store._frame_cache) == 1


def test_frame_cache_key_and_parser_use_the_same_input_snapshot(env, monkeypatch):
    task = synthetic_frame_task(count=2)
    original = dict(task)
    parse = env.identity._parse_frames

    def change_caller_input(snapshot):
        task.update(synthetic_frame_task(count=3))
        return parse(snapshot)

    monkeypatch.setattr(env.identity, "_parse_frames", change_caller_input)
    assert len(env.identity._frames(task)) == 2
    assert len(env.identity._frames(task)) == 3
    assert len(env.identity._frames(original)) == 2


def test_frame_cache_reparses_new_revisions_and_does_not_cache_failures(env, monkeypatch):
    task = synthetic_frame_task(count=3)
    parse, calls = env.identity._parse_frames, []

    def counted(row):
        calls.append(1)
        return parse(row)

    monkeypatch.setattr(env.identity, "_parse_frames", counted)
    assert env.identity._frames(task)["s0_f0"]["time_sec"] == 0
    task["processing_result_json"] += "\n"
    env.identity._frames(task)
    result = json.loads(task["processing_result_json"])
    sample = result["segments"][0]["visual"]["samples"][0]
    sample.update(timestamp_sec=0.5, image_path="media_fixture/frames/new.jpg")
    task["processing_result_json"] = json.dumps(result)
    assert env.identity._frames(task)["s0_f0"]["time_sec"] == 0.5
    assert env.identity._frames(task)["s0_f0"]["relative_image"].endswith("/new.jpg")
    assert len(calls) == 3
    good_raw = task["processing_result_json"]
    cached_keys = list(env.identity._frame_cache)
    task["processing_result_json"] = "{"
    for _ in range(2):
        raises_identity(409, "invalid_frame_manifest", env.identity._frames, task)
    assert len(calls) == 5 and list(env.identity._frame_cache) == cached_keys
    task["processing_result_json"] = good_raw
    assert env.identity._frames(task)["s0_f0"]["time_sec"] == 0.5
    assert len(calls) == 5


@pytest.mark.parametrize("raw", [None, {}, "\ud800", " " * (MAX_PROCESSING_RESULT_BYTES + 1)],
                         ids=["null", "object", "invalid-unicode", "oversize"])
def test_frame_cache_checks_raw_type_encoding_and_size_before_lookup(env, raw):
    task = synthetic_frame_task(count=1)
    env.identity._frames(task)
    raises_identity(409, "invalid_frame_manifest", env.identity._frames, {**task, "processing_result_json": raw})
    assert len(env.identity._frame_cache) == 1 and env.identity._frame_cache_entries == 1


@pytest.mark.parametrize("source_hash", ["0" * 64, "invalid", None, [], "\ud800"])
def test_frame_cache_rechecks_persisted_source_hash_even_when_revision_is_unchanged(env, source_hash):
    task = make_task(env)
    env.identity.preview_source(task.token, task.task_id, "s0_f0", task.revision)
    row = task_row(env, task.task_id)
    raises_identity(409, "source_hash_mismatch", env.identity._frames, {**row, "sha256": source_hash})
    if isinstance(source_hash, str) and source_hash.isascii():
        with env.record._connect() as connection:
            connection.execute("UPDATE video_analysis_tasks SET sha256 = ? WHERE task_id = ?", (source_hash, task.task_id))
        for method in (env.identity.frame_file, env.identity.preview_source):
            raises_identity(409, "source_hash_mismatch", method, task.token, task.task_id, "s0_f0", task.revision)
        workspace = env.identity.workspace(task.token, task.task_id)
        assert workspace["frames"] == [] and not workspace["can_edit"] and not workspace["media_available"]
    assert len(env.identity._frame_cache) == 1


def test_frame_cache_accepts_case_equivalent_source_hash(env):
    task = synthetic_frame_task(count=1)
    expected = env.identity._frames(task)
    assert env.identity._frames({**task, "sha256": task["sha256"].upper()}) == expected
    assert len(env.identity._frame_cache) == 1


def test_frame_cache_lru_manifest_limit_includes_empty_manifests(env):
    assert MAX_FRAME_CACHE_MANIFESTS == 8
    tasks = [synthetic_frame_task(f"cache-{index}", count=0) for index in range(9)]
    for task in tasks[:8]:
        assert env.identity._frames(task) == {}
    env.identity._frames(tasks[0])
    env.identity._frames(tasks[8])
    keys = [key[0] for key in env.identity._frame_cache]
    assert keys == [task["task_id"] for task in tasks[2:8]] + [tasks[0]["task_id"], tasks[8]["task_id"]]
    assert env.identity._frame_cache_entries == 0


def test_frame_cache_total_entries_evict_lru_before_publishing(env):
    assert MAX_FRAME_CACHE_ENTRIES == 40_000
    tasks = [synthetic_frame_task(f"large-{index}", count=20_000) for index in range(3)]
    for task in tasks[:2]:
        assert len(env.identity._frames(task)) == 20_000
    assert env.identity._frame_cache_entries == 40_000
    env.identity._frames(tasks[0])
    env.identity._frames(tasks[2])
    assert [key[0] for key in env.identity._frame_cache] == ["large-0", "large-2"]
    assert env.identity._frame_cache_entries == sum(map(len, env.identity._frame_cache.values())) == 40_000
    env.identity._frames(synthetic_frame_task("one-more", count=1))
    assert [key[0] for key in env.identity._frame_cache] == ["large-2", "one-more"]
    assert env.identity._frame_cache_entries == 20_001
    raises_identity(409, "invalid_frame_manifest", env.identity._frames, synthetic_frame_task("too-many", count=20_001))
    assert env.identity._frame_cache_entries == 20_001


def test_frame_cache_concurrent_cold_reads_parse_once_and_cannot_pollute_each_other(env, monkeypatch):
    task = synthetic_frame_task()
    gate = Barrier(8)
    parse, calls = env.identity._parse_frames, []

    def counted(row):
        calls.append(1)
        time.sleep(0.02)
        return parse(row)

    def read(index):
        gate.wait(timeout=10)
        frames = env.identity._frames(task)
        assert frames["s0_f0"]["time_sec"] == 0
        frames["s0_f0"]["time_sec"] = -index - 1
        frames.pop("s112_f17")

    monkeypatch.setattr(env.identity, "_parse_frames", counted)
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(read, range(8)))
    assert calls == [1] and env.identity._frame_cache_entries == 2258
    assert len(env.identity._frames(task)) == 2258
    assert env.identity._frames(task)["s0_f0"]["time_sec"] == 0


def test_frame_cache_concurrent_eviction_respects_both_limits(env):
    tasks = [synthetic_frame_task(f"concurrent-{index}", count=6000) for index in range(10)]

    def read(task):
        for _ in range(2):
            assert len(env.identity._frames(task)) == 6000
            with env.identity._frame_cache_lock:
                assert len(env.identity._frame_cache) <= 8
                assert env.identity._frame_cache_entries == sum(map(len, env.identity._frame_cache.values())) <= 40_000

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(read, tasks))


def test_frame_cache_keeps_roster_scope_and_write_state_live(env):
    task = make_task(env)
    assert env.identity.workspace(task.token, task.task_id)["students"] == []
    pupil = student(env)
    assert env.identity.workspace(task.token, task.task_id)["students"] == [pupil]
    admin = login(env, ADMIN)[1]
    assert not env.identity.workspace(admin, task.task_id)["can_edit"]
    assert env.identity.workspace(task.token, task.task_id)["can_edit"]
    with env.record._connect() as connection:
        connection.execute("UPDATE video_analysis_tasks SET school_context_json = '{}' WHERE task_id = ?", (task.task_id,))
    workspace = env.identity.workspace(task.token, task.task_id)
    assert workspace["students"] == [] and workspace["scope_key"] == "" and not workspace["can_edit"]
    assert workspace["media_available"] and len(env.identity._frame_cache) == 1


@pytest.mark.parametrize("username", [OWNER, ADMIN])
def test_preview_source_is_server_only_read_only_and_audited(env, monkeypatch, username):
    task = make_task(env, count=23)
    token = login(env, username)[1]
    before = task_row(env, task.task_id)
    source_bytes = task.source.read_bytes()
    source_path, calls = env.record._video_source_path, []

    def controlled(row):
        calls.append(row["task_id"])
        return source_path(row)

    monkeypatch.setattr(env.record, "_video_source_path", controlled)
    for _ in range(2):
        result = env.identity.preview_source(token, task.task_id, "s1_f1", task.revision)
        assert result == {"source_path": task.source, "time_sec": 21.0}
        assert isinstance(result["source_path"], Path) and type(result["time_sec"]) is float
    assert len(calls) >= 2 and all(task_id == task.task_id for task_id in calls)
    assert task_row(env, task.task_id) == before and task.source.read_bytes() == source_bytes
    for method in (env.identity.workspace, env.identity.export):
        public = json.dumps(method(token, task.task_id), ensure_ascii=False)
        assert "source_path" not in public and str(task.source) not in public
    with env.record._connect() as connection:
        audits = [dict(row) for row in connection.execute("SELECT * FROM audit_logs WHERE action = 'identity_preview_viewed'")]
        assert connection.execute("SELECT COUNT(*) FROM demo2_identity_bindings").fetchone()[0] == 0
    assert len(audits) == 2
    assert all(row["actor"] == username and row["object_id"] == task.task_id for row in audits)
    assert task.token not in json.dumps(audits) and str(task.source) not in json.dumps(audits)
    assert all(json.loads(row["detail_json"]) == {"frame_key": "s1_f1", "frame_revision": task.revision} for row in audits)


@pytest.mark.parametrize("change", ["role", "owner"])
def test_preview_source_rechecks_role_and_task_owner_before_using_warm_cache(env, monkeypatch, change):
    task = make_task(env)
    env.identity.preview_source(task.token, task.task_id, "s0_f0", task.revision)
    account, _ = login(env)
    other, other_token = login(env, OTHER)
    with env.record._connect() as connection:
        if change == "role":
            connection.execute("UPDATE platform_accounts SET role = 'registered_member', bound_channel_id = NULL WHERE account_id = ?",
                               (account["account_id"],))
        else:
            connection.execute("UPDATE video_analysis_tasks SET account_id = ? WHERE task_id = ?", (other["account_id"], task.task_id))

    def must_not_read(task):
        pytest.fail("Unauthorized requests must not access the frame cache")

    with monkeypatch.context() as patch:
        patch.setattr(env.identity, "_frames", must_not_read)
        expected = (403, "identity_forbidden") if change == "role" else (404, "task_unavailable")
        for method in (env.identity.frame_file, env.identity.preview_source):
            raises_identity(*expected, method, task.token, task.task_id, "s0_f0", task.revision)
    if change == "owner":
        assert env.identity.preview_source(other_token, task.task_id, "s0_f0", task.revision)["source_path"] == task.source


@pytest.mark.parametrize("frame_key,revision", [(None, "current"), ([], "current"), ("s0_f0", None),
                                                ("s0_f0", []), ("s0_f0", "old")])
def test_preview_source_rejects_invalid_frame_or_revision_without_audit(env, frame_key, revision):
    task = make_task(env)
    env.identity.frame_file(task.token, task.task_id, "s0_f0", task.revision)
    expected = (404, "frame_unavailable") if revision == "current" else (409, "stale_frame_revision")
    raises_identity(*expected, env.identity.preview_source, task.token, task.task_id, frame_key,
                    task.revision if revision == "current" else revision)
    with env.record._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_logs WHERE action = 'identity_preview_viewed'").fetchone()[0] == 0


def test_preview_source_rejects_redirected_upload_after_cache_warmup(env):
    task = make_task(env)
    other = make_task(env, OTHER)
    env.identity.preview_source(task.token, task.task_id, "s0_f0", task.revision)
    with env.record._connect() as connection:
        connection.execute("UPDATE video_analysis_tasks SET file_path = ? WHERE task_id = ?", (str(other.source), task.task_id))
    raises_identity(410, "media_unavailable", env.identity.preview_source, task.token, task.task_id, "s0_f0", task.revision)


def test_preview_source_audit_failure_returns_no_source(env, monkeypatch):
    task = make_task(env)

    def fail_audit(*args):
        raise RuntimeError("synthetic preview audit failure")

    monkeypatch.setattr(env.identity, "_audit", fail_audit)
    with pytest.raises(RuntimeError, match="synthetic preview audit failure"):
        env.identity.preview_source(task.token, task.task_id, "s0_f0", task.revision)
    with env.record._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM audit_logs WHERE action = 'identity_preview_viewed'").fetchone()[0] == 0


def test_frame_cache_2258_synthetic_parse_timing(env):
    task = synthetic_frame_task()
    expected = env.identity._parse_frames(task)
    assert len(expected) == 2258 and env.identity._frames(task) == expected
    uncached = statistics.median(timeit.repeat(lambda: env.identity._parse_frames(task), repeat=5, number=20)) / 20
    cached = statistics.median(timeit.repeat(lambda: env.identity._frames(task), repeat=5, number=20)) / 20
    print(f"2258 synthetic frames ({len(task['processing_result_json'].encode('utf-8'))} bytes): "
          f"uncached={uncached * 1000:.3f}ms cached={cached * 1000:.3f}ms speedup={uncached / cached:.1f}x")
