from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from .inputs import AudioChunk, CameraFrame, TaskBehavior
from .schema import ModalitySignal


VALID_STATES = {
    "engaged",
    "neutral",
    "confused",
    "fatigued",
    "frustrated",
    "refusing",
    "pain_risk",
    "low_attention",
    "needs_help",
}

STATE_ALIASES = {
    "discomfort": "pain_risk",
    "need_help": "needs_help",
}

EMOTION_TO_STATE = {
    "happy": "engaged",
    "positive": "engaged",
    "neutral": "neutral",
    "surprise": "confused",
    "confused": "confused",
    "sad": "fatigued",
    "tired": "fatigued",
    "fatigue": "fatigued",
    "angry": "frustrated",
    "frustrated": "frustrated",
    "refusing": "refusing",
    "fear": "pain_risk",
    "pain": "pain_risk",
    "disgust": "pain_risk",
}

STATE_DEFAULTS = {
    "engaged": (0.30, 0.45),
    "neutral": (0.00, 0.30),
    "confused": (-0.20, 0.45),
    "fatigued": (-0.35, 0.22),
    "frustrated": (-0.55, 0.70),
    "refusing": (-0.45, 0.55),
    "pain_risk": (-0.70, 0.78),
    "low_attention": (-0.10, 0.18),
    "needs_help": (-0.55, 0.68),
}


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _canonical_state(state: str) -> str:
    return STATE_ALIASES.get(state, state)


def _signal(
    source: str,
    state: str,
    confidence: float,
    metadata: Mapping[str, Any] | None = None,
    valence: float | None = None,
    arousal: float | None = None,
) -> ModalitySignal:
    state = _canonical_state(state)
    default_valence, default_arousal = STATE_DEFAULTS[state]
    return ModalitySignal(
        source=source,
        state=state,
        confidence=float(_clamp(confidence)),
        valence=float(valence if valence is not None else default_valence),
        arousal=float(_clamp(arousal if arousal is not None else default_arousal)),
        metadata=dict(metadata or {}),
    )


def _state_from_metadata(source: str, metadata: Mapping[str, Any]) -> ModalitySignal | None:
    state = metadata.get("state") or metadata.get("state_hint")
    if isinstance(state, str):
        canonical = _canonical_state(state)
        if canonical in VALID_STATES:
            confidence = _safe_float(metadata.get("confidence"), 0.65)
            valence = _safe_float(metadata.get("valence"), STATE_DEFAULTS[canonical][0])
            arousal = _safe_float(metadata.get("arousal"), STATE_DEFAULTS[canonical][1])
            return _signal(source, canonical, confidence, metadata, valence=valence, arousal=arousal)
    return None


