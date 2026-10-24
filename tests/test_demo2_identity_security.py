"""Independent identity HTTP acceptance; disposable DB/media, never live services.

The shared harness marks source video and detector output as synthetic fixtures.
These tests verify manual single-frame confirmation, not recognition accuracy.
"""
from __future__ import annotations

import hashlib
import http.client
import importlib
import json
import socket
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from urllib.parse import urlencode
from uuid import uuid4

import pytest


API = "/api/v1/demo2/identity"
BOX = {"x": 0.10, "y": 0.15, "width": 0.25, "height": 0.35}
OTHER_BOX = {"x": 0.60, "y": 0.15, "width": 0.25, "height": 0.35}
NEW_SCHOOL = {"city": "虚构乙市", "district": "虚构二区", "school_name": "QA独立乙学校"}


def request(env, method, path, payload=None, *, user="t1", token=None):
    """One small HTTP write avoids Windows early-rejection header/body races."""
    if token is None:
        token = "" if user is None else env.tokens[user]
    body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Host": f"127.0.0.1:{env.port}", "Connection": "close",
               "Content-Type": "application/json", "Content-Length": str(len(body))}
    if token:
        headers["Cookie"] = "rehab_demo2_session=" + token
    wire = (f"{method} {path} HTTP/1.1\r\n" +
            "".join(f"{key}: {value}\r\n" for key, value in headers.items()) + "\r\n").encode("ascii") + body
    connection = http.client.HTTPConnection("127.0.0.1", env.port, timeout=15)
    try:
        connection.connect()
        connection.sock.sendall(wire)
        response = http.client.HTTPResponse(connection.sock, method=method)
        response.begin()
        data = response.read()
        response_headers = {key.lower(): value for key, value in response.getheaders()}
        parsed = json.loads(data) if "application/json" in response_headers.get("content-type", "") else data
        return response.status, response_headers, parsed
    finally:
        connection.close()


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    from scripts.qa_demo2_identity_20260910 import isolated_identity_server

    with isolated_identity_server(tmp_path_factory.mktemp("identity_security")) as value:
        yield value


@pytest.fixture()
def fresh_env(tmp_path):
    from scripts.qa_demo2_identity_20260910 import isolated_identity_server

    with isolated_identity_server(tmp_path / "identity_security") as value:
        yield value


def workspace(env, *, user="t1", task_id=None):
    task_id = task_id or env.task_ids["t1"]
    status, _, body = request(env, "GET", API + "/workspace?" + urlencode({"task_id": task_id}), user=user)
    assert status == 200, body
    assert body.get("ok") is True
    return body["workspace"]


def frame_query(env, *, task_id=None, frame=None, revision=None):
    task_id = task_id or env.task_ids["t1"]
    current = workspace(env, user="t1" if task_id == env.task_ids["t1"] else "t2", task_id=task_id)
    assert current["frames"], ("Real finish_video_analysis must publish a usable trusted frame manifest", current)
    return urlencode({"task_id": task_id, "frame_key": frame or current["frames"][0]["frame_key"],
                      "frame_revision": revision or current["frame_revision"]})


def binding_payload(env, *, student_id=None, role="unknown", task_id=None, box=None):
    task_id = task_id or env.task_ids["t1"]
    current = workspace(env, user="t1" if task_id == env.task_ids["t1"] else "t2", task_id=task_id)
    assert current["media_available"] is True and current["frames"], current
    payload = {"task_id": task_id, "frame_key": current["frames"][0]["frame_key"],
               "frame_revision": current["frame_revision"], "role": role, "bbox": box or dict(BOX)}
    if student_id is not None:
        payload["student_id"] = student_id
    return payload


def create_student(env, *, user="t1", code=None, name="虚拟同名学生"):
    status, _, body = request(env, "POST", API + "/students", {
        "display_name": name, "student_code": code or uuid4().hex[:12],
        "class_name": "QA虚拟班级", "note": "测试夹具；非真实学生",
    }, user=user)
    assert status == 200, body
    assert body.get("ok") is True
    return body["student"]


def save_binding(env, **options):
    status, _, body = request(env, "POST", API + "/bindings", binding_payload(env, **options))
    assert status == 200, body
    return body["binding"]


