from pathlib import Path

from src.rehab_affect.demo_launcher import (
    build_demo_index_payload,
    export_demo_index,
    render_demo_index_html,
)


def test_demo_launcher_exports_index_from_manifest(tmp_path: Path) -> None:
    screenshot = tmp_path / "scenario_lab.png"
    screenshot.write_bytes(b"fake image")
    manifest_path = tmp_path / "manifest.json"
    manifest = {
        "release": "test_release",
        "project": "RehabAffectPerception",
        "training": {"row_count": 12, "holdout_action_accuracy": 0.9},
        "benchmark": {"action_match_accuracy": 1.0, "safety_violation_count": 0},
        "closed_loop": {
            "action_match_accuracy": 0.95,
            "recovery_count": 2,
            "safety_violation_count": 0,
        },
        "artifacts": {
            "scenario_lab_screenshot": str(screenshot),
            "closed_loop_report": str(tmp_path / "closed_loop.html"),
        },
    }
    manifest_path.write_text(__import__("json").dumps(manifest), encoding="utf-8")

    result = export_demo_index(output=tmp_path / "index.html", manifest_path=manifest_path)

    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert result["artifact_count"] >= 1
    assert "RehabAffectPerception Demo Index" in html
    assert "Closed-loop Scenario Lab" in html
    assert "闭环动作命中" in html
    assert "scenario_lab.png" in html


def test_demo_index_payload_and_html_have_live_links() -> None:
    payload = build_demo_index_payload(
        manifest={
            "project": "RehabAffectPerception",
            "release": "unit",
            "artifacts": {},
        },
        scenario_lab_url="http://127.0.0.1:8787",
    )
    html = render_demo_index_html(payload)

    assert "http://127.0.0.1:8787/showcase" in html
    assert "http://127.0.0.1:8787?preset=pain" in html
    assert "scenario=shape_sorting_confused&amp;loop=1" in html
