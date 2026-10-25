from __future__ import annotations

import copy
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

import cv2 as cv
import numpy as np
import pytest

from rehab_affect import demo2_roi_tracking as tracking


def _texture(size=48):
    rng = np.random.default_rng(317)
    return cv.resize(rng.integers(30, 230, (12, 12), dtype=np.uint8), (size, size), interpolation=cv.INTER_NEAREST)


def _scene(x, y, *, size=(320, 192), patch=None):
    image = np.full((size[1], size[0]), 30, np.uint8)
    if patch is not None:
        h, w = patch.shape
        left, top, right, bottom = max(x, 0), max(y, 0), min(x + w, size[0]), min(y + h, size[1])
        if right > left and bottom > top:
            image[top:bottom, left:right] = patch[top - y:bottom - y, left - x:right - x]
    return image


def _samples(tmp_path, images, *, suffix=".png", times=None):
    samples = []
    for index, image in enumerate(images):
        path = tmp_path / f"synthetic-{index}{suffix}"
        ok, encoded = cv.imencode(suffix, image)
        assert ok
        path.write_bytes(encoded.tobytes())
        samples.append({"frame_key": f"frame_{index}", "time_sec": float(index) if times is None else times[index], "path": path})
    return samples


def _box(x=70, y=60, w=48, h=48, width=320, height=192):
    return {"x": x / width, "y": y / height, "width": w / width, "height": h / height}


def _assert_error(samples, box, code):
    with pytest.raises(tracking.TrackingError) as exc:
        tracking.track_frames(samples, box)
    assert exc.value.code == code
    assert exc.value.message == str(exc.value)
    assert "PRIVATE_" not in str(exc.value)


@pytest.fixture
def moving(tmp_path):
    positions = [(70 + 5 * i, 60 + 3 * i) for i in range(6)]
    return _samples(tmp_path, [_scene(x, y, patch=_texture()) for x, y in positions]), _box(), positions


def _assert_contract(result, samples):
    assert set(result) == {"algorithm", "status", "points", "reason", "automatic_identity"}
    assert result["algorithm"] == "opencv_lk" and result["automatic_identity"] is False
    assert result["status"] in {"completed", "lost", "insufficient"}
    assert result["reason"] in tracking._REASONS
    if result["status"] == "completed":
        assert len(result["points"]) == len(samples) >= 2
    elif result["status"] == "lost":
        assert len(result["points"]) >= 2
        assert result["points"][-1]["status"] == "lost" and result["points"][-1]["bbox"] is None
    else:
        assert len(result["points"]) == 1 and result["points"][0]["status"] == "seed"
    text = json.dumps(result, allow_nan=False)
    for sample in samples:
        assert str(sample["path"]) not in text
    stopped = False
    for point, sample in zip(result["points"], samples):
        assert set(point) == {"frame_key", "time_sec", "bbox", "status", "quality", "reason"}
        assert point["frame_key"] == sample["frame_key"] and point["time_sec"] == sample["time_sec"]
        assert point["reason"] in tracking._REASONS
        if point["status"] == "lost":
            stopped = True
            assert point["bbox"] is None and point["quality"] is None
        else:
            assert not stopped
            assert tracking._bbox(point["bbox"]) == point["bbox"]
            if point["status"] == "suggested":
                assert 0 <= point["quality"] <= 1


def test_known_trajectory_and_public_contract_no_writes(moving, tmp_path):
    samples, box, positions = moving
    before = {s["path"]: (hashlib.sha256(s["path"].read_bytes()).digest(), s["path"].stat().st_mtime_ns) for s in samples}
    files = set(tmp_path.iterdir())
    result = tracking.track_frames(samples, box)
    _assert_contract(result, samples)
    assert result["status"] == "completed", result
    assert len(result["points"]) == 6
    assert result["points"][0]["status"] == "seed" and result["points"][0]["quality"] is None
    for point, (x, y) in zip(result["points"], positions):
        found = point["bbox"]
        assert abs(found["x"] * 320 - x) < 1.5
        assert abs(found["y"] * 192 - y) < 1.5
        assert found["width"] == box["width"] and found["height"] == box["height"]
    assert set(tmp_path.iterdir()) == files
    assert {s["path"]: (hashlib.sha256(s["path"].read_bytes()).digest(), s["path"].stat().st_mtime_ns) for s in samples} == before


