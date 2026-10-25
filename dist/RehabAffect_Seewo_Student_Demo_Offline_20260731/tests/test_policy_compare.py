from pathlib import Path

import pytest

from src.rehab_affect.policy_compare import compare_policies
from src.rehab_affect.train_policy import train_and_evaluate


pytest.importorskip("sklearn")

SCENARIO_DIR = Path(__file__).resolve().parents[1] / "configs" / "scenarios"


def test_policy_compare_reports_rule_raw_and_shielded_variants(tmp_path: Path) -> None:
    model_path = tmp_path / "learned_school_policy.pkl"
    metrics_path = tmp_path / "metrics.json"
    train_and_evaluate(
        scenario_dir=SCENARIO_DIR,
        output=model_path,
        metrics_output=metrics_path,
        augmentations_per_scenario=2,
        eval_ratio=0.25,
        benchmark_backend="kinematic",
    )

    payload = compare_policies(
        scenario_dir=SCENARIO_DIR,
        model_path=model_path,
        backend_name="kinematic",
        augmentations_per_scenario=1,
    )

    variants = {item["variant"]: item for item in payload["variants"]}
    assert set(variants) == {"rule", "learned_raw", "learned_shielded"}
    assert variants["rule"]["aggregate_metrics"]["safety_violation_count"] == 0
    assert variants["learned_shielded"]["aggregate_metrics"]["safety_violation_count"] == 0
    assert "continue_and_encourage" in variants["learned_shielded"]["confusion_matrix"]
    assert "disabled" in variants["learned_raw"]["shield_counts"]
