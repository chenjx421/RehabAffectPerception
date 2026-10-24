"""Bounded, offline, single-frame YuNet face-position candidates.

Public API: ``detect_faces(path: Path) -> dict``. The caller must authorize the
local frame before calling; this module is not an HTTP/file authorization layer.
Boxes refer to the decoded image (including its display orientation), not a
player's CSS box. Scores are detector scores, NOT identity probabilities. There
are no names, embeddings, identity matching, tracking, or network operations.

One full-frame view and up to four overlapping, enlarged crops share a detector;
boxes are mapped back, globally suppressed, and capped at 32. Enlarging sampled
pixels does not recover lost detail. All views share ONE 6-second child-process
timeout, which can actually terminate native inference. No images are written.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import stat
import subprocess
import sys
from threading import Lock
from typing import Any


MODEL_NAME = "face_detection_yunet_2023mar.onnx"
MODEL_PATH = Path(__file__).resolve().parents[2] / "models" / MODEL_NAME
EXPECTED_MODEL_SHA256 = "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"
EXPECTED_MODEL_BYTES = 232589
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_SIDE = 8192
MAX_IMAGE_PIXELS = 16_000_000
INFERENCE_SIDE = 640
MAX_FACES = 32
MAX_RAW_CANDIDATES = 512
MAX_DETECTION_VIEWS = 5
TILE_FRACTION = 0.6
SCORE_THRESHOLD = 0.8
NMS_THRESHOLD = 0.3
# The public single-frame endpoint keeps its conservative threshold.  The
# classroom tracker gets a separate small-face budget because its candidates
# are still constrained by a fixed seat lane and are never treated as names.
TRACKING_TILE_FRACTION = 0.45
TRACKING_SCORE_THRESHOLD = 0.62
LOCK_TIMEOUT_SEC = 0.25
# Leave room for validation/response handling inside the 10-second gateway.
WORKER_TIMEOUT_SEC = 6.0
MAX_WORKER_OUTPUT_BYTES = 32 * 1024
_DETECTION_LOCK = Lock()
_SCORE_NOTE = "detection_score_not_identity_confidence; teacher_name_confirmation_required"


def _failure(reason: str) -> dict[str, Any]:
    return {"available": False, "model": MODEL_NAME, "faces": [],
            "reason": reason + "; no_network_download"}


def _success(faces: list[dict[str, Any]]) -> dict[str, Any]:
    reason = "face_position_candidates_only" if faces else "no_faces_detected"
    return {"available": True, "model": MODEL_NAME, "faces": faces,
            "reason": reason + "; " + _SCORE_NOTE}


def _validate_image_path(path: Path) -> dict[str, Any] | None:
    if not isinstance(path, Path) or str(path).startswith(("\\\\", "//")):
        return _failure("local_image_path_required")
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or path.is_symlink()
                or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            return _failure("regular_image_file_required")
        if not 0 < info.st_size <= MAX_IMAGE_BYTES:
            return _failure("image_byte_limit")
    except (OSError, ValueError):
        return _failure("image_unavailable")
    return None


def _validate_model(path: Path) -> dict[str, Any] | None:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.is_symlink():
            return _failure("model_invalid")
        if info.st_size != EXPECTED_MODEL_BYTES:
            return _failure("model_integrity_failed")
        with path.open("rb") as handle:
            contents = handle.read(EXPECTED_MODEL_BYTES + 1)
        if len(contents) != EXPECTED_MODEL_BYTES or hashlib.sha256(contents).hexdigest() != EXPECTED_MODEL_SHA256:
            return _failure("model_integrity_failed")
    except FileNotFoundError:
        return _failure("model_missing")
    except (OSError, ValueError):
        return _failure("model_unavailable")
    return None


def _collect_candidates(
    raw: Any, original_width: int, original_height: int,
    resized_width: int, resized_height: int, pad_x: int, pad_y: int,
    *, region: tuple[int, int, int, int] | None = None,
    score_threshold: float = SCORE_THRESHOLD,
) -> set[tuple[float, float, float, float, float]]:
    """Map bounded view predictions to the ORIGINAL image before global NMS.

    Region is a source-image (x, y, width, height) crop. Boxes crossing an
    artificial crop edge are discarded before clipping; original image edges
    still permit clipping. Never truncate to 32 at this stage: duplicate views
    must not displace independent candidates before NMS.
    """
    if raw is None:
        return set()
    dims = (original_width, original_height, resized_width, resized_height)
    if any(not isinstance(n, (int, float)) or not math.isfinite(n) or n <= 0 for n in dims):
        return set()
    if not all(math.isfinite(n) for n in (pad_x, pad_y)):
        return set()
    crop_x, crop_y, crop_width, crop_height = region or (0, 0, original_width, original_height)
    if (not all(math.isfinite(n) for n in (crop_x, crop_y, crop_width, crop_height))
            or crop_x < 0 or crop_y < 0 or crop_width <= 0 or crop_height <= 0
            or crop_x + crop_width > original_width or crop_y + crop_height > original_height):
        return set()
    candidates: set[tuple[float, float, float, float, float]] = set()
    try:
        for index, row in enumerate(raw):
            if index >= MAX_RAW_CANDIDATES:
                break
            try:
                if len(row) != 15:
                    continue
                values = [float(value) for value in row]
            except (TypeError, ValueError, OverflowError):
                continue
            if not all(math.isfinite(value) for value in values):
                continue
            x, y, width, height = values[:4]
            score = values[14]
            if width <= 0 or height <= 0 or not score_threshold <= score <= 1.0:
                continue
            # Keep precision; clipping rather than rounding preserves 0 < w/h
            # and x+w/y+h <= 1, including boxes exactly on the image boundary.
            right, bottom = x + width, y + height
            if not math.isfinite(right) or not math.isfinite(bottom):
                continue
            if ((crop_x > 0 and x < pad_x)
                    or (crop_y > 0 and y < pad_y)
                    or (crop_x + crop_width < original_width and right > pad_x + resized_width)
                    or (crop_y + crop_height < original_height and bottom > pad_y + resized_height)):
                continue
            local_x1 = min(1.0, max(0.0, (x - pad_x) / resized_width))
            local_y1 = min(1.0, max(0.0, (y - pad_y) / resized_height))
            local_x2 = min(1.0, max(0.0, (right - pad_x) / resized_width))
            local_y2 = min(1.0, max(0.0, (bottom - pad_y) / resized_height))
            x1 = min(1.0, (crop_x + local_x1 * crop_width) / original_width)
            y1 = min(1.0, (crop_y + local_y1 * crop_height) / original_height)
            x2 = min(1.0, (crop_x + local_x2 * crop_width) / original_width)
            y2 = min(1.0, (crop_y + local_y2 * crop_height) / original_height)
            if x2 <= x1 or y2 <= y1:
                continue
            candidates.add((score, x1, y1, x2 - x1, y2 - y1))
    except TypeError:
        return set()
    return candidates


def _format_candidates(ordered: list[tuple[float, float, float, float, float]]) -> list[dict[str, Any]]:
    return [{"candidate_id": f"face_{index:03d}",
             "bbox": {"x": x, "y": y, "width": width, "height": height}, "score": score}
            for index, (score, x, y, width, height) in enumerate(ordered, 1)]


def _normalize_faces(
    raw: Any, original_width: int, original_height: int,
    resized_width: int, resized_height: int, pad_x: int, pad_y: int,
) -> list[dict[str, Any]]:
    """Single-view normalization, also used to validate the worker response."""
    candidates = _collect_candidates(raw, original_width, original_height,
                                     resized_width, resized_height, pad_x, pad_y)
    ordered = sorted(candidates, key=lambda row: (-row[0], *row[1:]))[:MAX_FACES]
    return _format_candidates(ordered)


def _view_regions(
    width: int, height: int, *, fraction: float = TILE_FRACTION,
    max_views: int = MAX_DETECTION_VIEWS,
) -> list[tuple[int, int, int, int]]:
    """Full frame plus four overlapping crops; at most five finite-size views."""
    if width <= 0 or height <= 0:
        return []
    if not math.isfinite(fraction) or not 0 < fraction <= 1:
        return []
    tile_width, tile_height = math.ceil(width * fraction), math.ceil(height * fraction)
    regions = [(0, 0, width, height)]
    for y in (0, height - tile_height):
        for x in (0, width - tile_width):
            region = (x, y, tile_width, tile_height)
            if region not in regions:
                regions.append(region)
    return regions[:max(1, min(MAX_DETECTION_VIEWS, int(max_views)))]


def _merge_candidates(
    candidates: Any, *, score_threshold: float = SCORE_THRESHOLD,
) -> list[dict[str, Any]]:
    """Deterministic greedy NMS, suppressing IoU > 0.3; then assign local IDs."""
    bounded = set()
    for index, row in enumerate(candidates):
        if index >= MAX_DETECTION_VIEWS * MAX_RAW_CANDIDATES:
            break
        if len(row) != 5 or not all(math.isfinite(value) for value in row):
            continue
        score, x, y, width, height = row
        if (not score_threshold <= score <= 1 or x < 0 or y < 0 or width <= 0 or height <= 0
                or x + width > 1 or y + height > 1):
            continue
        bounded.add(tuple(row))
    kept = []
    for candidate in sorted(bounded, key=lambda row: (-row[0], *row[1:])):
        _, x, y, width, height = candidate
        suppressed = False
        for previous in kept:
            _, px, py, pw, ph = previous
            overlap_width = max(0.0, min(x + width, px + pw) - max(x, px))
            overlap_height = max(0.0, min(y + height, py + ph) - max(y, py))
            intersection = overlap_width * overlap_height
            union = width * height + pw * ph - intersection
            if union > 0 and intersection / union > NMS_THRESHOLD:
                suppressed = True
                break
        if not suppressed:
            kept.append(candidate)
            if len(kept) == MAX_FACES:
                break
    return _format_candidates(kept)


def _detect_in_process(path: Path, model_path: Path) -> dict[str, Any]:
    """Child-only implementation; public callers must use detect_faces()."""
    for problem in (_validate_image_path(path), _validate_model(model_path)):
        if problem is not None:
            return problem
    try:
        import cv2
        import numpy as np
    except (ImportError, OSError):
        return _failure("cv2_unavailable")
    if not hasattr(cv2, "FaceDetectorYN") or not callable(getattr(cv2.FaceDetectorYN, "create", None)):
        return _failure("cv2_face_detector_unavailable")
    try:
        with path.open("rb") as handle:
            contents = handle.read(MAX_IMAGE_BYTES + 1)
        if not 0 < len(contents) <= MAX_IMAGE_BYTES:
            return _failure("image_byte_limit")
        # imread(path) is deliberately avoided: imdecode supports Unicode paths.
        image = cv2.imdecode(np.frombuffer(contents, dtype=np.uint8), cv2.IMREAD_COLOR)
    except OSError:
        return _failure("image_unavailable")
    except Exception:
        return _failure("invalid_image_or_dimensions")
    if image is None or image.ndim != 3 or image.shape[2] != 3:
        return _failure("invalid_image")
    height, width = image.shape[:2]
    if not (0 < width <= MAX_IMAGE_SIDE and 0 < height <= MAX_IMAGE_SIDE and width * height <= MAX_IMAGE_PIXELS):
        return _failure("image_dimensions_exceeded")
    try:
        cv2.setNumThreads(1)
        # Fixed 640x640 is the model's exported shape; also works with OpenCV 5
        # fixed-shape inference engines. No runtime/model substitution is needed.
        detector = cv2.FaceDetectorYN.create(
            str(model_path), "", (INFERENCE_SIDE, INFERENCE_SIDE),
            SCORE_THRESHOLD, NMS_THRESHOLD, MAX_RAW_CANDIDATES,
            cv2.dnn.DNN_BACKEND_OPENCV, cv2.dnn.DNN_TARGET_CPU,
        )
        candidates = set()
        for index, region in enumerate(_view_regions(width, height)):
            crop_x, crop_y, crop_width, crop_height = region
            crop = image[crop_y:crop_y + crop_height, crop_x:crop_x + crop_width]
            # The full view retains baseline scaling. Local crops are enlarged;
            # interpolation may help scale-sensitive detection, not add detail.
            ratio = INFERENCE_SIDE / max(crop_width, crop_height)
            if index == 0:
                ratio = min(1.0, ratio)
            resized_width, resized_height = max(1, round(crop_width * ratio)), max(1, round(crop_height * ratio))
            interpolation = cv2.INTER_LINEAR if ratio > 1 else cv2.INTER_AREA
            resized = cv2.resize(crop, (resized_width, resized_height), interpolation=interpolation)
            pad_x, pad_y = (INFERENCE_SIDE - resized_width) // 2, (INFERENCE_SIDE - resized_height) // 2
            canvas = np.zeros((INFERENCE_SIDE, INFERENCE_SIDE, 3), dtype=np.uint8)
            canvas[pad_y:pad_y + resized_height, pad_x:pad_x + resized_width] = resized
            _, raw = detector.detect(canvas)
            candidates.update(_collect_candidates(raw, width, height, resized_width, resized_height,
                                                  pad_x, pad_y, region=region))
        return _success(_merge_candidates(candidates))
    except Exception:
        # Never expose local image/model paths or native diagnostics in the API.
        return _failure("detection_failed")


def _run_worker(path: Path, model_path: Path) -> dict[str, Any]:
    env = dict(os.environ)
    env.update({"OPENCV_IO_MAX_IMAGE_WIDTH": str(MAX_IMAGE_SIDE),
                "OPENCV_IO_MAX_IMAGE_HEIGHT": str(MAX_IMAGE_SIDE),
                "OPENCV_IO_MAX_IMAGE_PIXELS": str(MAX_IMAGE_PIXELS),
                "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1", "OPENCV_LOG_LEVEL": "SILENT"})
    options: dict[str, Any] = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    completed = subprocess.run(
        [sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--worker", str(path), str(model_path)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        timeout=WORKER_TIMEOUT_SEC, check=False, env=env, **options,
    )
    if completed.returncode or len(completed.stdout) > MAX_WORKER_OUTPUT_BYTES:
        return _failure("worker_failed")
    try:
        payload = json.loads(completed.stdout)
        if not isinstance(payload, dict) or type(payload.get("available")) is not bool:
            return _failure("worker_invalid_response")
        if payload["available"]:
            # Revalidate across the process boundary; never pass through names
            # or unexpected native output, even if the worker is later changed.
            faces = payload.get("faces")
            if not isinstance(faces, list) or len(faces) > MAX_FACES:
                return _failure("worker_invalid_response")
            raw = []
            for face in faces:
                box = face["bbox"]
                raw.append([box["x"], box["y"], box["width"], box["height"], *([0.0] * 10), face["score"]])
            return _success(_normalize_faces(raw, 1, 1, 1, 1, 0, 0))
        allowed = {"model_missing", "model_invalid", "model_integrity_failed", "model_unavailable",
                   "cv2_unavailable", "cv2_face_detector_unavailable", "image_unavailable", "image_byte_limit",
                   "local_image_path_required", "regular_image_file_required", "invalid_image",
                   "image_dimensions_exceeded", "invalid_image_or_dimensions", "detection_failed"}
        reason = str(payload.get("reason", "")).split(";", 1)[0]
        return _failure(reason if reason in allowed else "worker_failed")
    except (ValueError, KeyError, TypeError, OverflowError):
        return _failure("worker_invalid_response")


def detect_faces(path: Path) -> dict[str, Any]:
    """Return at most 32 anonymous face-position candidates for a local image.

    ``available=True, faces=[]`` means detection completed with no candidates;
    ``available=False`` means detection did NOT complete. It is never proof of
    absence. Missing dependencies/models always fail closed without downloads.
    Candidate IDs have no cross-frame or cross-video identity meaning.
    """
    problem = _validate_image_path(path)
    if problem is not None:
        return problem
    problem = _validate_model(MODEL_PATH)
    if problem is not None:
        return problem
    if not _DETECTION_LOCK.acquire(timeout=LOCK_TIMEOUT_SEC):
        return _failure("detector_busy")
    try:
        return _run_worker(path.absolute(), MODEL_PATH.absolute())
    except subprocess.TimeoutExpired:
        return _failure("detection_timeout")
    except (OSError, ValueError):
        return _failure("worker_unavailable")
    finally:
        _DETECTION_LOCK.release()


def _worker_main() -> int:
    if len(sys.argv) != 4 or sys.argv[1] != "--worker":
        return 2
    # Native libraries sometimes write to stdout. Suppress their diagnostics,
    # then emit only our small, sanitized JSON on the original pipe.
    response_fd = os.dup(sys.stdout.fileno())
    try:
        with open(os.devnull, "wb") as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())
            try:
                result = _detect_in_process(Path(sys.argv[2]), Path(sys.argv[3]))
            except Exception:
                result = _failure("detection_failed")
        encoded = json.dumps(result, ensure_ascii=True, allow_nan=False).encode("ascii")
        if len(encoded) > MAX_WORKER_OUTPUT_BYTES:
            encoded = json.dumps(_failure("worker_failed")).encode("ascii")
        os.write(response_fd, encoded)
    finally:
        os.close(response_fd)
    return 0


if __name__ == "__main__":
    raise SystemExit(_worker_main())