@pytest.mark.parametrize("dx,dy", [(0, 0), (-4, 2), (3, -4)])
def test_static_and_reverse_motion(tmp_path, dx, dy):
    samples = _samples(tmp_path, [_scene(70 + i * dx, 60 + i * dy, patch=_texture()) for i in range(4)])
    result = tracking.track_frames(samples, _box())
    assert result["status"] == "completed", result
    last = result["points"][-1]["bbox"]
    assert abs(last["x"] * 320 - (70 + 3 * dx)) < 1.5
    assert abs(last["y"] * 192 - (60 + 3 * dy)) < 1.5


@pytest.mark.parametrize("mode", ["occlusion", "disappearance", "appearance_change"])
def test_no_fabricated_tracking_or_reconnection(tmp_path, mode):
    images = [_scene(70 + i * 5, 60 + i * 3, patch=_texture()) for i in range(5)]
    if mode == "occlusion":
        images[2][66:114, 80:104] = 30
    elif mode == "disappearance":
        images[2][:] = 30
    else:
        images[2][66:114, 80:128] = 255 - _texture()
    samples = _samples(tmp_path, images)
    result = tracking.track_frames(samples, _box())
    _assert_contract(result, samples)
    assert result["status"] == "lost", result
    assert result["points"][1]["status"] == "suggested"
    assert result["points"][2]["status"] == "lost"
    assert result["points"][2]["bbox"] is None
    assert len(result["points"]) == 3, "Stop immediately; never return points after the first loss"


@pytest.mark.parametrize("brightness_offset", [0, 7])
def test_two_similar_targets_are_ambiguous(tmp_path, brightness_offset):
    images = []
    for i in range(3):
        image = _scene(70 + i * 3, 60, patch=_texture())
        image[60:108, 132 + i * 3:180 + i * 3] = _texture() + brightness_offset
        images.append(image)
    samples = _samples(tmp_path, images)
    result = tracking.track_frames(samples, _box())
    assert result["status"] == "lost" and result["reason"] == "ambiguous", result
    assert result["points"][1]["bbox"] is None


def test_scene_cut_stops_before_a_similar_target_can_be_reused(tmp_path):
    images = [_scene(70, 60, patch=_texture()), np.full((192, 320), 230, np.uint8),
              _scene(70, 60, patch=_texture())]
    result = tracking.track_frames(_samples(tmp_path, images), _box())
    assert result["status"] == "lost" and result["reason"] == "scene_cut"
    assert all(p["bbox"] is None for p in result["points"][1:])


def test_offscreen_never_clips_or_invents_a_box(tmp_path):
    samples = _samples(tmp_path, [_scene(268 + 12 * i, 60, patch=_texture()) for i in range(3)])
    result = tracking.track_frames(samples, _box(x=268))
    assert result["status"] == "lost", result
    assert result["points"][1]["bbox"] is None
    assert result["reason"] in {"offscreen", "flow_lost", "appearance_changed", "motion_inconsistent"}


def test_large_jump_does_not_reacquire(tmp_path):
    samples = _samples(tmp_path, [_scene(70, 60, patch=_texture()), _scene(170, 60, patch=_texture())])
    result = tracking.track_frames(samples, _box())
    assert result["status"] == "lost", result
    assert result["points"][1]["bbox"] is None


def test_initial_appearance_prevents_gradual_template_drift(tmp_path):
    images = [_scene(70 + 3 * i, 60, patch=_texture() + i * 6) for i in range(6)]
    result = tracking.track_frames(_samples(tmp_path, images), _box())
    assert result["status"] == "lost" and result["reason"] == "appearance_changed", result
    assert 2 <= len(result["points"]) <= 5
    assert result["points"][-1]["bbox"] is None


