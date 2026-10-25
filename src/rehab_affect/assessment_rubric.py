"""可复核的学生课堂评分标准与长期趋势聚合（试点校内部参考）。

评分只描述课堂中被观察到的学习机会，不把表情、动作或参与度直接当成
“学会”。0--10 分的定义、及格线和维度权重集中在这里，前端、报告和
后续数据库服务都可以复用同一份契约。

本量表是试点校教师复核用的内部评分参考，不是任何官方标准：
- 35/30/20/15 的维度权重是试点设计，待学校校准；
- 6/10 的及格线是本次试点请求的参考线，不是官方认证的及格标准；
- 只有教师复核过（reviewed=True）且证据充分（observed>=2、四个维度齐全）
  的记录才产出总分；置信度不做任何校准，恒为 None，不伪造；
- 长期趋势只聚合已复核、证据充分的记录，空缺课时保留为空缺点，
  绝不按 0 分处理，也不生成任何预测或合成数据。
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta
from statistics import mean
from typing import Any


RUBRIC_VERSION = "2026-09-15.pilot-v2"
PASS_SCORE = 6.0
# 试点权重：35/30/20/15 为试点设计，待学校校准，不代表官方权重。
DIMENSION_WEIGHTS: dict[str, float] = {
    "accuracy": 0.35,
    "independence": 0.30,
    "consistency": 0.20,
    "transfer": 0.15,
}

SCORE_LEVELS = {
    0: "已经提供并观察学习机会，但未达到该项表现要求；无证据请记为未观察",
    2: "在完整示范或持续协助下完成，尚不能独立复现",
    4: "部分完成，需要重复提示、拆分任务或明显协助",
    6: "达到本节目标的最低要求，可在简单提示下完成",
    8: "大多独立且表现稳定，偶尔需要普通提示",
    10: "独立、稳定，并能迁移到相似的新材料或新情境",
}

SCALE = {"min": 0, "max": 10, "pass_score": PASS_SCORE, "pass_label": "及格"}

_NOTE = (
    "本量表为试点校内部评分参考：35/30/20/15 维度权重与 6 分及格线均为试点设定，"
    "待学校校准；仅教师复核且证据充分的记录产出总分，不构成任何官方成绩或等级。"
)

_TREND_NOTE = (
    "长期趋势只聚合已教师复核且证据充分的正式记录；未复核、证据不足或无效评分的"
    "课堂保留为空缺点，不按 0 分处理，也不生成任何预测或合成数据。"
)


def _validate_score(value: Any) -> float | None:
    """Strict 0--10 score validation.

    ``None`` means unobserved and is returned as-is.  Anything else must be a
    real ``int``/``float`` (never ``bool``, NaN or Inf) within 0..10; values
    out of range raise instead of being silently clamped.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("评分必须是 0 到 10 之间的数字（仅接受 int/float，不接受 bool/字符串）")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("评分必须是有限数值，不接受 NaN/Inf")
    if number < 0.0 or number > 10.0:
        raise ValueError("评分超出 0--10 范围：直接拒绝，不做截断")
    return number


def score_band(score: float | None) -> dict[str, Any]:
    """Return a human-readable band while keeping the numeric score intact."""
    if score is None:
        return {"key": "unobserved", "label": "未观察", "pass": None}
    score = _validate_score(score)
    if score >= 8:
        key, label = "independent", "独立稳定"
    elif score >= PASS_SCORE:
        key, label = "pass", "达到标准"
    elif score >= 4:
        key, label = "developing", "发展中"
    else:
        key, label = "support", "需要支持"
    return {"key": key, "label": label, "pass": score >= PASS_SCORE}


def weighted_score(scores: Mapping[str, Any] | None, observed: Iterable[str] | None = None) -> float | None:
    """Weighted mean with missing dimensions removed and weights renormalised.

    ``None`` values are unobserved dimensions and are skipped; any other value
    must pass strict 0--10 validation or ``ValueError`` is raised.  A valid
    zero is a real score and is never treated as missing.
    """
    if scores is None:
        return None
    names = set(observed) if observed is not None else set(scores)
    usable: list[tuple[str, float]] = []
    for name in DIMENSION_WEIGHTS:
        if name in names and name in scores:
            value = _validate_score(scores[name])
            if value is not None:
                usable.append((name, value))
    if not usable:
        return None
    total_weight = sum(DIMENSION_WEIGHTS[name] for name, _ in usable)
    return round(sum(value * DIMENSION_WEIGHTS[name] for name, value in usable) / total_weight, 2)


