import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

from src.rehab_affect.seewo_student_demo import (
    load_seewo_student_demo,
    render_seewo_student_demo_html,
)


data = load_seewo_student_demo()
assert data.get("ui_version") == "student_support_v4"
assert len(data.get("timeline", [])) == 77
assert data.get("teacher_effectiveness", {}).get("overall_score") == 71
assert data.get("target_student", {}).get("student_id") == "student_A"
assert (root / "outputs/seewo_xiaoyudi_demo/frames/target_roi_reference.jpg").exists()
html = render_seewo_student_demo_html()
assert "学生个体状态追踪与课堂支持 Demo" in html
assert "教师支持效果评估" in html
print("PASS: cached analysis, assets, HTML rendering and teacher-effectiveness data are ready.")
