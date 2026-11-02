"""课程总览（系统大纲）：结论分口径、等级阈值、数据不完整、管理员化名与访问控制（调整意见第 3 条）。

只用合成任务、虚构学生与虚构课程任务目标。
"""
from __future__ import annotations

import json
import re

import pytest

from rehab_affect.assessment_rubric import (
    COURSE_GRADE_WEIGHTS,
    course_conclusion_score,
    course_grade,
    rubric_contract,
)
from rehab_affect.classroom_rubric import evaluate
from rehab_affect.demo2_course_overview import (
    OverviewError,
    SECTION_SOURCE,
    SECTION_TITLE,
    admin_view,
    build_overview,
    check_task_access,
    overview_section,
    render_course_overview,
)
from rehab_affect.demo2_course_page import render_course_analysis
from rehab_affect.demo2_report_store import ReportError

from test_demo2_evaluation_store import payload as evaluation_payload


TEACHER = {"role": "school_uploader", "username": "t1", "account_id": "acc-t1"}
ADMIN = {"role": "company_admin", "username": "admin", "account_id": "acc-admin"}
DIMS = ("accuracy", "independence", "consistency", "transfer")
SCHOOL_SCORES = [9, 5, 8, 7, 9, 8, 9, 6, 7, 4]  # i1..i10, raw total 72


# ------------------------------------------------------------------ grade rule

@pytest.mark.parametrize("score,label", [
    (59.9, "待改进"), (60, "合格"), (69.9, "合格"), (70, "良好"), (84.9, "良好"), (85, "优秀"),
    (0, "待改进"), (100, "优秀"),
])
def test_grade_band_boundaries(score, label):
    assert course_grade(score)["label"] == label


def test_grade_rejects_invalid_and_keeps_none():
    assert course_grade(None) is None
    for bad in (-0.1, 100.1, float("nan"), True, "80"):
        with pytest.raises(ValueError):
            course_grade(bad)


@pytest.mark.parametrize("total,attainment,expected,label", [
    (80, 72.5, 77.0, "良好"),     # 48 + 29
    (99.9, 99.9, 99.9, "优秀"),
    (60, 59.75, 59.9, "待改进"),  # attainment rounds to 59.8 → 36 + 23.92 = 59.92 → 59.9
    (100, 25, 70.0, "良好"),      # 60 + 10
    (85, 85, 85.0, "优秀"),
])
def test_conclusion_score_formula(total, attainment, expected, label):
    result = course_conclusion_score(total, attainment)
    assert result["score"] == expected and result["grade"]["label"] == label
    assert result["course_weight"] == COURSE_GRADE_WEIGHTS["course_evaluation"] == 0.6
    assert result["attainment_weight"] == COURSE_GRADE_WEIGHTS["student_attainment"] == 0.4
    assert abs(result["course_part"] + result["attainment_part"] - result["score"]) <= 0.05 + 1e-9
    assert result["text"].startswith("结论分 = 课程评价总分")


def test_contract_states_trial_thresholds():
    grade = rubric_contract()["course_grade"]
    assert grade["trial"] is True and "试行" in grade["note"]
    assert [(b["label"], b["min"]) for b in grade["bands"]] == [("优秀", 85), ("良好", 70), ("合格", 60), ("待改进", 0)]
    assert [w["weight_percent"] for w in grade["weights"]] == [60, 40]


# --------------------------------------------------------------- pure overview

def _record(rid, sid, goal, overall, *, reviewed=True, video=False, scores=None):
    record = {"record_id": rid, "student_id": sid, "goal_id": goal, "version": 1, "reviewed": reviewed,
              "evidence_status": "current", "lesson_date": "2026-10-31",
              "scores": scores or {k: overall for k in DIMS},
              "assessment": {"overall_score": overall if reviewed else None},
              "source_type": "video" if video else "video_review"}
    if video:
        record["video_metrics"] = {"engaged_segments": 2, "low_response_segments": 1}
        record["evidence_segments"] = [
            {"start_sec": 0, "end_sec": 20, "state": "engaged"},
            {"start_sec": 20, "end_sec": 40, "state": "low_response"},
            {"start_sec": 40, "end_sec": 60, "state": "engaged"}]
    return record


