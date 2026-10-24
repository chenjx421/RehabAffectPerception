from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from .policy import ACTION_TEMPLATES, build_robot_action
from .schema import HumanState, RobotAction, RobotContext


STATE_VOCAB = (
    "neutral",
    "engaged",
    "confused",
    "fatigued",
    "frustrated",
    "refusing",
    "pain_risk",
    "low_attention",
    "needs_help",
)
RISK_VOCAB = ("low", "medium", "high", "critical")
TASK_STAGE_VOCAB = (
    "task_intro",
    "instruction",
    "task_attempt",
    "task_feedback",
    "transition",
    "free_choice",
    "unknown",
)
DIFFICULTY_VOCAB = ("easy", "normal", "hard", "adaptive")
OBJECT_VOCAB = ("student", "teacher", "desk", "teaching_aid", "obstacle")
STATE_ACTION_PRIORS = {
    "engaged": "continue_and_encourage",
    "confused": "repeat_instruction_slowly",
    "fatigued": "reduce_task_load_and_offer_break",
    "frustrated": "pause_and_reduce_pressure",
    "refusing": "pause_and_request_consent",
    "pain_risk": "stop_and_check_pain_risk",
    "low_attention": "regain_attention",
    "needs_help": "offer_help",
}


def feature_names() -> list[str]:
    names = [
        "confidence",
        "valence",
        "arousal",
        "handoff_required",
        "robot_distance_m",
        "robot_distance_missing",
        "obstacle_distance_m",
        "obstacle_distance_missing",
        "is_robot_moving",
        "visible_object_count",
    ]
    names += [f"state={state}" for state in STATE_VOCAB]
    names += [f"risk={risk}" for risk in RISK_VOCAB]
    names += [f"task_stage={stage}" for stage in TASK_STAGE_VOCAB]
    names += [f"task_difficulty={difficulty}" for difficulty in DIFFICULTY_VOCAB]
    names += [f"visible_object={name}" for name in OBJECT_VOCAB]
    names += [f"state_score={state}" for state in STATE_VOCAB]
    return names


def featurize(human_state: HumanState, context: RobotContext | None = None) -> np.ndarray:
    context = context or RobotContext()
    visible_objects = set(context.visible_objects)
    state_scores = dict(human_state.metadata.get("state_scores", {}))
    task_stage = context.task_stage or "unknown"

    values: list[float] = [
        float(human_state.confidence),
        float(human_state.valence),
        float(human_state.arousal),
        1.0 if human_state.handoff_required else 0.0,
        _bounded_or_zero(context.robot_distance_m, upper=3.0),
        1.0 if context.robot_distance_m is None else 0.0,
        _bounded_or_zero(context.obstacle_distance_m, upper=3.0),
        1.0 if context.obstacle_distance_m is None else 0.0,
        1.0 if context.is_robot_moving else 0.0,
        float(min(len(visible_objects), 8)),
    ]
    values.extend(_one_hot(human_state.state, STATE_VOCAB))
    values.extend(_one_hot(human_state.risk_level, RISK_VOCAB))
    values.extend(_one_hot(task_stage if task_stage in TASK_STAGE_VOCAB else "unknown", TASK_STAGE_VOCAB))
    values.extend(_one_hot(context.task_difficulty, DIFFICULTY_VOCAB))
    values.extend(1.0 if name in visible_objects else 0.0 for name in OBJECT_VOCAB)
    values.extend(float(state_scores.get(state, 0.0)) for state in STATE_VOCAB)
    return np.asarray(values, dtype=np.float32)


