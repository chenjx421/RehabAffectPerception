from __future__ import annotations

import json
from random import Random

from .fusion import fuse_signals
from .policy import RuleRobotPolicy
from .schema import ModalitySignal
from .smoothing import TemporalSmoother


def _mock_frame_signals(rng: Random, step: int) -> list[ModalitySignal]:
    """Creates deterministic fake signals for a rehabilitation interaction."""

    if step < 3:
        face_state, voice_state, behavior_state = "engaged", "neutral", "engaged"
    elif step < 7:
        face_state, voice_state, behavior_state = "fatigued", "fatigued", "low_attention"
    else:
        face_state, voice_state, behavior_state = "pain_risk", "fatigued", "needs_help"

    return [
        ModalitySignal(
            source="face",
            state=face_state,
            confidence=0.65 + 0.1 * rng.random(),
            valence=-0.35 if face_state in {"fatigued", "pain_risk"} else 0.2,
            arousal=0.2 if face_state == "fatigued" else 0.65 if face_state == "pain_risk" else 0.4,
        ),
        ModalitySignal(
            source="voice",
            state=voice_state,
            confidence=0.55 + 0.1 * rng.random(),
            valence=-0.25 if voice_state == "fatigued" else 0.0,
            arousal=0.25,
        ),
        ModalitySignal(
            source="task_behavior",
            state=behavior_state,
            confidence=0.7 + 0.1 * rng.random(),
            valence=-0.4 if behavior_state in {"low_attention", "needs_help"} else 0.1,
            arousal=0.3 if behavior_state == "low_attention" else 0.7 if behavior_state == "needs_help" else 0.4,
        ),
    ]


def main() -> None:
    rng = Random(42)
    policy = RuleRobotPolicy()
    smoothers = {
        "face": TemporalSmoother(window_size=3),
        "voice": TemporalSmoother(window_size=3),
        "task_behavior": TemporalSmoother(window_size=3),
    }

    for step in range(10):
        raw_signals = _mock_frame_signals(rng, step)
        smoothed = [smoothers[signal.source].update(signal) for signal in raw_signals]
        fused = fuse_signals(person_id="user_001", signals=smoothed)
        action = policy.decide(fused)
        print(
            json.dumps(
                {
                    "step": step,
                    "human_state": fused.to_dict(),
                    "robot_action": action.to_dict(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