def _workspace(*, third_reviewed=True):
    people = [{"student_id": f"s{n}", "display_name": name, "student_code": f"QA-{n}", "class_name": "测试班"}
              for n, name in ((1, "虚构甲"), (2, "虚构乙"), (3, "虚构丙"))]
    records = [
        _record("r1", "s1", "G-01", 8.0), _record("r2", "s1", "G-02", 7.0),
        _record("r3", "s2", "G-01", 6.5), _record("r4", "s2", "G-02", 5.0),
        _record("r5", "s3", "G-01", 4.0, reviewed=third_reviewed),
        _record("v1", "s1", "G-01", None, reviewed=False, video=True),
        _record("v2", "s2", "G-01", None, reviewed=False, video=True),
    ]
    return {"task_id": "task-overview-1", "course_id": "course-1", "course_name": "合成分类课",
            "school_context": {"school_name": "虚构辅读学校"}, "media": {"duration_sec": 60},
            "people": people, "records": records,
            "course_task": {"course_task_doc_id": "ctd-" + "3" * 32, "course_task_doc_short": "33333333",
                            "version": 2, "lesson_date": "2026-10-31",
                            "goals": [{"goal_code": "G-01", "description": "按颜色分类（虚构）", "pass_criteria": "3次中2次"},
                                      {"goal_code": "G-02", "description": "回应提问（虚构）", "pass_criteria": ""}]},
            "applicability": {"confirmed_for_source": True}}


def _evaluation(*, reviewed=True, course=True):
    items = [dict(id=f"i{n}", school_score=SCHOOL_SCORES[n - 1], enhanced_score=SCHOOL_SCORES[n - 1] - 0.5,
                  evidence="课堂观察 00:20（虚构）", reason="复核调整", suggestion="下一课增加机会")
             for n in range(1, 11)]
    result = evaluate(evaluation_payload(items=items, reviewed=reviewed))
    value = {"evaluation_id": "evaluation-ov-1", "template_id": "basic_100", "reviewed": reviewed,
             "result": result, "updated_at": "2026-10-31T10:00:00+08:00", "version": 1}
    if course:
        value["course_evaluation"] = {"items": [], "fingerprint": {"fingerprint": "x"}}
    return value


def test_complete_lesson_has_grade_highlights_and_matrix():
    work = _workspace()
    overview = build_overview(work, [_evaluation()])
    conclusion = overview["conclusion"]
    assert conclusion["available"] is True and conclusion["missing"] == []
    # s1: (8+7)/2=7.5→75; s2: (6.5+5)/2=5.75→57.5; s3: 4→40 → mean 57.5
    rows = {r["student_id"]: r for r in overview["students"]}
    assert [rows[s]["attainment"] for s in ("s1", "s2", "s3")] == [75.0, 57.5, 40.0]
    assert overview["indicators"]["attainment_mean"] == 57.5
    assert overview["indicators"]["school_total_100"] == 72
    expected = course_conclusion_score(72, 57.5)
    assert conclusion["score"] == expected["score"] == 66.2 and conclusion["grade"]["label"] == "合格"
    assert conclusion["formula"]["course_part"] == 43.2 and conclusion["formula"]["attainment_part"] == 23.0
    assert len(conclusion["strengths"]) == 3 and len(conclusion["improvements"]) == 3
    for entry in conclusion["strengths"] + conclusion["improvements"]:
        assert entry["text"] and entry["basis"]["lines"] and entry["basis"]["href"].startswith("#ov-")
    keys = {e["kind"] + e["key"] for e in conclusion["strengths"]}
    assert not keys & {e["kind"] + e["key"] for e in conclusion["improvements"]}
    assert conclusion["improvements"][0]["value"] <= conclusion["strengths"][-1]["value"]
    # Indicators: 4 categories (school vs system), 10 items, goal table, coverage 2/3.
    assert len(overview["indicators"]["categories"]) == 4 and len(overview["indicators"]["items"]) == 10
    assert all(c["school"] is not None and c["system"] is not None for c in overview["indicators"]["categories"])
    goals = {g["goal_code"]: g for g in overview["indicators"]["goals"]}
    assert (goals["G-01"]["achieved"], goals["G-01"]["included"]) == (2, 3)
    assert (goals["G-02"]["achieved"], goals["G-02"]["included"]) == (1, 3)
    assert overview["indicators"]["coverage"]["participating"] == 2
    assert overview["completeness"]["reviewed"] == 5 and overview["completeness"]["expected"] == 6
    assert len(overview["students"]) == 3
    assert rows["s1"]["goals_achieved"] == 2 and rows["s1"]["goals_total"] == 2
    assert rows["s1"]["timeline"]["available"] and len(rows["s1"]["timeline"]["segments"]) == 3
    assert rows["s3"]["timeline"]["available"] is False
    assert rows["s1"]["measurement_href"] == "/demo2/measurement?student_id=s1"
    assert rows["s1"]["report_href"].endswith("record_id=r1#tab-report")
    section = overview_section(overview)
    assert section["title"] == SECTION_TITLE == "课程总览与结论" and section["source"] == SECTION_SOURCE
    assert "合格" in section["text"] and "虚构甲" in section["text"] and "主要优点" in section["text"]
    assert not re.search(r"[#*|`{}]", section["text"])