class FaceStateRecognizer:
    """Interprets camera metadata or raw frames as a face/attention signal."""

    def __init__(self, use_opencv_face_detector: bool = True):
        self.use_opencv_face_detector = use_opencv_face_detector
        self._cv2: Any | None = None
        self._cascade: Any | None = None

    def predict(self, frame: CameraFrame | None) -> ModalitySignal:
        if frame is None:
            return _signal("face", "neutral", 0.05, {"detected": False})

        metadata: dict[str, Any] = dict(frame.metadata)
        metadata_signal = _state_from_metadata("face", metadata)
        if metadata_signal is not None:
            return metadata_signal

        emotion_signal = self._from_emotion_probs(metadata)
        if emotion_signal is not None:
            return emotion_signal

        face_detected = metadata.get("face_detected")
        attention_score = metadata.get("attention_score")
        if isinstance(face_detected, bool):
            return self._from_face_presence(face_detected, attention_score, metadata)

        image = frame.image
        if image is None:
            return _signal("face", "neutral", 0.08, {**metadata, "detected": False})

        image_array = np.asarray(image)
        brightness = float(np.mean(image_array) / 255.0)
        contrast = float(np.std(image_array) / 255.0)
        metadata.update({"brightness": brightness, "contrast": contrast})

        face_info = self._detect_faces(image_array)
        if face_info is not None:
            metadata.update(face_info)
            return self._from_face_presence(face_info["face_count"] > 0, attention_score, metadata)

        if brightness < 0.18:
            return _signal("face", "low_attention", 0.34, metadata, valence=-0.05, arousal=0.15)
        return _signal("face", "neutral", 0.28, metadata)

    def _from_emotion_probs(self, metadata: Mapping[str, Any]) -> ModalitySignal | None:
        emotion_probs = metadata.get("emotion_probs")
        if not isinstance(emotion_probs, Mapping) or not emotion_probs:
            return None

        emotion, probability = max(
            emotion_probs.items(),
            key=lambda item: _safe_float(item[1], 0.0),
        )
        state = EMOTION_TO_STATE.get(str(emotion).lower(), "neutral")
        confidence = 0.35 + 0.55 * _safe_float(probability, 0.0)
        valence = _safe_float(metadata.get("valence"), STATE_DEFAULTS[state][0])
        arousal = _safe_float(metadata.get("arousal"), STATE_DEFAULTS[state][1])
        return _signal("face", state, confidence, metadata, valence=valence, arousal=arousal)

    def _from_face_presence(
        self,
        face_detected: bool,
        attention_score: Any,
        metadata: Mapping[str, Any],
    ) -> ModalitySignal:
        if not face_detected:
            return _signal("face", "low_attention", 0.48, metadata, valence=-0.08, arousal=0.12)

        attention = _safe_float(attention_score, 0.55)
        if attention < 0.35:
            return _signal("face", "low_attention", 0.55, metadata, valence=-0.08, arousal=0.18)
        if attention > 0.72:
            return _signal("face", "engaged", 0.50 + 0.30 * attention, metadata)
        return _signal("face", "neutral", 0.42 + 0.25 * attention, metadata)

    def _detect_faces(self, image: np.ndarray) -> dict[str, Any] | None:
        if not self.use_opencv_face_detector:
            return None
        try:
            import cv2  # type: ignore[import-not-found]
        except ImportError:
            return None

        if self._cv2 is None:
            self._cv2 = cv2
        if self._cascade is None:
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self._cascade = cv2.CascadeClassifier(cascade_path)
            if self._cascade.empty():
                return None

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        faces = self._cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
        if len(faces) == 0:
            return {"face_count": 0}

        height, width = gray.shape[:2]
        x, y, w, h = max(faces, key=lambda box: box[2] * box[3])
        center_x = (x + w / 2.0) / max(width, 1)
        center_y = (y + h / 2.0) / max(height, 1)
        center_offset = abs(center_x - 0.5) + abs(center_y - 0.45)
        area_ratio = (w * h) / max(width * height, 1)
        return {
            "face_count": int(len(faces)),
            "largest_face_area_ratio": float(area_ratio),
            "face_center_offset": float(center_offset),
        }


class VoiceStateRecognizer:
    """Interprets microphone chunks and optional transcript/sentiment metadata."""

    def __init__(
        self,
        silence_threshold: float = 0.012,
        low_energy_threshold: float = 0.030,
        high_energy_threshold: float = 0.110,
    ):
        self.silence_threshold = silence_threshold
        self.low_energy_threshold = low_energy_threshold
        self.high_energy_threshold = high_energy_threshold

    def predict(self, audio: AudioChunk | None) -> ModalitySignal:
        if audio is None:
            return _signal("voice", "neutral", 0.05, {"detected": False})

        metadata: dict[str, Any] = dict(audio.metadata)
        metadata_signal = _state_from_metadata("voice", metadata)
        if metadata_signal is not None:
            return metadata_signal

        transcript = str(metadata.get("transcript") or "").lower()
        text_signal = self._from_text(transcript, metadata)
        if text_signal is not None:
            return text_signal

        samples = audio.samples
        if samples is None or len(samples) == 0:
            return _signal("voice", "neutral", 0.08, {**metadata, "detected": False})

        samples_array = np.asarray(samples, dtype=np.float32).reshape(-1)
        rms = float(np.sqrt(np.mean(np.square(samples_array))))
        peak = float(np.max(np.abs(samples_array)))
        zcr = self._zero_crossing_rate(samples_array)
        metadata.update({"energy": rms, "peak": peak, "zero_crossing_rate": zcr})

        sentiment = str(metadata.get("sentiment") or "").lower()
        if sentiment in {"negative", "angry", "frustrated"} and rms > self.low_energy_threshold:
            return _signal("voice", "frustrated", 0.58, metadata)
        if sentiment in {"positive", "encouraged"} and rms > self.low_energy_threshold:
            return _signal("voice", "engaged", 0.55, metadata)

        if rms < self.silence_threshold:
            return _signal("voice", "low_attention", 0.35, metadata, valence=-0.05, arousal=0.10)
        if rms < self.low_energy_threshold:
            return _signal("voice", "fatigued", 0.45, metadata)
        if rms > self.high_energy_threshold and zcr > 0.08:
            return _signal("voice", "frustrated", 0.48, metadata)
        return _signal("voice", "neutral", 0.42, metadata)

    def _from_text(self, transcript: str, metadata: Mapping[str, Any]) -> ModalitySignal | None:
        if not transcript:
            return None

        text_rules = [
            ("pain_risk", ("疼", "痛", "不舒服", "难受", "pain", "hurt", "ache"), 0.88),
            ("needs_help", ("帮", "扶", "救", "help", "assist"), 0.82),
            ("fatigued", ("累", "休息", "tired", "rest"), 0.76),
            ("confused", ("不会", "不懂", "听不懂", "怎么做", "再说", "哪一个", "confused"), 0.72),
            ("refusing", ("不要", "不想", "不做", "拒绝", "算了", "停一下", "stop", "no more"), 0.74),
            ("frustrated", ("烦", "生气", "angry", "annoy"), 0.72),
        ]
        for state, keywords, confidence in text_rules:
            if any(keyword in transcript for keyword in keywords):
                return _signal("voice", state, confidence, metadata)
        return None

    def _zero_crossing_rate(self, samples: np.ndarray) -> float:
        if len(samples) < 2:
            return 0.0
        return float(np.mean(samples[:-1] * samples[1:] < 0.0))


