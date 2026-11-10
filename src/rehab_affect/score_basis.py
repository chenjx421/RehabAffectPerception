"""Score basis (评分依据) for student measurements and the dual-track system score.

The basis explains a score that has already been computed elsewhere:
``assessment_rubric.build_assessment_summary`` for measurements and
``classroom_rubric.evaluate`` for classroom evaluations.  Nothing here feeds
back into those calculations, so saved scores stay exactly the same; the basis
only re-states the formula with the substituted numbers, the anchor level that
was hit, the evidence that was cited and the reasons a score was not produced.

Two views exist:
- teacher view: full basis, including the teacher's observation excerpt and
  confirmed IEP points (already gated by authorisation on read);
- admin view (:func:`redact_for_admin`): numbers, anchors, time points and
  goal codes only -- no observation text, no IEP text, no student names.
"""
from __future__ import annotations

import math
import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .assessment_rubric import (
    ANCHOR_LEVELS,
    DATA_SOURCE_LABELS,
    DIMENSION_ANCHORS,
    DIMENSION_EVIDENCE,
    DIMENSION_LABELS,
    DIMENSION_NOT_SCORED,
    DIMENSION_SOURCES,
    DIMENSION_WEIGHTS,
    EVIDENCE_INSUFFICIENT,
    MIN_OBSERVED,
    RUBRIC_DETAIL_VERSION,
    RUBRIC_VERSION,
    SUPPORT_LEVEL_ANCHORS,
    anchor_level,
)

BASIS_VERSION = "2026-11-01.score-basis-v1"
EVALUATION_DETAIL_VERSION = "2026-11-01.classroom-anchors-v1"
NOT_SCORED_LABEL = "证据不足，未计分"
_EXCERPT = 120
_VIDEO_SOURCES = {"video_review", "video"}

# 双轨评价 10 个条目的分档锚点（0/2/4/6/8/10），与 evaluation_policy.ANCHORS 的通用含义一致，
# 只把「看什么」具体到条目；学校原表 A/B/C/D 区间见 SCHOOL_GRADES。
CLASSROOM_ITEM_ANCHORS: dict[str, dict[int, str]] = {
    "i1": {10: "分层目标完整对应课标与每名学生起点，支持约定写明且课堂中一致落实",
           8: "分层目标与学生起点基本对应，个别学生的支持约定不够具体",
           6: "有分层目标并能对应多数学生，达到本课最低约定",
           4: "目标分层笼统，部分学生目标与起点不匹配",
           2: "目标未体现差异，仅按统一要求呈现",
           0: "已核对教案与课堂，目标与课标和学生实际明显脱节"},
    "i2": {10: "多处联系学生生活经验与已学内容，学生能用自己的经历回应",
           8: "有明确的生活经验联系，多数学生能参与回应",
           6: "有一处以上生活经验联系，达到最低要求",
           4: "联系生硬或只由教师讲述，学生参与少",
           2: "几乎没有联系学生经历",
           0: "已核对全课，内容与学生经验完全脱离"},
    "i3": {10: "内容经教案或专业复核正确，密度与容量与学生节奏一致",
           8: "内容正确，个别环节容量偏多或偏少",
           6: "内容正确，容量基本可接受",
           4: "存在需要更正的表述，或容量明显不合适",
           2: "多处内容需要更正",
           0: "已复核，存在明显科学性错误且未更正"},
    "i4": {10: "重点在任务与学生回应中反复落实，难点有分步突破且有回应证据",
           8: "重点突出，难点有突破措施，个别学生仍需支持",
           6: "重点清楚，难点有初步处理",
           4: "重点不够突出，难点处理不足",
           2: "重点与难点未区分",
           0: "已核对任务与回应，重点与难点均未落实"},
    "i5": {10: "环节衔接紧凑，等待时间与材料可及性适合每名学生",
           8: "环节清晰，个别过渡耗时",
           6: "环节基本有序，达到最低要求",
           4: "环节松散或过渡混乱，影响部分学生参与",
           2: "组织混乱，较多时间用于等待或维持秩序",
           0: "已核对，组织无序导致学习任务无法开展"},
    "i6": {10: "支持手段让每名学生都能完成约定任务，辅助器具与信息技术使用有效",
           8: "方法与资源适配多数学生，个别支持不到位",
           6: "方法与资源基本适配，达到最低约定",
           4: "方法单一或资源使用不当，部分学生无法完成",
           2: "支持手段明显不足",
           0: "已核对，约定的必要支持没有提供"},
    "i7": {10: "按机会覆盖核对，全体学生都有主动参与与互动机会",
           8: "多数学生有参与机会，互动积极",
           6: "过半学生有参与机会，达到最低要求",
           4: "参与集中在少数学生",
           2: "以教师讲授为主，学生参与很少",
           0: "已核对，学生基本没有参与机会"},
    "i8": {10: "按分层目标核对，各层学生都有达成证据",
           8: "多数学生达成分层目标，有可复核证据",
           6: "部分学生达成目标，达到本课最低约定",
           4: "达成证据少，教师代答或机械跟读较多",
           2: "仅个别学生有达成迹象",
           0: "已有充分机会与观察，仍未见目标达成"},
    "i9": {10: "指令清晰易懂，示范熟练，板书或视觉支持规范，并提供必要支持",
           8: "表达清楚，个别指令需重复",
           6: "表达基本清楚，达到最低要求",
           4: "指令不够清晰，学生多次无法理解",
           2: "表达与示范明显不足",
           0: "已核对，教师表达导致学生无法理解任务"},
    "i10": {10: "识别学生困难后及时调整并有后续回应，信息技术运用得当",
            8: "多数困难能及时调整",
            6: "有调整措施，达到最低要求",
            4: "调整不及时或调整后无跟进",
            2: "很少根据学生反应调整",
            0: "已核对，出现困难时没有任何调整"},
}
CLASSROOM_ITEM_EVIDENCE: dict[str, str] = {
    "i1": "教案分层目标、学生起点说明与课堂中的支持约定落实时间点。",
    "i2": "教师联系生活经验的片段时间点与学生回应。",
    "i3": "教案或专业复核意见；视频安静有序不能代替科学性证据。",
    "i4": "重点任务、难点突破步骤与对应学生回应的时间点。",
    "i5": "环节切换时间点、等待时间与材料可及情况。",
    "i6": "使用的支持手段、辅助器具及学生借此完成任务的时间点。",
    "i7": "按学生统计的参与机会（谁、何时、以何种方式参与）。",
    "i8": "各层目标对应的学生表现时间点，或本课测量记录。",
    "i9": "关键指令与示范的时间点，以及学生是否理解。",
    "i10": "识别困难的时间点、实际调整与后续回应。",
}
SCHOOL_GRADES = (("A", 9, 10), ("B", 6, 8), ("C", 3, 5), ("D", 1, 2))
_TIME_RE = re.compile(r"(?<![\d:])(?:(\d{1,2}):)?(\d{1,2}):(\d{2})(?![\d:])")


