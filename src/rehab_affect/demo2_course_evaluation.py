"""课程评价：用本课已确认的数据为 basic_100 的 10 个条目生成「系统建议分」。

建议分只是给教师的预填参考：教师采纳后它才成为系统增强轨的条目分，
``classroom_rubric.evaluate`` 的计算口径不变。每个建议分都带一份依据
（数据来源、代入数值、命中锚点、引用的视频片段/测量记录），数据不足的
条目给出「证据不足，待教师评分」，不编造分数。

数据来源（全部按 owner_account_id + task_id 读取，不读其他账号数据）：
- 课程任务目标：``demo2_course_task_documents`` 中本课课程批次的最新确认版本；
- 学生覆盖率：本课纳入检测的学生（归档到本课的学生 + 本课视频测量记录的学生），
  以及其中有「稳定参与 / 回应」视频片段的学生；
- 测量综合分：本课各学生测量记录（教师已复核的综合分优先，否则用视频参与线索参考分并标注未复核）；
- 视频片段 + 教师观察记录：教师响应调节（回应偏低后恢复参与）需要两者同时具备。

课程评价只引用测量记录的 record_id 与汇总值，不保存学生个体能力分字段。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .classroom_rubric import TEMPLATES

SUGGESTION_VERSION = "2026-11-01.course-eval-suggest-v1"
TEMPLATE_ID = "basic_100"
INSUFFICIENT_LABEL = "证据不足，待教师评分"
SOURCE_LABELS = {
    "course_goal": "课程任务目标",
    "coverage": "学生覆盖率",
    "measurement": "测量综合分",
    "video": "视频片段",
    "teacher_observation": "教师观察记录",
}
# 每个条目可以使用的数据来源；未列出的来源不会被用来推算该条目。
ITEM_SOURCES: dict[str, tuple[str, ...]] = {
    "i1": ("course_goal",),
    "i2": ("teacher_observation",),
    "i3": ("teacher_observation",),
    "i4": ("course_goal", "measurement"),
    "i5": ("video",),
    "i6": ("measurement", "video"),
    "i7": ("coverage", "video"),
    "i8": ("measurement", "video"),
    "i9": ("teacher_observation",),
    "i10": ("video", "teacher_observation"),
}
# 系统无法从现有数据推算、必须由教师判断的条目及原因。
TEACHER_ONLY_REASONS = {
    "i2": "联系学生生活经验需要教师结合课堂内容判断，视频与测量数据无法推算。",
    "i3": "内容正确性与容量需要教案或专业复核，视频安静有序不能代替科学性证据。",
    "i9": "教师语言、示范与板书需要教师观察或同行听课记录，系统不从视频推断。",
}
_SYSTEM_ACTOR = "system:video_archive"
_GOAL_CODE = re.compile(r"[Gg]-?\d{1,3}")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def short_id(value: Any) -> str:
    text = str(value or "")
    for prefix in ("evaluation-", "vm-", "ctd-"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text[:8]


def _half(value: float) -> float:
    """Round to the nearest 0.5 and clamp to the system's 1—10 suggestion range."""
    rounded = float((Decimal(str(value)) * 2).quantize(Decimal("1"), rounding=ROUND_HALF_UP) / 2)
    return min(10.0, max(1.0, rounded))


def _shown(raw: float, score: float) -> str:
    """Formula result: the raw value, then the suggestion actually used when rounding/clamping changed it."""
    text = _fmt(round(raw, 2))
    return text if float(round(raw, 2)) == score else f"{text} → 建议 {_fmt(score)}（取 0.5 档，范围 1—10）"


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _pct(value: float) -> str:
    return f"{round(value * 100)}%"


