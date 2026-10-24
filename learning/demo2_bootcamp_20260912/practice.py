"""Read-only project learning exercises. No live DB or identity writes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def model_info() -> dict:
    from src.rehab_affect import demo2_face_detection as face

    path = face.MODEL_PATH
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    return {
        "name": face.MODEL_NAME,
        "bytes": len(data),
        "sha256": digest,
        "integrity_ok": digest == face.EXPECTED_MODEL_SHA256 and len(data) == face.EXPECTED_MODEL_BYTES,
        "inference_side": face.INFERENCE_SIDE,
        "score_threshold": face.SCORE_THRESHOLD,
        "nms_threshold": face.NMS_THRESHOLD,
        "max_views": face.MAX_DETECTION_VIEWS,
        "trained_in_this_project": False,
        "scope": "face_position_candidates_only",
    }


def self_check() -> dict:
    import cv2 as cv
    import numpy as np
    from src.rehab_affect.demo2_face_detection import _collect_candidates, _merge_candidates

    checks = []
    box = tuple(v / d for v, d in zip((160, 90, 128, 72), (640, 360, 640, 360)))
    assert box == (0.25, 0.25, 0.2, 0.2)
    checks.append({"topic": "normalized_bbox", "answer": box})
    intersection = 80 * 100
    iou = intersection / (10000 + 10000 - intersection)
    assert abs(iou - 2 / 3) < 1e-9
    checks.append({"topic": "IoU", "answer": iou})
    raw = [[160, 230, 128, 72] + [0] * 10 + [0.9]]
    recovered = _collect_candidates(raw, 640, 360, 640, 360, 0, 140)
    assert recovered == {(0.9, 0.25, 0.25, 0.2, 0.2)}
    checks.append({"topic": "letterbox_backmap", "answer": list(recovered)})
    kept = _merge_candidates({(0.95, .1, .1, .2, .2), (.85, .11, .1, .2, .2), (.9, .65, .6, .15, .2)})
    assert len(kept) == 2
    checks.append({"topic": "production_NMS", "kept": len(kept)})
    samples = np.array([1., -1., 1., -1.])
    assert float(np.sqrt(np.mean(samples ** 2))) == 1.
    checks.append({"topic": "RMS", "answer": 1.0, "speaker": "unknown"})
    independent, prompted, errors, unknown = 3, 2, 1, 2
    count = independent + prompted + errors
    checks.append({"topic": "learning_opportunity_example", "independent_rate": independent / count,
                   "supported_completion_rate": (independent + prompted) / count, "unknown": unknown})
    # Synthetic arrays test local translation only; they do not depict students.
    rng = np.random.default_rng(7)
    first = rng.integers(0, 256, (128, 128), dtype=np.uint8)
    second = cv.warpAffine(first, np.float32([[1, 0, 2], [0, 1, 1]]), (128, 128))
    mask = np.zeros_like(first)
    mask[24:100, 24:100] = 255
    corners = cv.goodFeaturesToTrack(first, 80, .03, 4, mask=mask)
    moved, valid, _ = cv.calcOpticalFlowPyrLK(first, second, corners, None, winSize=(21, 21), maxLevel=3)
    assert moved is not None and valid is not None
    shift = np.median((moved - corners).reshape(-1, 2)[valid.ravel() == 1], axis=0)
    assert np.allclose(shift, (2, 1), atol=.3), shift
    checks.append({"topic": "synthetic_LK", "expected": [2, 1], "measured": shift.tolist(),
                   "real_classroom_accuracy": None})
    assert model_info()["integrity_ok"]
    return {"passed": len(checks) + 1, "checks": checks, "model_integrity": True, "live_data_written": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-check")
    sub.add_parser("model-info")
    detect = sub.add_parser("detect")
    detect.add_argument("--image", type=Path, required=True, help="Authorized local image, never a remote URL")
    args = parser.parse_args()
    if args.command == "self-check":
        result = self_check()
    elif args.command == "model-info":
        result = model_info()
    else:
        from src.rehab_affect.demo2_face_detection import detect_faces
        result = detect_faces(args.image)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
