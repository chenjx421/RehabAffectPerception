"""Select a small set of current evidence images without sending student metadata."""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import tempfile
import time


MAX_IMAGES = 8
MAX_IMAGE_BYTES = 1500000
MAX_PERSON_PROPOSALS = 12
MAX_MODEL_IMAGE_BYTES = 512 * 1024
COLOR_BUDGET_SEC = 30.0
SOURCE_HASH_TIMEOUT_SEC = 5.0
FRAME_PREP_BUDGET_SEC = 45.0


def _source_hash(source, signature, deadline):
    from rehab_affect import demo2_frame_preview as preview
    digest, size, timed_out = hashlib.sha256(), 0, False
    with source.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != signature[:4]:
            raise ValueError("source_changed")
        while True:
            if time.monotonic() >= deadline:
                timed_out = True
                break
            block = handle.read(1024 * 1024)
            if not block:
                break
            size += len(block)
            if size > signature[2]:
                raise ValueError("source_changed")
            digest.update(block)
        current = os.fstat(handle.fileno())
        if (current.st_size, current.st_mtime_ns, current.st_ctime_ns) != (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns):
            raise ValueError("source_changed")
    if preview._source_signature(source) != signature or (not timed_out and size != signature[2]):
        raise ValueError("source_changed")
    return None if timed_out else digest.hexdigest()


def _color_context(identities, task, job, deadline=None, verify_hash=False):
    source = identities._require_media(task)
    try:
        from rehab_affect import demo2_frame_preview as preview
    except ImportError:
        return {"failure": "hq_dependency_unavailable", "verified": False, "frames": {}}
    try:
        source = preview._local_source(source)
        signature = preview._source_signature(source)
    except (preview.PreviewError, preview.media_analysis.MediaAnalysisError, OSError):
        raise ValueError("source_unavailable") from None
    cached = job.get("_observation_color_cache")
    if cached is not None:
        if (cached["source"] != source or cached["signature"] != signature
                or cached["source_sha256"] != job["source_sha256"]):
            raise ValueError("source_changed")
        if verify_hash and cached["verified"]:
            digest = _source_hash(source, signature, time.monotonic() + SOURCE_HASH_TIMEOUT_SEC)
            if digest is None:
                raise ValueError("source_hash_recheck_timeout")
            if not hmac.compare_digest(digest, job["source_sha256"].lower()):
                raise ValueError("source_hash_mismatch")
        return cached
    color_deadline = time.monotonic() + COLOR_BUDGET_SEC
    if deadline is not None:
        color_deadline = min(color_deadline, deadline)
    context = {"source": source, "signature": signature, "source_sha256": job["source_sha256"],
               "deadline": color_deadline, "verified": False, "frames": {}, "failure": None}
    hash_deadline = min(context["deadline"], time.monotonic() + SOURCE_HASH_TIMEOUT_SEC)
    digest = _source_hash(source, signature, hash_deadline)
    if digest is None:
        context["failure"] = "source_hash_timeout"
    else:
        if not hmac.compare_digest(digest, job["source_sha256"].lower()):
            raise ValueError("source_hash_mismatch")
        context["verified"] = True
    job["_observation_color_cache"] = context
    return context


def _fit_color_jpeg(data):
    from rehab_affect import demo2_frame_preview as preview
    import cv2
    import numpy as np
    width, height = preview._jpeg_dimensions(data)
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.shape != (height, width, 3):
        raise ValueError("invalid_color_image")
    for side in (1600, 1280):
        ratio = min(1.0, side / max(width, height))
        dimensions = max(1, round(width * ratio)), max(1, round(height * ratio))
        resized = cv2.resize(image, dimensions, interpolation=cv2.INTER_AREA) if dimensions != (width, height) else image
        for quality in (88, 80, 72, 64):
            ok, encoded = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, quality])
            if ok and 0 < encoded.size <= MAX_MODEL_IMAGE_BYTES:
                return encoded.tobytes(), dimensions
    raise ValueError("color_image_size_limit")


