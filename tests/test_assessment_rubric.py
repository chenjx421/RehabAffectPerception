"""Tests for the pilot teacher-reviewed assessment rubric and trend aggregation."""

import math
from datetime import date, timedelta

import pytest

from rehab_affect.assessment_rubric import (
    DIMENSION_WEIGHTS,
    PASS_SCORE,
    RUBRIC_VERSION,
    build_assessment_summary,
    build_longitudinal_series,
    score_band,
    weighted_score,
)


def _valid_record(record_id, when, score, **overrides):
    record = {
        "record_id": record_id,
        "date": when,
        "overall_score": score,
        "reviewed": True,
        "insufficient_evidence": False,
        "rubric_version": RUBRIC_VERSION,
    }
    record.update(overrides)
    return record


# ---------------------------------------------------------------- contract


def test_pilot_version_pass_line_and_weights():
    assert RUBRIC_VERSION == "2026-09-15.pilot-v2"
    assert PASS_SCORE == 6
    # 35/30/20/15 are pilot design weights pending school calibration.
    assert DIMENSION_WEIGHTS == {
        "accuracy": 0.35,
        "independence": 0.30,
        "consistency": 0.20,
        "transfer": 0.15,
    }
    assert sum(DIMENSION_WEIGHTS.values()) == 1


def test_score_band_boundaries_and_null_pass_is_none():
    assert score_band(None) == {"key": "unobserved", "label": "未观察", "pass": None}
    assert score_band(0)["key"] == "support"
    assert score_band(4)["key"] == "developing"
    assert score_band(5.999)["key"] == "developing"
    assert score_band(5.999)["pass"] is False
    assert score_band(6)["key"] == "pass"
    assert score_band(6)["pass"] is True
    assert score_band(8)["key"] == "independent"
    assert score_band(10)["pass"] is True


# ------------------------------------------------------------- weighted score


def test_weighted_score_all_dimensions_and_renormalised_missing():
    assert weighted_score({"accuracy": 6, "independence": 6, "consistency": 6, "transfer": 6}) == 6
    # Missing dimensions are dropped and remaining weights renormalised.
    assert weighted_score({"accuracy": 6}) == 6
    assert weighted_score({"transfer": 8}) == 8


def test_weighted_score_zero_is_a_real_score_not_missing():
    # A valid 0 must keep its weight, unlike a missing/unobserved dimension.
    assert weighted_score({"accuracy": 0, "independence": 6}) == pytest.approx(2.77)
    assert weighted_score({"independence": 6}) == 6
    # None means unobserved and is skipped entirely.
    assert weighted_score({"accuracy": None, "independence": 6}) == 6
    # observed= narrows which dimensions count.
    assert weighted_score({"accuracy": 4, "independence": 8}, observed=["accuracy"]) == 4


@pytest.mark.parametrize(
    "bad",
    [True, False, "8", math.nan, math.inf, -math.inf, -0.01, 10.01, [6]],
)
def test_weighted_score_rejects_invalid_values_instead_of_clamping(bad):
    with pytest.raises(ValueError):
        weighted_score({"accuracy": bad})


def test_weighted_score_none_scores_argument_is_unobserved():
    assert weighted_score(None) is None
    assert weighted_score({}) is None
    assert weighted_score({"accuracy": None}) is None


# ----------------------------------------------------------- assessment summary


def test_summary_reviewed_complete_produces_score_without_fabricated_confidence():
    summary = build_assessment_summary(
        {"accuracy": 8, "independence": 6, "consistency": 8, "transfer": 4},
        opportunities=5,
        observed=5,
        reviewed=True,
    )
    assert summary["overall_score"] == 6.8
    assert summary["provisional_score"] == 6.8
    assert summary["passed"] is True
    assert summary["band"]["key"] == "pass"
    assert summary["band"]["pass"] is True
    assert summary["confidence"] is None  # never fabricated or calibrated
    assert summary["reviewed"] is True
    assert isinstance(summary["reviewed"], bool)
    assert summary["review_status"] == "教师已复核"
    assert summary["insufficient_evidence"] is False
    assert summary["rubric_version"] == "2026-09-15.pilot-v2"
    assert summary["scale"] == {"min": 0, "max": 10, "pass_score": 6, "pass_label": "及格"}
    # Every dimension name is present with weight info; scores nullable.
    assert set(summary["dimensions"]) == set(DIMENSION_WEIGHTS)
    assert summary["dimensions"]["accuracy"]["score"] == 8
    assert summary["dimensions"]["accuracy"]["weight"] == 0.35
    assert summary["dimensions"]["accuracy"]["weight_percent"] == 35
    assert summary["dimensions"]["transfer"]["weight_percent"] == 15
    # The rubric is a pilot reference, not an official grade.
    assert "试点" in summary["note"]
    assert "官方" in summary["note"]