def short_id(value: Any) -> str:
    text = str(value or "")
    for prefix in ("evaluation-", "vm-"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text[:8] if text else ""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _excerpt(text: Any, limit: int = _EXCERPT) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[:limit] + "…"


def _dec(value: Any) -> Decimal:
    return Decimal(str(value))


def _plain(value: Decimal) -> str:
    """Exact decimal without trailing zeros (2.800 -> 2.8, 3 -> 3)."""
    text = format(value.normalize(), "f")
    return text if text not in {"-0", ""} else "0"


def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _fmt(value: Any) -> str:
    number = _num(value)
    if number is None:
        return "—"
    return str(int(number)) if number.is_integer() else f"{number:g}"


def school_grade(score: Any) -> str | None:
    number = _num(score)
    if number is None:
        return None
    for letter, low, high in SCHOOL_GRADES:
        if low <= number <= high:
            return letter
    return None


def _video_url(task_id: str, seconds: Any) -> str:
    return f"/demo2/video?id={task_id}&t={int(max(0.0, _num(seconds) or 0.0))}"


def _fmt_sec(seconds: Any) -> str:
    value = int(max(0.0, _num(seconds) or 0.0))
    return f"{value // 60:02d}:{value % 60:02d}"


# ---------------------------------------------------------------- measurements

def _measurement_refs(record: dict[str, Any]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    task_id = str(record.get("task_id") or "")
    source_type = record.get("source_type")
    if source_type in _VIDEO_SOURCES and task_id:
        segments = [s for s in record.get("evidence_segments") or [] if isinstance(s, dict)]
        for segment in segments:
            start = _num(segment.get("start_sec"))
            end = _num(segment.get("end_sec"))
            if start is None:
                continue
            refs.append({"kind": "video", "label": DATA_SOURCE_LABELS["video"],
                         "start_sec": start, "end_sec": end,
                         "text": f"{_fmt_sec(start)}–{_fmt_sec(end)} {_excerpt(segment.get('state_label'), 20)}".strip(),
                         "url": _video_url(task_id, start)})
        if not segments and _num(record.get("start_sec")) is not None:
            start, end = _num(record.get("start_sec")), _num(record.get("end_sec"))
            refs.append({"kind": "video", "label": DATA_SOURCE_LABELS["video"], "start_sec": start, "end_sec": end,
                         "text": f"{_fmt_sec(start)}–{_fmt_sec(end)} 复核时段", "url": _video_url(task_id, start)})
    evidence = str(record.get("evidence") or "").strip()
    if evidence and record.get("saved_by") != "system:video_archive":
        refs.append({"kind": "teacher_observation", "label": DATA_SOURCE_LABELS["teacher_observation"],
                     "text": _excerpt(evidence),
                     "prompt": _excerpt(record.get("teacher_prompt"), 60),
                     "response": _excerpt(record.get("student_response"), 60)})
    elif evidence:
        refs.append({"kind": "teacher_observation", "label": DATA_SOURCE_LABELS["teacher_observation"],
                     "text": _excerpt(evidence), "prompt": "", "response": "",
                     "note": "系统生成的待复核说明，教师复核后以教师观察为准"})
    goal_id = str(record.get("goal_id") or "")
    if record.get("course_task_doc_id") or re.fullmatch(r"[Gg]-?\d{1,3}", goal_id):
        refs.append({"kind": "course_goal", "label": DATA_SOURCE_LABELS["course_goal"], "goal_id": goal_id,
                     "text": _excerpt(record.get("goal_description") or record.get("criterion"), 80),
                     "pass_criteria": _excerpt(record.get("pass_criteria") or record.get("criterion"), 80),
                     "course_task_doc_short": short_id(record.get("course_task_doc_id"))})
    iep_items = [i for i in record.get("iep_support") or [] if isinstance(i, dict)]
    if record.get("iep_document_id") or iep_items:
        refs.append({"kind": "iep", "label": DATA_SOURCE_LABELS["iep"],
                     "document_short": short_id(record.get("iep_document_id")),
                     "item_count": len(iep_items),
                     "text": f"本课确认的 IEP 支持条件 {len(iep_items)} 条" if iep_items else "已关联 IEP（要点当前不可读或未确认）"})
    return refs


def measurement_score_basis(record: dict[str, Any], *, computed_at: str | None = None) -> dict[str, Any]:
    """Explain one measurement record's dimension scores and composite score.

    ``record`` is the stored (or effective) payload; the composite score shown
    on the page is ``record['assessment']['score']`` and the formula below
    reproduces it with exact decimals, so ``overall.matches_page`` is True for
    every scored record.
    """
    scores = record.get("scores") if isinstance(record.get("scores"), dict) else {}
    assessment = record.get("assessment") if isinstance(record.get("assessment"), dict) else {}
    observed = record.get("observed")
    opportunities = record.get("opportunities")
    refs = _measurement_refs(record)
    ref_kinds = {ref["kind"] for ref in refs}
    usable = [(name, _dec(scores[name])) for name in DIMENSION_WEIGHTS if _num(scores.get(name)) is not None]
    total_weight = sum((_dec(DIMENSION_WEIGHTS[name]) for name, _ in usable), Decimal("0"))
    weighted_sum = sum((value * _dec(DIMENSION_WEIGHTS[name]) for name, value in usable), Decimal("0"))
    support_key = record.get("support_level") if record.get("support_level") in SUPPORT_LEVEL_ANCHORS else "unknown"
    support_label, support_anchor = SUPPORT_LEVEL_ANCHORS[support_key]
    dimensions = []
    for name, weight in DIMENSION_WEIGHTS.items():
        raw = _num(scores.get(name))
        sources = [{"key": key, "label": DATA_SOURCE_LABELS[key], "available": key in ref_kinds}
                   for key in DIMENSION_SOURCES[name]]
        entry: dict[str, Any] = {
            "key": name, "label": DIMENSION_LABELS[name], "score": raw,
            "weight": weight, "weight_percent": round(weight * 100),
            "evidence_requirement": DIMENSION_EVIDENCE[name], "data_sources": sources,
            "evidence_refs": [index for index, ref in enumerate(refs) if ref["kind"] in DIMENSION_SOURCES[name]],
        }
        if raw is None:
            entry.update(status="not_observed", status_label=NOT_SCORED_LABEL, contribution=None,
                         normalized_contribution=None, anchor_level=None, anchor_text="",
                         reason="该维度留空（未观察）：按规则不填 0，也不计入综合分。常见情形："
                                + "；".join(DIMENSION_NOT_SCORED[name]) + "。")
        else:
            level = anchor_level(raw)
            contribution = _dec(raw) * _dec(weight)
            entry.update(status="scored", status_label="已计分", contribution=float(contribution),
                         contribution_text=_plain(contribution),
                         normalized_contribution=float((contribution / total_weight).quantize(
                             Decimal("0.0001"), rounding=ROUND_HALF_UP)) if total_weight else None,
                         anchor_level=level, anchor_text=DIMENSION_ANCHORS[name][level],
                         reason="")
            if name == "independence" and support_anchor is not None and level != support_anchor:
                entry["reason"] = (f"记录的提示层级为「{support_label}」（参考 {support_anchor} 分档），"
                                   f"与教师评分所在的 {level} 分档不同，请复核提示层级或评分。")
        dimensions.append(entry)
    formula_terms = [f"{DIMENSION_LABELS[name]} {_plain(value)}×{DIMENSION_WEIGHTS[name]:.2f}" for name, value in usable]
    computed = (weighted_sum / total_weight).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if total_weight else None
    page_score = assessment.get("score")
    reasons = [str(r) for r in assessment.get("evidence_reasons") or []]
    scored = page_score is not None and assessment.get("evidence_status") != EVIDENCE_INSUFFICIENT
    status = "scored" if scored else "insufficient"
    renormalized = bool(usable) and total_weight != Decimal("1")
    expression = " + ".join(formula_terms) if formula_terms else "（无已填写维度）"
    if renormalized:
        expression = f"({expression}) ÷ {_plain(total_weight)}"
    overall = {
        "score": page_score if scored else None,
        "display": f"{page_score:.2f}" if scored else None,
        "formula_value": float(computed) if computed is not None else None,
        "formula_display": f"{computed:.2f}" if computed is not None else None,
        "matches_page": bool(scored and computed is not None and float(computed) == float(page_score)),
        "anchor_level": anchor_level(page_score) if scored else None,
        "status_label": "已计分" if scored else NOT_SCORED_LABEL,
    }
    observation_rate = None
    if isinstance(observed, int) and isinstance(opportunities, int) and opportunities > 0:
        observation_rate = round(observed / opportunities, 3)
    metrics = record.get("video_metrics") if isinstance(record.get("video_metrics"), dict) else {}
    inputs: dict[str, Any] = {
        "opportunities": opportunities if isinstance(opportunities, int) else None,
        "observed": observed if isinstance(observed, int) else None,
        "observation_rate": observation_rate,
        "min_observed": MIN_OBSERVED,
        "reviewed": record.get("reviewed") is True,
        "support_level": support_key,
        "support_label": support_label,
        "support_anchor_level": support_anchor,
        "source_type": record.get("source_type") or "",
    }
    if metrics:
        inputs["video"] = {key: metrics.get(key) for key in (
            "engaged_segments", "low_response_segments", "away_segments", "not_observed_segments",
            "engaged_ratio", "participation_score_ref") if key in metrics}
        inputs["video"]["success_segments"] = metrics.get("engaged_segments")
    if record.get("suggested_scores"):
        inputs["suggested_scores"] = {k: (record["suggested_scores"] or {}).get(k) for k in DIMENSION_WEIGHTS}
        inputs["suggestion_note"] = "系统建议分只来自视频线索，教师复核后以教师评分为准，建议分不计入综合分。"
    return {
        "basis_version": BASIS_VERSION,
        "rubric_version": record.get("rubric_version") or RUBRIC_VERSION,
        "detail_version": RUBRIC_DETAIL_VERSION,
        "kind": "measurement",
        "record_short": short_id(record.get("record_id")),
        "status": status,
        "status_label": "已计分" if scored else NOT_SCORED_LABEL,
        "formula": {
            "rule": "综合分 = Σ(维度分 × 权重) ÷ Σ已填写维度权重，四舍五入保留 2 位小数",
            "expression": expression,
            "weighted_sum": float(weighted_sum) if usable else None,
            "weighted_sum_text": _plain(weighted_sum) if usable else None,
            "total_weight": float(total_weight) if usable else None,
            "renormalized": renormalized,
            "result": overall["formula_display"],
            "decimals": 2,
        },
        "overall": overall,
        "inputs": inputs,
        "dimensions": dimensions,
        "evidence_refs": refs,
        "reasons": [] if scored else (reasons or ["未达到最低评分条件"]),
        "computed_at": computed_at or _now(),
    }


def measurement_basis_sentence(record: dict[str, Any]) -> str:
    """One-sentence basis summary appended after a score in reports."""
    basis = record.get("score_basis") if isinstance(record.get("score_basis"), dict) else None
    if basis is None or basis.get("kind") != "measurement":
        basis = measurement_score_basis(record)
    if basis["status"] != "scored":
        return f"依据：{NOT_SCORED_LABEL}（{'；'.join(basis['reasons'])}）"
    parts = [f"{d['label']}{_fmt(d['score'])}×{d['weight']:.2f}" for d in basis["dimensions"] if d["status"] == "scored"]
    anchors = "、".join(f"{d['label']}{d['anchor_level']}档" for d in basis["dimensions"] if d["status"] == "scored")
    inputs = basis["inputs"]
    video = sum(1 for ref in basis["evidence_refs"] if ref["kind"] == "video")
    evidence = f"视频片段 {video} 个" if video else "教师观察记录"
    return (f"依据：{' + '.join(parts)} = {basis['overall']['display']}；"
            f"观察 {inputs.get('observed')}/{inputs.get('opportunities')} 次，提示层级「{inputs.get('support_label')}」；"
            f"命中锚点 {anchors}；证据来自{evidence}（量表 {basis['rubric_version']}）")


# ------------------------------------------------------------- classroom eval

def _time_refs(text: str, task_id: str) -> list[dict[str, Any]]:
    refs = []
    for match in _TIME_RE.finditer(text or ""):
        hours, minutes, seconds = match.group(1), int(match.group(2)), int(match.group(3))
        if seconds >= 60:
            continue
        total = (int(hours) * 3600 if hours else 0) + minutes * 60 + seconds
        ref = {"kind": "video", "label": "课堂视频时间点", "start_sec": float(total), "text": match.group(0)}
        if task_id:
            ref["url"] = _video_url(task_id, total)
        refs.append(ref)
        if len(refs) >= 6:
            break
    return refs


def evaluation_rubric_detail() -> dict[str, Any]:
    """Per-item anchors for the 10-item basic table, shown on the evaluation page."""
    from .classroom_rubric import RULE_VERSION, TEMPLATES
    from .evaluation_policy import ANCHORS

    template = TEMPLATES["basic_100"]
    categories = {c["id"]: c["label"] for c in template["categories"]}
    return {
        "rule_version": RULE_VERSION,
        "detail_version": EVALUATION_DETAIL_VERSION,
        "general_anchors": [dict(level=a["score"], label=a["label"], text=a["detail"]) for a in ANCHORS],
        "school_grades": [dict(grade=g, low=low, high=high) for g, low, high in SCHOOL_GRADES],
        "anchor_rule": "系统增强分落在两档之间时取不高于该分的锚点；未观察或无证据留空，不填 0。",
        "items": [
            {"id": item["id"], "label": item["label"], "category_id": item["category_id"],
             "category_label": categories.get(item["category_id"], ""),
             "school_weight": item["school_weight"], "enhanced_weight": item["enhanced_weight"],
             "check_point": item["anchor"], "evidence": CLASSROOM_ITEM_EVIDENCE[item["id"]],
             "anchors": [{"level": level, "text": CLASSROOM_ITEM_ANCHORS[item["id"]][level]} for level in ANCHOR_LEVELS]}
            for item in template["items"]
        ],
        "not_scored": ["本课未涉及该条目（留空，不填 0）", "已评分但没有证据摘要或时间点", "情境修正未经教师复核"],
    }


def evaluation_score_basis(record: dict[str, Any], *, computed_at: str | None = None) -> dict[str, Any]:
    """Explain each system-track (增强) item score and the system total of one evaluation."""
    from .classroom_rubric import TEMPLATES
    from .evaluation_policy import ANCHORS

    result = record.get("result") if isinstance(record.get("result"), dict) else {}
    template = TEMPLATES.get(record.get("template_id")) or {}
    enhanced_available = bool(template.get("enhanced_available"))
    policy = result.get("weight_policy") if isinstance(result.get("weight_policy"), dict) else {}
    policy_rows = {row.get("id"): row for row in policy.get("items") or [] if isinstance(row, dict)}
    rows = {row.get("id"): row for row in record.get("items") or [] if isinstance(row, dict)}
    comparison = result.get("comparison") if isinstance(result.get("comparison"), dict) else {}
    delta_rows = {row.get("id"): row for row in comparison.get("items") or [] if isinstance(row, dict)}
    context_changes = {c.get("id"): c for c in (result.get("context_review") or {}).get("changes") or []}
    mode = policy.get("mode") or record.get("weight_policy") or "common"
    reviewed = record.get("reviewed") is True
    task_id = str(record.get("task_id") or "")
    goal_links: dict[str, list[str]] = {}
    for basis in record.get("course_task_goal_basis") or []:
        for item_id in basis.get("item_ids") or []:
            goal_links.setdefault(item_id, []).append(str(basis.get("goal_code") or ""))
    measurement_refs = [r for r in record.get("measurement_refs") or [] if isinstance(r, dict)]
    anchors_by_level = {a["score"]: a for a in ANCHORS}
    items = []
    weighted_terms = []
    insufficient = []
    for spec in template.get("items") or []:
        item_id = spec["id"]
        row = rows.get(item_id, {})
        delta = delta_rows.get(item_id, {})
        school = _num(delta.get("school_score", row.get("school_score")))
        enhanced = _num(delta.get("enhanced_score")) if enhanced_available else None
        weight = _num((policy_rows.get(item_id) or {}).get("final_weight"))
        if weight is None:
            weight = _num(spec.get("enhanced_weight"))
        evidence_text = str(row.get("evidence") or "").strip()
        times = _time_refs(evidence_text, task_id)
        refs: list[dict[str, Any]] = []
        if evidence_text:
            refs.append({"kind": "teacher_observation", "label": "教师课堂观察", "text": _excerpt(evidence_text),
                         "reason": _excerpt(row.get("reason"), 80)})
        refs.extend(times)
        for goal in goal_links.get(item_id, []):
            refs.append({"kind": "course_goal", "label": "课程任务目标", "goal_id": goal, "text": goal})
        if item_id in {"i4", "i7", "i8"} and measurement_refs:
            reviewed_count = sum(1 for r in measurement_refs if r.get("reviewed"))
            refs.append({"kind": "measurement", "label": "本课测量记录",
                         "text": f"关联测量记录 {len(measurement_refs)} 条（已复核 {reviewed_count} 条）",
                         "record_shorts": [short_id(r.get("record_id")) for r in measurement_refs[:8]]})
        sources = sorted({ref["label"] for ref in refs})
        change = context_changes.get(item_id)
        entry: dict[str, Any] = {
            "id": item_id, "label": spec["label"], "category_id": spec["category_id"],
            "school_score": school, "school_grade": school_grade(school) if enhanced_available else None,
            "enhanced_score": enhanced, "weight": weight,
            "school_weight": spec.get("school_weight"),
            "check_point": spec.get("anchor", ""),
            "evidence_requirement": CLASSROOM_ITEM_EVIDENCE.get(item_id, ""),
            "data_sources": sources, "evidence_refs": refs,
            "delta": {k: delta.get(k) for k in ("evidence_delta", "weight_delta", "total_delta")},
        }
        if not enhanced_available:
            entry.update(status="not_available", status_label="该表尚无系统增强映射", contribution=None,
                         anchor_level=None, anchor_label="", anchor_text="", item_anchor_text="",
                         reason="15 项原表没有系统增强轨，只保留学校原评分。")
        elif enhanced is None:
            entry.update(status="not_scored", status_label=NOT_SCORED_LABEL, contribution=None,
                         anchor_level=None, anchor_label="", anchor_text="", item_anchor_text="",
                         reason=("未录入系统增强分：本条目未观察到或缺少可复核证据。按规则不填 0、不归一化，"
                                 "因此系统增强总分暂不生成。" if school is not None else
                                 "学校分与系统增强分都未录入：本课未评价该条目，按规则留空。"))
            insufficient.append(item_id)
        elif not evidence_text and not times:
            entry.update(status="no_evidence", status_label=NOT_SCORED_LABEL, contribution=None,
                         anchor_level=None, anchor_label="", anchor_text="", item_anchor_text="",
                         reason="该条目没有填写证据摘要或时间点，暂填的分数未经证据支撑，不作为评分依据；"
                                "勾选「已核对」前须补充证据。")
            insufficient.append(item_id)
            weighted_terms.append((item_id, enhanced, weight))
        else:
            level = anchor_level(enhanced)
            general = anchors_by_level.get(level, {})
            contribution = _dec(enhanced) * _dec(weight) if weight is not None else None
            entry.update(status="scored", status_label="已计分",
                         contribution=float(contribution) if contribution is not None else None,
                         contribution_text=_plain(contribution.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
                         if contribution is not None else None,
                         anchor_level=level, anchor_label=general.get("label", ""),
                         anchor_text=general.get("detail", ""),
                         item_anchor_text=CLASSROOM_ITEM_ANCHORS.get(item_id, {}).get(level, ""), reason="")
            if mode == "school_context" and change is None and school is not None and enhanced == school:
                entry["reason"] = "情境复核方案：没有新的情境证据，沿用学校基础分。"
                entry["data_sources"] = sorted({*sources, "学校基础分（沿用）"})
            if change is not None and not change.get("applied"):
                entry.update(status="pending_review", status_label="情境修正待复核",
                             reason=f"提出的修正分 {_fmt(change.get('proposed_score'))} 尚未经教师复核，暂沿用学校分。")
            weighted_terms.append((item_id, enhanced, weight))
        items.append(entry)
    enhanced_block = result.get("enhanced") if isinstance(result.get("enhanced"), dict) else {}
    school_block = result.get("school") if isinstance(result.get("school"), dict) else {}
    system_score = enhanced_block.get("score_10")
    full = enhanced_available and all(i["enhanced_score"] is not None for i in items) and items
    weighted_sum = sum((enhanced or 0.0) * (weight or 0.0) for _, enhanced, weight in weighted_terms) if full else None
    formula_value = round(float(Decimal(str(weighted_sum)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)), 4) \
        if weighted_sum is not None else None
    expression = " + ".join(f"{iid} {_fmt(z)}×{_plain(_dec(w).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)) if w is not None else '—'}"
                            for iid, z, w in weighted_terms) if full else ""
    if not enhanced_available:
        status, label = "not_available", "该表尚无系统增强映射"
        reasons = ["15 项原表没有系统增强轨"]
    elif system_score is None:
        status, label = "insufficient", NOT_SCORED_LABEL
        reasons = [f"{len([i for i in items if i['status'] == 'not_scored'])} 个条目未录入系统增强分（"
                   + "、".join(i["id"] for i in items if i["status"] == "not_scored") + "），总分不生成"]
    else:
        status = "scored" if reviewed else "provisional"
        label = "已计分" if reviewed else "未复核暂算"
        reasons = []
        if not reviewed:
            reasons.append("评价尚未勾选「已核对」，系统增强分为暂算值")
        no_evidence = [i["id"] for i in items if i["status"] == "no_evidence"]
        if no_evidence:
            reasons.append("以下条目没有证据摘要，暂填分数未经证据支撑：" + "、".join(no_evidence))
    return {
        "basis_version": BASIS_VERSION,
        "rubric_version": result.get("rule_version") or "",
        "detail_version": EVALUATION_DETAIL_VERSION,
        "kind": "evaluation",
        "record_short": short_id(record.get("record_id")),
        "template_id": record.get("template_id") or "",
        "weight_mode": mode,
        "status": status,
        "status_label": label,
        "formula": {
            "rule": policy.get("formula") or "系统增强分 = Σ(条目增强分 × 条目权重)",
            "expression": expression,
            "result": f"{formula_value:.4f}".rstrip("0").rstrip(".") if formula_value is not None else None,
            "decimals": 4,
            "comparison_rule": ("证据分差 = Σ(学校权重 × 增强分) − 学校分；权重分差 = 增强分 − Σ(学校权重 × 增强分)；"
                                "总分差 = 证据分差 + 权重分差"),
        },
        "overall": {
            "system_score": system_score,
            "formula_value": formula_value,
            "matches_page": bool(system_score is not None and formula_value is not None
                                 and abs(formula_value - float(system_score)) < 1e-9),
            "school_score": school_block.get("score_10"),
            "school_raw": school_block.get("raw_score"),
            "teaching_score_70": school_block.get("teaching_score_70"),
            "anchor_level": anchor_level(system_score) if system_score is not None else None,
            "evidence_delta": comparison.get("evidence_delta"),
            "weight_delta": comparison.get("weight_delta"),
            "total_delta": comparison.get("total_delta"),
            "school_weight_reviewed_score": comparison.get("school_weight_reviewed_score"),
        },
        "items": items,
        "insufficient_items": insufficient,
        "reasons": reasons,
        "computed_at": computed_at or _now(),
    }


def evaluation_basis_sentence(record: dict[str, Any]) -> str:
    basis = record.get("score_basis") if isinstance(record.get("score_basis"), dict) else None
    if basis is None or basis.get("kind") != "evaluation":
        basis = evaluation_score_basis(record)
    overall = basis["overall"]
    if basis["status"] in {"insufficient", "not_available"}:
        return f"系统增强分依据：{basis['status_label']}（{'；'.join(basis['reasons'])}）"
    scored = [i for i in basis["items"] if i["status"] in {"scored", "pending_review"}]
    missing = basis["insufficient_items"]
    text = (f"系统增强分依据：{len(scored)} 个条目按「分数×权重」加总得 {_fmt(overall['system_score'])}"
            f"（学校分 {_fmt(overall['school_score'])}，证据分差 {_fmt(overall['evidence_delta'])}、"
            f"权重分差 {_fmt(overall['weight_delta'])}），命中锚点 {_fmt(overall['anchor_level'])} 分档")
    if missing:
        text += f"；{NOT_SCORED_LABEL}条目：{'、'.join(missing)}"
    return text + f"（规则 {basis['rubric_version']}）"


# ------------------------------------------------------------------- privacy

def redact_for_admin(basis: dict[str, Any]) -> dict[str, Any]:
    """Company-admin view: numbers, anchors, time points and goal codes only."""
    import copy

    value = copy.deepcopy(basis)
    value["view"] = "admin"
    value["privacy_note"] = "管理员视角：不显示教师观察原文、IEP 原文与学生姓名。"

    def clean_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cleaned = []
        for ref in refs:
            kind = ref.get("kind")
            if kind == "teacher_observation":
                cleaned.append({"kind": kind, "label": ref.get("label"), "text": "（教师观察原文不对管理员展示）"})
            elif kind == "iep":
                cleaned.append({"kind": kind, "label": ref.get("label"), "item_count": ref.get("item_count"),
                                "text": "（IEP 原文不对管理员展示）"})
            elif kind == "course_goal":
                cleaned.append({"kind": kind, "label": ref.get("label"), "goal_id": ref.get("goal_id"),
                                "text": ref.get("goal_id")})
            else:
                cleaned.append({k: v for k, v in ref.items() if k in {"kind", "label", "start_sec", "end_sec",
                                                                       "text", "url", "record_shorts"}})
        return cleaned

    if "evidence_refs" in value:
        value["evidence_refs"] = clean_refs(value["evidence_refs"])
    for item in value.get("items") or []:
        item["evidence_refs"] = clean_refs(item.get("evidence_refs") or [])
    value.pop("student_name", None)
    return value


# -------------------------------------------------------------------- reports

def rubric_appendix_text() -> str:
    """「评分标准细则」appendix: every dimension's anchors, evidence and sources, plus the 10 items."""
    from .assessment_rubric import DIMENSION_WEIGHTS as weights

    parts = [f"学生测量量表 {RUBRIC_VERSION}（细则 {RUBRIC_DETAIL_VERSION}）：十分制，6 分为试行参考线；"
             "综合分 = Σ(维度分 × 权重)，仅在教师复核、四个维度齐全且观察至少 2 次时生成。"]
    for name, weight in weights.items():
        anchors = "；".join(f"{level}分 {DIMENSION_ANCHORS[name][level]}" for level in ANCHOR_LEVELS)
        sources = "、".join(DATA_SOURCE_LABELS[key] for key in DIMENSION_SOURCES[name])
        parts.append(f"{DIMENSION_LABELS[name]}（权重 {round(weight * 100)}%）：{anchors}。证据要求：{DIMENSION_EVIDENCE[name]}"
                     f"数据来源：{sources}。不计分情形：{'；'.join(DIMENSION_NOT_SCORED[name])}。")
    detail = evaluation_rubric_detail()
    parts.append(f"课堂双轨评价（规则 {detail['rule_version']}，细则 {detail['detail_version']}）：学校单项 A 9—10 / B 6—8 / "
                 "C 3—5 / D 1—2；系统增强分 = Σ(条目增强分 × 条目权重)，未观察或无证据的条目留空、不填 0。")
    for item in detail["items"]:
        anchors = "；".join(f"{a['level']}分 {a['text']}" for a in item["anchors"] if a["level"] in (10, 6, 2))
        parts.append(f"{item['id']}「{item['label']}」：{anchors}。证据：{item['evidence']}")
    return "".join(parts)


def attach_score_basis_report(workspace: dict[str, Any], evaluations: list[dict[str, Any]] | None = None) -> None:
    """Add 「评分依据摘要」 and 「附录：评分标准细则」 chapters to a course workspace report."""
    report = workspace.get("report")
    if not isinstance(report, dict) or not isinstance(report.get("sections"), list):
        return
    names = {p.get("student_id"): p.get("display_name") or "学生" for p in workspace.get("people") or []}
    lines = []
    for record in workspace.get("records") or []:
        assessment = record.get("assessment") or {}
        if not record.get("reviewed") or record.get("evidence_status", "current") != "current":
            continue
        score = assessment.get("score")
        label = f"{names.get(record.get('student_id'), '学生')} · {record.get('goal_id')}"
        if score is None:
            lines.append(f"{label}：{measurement_basis_sentence(record)}。")
        else:
            lines.append(f"{label} 综合 {score:.2f}/10，{measurement_basis_sentence(record)}。")
    for evaluation in evaluations or []:
        result = evaluation.get("result") or {}
        school = (result.get("school") or {}).get("score_10")
        lines.append(f"课堂评价「{_excerpt(evaluation.get('course_name'), 30)}」学校分 {_fmt(school)}，"
                     f"{evaluation_basis_sentence(evaluation)}。")
    # 依据摘要与细则附录放在 appendix_sections：正文 sections 与正文字数口径保持不变。
    appendix = []
    if lines:
        appendix.append({"title": "评分依据摘要", "source": "score_basis",
                         "text": "每个分数均可在页面「查看依据」中看到公式、代入数值、命中锚点与证据。" + "".join(lines)})
        appendix.append({"title": "附录：评分标准细则", "source": "rubric_appendix", "text": rubric_appendix_text()})
        report["appendix_sections"] = appendix
        report["appendix_character_count"] = sum(len(s["text"]) for s in appendix)
    else:
        report.pop("appendix_sections", None)
        report.pop("appendix_character_count", None)
