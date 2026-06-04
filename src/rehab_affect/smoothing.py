from __future__ import annotations

from collections import Counter, deque

from .schema import ModalitySignal


class TemporalSmoother:
    """Smooths noisy state estimates with a short sliding window."""

    def __init__(self, window_size: int = 5):
        if window_size <= 0:
            raise ValueError("window_size must be positive")
        self.window_size = window_size
        self._history: deque[ModalitySignal] = deque(maxlen=window_size)

    def update(self, signal: ModalitySignal) -> ModalitySignal:
        self._history.append(signal)
        states = [item.state for item in self._history]
        state = Counter(states).most_common(1)[0][0]

        selected = [item for item in self._history if item.state == state]
        confidence = sum(item.confidence for item in selected) / len(selected)
        valence = sum(item.valence for item in selected) / len(selected)
        arousal = sum(item.arousal for item in selected) / len(selected)

        return ModalitySignal(
            source=signal.source,
            state=state,
            confidence=float(confidence),
            valence=float(valence),
            arousal=float(arousal),
            metadata={"window_size": len(self._history)},
        )

