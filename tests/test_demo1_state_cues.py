"""Demo1 state cues: five classroom states, per-window advice, no robot action."""

import json

import pytest

from rehab_affect import demo2_student_tracking as tracking


def cue(activity, *, adult=0.1, audio=0.1, visibility=1.0, quality=0.8, expected=10,
        motions=None, previous=None):
    return tracking._student_state(
        activity, audio, adult, visibility, quality,
        motions if motions is not None else [activity] * expected, expected,
        lesson_phase="引导练习", previous_activity=previous,
    )


def test_engaged_state_when_sustained_movement():
    state, label, evidence, interpretation, confidence = cue(.62)
    assert state == "engaged" and label == "参与"
    assert "参与线索" in evidence and confidence >= .6


def test_adult_interference_defers_to_teacher():
    state, label, *_ = cue(.10, adult=.8)
    assert state == "uncertain_adult_interference" and label == "成人干扰下不确定"


def test_quiet_after_activity_with_classroom_sound_is_confused_or_stuck():
    state, label, evidence, interpretation, _ = cue(.10, adult=.2, audio=.6, previous=.5)
    assert state == "confused_or_stuck" and label == "困惑·停滞"
    assert "声音" in evidence and "提示" in interpretation


def test_quiet_after_quiet_is_low_attention_not_confused():
    state, *_ = cue(.10, adult=.2, audio=.6, previous=.05)
    assert state == "low_attention"


def test_quiet_seat_without_sound_is_low_attention():
    state, label, *_ = cue(.16, adult=.2, audio=.1)
    assert state == "low_attention" and label == "注意力下降"


def test_engagement_wins_over_interference_when_student_is_active():
    state, *_ = cue(.5, adult=.9, audio=.1)
    assert state == "engaged"


def test_insufficient_visibility_is_uncertain():
    state, label, *_ = cue(.6, visibility=.1)
    assert state == "uncertain" and label == "无法判断"


def test_low_quality_lowers_confidence_without_changing_state():
    _, _, evidence, _, low_confidence = cue(.62, quality=.4)
    _, _, _, _, high_confidence = cue(.62, quality=.9)
    assert "清晰度偏低" in evidence and low_confidence < high_confidence


@pytest.mark.parametrize("state", list(tracking.STUDENT_STATE_LABELS))
def test_every_state_has_advice_without_robot_motion(state):
    action = tracking.STUDENT_STATE_ACTIONS[state]
    assert action["action_id"] and action["screen"] and action["speech"]
    assert "robot_motion" not in action
    assert isinstance(action["teacher_alert"], bool)


def test_key_moments_prioritise_review_cues_and_stay_ordered():
    windows = [
        dict(start_sec=30, end_sec=60, state="engaged", state_zh="参与", interpretation="继续观察"),
        dict(start_sec=60, end_sec=90, state="confused_or_stuck", state_zh="困惑·停滞", interpretation="重复一步"),
        dict(start_sec=90, end_sec=120, state="low_attention", state_zh="注意力下降", interpretation="低刺激提示"),
        dict(start_sec=120, end_sec=150, state="uncertain_adult_interference", state_zh="成人干扰下不确定", interpretation="教师确认"),
        dict(start_sec=150, end_sec=180, state="engaged", state_zh="参与", interpretation="继续观察"),
        dict(start_sec=180, end_sec=210, state="engaged", state_zh="参与", interpretation="继续观察"),
        dict(start_sec=210, end_sec=240, state="engaged", state_zh="参与", interpretation="继续观察"),
    ]
    moments = tracking._select_key_moments(windows)
    assert len(moments) == 6
    assert [item["start_sec"] for item in moments] == sorted(item["start_sec"] for item in moments)
    picked = {item["start_sec"] for item in moments}
    assert {60, 90, 120} <= picked
    assert 210 not in picked
    assert {item["state"] for item in moments} >= {
        "confused_or_stuck", "low_attention", "uncertain_adult_interference"}


def _person_with_mixed_windows():
    windows = [
        dict(start_sec=0, end_sec=30, state='engaged', state_zh='参与', motion_signal=.6,
             audio_activity=.1, adult_interference=.1, interpretation='x',
             recommended_action=dict(teacher_alert=False)),
        dict(start_sec=30, end_sec=60, state='low_attention', state_zh='注意力下降', motion_signal=.1,
             audio_activity=.6, adult_interference=.2, interpretation='y',
             recommended_action=dict(teacher_alert=False)),
        dict(start_sec=60, end_sec=90, state='confused_or_stuck', state_zh='困惑·停滞', motion_signal=.1,
             audio_activity=.1, adult_interference=.7, interpretation='z',
             recommended_action=dict(teacher_alert=True)),
    ]
    return dict(display_name='人物 1', windows=windows,
                state_summary={'counts': {'engaged': 1, 'low_attention': 1, 'confused_or_stuck': 1,
                                          'uncertain_adult_interference': 0, 'uncertain': 0},
                               'review_required': 1, 'window_count': 3})


def test_classroom_rhythm_counts_talk_wait_and_support():
    rhythm = tracking._classroom_rhythm([_person_with_mixed_windows()], 90)
    assert rhythm['window_count'] == 3
    assert rhythm['teacher_talk_seconds'] == 30.0
    assert rhythm['question_wait_events'] == 1
    assert rhythm['individual_support_seconds'] == 30.0
    assert 0 < rhythm['teacher_talk_ratio'] <= 1
    assert '30秒' in rhythm['note']


def test_support_conclusions_are_three_items_with_next_lesson():
    person = _person_with_mixed_windows()
    rhythm = tracking._classroom_rhythm([person], 90)
    support = tracking._support_conclusions([person], rhythm)
    assert len(support['conclusions']) == 3
    assert [item['title'] for item in support['conclusions']] == ['本课状态分布', '优先复核', '课堂节奏']
    assert 1 <= len(support['next_lesson']) <= 3
    assert all('机器人' not in item['action'] for item in support['next_lesson'])
    assert support['profile']['attached'] is False and 'IEP' in support['profile']['note']
    assert '人物 1' in support['conclusions'][1]['text']
