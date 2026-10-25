"""Manual identity and company-channel acceptance using disposable real stores."""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

import pytest

from scripts.qa_demo2_teacher_flow_20260911 import (
    API, BOX, CHANNELS, PARTIAL_BOX, binding_payload, channel_payload, channels,
    enable_tracking_stub, extend_synthetic_manifest, history_snapshot, isolated_gateway,
    request, save_manual, teacher_flow_server, upload_payload, workspace,
)


@pytest.fixture
def env(tmp_path):
    with teacher_flow_server(tmp_path / "tf") as fixture:
        yield fixture


def assert_saved_student(env, binding, expected_box):
    current = workspace(env)
    saved = next(item for item in current["bindings"] if item["binding_id"] == binding["binding_id"])
    assert saved["student_id"] == binding["student_id"]
    assert saved["bbox"] == expected_box
    assert saved["status"] == "confirmed" and saved["current_revision"] is True
    expected = next(item for item in env.students["t1"] if item["student_id"] == saved["student_id"])
    student = next(item for item in current["students"] if item["student_id"] == saved["student_id"])
    assert student["display_name"] == expected["display_name"]
    assert student["student_code"] == expected["student_code"]
    return saved


def test_manual_save_without_available_detector_survives_refresh_and_reopen(env):
    current = workspace(env)
    query = {"task_id": env.task_ids["t1"], "frame_key": current["frames"][0]["frame_key"],
             "frame_revision": current["frame_revision"]}
    status, _, detected = request(env, API + "/detect?" + urlencode(query))
    assert status == 200 and detected["detection"]["available"] is False
    assert detected["detection"]["faces"] == [] and len(env.detect_calls) == 1
    binding = save_manual(env)
    assert_saved_student(env, binding, BOX)
    assert len(env.detect_calls) == 1, "Saving a manual ROI must not run the detector"
    env.reopen()
    assert_saved_student(env, binding, BOX)
    assert len(env.detect_calls) == 1


@pytest.mark.parametrize("confirm", [None, False])
def test_manual_partial_overlap_is_rejected_without_explicit_confirmation(env, confirm):
    save_manual(env)
    before = history_snapshot(env)
    extra = {} if confirm is None else {"overlap_confirmed": confirm}
    payload = binding_payload(env, student=1, box=PARTIAL_BOX, **extra)
    status, _, body = request(env, API + "/bindings", method="POST", payload=payload)
    assert status == 409 and body["error"]["code"] == "overlapping_student_binding"
    assert history_snapshot(env) == before


def test_manual_explicit_partial_overlap_persists_two_same_name_students_and_audit(env):
    first = save_manual(env)
    second = save_manual(env, student=1, box=PARTIAL_BOX, overlap_confirmed=True)
    assert first["student_id"] != second["student_id"]
    assert env.students["t1"][0]["display_name"] == env.students["t1"][1]["display_name"]
    assert second["overlap_confirmed"] is True
    with env.records._connect() as connection:
        stored = connection.execute("SELECT overlap_confirmed FROM demo2_identity_bindings WHERE binding_id=?",
                                    (second["binding_id"],)).fetchone()
        assert stored[0] == 1
        audit = connection.execute("SELECT detail_json FROM audit_logs WHERE object_id=?",
                                   (second["binding_id"],)).fetchall()
        assert any(json.loads(row[0]).get("overlap_confirmed") is True for row in audit)
    before = history_snapshot(env)
    env.reopen()
    assert history_snapshot(env) == before, "Idempotent initialization must not rewrite historical rows"
    assert_saved_student(env, first, BOX)
    assert_saved_student(env, second, PARTIAL_BOX)


def test_manual_indistinguishable_box_still_rejects_explicit_confirmation(env):
    save_manual(env)
    before = history_snapshot(env)
    status, _, body = request(env, API + "/bindings", method="POST",
                              payload=binding_payload(env, student=1, overlap_confirmed=True))
    assert status == 409 and body["error"]["code"] == "indistinguishable_student_binding"
    assert history_snapshot(env) == before


def test_manual_duplicate_student_cannot_bypass_with_explicit_confirmation(env):
    save_manual(env)
    before = history_snapshot(env)
    other_box = {**BOX, "x": .60}
    status, _, body = request(env, API + "/bindings", method="POST",
                              payload=binding_payload(env, box=other_box, overlap_confirmed=True))
    assert status == 409 and body["error"]["code"] == "duplicate_student_binding"
    assert history_snapshot(env) == before


