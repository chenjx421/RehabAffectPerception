from __future__ import annotations

from collections import defaultdict
from time import time

from .schema import HumanState, ModalitySignal


STATE_ALIASES = {
    "discomfort": "pain_risk",
    "need_help": "needs_help",
}

ACTION_PROFILES = {
    "engaged": {
        "recommended_robot_action": "continue_and_encourage",
        "risk_level": "low",
        "handoff_required": False,
    },
    "neutral": {
        "recommended_robot_action": "continue_current_plan",
        "risk_level": "low",
        "handoff_required": False,
    },
    "confused": {
        "recommended_robot_action": "repeat_instruction_slowly",
        "risk_level": "medium",
        "handoff_required": False,
    },
    "fatigued": {
        "recommended_robot_action": "reduce_task_load_and_offer_break",
        "risk_level": "medium",
        "handoff_required": False,
    },
    "frustrated": {
        "recommended_robot_action": "pause_and_reduce_pressure",
        "risk_level": "medium",
        "handoff_required": False,
    },
    "refusing": {
        "recommended_robot_action": "pause_ask_consent_and_offer_choice",
        "risk_level": "medium",
        "handoff_required": False,
    },
    "pain_risk": {
        "recommended_robot_action": "stop_check_pain_risk_and_alert_teacher_or_caregiver",
        "risk_level": "high",
        "handoff_required": True,
    },
    "low_attention": {
        "recommended_robot_action": "regain_attention_or_simplify_task",
        "risk_level": "medium",
        "handoff_required": False,
    },
    "needs_help": {
        "recommended_robot_action": "offer_help_or_call_caregiver",
        "risk_level": "high",
        "handoff_required": True,
    },
}

SUGGESTED_ACTIONS = {
    state: profile["recommended_robot_action"] for state, profile in ACTION_PROFILES.items()
}
SUGGESTED_ACTIONS.update(
    {
        alias: ACTION_PROFILES[canonical]["recommended_robot_action"]
        for alias, canonical in STATE_ALIASES.items()
    }
)

SAFETY_PRIORITY = {
    "pain_risk": 100,
    "needs_help": 95,
    "refusing": 80,
    "frustrated": 70,
    "fatigued": 60,
    "confused": 50,
    "low_attention": 40,
    "engaged": 20,
    "neutral": 10,
    "discomfort": 100,
    "need_help": 95,
}


def canonical_state(state: str) -> str:
    return STATE_ALIASES.get(state, state)


def action_profile(state: str) -> dict[str, object]:
    return ACTION_PROFILES.get(canonical_state(state), ACTION_PROFILES["neutral"])


def fuse_signals(
    person_id: str,
    signals: list[ModalitySignal],
    timestamp: float | None = None,
) -> HumanState:
    """Fuses face, voice, pose, and task-behavior estimates.

    The first version intentionally uses a transparent rule-based fusion layer.
    In rehabilitation settings, explainability and conservative safety behavior
    are more important than pretending the system knows a user's true emotion.
    """

    if not signals:
        profile = action_profile("neutral")
        return HumanState(
            person_id=person_id,
            state="neutral",
            confidence=0.0,
            valence=0.0,
            arousal=0.0,
            evidence=[],
            recommended_robot_action=str(profile["recommended_robot_action"]),
            risk_level=str(profile["risk_level"]),
            handoff_required=bool(profile["handoff_required"]),
            timestamp=timestamp if timestamp is not None else time(),
        )

    scores: dict[str, float] = defaultdict(float)
    for signal in signals:
        state = canonical_state(signal.state)
        priority_bonus = SAFETY_PRIORITY.get(state, 10) / 100.0
        scores[state] += signal.confidence + 0.15 * priority_bonus

    state = max(scores.items(), key=lambda item: item[1])[0]
    state_signals = [signal for signal in signals if canonical_state(signal.state) == state]
    confidence = min(1.0, scores[state] / max(1, len(signals)))

    valence = sum(signal.valence * signal.confidence for signal in signals)
    arousal = sum(signal.arousal * signal.confidence for signal in signals)
    weight = sum(signal.confidence for signal in signals) or 1.0
    profile = action_profile(state)

    return HumanState(
        person_id=person_id,
        state=state,
        confidence=float(confidence),
        valence=float(valence / weight),
        arousal=float(arousal / weight),
        evidence=sorted({signal.source for signal in state_signals}),
        recommended_robot_action=str(profile["recommended_robot_action"]),
        risk_level=str(profile["risk_level"]),
        handoff_required=bool(profile["handoff_required"]),
        timestamp=timestamp if timestamp is not None else time(),
        metadata={"state_scores": dict(scores)},
    )
