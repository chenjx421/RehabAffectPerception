"""Student-only person screening: teacher / blank exclusion, overrides, avatars, logs.

All inputs are synthetic (drawn shapes or OpenCV cartoon faces); no real people.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import pytest

from rehab_affect import demo2_person_filter as pf
from rehab_affect import demo2_student_tracking as tracking

ROOT = Path(__file__).resolve().parents[1]


def _features(width, cy, *, frames=27, attempts=27, score=.9, x_range=.01, presence=.86, sharp=300., px=None):
    return {"face_frames": frames, "detection_attempts": attempts, "face_ratio": frames / attempts,
            "mean_score": score, "median_face_width": width, "median_face_height": width * 1.2,
            "median_face_px": px if px is not None else width * 768, "median_cx": .5, "median_cy": cy,
            "x_range": x_range, "presence_ratio": presence, "best_sharpness": sharp}


def test_rules_exclude_large_standing_walker_and_blank_but_not_moving_student():
    features = [
        _features(.135, .37, x_range=.14),                 # adult: large, high, walking
        _features(.08, .57),
        _features(.08, .57, x_range=.2),                   # lively student: moves but is seated/small
        _features(.08, .575),
        _features(.07, .6, frames=1),                      # blank: almost never a face
        _features(.02, .6, px=15),                         # tiny face
        _features(.08, .58, sharp=3.),                     # never sharp
        _features(.08, .58, score=.5),                     # low confidence
    ]
    result = pf.classify_candidates(features, pf.person_filter_config())
    assert [r["auto_status"] for r in result] == [
        "teacher", "student", "student", "student", "blank", "blank", "blank", "blank"]
    assert {"large_face", "standing_height", "wide_movement"} <= set(result[0]["reasons"])
    assert result[0]["teacher_score"] >= .55
    assert result[2]["teacher_score"] < .55
    assert "few_face_frames" in result[4]["reasons"]
    assert "small_face" in result[5]["reasons"]
    assert result[6]["reasons"] == ["blurry_face"]
    assert result[7]["reasons"] == ["low_confidence"]


def test_single_valid_candidate_is_never_called_teacher():
    result = pf.classify_candidates([_features(.2, .3, x_range=.3)])
    assert result[0]["auto_status"] == "student"


def test_config_reads_bounded_environment_overrides(monkeypatch):
    monkeypatch.setenv("REHAB_DEMO2_PERSON_FILTER_MIN_FACE_FRAMES", "5")
    monkeypatch.setenv("REHAB_DEMO2_PERSON_FILTER_TEACHER_THRESHOLD", "abc")
    monkeypatch.setenv("REHAB_DEMO2_PERSON_FILTER_AVATAR_SIDE", "64")
    config = pf.person_filter_config()
    assert config["min_face_frames"] == 5
    assert config["teacher_threshold"] == .55
    assert config["avatar_side"] == 192


def _person(index, x, status, reasons=()):
    return {"person_id": f"person_{index + 1:02d}", "candidate_index": index, "display_name": f"人物 {index + 1}",
            "anchor_bbox": {"x": x, "y": .5, "width": .08, "height": .1},
            "track_points": [[2.0, x, .5, .08, .1]],
            "person_filter": {"auto_status": status, "reasons": list(reasons), "status": status}}


def _analysis():
    return {"available": True, "persons": [
        _person(0, .05, "teacher", ["large_face"]), _person(1, .3, "student"), _person(2, .5, "student"),
        _person(3, .7, "student"), _person(4, .9, "blank", ["few_face_frames"])]}


def test_presentation_renumbers_students_and_applies_overrides_idempotently():
    view = pf.apply_person_filter(_analysis())
    assert [p["display_name"] for p in view["persons"]] == ["学生 1", "学生 2", "学生 3"]
    assert [p["display_name"] for p in view["excluded_persons"]] == ["疑似老师 1", "无效人选 1"]
    summary = view["person_filter_summary"]
    assert (summary["student_count"], summary["excluded_teacher"], summary["excluded_blank"]) == (3, 1, 1)
    assert "已自动排除疑似老师 1 人、无效人选 1 个" in summary["notice"]
    assert "需教师复核" in summary["boundary"] and "不代表识别准确性已验证" in summary["boundary"]
    changed = pf.apply_person_filter(view, {"person_01": "student", "person_03": "teacher"})
    assert [p["person_id"] for p in changed["persons"]] == ["person_01", "person_02", "person_04"]
    assert changed["persons"][0]["display_name"] == "学生 1"
    assert changed["persons"][0]["person_filter"]["reasons"][-1] == "manual_restore"
    marked = next(p for p in changed["excluded_persons"] if p["person_id"] == "person_03")
    assert marked["person_filter"]["status"] == "teacher" and marked["person_filter"]["manual"]
    assert "manual_teacher" in marked["person_filter"]["reasons"]
    assert pf.apply_person_filter(changed, {"person_01": "student", "person_03": "teacher"}) == changed
    legacy = {"available": True, "persons": [{"person_id": "person_01", "display_name": "人物 1"}]}
    assert pf.apply_person_filter(legacy) is legacy


def test_identity_candidates_are_tagged_from_tracks():
    view = pf.apply_person_filter(_analysis())
    faces = [{"bbox": {"x": .05, "y": .5, "width": .08, "height": .1}},
             {"bbox": {"x": .3, "y": .5, "width": .08, "height": .1}},
             {"bbox": {"x": .5, "y": .1, "width": .02, "height": .03}}]
    tagged = pf.annotate_faces(faces, view, 2.5, frame_width=768)
    assert [f["filter_status"] for f in tagged] == ["teacher", "student", "blank"]
    assert tagged[0]["filter_status_zh"] == "疑似老师"


def _scene(tmp_path, count=40):
    cv = pytest.importorskip("cv2")
    rng = np.random.default_rng(7)
    root = tmp_path / "frames"
    root.mkdir()
    for i in range(count):
        image = np.full((432, 768, 3), 205, np.uint8)
        for x in (.3, .5, .7):  # textured seated "students"
            x0 = int(x * 768)
            image[230:280, x0:x0 + 48] = rng.integers(0, 255, (50, 48, 3), dtype=np.uint8)
        tx = int((.06 + .06 * np.sin(i / 3)) * 768)
        image[120:205, tx:tx + 80] = rng.integers(0, 255, (85, 80, 3), dtype=np.uint8)
        _, encoded = cv.imencode(".jpg", image, [cv.IMWRITE_JPEG_QUALITY, 95])
        (root / f"frame_{i:06d}.jpg").write_bytes(encoded.tobytes())
    return dict(root=str(root), duration=count, samples=[dict(frame=f"frame_{i:06d}.jpg", time=i) for i in range(count)])


def _stub_detector():
    calls = []

    def detect(image):
        calls.append(1)
        n = len(calls)
        faces = [dict(bbox=dict(x=x, y=.53, width=.0625, height=.115), score=.9) for x in (.3, .5, .7)]
        teacher_x = .06 + .06 * np.sin(((n - 1) % 40) / 3)
        faces.append(dict(bbox=dict(x=float(teacher_x), y=.28, width=.104, height=.196), score=.92))
        if n in (1, 2):
            faces.append(dict(bbox=dict(x=.9, y=.55, width=.06, height=.1), score=.75))
        return faces
    return detect


def test_tracker_marks_teacher_and_blank_and_keeps_all_candidates(tmp_path):
    result = tracking.analyze(_scene(tmp_path), _stub_detector())
    assert result["analysis_version"] == tracking.VERSION
    statuses = {p["person_id"]: p["person_filter"]["auto_status"] for p in result["persons"]}
    assert sorted(statuses.values()) == ["blank", "student", "student", "student", "teacher"]
    for person in result["persons"]:
        if person["person_filter"]["auto_status"] == "blank":
            assert person["filter_features"]["face_frames"] < 3
            continue
        assert person["filter_features"]["face_frames"] >= 3
        assert person["track_points"] and len(person["track_points"][0]) == 5
        avatar = person["avatar"]
        assert avatar["sharpness"] == avatar["max_sharpness"]
    view = pf.apply_person_filter(result)
    assert [p["display_name"] for p in view["persons"]] == ["学生 1", "学生 2", "学生 3"]
    presented = tracking.present_motion_analysis(view)
    assert "疑似老师1人、无效人选1个" in presented["lesson_report"]["text"]
    assert all(p["display_name"].startswith("学生") for p in presented["persons"])


@pytest.mark.skipif(not (ROOT / "models" / "face_detection_yunet_2023mar.onnx").is_file(),
                    reason="YuNet model not installed")
def test_synthetic_cartoon_classroom_with_real_yunet(tmp_path):
    cv = pytest.importorskip("cv2")
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from make_person_filter_synthetic_video import render_frame
    finally:
        sys.path.pop(0)
    root = tmp_path / "frames"
    root.mkdir()
    count = 30
    for i in range(count):
        image = cv.resize(render_frame(float(i)), (768, 432), interpolation=cv.INTER_AREA)
        (root / f"frame_{i:06d}.jpg").write_bytes(cv.imencode(".jpg", image)[1].tobytes())
    result = tracking.analyze(dict(root=str(root), duration=count,
                                   samples=[dict(frame=f"frame_{i:06d}.jpg", time=i) for i in range(count)]))
    view = pf.apply_person_filter(result)
    assert [p["display_name"] for p in view["persons"]] == ["学生 1", "学生 2", "学生 3"]
    excluded = {p["person_filter"]["status"] for p in view["excluded_persons"]}
    assert excluded == {"teacher", "blank"} and len(view["excluded_persons"]) == 2
    for person in view["persons"]:
        assert person["avatar"]["sharpness"] == person["avatar"]["max_sharpness"]


@pytest.fixture
def avatar_store(tmp_path, monkeypatch):
    cv = pytest.importorskip("cv2")
    from rehab_affect.student_record_store import Demo2StudentRecordStore
    frame = tmp_path / "frames" / "frame_000000.jpg"
    frame.parent.mkdir()
    image = np.full((432, 768, 3), 220, np.uint8)
    image[200:260, 300:350] = (20, 30, 230)
    frame.write_bytes(cv.imencode(".jpg", image)[1].tobytes())
    store = object.__new__(Demo2StudentRecordStore)
    monkeypatch.setattr(store, "account_from_session", lambda _: {"username": "synthetic"})
    monkeypatch.setattr(store, "_connect", lambda: nullcontext(None))
    monkeypatch.setattr(store, "_authorized_video_task", lambda *a: {"analysis_status": "completed"})
    monkeypatch.setattr(store, "_require_live_video", lambda *a: None)
    monkeypatch.setattr(store, "_video_analysis_dir", lambda *a: tmp_path)
    monkeypatch.setattr(store, "_controlled_video_path", lambda path, *a: path)
    monkeypatch.setattr(store, "_audit", lambda *a: None)
    return store, cv, frame


def test_avatar_is_square_high_quality_and_at_least_160(avatar_store):
    store, cv, frame = avatar_store
    box = dict(x=300 / 768, y=200 / 432, width=50 / 768, height=60 / 432)
    path, mime = store.account_simple_analysis_frame("t", "task", frame.name, box, avatar=True)
    image = cv.imdecode(np.frombuffer(path.read_bytes(), np.uint8), cv.IMREAD_COLOR)
    assert mime == "image/jpeg" and image.shape[0] == image.shape[1] >= 160
    red = (image[:, :, 2] > 180) & (image[:, :, 0] < 90)
    rows, cols = np.where(red)
    # Face box + 40% margin on each side: the face fills the middle of the portrait.
    assert rows.min() > 10 and rows.max() < image.shape[0] - 10 and cols.min() > 10
    assert (rows.max() - rows.min()) / image.shape[0] > .5


# ------------------------------------------------------------ HTTP / store --

from test_demo2_upload_analysis_flow import _create_task, _login, _request, _upload, flow  # noqa: E402,F401


def test_identity_candidates_before_first_track_sample_use_whole_track():
    # The tracker's first sample can start seconds into the video; frame 0 must still be tagged.
    analysis = _analysis()
    for person in analysis["persons"]:
        person["track_points"] = [[6.0, *person["track_points"][0][1:]], [8.0, *person["track_points"][0][1:]]]
    view = pf.apply_person_filter(analysis)
    faces = [{"bbox": {"x": .05, "y": .5, "width": .08, "height": .1}},
             {"bbox": {"x": .3, "y": .5, "width": .08, "height": .1}},
             {"bbox": {"x": .9, "y": .5, "width": .08, "height": .1}},
             {"bbox": {"x": .5, "y": .05, "width": .08, "height": .1}}]
    tagged = pf.annotate_faces(faces, view, 0.0, frame_width=768)
    assert [f["filter_status"] for f in tagged] == ["teacher", "student", "blank", "student"]
    assert "matched_person" not in tagged[3]


def _read(folder):
    return [json.loads(line) for path in sorted(folder.glob("person_filter_debug_*.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _ready_task(flow, tmp_path, monkeypatch):
    from rehab_affect.demo2_media_analysis import SIMPLE_ANALYSIS_VERSION
    from rehab_affect.demo2_identity_store import Demo2IdentityStore
    log_dir = tmp_path / "pf-logs"
    monkeypatch.setenv(pf.DEBUG_LOG_DIR_ENV, str(log_dir))
    task_id = _create_task(flow)[1]["task"]["task_id"]
    assert _upload(flow, task_id)[0] == 200
    analysis = tracking.analyze(_scene(tmp_path), _stub_detector())
    assert analysis["analysis_version"] == SIMPLE_ANALYSIS_VERSION
    Demo2IdentityStore(flow["store"])  # creates the identity tables
    document = json.dumps({"simple_student_analysis": analysis})
    result_path = flow["store"].video_task_dir.resolve() / "results" / f"{task_id}.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(document, encoding="utf-8")
    with sqlite3.connect(flow["store"].db_path) as db:
        db.execute("UPDATE video_analysis_tasks SET analysis_status='evidence_ready', processing_result_json=?, "
                   "result_path=? WHERE task_id=?", (document, str(result_path), task_id))
    return task_id, log_dir


def _people(flow, task_id, cookie=None):
    status, _, body = _request(flow["port"], "GET", f"/api/v1/demo2/simple-result?task_id={task_id}",
                               cookie=cookie or flow["cookie"])
    assert status == 200, body
    return body["analysis"]


def test_api_restore_and_mark_teacher_persist_and_remove_archive(flow, tmp_path, monkeypatch):
    task_id, log_dir = _ready_task(flow, tmp_path, monkeypatch)
    analysis = _people(flow, task_id)
    assert [p["display_name"] for p in analysis["persons"]] == ["学生 1", "学生 2", "学生 3"]
    excluded = {p["person_filter"]["status"]: p for p in analysis["excluded_persons"]}
    assert set(excluded) == {"teacher", "blank"}
    assert "已自动排除疑似老师 1 人、无效人选 1 个" in analysis["person_filter_summary"]["notice"]
    timeline_people = {p["person_id"] for p in analysis["persons"]}
    assert excluded["teacher"]["person_id"] not in timeline_people

    teacher_id = excluded["teacher"]["person_id"]
    port, cookie = flow["port"], flow["cookie"]
    status, _, body = _request(port, "POST", "/api/v1/demo2/simple-result/person-filter",
                               {"task_id": task_id, "person_id": teacher_id, "decision": "restore"}, cookie=cookie)
    assert status == 200 and body["decision"]["status"] == "student"
    analysis = _people(flow, task_id)
    assert teacher_id in {p["person_id"] for p in analysis["persons"]}
    assert analysis["persons"][0]["person_id"] == teacher_id and analysis["persons"][0]["display_name"] == "学生 1"
    assert len(analysis["persons"]) == 4 and analysis["person_filter_summary"]["manual_overrides"] == 1

    # A student with a saved lesson archive is marked as teacher: archive and binding disappear.
    student = analysis["persons"][2]
    account_id = flow["store"].account_from_session(cookie.split("=", 1)[1])["account_id"]
    with sqlite3.connect(flow["store"].db_path) as db:
        db.execute("INSERT INTO demo2_identity_students(student_id,owner_account_id,scope_key,school_context_json,"
                   "display_name,created_at) VALUES('stu_pf',?,'scope','{}','虚构学生','2026-10-31T00:00:00+00:00')",
                   (account_id,))
        db.execute("INSERT INTO demo2_identity_bindings(binding_id,task_id,owner_account_id,scope_key,student_id,role,"
                   "frame_key,frame_revision,source_sha256,time_sec,bbox_json,confirmed_by,created_at) VALUES"
                   "('bind_pf',?,?,'scope','stu_pf','student','s0_f0','rev','sha',0,'{}','t','2026-10-31')",
                   (task_id, account_id))
        db.execute("""CREATE TABLE IF NOT EXISTS demo2_simple_lesson_archives (
            archive_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, person_id TEXT NOT NULL,
            student_id TEXT NOT NULL, binding_id TEXT NOT NULL, owner_account_id TEXT NOT NULL,
            main_state TEXT NOT NULL, average_score REAL, key_times_json TEXT NOT NULL,
            state_breakdown_json TEXT NOT NULL, lesson_summary TEXT NOT NULL,
            iep_support_summary TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, UNIQUE(task_id, person_id, student_id))""")
        db.execute("INSERT INTO demo2_simple_lesson_archives VALUES('sla_pf',?,?,'stu_pf','bind_pf',?,'engaged',5,"
                   "'[]','{}','summary','',?,?)", (task_id, student["person_id"], account_id, "t", "t"))
    status, _, body = _request(port, "POST", "/api/v1/demo2/simple-result/person-filter",
                               {"task_id": task_id, "person_id": student["person_id"], "decision": "mark_teacher"},
                               cookie=cookie)
    assert status == 200 and body["decision"]["archives_removed"] == 1 and body["decision"]["bindings_revoked"] == 1
    for _ in range(2):  # persists across reloads
        analysis = _people(flow, task_id)
        assert student["person_id"] not in {p["person_id"] for p in analysis["persons"]}
        assert not any(a["person_id"] == student["person_id"] for a in analysis["lesson_archives"])
        moved = next(p for p in analysis["excluded_persons"] if p["person_id"] == student["person_id"])
        assert moved["person_filter"]["manual"] and moved["display_name"].startswith("疑似老师")
    with sqlite3.connect(flow["store"].db_path) as db:
        assert db.execute("SELECT status FROM demo2_identity_bindings WHERE binding_id='bind_pf'").fetchone()[0] == "revoked"

    # The derived export used by the video page carries the same filtered list.
    status, _, body = _request(port, "GET", f"/api/v1/demo2/upload/task?id={task_id}", cookie=cookie)
    assert status == 200
    exported = body["result"]["simple_student_analysis"]
    assert [p["person_id"] for p in exported["persons"]] == [p["person_id"] for p in analysis["persons"]]

    # Validation, ownership.
    status, _, body = _request(port, "POST", "/api/v1/demo2/simple-result/person-filter",
                               {"task_id": task_id, "person_id": "person_01", "decision": "delete"}, cookie=cookie)
    assert status == 400 and body["error"]["code"] == "invalid_person_filter"
    status, _, body = _request(port, "POST", "/api/v1/demo2/simple-result/person-filter",
                               {"task_id": task_id, "person_id": "person_99", "decision": "restore"}, cookie=cookie)
    assert status == 400 and body["error"]["code"] == "person_not_in_task"
    other = _login(port, "school_uploader_02")
    status, _, _ = _request(port, "POST", "/api/v1/demo2/simple-result/person-filter",
                            {"task_id": task_id, "person_id": teacher_id, "decision": "mark_teacher"}, cookie=other)
    assert status == 403

    entries = _read(log_dir)
    operations = [e["operation"] for e in entries]
    for expected in ("person_restore", "person_mark_teacher"):
        assert expected in operations
    mark = next(e for e in entries if e["operation"] == "person_mark_teacher" and e["result"] == "ok")
    assert mark["task_id"] == task_id and mark["status"] == "teacher" and mark["archives_removed"] == 1
    assert any(e["result"] == "rejected" for e in entries)
    raw = "\n".join(p.read_text(encoding="utf-8") for p in log_dir.glob("*.jsonl"))
    assert "虚构学生" not in raw and "bbox" not in raw


def _insert(db, table, values):
    columns = db.execute(f"PRAGMA table_info({table})").fetchall()
    row = {c[1]: values.get(c[1], 0 if "INT" in (c[2] or "").upper() or "REAL" in (c[2] or "").upper() else "")
           for c in columns if c[1] in values or (c[3] and c[4] is None)}
    db.execute(f"INSERT INTO {table}({','.join(row)}) VALUES({','.join('?' * len(row))})", tuple(row.values()))


def test_mark_teacher_withdraws_video_measurements_and_iep_reference(flow, tmp_path, monkeypatch):
    task_id, log_dir = _ready_task(flow, tmp_path, monkeypatch)
    student = _people(flow, task_id)["persons"][1]
    other = _people(flow, task_id)["persons"][0]
    cookie = flow["cookie"]
    account_id = flow["store"].account_from_session(cookie.split("=", 1)[1])["account_id"]
    with sqlite3.connect(flow["store"].db_path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS demo2_simple_lesson_archives (
            archive_id TEXT PRIMARY KEY, task_id TEXT NOT NULL, person_id TEXT NOT NULL,
            student_id TEXT NOT NULL, binding_id TEXT NOT NULL, owner_account_id TEXT NOT NULL,
            main_state TEXT NOT NULL, average_score REAL, key_times_json TEXT NOT NULL,
            state_breakdown_json TEXT NOT NULL, lesson_summary TEXT NOT NULL,
            iep_support_summary TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            iep_document_id TEXT NOT NULL DEFAULT '', iep_reference_id TEXT NOT NULL DEFAULT '',
            UNIQUE(task_id, person_id, student_id))""")
        db.execute("""CREATE TABLE IF NOT EXISTS demo2_measurements (record_id TEXT PRIMARY KEY,
            owner_account_id TEXT NOT NULL, scope_key TEXT NOT NULL, student_id TEXT NOT NULL, lesson_date TEXT NOT NULL,
            lesson_id TEXT NOT NULL, goal_id TEXT NOT NULL, measurement_context TEXT NOT NULL, version INTEGER NOT NULL,
            status TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            expires_at TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS demo2_measurement_versions (record_id TEXT NOT NULL,
            version INTEGER NOT NULL, payload_json TEXT NOT NULL, saved_by TEXT NOT NULL, saved_at TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS demo2_dossier_references (reference_id TEXT PRIMARY KEY,
            student_id TEXT NOT NULL, owner_account_id TEXT NOT NULL, task_id TEXT NOT NULL,
            withdrawn_at TEXT NOT NULL DEFAULT '')""")
        for archive_id, person, binding, reference in (("sla_a", student["person_id"], "bind_a", "ref_a"),
                                                         ("sla_b", other["person_id"], "bind_b", "ref_b")):
            _insert(db, "demo2_identity_bindings", dict(
                binding_id=binding, task_id=task_id, owner_account_id=account_id, scope_key="scope",
                student_id="stu_" + archive_id, role="student", frame_key="s0_f0", frame_revision="rev",
                source_sha256="sha", time_sec=0, bbox_json="{}", confirmed_by="t", created_at="t", status="confirmed"))
            _insert(db, "demo2_simple_lesson_archives", dict(
                archive_id=archive_id, task_id=task_id, person_id=person, student_id="stu_" + archive_id,
                binding_id=binding, owner_account_id=account_id, main_state="x", key_times_json="[]",
                state_breakdown_json="{}", lesson_summary="s", iep_support_summary="", created_at="t", updated_at="t",
                iep_document_id="doc_" + archive_id, iep_reference_id=reference))
            _insert(db, "demo2_dossier_references", dict(
                reference_id=reference, student_id="stu_" + archive_id, owner_account_id=account_id, task_id=task_id,
                scope_key="scope", frame_revision="rev", source_sha256="sha", binding_ids_json="[]", created_at="t",
                withdrawn_at=""))
            payload = json.dumps({"record_id": "vm-" + archive_id, "task_id": task_id, "person_id": person,
                                  "source_type": "video", "status": "active", "version": 1})
            _insert(db, "demo2_measurements", dict(
                record_id="vm-" + archive_id, owner_account_id=account_id, scope_key="scope",
                student_id="stu_" + archive_id, lesson_date="2026-10-31", lesson_id="c", goal_id="G-01",
                measurement_context="课堂视频", version=1, status="active", payload_json=payload,
                created_at="t", updated_at="t", expires_at="t"))
    status, _, body = _request(flow["port"], "POST", "/api/v1/demo2/simple-result/person-filter",
                               {"task_id": task_id, "person_id": student["person_id"], "decision": "mark_teacher"},
                               cookie=cookie)
    assert status == 200, body
    decision = body["decision"]
    assert (decision["archives_removed"], decision["bindings_revoked"]) == (1, 1)
    assert (decision["measurements_withdrawn"], decision["references_withdrawn"]) == (1, 1)
    with sqlite3.connect(flow["store"].db_path) as db:
        rows = dict(db.execute("SELECT record_id, status FROM demo2_measurements").fetchall())
        assert rows == {"vm-sla_a": "withdrawn", "vm-sla_b": "active"}
        withdrawn = json.loads(db.execute("SELECT payload_json FROM demo2_measurements WHERE record_id='vm-sla_a'")
                               .fetchone()[0])
        assert withdrawn["status"] == "withdrawn" and withdrawn["version"] == 2
        assert db.execute("SELECT version FROM demo2_measurement_versions WHERE record_id='vm-sla_a'").fetchone()[0] == 2
        refs = dict(db.execute("SELECT reference_id, withdrawn_at FROM demo2_dossier_references").fetchall())
        assert refs["ref_a"] and refs["ref_b"] == ""
    mark = next(e for e in _read(log_dir) if e["operation"] == "person_mark_teacher" and e["result"] == "ok")
    assert mark["measurements_withdrawn"] == 1 and mark["references_withdrawn"] == 1