@pytest.mark.parametrize("value", [1, "true", None, [], {}])
def test_manual_overlap_confirmation_requires_a_real_boolean(env, value):
    before = history_snapshot(env)
    status, _, _ = request(env, API + "/bindings", method="POST",
                           payload=binding_payload(env, overlap_confirmed=value))
    assert status == 400
    assert history_snapshot(env) == before


@pytest.mark.parametrize("user,status", [(None, 401), ("admin", 403), ("member", 403), ("t2", 404)])
def test_manual_save_keeps_http_ownership_guards(env, user, status):
    before = history_snapshot(env)
    actual, _, _ = request(env, API + "/bindings", method="POST", user=user, payload=binding_payload(env))
    assert actual == status
    assert history_snapshot(env) == before


@pytest.mark.parametrize("method", ["GET", "POST"])
@pytest.mark.parametrize("user,status", [(None, 401), ("t1", 403), ("t2", 403), ("member", 403)])
def test_channel_http_roles_rejected_before_configuration_changes(env, method, user, status):
    before = channels(env)
    payload = channel_payload(env, channel_name="Unauthorized fixture edit") if method == "POST" else None
    actual, _, _ = request(env, CHANNELS, method=method, user=user, payload=payload)
    assert actual == status
    assert channels(env) == before


def test_channel_admin_update_reopen_pause_resume_and_historical_identity(env):
    saved = save_manual(env)
    history = history_snapshot(env)
    payload = channel_payload(env, channel_name="Synthetic QA channel", owner_label="Synthetic QA owner",
                              status="paused", course_upload_limit=3)
    status, _, body = request(env, CHANNELS, method="POST", user="admin", payload=payload)
    assert status == 200 and body["ok"] is True
    assert body["channel"]["version"] != payload["expected_version"]
    assert history_snapshot(env) == history
    env.reopen()
    updated = next(item for item in channels(env) if item["channel_id"] == "channel_1")
    for key in ("channel_name", "owner_label", "status", "course_upload_limit"):
        assert updated[key] == payload[key]
    assert history_snapshot(env) == history
    assert_saved_student(env, saved, BOX)
    rejected, _, body = request(env, "/api/v1/demo2/upload/tasks", method="POST", payload=upload_payload())
    assert rejected in {400, 409} and body["ok"] is False
    assert history_snapshot(env) == history, "Paused channels must not reserve a new task"
    resume = channel_payload(env, status="active")
    assert request(env, CHANNELS, method="POST", user="admin", payload=resume)[0] == 200
    assert history_snapshot(env) == history
    status, _, body = request(env, "/api/v1/demo2/upload/tasks", method="POST", payload=upload_payload())
    assert status == 200 and body["ok"] is True
    assert len(history_snapshot(env)["video_analysis_tasks"]) == len(history["video_analysis_tasks"]) + 1
    assert_saved_student(env, saved, BOX)


def test_channel_stale_version_cannot_overwrite_another_admin_update(env):
    payload = channel_payload(env, channel_name="First synthetic admin change")
    status, _, first = request(env, CHANNELS, method="POST", user="admin", payload=payload)
    assert status == 200
    status, _, conflict = request(env, CHANNELS, method="POST", user="admin",
                                  payload={**payload, "channel_name": "Stale synthetic overwrite"})
    assert status == 409 and conflict["error"]["code"] == "channel_version_conflict"
    current = next(item for item in channels(env) if item["channel_id"] == "channel_1")
    assert current["channel_name"] == first["channel"]["channel_name"]
    assert current["version"] == first["channel"]["version"]


@pytest.mark.parametrize("limit", [2, 6, True, 3.5, "3"])
def test_channel_course_limit_is_strict_integer_three_to_five(env, limit):
    before = channels(env)
    status, _, _ = request(env, CHANNELS, method="POST", user="admin",
                           payload=channel_payload(env, course_upload_limit=limit))
    assert status == 400
    assert channels(env) == before


def test_channel_quota_changes_really_limit_reservations_without_deleting_history(env):
    assert request(env, CHANNELS, method="POST", user="admin",
                   payload=channel_payload(env, course_upload_limit=3))[0] == 200
    payload = upload_payload(course_id="qa-three-slot-course")
    for _ in range(3):
        assert request(env, "/api/v1/demo2/upload/tasks", method="POST", payload=payload)[0] == 200
    before = history_snapshot(env)
    status, _, body = request(env, "/api/v1/demo2/upload/tasks", method="POST", payload=payload)
    assert status == 409 and body["error"]["code"] == "quota_exceeded"
    assert history_snapshot(env) == before
    assert request(env, CHANNELS, method="POST", user="admin",
                   payload=channel_payload(env, course_upload_limit=5))[0] == 200
    assert request(env, "/api/v1/demo2/upload/tasks", method="POST", payload=payload)[0] == 200
    before = history_snapshot(env)
    status, _, body = request(env, CHANNELS, method="POST", user="admin",
                              payload=channel_payload(env, course_upload_limit=3))
    assert status == 409 and body["error"]["code"] == "channel_quota_in_use"
    assert history_snapshot(env) == before


