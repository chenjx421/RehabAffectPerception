from pathlib import Path

import pytest

from src.rehab_affect.precloud_release import run_precloud_release


pytest.importorskip("sklearn")

SCENARIO_DIR = Path(__file__).resolve().parents[1] / "configs" / "scenarios"


def test_precloud_release_builds_manifest_and_report(tmp_path: Path) -> None:
    model_path = tmp_path / "learned_school_policy.pkl"
    manifest_path = tmp_path / "manifest.json"
    report_path = tmp_path / "final_report.md"

    manifest = run_precloud_release(
        scenario_dir=SCENARIO_DIR,
        model_path=model_path,
        release_manifest_path=manifest_path,
        final_report_path=report_path,
        benchmark_backend="kinematic",
        compare_backend="kinematic",
        train_augmentations_per_scenario=1,
        compare_augmentations_per_scenario=1,
        robustness_augmentations_per_scenario=1,
        robustness_seeds=[7],
        processed_dir=tmp_path / "processed",
        demo_html_path=tmp_path / "demo.html",
        console_html_path=tmp_path / "console.html",
    )

    assert manifest_path.exists()
    assert report_path.exists()
    assert model_path.exists()
    assert (tmp_path / "demo.html").exists()
    assert (tmp_path / "console.html").exists()
    assert manifest["release"] == "precloud_local_final"
    assert manifest["benchmark"]["safety_violation_count"] == 0
    assert manifest["robustness"]["learned_shielded"]["pass_safety_gate"] is True
