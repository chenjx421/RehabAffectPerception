from pathlib import Path

from src.rehab_affect.closed_loop_report import (
    build_closed_loop_payload,
    export_closed_loop_report,
    render_closed_loop_html,
)


SCENARIO_DIR = Path(__file__).resolve().parents[1] / "configs" / "scenarios"


def test_closed_loop_report_exports_json_and_html(tmp_path: Path) -> None:
    payload = build_closed_loop_payload(
        scenario_dir=SCENARIO_DIR,
        backend="kinematic",
        policy="rule",
    )
    json_output = tmp_path / "closed_loop.json"
    html_output = tmp_path / "closed_loop.html"

    export_closed_loop_report(payload, json_output=json_output, html_output=html_output)

    assert json_output.exists()
    assert html_output.exists()
    html = html_output.read_text(encoding="utf-8")
    assert "Closed-loop Embodied Benchmark" in html
    assert "human_state -> robot_action" in html
    assert "instruction_clarified" in html
    assert "risk_contained" in html


def test_closed_loop_html_contains_aggregate_metrics() -> None:
    payload = build_closed_loop_payload(
        scenario_dir=SCENARIO_DIR,
        backend="kinematic",
        policy="rule",
    )
    html = render_closed_loop_html(payload)

    assert "闭环分" in html
    assert "风险遏制" in html
    assert payload["aggregate_metrics"]["safety_violation_count"] == 0