def count_rows(env, table):
    assert table in {"demo2_identity_students", "demo2_identity_bindings", "students", "audit_logs"}
    with sqlite3.connect(env.records.db_path) as connection:
        return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def assert_no_private_paths_or_credentials(env, value):
    encoded = json.dumps(value, ensure_ascii=False)
    assert str(env.records.db_path) not in encoded
    assert str(env.records.video_task_dir) not in encoded
    for secret in [*env.tokens.values(), *env.users.values()]:
        assert secret not in encoded
    for key in ("password_hash", "password_salt", "token_hash", "relative_image", "image_path", "file_path"):
        assert key not in encoded


@contextmanager
def temporary_task_values(env, **changes):
    allowed = {"expires_at", "analysis_status", "processing_result_json", "sha256", "school_context_json"}
    assert changes and set(changes) <= allowed
    task_id = env.task_ids["t1"]
    with sqlite3.connect(env.records.db_path) as connection:
        connection.row_factory = sqlite3.Row
        original = dict(connection.execute("SELECT * FROM video_analysis_tasks WHERE task_id=?", (task_id,)).fetchone())
        connection.execute("UPDATE video_analysis_tasks SET " + ",".join(key + "=?" for key in changes) + " WHERE task_id=?",
                           (*changes.values(), task_id))
    try:
        yield
    finally:
        with sqlite3.connect(env.records.db_path) as connection:
            connection.execute("UPDATE video_analysis_tasks SET " + ",".join(key + "=?" for key in changes) + " WHERE task_id=?",
                               (*(original[key] for key in changes), task_id))


def test_real_result_publication_exposes_current_protected_frames_without_identity_inference(env):
    current = workspace(env)
    assert current["media_available"] is True, current["summary"]
    assert current["can_edit"] is True and len(current["frames"]) >= 2
    assert current["summary"]["identity_scope"] == "single_sample_frame"
    assert current["summary"]["tracking_performed"] is False
    assert current["summary"]["global_motion_attributed_to_student"] is False
    assert current["summary"]["global_audio_attributed_to_student"] is False
    for frame in current["frames"]:
        assert frame["image_url"].startswith(API + "/frame?")
    status, headers, data = request(env, "GET", current["frames"][0]["image_url"])
    assert status == 200 and headers["content-type"].startswith("image/")
    assert data.startswith(b"\xff\xd8") or data.startswith(b"\x89PNG")
    assert_no_private_paths_or_credentials(env, current)


@pytest.mark.parametrize("suffix", ["roster", "workspace", "frame", "detect", "export"])
@pytest.mark.parametrize("identity", ["anonymous", "member", "expired"])
def test_all_identity_get_routes_reject_anonymous_members_and_expired_sessions(env, suffix, identity):
    query = urlencode({"task_id": env.task_ids["t1"], "frame_key": "s0_f0", "frame_revision": "stale"})
    token = "" if identity == "anonymous" else env.tokens["member"]
    if identity == "expired":
        session = env.records.create_account_session(env.accounts["t1"]["account_id"])
        token = session["token"]
        with sqlite3.connect(env.records.db_path) as connection:
            connection.execute("UPDATE account_sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE token_hash=?",
                               (hashlib.sha256(token.encode()).hexdigest(),))
    status, _, body = request(env, "GET", API + "/" + suffix + "?" + query, token=token)
    assert status == (403 if identity == "member" else 401), body
    assert_no_private_paths_or_credentials(env, body)


@pytest.mark.parametrize("suffix", ["students", "bindings", "bindings/revoke"])
@pytest.mark.parametrize("identity", ["anonymous", "member", "admin"])
def test_identity_writes_are_forbidden_before_payload_validation(env, suffix, identity):
    before = (count_rows(env, "demo2_identity_students"), count_rows(env, "demo2_identity_bindings"))
    status, _, body = request(env, "POST", API + "/" + suffix, {"malformed": True},
                              user=None if identity == "anonymous" else identity)
    assert status == (401 if identity == "anonymous" else 403), body
    assert (count_rows(env, "demo2_identity_students"), count_rows(env, "demo2_identity_bindings")) == before


