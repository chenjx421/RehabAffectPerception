from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping

from .schema import ModalitySignal


class TemporalSmoother:
    """Smooths noisy state estimates with a short sliding window."""

    def __init__(
        self,
        window_size: int = 5,
        state_priority: Mapping[str, float] | None = None,
        bypass_states: set[str] | None = None,
        bypass_threshold: float = 0.75,
    ):
        if window_size <= 0:
            raise ValueError("window_size must be positive")
        if not 0.0 <= bypass_threshold <= 1.0:
            raise ValueError("bypass_threshold must be in [0, 1]")
        self.window_size = window_size
        self.state_priority = dict(state_priority or {})
        self.bypass_states = bypass_states or {"pain_risk", "needs_help", "discomfort", "need_help"}
        self.bypass_threshold = bypass_threshold
        self._history: deque[ModalitySignal] = deque(maxlen=window_size)

    def update(self, signal: ModalitySignal) -> ModalitySignal:
        self._history.append(signal)

        if signal.state in self.bypass_states and signal.confidence >= self.bypass_threshold:
            return ModalitySignal(
                source=signal.source,
                state=signal.state,
                confidence=signal.confidence,
                valence=signal.valence,
                arousal=signal.arousal,
                metadata={
                    **signal.metadata,
                    "window_size": len(self._history),
                    "smoothing": "bypass_for_safety_state",
                },
            )

        scores: dict[str, float] = defaultdict(float)
        history_len = len(self._history)
        for index, item in enumerate(self._history):
            recency = (index + 1) / history_len
            priority = self.state_priority.get(item.state, 0.0)
            scores[item.state] += item.confidence + 0.05 * recency + 0.03 * priority

        state = max(scores.items(), key=lambda item: item[1])[0]

        selected = [item for item in self._history if item.state == state]
        weight = sum(max(item.confidence, 1e-6) for item in selected)
        confidence = sum(item.confidence for item in selected) / len(selected)
        valence = sum(item.valence * max(item.confidence, 1e-6) for item in selected) / weight
        arousal = sum(item.arousal * max(item.confidence, 1e-6) for item in selected) / weight

        return ModalitySignal(
            source=signal.source,
            state=state,
            confidence=float(confidence),
            valence=float(valence),
            arousal=float(arousal),
            metadata={"window_size": len(self._history), "state_scores": dict(scores)},
        )
