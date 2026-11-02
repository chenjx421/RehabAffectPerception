"""Multi-student detection (每课至少 3 名), unified student switcher and 本课检测学生 selection.

All inputs are synthetic (OpenCV cartoon faces or drawn shapes); no real people.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from rehab_affect import demo2_person_filter as pf
from rehab_affect import demo2_student_tracking as tracking

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_demo2_person_filter import _insert, _people, _read, _ready_task  # noqa: E402
from test_demo2_upload_analysis_flow import PASSWORD_PREFIX, _login, _request, flow  # noqa: E402,F401

ROOT = Path(__file__).resolve().parents[1]
YUNET = ROOT / "models" / "face_detection_yunet_2023mar.onnx"


def _synthetic_frames(tmp_path, students, count=30):
    cv = pytest.importorskip("cv2")
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        from make_person_filter_synthetic_video import render_frame
    finally:
        sys.path.pop(0)
    root = tmp_path / f"frames_{students}"
    root.mkdir()
    for i in range(count):
        image = cv.resize(render_frame(float(i), students), (768, 432), interpolation=cv.INTER_AREA)
        (root / f"frame_{i:06d}.jpg").write_bytes(cv.imencode(".jpg", image)[1].tobytes())
    return dict(root=str(root), duration=count, samples=[dict(frame=f"frame_{i:06d}.jpg", time=i) for i in range(count)])


@pytest.mark.skipif(not YUNET.is_file(), reason="YuNet model not installed")
def test_three_cartoon_students_and_walking_teacher_give_three_switchable_students(tmp_path):
    view = pf.apply_person_filter(tracking.analyze(_synthetic_frames(tmp_path, 3)))
    assert [p["display_name"] for p in view["persons"]] == ["学生 1", "学生 2", "学生 3"]
    teachers = [p for p in view["excluded_persons"] if p["person_filter"]["status"] == "teacher"]
    assert len(teachers) == 1
    summary = view["person_filter_summary"]
    assert summary["student_count"] == 3 and summary["low_student_notice"] is None
    assert pf.person_filter_config()["avatar_side"] >= 160
    # Three distinct, sharp avatars: one per student, never the same face twice.
    avatars = [p["avatar"] for p in view["persons"]]
    assert all(a["sharpness"] > 0 and a["face_px"] >= 24 for a in avatars)
    assert len({round(a["bbox"]["x"], 3) for a in avatars}) == 3
    items = pf.switcher_items(view)
    assert [i["binding"] for i in items[:3]] == ["unbound"] * 3 and items[3]["binding"] == "excluded"
    assert all(i["avatar"]["crop"] == "avatar" for i in items[:3])


@pytest.mark.skipif(not YUNET.is_file(), reason="YuNet model not installed")
@pytest.mark.parametrize("students", [1, 2])
def test_fewer_than_three_students_explain_why(tmp_path, students):
    view = pf.apply_person_filter(tracking.analyze(_synthetic_frames(tmp_path, students)))
    assert len(view["persons"]) == students
    low = view["person_filter_summary"]["low_student_notice"]
    assert low["message"] == f"本视频仅识别到 {students} 名学生"
    assert any(r["code"] == "excluded_teacher" for r in low["reasons"])
    assert "手动画框" in low["hint"]


def test_low_student_notice_reasons_cover_faces_teachers_blanks_and_unticked():
    low = pf.low_student_notice(1, 2, {"teacher": 1, "blank": 0, "excluded_by_teacher": 0})
    assert low["message"] == "本视频仅识别到 1 名学生"
    assert [r["code"] for r in low["reasons"]] == ["few_faces", "excluded_teacher"]
    assert "只持续检出 2 张人脸" in low["reasons"][0]["text"]
    low = pf.low_student_notice(2, 5, {"teacher": 1, "blank": 1, "excluded_by_teacher": 1})
    assert [r["code"] for r in low["reasons"]] == ["excluded_teacher", "excluded_blank", "excluded_by_teacher"]
    assert pf.low_student_notice(3, 3, {}) is None


def test_small_far_classroom_faces_stay_students():
    """Wide-angle classroom footage: 10–12 px faces at the 768 px analysis size are real students."""
    def far(cx, score=.69, px=11.0):
        return {"face_frames": 300, "detection_attempts": 576, "face_ratio": .52, "mean_score": score,
                "median_face_width": px / 768, "median_face_height": px / 432, "median_face_px": px,
                "median_cx": cx, "median_cy": .45, "x_range": .01, "presence_ratio": .95, "best_sharpness": 80.0}
    result = pf.classify_candidates([far(.2), far(.4, px=10.2), far(.6, score=.685), far(.8, px=12.4)])
    assert [r["auto_status"] for r in result] == ["student"] * 4
    # A genuine blank pick (two flickering frames, tiny, low score) is still excluded.
    blank = dict(far(.9, score=.55, px=7.0), face_frames=2, face_ratio=.004)
    assert pf.classify_candidates([far(.2), blank])[1]["auto_status"] == "blank"
    # A background face far smaller than the class is excluded relative to the group.
    classified = pf.classify_candidates([far(.2, px=40.0), far(.4, px=42.0), far(.6, px=41.0), far(.8, px=12.0)])
    assert [r["auto_status"] for r in classified] == ["student", "student", "student", "blank"]


def test_override_table_migrates_old_check_constraint(tmp_path):
    db = sqlite3.connect(tmp_path / "old.sqlite3")
    db.execute(pf.OVERRIDE_TABLE.replace(", 'excluded_by_teacher'", ""))
    db.execute("INSERT INTO demo2_person_filter_overrides VALUES('t','person_01','a','teacher','u','2026')")
    pf.ensure_table(db)
    db.execute("INSERT INTO demo2_person_filter_overrides VALUES('t','person_02','a','excluded_by_teacher','u','2026')")
    assert pf.load_overrides(db, "t") == {"person_01": "teacher", "person_02": "excluded_by_teacher"}
    view = pf.apply_person_filter(_three_students(), {"person_02": "excluded_by_teacher"})
    moved = next(p for p in view["excluded_persons"] if p["person_id"] == "person_02")
    assert moved["display_name"] == "未纳入人物 1" and moved["person_filter"]["status_zh"] == "未纳入本课检测"
    assert view["person_filter_summary"]["excluded_by_teacher"] == 1
    assert view["person_filter_summary"]["low_student_notice"]["message"] == "本视频仅识别到 2 名学生"


def _three_students():
    people = []
    for index, x in enumerate((.2, .45, .7), 1):
        people.append({"person_id": f"person_{index:02d}", "candidate_index": index - 1,
                       "anchor_bbox": {"x": x, "y": .5, "width": .06, "height": .1},
                       "person_filter": {"auto_status": "student", "reasons": []}, "windows": [],
                       "avatar": {"frame": "frame_000001.jpg", "bbox": {"x": x, "y": .5, "width": .06, "height": .1},
                                  "time_sec": 1.0}})
    return {"analysis_version": tracking.VERSION, "available": True, "persons": people}


def _account_id(flow):
    return flow["store"].account_from_session(flow["cookie"].split("=", 1)[1])["account_id"]


def _seed_archive(flow, task_id, person, suffix):
    account_id = _account_id(flow)
    person_id = person["person_id"]
    window = next(w for w in person["windows"] if w.get("bbox"))  # binding must match the tracked box
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
        _insert(db, "demo2_identity_students", dict(student_id="stu_" + suffix, owner_account_id=account_id,
                                                    scope_key="scope", school_context_json="{}",
                                                    display_name="虚构学生" + suffix, created_at="t"))
        _insert(db, "demo2_identity_bindings", dict(
            binding_id="bind_" + suffix, task_id=task_id, owner_account_id=account_id, scope_key="scope",
            student_id="stu_" + suffix, role="student", frame_key="s0_f" + suffix, frame_revision="rev",
            source_sha256="sha", time_sec=window["frame_time_sec"], bbox_json=json.dumps(window["bbox"]),
            confirmed_by="t", created_at="t", status="confirmed"))
        _insert(db, "demo2_simple_lesson_archives", dict(
            archive_id="sla_" + suffix, task_id=task_id, person_id=person_id, student_id="stu_" + suffix,
            binding_id="bind_" + suffix, owner_account_id=account_id, main_state="x", key_times_json="[]",
            state_breakdown_json="{}", lesson_summary="s", iep_support_summary="", created_at="t", updated_at="t",
            iep_document_id="doc_" + suffix, iep_reference_id="ref_" + suffix))
        _insert(db, "demo2_dossier_references", dict(
            reference_id="ref_" + suffix, student_id="stu_" + suffix, owner_account_id=account_id, task_id=task_id,
            scope_key="scope", frame_revision="rev", source_sha256="sha", binding_ids_json="[]", created_at="t",
            withdrawn_at=""))
        payload = json.dumps({"record_id": "vm-" + suffix, "task_id": task_id, "person_id": person_id,
                              "source_type": "video", "status": "active", "version": 1})
        _insert(db, "demo2_measurements", dict(
            record_id="vm-" + suffix, owner_account_id=account_id, scope_key="scope", student_id="stu_" + suffix,
            lesson_date="2026-11-01", lesson_id="c", goal_id="G-01", measurement_context="课堂视频", version=1,
            status="active", payload_json=payload, created_at="t", updated_at="t", expires_at="t"))


def _decide(flow, task_id, person_id, decision, cookie=None):
    return _request(flow["port"], "POST", "/api/v1/demo2/simple-result/person-filter",
                    {"task_id": task_id, "person_id": person_id, "decision": decision},
                    cookie=cookie or flow["cookie"])


def test_exclude_then_include_cascades_and_restores_lesson_data(flow, tmp_path, monkeypatch):
    task_id, log_dir = _ready_task(flow, tmp_path, monkeypatch)
    students = _people(flow, task_id)["persons"]
    assert len(students) == 3
    target, other = students[1], students[0]
    _seed_archive(flow, task_id, target, "a")
    _seed_archive(flow, task_id, other, "b")

    status, _, body = _request(flow["port"], "GET", f"/api/v1/demo2/simple-result/persons?task_id={task_id}",
                               cookie=flow["cookie"])
    assert status == 200, body
    items = {i["person_id"]: i for i in body["persons"]}
    assert items[target["person_id"]]["binding"] == "bound" and items[target["person_id"]]["student_id"] == "stu_a"
    assert sum(1 for i in body["persons"] if i["included"]) == 3
    assert body["summary"]["low_student_notice"] is None

    status, _, body = _decide(flow, task_id, target["person_id"], "exclude")
    assert status == 200, body
    decision = body["decision"]
    assert decision["status"] == "excluded_by_teacher" and decision["included"] is False
    assert (decision["measurements_withdrawn"], decision["references_withdrawn"],
            decision["bindings_revoked"], decision["archives_removed"]) == (1, 1, 1, 1)
    assert "report_regenerated" in decision
    analysis = _people(flow, task_id)
    assert target["person_id"] not in {p["person_id"] for p in analysis["persons"]}
    assert not any(a["person_id"] == target["person_id"] for a in analysis["lesson_archives"])
    moved = next(p for p in analysis["excluded_persons"] if p["person_id"] == target["person_id"])
    assert moved["person_filter"]["status"] == "excluded_by_teacher"
    low = analysis["person_filter_summary"]["low_student_notice"]
    assert low["message"] == "本视频仅识别到 2 名学生"
    with sqlite3.connect(flow["store"].db_path) as db:
        rows = dict(db.execute("SELECT record_id, status FROM demo2_measurements").fetchall())
        assert rows == {"vm-a": "withdrawn", "vm-b": "active"}
        assert db.execute("SELECT max(version) FROM demo2_measurement_versions WHERE record_id='vm-a'").fetchone()[0] == 2
        refs = dict(db.execute("SELECT reference_id, withdrawn_at FROM demo2_dossier_references").fetchall())
        assert refs["ref_a"] and refs["ref_b"] == ""

    status, _, body = _decide(flow, task_id, target["person_id"], "include")
    assert status == 200, body
    decision = body["decision"]
    assert decision["status"] == "student" and decision["included"] is True
    assert (decision["measurements_restored"], decision["references_restored"],
            decision["bindings_restored"], decision["archives_restored"]) == (1, 1, 1, 1)
    analysis = _people(flow, task_id)
    assert target["person_id"] in {p["person_id"] for p in analysis["persons"]}
    assert any(a["person_id"] == target["person_id"] and a["student_id"] == "stu_a" for a in analysis["lesson_archives"])
    with sqlite3.connect(flow["store"].db_path) as db:
        payload = json.loads(db.execute("SELECT payload_json FROM demo2_measurements WHERE record_id='vm-a'").fetchone()[0])
        assert payload["status"] == "active" and payload["version"] == 3 and "withdrawal_reason" not in payload
        assert db.execute("SELECT status FROM demo2_identity_bindings WHERE binding_id='bind_a'").fetchone()[0] == "confirmed"
        assert db.execute("SELECT withdrawn_at FROM demo2_dossier_references WHERE reference_id='ref_a'").fetchone()[0] == ""
        assert db.execute("SELECT count(*) FROM demo2_person_filter_suspended").fetchone()[0] == 0

    # Mark-teacher then restore takes the same restore path.
    status, _, body = _decide(flow, task_id, target["person_id"], "mark_teacher")
    assert status == 200 and body["decision"]["measurements_withdrawn"] == 1
    status, _, body = _decide(flow, task_id, target["person_id"], "restore")
    assert status == 200 and body["decision"]["measurements_restored"] == 1

    entries = _read(log_dir)
    ops = [(e["operation"], e["result"]) for e in entries]
    assert ("person_exclude", "ok") in ops and ("person_include", "ok") in ops and ("person_list", "ok") in ops
    exclude = next(e for e in entries if e["operation"] == "person_exclude" and e["result"] == "ok")
    assert exclude["task_short"] == task_id[:8] and exclude["person_id"] == target["person_id"]
    assert exclude["measurements_withdrawn"] == 1 and exclude["ts"]
    include = next(e for e in entries if e["operation"] == "person_include" and e["result"] == "ok")
    assert include["measurements_restored"] == 1 and include["references_restored"] == 1
    raw = "\n".join(p.read_text(encoding="utf-8") for p in log_dir.glob("*.jsonl"))
    assert "虚构学生" not in raw and "bbox" not in raw


def test_person_selection_permissions_and_validation(flow, tmp_path, monkeypatch):
    task_id, log_dir = _ready_task(flow, tmp_path, monkeypatch)
    person_id = _people(flow, task_id)["persons"][0]["person_id"]
    other = _login(flow["port"], "school_uploader_02")
    status, _, body = _decide(flow, task_id, person_id, "exclude", cookie=other)
    assert status == 403, body
    status, _, _ = _request(flow["port"], "GET", f"/api/v1/demo2/simple-result/persons?task_id={task_id}", cookie=other)
    assert status == 403
    status, _, body = _decide(flow, "a" * 32, person_id, "exclude")
    assert status == 404 and body["error"]["code"] == "task_unavailable"
    status, _, body = _decide(flow, task_id, "person_99", "exclude")
    assert status == 400 and body["error"]["code"] == "person_not_in_task"
    status, _, body = _decide(flow, task_id, person_id, "drop")
    assert status == 400 and body["error"]["code"] == "invalid_person_filter"
    status, headers, _ = _request(flow["port"], "POST", "/api/v1/demo2/auth/login",
                                  {"username": "admin", "password": PASSWORD_PREFIX + "company_admin",
                                   "login_role": "admin"})
    assert status == 200
    admin = headers["set-cookie"].split(";", 1)[0]
    status, _, _ = _decide(flow, task_id, person_id, "exclude", cookie=admin)
    assert status == 403
    status, _, _ = _request(flow["port"], "GET", f"/api/v1/demo2/simple-result/persons?task_id={task_id}", cookie=admin)
    assert status == 403
    assert all(p["person_filter"]["status"] == "student" for p in _people(flow, task_id)["persons"])


def test_switch_event_logged_without_names(flow, tmp_path, monkeypatch):
    task_id, log_dir = _ready_task(flow, tmp_path, monkeypatch)
    person_id = _people(flow, task_id)["persons"][2]["person_id"]
    for page in ("simple_result", "identity", "analysis"):
        status, _, body = _request(flow["port"], "POST", "/api/v1/demo2/simple-result/person-switch",
                                   {"task_id": task_id, "person_id": person_id, "page": page, "trigger": "click"},
                                   cookie=flow["cookie"])
        assert status == 200, body
    status, _, _ = _request(flow["port"], "POST", "/api/v1/demo2/simple-result/person-switch",
                            {"student_id": "stu_x", "page": "measurement", "trigger": "history"}, cookie=flow["cookie"])
    assert status == 200
    for bad in ({"page": "simple_result"}, {"person_id": person_id, "page": "elsewhere"},
                {"person_id": "张三", "page": "identity"}, {"person_id": person_id, "page": "identity", "name": "x"}):
        status, _, _ = _request(flow["port"], "POST", "/api/v1/demo2/simple-result/person-switch", bad,
                                cookie=flow["cookie"])
        assert status == 400
    switches = [e for e in _read(log_dir) if e["operation"] == "person_switch"]
    assert [e["page"] for e in switches] == ["simple_result", "identity", "analysis", "measurement"]
    assert switches[0]["task_short"] == task_id[:8] and switches[0]["person_id"] == person_id
    assert switches[-1]["trigger"] == "history" and switches[-1]["student_id"] == "stu_x"


def _page_scripts(html):
    return [m for m in re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)]


def test_four_pages_carry_the_unified_switcher():
    from rehab_affect.demo2_course_page import render_course_analysis
    from rehab_affect.demo2_identity import render_identity
    from rehab_affect.demo2_measurement import render_measurement
    from rehab_affect.demo2_simple_result import render_simple_result
    teacher = {"role": "school_uploader", "username": "t1"}
    pages = {"simple_result": render_simple_result(teacher), "identity": render_identity(teacher),
             "analysis": render_course_analysis(teacher), "measurement": render_measurement(teacher)}
    hosts = {"simple_result": 'id="personTabs"', "identity": 'id="identitySwitch"',
             "analysis": 'id="personSwitch"', "measurement": 'id="measureSwitch"'}
    for page, html in pages.items():
        assert hosts[page] in html, page
        assert f"page:'{page}'" in html, page
        assert "R.studentSwitcher=studentSwitcher" in html, page  # kit component, not a page copy
        assert ".rx-switch-card" in html, page
    result = pages["simple_result"]
    for marker in ('id="detectionPanel"', "本课检测学生", "纳入本课检测", "data-include=", "'exclude'", "'include'",
                   "标记为老师/非学生", "恢复为学生", "stateCurve(p)", "personMeasureHtml(p)", "data-person-report"):
        assert marker in result, marker
    assert "切换学生：点击下方姓名" in pages["measurement"]
    assert "personTimeline(lp)" in pages["analysis"] and "personCurve(lp)" in pages["analysis"]


def test_switcher_component_keeps_url_history_and_low_notice_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required")
    from rehab_affect.demo2_ui_kit import UI_SWITCHER_JS
    harness = r"""