def _color_frame(context, timestamp):
    if type(timestamp) not in (int, float) or not math.isfinite(timestamp) or not 0 <= timestamp <= 10800:
        raise ValueError("invalid_sample_time")
    cached = context["frames"].get(timestamp)
    if cached is not None:
        return cached[0], dict(cached[1])
    if len(context["frames"]) >= MAX_IMAGES:
        raise ValueError("invalid_sample_count")
    metadata = {"status": "original_evidence_fallback", "reason": context["failure"],
                "requested_time_sec": timestamp, "source_hash_verified": context["verified"],
                "timestamp_basis": "original_evidence_sample", "pixel_identical_to_evidence": True,
                "width": None, "height": None}
    data = None
    if context["failure"] is None:
        from rehab_affect import demo2_frame_preview as preview
        if time.monotonic() + preview.PREVIEW_TIMEOUT_SEC > context["deadline"]:
            metadata["reason"] = "color_sampling_budget_exceeded"
        else:
            try:
                result = preview.extract_preview(context["source"], timestamp)
                if preview._source_signature(context["source"]) != context["signature"]:
                    raise ValueError("source_changed")
                if result["requested_time_sec"] != timestamp:
                    raise ValueError("sample_time_changed")
                data, dimensions = _fit_color_jpeg(result["image_bytes"])
                metadata.update(status="source_color", reason="ok", width=dimensions[0], height=dimensions[1],
                                timestamp_basis="requested_source_seek_not_original_pts", pixel_identical_to_evidence=False)
            except preview.PreviewError as error:
                if error.code in {"source_changed", "unsafe_path"}:
                    raise ValueError("source_changed") from None
                allowed = {"timeout", "busy", "missing_dependency", "invalid_media", "no_frame", "resource_limit",
                           "tool_start_failed", "tool_io_failed", "tool_failed", "io_error"}
                reason = "preview_" + error.code if error.code in allowed else "preview_failed"
                metadata["reason"] = reason
                if error.code in {"missing_dependency", "invalid_media", "tool_start_failed", "busy"}:
                    context["failure"] = reason
            except ImportError:
                metadata["reason"] = context["failure"] = "hq_dependency_unavailable"
            except ValueError as error:
                if str(error) in {"source_changed", "sample_time_changed"}:
                    raise
                metadata["reason"] = "color_image_invalid_or_oversize"
    context["frames"][timestamp] = data, dict(metadata)
    return data, metadata


def _color_face_boxes(data):
    # The existing offline detector accepts only authorized local files.
    with tempfile.TemporaryDirectory(prefix="rehab-observation-color-") as directory:
        path = Path(directory) / "frame.jpg"
        path.write_bytes(data)
        path.chmod(0o600)
        return _face_boxes(path)


def _valid_box(box):
    return (isinstance(box, dict) and set(box) == {"x", "y", "width", "height"}
            and all(type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1 for value in box.values())
            and box["width"] > 0 and box["height"] > 0
            and box["x"] + box["width"] <= 1 and box["y"] + box["height"] <= 1)


def _face_boxes(path):
    try:
        from rehab_affect.demo2_face_detection import detect_faces
        result = detect_faces(path)
    except Exception:
        return []
    if not isinstance(result, dict) or result.get("available") is not True or not isinstance(result.get("faces"), list):
        return []
    boxes = []
    for face in result["faces"][:32]:
        box = face.get("bbox") if isinstance(face, dict) else None
        if _valid_box(box) and box not in boxes:
            boxes.append(dict(box))
            if len(boxes) == MAX_PERSON_PROPOSALS:
                break
    return boxes


