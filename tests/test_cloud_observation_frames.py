import importlib.util
import importlib
import importlib.machinery
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace

import pytest


spec = importlib.util.spec_from_file_location("observation_frames", Path(__file__).resolve().parents[1] / "scripts/cloud_observation_frames.py")
frames = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frames)


def samples(count):
    return {str(i): {"frame_key": str(i), "time_sec": i} for i in range(count)}


def test_uniform_sampling_covers_endpoints_with_bounded_payload():
    selected = frames.select_frames(samples(3600))
    assert len(selected) == 8
    assert selected[0]["time_sec"] == 0
    assert selected[-1]["time_sec"] == 3599


def test_confirmed_frames_prioritized_but_never_invent_identity():
    selected = frames.select_frames(samples(3600), [
        {"frame_key": "14", "status": "confirmed", "student_name": "Do not transmit"},
        {"frame_key": "15", "status": "revoked"},
    ])
    assert any(frame["frame_key"] == "14" for frame in selected)
    assert not any(frame["frame_key"] == "15" for frame in selected)
    assert all(set(frame) == {"frame_key", "time_sec"} for frame in selected)
    assert len(selected) == 8


def test_short_video_has_no_duplicate_samples():
    assert frames.select_frames(samples(2)) == list(samples(2).values())


@pytest.fixture(scope="module")
def runtime():
    root = Path(__file__).resolve().parents[1]
    saved = {name: module for name, module in sys.modules.items() if name == "rehab_affect" or name.startswith("rehab_affect.")}
    for name in saved:
        del sys.modules[name]
    package = ModuleType("rehab_affect")
    package.__spec__ = importlib.machinery.ModuleSpec("rehab_affect", loader=None, is_package=True)
    package.__path__ = [str(root / "src/rehab_affect")]
    sys.modules["rehab_affect"] = package
    try:
        preview = importlib.import_module("rehab_affect.demo2_frame_preview")
        yield SimpleNamespace(preview=preview, real_extract=preview.extract_preview,
                              cv=pytest.importorskip("cv2"), np=pytest.importorskip("numpy"))
    finally:
        for name in list(sys.modules):
            if name == "rehab_affect" or name.startswith("rehab_affect."):
                del sys.modules[name]
        sys.modules.update(saved)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Only local synthetic media is permitted")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


@pytest.fixture
def env(runtime, tmp_path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"synthetic source for intercepted local preview tests")
    ok, jpeg = runtime.cv.imencode(".jpg", runtime.np.zeros((360, 640), dtype=runtime.np.uint8))
    assert ok
    original = jpeg.tobytes()
    image_paths, indexed = {}, {}
    for index in range(8):
        path = tmp_path / f"frame_{index}.jpg"
        path.write_bytes(original)
        image_paths[str(index)] = path
        indexed[str(index)] = {"frame_key": str(index), "time_sec": index / 4}
    revision = "b" * 64
    job = {"task_id": "synthetic-task", "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
           "frame_revision": revision, "frames": [{"frame_key": key} for key in indexed]}
    db_path = tmp_path / "records.sqlite3"
    with sqlite3.connect(db_path) as db:
        db.executescript("""CREATE TABLE video_analysis_tasks(task_id TEXT,sha256 TEXT,file_path TEXT,
            expires_at REAL,analysis_status TEXT,processing_result_json TEXT);
            CREATE TABLE demo2_identity_bindings(task_id TEXT,frame_revision TEXT,source_sha256 TEXT,
            frame_key TEXT,status TEXT,time_sec REAL,student_id TEXT,bbox_json TEXT,role TEXT,created_at TEXT);""")
        db.execute("INSERT INTO video_analysis_tasks VALUES(?,?,?,?,?,?)", (job["task_id"], job["source_sha256"], str(source),
                   time.time() + 3600, "evidence_ready", json.dumps({"untouched": True, "private_name": "NEVER_SEND_NAME", "iep": "NEVER_SEND_IEP"})))

    @contextmanager
    def connect():
        db = sqlite3.connect(db_path)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def require_media(task):
        if task["expires_at"] <= time.time() or task["analysis_status"] != "evidence_ready":
            raise ValueError("source_unavailable")
        candidate = runtime.preview._local_source(Path(task["file_path"]))
        if candidate != source or not candidate.is_file():
            raise ValueError("source_unavailable")
        return candidate

    def frame(task, key, supplied_revision):
        require_media(task)
        if supplied_revision != revision:
            raise ValueError("source_changed")
        return dict(indexed[key]), image_paths[key]

    records = SimpleNamespace(_connect=connect)
    identities = SimpleNamespace(_require_media=require_media, _revision=lambda task: revision,
                                 _frames=lambda task: {key: dict(value) for key, value in indexed.items()}, _frame=frame)
    calls = []
    color = runtime.np.zeros((1080, 1920, 3), dtype=runtime.np.uint8)
    color[:, :, 2] = 240
    ok, encoded = runtime.cv.imencode(".jpg", color)
    assert ok

    def preview(path, timestamp):
        assert path == source
        calls.append(timestamp)
        return {"image_bytes": encoded.tobytes(), "requested_time_sec": timestamp,
                "content_type": "image/jpeg", "width": 1920, "height": 1080}

    monkeypatch.setattr(runtime.preview, "extract_preview", preview)
    monkeypatch.setattr(frames, "_face_boxes", lambda path: [])
    monkeypatch.setattr(frames, "_color_face_boxes", lambda data: [])
    return SimpleNamespace(runtime=runtime, source=source, records=records, identities=identities, job=job,
                           indexed=indexed, paths=image_paths, original=original, calls=calls, connect=connect)


