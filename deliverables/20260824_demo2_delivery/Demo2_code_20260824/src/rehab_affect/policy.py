from __future__ import annotations

from .schema import HumanState, RobotAction, RobotContext


ACTION_TEMPLATES: dict[str, dict[str, str]] = {
    "stop_and_check_pain_risk": {
        "speech_action": "ask_discomfort_and_reassure",
        "motion_policy": "stop_motion",
        "task_adjustment": "pause_task",
        "safety_action": "alert_teacher_or_caregiver",
        "priority": "critical",
        "reason": (
            "Pain-risk cues require immediate pause, confirmation, and teacher or "
            "caregiver handoff."
        ),
    },
    "offer_help": {
        "speech_action": "offer_help_and_confirm_need",
        "motion_policy": "hold_position",
        "task_adjustment": "pause_task",
        "safety_action": "notify_teacher_or_caregiver_if_unresolved",
        "priority": "high",
        "reason": "The student appears to need assistance beyond the current classroom task flow.",
    },
    "pause_and_request_consent": {
        "speech_action": "ask_consent_and_offer_choice",
        "motion_policy": "increase_personal_space",
        "task_adjustment": "pause_task",
        "safety_action": "respect_refusal",
        "priority": "high",
        "reason": "The robot should respect refusal and avoid pressuring the student.",
    },
    "reduce_task_load_and_offer_break": {
        "speech_action": "offer_break",
        "motion_policy": "slow_down",
        "task_adjustment": "reduce_task_load",
        "safety_action": "monitor_fatigue",
        "priority": "medium",
        "reason": (
            "Fatigue cues should reduce classroom task load before frustration or "
            "risk escalates."
        ),
    },
    "repeat_instruction_slowly": {
        "speech_action": "repeat_instruction_slowly",
        "motion_policy": "hold_position",
        "task_adjustment": "simplify_next_step",
        "safety_action": "avoid_new_motion_until_confirmed",
        "priority": "medium",
        "reason": "Confusion should trigger simpler instruction before continuing motion.",
    },
    "pause_and_reduce_pressure": {
        "speech_action": "acknowledge_and_encourage",
        "motion_policy": "hold_position",
        "task_adjustment": "reduce_pressure",
        "safety_action": "avoid_repeated_prompting",
        "priority": "medium",
        "reason": "Frustration cues should lower interaction pressure and avoid escalation.",
    },
    "regain_attention": {
        "speech_action": "regain_attention",
        "motion_policy": "slow_down",
        "task_adjustment": "simplify_next_step",
        "safety_action": "confirm_attention_before_motion",
        "priority": "medium",
        "reason": "Low attention should be resolved before the robot continues an embodied task.",
    },
    "continue_and_encourage": {
        "speech_action": "positive_feedback",
        "motion_policy": "continue_planned_motion",
        "task_adjustment": "maintain_or_slightly_progress",
        "safety_action": "monitor",
        "priority": "low",
        "reason": "The student is engaged, so the robot can continue while monitoring safety.",
    },
    "continue_current_plan": {
        "speech_action": "neutral_prompt",
        "motion_policy": "continue_cautiously",
        "task_adjustment": "maintain_current_difficulty",
        "safety_action": "monitor",
        "priority": "low",
        "reason": "No strong state cue is present, so the robot maintains the current plan.",
    },
}


def build_robot_action(
    human_state: HumanState,
    *,
    action_id: str,
    context: RobotContext | None = None,
    handoff_required: bool | None = None,
    reason: str | None = None,
    metadata: dict[str, object] | None = None,
) -> RobotAction:
    context = context or RobotContext()
    template = ACTION_TEMPLATES.get(action_id, ACTION_TEMPLATES["continue_current_plan"])
    motion_policy = template["motion_policy"]
    action_metadata = dict(metadata or {})

    if action_id == "regain_attention" and needs_motion_stop(context):
        motion_policy = "stop_motion"
        action_metadata["context_motion_stop"] = True

    if handoff_required is None:
        handoff_required = _default_handoff(human_state, action_id)

    return RobotAction(
        action_id=action_id if action_id in ACTION_TEMPLATES else "continue_current_plan",
        speech_action=template["speech_action"],
        motion_policy=motion_policy,
        task_adjustment=template["task_adjustment"],
        safety_action=template["safety_action"],
        priority=template["priority"],
        reason=reason or template["reason"],
        target_state=human_state.state,
        confidence=human_state.confidence,
        handoff_required=handoff_required,
        timestamp=human_state.timestamp,
        metadata=action_metadata,
    )


def needs_motion_stop(context: RobotContext) -> bool:
    if context.is_robot_moving:
        return True
    if context.obstacle_distance_m is not None and context.obstacle_distance_m < 0.8:
        return True
    return False


def _default_handoff(human_state: HumanState, action_id: str) -> bool:
    if action_id == "stop_and_check_pain_risk":
        return True
    if action_id == "offer_help":
        return True
    if action_id == "pause_and_request_consent":
        return human_state.confidence >= 0.85
    return human_state.handoff_required


class RuleRobotPolicy:
    """Maps human state and robot context to concrete robot action fields."""

    def decide(
        self,
        human_state: HumanState,
        context: RobotContext | None = None,
    ) -> RobotAction:
        context = context or RobotContext()
        state = human_state.state

        if state == "pain_risk":
            return build_robot_action(
                human_state,
                action_id="stop_and_check_pain_risk",
                context=context,
                handoff_required=True,
            )

        if state == "needs_help":
            return build_robot_action(
                human_state,
                action_id="offer_help",
                context=context,
                handoff_required=True,
            )

        if state == "refusing":
            return build_robot_action(
                human_state,
                action_id="pause_and_request_consent",
                context=context,
                handoff_required=human_state.confidence >= 0.85,
            )

        if state == "fatigued":
            return build_robot_action(
                human_state,
                action_id="reduce_task_load_and_offer_break",
                context=context,
            )

        if state == "confused":
            return build_robot_action(
                human_state,
                action_id="repeat_instruction_slowly",
                context=context,
            )

        if state == "frustrated":
            return build_robot_action(
                human_state,
                action_id="pause_and_reduce_pressure",
                context=context,
            )

        if state == "low_attention":
            return build_robot_action(
                human_state,
                action_id="regain_attention",
                context=context,
            )

        if state == "engaged":
            return build_robot_action(
                human_state,
                action_id="continue_and_encourage",
                context=context,
            )

        return build_robot_action(
            human_state,
            action_id="continue_current_plan",
            context=context,
        )
