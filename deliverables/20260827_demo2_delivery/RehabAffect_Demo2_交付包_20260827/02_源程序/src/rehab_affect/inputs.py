from __future__ import annotations

from dataclasses import dataclass, field
from time import time
from typing import Any

import numpy as np


class OptionalDependencyError(RuntimeError):
    """Raised when a live input backend is requested but not installed."""


@dataclass
class CameraFrame:
    timestamp: float
    image: np.ndarray | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AudioChunk:
    timestamp: float
    samples: np.ndarray | None
    sample_rate: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskBehavior:
    instruction_repeated: int = 0
    response_delay_sec: float = 0.0
    recent_failure_count: int = 0
    request_text: str | None = None
    task_success: bool | None = None
    task_stage: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class InputBatch:
    timestamp: float
    camera: CameraFrame | None = None
    audio: AudioChunk | None = None
    pose_features: dict[str, Any] = field(default_factory=dict)
    task_behavior: TaskBehavior | None = None


class CameraInput:
    """Small OpenCV camera adapter used by the MVP live pipeline."""

    def __init__(
        self,
        camera_index: int = 0,
        width: int | None = None,
        height: int | None = None,
    ):
        self.camera_index = camera_index
        self.width = width
        self.height = height
        self._cv2: Any | None = None
        self._capture: Any | None = None

    def open(self) -> None:
        try:
            import cv2  # type: ignore[import-not-found]
        except ImportError as exc:
            raise OptionalDependencyError(
                "OpenCV is required for live camera input. Install with: "
                "pip install -e .[input]"
            ) from exc

        self._cv2 = cv2
        self._capture = cv2.VideoCapture(self.camera_index)
        if self.width is not None:
            self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        if self.height is not None:
            self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        if not self._capture.isOpened():
            raise RuntimeError(f"Could not open camera index {self.camera_index}")

    def read(self) -> CameraFrame:
        if self._capture is None:
            self.open()

        ok, frame = self._capture.read()
        if not ok:
            return CameraFrame(
                timestamp=time(),
                image=None,
                metadata={"capture_error": "camera_read_failed", "camera_index": self.camera_index},
            )

        return CameraFrame(
            timestamp=time(),
            image=frame,
            metadata={
                "camera_index": self.camera_index,
                "width": int(frame.shape[1]),
                "height": int(frame.shape[0]),
            },
        )

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
        self._capture = None


class MicrophoneInput:
    """Small sounddevice microphone adapter used by the MVP live pipeline."""

    def __init__(
        self,
        duration_sec: float = 0.8,
        sample_rate: int = 16000,
        channels: int = 1,
        device: int | str | None = None,
    ):
        if duration_sec <= 0:
            raise ValueError("duration_sec must be positive")
        if sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        self.duration_sec = duration_sec
        self.sample_rate = sample_rate
        self.channels = channels
        self.device = device
        self._sd: Any | None = None

    def open(self) -> None:
        try:
            import sounddevice as sd  # type: ignore[import-not-found]
        except ImportError as exc:
            raise OptionalDependencyError(
                "sounddevice is required for live microphone input. Install with: "
                "pip install -e .[input]"
            ) from exc
        self._sd = sd

    def read(self) -> AudioChunk:
        if self._sd is None:
            self.open()

        sample_count = max(1, int(self.duration_sec * self.sample_rate))
        recording = self._sd.rec(
            sample_count,
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="float32",
            device=self.device,
        )
        self._sd.wait()
        samples = np.asarray(recording, dtype=np.float32).reshape(-1)

        return AudioChunk(
            timestamp=time(),
            samples=samples,
            sample_rate=self.sample_rate,
            metadata={
                "duration_sec": self.duration_sec,
                "sample_rate": self.sample_rate,
                "channels": self.channels,
                "device": self.device,
            },
        )

    def close(self) -> None:
        self._sd = None


