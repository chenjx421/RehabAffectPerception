"""Local face-position candidates: synthetic images and mocked YuNet rows only."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from rehab_affect import demo2_face_detection as detection


def _row(x=100, y=100, width=100, height=100, score=0.95):
    return [x, y, width, height, *([0.0] * 10), score]


def _normalize(rows, **overrides):
    arguments = dict(
        original_width=640, original_height=640,
        resized_width=640, resized_height=640, pad_x=0, pad_y=0,
    )
    arguments.update(overrides)
    return detection._normalize_faces(np.asarray(rows, dtype=np.float64), **arguments)


def _assert_contract(result, *, available):
    assert set(result) == {"available", "model", "faces", "reason"}
    assert result["available"] is available
    assert isinstance(result["model"], str) and result["model"]
    assert isinstance(result["reason"], str) and result["reason"]
    assert isinstance(result["faces"], list)
    assert len(result["faces"]) <= 32
    if not available:
        assert result["faces"] == []
    for index, face in enumerate(result["faces"], start=1):
        assert set(face) == {"candidate_id", "bbox", "score"}
        assert face["candidate_id"] == f"face_{index:03d}"
        box = face["bbox"]
        assert set(box) == {"x", "y", "width", "height"}
        assert all(math.isfinite(value) for value in [face["score"], *box.values()])
        assert 0 <= face["score"] <= 1
        assert 0 <= box["x"] < 1 and 0 <= box["y"] < 1
        assert 0 < box["width"] <= 1 and 0 < box["height"] <= 1
        assert box["x"] + box["width"] <= 1 + 1e-7
        assert box["y"] + box["height"] <= 1 + 1e-7
    # The public payload must remain strict JSON, with no NaN/Infinity extensions.
    json.dumps(result, allow_nan=False)


@pytest.fixture
def mock_model(tmp_path, monkeypatch):
    path = tmp_path / "synthetic-not-an-onnx-model.onnx"
    content = b"unit-test-model-contents-not-for-real-inference"
    path.write_bytes(content)
    monkeypatch.setattr(detection, "MODEL_PATH", path)
    monkeypatch.setattr(detection, "EXPECTED_MODEL_BYTES", len(content))
    monkeypatch.setattr(detection, "EXPECTED_MODEL_SHA256", hashlib.sha256(content).hexdigest())
    return path


@pytest.fixture
def blank_image(tmp_path):
    cv2 = pytest.importorskip("cv2")
    # imwrite is intentionally not used: this tests the Unicode-path byte workflow.
    path = tmp_path / "合成空白帧_非真人.png"
    ok, encoded = cv2.imencode(".png", np.zeros((180, 320, 3), dtype=np.uint8))
    assert ok
    path.write_bytes(encoded.tobytes())
    return path


def _mock_detector(monkeypatch, rows=None, *, predictions=None, images=None):
    cv2 = pytest.importorskip("cv2")
    calls = []
    pending = iter(predictions) if predictions is not None else None

    class MockDetector:
        def setInputSize(self, size):
            calls.append(("input_size", size))

        def detect(self, image):
            calls.append(("detect", image.shape))
            if images is not None:
                images.append(image.copy())
            current = next(pending) if pending is not None else rows
            return 1, np.asarray(current, dtype=np.float32) if current is not None else None

    def create(*args, **kwargs):
        calls.append(("create", args, kwargs))
        return MockDetector()

    monkeypatch.setattr(cv2, "FaceDetectorYN", SimpleNamespace(create=create))
    return calls


def test_resource_limits_are_explicit_and_bounded():
    assert 0 < detection.MAX_IMAGE_BYTES <= 8 * 1024 * 1024
    assert 0 < detection.MAX_IMAGE_SIDE <= 8192
    assert 0 < detection.MAX_IMAGE_PIXELS <= 16_777_216
    assert detection.MAX_FACES == 32
    assert detection.INFERENCE_SIDE == 640


def test_normalized_box_uses_original_image_letterbox_geometry():
    faces = _normalize(
        [_row(x=64, y=192, width=128, height=96)],
        original_width=1280, original_height=640,
        resized_width=640, resized_height=320, pad_y=160,
    )
    assert len(faces) == 1
    assert faces[0]["bbox"] == pytest.approx(dict(x=0.1, y=0.1, width=0.2, height=0.3))


def test_partial_box_clips_to_image_and_padding_only_boxes_are_dropped():
    faces = _normalize(
        [
            _row(x=-32, y=144, width=96, height=80),
            _row(x=100, y=1, width=100, height=50),
            _row(x=641, y=200, width=100, height=50),
        ],
        original_width=1280, original_height=640,
        resized_width=640, resized_height=320, pad_y=160,
    )
    assert len(faces) == 1
    assert faces[0]["bbox"] == pytest.approx(dict(x=0, y=0, width=0.1, height=0.2))


@pytest.mark.parametrize("column", range(15))
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_detector_rows_are_not_candidates(column, value):
    row = _row()
    row[column] = value
    assert _normalize([row]) == []


@pytest.mark.parametrize("width,height,score", [
    (0, 100, 0.95), (-1, 100, 0.95), (100, 0, 0.95), (100, -1, 0.95),
    (100, 100, -0.1), (100, 100, 1.01), (100, 100, 0.01),
])
def test_invalid_geometry_or_score_is_not_a_candidate(width, height, score):
    assert _normalize([_row(width=width, height=height, score=score)]) == []


def test_candidates_are_capped_and_stably_sorted_independent_of_detector_order():
    rows = [_row(x=10 + index * 7, y=20, width=4, height=5, score=0.99 - index % 3 * 0.01)
            for index in range(48)]
    first = _normalize(rows)
    assert len(first) == detection.MAX_FACES == 32
    assert first == _normalize(list(reversed(rows)))
    assert [face["score"] for face in first] == sorted(
        [face["score"] for face in first], reverse=True,
    )
    assert [face["candidate_id"] for face in first] == [f"face_{index:03d}" for index in range(1, 33)]


def test_exact_duplicate_predictions_do_not_invent_multiple_people():
    row = _row()
    assert _normalize([row, row, row]) == _normalize([row])


def test_no_detection_rows_produces_no_invented_candidate():
    assert _normalize([]) == []
    assert detection._normalize_faces(None, 640, 640, 640, 640, 0, 0) == []


def test_mock_yunet_uses_unicode_image_and_only_emits_position_candidates(
    blank_image, mock_model, monkeypatch,
):
    # Small frames are not enlarged: 320x180 has left/top padding of 160/230.
    calls = _mock_detector(monkeypatch, predictions=[
        [_row(x=192, y=248, width=64, height=36)], None, None, None, None,
    ])
    result = detection._detect_in_process(blank_image, mock_model)
    _assert_contract(result, available=True)
    assert "detection_score_not_identity_confidence" in result["reason"]
    assert len(result["faces"]) == 1
    assert result["faces"][0]["bbox"] == pytest.approx(dict(x=0.1, y=0.1, width=0.2, height=0.2))
    assert ("detect", (640, 640, 3)) in calls
    assert "student_id" not in result and "name" not in result


def test_tile_regions_have_explicit_overlap_ceil_rounding_and_original_bounds():
    regions = detection._view_regions(641, 359)
    assert regions[0] == (0, 0, 641, 359)
    assert set(regions[1:]) == {
        (0, 0, 385, 216), (256, 0, 385, 216),
        (0, 143, 385, 216), (256, 143, 385, 216),
    }
    assert len(regions) == 5


@pytest.mark.parametrize("width,height", [(1, 1), (2, 2), (1, 11), (11, 1), (3, 3)])
def test_tiny_and_thin_images_never_generate_empty_or_duplicate_tiles(width, height):
    regions = detection._view_regions(width, height)
    assert regions[0] == (0, 0, width, height)
    assert len(regions) == len(set(regions)) <= 5
    for x, y, crop_width, crop_height in regions:
        assert all(isinstance(value, int) for value in (x, y, crop_width, crop_height))
        assert 0 <= x < width and 0 <= y < height
        assert 0 < crop_width <= width - x and 0 < crop_height <= height - y
    if (width, height) in {(1, 1), (2, 2)}:
        assert len(regions) == 1


def test_tile_candidates_map_back_to_whole_image_not_tile_coordinates():
    rows = [_row(x=64, y=192, width=128, height=96)]
    candidates = detection._collect_candidates(
        rows, 1000, 600, 640, 384, 0, 128, region=(400, 240, 600, 360),
    )
    assert len(candidates) == 1
    assert next(iter(candidates)) == pytest.approx((0.95, 0.46, 0.50, 0.12, 0.15))


def test_odd_tile_geometry_uses_actual_resized_dimensions_in_each_axis():
    candidates = detection._collect_candidates(
        [_row(x=64, y=175.9, width=128, height=71.8)],
        641, 359, 640, 359, 0, 140, region=(256, 143, 385, 216),
    )
    assert len(candidates) == 1
    assert next(iter(candidates)) == pytest.approx(
        (0.95, (256 + 38.5) / 641, (143 + 21.6) / 359, 77 / 641, 43.2 / 359),
    )


@pytest.mark.parametrize("region,row", [
    ((400, 240, 600, 360), _row(x=-1, y=192, width=64, height=32)),
    ((400, 240, 600, 360), _row(x=64, y=127, width=64, height=32)),
    ((0, 0, 600, 360), _row(x=630, y=192, width=20, height=32)),
    ((0, 0, 600, 360), _row(x=64, y=500, width=64, height=20)),
])
def test_boxes_crossing_artificial_tile_edges_are_dropped_before_clipping(region, row):
    assert detection._collect_candidates(
        [row], 1000, 600, 640, 384, 0, 128, region=region,
    ) == set()


def test_original_image_border_can_clip_and_padding_only_boxes_are_dropped():
    candidates = detection._collect_candidates(
        [
            _row(x=-32, y=112, width=96, height=80),
            _row(x=64, y=10, width=64, height=20),
        ],
        1000, 600, 640, 384, 0, 128, region=(0, 0, 600, 360),
    )
    assert len(candidates) == 1
    assert next(iter(candidates)) == pytest.approx((0.95, 0, 0, 0.06, 0.1))


def test_overlapping_tile_can_recover_candidate_cut_at_other_tile_edge():
    cut = detection._collect_candidates(
        [_row(x=620, y=256, width=64, height=64)],
        1000, 600, 640, 384, 0, 128, region=(0, 0, 600, 360),
    )
    complete = detection._collect_candidates(
        [_row(x=193.33333333333334, y=256, width=64, height=64)],
        1000, 600, 640, 384, 0, 128, region=(400, 0, 600, 360),
    )
    assert cut == set()
    assert len(complete) == 1
    assert next(iter(complete)) == pytest.approx((0.95, 0.58125, 0.2, 0.06, 0.1))


def test_global_nms_merges_cross_view_jitter_but_keeps_neighboring_faces():
    rows = [
        (0.95, 0.10, 0.10, 0.10, 0.10),
        (0.96, 0.102, 0.102, 0.10, 0.10),
        (0.94, 0.098, 0.099, 0.102, 0.102),
        (0.93, 0.19, 0.10, 0.10, 0.10),
    ]
    faces = detection._merge_candidates(rows)
    assert len(faces) == 2
    assert faces[0]["score"] == 0.96
    assert faces[0]["bbox"] == pytest.approx(dict(x=0.102, y=0.102, width=0.1, height=0.1))
    assert faces[1]["bbox"]["x"] == pytest.approx(0.19)


def test_global_nms_order_and_candidate_ids_do_not_depend_on_view_order():
    candidates = [
        (0.95, 0.102, 0.102, 0.1, 0.1),
        (0.95, 0.100, 0.100, 0.1, 0.1),
        (0.95, 0.5, 0.2, 0.1, 0.1),
        (0.94, 0.7, 0.5, 0.1, 0.1),
    ]
    expected = detection._merge_candidates(candidates)
    assert len(expected) == 3
    assert expected[0]["bbox"]["x"] == 0.1
    for reordered in (list(reversed(candidates)), candidates[2:] + candidates[:2]):
        assert detection._merge_candidates(reordered) == expected
    assert [face["candidate_id"] for face in expected] == ["face_001", "face_002", "face_003"]


@pytest.mark.parametrize("relative_to_threshold,expected_count", [(-1, 1), (0, 2), (1, 2)])
def test_global_nms_suppresses_strictly_greater_iou_only(monkeypatch, relative_to_threshold, expected_count):
    # Binary-exact coordinates make IoU exactly 1/3; vary the threshold, not geometry.
    candidates = [(0.95, 0, 0, 0.25, 0.25), (0.94, 0.125, 0, 0.25, 0.25)]
    monkeypatch.setattr(detection, "NMS_THRESHOLD", 1 / 3 + relative_to_threshold * 1e-9)
    assert len(detection._merge_candidates(candidates)) == expected_count


def test_global_nms_is_greedy_not_transitive_connected_component_merging():
    faces = detection._merge_candidates([
        (0.99, 0, 0, 0.25, 0.25),
        (0.98, 0.125, 0, 0.25, 0.25),
        (0.97, 0.25, 0, 0.25, 0.25),
    ])
    assert len(faces) == 2
    assert [face["bbox"]["x"] for face in faces] == [0, 0.25]


def test_global_limit_is_applied_after_nms_not_before_independent_faces():
    raw = [_row(x=1 + index * 0.01, y=1, width=10, height=10, score=0.99)
           for index in range(40)]
    raw += [_row(x=20 + index * 12, y=50, width=5, height=5, score=0.9)
            for index in range(40)]
    candidates = detection._collect_candidates(raw, 640, 640, 640, 640, 0, 0)
    assert len(candidates) == 80
    faces = detection._merge_candidates(candidates)
    assert len(faces) == 32
    assert sum(face["bbox"]["y"] == pytest.approx(50 / 640) for face in faces) == 31
    assert faces[-1]["candidate_id"] == "face_032"


def test_per_view_raw_candidate_processing_remains_bounded():
    def raw():
        for _ in range(detection.MAX_RAW_CANDIDATES + 1):
            yield _row()
        pytest.fail("read beyond bounded YuNet candidate rows")

    candidates = detection._collect_candidates(raw(), 640, 640, 640, 640, 0, 0)
    assert len(candidates) == 1


def test_five_views_reuse_one_detector_and_upscale_only_tiles(tmp_path, mock_model, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    path = tmp_path / "合成纯色帧_非真人.png"
    ok, encoded = cv2.imencode(".png", np.full((180, 320, 3), 200, dtype=np.uint8))
    assert ok
    path.write_bytes(encoded.tobytes())
    images = []
    calls = _mock_detector(monkeypatch, predictions=[None] * 5, images=images)
    result = detection._detect_in_process(path, mock_model)
    _assert_contract(result, available=True)
    assert result["faces"] == []
    creations = [call for call in calls if call[0] == "create"]
    assert len(creations) == 1
    assert creations[0][1][3] == detection.SCORE_THRESHOLD == 0.8
    assert [call for call in calls if call[0] == "detect"] == [("detect", (640, 640, 3))] * 5
    occupied_shapes = []
    for image in images:
        y, x = np.nonzero(image[:, :, 0])
        occupied_shapes.append((int(x.max() - x.min() + 1), int(y.max() - y.min() + 1)))
    assert occupied_shapes == [(320, 180)] + [(640, 360)] * 4


def test_mock_yunet_no_faces_is_success_not_model_unavailable(blank_image, mock_model, monkeypatch):
    _mock_detector(monkeypatch, None)
    result = detection._detect_in_process(blank_image, mock_model)
    _assert_contract(result, available=True)
    assert result["faces"] == []
    assert "detection_score_not_identity_confidence" in result["reason"]


def test_missing_model_never_attempts_worker(blank_image, tmp_path, monkeypatch):
    monkeypatch.setattr(detection, "MODEL_PATH", tmp_path / "missing.onnx")
    monkeypatch.setattr(detection, "_run_worker", lambda *args: pytest.fail("missing model started worker"))
    result = detection.detect_faces(blank_image)
    _assert_contract(result, available=False)
    assert "no_network_download" in result["reason"]


def test_missing_cv2_degrades_without_network(blank_image, mock_model, monkeypatch):
    monkeypatch.setitem(sys.modules, "cv2", None)
    result = detection._detect_in_process(blank_image, mock_model)
    _assert_contract(result, available=False)
    assert "no_network_download" in result["reason"]


def test_opencv_without_yunet_degrades_without_network(blank_image, mock_model, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    monkeypatch.delattr(cv2, "FaceDetectorYN", raising=False)
    result = detection._detect_in_process(blank_image, mock_model)
    _assert_contract(result, available=False)
    assert "no_network_download" in result["reason"]


@pytest.mark.parametrize("problem", ["size", "hash"])
def test_model_integrity_failure_never_starts_worker(blank_image, mock_model, monkeypatch, problem):
    if problem == "size":
        mock_model.write_bytes(mock_model.read_bytes() + b"corrupt")
    else:
        monkeypatch.setattr(detection, "EXPECTED_MODEL_SHA256", "0" * 64)
    monkeypatch.setattr(detection, "_run_worker", lambda *args: pytest.fail("invalid model started worker"))
    result = detection.detect_faces(blank_image)
    _assert_contract(result, available=False)
    assert "model_integrity_failed" in result["reason"]
    assert "no_network_download" in result["reason"]


@pytest.mark.parametrize("shape", [(1, 8193, 3), (8193, 1, 3), (4096, 4096, 3)])
def test_oversized_decoded_image_is_rejected_before_dnn(
    blank_image, mock_model, monkeypatch, shape,
):
    cv2 = pytest.importorskip("cv2")
    # No large allocation: the mock represents a decompression-bomb dimension.
    monkeypatch.setattr(cv2, "imdecode", lambda *args: SimpleNamespace(ndim=3, shape=shape))
    calls = _mock_detector(monkeypatch, [])
    result = detection._detect_in_process(blank_image, mock_model)
    _assert_contract(result, available=False)
    assert "image_dimensions_exceeded" in result["reason"]
    assert not calls


@pytest.mark.parametrize("payload", [b"", b"this is not an image", b"\x89PNG\r\n\x1a\ncorrupt"])
def test_invalid_image_cannot_produce_fake_candidates(tmp_path, mock_model, payload):
    path = tmp_path / "invalid.png"
    path.write_bytes(payload)
    result = detection._detect_in_process(path, mock_model)
    _assert_contract(result, available=False)


@pytest.mark.parametrize("kind", ["missing", "directory", "too_large"])
def test_invalid_input_is_rejected_before_worker(tmp_path, mock_model, monkeypatch, kind):
    path = tmp_path / "input.png"
    if kind == "directory":
        path.mkdir()
    elif kind == "too_large":
        with path.open("wb") as stream:
            stream.truncate(detection.MAX_IMAGE_BYTES + 1)
    monkeypatch.setattr(detection, "_run_worker", lambda *args: pytest.fail("invalid input started worker"))
    result = detection.detect_faces(path)
    _assert_contract(result, available=False)


def test_worker_timeout_returns_unavailable_without_candidates(blank_image, mock_model, monkeypatch):
    def timeout(*args):
        raise subprocess.TimeoutExpired("synthetic-test-worker", detection.WORKER_TIMEOUT_SEC)

    monkeypatch.setattr(detection, "_run_worker", timeout)
    result = detection.detect_faces(blank_image)
    _assert_contract(result, available=False)
    assert "timeout" in result["reason"]
    # The timeout path must release the lock, so it cannot block later requests.
    assert detection._DETECTION_LOCK.acquire(blocking=False)
    detection._DETECTION_LOCK.release()


def test_busy_lock_rejects_concurrent_request_without_starting_worker(blank_image, mock_model, monkeypatch):
    monkeypatch.setattr(detection, "LOCK_TIMEOUT_SEC", 0.01)
    monkeypatch.setattr(detection, "_run_worker", lambda *args: pytest.fail("busy lock started worker"))
    assert detection._DETECTION_LOCK.acquire(blocking=False)
    try:
        result = detection.detect_faces(blank_image)
    finally:
        detection._DETECTION_LOCK.release()
    _assert_contract(result, available=False)


def _mock_child(monkeypatch, payload, returncode=0):
    observed = {}
    encoded = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")

    def run(command, **kwargs):
        observed.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, returncode, stdout=encoded)

    monkeypatch.setattr(detection.subprocess, "run", run)
    return observed


def test_worker_uses_hard_timeout_decode_limits_and_sanitized_payload(
    blank_image, mock_model, monkeypatch,
):
    observed = _mock_child(monkeypatch, {
        "available": True, "model": "unexpected-model-value", "reason": "identity confidence",
        "student_id": "untrusted", "faces": [{
            "candidate_id": "untrusted-cross-frame-id", "name": "untrusted",
            "bbox": dict(x=0.1, y=0.2, width=0.3, height=0.4), "score": 0.9,
        }],
    })
    result = detection._run_worker(blank_image, mock_model)
    _assert_contract(result, available=True)
    assert "detection_score_not_identity_confidence" in result["reason"]
    assert "untrusted" not in json.dumps(result)
    assert observed["timeout"] == detection.WORKER_TIMEOUT_SEC == 6.0
    assert observed["stdin"] == subprocess.DEVNULL
    assert observed["stderr"] == subprocess.DEVNULL
    assert "-I" in observed["command"] and "-B" in observed["command"]
    assert observed["env"]["OPENCV_IO_MAX_IMAGE_WIDTH"] == str(detection.MAX_IMAGE_SIDE)
    assert observed["env"]["OPENCV_IO_MAX_IMAGE_HEIGHT"] == str(detection.MAX_IMAGE_SIDE)
    assert observed["env"]["OPENCV_IO_MAX_IMAGE_PIXELS"] == str(detection.MAX_IMAGE_PIXELS)
    assert observed["env"]["OMP_NUM_THREADS"] == "1"
    if sys.platform == "win32":
        assert observed["creationflags"] & subprocess.CREATE_NO_WINDOW


@pytest.mark.parametrize("payload", [
    b"not-json", [], {"available": "true", "faces": []},
    {"available": True, "faces": "not-a-list"},
    {"available": True, "faces": [{}]},
    {"available": True, "faces": [{}] * 33},
])
def test_malformed_worker_response_fails_without_candidates(blank_image, mock_model, monkeypatch, payload):
    _mock_child(monkeypatch, payload)
    result = detection._run_worker(blank_image, mock_model)
    _assert_contract(result, available=False)


@pytest.mark.parametrize(
    "returncode,payload", [(1, b"error"), (0, b"x" * (32 * 1024 + 1))],
    ids=["nonzero_exit", "oversized_output"],
)
def test_worker_error_or_oversized_response_is_not_exposed(
    blank_image, mock_model, monkeypatch, returncode, payload,
):
    _mock_child(monkeypatch, payload, returncode=returncode)
    result = detection._run_worker(blank_image, mock_model)
    _assert_contract(result, available=False)
    assert str(blank_image) not in result["reason"]


def test_synthetic_blank_image_real_yunet_has_no_face_candidates(blank_image):
    cv2 = pytest.importorskip("cv2")
    if not hasattr(cv2, "FaceDetectorYN"):
        pytest.skip("local OpenCV does not provide FaceDetectorYN")
    if not detection.MODEL_PATH.is_file():
        pytest.skip("official model not installed; tests never download it")
    result = detection.detect_faces(blank_image)
    _assert_contract(result, available=True)
    assert result["faces"] == []
    assert "detection_score_not_identity_confidence" in result["reason"]


def test_real_worker_rejects_oversized_synthetic_png_before_inference(tmp_path):
    cv2 = pytest.importorskip("cv2")
    if not hasattr(cv2, "FaceDetectorYN"):
        pytest.skip("local OpenCV does not provide FaceDetectorYN")
    if not detection.MODEL_PATH.is_file():
        pytest.skip("official model not installed; tests never download it")
    path = tmp_path / "超宽合成空白帧_非真人.png"
    ok, encoded = cv2.imencode(".png", np.zeros((1, 8193, 3), dtype=np.uint8))
    assert ok
    assert len(encoded) < detection.MAX_IMAGE_BYTES
    path.write_bytes(encoded.tobytes())
    result = detection.detect_faces(path)
    _assert_contract(result, available=False)
    assert result["reason"].split(";", 1)[0] in {
        "image_dimensions_exceeded", "invalid_image_or_dimensions",
    }
