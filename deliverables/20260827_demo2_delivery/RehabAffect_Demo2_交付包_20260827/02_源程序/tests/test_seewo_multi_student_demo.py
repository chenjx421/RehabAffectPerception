from __future__ import annotations

from pathlib import Path

import pytest

from rehab_affect.seewo_multi_student_demo import (
    ANALYSIS_PATH,
    CONFIG_PATH,
    OUTPUT_DIR,
    load_seewo_demo2,
    render_seewo_demo2_html,
)
from rehab_affect.seewo_long_report import build_long_course_report, report_writer_status


def _local_payload() -> dict:
    if not CONFIG_PATH.exists() or not ANALYSIS_PATH.exists():
        pytest.skip("Demo2 local authorized data is not installed")
    return load_seewo_demo2()


def test_demo2_covers_three_students_and_two_courses() -> None:
    payload = _local_payload()

    assert len(payload["students"]) == 3
    assert len(payload["courses"]) == 2
    assert {student["display_name"] for student in payload["students"]} == {
        "Student A",
        "Student B",
        "Student C",
    }
    for course in payload["courses"]:
        assert len(course["course_fit"]["students"]) == 3
        assert len(course["student_results"]) == 3
        assert course["lesson_standard"]
        assert course["school_assessment_standard"]
        assert len(course["teacher_effectiveness"]["metrics"]) == 5
        assert course["report_summary"]["available"] is True
        assert course["data_source"]["student_video"]
        assert 900 <= course["course_analysis"]["char_count"] <= 1300
        assert course["course_analysis"]["scope"] == "一节课 / 一个学校 / 三名重点学生"
        assert "不构成医学诊断" in course["course_analysis"]["boundary"]
        assert len(course["teacher_review_spec"]["required_fields"]) == 6
        assert any(
            metric["key"] == "teacher_student_contingency"
            for metric in course["teacher_effectiveness"]["metrics"]
        )


def test_demo2_results_keep_mastery_participation_and_unknown_separate() -> None:
    payload = _local_payload()

    for course in payload["courses"]:
        for result in course["student_results"]:
            mastery = result["mastery"]
            assert 0 <= mastery["overall_score"] <= 100
            assert set(mastery["dimensions"]) == {
                "accuracy",
                "independence",
                "consistency",
                "transfer",
            }
            assert 0 <= result["state_summary"]["participation_score"] <= 100
            assert all("unobserved" in objective for objective in mastery["objectives"])
            assert result["robot_action"]["motion"]
            assert isinstance(result["robot_action"]["teacher_confirmation_required"], bool)
            assert result["student_tracking"]["growth_indicators"]
            assert len(result["growth_projection"]["domains"]) == 5
            assert result["growth_projection"]["evidence_grade"].startswith("C级")
            assert result["special_education_support"]["teacher_controlled"] is True
            assert "实物操作" in result["special_education_support"]["response_channels"]
            assert result["state_timeline"]
            state_window = result["state_timeline"][0]
            assert state_window["recommended_action"]["action_id"]
            assert state_window["human_state_json"]["person_id"] == result["student_id"]
            assert set(state_window["human_state_json"]) == {
                "timestamp_sec",
                "person_id",
                "state",
                "confidence",
                "evidence",
                "risk_level",
                "handoff_required",
                "recommended_robot_action",
            }


def test_demo2_feedback_and_review_assets_are_delivery_ready() -> None:
    payload = _local_payload()

    for course in payload["courses"]:
        group_asset = OUTPUT_DIR / course["assets"]["group_image_url"].split("/assets/seewo_demo2/", 1)[1]
        assert group_asset.is_file()
        for result in course["student_results"]:
            assert 900 <= result["feedback_char_count"] <= 1400
            portrait_asset = OUTPUT_DIR / result["portrait_url"].split("/assets/seewo_demo2/", 1)[1]
            assert portrait_asset.is_file()
            assert result["key_interactions"]
            assert all(interaction["clip_id"] for interaction in result["key_interactions"])
            assert all("review_reason" in interaction for interaction in result["key_interactions"])
            assert all("interaction_chain" in interaction for interaction in result["key_interactions"])