def test_tracker_run_log_records_scores_and_avatar(tmp_path, monkeypatch):
    monkeypatch.setenv(pf.DEBUG_LOG_DIR_ENV, str(tmp_path / "logs"))
    result = tracking.analyze(_scene(tmp_path), _stub_detector())
    pf.log_analysis(result, task_id="task_pf")
    entries = _read(tmp_path / "logs")
    operations = [e["operation"] for e in entries]
    assert operations.count("person_filter_run") == 1
    assert "person_excluded_teacher" in operations and "person_excluded_blank" in operations
    assert operations.count("avatar_select") >= 4
    run = entries[0]
    assert (run["candidate_count"], run["student_count"], run["excluded_teacher"], run["excluded_blank"]) == (5, 3, 1, 1)
    teacher = next(e for e in entries if e["operation"] == "person_excluded_teacher")
    assert teacher["teacher_score"] >= .55 and "large_face" in teacher["reasons"] and "size" in teacher["scores"]
    avatar = next(e for e in entries if e["operation"] == "avatar_select")
    assert avatar["avatar_sharpness"] > 0 and avatar["max_sharpness"] >= avatar["avatar_sharpness"]
    assert all(e["ts"] and e["task_id"] == "task_pf" for e in entries)


def test_result_page_has_student_only_filter_ui():
    from rehab_affect.demo2_simple_result import render_simple_result
    html = render_simple_result()
    for marker in ("id=\"filterNotice\"", "id=\"excludedPanel\"", "恢复为学生", "标记为老师/非学生",
                   "/simple-result/person-filter", "crop:crop==='avatar'?'avatar':'person'"):
        assert marker in html
    # A retry after a failed archive (binding saved, archive rejected) reuses the binding on the same frame
    # instead of creating a duplicate that the server rejects with duplicate_student_binding.
    assert "liveBindings.find(b=>b.frame_key===frame.frame_key)" in html
    # No student left (no faces, or every candidate excluded) → explicit empty state, not an error.
    assert 'id="noStudentState"' in html and "未识别到学生" in html


def test_identity_page_hides_excluded_candidates_by_default():
    from rehab_affect.demo2_identity import render_identity
    html = render_identity()
    assert 'id="showExcludedCandidates"' in html and "显示已排除候选" in html
    assert "allCandidates.filter(face=>!isExcludedCandidate(face))" in html
