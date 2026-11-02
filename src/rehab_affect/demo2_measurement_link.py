"""Video measurement link: one archived lesson → pending, teacher-reviewable measurement records.

After a teacher binds a detected person to a student and saves the lesson
(「绑定并保存本课记录」), every confirmed course-task goal of that course gets
one ``source_type='video'`` measurement record for the student, status
「待教师复核」. The record carries the stable chain (school_id, student_id,
iep_document_id, course_id, video_task_id, course_task_doc_id), the goal's
pass criteria and measurement conditions, the confirmed IEP support points,
the per-person video indicators and evidence segment links.

System-suggested four-dimension scores are stored separately as
``suggested_scores`` and labelled 「建议·待复核」: the formal ``scores`` stay
empty and ``reviewed`` stays False, so nothing enters a trend line, a report
score or a pass judgement until the teacher reviews it through the normal
measurement save (which still enforces identity and applicability rules).

The completeness check compares, per bound task, the confirmed goals, the
confirmed IEP points and the key video indicators with what the measurement
records and the saved classroom report contain; the backfill re-creates
what is missing. Debug lines go to ``measurement_link_YYYYMMDD.jsonl`` (same
directory as ``measurement_debug_*``) with IDs, counts and statuses only.
"""
from __future__ import annotations

import json
import logging
import math
import re
import sqlite3
import statistics
import threading
from datetime import date, datetime, timedelta
from typing import Any, Callable
from uuid import uuid4

from .assessment_rubric import RUBRIC_VERSION, build_assessment_summary
from .demo2_course_task_store import current_for_course
from .demo2_iep_intake import manual_supplement_body
from .demo2_measurement_debug import measurement_log_dir
from .evaluation_report_contract import school_id_from_context
from .student_record_store import _iso

DEBUG_LOGGER = logging.getLogger("rehab_affect.measurement_link")
LINK_OPERATIONS = frozenset({
    "video_measurement_create", "measurement_prefill", "measurement_review",
    "completeness_check", "completeness_backfill",
})
VIDEO_SOURCE = "video"
VIDEO_SOURCE_TYPES = frozenset({"video_review", VIDEO_SOURCE})
SUGGESTION_LABEL = "建议·待复核"
SYSTEM_ACTOR = "system:video_archive"
DEFAULT_GOAL_ID = "VIDEO-PARTICIPATION"
DEFAULT_GOAL_TEXT = "课堂参与与回应（视频来源，本课未确认课程任务目标）"
DEFAULT_CONTEXT = "课堂视频（整节课）"
DEFAULT_CRITERION = "教师结合视频片段复核学生在本课任务中的参与、回应与所需支持；系统建议分只作参考。"
MAX_SEGMENTS = 12
# Key video indicators the completeness check requires on every video record.
METRIC_KEYS = ("engaged_segments", "low_response_segments", "away_segments", "not_observed_segments",
               "engaged_ratio", "participation_score_ref", "evidence_segments")
METRIC_LABELS = {
    "engaged_segments": "稳定参与片段数", "low_response_segments": "回应偏低片段数",
    "away_segments": "离开或不可见片段数", "not_observed_segments": "未观察片段数",
    "engaged_ratio": "参与时长占比", "participation_score_ref": "参与得分参考",
    "evidence_segments": "证据片段链接",
}
# Fields owned by this link: kept when a teacher reviews the record through the normal save.
LINK_FIELDS = (
    "origin", "school_id", "course_id", "video_task_id", "course_task_doc_id", "course_task_version",
    "goal_description", "pass_criteria", "measurement_conditions", "iep_document_id", "iep_reference_id",
    "iep_support", "iep_manual_supplement", "video_metrics", "evidence_segments", "lesson_summary",
    "suggested_scores", "suggested_opportunities", "suggested_observed", "suggestion_basis", "suggestion_label",
    "person_id", "archive_id", "lesson_date_source",
)
STATE_GROUPS = {
    "engaged": "engaged", "active_response": "engaged",
    "low_response": "low_response",
    "uncertain": "away", "not_visible": "away",
    "not_observed": "not_observed",
}
_LOCK = threading.Lock()
_ID_RE = re.compile(r"[A-Za-z0-9_.:-]{1,128}")
IepLoader = Callable[[str, str, str], "dict[str, Any] | None"]


class LinkError(ValueError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ---------------------------------------------------------------------------
# debug log
# ---------------------------------------------------------------------------

def short_id(value: Any) -> str:
    text = str(value or "")
    return text[:8] if _ID_RE.fullmatch(text) else ("" if not text else "<invalid>")


def measurement_link_event(store: Any, operation: str, result: str, **fields: Any) -> dict[str, Any]:
    """One JSON line; never contains goal/evidence/IEP text or student names."""
    entry: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "operation": operation if operation in LINK_OPERATIONS else "<invalid>",
        "result": result if isinstance(result, str) and _ID_RE.fullmatch(result) else "<invalid>",
    }
    for key, value in fields.items():
        if value is None:
            continue
        if key == "student_id":
            entry["student_short"] = short_id(value)
        elif key in {"task_id", "record_id", "course_id", "course_task_doc_id", "iep_document_id", "account_id",
                     "code", "status", "source_type"}:
            text = str(value)
            entry[key] = text if _ID_RE.fullmatch(text) else "<invalid>"
        elif key in {"record_ids"} and isinstance(value, list):
            entry[key] = [str(v) if _ID_RE.fullmatch(str(v)) else "<invalid>" for v in value[:60]]
        elif key in {"missing_count", "created_count", "updated_count", "unchanged_count", "goal_count",
                     "iep_item_count", "record_count", "version", "student_count", "http_status", "duration_ms"}:
            entry[key] = value if isinstance(value, int) and not isinstance(value, bool) else "<invalid>"
        elif key in {"missing_kinds"} and isinstance(value, dict):
            entry[key] = {str(k)[:40]: int(v) for k, v in value.items() if isinstance(v, int)}
        elif key in {"reviewed", "report_regenerated"}:
            entry[key] = value if isinstance(value, bool) else "<invalid>"
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    DEBUG_LOGGER.debug(line)
    try:
        folder = measurement_log_dir(store)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"measurement_link_{entry['ts'][:10].replace('-', '')}.jsonl"
        with _LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except (OSError, TypeError, ValueError):
        DEBUG_LOGGER.warning("measurement link log write failed")
    return entry


# ---------------------------------------------------------------------------
# pure helpers (no I/O)
# ---------------------------------------------------------------------------

def _clean(text: Any, limit: int) -> str:
    value = " ".join(str(text or "").replace("\x00", " ").split())
    value = "".join(ch for ch in value if ch.isprintable())
    return value[:limit]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _half(value: float) -> float:
    return max(0.0, min(10.0, round(value * 2) / 2))


def fmt_time(seconds: Any) -> str:
    value = max(0, int(round(_number(seconds) or 0)))
    return f"{value // 60:02d}:{value % 60:02d}"