def test_blurred_roi_is_insufficient_not_a_zero_motion_track(tmp_path):
    image = _scene(70, 60, patch=cv.GaussianBlur(_texture(), (31, 31), 8))
    result = tracking.track_frames(_samples(tmp_path, [image, image]), _box())
    assert result["status"] == "insufficient"
    assert result["reason"] in {"insufficient_texture", "insufficient_features"}
    assert len(result["points"]) == 1
    assert result["points"][0]["status"] == "seed" and result["points"][0]["bbox"] == _box()


@pytest.mark.parametrize("kind,reason", [("textureless", "insufficient_texture"),
                                        ("tiny_roi", "roi_too_small"), ("tiny_image", "image_too_small")])
def test_low_information_is_explicitly_insufficient(tmp_path, kind, reason):
    image = _scene(70, 60, patch=_texture())
    bbox = _box()
    if kind == "textureless":
        image[:] = 90
    elif kind == "tiny_roi":
        bbox = _box(w=12, h=12)
    else:
        image = cv.resize(image, (40, 30))
    result = tracking.track_frames(_samples(tmp_path, [image, image]), bbox)
    assert result["status"] == "insufficient" and result["reason"] == reason
    assert len(result["points"]) == 1
    assert result["points"][0]["status"] == "seed" and result["points"][0]["bbox"] == bbox


def test_single_seed_is_not_completed(moving):
    samples, box, _ = moving
    result = tracking.track_frames(samples[:1], box)
    assert result["status"] == "insufficient" and result["reason"] == "needs_more_samples"
    assert len(result["points"]) == 1 and result["points"][0]["status"] == "seed"


def test_hd_jpeg_rescaling_keeps_normalized_trajectory(tmp_path):
    samples = _samples(tmp_path, [_scene(400 + 12 * i, 300 + 8 * i, size=(1920, 1080), patch=_texture(144))
                                  for i in range(6)], suffix=".jpg")
    started = time.monotonic()
    result = tracking.track_frames(samples, _box(400, 300, 144, 144, 1920, 1080))
    assert result["status"] == "completed", result
    assert time.monotonic() - started < 6
    for i, point in enumerate(result["points"]):
        assert abs(point["bbox"]["x"] * 1920 - (400 + 12 * i)) < 3
        assert abs(point["bbox"]["y"] * 1080 - (300 + 8 * i)) < 3


@pytest.mark.parametrize("times,reason", [([0, 1.51], "time_gap"), ([0, 1, 2, 3, 4, 5.11], "time_window"),
    ([0, 0], "invalid_time"), ([2, 1], "invalid_time"), ([-1, 0], "invalid_time"),
    ([0, float("nan")], "invalid_time"), ([0, float("inf")], "invalid_time"), ([True, 1], "invalid_time")])
def test_time_bounds_before_file_reads(monkeypatch, times, reason):
    monkeypatch.setattr(tracking, "_local_path", lambda *args: pytest.fail("must validate times first"))
    samples = [{"frame_key": f"f{i}", "time_sec": seconds, "path": Path("not-opened.png")} for i, seconds in enumerate(times)]
    _assert_error(samples, _box(), reason)


def test_six_samples_at_window_tolerance_are_accepted(moving):
    samples, box, _ = moving
    for i, sample in enumerate(samples):
        sample["time_sec"] = i * 1.02
    result = tracking.track_frames(samples, box)
    assert result["status"] == "completed", result


@pytest.mark.parametrize("samples,reason", [([], "invalid_samples"), (None, "invalid_samples"),
    ([{}] * 7, "sample_limit"), ([{}], "invalid_samples"),
    ([{"frame_key": "../private", "time_sec": 0, "path": Path("x")}], "invalid_frame_key")])
def test_invalid_samples(samples, reason):
    _assert_error(samples, _box(), reason)


@pytest.mark.parametrize("changes", [{"x": -0.1}, {"width": 0}, {"x": 0.9, "width": 0.2},
    {"height": float("nan")}, {"y": True}, {"x": "0.1"}, {"height": 10**500}, {"label": "not_allowed"}])
