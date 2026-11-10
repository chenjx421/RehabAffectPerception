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
from decimal import ROUND_HALF_UP, Decimal
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

MIN_OBSERVED = 2
EVIDENCE_SUFFICIENT = "证据充分"
EVIDENCE_INSUFFICIENT = "证据不足"
DIMENSION_LABELS: dict[str, str] = {
    "accuracy": "准确性",
    "independence": "独立性",
    "consistency": "一致性",
    "transfer": "泛化性",
}
# 页面“评分标准”与后端计算共用的说明，避免两处口径漂移。
DIMENSION_DESCRIPTIONS: dict[str, str] = {
    "accuracy": "目标行为完成正确率，0分=有机会但无成功，留空=无观察机会",
    "independence": "完成行为所需提示级别，10分=完全独立，0分=全程辅助",
    "consistency": "相同条件下重复出现的稳定程度，需至少2次观察机会",
    "transfer": "在新材料或新情境中是否出现，无泛化机会时留空而非填0",
}
SCORING_PRINCIPLES: tuple[tuple[str, str], ...] = (
    ("目标对齐", "所记录行为须与学习目标直接对应，不记录课堂管理或偶发行为。"),
    ("提示层级", "同一课次内使用相同提示级别，不混合不同支持强度的观察。"),
    ("相同难度", "一致性维度仅统计难度相当的重复试次，不将新材料与熟悉材料混合。"),
    ("新材料独立性", "首次接触新材料或新情境的表现，记入泛化性维度而非准确性。"),
    ("留空而非填0", "当某维度没有观察机会时，留空；0分表示有机会但未成功，含义不同。"),
    ("可比性保证", "跨课比较须相同目标、测量条件、通过标准和量表版本；任一项不同即不可比。"),
)

# 评分标准细则（锚点 / 证据要求 / 数据来源 / 不计分情形）。细则只解释每个分档，
# 不改变上面的权重与计算；细则文字调整时递增 RUBRIC_DETAIL_VERSION。
RUBRIC_DETAIL_VERSION = "2026-11-01.anchors-v1"
ANCHOR_LEVELS: tuple[int, ...] = (10, 8, 6, 4, 2, 0)
DIMENSION_ANCHORS: dict[str, dict[int, str]] = {
    "accuracy": {
        10: "本课约定的学习机会中几乎全部正确完成（约 90% 以上），出现错误能自我纠正",
        8: "多数机会正确完成（约 70%–89%），偶有错误",
        6: "过半机会正确完成（约 50%–69%），达到本节目标最低要求",
        4: "少数机会正确完成（约 30%–49%），常需教师纠错",
        2: "偶尔正确（约 10%–29%），多数机会未完成",
        0: "提供了学习机会但未出现正确表现（10% 以下）；没有机会时应留空而非记 0",
    },
    "independence": {
        10: "完全独立完成，不需要任何提示",
        8: "仅需手势或视觉提示（指向、图卡）即可完成",
        6: "需要口语提示才能完成",
        4: "需要教师示范后才能完成",
        2: "需要部分肢体辅助才能完成",
        0: "全程需要肢体辅助，无法自主启动",
    },
    "consistency": {
        10: "相同条件下每次机会都稳定出现",
        8: "绝大多数重复机会稳定出现，仅一次波动",
        6: "过半的重复机会出现，表现基本稳定",
        4: "时有时无，出现次数不足一半",
        2: "多次机会中仅偶发出现一次",
        0: "至少 2 次相同条件机会均未出现",
    },
    "transfer": {
        10: "在新材料和新情境中都能独立出现",
        8: "在新材料或新情境中出现，仅需普通提示",
        6: "在相近的新材料中出现，需要口语提示",
        4: "在新材料中需要示范后才出现",
        2: "新材料中只在大量辅助下出现",
        0: "提供了新材料或新情境机会但未出现；没有泛化机会时留空",
    },
}
DIMENSION_EVIDENCE: dict[str, str] = {
    "accuracy": "记录本课学习机会次数与正确完成次数（或视频中稳定参与/正确回应的片段），并写明通过标准。",
    "independence": "记录每次完成时实际使用的提示层级（独立/视觉/口语/示范/肢体），同一课次按最高支持强度归档。",
    "consistency": "至少 2 次相同难度、相同条件的重复机会，写明各次是否出现。",
    "transfer": "写明所用的新材料或新情境，以及该情境下的完成方式；单节视频没有新情境时留空。",
}
DATA_SOURCE_LABELS: dict[str, str] = {
    "video": "视频指标",
    "teacher_observation": "教师观察",
    "course_goal": "课程任务目标",
    "iep": "IEP 要点",
}
DIMENSION_SOURCES: dict[str, tuple[str, ...]] = {
    "accuracy": ("teacher_observation", "video", "course_goal"),
    "independence": ("teacher_observation", "video", "iep"),
    "consistency": ("teacher_observation", "video"),
    "transfer": ("teacher_observation", "course_goal", "iep"),
}
DIMENSION_NOT_SCORED: dict[str, tuple[str, ...]] = {
    "accuracy": ("本课没有提供该目标的学习机会", "目标行为与本课学习目标无关（如课堂管理行为）"),
    "independence": ("提示层级未记录或无法从视频判断", "他人代答或集体回答无法归到该学生"),
    "consistency": ("相同条件的重复机会少于 2 次", "各次机会的材料或难度不同，不可比较"),
    "transfer": ("本课没有安排新材料或新情境", "单节视频只有熟悉材料，无法观察泛化"),
}
# 记录中的提示层级（support_level）对应的独立性参考档位。
SUPPORT_LEVEL_ANCHORS: dict[str, tuple[str, int | None]] = {
    "independent": ("独立完成", 10),
    "visual": ("视觉/手势提示", 8),
    "verbal": ("口语提示", 6),
    "demonstration": ("示范", 4),
    "physical": ("肢体辅助", 2),
    "unknown": ("未记录", None),
}
MIN_CONDITIONS: tuple[str, ...] = (
    "教师须勾选「已完成复核」，否则不生成综合得分。",
    "准确性、独立性、一致性、泛化性四个维度都须有有效分数（非空）。",
    f"观察次数至少为 {MIN_OBSERVED} 次（observed ≥ {MIN_OBSERVED}）。",
    "不满足任一条件时标注「证据不足」，不输出得分数字，不使用置信度替代。",
)


