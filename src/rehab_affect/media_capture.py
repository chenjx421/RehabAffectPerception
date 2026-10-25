"""Optional hardware capture adapters for the school pilot.

Capture is deliberately separate from scoring: a failed camera or microphone
must leave the lesson in ``capture_failed`` and cannot produce a student score.
The module uses lazy imports so the existing Windows upload workflow still works
without camera/audio drivers installed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CaptureManifest:
    session_id: str
    video_path: str
    audio_path: str | None
    started_at: str
    ended_at: str | None
    video_ok: bool
    audio_ok: bool
    status: str
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def capture_preflight(*, camera_index: int = 0, microphone: bool = True) -> dict[str, Any]:
    """Check hardware availability without opening a long-running recording."""
    camera_ok = False
    camera_error = None
    try:
        import cv2

        capture = cv2.VideoCapture(camera_index)
        camera_ok = bool(capture.isOpened())
        capture.release()
        if not camera_ok:
            camera_error = "camera_unavailable"
    except Exception as exc:  # optional dependency or driver failure
        camera_error = type(exc).__name__
    audio_ok = False
    audio_error = None
    if microphone:
        try:
            import sounddevice  # noqa: F401

            audio_ok = True
        except Exception as exc:
            audio_error = type(exc).__name__
    return {
        "camera": {"ok": camera_ok, "error": camera_error},
        "microphone": {"ok": audio_ok, "error": audio_error} if microphone else {"ok": False, "skipped": True},
        "ready": camera_ok and (audio_ok if microphone else True),
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def build_capture_manifest(
    *,
    session_id: str,
    video_path: Path,
    audio_path: Path | None,
    video_ok: bool,
    audio_ok: bool,
    started_at: str,
    ended_at: str | None = None,
    error: str | None = None,
) -> CaptureManifest:
    status = "completed" if video_ok and (audio_path is None or audio_ok) else "capture_failed"
    return CaptureManifest(
        session_id=session_id,
        video_path=str(video_path),
        audio_path=str(audio_path) if audio_path else None,
        started_at=started_at,
        ended_at=ended_at,
        video_ok=video_ok,
        audio_ok=audio_ok,
        status=status,
        error=error,
    )
