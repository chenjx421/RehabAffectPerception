"""Teacher home page: loop steps, to-dos, recent tasks, access and debug log.

Synthetic accounts, students and videos only (fixtures from the dossier store
tests); no live services or real student data.
"""
from __future__ import annotations

import base64
import json
import re
from datetime import date, timedelta
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest

from rehab_affect import demo2_manager_gateway as gateway
from rehab_affect import scenario_lab_server as server
from rehab_affect import demo2_ui_kit as kit
from rehab_affect.demo2_home import (
    HomeSources, STEP_KEYS, build_home_summary, home_debug_event, render_home,
)
from rehab_affect.demo2_measurement_store import Demo2MeasurementStore
from rehab_affect.demo2_portal import render_demo2_upload_html
from rehab_affect.video_applicability import ApplicabilityStore
from test_demo2_dossier_store import authorize, day, document, env, reference, task, template  # noqa: F401

TEACHER = {"username": "school_uploader_01", "login_alias": "t1", "role": "school_uploader"}


def _sources(env, *, measurement_records=None, reports=None, applicability=None, evaluation_records=None):
    measurements = Demo2MeasurementStore(env.records)

    def measurement(method, *args):
        if method == "workspace" and measurement_records is not None:
            return {"records": measurement_records}
        return getattr(measurements, method)(*args)

    def report(method, token, task_id):
        return {"reports": (reports or {}).get(task_id, [])}

    def applicability_call(method, token, task_id):
        if applicability is not None:
            return applicability.get(task_id, {"category": "pending"})
        return getattr(ApplicabilityStore(env.records), method)(token, task_id)

    return HomeSources(identity=lambda method, *args: getattr(env.identities, method)(*args),
                       measurement=measurement, evaluation=lambda method, *args: {"records": list(evaluation_records or [])},
                       report=report, applicability=applicability_call)


def _fresh_token(env, username="school_uploader_04"):
    with env.records._connect() as connection:
        account_id = connection.execute("SELECT account_id FROM platform_accounts WHERE username = ?",
                                        (username,)).fetchone()[0]
    return env.records.create_account_session(account_id)["token"]


def _failed_task(env, owner="a"):
    content = b"synthetic failing bytes"
    created = env.records.create_video_task({
        "account_session_token": env.tokens[owner], "channel_id": env.accounts[owner]["bound_channel_id"],
        "session_id": "home-session", "course_id": "home-course", "course_name": "虚构失败课堂",
        "uploader_name": "测试", "filename": "broken.mp4", "byte_size": len(content), "total_chunks": 1})
    env.records.append_video_chunk({"account_session_token": env.tokens[owner], "task_id": created["task_id"],
                                    "chunk_index": 0, "content_base64": base64.b64encode(content).decode()})
    claim = env.records.claim_next_video_analysis()
    assert claim["task_id"] == created["task_id"]
    env.records.fail_video_analysis(created["task_id"], "processing_failed", "synthetic failure")
    return created["task_id"]


def _steps(summary):
    return {step["key"]: step for step in summary["steps"]}


def test_new_account_highlights_school_step_and_has_no_todos(env, tmp_path, monkeypatch):
    monkeypatch.setenv("REHAB_DEMO2_HOME_DEBUG_LOG_DIR", str(tmp_path / "logs"))
    token = _fresh_token(env)
    account = env.records.account_from_session(token)
    summary = build_home_summary(env.records, token, account, _sources(env))
    assert [step["key"] for step in summary["steps"]] == list(STEP_KEYS)
    steps = _steps(summary)
    assert steps["school"]["status"] == "not_started" and steps["school"]["action"]["href"] == "/demo2/school"
    assert summary["is_new_account"] is True
    assert summary["next_step"]["key"] == "school"
    assert all(step["status"] in {"not_started", "attention"} for step in summary["steps"])
    assert summary["todos"] == [] and summary["todo_total"] == 0
    assert summary["recent_tasks"] == []
    assert steps["roster"]["count"] == "名册 0 人"


