"""Fresh-process acceptance; deliberately never imports a live store singleton."""
import json
from pathlib import Path
import subprocess
import sys


def test_four_first_use_schools_real_media_named_binding_reload_report():
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-X", "utf8", str(repo / "scripts/verify_first_use_isolated_20261016.py")],
                            cwd=repo, capture_output=True, text=True, encoding="utf-8", timeout=200)
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    assert summary["status"] == "passed"
    assert len(summary["schools"]) == 4
    assert len({row["school"] for row in summary["schools"]}) == 4
    assert summary["live_instance_accessed"] is False
    root = Path(summary["isolated_root"])
    assert all(Path(summary[key]).is_relative_to(root) for key in ("database", "upload_dir", "video_dir"))
    assert all(row["real_media_decode"] and row["identity_report_verified"] for row in summary["schools"])
    for row in summary["schools"]:
        reports = row["teacher_reports"]
        assert reports["task_student_source_verified"] and reports["teacher_course_report_verified"]
        assert reports["applicability_gate_verified"] and reports["manual_evaluation_reloaded"]
        assert reports["measurement_score"] == 6.85
        assert reports["incomplete_measurement_score"] is None
        assert reports["incomplete_evaluation_score"] is None
        assert reports["evaluation_structured_task_student_binding"] is False
    assert "not automatic assessment" in summary["assessment_limitation"]
    assert "no task_id/student_id" in summary["evaluation_provenance_gap"]
    print("Acceptance evidence:", root / "acceptance-summary.json")
    print("Browser:", summary["browser"])