def test_summary_unreviewed_has_no_score_only_provisional():
    summary = build_assessment_summary(
        {"accuracy": 8, "independence": 6, "consistency": 8, "transfer": 4},
        opportunities=5,
        observed=5,
        reviewed=False,
    )
    assert summary["overall_score"] is None
    assert summary["provisional_score"] == 6.8
    assert summary["passed"] is None
    assert summary["band"] == {"key": "unobserved", "label": "未观察", "pass": None}
    assert summary["review_status"] == "系统初评，待教师复核"


def test_summary_insufficient_evidence_blocks_score_even_when_reviewed():
    summary = build_assessment_summary(
        {"accuracy": 8, "independence": 6, "consistency": 8, "transfer": 4},
        opportunities=1,
        observed=1,
        reviewed=True,
    )
    assert summary["overall_score"] is None
    assert summary["provisional_score"] is None  # observed < 2
    assert summary["passed"] is None
    assert summary["insufficient_evidence"] is True


def test_summary_missing_dimension_marks_insufficient_and_null_score():
    summary = build_assessment_summary(
        {"accuracy": 8},
        opportunities=5,
        observed=5,
        reviewed=True,
    )
    assert summary["overall_score"] is None
    assert summary["passed"] is None
    assert summary["insufficient_evidence"] is True
    # All four dimension names stay present with nullable scores.
    assert set(summary["dimensions"]) == set(DIMENSION_WEIGHTS)
    assert summary["dimensions"]["transfer"]["score"] is None
    assert summary["dimensions"]["accuracy"]["score"] == 8


def test_summary_none_or_empty_scores_allowed_as_unobserved():
    for scores in (None, {}):
        summary = build_assessment_summary(scores, opportunities=3, observed=3, reviewed=True)
        assert summary["overall_score"] is None
        assert summary["passed"] is None
        assert summary["insufficient_evidence"] is True
        assert set(summary["dimensions"]) == set(DIMENSION_WEIGHTS)
        assert all(dim["score"] is None for dim in summary["dimensions"].values())


def test_summary_near_pass_boundary_is_consistent_with_display():
    # 5.999 and 6 both display as 6.0, so both must read as passing:
    # the band must never contradict the displayed score.
    for scores in (
        {"accuracy": 5.999, "independence": 5.999, "consistency": 5.999, "transfer": 5.999},
        {"accuracy": 6, "independence": 6, "consistency": 6, "transfer": 6},
    ):
        summary = build_assessment_summary(scores, opportunities=2, observed=2, reviewed=True)
        assert summary["overall_score"] == 6.0
        assert summary["band"]["pass"] is True
        assert summary["passed"] is True
    # Just below the rounding threshold, display and band agree again.
    summary = build_assessment_summary(
        {"accuracy": 5.994, "independence": 5.994, "consistency": 5.994, "transfer": 5.994},
        opportunities=2,
        observed=2,
        reviewed=True,
    )
    assert summary["overall_score"] == 5.99
    assert summary["band"]["key"] == "developing"
    assert summary["passed"] is False


@pytest.mark.parametrize("bad", [True, "8", math.nan, math.inf, -1, 11, 10.5])
def test_summary_rejects_invalid_scores_instead_of_clamping(bad):
    with pytest.raises(ValueError):
        build_assessment_summary({"accuracy": bad}, opportunities=2, observed=2, reviewed=True)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"opportunities": -1},
        {"observed": -1},
        {"observed": True},
        {"opportunities": True},
        {"opportunities": 2.0},
        {"observed": 1.5},
        {"observed": 3, "opportunities": 2},  # observed cannot exceed opportunities
    ],
)
def test_summary_rejects_invalid_opportunity_counts(kwargs):
    with pytest.raises(ValueError):
        build_assessment_summary({"accuracy": 6}, reviewed=True, **kwargs)


def test_summary_ignores_unknown_dimension_keys():
    summary = build_assessment_summary(
        {"accuracy": 6, "attention": 99},
        opportunities=2,
        observed=2,
        reviewed=True,
    )
    assert "attention" not in summary["dimensions"]
    assert summary["overall_score"] is None  # other three dimensions unobserved


# --------------------------------------------------------- longitudinal series


