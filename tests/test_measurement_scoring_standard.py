from __future__ import annotations

import json
from pathlib import Path

import pytest

from rehab_affect.assessment_rubric import (
    DIMENSION_WEIGHTS,
    MIN_OBSERVED,
    build_assessment_summary,
    rubric_contract,
)
from rehab_affect.demo2_measurement import render_measurement
from rehab_affect.demo2_measurement_store import Demo2MeasurementStore
from rehab_affect.student_record_store import Demo2StudentRecordStore

FULL = {"accuracy": 10, "independence": 10, "consistency": 10, "transfer": 10}


def test_weights_match_page_contract():
    contract = rubric_contract()
    assert DIMENSION_WEIGHTS == {"accuracy": 0.35, "independence": 0.30, "consistency": 0.20, "transfer": 0.15}
    assert [(d["label"], d["weight_percent"]) for d in contract["dimensions"]] == [
        ("准确性", 35), ("独立性", 30), ("一致性", 20), ("泛化性", 15)]
    assert contract["scale"]["pass_score"] == 6 and contract["scale"]["max"] == 10
    assert contract["min_observed"] == MIN_OBSERVED == 2
    assert [p["title"] for p in contract["principles"]] == [
        "目标对齐", "提示层级", "相同难度", "新材料独立性", "留空而非填0", "可比性保证"]


def test_full_marks_scores_ten_with_two_decimals():
    summary = build_assessment_summary(FULL, opportunities=3, observed=2, reviewed=True)
    assert summary["score"] == 10.0
    assert summary["score_display"] == "10.00"
    assert summary["evidence_status"] == "证据充分"
    assert summary["evidence_reasons"] == []


@pytest.mark.parametrize("scores,expected", [
    ({"accuracy": 8, "independence": 7, "consistency": 6, "transfer": 5}, 6.85),
    ({"accuracy": 7.3, "independence": 6.1, "consistency": 5.9, "transfer": 4.7}, 6.27),
    ({"accuracy": 0, "independence": 0, "consistency": 0, "transfer": 0}, 0.0),
    ({"accuracy": 9.9, "independence": 0, "consistency": 3.3, "transfer": 10}, 5.63),
])
def test_weighted_formula_rounds_half_up(scores, expected):
    summary = build_assessment_summary(scores, opportunities=5, observed=5, reviewed=True)
    manual = sum(scores[k] * w for k, w in DIMENSION_WEIGHTS.items())
    assert summary["score"] == expected
    assert abs(summary["score"] - manual) <= 0.005 + 1e-9
    assert summary["score_display"] == f"{expected:.2f}"


@pytest.mark.parametrize("kwargs,reason_fragment", [
    ({"scores": FULL, "observed": 3, "reviewed": False}, "已完成复核"),
    ({"scores": {**FULL, "transfer": None}, "observed": 3, "reviewed": True}, "泛化性"),
    ({"scores": {"accuracy": 10, "independence": 10, "consistency": 10}, "observed": 3, "reviewed": True}, "泛化性"),
    ({"scores": FULL, "observed": 1, "reviewed": True}, "observed=1"),
    ({"scores": FULL, "observed": 0, "reviewed": True}, "observed=0"),
])
def test_unmet_condition_is_evidence_insufficient_without_score(kwargs, reason_fragment):
    summary = build_assessment_summary(kwargs["scores"], opportunities=3, observed=kwargs["observed"],
                                       reviewed=kwargs["reviewed"])
    assert summary["evidence_status"] == "证据不足"
    assert summary["score"] is None and summary["score_display"] is None
    assert summary["overall_score"] is None
    assert summary["confidence"] is None
    assert any(reason_fragment in reason for reason in summary["evidence_reasons"])


