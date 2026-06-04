from __future__ import annotations

from dataclasses import asdict, dataclass, field
from time import time
from typing import Any


@dataclass
class ModalitySignal:
    """One modality's state estimate before fusion."""

    source: str
    state: str
    confidence: float
    valence: float = 0.0
    arousal: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HumanState:
    """Fused human state exposed to the robot policy."""

    person_id: str
    state: str
    confidence: float
    valence: float
    arousal: float
    evidence: list[str]
    suggested_robot_action: str
    timestamp: float = field(default_factory=time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

