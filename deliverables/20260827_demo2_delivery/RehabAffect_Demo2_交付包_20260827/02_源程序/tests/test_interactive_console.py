from pathlib import Path

import pytest

from src.rehab_affect.interactive_console import build_console_payload, export_console
from src.rehab_affect.train_policy import train_and_evaluate


pytest.importorskip("sklearn")

SCENARIO_DIR = Path(__file__).resolve().parents[1] / "configs" / "scenarios"


def test_interactive_console_exports_html(tmp_path: Path) -> None:
    model_path = tmp_path / "learned_school_policy.pkl"
    train_and_evaluate(
        scenario_dir=SCENARIO_DIR,
        output=model_path,
        metrics_output=tmp_path / "metrics.json",
        benchmark_backend="kinematic",
    )

    payload = build_console_payload(
        scenario_dir=SCENARIO_DIR,
        backend="kinematic",
        policy="learned",
        model_path=model_path,
        compare_backend="kinematic",
    )
    output = tmp_path / "console.html"
    export_console(payload, output)

    html = output.read_text(encoding="utf-8")
    assert "辅读学校辅助机器人交互式 Benchmark 控制台" in html
    assert "policy_comparison" in html
    assert "perception_decision" in html