def test_teacher_loop_reflects_real_data_and_todos(env, tmp_path, monkeypatch):
    monkeypatch.setenv("REHAB_DEMO2_HOME_DEBUG_LOG_DIR", str(tmp_path / "logs"))
    token = env.tokens["a"]
    account = env.records.account_from_session(token)
    a1, a2 = env.pupils["a1"]["student_id"], env.pupils["a2"]["student_id"]
    authorization = authorize(env, "a1", valid_until=day(10))
    document(env, "a1", authorization, retain_until=day(10))
    bound = task(env, "a1", bind=True)
    unbound = task(env, "a1", bind=False)
    failed_id = _failed_task(env)
    # Timestamps have second precision; spread them so upload order is explicit.
    with env.records._connect() as connection:
        for minutes, task_id in ((10, bound.task_id), (20, unbound.task_id), (30, failed_id)):
            connection.execute("UPDATE video_analysis_tasks SET created_at = ? WHERE task_id = ?",
                               ((date.today() - timedelta(days=1)).isoformat() + f"T10:{minutes:02d}:00+08:00", task_id))
    pending_record = {"record_id": "m1", "student_id": a2, "task_id": unbound.task_id, "lesson_date": day(-1),
                      "reviewed": False, "evidence_status": "current"}
    reviewed_record = {"record_id": "m2", "student_id": a1, "task_id": "", "lesson_date": day(-2),
                       "reviewed": True, "evidence_status": "current"}
    field_record = {"record_id": "m3", "student_id": a1, "task_id": "", "lesson_date": day(-3),
                    "reviewed": False, "evidence_status": "current"}
    reports = {bound.task_id: [{"report_id": "r-stale", "task_id": bound.task_id, "stale": True}]}
    applicability = {bound.task_id: {"category": "special"}, unbound.task_id: {"category": "pending"}}

    summary = build_home_summary(env.records, token, account,
                                 _sources(env, measurement_records=[pending_record, reviewed_record, field_record],
                                          reports=reports, applicability=applicability))
    steps = _steps(summary)
    assert steps["school"]["status"] == "done"
    assert steps["roster"]["status"] == "done" and steps["roster"]["count"] == "名册 2 人"
    assert steps["dossier"]["status"] == "in_progress"
    assert steps["dossier"]["count"] == "已授权 1/2 人 · IEP 1 人"
    assert steps["dossier"]["action"]["href"] == f"/demo2/dossier?student_id={a2}"
    assert steps["upload"]["status"] == "done"
    assert steps["upload"]["count"] == "已上传 3 个 · 分析完成 2 个"
    assert steps["identity"]["status"] == "in_progress"
    assert steps["identity"]["count"] == "待确认身份的任务 1 个"
    assert steps["identity"]["action"]["href"] == f"/demo2/identity?task_id={unbound.task_id}"
    assert steps["applicability"]["status"] == "in_progress"
    assert steps["applicability"]["action"]["href"] == f"/demo2/analysis?task_id={unbound.task_id}"
    assert steps["assessment"]["status"] == "in_progress"
    assert steps["report"]["status"] == "attention"
    assert summary["next_step"]["key"] == "dossier"
    assert summary["is_new_account"] is False

    kinds = {item["kind"]: item for item in summary["todos"]}
    assert summary["todo_counts"] == {"failed_tasks": 1, "course_task_uploads": 1, "iep_summaries": 0,
                                      "lesson_measurement_reviews": 1, "measurement_reviews": 1, "stale_reports": 1,
                                      "expiring_authorizations": 1, "course_evaluations": 0, "course_overviews": 0,
                                      "few_students": 0}
    assert kinds["failed_task"]["task_id"] == failed_id and f"task_id={failed_id}" in kinds["failed_task"]["action"]["href"]
    # Video-sourced pending records are grouped per lesson; field observations stay one per record.
    lesson = kinds["lesson_measurement_review"]
    assert lesson["text"].startswith("复核本课测量（1 条）") and lesson["count"] == 1
    assert lesson["action"]["href"] == (
        f"/demo2/measurement?student_id={a2}&task_id={unbound.task_id}&record_id=m1")
    assert kinds["measurement_review"]["action"]["href"] == f"/demo2/measurement?student_id={a1}"
    upload_todo = kinds["course_task_upload"]
    assert upload_todo["text"].startswith("上传课程任务文件") and "上传课程任务文件可自动带入课程目标" in upload_todo["text"]
    assert upload_todo["action"] == {"label": "上传课程任务文件", "href": "/demo2/upload?course_id=dossier-course"}
    assert "上传课程任务文件可自动带入课程目标" in steps["upload"]["detail"]
    assert steps["upload"]["secondary_action"]["label"] == "上传课程任务文件"
    assert kinds["stale_report"]["action"]["href"] == f"/demo2/analysis?task_id={bound.task_id}"
    assert kinds["expiring_authorization"]["action"]["href"] == f"/demo2/dossier?student_id={a1}"
    assert kinds["expiring_authorization"]["days_left"] == 10

    recent = summary["recent_tasks"]
    assert len(recent) == 3 and recent[0]["task_id"] == failed_id
    assert [item["created_at"] for item in recent] == sorted((item["created_at"] for item in recent), reverse=True)
    assert recent[0]["status_code"] == "failed"
    ready = next(item for item in recent if item["task_id"] == bound.task_id)
    assert ready["action"]["href"] == f"/demo2/simple-result?task_id={bound.task_id}"

    # Debug log: one line per load, step codes and counts, never student or course names.
    lines = [json.loads(line) for path in (tmp_path / "logs").glob("home_debug_*.jsonl")
             for line in path.read_text(encoding="utf-8").splitlines()]
    entry = lines[-1]
    assert entry["operation"] == "home_load" and entry["account_id"] == account["account_id"]
    assert entry["step_status"]["dossier"] == "in_progress" and entry["todo_total"] == 6
    assert entry["new_todo_counts"] == {"course_task_uploads": 1, "iep_summaries": 0, "lesson_measurement_reviews": 1}
    assert entry["v4_todo_counts"] == {"course_evaluations": 0, "course_overviews": 0, "few_students": 0}
    assert isinstance(entry["elapsed_ms"], (int, float)) and entry["ts"]
    raw = "".join(path.read_text(encoding="utf-8") for path in (tmp_path / "logs").glob("*.jsonl"))
    assert "虚构同名学生" not in raw and "虚构课堂" not in raw and "虚构失败课堂" not in raw


