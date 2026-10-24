from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np
import pytest

from rehab_affect import demo2_media_analysis as media


@pytest.fixture(scope="module")
def media_tools() -> tuple[str, str]:
    try:
        return media._resolve_tool("ffmpeg"), media._resolve_tool("ffprobe")
    except media.MediaAnalysisError as exc:
        pytest.skip(str(exc))


def _generate(
    ffmpeg: str, path: Path, *, duration: float = 3.2, audio: bool = True,
    silent: bool = False, pts_offset: float = 0, audio_delay: float = 0,
) -> Path:
    command = [ffmpeg, "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
               f"testsrc2=size=160x96:rate=10:duration={duration}"]
    if audio:
        if audio_delay:
            command += ["-itsoffset", str(audio_delay)]
        signal = "0" if silent else "if(lt(t,20),0.2*sin(2*PI*440*t),0)"
        command += ["-f", "lavfi", "-i", f"aevalsrc='{signal}':s=16000:d={duration - audio_delay}"]
    command += ["-c:v", "mpeg4", "-q:v", "2", "-threads", "1"]
    if audio:
        command += ["-c:a", "aac", "-ac", "1", "-ar", "16000"]
    if pts_offset:
        command += ["-output_ts_offset", str(pts_offset)]
    command += [str(path)]
    subprocess.run(command, check=True, capture_output=True, timeout=30)
    return path


@pytest.fixture(scope="module")
def clip(tmp_path_factory, media_tools) -> Path:
    return _generate(media_tools[0], tmp_path_factory.mktemp("generated_media") / "lesson.mp4", duration=22.4)