const assert=require('node:assert/strict');
const listeners={};const pushed=[];
function el(){return {hidden:true,innerHTML:'',classList:{add(){}},setAttribute(){},addEventListener(){},querySelectorAll(){return []},querySelector(){return null}};}
global.location={href:'http://x.test/demo2/simple-result?task_id=t1&person_id=person_03',pathname:'/demo2/simple-result',search:'?task_id=t1&person_id=person_03',hash:''};
function setUrl(u){const url=new URL(u,'http://x.test');location.href=url.href;location.search=url.search;location.pathname=url.pathname;location.hash=url.hash;}
global.window={RxUI:{},addEventListener:(n,f)=>{(listeners[n]=listeners[n]||[]).push(f);},history:{state:null,pushState(s,t,u){pushed.push(u);setUrl(u);},replaceState(s,t,u){setUrl(u);}}};
global.history=window.history;global.document={activeElement:null,createElement:el};
const posts=[];global.fetch=(u,o)=>{posts.push([u,JSON.parse(o.body)]);return Promise.resolve({ok:true,json:()=>({})});};
global.console={info(){}};
__KIT__
const R=window.RxUI,host=el();const seen=[];
const sw=R.studentSwitcher(host,{page:'simple_result',taskId:'t1',param:'person_id',onSelect:(item,meta)=>seen.push([item.person_id,meta.trigger])});
const items=['person_01','person_02','person_03'].map((p,i)=>({key:p,person_id:p,title:'学生 '+(i+1),status:'unbound'}));
assert.equal(sw.update(items).person_id,'person_03');
assert.deepEqual(seen[0],['person_03','deeplink']);
assert.match(host.innerHTML,/共 3 名学生 · 当前：学生 3/);
assert.match(host.innerHTML,/aria-selected="true"[^>]*title="切换到 学生 3"/);
sw.select('person_02');
assert.equal(pushed.pop(),'/demo2/simple-result?task_id=t1&person_id=person_02');
assert.equal(posts.pop()[1].person_id,'person_02');
setUrl('/demo2/simple-result?task_id=t1&person_id=person_03');listeners.popstate.forEach(f=>f());
assert.equal(sw.current().person_id,'person_03');assert.deepEqual(seen.pop(),['person_03','history']);
sw.setLow({student_count:1,message:'本视频仅识别到 1 名学生',reasons:[{text:'已排除 1 个疑似老师'}],hint:'可手动画框'},'/demo2/identity?task_id=t1');
assert.match(host.innerHTML,/本视频仅识别到 1 名学生/);assert.match(host.innerHTML,/data-manual-box>手动画框添加学生/);
"""
    script = harness.replace("__KIT__", UI_SWITCHER_JS)
    result = subprocess.run([node, "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