def _numbered_copy(data, path, boxes):
    if not boxes:
        return None
    try:
        from rehab_affect.demo2_roi_tracking import _image_header
        import cv2
        import numpy as np
        _, width, height = _image_header(data, str(path))
        if width < 64 or height < 64:
            return None
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.shape[:2] != (height, width):
            return None
        annotated = image.copy()
        colors = ((0, 220, 255), (255, 200, 0), (80, 240, 80))
        for index, box in enumerate(boxes, 1):
            x, y = round(box["x"] * width), round(box["y"] * height)
            right = min(width - 1, round((box["x"] + box["width"]) * width))
            bottom = min(height - 1, round((box["y"] + box["height"]) * height))
            color = colors[(index - 1) % len(colors)]
            cv2.rectangle(annotated, (x, y), (right, bottom), color, 2)
            label_width = cv2.getTextSize(str(index), cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0][0] + 6
            label_x, label_y = min(x, width - label_width), max(18, y - 3)
            cv2.rectangle(annotated, (label_x, label_y - 16), (label_x + label_width, label_y + 3), color, -1)
            cv2.putText(annotated, str(index), (label_x + 3, label_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
        ok, encoded = cv2.imencode(".jpg", annotated, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if ok and 0 < encoded.size <= 512 * 1024:
            return encoded.tobytes()
    except Exception:
        pass
    return None


def select_frames(frames, bindings=()):
    ordered = sorted(frames.values(), key=lambda frame: frame["time_sec"])
    if not ordered:
        raise ValueError("no_evidence_frames")
    by_key = {frame["frame_key"]: frame for frame in ordered}
    selected = {}
    # Confirmed identity frames first; never assume a name persists across frames.
    for binding in bindings:
        key = binding.get("frame_key")
        if binding.get("status") == "confirmed" and key in by_key and len(selected) < 4:
            selected[key] = by_key[key]
    remaining = MAX_IMAGES - len(selected)
    for index in range(remaining):
        frame = ordered[round(index * (len(ordered) - 1) / max(1, remaining - 1))]
        if len(selected) < MAX_IMAGES:
            selected[frame["frame_key"]] = frame
    return sorted(selected.values(), key=lambda frame: frame["time_sec"])


def load_job_frames(records, identities, job):
    preparation_deadline = time.monotonic() + FRAME_PREP_BUDGET_SEC
    selected_students = job.get("selected_student_ids", [])
    if (not isinstance(selected_students, list) or len(selected_students) > 3
            or any(not isinstance(value, str) or not value for value in selected_students)
            or len(set(selected_students)) != len(selected_students)):
        raise ValueError("invalid_selected_students")
    with records._connect() as connection:
        row = connection.execute("SELECT * FROM video_analysis_tasks WHERE task_id = ?", (job["task_id"],)).fetchone()
        if row is None:
            raise ValueError("source_unavailable")
        task = dict(row)
        revision = identities._revision(task)
        if task["sha256"] != job["source_sha256"] or revision != job["frame_revision"]:
            raise ValueError("source_changed")
        bindings = [dict(item) for item in connection.execute(
            """SELECT frame_key,status,time_sec,student_id,bbox_json,role FROM demo2_identity_bindings
            WHERE task_id=? AND frame_revision=? AND source_sha256=? AND status='confirmed'
            ORDER BY created_at""",
            (job["task_id"], revision, job["source_sha256"]),
        )]
    frames = identities._frames(task)
    if job.get("frames"):
        selected = sorted(
            (frames[item["frame_key"]] for item in job["frames"]),
            key=lambda frame: frame["time_sec"],
        )
    else:
        selected = select_frames(frames, [binding for binding in bindings if binding["role"] == "student"])
    if not 1 <= len(selected) <= MAX_IMAGES:
        raise ValueError("invalid_sample_count")
    color_context = _color_context(identities, task, job, preparation_deadline)
    images, manifest = [], []
    for frame in selected:
        verified, path = identities._frame(task, frame["frame_key"], revision)
        if not 0 < path.stat().st_size <= MAX_IMAGE_BYTES:
            raise ValueError("evidence_image_size")
        data = path.read_bytes()
        if len(data) > MAX_IMAGE_BYTES or not data.startswith(b"\xff\xd8\xff"):
            raise ValueError("invalid_evidence_image")
        images.append({"timestamp_sec": verified["time_sec"], "image_bytes": data, "mime_type": "image/jpeg"})
        boxes = []
        confirmed_roi = any(binding["frame_key"] == verified["frame_key"] and binding["time_sec"] == verified["time_sec"]
                            for binding in bindings)
        for binding in bindings:
            if (binding["role"] != "student" or (selected_students and binding["student_id"] not in selected_students) or binding["frame_key"] != verified["frame_key"]
                    or binding["time_sec"] != verified["time_sec"]):
                continue
            box = json.loads(binding["bbox_json"])
            if not _valid_box(box):
                raise ValueError("invalid_person_region")
            if box not in boxes:
                boxes.append(box)
            if len(boxes) == 3:
                break
        box_source = "confirmed_frame_roi" if boxes else "local_face_detection"
        image_hash = hashlib.sha256(data).hexdigest()
        if confirmed_roi:
            color = None
            color_metadata = {"status": "original_evidence_fallback", "reason": "confirmed_roi_exact_frame_required",
                              "requested_time_sec": verified["time_sec"], "source_hash_verified": color_context["verified"],
                              "timestamp_basis": "original_evidence_sample", "pixel_identical_to_evidence": True,
                              "width": None, "height": None}
        else:
            color, color_metadata = _color_frame(color_context, verified["time_sec"])
        derived_hash = hashlib.sha256(color).hexdigest() if color is not None else None
        if not boxes:
            # Keep proposals only for this job; the second evidence read checks the image hash again.
            cache = job.setdefault("_observation_region_cache", {})
            key = (verified["frame_key"], image_hash, derived_hash)
            if key not in cache:
                if time.monotonic() + 6.0 > preparation_deadline:
                    cache[key] = []
                    job.setdefault("_observation_proposal_budget_skips", set()).add(key)
                else:
                    cache[key] = _color_face_boxes(color) if color is not None else _face_boxes(path)
                if hashlib.sha256(path.read_bytes()).hexdigest() != image_hash:
                    raise ValueError("evidence_changed")
            boxes = [dict(box) for box in cache[key]]
            if key in job.get("_observation_proposal_budget_skips", set()):
                box_source = "local_face_detection_budget_exceeded"
        images[-1]["person_boxes"] = boxes
        model_cache = job.setdefault("_observation_model_image_cache", {})
        model_key = (image_hash, derived_hash, tuple(tuple(box[key] for key in ("x", "y", "width", "height")) for box in boxes))
        previous_model = model_cache.get(verified["frame_key"])
        if previous_model is None or previous_model[0] != model_key:
            model_image = _numbered_copy(color if color is not None else data, path, boxes)
            model_cache[verified["frame_key"]] = model_key, model_image
        else:
            model_image = previous_model[1]
        if model_image is None:
            model_image = color
        if model_image is not None:
            images[-1]["model_image_bytes"] = model_image
        manifest.append({
            "frame_key": verified["frame_key"], "timestamp_sec": verified["time_sec"],
            "image_sha256": image_hash,
            "person_boxes": boxes, "person_box_source": box_source,
            "model_image_sha256": hashlib.sha256(model_image if model_image is not None else data).hexdigest(),
            "derived_image_sha256": derived_hash, "source_sha256": job["source_sha256"],
            "high_quality": color_metadata,
            "normalized_to_evidence": {"scale_x": 1, "scale_y": 1, "offset_x": 0, "offset_y": 0, "crop": False},
        })
    assert_current(records, identities, job)
    _color_context(identities, task, job, verify_hash=True)
    return images, manifest


def assert_current(records, identities, job):
    with records._connect() as connection:
        row = connection.execute("SELECT * FROM video_analysis_tasks WHERE task_id = ?", (job["task_id"],)).fetchone()
        if row is None:
            raise ValueError("source_unavailable")
        task = dict(row)
    if (task["sha256"] != job["source_sha256"] or identities._revision(task) != job["frame_revision"]):
        raise ValueError("source_changed")
    identities._require_media(task)