def _load(env):
    return frames.load_job_frames(env.records, env.identities, env.job)


def _row(env):
    with env.connect() as db:
        return dict(db.execute("SELECT * FROM video_analysis_tasks").fetchone())


def test_eight_color_frames_preserve_source_evidence_revision_times_and_normalized_coordinates(env):
    before = _row(env)
    source_hash = hashlib.sha256(env.source.read_bytes()).hexdigest()
    images, manifest = _load(env)
    assert len(images) == len(manifest) == len(env.calls) == 8
    assert env.calls == [value["time_sec"] for value in env.indexed.values()]
    assert _row(env) == before and hashlib.sha256(env.source.read_bytes()).hexdigest() == source_hash
    for image, item in zip(images, manifest):
        assert image["timestamp_sec"] == item["timestamp_sec"] == item["high_quality"]["requested_time_sec"]
        assert image["image_bytes"] == env.original and all(path.read_bytes() == env.original for path in env.paths.values())
        assert item["image_sha256"] == hashlib.sha256(env.original).hexdigest()
        assert item["derived_image_sha256"] == item["model_image_sha256"] == hashlib.sha256(image["model_image_bytes"]).hexdigest()
        assert 0 < len(image["model_image_bytes"]) <= 512 * 1024
        decoded = env.runtime.cv.imdecode(env.runtime.np.frombuffer(image["model_image_bytes"], env.runtime.np.uint8), env.runtime.cv.IMREAD_COLOR)
        assert decoded.shape == (900, 1600, 3) and decoded[:, :, 2].mean() > 220 and decoded[:, :, 0].mean() < 20
        assert item["normalized_to_evidence"] == {"scale_x": 1, "scale_y": 1, "offset_x": 0, "offset_y": 0, "crop": False}
        assert item["high_quality"]["source_hash_verified"] is True
        assert item["high_quality"]["timestamp_basis"] == "requested_source_seek_not_original_pts"
        assert item["high_quality"]["pixel_identical_to_evidence"] is False
    assert "NEVER_SEND" not in json.dumps(manifest)


def test_second_load_revalidates_source_and_reuses_exact_color_bytes_without_extraction_or_encoding(env, monkeypatch):
    images, manifest = _load(env)
    assert len(env.job["_observation_color_cache"]["frames"]) == 8
    monkeypatch.setattr(env.runtime.preview, "extract_preview", lambda *args: pytest.fail("Repeated extraction"))
    monkeypatch.setattr(frames, "_fit_color_jpeg", lambda *args: pytest.fail("Repeated encoding"))
    monkeypatch.setattr(frames, "_numbered_copy", lambda *args: pytest.fail("Repeated overlay encoding"))
    again, current = _load(env)
    assert images == again and manifest == current and len(env.calls) == 8


