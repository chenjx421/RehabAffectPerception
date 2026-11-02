"""课程总览（系统大纲）：每个学生的评价 + 整体课程指标 + 本课好坏的试行结论。

总览只汇总本课已确认的数据，不产生新的分数：
- 课程评价：本课（task_id）最近一份「课堂教学基本评价指标 · 100分原表」评价；
  只有教师已核对（status=reviewed）且依据未变化时才参与结论；
- 学生目标达成度：每名纳入学生「已复核且证据充分」的测量综合分，先按目标求平均，
  再对目标求平均，×10 折算为百分制；
- 结论分 = 课程评价总分 × 60% + 学生目标达成度均值 × 40%（assessment_rubric.course_grade_contract，试行）。

数据不完整时不给等级，只列出还缺的步骤与跳转链接。总览随课堂报告快照保存（章节
「课程总览与结论」），公司管理员只能读快照：学生名替换为「学生1/学生2…」，没有 IEP
内容、学生编号和教师端跳转链接。
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .assessment_rubric import (
    DIMENSION_LABELS,
    DIMENSION_WEIGHTS,
    PASS_SCORE,
    course_conclusion_score,
    course_grade_contract,
)
from .classroom_rubric import TEMPLATES
from .demo2_report_debug import report_debug_event

OVERVIEW_VERSION = "2026-11-01.course-overview-v1"
SECTION_TITLE = "课程总览与结论"
SECTION_SOURCE = "course_overview"
TEMPLATE_ID = "basic_100"
TOP_COUNT = 3
STATE_LABELS = {"engaged": "稳定参与", "low_response": "回应偏低", "away": "离开或不可见",
                "not_observed": "未观察"}
STATE_COLORS = {"engaged": "#2f9e6b", "low_response": "#d69d31", "away": "#c45c5c", "not_observed": "#c9d3df"}
_TASK_ID = re.compile(r"[A-Za-z0-9_-]{1,120}")
_TEACHER_TEXT_PREFIXES = ("教师填写的证据：", "系统建议分依据：")


class OverviewError(ValueError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def short_id(value: Any) -> str:
    return str(value or "")[:8]


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _round(value: float | None, places: int = 2) -> float | None:
    if value is None:
        return None
    step = Decimal("1").scaleb(-places)
    return float(Decimal(str(value)).quantize(step, rounding=ROUND_HALF_UP))


def _fmt(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "—"
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _goal_key(value: Any) -> str:
    return re.sub(r"[\s_-]", "", unicodedata.normalize("NFKC", str(value or ""))).upper()


def _excerpt(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text if len(text) <= limit else text[:limit] + "…"


# ------------------------------------------------------------------ evaluation

def pick_course_evaluation(evaluations: Any) -> dict[str, Any] | None:
    """Latest basic_100 evaluation of the lesson; course evaluations (with system suggestions) win."""
    usable = [e for e in evaluations or [] if isinstance(e, dict) and e.get("template_id") == TEMPLATE_ID
              and isinstance(e.get("result"), dict)]
    if not usable:
        return None
    usable.sort(key=lambda e: (bool(e.get("course_evaluation")), str(e.get("updated_at") or "")), reverse=True)
    return usable[0]


def _evaluation_state(evaluation: dict[str, Any] | None, stale: list[str]) -> dict[str, Any]:
    if evaluation is None:
        return {"exists": False, "reviewed": False, "complete": False, "stale": False, "stale_reasons": [],
                "status": "missing", "label": "未做课程评价", "evaluation_id": "", "evaluation_short": ""}
    result = evaluation["result"]
    school = result.get("school") or {}
    complete = school.get("raw_score") is not None
    reviewed = evaluation.get("reviewed") is True and result.get("status") == "reviewed"
    if stale:
        label = "依据已变化，需重新核对"
    elif reviewed:
        label = "已核对"
    elif complete:
        label = "未勾选「已核对」"
    else:
        label = "评分不完整"
    return {"exists": True, "reviewed": reviewed, "complete": complete, "stale": bool(stale),
            "stale_reasons": list(stale), "status": result.get("status") or "",
            "label": label, "evaluation_id": evaluation.get("evaluation_id") or "",
            "evaluation_short": short_id(str(evaluation.get("evaluation_id") or "").replace("evaluation-", "")),
            "kind": "course" if evaluation.get("course_evaluation") else "classroom",
            "version": evaluation.get("version")}


def _indicators(evaluation: dict[str, Any] | None) -> dict[str, Any]:
    template = TEMPLATES[TEMPLATE_ID]
    labels = {c["id"]: c["label"] for c in template["categories"]}
    result = (evaluation or {}).get("result") or {}
    by_category = {c.get("id"): c for c in result.get("categories") or [] if isinstance(c, dict)}
    categories = []
    for category in template["categories"]:
        row = by_category.get(category["id"], {})
        school, system = _num(row.get("school_score")), _num(row.get("enhanced_score"))
        categories.append({"id": category["id"], "label": category["label"],
                           "school": _round(school), "system": _round(system),
                           "gap": _round(system - school) if school is not None and system is not None else None,
                           "item_ids": [i["id"] for i in template["items"] if i["category_id"] == category["id"]]})
    compared = {i.get("id"): i for i in (result.get("comparison") or {}).get("items") or [] if isinstance(i, dict)}
    decisions = {i.get("id"): i for i in ((evaluation or {}).get("course_evaluation") or {}).get("items") or []
                 if isinstance(i, dict)}
    items = []
    for number, spec in enumerate(template["items"], start=1):
        row = compared.get(spec["id"], {})
        decision = decisions.get(spec["id"], {})
        school, system = _num(row.get("school_score")), _num(row.get("enhanced_score"))
        items.append({"id": spec["id"], "number": number, "label": spec["label"],
                      "category_id": spec["category_id"], "category_label": labels.get(spec["category_id"], ""),
                      "school": school, "system": system,
                      "gap": _round(system - school) if school is not None and system is not None else None,
                      "evidence": _excerpt(row.get("evidence"), 80),
                      "decision": decision.get("decision") or "",
                      "formula": _excerpt(decision.get("formula"), 160)})
    school = result.get("school") or {}
    enhanced = result.get("enhanced") or {}
    system_10 = _num(enhanced.get("score_10"))
    return {"categories": categories, "items": items,
            "school_total_100": _num(school.get("raw_score")),
            "school_score_10": _num(school.get("score_10")),
            "teaching_score_70": _num(school.get("teaching_score_70")),
            "system_score_10": system_10,
            "system_total_100": _round(system_10 * 10, 1) if system_10 is not None else None,
            "total_gap_10": _num((result.get("comparison") or {}).get("total_delta"))}


# --------------------------------------------------------------------- students

def _scored(record: dict[str, Any]) -> bool:
    return (record.get("reviewed") is True and record.get("evidence_status", "current") == "current"
            and _num((record.get("assessment") or {}).get("overall_score")) is not None)


def _timeline(records: list[dict[str, Any]], duration: float | None) -> dict[str, Any]:
    video = next((r for r in records if r.get("source_type") == "video" and r.get("evidence_segments")), None)
    if video is None:
        return {"available": False, "segments": [], "duration_sec": duration}
    segments = []
    for segment in video.get("evidence_segments") or []:
        if not isinstance(segment, dict):
            continue
        start, end = _num(segment.get("start_sec")), _num(segment.get("end_sec"))
        state = segment.get("state") if segment.get("state") in STATE_LABELS else "not_observed"
        if start is None or end is None or end <= start:
            continue
        segments.append({"start_sec": start, "end_sec": end, "state": state, "label": STATE_LABELS[state]})
    segments.sort(key=lambda s: s["start_sec"])
    span = duration or (max((s["end_sec"] for s in segments), default=0.0) or None)
    return {"available": bool(segments), "segments": segments[:120], "duration_sec": span,
            "record_id": video.get("record_id") or ""}


def _student_rows(work: dict[str, Any], goals: list[dict[str, Any]], task_id: str) -> list[dict[str, Any]]:
    duration = _num((work.get("media") or {}).get("duration_sec"))
    records = [r for r in work.get("records") or [] if isinstance(r, dict)]
    goal_keys = [(_goal_key(g.get("goal_code")), g.get("goal_code") or "") for g in goals if g.get("goal_code")]
    rows = []
    for person in work.get("people") or []:
        student_id = person.get("student_id")
        if not student_id:
            continue
        mine = [r for r in records if r.get("student_id") == student_id]
        scored = [r for r in mine if _scored(r)]
        per_goal: dict[str, list[float]] = {}
        for record in scored:
            per_goal.setdefault(_goal_key(record.get("goal_id")), []).append(
                float(record["assessment"]["overall_score"]))
        goal_avgs = {key: sum(values) / len(values) for key, values in per_goal.items()}
        if goal_keys:
            relevant = {key: goal_avgs[key] for key, _ in goal_keys if key in goal_avgs}
            goals_total = len(goal_keys)
        else:
            relevant = goal_avgs
            goals_total = len({_goal_key(r.get("goal_id")) for r in mine}) or 0
        # Without a course task every reviewed goal counts; with one, only its goals do.
        attainment_base = relevant if goal_keys else goal_avgs
        attainment = (_round(sum(attainment_base.values()) / len(attainment_base) * 10, 1)
                      if attainment_base else None)
        dims = {}
        for key in DIMENSION_WEIGHTS:
            values = [_num((r.get("scores") or {}).get(key)) for r in scored]
            values = [v for v in values if v is not None]
            dims[key] = _round(sum(values) / len(values)) if values else None
        overall = [float(r["assessment"]["overall_score"]) for r in scored]
        insufficient = [r for r in mine if r.get("reviewed") is True and not _scored(r)]
        pending = [r for r in mine if r.get("reviewed") is not True]
        first_scored = scored[0]["record_id"] if scored else ""
        flags = []
        if not scored:
            flags.append("暂无已复核且证据充分的测量")
        if insufficient:
            flags.append(f"{len(insufficient)} 条已复核记录证据不足")
        if pending:
            flags.append(f"{len(pending)} 条待复核")
        rows.append({
            "student_id": student_id,
            "display_name": person.get("display_name") or "学生",
            "student_code": person.get("student_code") or "",
            "class_name": person.get("class_name") or "",
            "dimensions": dims,
            "composite": _round(sum(overall) / len(overall)) if overall else None,
            "attainment": attainment,
            "goals_achieved": sum(1 for value in relevant.values() if value >= PASS_SCORE),
            "goals_reviewed": len(relevant),
            "goals_total": goals_total,
            "goal_scores": {code: _round(goal_avgs[key]) for key, code in goal_keys if key in goal_avgs},
            "record_count": len(mine), "scored_count": len(scored),
            "pending_count": len(pending), "insufficient_count": len(insufficient),
            "evidence_insufficient": not scored or bool(insufficient),
            "flags": flags,
            "timeline": _timeline(mine, duration),
            "measurement_href": f"/demo2/measurement?student_id={student_id}",
            "report_href": (f"/demo2/measurement?student_id={student_id}&record_id={first_scored}#tab-report"
                            if first_scored else ""),
            "video_href": f"/demo2/video?id={task_id}",
        })
    return rows


def _coverage(work: dict[str, Any], student_ids: set[str]) -> dict[str, Any]:
    metrics: dict[str, dict[str, Any]] = {}
    for record in work.get("records") or []:
        if (isinstance(record, dict) and record.get("student_id") in student_ids
                and isinstance(record.get("video_metrics"), dict)):
            metrics.setdefault(record["student_id"], record["video_metrics"])
    if not student_ids or not metrics:
        return {"available": False, "participating": 0, "included": len(student_ids), "ratio": None,
                "note": "本课学生还没有视频参与线索（需在结果页绑定学生并保存本课记录）。"}
    participating = sum(1 for m in metrics.values()
                        if (m.get("engaged_segments") or 0) + (m.get("low_response_segments") or 0) > 0)
    return {"available": True, "participating": participating, "included": len(student_ids),
            "ratio": _round(participating / len(student_ids), 3),
            "note": "覆盖率 = 视频中有「稳定参与」或「回应偏低」片段的学生 / 本课纳入检测的学生。"}


def _goal_table(goals: list[dict[str, Any]], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    table = []
    for goal in goals:
        code = goal.get("goal_code") or ""
        scores = [row["goal_scores"][code] for row in rows if code in row["goal_scores"]]
        achieved = sum(1 for value in scores if value >= PASS_SCORE)
        table.append({"goal_code": code, "description": _excerpt(goal.get("description"), 80),
                      "pass_criteria": _excerpt(goal.get("pass_criteria"), 80),
                      "achieved": achieved, "reviewed_students": len(scores), "included": len(rows),
                      "ratio": _round(achieved / len(rows), 3) if rows else None,
                      "label": (f"{achieved}/{len(rows)} 名学生达成" if rows else "暂无纳入学生")})
    return table


# ------------------------------------------------------------- strengths/gaps

def _pool(indicators: dict[str, Any], goals: list[dict[str, Any]], coverage: dict[str, Any],
          attainment_mean: float | None, rows: list[dict[str, Any]], task_id: str) -> list[dict[str, Any]]:
    evaluation_href = f"/demo2/evaluation?task_id={task_id}"
    pool = []
    for category in indicators["categories"]:
        if category["school"] is None:
            continue
        lines = [f"学校评分 {_fmt(category['school'])}/10（类目内条目平均）",
                 f"系统评分 {_fmt(category['system'])}/10" if category["system"] is not None else "系统评分：未完整",
                 "包含条目：" + "、".join(f"第{int(i[1:])}项" for i in category["item_ids"])]
        pool.append({"kind": "category", "key": category["id"], "group": category["id"],
                     "value": category["school"] * 10, "score_text": f"{_fmt(category['school'])}/10",
                     "label": category["label"],
                     "basis": {"title": f"类目「{category['label']}」", "lines": lines,
                               "href": "#ov-categories", "href_label": "查看类目图表",
                               "source_href": evaluation_href, "source_label": "打开课程评价"}})
    for item in indicators["items"]:
        if item["school"] is None:
            continue
        lines = [f"学校评分 {_fmt(item['school'])}/10", f"所属类目：{item['category_label']}"]
        if item["system"] is not None:
            lines.append(f"系统评分 {_fmt(item['system'])}/10")
        if item["evidence"]:
            lines.append("教师填写的证据：" + item["evidence"])
        if item["formula"]:
            lines.append("系统建议分依据：" + item["formula"])
        pool.append({"kind": "item", "key": item["id"], "group": item["category_id"],
                     "value": item["school"] * 10, "score_text": f"{_fmt(item['school'])}/10",
                     "label": f"第{item['number']}项「{_excerpt(item['label'], 24)}」",
                     "basis": {"title": f"条目 {item['number']}：{item['label']}", "lines": lines,
                               "href": f"#ov-item-{item['id']}", "href_label": "查看条目分",
                               "source_href": evaluation_href, "source_label": "打开课程评价"}})
    for goal in goals:
        if not goal["included"]:
            continue
        value = goal["achieved"] / goal["included"] * 100
        pool.append({"kind": "goal", "key": goal["goal_code"], "group": "goal:" + goal["goal_code"],
                     "value": value, "score_text": f"{goal['achieved']}/{goal['included']}",
                     "label": f"目标 {goal['goal_code']}「{_excerpt(goal['description'], 20)}」",
                     "basis": {"title": f"课程任务目标 {goal['goal_code']}",
                               "lines": [f"{goal['achieved']}/{goal['included']} 名学生达成（已复核综合分 ≥ {PASS_SCORE:g}）",
                                         f"有已复核测量的学生 {goal['reviewed_students']} 名",
                                         "通过标准：" + (goal["pass_criteria"] or "未填写")],
                               "href": f"#ov-goal-{goal['goal_code']}", "href_label": "查看目标达成表"}})
    if attainment_mean is not None and rows:
        passed = sum(1 for row in rows if row["attainment"] is not None and row["attainment"] >= PASS_SCORE * 10)
        pool.append({"kind": "attainment", "key": "attainment", "group": "attainment",
                     "value": attainment_mean, "score_text": f"{_fmt(attainment_mean)}",
                     "label": "学生目标达成度均值",
                     "basis": {"title": "学生目标达成度",
                               "lines": [f"{len(rows)} 名学生的达成度均值 {_fmt(attainment_mean)}（百分制）",
                                         f"{passed}/{len(rows)} 名学生达到 {PASS_SCORE * 10:g} 分参考线",
                                         "每名学生：已复核且证据充分的目标综合分先按目标求平均，再 × 10"],
                               "href": "#ov-students", "href_label": "查看学生评价矩阵"}})
    if coverage.get("available"):
        pool.append({"kind": "coverage", "key": "coverage", "group": "coverage",
                     "value": (coverage["ratio"] or 0) * 100,
                     "score_text": f"{round((coverage['ratio'] or 0) * 100)}%", "label": "学生覆盖率",
                     "basis": {"title": "学生覆盖率",
                               "lines": [f"{coverage['participating']}/{coverage['included']} 名学生有参与或回应片段",
                                         coverage["note"]],
                               "href": "#ov-coverage", "href_label": "查看学生覆盖率"}})
    return pool


_KIND_ORDER = {"category": 0, "goal": 1, "attainment": 2, "coverage": 3, "item": 4}


def _phrase(entry: dict[str, Any], positive: bool) -> str:
    kind, label, score = entry["kind"], entry["label"], entry["score_text"]
    if kind == "category":
        tail = "，在四个类目中表现较好" if positive else ("，低于 6 分试行参考线" if entry["value"] < 60 else "，是四个类目中相对较弱的一项")
        return f"类目「{label}」学校评分 {score}{tail}"
    if kind == "item":
        tail = "，落实较好" if positive else ("，低于 6 分试行参考线" if entry["value"] < 60 else "，仍有提升空间")
        return f"{label}学校评分 {score}{tail}"
    if kind == "goal":
        return f"{label}{score} 名学生达成" + ("，目标落实到位" if positive else "，需要调整支持或分层要求")
    if kind == "attainment":
        return f"{label} {score}" + ("，多数学生达到本课目标" if positive else "，学生整体达成仍需加强")
    return f"{label} {score}" + ("，大部分学生有参与或回应" if positive else "，部分学生缺少参与或回应机会")


def _rank(pool: list[dict[str, Any]], *, positive: bool, taken: set[str]) -> list[dict[str, Any]]:
    ordered = sorted(pool, key=lambda e: ((-e["value"]) if positive else e["value"], _KIND_ORDER[e["kind"]], e["key"]))
    picked: list[dict[str, Any]] = []
    groups: set[str] = set()
    for entry in ordered:
        if len(picked) >= TOP_COUNT:
            break
        if entry["kind"] + ":" + entry["key"] in taken or entry["group"] in groups:
            continue
        picked.append(entry)
        groups.add(entry["group"])
    out = []
    for entry in picked:
        tone = ("strength" if entry["value"] >= 80 else "relative") if positive else (
            "gap" if entry["value"] < 70 else "relative")
        out.append({"kind": entry["kind"], "key": entry["key"], "label": entry["label"],
                    "value": _round(entry["value"], 1), "score_text": entry["score_text"], "tone": tone,
                    "text": _phrase(entry, positive), "basis": entry["basis"]})
    return out


def _highlights(pool: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    strengths = _rank(pool, positive=True, taken=set())
    taken = {s["kind"] + ":" + s["key"] for s in strengths}
    improvements = _rank(pool, positive=False, taken=taken)
    return strengths, improvements


# ------------------------------------------------------------------- overview

def build_overview(work: dict[str, Any], evaluations: Any = (), *, stale: list[str] | None = None,
                   task: dict[str, Any] | None = None, computed_at: str | None = None) -> dict[str, Any]:
    """Pure aggregation of one lesson workspace; never invents a score."""
    task_id = str(work.get("task_id") or "")
    task = task or {}
    course_task = work.get("course_task") if isinstance(work.get("course_task"), dict) else None
    goals = [g for g in (course_task or {}).get("goals") or [] if isinstance(g, dict)]
    evaluation = pick_course_evaluation(evaluations)
    evaluation_state = _evaluation_state(evaluation, list(stale or []))
    indicators = _indicators(evaluation)
    rows = _student_rows(work, goals, task_id)
    student_ids = {row["student_id"] for row in rows}
    coverage = _coverage(work, student_ids)
    goal_table = _goal_table(goals, rows)
    attainments = [row["attainment"] for row in rows if row["attainment"] is not None]
    attainment_mean = _round(sum(attainments) / len(attainments), 1) if attainments else None
    expected = len(rows) * (len(goals) or 1)
    reviewed_pairs = sum(row["goals_reviewed"] if goals else (1 if row["scored_count"] else 0) for row in rows)
    applicability = work.get("applicability") if isinstance(work.get("applicability"), dict) else None
    applicable = applicability is None or bool(applicability.get("confirmed_for_source"))

    missing: list[dict[str, Any]] = []
    evaluation_href = f"/demo2/evaluation?task_id={task_id}"
    if not applicable:
        missing.append({"code": "applicability_required", "text": "视频适用性尚未确认（确认后才能复核测量与评价）",
                        "href": f"/demo2/analysis?task_id={task_id}#tab-group", "label": "去确认视频适用性"})
    if not rows:
        missing.append({"code": "students_missing", "text": "本课还没有纳入检测的学生",
                        "href": f"/demo2/simple-result?task_id={task_id}", "label": "去绑定本课学生"})
    for row in rows:
        if row["attainment"] is None:
            missing.append({"code": "measurement_review_required", "student_id": row["student_id"],
                            "text": f"{row['display_name']}：还没有已复核且证据充分的测量",
                            "href": row["measurement_href"], "label": "去复核测量"})
    if not evaluation_state["exists"]:
        missing.append({"code": "course_evaluation_missing", "text": "本课还没有课程评价",
                        "href": evaluation_href, "label": "去做课程评价"})
    elif evaluation_state["stale"]:
        missing.append({"code": "course_evaluation_stale", "text": "课程评价的依据数据已变化，需要刷新系统建议分并重新核对",
                        "href": evaluation_href, "label": "重新核对课程评价"})
    elif not evaluation_state["complete"]:
        missing.append({"code": "course_evaluation_incomplete", "text": "课程评价 10 个条目的学校评分还没有填完",
                        "href": evaluation_href, "label": "补全课程评价"})
    elif not evaluation_state["reviewed"]:
        missing.append({"code": "course_evaluation_unreviewed", "text": "课程评价尚未勾选「已核对」",
                        "href": evaluation_href, "label": "核对课程评价"})

    contract = course_grade_contract()
    conclusion: dict[str, Any] = {"available": False, "trial": True, "missing": missing, "score": None,
                                  "grade": None, "formula": None, "strengths": [], "improvements": [],
                                  "note": contract["note"]}
    if not missing and indicators["school_total_100"] is not None and attainment_mean is not None:
        formula = course_conclusion_score(indicators["school_total_100"], attainment_mean)
        strengths, improvements = _highlights(_pool(indicators, goal_table, coverage, attainment_mean, rows, task_id))
        conclusion.update(available=True, score=formula["score"], grade=formula["grade"], formula=formula,
                          strengths=strengths, improvements=improvements, missing=[])
    elif not missing:
        missing.append({"code": "course_evaluation_incomplete", "text": "课程评价总分暂不可用",
                        "href": evaluation_href, "label": "补全课程评价"})

    school = work.get("school_context") or {}
    lesson_dates = sorted({str(r.get("lesson_date")) for r in work.get("records") or []
                           if isinstance(r, dict) and r.get("lesson_date")})
    lesson_date = ((course_task or {}).get("lesson_date") or (lesson_dates[0] if lesson_dates else "")
                   or str(task.get("created_at") or "")[:10])
    return {
        "version": OVERVIEW_VERSION,
        "task_id": task_id,
        "task_short": short_id(task_id),
        "course_id": work.get("course_id") or "",
        "course_name": work.get("course_name") or "",
        "lesson_date": lesson_date,
        "school_name": school.get("school_name") or "",
        "course_task": ({"course_task_doc_id": course_task.get("course_task_doc_id") or "",
                         "course_task_doc_short": course_task.get("course_task_doc_short")
                         or short_id(str(course_task.get("course_task_doc_id") or "").replace("ctd-", "")),
                         "version": course_task.get("version"), "goal_count": len(goals)}
                        if course_task else None),
        "student_count": len(rows),
        "completeness": {"reviewed": reviewed_pairs, "expected": expected,
                         "ratio": _round(reviewed_pairs / expected, 3) if expected else None,
                         "unit": "学生×目标" if goals else "学生",
                         "evaluation": evaluation_state, "applicable": applicable},
        "conclusion": conclusion,
        "indicators": {**indicators, "coverage": coverage, "goals": goal_table,
                       "attainment_mean": attainment_mean,
                       "dimension_labels": dict(DIMENSION_LABELS)},
        "students": rows,
        "grade_contract": contract,
        "state_colors": dict(STATE_COLORS),
        "state_labels": dict(STATE_LABELS),
        "boundary": "课程总览只汇总本课教师已复核的测量与已核对的课程评价，用于课堂教学复盘；"
                    "等级为试行口径，不构成教师绩效结论或学生能力定级。",
        "computed_at": computed_at or _now(),
    }


def overview_section(overview: dict[str, Any]) -> dict[str, Any]:
    """「课程总览与结论」 report chapter in plain sentences (no tables, no markup)."""
    parts = []
    head = (f"本课「{overview['course_name'] or '未命名课程'}」纳入检测学生 {overview['student_count']} 名，"
            f"已复核测量 {overview['completeness']['reviewed']}/{overview['completeness']['expected']}"
            f"（按{overview['completeness']['unit']}计），课程评价状态：{overview['completeness']['evaluation']['label']}。")
    if overview.get("course_task"):
        head += f"课程任务版本 {overview['course_task']['version']}，共 {overview['course_task']['goal_count']} 个目标。"
    parts.append(head)
    conclusion = overview["conclusion"]
    if conclusion["available"]:
        formula = conclusion["formula"]
        parts.append(f"课程结论（试行）：{conclusion['grade']['label']}，结论分 {_fmt(conclusion['score'])}。"
                     f"{formula['text']}。等级阈值：优秀 ≥ 85、良好 70~84.9、合格 60~69.9、待改进 < 60。")
        if conclusion["strengths"]:
            parts.append("主要优点：" + "；".join(f"{n}）{s['text']}" for n, s in enumerate(conclusion["strengths"], 1)) + "。")
        if conclusion["improvements"]:
            parts.append("主要待改进：" + "；".join(f"{n}）{s['text']}" for n, s in enumerate(conclusion["improvements"], 1)) + "。")
    else:
        parts.append("暂无结论，还缺：" + "；".join(m["text"] for m in conclusion["missing"]) + "。数据补齐后系统才给出等级。")
    indicators = overview["indicators"]
    categories = [c for c in indicators["categories"] if c["school"] is not None]
    if categories:
        parts.append("四个类目得分（学校/系统，10分制）：" + "；".join(
            f"{c['label']} {_fmt(c['school'])}/{_fmt(c['system'])}" for c in categories) + "。"
            + (f"课程评价总分（学校原表）{_fmt(indicators['school_total_100'])} 分。" if indicators["school_total_100"] is not None else ""))
    coverage = indicators["coverage"]
    if coverage["available"]:
        parts.append(f"学生覆盖率 {round((coverage['ratio'] or 0) * 100)}%（{coverage['participating']}/{coverage['included']} 名学生有参与或回应片段）。")
    if indicators["goals"]:
        parts.append("课程任务目标达成：" + "；".join(
            f"{g['goal_code']} {g['achieved']}/{g['included']} 名学生达成" for g in indicators["goals"]) + "。")
    for row in overview["students"]:
        dims = "、".join(f"{DIMENSION_LABELS[k]} {_fmt(v)}" for k, v in row["dimensions"].items() if v is not None)
        text = f"{row['display_name']}："
        text += (f"四维平均 {dims}，综合分 {_fmt(row['composite'])}，目标达成 {row['goals_achieved']}/{row['goals_total']}，"
                 f"达成度 {_fmt(row['attainment'])}" if row["composite"] is not None else "暂无已复核且证据充分的测量")
        if row["flags"] and row["composite"] is not None:
            text += "（" + "，".join(row["flags"]) + "）"
        parts.append(text + "。")
    parts.append(overview["boundary"])
    return {"title": SECTION_TITLE, "text": "".join(parts), "source": SECTION_SOURCE}


def admin_view(overview: dict[str, Any]) -> dict[str, Any]:
    """Company-admin copy: no student codes, class names or teacher-side links (names already aliased)."""
    data = json.loads(json.dumps(overview, ensure_ascii=False))
    for row in data.get("students") or []:
        for key in ("student_code", "class_name", "measurement_href", "report_href", "video_href"):
            row[key] = ""
        row["timeline"].pop("record_id", None)
    for item in (data.get("conclusion") or {}).get("missing") or []:
        item["href"] = ""
        item.pop("student_id", None)
    for group in ("strengths", "improvements"):
        for item in (data.get("conclusion") or {}).get(group) or []:
            item["basis"].pop("source_href", None)
            item["basis"].pop("source_label", None)
            # Teacher free text stays teacher-side; the scores themselves remain.
            item["basis"]["lines"] = [line for line in item["basis"].get("lines") or []
                                      if not str(line).startswith(_TEACHER_TEXT_PREFIXES)]
    for item in (data.get("indicators") or {}).get("items") or []:
        item["evidence"] = ""
        item["formula"] = ""

    def drop_pages(value: Any) -> None:
        # In-page anchors (#ov-…) stay; teacher workspace pages (/demo2/…) do not.
        if isinstance(value, dict):
            for key, child in value.items():
                if isinstance(child, str) and child.startswith("/demo2/"):
                    value[key] = ""
                else:
                    drop_pages(child)
        elif isinstance(value, list):
            for child in value:
                drop_pages(child)

    drop_pages(data)
    data["viewer"] = "company_admin"
    return data


# --------------------------------------------------------------- workspace hook

def _stale_for(records: Any, account: dict[str, Any], task_id: str, evaluation: dict[str, Any] | None) -> list[str]:
    if not evaluation or not isinstance(evaluation.get("course_evaluation"), dict):
        return []
    from .demo2_course_evaluation import data_fingerprint, load_lesson_data, stale_reasons
    with records._connect() as db:
        row = db.execute("SELECT * FROM video_analysis_tasks WHERE task_id=? AND account_id=?",
                         (task_id, account["account_id"])).fetchone()
        if row is None:
            return ["task_missing"]
        current = data_fingerprint(load_lesson_data(db, account["account_id"], dict(row)))
    return stale_reasons(evaluation["course_evaluation"].get("fingerprint"), current)


def attach_course_overview(records: Any, account: dict[str, Any], workspace: dict[str, Any],
                           evaluations: Any = ()) -> None:
    """Add ``course_overview`` and the 「课程总览与结论」 chapter; a failure never blocks the workspace."""
    task_id = str(workspace.get("task_id") or "")
    try:
        evaluation = pick_course_evaluation(evaluations)
        stale = _stale_for(records, account, task_id, evaluation)
        overview = build_overview(workspace, evaluations, stale=stale)
    except (sqlite3.Error, ValueError, TypeError, KeyError) as exc:
        report_debug_event(records, "course_overview_error", "failed", role="teacher", task_id=task_id,
                           task_short=short_id(task_id), account_id=account.get("account_id"),
                           code=type(exc).__name__)
        workspace["course_overview"] = {"available": False, "task_id": task_id,
                                        "error": "课程总览暂时无法计算，请稍后刷新"}
        return
    workspace["course_overview"] = overview
    report = workspace.get("report")
    if isinstance(report, dict) and isinstance(report.get("sections"), list):
        # Like the score-basis appendix, the chapter sits outside the counted 千字正文 (sections /
        # character_count unchanged) and is shown first in the page report and in downloads.
        section = overview_section(overview)
        report["lead_sections"] = [section]
        report["lead_character_count"] = len(section["text"])
        report["course_overview"] = overview
    conclusion = overview["conclusion"]
    common = dict(role="teacher", task_id=task_id, task_short=overview["task_short"],
                  account_id=account.get("account_id"), student_count=overview["student_count"])
    report_debug_event(records, "course_overview_compute", "ok", **common,
                       record_count=overview["completeness"]["reviewed"],
                       evaluation_id=overview["completeness"]["evaluation"]["evaluation_id"] or None,
                       status=overview["completeness"]["evaluation"]["status"] or "missing")
    if conclusion["available"]:
        report_debug_event(records, "course_overview_conclusion", "generated", **common,
                           grade=conclusion["grade"]["key"], conclusion_score=conclusion["score"])
    else:
        report_debug_event(records, "course_overview_incomplete", "no_conclusion", **common,
                           missing_steps=[m["code"] for m in conclusion["missing"]])


def check_task_access(records: Any, token: str, task_id: Any) -> dict[str, Any]:
    """Teacher of the task → account; other school's teacher 403, missing task 404, no session 401."""
    try:
        account = records.account_from_session(token)
    except ValueError:
        raise OverviewError(401, "authentication_required", "请重新登录") from None
    if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
        raise OverviewError(400, "invalid_task", "课堂任务编号无效")
    with records._connect() as db:
        row = db.execute("SELECT account_id, upload_status FROM video_analysis_tasks WHERE task_id=?",
                         (task_id,)).fetchone()
    if row is None or row["upload_status"] == "cancelled":
        raise OverviewError(404, "task_unavailable", "课堂任务不存在或已取消")
    if account.get("role") != "school_uploader" or row["account_id"] != account["account_id"]:
        raise OverviewError(403, "task_forbidden", "该课堂任务不属于当前学校账号，无权查看课程总览")
    return account


