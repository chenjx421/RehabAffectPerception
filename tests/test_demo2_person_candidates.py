"""Sidecar contract tests: synthetic images/embeddings, never accuracy tests."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import socket
import sys
from types import SimpleNamespace

import numpy as np
import pytest


MODULE = Path(__file__).resolve().parents[1] / ".runtime/cloud_student_release/demo2_person_candidates.py"


@pytest.fixture(scope="module")
def candidates():
    name = "_test_offline_person_candidates"
    spec = importlib.util.spec_from_file_location(name, MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No network allowed in candidate tests")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def face(module, frame, vector, index=0):
    return module.FaceCandidate(
        face_id=f"f{frame}_{index}", frame_key=f"frame_{frame}", time_sec=float(frame),
        path=f"/synthetic/frame_{frame}.png", frame_sha256=str(frame) * 64,
        frame_size=(320, 180), crop_bbox=(10 + index * 40, 10, 30, 30),
        detection_score=0.95, embedding=vector,
    )


def angle(degrees):
    radians = math.radians(degrees)
    return [math.cos(radians), math.sin(radians)]


def test_fixed_anchor_prevents_transitive_chaining(candidates):
    result = candidates.cluster_face_candidates([
        face(candidates, 0, angle(0)), face(candidates, 1, angle(50)), face(candidates, 2, angle(100)),
    ])
    assert [len(c["members"]) for c in result["clusters"]] == [2, 1]
    assert result["clusters"][0]["representative"]["frame_key"] == "frame_0"
    assert result["unknown"] == []


def test_ambiguous_margin_retains_unknown(candidates):
    result = candidates.cluster_face_candidates([
        face(candidates, 0, [1, 0], 0), face(candidates, 0, [0, 1], 1),
        face(candidates, 1, [1, 1]),
    ])
    assert [len(c["members"]) for c in result["clusters"]] == [1, 1]
    assert result["unknown"][0]["reason"] == "ambiguous_anchor_margin"


@pytest.mark.parametrize("first,second,expected", [(0.63, 0.55, True), (0.63, 0.551, False), (0.56, 0.50, False)])
def test_margin_includes_runner_up_below_threshold(candidates, first, second, expected):
    vector = [first, second, math.sqrt(1 - first**2 - second**2)]
    result = candidates.cluster_face_candidates([
        face(candidates, 0, [1, 0, 0], 0), face(candidates, 0, [0, 1, 0], 1),
        face(candidates, 1, vector),
    ])
    assert (len(result["clusters"][0]["members"]) == 2) is expected
    assert bool(result["unknown"]) is not expected


@pytest.mark.parametrize("score,cluster_count", [(0.55, 1), (0.5499, 2)])
def test_threshold_boundary(candidates, score, cluster_count):
    result = candidates.cluster_face_candidates([
        face(candidates, 0, [1, 0]), face(candidates, 1, [score, math.sqrt(1 - score**2)]),
    ])
    assert len(result["clusters"]) == cluster_count


def test_same_frame_conflict_is_unknown_not_second_choice(candidates):
    result = candidates.cluster_face_candidates([
        face(candidates, 0, [1, 0, 0], 0), face(candidates, 0, [0, 1, 0], 1),
        face(candidates, 1, [0.8, 0.6, 0], 0), face(candidates, 1, [0.8, 0.6, 0], 1),
    ])
    assert [len(c["members"]) for c in result["clusters"]] == [1, 1]
    assert [item["reason"] for item in result["unknown"]] == ["same_frame_anchor_conflict"] * 2


def test_no_same_frame_merges_and_order_deterministic(candidates):
    faces = [face(candidates, 0, [1, 0], 0), face(candidates, 0, [1, 0], 1), face(candidates, 1, [1, 0])]
    result = candidates.cluster_face_candidates(faces)
    assert len(result["clusters"]) == 2
    assert result == candidates.cluster_face_candidates(list(reversed(faces)))
    for cluster in result["clusters"]:
        assert len({m["frame_key"] for m in cluster["members"]}) == len(cluster["members"])


@pytest.mark.parametrize("embedding", [None, [], [0, 0], [float("nan"), 0], [float("inf"), 0], [[1, 0], [1, 0]], [1, 0, 0]])
def test_invalid_embeddings_are_unknown(candidates, embedding):
    result = candidates.cluster_face_candidates([face(candidates, 0, [1, 0]), face(candidates, 1, embedding)])
    assert len(result["clusters"]) == 1
    assert result["unknown"][0]["reason"] == "invalid_or_unavailable_embedding"


def test_embeddings_transient_and_inputs_unchanged(candidates):
    vector = np.array([[100.0, 0.0]])
    item = face(candidates, 0, vector)
    result = candidates.cluster_face_candidates([item, face(candidates, 1, [1, 0])])
    assert np.array_equal(vector, [[100, 0]])
    assert "embedding" not in repr(item)
    assert "embedding" not in json.dumps(result, allow_nan=False)
    assert all(c["role"] == "unassigned" for c in result["clusters"])
    reference = result["clusters"][0]["representative"]
    assert reference["path"] == item.path
    assert reference["crop_bbox"] == [10, 10, 30, 30]
    assert reference["frame_sha256"] == item.frame_sha256


@pytest.mark.parametrize("frames,per_frame", [(9, 1), (1, 13)])
def test_pure_matching_limits(candidates, frames, per_frame):
    with pytest.raises(ValueError, match="limit"):
        candidates.cluster_face_candidates([face(candidates, f, [1, 0], i) for f in range(frames) for i in range(per_frame)])


def test_duplicate_face_ids_rejected(candidates):
    with pytest.raises(ValueError, match="duplicate_face_id"):
        candidates.cluster_face_candidates([face(candidates, 0, [1, 0])] * 2)


def row(x=10, y=10, width=30, height=30, score=0.95):
    return [x, y, width, height, x + 8, y + 8, x + 22, y + 8, x + 15, y + 15,
            x + 8, y + 22, x + 22, y + 22, score]


@pytest.fixture
def setup(tmp_path, monkeypatch):
    cv2 = pytest.importorskip("cv2")
    image = pytest.importorskip("PIL.Image")
    root = tmp_path / "evidence"
    root.mkdir()
    frames = []
    for index in range(2):
        path = root / f"frame_{index}.png"
        image.new("RGB", (320, 180), (index, 0, 0)).save(path)
        frames.append({"frame_key": f"frame_{index}", "time_sec": index, "path": str(path)})
    arguments = {"evidence_root": root}
    for name in ("yunet", "sface"):
        data = f"synthetic {name} not model weights".encode()
        path = tmp_path / f"{name}.onnx"
        path.write_bytes(data)
        arguments.update({f"{name}_path": path, f"{name}_sha256": hashlib.sha256(data).hexdigest(), f"{name}_bytes": len(data)})
    state = SimpleNamespace(rows=[row()], vectors=None, aligned=[], creates=[], sizes=[], calls=0)

    class Detector:
        def setInputSize(self, size):
            state.sizes.append(size)

        def detect(self, pixels):
            state.calls += 1
            return 1, None if state.rows is None else np.array(state.rows, dtype=np.float32)

    class Recognizer:
        def alignCrop(self, pixels, detection):
            state.aligned.append((pixels.shape, detection.copy()))
            return np.zeros((112, 112, 3), dtype=np.uint8)

        def feature(self, pixels):
            if state.vectors is not None:
                return next(state.vectors)
            return np.array([[1.0] + [0.0] * 127])

    def create_detector(*args):
        state.creates.append(("yunet", args))
        return Detector()

    def create_recognizer(*args):
        state.creates.append(("sface", args))
        return Recognizer()

    monkeypatch.setattr(cv2, "FaceDetectorYN", SimpleNamespace(create=create_detector))
    monkeypatch.setattr(cv2, "FaceRecognizerSF", SimpleNamespace(create=create_recognizer))
    return frames, arguments, state


def test_mocked_pipeline_read_only_original_association(candidates, setup, tmp_path):
    frames, kwargs, state = setup
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    original = copy.deepcopy(frames)
    result = candidates.build_person_candidates(frames, **kwargs)
    assert frames == original
    assert before == {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert len(result["clusters"]) == 1
    assert len(result["clusters"][0]["members"]) == 2
    assert result["requires_manual_selection"] is True
    assert result["unknown"] == []
    ref = result["clusters"][0]["representative"]
    assert Path(ref["path"]) == Path(frames[0]["path"])
    assert ref["frame_sha256"] == hashlib.sha256(Path(ref["path"]).read_bytes()).hexdigest()
    assert ref["crop_bbox"] == [10, 10, 30, 30]
    assert ref["frame_size"] == [320, 180]
    assert state.calls == 2 and len(state.aligned) == 2
    for name, args in state.creates:
        assert args[0] == "onnx"
        assert args[1].tobytes() == kwargs[f"{name}_path"].read_bytes()
    serialized = json.dumps(result, allow_nan=False)
    assert '"embedding"' not in serialized and '"name"' not in serialized
    assert '"emotion"' not in serialized and '"attention"' not in serialized


def test_teacher_geometry_excluded_before_feature_extraction(candidates, setup):
    frames, kwargs, state = setup
    result = candidates.build_person_candidates(frames, known_teacher_regions={"frame_0": [[0, 0, 80, 80]]}, **kwargs)
    assert len(state.aligned) == 1
    assert result["frames"][0]["excluded_by_teacher_region"] == 1
    assert result["clusters"][0]["representative"]["frame_key"] == "frame_1"
    assert result["clusters"][0]["role"] == "unassigned"


def test_cap_face_extraction_at_twelve_and_report_truncation(candidates, setup):
    frames, kwargs, state = setup
    state.rows = [row(x=2 + i * 23, width=22, score=0.99) for i in range(13)]
    result = candidates.build_person_candidates(frames[:1], **kwargs)
    assert len(state.aligned) == 12
    assert result["frames"][0]["truncated"] is True
    assert len(result["clusters"]) == 12


def test_empty_detection_does_not_invent_candidates(candidates, setup):
    frames, kwargs, state = setup
    state.rows = None
    result = candidates.build_person_candidates(frames, **kwargs)
    assert result["clusters"] == [] and result["unknown"] == []
    assert state.aligned == []


def test_failed_recognition_stays_unknown(candidates, setup):
    frames, kwargs, state = setup
    state.vectors = iter([np.zeros((1, 128)), np.array([[1.0, 0.0]])])
    result = candidates.build_person_candidates(frames, **kwargs)
    assert result["clusters"] == [] and len(result["unknown"]) == 2


@pytest.mark.parametrize("model", ["yunet", "sface"])
@pytest.mark.parametrize("change", ["sha256", "bytes", "missing"])
def test_model_integrity_fails_before_inference(candidates, setup, model, change):
    frames, kwargs, state = setup
    if change == "sha256":
        kwargs[f"{model}_sha256"] = "0" * 64
    elif change == "bytes":
        kwargs[f"{model}_bytes"] += 1
    else:
        kwargs[f"{model}_path"] = kwargs[f"{model}_path"].with_name("missing.onnx")
    with pytest.raises((ValueError, FileNotFoundError)):
        candidates.build_person_candidates(frames, **kwargs)
    assert state.calls == 0 and state.creates == []


@pytest.mark.parametrize("path", ["https://example.invalid/child.png", "//server/share/child.png", "\\\\server\\share\\child.png", "../child.png", "frame.png:stream"])
def test_unsafe_evidence_paths_rejected(candidates, setup, path):
    frames, kwargs, state = setup
    frames[0]["path"] = path
    with pytest.raises(ValueError):
        candidates.build_person_candidates(frames, **kwargs)
    assert state.calls == 0


def test_outside_root_and_duplicate_files_rejected(candidates, setup):
    frames, kwargs, state = setup
    frames[1]["path"] = frames[0]["path"]
    with pytest.raises(ValueError, match="duplicate_evidence"):
        candidates.build_person_candidates(frames, **kwargs)
    frames[1]["path"] = str(kwargs["yunet_path"])
    with pytest.raises(ValueError, match="outside_evidence_root"):
        candidates.build_person_candidates(frames, **kwargs)
    assert state.calls == 0


@pytest.mark.parametrize("count", [0, 9])
def test_frame_limit_precedes_file_reads(candidates, setup, count):
    frames, kwargs, state = setup
    with pytest.raises(ValueError, match="one_to_eight"):
        candidates.build_person_candidates([frames[0]] * count, **kwargs)
    assert state.creates == []


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True, "1"])
def test_bad_timestamps_rejected(candidates, setup, value):
    frames, kwargs, _ = setup
    frames[0]["time_sec"] = value
    with pytest.raises(ValueError, match="time"):
        candidates.build_person_candidates(frames, **kwargs)


def test_oversized_image_rejected_before_decode(candidates, setup, monkeypatch):
    frames, kwargs, state = setup
    monkeypatch.setattr(candidates, "MAX_IMAGE_PIXELS", 10)
    with pytest.raises(ValueError, match="pixel_limit"):
        candidates.build_person_candidates(frames, **kwargs)
    assert state.calls == 0


def test_image_byte_limit(candidates, setup, monkeypatch):
    frames, kwargs, state = setup
    monkeypatch.setattr(candidates, "MAX_IMAGE_BYTES", 5)
    with pytest.raises(ValueError, match="byte_limit"):
        candidates.build_person_candidates(frames, **kwargs)
    assert state.calls == 0


def test_scaled_landmarks_and_box_return_to_original_pixels(candidates):
    result = candidates._detect_rows([row()], 1280, 720, 2, 2)
    assert result[0][1] == (20, 20, 60, 60)
    assert result[0][0][4:14] == pytest.approx(np.array(row()[4:14]) * 2)


def test_duplicate_and_invalid_detector_rows(candidates):
    bad = row()
    bad[4] = float("nan")
    assert len(candidates._detect_rows([row(), row(), bad], 320, 180, 1, 1)) == 1
    assert candidates._detect_rows([row(x=500)], 320, 180, 1, 1) == []


def test_missing_cv2_capability_fails_closed(candidates, setup, monkeypatch):
    import cv2
    frames, kwargs, state = setup
    monkeypatch.setattr(cv2, "FaceRecognizerSF", None)
    with pytest.raises(RuntimeError, match="capabilities_required"):
        candidates.build_person_candidates(frames, **kwargs)
    assert state.creates == []


def test_cli_uses_explicit_pins_and_stdout_only(candidates, setup, tmp_path, capsys):
    frames, kwargs, _ = setup
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"frames": frames}), encoding="utf-8")
    argv = ["--manifest", str(manifest)]
    for key, value in kwargs.items():
        argv += ["--" + key.replace("_", "-"), str(value)]
    assert candidates.main(argv) == 0
    assert len(json.loads(capsys.readouterr().out)["clusters"]) == 1


def test_full_eight_frame_budget(candidates, setup):
    from PIL import Image

    frames, kwargs, state = setup
    for index in range(2, 8):
        path = kwargs["evidence_root"] / f"frame_{index}.png"
        Image.new("RGB", (320, 180), (index, 0, 0)).save(path)
        frames.append({"frame_key": f"frame_{index}", "time_sec": index, "path": str(path)})
    result = candidates.build_person_candidates(frames, **kwargs)
    assert state.calls == 8 and len(state.aligned) == 8
    assert len(result["clusters"][0]["members"]) == 8
    assert len({m["frame_key"] for m in result["clusters"][0]["members"]}) == 8


def test_pipeline_resizes_detection_but_aligns_original(candidates, setup):
    from PIL import Image

    frames, kwargs, state = setup
    Image.new("RGB", (1280, 720)).save(frames[0]["path"])
    result = candidates.build_person_candidates(frames[:1], **kwargs)
    assert state.sizes == [(640, 360)]
    assert state.aligned[0][0] == (720, 1280, 3)
    assert state.aligned[0][1][:4] == pytest.approx([20, 20, 60, 60])
    assert result["clusters"][0]["representative"]["crop_bbox"] == [20, 20, 60, 60]


def test_jpeg_exif_orientation_is_explicitly_ignored(candidates, setup):
    from PIL import Image

    frames, kwargs, state = setup
    path = kwargs["evidence_root"] / "rotated.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (320, 180)).save(path, exif=exif)
    frames[0]["path"] = str(path)
    result = candidates.build_person_candidates(frames[:1], **kwargs)
    assert state.aligned[0][0] == (180, 320, 3)
    assert result["clusters"][0]["representative"]["frame_size"] == [320, 180]
    assert result["coordinate_space"] == "original_encoded_pixels_xywh_no_exif_rotation"


def test_animation_rejected(candidates, setup):
    from PIL import Image

    frames, kwargs, state = setup
    Image.new("RGB", (320, 180)).save(
        frames[0]["path"], save_all=True, append_images=[Image.new("RGB", (320, 180), "white")], duration=100,
    )
    with pytest.raises(ValueError, match="single_png_or_jpeg"):
        candidates.build_person_candidates(frames[:1], **kwargs)
    assert state.calls == 0


@pytest.mark.parametrize("regions", [
    {"missing": [[0, 0, 20, 20]]}, {"frame_0": [[0, 0, 0, 20]]},
    {"frame_0": [[-1, 0, 20, 20]]}, {"frame_0": [[0, 0, 321, 20]]},
    {"frame_0": [[0, 0, float("nan"), 20]]}, {"frame_0": [[0, 0, 1, 1]] * 13},
])
def test_invalid_teacher_regions_fail_closed(candidates, setup, regions):
    frames, kwargs, state = setup
    with pytest.raises(ValueError, match="teacher_region"):
        candidates.build_person_candidates(frames, known_teacher_regions=regions, **kwargs)
    assert state.aligned == []


def test_links_in_evidence_ancestors_are_rejected(candidates, setup, tmp_path):
    frames, kwargs, state = setup
    alias = kwargs["evidence_root"] / "alias"
    try:
        alias.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("OS does not permit test symlinks")
    frames[0]["path"] = str(alias / "evidence" / "frame_0.png")
    with pytest.raises(ValueError, match="links_not_allowed"):
        candidates.build_person_candidates(frames[:1], **kwargs)
    assert state.creates == []


def test_reparse_point_ancestor_is_rejected_without_os_symlink_permission(candidates, setup, monkeypatch):
    frames, kwargs, state = setup
    original = Path.lstat
    monkeypatch.setattr(candidates.stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024, raising=False)

    def reparse_info(path, *args, **options):
        info = original(path, *args, **options)
        if path == kwargs["evidence_root"]:
            return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=1024)
        return info

    monkeypatch.setattr(Path, "lstat", reparse_info)
    with pytest.raises(ValueError, match="links_not_allowed"):
        candidates.build_person_candidates(frames, **kwargs)
    assert state.creates == []


def test_actual_yunet_api_exception_does_not_fallback(candidates, setup, monkeypatch):
    import cv2

    frames, kwargs, state = setup

    def fail(*args):
        raise cv2.error("synthetic incompatible model")

    monkeypatch.setattr(cv2.FaceRecognizerSF, "create", fail)
    with pytest.raises(RuntimeError, match="no_download_or_fallback"):
        candidates.build_person_candidates(frames, **kwargs)
    assert state.calls == 0


def test_sface_alignment_error_preserves_face_as_unknown(candidates, setup, monkeypatch):
    import cv2

    frames, kwargs, _ = setup

    def fail(*args):
        raise cv2.error("synthetic unalignable landmarks")

    monkeypatch.setattr(cv2.FaceRecognizerSF, "create", lambda *args: SimpleNamespace(alignCrop=fail))
    result = candidates.build_person_candidates(frames[:1], **kwargs)
    assert result["clusters"] == []
    assert result["unknown"][0]["crop_bbox"] == [10, 10, 30, 30]


def test_extreme_detector_coordinates_are_discarded(candidates):
    invalid = row()
    invalid[2] = 1e308
    assert candidates._detect_rows([invalid], 1280, 720, 2, 2) == []


def test_exactly_three_distinct_synthetic_candidates_can_be_selected(candidates, setup):
    frames, kwargs, state = setup
    state.rows = [row(x=10 + i * 80) for i in range(3)]
    vectors = np.eye(128)[:3]
    state.vectors = iter([v.reshape(1, 128) for v in [*vectors, *vectors]])
    result = candidates.build_person_candidates(frames, **kwargs)
    assert [len(c["members"]) for c in result["clusters"]] == [2, 2, 2]
    assert len({c["cluster_id"] for c in result["clusters"]}) == 3
    assert all(c["role"] == "unassigned" for c in result["clusters"])