@pytest.mark.parametrize("suffix", ["workspace", "frame", "detect", "export"])
@pytest.mark.parametrize("other_user", ["t2", "t3", "t4"])
def test_other_upload_account_cannot_read_task_even_when_school_text_is_identical(env, suffix, other_user):
    query = (frame_query(env) if suffix in {"frame", "detect"}
             else urlencode({"task_id": env.task_ids["t1"]}))
    status, _, body = request(env, "GET", API + "/" + suffix + "?" + query, user=other_user)
    # This new contract deliberately conceals task existence with 404.
    assert status == 404, body
    assert env.task_ids["t1"] not in json.dumps(body)
    assert_no_private_paths_or_credentials(env, body)


def test_admin_can_read_task_workspace_frames_and_export_but_cannot_bind_or_revoke(fresh_env):
    env = fresh_env
    current = workspace(env, user="admin")
    assert current["can_edit"] is False
    for suffix in ("frame", "export"):
        query = frame_query(env) if suffix == "frame" else urlencode({"task_id": env.task_ids["t1"]})
        status, _, _ = request(env, "GET", API + "/" + suffix + "?" + query, user="admin")
        assert status == 200
    created = save_binding(env)
    for suffix, payload in (
        ("students", {"display_name": "不应创建", "student_code": "NO", "class_name": "", "note": ""}),
        ("bindings", binding_payload(env)),
        ("bindings/revoke", {"task_id": env.task_ids["t1"], "binding_id": created["binding_id"], "reason": "不应撤销"}),
    ):
        before = (count_rows(env, "demo2_identity_students"), count_rows(env, "demo2_identity_bindings"))
        assert request(env, "POST", API + "/" + suffix, payload, user="admin")[0] == 403
        assert (count_rows(env, "demo2_identity_students"), count_rows(env, "demo2_identity_bindings")) == before
    assert workspace(env)["bindings"][0]["status"] == "confirmed"


def test_first_roster_is_empty_and_old_demo_students_never_enter_identity_roster(fresh_env):
    env = fresh_env
    env.records.ensure_students([{"student_id": "QA_LEGACY_DEMO", "display_name": "旧演示不得混入"}])
    status, _, body = request(env, "GET", API + "/roster")
    assert status == 200 and body["roster"]["students"] == []
    assert workspace(env)["students"] == []
    before = count_rows(env, "students")
    a, b = create_student(env, code="QA-A"), create_student(env, code="QA-B")
    assert a["display_name"] == b["display_name"] and a["student_id"] != b["student_id"]
    roster = request(env, "GET", API + "/roster")[2]["roster"]
    assert {s["student_id"] for s in roster["students"]} == {a["student_id"], b["student_id"]}
    assert count_rows(env, "students") == before
    assert request(env, "GET", API + "/roster", user="t2")[2]["roster"]["students"] == []


def test_duplicate_code_conflicts_but_same_name_and_separate_owner_are_allowed(fresh_env):
    env = fresh_env
    a = create_student(env, code="A")
    b = create_student(env, code="B")
    before = count_rows(env, "demo2_identity_students")
    status, _, body = request(env, "POST", API + "/students", {
        "display_name": "另一虚拟学生", "student_code": "A", "class_name": a["class_name"], "note": "",
    })
    assert status == 409 and body["error"]["code"] == "student_code_conflict"
    assert count_rows(env, "demo2_identity_students") == before
    other = create_student(env, user="t2", code="A")
    assert other["scope_key"] != a["scope_key"] and other["student_id"] != b["student_id"]
    status, _, _ = request(env, "POST", API + "/bindings", binding_payload(env, role="student", student_id=other["student_id"]))
    assert status == 404