def build_assessment_summary(
    scores: Mapping[str, Any] | None,
    *,
    opportunities: int = 0,
    observed: int = 0,
    reviewed: bool = False,
    source: str = "课堂视频窗口与教师复核",
) -> dict[str, Any]:
    """Build the shared 10-point assessment object used by UI and reports.

    Only teacher-reviewed, evidence-sufficient assessments produce an
    ``overall_score``: all four dimensions must be present, ``observed >= 2``
    and ``reviewed`` must be True.  Otherwise ``overall_score`` is None and
    ``provisional_score`` carries a preliminary weighted value only when all
    four dimensions are available (regardless of review state).  No
    confidence number is ever fabricated -- it stays None.
    """
    if isinstance(opportunities, bool) or not isinstance(opportunities, int) or opportunities < 0:
        raise ValueError("opportunities 必须是非负整数")
    if isinstance(observed, bool) or not isinstance(observed, int) or observed < 0:
        raise ValueError("observed 必须是非负整数")
    if observed > opportunities:
        raise ValueError("observed 不能大于 opportunities")
    if type(reviewed) is not bool:
        raise ValueError('reviewed 必须明确为 true 或 false')
    if scores is None:
        scores = {}
    if not isinstance(scores, Mapping):
        raise ValueError('scores 必须是四维评分对象')

    normalized: dict[str, float | None] = {}
    for name in DIMENSION_WEIGHTS:
        if name in scores:
            normalized[name] = _validate_score(scores[name])

    all_present = all(normalized.get(name) is not None for name in DIMENSION_WEIGHTS)
    provisional = weighted_score(normalized) if all_present and observed >= 2 else None
    overall = provisional if reviewed else None
    insufficient = observed < 2 or not all_present
    band = score_band(overall)
    passed = None if overall is None else overall >= PASS_SCORE

    return {
        "rubric_version": RUBRIC_VERSION,
        "scale": dict(SCALE),
        "dimensions": {
            name: {
                "score": round(normalized[name], 1) if normalized.get(name) is not None else None,
                "weight": weight,
                "weight_percent": round(weight * 100),
            }
            for name, weight in DIMENSION_WEIGHTS.items()
        },
        "overall_score": overall,
        "provisional_score": provisional,
        "band": band,
        "passed": passed,
        "confidence": None,
        "opportunities": opportunities,
        "observed": observed,
        "reviewed": reviewed,
        "review_status": "教师已复核" if reviewed else "系统初评，待教师复核",
        "insufficient_evidence": insufficient,
        "source": source,
        "note": _NOTE,
    }


def _as_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()