def _fmt(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "—"
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _goal_key(value: Any) -> str:
    return re.sub(r"[\s_-]", "", str(value or "")).upper().replace("Ｇ", "G")


def _table(db, name: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _fmt_sec(seconds: Any) -> str:
    value = int(max(0.0, _num(seconds) or 0.0))
    return f"{value // 60:02d}:{value % 60:02d}"


# ------------------------------------------------------------------ data load

def load_lesson_data(db, owner_account_id: str, task: dict[str, Any]) -> dict[str, Any]:
    """Read everything a suggestion may cite for one owned task (no names, no IEP text)."""
    from .demo2_course_task_store import current_for_course

    task_id = str(task.get("task_id") or "")
    course_id = str(task.get("course_id") or "")
    course_task = current_for_course(db, owner_account_id, course_id) if course_id else None
    measurements: list[dict[str, Any]] = []
    if _table(db, "demo2_measurements"):
        for row in db.execute("""SELECT record_id,student_id,goal_id,version,payload_json FROM demo2_measurements
                WHERE owner_account_id=? AND status='active' AND json_extract(payload_json,'$.task_id')=?
                ORDER BY student_id, goal_id, record_id""", (owner_account_id, task_id)):
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, ValueError):
                continue
            measurements.append({"record_id": row["record_id"], "student_id": row["student_id"],
                                 "goal_id": row["goal_id"], "version": row["version"], "payload": payload})
    archived: list[str] = []
    if _table(db, "demo2_simple_lesson_archives"):
        archived = [r["student_id"] for r in db.execute(
            "SELECT DISTINCT student_id FROM demo2_simple_lesson_archives WHERE task_id=? AND owner_account_id=? "
            "ORDER BY student_id", (task_id, owner_account_id))]
    return {"task_id": task_id, "course_id": course_id, "course_task": course_task,
            "measurements": measurements, "archived_students": archived}


def data_fingerprint(data: dict[str, Any]) -> dict[str, Any]:
    """Stable description of the cited data; any change marks a locked evaluation as stale."""
    course_task = data.get("course_task") or {}
    measurement_versions = sorted([m["record_id"], int(m["version"])] for m in data.get("measurements") or [])
    students = sorted(set(data.get("archived_students") or []) |
                      {m["student_id"] for m in data.get("measurements") or []})
    body = {
        "course_task_doc_id": course_task.get("course_task_doc_id") or "",
        "course_task_version": course_task.get("version") or 0,
        "measurements": measurement_versions,
        "students": students,
    }
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return {**body, "student_count": len(students), "measurement_count": len(measurement_versions),
            "fingerprint": digest}


def stale_reasons(saved: dict[str, Any] | None, current: dict[str, Any]) -> list[str]:
    """Which cited data changed since the evaluation was saved (category codes only)."""
    if not isinstance(saved, dict) or not saved.get("fingerprint"):
        return []
    if saved.get("fingerprint") == current.get("fingerprint"):
        return []
    reasons = []
    if (saved.get("course_task_doc_id"), saved.get("course_task_version")) != (
            current.get("course_task_doc_id"), current.get("course_task_version")):
        reasons.append("course_task_changed")
    if saved.get("measurements") != current.get("measurements"):
        reasons.append("measurements_changed")
    if saved.get("students") != current.get("students"):
        reasons.append("students_changed")
    return reasons or ["data_changed"]


STALE_REASON_TEXT = {
    "course_task_changed": "课程任务已确认新版本",
    "measurements_changed": "本课学生测量记录已新增、修改或撤销",
    "students_changed": "本课纳入检测的学生已变化",
    "data_changed": "本课依据数据已变化",
}


# ------------------------------------------------------------ per-student view

def _student_views(data: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per included student: video metrics, segments, reviewed scores (record IDs only)."""
    students: dict[str, dict[str, Any]] = {}
    for student_id in data.get("archived_students") or []:
        students.setdefault(student_id, {"student_id": student_id, "records": []})
    for record in data.get("measurements") or []:
        students.setdefault(record["student_id"], {"student_id": record["student_id"], "records": []})
        students[record["student_id"]]["records"].append(record)
    views = []
    for student in students.values():
        metrics, segments, video_record = None, [], None
        reviewed_scores, independence, observations = [], [], []
        for record in student["records"]:
            payload = record["payload"]
            if payload.get("source_type") in {"video", "video_review"} and isinstance(payload.get("video_metrics"), dict):
                if metrics is None:
                    metrics = payload["video_metrics"]
                    segments = [s for s in payload.get("evidence_segments") or [] if isinstance(s, dict)]
                    video_record = record["record_id"]
            score = _num((payload.get("assessment") or {}).get("score"))
            if payload.get("reviewed") is True and score is not None:
                reviewed_scores.append((record["record_id"], record["goal_id"], score))
                ind = _num((payload.get("scores") or {}).get("independence"))
                if ind is not None:
                    independence.append(ind)
            evidence = str(payload.get("evidence") or "").strip()
            if payload.get("reviewed") is True and evidence and payload.get("saved_by") != _SYSTEM_ACTOR:
                observations.append(record["record_id"])
        views.append({"student_id": student["student_id"], "metrics": metrics, "segments": segments,
                      "video_record": video_record, "reviewed_scores": reviewed_scores,
                      "independence": independence, "observations": observations,
                      "record_ids": [r["record_id"] for r in student["records"]]})
    views.sort(key=lambda v: v["student_id"])
    return views


def _video_refs(task_id: str, views: list[dict[str, Any]], states: set[str], limit: int = 6) -> list[dict[str, Any]]:
    refs = []
    for index, view in enumerate(views, start=1):
        for segment in view["segments"]:
            if segment.get("state") not in states:
                continue
            start = _num(segment.get("start_sec"))
            if start is None:
                continue
            refs.append({"kind": "video", "label": SOURCE_LABELS["video"], "start_sec": start,
                         "end_sec": _num(segment.get("end_sec")),
                         "text": f"学生{index} {_fmt_sec(start)}–{_fmt_sec(segment.get('end_sec'))} "
                                 f"{str(segment.get('state_label') or '')[:20]}".strip(),
                         "url": f"/demo2/video?id={task_id}&t={int(start)}"})
            break
        if len(refs) >= limit:
            break
    return refs


# --------------------------------------------------------------- suggestions

def _entry(spec: dict[str, Any], category_label: str) -> dict[str, Any]:
    from .score_basis import CLASSROOM_ITEM_EVIDENCE

    return {"id": spec["id"], "label": spec["label"], "category_id": spec["category_id"],
            "category_label": category_label, "status": "insufficient", "status_label": INSUFFICIENT_LABEL,
            "suggested_score": None, "anchor_level": None, "item_anchor_text": "",
            "check_point": spec.get("anchor", ""), "evidence_requirement": CLASSROOM_ITEM_EVIDENCE.get(spec["id"], ""),
            "data_sources": [{"key": key, "label": SOURCE_LABELS[key], "available": False}
                             for key in ITEM_SOURCES[spec["id"]]],
            "formula": "", "inputs": {}, "evidence_refs": [], "reason": "", "confidence": ""}


def _scored(entry: dict[str, Any], score: float, *, formula: str, inputs: dict[str, Any],
            refs: list[dict[str, Any]], used: set[str], confidence: str = "data") -> None:
    from .assessment_rubric import anchor_level
    from .score_basis import CLASSROOM_ITEM_ANCHORS

    level = anchor_level(score)
    entry.update(status="suggested", status_label="系统建议分" + ("（含未复核线索）" if confidence == "unreviewed" else ""),
                 suggested_score=score, anchor_level=level,
                 item_anchor_text=CLASSROOM_ITEM_ANCHORS.get(entry["id"], {}).get(level, ""),
                 formula=formula, inputs=inputs, evidence_refs=refs, confidence=confidence)
    for source in entry["data_sources"]:
        source["available"] = source["key"] in used


def _insufficient(entry: dict[str, Any], reason: str, *, inputs: dict[str, Any] | None = None,
                  used: set[str] | None = None) -> None:
    entry.update(reason=reason, inputs=inputs or {})
    for source in entry["data_sources"]:
        source["available"] = source["key"] in (used or set())


def build_suggestions(data: dict[str, Any], *, computed_at: str | None = None) -> dict[str, Any]:
    template = TEMPLATES[TEMPLATE_ID]
    categories = {c["id"]: c["label"] for c in template["categories"]}
    task_id = data["task_id"]
    course_task = data.get("course_task") or {}
    goals = [g for g in course_task.get("goals") or [] if isinstance(g, dict)]
    views = _student_views(data)
    video_views = [v for v in views if v["metrics"]]
    fingerprint = data_fingerprint(data)
    items = []
    for spec in template["items"]:
        entry = _entry(spec, categories.get(spec["category_id"], ""))
        item_id = spec["id"]
        if item_id in TEACHER_ONLY_REASONS:
            _insufficient(entry, TEACHER_ONLY_REASONS[item_id])
        elif item_id == "i1":
            _suggest_goal_fit(entry, course_task, goals)
        elif item_id == "i4":
            _suggest_key_points(entry, goals, views)
        elif item_id == "i5":
            _suggest_organization(entry, task_id, video_views)
        elif item_id == "i6":
            _suggest_support(entry, task_id, views, video_views)
        elif item_id == "i7":
            _suggest_coverage(entry, task_id, views, video_views)
        elif item_id == "i8":
            _suggest_attainment(entry, task_id, views, video_views)
        elif item_id == "i10":
            _suggest_adjustment(entry, task_id, views, video_views)
        items.append(entry)
    suggested = [i for i in items if i["status"] == "suggested"]
    measurement_summary = {
        "record_ids": sorted(m["record_id"] for m in data.get("measurements") or []),
        "record_count": len(data.get("measurements") or []),
        "reviewed_scored_count": sum(len(v["reviewed_scores"]) for v in views),
        "student_count": len(views),
        "video_student_count": len(video_views),
    }
    return {
        "suggestion_version": SUGGESTION_VERSION,
        "template_id": TEMPLATE_ID,
        "task_id": task_id,
        "course_id": data.get("course_id") or "",
        "course_task_doc_id": course_task.get("course_task_doc_id") or "",
        "course_task_version": course_task.get("version") or 0,
        "goal_count": len(goals),
        "items": items,
        "suggested_count": len(suggested),
        "insufficient_count": len(items) - len(suggested),
        "measurement_summary": measurement_summary,
        "fingerprint": fingerprint,
        "note": "系统建议分只来自本课已确认的数据，是给教师的预填参考；采纳或修改后才计入系统增强轨，计算口径不变。",
        "computed_at": computed_at or _now(),
    }


def _goal_refs(goals: list[dict[str, Any]], limit: int = 6) -> list[dict[str, Any]]:
    return [{"kind": "course_goal", "label": SOURCE_LABELS["course_goal"], "goal_id": g.get("goal_code") or "",
             "text": str(g.get("description") or "")[:80], "pass_criteria": str(g.get("pass_criteria") or "")[:80]}
            for g in goals[:limit]]


def _suggest_goal_fit(entry, course_task, goals) -> None:
    if not goals:
        _insufficient(entry, "本课没有已确认的课程任务目标；上传并确认课程任务后可生成建议分。")
        return
    with_criteria = sum(1 for g in goals if str(g.get("pass_criteria") or "").strip())
    with_conditions = sum(1 for g in goals if str(g.get("measurement_conditions") or "").strip())
    layered = len(goals) >= 2
    points = Decimal("4")
    terms = ["有已确认目标 4"]
    criteria_part = Decimal(2) * Decimal(with_criteria) / Decimal(len(goals))
    points += criteria_part
    terms.append(f"通过标准覆盖 {with_criteria}/{len(goals)}×2")
    conditions_part = Decimal(1) * Decimal(with_conditions) / Decimal(len(goals))
    points += conditions_part
    terms.append(f"测量条件覆盖 {with_conditions}/{len(goals)}×1")
    if layered:
        points += 1
        terms.append("多目标分层 +1")
    score = min(_half(float(points)), 8.0)
    _scored(entry, score,
            formula="目标适配建议分 = 4（有已确认目标）+ 2×有通过标准的目标占比 + 1×有测量条件的目标占比 + 1（≥2 个目标，体现分层），"
                    "四舍五入到 0.5，上限 8 分（满分需要教师核对课堂中的落实）：" + " + ".join(terms) + f" = {_shown(float(points), score)}",
            inputs={"goal_count": len(goals), "goals_with_pass_criteria": with_criteria,
                    "goals_with_conditions": with_conditions, "layered": layered,
                    "course_task_version": course_task.get("version")},
            refs=_goal_refs(goals), used={"course_goal"})


def _suggest_key_points(entry, goals, views) -> None:
    if not goals:
        _insufficient(entry, "本课没有已确认的课程任务目标，无法按目标核对重点与难点。")
        return
    codes = {_goal_key(g.get("goal_code")): g for g in goals if g.get("goal_code")}
    per_goal: dict[str, list[tuple[str, float]]] = {}
    for view in views:
        for record_id, goal_id, score in view["reviewed_scores"]:
            key = _goal_key(goal_id)
            if key in codes:
                per_goal.setdefault(key, []).append((record_id, score))
    if not per_goal:
        _insufficient(entry, "本课还没有按课程目标复核的测量记录（需教师复核并生成综合分），无法判断重点、难点落实。",
                      inputs={"goal_count": len(goals)}, used={"course_goal"})
        return
    achieved = sum(1 for values in per_goal.values() if sum(s for _, s in values) / len(values) >= 6)
    share = achieved / len(goals)
    raw = 2 + 8 * share
    score = _half(raw)
    record_ids = [rid for values in per_goal.values() for rid, _ in values]
    _scored(entry, score,
            formula=f"重点难点建议分 = 2 + 8 × 达成目标占比；达成 = 该目标已复核测量综合分平均 ≥ 6：2 + 8 × {achieved}/{len(goals)} = {_shown(raw, score)}",
            inputs={"goal_count": len(goals), "goals_with_reviewed_records": len(per_goal), "goals_achieved": achieved},
            refs=_goal_refs([codes[k] for k in per_goal]) + [{
                "kind": "measurement", "label": SOURCE_LABELS["measurement"],
                "text": f"按目标复核的测量记录 {len(record_ids)} 条", "record_shorts": [short_id(r) for r in record_ids[:8]]}],
            used={"course_goal", "measurement"})


def _suggest_organization(entry, task_id, video_views) -> None:
    usable = [v for v in video_views if (_num(v["metrics"].get("observed_seconds")) or 0) > 0]
    if not usable:
        _insufficient(entry, "本课没有可用的学生视频片段（未归档学生或视频中未定位到学生），无法核对环节组织。")
        return
    ratios = [(_num(v["metrics"].get("engaged_ratio")) or 0) + (_num(v["metrics"].get("low_response_ratio")) or 0)
              for v in usable]
    average = sum(ratios) / len(ratios)
    score = _half(10 * average)
    _scored(entry, score,
            formula=f"组织有序建议分 = 10 × 学生在画面内参与或回应的平均时长占比（不含离开、不可见、未观察）："
                    f"10 × {_pct(average)} = {_shown(10 * average, score)}",
            inputs={"student_count": len(usable), "average_in_task_ratio": round(average, 3)},
            refs=_video_refs(task_id, usable, {"engaged", "low_response"}), used={"video"})


def _suggest_support(entry, task_id, views, video_views) -> None:
    independence = [value for v in views for value in v["independence"]]
    if independence:
        average = sum(independence) / len(independence)
        score = _half(average)
        record_ids = [rid for v in views for rid, _, _ in v["reviewed_scores"]]
        _scored(entry, score,
                formula=f"支持适配建议分 = 已复核测量记录「独立性」维度平均（提示越少分越高）：{_shown(average, score)}",
                inputs={"reviewed_records": len(independence), "average_independence": round(average, 2)},
                refs=[{"kind": "measurement", "label": SOURCE_LABELS["measurement"],
                       "text": f"已复核测量记录 {len(independence)} 条的独立性维度",
                       "record_shorts": [short_id(r) for r in record_ids[:8]]}],
                used={"measurement"})
        return
    rows = []
    for view in video_views:
        engaged = _num(view["metrics"].get("engaged_seconds")) or 0
        low = _num(view["metrics"].get("low_response_seconds")) or 0
        if engaged + low > 0:
            rows.append(engaged / (engaged + low))
    if not rows:
        _insufficient(entry, "本课没有已复核的测量记录，视频中也没有学生回应片段，无法判断支持手段是否让学生完成任务。")
        return
    average = sum(rows) / len(rows)
    score = _half(10 * average)
    _scored(entry, score,
            formula=f"支持适配建议分 = 10 × 学生回应时段中稳定参与的平均占比（视频线索，未经教师复核）：10 × {_pct(average)} = {_shown(10 * average, score)}",
            inputs={"student_count": len(rows), "average_stable_share": round(average, 3)},
            refs=_video_refs(task_id, video_views, {"engaged"}), used={"video"}, confidence="unreviewed")


def _suggest_coverage(entry, task_id, views, video_views) -> None:
    included = len(views)
    if not included or not video_views:
        _insufficient(entry, "本课还没有纳入检测的学生（请在结果页绑定学生并保存本课记录），无法计算学生覆盖率。",
                      inputs={"included_students": included})
        return
    participating = [v for v in video_views
                     if (v["metrics"].get("engaged_segments") or 0) + (v["metrics"].get("low_response_segments") or 0) > 0]
    coverage = len(participating) / included
    engaged = [(_num(v["metrics"].get("engaged_ratio")) or 0) for v in video_views]
    average_engaged = sum(engaged) / len(engaged)
    raw = 10 * (0.6 * coverage + 0.4 * average_engaged)
    score = _half(raw)
    _scored(entry, score,
            formula=f"全体参与建议分 = 10 × (0.6 × 学生覆盖率 + 0.4 × 平均稳定参与时长占比)："
                    f"10 × (0.6 × {len(participating)}/{included} + 0.4 × {_pct(average_engaged)}) = {_shown(raw, score)}",
            inputs={"included_students": included, "participating_students": len(participating),
                    "coverage": round(coverage, 3), "average_engaged_ratio": round(average_engaged, 3)},
            refs=[{"kind": "coverage", "label": SOURCE_LABELS["coverage"],
                   "text": f"本课纳入检测 {included} 名学生，其中 {len(participating)} 名有参与或回应片段（覆盖率 {_pct(coverage)}）"}]
                 + _video_refs(task_id, participating, {"engaged", "low_response"}),
            used={"coverage", "video"})


def _suggest_attainment(entry, task_id, views, video_views) -> None:
    reviewed = [(rid, score) for v in views for rid, _, score in v["reviewed_scores"]]
    if reviewed:
        per_student = [sum(sc for _, _, sc in v["reviewed_scores"]) / len(v["reviewed_scores"])
                       for v in views if v["reviewed_scores"]]
        average = sum(per_student) / len(per_student)
        score = _half(average)
        _scored(entry, score,
                formula=f"目标落实建议分 = 各学生已复核测量综合分的平均（先求每名学生的平均，再对学生取平均）："
                        f"{len(per_student)} 名学生平均 {_shown(average, score)}",
                inputs={"students_with_reviewed_scores": len(per_student), "reviewed_records": len(reviewed),
                        "average_composite": round(average, 2)},
                refs=[{"kind": "measurement", "label": SOURCE_LABELS["measurement"],
                       "text": f"{len(per_student)} 名学生的已复核测量记录 {len(reviewed)} 条，综合分平均 {_fmt(round(average, 2))}",
                       "record_shorts": [short_id(r) for r, _ in reviewed[:8]]}],
                used={"measurement"})
        return
    refs = [_num(v["metrics"].get("participation_score_ref")) for v in video_views]
    refs = [r for r in refs if r is not None]
    if not refs:
        _insufficient(entry, "本课没有已复核的测量综合分，视频中也没有可用的参与线索分，无法判断目标落实。")
        return
    average = sum(refs) / len(refs)
    score = _half(average)
    record_ids = [v["video_record"] for v in video_views if v["video_record"]]
    _scored(entry, score,
            formula=f"目标落实建议分 = 各学生视频参与线索参考分平均（测量记录尚未经教师复核）：{len(refs)} 名学生平均 "
                    f"{_shown(average, score)}；教师复核测量后建议分会改用测量综合分",
            inputs={"students_with_video_reference": len(refs), "average_participation_ref": round(average, 2)},
            refs=[{"kind": "measurement", "label": SOURCE_LABELS["measurement"],
                   "text": f"视频来源测量记录 {len(record_ids)} 条（待复核）",
                   "record_shorts": [short_id(r) for r in record_ids[:8]]}]
                 + _video_refs(task_id, video_views, {"engaged"}),
            used={"measurement", "video"}, confidence="unreviewed")


def _suggest_adjustment(entry, task_id, views, video_views) -> None:
    observations = [rid for v in views for rid in v["observations"]]
    if not observations:
        _insufficient(entry, "本课没有教师观察记录（需在学生测量中复核并填写观察证据），仅凭视频不能判断教师调整。",
                      inputs={"teacher_observations": 0}, used={"video"} if video_views else set())
        return
    with_low, recovered, refs = 0, 0, []
    for index, view in enumerate(video_views, start=1):
        ordered = sorted(view["segments"], key=lambda s: _num(s.get("start_sec")) or 0)
        low_at = next((s for s in ordered if s.get("state") == "low_response"), None)
        if low_at is None:
            continue
        with_low += 1
        after = next((s for s in ordered if s.get("state") == "engaged"
                      and (_num(s.get("start_sec")) or 0) >= (_num(low_at.get("end_sec")) or 0)), None)
        if after is not None:
            recovered += 1
            start = _num(after.get("start_sec")) or 0
            refs.append({"kind": "video", "label": SOURCE_LABELS["video"], "start_sec": start,
                         "text": f"学生{index} {_fmt_sec(low_at.get('start_sec'))} 回应偏低 → {_fmt_sec(start)} 恢复参与",
                         "url": f"/demo2/video?id={task_id}&t={int(_num(low_at.get('start_sec')) or 0)}"})
    if not with_low:
        _insufficient(entry, "本课视频中没有出现回应偏低的片段，无法据此判断教师识别困难后的调整，请教师结合观察评分。",
                      inputs={"teacher_observations": len(observations)}, used={"teacher_observation"})
        return
    share = recovered / with_low
    raw = 2 + 8 * share
    score = _half(raw)
    _scored(entry, score,
            formula=f"响应调节建议分 = 2 + 8 × 回应偏低后恢复参与的学生占比：2 + 8 × {recovered}/{with_low} = {_shown(raw, score)}",
            inputs={"students_with_low_response": with_low, "students_recovered": recovered,
                    "teacher_observations": len(observations)},
            refs=refs[:6] + [{"kind": "teacher_observation", "label": SOURCE_LABELS["teacher_observation"],
                              "text": f"教师已复核的观察记录 {len(observations)} 条（原文在测量记录中查看）"}],
            used={"video", "teacher_observation"})


# -------------------------------------------------------------- save support

def apply_teacher_decisions(suggestions: dict[str, Any], items: list[dict[str, Any]],
                            reasons: dict[str, str]) -> tuple[dict[str, Any], list[str]]:
    """Compare the submitted system-track scores with the suggestions.

    Returns the snapshot to store and the item ids whose modification reason is missing.
    """
    by_id = {row.get("id"): row for row in items if isinstance(row, dict)}
    missing, out = [], []
    for item in suggestions["items"]:
        row = by_id.get(item["id"], {})
        submitted = _num(row.get("enhanced_score"))
        suggested = item["suggested_score"]
        reason = (reasons.get(item["id"]) or "").strip()
        if suggested is None:
            decision = "teacher_scored" if submitted is not None else "not_scored"
        elif submitted is None:
            decision = "not_used"
        elif submitted == suggested:
            decision = "adopted"
        else:
            decision = "modified"
            if not reason:
                missing.append(item["id"])
        out.append({"id": item["id"], "category_id": item["category_id"], "status": item["status"],
                    "suggested_score": suggested, "final_score": submitted, "decision": decision,
                    "modify_reason": reason if decision == "modified" else "",
                    "data_sources": [s["label"] for s in item["data_sources"] if s["available"]],
                    "formula": item["formula"], "reason": item["reason"], "confidence": item["confidence"],
                    "anchor_level": item["anchor_level"], "item_anchor_text": item["item_anchor_text"],
                    "check_point": item["check_point"], "evidence_requirement": item["evidence_requirement"],
                    "evidence_refs": item["evidence_refs"], "inputs": item["inputs"],
                    "label": item["label"], "category_label": item["category_label"],
                    "status_label": item["status_label"]})
    snapshot = {key: suggestions[key] for key in ("suggestion_version", "template_id", "course_task_doc_id",
                                                   "course_task_version", "goal_count", "suggested_count",
                                                   "insufficient_count", "measurement_summary", "fingerprint",
                                                   "computed_at")}
    snapshot["items"] = out
    snapshot["counts"] = {key: sum(1 for i in out if i["decision"] == key)
                          for key in ("adopted", "modified", "not_used", "teacher_scored", "not_scored")}
    return snapshot, missing


def category_summary(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-category school vs system averages (10-point) and their gap, from a computed result."""
    template = TEMPLATES[TEMPLATE_ID]
    rows = {row.get("id"): row for row in (result.get("comparison") or {}).get("items") or []}
    out = []
    for category in template["categories"]:
        ids = [i["id"] for i in template["items"] if i["category_id"] == category["id"]]
        school = [rows.get(i, {}).get("school_score") for i in ids]
        system = [rows.get(i, {}).get("enhanced_score") for i in ids]
        school_avg = sum(school) / len(school) if all(v is not None for v in school) else None
        system_avg = sum(system) / len(system) if all(v is not None for v in system) else None
        out.append({"id": category["id"], "label": category["label"], "item_ids": ids,
                    "school_score": round(school_avg, 2) if school_avg is not None else None,
                    "system_score": round(system_avg, 2) if system_avg is not None else None,
                    "gap": round(system_avg - school_avg, 2) if school_avg is not None and system_avg is not None else None})
    return out


def school_grade_label(score_10: Any) -> str:
    """Grade of the school total on the A/B/C/D single-item bands (项目参考，不替代学校判定)."""
    number = _num(score_10)
    if number is None:
        return ""
    if number >= 9:
        return "A"
    if number >= 6:
        return "B"
    if number >= 3:
        return "C"
    return "D"


__all__ = [
    "INSUFFICIENT_LABEL", "SOURCE_LABELS", "STALE_REASON_TEXT", "SUGGESTION_VERSION", "TEMPLATE_ID",
    "apply_teacher_decisions", "build_suggestions", "category_summary", "data_fingerprint",
    "load_lesson_data", "school_grade_label", "stale_reasons",
]