def video_metrics(person: dict[str, Any]) -> dict[str, Any]:
    """Per-person indicator summary from the simple-analysis windows."""
    windows = [w for w in person.get("windows") or [] if isinstance(w, dict)]
    counts = {"engaged": 0, "low_response": 0, "away": 0, "not_observed": 0}
    durations = {key: 0.0 for key in counts}
    scores: list[float] = []
    total = 0.0
    for window in windows:
        start, end = _number(window.get("start_sec")), _number(window.get("end_sec"))
        span = max(0.0, (end or 0.0) - (start or 0.0)) if start is not None and end is not None else 0.0
        group = STATE_GROUPS.get(str(window.get("student_state") or window.get("state") or ""), "away")
        counts[group] += 1
        durations[group] += span
        total += span
        score = _number(window.get("student_score"))
        if score is None:
            score = _number(window.get("score"))
        if score is not None:
            scores.append(score)
    reference = _number(person.get("average_student_score"))
    if reference is None:
        reference = _number(person.get("average_score"))
    if reference is None and scores:
        reference = round(sum(scores) / len(scores), 1)

    def ratio(key: str) -> float:
        return round(durations[key] / total, 3) if total > 0 else 0.0

    return {
        "window_count": len(windows),
        "engaged_segments": counts["engaged"],
        "low_response_segments": counts["low_response"],
        "away_segments": counts["away"],
        "not_observed_segments": counts["not_observed"],
        "engaged_seconds": round(durations["engaged"], 1),
        "low_response_seconds": round(durations["low_response"], 1),
        "away_seconds": round(durations["away"], 1),
        "not_observed_seconds": round(durations["not_observed"], 1),
        "observed_seconds": round(total, 1),
        "engaged_ratio": ratio("engaged"),
        "low_response_ratio": ratio("low_response"),
        "away_ratio": ratio("away"),
        "not_observed_ratio": ratio("not_observed"),
        "participation_score_ref": round(reference, 1) if reference is not None else None,
        "score_samples": len(scores),
        "dominant_state": _clean(person.get("dominant_student_state_zh") or person.get("dominant_state_zh") or "", 40),
    }


def evidence_segments(task_id: str, person: dict[str, Any]) -> list[dict[str, Any]]:
    """Up to 12 time slices, preferring engaged/response windows, each linking to /demo2/video."""
    windows = [w for w in person.get("windows") or [] if isinstance(w, dict)
               and _number(w.get("start_sec")) is not None and _number(w.get("end_sec")) is not None]
    priority = {"engaged": 0, "low_response": 1, "not_observed": 2, "away": 3}
    ranked = sorted(windows, key=lambda w: (priority.get(STATE_GROUPS.get(str(w.get("student_state") or ""), "away"), 3),
                                            _number(w.get("start_sec")) or 0.0))[:MAX_SEGMENTS]
    ranked.sort(key=lambda w: _number(w.get("start_sec")) or 0.0)
    result = []
    for window in ranked:
        start, end = _number(window["start_sec"]), _number(window["end_sec"])
        state = str(window.get("student_state") or window.get("state") or "")
        result.append({
            "start_sec": round(start, 2), "end_sec": round(end, 2),
            "state": STATE_GROUPS.get(state, "away"),
            "state_label": _clean(window.get("student_state_zh") or window.get("state_zh") or "待观察", 30),
            "score": _number(window.get("student_score")),
            "url": f"/demo2/video?id={task_id}&t={int(start)}",
        })
    return result


def suggest_scores(metrics: dict[str, Any]) -> dict[str, Any]:
    """System suggestion from video cues only; never a reviewed score.

    accuracy ≈ participation reference, independence ≈ share of engaged time
    among response opportunities, consistency ≈ spread of window scores;
    transfer is left empty because one lesson video has no new context.
    """
    engaged, low = metrics["engaged_segments"], metrics["low_response_segments"]
    opportunities = engaged + low + metrics["away_segments"]
    observed = engaged + low
    reference = metrics.get("participation_score_ref")
    accuracy = _half(reference) if reference is not None else None
    response_time = metrics["engaged_seconds"] + metrics["low_response_seconds"]
    independence = _half(10 * metrics["engaged_seconds"] / response_time) if response_time > 0 else None
    consistency = None
    if observed >= 2:
        share = engaged / observed
        consistency = _half(10 * (0.5 + abs(share - 0.5)))
    scores = {"accuracy": accuracy, "independence": independence, "consistency": consistency, "transfer": None}
    basis = (f"按视频片段推算：稳定参与 {engaged} 段、回应偏低 {low} 段、离开或不可见 {metrics['away_segments']} 段、"
             f"未观察 {metrics['not_observed_segments']} 段；参与线索参考分 "
             f"{'—' if reference is None else f'{reference:g}'}/10。准确性参考参与线索分，独立性参考稳定参与时长占比，"
             "一致性参考各片段状态是否一致；泛化性需在新材料或新场景中观察，单节视频建议留空。"
             "以上为系统建议，须教师复核后才计分。")
    return {"scores": scores, "opportunities": opportunities, "observed": observed, "basis": basis}