def anchor_level(score: Any) -> int | None:
    """Highest anchor level not above ``score`` (7.5 -> 6); None stays None."""
    value = _validate_score(score)
    if value is None:
        return None
    return min(10, int(value // 2) * 2)


# 课程总览「课程结论」的试行等级：结论分 = 课程评价总分 × 60% + 学生目标达成度均值 × 40%。
# 阈值与权重是试行口径（未经学校校准），页面与报告都要标明「试行」。
COURSE_GRADE_VERSION = "2026-11-01.course-grade-trial-v1"
COURSE_GRADE_WEIGHTS: dict[str, float] = {"course_evaluation": 0.6, "student_attainment": 0.4}
COURSE_GRADE_BANDS: tuple[dict[str, Any], ...] = (
    {"key": "excellent", "label": "优秀", "min": 85.0, "range": "≥ 85"},
    {"key": "good", "label": "良好", "min": 70.0, "range": "70 ~ 84.9"},
    {"key": "qualified", "label": "合格", "min": 60.0, "range": "60 ~ 69.9"},
    {"key": "improve", "label": "待改进", "min": 0.0, "range": "< 60"},
)
COURSE_GRADE_NOTE = (
    "课程等级为试行口径：课程评价总分取学校标准评分原表总分（10 项 × 10 分 = 100 分，须已核对），"
    "学生目标达成度 = 每名学生已复核且证据充分的目标综合分平均 × 10；两者按 60% / 40% 合成，"
    "保留一位小数后对照等级阈值。阈值与权重待学校校准，不构成教师绩效或学生能力定级。"
)


def _one_decimal(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def course_grade(score: Any) -> dict[str, Any] | None:
    """Grade band of a 0--100 conclusion score; ``None`` stays ``None`` (no conclusion)."""
    if score is None:
        return None
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(float(score)):
        raise ValueError("课程结论分必须是有限数字")
    number = float(score)
    if number < 0 or number > 100:
        raise ValueError("课程结论分超出 0--100 范围")
    for band in COURSE_GRADE_BANDS:
        if number >= band["min"]:
            return {"key": band["key"], "label": band["label"], "range": band["range"]}
    return {"key": COURSE_GRADE_BANDS[-1]["key"], "label": COURSE_GRADE_BANDS[-1]["label"],
            "range": COURSE_GRADE_BANDS[-1]["range"]}


def course_conclusion_score(course_total: Any, attainment_mean: Any) -> dict[str, Any]:
    """Weighted conclusion with every intermediate value rounded the way the page shows it."""
    for value in (course_total, attainment_mean):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise ValueError("课程评价总分与学生目标达成度均值必须是有限数字")
        if float(value) < 0 or float(value) > 100:
            raise ValueError("课程评价总分与学生目标达成度均值须在 0--100 之间")
    total = Decimal(str(_one_decimal(Decimal(str(course_total)))))
    attainment = Decimal(str(_one_decimal(Decimal(str(attainment_mean)))))
    course_weight = Decimal(str(COURSE_GRADE_WEIGHTS["course_evaluation"]))
    attainment_weight = Decimal(str(COURSE_GRADE_WEIGHTS["student_attainment"]))
    course_part = (total * course_weight).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    attainment_part = (attainment * attainment_weight).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    score = _one_decimal(course_part + attainment_part)
    return {
        "course_total": float(total), "course_weight": float(course_weight),
        "attainment_mean": float(attainment), "attainment_weight": float(attainment_weight),
        "course_part": float(course_part), "attainment_part": float(attainment_part),
        "score": score, "grade": course_grade(score),
        "text": (f"结论分 = 课程评价总分 {float(total):g} × {float(course_weight):g} + 学生目标达成度均值 "
                 f"{float(attainment):g} × {float(attainment_weight):g} = {float(course_part):g} + "
                 f"{float(attainment_part):g} = {score:g}"),
    }


def course_grade_contract() -> dict[str, Any]:
    return {
        "version": COURSE_GRADE_VERSION,
        "trial": True,
        "weights": [
            {"key": "course_evaluation", "label": "课程评价总分", "weight": COURSE_GRADE_WEIGHTS["course_evaluation"],
             "weight_percent": round(COURSE_GRADE_WEIGHTS["course_evaluation"] * 100)},
            {"key": "student_attainment", "label": "学生目标达成度均值", "weight": COURSE_GRADE_WEIGHTS["student_attainment"],
             "weight_percent": round(COURSE_GRADE_WEIGHTS["student_attainment"] * 100)},
        ],
        "bands": [dict(band) for band in COURSE_GRADE_BANDS],
        "formula": "结论分 = 课程评价总分 × 60% + 学生目标达成度均值 × 40%（保留一位小数）",
        "note": COURSE_GRADE_NOTE,
    }


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
    # Decimal + ROUND_HALF_UP keeps the page rule "两位小数" exact (no 6.849999 drift).
    total_weight = sum(Decimal(str(DIMENSION_WEIGHTS[name])) for name, _ in usable)
    weighted = sum(Decimal(str(value)) * Decimal(str(DIMENSION_WEIGHTS[name])) for name, value in usable)
    return float((weighted / total_weight).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def evidence_shortfalls(scores: Mapping[str, Any] | None, *, observed: Any, reviewed: Any) -> list[str]:
    """Return every unmet minimum-scoring condition (empty list = 证据充分).

    Order follows the page: 复核 -> 四维非空 -> observed >= 2.
    """
    reasons: list[str] = []
    if reviewed is not True:
        reasons.append("教师未勾选「已完成复核」")
    scores = scores if isinstance(scores, Mapping) else {}
    missing = [DIMENSION_LABELS[name] for name in DIMENSION_WEIGHTS if scores.get(name) is None]
    if missing:
        reasons.append("维度为空：" + "、".join(missing))
    if isinstance(observed, bool) or not isinstance(observed, int) or observed < MIN_OBSERVED:
        reasons.append(f"观察次数不足（observed={observed}，至少需要 {MIN_OBSERVED} 次）")
    return reasons


def rubric_contract() -> dict[str, Any]:
    """Machine-readable rubric shared by the 评分标准 page and the scoring code."""
    return {
        "rubric_version": RUBRIC_VERSION,
        "detail_version": RUBRIC_DETAIL_VERSION,
        "scale": dict(SCALE),
        "min_observed": MIN_OBSERVED,
        "decimals": 2,
        "dimensions": [
            {
                "key": name,
                "label": DIMENSION_LABELS[name],
                "weight": weight,
                "weight_percent": round(weight * 100),
                "description": DIMENSION_DESCRIPTIONS[name],
                "anchors": [{"level": level, "text": DIMENSION_ANCHORS[name][level]} for level in ANCHOR_LEVELS],
                "evidence": DIMENSION_EVIDENCE[name],
                "data_sources": [{"key": key, "label": DATA_SOURCE_LABELS[key]} for key in DIMENSION_SOURCES[name]],
                "not_scored": list(DIMENSION_NOT_SCORED[name]),
            }
            for name, weight in DIMENSION_WEIGHTS.items()
        ],
        "score_levels": [{"level": level, "text": SCORE_LEVELS[level]} for level in ANCHOR_LEVELS],
        "anchor_rule": "得分落在两个锚点之间时，取不高于得分的锚点（如 7.5 分对应 6 分档）。",
        "support_levels": [{"key": key, "label": label, "anchor_level": level}
                           for key, (label, level) in SUPPORT_LEVEL_ANCHORS.items()],
        "min_conditions": list(MIN_CONDITIONS),
        "principles": [{"title": title, "text": text} for title, text in SCORING_PRINCIPLES],
        "evidence_status": {"sufficient": EVIDENCE_SUFFICIENT, "insufficient": EVIDENCE_INSUFFICIENT},
        "confidence_substitute": False,
        "course_grade": course_grade_contract(),
    }


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
    provisional = weighted_score(normalized) if all_present and observed >= MIN_OBSERVED else None
    overall = provisional if reviewed else None
    insufficient = observed < MIN_OBSERVED or not all_present
    shortfalls = evidence_shortfalls(normalized, observed=observed, reviewed=reviewed)
    evidence_status = EVIDENCE_INSUFFICIENT if shortfalls else EVIDENCE_SUFFICIENT
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
        # score/evidence_status 是对外评分契约：证据不足时 score 恒为 None，不用置信度替代。
        "score": overall if not shortfalls else None,
        "score_display": f"{overall:.2f}" if overall is not None and not shortfalls else None,
        "evidence_status": evidence_status,
        "evidence_reasons": shortfalls,
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
