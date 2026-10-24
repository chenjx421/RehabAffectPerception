from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from rehab_affect import demo2_frame_preview as preview


@pytest.fixture(scope="module")
def media_tools() -> tuple[str, str]:
    try:
        return (preview.media_analysis._resolve_tool("ffmpeg"),
                preview.media_analysis._resolve_tool("ffprobe"))
    except preview.media_analysis.MediaAnalysisError as exc:
        pytest.skip(str(exc))


def _generate(ffmpeg: str, path: Path, *, size="320x180", duration=1,
              rate=4, vf=None, audio=False, offset=0) -> Path:
    command = [ffmpeg, "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
               f"color=c=red:size={size}:rate={rate}:duration={duration}"]
    if audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"]
    if vf:
        command += ["-vf", vf]
    command += ["-c:v", "mpeg4", "-q:v", "2", "-g", "12", "-threads", "1"]
    if audio:
        command += ["-c:a", "aac"]
    if offset:
        command += ["-output_ts_offset", str(offset)]
    command += [str(path)]
    subprocess.run(command, check=True, capture_output=True, timeout=30,
                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    return path


@pytest.fixture(scope="module")
def clip(tmp_path_factory, media_tools) -> Path:
    return _generate(media_tools[0], tmp_path_factory.mktemp("preview_synthetic") / "color.mp4",
                     duration=2, audio=True)


@pytest.fixture
def dummy_source(tmp_path) -> Path:
    path = tmp_path / "synthetic.mp4"
    path.write_bytes(b"synthetic source for mocked tool tests")
    return path


def _decode(result: dict) -> np.ndarray:
    assert set(result) == {"image_bytes", "content_type", "width", "height", "requested_time_sec"}
    assert isinstance(result["image_bytes"], bytes)
    assert 0 < len(result["image_bytes"]) <= 4 * 1024 * 1024
    assert result["content_type"] == "image/jpeg"
    decoded = cv2.imdecode(np.frombuffer(result["image_bytes"], dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    assert decoded.shape == (result["height"], result["width"], 3)
    return decoded


def _red_jpeg(width=40, height=20) -> bytes:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:, :, 2] = 255
    ok, encoded = cv2.imencode(".jpg", frame)
    assert ok
    return encoded.tobytes()


def _mock_probe(monkeypatch, payload=None):
    monkeypatch.setattr(preview.media_analysis, "_resolve_tool", lambda name: name)
    payload = payload if payload is not None else {"streams": [{"index": 0, "width": 320, "height": 180}]}
    monkeypatch.setattr(preview, "_run_tool", lambda command, deadline, max_bytes:
                        json.dumps(payload).encode() if command[0] == "ffprobe" else _red_jpeg())


def test_color_contract_read_only_memory_only(clip, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    before_files = set(clip.parent.iterdir())
    before_stat = clip.stat()
    before_hash = hashlib.sha256(clip.read_bytes()).hexdigest()
    result = preview.extract_preview(clip, 0.625)
    image = _decode(result)
    assert (result["width"], result["height"]) == (320, 180)
    assert result["requested_time_sec"] == 0.625
    blue, green, red = image.mean(axis=(0, 1))
    assert red > 220 and green < 25 and blue < 25
    assert set(clip.parent.iterdir()) == before_files
    assert not list(tmp_path.iterdir())
    assert clip.stat().st_mtime_ns == before_stat.st_mtime_ns
    assert hashlib.sha256(clip.read_bytes()).hexdigest() == before_hash


@pytest.mark.parametrize("size,expected", [
    ("2560x1440", (1920, 1080)), ("1440x2560", (1080, 1920)),
    ("2048x2048", (1920, 1920)), ("5120x720", (1920, 270)),
    ("160x96", (160, 96)),
])
def test_aspect_ratio_hd_and_no_upscale(media_tools, tmp_path, size, expected):
    source = _generate(media_tools[0], tmp_path / "dimensions.mp4", size=size, duration=0.25)
    result = preview.extract_preview(source, 0)
    _decode(result)
    assert (result["width"], result["height"]) == expected


@pytest.mark.parametrize("sar,expected", [("2/1", (320, 90)), ("1/2", (160, 180))])
def test_non_square_pixels_preserve_display_aspect_without_upscale(media_tools, tmp_path, sar, expected):
    source = _generate(media_tools[0], tmp_path / "aspect.mp4", vf=f"setsar={sar}")
    result = preview.extract_preview(source, 0)
    _decode(result)
    assert (result["width"], result["height"]) == expected


def test_rotation_and_nonzero_pts(media_tools, tmp_path):
    source = _generate(media_tools[0], tmp_path / "offset.mp4", offset=5)
    rotated = tmp_path / "rotated.mp4"
    subprocess.run([media_tools[0], "-v", "error", "-nostdin", "-y", "-copyts",
                    "-display_rotation:v:0", "90", "-i", str(source), "-c", "copy", str(rotated)],
                   check=True, capture_output=True, timeout=15,
                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    result = preview.extract_preview(rotated, 0.25)
    _decode(result)
    assert (result["width"], result["height"]) == (180, 320)


def test_two_hour_video_uses_input_seek_and_shared_deadline(media_tools, tmp_path, monkeypatch):
    source = _generate(media_tools[0], tmp_path / "long.mp4", size="64x48", rate=1, duration=7201,
                       vf="drawbox=x=0:y=0:w=iw:h=ih:color=blue:t=fill:enable='gte(t,7000)'")
    commands = []
    original = preview._run_tool

    def record(command, deadline, max_bytes):
        commands.append((command, deadline, max_bytes))
        return original(command, deadline, max_bytes)

    monkeypatch.setattr(preview, "_run_tool", record)
    started = time.monotonic()
    result = preview.extract_preview(source, 7199.25)
    assert time.monotonic() - started < preview.PREVIEW_TIMEOUT_SEC
    image = _decode(result)
    assert image[:, :, 0].mean() > 220 and image[:, :, 2].mean() < 25
    assert result["requested_time_sec"] == 7199.25
    assert len(commands) == 2 and commands[0][1] == commands[1][1]
    command = commands[1][0]
    assert command.index("-ss") < command.index("-i")
    assert command[command.index("-ss") + 1] == "7199.250000000"
    assert command[command.index("-frames:v") + 1] == "1"
    assert command[command.index("-map") + 1] == "0:0"
    for flag in ("-an", "-sn", "-dn"):
        assert flag in command[:command.index("-i")]
        assert flag in command[command.index("-i") + 2:]
    assert command[command.index("-protocol_whitelist") + 1] == "file"
    assert command[command.index("-max_pixels") + 1] == str(preview.media_analysis.MAX_PIXELS)
    assert command[-1] == "pipe:1"


@pytest.mark.parametrize("requested", [-1, float("nan"), float("inf"), -float("inf"),
                                          10800.01, 10**500, True, "1", None])
def test_invalid_time_rejected_before_tool_or_file_access(monkeypatch, requested):
    monkeypatch.setattr(preview, "_local_source", lambda *args: pytest.fail("must reject time first"))
    with pytest.raises(preview.PreviewError) as exc:
        preview.extract_preview(Path("never-open.mp4"), requested)
    assert exc.value.code == "invalid_time"


@pytest.mark.parametrize("source", [Path("https://example.test/video.mp4"),
    Path("file:///tmp/video.mp4"), Path("concat:one|two"), Path("//server/share/video.mp4"),
    Path(r"\\server\share\video.mp4"), Path("C:/video.mp4:stream"), Path("bad\x00path")])
def test_remote_protocol_and_alternate_stream_paths_rejected(source, monkeypatch):
    monkeypatch.setattr(preview.media_analysis, "_resolve_tool", lambda *args: pytest.fail("tool started"))
    with pytest.raises(preview.PreviewError) as exc:
        preview.extract_preview(source, 0)
    assert exc.value.code == "unsafe_path"


def test_requires_path_object():
    with pytest.raises(preview.PreviewError) as exc:
        preview.extract_preview("local.mp4", 0)
    assert exc.value.code == "invalid_input"


@pytest.mark.parametrize("kind,code", [("missing", "io_error"), ("directory", "invalid_input"),
                                       ("empty", "resource_limit")])
def test_missing_directory_and_empty_sources(tmp_path, monkeypatch, kind, code):
    path = tmp_path / "source.mp4"
    if kind == "directory":
        path.mkdir()
    if kind == "empty":
        path.touch()
    monkeypatch.setattr(preview.media_analysis, "_resolve_tool", lambda *args: pytest.fail("tool started"))
    with pytest.raises(preview.PreviewError) as exc:
        preview.extract_preview(path, 0)
    assert exc.value.code == code


@pytest.mark.parametrize("link_parent", [False, True])
def test_rejects_symlink_at_file_or_parent(dummy_source, tmp_path, link_parent):
    link = tmp_path / "link"
    try:
        link.symlink_to(dummy_source.parent if link_parent else dummy_source, target_is_directory=link_parent)
    except OSError:
        pytest.skip("OS does not permit test symlinks")
    with pytest.raises(preview.PreviewError) as exc:
        preview.extract_preview(link / dummy_source.name if link_parent else link, 0)
    assert exc.value.code == "unsafe_path"


def test_reparse_point_parent_rejected_without_os_privileges(dummy_source, monkeypatch):
    original = Path.lstat

    def reparse(path, *args, **kwargs):
        if path == dummy_source.parent:
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", reparse)
    with pytest.raises(preview.PreviewError) as exc:
        preview.extract_preview(dummy_source, 0)
    assert exc.value.code == "unsafe_path"


@pytest.mark.parametrize("link_parent", [False, True])
def test_symlink_policy_without_os_privileges(dummy_source, monkeypatch, link_parent):
    original = Path.lstat
    link = dummy_source.parent if link_parent else dummy_source

    def linked(path, *args, **kwargs):
        if path == link:
            return SimpleNamespace(st_mode=stat.S_IFLNK, st_file_attributes=0)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", linked)
    with pytest.raises(preview.PreviewError) as exc:
        preview.extract_preview(dummy_source, 0)
    assert exc.value.code == "unsafe_path"


def test_expanded_home_cannot_bypass_remote_path_policy(monkeypatch):
    monkeypatch.setattr(Path, "expanduser", lambda path: Path("//server/share/video.mp4"))
    monkeypatch.setattr(preview.media_analysis, "_local_path", lambda *args: pytest.fail("remote stat"))
    with pytest.raises(preview.PreviewError) as exc:
        preview.extract_preview(Path("~/video.mp4"), 0)
    assert exc.value.code == "unsafe_path"


@pytest.mark.skipif(os.name != "nt", reason="Windows mapped network drive policy")
def test_mapped_network_drive_rejected_before_stat(dummy_source, monkeypatch):
    import ctypes

    monkeypatch.setattr(ctypes.windll.kernel32, "GetDriveTypeW", lambda root: 4)
    monkeypatch.setattr(preview.media_analysis, "_local_path", lambda *args: pytest.fail("network stat"))
    with pytest.raises(preview.PreviewError) as exc:
        preview.extract_preview(dummy_source, 0)
    assert exc.value.code == "unsafe_path"


@pytest.mark.parametrize("width,height", [(8193, 10), (10, 8193), (4096, 2161), (0, 100)])
def test_source_dimension_and_pixel_caps_before_decode(dummy_source, monkeypatch, width, height):
    _mock_probe(monkeypatch, {"streams": [{"index": 0, "width": width, "height": height}]})
    with pytest.raises(preview.PreviewError) as exc:
        preview.extract_preview(dummy_source, 0)
    assert exc.value.code == "resource_limit"


def test_source_byte_limit(dummy_source, monkeypatch):
    monkeypatch.setattr(preview.media_analysis, "MAX_INPUT_BYTES", 4)
    with pytest.raises(preview.PreviewError) as exc:
        preview.extract_preview(dummy_source, 0)
    assert exc.value.code == "resource_limit"


@pytest.mark.parametrize("payload", [{}, {"streams": []}, {"streams": [None]},
                                     {"streams": [{"index": -1, "width": 320, "height": 180}]}])
def test_bad_metadata(dummy_source, monkeypatch, payload):
    _mock_probe(monkeypatch, payload)
    with pytest.raises(preview.PreviewError) as exc:
        preview.extract_preview(dummy_source, 0)
    assert exc.value.code == "invalid_media"


def test_missing_tool_is_custom_error_and_releases_slot(dummy_source, monkeypatch):
    def unavailable(name):
        raise preview.media_analysis.MediaAnalysisError("missing_dependency", "Local tool unavailable.")

    monkeypatch.setattr(preview.media_analysis, "_resolve_tool", unavailable)
    for _ in range(2):
        with pytest.raises(preview.PreviewError) as exc:
            preview.extract_preview(dummy_source, 0)
        assert exc.value.code == "missing_dependency"
        assert exc.value.message == str(exc.value)


def test_busy_rejected_without_waiting(dummy_source):
    assert preview._PREVIEW_SLOT.acquire(blocking=False)
    try:
        started = time.monotonic()
        with pytest.raises(preview.PreviewError) as exc:
            preview.extract_preview(dummy_source, 0)
        assert exc.value.code == "busy"
        assert time.monotonic() - started < 0.5
    finally:
        preview._PREVIEW_SLOT.release()


@pytest.mark.parametrize("stage", ["ffprobe", "ffmpeg"])
def test_source_change_rejected(dummy_source, monkeypatch, stage):
    _mock_probe(monkeypatch)
    original = preview._run_tool

    def change(command, deadline, max_bytes):
        raw = original(command, deadline, max_bytes)
        if command[0] == stage:
            dummy_source.write_bytes(b"changed synthetic source")
        return raw

    monkeypatch.setattr(preview, "_run_tool", change)
    with pytest.raises(preview.PreviewError) as exc:
        preview.extract_preview(dummy_source, 0)
    assert exc.value.code == "source_changed"


def test_audio_only_and_corrupt_media_fail(media_tools, tmp_path):
    audio = tmp_path / "audio.m4a"
    subprocess.run([media_tools[0], "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=0.25", "-c:a", "aac", str(audio)],
                   check=True, capture_output=True, timeout=15,
                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"not a media file")
    for source, code in [(audio, "invalid_media"), (corrupt, "tool_failed")]:
        with pytest.raises(preview.PreviewError) as exc:
            preview.extract_preview(source, 0)
        assert exc.value.code == code
        assert str(source) not in str(exc.value)


def test_playlist_demuxers_remain_disabled(media_tools, tmp_path):
    source = tmp_path / "playlist.m3u8"
    source.write_text("#EXTM3U\n#EXTINF:1,\nhttps://example.invalid/no-request.ts\n", encoding="ascii")
    with pytest.raises(preview.PreviewError) as exc:
        preview.extract_preview(source, 0)
    assert exc.value.code == "tool_failed"


def test_past_end_never_silently_returns_another_frame(clip):
    with pytest.raises(preview.PreviewError) as exc:
        preview.extract_preview(clip, 2.0)
    assert exc.value.code == "no_frame"


def _record_children(monkeypatch):
    original = subprocess.Popen
    children = []

    def record(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append((child, kwargs))
        return child

    monkeypatch.setattr(preview.subprocess, "Popen", record)
    return children


def _assert_clean(children):
    assert children
    for child, kwargs in children:
        assert child.poll() is not None
        assert child.stdout.closed
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["shell"] is False
        if os.name == "nt":
            assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert not any(t.name == "frame-preview-stdout" for t in threading.enumerate())


@pytest.mark.parametrize("script", ["import time; time.sleep(30)",
    "import os,time; os.close(1); time.sleep(30)",
    "import os,time; os.write(1,b'x'); time.sleep(30)"])
def test_hanging_child_or_eof_killed_with_bounded_timeout(monkeypatch, script):
    children = _record_children(monkeypatch)
    started = time.monotonic()
    with pytest.raises(preview.PreviewError) as exc:
        preview._run_tool([sys.executable, "-B", "-c", script], started + 1.5, 1024)
    assert exc.value.code == "timeout"
    assert time.monotonic() - started < 1.5
    _assert_clean(children)


def test_stdout_flood_is_stopped_before_buffering_unbounded_output(monkeypatch):
    children = _record_children(monkeypatch)
    with pytest.raises(preview.PreviewError) as exc:
        preview._run_tool([sys.executable, "-B", "-c",
                           "import os; chunk=b'x'*65536\nwhile True: os.write(1,chunk)"],
                          time.monotonic() + 3, 128 * 1024)
    assert exc.value.code == "resource_limit"
    _assert_clean(children)


def test_stderr_is_discarded_no_window_no_report_and_exit_failure_cleaned(monkeypatch):
    children = _record_children(monkeypatch)
    monkeypatch.setenv("FFREPORT", "file=must-not-write.log")
    script = "import os; assert 'FFREPORT' not in os.environ; os.write(2,b'private path'*100000); os.write(1,b'ok')"
    assert preview._run_tool([sys.executable, "-B", "-c", script], time.monotonic() + 3, 2) == b"ok"
    with pytest.raises(preview.PreviewError) as exc:
        preview._run_tool([sys.executable, "-B", "-c", "import sys; sys.exit(7)"],
                          time.monotonic() + 3, 1024)
    assert exc.value.code == "tool_failed"
    assert "private path" not in str(exc.value)
    _assert_clean(children)


def test_jpeg_over_byte_budget_fails(clip, monkeypatch):
    children = _record_children(monkeypatch)
    monkeypatch.setattr(preview, "MAX_JPEG_BYTES", 100)
    with pytest.raises(preview.PreviewError) as exc:
        preview.extract_preview(clip, 0)
    assert exc.value.code == "resource_limit"
    _assert_clean(children)


def test_probe_budget_fails(clip, monkeypatch):
    children = _record_children(monkeypatch)
    monkeypatch.setattr(preview, "MAX_PROBE_BYTES", 10)
    with pytest.raises(preview.PreviewError) as exc:
        preview.extract_preview(clip, 0)
    assert exc.value.code == "resource_limit"
    assert len(children) == 1
    _assert_clean(children)


def test_probe_and_decode_do_not_receive_separate_timeout_budgets(dummy_source, monkeypatch):
    run_real = preview._run_tool
    _mock_probe(monkeypatch)
    monkeypatch.setattr(preview, "PREVIEW_TIMEOUT_SEC", 1.6)
    original = preview._run_tool
    children = _record_children(monkeypatch)
    calls = []

    def slow_probe(command, deadline, max_bytes):
        calls.append(deadline)
        if command[0] == "ffprobe":
            time.sleep(0.6)
            return original(command, deadline, max_bytes)
        return run_real([sys.executable, "-B", "-c", "import time; time.sleep(30)"], deadline, max_bytes)

    monkeypatch.setattr(preview, "_run_tool", slow_probe)
    started = time.monotonic()
    with pytest.raises(preview.PreviewError) as exc:
        preview.extract_preview(dummy_source, 0)
    assert exc.value.code == "timeout"
    assert len(calls) == 2 and calls[0] == calls[1]
    assert time.monotonic() - started < 1.6
    _assert_clean(children)


def test_public_default_eight_second_timeout_reaps_hanging_tool(dummy_source, monkeypatch):
    run_real = preview._run_tool
    monkeypatch.setattr(preview.media_analysis, "_resolve_tool", lambda name: name)
    monkeypatch.setattr(preview, "_run_tool", lambda command, deadline, max_bytes:
                        run_real([sys.executable, "-B", "-c", "import time; time.sleep(30)"],
                                 deadline, max_bytes))
    assert preview.PREVIEW_TIMEOUT_SEC == 8.0
    children = _record_children(monkeypatch)
    started = time.monotonic()
    with pytest.raises(preview.PreviewError) as exc:
        preview.extract_preview(dummy_source, 0)
    assert exc.value.code == "timeout"
    assert 7 <= time.monotonic() - started < 8
    _assert_clean(children)


def test_reader_start_failure_reaps_process(monkeypatch):
    children = _record_children(monkeypatch)

    def fail(thread):
        raise RuntimeError("cannot allocate a thread")

    monkeypatch.setattr(threading.Thread, "start", fail)
    with pytest.raises(preview.PreviewError) as exc:
        preview._run_tool([sys.executable, "-B", "-c", "import time; time.sleep(30)"],
                          time.monotonic() + 3, 1024)
    assert exc.value.code == "tool_io_failed"
    _assert_clean(children)


def test_deadline_expired_never_starts_process(monkeypatch):
    monkeypatch.setattr(preview.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("process started"))
    with pytest.raises(preview.PreviewError) as exc:
        preview._run_tool(["ffmpeg"], time.monotonic() - 1, 10)
    assert exc.value.code == "timeout"


def test_tool_start_failure_is_custom(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("private executable path")

    monkeypatch.setattr(preview.subprocess, "Popen", fail)
    with pytest.raises(preview.PreviewError) as exc:
        preview._run_tool(["ffmpeg"], time.monotonic() + 3, 1024)
    assert exc.value.code == "tool_start_failed"
    assert "private executable path" not in str(exc.value)


@pytest.mark.parametrize("data", [b"bad", b"\xff\xd8\xff\xd9",
    b"\xff\xd8\xff\xc0\x00\x00\xff\xd9", b"\xff\xd8\xff\xe0\xff\xff\xff\xd9"])
def test_invalid_jpeg_header_rejected(data):
    with pytest.raises(preview.PreviewError) as exc:
        preview._jpeg_dimensions(data)
    assert exc.value.code == "invalid_media"


def test_no_frame_and_oversized_jpeg_header_rejected():
    with pytest.raises(preview.PreviewError) as exc:
        preview._jpeg_dimensions(b"")
    assert exc.value.code == "no_frame"
    data = b"\xff\xd8\xff\xc0" + struct.pack(">HBHHB", 8, 8, 1921, 1921, 3) + b"\xff\xd9"
    with pytest.raises(preview.PreviewError) as exc:
        preview._jpeg_dimensions(data)
    assert exc.value.code == "resource_limit"