def _task(source: Path) -> dict:
    return {"task_id": "test_task_01", "course_name": "synthetic course", "subject_id": "unverified_subject",
            "file_path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}


def test_real_video_audio_and_frontend_contract(clip: Path, tmp_path: Path) -> None:
    calls = []
    result = media.process_video_task(_task(clip), tmp_path, lambda pct, stage: calls.append((pct, stage)))
    assert result["analysis_status"] == "evidence_ready"
    assert result["analysis_version"] == media.ANALYSIS_VERSION
    assert result["media"]["duration_sec"] == pytest.approx(22.4, abs=0.1)
    assert result["media"]["width"] == 160
    assert result["media"]["height"] == 96
    assert result["media"]["fps"] == 10
    assert result["media"]["has_audio"] is True
    assert result["media"]["audio_status"] == "extracted"
    assert result["summary"]["segment_count"] == 2
    assert result["summary"]["decoded_frames"] == 224
    assert 22 <= result["summary"]["sampled_frames"] <= 23
    assert result["segments"][0]["end_sec"] == 20
    assert result["segments"][1]["start_sec"] == 20
    assert result["segments"][1]["end_sec"] == pytest.approx(22.4, abs=0.1)
    samples = []
    for segment in result["segments"]:
        assert segment["review_status"] == "unreviewed"
        visual = segment["visual"]
        assert {"sampled_frames", "mean_brightness", "mean_sharpness", "mean_motion"} <= visual.keys()
        assert visual["sampled_frames"] == len(visual["samples"])
        assert 0 < visual["mean_brightness"] < 255
        assert visual["mean_sharpness"] > 0
        assert 0 < visual["mean_motion"] <= 1
        assert segment["audio"]["available"] is True
        samples.extend(visual["samples"])
    assert [s["timestamp_sec"] for s in samples] == list(range(len(samples)))
    assert samples[0]["scene_motion"] is None
    import cv2

    first = samples[0]
    image = cv2.imdecode(np.frombuffer((tmp_path / first["image_path"]).read_bytes(), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    assert image.shape == (96, 160)
    assert float(image.mean()) == pytest.approx(first["brightness"], abs=2)
    assert result["segments"][0]["audio"]["rms"] > 0.1
    assert result["segments"][1]["audio"]["rms"] < 0.02
    with wave.open(str(tmp_path / result["artifacts"]["audio"]), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
        assert wav.getnframes() / 16000 == pytest.approx(22.4, abs=0.02)
    persisted = json.loads((tmp_path / result["artifacts"]["result"]).read_text())
    assert persisted == result
    serialized = json.dumps(result)
    assert str(tmp_path) not in serialized and str(clip) not in serialized
    assert "unverified_subject" not in serialized
    assert "transcript" not in result and "state" not in result
    assert result["summary"]["transcription_performed"] is False
    assert all(isinstance(s, str) for s in result["limitations"])
    assert calls[0] == (0, "validating") and calls[-1] == (100, "evidence_ready")
    assert [c[0] for c in calls] == sorted(c[0] for c in calls)
    assert {"probing", "sampling_video", "extracting_audio", "writing_result"} <= {c[1] for c in calls}


def test_simple_student_analysis_delegates_to_per_person_engine(monkeypatch, tmp_path: Path) -> None:
    from rehab_affect import demo2_student_tracking as tracking
    captured = {}
    def build(segments, run, meta, *, stop_event=None):
        captured.update(segments=segments, run=run, meta=meta, stop_event=stop_event)
        return {"analysis_version": tracking.VERSION, "available": False, "persons": []}
    monkeypatch.setattr(tracking, "build_analysis", build)
    event = threading.Event()
    segments = [{"visual": {"samples": [{"timestamp_sec": 0}]}}]
    result = media._build_simple_student_analysis(segments, tmp_path, {"duration_sec": 1},
                                                   stop_event=event)
    assert result["analysis_version"] == media.SIMPLE_ANALYSIS_VERSION
    assert captured == dict(segments=segments, run=tmp_path, meta={"duration_sec": 1}, stop_event=event)


def test_simple_student_analysis_falls_back_to_sample_ordinal_when_path_is_missing(monkeypatch, tmp_path: Path) -> None:
    from rehab_affect import demo2_student_tracking as tracking
    captured = {}
    class Child:
        returncode = 0
        def communicate(self, input=None, timeout=None):
            if input is not None:
                captured.update(json.loads(input))
            return json.dumps(tracking.unavailable("no_faces")).encode(), None
        def poll(self):
            return 0
    monkeypatch.setattr(tracking.subprocess, "Popen", lambda *a, **kw: Child())
    samples = [{"timestamp_sec": index} for index in range(60)]
    media._build_simple_student_analysis([{"visual": {"samples": samples}}],
                                         tmp_path, {"duration_sec": 60}, max_detection_samples=12)
    assert len(captured["samples"]) == 60
    assert captured["samples"][59] == {"frame": "frame_000059.jpg", "time": 59}


@pytest.mark.parametrize("audio,silent", [(False, False), (True, True)])
def test_absent_audio_is_not_observed_silence(media_tools, tmp_path, audio, silent) -> None:
    source = _generate(media_tools[0], tmp_path / "input.mp4", audio=audio, silent=silent)
    output = tmp_path / "out"
    result = media.process_video_task(_task(source), output)
    assert result["media"]["has_audio"] is audio
    assert result["media"]["audio_status"] == ("extracted" if audio else "absent")
    evidence = result["segments"][0]["audio"]
    assert evidence["available"] is audio
    if audio:
        assert evidence["rms"] == 0
        assert evidence["energy_activity_ratio"] == 0
    else:
        assert evidence["rms"] is None
        assert result["artifacts"]["audio"] is None
        assert not list(output.rglob("*.wav"))


def test_nonzero_pts_rotation_and_delayed_audio(media_tools, tmp_path) -> None:
    ffmpeg, _ = media_tools
    source = _generate(ffmpeg, tmp_path / "offset.mp4", pts_offset=5, audio_delay=1)
    rotated = tmp_path / "rotated.mp4"
    subprocess.run([ffmpeg, "-v", "error", "-y", "-copyts", "-display_rotation:v:0", "90",
                    "-i", str(source), "-c", "copy", str(rotated)], check=True, capture_output=True, timeout=20)
    result = media.process_video_task(_task(rotated), tmp_path / "out")
    assert result["media"]["source_start_sec"] == pytest.approx(5, abs=0.1)
    assert result["media"]["duration_sec"] == pytest.approx(3.2, abs=0.1)
    assert (result["media"]["width"], result["media"]["height"]) == (96, 160)
    assert result["media"]["rotation_degrees"] in {90, 270}
    assert result["segments"][0]["visual"]["samples"][0]["timestamp_sec"] == 0
    import cv2

    frame_path = tmp_path / "out" / result["segments"][0]["visual"]["samples"][0]["image_path"]
    assert cv2.imdecode(np.frombuffer(frame_path.read_bytes(), dtype=np.uint8), cv2.IMREAD_GRAYSCALE).shape == (160, 96)
    with wave.open(str(tmp_path / "out" / result["artifacts"]["audio"]), "rb") as wav:
        data = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(float) / 32768
    assert np.sqrt(np.mean(data[:8000] ** 2)) < 0.001
    assert np.sqrt(np.mean(data[24000:40000] ** 2)) > 0.1


def test_subsecond_video_has_a_real_sample(media_tools, tmp_path) -> None:
    source = _generate(media_tools[0], tmp_path / "short.mp4", duration=0.2, audio=False)
    result = media.process_video_task(_task(source), tmp_path / "out")
    assert result["summary"]["sampled_frames"] == 1
    assert result["summary"]["decoded_frames"] == 2


def test_variable_frame_rate_uses_normalized_sampling_grid(media_tools, tmp_path) -> None:
    source = tmp_path / "vfr.mp4"
    subprocess.run([
        media_tools[0], "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
        "testsrc2=size=160x96:rate=10:duration=4",
        "-vf", "select='if(lt(t,2),1,not(mod(n,2)))'", "-fps_mode", "vfr",
        "-c:v", "mpeg4", "-threads", "1", str(source),
    ], check=True, capture_output=True, timeout=30)
    result = media.process_video_task(_task(source), tmp_path / "out")
    assert result["summary"]["decoded_frames"] == 30
    samples = result["segments"][0]["visual"]["samples"]
    assert [s["timestamp_sec"] for s in samples] == [0, 1, 2, 3]
    assert "not original frame PTS" in result["sampling"]["timestamp_basis"]


@pytest.mark.parametrize("content", [b"", b"this is not a video"])
def test_empty_and_corrupt_files_fail_without_fake_result(media_tools, tmp_path, content) -> None:
    source = tmp_path / "input.mp4"
    source.write_bytes(content)
    output = tmp_path / "out"
    with pytest.raises(media.MediaAnalysisError):
        media.process_video_task(_task(source), output)
    assert not list(output.rglob("analysis.json"))


def test_cancel_cleans_only_its_run(clip, tmp_path) -> None:
    marker = tmp_path / "keep.txt"
    marker.write_text("caller data")
    event = threading.Event()

    def progress(percent, stage):
        if stage == "sampling_video" and percent >= 20:
            event.set()

    with pytest.raises(media.MediaAnalysisCancelled) as exc:
        media.process_video_task(_task(clip), tmp_path, progress, event)
    assert exc.value.code == "cancelled"
    assert list(tmp_path.iterdir()) == [marker]


def test_cancel_during_audio_removes_frames_and_partial_wav(clip, tmp_path) -> None:
    event = threading.Event()

    def progress(percent, stage):
        if stage == "extracting_audio" and percent > 71:
            event.set()

    with pytest.raises(media.MediaAnalysisCancelled):
        media.process_video_task(_task(clip), tmp_path, progress, event)
    assert not list(tmp_path.iterdir())


def test_artifact_budget_cleans_partial_output(clip, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(media, "MAX_OUTPUT_BYTES", 100)
    with pytest.raises(media.MediaAnalysisError) as exc:
        media.process_video_task(_task(clip), tmp_path)
    assert exc.value.code == "resource_limit"
    assert not list(tmp_path.iterdir())


def test_actual_decode_limit_is_enforced(clip, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(media, "MAX_DECODED_FRAMES", 5)
    with pytest.raises(media.MediaAnalysisError) as exc:
        media.process_video_task(_task(clip), tmp_path)
    assert exc.value.code == "resource_limit"
    assert not list(tmp_path.iterdir())


def test_source_change_before_publication_rejects_result(clip, tmp_path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(clip.read_bytes())
    output = tmp_path / "out"

    def progress(percent, stage):
        if stage == "writing_result":
            with source.open("ab") as handle:
                handle.write(b"changed")

    with pytest.raises(media.MediaAnalysisError) as exc:
        media.process_video_task(_task(source), output, progress)
    assert exc.value.code == "source_changed"
    assert not list(output.iterdir())


def test_pre_cancel_does_not_require_tools_or_create_files(tmp_path) -> None:
    event = threading.Event()
    event.set()
    with pytest.raises(media.MediaAnalysisCancelled):
        media.process_video_task({}, tmp_path / "out", stop_event=event)
    assert not (tmp_path / "out").exists()


def test_callback_failure_cleans_partial_run(clip, tmp_path) -> None:
    def progress(percent, stage):
        if stage == "writing_result":
            raise RuntimeError("caller stopped")

    with pytest.raises(RuntimeError, match="caller stopped"):
        media.process_video_task(_task(clip), tmp_path, progress)
    assert not list(tmp_path.iterdir())


def test_checksum_and_resource_limits(clip, tmp_path, monkeypatch) -> None:
    task = {**_task(clip), "sha256": "a" * 64}
    with pytest.raises(media.MediaAnalysisError) as exc:
        media.process_video_task(task, tmp_path / "out")
    assert exc.value.code == "hash_mismatch"
    monkeypatch.setattr(media, "MAX_INPUT_BYTES", 1)
    with pytest.raises(media.MediaAnalysisError) as exc:
        media.process_video_task(_task(clip), tmp_path / "out")
    assert exc.value.code == "resource_limit"


@pytest.mark.parametrize("field,value", [("duration", "10801"), ("width", 9000), ("avg_frame_rate", "999/1")])
def test_probe_rejects_unbounded_metadata(monkeypatch, field, value) -> None:
    stream = {"index": 0, "codec_type": "video", "width": 160, "height": 96,
              "duration": "2", "start_time": "0", "avg_frame_rate": "10/1"}
    stream[field] = value
    monkeypatch.setattr(media, "_pipe_chunks", lambda *a, **kw: iter([json.dumps({"streams": [stream]}).encode()]))
    with pytest.raises(media.MediaAnalysisError) as exc:
        media._probe_media("unused", Path("unused.mp4"), None)
    assert exc.value.code == "resource_limit"


@pytest.mark.parametrize("path", ["https://example.invalid/a.mp4", "file:///tmp/a.mp4", "//server/video.mp4", "C:\\video.mp4:stream"])
def test_remote_paths_and_streams_rejected(path, tmp_path) -> None:
    with pytest.raises(media.MediaAnalysisError) as exc:
        media.process_video_task({"task_id": "task", "file_path": path}, tmp_path)
    assert exc.value.code == "unsafe_path"


def test_playlist_demuxer_is_disabled(media_tools, tmp_path) -> None:
    source = tmp_path / "remote.m3u8"
    source.write_text("#EXTM3U\n#EXTINF:3,\nhttps://example.invalid/private.ts\n#EXT-X-ENDLIST\n")
    with pytest.raises(media.MediaAnalysisError):
        media.process_video_task(_task(source), tmp_path / "out")


def test_output_symlink_rejected(tmp_path) -> None:
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Local account cannot create symlinks")
    with pytest.raises(media.MediaAnalysisError) as exc:
        media._local_path(link / "out")
    assert exc.value.code == "unsafe_path"


@pytest.mark.parametrize("mode,code", [("timeout", "timeout"), ("cancel", "cancelled"), ("fail", "tool_failed"), ("size", "resource_limit")])
def test_subprocess_watchdog_and_limits(mode, code) -> None:
    event = threading.Event()
    script = "import time; time.sleep(10)"
    if mode == "fail":
        script = "import sys; sys.stderr.write('private absolute path'); sys.exit(2)"
    elif mode == "size":
        script = "import sys; sys.stdout.buffer.write(b'x'*1000)"
    timer = threading.Timer(0.2, event.set) if mode == "cancel" else None
    if timer:
        timer.start()
    start = time.monotonic()
    try:
        with pytest.raises(media.MediaAnalysisError) as exc:
            list(media._pipe_chunks([sys.executable, "-c", script], stage="test", stop_event=event,
                                   timeout=0.2 if mode == "timeout" else 5, chunk_size=16, max_bytes=32))
        assert exc.value.code == code
        assert "private absolute" not in str(exc.value)
        assert time.monotonic() - start < 6
    finally:
        if timer:
            timer.cancel()
            timer.join()


def test_environment_tool_override_is_explicit(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("REHAB_FFMPEG", str(tmp_path / "not_installed.exe"))
    with pytest.raises(media.MediaAnalysisError) as exc:
        media._resolve_tool("ffmpeg")
    assert exc.value.code == "missing_dependency"


def test_interleaved_ffmpeg_headers_do_not_drop_numeric_frame_timing() -> None:
    counters = {}
    media._record_diagnostics(b"[showinfo@evidence_video] config in time_base: 1/10, frame_rate: 10/1\n", counters)
    for i, prefix in enumerate((b"[showinfo@evidence_video] ", b"  Stream #1", b"122 kb/s", b"encoder: ")):
        media._record_diagnostics(prefix + f"n: {i} pts: {i} pts_time:{i/10} duration: 1 duration_time:0.1 fmt:yuv420p\n".encode(), counters)
    assert counters["decoded_frames"] == 4
    assert counters["end_pts"] == pytest.approx(0.4)
    assert not counters.get("timing_error")


def test_delayed_audio_does_not_turn_padding_into_observed_silence(media_tools, tmp_path) -> None:
    source = _generate(media_tools[0], tmp_path / "late.mp4", duration=23, audio_delay=21)
    result = media.process_video_task(_task(source), tmp_path / "out")
    first, second = (s["audio"] for s in result["segments"])
    assert first["available"] is False
    assert first["rms"] is None and first["energy_activity_ratio"] is None
    assert first["observed_sample_count"] == 0
    assert first["padded_sample_count"] == 20 * media.AUDIO_RATE
    assert first["coverage_intervals"] == []
    assert first["reason"] == "no_audio_coverage"
    assert second["available"] is True
    assert 0.6 < second["coverage_ratio"] < 0.8
    assert second["reason"] == "partial_audio_coverage"
    assert second["rms"] > 0.1
    assert second["coverage_intervals"][0]["start_sec"] == pytest.approx(21, abs=0.07)
    assert second["sample_count"] == second["observed_sample_count"] + second["padded_sample_count"]


@pytest.mark.parametrize("video_duration,audio_duration", [(3.2, 6), (23, 2)])
def test_video_and_audio_ends_are_measured_independently(media_tools, tmp_path, video_duration, audio_duration) -> None:
    source = tmp_path / "different_ends.mkv"
    subprocess.run([
        media_tools[0], "-v", "error", "-y", "-f", "lavfi", "-i",
        f"testsrc2=size=160x96:rate=10:duration={video_duration}",
        "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=16000:duration={audio_duration}",
        "-c:v", "mpeg4", "-threads", "1", "-c:a", "pcm_s16le", str(source),
    ], check=True, capture_output=True, timeout=30)
    result = media.process_video_task(_task(source), tmp_path / "out")
    assert result["media"]["duration_sec"] == pytest.approx(video_duration, abs=0.001)
    assert result["media"]["duration_basis"] == "decoded_video_frame_end"
    assert result["segments"][-1]["end_sec"] == pytest.approx(video_duration, abs=0.001)
    assert result["summary"]["decoded_frames"] == round(video_duration * 10)
    with wave.open(str(tmp_path / "out" / result["artifacts"]["audio"]), "rb") as wav:
        assert wav.getnframes() == round(video_duration * media.AUDIO_RATE)
    if audio_duration < video_duration:
        assert result["segments"][0]["audio"]["coverage_ratio"] == pytest.approx(0.1)
        assert result["segments"][1]["audio"]["available"] is False
        assert result["segments"][1]["audio"]["rms"] is None


@pytest.mark.parametrize("gap_start,gap_end,coverage_bounds", [(2, 4, (0.6, 0.75)), (1, 1.04, (0.98, 1.0))])
def test_internal_audio_gap_is_not_counted_as_observed_silence(media_tools, tmp_path, gap_start, gap_end, coverage_bounds) -> None:
    source = tmp_path / "gap.mkv"
    subprocess.run([
        media_tools[0], "-v", "error", "-y", "-f", "lavfi", "-i",
        "testsrc2=size=160x96:rate=10:duration=6",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=6",
        "-af", f"aselect='not(between(t,{gap_start},{gap_end}))'", "-c:v", "mpeg4", "-threads", "1",
        "-c:a", "pcm_s16le", str(source),
    ], check=True, capture_output=True, timeout=30)
    result = media.process_video_task(_task(source), tmp_path / "out")
    evidence = result["segments"][0]["audio"]
    assert len(evidence["coverage_intervals"]) == 2
    assert coverage_bounds[0] < evidence["coverage_ratio"] < coverage_bounds[1]
    # A sine's RMS remains unchanged when the two-second gap is excluded.
    assert evidence["rms"] == pytest.approx(0.125 / np.sqrt(2), abs=0.004)
    intervals = evidence["coverage_intervals"]
    a, b = (round(sec * media.AUDIO_RATE) for sec in (intervals[0]["end_sec"], intervals[1]["start_sec"]))
    with wave.open(str(tmp_path / "out" / result["artifacts"]["audio"]), "rb") as wav:
        data = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
    assert np.max(np.abs(data[a:b])) == 0


@pytest.mark.parametrize("duration", [0.1, 19.9, 20, 20.1, 40.1])
def test_tail_and_window_boundaries_cover_actual_video(media_tools, tmp_path, duration) -> None:
    source = _generate(media_tools[0], tmp_path / "tail.mp4", duration=duration, audio=False)
    result = media.process_video_task(_task(source), tmp_path / "out")
    segments = result["segments"]
    assert segments[0]["start_sec"] == 0
    assert segments[-1]["end_sec"] == pytest.approx(duration)
    assert all(a["end_sec"] == b["start_sec"] for a, b in zip(segments, segments[1:]))
    samples = [sample for segment in segments for sample in segment["visual"]["samples"]]
    assert all(0 <= sample["timestamp_sec"] < duration for sample in samples)
    assert result["summary"]["decoded_frames"] == round(duration * 10)
    assert result["summary"]["sampled_frames"] == len(samples)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotation_preserves_pixel_orientation(media_tools, tmp_path, rotation) -> None:
    import cv2

    # A single source frame isolates orientation from fps-filter selection.
    source = _generate(media_tools[0], tmp_path / "source.mp4", duration=0.1, audio=False)
    rotated = tmp_path / "rotated.mp4"
    subprocess.run([media_tools[0], "-v", "error", "-y", "-display_rotation:v:0", str(rotation),
                    "-i", str(source), "-c", "copy", str(rotated)], check=True, capture_output=True, timeout=20)
    output = tmp_path / "out"
    result = media.process_video_task(_task(rotated), output)
    path = output / result["segments"][0]["visual"]["samples"][0]["image_path"]
    actual = cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    raw = subprocess.run([media_tools[0], "-v", "error", "-i", str(source), "-frames:v", "1",
                          "-pix_fmt", "gray", "-f", "rawvideo", "pipe:1"],
                         check=True, capture_output=True, timeout=20).stdout
    expected = np.rot90(np.frombuffer(raw, dtype=np.uint8).reshape(96, 160), rotation // 90)
    assert actual.shape == expected.shape
    assert np.mean(np.abs(actual.astype(float) - expected)) < 3


def test_audio_before_video_uses_actual_video_origin(media_tools, tmp_path) -> None:
    source = tmp_path / "early_audio.mp4"
    subprocess.run([
        media_tools[0], "-v", "error", "-y", "-itsoffset", "2", "-f", "lavfi", "-i",
        "testsrc2=size=160x96:rate=10:duration=3",
        "-f", "lavfi", "-i", "aevalsrc='if(lt(t,2),0,0.2*sin(2*PI*440*t))':s=16000:d=5",
        "-map", "0:v", "-map", "1:a", "-fps_mode", "passthrough", "-c:v", "mpeg4",
        "-threads", "1", "-c:a", "aac", str(source),
    ], check=True, capture_output=True, timeout=30)
    result = media.process_video_task(_task(source), tmp_path / "out")
    assert result["media"]["source_start_sec"] == pytest.approx(2)
    assert result["media"]["duration_sec"] == pytest.approx(3)
    with wave.open(str(tmp_path / "out" / result["artifacts"]["audio"]), "rb") as wav:
        data = np.frombuffer(wav.readframes(8000), dtype="<i2").astype(float) / 32768
    assert np.sqrt(np.mean(data ** 2)) > 0.1


def test_fractional_audio_end_and_window_accounting(media_tools, tmp_path) -> None:
    source = tmp_path / "fractional.mp4"
    subprocess.run([
        media_tools[0], "-v", "error", "-y", "-f", "lavfi", "-i",
        "testsrc2=size=160x96:rate=30:duration=20.033333333",
        "-f", "lavfi", "-i", "sine=sample_rate=44100:duration=20.033333333",
        "-c:v", "mpeg4", "-threads", "1", "-c:a", "aac", str(source),
    ], check=True, capture_output=True, timeout=30)
    result = media.process_video_task(_task(source), tmp_path / "out")
    audio = [s["audio"] for s in result["segments"]]
    assert audio[0]["sample_count"] == 320000
    assert abs(sum(a["sample_count"] for a in audio) - result["media"]["duration_sec"] * 16000) <= 1
    assert all(0 <= a["observed_sample_count"] <= a["sample_count"] for a in audio)


def test_failure_at_completion_closes_decoders_and_cleans_run(clip, tmp_path) -> None:
    event = threading.Event()

    def progress(percent, stage):
        if percent == 100:
            event.set()

    with pytest.raises(media.MediaAnalysisCancelled):
        media.process_video_task(_task(clip), tmp_path, progress, event)
    assert not list(tmp_path.iterdir())


def test_same_task_rerun_keeps_previous_artifacts(clip, tmp_path) -> None:
    first = media.process_video_task(_task(clip), tmp_path)
    result_path = tmp_path / first["artifacts"]["result"]
    original = result_path.read_bytes()
    second = media.process_video_task(_task(clip), tmp_path)
    assert first["artifacts"]["result"] != second["artifacts"]["result"]
    assert result_path.read_bytes() == original
    assert (tmp_path / second["artifacts"]["audio"]).is_file()


def test_truncated_decodable_container_fails_and_removes_partial_run(clip, tmp_path, media_tools) -> None:
    source = tmp_path / "truncated.mp4"
    subprocess.run([media_tools[0], "-v", "error", "-y", "-i", str(clip), "-c", "copy",
                    "-movflags", "+faststart", str(source)], check=True, capture_output=True, timeout=20)
    with source.open("r+b") as handle:
        handle.truncate(source.stat().st_size // 2)
    output = tmp_path / "out"
    with pytest.raises(media.MediaAnalysisError):
        media.process_video_task(_task(source), output)
    assert not list(output.glob("media_*"))


def test_real_engine_artifact_is_playable_through_authenticated_api(clip, tmp_path, monkeypatch) -> None:
    """Join the real engine's relative path to store publication and HTTP."""
    import base64
    import http.client
    import io

    from src.rehab_affect import scenario_lab_server as server
    from src.rehab_affect.student_record_store import Demo2StudentRecordStore

    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "EngineHttpTest-")
    store = Demo2StudentRecordStore(tmp_path / "test.sqlite3", tmp_path / "documents")
    account = store.authenticate_account("school_uploader_01", "EngineHttpTest-school_uploader_01")
    token = store.create_account_session(account)["token"]
    content = clip.read_bytes()
    task = store.create_video_task({
        "account_id": account["account_id"], "channel_id": "channel_1", "session_id": "engine-http",
        "course_id": "engine-http", "course_name": "Synthetic test", "uploader_name": "Test",
        "filename": "synthetic.mp4", "byte_size": len(content), "total_chunks": 1,
    })
    task_id = task["task_id"]
    store.append_video_chunk({"task_id": task_id, "chunk_index": 0,
                              "content_base64": base64.b64encode(content).decode("ascii")})
    claimed = store.claim_next_video_analysis()
    result = media.process_video_task(claimed, Path(claimed["analysis_dir"]))
    store.finish_video_analysis(task_id, result)
    expected = (Path(claimed["analysis_dir"]) / result["artifacts"]["audio"]).read_bytes()
    monkeypatch.setattr(server, "get_demo2_student_store", lambda: store)
    monkeypatch.setattr(server, "load_seewo_demo2", lambda: {"students": []})
    handler = server.create_handler(scenario_dir=tmp_path, model_path=tmp_path / "unused", policy_name="rule")
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        for range_header, status, data in [(None, 200, expected), ("bytes=44-59", 206, expected[44:60])]:
            connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=10)
            try:
                headers = {"Cookie": "rehab_demo2_session=" + token}
                if range_header:
                    headers["Range"] = range_header
                connection.request("GET", f"/api/v1/demo2/upload/media?id={task_id}&asset=audio", headers=headers)
                response = connection.getresponse()
                body = response.read()
                assert response.status == status
                assert response.getheader("Content-Type") == "audio/wav"
                assert body == data
                if status == 200:
                    with wave.open(io.BytesIO(body), "rb") as wav:
                        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
                        assert wav.getnframes() / 16000 == pytest.approx(22.4, abs=0.02)
            finally:
                connection.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(5)
