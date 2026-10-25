from pathlib import Path

from src.rehab_affect.scenario_lab_server import (
    build_edited_step,
    list_scenarios,
    load_scenario_by_id,
    mujoco_assets_for_scenario,
    process_closed_loop_scenario,
    process_edited_step,
)
from src.rehab_affect.showcase import render_showcase_html


SCENARIO_DIR = Path(__file__).resolve().parents[1] / "configs" / "scenarios"


def test_scenario_lab_lists_and_loads_scenarios() -> None:
    scenarios = list_scenarios(SCENARIO_DIR)

    assert len(scenarios) >= 6
    assert any(item["scenario_id"] == "shape_sorting_confused" for item in scenarios)
    loaded = load_scenario_by_id("shape_sorting_confused", SCENARIO_DIR)
    assert loaded["scenario_id"] == "shape_sorting_confused"


def test_scenario_lab_processes_edited_pain_risk_step() -> None:
    scenario = load_scenario_by_id("shape_sorting_confused", SCENARIO_DIR)
    edited = build_edited_step(
        scenario["steps"][0],
        {
            "expected_action_id": "stop_and_check_pain_risk",
            "observable_cues": {
                "speech_text": "这里疼，不舒服",
                "face_state_hint": "pain_risk",
                "attention_score": 0.32,
                "movement_speed": 0.03,
                "pain_guarding": True,
            },
            "robot_context": {
                "robot_distance_m": 0.75,
                "obstacle_distance_m": 1.0,
                "is_robot_moving": True,
            },
        },
    )

    result = process_edited_step(edited, policy_name="rule")

    assert result["human_state"]["state"] == "pain_risk"
    assert result["robot_action"]["action_id"] == "stop_and_check_pain_risk"
    assert result["robot_action"]["motion_policy"] == "stop_motion"


def test_scenario_lab_runs_closed_loop_scenario() -> None:
    scenario = load_scenario_by_id("shape_sorting_confused", SCENARIO_DIR)

    result = process_closed_loop_scenario(scenario, policy_name="rule")

    assert result["closed_loop"] is True
    assert result["metrics"]["recovery_count"] >= 1
    assert result["steps"][1]["embodied_feedback"]["outcome"] == "instruction_clarified"


def test_showcase_html_exposes_full_classroom_loop() -> None:
    html = render_showcase_html()

    assert "辅读学校具身智能课堂 Demo" in html
    assert "学生端" in html
    assert "教师端" in html
    assert "MuJoCo 实渲染" in html
    assert "robot_action" in html
    assert "/api/mujoco_assets" in html
    assert "/api/process_step" in html
    assert "/api/run_closed_loop" in html


def test_mujoco_assets_for_scenario_uses_static_asset_urls() -> None:
    assets = mujoco_assets_for_scenario("shape_sorting_confused")

    assert assets["scenario_id"] == "shape_sorting_confused"
    assert assets["contact_sheet"]["url"].endswith("shape_sorting_confused_contact_sheet.png")
    assert all(item["url"].startswith("/assets/mujoco_frames/") for item in assets["frames"])