# ------------------------------------------------------------------- front end

OVERVIEW_CSS = r"""
.ov-root{display:grid;gap:18px}.ov-card{background:#fff;border:1px solid #dce5f0;border-radius:8px;padding:20px 22px}
.ov-card h2{font-size:18px;margin:0 0 12px}.ov-card h3{font-size:15px;margin:16px 0 8px}
.ov-head{display:grid;gap:12px}.ov-head-top{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:flex-start}
.ov-kicker{color:#1f5fbf;font-weight:700;font-size:13px}.ov-title{font-size:22px;margin:2px 0 0;line-height:1.4}
.ov-meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px 18px;margin:0}
.ov-meta div{min-width:0}.ov-meta dt{color:#62758c;font-size:12px}.ov-meta dd{margin:2px 0 0;font-weight:600;word-break:break-all}
.ov-progress{height:8px;background:#e7eef7;border-radius:4px;overflow:hidden;margin-top:6px}.ov-progress i{display:block;height:100%;background:#1f5fbf}
.ov-conclusion{border-left:4px solid #1f5fbf}.ov-conclusion[data-grade=excellent]{border-left-color:#1d8a5c}.ov-conclusion[data-grade=good]{border-left-color:#1f5fbf}
.ov-conclusion[data-grade=qualified]{border-left-color:#c98a1b}.ov-conclusion[data-grade=improve]{border-left-color:#c24d4d}.ov-conclusion.is-pending{border-left-color:#9aa9bb;background:#fbfcfe}
.ov-grade-row{display:flex;gap:18px;align-items:center;flex-wrap:wrap}.ov-grade{font-size:34px;font-weight:800;line-height:1.1}
.ov-grade[data-grade=excellent]{color:#1d8a5c}.ov-grade[data-grade=good]{color:#1f5fbf}.ov-grade[data-grade=qualified]{color:#a8700f}.ov-grade[data-grade=improve]{color:#b13f3f}
.ov-score{font-size:15px;color:#23334a}.ov-score strong{font-size:22px}.ov-trial{display:inline-block;padding:2px 8px;border-radius:4px;background:#fff4dc;color:#8a5a00;font-size:12px;font-weight:700}
.ov-formula{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:14px 0 8px}
.ov-formula div{background:#f4f8fd;border:1px solid #dce5f0;border-radius:6px;padding:10px 12px}.ov-formula span{display:block;color:#62758c;font-size:12px}.ov-formula strong{font-size:18px}
.ov-formula-text{font-size:13px;color:#3d4e63;background:#f8fafc;border-radius:6px;padding:8px 10px;margin:6px 0}
.ov-bands{display:flex;gap:8px;flex-wrap:wrap;font-size:12px;color:#62758c;margin:4px 0 0}.ov-bands span{border:1px solid #dce5f0;border-radius:4px;padding:2px 8px}.ov-bands span.is-current{border-color:#1f5fbf;color:#1f5fbf;font-weight:700}
.ov-two{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;margin-top:14px}
.ov-list{list-style:none;margin:0;padding:0;display:grid;gap:8px}.ov-list details{border:1px solid #dce5f0;border-radius:6px;background:#fff}
.ov-list summary{cursor:pointer;padding:9px 12px;display:flex;gap:8px;align-items:flex-start;list-style:none}.ov-list summary::-webkit-details-marker{display:none}
.ov-list summary b{flex:none;width:22px;height:22px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:12px;color:#fff;background:#1d8a5c}
.ov-list.is-gap summary b{background:#c98a1b}.ov-list summary em{margin-left:auto;font-style:normal;color:#1f5fbf;font-size:12px;white-space:nowrap}
.ov-basis{padding:4px 14px 12px 42px;font-size:13px;color:#3d4e63}.ov-basis ul{margin:4px 0 8px;padding-left:18px}.ov-basis a{margin-right:12px}
.ov-missing{margin:10px 0 0;padding:0;list-style:none;display:grid;gap:8px}.ov-missing li{display:flex;justify-content:space-between;gap:12px;align-items:center;border:1px dashed #c8d4e3;border-radius:6px;padding:9px 12px;background:#fff}
.ov-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:14px}.ov-kpis div{background:#f4f8fd;border-radius:6px;padding:10px 12px}.ov-kpis span{display:block;color:#62758c;font-size:12px}.ov-kpis strong{font-size:20px}
svg.ov-chart{width:100%;height:auto;min-height:220px;max-width:760px;display:block}
svg.ov-timeline{width:170px;height:16px;display:block}
.ov-legend{display:flex;gap:14px;font-size:12px;color:#62758c;margin:4px 0 8px;flex-wrap:wrap}.ov-legend i{display:inline-block;width:12px;height:12px;border-radius:2px;margin-right:4px;vertical-align:-1px}
.ov-table-wrap{overflow-x:auto}.ov-table{width:100%;border-collapse:collapse;font-size:13px;min-width:640px}.ov-table th,.ov-table td{border-bottom:1px solid #e3eaf3;padding:8px 8px;text-align:left;vertical-align:middle}
.ov-table th{background:#f4f8fd;color:#3d4e63;font-weight:600;white-space:nowrap}.ov-table td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.ov-mini{display:inline-block;width:70px;height:6px;background:#e7eef7;border-radius:3px;vertical-align:middle;margin-left:6px;overflow:hidden}.ov-mini i{display:block;height:100%;background:#1f5fbf}
.ov-matrix tbody tr{cursor:pointer}.ov-matrix tbody tr:hover{background:#f4f8fd}.ov-matrix tbody tr.is-selected{background:#eaf2ff;box-shadow:inset 3px 0 0 #1f5fbf}
.ov-avatar{width:44px;height:44px;border-radius:50%;object-fit:cover;background:#e7eef7;display:inline-flex;align-items:center;justify-content:center;font-weight:700;color:#1f5fbf;flex:none}
.ov-who{display:flex;gap:10px;align-items:center;min-width:150px}.ov-who small{display:block;color:#62758c}
.ov-flag{display:inline-block;margin-top:3px;padding:1px 6px;border-radius:4px;background:#fff4dc;color:#8a5a00;font-size:12px}
.ov-actions{display:flex;gap:6px;flex-wrap:wrap}.ov-actions a{white-space:nowrap}
.ov-empty{color:#62758c;padding:12px 0}.ov-note{color:#62758c;font-size:12px;margin:8px 0 0}
.ov-stale{border:1px solid #f0c674;background:#fffaf0;color:#8a5a00;border-radius:6px;padding:10px 12px}
@media print{.ov-actions,.ov-switch{display:none!important}.ov-card{break-inside:avoid}}
"""

