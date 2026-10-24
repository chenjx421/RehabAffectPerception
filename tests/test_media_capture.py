from rehab_affect.media_capture import build_capture_manifest


def test_capture_failure_cannot_be_marked_completed():
    manifest = build_capture_manifest(
        session_id="s1",
        video_path="video.mp4",
        audio_path="audio.wav",
        video_ok=True,
        audio_ok=False,
        started_at="2026-09-15T10:00:00+00:00",
        error="microphone_unavailable",
    )
    assert manifest.status == "capture_failed"
    assert manifest.as_dict()["error"] == "microphone_unavailable"
