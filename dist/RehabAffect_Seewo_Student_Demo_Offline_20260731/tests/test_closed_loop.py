from pathlib import Path

from src.rehab_affect.closed_loop import (
    aggregate_closed_loop_results,
    run_closed_loop_scenario,
)
from src.rehab_affect.sim_runner import load_scenario


SCENARIO_DIR = Path(__file__).resolve().parents[1] / "configs" / "scenarios"


def test_closed_loop_instruction_feedback_can_recover_confusion() -> None:
    result = run_closed_loop_scenario(
        load_scenario(SCENARIO_DIR / "shape_sorting_confused.json"),
        include_base_steps=True,
    )

    assert result["closed_loop"] is True
    assert result["metrics"]["recovery_count"] >= 1
    assert result["steps"][1]["embodied_feedback"]["outcome"] == "instruction_clarified"
    assert result["steps"][2]["base_ground_truth_state"] == "confused"
    assert result["steps"][2]["ground_truth_state"] == "engaged"
    assert result["steps"][2]["human_state"]["state"] == "engaged"


def test_closed_loop_pain_risk_keeps_robot_stopped_and_handoff_active() -> None:
    result = run_closed_loop_scenario(load_scenario(SCENARIO_DIR / "pain_risk_safety.json"))

    assert result["metrics"]["safety_violation_count"] == 0
    assert result["metrics"]["risk_containment_count"] >= 1
    assert result["metrics"]["handoff_latency_steps"] == 0
    assert result["steps"][1]["robot_action"]["motion_policy"] == "stop_motion"
    assert result["steps"][2]["robot_context"]["is_robot_moving"] is False
    assert result["steps"][2]["robot_action"]["handoff_required"] is True


def test_closed_loop_aggregate_metrics_include_embodied_effects() -> None:
    results = [
        run_closed_loop_scenario(load_scenario(SCENARIO_DIR / "shape_sorting_confused.json")),
        run_closed_loop_scenario(load_scenario(SCENARIO_DIR / "pain_risk_safety.json")),
    ]
    aggregate = aggregate_closed_loop_results(results)

    assert aggregate["scenario_count"] == 2
    assert aggregate["step_count"] == 6
    assert aggregate["recovery_count"] >= 1
    assert aggregate["risk_containment_count"] >= 1
    assert aggregate["safety_violation_count"] == 0
