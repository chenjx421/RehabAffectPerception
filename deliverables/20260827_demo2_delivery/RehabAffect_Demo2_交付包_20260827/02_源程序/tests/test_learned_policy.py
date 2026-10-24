from pathlib import Path

import pytest

from src.rehab_affect.learned_policy import LearnedSchoolPolicy
from src.rehab_affect.sim_runner import load_scenario, run_scenario
from src.rehab_affect.train_policy import train_and_evaluate


pytest.importorskip("sklearn")

SCENARIO_DIR = Path(__file__).resolve().parents[1] / "configs" / "scenarios"


def test_train_policy_baseline_runs_full_scenario_set(tmp_path: Path) -> None:
    model_path = tmp_path / "learned_school_policy.pkl"
    metrics_path = tmp_path / "learned_policy_metrics.json"

    payload = train_and_evaluate(
        scenario_dir=SCENARIO_DIR,
        output=model_path,
        metrics_output=metrics_path,
        benchmark_backend="kinematic",
    )

    assert model_path.exists()
    assert metrics_path.exists()
    assert payload["dataset"]["row_count"] == 18
    assert payload["training_metrics"]["action_accuracy"] == 1.0
    assert payload["benchmark"]["aggregate_metrics"]["action_match_accuracy"] == 1.0
    assert payload["benchmark"]["aggregate_metrics"]["safety_violation_count"] == 0


def test_train_policy_with_domain_randomized_holdout(tmp_path: Path) -> None:
    model_path = tmp_path / "learned_school_policy.pkl"
    metrics_path = tmp_path / "learned_policy_metrics.json"

    payload = train_and_evaluate(
        scenario_dir=SCENARIO_DIR,
        output=model_path,
        metrics_output=metrics_path,
        benchmark_backend="kinematic",
        augmentations_per_scenario=4,
        eval_ratio=0.25,
        seed=123,
    )

    assert payload["dataset"]["base_row_count"] == 18
    assert payload["dataset"]["row_count"] > 18
    assert payload["dataset"]["eval_row_count"] > 0
    assert payload["holdout_metrics"]["action_accuracy"] >= 0.85
    assert (
        payload["holdout_metrics"]["benchmark_aggregate_metrics"]["safety_violation_count"]
        == 0
    )


def test_loaded_learned_policy_drives_robot_action(tmp_path: Path) -> None:
    model_path = tmp_path / "learned_school_policy.pkl"
    metrics_path = tmp_path / "learned_policy_metrics.json"
    train_and_evaluate(
        scenario_dir=SCENARIO_DIR,
        output=model_path,
        metrics_output=metrics_path,
        benchmark_backend="kinematic",
    )

    policy = LearnedSchoolPolicy.load(model_path)
    result = run_scenario(
        load_scenario(SCENARIO_DIR / "pain_risk_safety.json"),
        robot_policy=policy,
    )

    assert result["policy"] == "learned_school_policy"
    assert result["metrics"]["action_match_accuracy"] == 1.0
    assert result["metrics"]["safety_violation_count"] == 0
    assert result["steps"][1]["robot_action"]["action_id"] == "stop_and_check_pain_risk"