def test_invalid_roi_rejected_before_read(changes, monkeypatch):
    monkeypatch.setattr(tracking, "_local_path", lambda *args: pytest.fail("must validate bbox first"))
    _assert_error([{"frame_key": "f0", "time_sec": 0, "path": Path("never.png")}],
                  {**_box(), **changes}, "invalid_bbox")


@pytest.mark.parametrize("path", [Path("https://example.invalid/a.png"), Path("file:///a.png"),
    Path("//server/share/a.png"), Path(r"\\server\share\a.png"), Path("C:/a.png:stream"), Path("bad\x00path"), "string.png"])
def test_unsafe_paths_are_sanitized(path):
    _assert_error([{"frame_key": "f0", "time_sec": 0, "path": path}], _box(), "unsafe_path")


def test_missing_file_and_empty_file(tmp_path):
    path = tmp_path / "missing.png"
    sample = [{"frame_key": "f0", "time_sec": 0, "path": path}]
    _assert_error(sample, _box(), "image_unavailable")
    path.touch()
    _assert_error(sample, _box(), "image_byte_limit")


@pytest.mark.parametrize("mode", ["symlink", "reparse"])
def test_link_policy_without_windows_link_privileges(moving, monkeypatch, mode):
    samples, box, _ = moving
    original = Path.lstat
    parent = samples[0]["path"].parent

    def linked(path, *args, **kwargs):
        if path == parent:
            return SimpleNamespace(st_mode=stat.S_IFLNK if mode == "symlink" else stat.S_IFDIR,
                                   st_file_attributes=0x400 if mode == "reparse" else 0)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", linked)
    _assert_error(samples, box, "unsafe_path")


@pytest.mark.skipif(os.name != "nt", reason="Windows mapped drive")
def test_network_drive_is_rejected_before_stat(moving, monkeypatch):
    import ctypes

    monkeypatch.setattr(ctypes.windll.kernel32, "GetDriveTypeW", lambda root: 4)
    _assert_error(moving[0], moving[1], "unsafe_path")


@pytest.mark.parametrize("mode,reason", [("dimensions", "dimensions_changed"), ("format", "format_changed"),
    ("corrupt", "unsupported_format"), ("alpha", "unsupported_format")])
def test_changed_dimensions_and_format_fail_closed(tmp_path, mode, reason):
    image = _scene(70, 60, patch=_texture())
    second = cv.resize(image, (640, 384)) if mode == "dimensions" else image
    if mode == "alpha":
        second = cv.cvtColor(image, cv.COLOR_GRAY2BGRA)
    samples = _samples(tmp_path, [image, second])
    if mode == "format":
        new = tmp_path / "different.jpg"
        new.write_bytes(cv.imencode(".jpg", image)[1].tobytes())
        samples[1]["path"] = new
    if mode == "corrupt":
        samples[1]["path"].write_bytes(b"not an image")
    _assert_error(samples, _box(), reason)


@pytest.mark.parametrize("width,height", [(8193, 10), (10, 8193), (4001, 4000)])
def test_pixel_and_dimension_caps_reject_before_native_decode(width, height):
    header = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR" + struct.pack(">II", width, height) + b"\x08\x00" + bytes(7)
    with pytest.raises(tracking._Failure) as exc:
        tracking._image_header(header, "synthetic.png")
    assert exc.value.reason == "image_dimensions_exceeded"


def test_byte_limit_without_large_file(moving, monkeypatch):
    monkeypatch.setattr(tracking, "MAX_IMAGE_BYTES", 2)
    _assert_error(moving[0], moving[1], "image_byte_limit")


def test_source_changed_after_tracking_discards_all_points(moving, monkeypatch):
    samples, box, _ = moving
    clean, box = tracking._inputs(samples, box)
    original = tracking._follow

    def replace(cv, np, images, clean_samples, box):
        result = original(cv, np, images, clean_samples, box)
        path = samples[0]["path"]
        before = path.stat()
        data = bytearray(path.read_bytes())
        data[-1] ^= 1
        path.write_bytes(data)
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        return result

    monkeypatch.setattr(tracking, "_follow", replace)
    with pytest.raises(tracking._Failure) as exc:
        tracking._track_in_process(clean, box)
    assert exc.value.reason == "source_changed"