def goal_entries(course_task: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not course_task:
        return [{"goal_code": DEFAULT_GOAL_ID, "description": DEFAULT_GOAL_TEXT, "pass_criteria": "",
                 "measurement_conditions": "", "rubric_dimension": "process"}]
    return [g for g in course_task.get("goals") or [] if isinstance(g, dict) and g.get("goal_code")]


def iep_items_from_document(document: dict[str, Any] | None) -> tuple[list[dict[str, Any]], str]:
    """Confirmed IEP support points of one dossier version (intake items, else summary fields)."""
    if not isinstance(document, dict):
        return [], ""
    intake = document.get("intake") if isinstance(document.get("intake"), dict) else None
    items: list[dict[str, Any]] = []
    manual = ""
    if intake:
        for item in intake.get("items") or []:
            if isinstance(item, dict) and str(item.get("text") or "").strip():
                items.append({"item_id": str(item.get("item_id") or f"s{len(items) + 1:02d}")[:8],
                              "category": str(item.get("category") or "")[:40],
                              "category_label": _clean(item.get("category_label") or "", 20),
                              "text": _clean(item.get("text"), 300), "page": item.get("page")})
        manual = _clean(intake.get("manual_supplement") or "", 1000)
    else:
        summary = document.get("summary") if isinstance(document.get("summary"), dict) else {}
        labels = {"learning_goals": "学习目标", "support_methods": "支持方式", "safety_notes": "注意事项"}
        for key, label in labels.items():
            for index, line in enumerate(str(summary.get(key) or "").splitlines(), start=1):
                if line.strip():
                    items.append({"item_id": f"{key[:1]}{index:02d}", "category": key, "category_label": label,
                                  "text": _clean(line, 300), "page": None})
    return items[:60], manual


# ---------------------------------------------------------------------------
# read-side helpers shared with the measurement/report stores
# ---------------------------------------------------------------------------

def iep_access(db, document_id: str, reference_id: str = "") -> tuple[bool, str]:
    """Whether stored IEP points may still be shown (authorization, version and lesson reference)."""
    if not document_id:
        return False, "not_linked"
    from .demo2_dossier_store import material_access_state
    try:
        state = material_access_state(db, document_id=document_id, purpose="analysis")
    except sqlite3.Error:
        return False, "dossier_unavailable"
    if not state.get("available"):
        return False, str(state.get("reason") or "unavailable")
    if reference_id:
        try:
            row = db.execute("SELECT withdrawn_at FROM demo2_dossier_references WHERE reference_id=?",
                             (reference_id,)).fetchone()
        except sqlite3.Error:
            row = None
        if row is None:
            return False, "reference_missing"
        if str(row[0] or ""):
            return False, "reference_withdrawn"
    return True, "available"


IEP_UNAVAILABLE_TEXT = {
    "authorization_withdrawn": "资料授权已撤回", "authorization_expired": "资料授权已到期",
    "document_withdrawn": "IEP 版本已撤回", "document_expired": "IEP 已过保存期", "document_deleted": "IEP 已删除",
    "document_missing": "IEP 资料不存在", "reference_withdrawn": "本课 IEP 引用已撤回",
    "reference_missing": "本课 IEP 引用不存在", "not_linked": "本课未关联 IEP",
    "dossier_unavailable": "资料服务暂不可用",
}


def gate_iep(db, record: dict[str, Any]) -> dict[str, Any]:
    """Hide stored IEP points once the authorization/reference no longer allows them."""
    if record.get("source_type") != VIDEO_SOURCE:
        return record
    document_id = str(record.get("iep_document_id") or "")
    ok, reason = iep_access(db, document_id, str(record.get("iep_reference_id") or "")) if document_id else (False, "not_linked")
    record = dict(record)
    record["iep_status"] = "available" if ok else reason
    record["iep_status_label"] = "已读取本课 IEP 支持条件" if ok else IEP_UNAVAILABLE_TEXT.get(reason, "IEP 不可用")
    if not ok:
        record["iep_support"] = []
        record["iep_manual_supplement"] = ""
    return record


def measurement_refs(db, owner_account_id: str, task_id: str) -> list[dict[str, Any]]:
    """Active measurement records of one task (IDs, goal, review state, formal score)."""
    if not task_id or not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo2_measurements'").fetchone():
        return []
    rows = db.execute("""SELECT record_id,student_id,goal_id,version,payload_json FROM demo2_measurements
        WHERE owner_account_id=? AND status='active' AND json_extract(payload_json,'$.task_id')=?
        ORDER BY lesson_date, record_id""", (owner_account_id, task_id)).fetchall()
    refs = []
    for row in rows:
        data = json.loads(row["payload_json"])
        refs.append({"record_id": row["record_id"], "student_id": row["student_id"], "goal_id": row["goal_id"],
                     "version": row["version"], "source_type": data.get("source_type", ""),
                     "reviewed": bool(data.get("reviewed")),
                     "score": (data.get("assessment") or {}).get("score"),
                     "course_task_doc_id": data.get("course_task_doc_id", "")})
    return refs


def _segment_text(segments: list[dict[str, Any]], limit: int = 4) -> str:
    return "、".join(f"{fmt_time(s.get('start_sec'))}–{fmt_time(s.get('end_sec'))}" for s in segments[:limit])


def _metrics_text(metrics: dict[str, Any]) -> str:
    reference = metrics.get("participation_score_ref")
    return (f"稳定参与 {metrics.get('engaged_segments', 0)} 段（时长占比 {round(100 * (metrics.get('engaged_ratio') or 0))}%）、"
            f"回应偏低 {metrics.get('low_response_segments', 0)} 段、离开或不可见 {metrics.get('away_segments', 0)} 段、"
            f"未观察 {metrics.get('not_observed_segments', 0)} 段，参与得分参考 "
            f"{'—' if reference is None else f'{reference:g}'}/10")


def _suggested_text(scores: dict[str, Any]) -> str:
    labels = {"accuracy": "准确性", "independence": "独立性", "consistency": "一致性", "transfer": "泛化性"}
    return "、".join(f"{labels[k]}{'留空' if scores.get(k) is None else format(scores[k], 'g')}" for k in labels)


def _basis_sentence(record: dict[str, Any]) -> str:
    from .score_basis import measurement_basis_sentence
    return measurement_basis_sentence(record)


def build_measurement_sections(records: list[dict[str, Any]], names: dict[str, str]) -> dict[str, Any]:
    """Report chapters 「学生测量结果」 and 「IEP 支持要点（教师侧）」 plus structured rows."""
    video = [r for r in records if r.get("source_type") == VIDEO_SOURCE]
    rows, lines, iep_lines, iep_index = [], [], [], []
    for record in video:
        assessment = record.get("assessment") or {}
        score = assessment.get("score") if record.get("evidence_status", "current") == "current" else None
        reviewed = bool(record.get("reviewed"))
        name = names.get(record.get("student_id"), "学生")
        segments = record.get("evidence_segments") or []
        metrics = record.get("video_metrics") or {}
        rows.append({
            "record_id": record.get("record_id"), "student_id": record.get("student_id"),
            "goal_id": record.get("goal_id"), "goal_description": record.get("goal_description", ""),
            "pass_criteria": record.get("pass_criteria") or record.get("criterion", ""),
            "measurement_context": record.get("measurement_context", ""),
            "course_task_doc_id": record.get("course_task_doc_id", ""), "version": record.get("version"),
            "reviewed": reviewed, "score": score, "passed": assessment.get("passed") if score is not None else None,
            "review_label": ("教师已复核" if reviewed else "待教师复核"),
            "suggested_scores": None if reviewed else record.get("suggested_scores"),
            "suggestion_label": "" if reviewed else SUGGESTION_LABEL,
            "video_metrics": {k: metrics.get(k) for k in METRIC_KEYS if k != "evidence_segments"},
            "evidence_segments": [{k: s.get(k) for k in ("start_sec", "end_sec", "state_label", "url")} for s in segments],
            "iep_document_ref": record.get("iep_document_id", ""),
            # Teacher's own observation note (Word/PDF 「教师观察摘要」); only reviewed records carry it.
            "observation_summary": _clean(record.get("evidence"), 300) if reviewed else "",
        })
        status = (f"教师已复核，综合 {score:.2f}/10（{'达到' if assessment.get('passed') else '未达到'}6分参考线；"
                  f"{_basis_sentence(record)}）"
                  if reviewed and score is not None else
                  "教师已复核，但证据不足以形成综合分" if reviewed else
                  f"待教师复核；系统{SUGGESTION_LABEL}：{_suggested_text(record.get('suggested_scores') or {})}，不计入综合分")
        line = (f"{name} · {record.get('goal_id')}「{_clean(record.get('goal_description') or record.get('criterion'), 50)}」："
                f"{status}。视频指标：{_metrics_text(metrics)}")
        if segments:
            line += f"；证据片段 {_segment_text(segments)}"
        lines.append(line + "。")
        items = record.get("iep_support") or []
        manual = record.get("iep_manual_supplement") or ""
        if items or manual:
            key = (record.get("student_id"), record.get("iep_document_id"))
            if key not in {(e["student_id"], e["iep_document_id"]) for e in iep_index}:
                iep_index.append({"student_id": record.get("student_id"), "iep_document_id": record.get("iep_document_id", ""),
                                  "item_ids": [i.get("item_id") for i in items] + (["manual"] if manual else [])})
                points = "；".join(f"{i.get('category_label') or '要点'}：{i.get('text')}" for i in items)
                if manual:
                    points += ("；" if points else "") + f"教师补充：{manual_supplement_body(manual)}"
                iep_lines.append(f"{name}（IEP {short_id(record.get('iep_document_id'))} · {len(items)} 条确认要点）：{points.rstrip('。；;. ')}。")
    sections = []
    if video:
        reviewed_count = sum(1 for r in video if r.get("reviewed"))
        intro = (f"本课共有 {len(video)} 条视频来源测量记录（已复核 {reviewed_count} 条、待教师复核 {len(video) - reviewed_count} 条）。"
                 f"视频来源记录由系统在「绑定并保存本课记录」后生成，系统建议分标注「{SUGGESTION_LABEL}」，"
                 "只有教师复核后才进入趋势得分线和报告综合分。")
        sections.append({"title": "学生测量结果", "source": "student_measurement", "text": intro + "".join(lines)})
    if iep_lines:
        sections.append({"title": "IEP 支持要点（教师侧）", "source": "iep_support_points",
                         "text": "以下为教师确认的 IEP 课堂支持条件，仅用于本课教学支持与复核参考，不对外导出，也不证明目标已达成。"
                                 + "".join(iep_lines)})
    return {"sections": sections, "rows": rows, "iep_index": iep_index}


MEASUREMENT_TABLE_HEADERS = ("学生", "目标编号", "通过标准", "复核状态", "综合分 / 建议分", "视频指标", "证据片段")


def measurement_table_cells(row: dict[str, Any], names: dict[str, str]) -> list[str]:
    """Same cells for the Markdown download and the HTML report table (page JS mirrors this)."""
    metrics = row.get("video_metrics") or {}
    if row.get("reviewed"):
        score = row.get("score")
        score_text = f"{score:.2f}" if isinstance(score, (int, float)) else "证据不足，空缺"
    else:
        score_text = f"{SUGGESTION_LABEL}：{_suggested_text(row.get('suggested_scores') or {})}"
    return [names.get(row.get("student_id"), "学生"), str(row.get("goal_id") or ""),
            str(row.get("pass_criteria") or "未填写"), str(row.get("review_label") or ""), score_text,
            _metrics_text(metrics), _segment_text(row.get("evidence_segments") or [], 6) or "无"]


def measurement_table_markdown(rows: list[dict[str, Any]], names: dict[str, str]) -> list[str]:
    lines = ["| " + " | ".join(MEASUREMENT_TABLE_HEADERS) + " |", "| " + " | ".join("---" for _ in MEASUREMENT_TABLE_HEADERS) + " |"]
    for row in rows:
        if isinstance(row, dict):
            cells = measurement_table_cells(row, names)
            lines.append("| " + " | ".join(c.replace("|", "／").replace("\n", " ") for c in cells) + " |")
    return lines


def attach_measurement_report(workspace: dict[str, Any]) -> None:
    """Add the measurement chapters to a course workspace report (live page)."""
    report = workspace.get("report")
    if not isinstance(report, dict) or not isinstance(report.get("sections"), list):
        return
    names = {p.get("student_id"): p.get("display_name") or "学生" for p in workspace.get("people") or []}
    built = build_measurement_sections(workspace.get("records") or [], names)
    sections = [s for s in report["sections"] if s.get("source") not in {"student_measurement", "iep_support_points"}]
    sections.extend(built["sections"])
    report["sections"] = sections
    # Keys only appear when the lesson has video-source records, so older reports stay byte-identical.
    for key, value in (("student_measurements", built["rows"]), ("iep_points_index", built["iep_index"])):
        if value:
            report[key] = value
        else:
            report.pop(key, None)
    report["character_count"] = sum(len(s.get("text", "")) for s in sections)
    if "full_text" in report:
        report["full_text"] = "\n\n".join(s["title"] + "\n" + s["text"] for s in sections)


def teacher_iep_section(records_store: Any, owner_account_id: str, task_id: str,
                        names: dict[str, str]) -> dict[str, Any] | None:
    """Re-build the teacher-only IEP chapter from live (gated) records for report get/download."""
    with records_store._connect() as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo2_measurements'").fetchone():
            return None
        rows = db.execute("""SELECT payload_json FROM demo2_measurements WHERE owner_account_id=? AND status='active'
            AND json_extract(payload_json,'$.task_id')=? AND json_extract(payload_json,'$.source_type')=?
            ORDER BY lesson_date, record_id""", (owner_account_id, task_id, VIDEO_SOURCE)).fetchall()
        records = [gate_iep(db, json.loads(row["payload_json"])) for row in rows]
    built = build_measurement_sections(records, names)
    return next((s for s in built["sections"] if s["source"] == "iep_support_points"), None)


# ---------------------------------------------------------------------------
# service
# ---------------------------------------------------------------------------

class MeasurementLinkService:
    def __init__(self, records: Any, iep_loader: IepLoader | None = None):
        from .demo2_measurement_store import Demo2MeasurementStore
        self.records = records
        self.measurements = Demo2MeasurementStore(records)
        self.iep_loader = iep_loader

    # -- helpers ---------------------------------------------------------------
    def _account(self, token: str) -> dict[str, Any]:
        try:
            account = self.records.account_from_session(token)
        except ValueError:
            raise LinkError(401, "authentication_required", "请重新登录") from None
        if account.get("role") != "school_uploader":
            raise LinkError(403, "measurement_forbidden", "当前账号无此操作权限")
        return account

    def _task(self, db, account, task_id: str) -> dict[str, Any]:
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", task_id):
            raise LinkError(400, "invalid_task", "课堂任务编号无效")
        row = db.execute("SELECT * FROM video_analysis_tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None or row["account_id"] != account["account_id"]:
            raise LinkError(404, "task_unavailable", "任务不存在或当前账号无权访问")
        return dict(row)

    def _analysis(self, task: dict[str, Any]) -> dict[str, Any]:
        from .demo2_media_analysis import SIMPLE_ANALYSIS_VERSION
        cached = self.records._read_simple_analysis_cache(task, SIMPLE_ANALYSIS_VERSION)
        if cached and cached.get("status") == "completed":
            return cached.get("analysis") or {}
        try:
            return json.loads(task.get("processing_result_json") or "{}").get("simple_student_analysis") or {}
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _person(analysis: dict[str, Any], person_id: str) -> dict[str, Any] | None:
        return next((p for p in analysis.get("persons") or [] if isinstance(p, dict) and p.get("person_id") == person_id), None)

    @staticmethod
    def _archives(db, account, task_id: str, student_id: str | None = None) -> list[dict[str, Any]]:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo2_simple_lesson_archives'").fetchone():
            return []
        sql = "SELECT * FROM demo2_simple_lesson_archives WHERE task_id=? AND owner_account_id=?"
        params: list[Any] = [task_id, account["account_id"]]
        if student_id:
            sql += " AND student_id=?"
            params.append(student_id)
        return [dict(r) for r in db.execute(sql + " ORDER BY created_at, archive_id", params)]

    def _load_iep(self, token: str, student_id: str, document_id: str) -> tuple[list[dict[str, Any]], str, str]:
        """(items, manual, status) of the archive's IEP version; text never reaches logs."""
        if not document_id:
            return [], "", "not_linked"
        loader = self.iep_loader
        if loader is None:
            from .demo2_dossier_store import Demo2DossierStore

            def loader(tok: str, sid: str, doc: str) -> dict[str, Any] | None:
                workspace = Demo2DossierStore(self.records).student_workspace(tok, sid)
                return next((d for d in workspace.get("documents") or [] if d.get("document_id") == doc), None)
        try:
            document = loader(token, student_id, document_id)
        except Exception:  # dossier vault missing or unavailable: the record keeps IDs only
            return [], "", "dossier_unavailable"
        if not isinstance(document, dict) or not document.get("available", True):
            return [], "", "document_unavailable"
        items, manual = iep_items_from_document(document)
        return items, manual, "available"

    @staticmethod
    def _lesson_date(course_task: dict[str, Any] | None, task: dict[str, Any]) -> tuple[str, str]:
        today = date.today()
        if course_task and course_task.get("lesson_date"):
            try:
                value = date.fromisoformat(course_task["lesson_date"])
                if value <= today:
                    return value.isoformat(), "course_task"
            except ValueError:
                pass
        try:
            created = datetime.fromisoformat(str(task.get("created_at") or "").replace("Z", "+00:00")).date()
            if created <= today:
                return created.isoformat(), "task_created_at"
        except ValueError:
            pass
        return today.isoformat(), "today"

    def _existing_video(self, db, account, scope: str, task_id: str, student_id: str, goal_id: str):
        return db.execute("""SELECT * FROM demo2_measurements WHERE owner_account_id=? AND scope_key=? AND student_id=?
            AND status='active' AND json_extract(payload_json,'$.task_id')=?
            AND json_extract(payload_json,'$.source_type')=? AND goal_id=?
            ORDER BY updated_at DESC LIMIT 1""", (account["account_id"], scope, student_id, task_id, VIDEO_SOURCE,
                                                 goal_id)).fetchone()

    def _write(self, db, account, scope: str, data: dict[str, Any], *, previous) -> None:
        now = _iso()
        version = (previous["version"] if previous is not None else 0) + 1
        data.update(version=version, status="active", saved_by=SYSTEM_ACTOR, updated_at=now)
        from .score_basis import measurement_score_basis
        data["score_basis"] = measurement_score_basis(data, computed_at=now)
        content = json.dumps(data, ensure_ascii=False, allow_nan=False)
        if previous is None:
            expires = (datetime.now().astimezone() + timedelta(days=730)).isoformat(timespec="seconds")
            db.execute("INSERT INTO demo2_measurements VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (data["record_id"], account["account_id"], scope, data["student_id"], data["lesson_date"],
                        data["lesson_id"], data["goal_id"], data["measurement_context"], version, "active", content,
                        now, now, expires))
        else:
            db.execute("""UPDATE demo2_measurements SET lesson_date=?,lesson_id=?,goal_id=?,measurement_context=?,
                version=?,payload_json=?,updated_at=? WHERE record_id=?""",
                       (data["lesson_date"], data["lesson_id"], data["goal_id"], data["measurement_context"], version,
                        content, now, data["record_id"]))
        db.execute("INSERT INTO demo2_measurement_versions VALUES(?,?,?,?,?)",
                   (data["record_id"], version, content, SYSTEM_ACTOR, now))
        self.records._audit(db, account["username"], "measurement_video_linked", "measurement", data["record_id"],
                            {"version": version, "task_id": data["task_id"], "goal_id": data["goal_id"]})

    def _link_payload(self, *, task, archive, person, goal, course_task, scope_context, iep_items, iep_manual,
                      lesson_date, date_source, duration) -> dict[str, Any]:
        metrics = video_metrics(person)
        segments = evidence_segments(task["task_id"], person)
        metrics["evidence_segments"] = len(segments)
        suggestion = suggest_scores(metrics)
        conditions = _clean(goal.get("measurement_conditions"), 200)
        criterion = _clean(goal.get("pass_criteria") or goal.get("description") or DEFAULT_CRITERION, 2000)
        if not course_task:
            criterion = DEFAULT_CRITERION
        summary = _clean(archive.get("lesson_summary"), 1000)
        evidence = (f"系统根据课堂视频生成的待复核记录。视频指标：{_metrics_text(metrics)}。"
                    + (f"证据片段：{_segment_text(segments, 6)}。" if segments else "")
                    + (f"本课总结：{summary}" if summary else ""))[:2000]
        return {
            "origin": "video_archive",
            "school_id": school_id_from_context(scope_context),
            "course_id": task.get("course_id") or "",
            "video_task_id": task["task_id"],
            "course_task_doc_id": course_task["course_task_doc_id"] if course_task else "",
            "course_task_version": course_task["version"] if course_task else 0,
            "goal_description": _clean(goal.get("description"), 500),
            "pass_criteria": _clean(goal.get("pass_criteria"), 500),
            "measurement_conditions": conditions,
            "iep_document_id": archive.get("iep_document_id") or "",
            "iep_reference_id": archive.get("iep_reference_id") or "",
            "iep_support": iep_items,
            "iep_manual_supplement": iep_manual,
            "video_metrics": metrics,
            "evidence_segments": segments,
            "lesson_summary": summary,
            "suggested_scores": suggestion["scores"],
            "suggested_opportunities": suggestion["opportunities"],
            "suggested_observed": suggestion["observed"],
            "suggestion_basis": suggestion["basis"],
            "suggestion_label": SUGGESTION_LABEL,
            "person_id": archive.get("person_id") or "",
            "archive_id": archive.get("archive_id") or "",
            "lesson_date_source": date_source,
            # base fields used when a new record is created
            "_base": {
                "student_id": archive["student_id"], "lesson_date": lesson_date,
                "course_name": _clean(course_task.get("course_name") if course_task and course_task.get("course_name")
                                      else task.get("course_name") or task.get("original_filename") or "课堂视频", 200),
                "goal_id": _clean(goal.get("goal_code"), 200),
                "measurement_context": conditions or DEFAULT_CONTEXT,
                "criterion": criterion, "evidence": evidence, "duration": duration,
            },
        }

    def _sync_student(self, db, account, task, archive, course_task, token: str,
                      iep_cache: dict[str, tuple[list, str, str]], only_goals: set[str] | None = None) -> dict[str, Any]:
        """Create/refresh the student's video records for every goal; returns per-action record ids."""
        binding = db.execute("SELECT * FROM demo2_identity_bindings WHERE binding_id=?", (archive["binding_id"],)).fetchone()
        if binding is None or binding["status"] != "confirmed" or binding["role"] != "student":
            return {"created": [], "updated": [], "unchanged": [], "skipped": "binding_unavailable"}
        scope = binding["scope_key"]
        if db.execute("SELECT 1 FROM demo2_identity_students WHERE student_id=? AND owner_account_id=? AND scope_key=?",
                      (archive["student_id"], account["account_id"], scope)).fetchone() is None:
            return {"created": [], "updated": [], "unchanged": [], "skipped": "student_unavailable"}
        person = self._person(self._analysis(task), archive["person_id"])
        if person is None:
            return {"created": [], "updated": [], "unchanged": [], "skipped": "person_unavailable"}
        manifest = json.loads(task.get("processing_result_json") or "{}")
        duration = _number((manifest.get("media") or {}).get("duration_sec"))
        window_end = max((_number(w.get("end_sec")) or 0.0 for w in person.get("windows") or []), default=0.0)
        duration = duration if duration and duration > 0 else max(window_end, float(binding["time_sec"] or 0) + 1.0)
        context = self.measurements.identities._context(task.get("school_context_json"), required=False)
        key = archive.get("iep_document_id") or ""
        # IEP text is preloaded outside the write transaction (the dossier store writes its own audit rows).
        iep_items, iep_manual, iep_state = iep_cache.get(key) or ([], "", "not_linked" if not key else "dossier_unavailable")
        if not iep_items and not iep_manual and archive.get("iep_manual_supplement"):
            iep_manual = _clean(archive["iep_manual_supplement"], 1000)
        lesson_date, date_source = self._lesson_date(course_task, task)
        result: dict[str, Any] = {"created": [], "updated": [], "unchanged": [], "skipped": ""}
        for goal in goal_entries(course_task):
            code = _clean(goal.get("goal_code"), 200)
            if only_goals is not None and code not in only_goals:
                continue
            link = self._link_payload(task=task, archive=archive, person=person, goal=goal, course_task=course_task,
                                      scope_context=context, iep_items=iep_items, iep_manual=iep_manual,
                                      lesson_date=lesson_date, date_source=date_source, duration=duration)
            base = link.pop("_base")
            if key and iep_state != "available":
                # Dossier temporarily unreadable: never wipe IEP points that were already recorded.
                link.pop("iep_support")
                link.pop("iep_manual_supplement")
            previous = self._existing_video(db, account, scope, task["task_id"], archive["student_id"], base["goal_id"])
            if previous is not None:
                data = json.loads(previous["payload_json"])
                if not data.get("reviewed"):
                    # Unreviewed: refresh the prefilled goal/criterion/context too.
                    candidate = {**data, **link, "measurement_context": base["measurement_context"],
                                 "criterion": base["criterion"], "evidence": base["evidence"],
                                 "course_name": base["course_name"], "lesson_date": base["lesson_date"]}
                else:
                    candidate = {**data, **link}
                if all(candidate.get(k) == data.get(k) for k in set(candidate) | set(data)
                       if k not in {"version", "updated_at", "saved_by", "evidence_status"}):
                    result["unchanged"].append(previous["record_id"])
                    continue
                self._check_duplicate(db, account, scope, candidate, previous["record_id"])
                self._write(db, account, scope, candidate, previous=previous)
                result["updated"].append(previous["record_id"])
                continue
            record_id = "vm-" + uuid4().hex
            lesson_id = _clean(task.get("course_id") or task["task_id"], 120)
            data = {
                "record_id": record_id, "student_id": base["student_id"], "lesson_id": lesson_id,
                "course_name": base["course_name"], "goal_id": base["goal_id"],
                "measurement_context": base["measurement_context"], "criterion": base["criterion"],
                "evidence": base["evidence"], "lesson_date": base["lesson_date"],
                "scores": {"accuracy": None, "independence": None, "consistency": None, "transfer": None},
                "opportunities": 0, "observed": 0, "reviewed": False, "source_type": VIDEO_SOURCE,
                "task_id": task["task_id"], "start_sec": 0, "end_sec": round(duration, 2),
                "rubric_version": RUBRIC_VERSION,
                "assessment": build_assessment_summary({"accuracy": None, "independence": None, "consistency": None,
                                                        "transfer": None}, opportunities=0, observed=0, reviewed=False,
                                                       source="课堂视频系统生成，待教师复核"),
                "teacher_prompt": "", "student_response": "", "support_level": "unknown", "observed_state": "unknown",
                "response_mode": "unknown", "audio_quality": "unknown", "vocalization": "unknown",
                "speaker_confirmed": False, "vocalization_scope": "scene_unknown_speaker",
                "binding_id": binding["binding_id"], "frame_revision": binding["frame_revision"],
                "source_sha256": binding["source_sha256"], **link,
            }
            if self._duplicate(db, account, scope, data, record_id):
                data["lesson_id"] = _clean(f"{lesson_id}-{task['task_id'][:8]}", 120)
                if self._duplicate(db, account, scope, data, record_id):
                    result.setdefault("conflicts", []).append(base["goal_id"])
                    continue
            self._write(db, account, scope, data, previous=None)
            result["created"].append(record_id)
        return result

    @staticmethod
    def _duplicate(db, account, scope, data, record_id) -> bool:
        return db.execute("""SELECT 1 FROM demo2_measurements WHERE owner_account_id=? AND scope_key=? AND student_id=?
            AND lesson_id=? AND goal_id=? AND measurement_context=? AND record_id<>? AND status='active'""",
                          (account["account_id"], scope, data["student_id"], data["lesson_id"], data["goal_id"],
                           data["measurement_context"], record_id)).fetchone() is not None

    def _check_duplicate(self, db, account, scope, data, record_id) -> None:
        if self._duplicate(db, account, scope, data, record_id):
            data["lesson_id"] = _clean(f"{data['lesson_id']}-{str(data['task_id'])[:8]}", 120)

    # -- API: after 「绑定并保存本课记录」 -----------------------------------------
    def create_from_archive(self, token: str, archive: dict[str, Any]) -> dict[str, Any]:
        account = self._account(token)
        task_id, student_id = str(archive.get("task_id") or ""), str(archive.get("student_id") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", task_id):
            raise LinkError(400, "invalid_task", "课堂任务编号无效")
        cache = self._preload_iep(token, account, task_id, student_id)
        with self.records._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = self._task(db, account, task_id)
            rows = [a for a in self._archives(db, account, task_id, student_id)
                    if a.get("person_id") == archive.get("person_id")]
            if not rows:
                raise LinkError(404, "archive_unavailable", "本课归档不存在，请重新绑定并保存")
            course_task = current_for_course(db, account["account_id"], task.get("course_id") or "")
            outcome = self._sync_student(db, account, task, rows[0], course_task, token, cache)
        record_ids = outcome["created"] + outcome["updated"] + outcome["unchanged"]
        measurement_link_event(
            self.records, "video_measurement_create", outcome.get("skipped") or ("created" if outcome["created"] else "refreshed"),
            task_id=task_id, student_id=student_id, record_ids=record_ids, course_id=task.get("course_id") or None,
            course_task_doc_id=course_task["course_task_doc_id"] if course_task else None,
            iep_document_id=rows[0].get("iep_document_id") or None,
            created_count=len(outcome["created"]), updated_count=len(outcome["updated"]),
            unchanged_count=len(outcome["unchanged"]), goal_count=len(goal_entries(course_task)),
            status="pending_review")
        return {"task_id": task_id, "student_id": student_id, "record_ids": record_ids,
                "created": len(outcome["created"]), "updated": len(outcome["updated"]),
                "unchanged": len(outcome["unchanged"]), "skipped": outcome.get("skipped") or "",
                "status": "pending_review", "status_label": "待教师复核",
                "measurement_url": f"/demo2/measurement?student_id={student_id}"
                                   + (f"&record_id={record_ids[0]}#tab-form" if record_ids else "")}

    # -- API: open one pending record in 「记录测量」 ------------------------------
    def prefill(self, token: str, record_id: Any) -> dict[str, Any]:
        account = self._account(token)
        if not isinstance(record_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", record_id):
            raise LinkError(400, "invalid_id", "记录编号格式无效")
        with self.records._connect() as db:
            row = db.execute("SELECT * FROM demo2_measurements WHERE record_id=? AND owner_account_id=?",
                             (record_id, account["account_id"])).fetchone()
            if row is None or row["status"] != "active":
                measurement_link_event(self.records, "measurement_prefill", "not_found", record_id=record_id, http_status=404)
                raise LinkError(404, "record_unavailable", "记录不存在、已撤销或无权查看")
            data = self.measurements._effective_record(db, account, json.loads(row["payload_json"]))
            data["version"] = row["version"]
        measurement_link_event(self.records, "measurement_prefill", "ok", record_id=record_id,
                               task_id=data.get("task_id") or None, student_id=data.get("student_id"),
                               source_type=data.get("source_type"), reviewed=bool(data.get("reviewed")),
                               iep_item_count=len(data.get("iep_support") or []), status=data.get("evidence_status"))
        return data

    # -- API: completeness ---------------------------------------------------------
    def _expected(self, db, account, task, token, iep_cache) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        course_task = current_for_course(db, account["account_id"], task.get("course_id") or "")
        students = []
        for archive in self._archives(db, account, task["task_id"]):
            binding = db.execute("SELECT status,role FROM demo2_identity_bindings WHERE binding_id=?",
                                 (archive["binding_id"],)).fetchone()
            if binding is None or binding["status"] != "confirmed" or binding["role"] != "student":
                continue
            name_row = db.execute("SELECT display_name FROM demo2_identity_students WHERE student_id=?",
                                  (archive["student_id"],)).fetchone()
            document_id = archive.get("iep_document_id") or ""
            ok, reason = iep_access(db, document_id, archive.get("iep_reference_id") or "") if document_id else (False, "not_linked")
            items: list[dict[str, Any]] = []
            manual = ""
            iep_state = reason
            if ok:
                items, manual, iep_state = iep_cache.get(document_id) or ([], "", "dossier_unavailable")
            students.append({"archive": archive, "student_id": archive["student_id"],
                             "display_name": name_row["display_name"] if name_row else "学生",
                             "iep_ok": ok and iep_state == "available", "iep_state": iep_state,
                             "iep_item_ids": [i["item_id"] for i in items] + (["manual"] if manual else []),
                             "iep_labels": {**{i["item_id"]: f"{i.get('category_label') or 'IEP 要点'}（{i['item_id']}）"
                                               for i in items}, "manual": "IEP 教师补充"}})
        return students, course_task

    def _preload_iep(self, token: str, account, task_id: str, student_id: str | None = None) -> dict[str, tuple[list, str, str]]:
        """Decrypt each archive's IEP version before any write transaction is opened."""
        targets: list[tuple[str, str]] = []
        with self.records._connect() as db:
            for archive in self._archives(db, account, task_id, student_id):
                document_id = archive.get("iep_document_id") or ""
                if document_id and document_id not in {doc for _, doc in targets}:
                    if iep_access(db, document_id, archive.get("iep_reference_id") or "")[0]:
                        targets.append((archive["student_id"], document_id))
        return {document_id: self._load_iep(token, student, document_id) for student, document_id in targets}

    def _check(self, db, account, task, token, iep_cache: dict[str, tuple[list, str, str]]) -> dict[str, Any]:
        students, course_task = self._expected(db, account, task, token, iep_cache)
        goals = goal_entries(course_task)
        rows = db.execute("""SELECT record_id,student_id,goal_id,version,payload_json FROM demo2_measurements
            WHERE owner_account_id=? AND status='active' AND json_extract(payload_json,'$.task_id')=?
            AND json_extract(payload_json,'$.source_type')=?""",
                          (account["account_id"], task["task_id"], VIDEO_SOURCE)).fetchall()
        records = [{**json.loads(r["payload_json"]), "version": r["version"]} for r in rows]
        report_row = db.execute("""SELECT report_id,payload_json,status,frame_revision FROM demo2_reports WHERE task_id=?
            ORDER BY updated_at DESC LIMIT 1""", (task["task_id"],)).fetchone() if db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo2_reports'").fetchone() else None
        report = json.loads(report_row["payload_json"]).get("report", {}) if report_row else {}
        report_rows = {r.get("record_id"): r for r in report.get("student_measurements") or [] if isinstance(r, dict)}
        report_iep = {(e.get("student_id"), e.get("iep_document_id")): set(e.get("item_ids") or [])
                      for e in report.get("iep_points_index") or [] if isinstance(e, dict)}
        report_goals = {g.get("goal_code") for g in (report.get("course_task") or {}).get("goals") or [] if isinstance(g, dict)}
        missing: list[dict[str, Any]] = []
        coverage = []

        def miss(kind: str, student: dict[str, Any] | None, key: str, label: str, where: str) -> None:
            missing.append({"kind": kind, "student_id": student["student_id"] if student else "",
                            "student_name": student["display_name"] if student else "", "key": key,
                            "label": label, "where": where})

        if report_row is None and students:
            miss("report", None, "report", "课堂图文报告尚未生成", "report")
        for student in students:
            own = [r for r in records if r.get("student_id") == student["student_id"]]
            found_goals = 0
            for goal in goals:
                code = goal.get("goal_code")
                record = next((r for r in own if r.get("goal_id") == code), None)
                if record is None:
                    miss("course_goal", student, code, f"课程目标 {code} 的测量记录", "measurement")
                    continue
                found_goals += 1
                if course_task and record.get("course_task_doc_id") != course_task["course_task_doc_id"]:
                    miss("course_goal", student, code, f"课程目标 {code} 未关联当前课程任务版本", "measurement")
                metrics = record.get("video_metrics") or {}
                for metric in METRIC_KEYS:
                    present = bool(record.get("evidence_segments")) if metric == "evidence_segments" else (
                        metric in metrics and (metrics.get(metric) is not None or metric == "participation_score_ref"))
                    if not present:
                        miss("video_metric", student, f"{code}:{metric}", f"{code} 的视频指标「{METRIC_LABELS[metric]}」", "measurement")
                if report_row is not None and record["record_id"] not in report_rows:
                    miss("report_measurement", student, record["record_id"],
                         f"课堂报告「学生测量结果」缺少 {code} 记录", "report")
                elif report_row is not None and report_rows[record["record_id"]].get("version") != record.get("version"):
                    miss("report_measurement", student, record["record_id"],
                         f"课堂报告中 {code} 记录不是最新版本", "report")
            if student["iep_ok"]:
                held = set()
                for record in own:
                    held |= {i.get("item_id") for i in record.get("iep_support") or []}
                    if record.get("iep_manual_supplement"):
                        held.add("manual")
                for item_id in student["iep_item_ids"]:
                    if item_id not in held:
                        miss("iep_item", student, item_id, student["iep_labels"].get(item_id, f"IEP 要点 {item_id}"), "measurement")
                    if report_row is not None and item_id not in report_iep.get(
                            (student["student_id"], student["archive"].get("iep_document_id") or ""), set()):
                        miss("report_iep", student, item_id,
                             f"课堂报告「IEP 支持要点」缺少{student['iep_labels'].get(item_id, item_id)}", "report")
            coverage.append({"student_id": student["student_id"], "display_name": student["display_name"],
                             "goal_total": len(goals), "goal_found": found_goals,
                             "iep_status": student["iep_state"], "iep_item_total": len(student["iep_item_ids"]),
                             "record_ids": [r["record_id"] for r in own]})
        if course_task and report_row is not None:
            for goal in goals:
                if goal.get("goal_code") not in report_goals:
                    miss("report_goal", None, goal.get("goal_code"), f"课堂报告「本课任务目标」缺少 {goal.get('goal_code')}", "report")
        kinds: dict[str, int] = {}
        for item in missing:
            kinds[item["kind"]] = kinds.get(item["kind"], 0) + 1
        status = "no_archive" if not students else ("complete" if not missing else "incomplete")
        return {
            "task_id": task["task_id"], "course_id": task.get("course_id") or "",
            "course_task_doc_id": course_task["course_task_doc_id"] if course_task else "",
            "course_task_version": course_task["version"] if course_task else 0,
            "goal_count": len(goals) if course_task else 0,
            "report_id": report_row["report_id"] if report_row else "",
            "report_status": report_row["status"] if report_row else "",
            "status": status, "missing": missing, "missing_count": len(missing), "missing_kinds": kinds,
            "students": coverage, "video_record_count": len(records),
            "message": ("还没有绑定学生并保存本课记录，暂无需要核对的内容。" if status == "no_archive" else
                        "课程任务目标、IEP 确认要点与视频关键指标均已录入测量记录和课堂报告。" if status == "complete" else
                        "以下内容尚未录入：" + "；".join(m["label"] + (f"（{m['student_name']}）" if m["student_name"] else "")
                                                for m in missing[:12]) + ("…" if len(missing) > 12 else "")),
        }

    def completeness(self, token: str, task_id: str) -> dict[str, Any]:
        account = self._account(token)
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", task_id):
            raise LinkError(400, "invalid_task", "课堂任务编号无效")
        cache = self._preload_iep(token, account, task_id)
        with self.records._connect() as db:
            task = self._task(db, account, task_id)
            result = self._check(db, account, task, token, cache)
        measurement_link_event(self.records, "completeness_check", result["status"], task_id=task_id,
                               missing_count=result["missing_count"], missing_kinds=result["missing_kinds"],
                               student_count=len(result["students"]), record_count=result["video_record_count"],
                               course_task_doc_id=result["course_task_doc_id"] or None)
        return result

    def backfill(self, token: str, task_id: str, regenerate_report: Callable[[], Any] | None = None) -> dict[str, Any]:
        account = self._account(token)
        created = updated = 0
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", task_id):
            raise LinkError(400, "invalid_task", "课堂任务编号无效")
        cache = self._preload_iep(token, account, task_id)
        with self.records._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = self._task(db, account, task_id)
            before = self._check(db, account, task, token, cache)
            course_task = current_for_course(db, account["account_id"], task.get("course_id") or "")
            for archive in self._archives(db, account, task_id):
                outcome = self._sync_student(db, account, task, archive, course_task, token, cache)
                created += len(outcome["created"])
                updated += len(outcome["updated"])
        regenerated = False
        report_error = ""
        if regenerate_report is not None and before["status"] != "no_archive":
            try:
                regenerate_report()
                regenerated = True
            except Exception as exc:  # report regeneration failure must not undo the record backfill
                report_error = getattr(exc, "code", "") or type(exc).__name__
        after = self.completeness(token, task_id)
        measurement_link_event(self.records, "completeness_backfill", "complete" if after["status"] == "complete" else after["status"],
                               task_id=task_id, missing_count=after["missing_count"], created_count=created,
                               updated_count=updated, report_regenerated=regenerated,
                               code=report_error or None, missing_kinds=before["missing_kinds"])
        return {**after, "backfill": {"created": created, "updated": updated, "missing_before": before["missing_count"],
                                      "report_regenerated": regenerated, "report_error": report_error}}


def log_teacher_review(records: Any, data: dict[str, Any], previous_reviewed: Any, account_id: str) -> None:
    """Called from the measurement save for video-source records (separate file from measurement_debug)."""
    measurement_link_event(records, "measurement_review",
                           "reviewed" if data.get("reviewed") else ("review_revoked" if previous_reviewed else "draft_saved"),
                           record_id=data.get("record_id"), task_id=data.get("task_id") or None,
                           student_id=data.get("student_id"), account_id=account_id, version=data.get("version"),
                           reviewed=bool(data.get("reviewed")),
                           status="scored" if (data.get("assessment") or {}).get("score") is not None else "unscored")
