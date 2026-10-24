from __future__ import annotations

import json
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
    recommended_robot_action: str
    risk_level: str = "low"
    handoff_required: bool = False
    timestamp: float = field(default_factory=time)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def suggested_robot_action(self) -> str:
        """Backward-compatible alias used by the earliest MVP docs."""

        return self.recommended_robot_action

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["suggested_robot_action"] = self.recommended_robot_action
        return payload

    def to_json(self, *, pretty: bool = False) -> str:
        indent = 2 if pretty else None
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


@dataclass
class RobotContext:
    """Robot and task context used to turn human state into embodied action."""

    task_id: str | None = None
    task_stage: str | None = None
    robot_distance_m: float | None = None
    obstacle_distance_m: float | None = None
    is_robot_moving: bool = False
    task_difficulty: str = "normal"
    visible_objects: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RobotAction:
    """Structured action target for robot speech, motion, task, and safety layers."""

    action_id: str
    speech_action: str
    motion_policy: str
    task_adjustment: str
    safety_action: str
    priority: str
    reason: str
    target_state: str
    confidence: float
    handoff_required: bool = False
    timestamp: float = field(default_factory=time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, *, pretty: bool = False) -> str:
        indent = 2 if pretty else None
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)