def test_series_lesson_points_carry_record_id_date_score_and_band():
    result = build_longitudinal_series(
        [_valid_record("r1", date(2026, 9, 1), 8)],
        today=date(2026, 9, 15),
    )
    assert result["lesson"] == [
        {
            "record_id": "r1",
            "date": "2026-09-01",
            "score": 8,
            "band": {"key": "independent", "label": "独立稳定", "pass": True},
        }
    ]
    assert result["accepted_records"] == 1
    assert result["excluded_records"] == 0
    assert result["rubric_version"] == RUBRIC_VERSION
    assert result["pass_score"] == PASS_SCORE


@pytest.mark.parametrize(
    "overrides",
    [
        {"reviewed": False},  # unreviewed stays a gap, never a 0
        {"reviewed": 1},  # truthy non-bool does not count as reviewed
        {"rubric_version": "2026-09-15.v1"},  # other rubric versions do not qualify
        {"insufficient_evidence": True},
        {"overall_score": None},
        {"overall_score": True},  # bool score is invalid
        {"overall_score": 11},  # out of range is rejected, not clamped
        {"overall_score": "8"},
    ],
)
def test_series_invalid_or_unreviewed_records_become_null_gaps(overrides):
    result = build_longitudinal_series(
        [_valid_record("r2", date(2026, 9, 10), 8, **overrides)],
        today=date(2026, 9, 15),
    )
    assert result["lesson"][0]["date"] == "2026-09-10"
    assert result["lesson"][0]["score"] is None
    assert result["lesson"][0]["band"] == {"key": "unobserved", "label": "未观察", "pass": None}
    assert result["accepted_records"] == 0
    assert result["excluded_records"] == 1


def test_series_accepts_score_fallback_key():
    record = {
        "record_id": "r3",
        "date": date(2026, 9, 2),
        "score": 7,
        "reviewed": True,
        "rubric_version": RUBRIC_VERSION,
    }
    result = build_longitudinal_series([record], today=date(2026, 9, 15))
    assert result["accepted_records"] == 1
    assert result["lesson"][0]["score"] == 7


def test_series_drops_invalid_and_future_dates_entirely():
    result = build_longitudinal_series(
        [
            _valid_record("bad", "not-a-date", 6),
            _valid_record("future", date(2026, 9, 16), 6),
            _valid_record("ok", date(2026, 9, 1), 6),
        ],
        today=date(2026, 9, 15),
    )
    assert [point["date"] for point in result["lesson"]] == ["2026-09-01"]
    assert result["accepted_records"] == 1
    assert result["excluded_records"] == 2


def test_series_never_defaults_lesson_date_to_today():
    result = build_longitudinal_series(
        [{"record_id": "x", "overall_score": 6, "reviewed": True, "rubric_version": RUBRIC_VERSION}],
        today=date(2026, 9, 15),
    )
    assert result["lesson"] == []
    assert result["excluded_records"] == 1
    assert "2026-09-15" not in {point["date"] for point in result["lesson"]}


def test_series_today_defaults_to_system_date_not_latest_input():
    result = build_longitudinal_series([_valid_record("r1", date(2026, 1, 5), 7)])
    today = date.today()
    assert result["rolling_60_days"]["to"] == today.isoformat()
    assert result["rolling_60_days"]["from"] == (today - timedelta(days=59)).isoformat()
    assert result["rolling_60_days"]["to"] != "2026-01-05"


def test_series_week_month_and_rolling_average_only_valid_sessions():
    result = build_longitudinal_series(
        [
            _valid_record("r1", date(2026, 9, 8), 8),
            _valid_record("r2", date(2026, 9, 12), 6),
            _valid_record("r3", date(2026, 9, 12), 5, reviewed=False),  # gap, not a 0
            _valid_record("r4", date(2026, 8, 1), 0),  # a real zero score
        ],
        today=date(2026, 9, 15),
    )
    week = {item["period"]: item for item in result["week"]}
    assert week["2026-W37"]["score"] == 7.0  # mean(8, 6), gap excluded
    assert week["2026-W37"]["sessions"] == 2
    assert week["2026-W37"]["missing_sessions"] == 1
    month = {item["period"]: item for item in result["month"]}
    assert month["2026-09"]["score"] == 7.0
    assert month["2026-09"]["sessions"] == 2
    assert month["2026-09"]["missing_sessions"] == 1
    # Zero is a valid session, distinct from the gap: mean(8, 6, 0).
    assert month["2026-08"]["score"] == 0.0
    assert month["2026-08"]["sessions"] == 1
    assert month["2026-08"]["missing_sessions"] == 0
    rolling = result["rolling_60_days"]
    assert rolling["from"] == "2026-07-18"
    assert rolling["to"] == "2026-09-15"
    assert rolling["score"] == pytest.approx(4.67)
    assert rolling["sessions"] == 3
    assert rolling["missing_sessions"] == 1
    assert result["accepted_records"] == 3
    assert result["excluded_records"] == 1
    assert len(result["lesson"]) == 4  # three sessions plus the visible gap


