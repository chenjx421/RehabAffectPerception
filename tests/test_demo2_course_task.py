"""Course-task Word/PDF upload, goal confirmation, versions and links (修改意见第 3 条).

Fixtures are fictional documents generated in test_demo2_document_parser; no real student data.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from types import SimpleNamespace

import pytest

pytest.importorskip("docx")
pytest.importorskip("pdfplumber")
pytest.importorskip("pypdf")

from rehab_affect import demo2_course_task_store as course_tasks  # noqa: E402
from rehab_affect.classroom_rubric import evaluate  # noqa: E402
from rehab_affect.demo2_evaluation_store import Demo2EvaluationStore  # noqa: E402
from rehab_affect.demo2_measurement_store import MeasurementError  # noqa: E402
from rehab_affect.student_record_store import Demo2StudentRecordStore  # noqa: E402
from test_demo2_document_parser import COURSE_TABLE, build_course_docx, http_env, samples  # noqa: E402,F401
from test_demo2_dossier_store import env, template  # noqa: E402,F401

COURSE = "synthetic-course-task-1"


@pytest.fixture
def api(http_env, tmp_path, monkeypatch):
    monkeypatch.setenv(course_tasks.DEBUG_LOG_DIR_ENV, str(tmp_path / "course_task_logs"))
    call = http_env.call

    def post(path, token, payload):
        return call("POST", path, token, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json")

    def raw_get(path, token):
        from http.client import HTTPConnection
        conn = HTTPConnection("127.0.0.1", http_env.port, timeout=60)
        try:
            conn.request("GET", path, headers={"Cookie": "rehab_demo2_session=" + token, "Connection": "close"})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    return SimpleNamespace(**vars(http_env), post=post, raw_get=raw_get, course_logs=tmp_path / "course_task_logs")


def _course_lines(folder):
    return [json.loads(line) for path in sorted(folder.glob("course_task_debug_*.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines()]


def _draft(api, token, data):
    status, body = api.upload(token, "course_task", "课程任务.pdf", data)
    assert status == 200, body
    status, body = api.post("/api/v1/demo2/course-tasks/draft", token, {"parse_id": body["result"]["parse_id"]})
    assert status == 200, body
    return body["draft"]


def _confirm_payload(draft, **changes):
    payload = {"parse_id": draft["parse_id"], "course_id": COURSE, "course_name": draft["course_name"],
               "lesson_date": draft["lesson_date"], "goals": draft["goals"],
               "notes": [{"text": item["text"]} for item in draft["other_content"] if not item["sensitive"]][:3],
               "expected_version": 0}
    payload.update(changes)
    return payload


def test_draft_lists_goals_criteria_and_other_content(api, samples):
    draft = _draft(api, api.env.tokens["a"], samples.pdf)
    assert draft["course_name"] == "认识人民币" and draft["lesson_date"] == "2026-11-05"
    assert [g["goal_code"] for g in draft["goals"]] == ["G-01", "G-02", "G-03"]
    assert [g["description"] for g in draft["goals"]] == [
        "能认出1元、5角、1角三种人民币。", "能在提示下用1元购买一件物品。", "能说出物品价格并找到对应的钱币。"]
    assert [g["pass_criteria"] for g in draft["goals"]] == [row[3] for row in COURSE_TABLE[1:]]
    assert all(g["measurement_conditions"].startswith("在模拟超市情境中进行") for g in draft["goals"])
    assert all(g["rubric_dimension"] in course_tasks.DIMENSIONS for g in draft["goals"])
    others = [item["text"] for item in draft["other_content"]]
    assert "导入：出示超市图片，引导学生说出想买的物品。" in others
    assert "练习：分组模拟购物，教师巡回记录。" in others and "备注：本课所有学生姓名均为虚构。" in others
    assert any(item["sensitive"] for item in draft["other_content"])  # 家长联系电话 is flagged, not hidden
    lines = _course_lines(api.course_logs)
    assert lines[-1]["operation"] == "course_task_upload" and lines[-1]["goal_count"] == 3
    assert "人民币" not in json.dumps(lines, ensure_ascii=False)


def test_confirm_versions_access_and_admin_scope(api, samples):
    a, b, admin = api.env.tokens["a"], api.env.tokens["b"], api.env.tokens["admin"]
    draft = _draft(api, a, samples.pdf)
    goals = [dict(g) for g in draft["goals"]]
    goals[0]["pass_criteria"] = "3次中正确2次及以上（教师修订）"
    goals.append({"goal_code": "G-04", "description": "能在集体活动中等待轮到自己。", "pass_criteria": "",
                  "measurement_conditions": "", "rubric_dimension": "process"})
    status, body = api.post("/api/v1/demo2/course-tasks/confirm", a, _confirm_payload(draft, goals=goals))
    assert status == 201, body
    first = body["course_task"]
    assert first["version"] == 1 and first["status"] == "confirmed" and first["goal_count"] == 4
    assert first["course_task_doc_id"].startswith("ctd-") and first["goals"][0]["pass_criteria"].endswith("（教师修订）")

    status, body = api.call("GET", f"/api/v1/demo2/course-tasks?course_id={COURSE}", a)
    assert status == 200 and body["current"]["version"] == 1 and len(body["versions"]) == 1
    status, body = api.call("GET", f"/api/v1/demo2/upload/workspace?course_id={COURSE}", a)
    assert status == 200 and body["workspace"]["course_task"]["version"] == 1

    doc_id = first["course_task_doc_id"]
    status, body = api.call("GET", f"/api/v1/demo2/course-tasks/document?course_task_doc_id={doc_id}", b)
    assert status == 403 and body["error"]["code"] == "course_task_forbidden"
    status, _, _ = api.raw_get(f"/api/v1/demo2/course-tasks/original?course_task_doc_id={doc_id}", b)
    assert status == 403
    status, body = api.call("GET", "/api/v1/demo2/course-tasks/document?course_task_doc_id=ctd-" + "0" * 32, a)
    assert status == 404

    status, body = api.call("GET", f"/api/v1/demo2/course-tasks/document?course_task_doc_id={doc_id}", admin)
    assert status == 200 and body["course_task"]["notes"] == [] and len(body["course_task"]["goals"]) == 4
    assert "owner_account_id" not in body["course_task"]
    status, headers, data = api.raw_get(f"/api/v1/demo2/course-tasks/original?course_task_doc_id={doc_id}", admin)
    assert status == 200 and data == samples.pdf and headers["Content-Type"] == "application/pdf"
    status, headers, data = api.raw_get(f"/api/v1/demo2/course-tasks/summary?course_task_doc_id={doc_id}", admin)
    text = data.decode("utf-8")
    assert status == 200 and "G-04" in text and "IEP" in text and "导入" not in text

    # A second confirmation is a new version; the first stays readable but superseded.
    stale = _confirm_payload(_draft(api, a, samples.pdf), expected_version=0)
    status, body = api.post("/api/v1/demo2/course-tasks/confirm", a, stale)
    assert status == 409 and body["error"]["code"] == "course_task_version_conflict"
    status, body = api.post("/api/v1/demo2/course-tasks/confirm", a, {**stale, "expected_version": 1})
    assert status == 201 and body["course_task"]["version"] == 2
    status, body = api.call("GET", f"/api/v1/demo2/course-tasks/document?course_task_doc_id={doc_id}", a)
    assert body["course_task"]["status"] == "superseded" and body["course_task"]["goal_count"] == 4

    lines = _course_lines(api.course_logs)
    operations = [line["operation"] for line in lines]
    assert {"course_task_confirm", "course_task_version", "course_task_read", "course_task_download",
            "course_task_rejected"} <= set(operations)
    version_line = next(line for line in lines if line["operation"] == "course_task_version")
    assert version_line["version"] == 2 and version_line["previous_doc_short"] == doc_id[4:12]
    assert all("course_task_doc_id" not in line for line in lines)
    dumped = json.dumps(lines, ensure_ascii=False)
    assert "人民币" not in dumped and "等待轮到自己" not in dumped


def test_goal_with_roster_name_or_phone_cannot_be_confirmed(api, samples):
    a = api.env.tokens["a"]
    draft = _draft(api, a, samples.pdf)
    goals = [dict(g) for g in draft["goals"]]
    goals[1]["description"] = "虚构同名学生能在提示下用1元购买一件物品。"
    status, body = api.post("/api/v1/demo2/course-tasks/confirm", a, _confirm_payload(draft, goals=goals))
    assert status == 400 and body["error"]["code"] == "goal_contains_student_name"
    assert body["error"]["field"] == "goals.1.description"
    goals[1]["description"] = "能在提示下购买物品，家长电话13812345678。"
    status, body = api.post("/api/v1/demo2/course-tasks/confirm", a, _confirm_payload(draft, goals=goals))
    assert status == 400 and body["error"]["code"] == "course_task_sensitive_content"
    status, body = api.call("GET", f"/api/v1/demo2/course-tasks?course_id={COURSE}", a)
    assert body["current"] is None
    rejected = [line for line in _course_lines(api.course_logs) if line["operation"] == "course_task_rejected"]
    assert rejected[-1]["code"] == "course_task_sensitive_content" and rejected[-1]["http_status"] == 400


def test_other_school_cannot_draft_from_foreign_parse(api, samples):
    status, body = api.upload(api.env.tokens["a"], "course_task", "课程任务.pdf", samples.pdf)
    parse_id = body["result"]["parse_id"]
    status, body = api.post("/api/v1/demo2/course-tasks/draft", api.env.tokens["b"], {"parse_id": parse_id})
    assert status == 403 and body["error"]["code"] == "parse_forbidden"


def test_word_original_keeps_docx_extension(api):
    a = api.env.tokens["a"]
    data = build_course_docx()
    status, body = api.upload(a, "course_task", "课程任务.docx", data)
    assert status == 200, body
    status, body = api.post("/api/v1/demo2/course-tasks/draft", a, {"parse_id": body["result"]["parse_id"]})
    draft = body["draft"]
    assert [g["goal_code"] for g in draft["goals"]] == ["G-01", "G-02", "G-03"]
    status, body = api.post("/api/v1/demo2/course-tasks/confirm", a, _confirm_payload(draft))
    assert status == 201 and body["course_task"]["original_extension"] == ".docx"
    status, headers, raw = api.raw_get(
        f"/api/v1/demo2/course-tasks/original?course_task_doc_id={body['course_task']['course_task_doc_id']}", a)
    assert status == 200 and raw == data and "wordprocessingml" in headers["Content-Type"]
    assert ".docx" in headers["Content-Disposition"]


# ---------------------------------------------------------------------------
# evaluation, report chapter and stale rule (no vault needed)
# ---------------------------------------------------------------------------

GOALS = [
    {"goal_code": "G-01", "description": "能认出三种人民币。", "pass_criteria": "3次中正确2次",
     "measurement_conditions": "模拟超市，口头提示", "evaluation_criteria": "", "rubric_dimension": "process"},
    {"goal_code": "G-02", "description": "能按分层任务完成购买。", "pass_criteria": "1次提示内完成",
     "measurement_conditions": "模拟超市", "evaluation_criteria": "", "rubric_dimension": "goals"},
]


@pytest.fixture
def evaluation_env(tmp_path, monkeypatch):
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "CourseTask-")
    monkeypatch.setenv("REHAB_DEMO2_EVALUATION_DEBUG_LOG_DIR", str(tmp_path / "eval_logs"))
    monkeypatch.setenv(course_tasks.DEBUG_LOG_DIR_ENV, str(tmp_path / "course_logs"))
    records = Demo2StudentRecordStore(tmp_path / "ct.sqlite3", tmp_path / "documents")
    tokens, accounts = {}, {}
    for alias, name, school in (("a", "school_uploader_01", "合成学校"), ("b", "school_uploader_02", "另一合成学校")):
        account = records.authenticate_account(name, "CourseTask-" + name)
        tokens[alias] = records.create_account_session(account)["token"]
        accounts[alias] = account
        records.save_account_school_context(tokens[alias], dict(city="测试市", district="测试区", school_name=school))

    def insert(owner="a", version=1, status="confirmed", doc_id=None, course=COURSE):
        doc_id = doc_id or f"ctd-{version:032x}"
        with records._connect() as db:
            course_tasks.ensure_schema(db)
            db.execute(
                "INSERT INTO demo2_course_task_documents (course_task_doc_id, course_id, owner_account_id, version, status, "
                "original_path, original_extension, original_sha256, byte_size, parse_id, course_name, goal_count, "
                "goals_json, created_at, confirmed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (doc_id, course, accounts[owner]["account_id"], version, status, "x", ".pdf", "0" * 64, 1,
                 "dp-" + "0" * 32, "合成课程", len(GOALS), json.dumps({"goals": GOALS, "notes": []}, ensure_ascii=False),
                 "2026-10-31T00:00:00+00:00", "2026-10-31T00:00:00+00:00"))
        return doc_id

    return SimpleNamespace(records=records, tokens=tokens, accounts=accounts, insert=insert,
                           store=Demo2EvaluationStore(records), course_logs=tmp_path / "course_logs")


def _evaluation(**changes):
    items = [dict(id=f"i{i}", school_score=8, enhanced_score=None, evidence="合成观察 00:20", reason="", suggestion="")
             for i in range(1, 11)]
    items[6].update(enhanced_score=9, reason="按课程任务目标复核", suggestion="")
    payload = dict(record_id="course-task-eval-1", expected_version=0, lesson_id=COURSE,
                   lesson_date=date.today().isoformat(), course_name="合成课程", subject_id="math",
                   template_id="basic_100", goal_context="G-01 能认出三种人民币。\nG-02 能按分层任务完成购买。",
                   school_source="teacher_recorded", school_rater="合成复核员", reviewed=False, items=items,
                   course_id=COURSE)
    payload.update(changes)
    return payload


def test_evaluation_binds_course_task_without_changing_scores(evaluation_env):
    env = evaluation_env
    doc_id = env.insert()
    plain = env.store.preview(env.tokens["a"], _evaluation())
    linked = env.store.preview(env.tokens["a"], _evaluation(course_task_doc_id=doc_id))
    assert {k: v for k, v in linked.items() if not k.startswith("course_task")} == plain
    assert {k: v for k, v in plain.items() if k != "evaluation_id"} == evaluate(
        {k: v for k, v in _evaluation().items() if k != "course_id"})
    basis = linked["course_task_goal_basis"]
    assert [b["goal_code"] for b in basis] == ["G-01", "G-02"]
    assert basis[0]["item_ids"] == ["i6", "i7", "i8"] and "增强分9分" in basis[0]["basis_text"]
    assert basis[1]["item_ids"] == ["i1", "i2"]

    saved = env.store.save(env.tokens["a"], _evaluation(course_task_doc_id=doc_id))
    assert saved["course_task_doc_id"] == doc_id and saved["course_task_version"] == 1
    with env.records._connect() as db:
        stored = json.loads(db.execute("SELECT payload_json FROM demo2_classroom_evaluations").fetchone()[0])
    assert env.store._public(stored) == saved and stored["course_task_goal_basis"] == saved["course_task_goal_basis"]
    with pytest.raises(MeasurementError) as error:
        env.store.save(env.tokens["a"], _evaluation(expected_version=1, course_task_doc_id=""))
    assert error.value.code == "configuration_locked"
    lines = _course_lines(env.course_logs)
    assert lines[-1]["operation"] == "course_task_link_evaluation" and lines[-1]["goal_count"] == 2
    assert "人民币" not in json.dumps(lines, ensure_ascii=False)


def test_evaluation_rejects_foreign_superseded_or_mismatched_course_task(evaluation_env):
    env = evaluation_env
    foreign = env.insert(owner="b", doc_id="ctd-" + "b" * 32)
    old = env.insert(version=1, status="superseded")
    other_course = env.insert(version=3, doc_id="ctd-" + "c" * 32, course="another-course")
    for doc_id, code in ((foreign, "course_task_forbidden"), (old, "course_task_superseded"),
                         (other_course, "course_task_course_mismatch"), ("ctd-" + "d" * 32, "course_task_not_found")):
        with pytest.raises(MeasurementError) as error:
            env.store.preview(env.tokens["a"], _evaluation(course_task_doc_id=doc_id))
        assert error.value.code == code


def test_report_chapter_and_stale_rule(evaluation_env):
    env = evaluation_env
    doc_id = env.insert()
    with env.records._connect() as db:
        current = course_tasks.current_for_course(db, env.accounts["a"]["account_id"], COURSE)
    records = [{"record_id": "r1", "student_id": "s1", "goal_id": "g-01", "start_sec": 12.0, "end_sec": 32.0,
                "reviewed": True, "evidence_status": "current", "assessment": {"passed": True}},
               {"record_id": "r2", "student_id": "s2", "goal_id": "其他目标", "start_sec": 40.0, "end_sec": 50.0,
                "reviewed": True, "evidence_status": "current", "assessment": {"passed": False}}]
    built = course_tasks.build_course_task_section(current, records)
    assert built["section"]["title"] == "本课任务目标与达成情况" and doc_id in built["section"]["text"]
    goal1, goal2 = built["reference"]["goals"]
    assert goal1["segments"][0]["start_sec"] == 12.0 and goal1["achievement_status"] == "achieved"
    assert goal2["record_count"] == 0 and goal2["achievement_status"] == "no_evidence"
    reference = built["reference"]
    with env.records._connect() as db:
        owner = env.accounts["a"]["account_id"]
        assert course_tasks.course_task_stale_reasons(db, owner, COURSE, reference) == []
        assert course_tasks.course_task_stale_reasons(db, owner, COURSE, None) == [f"course_task_added:{doc_id}"]
        db.execute("UPDATE demo2_course_task_documents SET status='superseded'")
    newer = env.insert(version=2)
    with env.records._connect() as db:
        assert course_tasks.course_task_stale_reasons(db, owner, COURSE, reference) == [f"course_task_changed:{doc_id}"]
        assert course_tasks.current_for_course(db, owner, COURSE)["course_task_doc_id"] == newer
