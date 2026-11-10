"""Stable contracts for the evaluation and classroom-report layer.

This module deliberately sits above upload, identity and dossier storage.  It
normalizes the identifiers that the evaluation/report side consumes without
trying to infer a student's identity or overwrite another team's data.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any, Iterable, Mapping


LINK_FIELDS = (
    "school_id",
    "student_id",
    "course_id",
    "task_id",
    "iep_summary_id",
    "evaluation_id",
    "report_id",
)


class EvaluationContractError(ValueError):
    """Raised when an evaluation/report link is incomplete or malformed."""


def _id(value: Any, field: str, *, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str) or len(value) > 160:
        raise EvaluationContractError(f"{field} 必须是 160 字符以内的稳定编号")
    value = value.strip()
    if required and not value:
        raise EvaluationContractError(f"{field} 不能为空")
    if value and any(ord(char) < 33 or ord(char) == 127 for char in value):
        raise EvaluationContractError(f"{field} 包含无效字符")
    return value


def school_id_from_context(context: Mapping[str, Any] | None) -> str:
    """Derive a non-sensitive, repeatable school key from selected context.

    The name is never returned by this helper.  A future directory-backed
    school ID can be passed directly to :func:`build_linkage` and will take
    precedence over this fallback.
    """
    context = context or {}
    parts = [str(context.get(key, "")).strip() for key in ("city", "district", "school_name")]
    if not any(parts):
        return ""
    canonical = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return "school-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def build_linkage(
    *,
    school_id: Any = "",
    school_context: Mapping[str, Any] | None = None,
    student_id: Any = "",
    course_id: Any = "",
    task_id: Any = "",
    iep_summary_id: Any = "",
    evaluation_id: Any = "",
    report_id: Any = "",
) -> dict[str, str]:
    """Return the complete stable-ID contract used by pages and reports."""
    resolved_school = _id(school_id, "school_id") or school_id_from_context(school_context)
    values = {
        "school_id": resolved_school,
        "student_id": _id(student_id, "student_id"),
        "course_id": _id(course_id, "course_id"),
        "task_id": _id(task_id, "task_id"),
        "iep_summary_id": _id(iep_summary_id, "iep_summary_id"),
        "evaluation_id": _id(evaluation_id, "evaluation_id"),
        "report_id": _id(report_id, "report_id"),
    }
    return values


def generated_report_id(task_id: str, evaluations: Iterable[Mapping[str, Any]] = ()) -> str:
    """Make a deterministic report ID for the current task/evaluation state."""
    normalized = []
    for evaluation in evaluations:
        normalized.append({
            "evaluation_id": evaluation.get("evaluation_id") or evaluation.get("record_id", ""),
            "version": evaluation.get("version", 0),
        })
    raw = json.dumps([task_id, sorted(normalized, key=lambda item: str(item["evaluation_id"]))],
                     ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "report-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _state_score(record: Mapping[str, Any], field: str) -> float | None:
    state = record.get(field)
    maps = {
        "observed_state": {"participating": 8.0, "help_requested": 7.0,
                           "repeat_prompt": 6.0, "paused": 5.0},
        "response_mode": {"speech": 8.0, "gesture": 8.0, "picture": 8.0,
                          "aac": 8.0, "gaze": 7.0, "action": 8.0,
                          "vocalization": 6.0, "mixed": 8.0},
        "support_level": {"independent": 9.0, "visual": 7.5, "verbal": 7.0,
                          "demonstration": 6.0, "physical": 5.0},
    }
    value = maps.get(field, {}).get(state)
    return value if value is None or math.isfinite(value) else None


def student_observation_summary(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize observed participation without converting missing evidence to 0.

    This is an observation summary, not an automatic diagnosis.  It is useful
    when a video has no complete four-dimension teacher score yet: the page can
    show participation, interaction and task-following evidence separately.
    """
    rows = [dict(row) for row in records if isinstance(row, Mapping)
            and row.get("evidence_status", "current") == "current"]
    if not rows:
        return {
            "status": "evidence_insufficient", "score_10": None, "confidence": None,
            "dimensions": {"participation": None, "interaction": None, "task_following": None},
            "evidence_count": 0,
            "reason": "没有可用的当前课堂证据，不能把缺失记录当作学生表现低分。",
        }
    dimensions = {
        "participation": _mean([value for row in rows if (value := _state_score(row, "observed_state")) is not None]),
        "interaction": _mean([value for row in rows if (value := _state_score(row, "response_mode")) is not None]),
        "task_following": _mean([value for row in rows if (value := _state_score(row, "support_level")) is not None]),
    }
    usable = [value for value in dimensions.values() if value is not None]
    observed = sum(bool(str(row.get("evidence", "")).strip()) for row in rows)
    confidence = round(min(1.0, observed / 3.0) * (len(usable) / 3.0), 2)
    if not usable or confidence < 0.5:
        return {
            "status": "evidence_insufficient", "score_10": None, "confidence": confidence,
            "dimensions": dimensions, "evidence_count": len(rows),
            "reason": "当前证据不足或置信度较低，显示为证据不足，不直接判定学生表现差。",
        }
    score = _mean(usable)
    # A regular, observable lesson should not be punished for an unrecorded
    # dimension.  Only the dimensions with evidence enter the mean.
    return {
        "status": "observed", "score_10": score, "confidence": confidence,
        "dimensions": dimensions, "evidence_count": len(rows),
        "reason": "分数仅根据当前可见课堂证据的参与、互动和任务跟随线索汇总；缺失维度未按零分计。",
    }