def test_channel_gateway_needs_invite_admin_session_and_same_origin_write(env):
    payload = channel_payload(env, channel_name="Gateway-approved synthetic channel")
    with isolated_gateway(env) as gateway:
        assert request(env, CHANNELS, port=gateway.port, user="admin")[0] in {401, 403}
        status, headers, _ = request(env, "/__manager/authorize", method="POST", user=None, port=gateway.port,
                                     payload={"secret": gateway.invite}, headers={"Origin": gateway.origin})
        assert status == 303
        invite_cookie = headers["set-cookie"].split(";", 1)[0]
        assert request(env, CHANNELS, port=gateway.port, user=None, headers={"Cookie": invite_cookie})[0] == 401
        admin_cookie = invite_cookie + "; rehab_demo2_session=" + env.tokens["admin"]
        teacher_cookie = invite_cookie + "; rehab_demo2_session=" + env.tokens["t1"]
        assert request(env, CHANNELS, port=gateway.port, user=None, headers={"Cookie": teacher_cookie})[0] == 403
        status, headers, _ = request(env, CHANNELS, port=gateway.port, user=None, headers={"Cookie": admin_cookie})
        assert status == 200 and "no-store" in headers["cache-control"]
        before = channels(env)
        for origin in (None, "https://other.invalid"):
            outgoing = {"Cookie": admin_cookie, **({"Origin": origin} if origin else {})}
            assert request(env, CHANNELS, method="POST", payload=payload, port=gateway.port,
                           user=None, headers=outgoing)[0] == 403
            assert channels(env) == before
        status, _, body = request(env, CHANNELS, method="POST", payload=payload, port=gateway.port,
                                  user=None, headers={"Cookie": admin_cookie, "Origin": gateway.origin})
        assert status == 200 and body["channel"]["channel_name"] == payload["channel_name"]


@pytest.fixture
def tracking(env):
    enable_tracking_stub(env)
    binding = save_manual(env)
    env.track_payload = {"task_id": env.task_ids["t1"], "binding_id": binding["binding_id"],
                         "frame_revision": binding["frame_revision"]}
    return env


def track(env, **options):
    return request(env, API + "/track", method="POST", payload=env.track_payload, **options)


def test_tracking_http_returns_saved_name_and_short_suggestions_without_writes(env):
    extend_synthetic_manifest(env, count=9)
    enable_tracking_stub(env)
    saved = save_manual(env)
    env.track_payload = {"task_id": env.task_ids["t1"], "binding_id": saved["binding_id"],
                         "frame_revision": saved["frame_revision"]}
    before = history_snapshot(env)
    status, headers, body = track(env)
    assert status == 200 and body["ok"] is True
    assert "no-store" in headers["cache-control"]
    result = body["track"]
    assert set(result) == {"binding_id", "student_id", "display_name", "frame_revision", "scope", "window_sec",
                           "algorithm", "status", "points", "reason", "automatic_identity"}
    assert isinstance(result["algorithm"], str) and result["algorithm"]
    assert result["status"] == "completed"
    assert result["student_id"] == saved["student_id"]
    assert result["display_name"] == env.students["t1"][0]["display_name"]
    assert result["binding_id"] == saved["binding_id"]
    assert result["frame_revision"] == saved["frame_revision"]
    assert result["scope"] == "short_window_suggestion" and result["window_sec"] == 5
    assert result["automatic_identity"] is False
    assert len(result["points"]) == 6
    assert [point["time_sec"] for point in result["points"]] == list(range(6))
    assert result["points"][0]["status"] == "seed" and result["points"][0]["bbox"] == BOX
    assert all(point["status"] == "suggested" for point in result["points"][1:])
    assert all(set(point) == {"frame_key", "time_sec", "bbox", "status", "quality", "reason"}
               for point in result["points"])
    encoded = json.dumps(body)
    assert str(env.root) not in encoded and '"path"' not in encoded
    assert not any(token in encoded for token in env.tokens.values())
    assert history_snapshot(env) == before, "Suggestions must not create or update saved identity bindings"
    assert len(env.track_calls) == 1 and env.detect_calls == []


