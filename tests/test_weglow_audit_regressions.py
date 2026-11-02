"""Regression tests for the two audit fixes (run with PYTHONPATH=src)."""
from io import BytesIO

from docx import Document

from rehab_affect import demo2_document_parser
from rehab_affect import demo2_report_render as render


def _docx_text(data: bytes) -> str:
    doc = Document(BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                text += "\n" + cell.text
    return text


def test_classroom_report_missing_steps_are_human_text():
    payload = {
        "report": {
            "course_overview": {
                "course_name": "测试课",
                "conclusion": {
                    "available": False,
                    "missing": [
                        {"code": "students_missing", "text": "本课还没有纳入检测的学生"},
                        {"code": "course_evaluation_missing", "text": "本课还没有课程评价"},
                    ],
                },
            }
        },
        "school_context": {"school_name": "测试学校", "city": "上海市", "district": "浦东新区"},
    }
    model = render.classroom_report_model(payload, {"report_id": "r1", "generated_at": "2026-11-02T10:00:00+08:00"},
                                          admin=False)
    data, _ = render.render_docx(model)
    text = _docx_text(data)
    assert "('code'" not in text
    assert "本课还没有纳入检测的学生" in text
    assert "本课还没有课程评价" in text


def test_course_task_table_header_is_not_a_goal():
    doc = Document()
    doc.add_paragraph("一、教学目标")
    doc.add_paragraph("1. 能指认苹果、香蕉。")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "目标"
    table.cell(0, 1).text = "支持方式"
    table.cell(1, 0).text = "指认苹果香蕉"
    table.cell(1, 1).text = "实物提示"
    buffer = BytesIO(); doc.save(buffer)
    parsed = demo2_document_parser.parse_document("course_task", "docx", buffer.getvalue())
    goal_values = [c.get("value") for c in parsed["candidates"] if c.get("field") == "course_goals"]
    assert "支持方式" not in goal_values
    assert any("指认" in (value or "") for value in goal_values)


def test_unmeasured_goal_is_todo_not_a_weakness():
    from rehab_affect.demo2_course_overview import build_overview

    work = {
        "task_id": "t",
        "course_task": {"goals": [{"goal_code": "G-01", "description": "A"},
                                  {"goal_code": "G-02", "description": "B"}]},
        "applicability": {"confirmed_for_source": True},
        "people": [{"student_id": "s1", "display_name": "学生1"}],
        "records": [{"record_id": "r1", "student_id": "s1", "goal_id": "G-01", "reviewed": True,
                     "evidence_status": "current", "assessment": {"overall_score": 8.0},
                     "lesson_date": "2026-11-02"}],
    }
    evaluation = {"template_id": "basic_100", "task_id": "t", "reviewed": True, "version": 1,
                  "result": {"status": "reviewed", "school": {"raw_score": 80.0, "score_10": 8.0},
                             "categories": [], "items": []}}
    overview = build_overview(work, [evaluation])
    labels = {g["goal_code"]: g["label"] for g in overview["indicators"]["goals"]}
    assert labels["G-02"] == "暂无已复核测量"
    assert not any("G-02" in item["text"] for item in overview["conclusion"]["improvements"])


def test_similar_numbered_goals_are_not_merged():
    from io import BytesIO

    from docx import Document
    from rehab_affect import demo2_document_parser

    doc = Document()
    doc.add_paragraph("一、教学目标")
    for number in range(1, 6):
        doc.add_paragraph(f"{number}. 能在提示下完成第{number}项任务。")
    buffer = BytesIO(); doc.save(buffer)
    parsed = demo2_document_parser.parse_document("course_task", "docx", buffer.getvalue())
    assert len(parsed["goals"]) == 5