def build_longitudinal_series(records: Iterable[Mapping[str, Any]], *, today: Any | None = None) -> dict[str, Any]:
    """Aggregate lesson-level assessment objects into lesson/week/month/60-day views.

    Only records that match the current rubric version, carry a teacher
    ``reviewed=True`` flag, are not flagged ``insufficient_evidence`` and have
    a valid numeric ``overall_score`` count as trend sessions.  Records with a
    valid, non-future lesson date that fail those checks still appear in the
    ``lesson`` view as null points (score None) so missing lessons show as
    gaps instead of silently becoming zero; they are counted as excluded.

    Invalid or future dates are dropped entirely and lesson dates are never
    defaulted to today.  ``today`` defaults to the system date, not the latest
    record.  Duplicate ``record_id`` values raise ``ValueError`` so repeated
    uploads cannot overweight the trend, and mixing different nonempty
    ``goal_id``/``measurement_context`` values across records also raises
    ``ValueError`` (the backend must prefilter to a single goal/context).
    """
    records = list(records)
    if not all(isinstance(record, Mapping) for record in records):
        raise ValueError("records 中的每一项都必须是映射（dict）")

    # Duplicate uploads must not be double-counted.
    seen_ids: dict[Any, int] = {}
    for record in records:
        record_id = record.get("record_id")
        if record_id is not None:
            seen_ids[record_id] = seen_ids.get(record_id, 0) + 1
    duplicates = sorted(str(record_id) for record_id, count in seen_ids.items() if count > 1)
    if duplicates:
        raise ValueError(f"records 中存在重复的 record_id：{', '.join(duplicates)}")

    # A single series must describe one goal/context; reject mixed groups.
    def _nonempty(value: Any) -> bool:
        return value is not None and value != ""

    goal_ids = [record.get("goal_id") for record in records if _nonempty(record.get("goal_id"))]
    contexts = [record.get("measurement_context") for record in records if _nonempty(record.get("measurement_context"))]
    if goal_ids and any(goal_id != goal_ids[0] for goal_id in goal_ids[1:]):
        raise ValueError("records 混用了不同的 goal_id，请按 goal_id 预过滤后再聚合")
    if contexts and any(context != contexts[0] for context in contexts[1:]):
        raise ValueError("records 混用了不同的 measurement_context，请按 measurement_context 预过滤后再聚合")

    anchor = _as_date(today) if today is not None else date.today()

    # (date, score-or-None, record_id): null points mark excluded-but-dated lessons.
    parsed: list[tuple[date, float | None, Any]] = []
    accepted = 0
    excluded = 0
    for record in records:
        record_id = record.get("record_id")
        try:
            when = _as_date(record.get("date", record.get("timestamp")))
        except (TypeError, ValueError):
            excluded += 1  # no usable lesson date; never default it to today
            continue
        if when > anchor:
            excluded += 1  # future records never enter any chart
            continue
        try:
            score = _validate_score(record.get("overall_score", record.get("score")))
        except ValueError:
            score = None
        qualifies = (
            score is not None
            and record.get("reviewed") is True
            and not bool(record.get("insufficient_evidence", False))
            and record.get("rubric_version") == RUBRIC_VERSION
        )
        if qualifies:
            accepted += 1
        else:
            excluded += 1
        parsed.append((when, score if qualifies else None, record_id))
    parsed.sort(key=lambda item: (item[0], item[1] is None))

    def _points(items: Iterable[tuple[date, float | None, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "record_id": record_id,
                "date": when.isoformat(),
                "score": round(score, 2) if score is not None else None,
                "band": score_band(score),
            }
            for when, score, record_id in items
        ]

    weekly: dict[str, list[float | None]] = defaultdict(list)
    monthly: dict[str, list[float | None]] = defaultdict(list)
    for when, score, _ in parsed:
        iso_year, week, _ = when.isocalendar()
        weekly[f"{iso_year}-W{week:02d}"].append(score)
        monthly[f"{when.year}-{when.month:02d}"].append(score)

    def _aggregate(groups: Mapping[str, list[float | None]]) -> list[dict[str, Any]]:
        result = []
        for key in sorted(groups):
            values = groups[key]
            valid = [value for value in values if value is not None]
            result.append(
                {
                    "period": key,
                    "score": round(mean(valid), 2) if valid else None,
                    "sessions": len(valid),
                    "missing_sessions": len(values) - len(valid),
                }
            )
        return result

    rolling_start = anchor - timedelta(days=59)
    rolling = [(when, score) for when, score, _ in parsed if rolling_start <= when <= anchor]
    rolling_valid = [score for _, score in rolling if score is not None]
    return {
        "rubric_version": RUBRIC_VERSION,
        "pass_score": PASS_SCORE,
        "lesson": _points(parsed),
        "week": _aggregate(weekly),
        "month": _aggregate(monthly),
        "rolling_60_days": {
            "from": rolling_start.isoformat(),
            "to": anchor.isoformat(),
            "score": round(mean(rolling_valid), 2) if rolling_valid else None,
            "sessions": len(rolling_valid),
            "missing_sessions": len(rolling) - len(rolling_valid),
        },
        "accepted_records": accepted,
        "excluded_records": excluded,
        "note": _TREND_NOTE,
    }