@pytest.mark.parametrize("user,status", [(None, 401), ("admin", 403), ("member", 403), ("t2", 404)])
def test_tracking_http_role_and_task_guards_run_before_engine(tracking, user, status):
    before = history_snapshot(tracking)
    assert track(tracking, user=user)[0] == status
    assert tracking.track_calls == [] and history_snapshot(tracking) == before


@pytest.mark.parametrize("endpoint", [CHANNELS, API + "/track"])
def test_new_post_routes_require_json_content_type_before_execution(tracking, endpoint):
    payload = channel_payload(tracking) if endpoint == CHANNELS else tracking.track_payload
    user = "admin" if endpoint == CHANNELS else "t1"
    before = history_snapshot(tracking)
    status, _, _ = request(tracking, endpoint, method="POST", payload=payload, user=user,
                           headers={"Content-Type": "text/plain"})
    assert status == 415
    assert tracking.track_calls == [] and history_snapshot(tracking) == before


@pytest.mark.parametrize("change,status", [("revoked", 409), ("expired", 410), ("revision", 409), ("owner", 404)])
@pytest.mark.parametrize("phase", ["before", "during"])
def test_tracking_rechecks_seed_authorization_and_revision_around_engine(tracking, change, status, phase):
    env = tracking

    def mutate():
        if change == "revoked":
            env.identity.revoke_binding(env.tokens["t1"], {"task_id": env.task_ids["t1"],
                "binding_id": env.track_payload["binding_id"], "reason": "Synthetic QA revocation"})
        else:
            with env.records._connect() as connection:
                if change == "expired":
                    connection.execute("UPDATE video_analysis_tasks SET expires_at='2000-01-01T00:00:00+00:00' "
                                       "WHERE task_id=?", (env.task_ids["t1"],))
                elif change == "revision":
                    connection.execute("UPDATE video_analysis_tasks SET processing_result_json=processing_result_json || ' ' "
                                       "WHERE task_id=?", (env.task_ids["t1"],))
                else:
                    connection.execute("UPDATE video_analysis_tasks SET account_id=? WHERE task_id=?",
                                       (env.accounts["t2"]["account_id"], env.task_ids["t1"]))

    if phase == "before":
        mutate()
    else:
        env.on_track = mutate
    actual, _, body = track(env)
    assert actual == status and body["ok"] is False
    assert "track" not in body
    assert len(env.track_calls) == (0 if phase == "before" else 1)
    assert len(history_snapshot(env)["demo2_identity_bindings"]) == 1


def test_tracking_source_replacement_during_engine_is_not_returned(tracking):
    env = tracking
    seed = env.identity.tracking_seed(env.tokens["t1"], env.track_payload)
    target = seed["frames"][-1]["path"]
    replacement = target.with_name("r.jpg")
    replacement.write_bytes(seed["frames"][0]["path"].read_bytes())
    env.on_track = lambda: replacement.replace(target)
    before = history_snapshot(env)
    status, _, body = track(env)
    assert status == 409 and body["error"]["code"] == "tracking_source_changed"
    assert "track" not in body and len(env.track_calls) == 1
    assert history_snapshot(env) == before


def test_tracking_rate_limit_preserves_two_seconds_and_twelve_per_minute(tracking):
    env = tracking
    assert track(env)[0] == 200
    status, _, body = track(env)
    assert status == 429 and body["error"]["code"] == "tracking_rate_limited"
    assert len(env.track_calls) == 1
    for _ in range(11):
        env.clock.now += 2.21
        assert track(env)[0] == 200
    env.clock.now += 2.21
    assert track(env)[0] == 429 and len(env.track_calls) == 12
    env.clock.now += 60
    assert track(env)[0] == 200 and len(env.track_calls) == 13


def test_tracking_global_concurrency_slot_is_released(tracking):
    env = tracking
    status, _, body = request(env, API + "/workspace?" + urlencode({"task_id": env.task_ids["t2"]}), user="t2")
    assert status == 200
    current = body["workspace"]
    payload = {"task_id": env.task_ids["t2"], "frame_key": current["frames"][0]["frame_key"],
               "frame_revision": current["frame_revision"], "role": "student", "bbox": BOX,
               "student_id": env.students["t2"][0]["student_id"]}
    status, _, body = request(env, API + "/bindings", method="POST", payload=payload, user="t2")
    assert status == 200
    other = {"task_id": env.task_ids["t2"], "binding_id": body["binding"]["binding_id"],
             "frame_revision": current["frame_revision"]}
    entered, release = threading.Event(), threading.Event()

    def blocking_engine():
        entered.set()
        assert release.wait(5)

    env.on_track = blocking_engine
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(track, env)
        try:
            assert entered.wait(3)
            status, _, body = request(env, API + "/track", method="POST", payload=other, user="t2")
            assert status == 429 and body["error"]["code"] == "tracking_busy"
            assert len(env.track_calls) == 1
        finally:
            release.set()
        assert future.result(timeout=5)[0] == 200
    env.on_track = None
    env.clock.now += 2.21
    assert request(env, API + "/track", method="POST", payload=other, user="t2")[0] == 200