def test_current_roster_scope_change_does_not_reassign_historical_task(fresh_env):
    env = fresh_env
    old_student = create_student(env, code="HISTORY")
    old = workspace(env)
    original_roster = request(env, "GET", API + "/roster")[2]["roster"]
    status, _, _ = request(env, "POST", "/api/v1/demo2/school/context", NEW_SCHOOL)
    assert status == 400
    assert request(env, "GET", API + "/roster")[2]["roster"] == original_roster
    assert workspace(env) == old
    # Administrator migration is simulated only in this isolated fixture database.
    assert env.records.db_path.resolve().is_relative_to(env.root.resolve())
    with sqlite3.connect(env.records.db_path) as connection:
        connection.execute(
            "UPDATE school_contexts SET city=?, district=?, school_name=? WHERE account_id=?",
            (NEW_SCHOOL["city"], NEW_SCHOOL["district"], NEW_SCHOOL["school_name"],
             old_student["owner_account_id"]),
        )
    roster = request(env, "GET", API + "/roster")[2]["roster"]
    assert roster["school_context"] == NEW_SCHOOL and roster["scope_key"] != old["scope_key"]
    assert roster["students"] == []
    new_student = create_student(env, code="HISTORY")
    historical = workspace(env)
    assert historical["scope_key"] == old["scope_key"]
    assert historical["school_context"] == old["school_context"]
    assert [s["student_id"] for s in historical["students"]] == [old_student["student_id"]]
    assert request(env, "POST", API + "/bindings",
                   binding_payload(env, role="student", student_id=new_student["student_id"]))[0] == 404
    saved = save_binding(env, role="student", student_id=old_student["student_id"])
    assert saved["scope_key"] == old["scope_key"]


@pytest.mark.parametrize("field,value", [
    ("owner_account_id", "company_admin"), ("scope_key", "forged"), ("school_context", NEW_SCHOOL),
    ("student_id", "legacy-id"), ("role", "company_admin"),
])
def test_student_creation_cannot_spoof_owner_scope_or_identity(env, field, value):
    before = count_rows(env, "demo2_identity_students")
    status, _, _ = request(env, "POST", API + "/students", {"display_name": "虚拟学生", field: value})
    assert status == 400
    assert count_rows(env, "demo2_identity_students") == before


@pytest.mark.parametrize("value", ["", "   ", None, 123, "a" * 81, "姓名\x00", "姓名\u202e"])
def test_invalid_student_name_has_no_side_effect(env, value):
    before = count_rows(env, "demo2_identity_students")
    status, _, _ = request(env, "POST", API + "/students", {"display_name": value})
    assert status == 400
    assert count_rows(env, "demo2_identity_students") == before


@pytest.mark.parametrize("box", [
    None, {}, {"x": 0, "y": 0, "width": 1},
    {"x": -0.1, "y": 0, "width": 0.2, "height": 0.2},
    {"x": 0.9, "y": 0, "width": 0.2, "height": 0.2},
    {"x": 0, "y": 0.9, "width": 0.2, "height": 0.2},
    {"x": 0, "y": 0, "width": 0, "height": 0.2},
    {"x": 0, "y": 0, "width": 0.2, "height": -0.1},
    {"x": True, "y": 0, "width": 0.2, "height": 0.2},
    {"x": "0", "y": 0, "width": 0.2, "height": 0.2},
    {"x": float("nan"), "y": 0, "width": 0.2, "height": 0.2},
    {"x": 0, "y": 0, "width": float("inf"), "height": 0.2},
    {**BOX, "student_id": "forged"},
])
def test_invalid_bbox_is_rejected_without_saving_any_confirmation(env, box):
    payload = binding_payload(env)
    payload["bbox"] = box
    before = count_rows(env, "demo2_identity_bindings")
    assert request(env, "POST", API + "/bindings", payload)[0] == 400
    assert count_rows(env, "demo2_identity_bindings") == before


@pytest.mark.parametrize("change", [
    {"owner_account_id": "company_admin"}, {"confirmed_by": "forged"},
    {"scope_key": "forged"}, {"time_sec": 900}, {"source_sha256": "0" * 64},
    {"identity_scope": "whole_video"}, {"role": "face_recognized"}, {"role": "student"},
    {"role": "teacher", "student_id": "forged"}, {"role": "unknown", "student_id": ""},
])
def test_binding_rejects_forged_authority_or_semantics(env, change):
    before = count_rows(env, "demo2_identity_bindings")
    assert request(env, "POST", API + "/bindings", {**binding_payload(env), **change})[0] == 400
    assert count_rows(env, "demo2_identity_bindings") == before