def test_unreviewed_evaluation_or_missing_measurement_gives_no_grade():
    overview = build_overview(_workspace(), [_evaluation(reviewed=False)])
    conclusion = overview["conclusion"]
    assert conclusion["available"] is False and conclusion["grade"] is None and conclusion["score"] is None
    assert [m["code"] for m in conclusion["missing"]] == ["course_evaluation_unreviewed"]
    assert conclusion["missing"][0]["href"] == "/demo2/evaluation?task_id=task-overview-1"
    assert conclusion["strengths"] == [] and conclusion["improvements"] == []

    overview = build_overview(_workspace(third_reviewed=False), [_evaluation()])
    missing = overview["conclusion"]["missing"]
    assert [m["code"] for m in missing] == ["measurement_review_required"]
    assert missing[0]["href"] == "/demo2/measurement?student_id=s3" and "虚构丙" in missing[0]["text"]

    overview = build_overview(_workspace(), [])
    assert [m["code"] for m in overview["conclusion"]["missing"]] == ["course_evaluation_missing"]
    overview = build_overview(_workspace(), [_evaluation()], stale=["measurements_changed"])
    assert [m["code"] for m in overview["conclusion"]["missing"]] == ["course_evaluation_stale"]
    assert overview["completeness"]["evaluation"]["label"] == "依据已变化，需重新核对"
    empty = build_overview({**_workspace(), "people": [], "records": []}, [_evaluation()])
    assert "students_missing" in [m["code"] for m in empty["conclusion"]["missing"]]
    blocked = build_overview({**_workspace(), "applicability": {"confirmed_for_source": False}}, [_evaluation()])
    assert blocked["conclusion"]["missing"][0]["code"] == "applicability_required"
    assert "暂无结论，还缺" in overview_section(overview)["text"]


def test_admin_view_drops_codes_links_and_teacher_text():
    data = admin_view(build_overview(_workspace(), [_evaluation()]))
    text = json.dumps(data, ensure_ascii=False)
    assert "QA-1" not in text and "测试班" not in text and "/demo2/measurement" not in text
    assert "/demo2/evaluation" not in text and "课堂观察 00:20" not in text
    assert data["viewer"] == "company_admin"


def test_pages_render_overview_first_and_keep_existing_tab_ids():
    html = render_course_analysis(TEACHER)
    tabs = re.findall(r'role="tab" id="(tab-[a-z]+)"', html)
    assert tabs == ["tab-overview", "tab-group", "tab-person", "tab-review", "tab-report"]
    assert 'id="tab-overview" aria-selected="true"' in html and 'id="ovRoot"' in html
    assert "tabHash({names:['overview','group','person','review','report']" in html
    assert "window.CourseOverview" in html and "__OVERVIEW" not in html
    for page in (render_course_overview(TEACHER), render_course_overview(ADMIN)):
        assert "svg.ov-chart{width:100%" in page and "svg.ov-timeline{" in page
        assert "/api/v1/demo2/course-overview" in page and "__OVERVIEW" not in page
        assert "WeGlow微光系统 · 课程总览" in page
    assert "viewer='company_admin'" in render_course_overview(ADMIN)
    assert "viewer='teacher'" in render_course_overview(TEACHER)


# ----------------------------------------------------------- integrated store

