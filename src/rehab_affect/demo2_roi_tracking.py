"""Short, conservative ROI position suggestions; never automatic identity.

The caller authorizes every sample and rechecks authorization/expiry before
publishing. Samples must live in private, caller-controlled storage. No names,
identity writes, behavior/emotion inference, downloads, cache, or image writes.
Sparse LK follows ONLY the seed corners: no corner refresh or reacquisition.
Appearance matching is a veto, never a search used to relocate a lost target.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys
import threading
import time


MAX_SAMPLES = 6
MAX_GAP_SEC = 1.5
MAX_SPAN_SEC = 5.1
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
MAX_IMAGE_SIDE = 8192
WORK_SIDE = 960
WORKER_TIMEOUT_SEC = 6.0
MAX_WORKER_BYTES = 64 * 1024
MAX_REQUEST_BYTES = 64 * 1024
MAX_CORNERS = 80
MIN_CORNERS = 12
MIN_ROI_SIDE = 24
MAX_FB_ERROR = 1.0
MAX_STEP_PX = 48.0
_CLEANUP_SEC = 0.35
_SLOT = threading.BoundedSemaphore(1)
_REASONS = frozenset({
    "invalid_samples", "sample_limit", "invalid_frame_key", "invalid_time", "time_gap", "time_window",
    "invalid_bbox", "unsafe_path", "image_unavailable", "image_byte_limit", "source_changed",
    "unsupported_format", "invalid_image", "format_changed", "dimensions_changed",
    "image_dimensions_exceeded", "image_too_small", "roi_too_small", "insufficient_texture",
    "insufficient_features", "needs_more_samples", "teacher_roi", "tracking_complete",
    "ambiguous", "scene_cut", "offscreen", "flow_lost", "motion_inconsistent", "motion_too_large",
    "appearance_changed", "missing_dependency", "busy", "timeout",
    "worker_unavailable", "worker_failed", "worker_output_limit", "worker_invalid_response",
})
_STOP_REASONS = frozenset({"ambiguous", "scene_cut", "offscreen", "flow_lost", "motion_inconsistent",
                           "motion_too_large", "appearance_changed"})
_INSUFFICIENT_REASONS = frozenset({"image_too_small", "roi_too_small", "insufficient_texture",
                                   "insufficient_features", "needs_more_samples"})


class TrackingError(RuntimeError):
    """Input, source-integrity, resource, or worker failure (no path details)."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