OVERVIEW_JS = r"""
(function(){
  'use strict';
  if (typeof window === 'undefined' || window.CourseOverview) return;
  var esc=function(x){return String(x==null?'':x).replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];});};
  var num=function(v,d){if(v===null||v===undefined||v===''||!isFinite(Number(v)))return '—';var n=Number(v);return d===undefined?String(Math.round(n*100)/100):n.toFixed(d);};
  var pct=function(v){return v===null||v===undefined?'—':Math.round(Number(v)*100)+'%';};
  var DIMS=[['accuracy','准确性'],['independence','独立性'],['consistency','一致性'],['transfer','泛化性']];
  function ida(x){return ' id="'+x+'"';}
  function link(href,label,cls){return href?'<a class="'+(cls||'')+'" href="'+esc(href)+'">'+esc(label)+'</a>':'';}
  function bandsHtml(contract,current){return '<div class="ov-bands" aria-label="等级阈值（试行）">'+(contract.bands||[]).map(function(b){return '<span class="'+(current===b.key?'is-current':'')+'">'+esc(b.label)+' '+esc(b.range)+'</span>';}).join('')+'</div>';}
  function basisHtml(b,admin){if(!b)return '';var links=[];if(b.href)links.push('<a href="'+esc(b.href)+'" data-ov-jump="'+esc(b.href)+'">'+esc(b.href_label||'查看')+'</a>');if(!admin&&b.source_href)links.push(link(b.source_href,b.source_label||'打开来源'));return '<div class="ov-basis"><strong>'+esc(b.title)+'</strong><ul>'+(b.lines||[]).map(function(l){return '<li>'+esc(l)+'</li>';}).join('')+'</ul>'+links.join('')+'</div>';}
  function highlightList(list,gap,admin,idPrefix){if(!list||!list.length)return '<p class="ov-empty">暂无可列出的条目。</p>';return '<ol class="ov-list'+(gap?' is-gap':'')+'">'+list.map(function(item,i){return '<li><details id="'+idPrefix+(i+1)+'"><summary><b>'+(i+1)+'</b><span>'+esc(item.text)+'</span><em>依据</em></summary>'+basisHtml(item.basis,admin)+'</details></li>';}).join('')+'</ol>';}
  function head(ov){
    var c=ov.completeness||{},ev=c.evaluation||{},ct=ov.course_task;
    var ratio=c.ratio===null||c.ratio===undefined?0:Math.max(0,Math.min(1,Number(c.ratio)));
    var evBadge=ev.reviewed&&!ev.stale?'rx-badge rx-badge-success':ev.exists?'rx-badge rx-badge-warning':'rx-badge rx-badge-neutral';
    return '<section class="ov-card ov-head" id="ovHead" aria-labelledby="ovCourseName"><div class="ov-head-top"><div><div class="ov-kicker">课程总览 · 系统大纲</div><h2 class="ov-title" id="ovCourseName">'+esc(ov.course_name||'未命名课程')+'</h2></div><span class="'+evBadge+'" id="ovEvaluationBadge">课程评价：'+esc(ev.label||'未做课程评价')+'</span></div>'+
      '<dl class="ov-meta"><div><dt>上课日期</dt><dd>'+esc(ov.lesson_date||'未记录')+'</dd></div><div><dt>学校</dt><dd>'+esc(ov.school_name||'学校待确认')+'</dd></div>'+
      '<div><dt>课程任务版本</dt><dd>'+(ct?esc('版本 '+ct.version+' · '+ct.goal_count+' 个目标'):'未上传课程任务')+'</dd></div><div><dt>纳入检测学生</dt><dd id="ovStudentCount">'+Number(ov.student_count||0)+' 名</dd></div>'+
      '<div><dt>数据完整度（已复核测量 / 应有）</dt><dd id="ovCompleteness">'+Number(c.reviewed||0)+' / '+Number(c.expected||0)+'（按'+esc(c.unit||'学生')+'计）<div class="ov-progress" aria-hidden="true"><i style="width:'+(ratio*100).toFixed(1)+'%"></i></div></dd></div></dl></section>';
  }
  function conclusion(ov,admin){
    var cc=ov.conclusion||{},contract=ov.grade_contract||{};
    if(!cc.available){
      return '<section class="ov-card ov-conclusion is-pending"'+ida('ovConclusion')+' aria-labelledby="ovConclusionTitle"><h2'+ida('ovConclusionTitle')+'>课程结论 <span class="ov-trial">试行</span></h2><p><strong>暂无结论，还缺：</strong></p><ul class="ov-missing" id="ovMissing">'+
        (cc.missing||[]).map(function(m){return '<li data-missing="'+esc(m.code)+'"><span>'+esc(m.text)+'</span>'+(admin||!m.href?'':'<a class="rx-btn rx-btn-secondary" href="'+esc(m.href)+'">'+esc(m.label||'去处理')+'</a>')+'</li>';}).join('')+
        '</ul><p class="ov-note">数据补齐后系统才给出等级，不会用不完整的数据推断课程好坏。'+esc(contract.formula||'')+'。</p>'+bandsHtml(contract,'')+'</section>';
    }
    var f=cc.formula||{},g=cc.grade||{};
    return '<section class="ov-card ov-conclusion"'+ida('ovConclusion')+' data-grade="'+esc(g.key)+'" aria-labelledby="ovConclusionTitle"><h2'+ida('ovConclusionTitle')+'>课程结论 <span class="ov-trial">试行</span></h2>'+
      '<div class="ov-grade-row"><div class="ov-grade" id="ovGrade" data-grade="'+esc(g.key)+'">'+esc(g.label)+'</div><div class="ov-score">结论分 <strong id="ovScore">'+num(cc.score,1)+'</strong> / 100</div></div>'+
      '<div class="ov-formula" id="ovFormula"><div><span>课程评价总分（学校原表）× '+Math.round(Number(f.course_weight)*100)+'%</span><strong>'+num(f.course_total,1)+' × '+num(f.course_weight)+' = '+num(f.course_part)+'</strong></div>'+
      '<div><span>学生目标达成度均值 × '+Math.round(Number(f.attainment_weight)*100)+'%</span><strong>'+num(f.attainment_mean,1)+' × '+num(f.attainment_weight)+' = '+num(f.attainment_part)+'</strong></div>'+
      '<div><span>结论分（保留一位小数）</span><strong>'+num(cc.score,1)+' → '+esc(g.label)+'</strong></div></div>'+
      '<p class="ov-formula-text" id="ovFormulaText">'+esc(f.text)+'</p>'+bandsHtml(contract,g.key)+'<p class="ov-note">'+esc(cc.note||'')+'</p>'+
      '<div class="ov-two"><div><h3>主要优点</h3>'+highlightList(cc.strengths,false,admin,'ovStrength')+'</div><div><h3>主要待改进</h3>'+highlightList(cc.improvements,true,admin,'ovImprove')+'</div></div></section>';
  }
  function chart(categories){
    var W=720,rowH=58,top=26,left=170,right=60,H=top+categories.length*rowH+30,scale=function(v){return (W-left-right)*Math.max(0,Math.min(10,Number(v)))/10;};
    var grid='';for(var t=0;t<=10;t+=2){var x=left+scale(t);grid+='<line x1="'+x+'" y1="'+(top-6)+'" x2="'+x+'" y2="'+(H-22)+'" stroke="#e3eaf3"/><text x="'+x+'" y="'+(H-6)+'" font-size="11" fill="#62758c" text-anchor="middle">'+t+'</text>';}
    var ref=left+scale(6);grid+='<line x1="'+ref+'" y1="'+(top-6)+'" x2="'+ref+'" y2="'+(H-22)+'" stroke="#d69d31" stroke-dasharray="4 4"/>';
    var bars=categories.map(function(c,i){var y=top+i*rowH,s=c.school,z=c.system;return '<text x="'+(left-10)+'" y="'+(y+24)+'" font-size="13" fill="#23334a" text-anchor="end">'+esc(c.label)+'</text>'+
      '<rect x="'+left+'" y="'+(y+4)+'" width="'+(s==null?0:scale(s)).toFixed(1)+'" height="18" rx="3" fill="#1f5fbf"><title>学校 '+num(s)+'</title></rect><text x="'+(left+(s==null?0:scale(s))+6).toFixed(1)+'" y="'+(y+18)+'" font-size="12" fill="#1f5fbf">'+(s==null?'未评分':num(s))+'</text>'+
      '<rect x="'+left+'" y="'+(y+26)+'" width="'+(z==null?0:scale(z)).toFixed(1)+'" height="18" rx="3" fill="#4fc3f7"><title>系统 '+num(z)+'</title></rect><text x="'+(left+(z==null?0:scale(z))+6).toFixed(1)+'" y="'+(y+40)+'" font-size="12" fill="#1679a8">'+(z==null?'未评分':num(z))+'</text>';}).join('');
    return '<svg class="ov-chart" viewBox="0 0 '+W+' '+H+'" role="img" aria-label="四个类目得分：学校与系统对照">'+grid+bars+'</svg>';
  }
  function indicators(ov){
    var ind=ov.indicators||{},cats=ind.categories||[],items=ind.items||[],cov=ind.coverage||{},goals=ind.goals||[];
    var kpis='<div class="ov-kpis"><div><span>课程评价总分（学校原表）</span><strong id="ovCourseTotal">'+num(ind.school_total_100,1)+'</strong></div><div><span>系统增强总分（折百分制）</span><strong>'+num(ind.system_total_100,1)+'</strong></div>'+
      '<div id="ov-coverage"><span>学生覆盖率</span><strong id="ovCoverage">'+(cov.available?pct(cov.ratio):'—')+'</strong>'+(cov.available?'<small> '+Number(cov.participating)+'/'+Number(cov.included)+' 名</small>':'')+'</div><div><span>学生目标达成度均值</span><strong id="ovAttainment">'+num(ind.attainment_mean,1)+'</strong></div></div>';
    var itemRows=items.map(function(it){var s=it.school,z=it.system;return '<tr id="ov-item-'+esc(it.id)+'"><td>'+it.number+'</td><td>'+esc(it.label)+'</td><td>'+esc(it.category_label)+'</td><td class="num">'+(s==null?'未评分':num(s))+'<span class="ov-mini"><i style="width:'+(s==null?0:Number(s)*10)+'%"></i></span></td><td class="num">'+(z==null?'未评分':num(z))+'</td><td class="num">'+(it.gap==null?'—':(it.gap>0?'+':'')+num(it.gap))+'</td></tr>';}).join('');
    var goalRows=goals.length?goals.map(function(g){var r=g.ratio==null?0:Number(g.ratio);return '<tr id="ov-goal-'+esc(g.goal_code)+'"><td><strong>'+esc(g.goal_code)+'</strong></td><td>'+esc(g.description)+'</td><td>'+esc(g.pass_criteria||'未填写')+'</td><td class="num">'+Number(g.achieved)+' / '+Number(g.included)+'<span class="ov-mini"><i style="width:'+(r*100).toFixed(1)+'%;background:#2f9e6b"></i></span></td><td class="num">'+Number(g.reviewed_students)+'</td></tr>';}).join(''):'';
    return '<section class="ov-card" id="ovIndicators" aria-labelledby="ovIndicatorsTitle"><h2 id="ovIndicatorsTitle">整体课程指标</h2>'+kpis+
      '<h3 id="ov-categories">四个类目得分 · 学校 vs 系统（10分制）</h3><div class="ov-legend"><span><i style="background:#1f5fbf"></i>学校标准评分</span><span><i style="background:#4fc3f7"></i>系统增强评分</span><span><i style="background:#d69d31"></i>6 分试行参考线</span></div>'+
      (cats.some(function(c){return c.school!=null||c.system!=null;})?chart(cats):'<p class="ov-empty">本课还没有课程评价，类目得分待评价后显示。</p>')+
      '<h3>10 个条目得分</h3><div class="ov-table-wrap"><table class="ov-table" id="ovItems"><thead><tr><th>序号</th><th>评价条目</th><th>所属类目</th><th>学校分</th><th>系统分</th><th>分差（系统−学校）</th></tr></thead><tbody>'+itemRows+'</tbody></table></div>'+
      '<h3>课程任务目标达成</h3>'+(goalRows?'<div class="ov-table-wrap"><table class="ov-table"'+ida('ovGoals')+'><thead><tr><th>目标编号</th><th>目标描述</th><th>通过标准</th><th>达成学生 / 纳入学生</th><th>有已复核测量的学生</th></tr></thead><tbody>'+goalRows+'</tbody></table></div><p class="ov-note">达成 = 该生该目标已复核且证据充分的综合分平均 ≥ 6。</p>':'<p class="ov-empty"'+ida('ovGoals')+'>本课还没有确认课程任务，目标达成表待上传课程任务后显示。</p>')+
      '<p class="ov-note">'+esc(cov.note||'')+'</p></section>';
  }
  function timeline(tl,colors,labels){
    if(!tl||!tl.available)return '<span class="ov-note">无视频时间轴</span>';
    var W=170,H=16,dur=Number(tl.duration_sec)||Math.max.apply(null,tl.segments.map(function(s){return s.end_sec;}))||1;
    var rects=tl.segments.map(function(s){var x=W*Math.max(0,s.start_sec)/dur,w=Math.max(1,W*(s.end_sec-s.start_sec)/dur);return '<rect x="'+x.toFixed(1)+'" y="2" width="'+w.toFixed(1)+'" height="12" fill="'+(colors[s.state]||'#c9d3df')+'"><title>'+esc((labels[s.state]||s.state)+' '+Math.round(s.start_sec)+'–'+Math.round(s.end_sec)+'秒')+'</title></rect>';}).join('');
    return '<svg class="ov-timeline" viewBox="0 0 '+W+' '+H+'" role="img" aria-label="学生状态时间轴迷你图"><rect x="0" y="2" width="'+W+'" height="12" fill="#eef2f7"/>'+rects+'</svg>';
  }
  function matrix(ov,admin){
    var rows=ov.students||[],colors=ov.state_colors||{},labels=ov.state_labels||{};
    var legend='<div class="ov-legend">'+Object.keys(labels).map(function(k){return '<span><i style="background:'+esc(colors[k]||'#c9d3df')+'"></i>'+esc(labels[k])+'</span>';}).join('')+'</div>';
    var body=rows.length?rows.map(function(r,i){var name=r.display_name||('学生'+(i+1));var flags=(r.flags||[]).map(function(f){return '<span class="ov-flag">'+esc(f)+'</span>';}).join(' ');
      return '<tr data-ov-student="'+esc(r.student_id)+'" data-href="'+esc(admin?'':r.measurement_href)+'" tabindex="0" aria-label="'+esc(name)+'：打开测量记录"><td><div class="ov-who"><span class="ov-avatar" data-ov-avatar="'+esc(r.student_id)+'">'+esc(String(name).trim().charAt(0)||'学')+'</span><span><strong>'+esc(name)+'</strong><small>'+esc(admin?'':(r.student_code||''))+'</small>'+(r.evidence_insufficient?'<span class="ov-flag">证据不足</span>':'')+'</span></div></td>'+
        DIMS.map(function(d){return '<td class="num">'+num((r.dimensions||{})[d[0]])+'</td>';}).join('')+
        '<td class="num"><strong>'+num(r.composite)+'</strong></td><td class="num">'+Number(r.goals_achieved)+' / '+Number(r.goals_total)+'<small> · 达成度 '+num(r.attainment,1)+'</small></td><td>'+timeline(r.timeline,colors,labels)+'</td><td>'+flags+(admin?'':'<div class="ov-actions">'+link(r.measurement_href,'测量记录')+link(r.report_href,'单次报告')+'</div>')+'</td></tr>';}).join(''):
      '<tr><td colspan="10" class="ov-empty">本课还没有纳入检测的学生。</td></tr>';
    return '<section class="ov-card" id="ovStudents" aria-labelledby="ovStudentsTitle"><span id="ov-students"></span><h2 id="ovStudentsTitle">学生评价矩阵</h2>'+(admin?'':'<section class="ov-switch" id="ovSwitch" hidden></section>')+
      '<p class="ov-note">'+(admin?'公司后台只显示化名与汇总分，不含学生编号、IEP 和教师端链接。':'点击某一行进入该生的测量记录；在测量页可用「切换学生」条切到同课其他学生。')+'</p>'+legend+
      '<div class="ov-table-wrap"><table class="ov-table ov-matrix" id="ovMatrix"><thead><tr><th>学生</th>'+DIMS.map(function(d){return '<th>'+d[1]+'</th>';}).join('')+'<th>综合分</th><th>目标达成</th><th>状态时间轴</th><th>标记 / 操作</th></tr></thead><tbody>'+body+'</tbody></table></div></section>';
  }
  function bindAvatars(host,ov,taskId,state){
    if(!window.RxUI||!window.RxUI.loadLessonPersons||!taskId)return Promise.resolve(null);
    return window.RxUI.loadLessonPersons(taskId).then(function(data){
      var byStudent={};((data&&data.persons)||[]).forEach(function(p){if(p.student_id&&p.avatar)byStudent[p.student_id]=p;});
      host.querySelectorAll('[data-ov-avatar]').forEach(function(el){var p=byStudent[el.getAttribute('data-ov-avatar')];var url=p&&window.RxUI.personAvatarUrl?window.RxUI.personAvatarUrl(taskId,p.avatar):'';if(!url)return;var img=document.createElement('img');img.className='ov-avatar';img.alt=el.textContent+' 头像';img.src=url;img.width=44;img.height=44;img.addEventListener('error',function(){img.replaceWith(el);});el.replaceWith(img);});
      state.avatars=byStudent;return byStudent;
    });
  }
  function selectRow(host,sid){host.querySelectorAll('[data-ov-student]').forEach(function(tr){tr.classList.toggle('is-selected',tr.getAttribute('data-ov-student')===sid);});}
  function render(host,ov,opts){
    opts=opts||{};if(!host)return;var admin=opts.viewer==='company_admin'||ov.viewer==='company_admin';
    if(!ov||ov.available===false){host.innerHTML='<div class="ov-card ov-stale">'+esc((ov&&ov.error)||'课程总览暂时无法计算，请稍后刷新')+'</div>';return;}
    host.innerHTML=(opts.staleNotice?'<div class="ov-stale" id="ovStaleNotice">'+esc(opts.staleNotice)+'</div>':'')+head(ov)+conclusion(ov,admin)+indicators(ov)+matrix(ov,admin)+'<p class="ov-note">'+esc(ov.boundary||'')+'</p>';
    host.querySelectorAll('[data-ov-jump]').forEach(function(a){a.addEventListener('click',function(e){var id=a.getAttribute('data-ov-jump').replace(/^#/,'');var t=document.getElementById(id);if(!t)return;e.preventDefault();t.scrollIntoView({behavior:'smooth',block:'center'});if(t.tagName==='TR'){t.classList.add('is-selected');setTimeout(function(){t.classList.remove('is-selected');},2400);}});});
    if(admin)return;
    host.querySelectorAll('[data-ov-student]').forEach(function(tr){
      var go=function(e){if(e.target.closest&&e.target.closest('a'))return;var href=tr.getAttribute('data-href');if(href)location.assign(href);};
      tr.addEventListener('click',go);tr.addEventListener('keydown',function(e){if(e.key==='Enter')go(e);});
    });
    var state={};
    bindAvatars(host,ov,opts.taskId||ov.task_id,state).then(function(){
      var sw=host.querySelector('#ovSwitch');if(!sw||!window.RxUI||!window.RxUI.studentSwitcher||(ov.students||[]).length<1)return;
      var items=(ov.students||[]).map(function(r,i){var p=(state.avatars||{})[r.student_id];return {key:r.student_id,student_id:r.student_id,person_id:p?p.person_id:'',title:r.display_name||('学生'+(i+1)),subtitle:(r.student_code?r.student_code+' · ':'')+'综合分 '+num(r.composite),avatarUrl:p&&window.RxUI.personAvatarUrl?window.RxUI.personAvatarUrl(opts.taskId||ov.task_id,p.avatar):'',initial:r.display_name,status:r.evidence_insufficient?'unbound':'bound',statusText:r.evidence_insufficient?'证据不足':'已复核'};});
      var switcher=window.RxUI.studentSwitcher(sw,{page:'course_overview',taskId:opts.taskId||ov.task_id,param:'student_id',label:'切换学生',note:'点击卡片在矩阵中定位该学生；点击矩阵中的行进入该生测量记录，测量页同样可以切换同课其他学生。',onSelect:function(item){selectRow(host,item.student_id);}});
      sw.hidden=false;var picked=switcher.update(items,undefined);if(picked)selectRow(host,picked.student_id);
    });
  }
  window.CourseOverview={render:render};
})();
"""