def test_single_frame_confirmation_persists_reloads_and_revokes_without_deleting_audit(fresh_env):
    env = fresh_env
    a, b = create_student(env, code="A"), create_student(env, code="B")
    saved = save_binding(env, role="student", student_id=a["student_id"])
    assert saved["identity_scope"] == "single_sample_frame" and saved["status"] == "confirmed"
    current = workspace(env)
    assert len(current["bindings"]) == 1 and current["summary"]["bound_student_count"] == 1
    assert current["bindings"][0]["frame_key"] == current["frames"][0]["frame_key"]
    assert current["frames"][1]["frame_key"] != saved["frame_key"]
    record_module = importlib.import_module(type(env.records).__module__)
    identity_module = importlib.import_module(type(env.identity).__module__)
    reopened = record_module.Demo2StudentRecordStore(env.records.db_path, env.records.upload_dir)
    reread = identity_module.Demo2IdentityStore(reopened).workspace(env.tokens["t1"], env.task_ids["t1"])
    assert reread["bindings"] == current["bindings"]
    payload = {"task_id": env.task_ids["t1"], "binding_id": saved["binding_id"], "reason": "QA错绑撤销"}
    assert request(env, "POST", API + "/bindings/revoke", payload)[0] == 200
    assert request(env, "POST", API + "/bindings/revoke", payload)[0] == 200
    current = workspace(env)
    assert current["bindings"][0]["status"] == "revoked"
    assert current["summary"]["bound_student_count"] == 0
    second = save_binding(env, role="student", student_id=b["student_id"])
    assert second["student_id"] != saved["student_id"]
    with sqlite3.connect(env.records.db_path) as connection:
        actions = [r[0] for r in connection.execute("SELECT action FROM audit_logs WHERE object_id=?", (saved["binding_id"],))]
        assert actions.count("identity_binding_confirmed") == 1
        assert actions.count("identity_binding_revoked") == 1
        assert connection.execute("SELECT COUNT(*) FROM demo2_identity_bindings WHERE binding_id=?", (saved["binding_id"],)).fetchone()[0] == 1
    exported = request(env, "GET", API + "/export?" + urlencode({"task_id": env.task_ids["t1"]}))[2]
    assert saved["binding_id"] in json.dumps(exported) and second["binding_id"] in json.dumps(exported)
    assert_no_private_paths_or_credentials(env, exported)


@pytest.mark.parametrize("role", ["unknown", "teacher"])
def test_unknown_and_teacher_do_not_require_or_assign_a_student(fresh_env, role):
    env = fresh_env
    saved = save_binding(env, role=role)
    assert saved["role"] == role and saved["student_id"] is None
    current = workspace(env)
    assert current["summary"]["bound_student_count"] == 0
    assert current["summary"]["tracking_performed"] is False


def test_new_revision_marks_old_confirmation_stale_and_rejects_old_frame_requests(fresh_env):
    env = fresh_env
    a = create_student(env)
    payload = binding_payload(env, role="student", student_id=a["student_id"])
    saved = save_binding(env, role="student", student_id=a["student_id"])
    old_query = frame_query(env)
    env.refresh_revision(env.task_ids["t1"])
    current = workspace(env)
    assert current["frame_revision"] != payload["frame_revision"]
    old = next(b for b in current["bindings"] if b["binding_id"] == saved["binding_id"])
    assert old["stale"] is True and old["current_revision"] is False
    assert current["summary"]["current_confirmed_count"] == 0
    before = count_rows(env, "demo2_identity_bindings")
    assert request(env, "POST", API + "/bindings", payload)[0] == 409
    for suffix in ("frame", "detect"):
        assert request(env, "GET", API + "/" + suffix + "?" + old_query)[0] == 409
    assert count_rows(env, "demo2_identity_bindings") == before


def test_expired_media_disables_frames_and_confirmation_but_keeps_structured_history(fresh_env):
    env = fresh_env
    saved = save_binding(env)
    payload = binding_payload(env)
    query = frame_query(env)
    with temporary_task_values(env, expires_at="2000-01-01T00:00:00+00:00"):
        current = workspace(env)
        assert current["media_available"] is False and current["can_edit"] is False
        assert all(not f["image_url"] for f in current["frames"])
        assert saved["binding_id"] in json.dumps(current["bindings"])
        for suffix in ("frame", "detect"):
            assert request(env, "GET", API + "/" + suffix + "?" + query)[0] == 410
        assert request(env, "POST", API + "/bindings", payload)[0] == 410
        assert request(env, "GET", API + "/export?" + urlencode({"task_id": env.task_ids["t1"]}))[0] == 200


