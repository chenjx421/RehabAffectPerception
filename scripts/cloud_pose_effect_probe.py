"""Private, offline MediaPipe Tasks pose experiment; never publishes app results."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import socket
import time
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime" / "pose_probe_20261021"
MODEL_URLS = {
    name: "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    f"pose_landmarker_{name}/float16/latest/pose_landmarker_{name}.task"
    for name in ("full", "lite")
}
NAMES = (
    "nose left_eye_inner left_eye left_eye_outer right_eye_inner right_eye "
    "right_eye_outer left_ear right_ear mouth_left mouth_right left_shoulder "
    "right_shoulder left_elbow right_elbow left_wrist right_wrist left_pinky "
    "right_pinky left_index right_index left_thumb right_thumb left_hip "
    "right_hip left_knee right_knee left_ankle right_ankle left_heel right_heel "
    "left_foot_index right_foot_index"
).split()
CONNECTIONS = (
    (11, 12), (11, 13), (13, 15), (15, 17), (15, 19), (15, 21),
    (12, 14), (14, 16), (16, 18), (16, 20), (16, 22),
    (11, 23), (12, 24), (23, 24), (23, 25), (24, 26),
    (25, 27), (26, 28), (27, 29), (28, 30), (29, 31), (30, 32),
)
GROUPS = {
    "upper_limb": (11, 12, 13, 14, 15, 16),
    "hip_knee": (23, 24, 25, 26),
}
COLORS = ("#00c55a", "#ff4141", "#247cff", "#cf32db", "#00b7c7")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def private_dir(path):
    path = path.resolve()
    if path == RUNTIME.resolve() or RUNTIME.resolve() in path.parents:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            path.chmod(0o700)
        return path
    raise ValueError("output_must_be_inside_isolated_runtime")


def save_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
    if os.name != "nt":
        path.chmod(0o600)


def download_models():
    destination = private_dir(RUNTIME / "models")
    records = []
    for name, url in MODEL_URLS.items():
        target = destination / f"pose_landmarker_{name}.task"
        if not target.exists():
            deadline = time.monotonic() + 90
            request = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(request, timeout=30) as response:
                if response.url != url or response.status != 200:
                    raise ValueError("unexpected_model_download_response")
                total = 0
                with target.open("xb") as stream:
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > 64 * 1024 * 1024 or time.monotonic() > deadline:
                            raise ValueError("model_download_limit")
                        stream.write(chunk)
        data = target.read_bytes()
        if not zipfile.is_zipfile(target) or len(data) < 1024 * 1024:
            raise ValueError("invalid_task_bundle")
        with zipfile.ZipFile(target) as bundle:
            if set(bundle.namelist()) != {"pose_detector.tflite", "pose_landmarks_detector.tflite"} or bundle.testzip() is not None:
                raise ValueError("invalid_task_bundle_contents")
        records.append({"name": name, "url": url, "bytes": len(data), "sha256": digest(data)})
    save_json(destination / "downloads.private.json", records)
    print(json.dumps({"downloaded": [item["name"] for item in records]}))


def deny_network():
    def forbidden(*args, **kwargs):
        raise RuntimeError("network_forbidden_during_pose_probe")
    socket.create_connection = forbidden
    socket.getaddrinfo = forbidden
    socket.socket.connect = forbidden
    socket.socket.connect_ex = forbidden


def checked_box(value, size):
    if not isinstance(value, list) or len(value) != 4 or any(type(x) is not int for x in value):
        raise ValueError("invalid_crop")
    x0, y0, x1, y1 = value
    if not (0 <= x0 < x1 <= size[0] and 0 <= y0 < y1 <= size[1]):
        raise ValueError("crop_out_of_bounds")
    return tuple(value)


def landmarks_data(result, crop_box, photo_size, threshold):
    x0, y0, x1, y1 = crop_box
    poses = []
    for index, raw in enumerate(result.pose_landmarks):
        points = []
        for number, point in enumerate(raw):
            values = [float(getattr(point, key)) for key in ("x", "y", "z", "visibility", "presence")]
            if not all(math.isfinite(value) for value in values):
                raise ValueError("nonfinite_landmark")
            x, y, z, visibility, presence = values
            points.append({
                "index": number, "name": NAMES[number], "crop_x": x, "crop_y": y, "z": z,
                "photo_x": (x0 + x * (x1 - x0)) / photo_size[0],
                "photo_y": (y0 + y * (y1 - y0)) / photo_size[1],
                "visibility": visibility, "presence": presence,
                "passes_display_gate": visibility >= threshold and presence >= threshold and 0 <= x <= 1 and 0 <= y <= 1,
            })
        poses.append({
            "pose_index": index, "landmarks": points,
            "joint_gate_counts_not_accuracy": {
                name: {"passing": sum(points[i]["passes_display_gate"] for i in indices), "total": len(indices)}
                for name, indices in GROUPS.items()
            },
            "target_correspondence": "manual_visual_review_required_not_auto_assigned",
            "behavior": None, "student_identity": None, "score": None,
        })
    return poses


def draw_skeleton(image, poses, *, photo_coordinates=False):
    from PIL import ImageDraw
    output = image.copy()
    draw = ImageDraw.Draw(output)
    width, height = output.size
    for pose in poses:
        color = COLORS[pose["pose_index"] % len(COLORS)]
        points = pose["landmarks"]

        def xy(point):
            prefix = "photo" if photo_coordinates else "crop"
            return point[f"{prefix}_x"] * width, point[f"{prefix}_y"] * height

        for start, end in CONNECTIONS:
            if points[start]["passes_display_gate"] and points[end]["passes_display_gate"]:
                draw.line((xy(points[start]), xy(points[end])), fill=color, width=2)
        for point in points:
            if point["passes_display_gate"]:
                x, y = xy(point)
                draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color)
                if point["index"] in range(11, 17) or point["index"] in range(23, 27):
                    draw.text((x + 3, y), str(point["index"]), fill=color, stroke_width=1, stroke_fill="black")
        if points:
            x, y = xy(points[0])
            if 0 <= x < width and 0 <= y < height:
                draw.text((x, max(0, y - 15)), f"P{pose['pose_index']}", fill=color)
    return output


def run(args):
    import mediapipe as mp
    import numpy as np
    from PIL import Image
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision

    deny_network()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    output = private_dir(args.output_dir)
    if any(output.iterdir()):
        raise ValueError("output_not_empty_no_overwrite")
    if len(plan["cases"]) != 4:
        raise ValueError("expected_three_targets_and_one_adult_control")
    threshold = 0.5
    model_info = []
    for name in ("full", "lite"):
        path = RUNTIME / "models" / f"pose_landmarker_{name}.task"
        model_info.append({"name": name, "sha256": digest(path.read_bytes())})
    summary = {
        "schema_version": "private_local_pose_effect_probe_v1",
        "classification": "sensitive_internal_do_not_publish",
        "runtime_versions": {name: importlib.metadata.version(name) for name in ("mediapipe", "numpy", "Pillow")},
        "models": model_info, "network_during_inference": "python_socket_connections_blocked",
        "plan_sha256": digest(args.plan.read_bytes()),
        "input_boundary": "Only left photo pixels from authorized local contact sheets; original 1600px inputs unavailable locally. Existing region overlays remain.",
        "identity_boundary": "Frame-local, manually chosen candidate regions; no names, student identity, scoring or automatic roles.",
        "interpretation": "Detection and joint gates are NOT behavior correctness. Occluded estimates are not proof of visible hip/knee positions. No cross-frame tracking.",
        "display_gate": {"visibility": threshold, "presence": threshold},
        "frames": [], "cases": [], "effectiveness_passed": None,
    }
    photos = {}
    for item in plan["frames"]:
        source = (args.contact_dir / item["filename"]).resolve()
        if source.parent != args.contact_dir.resolve() or source.suffix.lower() != ".png":
            raise ValueError("invalid_input_source")
        if source.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("input_too_large")
        with Image.open(source) as contact:
            if list(contact.size) != item["contact_size"]:
                raise ValueError("unexpected_contact_dimensions")
            box = checked_box(item["photo_box"], contact.size)
            photo = contact.convert("RGB").crop(box)
        photo.save(output / f"{item['frame_id']}.photo.private.png")
        photos[item["frame_id"]] = photo
        summary["frames"].append({**item, "contact_sha256": digest(source.read_bytes()), "photo_rgb_sha256": digest(photo.tobytes())})

    for model in model_info:
        model_name = model["name"]
        options = vision.PoseLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=str(RUNTIME / "models" / f"pose_landmarker_{model_name}.task"), delegate=python.BaseOptions.Delegate.CPU),
            running_mode=vision.RunningMode.IMAGE, num_poses=12,
            min_pose_detection_confidence=0.5, min_pose_presence_confidence=0.5,
            output_segmentation_masks=False,
        )
        with vision.PoseLandmarker.create_from_options(options) as detector:
            items = [{"case_id": f"{item['frame_id']}_full", "frame_id": item["frame_id"], "kind": "full_photo_control"} for item in plan["frames"]]
            items.extend(plan["cases"])
            for case in items:
                photo = photos[case["frame_id"]]
                box = checked_box(case.get("crop_box", [0, 0, *photo.size]), photo.size)
                crop = photo.crop(box)
                rgb = np.array(crop, dtype=np.uint8)
                started = time.monotonic()
                result = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
                elapsed = time.monotonic() - started
                poses = landmarks_data(result, box, photo.size, threshold)
                stem = f"{case['case_id']}.{model_name}"
                crop.save(output / f"{stem}.input.private.png")
                skeleton = draw_skeleton(crop, poses)
                if skeleton.width < 640:
                    skeleton = skeleton.resize((skeleton.width * 3, skeleton.height * 3), Image.Resampling.NEAREST)
                skeleton.save(output / f"{stem}.skeleton.private.png")
                draw_skeleton(photo, poses, photo_coordinates=True).save(output / f"{stem}.mapped.private.png")
                record = {
                    **case, "model": model_name, "crop_box": list(box), "input_size": list(crop.size),
                    "crop_rgb_sha256": digest(crop.tobytes()), "elapsed_sec": elapsed,
                    "poses_detected_not_correctness": len(poses), "poses": poses,
                }
                save_json(output / f"{stem}.landmarks.private.json", record)
                summary["cases"].append({key: value for key, value in record.items() if key != "poses"})
                print(json.dumps({"case": case["case_id"], "model": model_name, "poses": len(poses), "seconds": round(elapsed, 3)}), flush=True)
    save_json(output / "summary.private.json", summary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download-models", action="store_true")
    parser.add_argument("--contact-dir", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.download_models:
        if any((args.contact_dir, args.plan, args.output_dir)):
            parser.error("downloads_and_image_inference_are_separate")
        download_models()
    else:
        if not all((args.contact_dir, args.plan, args.output_dir)):
            parser.error("contact_dir_plan_output_dir_required")
        run(args)


if __name__ == "__main__":
    main()