_PAGE = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>课程总览</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f4f8fd;color:#23334a;font:15px/1.65 "Microsoft YaHei UI","PingFang SC","Segoe UI",sans-serif}
a{color:#1f5fbf}main{max-width:1280px;margin:0 auto;padding:24px 28px 60px;min-width:0}[hidden]{display:none!important}
.ov-page-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-end;flex-wrap:wrap;margin-bottom:16px}.ov-page-head h1{margin:2px 0 4px;font-size:24px}
.ov-page-head p{margin:0;color:#62758c;font-size:13px}.ov-page-actions{display:flex;gap:8px;flex-wrap:wrap}
#ovMessage:empty{display:none}#ovMessage{margin:0 0 12px;padding:10px 12px;border-radius:6px;background:#fff4f4;color:#a33a3a;border:1px solid #f0c4c4}
__OVERVIEW_CSS__
</style></head><body>
<header></header>
<main>
<div class="ov-page-head"><div><div class="ov-kicker" id="ovKicker">教师工作台 · 课堂复核与分析</div><h1>课程总览（系统大纲）</h1><p>同时看每个学生的评价和整体课程指标，判断这节课好还是不好。等级为试行口径。</p></div>
<div class="ov-page-actions"><a class="rx-btn rx-btn-secondary" id="ovAnalysisLink" href="/demo2/analysis">返回课堂分析</a><a class="rx-btn rx-btn-secondary" id="ovEvaluationLink" href="/demo2/evaluation">课程评价</a><button class="rx-btn rx-btn-primary" id="ovRefresh" type="button">刷新</button></div></div>
<div id="ovMessage" role="alert"></div>
<div id="ovRoot" class="ov-root" aria-live="polite"><div class="ov-card">正在汇总本课数据…</div></div>
</main>
<script>
__OVERVIEW_JS__
(function(){
  'use strict';
  var taskId=new URLSearchParams(location.search).get('task_id')||'', viewer='__VIEWER__';
  var $=function(id){return document.getElementById(id);};
  if(viewer==='company_admin'){$('ovKicker').textContent='公司后台 · 任务查询';$('ovAnalysisLink').href='/demo2/admin#taskQueryTitle';$('ovAnalysisLink').textContent='返回任务查询';$('ovEvaluationLink').hidden=true;}
  else{$('ovAnalysisLink').href='/demo2/analysis?task_id='+encodeURIComponent(taskId);$('ovEvaluationLink').href='/demo2/evaluation?task_id='+encodeURIComponent(taskId);}
  function load(){
    $('ovMessage').textContent='';$('ovRefresh').disabled=true;
    return fetch('/api/v1/demo2/course-overview?task_id='+encodeURIComponent(taskId),{cache:'no-store',credentials:'same-origin'})
      .then(function(r){return r.json().catch(function(){return {};}).then(function(j){if(!r.ok||j.ok===false){var e=new Error((j.error&&j.error.message)||'课程总览加载失败，请稍后重试');e.status=r.status;throw e;}return j;});})
      .then(function(j){var ov=j.overview||{};if(ov.course_name)document.title='WeGlow微光系统 · 课程总览 · '+ov.course_name;
        window.CourseOverview.render($('ovRoot'),ov,{taskId:taskId,viewer:viewer,staleNotice:j.stale?'教师端数据已在本快照生成后变化，以下为上次生成时的课程总览；教师重新打开课堂分析后会自动更新。':''});})
      .catch(function(e){$('ovMessage').textContent=e.message;$('ovRoot').innerHTML='';})
      .then(function(){$('ovRefresh').disabled=false;});
  }
  $('ovRefresh').addEventListener('click',load);
  load();
})();
</script></body></html>"""


def render_course_overview(account: dict[str, Any] | None = None) -> str:
    from .demo2_ui_kit import header_for, inject_kit

    viewer = "company_admin" if (account or {}).get("role") == "company_admin" else "teacher"
    html = (_PAGE.replace("__OVERVIEW_CSS__", OVERVIEW_CSS).replace("__OVERVIEW_JS__", OVERVIEW_JS)
            .replace("__VIEWER__", viewer))
    header = header_for(account, "evaluation", admin_active="tasks", page="course_overview", logout_bound=False)
    return inject_kit(html, header=header, page="course_overview")


__all__ = [
    "OVERVIEW_CSS", "OVERVIEW_JS", "OVERVIEW_VERSION", "OverviewError", "SECTION_SOURCE", "SECTION_TITLE",
    "admin_view", "attach_course_overview", "build_overview", "check_task_access", "overview_section",
    "pick_course_evaluation", "render_course_overview",
]