class LiveInputSource:
    """Combines optional camera and microphone adapters into one batch stream."""

    def __init__(
        self,
        camera: CameraInput | None = None,
        microphone: MicrophoneInput | None = None,
        task_behavior: TaskBehavior | None = None,
    ):
        self.camera = camera
        self.microphone = microphone
        self.task_behavior = task_behavior or TaskBehavior()

    def open(self) -> None:
        if self.camera is not None:
            self.camera.open()
        if self.microphone is not None:
            self.microphone.open()

    def read(self) -> InputBatch:
        camera_frame = self.camera.read() if self.camera is not None else None
        audio_chunk = self.microphone.read() if self.microphone is not None else None
        return InputBatch(
            timestamp=time(),
            camera=camera_frame,
            audio=audio_chunk,
            task_behavior=self.task_behavior,
        )

    def close(self) -> None:
        if self.camera is not None:
            self.camera.close()
        if self.microphone is not None:
            self.microphone.close()


class MockInputSource:
    """Deterministic sensor stream for demos, tests, and hardware-free runs."""

    def __init__(self, seed: int = 42):
        self._rng = np.random.default_rng(seed)
        self._step = 0

    def open(self) -> None:
        return None

    def read(self) -> InputBatch:
        step = self._step
        self._step += 1
        timestamp = time()

        if step < 3:
            camera = self._camera_frame(timestamp, "engaged", attention_score=0.88)
            audio = self._audio_chunk(timestamp, amplitude=0.07, transcript="好的")
            pose = {"attention_score": 0.86, "movement_speed": 0.42}
            task = TaskBehavior(response_delay_sec=0.6, task_success=True, task_stage="instruction")
        elif step < 7:
            camera = self._camera_frame(timestamp, "fatigued", attention_score=0.52)
            audio = self._audio_chunk(timestamp, amplitude=0.018, transcript="有点累")
            pose = {"attention_score": 0.48, "movement_speed": 0.12}
            task = TaskBehavior(
                instruction_repeated=1,
                response_delay_sec=3.4,
                recent_failure_count=1,
                task_stage="movement_execution",
            )
        else:
            camera = self._camera_frame(timestamp, "pain_risk", attention_score=0.36)
            audio = self._audio_chunk(timestamp, amplitude=0.11, transcript="疼，需要帮忙")
            pose = {"attention_score": 0.42, "movement_speed": 0.08, "pain_guarding": True}
            task = TaskBehavior(
                instruction_repeated=2,
                response_delay_sec=5.2,
                recent_failure_count=2,
                request_text="疼，需要帮忙",
                task_stage="movement_execution",
            )

        return InputBatch(
            timestamp=timestamp,
            camera=camera,
            audio=audio,
            pose_features=pose,
            task_behavior=task,
        )

    def close(self) -> None:
        return None

    def _camera_frame(self, timestamp: float, state: str, attention_score: float) -> CameraFrame:
        brightness = 190 if state == "engaged" else 135 if state == "fatigued" else 115
        image = np.full((240, 320, 3), brightness, dtype=np.uint8)
        emotion_probs = {
            "engaged": {"happy": 0.25, "neutral": 0.65, "tired": 0.05},
            "fatigued": {"tired": 0.72, "neutral": 0.18, "sad": 0.10},
            "pain_risk": {"pain": 0.78, "tired": 0.12, "neutral": 0.10},
        }[state]
        return CameraFrame(
            timestamp=timestamp,
            image=image,
            metadata={
                "face_detected": True,
                "attention_score": attention_score,
                "emotion_probs": emotion_probs,
            },
        )

    def _audio_chunk(self, timestamp: float, amplitude: float, transcript: str) -> AudioChunk:
        sample_rate = 16000
        t = np.linspace(0.0, 0.8, int(sample_rate * 0.8), endpoint=False)
        tone = amplitude * np.sin(2.0 * np.pi * 220.0 * t)
        noise = self._rng.normal(0.0, amplitude / 6.0, size=t.shape)
        samples = np.asarray(tone + noise, dtype=np.float32)
        return AudioChunk(
            timestamp=timestamp,
            samples=samples,
            sample_rate=sample_rate,
            metadata={"transcript": transcript, "duration_sec": 0.8},
        )