def build_task_report(
    *,
    task: Mapping[str, Any],
    school_context: Mapping[str, Any] | None,
    people: Iterable[Mapping[str, Any]],
    records: Iterable[Mapping[str, Any]],
    evaluations: Iterable[Mapping[str, Any]] = (),
    base_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Attach stable IDs and evidence-grounded report sections to a task."""
    task_id = str(task.get("task_id", "")).strip()
    course_id = str(task.get("course_id", "")).strip() or task_id
    evaluations = [dict(item) for item in evaluations if isinstance(item, Mapping)]
    records = [dict(item) for item in records if isinstance(item, Mapping)]
    people = [dict(item) for item in people if isinstance(item, Mapping)]
    report_id = generated_report_id(task_id, evaluations)
    linkage = build_linkage(
        school_context=school_context,
        course_id=course_id,
        task_id=task_id,
        report_id=report_id,
        evaluation_id=str(evaluations[0].get("evaluation_id") or evaluations[0].get("record_id", "")) if evaluations else "",
    )
    sections = list((base_report or {}).get("sections", []))
    existing_titles = {str(item.get("title", "")) for item in sections}
    if "双轨评价对照" not in existing_titles:
        comparisons = []
        for evaluation in evaluations:
            result = evaluation.get("result", {})
            comparison = result.get("comparison", {}) if isinstance(result, Mapping) else {}
            if comparison.get("available"):
                comparisons.append(
                    f"评价 {evaluation.get('evaluation_id') or evaluation.get('record_id', '未命名')}："
                    f"学校分 {result.get('school', {}).get('score_10', '—')}，"
                    f"系统增强分 {result.get('enhanced', {}).get('score_10', '—')}，"
                    f"总差值 {comparison.get('total_delta', '—')}。"
                    f"差值拆分为证据修正 {comparison.get('evidence_delta', '—')}、"
                    f"权重调整 {comparison.get('weight_delta', '—')}。"
                )
        sections.append({"title": "双轨评价对照", "text": "".join(comparisons) or "当前任务尚未保存完整的学校评分和系统增强评分，暂不虚构差值。"})
    if "学生状态摘要" not in existing_titles:
        student_lines = []
        for person in people:
            summary = student_observation_summary([row for row in records if row.get("student_id") == person.get("student_id")])
            student_lines.append(
                f"{person.get('display_name') or person.get('student_id') or '匿名学生'}："
                f"{summary['reason']} 观察条数 {summary['evidence_count']}，"
                f"状态摘要分 {summary['score_10'] if summary['score_10'] is not None else '未形成'} / 10。"
            )
        sections.append({"title": "学生状态摘要", "text": "".join(student_lines) or "当前任务尚未关联学生，暂不生成学生个体结论。"})
    if "证据限制与教学建议" not in existing_titles:
        sections.append({"title": "证据限制与教学建议", "text": (
            "建议教师优先复核关键时间段的任务指令、学生回应方式和支持等级。收音缺失、画面遮挡、多人同时回应或学生身份未确认时，"
            "相关结果标记为证据不足，不按低分处理。系统评分用于课堂复盘，不能替代教师判断、医学诊断或学校正式评价。"
        )})
    text = "\n\n".join(f"{item.get('title', '')}\n{item.get('text', '')}" for item in sections)
    result = dict(base_report or {})
    result.update({
        "report_id": report_id,
        "task_id": task_id,
        "course_id": course_id,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "identifiers": linkage,
        "evaluation_ids": [str(item.get("evaluation_id") or item.get("record_id", "")) for item in evaluations],
        "evaluation_versions": [{"evaluation_id": str(item.get("evaluation_id") or item.get("record_id", "")),
                                 "record_id": item.get("record_id", ""), "version": item.get("version", 0)}
                                for item in evaluations],
        "sections": sections,
        "full_text": text,
        "character_count": sum(len(str(item.get("text", ""))) for item in sections),
        "report_download_url": f"/api/v1/demo2/course-analysis/report?task_id={task_id}",
        "generation": "本地规则与教师复核记录（含学校评分和系统增强评价）；未调用外部大模型",
    })
    return result