def test_source_change_between_worker_and_return_raises_not_partial_result(moving, monkeypatch):
    samples, box, _ = moving

    def changed(payload, deadline):
        points = [tracking._point(s, dict(box), "seed" if i == 0 else "suggested", None if i == 0 else 1,
                                  "teacher_roi" if i == 0 else "tracking_complete") for i, s in enumerate(samples)]
        samples[-1]["path"].write_bytes(b"modified synthetic image")
        return json.dumps(tracking._result("completed", points, "tracking_complete")).encode()

    monkeypatch.setattr(tracking, "_run_worker", changed)
    _assert_error(samples, box, "source_changed")


def test_stat_fstat_ctime_difference_does_not_look_like_replacement(moving, monkeypatch):
    samples, box, _ = moving
    clean, _ = tracking._inputs(samples, box)
    original = os.fstat

    def different_ctime(fd):
        info = original(fd)
        return SimpleNamespace(**{key: getattr(info, key) for key in (
            "st_mode", "st_size", "st_dev", "st_ino", "st_mtime_ns")}, st_ctime_ns=1)

    monkeypatch.setattr(tracking.os, "fstat", different_ctime)
    assert tracking._read_sample(clean[0]) == samples[0]["path"].read_bytes()


def test_source_replaced_before_worker_reads_is_rejected(moving):
    samples, box, _ = moving
    clean, _ = tracking._inputs(samples, box)
    samples[0]["path"].write_bytes(b"different synthetic input")
    with pytest.raises(tracking._Failure) as exc:
        tracking._read_sample(clean[0])
    assert exc.value.reason == "source_changed"


def test_forward_backward_validation_is_mandatory(moving, monkeypatch):
    samples, box, _ = moving
    clean, box = tracking._inputs(samples, box)
    images = [cv.imread(str(s["path"]), cv.IMREAD_GRAYSCALE) for s in samples]
    original = cv.calcOpticalFlowPyrLK
    calls = []

    def inconsistent(*args, **kwargs):
        calls.append(True)
        points, status, errors = original(*args, **kwargs)
        if len(calls) == 2:
            points += 5
        return points, status, errors

    monkeypatch.setattr(cv, "calcOpticalFlowPyrLK", inconsistent)
    result = tracking._follow(cv, np, images, clean, box)
    assert result["status"] == "lost" and result["reason"] == "flow_lost"
    assert len(calls) == 2, "No tracking calls are allowed after loss"