@dataclass
class LearnedSchoolPolicy:
    """Small supervised baseline that maps state/context features to robot actions."""

    classifier: Any
    metadata: dict[str, Any] = field(default_factory=dict)
    shield_enabled: bool = True

    @classmethod
    def fit(
        cls,
        feature_rows: Sequence[Sequence[float] | np.ndarray],
        labels: Sequence[str],
        *,
        random_state: int = 42,
        max_depth: int = 5,
    ) -> "LearnedSchoolPolicy":
        if not feature_rows:
            raise ValueError("At least one training row is required")
        if len(feature_rows) != len(labels):
            raise ValueError("feature_rows and labels must have the same length")

        try:
            from sklearn.tree import DecisionTreeClassifier
        except ImportError as exc:
            raise RuntimeError(
                "scikit-learn is required for policy training. "
                "Install it with: pip install -e .[training]"
            ) from exc

        x = np.asarray(feature_rows, dtype=np.float32)
        classifier = DecisionTreeClassifier(
            max_depth=max_depth,
            random_state=random_state,
            class_weight="balanced",
        )
        classifier.fit(x, np.asarray(labels))
        return cls(
            classifier=classifier,
            metadata={
                "policy_type": "learned_school_policy",
                "model_family": "DecisionTreeClassifier",
                "feature_names": feature_names(),
                "training_rows": len(labels),
                "label_set": sorted(set(labels)),
                "random_state": random_state,
                "max_depth": max_depth,
            },
        )

    def decide(
        self,
        human_state: HumanState,
        context: RobotContext | None = None,
    ) -> RobotAction:
        context = context or RobotContext()
        vector = featurize(human_state, context)
        predicted_action_id = self.predict_action_id(vector)
        action_confidence = self.predict_action_confidence(vector, predicted_action_id)
        if self.shield_enabled:
            action_id, shield_reason = self._apply_action_shield(
                human_state,
                predicted_action_id,
                action_confidence,
            )
        else:
            action_id, shield_reason = predicted_action_id, "disabled"
        return build_robot_action(
            human_state,
            action_id=action_id,
            context=context,
            metadata={
                "policy_type": "learned_school_policy",
                "predicted_action_id": predicted_action_id,
                "action_confidence": action_confidence,
                "action_shield": shield_reason,
                "model_family": self.metadata.get("model_family", "unknown"),
                "shield_enabled": self.shield_enabled,
            },
        )

    def predict_action_id(self, vector: Sequence[float] | np.ndarray) -> str:
        x = np.asarray(vector, dtype=np.float32).reshape(1, -1)
        action_id = str(self.classifier.predict(x)[0])
        if action_id not in ACTION_TEMPLATES:
            return "continue_current_plan"
        return action_id

    def predict_action_confidence(
        self,
        vector: Sequence[float] | np.ndarray,
        action_id: str | None = None,
    ) -> float | None:
        if not hasattr(self.classifier, "predict_proba"):
            return None
        x = np.asarray(vector, dtype=np.float32).reshape(1, -1)
        probabilities = self.classifier.predict_proba(x)[0]
        classes = [str(label) for label in getattr(self.classifier, "classes_", [])]
        if action_id in classes:
            return float(probabilities[classes.index(action_id)])
        return float(max(probabilities)) if len(probabilities) else None

    def _apply_action_shield(
        self,
        human_state: HumanState,
        predicted_action_id: str,
        action_confidence: float | None,
    ) -> tuple[str, str]:
        prior_action_id = STATE_ACTION_PRIORS.get(human_state.state)
        if prior_action_id is None:
            return predicted_action_id, "none"
        if predicted_action_id == prior_action_id:
            return predicted_action_id, "consistent"
        if human_state.state in {"pain_risk", "needs_help", "refusing"}:
            return prior_action_id, "safety_state_prior"
        if human_state.confidence >= 0.45 and action_confidence is not None and action_confidence < 0.90:
            return prior_action_id, "state_prior_low_model_confidence"
        if human_state.confidence >= 0.60 and human_state.state in {"confused", "fatigued", "low_attention"}:
            return prior_action_id, "state_prior_high_state_confidence"
        return predicted_action_id, "model_preferred"

    def save(self, path: Path | str) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump(
                {
                    "classifier": self.classifier,
                    "metadata": self.metadata,
                    "shield_enabled": self.shield_enabled,
                },
                f,
            )

    @classmethod
    def load(cls, path: Path | str) -> "LearnedSchoolPolicy":
        with Path(path).open("rb") as f:
            payload = pickle.load(f)
        if isinstance(payload, cls):
            return payload
        return cls(
            classifier=payload["classifier"],
            metadata=dict(payload.get("metadata", {})),
            shield_enabled=bool(payload.get("shield_enabled", True)),
        )


def _bounded_or_zero(value: float | None, *, upper: float) -> float:
    if value is None:
        return 0.0
    return float(max(0.0, min(float(value), upper)))


def _one_hot(value: str, vocab: Sequence[str]) -> list[float]:
    return [1.0 if value == item else 0.0 for item in vocab]
