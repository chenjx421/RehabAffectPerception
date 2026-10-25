from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .fusion import SAFETY_PRIORITY, fuse_signals
from .inputs import InputBatch
from .recognizers import (
    FaceStateRecognizer,
    PoseStateRecognizer,
    TaskBehaviorRecognizer,
    VoiceStateRecognizer,
)
from .policy import RuleRobotPolicy
from .schema import HumanState, ModalitySignal, RobotAction, RobotContext
from .smoothing import TemporalSmoother


@dataclass
class PipelineResult:
    human_state: HumanState
    robot_action: RobotAction
    raw_signals: list[ModalitySignal]
    smoothed_signals: list[ModalitySignal]

    def to_dict(self, include_signals: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "human_state": self.human_state.to_dict(),
            "robot_action": self.robot_action.to_dict(),
        }
        if include_signals:
            payload["raw_signals"] = [signal.__dict__ for signal in self.raw_signals]
            payload["smoothed_signals"] = [signal.__dict__ for signal in self.smoothed_signals]
        return payload


class RehabAffectPipeline:
    """MVP pipeline from input batch to smoothed, fused human_state."""

    def __init__(
        self,
        person_id: str = "user_001",
        smooth_window: int = 3,
        face_recognizer: FaceStateRecognizer | None = None,
        voice_recognizer: VoiceStateRecognizer | None = None,
        pose_recognizer: PoseStateRecognizer | None = None,
        task_behavior_recognizer: TaskBehaviorRecognizer | None = None,
        robot_policy: Any | None = None,
    ):
        self.person_id = person_id
        self.smooth_window = smooth_window
        self.face_recognizer = face_recognizer or FaceStateRecognizer()
        self.voice_recognizer = voice_recognizer or VoiceStateRecognizer()
        self.pose_recognizer = pose_recognizer or PoseStateRecognizer()
        self.task_behavior_recognizer = task_behavior_recognizer or TaskBehaviorRecognizer()
        self.robot_policy = robot_policy or RuleRobotPolicy()
        self._smoothers: dict[str, TemporalSmoother] = {}

    def process_batch(
        self,
        batch: InputBatch,
        robot_context: RobotContext | None = None,
    ) -> PipelineResult:
        raw_signals: list[ModalitySignal] = []

        if batch.camera is not None:
            raw_signals.append(self.face_recognizer.predict(batch.camera))
        if batch.audio is not None:
            raw_signals.append(self.voice_recognizer.predict(batch.audio))
        if batch.pose_features:
            raw_signals.append(self.pose_recognizer.predict(batch.pose_features))
        if batch.task_behavior is not None:
            raw_signals.append(self.task_behavior_recognizer.predict(batch.task_behavior))

        smoothed_signals = [self._smooth(signal) for signal in raw_signals]
        human_state = fuse_signals(
            person_id=self.person_id,
            signals=smoothed_signals,
            timestamp=batch.timestamp,
        )
        context = robot_context or self._context_from_batch(batch)
        robot_action = self.robot_policy.decide(human_state, context)
        return PipelineResult(
            human_state=human_state,
            robot_action=robot_action,
            raw_signals=raw_signals,
            smoothed_signals=smoothed_signals,
        )

    def _smooth(self, signal: ModalitySignal) -> ModalitySignal:
        if signal.source not in self._smoothers:
            self._smoothers[signal.source] = TemporalSmoother(
                window_size=self.smooth_window,
                state_priority=SAFETY_PRIORITY,
                bypass_states={"pain_risk", "needs_help", "discomfort", "need_help"},
                bypass_threshold=0.72,
            )
        return self._smoothers[signal.source].update(signal)

    def _context_from_batch(self, batch: InputBatch) -> RobotContext:
        task = batch.task_behavior
        metadata: dict[str, Any] = {"batch_timestamp": batch.timestamp}
        if task is not None:
            metadata.update(task.metadata)
        return RobotContext(
            task_stage=task.task_stage if task is not None else None,
            metadata=metadata,
        )
