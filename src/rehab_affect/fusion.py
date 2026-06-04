from __future__ import annotations

from collections import defaultdict

from .schema import HumanState, ModalitySignal


SUGGESTED_ACTIONS = {
    "engaged": "continue_and_encourage",
    "neutral": "continue_current_plan",
    "confused": "repeat_instruction_slowly",
    "fatigued": "slow_down_and_offer_break",
    "frustrated": "pause_and_reduce_pressure",
    "discomfort": "stop_and_alert_caregiver",
    "low_attention": "regain_attention_or_simplify_task",
    "need_help": "offer_help_or_call_caregiver",
}

SAFETY_PRIORITY = {
    "discomfort": 100,
    "need_help": 90,
    "frustrated": 70,
    "fatigued": 60,
    "confused": 50,
    "low_attention": 40,
    "engaged": 20,
    "neutral": 10,
}


def fuse_signals(person_id: str, signals: list[ModalitySignal]) -> HumanState:
    """Fuses face, voice, pose, and task-behavior estimates.

    The first version intentionally uses a transparent rule-based fusion layer.
    In rehabilitation settings, explainability and conservative safety behavior
    are more important than pretending the system knows a user's true emotion.
    """

    if not signals:
        return HumanState(
            person_id=person_id,
            state="neutral",
            confidence=0.0,
            valence=0.0,
            arousal=0.0,
            evidence=[],
            suggested_robot_action=SUGGESTED_ACTIONS["neutral"],
        )

    scores: dict[str, float] = defaultdict(float)
    for signal in signals:
        priority_bonus = SAFETY_PRIORITY.get(signal.state, 10) / 100.0
        scores[signal.state] += signal.confidence + 0.15 * priority_bonus

    state = max(scores.items(), key=lambda item: item[1])[0]
    state_signals = [signal for signal in signals if signal.state == state]
    confidence = min(1.0, scores[state] / max(1, len(signals)))

    valence = sum(signal.valence * signal.confidence for signal in signals)
    arousal = sum(signal.arousal * signal.confidence for signal in signals)
    weight = sum(signal.confidence for signal in signals) or 1.0

    return HumanState(
        person_id=person_id,
        state=state,
        confidence=float(confidence),
        valence=float(valence / weight),
        arousal=float(arousal / weight),
        evidence=sorted({signal.source for signal in state_signals}),
        suggested_robot_action=SUGGESTED_ACTIONS.get(state, SUGGESTED_ACTIONS["neutral"]),
    )

