"""The downloadable PDFs keep the designed layout and stay valid documents."""

from rehab_affect import demo2_report_pdf as pdf


def _person():
    return {
        "person_id": "person_01",
        "display_name": "人物 1",
        "dominant_state_zh": "参与",
        "average_student_score": 6.5,
        "state_summary": {"counts": {"engaged": 20, "low_attention": 0, "confused_or_stuck": 0,
                                     "uncertain_adult_interference": 1, "uncertain": 0},
                          "review_required": 1},
        "windows": [{"start_sec": 0, "end_sec": 30}] * 21,
        "lesson_report": {"text": "一、整体情况。\n二、参与情况。\n三、安静下来的时段。"},
        "key_moments": [{"start_sec": 210, "end_sec": 240, "state_zh": "成人干扰下不确定", "reason": "被旁边人挡住"}],
    }


def _evaluation():
    return {
        "reviewed": True,
        "lesson_date": "2026-10-27",
        "result": {
            "school": {"score_10": 8.0}, "enhanced": {"score_10": 8.1},
            "comparison": {"total_delta": 0.1, "evidence_delta": 0.1, "weight_delta": 0.0,
                           "items": [{"id": "i7", "label": "师生互动", "school_score": 7,
                                      "enhanced_score": 8, "total_delta": 0.1}]},
            "categories": [{"label": "目标适配与分层要求", "school_score": 8.0,
                            "enhanced_score": 8.0, "school_weight": 0.2}],
        },
    }


def test_student_pdf_is_a_designed_pdf():
    data = pdf.student_pdf({"persons": [_person()]}, _person(),
                           {"student_name": "薛艺靖"}, _evaluation())
    assert data.startswith(b"%PDF-")
    assert len(data) > 4000


def test_class_pdf_renders_dual_track_and_references():
    refs = {"items": [{"title": "培智学校义务教育课程标准", "issuer": "教育部", "year": "2016",
                       "scope": "课程目标", "note": "依据", "url": "https://example.org"}],
            "note": "参考资料只说明口径来源。"}
    data = pdf.class_pdf({"task_id": "t1", "course_name": "室外活动示例课"}, _evaluation(), refs)
    assert data.startswith(b"%PDF-")
    assert len(data) > 4000