def test_empty_dimension_stays_empty_and_is_not_zero():
    summary = build_assessment_summary({**FULL, "consistency": None}, opportunities=3, observed=3, reviewed=True)
    assert summary["dimensions"]["consistency"]["score"] is None
    assert summary["score"] is None
    zero = build_assessment_summary({**FULL, "consistency": 0}, opportunities=3, observed=3, reviewed=True)
    assert zero["dimensions"]["consistency"]["score"] == 0
    assert zero["score"] == 8.0


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "ScoringTest-")
    log_dir = tmp_path / "logs"
    monkeypatch.setenv("REHAB_DEMO2_MEASUREMENT_DEBUG_LOG_DIR", str(log_dir))
    records = Demo2StudentRecordStore(tmp_path / "m.sqlite3", tmp_path / "documents")
    teacher = records.authenticate_account("school_uploader_01", "ScoringTest-school_uploader_01")
    token = records.create_account_session(teacher)["token"]
    records.save_account_school_context(token, {"city": "测试市", "district": "测试区", "school_name": "测试学校"})
    store = Demo2MeasurementStore(records)
    student = store.identities.create_student(token, {"display_name": "虚构同名学生"})
    return store, token, student["student_id"], log_dir


def _payload(student_id, **overrides):
    payload = {
        "record_id": "score-1", "expected_version": 0, "student_id": student_id,
        "lesson_date": "2026-09-10", "lesson_id": "lesson-1", "course_name": "合成课程",
        "goal_id": "goal-1", "measurement_context": "独立完成", "criterion": "三次中两次独立完成",
        "scores": dict(FULL), "opportunities": 3, "observed": 2, "reviewed": False,
        "evidence": "合成观察证据", "source_type": "classroom_observation",
    }
    payload.update(overrides)
    return payload


def _log_lines(log_dir: Path):
    lines = []
    for path in sorted(log_dir.glob("measurement_debug_*.jsonl")):
        lines += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return lines


def test_store_create_review_and_debug_log(env):
    store, token, student_id, log_dir = env
    first = store.save(token, _payload(student_id, scores={**FULL, "transfer": None}))
    assert first["assessment"]["evidence_status"] == "证据不足"
    assert first["assessment"]["score"] is None
    assert first["scores"]["transfer"] is None

    second = store.save(token, _payload(student_id, expected_version=1, reviewed=True))
    assert second["assessment"]["evidence_status"] == "证据充分"
    assert second["assessment"]["score"] == 10.0
    assert second["assessment"]["score_display"] == "10.00"

    workspace = store.workspace(token)
    assert workspace["rubric"] == rubric_contract()
    assert workspace["records"][0]["assessment"]["score"] == 10.0

    entries = _log_lines(log_dir)
    ops = [entry["operation"] for entry in entries]
    assert ops == ["measurement_create", "score_compute", "measurement_update", "measurement_review", "score_compute"]
    for entry in entries:
        assert entry["ts"] and entry["student_id"] == student_id
        assert set(entry["scores"]) == set(DIMENSION_WEIGHTS)
        assert "observed" in entry
    insufficient = entries[1]
    assert insufficient["result"] == "insufficient_evidence"
    assert insufficient["score"] is None and insufficient["evidence_status"] == "证据不足"
    assert insufficient["scores"]["transfer"] is None
    assert any("已完成复核" in r for r in insufficient["evidence_reasons"])
    scored = entries[-1]
    assert scored["result"] == "scored" and scored["score"] == 10.0 and scored["observed"] == 2
    assert "10×0.35" in scored["formula"]
    assert "虚构同名学生" not in json.dumps(entries, ensure_ascii=False)


def test_standard_page_renders_from_backend_contract():
    html = render_measurement({"role": "school_uploader", "username": "t1"})
    assert "const RUBRIC=" in html
    assert '"weight_percent": 35' in html and '"min_observed": 2' in html
    assert "renderStandard" in html and "最低评分条件" in html and "评分原则" in html
    assert "provScore" not in html  # 未达条件时页面不显示任何暂定分数字
