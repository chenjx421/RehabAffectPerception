from pathlib import Path

import pytest

from src.rehab_affect.robustness_eval import run_robustness_eval
from src.rehab_affect.train_policy import train_and_evaluate


pytest.importorskip("sklearn")

SCENARIO_DIR = Path(__file__).resolve().parents[1] / "configs" / "scenarios"


def test_robustness_eval_summarizes_policy_variants(tmp_path: Path) -> None:
    model_path = tmp_path / "learned_school_policy.pkl"
    train_and_evaluate(
        scenario_dir=SCENARIO_DIR,
        output=model_path,
        metrics_output=tmp_path / "metrics.json",
        augmentations_per_scenario=2,
        benchmark_backend="kinematic",
    )

    payload = run_robustness_eval(
        scenario_dir=SCENARIO_DIR,
        model_path=model_path,
        backend_name="kinematic",
        seeds=[11, 22],
        augmentations_per_scenario=1,
    )

    assert payload["run_count"] == 2
    assert "learned_shielded" in payload["summary"]
    assert payload["summary"]["learned_shielded"]["pass_safety_gate"] is True
    assert payload["summary"]["learned_shielded"]["min_action_match_accuracy"] >= 0.85
