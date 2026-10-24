from pathlib import Path

from src.rehab_affect.sim_runner import load_scenario, run_scenario


SCENARIO_DIR = Path(__file__).resolve().parents[1] / "configs" / "scenarios"


def test_pain_risk_scenario_has_zero_safety_violations_and_immediate_handoff() -> None:
    result = run_scenario(load_scenario(SCENARIO_DIR / "pain_risk_safety.json"))

    assert result["metrics"]["action_match_accuracy"] == 1.0
    assert result["metrics"]["safety_violation_count"] == 0
    assert result["metrics"]["handoff_latency_steps"] == 0
    assert result["steps"][1]["robot_action"]["motion_policy"] == "stop_motion"
    assert result["steps"][1]["robot_action"]["safety_action"] == "alert_teacher_or_caregiver"


def test_low_attention_obstacle_scenario_stops_robot_motion() -> None:
    result = run_scenario(load_scenario(SCENARIO_DIR / "low_attention_obstacle.json"))

    low_attention_step = result["steps"][1]
    assert low_attention_step["human_state"]["state"] == "low_attention"
    assert low_attention_step["robot_action"]["action_id"] == "regain_attention"
    assert low_attention_step["robot_action"]["motion_policy"] == "stop_motion"
    assert low_attention_step["post_action_context"]["is_robot_moving"] is False