def test_other_school_data_never_appears(env, tmp_path, monkeypatch):
    monkeypatch.setenv("REHAB_DEMO2_HOME_DEBUG_LOG_DIR", str(tmp_path / "logs"))
    authorize(env, "a1", valid_until=day(5))
    video = task(env, "a1", bind=True)
    token = env.tokens["b"]
    summary = build_home_summary(env.records, token, env.records.account_from_session(token), _sources(env))
    assert video.task_id not in json.dumps(summary)
    assert summary["recent_tasks"] == [] and summary["todo_counts"]["expiring_authorizations"] == 0
    assert _steps(summary)["roster"]["count"] == "名册 1 人"


def test_failing_section_is_marked_attention_and_logged(env, tmp_path, monkeypatch):
    monkeypatch.setenv("REHAB_DEMO2_HOME_DEBUG_LOG_DIR", str(tmp_path / "logs"))
    sources = _sources(env)

    def broken(method, *args):
        raise RuntimeError("store down")

    sources.identity = broken
    token = env.tokens["a"]
    summary = build_home_summary(env.records, token, env.records.account_from_session(token), sources)
    assert _steps(summary)["roster"]["status"] == "attention"
    assert "roster" in summary["errors"]
    entry = json.loads(next((tmp_path / "logs").glob("home_debug_*.jsonl")).read_text().splitlines()[-1])
    assert entry["result"] == "partial" and entry["errors"]["roster"] == "RuntimeError"


def test_debug_event_drops_unsafe_values(tmp_path, monkeypatch):
    monkeypatch.setenv("REHAB_DEMO2_HOME_DEBUG_LOG_DIR", str(tmp_path))
    entry = home_debug_event(object(), "home_load", "ok", account_id="张三", step_status={"school": "done"},
                             todo_counts={"failed_tasks": 2}, elapsed_ms=3.5)
    assert entry["account_id"] == "<invalid>" and entry["todo_counts"] == {"failed_tasks": 2}


def test_home_page_markup_and_navigation():
    assert kit.TEACHER_HOME_URL == "/demo2/home"
    html = render_home(TEACHER)
    assert re.findall(r'data-rx-nav-key="(\w+)" aria-current="page"', html) == ["home"]
    assert 'href="/demo2/home" id="rxNavHome"' in html
    for element_id in ("loopSteps", "todoList", "recentList", "homeSchool", "homeAccount", "homeToday", "homeNext"):
        assert f'id="{element_id}"' in html
    assert "目前没有需要处理的事项" in html
    ids = re.findall(r'\sid="([^"]+)"', html)
    assert len(ids) == len(set(ids))
    assert not re.search(r"<script[^>]+src=", html)