def _children(monkeypatch):
    children = []
    original = tracking.subprocess.Popen

    def record(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append((child, kwargs))
        return child

    monkeypatch.setattr(tracking.subprocess, "Popen", record)
    return children


def _assert_reaped(children):
    assert children
    for child, kwargs in children:
        assert child.poll() is not None
        assert child.stdout.closed and child.stdin.closed
        assert kwargs["stderr"] == subprocess.DEVNULL and kwargs["shell"] is False
        if os.name == "nt":
            assert kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW
    assert not any(t.name == "roi-tracking-pipe" for t in threading.enumerate())


def test_default_timeout_reaps_worker_and_releases_slot(moving, monkeypatch):
    monkeypatch.setattr(tracking, "_worker_command", lambda: [sys.executable, "-B", "-c", "import time; time.sleep(30)"])
    children = _children(monkeypatch)
    started = time.monotonic()
    _assert_error(moving[0], moving[1], "timeout")
    assert 5 <= time.monotonic() - started < 6
    _assert_reaped(children)
    assert tracking._SLOT.acquire(blocking=False)
    tracking._SLOT.release()


@pytest.mark.parametrize("script,reason", [
    ("import os; chunk=b'x'*4096\nwhile True: os.write(1,chunk)", "worker_output_limit"),
    ("import sys; sys.exit(7)", "worker_failed"),
    ("import os; os.write(1,b'PRIVATE_PATH_STACKTRACE')", "worker_invalid_response"),
])
def test_worker_output_is_bounded_and_sanitized(moving, monkeypatch, script, reason):
    monkeypatch.setattr(tracking, "_worker_command", lambda: [sys.executable, "-B", "-c", script])
    children = _children(monkeypatch)
    _assert_error(moving[0], moving[1], reason)
    _assert_reaped(children)


def test_blocked_stdin_and_eof_do_not_escape_deadline(monkeypatch):
    monkeypatch.setattr(tracking, "_worker_command", lambda: [sys.executable, "-B", "-c",
        "import os,time; os.close(1); time.sleep(30)"])
    children = _children(monkeypatch)
    start = time.monotonic()
    with pytest.raises(tracking._Failure) as exc:
        tracking._run_worker(b"x" * tracking.MAX_REQUEST_BYTES, start + 1.5)
    assert exc.value.reason == "timeout" and time.monotonic() - start < 1.5
    _assert_reaped(children)


def test_one_local_call_at_a_time(moving):
    assert tracking._SLOT.acquire(blocking=False)
    try:
        _assert_error(moving[0], moving[1], "busy")
    finally:
        tracking._SLOT.release()


def test_start_failure_is_sanitized(moving, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("PRIVATE_EXECUTABLE_PATH")

    monkeypatch.setattr(tracking.subprocess, "Popen", fail)
    _assert_error(moving[0], moving[1], "worker_unavailable")


def test_thread_start_failure_still_reaps_child(moving, monkeypatch):
    children = _children(monkeypatch)

    def fail(thread):
        raise RuntimeError("PRIVATE_THREAD_ERROR")

    monkeypatch.setattr(threading.Thread, "start", fail)
    _assert_error(moving[0], moving[1], "worker_failed")
    _assert_reaped(children)


def test_stderr_flood_is_not_retained(moving, monkeypatch):
    script = "import os; os.write(2,b'PRIVATE_DIAGNOSTIC'*100000); os.write(1,b'{}')"
    monkeypatch.setattr(tracking, "_worker_command", lambda: [sys.executable, "-B", "-c", script])
    children = _children(monkeypatch)
    _assert_error(moving[0], moving[1], "worker_invalid_response")
    _assert_reaped(children)


@pytest.mark.parametrize("mode", ["identity", "foreign_frame", "foreign_time", "changed_seed", "path_reason",
                                  "reconnect", "post_loss_point", "short_completed", "oversized_box", "nan_quality"])
def test_parent_revalidates_worker_contract(moving, mode):
    samples, box, _ = moving
    clean, box = tracking._inputs(samples, box)
    points = [tracking._point(s, dict(box), "seed" if i == 0 else "suggested", None if i == 0 else 1.0,
                              "teacher_roi" if i == 0 else "tracking_complete") for i, s in enumerate(clean)]
    result = tracking._result("completed", points, "tracking_complete")
    if mode == "identity":
        result["automatic_identity"] = True
    elif mode == "foreign_frame":
        points[1]["frame_key"] = "other_frame"
    elif mode == "foreign_time":
        points[1]["time_sec"] = 1.01
    elif mode == "changed_seed":
        points[0]["bbox"]["x"] += 0.01
    elif mode == "path_reason":
        result["reason"] = "PRIVATE_PATH"
    elif mode == "reconnect":
        points[1].update(status="lost", bbox=None, quality=None, reason="flow_lost")
    elif mode == "post_loss_point":
        result.update(status="lost", reason="flow_lost")
        for point in points[1:]:
            point.update(status="lost", bbox=None, quality=None, reason="flow_lost")
    elif mode == "short_completed":
        points.pop()
    elif mode == "oversized_box":
        points[1]["bbox"]["width"] = 2
    else:
        points[1]["quality"] = float("nan")
    assert tracking._checked_result(json.dumps(result).encode(), clean, box) == tracking._failure("worker_invalid_response")
