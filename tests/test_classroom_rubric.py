"""Contract tests for the dual-track classroom rubric (school table vs enhanced weights).

Numbers are hand-computed or cross-checked with Decimal; assertions follow the documented
contract in docs/dual_track_api_20260916.md rather than mirroring implementation order.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import json

import pytest

from rehab_affect.classroom_rubric import catalog, evaluate

BASIC = "basic_100"
LEGACY = "qingpu_15"

_CATALOG = catalog()
_TEMPLATES = {t["id"]: t for t in _CATALOG["templates"]}
_BASIC_IDS = [item["id"] for item in _TEMPLATES[BASIC]["items"]]
_LEGACY_IDS = [item["id"] for item in _TEMPLATES[LEGACY]["items"]]


# ------------------------------------------------------------------ helpers


def _d(value):
    return Decimal(str(value))


def _round4(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _row(item_id, school, enhanced, *, evidence="", reason="", suggestion=""):
    return {
        "id": item_id,
        "school_score": school,
        "enhanced_score": enhanced,
        "evidence": evidence,
        "reason": reason,
        "suggestion": suggestion,
    }


def _pick(value, index):
    return value[index] if isinstance(value, (list, tuple)) else value


def _rows(template_id, school, enhanced, *, evidence="", reason="", suggestion=""):
    ids = _BASIC_IDS if template_id == BASIC else _LEGACY_IDS
    return [
        _row(item_id, s, z, evidence=_pick(evidence, n), reason=_pick(reason, n), suggestion=_pick(suggestion, n))
        for n, (item_id, s, z) in enumerate(zip(ids, school, enhanced))
    ]


def _payload(template_id, rows, *, reviewed=False, school_source="teacher_recorded"):
    return {
        "template_id": template_id,
        "reviewed": reviewed,
        "school_source": school_source,
        "items": rows,
    }


def _basic(school, enhanced, *, reviewed=False, evidence="", reason="", suggestion=""):
    rows = _rows(BASIC, school, enhanced, evidence=evidence, reason=reason, suggestion=suggestion)
    return _payload(BASIC, rows, reviewed=reviewed)


def _legacy(scores, *, reviewed=False, evidence="", school_source="rubric_initial"):
    rows = _rows(LEGACY, scores, [None] * len(_LEGACY_IDS), evidence=evidence)
    return _payload(LEGACY, rows, reviewed=reviewed, school_source=school_source)


def _item(result, item_id):
    return next(row for row in result["comparison"]["items"] if row["id"] == item_id)


def _all_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _all_keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from _all_keys(value)


def _rejects(payload, why):
    try:
        evaluate(payload)
    except ValueError:
        return
    raise AssertionError(f"{why} 未被拒绝")


# ------------------------------------------------------------------ catalog


def test_catalog_shape_rule_version_and_deep_copy_isolation():
    assert _CATALOG["rule_version"]
    assert [t["id"] for t in _CATALOG["templates"]] == [BASIC, LEGACY]
    assert [s["id"] for s in _CATALOG["subjects"]] == [
        "language",
        "math",
        "practice",
        "sports",
        "music",
        "general",
    ]
    assert all(s["focus"] and s["note"] for s in _CATALOG["subjects"])
    assert {r["id"] for r in _CATALOG["references"]} == {"policy", "feedback", "gas", "udl", "aac2024", "cast2024"}

    snapshot = catalog()
    mutated = catalog()
    mutated["templates"][0]["items"][0]["school_weight"] = 0.99
    mutated["templates"][0]["items"][0]["enhanced_weight"] = 0.99
    mutated["templates"][0]["categories"][0]["enhanced_weight"] = 0.99
    mutated["subjects"][0]["focus"].append("被篡改")
    mutated["references"][0]["title"] = "被篡改"

    fresh = catalog()
    assert fresh["templates"][0] is not mutated["templates"][0]
    assert fresh["templates"][0]["items"][0]["school_weight"] == 0.1
    assert fresh["templates"][0]["items"][0]["enhanced_weight"] == 0.15
    assert fresh["templates"][0]["categories"][0]["enhanced_weight"] == 0.25
    assert fresh["subjects"][0]["focus"] == snapshot["subjects"][0]["focus"]
    assert fresh["references"][0]["title"] == snapshot["references"][0]["title"]

    # 篡改 catalog 返回值不得影响计算：i1 仍按未篡改的 (0.15-0.10)*8 计算
    result = evaluate(_basic([8] * 10, [8] * 10))
    assert result["enhanced"]["score_10"] == 8.0
    assert _item(result, "i1")["weight_delta"] == 0.4


def test_references_do_not_claim_validated_weights():
    for ref in _CATALOG["references"]:
        assert ref["url"].startswith("https://")
        assert ref["support"].strip() and ref["limitation"].strip()
        # 文献只描述支持方向，不得声称验证了权重百分比
        assert not any(word in ref["support"] for word in ("验证", "权重", "有效"))
        assert any(word in ref["limitation"] for word in ("不", "未"))
    assert "尚未校准" in _TEMPLATES[BASIC]["note"]
    assert "尚未验证" in evaluate(_basic([8] * 10, [8] * 10))["enhanced"]["status_label"]


# ------------------------------------------------------------------ weights


def test_basic_template_has_ten_items_and_weights_sum_to_one():
    basic = _TEMPLATES[BASIC]
    assert basic["enhanced_available"] is True
    assert (basic["school_min"], basic["school_max"]) == (1, 10)
    assert [item["id"] for item in basic["items"]] == [f"i{n}" for n in range(1, 11)]
    # 学校10项各0.1；增强为候选设计权重，两者合计都必须为1
    assert [item["school_weight"] for item in basic["items"]] == [0.1] * 10
    assert [item["enhanced_weight"] for item in basic["items"]] == [
        0.15,
        0.10,
        0.08,
        0.07,
        0.05,
        0.10,
        0.10,
        0.20,
        0.08,
        0.07,
    ]
    assert sum(_d(item["school_weight"]) for item in basic["items"]) == Decimal("1")
    assert sum(_d(item["enhanced_weight"]) for item in basic["items"]) == Decimal("1")


def test_basic_category_weights_are_25_20_40_15_and_items_match():
    categories = _TEMPLATES[BASIC]["categories"]
    assert [c["id"] for c in categories] == ["goals", "content", "process", "teacher"]
    assert [c["school_weight"] for c in categories] == [0.20, 0.30, 0.30, 0.20]
    assert [c["enhanced_weight"] for c in categories] == [0.25, 0.20, 0.40, 0.15]
    assert sum(_d(c["school_weight"]) for c in categories) == Decimal("1")
    assert sum(_d(c["enhanced_weight"]) for c in categories) == Decimal("1")
    for category in categories:
        assert category["rationale"].strip()
        members = [i for i in _TEMPLATES[BASIC]["items"] if i["category_id"] == category["id"]]
        assert members
        assert sum(_d(i["school_weight"]) for i in members) == _d(category["school_weight"])
        assert sum(_d(i["enhanced_weight"]) for i in members) == _d(category["enhanced_weight"])


def test_result_categories_carry_template_weights_and_rationale():
    result = evaluate(_basic([8] * 10, [8] * 10))
    assert [c["id"] for c in result["categories"]] == ["goals", "content", "process", "teacher"]
    assert [c["enhanced_weight"] for c in result["categories"]] == [0.25, 0.20, 0.40, 0.15]
    assert all(c["rationale"].strip() for c in result["categories"])
    assert [c["school_score"] for c in result["categories"]] == [8.0] * 4
    assert [c["enhanced_score"] for c in result["categories"]] == [8.0] * 4


# ------------------------------------------------------------------ numbers


def test_uniform_school_8_keeps_80_out_of_100_and_56_out_of_70():
    result = evaluate(_basic([8] * 10, [8] * 10))
    school = result["school"]
    assert result["rule_version"] == _CATALOG["rule_version"]
    assert result["template_id"] == BASIC
    assert school["score_10"] == 8.0
    assert school["raw_score"] == 80.0
    assert school["raw_max"] == 100
    assert school["teaching_score_70"] == 56.0
    assert school["coverage"] == {"scored": 10, "total": 10}
    assert school["passed"] is None

    # 增强同分8：权重合计为1，加权和不改变分数
    assert result["enhanced"]["score_10"] == 8.0
    assert result["enhanced"]["coverage"] == {"scored": 10, "total": 10}
    assert result["enhanced"]["reference_line"] == 6
    assert result["comparison"]["available"] is True
    assert result["comparison"]["evidence_delta"] == 0.0
    assert result["comparison"]["weight_delta"] == 0.0
    assert result["comparison"]["total_delta"] == 0.0

    # 逐项差值：0.10*(8-8) 与 (v-w)*8；逐项权重差合计抵消为0
    first = _item(result, "i1")
    assert first["evidence_delta"] == 0.0
    assert first["weight_delta"] == 0.4  # (0.15 - 0.10) * 8
    assert first["total_delta"] == 0.4
    item_weight = sum((_d(i["weight_delta"]) for i in result["comparison"]["items"]), Decimal("0"))
    item_total = sum((_d(i["total_delta"]) for i in result["comparison"]["items"]), Decimal("0"))
    assert abs(item_weight - _d(result["comparison"]["weight_delta"])) < Decimal("0.001")
    assert abs(item_total - _d(result["comparison"]["total_delta"])) < Decimal("0.001")


def test_uniform_school_8_enhanced_7_gives_minus_one_with_zero_weight_delta():
    result = evaluate(_basic([8] * 10, [7] * 10, reason="增强证据与原分不同"))
    assert result["school"]["score_10"] == 8.0
    assert result["enhanced"]["score_10"] == 7.0
    assert result["comparison"]["evidence_delta"] == -1.0
    assert result["comparison"]["weight_delta"] == 0.0
    assert result["comparison"]["total_delta"] == -1.0
    assert result["comparison"]["school_weight_reviewed_score"] == 7.0

    # 逐项差值 (z-s)*w 与 (v-w)*z，逐项合计等于总分差
    specs = _TEMPLATES[BASIC]["items"]
    for row, spec in zip(result["comparison"]["items"], specs):
        assert _d(row["evidence_delta"]) == _d(spec["school_weight"]) * (_d(7) - _d(8))
        assert _d(row["weight_delta"]) == (_d(spec["enhanced_weight"]) - _d(spec["school_weight"])) * _d(7)
    item_evidence = sum((_d(i["evidence_delta"]) for i in result["comparison"]["items"]), Decimal("0"))
    item_weight = sum((_d(i["weight_delta"]) for i in result["comparison"]["items"]), Decimal("0"))
    item_total = sum((_d(i["total_delta"]) for i in result["comparison"]["items"]), Decimal("0"))
    assert abs(item_evidence - _d(result["comparison"]["evidence_delta"])) < Decimal("0.001")
    assert abs(item_weight - _d(result["comparison"]["weight_delta"])) < Decimal("0.001")
    assert abs(item_total - _d(result["comparison"]["total_delta"])) < Decimal("0.001")


def test_mixed_scores_match_hand_and_decimal_calculation():
    school = [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]
    enhanced = [9, 7, 6, 5, 4, 8, 3, 2, 1, 0]
    result = evaluate(_basic(school, enhanced, reason="逐项说明分差"))

    weights_school = [_d(i["school_weight"]) for i in _TEMPLATES[BASIC]["items"]]
    weights_enhanced = [_d(i["enhanced_weight"]) for i in _TEMPLATES[BASIC]["items"]]
    expected_school = sum(_d(s) for s in school) / Decimal(10)  # 55/10
    expected_enhanced = sum((_d(z) * v for z, v in zip(enhanced, weights_enhanced)), Decimal("0"))
    expected_base = sum((_d(z) * w for z, w in zip(enhanced, weights_school)), Decimal("0"))

    assert result["school"]["score_10"] == 5.5
    assert result["school"]["raw_score"] == 55.0
    assert result["school"]["teaching_score_70"] == 38.5
    assert result["enhanced"]["score_10"] == 4.66  # 加权和，不是算术平均 4.5
    assert result["comparison"]["school_weight_reviewed_score"] == 4.5
    assert result["comparison"]["evidence_delta"] == -1.0  # 4.5 - 5.5
    assert result["comparison"]["weight_delta"] == 0.16  # 4.66 - 4.5
    assert result["comparison"]["total_delta"] == -0.84  # 4.66 - 5.5

    assert _d(result["school"]["score_10"]) == expected_school
    assert _d(result["enhanced"]["score_10"]) == expected_enhanced
    assert _d(result["comparison"]["school_weight_reviewed_score"]) == expected_base
    assert _d(result["comparison"]["evidence_delta"]) == expected_base - expected_school
    assert _d(result["comparison"]["weight_delta"]) == expected_enhanced - expected_base
    assert _d(result["comparison"]["total_delta"]) == expected_enhanced - expected_school

    first = _item(result, "i1")
    assert (first["school_score"], first["enhanced_score"]) == (10, 9)
    assert first["evidence_delta"] == -0.1  # 0.10 * (9 - 10)
    assert first["weight_delta"] == 0.45  # (0.15 - 0.10) * 9
    assert first["total_delta"] == 0.35

    # 分类分：学校为组内算术平均；增强为组内加权和除以该分类增强权重
    expected_enhanced_categories = {
        "goals": Decimal("2.05") / Decimal("0.25"),
        "content": (Decimal("0.08") * 6 + Decimal("0.07") * 5 + Decimal("0.05") * 4) / Decimal("0.20"),
        "process": (Decimal("0.10") * 8 + Decimal("0.10") * 3 + Decimal("0.20") * 2) / Decimal("0.40"),
        "teacher": (Decimal("0.08") * 1 + Decimal("0.07") * 0) / Decimal("0.15"),
    }
    assert [c["school_score"] for c in result["categories"]] == [9.5, 7.0, 4.0, 1.5]
    for category in result["categories"]:
        assert _d(category["enhanced_score"]) == _d(_round4(expected_enhanced_categories[category["id"]]))


def test_item_text_fields_round_trip_to_result():
    result = evaluate(
        _basic(
            [8] * 10,
            [8] * 10,
            evidence="课堂观察 00:03:20",
            reason="原分与增强分相同，无需调整",
            suggestion="下节课增加实物提示",
        )
    )
    row = _item(result, "i7")
    assert row["evidence"] == "课堂观察 00:03:20"
    assert row["reason"] == "原分与增强分相同，无需调整"
    assert row["suggestion"] == "下节课增加实物提示"
    assert row["label"] == _TEMPLATES[BASIC]["items"][6]["label"]


# ------------------------------------------------------------------ missing


def test_missing_school_item_blocks_totals_and_all_deltas():
    school = [8] * 10
    school[3] = None
    result = evaluate(_basic(school, [8] * 10, reason="i4 缺学校分，增强分单独说明"))

    assert result["school"]["score_10"] is None
    assert result["school"]["raw_score"] is None
    assert result["school"]["teaching_score_70"] is None
    assert result["school"]["coverage"] == {"scored": 9, "total": 10}
    assert result["school"]["passed"] is None
    assert result["status"] == "incomplete"
    assert result["enhanced"]["score_10"] == 8.0  # 增强轨仍完整，可单独给出增强总分
    assert result["comparison"]["available"] is False
    assert result["comparison"]["evidence_delta"] is None
    assert result["comparison"]["weight_delta"] is None
    assert result["comparison"]["total_delta"] is None

    # 缺项保持 null，不填0、不归一化
    row = _item(result, "i4")
    assert row["school_score"] is None
    assert row["enhanced_score"] == 8
    assert row["evidence_delta"] is None
    assert row["weight_delta"] is None
    assert row["total_delta"] is None
    assert [r["school_score"] for r in result["comparison"]["items"] if r["id"] != "i4"] == [8] * 9


def test_missing_enhanced_item_blocks_enhanced_total_but_keeps_school_total():
    enhanced = [8] * 10
    enhanced[0] = None
    result = evaluate(_basic([8] * 10, enhanced))

    assert result["school"]["score_10"] == 8.0
    assert result["school"]["teaching_score_70"] == 56.0
    assert result["enhanced"]["score_10"] is None
    assert result["enhanced"]["coverage"] == {"scored": 9, "total": 10}
    assert result["enhanced"]["passed"] is None
    assert result["comparison"]["available"] is False
    assert result["comparison"]["evidence_delta"] is None
    assert result["comparison"]["total_delta"] is None
    assert result["comparison"]["school_weight_reviewed_score"] is None
    assert _item(result, "i1")["school_score"] == 8
    assert _item(result, "i1")["enhanced_score"] is None


def test_enhanced_zero_is_a_scored_zero_not_a_missing_item():
    result = evaluate(
        _basic(
            [8] * 10,
            [0] * 10,
            reviewed=True,
            evidence="课堂观察记录",
            reason="按增强证据下调",
        )
    )
    assert result["status"] == "reviewed"
    assert result["enhanced"]["score_10"] == 0.0
    assert result["enhanced"]["coverage"] == {"scored": 10, "total": 10}
    assert result["enhanced"]["passed"] is False  # 真0分未达6分参考线，而不是缺项
    assert result["comparison"]["available"] is True
    assert result["comparison"]["evidence_delta"] == -8.0
    assert result["comparison"]["weight_delta"] == 0.0
    assert result["comparison"]["total_delta"] == -8.0
    assert _item(result, "i1")["enhanced_score"] == 0
    assert _item(result, "i1")["evidence_delta"] == -0.8
    assert _item(result, "i1")["weight_delta"] == 0.0


# ------------------------------------------------------------------ review


def test_unreviewed_full_result_has_no_pass_verdict():
    result = evaluate(_basic([8] * 10, [9] * 10, reason="增强证据上调"))
    assert result["status"] == "provisional"
    assert result["school"]["passed"] is None
    assert result["enhanced"]["passed"] is None
    assert result["enhanced"]["score_10"] == 9.0
    assert result["comparison"]["available"] is True

    reviewed = evaluate(
        _basic([8] * 10, [9] * 10, reviewed=True, evidence="观察记录", reason="增强证据上调")
    )
    assert reviewed["status"] == "reviewed"
    assert reviewed["enhanced"]["passed"] is True
    assert reviewed["school"]["passed"] is None


def test_pass_line_six_applies_only_to_reviewed_complete_enhanced():
    below = evaluate(_basic([8] * 10, [5] * 10, reviewed=True, evidence="观察记录", reason="下调"))
    assert below["enhanced"]["score_10"] == 5.0
    assert below["enhanced"]["passed"] is False
    assert below["enhanced"]["reference_line"] == 6

    incomplete = evaluate(
        _basic([8] * 10, [6] * 9 + [None], reviewed=True, evidence="观察记录", reason="下调")
    )
    assert incomplete["status"] == "incomplete"
    assert incomplete["enhanced"]["passed"] is None
    assert incomplete["enhanced"]["score_10"] is None


def test_reviewed_requires_evidence_per_scored_item():
    evidence = ["课堂观察记录"] * 10
    evidence[6] = "   "
    _rejects(_basic([8] * 10, [8] * 10, reviewed=True, evidence=evidence), "已复核但缺证据")

    # 未评分项不要求证据
    school = [8] * 10
    enhanced = [8] * 10
    school[6] = None
    enhanced[6] = None
    result = evaluate(_basic(school, enhanced, reviewed=True, evidence=evidence))
    assert result["status"] == "incomplete"
    assert result["school"]["coverage"] == {"scored": 9, "total": 10}
    assert _item(result, "i7")["evidence"] == "   "

    # 未复核时不要求证据
    assert evaluate(_basic([8] * 10, [8] * 10))["status"] == "provisional"


def test_changed_enhanced_score_requires_reason_only_where_changed():
    enhanced = [8] * 10
    enhanced[0] = 7
    _rejects(_basic([8] * 10, enhanced), "增强分改变但未填原因")
    _rejects(_basic([8] * 10, enhanced, reason=["   "] * 10), "增强分改变但原因只有空白")

    reasons = [""] * 10
    reasons[0] = "依增强证据下调"
    result = evaluate(_basic([8] * 10, enhanced, reason=reasons))
    assert _item(result, "i1")["evidence_delta"] == -0.1
    assert _item(result, "i1")["reason"] == "依增强证据下调"
    assert _item(result, "i2")["reason"] == ""
    assert _item(result, "i2")["weight_delta"] == 0.0


# ------------------------------------------------------------------ invalid


@pytest.mark.parametrize(
    "bad",
    [True, False, "8", "8.0", float("nan"), float("inf"), float("-inf"), 0, 11, -1, 0.9, 10.5],
)
def test_school_score_rejects_bool_string_non_finite_and_out_of_range(bad):
    payload = _basic([8] * 10, [8] * 10)
    payload["items"][0]["school_score"] = bad
    with pytest.raises(ValueError):
        evaluate(payload)


@pytest.mark.parametrize(
    "bad",
    [True, False, "7", "7.0", float("nan"), float("inf"), float("-inf"), -1, 11, -0.5, 10.5],
)
def test_enhanced_score_rejects_bool_string_non_finite_and_out_of_range(bad):
    payload = _basic([8] * 10, [8] * 10)
    payload["items"][0]["enhanced_score"] = bad
    with pytest.raises(ValueError):
        evaluate(payload)


@pytest.mark.parametrize("bad", [True, False, 2.5, 1, 6, "5", "A", float("nan")])
def test_legacy_school_score_accepts_only_abcd_enum(bad):
    with pytest.raises(ValueError):
        evaluate(_legacy([bad] + [5] * 14))


@pytest.mark.parametrize("bad", [0, 2, 5, 10])
def test_legacy_rejects_any_enhanced_score(bad):
    rows = _rows(LEGACY, [5] * 15, [bad] * 15)
    with pytest.raises(ValueError):
        evaluate(_payload(LEGACY, rows, school_source="rubric_initial"))


@pytest.mark.parametrize("bad", [1, 0, "true", "yes", None])
def test_reviewed_must_be_an_explicit_bool(bad):
    payload = _basic([8] * 10, [8] * 10)
    payload["reviewed"] = bad
    with pytest.raises(ValueError):
        evaluate(payload)

    missing = _basic([8] * 10, [8] * 10)
    del missing["reviewed"]
    with pytest.raises(ValueError):
        evaluate(missing)


@pytest.mark.parametrize("bad", ["teacher", "", None, "TEACHER_RECORDED", 1])
def test_school_source_must_be_one_of_two_documented_values(bad):
    payload = _basic([8] * 10, [8] * 10)
    payload["school_source"] = bad
    with pytest.raises(ValueError):
        evaluate(payload)


@pytest.mark.parametrize("bad", ["unknown", "", None, "basic", "BASIC_100", 100])
def test_unknown_or_missing_template_is_rejected(bad):
    payload = _basic([8] * 10, [8] * 10)
    payload["template_id"] = bad
    with pytest.raises(ValueError):
        evaluate(payload)


def test_source_label_distinguishes_human_scoring_from_rubric_initial():
    human = evaluate(_basic([8] * 10, [8] * 10))["school"]["source_label"]
    initial = evaluate(
        _payload(BASIC, _rows(BASIC, [8] * 10, [8] * 10), school_source="rubric_initial")
    )["school"]["source_label"]
    assert human.strip() and initial.strip() and human != initial


def test_items_must_match_template_exactly():
    rows = _rows(BASIC, [8] * 10, [8] * 10)
    _rejects(_payload(BASIC, None), "缺items")
    _rejects(_payload(BASIC, {"i1": 8}), "items不是列表")
    _rejects(_payload(BASIC, rows[:9]), "少一项")
    _rejects(_payload(BASIC, rows + [_row("i11", 8, 8)]), "多一项")
    _rejects(_payload(BASIC, rows[:-1] + [_row("i1", 8, 8)]), "重复项")
    _rejects(_payload(BASIC, rows[:-1] + [_row("k10", 8, 8)]), "未知项")
    legacy_rows = _rows(LEGACY, [5] * 15, [None] * 15)
    _rejects(_payload(LEGACY, legacy_rows[:-1] + [_row("i15", 5, None)]), "15项模板混入基本模板条目")


def test_item_rows_must_use_exact_contract_fields():
    cases = {
        "多余字段": lambda row: row.update(grade="A"),
        "缺少suggestion": lambda row: row.pop("suggestion"),
        "缺少evidence": lambda row: row.pop("evidence"),
        "id非字符串": lambda row: row.update(id=1),
        "evidence非字符串": lambda row: row.update(evidence=None),
        "reason非字符串": lambda row: row.update({"reason": 3}),
        "suggestion非字符串": lambda row: row.update(suggestion=["x"]),
        "evidence超长": lambda row: row.update(evidence="观" * 2001),
        "reason超长": lambda row: row.update(reason="因" * 2001),
        "suggestion超长": lambda row: row.update(suggestion="建" * 2001),
    }
    for name, mutate in cases.items():
        payload = _basic([8] * 10, [8] * 10)
        mutate(payload["items"][0])
        _rejects(payload, name)

    payload = _basic([8] * 10, [8] * 10)
    payload["items"][0] = "i1"
    _rejects(payload, "整行非字典")


# ------------------------------------------------------------------ legacy


def test_legacy_template_shape_has_15_items_and_no_enhanced_weights():
    legacy = _TEMPLATES[LEGACY]
    assert legacy["enhanced_available"] is False
    assert (legacy["school_min"], legacy["school_max"]) == (2, 5)
    assert [item["id"] for item in legacy["items"]] == [f"j{n}" for n in range(1, 16)]
    assert all(item["enhanced_weight"] is None for item in legacy["items"])
    assert all(_round4(_d(item["school_weight"])) == _round4(Decimal(1) / Decimal(15)) for item in legacy["items"])
    assert all(c["enhanced_weight"] is None for c in legacy["categories"])
    assert sum(c["school_weight"] for c in legacy["categories"]) == pytest.approx(1.0)
    assert [round(c["school_weight"] * 15) for c in legacy["categories"]] == [2, 2, 4, 4, 3]
    assert "尚无增强映射" in legacy["note"]


def test_legacy_scores_use_abcd_enum_and_mean_times_two():
    scores = [5, 4, 3, 2] * 3 + [5, 4, 3]
    result = evaluate(_legacy(scores))
    mean = sum(_d(s) for s in scores) / Decimal(15)  # 54/15 = 3.6
    assert result["school"]["score_10"] == 7.2
    assert result["school"]["raw_score"] == 3.6
    assert result["school"]["raw_max"] == 5
    assert result["school"]["coverage"] == {"scored": 15, "total": 15}
    assert _d(result["school"]["score_10"]) == mean * 2
    assert _d(result["school"]["raw_score"]) == mean

    repeating = evaluate(_legacy([5] * 7 + [4] * 8))
    repeating_mean = Decimal(67) / Decimal(15)
    assert repeating["school"]["score_10"] == _round4(repeating_mean * 2) == 8.9333
    assert repeating["school"]["raw_score"] == _round4(repeating_mean)

    assert evaluate(_legacy([2] * 15))["school"]["score_10"] == 4.0
    assert evaluate(_legacy([5] * 15))["school"]["score_10"] == 10.0

    categories = {c["id"]: c for c in result["categories"]}
    assert categories["goals"]["school_score"] == 9.0  # (5+4)/2*2
    assert categories["content"]["school_score"] == 5.0  # (3+2)/2*2
    assert categories["process"]["school_score"] == 7.0  # (5+4+3+2)/4*2
    assert categories["teacher"]["school_score"] == 7.0
    assert categories["outcomes"]["school_score"] == 8.0  # (5+4+3)/3*2


def test_legacy_has_no_enhanced_track_no_70_point_score_and_no_fake_grade():
    result = evaluate(_legacy([5, 4, 3, 2] * 3 + [5, 4, 3]))
    assert result["enhanced"]["score_10"] is None
    assert result["enhanced"]["coverage"] == {"scored": 0, "total": 15}
    assert result["enhanced"]["passed"] is None
    assert "尚无增强映射" in result["enhanced"]["status_label"]
    assert result["school"]["teaching_score_70"] is None
    assert result["comparison"]["available"] is False
    for key in ("evidence_delta", "weight_delta", "total_delta", "school_weight_reviewed_score"):
        assert result["comparison"][key] is None
    for row in result["comparison"]["items"]:
        assert row["enhanced_score"] is None
        assert row["evidence_delta"] is None
        assert row["weight_delta"] is None
        assert row["total_delta"] is None
    for category in result["categories"]:
        assert category["enhanced_weight"] is None
        assert category["enhanced_score"] is None
    # 不伪造综合等第：结果中没有任何等级字段或等级文案
    assert not ({"grade", "level", "band", "rank", "等第", "总等第"} & set(_all_keys(result)))
    assert "等第" not in json.dumps(result, ensure_ascii=False)


def test_legacy_reviewed_keeps_pass_empty_and_reports_missing_items():
    result = evaluate(_legacy([5] * 15, reviewed=True, evidence="原表人工评分"))
    assert result["status"] == "reviewed"
    assert result["school"]["passed"] is None
    assert result["enhanced"]["passed"] is None
    assert result["school"]["score_10"] == 10.0

    partial = evaluate(_legacy([5] * 14 + [None]))
    assert partial["status"] == "incomplete"
    assert partial["school"]["score_10"] is None
    assert partial["school"]["coverage"] == {"scored": 14, "total": 15}
    assert partial["comparison"]["available"] is False
