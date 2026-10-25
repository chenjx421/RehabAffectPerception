from src.rehab_affect.seewo_student_demo import _build_teacher_effectiveness


def test_teacher_effectiveness_scores_from_student_response_and_lesson_context() -> None:
    timeline = [
        {"state": "engaged"},
        {"state": "low_attention"},
        {"state": "engaged"},
        {"state": "confused_or_stuck"},
        {"state": "low_attention"},
        {"state": "uncertain_adult_interference"},
        {"state": "engaged"},
        {"state": "engaged"},
    ]
    summary = {
        "window_count": len(timeline),
        "state_counts": {
            "engaged": 4,
            "low_attention": 2,
            "confused_or_stuck": 1,
            "uncertain_adult_interference": 1,
        },
        "state_ratio": {"engaged": 0.5},
    }
    report = {
        "lecture_metrics": {
            "课程时长": "40分钟",
            "讲授时长": "16分0秒",
            "平均语速": "3.6字/秒",
        },
        "question_metrics": {
            "等候5秒以上": "100%",
            "理解型": "40%",
            "应用型": "30%",
            "分析型": "10%",
            "创造型": "0%",
        },
    }
    support_profile = {
        "diagnosis_context": {"iep_primary_disability_category": "自闭症"},
        "classroom_support_implications": {"prefer_visual_step_prompt": True},
    }

    result = _build_teacher_effectiveness(timeline, summary, report, support_profile)

    assert 0 <= result["overall_score"] <= 100
    assert result["boundary"].startswith("该评分只评估本节课")
    assert {metric["key"] for metric in result["metrics"]} == {
        "student_engagement",
        "recovery_after_challenge",
        "pace_and_scaffold",
        "low_disruption_support",
        "individualized_fit",
    }
    recovery = next(metric for metric in result["metrics"] if metric["key"] == "recovery_after_challenge")
    assert recovery["score"] == 67
    rhythm = next(metric for metric in result["metrics"] if metric["key"] == "pace_and_scaffold")
    assert rhythm["score"] >= 85