def test_changed_source_even_with_same_size_and_mtime_is_not_served_from_color_cache(env):
    _load(env)
    stamp = env.source.stat()
    body = bytearray(env.source.read_bytes())
    body[0] ^= 1
    env.source.write_bytes(body)
    os.utime(env.source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    with pytest.raises(ValueError, match="source_changed|source_hash_mismatch"):
        _load(env)


def test_wrong_source_hash_fails_closed_without_using_gray_or_color_fallback(env):
    env.source.write_bytes(b"a different synthetic source")
    with pytest.raises(ValueError, match="source_hash_mismatch"):
        _load(env)
    assert not env.calls


@pytest.mark.parametrize("code", ["timeout", "missing_dependency", "invalid_media", "busy", "resource_limit"])
def test_preview_failures_explicitly_fall_back_to_original_evidence_and_cache_failure(env, monkeypatch, code):
    calls = []

    def fail(*args):
        calls.append(args)
        raise env.runtime.preview.PreviewError(code, "NEVER_SEND_NAME NEVER_SEND_IEP")

    monkeypatch.setattr(env.runtime.preview, "extract_preview", fail)
    images, manifest = _load(env)
    count = len(calls)
    assert all(image["image_bytes"] == env.original and "model_image_bytes" not in image for image in images)
    assert all(item["derived_image_sha256"] is None and item["high_quality"]["reason"] == "preview_" + code for item in manifest)
    assert all(item["high_quality"]["status"] == "original_evidence_fallback" for item in manifest)
    assert "NEVER_SEND" not in json.dumps(manifest)
    assert _load(env) == (images, manifest) and len(calls) == count


def test_sampling_and_source_hash_budgets_have_explicit_cached_fallbacks(env, monkeypatch):
    monkeypatch.setattr(frames, "COLOR_BUDGET_SEC", 0)
    images, manifest = _load(env)
    assert not env.calls and all(item["high_quality"]["reason"] == "source_hash_timeout" for item in manifest)
    assert all(not item["high_quality"]["source_hash_verified"] for item in manifest)
    assert len(images) == 8


def test_total_color_budget_does_not_start_a_preview_that_cannot_finish_in_budget(env, monkeypatch):
    monkeypatch.setattr(frames, "COLOR_BUDGET_SEC", 1)
    images, manifest = _load(env)
    assert not env.calls and len(images) == 8
    assert all(item["high_quality"]["reason"] == "color_sampling_budget_exceeded" for item in manifest)


@pytest.mark.parametrize("mutation", ["expired", "revision", "deleted"])
def test_second_load_rechecks_live_source_and_revision_before_using_cache(env, mutation):
    _load(env)
    if mutation == "deleted":
        env.source.unlink()
    elif mutation == "expired":
        with env.connect() as db:
            db.execute("UPDATE video_analysis_tasks SET expires_at=0")
    else:
        env.identities._revision = lambda task: "c" * 64
    with pytest.raises(ValueError):
        _load(env)


def test_source_changed_during_extraction_never_becomes_a_fallback(env, monkeypatch):
    extract = env.runtime.preview.extract_preview

    def changed(*args):
        result = extract(*args)
        env.source.write_bytes(b"changed while extracting")
        return result

    monkeypatch.setattr(env.runtime.preview, "extract_preview", changed)
    with pytest.raises(ValueError, match="source_changed"):
        _load(env)


def test_fit_color_jpeg_can_use_1280_when_1600_cannot_fit(runtime, monkeypatch):
    ok, original = runtime.cv.imencode(".jpg", runtime.np.zeros((1080, 1920, 3), dtype=runtime.np.uint8))
    assert ok
    encode = runtime.cv.imencode
    dimensions = []

    def limited(ext, image, options):
        dimensions.append(image.shape[:2])
        if image.shape[1] > 1280:
            return True, runtime.np.zeros(frames.MAX_MODEL_IMAGE_BYTES + 1, dtype=runtime.np.uint8)
        return encode(ext, image, options)

    monkeypatch.setattr(runtime.cv, "imencode", limited)
    image, size = frames._fit_color_jpeg(original.tobytes())
    assert size == (1280, 720) and len(image) <= 512 * 1024
    assert dimensions == [(900, 1600)] * 4 + [(720, 1280)]


def test_same_requested_timestamps_extract_real_synthetic_source_color_without_altering_evidence(env, monkeypatch):
    try:
        ffmpeg = env.runtime.preview.media_analysis._resolve_tool("ffmpeg")
        env.runtime.preview.media_analysis._resolve_tool("ffprobe")
    except env.runtime.preview.media_analysis.MediaAnalysisError:
        pytest.skip("Local FFmpeg/FFprobe unavailable")
    command = [ffmpeg, "-v", "error", "-nostdin", "-y", "-f", "lavfi", "-i",
               "color=c=red:size=2560x1440:rate=8:duration=2", "-vf",
               "drawbox=x=0:y=0:w=iw:h=ih:color=blue:t=fill:enable='gte(t,1)'",
               "-c:v", "mpeg4", "-q:v", "2", "-threads", "1", str(env.source)]
    subprocess.run(command, check=True, capture_output=True, timeout=30,
                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    digest = hashlib.sha256(env.source.read_bytes()).hexdigest()
    env.job["source_sha256"] = digest
    with env.connect() as db:
        db.execute("UPDATE video_analysis_tasks SET sha256=?", (digest,))
    monkeypatch.setattr(env.runtime.preview, "extract_preview", env.runtime.real_extract)
    before = _row(env)
    images, manifest = _load(env)
    assert len(images) == 8 and all(item["high_quality"]["status"] == "source_color" for item in manifest)
    assert [image["timestamp_sec"] for image in images] == [index / 4 for index in range(8)]
    for index, image in enumerate(images):
        pixels = env.runtime.cv.imdecode(env.runtime.np.frombuffer(image["model_image_bytes"], env.runtime.np.uint8), env.runtime.cv.IMREAD_COLOR)
        assert pixels.shape == (900, 1600, 3) and len(image["model_image_bytes"]) <= 512 * 1024
        channel = 2 if index < 4 else 0
        assert pixels[:, :, channel].mean() > 220 and pixels[:, :, 2 - channel].mean() < 25
    assert _row(env) == before and hashlib.sha256(env.source.read_bytes()).hexdigest() == digest
    assert all(path.read_bytes() == env.original for path in env.paths.values())


def test_source_link_is_rejected_before_extraction(env):
    link = env.source.with_name("linked.mp4")
    try:
        link.symlink_to(env.source)
    except OSError:
        pytest.skip("Symlink creation unavailable")
    with env.connect() as db:
        db.execute("UPDATE video_analysis_tasks SET file_path=?", (str(link),))
    with pytest.raises((ValueError, env.runtime.preview.media_analysis.MediaAnalysisError)):
        _load(env)
    assert not env.calls


def test_more_than_eight_requested_frames_are_rejected_before_color_extraction(env):
    env.job["frames"].append({"frame_key": "0"})
    with pytest.raises(ValueError, match="invalid_sample_count"):
        _load(env)
    assert not env.calls


def test_zero_preparation_budget_neither_decodes_nor_detects_people(env, monkeypatch):
    monkeypatch.setattr(frames, "FRAME_PREP_BUDGET_SEC", 0)
    monkeypatch.setattr(frames, "_face_boxes", lambda *args: pytest.fail("Detection exceeded preparation budget"))
    images, manifest = _load(env)
    assert len(images) == 8 and not env.calls
    assert all(item["person_box_source"] == "local_face_detection_budget_exceeded" for item in manifest)


@pytest.mark.parametrize("role", ["student", "teacher"])
def test_confirmed_roi_requires_exact_old_evidence_and_never_independent_seek(env, role):
    box = {"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.3}
    with env.connect() as db:
        db.execute("INSERT INTO demo2_identity_bindings VALUES(?,?,?,?,?,?,?,?,?,?)", (
            env.job["task_id"], env.job["frame_revision"], env.job["source_sha256"], "0", "confirmed", 0,
            "LOCAL_STUDENT_NOT_FOR_PROVIDER", json.dumps(box), role, "2026-01-01"))
    images, manifest = _load(env)
    assert len(images) == 8 and 0 not in env.calls
    assert images[0]["image_bytes"] == env.original
    assert manifest[0]["high_quality"]["reason"] == "confirmed_roi_exact_frame_required"
    assert manifest[0]["high_quality"]["pixel_identical_to_evidence"] is True
    assert manifest[0]["derived_image_sha256"] is None
    assert all(item["high_quality"]["pixel_identical_to_evidence"] is False for item in manifest[1:])


def test_binding_added_after_anonymous_seek_invalidates_high_quality_manifest(env):
    _, before = _load(env)
    assert before[0]["high_quality"]["pixel_identical_to_evidence"] is False
    with env.connect() as db:
        db.execute("INSERT INTO demo2_identity_bindings VALUES(?,?,?,?,?,?,?,?,?,?)", (
            env.job["task_id"], env.job["frame_revision"], env.job["source_sha256"], "0", "confirmed", 0,
            "LOCAL_ONLY", json.dumps({"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.3}), "student", "2026-01-01"))
    _, after = _load(env)
    assert before != after and after[0]["high_quality"]["reason"] == "confirmed_roi_exact_frame_required"
