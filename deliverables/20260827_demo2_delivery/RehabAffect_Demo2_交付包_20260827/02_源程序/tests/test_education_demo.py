from src.rehab_affect.education_demo import (
    list_education_clips,
    render_education_demo_html,
    run_education_demo_json,
)


def test_education_demo_lists_review_ready_clips() -> None:
    clips = list_education_clips()

    assert len(clips) >= 3
    assert any(clip["clip_id"] == "bag_instruction_attention" for clip in clips)
    assert all("target_problem" in clip for clip in clips)


def test_education_demo_runs_multimodal_timeline() -> None:
    report = run_education_demo_json("bag_instruction_attention")

    assert report["demo_name"] == "辅读学校 AI 助教课堂状态 Demo"
    assert len(report["timeline"]) >= 4
    first_event = report["timeline"][0]
    assert "video_head_1_person_state" in first_event["recognition_heads"]
    assert "video_head_2_scene_activity" in first_event["recognition_heads"]
    assert "speech_head" in first_event["recognition_heads"]
    assert report["final_output"]["human_state"]["person_id"] == "student_A"
    assert report["final_output"]["robot_action"]["action_id"]
    assert report["final_output"]["robot_execution"]["speech"]["text"]
    assert report["final_output"]["robot_execution"]["integration"]["ros2_topic"] == "/ai_tutor/robot_action"


def test_education_demo_exposes_person_store_and_guidance() -> None:
    report = run_education_demo_json("noisy_classroom_speech_uncertain")

    store = report["per_person_store"]["student_C"]
    assert store["risk_events"]
    assert "语音置信度偏低" in report["timeline"][1]["likely_reasons"][0]
    assert report["review_boundary"]["speech_caveat"]
    assert "future_robot_embodiment" in report["timeline"][1]["robot_action"]
    assert report["timeline"][1]["robot_execution"]["safety"]["low_stimulation"] is True


def test_education_demo_html_exposes_review_page() -> None:
    html = render_education_demo_html()

    assert "辅读学校 AI 助教 Demo" in html
    assert "视频识别头 1" in html
    assert "视频识别头 2" in html
    assert "语音识别头" in html
    assert "/api/education_demo" in html
    assert "robot_action" in html
    assert "机器人执行层预览" in html
    assert "robot_executor" in html