class _Failure(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _result(status: str, points: list, reason: str) -> dict:
    return {"algorithm": "opencv_lk", "status": status, "points": points, "reason": reason,
            "automatic_identity": False}


def _failure(reason: str) -> dict:
    return _result("insufficient", [], reason if reason in _REASONS else "worker_failed")


def _number(value, reason: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _Failure(reason)
    try:
        value = float(value)
    except (ValueError, OverflowError):
        raise _Failure(reason) from None
    if not math.isfinite(value):
        raise _Failure(reason)
    return value


def _bbox(value) -> dict:
    if not isinstance(value, dict) or set(value) != {"x", "y", "width", "height"}:
        raise _Failure("invalid_bbox")
    box = {key: _number(value[key], "invalid_bbox") for key in ("x", "y", "width", "height")}
    x, y, w, h = (box[key] for key in ("x", "y", "width", "height"))
    if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1 and x + w <= 1 and y + h <= 1):
        raise _Failure("invalid_bbox")
    return box


def _local_path(value: Path) -> Path:
    # Same local-file/no-links policy as media_analysis, kept stdlib-only so
    # the isolated worker never needs to import the application or native code
    # in the parent before its watchdog exists.
    if not isinstance(value, Path):
        raise _Failure("unsafe_path")
    try:
        value = value.expanduser()
    except RuntimeError:
        raise _Failure("unsafe_path") from None
    raw = str(value)
    if (len(raw) > 1024 or "\x00" in raw or raw.startswith(("\\\\", "//"))
            or (":" in raw and not re.match(r"^[A-Za-z]:[\\/]", raw)) or ":" in raw[2:]):
        raise _Failure("unsafe_path")
    path = value.absolute()
    if os.name == "nt":
        import ctypes

        if ctypes.windll.kernel32.GetDriveTypeW(path.anchor) == 4:
            raise _Failure("unsafe_path")
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise _Failure("unsafe_path")
    return path


def _stamp(info) -> tuple:
    if not stat.S_ISREG(info.st_mode):
        raise _Failure("unsafe_path")
    if not 0 < info.st_size <= MAX_IMAGE_BYTES:
        raise _Failure("image_byte_limit")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _file_stamp(path: Path) -> tuple:
    return _stamp(_local_path(path).stat())


def _inputs(samples, bbox) -> tuple[list[dict], dict]:
    if not isinstance(samples, list) or not samples:
        raise _Failure("invalid_samples")
    if len(samples) > MAX_SAMPLES:
        raise _Failure("sample_limit")
    box = _bbox(bbox)
    clean, keys = [], set()
    for sample in samples:
        if not isinstance(sample, dict) or set(sample) != {"frame_key", "time_sec", "path"}:
            raise _Failure("invalid_samples")
        key = sample["frame_key"]
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", key) or key in keys:
            raise _Failure("invalid_frame_key")
        keys.add(key)
        seconds = _number(sample["time_sec"], "invalid_time")
        if seconds < 0 or (clean and seconds <= clean[-1]["time_sec"]):
            raise _Failure("invalid_time")
        if clean and seconds - clean[-1]["time_sec"] > MAX_GAP_SEC + 1e-9:
            raise _Failure("time_gap")
        if clean and seconds - clean[0]["time_sec"] > MAX_SPAN_SEC + 1e-9:
            raise _Failure("time_window")
        clean.append({"frame_key": key, "time_sec": seconds, "path": sample["path"]})
    for sample in clean:
        path = _local_path(sample["path"])
        sample.update(path=str(path), stamp=list(_stamp(path.stat())))
    return clean, box


def _read_sample(sample: dict) -> bytes:
    path = _local_path(Path(sample["path"]))
    expected = tuple(sample["stamp"])
    if _stamp(path.stat()) != expected:
        raise _Failure("source_changed")
    with path.open("rb") as handle:
        opened_stamp = _stamp(os.fstat(handle.fileno()))
        # Some Windows Python builds expose different ctime semantics for
        # stat/fstat. Compare identity/size/mtime across APIs, ctime within each.
        if opened_stamp[:4] != expected[:4]:
            raise _Failure("source_changed")
        data = handle.read(MAX_IMAGE_BYTES + 1)
        if len(data) != expected[2] or _stamp(os.fstat(handle.fileno())) != opened_stamp:
            raise _Failure("source_changed")
    if _file_stamp(path) != expected:
        raise _Failure("source_changed")
    return data


def _image_header(data: bytes, path: str) -> tuple[str, int, int]:
    suffix = Path(path).suffix.lower()
    if (suffix == ".png" and data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 33
            and data[8:16] == b"\x00\x00\x00\x0dIHDR"):
        w, h = struct.unpack_from(">II", data, 16)
        if data[24] != 8 or data[25] not in (0, 2):
            raise _Failure("unsupported_format")
        kind = "png"
    elif suffix in {".jpg", ".jpeg"} and data.startswith(b"\xff\xd8") and data.endswith(b"\xff\xd9"):
        pos, w, h = 2, 0, 0
        while pos + 4 <= len(data) and data[pos] == 0xFF:
            marker = data[pos + 1]
            if marker == 0xFF:
                pos += 1
                continue
            if marker in (0xDA, 0xD9):
                break
            length = struct.unpack_from(">H", data, pos + 2)[0]
            if length < 2 or pos + 2 + length > len(data):
                break
            if marker in (0xC0, 0xC1, 0xC2) and length >= 8:
                depth, h, w, channels = struct.unpack_from(">BHHB", data, pos + 4)
                if depth != 8 or channels not in (1, 3):
                    raise _Failure("unsupported_format")
                break
            pos += 2 + length
        if not w or not h:
            raise _Failure("invalid_image")
        kind = "jpeg"
    else:
        raise _Failure("unsupported_format")
    if not (0 < w <= MAX_IMAGE_SIDE and 0 < h <= MAX_IMAGE_SIDE and w * h <= MAX_IMAGE_PIXELS):
        raise _Failure("image_dimensions_exceeded")
    return kind, w, h


def _point(sample: dict, box: dict | None, status: str, quality: float | None, reason: str) -> dict:
    return {"frame_key": sample["frame_key"], "time_sec": sample["time_sec"], "bbox": box,
            "status": status, "quality": quality, "reason": reason}


def _insufficient(samples: list[dict], box: dict, reason: str) -> dict:
    return _result("insufficient", [_point(samples[0], dict(box), "seed", None, "teacher_roi")], reason)


def _patch(cv, image, rect):
    x, y, w, h = rect
    return cv.getRectSubPix(image, (w, h), (float(x + (w - 1) / 2), float(y + (h - 1) / 2)))


def _appearance(cv, np, first, second) -> tuple[float, float, float]:
    a = cv.resize(first, (48, 48), interpolation=cv.INTER_AREA).astype(np.float32)
    b = cv.resize(second, (48, 48), interpolation=cv.INTER_AREA).astype(np.float32)
    diff = np.abs(a - b)
    aa, bb = a - a.mean(), b - b.mean()
    denominator = float(np.linalg.norm(aa) * np.linalg.norm(bb))
    correlation = float(np.sum(aa * bb) / denominator) if denominator > 1e-6 else 0.0
    tiles = diff.reshape(4, 12, 4, 12).mean(axis=(1, 3))
    return correlation, float(diff.mean()), float(tiles.max())


def _ambiguous(cv, image, template, rect) -> bool:
    x, y, w, h = rect
    radius = min(96, max(48, 2 * max(w, h)))
    left, top = max(0, int(x) - radius), max(0, int(y) - radius)
    right, bottom = min(image.shape[1], int(x + w) + radius), min(image.shape[0], int(y + h) + radius)
    region = image[top:bottom, left:right]
    scale = min(1.0, 64 / max(w, h))
    size = (max(4, round(w * scale)), max(4, round(h * scale)))
    small_template = cv.resize(template, size, interpolation=cv.INTER_AREA)
    region = cv.resize(region, (max(size[0], round(region.shape[1] * scale)),
                                max(size[1], round(region.shape[0] * scale))), interpolation=cv.INTER_AREA)
    scores = cv.matchTemplate(region, small_template, cv.TM_CCOEFF_NORMED)
    _, best, _, location = cv.minMaxLoc(scores)
    if best < 0.88:
        return False
    px, py = location
    rx, ry = max(3, round(size[0] * 0.45)), max(3, round(size[1] * 0.45))
    scores[max(0, py - ry):py + ry + 1, max(0, px - rx):px + rx + 1] = -1
    second = cv.minMaxLoc(scores)[1]
    return second >= 0.88 and best - second <= 0.06


def _follow(cv, np, images: list, samples: list[dict], box: dict) -> dict:
    first = images[0]
    height, width = first.shape
    x, y = box["x"] * width, box["y"] * height
    w, h = round(box["width"] * width), round(box["height"] * height)
    if min(w, h) < MIN_ROI_SIDE:
        return _insufficient(samples, box, "roi_too_small")
    rect = (x, y, w, h)
    seed = _patch(cv, first, rect)
    if seed.std() < 10 or cv.Laplacian(seed, cv.CV_32F).var() < 35:
        return _insufficient(samples, box, "insufficient_texture")
    mask = np.zeros_like(first)
    mask[math.ceil(y) + 3:math.floor(y + h) - 3, math.ceil(x) + 3:math.floor(x + w) - 3] = 255
    corners = cv.goodFeaturesToTrack(first, MAX_CORNERS, 0.03, 4, mask=mask, blockSize=5)
    if corners is None or len(corners) < MIN_CORNERS:
        return _insufficient(samples, box, "insufficient_features")
    quadrants = set((int(px >= x + w / 2), int(py >= y + h / 2)) for px, py in corners.reshape(-1, 2))
    if len(quadrants) < 3:
        return _insufficient(samples, box, "insufficient_features")
    points = [_point(samples[0], dict(box), "seed", None, "teacher_roi")]
    if len(images) == 1:
        return _result("insufficient", points, "needs_more_samples")
    initial_count = len(corners)
    previous, previous_patch = first, seed
    lk = {"winSize": (21, 21), "maxLevel": 3,
          "criteria": (cv.TERM_CRITERIA_EPS | cv.TERM_CRITERIA_COUNT, 30, 0.01)}
    for index, current in enumerate(images[1:], 1):
        reason, quality = "", None
        old_small = cv.resize(previous, (64, 64), interpolation=cv.INTER_AREA).astype(np.float32)
        new_small = cv.resize(current, (64, 64), interpolation=cv.INTER_AREA).astype(np.float32)
        scene_diff = np.abs(old_small - new_small)
        if float(scene_diff.mean()) > 40 and float((scene_diff > 30).mean()) > 0.65:
            reason = "scene_cut"
        elif _ambiguous(cv, previous, seed, rect) or _ambiguous(cv, current, seed, rect):
            reason = "ambiguous"
        else:
            forward, ok, error = cv.calcOpticalFlowPyrLK(previous, current, corners, None, **lk)
            if forward is None or ok is None or error is None or not np.isfinite(forward).all():
                reason = "flow_lost"
            else:
                backward, back_ok, _ = cv.calcOpticalFlowPyrLK(current, previous, forward, None, **lk)
                if backward is None or back_ok is None:
                    reason = "flow_lost"
                else:
                    fb = np.linalg.norm(backward - corners, axis=2).reshape(-1)
                    valid = (ok.reshape(-1) == 1) & (back_ok.reshape(-1) == 1)
                    valid &= np.isfinite(fb) & (fb <= MAX_FB_ERROR) & (error.reshape(-1) <= 20)
                    delta = (forward - corners).reshape(-1, 2)
                    if int(valid.sum()) < max(MIN_CORNERS, math.ceil(initial_count * 0.65)):
                        reason = "flow_lost"
                    else:
                        shift = np.median(delta[valid], axis=0)
                        valid &= np.linalg.norm(delta - shift, axis=1) <= 1.5
                        if int(valid.sum()) < max(MIN_CORNERS, math.ceil(initial_count * 0.65)):
                            reason = "motion_inconsistent"
                        else:
                            shift = np.median(delta[valid], axis=0)
                            nx, ny = float(x + shift[0]), float(y + shift[1])
                            if nx < 0 or ny < 0 or nx + box["width"] * width > width or ny + box["height"] * height > height:
                                reason = "offscreen"
                            elif float(np.linalg.norm(shift)) > min(MAX_STEP_PX, min(w, h) * 0.45):
                                reason = "motion_too_large"
                            else:
                                patch = _patch(cv, current, (nx, ny, w, h))
                                consistency = [_appearance(cv, np, seed, patch), _appearance(cv, np, previous_patch, patch)]
                                if any(corr < 0.88 or mae > 18 or tile > 30 for corr, mae, tile in consistency):
                                    reason = "appearance_changed"
                                else:
                                    kept = corners.reshape(-1, 2)[valid]
                                    quadrants = set((int(px >= x + w / 2), int(py >= y + h / 2)) for px, py in kept)
                                    if len(quadrants) < 3:
                                        reason = "motion_inconsistent"
                                    else:
                                        quality = round(float(min(valid.sum() / initial_count, consistency[0][0],
                                                                  consistency[1][0], 1 - np.median(fb[valid]) / 2)), 6)
                                        x, y, rect = nx, ny, (nx, ny, w, h)
                                        corners = forward[valid].reshape(-1, 1, 2)
                                        previous, previous_patch = current, patch
        if reason:
            points.append(_point(samples[index], None, "lost", None, reason))
            return _result("lost", points, reason)
        else:
            moved = {"x": x / width, "y": y / height, "width": box["width"], "height": box["height"]}
            points.append(_point(samples[index], moved, "suggested", quality, "tracking_complete"))
    return _result("completed", points, "tracking_complete")


def _track_in_process(samples: list[dict], box: dict) -> dict:
    try:
        import cv2 as cv
        import numpy as np
    except ImportError:
        return _failure("missing_dependency")
    cv.setNumThreads(1)
    cv.ocl.setUseOpenCL(False)
    images, hashes, shape, image_format = [], [], None, None
    for sample in samples:
        data = _read_sample(sample)
        kind, raw_w, raw_h = _image_header(data, sample["path"])
        gray = cv.imdecode(np.frombuffer(data, np.uint8), cv.IMREAD_GRAYSCALE)
        if gray is None or gray.dtype != np.uint8 or gray.ndim != 2:
            raise _Failure("invalid_image")
        height, width = gray.shape
        if width * height != raw_w * raw_h:
            raise _Failure("invalid_image")
        if shape is not None and shape != (raw_w, raw_h, width, height):
            raise _Failure("dimensions_changed")
        if image_format is not None and image_format != kind:
            raise _Failure("format_changed")
        shape, image_format = (raw_w, raw_h, width, height), kind
        scale = min(1.0, WORK_SIDE / max(width, height))
        images.append(cv.resize(gray, (max(1, round(width * scale)), max(1, round(height * scale))),
                                interpolation=cv.INTER_AREA) if scale < 1 else gray)
        hashes.append(hashlib.sha256(data).digest())
    result = (_insufficient(samples, box, "image_too_small") if min(shape[2:]) < 48
              else _follow(cv, np, images, samples, box))
    # Re-read bounded bytes in the worker: stat alone misses in-place writes
    # with restored timestamps on Windows. Never publish mixed-source results.
    for sample, digest in zip(samples, hashes):
        if hashlib.sha256(_read_sample(sample)).digest() != digest:
            raise _Failure("source_changed")
    return result


def _worker_command() -> list[str]:
    return [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--worker"]


def _run_worker(payload: bytes, deadline: float) -> bytes:
    env = os.environ.copy()
    env.update({"OPENCV_IO_MAX_IMAGE_WIDTH": str(MAX_IMAGE_SIDE),
                "OPENCV_IO_MAX_IMAGE_HEIGHT": str(MAX_IMAGE_SIDE), "OPENCV_IO_MAX_IMAGE_PIXELS": str(MAX_IMAGE_PIXELS),
                "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                "OPENCV_LOG_LEVEL": "SILENT"})
    work_deadline = deadline - _CLEANUP_SEC
    if time.monotonic() >= work_deadline:
        raise _Failure("timeout")
    try:
        process = subprocess.Popen(_worker_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, bufsize=0, shell=False, close_fds=True, env=env,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except OSError:
        raise _Failure("worker_unavailable") from None
    output, errors, readers = bytearray(), [], []
    done, closing = threading.Event(), threading.Event()

    def read_stdout():
        try:
            while not closing.is_set():
                block = process.stdout.read(4096)
                if not block:
                    break
                if len(output) + len(block) > MAX_WORKER_BYTES:
                    errors.append("worker_output_limit")
                    break
                output.extend(block)
        except (OSError, ValueError):
            errors.append("worker_failed")
        finally:
            done.set()

    def write_stdin():
        try:
            view = memoryview(payload)
            while view and not closing.is_set():
                count = process.stdin.write(view)
                if not count:
                    break
                view = view[count:]
        except (OSError, ValueError):
            pass
        finally:
            process.stdin.close()

    try:
        for target in (read_stdout, write_stdin):
            thread = threading.Thread(target=target, name="roi-tracking-pipe", daemon=True)
            thread.start()
            readers.append(thread)
        if not done.wait(max(0, work_deadline - time.monotonic())):
            raise _Failure("timeout")
        if errors:
            raise _Failure(errors[0])
        process.wait(timeout=max(0, work_deadline - time.monotonic()))
        if time.monotonic() >= work_deadline:
            raise _Failure("timeout")
        if process.returncode:
            raise _Failure("worker_failed")
        return bytes(output)
    except subprocess.TimeoutExpired:
        raise _Failure("timeout") from None
    finally:
        closing.set()
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise _Failure("timeout") from None
        finally:
            for thread in readers:
                thread.join(timeout=max(0, deadline - time.monotonic()))
            process.stdin.close()
            process.stdout.close()


def _checked_result(raw: bytes, samples: list[dict], box: dict) -> dict:
    try:
        value = json.loads(raw)
        if (not isinstance(value, dict) or set(value) != {"algorithm", "status", "points", "reason", "automatic_identity"}
                or value["algorithm"] != "opencv_lk" or value["automatic_identity"] is not False
                or value["status"] not in {"completed", "lost", "insufficient"} or value["reason"] not in _REASONS):
            raise ValueError
        points = value["points"]
        if value["status"] == "insufficient" and points == []:
            if value["reason"] in _INSUFFICIENT_REASONS:
                raise ValueError
            return _failure(value["reason"])
        if not isinstance(points, list) or not 1 <= len(points) <= len(samples):
            raise ValueError
        stopped = False
        for index, (point, sample) in enumerate(zip(points, samples)):
            if (not isinstance(point, dict) or set(point) != {"frame_key", "time_sec", "bbox", "status", "quality", "reason"}
                    or point["frame_key"] != sample["frame_key"]
                    or _number(point["time_sec"], "worker_invalid_response") != sample["time_sec"]
                    or point["reason"] not in _REASONS):
                raise ValueError
            if index == 0:
                if point["status"] != "seed" or _bbox(point["bbox"]) != box or point["quality"] is not None:
                    raise ValueError
            elif point["status"] == "lost":
                if (point["bbox"] is not None or point["quality"] is not None or stopped
                        or index != len(points) - 1 or point["reason"] not in _STOP_REASONS):
                    raise ValueError
                stopped = True
            else:
                if stopped or point["status"] != "suggested":
                    raise ValueError
                moved = _bbox(point["bbox"])
                if (moved["width"] != box["width"] or moved["height"] != box["height"]
                        or not 0 <= _number(point["quality"], "worker_invalid_response") <= 1):
                    raise ValueError
        if ((value["status"] == "completed" and (stopped or len(points) != len(samples) or len(points) < 2
                                                  or value["reason"] != "tracking_complete"))
                or (value["status"] == "lost" and (not stopped or value["reason"] != points[-1]["reason"]))
                or (value["status"] == "insufficient" and (len(points) != 1 or value["reason"] not in _INSUFFICIENT_REASONS))
                or (value["reason"] == "needs_more_samples" and len(samples) != 1)):
            raise ValueError
        return value
    except (ValueError, TypeError, KeyError, RecursionError, _Failure):
        return _failure("worker_invalid_response")


def track_frames(samples: list[dict], bbox: dict) -> dict:
    """Suggest translation-only positions for <=6 samples over <=5.1 seconds.

    Times must increase with gaps <=1.5s. Opaque 8-bit JPEG/PNG only, unchanged
    format/display dimensions, <=8 MiB and <=16M pixels each. Work images have
    longest side <=960 without upscaling; ROI sides must remain >=24 work pixels.
    A step is limited to min(48, 0.45 * shorter ROI side) work pixels. Zoom,
    rotation, occlusion, similar neighbors or insufficient evidence can stop it.
    points is an input-aligned prefix ending immediately at the first lost
    point (bbox=None). There are no later points and no automatic reconnect.
    quality is technical consistency, NOT identity or detection probability.
    Every suggested box requires a separate teacher confirmation. Input/source
    and execution failures raise TrackingError(code, message); insufficient is
    reserved for inadequate visual/temporal evidence and contains only the
    unchanged teacher seed. completed contains every supplied sample (>=2).

    All native imports, decodes and tracking run in one hidden child with a
    six-second watchdog (including 0.35s cleanup reserve), stdout <=64 KiB and
    at most two pipe threads. OS process creation/filesystem stalls are not a
    hard-real-time guarantee. There is no persistent or cross-call state.
    """
    deadline = time.monotonic() + WORKER_TIMEOUT_SEC
    if not _SLOT.acquire(blocking=False):
        raise TrackingError("busy", "Another ROI tracking request is running.")
    try:
        clean, box = _inputs(samples, bbox)
        payload = json.dumps({"samples": clean, "bbox": box}, ensure_ascii=True, allow_nan=False).encode("ascii")
        if len(payload) > MAX_REQUEST_BYTES:
            raise _Failure("sample_limit")
        result = _checked_result(_run_worker(payload, deadline), clean, box)
        if result["status"] == "insufficient" and result["reason"] not in _INSUFFICIENT_REASONS:
            raise _Failure(result["reason"])
        if result["points"]:
            for sample in clean:
                if _file_stamp(Path(sample["path"])) != tuple(sample["stamp"]):
                    raise _Failure("source_changed")
        if time.monotonic() > deadline:
            raise _Failure("timeout")
        return result
    except _Failure as exc:
        raise TrackingError(exc.reason, "ROI tracking could not be completed for this request.") from None
    except OSError:
        raise TrackingError("image_unavailable", "A requested sample image is unavailable.") from None
    except (ValueError, RuntimeError):
        raise TrackingError("worker_failed", "The local ROI tracking worker could not complete.") from None
    finally:
        _SLOT.release()


def _worker_main() -> int:
    if sys.argv[1:] != ["--worker"]:
        return 2
    response_fd = os.dup(sys.stdout.fileno())
    try:
        with open(os.devnull, "wb") as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())
            try:
                raw = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
                if len(raw) > MAX_REQUEST_BYTES:
                    raise _Failure("sample_limit")
                payload = json.loads(raw)
                supplied = payload["samples"]
                clean, box = _inputs([{**{k: row[k] for k in ("frame_key", "time_sec")},
                                       "path": Path(row["path"])} for row in supplied], payload["bbox"])
                if any(a["stamp"] != b["stamp"] for a, b in zip(clean, supplied)):
                    raise _Failure("source_changed")
                result = _track_in_process(clean, box)
            except _Failure as exc:
                result = _failure(exc.reason)
            except OSError:
                result = _failure("image_unavailable")
            except Exception:
                result = _failure("worker_failed")
        encoded = json.dumps(result, ensure_ascii=True, allow_nan=False).encode("ascii")
        if len(encoded) > MAX_WORKER_BYTES:
            encoded = json.dumps(_failure("worker_output_limit")).encode("ascii")
        with os.fdopen(response_fd, "wb") as response:
            response_fd = -1
            response.write(encoded)
    finally:
        if response_fd >= 0:
            os.close(response_fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(_worker_main())