def test_series_gap_only_groups_keep_null_score_with_missing_sessions():
    result = build_longitudinal_series(
        [_valid_record("r1", date(2026, 9, 10), 8, reviewed=False)],
        today=date(2026, 9, 15),
    )
    week = result["week"][0]
    assert week["period"] == "2026-W37"
    assert week["score"] is None
    assert week["sessions"] == 0
    assert week["missing_sessions"] == 1
    assert result["month"][0]["score"] is None
    assert result["rolling_60_days"]["score"] is None
    assert result["rolling_60_days"]["sessions"] == 0
    assert result["rolling_60_days"]["missing_sessions"] == 1
    assert result["accepted_records"] == 0
    assert result["excluded_records"] == 1


def test_series_iso_week_year_boundary():
    result = build_longitudinal_series(
        [
            _valid_record("r1", date(2024, 12, 30), 6),  # Monday of ISO 2025-W01
            _valid_record("r2", date(2026, 1, 1), 8),  # ISO 2026-W01, month 2026-01
        ],
        today=date(2026, 1, 1),
    )
    week_periods = {item["period"] for item in result["week"]}
    assert "2025-W01" in week_periods  # ISO year, not calendar year 2024
    assert "2026-W01" in week_periods
    assert "2024-W53" not in week_periods
    month_periods = {item["period"] for item in result["month"]}
    assert "2026-01" in month_periods


def test_series_60_day_window_is_inclusive_on_both_edges():
    result = build_longitudinal_series(
        [
            _valid_record("before", date(2026, 7, 17), 5),
            _valid_record("edge", date(2026, 7, 18), 6),
            _valid_record("today", date(2026, 9, 15), 8),
            _valid_record("future", date(2026, 9, 16), 7),
        ],
        today=date(2026, 9, 15),
    )
    rolling = result["rolling_60_days"]
    assert rolling["from"] == "2026-07-18"
    assert rolling["to"] == "2026-09-15"
    assert rolling["sessions"] == 2  # 2026-07-17 outside, future date dropped
    assert rolling["score"] == 7.0
    assert [point["date"] for point in result["lesson"]] == [
        "2026-07-17",
        "2026-07-18",
        "2026-09-15",
    ]
    assert result["accepted_records"] == 3
    assert result["excluded_records"] == 1


def test_series_rejects_duplicate_record_ids():
    with pytest.raises(ValueError, match="重复"):
        build_longitudinal_series(
            [
                _valid_record("dup", date(2026, 9, 1), 6),
                _valid_record("dup", date(2026, 9, 1), 6),
            ],
            today=date(2026, 9, 15),
        )


def test_series_rejects_mixed_goal_or_context_groups():
    with pytest.raises(ValueError, match="goal_id"):
        build_longitudinal_series(
            [
                _valid_record("a", date(2026, 9, 1), 6, goal_id="goal-1"),
                _valid_record("b", date(2026, 9, 2), 6, goal_id="goal-2"),
            ],
            today=date(2026, 9, 15),
        )
    with pytest.raises(ValueError, match="measurement_context"):
        build_longitudinal_series(
            [
                _valid_record("a", date(2026, 9, 1), 6, measurement_context="class"),
                _valid_record("b", date(2026, 9, 2), 6, measurement_context="recess"),
            ],
            today=date(2026, 9, 15),
        )
    # Empty or missing group keys are ignored, not treated as a distinct group.
    result = build_longitudinal_series(
        [
            _valid_record("a", date(2026, 9, 1), 6, goal_id="goal-1"),
            _valid_record("b", date(2026, 9, 2), 6, goal_id=""),
            _valid_record("c", date(2026, 9, 3), 6),
        ],
        today=date(2026, 9, 15),
    )
    assert result["accepted_records"] == 3


def test_series_never_forecasts_or_synthesises_points():
    result = build_longitudinal_series(
        [
            _valid_record("r1", date(2026, 9, 1), 6),
            _valid_record("r2", date(2026, 9, 3), 5, reviewed=False),
        ],
        today=date(2026, 9, 15),
    )
    assert "forecast" not in result
    # Only the two uploaded lesson dates exist; nothing is filled between them
    # or up to today, and the gap stays None instead of becoming 0.
    assert [point["date"] for point in result["lesson"]] == ["2026-09-01", "2026-09-03"]
    assert [point["score"] for point in result["lesson"]] == [6, None]
    assert result["accepted_records"] == 1
    assert result["excluded_records"] == 1