def test_upload_page_has_dismissible_next_step_banner():
    html = render_demo2_upload_html(TEACHER)
    assert 'id="nextStepBanner"' in html and 'id="nextStepClose"' in html
    assert "sessionStorage" in html and "rx_next_step_dismissed" in html
    # The banner script is tagged so harnesses evaluating bare <script> blocks skip it.
    assert "/home/summary" not in "\n".join(re.findall(r"<script>(.*?)</script>", html, re.S))


def test_gateway_admits_home_routes():
    assert "/demo2/home" in gateway._PAGES
    assert "/api/v1/demo2/home/summary" in gateway._GET_API
    assert "/api/v1/demo2/home/summary" not in gateway._POST_API


@pytest.fixture
def http_env(env, monkeypatch, tmp_path):
    monkeypatch.setenv("REHAB_DEMO2_HOME_DEBUG_LOG_DIR", str(tmp_path / "home_logs"))
    monkeypatch.setattr(server, "get_demo2_student_store", lambda: env.records)
    handler = server.create_handler(scenario_dir=Path("configs/scenarios"),
                                    model_path=server.DEFAULT_LEARNED_POLICY_PATH, policy_name="rule")
    http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()

    def request(path, token=None):
        headers = {"Connection": "close"}
        if token:
            headers["Cookie"] = "rehab_demo2_session=" + token
        conn = HTTPConnection("127.0.0.1", http.server_port, timeout=20)
        try:
            conn.request("GET", path, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            body = json.loads(raw) if "json" in response.getheader("Content-Type", "") else raw.decode("utf-8", "replace")
            return response.status, dict(response.getheaders()), body
        finally:
            conn.close()

    yield SimpleNamespace(request=request, env=env, logs=tmp_path / "home_logs")
    http.shutdown()
    http.server_close()
    thread.join(3)


def test_http_access_rules(http_env):
    request, env = http_env.request, http_env.env
    status, headers, _ = request("/demo2/home")
    assert status == 302 and headers["Location"] == "/demo2/login"
    status, headers, _ = request("/demo2/home", env.tokens["admin"])
    assert status == 302 and headers["Location"] == "/demo2/admin"
    status, headers, _ = request("/demo2/home", env.tokens["member"])
    assert status == 302 and headers["Location"] == "/demo2/membership"
    status, headers, html = request("/demo2/home", env.tokens["a"])
    assert status == 200 and "no-store" in headers["Cache-Control"] and 'id="loopSteps"' in html
    assert request("/api/v1/demo2/home/summary")[0] == 401
    assert request("/api/v1/demo2/home/summary", env.tokens["admin"])[0] == 403
    assert request("/api/v1/demo2/home/summary?x=1", env.tokens["a"])[0] == 400
    opened = [json.loads(line) for path in http_env.logs.glob("home_debug_*.jsonl")
              for line in path.read_text(encoding="utf-8").splitlines()]
    assert {entry["result"] for entry in opened if entry["operation"] == "home_page_open"} >= {
        "ok", "redirect_admin", "redirect_member"}


def test_http_summary_uses_real_stores(http_env):
    request, env = http_env.request, http_env.env
    video = task(env, "a1", bind=True)
    status, _, body = request("/api/v1/demo2/home/summary", env.tokens["a"])
    assert status == 200 and body["ok"] is True
    home = body["home"]
    steps = _steps(home)
    assert steps["upload"]["status"] == "done"
    assert steps["identity"]["status"] == "done"
    assert steps["applicability"]["status"] == "not_started"
    assert home["recent_tasks"][0]["task_id"] == video.task_id
    assert home["errors"] == []
    status, _, other = request("/api/v1/demo2/home/summary", env.tokens["b"])
    assert status == 200 and video.task_id not in json.dumps(other)
    fresh = _fresh_token(env)
    status, _, new_home = request("/api/v1/demo2/home/summary", fresh)
    assert status == 200 and new_home["home"]["next_step"]["key"] == "school"
    assert _steps(new_home["home"])["school"]["status"] == "not_started"


def test_identity_step_waits_for_lesson_iep_link_when_student_has_iep(env, tmp_path, monkeypatch):
    """Following only the home guide must end with the IEP linked to the lesson
    (school_id -> student_id -> iep_document_id chain), not just confirmed faces."""
    monkeypatch.setenv("REHAB_DEMO2_HOME_DEBUG_LOG_DIR", str(tmp_path / "logs"))
    token = env.tokens["a"]
    account = env.records.account_from_session(token)
    authorization = authorize(env, "a1")
    iep = document(env, "a1", authorization)
    video = task(env, "a1", bind=True)

    steps = _steps(build_home_summary(env.records, token, account, _sources(env)))
    assert steps["identity"]["status"] == "in_progress"
    assert steps["identity"]["count"] == "待确认身份的任务 0 个"
    assert "1 位学生未关联本课 IEP" in steps["identity"]["detail"]
    assert steps["identity"]["action"] == {"label": "关联本课 IEP",
                                           "href": f"/demo2/course-dossier?task_id={video.task_id}"}

    linked = reference(env, video, [iep])
    steps = _steps(build_home_summary(env.records, token, account, _sources(env)))
    assert steps["identity"]["status"] == "done"
    assert steps["identity"]["action"]["href"] == f"/demo2/identity?task_id={video.task_id}"

    env.store.withdraw_reference(token, {"reference_id": linked["reference_id"], "confirmed": True})
    steps = _steps(build_home_summary(env.records, token, account, _sources(env)))
    assert steps["identity"]["status"] == "in_progress"
    assert steps["identity"]["action"]["label"] == "关联本课 IEP"


def _confirm_course_task(env, owner, course_id):
    from rehab_affect import demo2_course_task_store as course_tasks
    account = env.records.account_from_session(env.tokens[owner])
    with env.records._connect() as connection:
        course_tasks.ensure_schema(connection)
        connection.execute(
            """INSERT INTO demo2_course_task_documents (course_task_doc_id, course_id, owner_account_id, version, status,
               original_path, original_extension, original_sha256, byte_size, parse_id, goal_count, goals_json,
               created_at, confirmed_at) VALUES (?, ?, ?, 1, 'confirmed', 'x', 'pdf', 'x', 1, 'p', 1, '[]', ?, ?)""",
            ("ctd_home_" + owner, course_id, account["account_id"], day(-1), day(-1)))


def test_course_task_and_iep_summary_todos(env, tmp_path, monkeypatch):
    """No course-task file -> upload hint + to-do; a confirmed student without IEP -> 补充 IEP 支持摘要."""
    monkeypatch.setenv("REHAB_DEMO2_HOME_DEBUG_LOG_DIR", str(tmp_path / "logs"))
    token = env.tokens["a"]
    account = env.records.account_from_session(token)
    a2 = env.pupils["a2"]["student_id"]
    task(env, "a2", bind=True)

    summary = build_home_summary(env.records, token, account, _sources(env))
    kinds = {item["kind"]: item for item in summary["todos"]}
    assert summary["todo_counts"]["iep_summaries"] == 1
    assert kinds["iep_summary_missing"]["text"].startswith("补充 IEP 支持摘要")
    assert kinds["iep_summary_missing"]["action"] == {"label": "补充 IEP 支持摘要",
                                                      "href": f"/demo2/dossier?student_id={a2}"}
    assert summary["todo_counts"]["course_task_uploads"] == 1
    assert "上传课程任务文件可自动带入课程目标" in _steps(summary)["upload"]["detail"]

    # Once the course task is confirmed and the student has a usable IEP, both to-dos disappear.
    _confirm_course_task(env, "a", "dossier-course")
    authorization = authorize(env, "a2")
    document(env, "a2", authorization)
    summary = build_home_summary(env.records, token, account, _sources(env))
    assert summary["todo_counts"]["course_task_uploads"] == 0 and summary["todo_counts"]["iep_summaries"] == 0
    assert "上传课程任务文件可自动带入课程目标" not in _steps(summary)["upload"]["detail"]
    assert "secondary_action" not in _steps(summary)["upload"]
    raw = "".join(path.read_text(encoding="utf-8") for path in (tmp_path / "logs").glob("*.jsonl"))
    entries = [entry for entry in (json.loads(line) for line in raw.splitlines()) if entry.get("operation") == "home_load"]
    assert [entry["new_todo_counts"]["iep_summaries"] for entry in entries] == [1, 0]
    assert "虚构" not in raw


def test_lesson_measurement_review_groups_video_records_per_task(env, tmp_path, monkeypatch):
    monkeypatch.setenv("REHAB_DEMO2_HOME_DEBUG_LOG_DIR", str(tmp_path / "logs"))
    token = env.tokens["a"]
    account = env.records.account_from_session(token)
    a1, a2 = env.pupils["a1"]["student_id"], env.pupils["a2"]["student_id"]
    video = task(env, "a1", bind=True)
    records = [{"record_id": f"v{i}", "student_id": sid, "task_id": video.task_id, "lesson_date": day(-1),
                "reviewed": False, "evidence_status": "current", "source_type": "video"}
               for i, sid in enumerate((a1, a2, a1))]
    records.append({"record_id": "done", "student_id": a1, "task_id": video.task_id, "lesson_date": day(-1),
                    "reviewed": True, "evidence_status": "current", "source_type": "video"})
    summary = build_home_summary(env.records, token, account, _sources(env, measurement_records=records))
    lessons = [item for item in summary["todos"] if item["kind"] == "lesson_measurement_review"]
    assert len(lessons) == 1 and lessons[0]["count"] == 3
    assert lessons[0]["text"].startswith("复核本课测量（3 条）")
    assert lessons[0]["action"]["href"] == f"/demo2/measurement?student_id={a1}&task_id={video.task_id}&record_id=v0"
    assert summary["todo_counts"]["measurement_reviews"] == 0


def test_home_page_labels_new_todo_kinds():
    html = render_home(TEACHER)
    for kind in ("course_task_upload", "iep_summary_missing", "lesson_measurement_review"):
        assert kind + ":[" in html


def _report_with_conclusion(env, owner, task_id, report_id, *, available=True):
    from rehab_affect.demo2_report_store import Demo2ReportStore

    Demo2ReportStore(env.records)  # creates the table
    account = env.records.account_from_session(env.tokens[owner])
    conclusion = ({"available": True, "score": 82.4, "grade": {"key": "good", "label": "良好", "range": "70 ~ 84.9"}}
                  if available else {"available": False, "missing": [{"code": "course_evaluation_missing"}]})
    payload = {"report": {"course_overview": {"student_count": 3, "conclusion": conclusion}}}
    now = day(0)
    with env.records._connect() as connection:
        connection.execute(
            """INSERT INTO demo2_reports (report_id, owner_account_id, scope_key, task_id, frame_revision, payload_json,
               generated_at, created_at, updated_at) VALUES (?, ?, 'scope', ?, ?, ?, ?, ?, ?)""",
            (report_id, account["account_id"], task_id, report_id, json.dumps(payload, ensure_ascii=False), now, now, now))


def test_phase_four_todos_course_evaluation_overview_and_few_students(env, tmp_path, monkeypatch):
    monkeypatch.setenv("REHAB_DEMO2_HOME_DEBUG_LOG_DIR", str(tmp_path / "logs"))
    token = env.tokens["a"]
    account = env.records.account_from_session(token)
    a1, a2 = env.pupils["a1"]["student_id"], env.pupils["a2"]["student_id"]
    lesson = task(env, "a1", bind=True)
    other = task(env, "a2", bind=True)
    reviewed = [{"record_id": f"r{i}", "student_id": sid, "task_id": lesson.task_id, "lesson_date": day(-1),
                 "reviewed": True, "evidence_status": "current"} for i, sid in enumerate((a1, a2))]
    # A reconfirmation-needed record does not count as reviewed evidence for course evaluation.
    stale_record = {"record_id": "rx", "student_id": a2, "task_id": other.task_id, "lesson_date": day(-1),
                    "reviewed": True, "evidence_status": "needs_reconfirmation"}
    _report_with_conclusion(env, "a", lesson.task_id, "rep_good")
    _report_with_conclusion(env, "a", other.task_id, "rep_none", available=False)
    reports = {lesson.task_id: [{"report_id": "rep_good", "task_id": lesson.task_id, "stale": False}],
               other.task_id: [{"report_id": "rep_none", "task_id": other.task_id, "stale": False}]}
    counts = {lesson.task_id: 5, other.task_id: 1}
    monkeypatch.setattr(env.records, "account_person_filter_view",
                        lambda tok, task_id: {"person_filter_summary": {"student_count": counts[task_id]}}, raising=False)

    summary = build_home_summary(env.records, token, account,
                                 _sources(env, measurement_records=reviewed + [stale_record], reports=reports))
    kinds = {}
    for item in summary["todos"]:
        kinds.setdefault(item["kind"], []).append(item)
    assert summary["todo_counts"]["course_evaluations"] == 1
    evaluation = kinds["course_evaluation_missing"][0]
    assert evaluation["task_id"] == lesson.task_id and evaluation["count"] == 2
    assert evaluation["text"].startswith("做课程评价") and "2 条" in evaluation["text"]
    assert evaluation["action"] == {"label": "去做课程评价", "href": f"/demo2/evaluation?task_id={lesson.task_id}"}
    assert summary["todo_counts"]["course_overviews"] == 1
    overview = kinds["course_overview_ready"][0]
    assert overview["task_id"] == lesson.task_id and overview["grade"] == "good" and "良好" in overview["text"]
    assert overview["action"] == {"label": "查看课程总览", "href": f"/demo2/course-overview?task_id={lesson.task_id}"}
    assert summary["todo_counts"]["few_students"] == 1
    few = kinds["few_students_detected"][0]
    assert few["task_id"] == other.task_id and few["student_count"] == 1
    assert few["action"] == {"label": "管理本课检测学生",
                             "href": f"/demo2/simple-result?task_id={other.task_id}#detectionPanel"}
    steps = _steps(summary)
    assert steps["assessment"]["title"] == "学生测量 / 课程评价"
    # Pending reconfirmation comes first; once every measurement is reviewed the step points at course evaluation.
    assert steps["assessment"]["status"] == "in_progress"
    assert steps["assessment"]["action"]["href"] == "/demo2/measurement"
    steps = _steps(build_home_summary(env.records, token, account,
                                      _sources(env, measurement_records=reviewed, reports=reports)))
    assert steps["assessment"]["status"] == "in_progress" and steps["assessment"]["action"]["label"] == "做课程评价"
    assert steps["assessment"]["action"]["href"] == f"/demo2/evaluation?task_id={lesson.task_id}"

    # A teacher-checked basic_100 evaluation clears the to-do; a stale report hides the conclusion;
    # restoring students to 3 clears the few-students to-do.
    checked = {"evaluation_id": "evaluation-1", "task_id": lesson.task_id, "template_id": "basic_100",
               "reviewed": True, "result": {"status": "reviewed"}}
    draft = {"evaluation_id": "evaluation-2", "task_id": other.task_id, "template_id": "basic_100",
             "reviewed": False, "result": {"status": "draft"}}
    reports[lesson.task_id][0]["stale"] = True
    counts[other.task_id] = 3
    summary = build_home_summary(env.records, token, account,
                                 _sources(env, measurement_records=reviewed, reports=reports,
                                          evaluation_records=[checked, draft]))
    assert summary["todo_counts"]["course_evaluations"] == 0
    assert summary["todo_counts"]["course_overviews"] == 0
    assert summary["todo_counts"]["few_students"] == 0
    assert _steps(summary)["assessment"]["status"] == "done"

    entries = [json.loads(line) for path in (tmp_path / "logs").glob("home_debug_*.jsonl")
               for line in path.read_text(encoding="utf-8").splitlines()]
    loads = [entry for entry in entries if entry["operation"] == "home_load"]
    assert [entry["v4_todo_counts"] for entry in loads] == [
        {"course_evaluations": 1, "course_overviews": 1, "few_students": 1},
        {"course_evaluations": 1, "course_overviews": 1, "few_students": 1},
        {"course_evaluations": 0, "course_overviews": 0, "few_students": 0}]
    assert all(entry["ts"] and entry["result"] in {"ok", "partial"} for entry in loads)
    raw = "".join(path.read_text(encoding="utf-8") for path in (tmp_path / "logs").glob("*.jsonl"))
    assert "虚构" not in raw and "良好" not in raw


def test_few_students_check_failure_is_isolated(env, tmp_path, monkeypatch):
    monkeypatch.setenv("REHAB_DEMO2_HOME_DEBUG_LOG_DIR", str(tmp_path / "logs"))
    token = env.tokens["a"]
    account = env.records.account_from_session(token)
    task(env, "a1", bind=True)

    def broken(tok, task_id):
        raise OSError("disk unavailable")

    monkeypatch.setattr(env.records, "account_person_filter_view", broken, raising=False)
    summary = build_home_summary(env.records, token, account, _sources(env))
    assert summary["todo_counts"]["few_students"] == 0 and "few_students" in summary["errors"]
    assert [step["key"] for step in summary["steps"]] == list(STEP_KEYS)


def test_home_page_labels_phase_four_todo_kinds():
    html = render_home(TEACHER)
    for kind in ("course_evaluation_missing", "course_overview_ready", "few_students_detected"):
        assert kind + ":[" in html