def test_tracking_gateway_enforces_same_origin_without_creating_bindings(tracking):
    env = tracking
    before = history_snapshot(env)
    with isolated_gateway(env) as gateway:
        status, headers, _ = request(env, "/__manager/authorize", method="POST", user=None, port=gateway.port,
                                     payload={"secret": gateway.invite}, headers={"Origin": gateway.origin})
        assert status == 303
        cookie = headers["set-cookie"].split(";", 1)[0] + "; rehab_demo2_session=" + env.tokens["t1"]
        for origin in (None, "https://other.invalid"):
            status, _, _ = track(env, port=gateway.port, user=None,
                                 headers={"Cookie": cookie, **({"Origin": origin} if origin else {})})
            assert status == 403 and env.track_calls == []
        status, headers, body = track(env, port=gateway.port, user=None,
                                      headers={"Cookie": cookie, "Origin": gateway.origin})
        assert status == 200 and body["track"]["automatic_identity"] is False
        assert "no-store" in headers["cache-control"]
    assert history_snapshot(env) == before


@pytest.mark.parametrize("occluded", [False, True], ids=["small-translation", "occluded-stop"])
def test_real_tracking_engine_through_http_preserves_manual_identity_and_source(env, occluded):
    import cv2
    import numpy as np

    extend_synthetic_manifest(env, count=6)
    current = workspace(env)
    texture = np.random.default_rng(20260911).integers(25, 230, (45, 40), dtype=np.uint8)
    texture = cv2.resize(texture, (160, 180), interpolation=cv2.INTER_NEAREST)
    sources = []
    for index, frame in enumerate(current["frames"]):
        path = env.identity.frame_file(env.tokens["t1"], env.task_ids["t1"], frame["frame_key"],
                                       current["frame_revision"])[0]
        assert path.resolve().is_relative_to(env.root.resolve())
        picture = np.full((360, 640), 155, dtype=np.uint8)
        if index == 0 or not occluded:
            x, y = 64 + 3 * index, 72 + index
            picture[y:y + 180, x:x + 160] = texture
        success, encoded = cv2.imencode(".jpg", picture, [cv2.IMWRITE_JPEG_QUALITY, 95])
        assert success
        path.write_bytes(encoded.tobytes())
        sources.append((path, path.read_bytes(), path.stat()))

    saved = save_manual(env)
    env.track_payload = {"task_id": env.task_ids["t1"], "binding_id": saved["binding_id"],
                         "frame_revision": saved["frame_revision"]}
    before = history_snapshot(env)
    assert env.tracking_stub is None, "This acceptance case must execute the real worker process"
    status, headers, body = track(env)
    assert status == 200 and body["ok"] is True, body
    result = body["track"]
    assert result["algorithm"] == "opencv_lk" and result["automatic_identity"] is False
    assert result["binding_id"] == saved["binding_id"] and result["student_id"] == saved["student_id"]
    assert result["display_name"] == env.students["t1"][0]["display_name"]
    assert result["scope"] == "short_window_suggestion" and result["window_sec"] == 5
    assert result["points"][0]["status"] == "seed" and result["points"][0]["bbox"] == BOX
    if occluded:
        assert result["status"] == "lost" and len(result["points"]) == 2, result
        assert result["points"][-1]["status"] == "lost"
        assert result["points"][-1]["bbox"] is None and result["points"][-1]["quality"] is None
    else:
        assert result["status"] == "completed" and len(result["points"]) == 6, result
        for index, point in enumerate(result["points"][1:], 1):
            assert point["status"] == "suggested" and 0 <= point["quality"] <= 1
            assert point["bbox"]["x"] == pytest.approx(BOX["x"] + 3 * index / 640, abs=.004)
            assert point["bbox"]["y"] == pytest.approx(BOX["y"] + index / 360, abs=.004)
            assert point["bbox"]["width"] == BOX["width"] and point["bbox"]["height"] == BOX["height"]
    assert "no-store" in headers["cache-control"]
    assert history_snapshot(env) == before and env.detect_calls == []
    for path, picture, stamp in sources:
        assert path.read_bytes() == picture
        assert (path.stat().st_mtime_ns, path.stat().st_ino) == (stamp.st_mtime_ns, stamp.st_ino)