pytest.importorskip("docx")

from test_demo2_course_task import GOALS  # noqa: E402,F401
from test_demo2_dossier_store import day, env, task, template  # noqa: E402,F401
from test_demo2_iep_intake import service  # noqa: E402,F401
from test_demo2_measurement_link import flow  # noqa: E402,F401


def _log_lines(folder):
    return [json.loads(line) for path in sorted(folder.glob("report_debug_*.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_teacher_overview_snapshot_admin_alias_and_access(flow, monkeypatch, tmp_path):
    logs = tmp_path / "report_logs"
    monkeypatch.setenv("REHAB_DEMO2_REPORT_DEBUG_LOG_DIR", str(logs))
    flow.link.create_from_archive(flow.token, flow.archive)
    # Admin before any snapshot → 404, not a guess.
    with pytest.raises(ReportError) as missing:
        flow.reports.admin_overview(flow.env.tokens["admin"], flow.video.task_id)
    assert missing.value.status == 404 and missing.value.code == "overview_unavailable"

    workspace = flow.measurements.course_workspace(flow.token, flow.video.task_id)
    overview = workspace["course_overview"]
    assert overview["student_count"] == 1 and overview["conclusion"]["available"] is False
    codes = [m["code"] for m in overview["conclusion"]["missing"]]
    assert "course_evaluation_missing" in codes
    lead = workspace["report"]["lead_sections"]
    assert lead[0]["source"] == "course_overview" and lead[0]["title"] == "课程总览与结论"
    # The 千字正文 count is unchanged: the chapter is not one of the counted body sections.
    sections = workspace["report"]["sections"]
    assert all(s.get("source") != "course_overview" for s in sections)
    assert workspace["report"]["character_count"] == sum(len(s["text"]) for s in sections)
    assert workspace["report"]["lead_character_count"] == len(lead[0]["text"])
    saved = flow.reports.save_from_workspace(flow.token, workspace)

    name = flow.env.pupils["a1"]["display_name"]
    assert name in json.dumps(overview, ensure_ascii=False)
    admin = flow.reports.admin_overview(flow.env.tokens["admin"], flow.video.task_id)
    assert admin["report_id"] == saved["report_id"]
    text = json.dumps(admin, ensure_ascii=False)
    assert name not in text and "学生1" in text
    assert "iep_links" not in text and "iep_support" not in text and "/demo2/measurement" not in text
    assert admin["overview"]["viewer"] == "company_admin"
    # Teachers cannot use the admin path; downloads still carry the new chapter.
    with pytest.raises(ReportError) as denied:
        flow.reports.admin_overview(flow.token, flow.video.task_id)
    assert denied.value.status == 403
    markdown, _, _ = flow.reports.download(flow.token, saved["report_id"], fmt="md")
    assert "## 课程总览与结论" in markdown and "暂无结论，还缺" in markdown

    # Access: own teacher ok, other school 403, unknown task 404, no session 401.
    assert check_task_access(flow.env.records, flow.token, flow.video.task_id)["role"] == "school_uploader"
    for token, task_id, status in ((flow.env.tokens["b"], flow.video.task_id, 403),
                                   (flow.token, "no-such-task", 404),
                                   ("not-a-session", flow.video.task_id, 401),
                                   (flow.env.tokens["admin"], flow.video.task_id, 403)):
        with pytest.raises(OverviewError) as error:
            check_task_access(flow.env.records, token, task_id)
        assert error.value.status == status

    lines = _log_lines(logs)
    operations = {line["operation"] for line in lines}
    assert {"course_overview_compute", "course_overview_incomplete", "course_overview_admin_view"} <= operations
    compute = next(line for line in lines if line["operation"] == "course_overview_compute")
    assert compute["task_short"] == flow.video.task_id[:8] and compute["student_count"] == 1 and compute["ts"]
    incomplete = next(line for line in lines if line["operation"] == "course_overview_incomplete")
    assert "course_evaluation_missing" in incomplete["missing_steps"]
    admin_line = [line for line in lines if line["operation"] == "course_overview_admin_view"][-1]
    assert admin_line["role"] == "company_admin" and admin_line["grade"] == "none" and admin_line["result"] == "ok"
    for line in lines:
        assert name not in json.dumps(line, ensure_ascii=False)
