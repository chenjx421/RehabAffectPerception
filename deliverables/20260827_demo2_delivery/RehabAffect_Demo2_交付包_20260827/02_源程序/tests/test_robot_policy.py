from src.rehab_affect.policy import RuleRobotPolicy
from src.rehab_affect.schema import HumanState, RobotContext


def _human_state(state: str, confidence: float = 0.9) -> HumanState:
    return HumanState(
        person_id="user_test",
        state=state,
        confidence=confidence,
        valence=-0.5,
        arousal=0.7,
        evidence=["voice"],
        recommended_robot_action="unused_by_policy_test",
        risk_level="high" if state in {"pain_risk", "needs_help"} else "medium",
        handoff_required=state in {"pain_risk", "needs_help"},
        timestamp=123.0,
    )


def test_pain_risk_maps_to_robot_stop_and_handoff() -> None:
    action = RuleRobotPolicy().decide(_human_state("pain_risk"))

    assert action.action_id == "stop_and_check_pain_risk"
    assert action.motion_policy == "stop_motion"
    assert action.task_adjustment == "pause_task"
    assert action.safety_action == "alert_teacher_or_caregiver"
    assert action.handoff_required is True


def test_low_attention_stops_motion_when_robot_is_moving() -> None:
    action = RuleRobotPolicy().decide(
        _human_state("low_attention", confidence=0.7),
        RobotContext(is_robot_moving=True),
    )

    assert action.action_id == "regain_attention"
    assert action.motion_policy == "stop_motion"
    assert action.safety_action == "confirm_attention_before_motion"
