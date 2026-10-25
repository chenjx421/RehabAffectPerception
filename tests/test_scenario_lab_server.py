import gzip
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen

from src.rehab_affect import scenario_lab_server as scenario_server
from src.rehab_affect.scenario_lab_server import (
    DEFAULT_LEARNED_POLICY_PATH,
    build_edited_step,
    create_handler,
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


def test_scenario_lab_gzips_large_html_when_supported(monkeypatch) -> None:
    class AuthenticatedStore:
        @staticmethod
        def account_from_session(token: str) -> dict[str, str]:
            if token != "test-session":
                raise ValueError("invalid session")
            return {
                "account_id": "test-account",
                "username": "test-user",
                "role": "school_uploader",
            }

    monkeypatch.setattr(scenario_server, "get_demo2_student_store", lambda: AuthenticatedStore())
    synthetic_html = "<!doctype html><title>QA compression</title>" + "Synthetic text only. " * 4000
    monkeypatch.setattr(scenario_server, "render_education_demo_html", lambda: synthetic_html)
    handler = create_handler(
        scenario_dir=SCENARIO_DIR,
        model_path=DEFAULT_LEARNED_POLICY_PATH,
        policy_name="rule",
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = Request(
            f"http://127.0.0.1:{server.server_port}/education_demo",
            headers={
                "Accept-Encoding": "gzip",
                "Cookie": "rehab_demo2_session=test-session",
            },
        )
        with urlopen(request, timeout=10) as response:  # noqa: S310
            compressed = response.read()
            assert response.headers["Content-Encoding"] == "gzip"
            assert response.headers["Vary"] == "Accept-Encoding"
        html = gzip.decompress(compressed).decode("utf-8")
        assert html == synthetic_html
        assert len(compressed) < len(html.encode("utf-8")) / 3
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