def test_foreign_task_binding_and_revoke_do_not_change_owners_confirmation(fresh_env):
    env = fresh_env
    saved = save_binding(env)
    assert request(env, "POST", API + "/bindings", binding_payload(env), user="t2")[0] == 404
    assert request(env, "POST", API + "/bindings/revoke", {
        "task_id": env.task_ids["t1"], "binding_id": saved["binding_id"], "reason": "越权不得生效",
    }, user="t2")[0] == 404
    assert workspace(env)["bindings"][0]["status"] == "confirmed"


def test_simultaneous_duplicate_student_confirmation_is_atomic(fresh_env):
    env = fresh_env
    student = create_student(env)
    payload = binding_payload(env, role="student", student_id=student["student_id"])
    barrier = threading.Barrier(4)

    def submit(_):
        barrier.wait()
        return request(env, "POST", API + "/bindings", payload)[0]

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sorted(pool.map(submit, range(4))) == [200, 409, 409, 409]
    assert count_rows(env, "demo2_identity_bindings") == 1
    assert workspace(env)["summary"]["bound_student_count"] == 1


def test_overlapping_students_need_revocation_before_reassignment(fresh_env):
    env = fresh_env
    a, b = create_student(env), create_student(env)
    save_binding(env, role="student", student_id=a["student_id"])
    status, _, body = request(env, "POST", API + "/bindings", binding_payload(env, role="student", student_id=b["student_id"]))
    assert status == 409 and body["error"]["code"] == "indistinguishable_student_binding"
    assert request(env, "POST", API + "/bindings",
                   binding_payload(env, role="student", student_id=b["student_id"], box=OTHER_BOX))[0] == 200


def test_detector_candidates_are_positions_only_and_do_not_write_bindings(env):
    before = count_rows(env, "demo2_identity_bindings")
    status, _, body = request(env, "GET", API + "/detect?" + frame_query(env))
    assert status == 200 and body.get("ok") is True, body
    detection = body["detection"]
    assert isinstance(detection["available"], bool) and isinstance(detection["faces"], list)
    for face in detection["faces"]:
        assert {"candidate_id", "bbox", "score"} <= set(face)
        assert not ({"student_id", "display_name", "matched_identity", "embedding"} & set(face))
        box = face["bbox"]
        assert 0 <= box["x"] < 1 and 0 <= box["y"] < 1
        assert 0 < box["width"] <= 1 - box["x"] and 0 < box["height"] <= 1 - box["y"]
    assert count_rows(env, "demo2_identity_bindings") == before
    assert_no_private_paths_or_credentials(env, body)


@pytest.mark.parametrize("path", ["../../outside.jpg", "D:/private/student.jpg", "//server/share/x.jpg"])
def test_untrusted_frame_manifest_cannot_escape_task_directory(env, path):
    with sqlite3.connect(env.records.db_path) as connection:
        raw = json.loads(connection.execute("SELECT processing_result_json FROM video_analysis_tasks WHERE task_id=?",
                                           (env.task_ids["t1"],)).fetchone()[0])
    raw["segments"][0]["visual"]["samples"][0]["image_path"] = path
    with temporary_task_values(env, processing_result_json=json.dumps(raw)):
        current = workspace(env)
        assert current["media_available"] is False and current["can_edit"] is False
        assert current["summary"]["media_unavailable_reason"] == "invalid_frame_manifest"
        query = urlencode({"task_id": env.task_ids["t1"], "frame_key": "s0_f0", "frame_revision": current["frame_revision"]})
        status, _, body = request(env, "GET", API + "/frame?" + query)
        assert status == 409 and path not in json.dumps(body)


def test_source_hash_mismatch_never_reuses_frames_or_student_confirmation(env):
    with temporary_task_values(env, sha256="0" * 64):
        current = workspace(env)
        assert current["media_available"] is False and current["can_edit"] is False
        assert current["summary"]["media_unavailable_reason"] == "source_hash_mismatch"
        query = urlencode({"task_id": env.task_ids["t1"], "frame_key": "s0_f0", "frame_revision": current["frame_revision"]})
        assert request(env, "GET", API + "/frame?" + query)[0] == 409