def test_demo2_html_exposes_school_workflow() -> None:
    _local_payload()
    html = render_seewo_demo2_html()

    for text in (
        "课程与评价依据",
        "校方考核标准",
        "三人同步课堂证据",
        "学习判断",
        "状态时间线",
        "动作方案",
        "历史记录",
        "支持效果",
        "一人一案",
        "数据来源",
        "约一千字综合报告",
        "结构化 JSON",
        "课程分析",
        "支持工具",
        "师生互动",
        "五域趋势",
        "未观察到有效作答机会",
        "导出整课复核清单 CSV",
        "开始6秒等待",
        "复制单步支持卡",
        "资料导入",
        "四路上传",
        "数据存储",
        "教师确认并保存",
        "四路视频上传与独立分析",
        "数据存储与保存周期",
        "数据安全与上传授权",
        "到期前 15 天提醒",
        "公司长期资源库",
    ):
        assert text in html
    assert "群像" in html and "人像" in html
    assert "返回 Demo1" in html
    assert "第 1/8 步" in html
    assert "学校希望学生学会什么" in html
    assert "一人一案证据页" in html
    assert "保存本片段复核" in html
    assert "定位到完整时间线核对" in html
    assert "/api/seewo_demo2_long_report" in html
    assert "/api/seewo_demo2/student_document" in html
    assert "/api/seewo_demo2/video_chunk" in html
    assert "/api/seewo_demo2/storage_policy" in html
    assert "/api/seewo_demo2/security_acceptance" in html
    assert "/api/seewo_demo2/archive_video_result" in html


def test_demo2_html_keeps_the_product_ui_contract() -> None:
    _local_payload()
    html = render_seewo_demo2_html()

    assert html.count('data-tab="') == 17
    assert html.count('data-icon="') == 17
    assert html.count('<details class="evidence review-clip"') >= 1
    assert 'role="tablist"' in html
    assert 'role="tabpanel"' in html
    assert 'role="progressbar"' in html
    assert "aria-selected" in html
    assert "aria-pressed" in html
    assert "ROBOT_MOTION_LABELS" in html
    assert ".tab-body > pre" in html and "max-height:700px" in html
    assert "打印 / 导出 PDF" in html
    assert "@media print" in html
    assert "@media (max-width:1120px)" in html
    assert "@media (max-width:860px)" in html
    assert "@media (max-width:600px)" in html
    assert html.count("<svg") >= 4
    for emoji in ("✅", "⚠", "📄", "📊", "👤", "🤖", "🧠", "🎯", "💡"):
        assert emoji not in html


def test_demo2_builds_ten_thousand_character_evidence_report() -> None:
    payload = _local_payload()
    course = payload["courses"][0]
    reviews = {
        f"{course['course_id']}:{course['student_results'][0]['student_id']}:0": {
            "verdict": "符合",
            "correctness": "正确",
            "prompt_level": "简单提示",
            "note": "教师确认该片段为明确作答机会。",
        }
    }
    report = build_long_course_report(
        payload,
        course["course_id"],
        course_context={
            "course_type": course["subject"],
            "course_name": course["course_name"],
            "lesson_standard": course["lesson_standard"],
            "school_assessment_standard": course["school_assessment_standard"],
            "lesson_plan_requirement": "按学校教案确认任务机会和提示等级。",
            "confirmed_by": "测试教师",
        },
        reviews=reviews,
    )

    assert 850 <= report["char_count"] <= 1500
    assert report["engine"] == "evidence_template"
    assert report["review_summary"]["reviewed"] == 1
    assert len(report["sections"]) >= 5
    assert "机器人动作" in report["full_text"]
    assert "不构成医学诊断" in report["boundary"]


def test_demo2_report_writer_defaults_to_offline_template() -> None:
    status = report_writer_status()
    assert status["default_engine"] == "evidence_template"
    assert "evidence_template" in status["supported_engines"]


def test_demo2_llm_request_falls_back_when_not_configured(monkeypatch) -> None:
    monkeypatch.delenv("REHAB_REPORT_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("REHAB_REPORT_LLM_MODEL", raising=False)
    payload = _local_payload()
    course = payload["courses"][0]
    report = build_long_course_report(payload, course["course_id"], use_llm=True)

    assert report["engine"] == "evidence_template"
    assert "回退" in report["engine_note"]


def test_demo2_cache_is_private_output() -> None:
    _local_payload()
    assert Path(ANALYSIS_PATH).is_file()
    assert "outputs" in ANALYSIS_PATH.parts