class PoseStateRecognizer:
    """Interprets pose features from a future pose model or RGB-D stack."""

    def predict(self, pose_features: Mapping[str, Any] | None) -> ModalitySignal:
        if not pose_features:
            return _signal("pose", "neutral", 0.05, {"detected": False})

        metadata = dict(pose_features)
        metadata_signal = _state_from_metadata("pose", metadata)
        if metadata_signal is not None:
            return metadata_signal

        if bool(metadata.get("pain_guarding")) or bool(metadata.get("protective_posture")):
            return _signal("pose", "pain_risk", 0.78, metadata)

        attention = metadata.get("attention_score")
        movement_speed = metadata.get("movement_speed")
        attention_score = _safe_float(attention, 0.55)
        speed = _safe_float(movement_speed, 0.30)

        if attention is not None and attention_score < 0.35:
            return _signal("pose", "low_attention", 0.62, metadata)
        if movement_speed is not None and speed < 0.16:
            return _signal("pose", "fatigued", 0.60, metadata)
        if attention_score > 0.70 and speed > 0.22:
            return _signal("pose", "engaged", 0.62, metadata)
        return _signal("pose", "neutral", 0.38, metadata)


class TaskBehaviorRecognizer:
    """Interprets robot task events such as delays, repeats, and requests."""

    def predict(self, behavior: TaskBehavior | None) -> ModalitySignal:
        if behavior is None:
            return _signal("task_behavior", "neutral", 0.05, {"detected": False})

        metadata = {
            "instruction_repeated": behavior.instruction_repeated,
            "response_delay_sec": behavior.response_delay_sec,
            "recent_failure_count": behavior.recent_failure_count,
            "request_text": behavior.request_text,
            "task_success": behavior.task_success,
            "task_stage": behavior.task_stage,
            **behavior.metadata,
        }
        metadata_signal = _state_from_metadata("task_behavior", metadata)
        if metadata_signal is not None:
            return metadata_signal

        request_text = str(behavior.request_text or "").lower()
        request_signal = VoiceStateRecognizer()._from_text(request_text, metadata)
        if request_signal is not None:
            request_signal.source = "task_behavior"
            return request_signal

        if behavior.response_delay_sec >= 5.0 and behavior.instruction_repeated >= 1:
            return _signal("task_behavior", "confused", 0.72, metadata)
        if behavior.recent_failure_count >= 3:
            return _signal("task_behavior", "frustrated", 0.70, metadata)
        if behavior.response_delay_sec >= 4.0:
            return _signal("task_behavior", "low_attention", 0.62, metadata)
        if behavior.instruction_repeated >= 2:
            return _signal("task_behavior", "confused", 0.62, metadata)
        if behavior.task_success is True and behavior.response_delay_sec <= 1.5:
            return _signal("task_behavior", "engaged", 0.66, metadata)
        return _signal("task_behavior", "neutral", 0.34, metadata)