def test_fixture_closes_listener_and_does_not_patch_canonical_server(tmp_path):
    from scripts.qa_demo2_identity_20260910 import isolated_identity_server
    from src.rehab_affect import scenario_lab_server as canonical

    names = ("get_demo2_student_store", "load_seewo_demo2", "load_seewo_student_demo",
             "_render_demo2_portal_page", "importlib")
    before = {name: getattr(canonical, name) for name in names}
    with isolated_identity_server(tmp_path / "close") as isolated:
        assert isolated.server is not canonical
        assert workspace(isolated)["media_available"] is True
        assert all(getattr(canonical, name) is value for name, value in before.items())
        port = isolated.port
    assert all(getattr(canonical, name) is value for name, value in before.items())
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=0.5)


def test_legacy_task_school_requires_owner_confirmation_and_cannot_migrate_twice(fresh_env):
    """One real-HTTP recovery flow; no production school attribution is inferred."""
    env = fresh_env
    task_id = env.task_ids["t1"]
    empty_school = {"city": "", "district": "", "school_name": ""}
    endpoint = API + "/task-school"

    def persisted_state():
        with sqlite3.connect(env.records.db_path) as connection:
            raw = connection.execute("SELECT school_context_json FROM video_analysis_tasks WHERE task_id=?",
                                     (task_id,)).fetchone()[0]
            audits = connection.execute(
                "SELECT actor, detail_json FROM audit_logs WHERE action='identity_task_school_confirmed' AND object_id=?",
                (task_id,),
            ).fetchall()
        return json.loads(raw), audits

    with temporary_task_values(env, school_context_json=json.dumps(empty_school)):
        initial = workspace(env)
        assert initial["bindings"] == []
        assert initial["school_context"] == empty_school
        assert initial["needs_school_confirmation"] is True
        assert initial["can_confirm_school"] is True and initial["can_edit"] is False
        status, _, body = request(env, "GET", API + "/roster")
        assert status == 200
        roster = body["roster"]
        assert all(roster["school_context"][key] for key in empty_school)
        assert persisted_state() == (empty_school, []), "Reading must never silently attribute a legacy task"
        payload = {"task_id": task_id, "expected_scope_key": roster["scope_key"], "confirmed": True}

        assert workspace(env, user="admin")["can_confirm_school"] is False
        for user, expected in [("admin", 403), ("t2", 404), ("t3", 404), ("t4", 404)]:
            assert request(env, "POST", endpoint, payload, user=user)[0] == expected
            assert persisted_state() == (empty_school, [])
        for unconfirmed in ({**payload, "confirmed": False}, {k: v for k, v in payload.items() if k != "confirmed"}):
            assert request(env, "POST", endpoint, unconfirmed)[0] == 400
            assert persisted_state() == (empty_school, [])

        status, _, body = request(env, "POST", endpoint, payload)
        assert status == 200 and body["ok"] is True, body
        repaired = body["workspace"]
        assert repaired["school_context"] == roster["school_context"]
        assert repaired["scope_key"] == roster["scope_key"] and repaired["can_edit"] is True
        assert repaired["needs_school_confirmation"] is False and repaired["can_confirm_school"] is False
        assert repaired["bindings"] == [] and repaired["frame_revision"] == initial["frame_revision"]
        snapshot, audits = persisted_state()
        assert snapshot == roster["school_context"] and len(audits) == 1
        assert audits[0][0] == env.accounts["t1"]["username"]
        detail = json.loads(audits[0][1])
        assert detail["old_scope_key"] == "" and detail["new_scope_key"] == roster["scope_key"]
        assert detail["confirmed_by"] == env.accounts["t1"]["username"]
        assert workspace(env)["school_context"] == snapshot

        # An explicit second click, even after the account's school changes,
        # must not turn this repair route into a school-migration operation.
        assert request(env, "POST", endpoint, payload)[0] == 409
        assert request(env, "POST", "/api/v1/demo2/school/context", NEW_SCHOOL)[0] == 200
        new_roster = request(env, "GET", API + "/roster")[2]["roster"]
        status, _, body = request(env, "POST", endpoint, {**payload, "expected_scope_key": new_roster["scope_key"]})
        assert status == 409 and body["error"]["code"] == "task_school_not_empty"
        assert persisted_state() == (snapshot, audits)
