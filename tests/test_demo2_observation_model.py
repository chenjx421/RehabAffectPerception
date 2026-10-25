"""Synthetic images and intercepted HTTPS only; explicitly import the override."""
from __future__ import annotations

import base64
import copy
import importlib.util
import json
from pathlib import Path
import socket
import ssl
import sys
import traceback

import pytest


MODULE = Path(__file__).resolve().parents[1] / ".runtime/cloud_release_overrides/demo2_observation_model.py"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aDOkAAAAASUVORK5CYII=")
SOURCE = {"task_id": "synthetic_task", "source_sha256": "a" * 64, "frame_revision": "b" * 64,
          "media_duration_sec": 3600}
KEY = "synthetic-test-credential-not-real"
BOX = {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.4}


@pytest.fixture(scope="module")
def model():
    name = "_synthetic_cloud_observation_model"
    spec = importlib.util.spec_from_file_location(name, MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
        assert Path(module.__file__).resolve() == MODULE
        yield module
    finally:
        sys.modules.pop(name, None)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Tests must never open a network connection")
    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture()
def config(model):
    return model.ObservationModelConfig(endpoint="https://synthetic.invalid/v1/chat/completions",
                                        model="synthetic-vision", api_key=KEY, enabled=True)


def samples(model):
    return [model.SampleFrame(t, PNG, "image/png", person_boxes=[dict(BOX)]) for t in (0, 2.5)]


def document():
    return {"frames": [{"timestamp_sec": 0, "observations": [
        {"behavior": "hand_raised", "person_index": 1}]},
        {"timestamp_sec": 2.5, "observations": []}]}


def canonical_document():
    return {"frames": [{"timestamp_sec": 0, "observations": [{"behavior": "hand_raised", "bbox": dict(BOX)}]},
                       {"timestamp_sec": 2.5, "observations": []}]}


def response(value=None, **changes):
    data = {"choices": [{"finish_reason": "stop", "message": {
        "role": "assistant", "content": json.dumps(document() if value is None else value)}}]}
    data["choices"][0].update(changes)
    return json.dumps(data).encode()


def invoke(model, config, monkeypatch, raw=None, frames=None, **source):
    calls = []

    def post(configured, body):
        assert configured is config
        calls.append(json.loads(body))
        return response() if raw is None else raw
    monkeypatch.setattr(model, "_https_post", post)
    result = model.ObservationModelClient(config).analyze(samples(model) if frames is None else frames,
                                                         **{**SOURCE, **source})
    return result, calls


def test_real_override_multiframe_schema_and_no_private_metadata_sent(model, config, monkeypatch, caplog):
    result, calls = invoke(model, config, monkeypatch)
    payload = calls[0]
    assert payload["max_tokens"] == 5000 and config.timeout_seconds == 90
    assert config.reasoning_effort == "" and "reasoning_effort" not in payload
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    schema = payload["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["frames"]["items"]["properties"]["timestamp_sec"]["enum"] == [0, 2.5]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["frames"]["items"]["properties"]["observations"]["maxItems"] == 9
    item = schema["properties"]["frames"]["items"]["properties"]["observations"]["items"]
    assert item["required"] == ["behavior", "person_index"] and "bbox" not in item["properties"]
    assert payload["response_format"]["json_schema"]["name"] == "visible_observation_indexed_v1"
    prompt = payload["messages"][0]["content"]
    assert "at most NINE" in prompt and "entire image" in prompt
    assert "head/face" in prompt and "GROUP-ONLY" in prompt and "Never borrow" in prompt
    images = [item for item in payload["messages"][1]["content"] if item["type"] == "image_url"]
    assert len(images) == 2
    for item in images:
        assert item["image_url"]["detail"] == "high"
        assert base64.b64decode(item["image_url"]["url"].split(",", 1)[1]) == PNG
    encoded = json.dumps(payload)
    assert KEY not in encoded and SOURCE["task_id"] not in encoded and SOURCE["source_sha256"] not in encoded
    assert result["coverage"] == {"scope": "sampled_frames_only", "sample_timestamps_sec": [0, 2.5],
                                  "sample_count": 2, "media_duration_sec": 3600,
                                  "continuous_coverage": False, "full_lesson": False}
    assert result["frames"][1]["observations"] == []
    assert result["teacher_suggestions"] == [{"timestamp_sec": 0, "code": "review_visible_turn_opportunity",
                                                "evidence_behaviors": ["hand_raised"]}]
    assert result["requires_teacher_review"] is True
    assert not result["identity_recognition_performed"] and not result["scoring_performed"]
    assert not caplog.records and KEY not in repr(config) and "synthetic.invalid" not in repr(config)
    assert "image_bytes" not in repr(samples(model)[0])


def test_request_defines_visible_action_thresholds_without_invented_scores(model, config, monkeypatch):
    _, calls = invoke(model, config, monkeypatch)
    prompt = calls[0]['messages'][0]['content']
    for evidence_rule in ('hand above their shoulder', 'writing implement contacting',
                          'head is too small or hidden', 'omit walking and out_of_seat',
                          'mirrors, screens, posters', 'not an adjacent person'):
        assert evidence_rule in prompt
    assert 'scores, or classroom quality' in prompt


@pytest.mark.parametrize('behavior', ['walking', 'out_of_seat'])
def test_single_frame_model_cannot_claim_temporal_actions_but_old_records_remain_readable(model, config, monkeypatch, behavior):
    data = document()
    data['frames'][0]['observations'][0]['behavior'] = behavior
    with pytest.raises(model.ObservationModelError, match='restricted schema'):
        invoke(model, config, monkeypatch, raw=response(data))
    old = canonical_document()
    old['frames'][0]['observations'][0]['behavior'] = behavior
    assert model._validate_frames(old, [0, 2.5]) == old['frames']


def test_default_disabled_and_explicit_server_configuration(model):
    config = model.ObservationModelConfig.from_env({})
    assert not config.enabled
    with pytest.raises(model.ObservationModelError) as error:
        model.ObservationModelClient(config).analyze(samples(model), **SOURCE)
    assert error.value.code == "disabled"
    env = {"REHAB_OBSERVATION_API_BASE": "https://synthetic.invalid/v1/",
           "REHAB_OBSERVATION_MODEL": "synthetic", "REHAB_OBSERVATION_API_KEY": KEY}
    configured = model.ObservationModelConfig.from_env(env)
    assert configured.enabled and configured.endpoint == "https://synthetic.invalid/v1/chat/completions"
    assert model.ObservationModelConfig.from_env({**env, "REHAB_OBSERVATION_API_BASE": configured.endpoint}).endpoint == configured.endpoint
    for field in ("API_BASE", "MODEL", "API_KEY"):
        with pytest.raises(model.ObservationModelError):
            model.ObservationModelConfig.from_env({**env, "REHAB_OBSERVATION_" + field: ""})


@pytest.mark.parametrize("effort", ["", "low", "high", "max"])
def test_explicit_reasoning_effort_only_adds_the_requested_payload_field(model, config, monkeypatch, effort):
    legacy_result, legacy_calls = invoke(model, config, monkeypatch)
    configured = model.ObservationModelConfig(
        endpoint=config.endpoint, model=config.model, api_key=config.api_key,
        enabled=True, reasoning_effort=effort)
    env = {"REHAB_OBSERVATION_API_BASE": config.endpoint,
           "REHAB_OBSERVATION_MODEL": config.model, "REHAB_OBSERVATION_API_KEY": config.api_key,
           "REHAB_OBSERVATION_REASONING_EFFORT": effort}
    assert model.ObservationModelConfig.from_env(env) == configured
    result, calls = invoke(model, configured, monkeypatch)
    expected = copy.deepcopy(legacy_calls[0])
    if effort:
        expected["reasoning_effort"] = effort
    assert calls == [expected] and result == legacy_result


@pytest.mark.parametrize("effort", [None, True, False, 0, [], {}, "medium", "LOW", " low", "low ", "low\r\n"])
def test_invalid_reasoning_effort_fails_for_constructor_and_environment(model, config, effort):
    settings = {"endpoint": config.endpoint, "model": config.model, "api_key": config.api_key, "enabled": True}
    env = {"REHAB_OBSERVATION_API_BASE": config.endpoint,
           "REHAB_OBSERVATION_MODEL": config.model, "REHAB_OBSERVATION_API_KEY": config.api_key}
    with pytest.raises(model.ObservationModelError) as error:
        model.ObservationModelConfig(**settings, reasoning_effort=effort)
    assert error.value.code == "invalid_config"
    for values in (env, {}):
        with pytest.raises(model.ObservationModelError) as error:
            model.ObservationModelConfig.from_env({**values, "REHAB_OBSERVATION_REASONING_EFFORT": effort})
        assert error.value.code == "invalid_config"


@pytest.mark.parametrize("effort", ["", "low", "high", "max"])
def test_reasoning_effort_alone_never_enables_the_provider(model, effort):
    config = model.ObservationModelConfig.from_env({"REHAB_OBSERVATION_REASONING_EFFORT": effort})
    assert config.reasoning_effort == effort and config.enabled is False
    with pytest.raises(model.ObservationModelError) as error:
        model.ObservationModelClient(config).analyze(samples(model), **SOURCE)
    assert error.value.code == "disabled"


def test_reasoning_effort_reads_process_environment_and_empty_value_omits_payload(model, monkeypatch):
    monkeypatch.setenv("REHAB_OBSERVATION_API_BASE", "https://synthetic.invalid/v1")
    monkeypatch.setenv("REHAB_OBSERVATION_MODEL", "glm-5.3-flash")
    monkeypatch.setenv("REHAB_OBSERVATION_API_KEY", KEY)
    monkeypatch.setenv("REHAB_OBSERVATION_REASONING_EFFORT", "low")
    config = model.ObservationModelConfig.from_env()
    _, calls = invoke(model, config, monkeypatch)
    assert calls[0]["reasoning_effort"] == "low"
    monkeypatch.setenv("REHAB_OBSERVATION_REASONING_EFFORT", "")
    _, calls = invoke(model, model.ObservationModelConfig.from_env(), monkeypatch)
    assert "reasoning_effort" not in calls[0]


def test_worker_entry_preserves_sameframe_samples_without_fabricating_provenance(model, config, monkeypatch):
    captured = []

    def post(_config, body):
        captured.append(json.loads(body))
        return response()
    monkeypatch.setattr(model, "_https_post", post)
    frames = [{"timestamp_sec": t, "image_bytes": PNG, "mime_type": "image/png", "person_boxes": [dict(BOX)]} for t in (0, 2.5)]
    result = model.analyze_frames(frames, config)
    assert result["frames"] == canonical_document()["frames"]
    assert not {"task_id", "source_sha256", "frame_revision"} & result.keys()
    assert result["coverage"]["sample_timestamps_sec"] == [0, 2.5]
    assert result["coverage"]["media_duration_sec"] is None
    images = [row for row in captured[0]["messages"][1]["content"] if row["type"] == "image_url"]
    assert all(base64.b64decode(row["image_url"]["url"].split(",", 1)[1]) == PNG for row in images)
    monkeypatch.setattr(model.ObservationModelConfig, "from_env", classmethod(lambda cls: config))
    assert model.analyze_frames(frames)["frames"] == result["frames"]


def test_worker_grayscale_640_jpeg_is_not_reencoded_or_rescaled(model, config, monkeypatch):
    cv = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    gray = np.zeros((360, 640), dtype=np.uint8)
    gray[80:160, 160:320] = 255
    ok, encoded = cv.imencode(".jpg", gray)
    assert ok
    image = encoded.tobytes()
    box = {"x": 0.25, "y": 0.25, "width": 0.25, "height": 0.25}
    data = {"frames": [{"timestamp_sec": 12.5, "observations": [{"behavior": "writing", "person_index": 1}]}]}

    def post(_config, body):
        content = json.loads(body)["messages"][1]["content"]
        url = next(row["image_url"]["url"] for row in content if row["type"] == "image_url")
        assert url.startswith("data:image/jpeg;base64,")
        sent = base64.b64decode(url.split(",", 1)[1])
        assert sent == image
        assert cv.imdecode(np.frombuffer(sent, np.uint8), cv.IMREAD_UNCHANGED).shape == (360, 640)
        return response(data)
    monkeypatch.setattr(model, "_https_post", post)
    result = model.analyze_frames([{"timestamp_sec": 12.5, "image_bytes": image, "mime_type": "image/jpeg", "person_boxes": [box]}], config)
    assert result["frames"] == [{"timestamp_sec": 12.5, "observations": [{"behavior": "writing", "bbox": box}]}]
    assert result["frames"][0]["observations"][0]["bbox"] == box


@pytest.mark.parametrize("mutation", ["empty", "too_many", "private_metadata", "missing_mime", "not_list"])
def test_worker_entry_rejects_noncontract_fields(model, config, mutation):
    frames = [{"timestamp_sec": 0, "image_bytes": PNG, "mime_type": "image/png"}]
    if mutation == "empty": frames = []
    elif mutation == "too_many": frames *= model.MAX_FRAMES + 1
    elif mutation == "private_metadata": frames[0]["student_name"] = "synthetic private name"
    elif mutation == "missing_mime": frames[0].pop("mime_type")
    elif mutation == "not_list": frames = iter(frames)
    with pytest.raises(model.ObservationModelError) as error:
        model.analyze_frames(frames, config)
    assert error.value.code == "invalid_input"


@pytest.mark.parametrize("endpoint", ["http://synthetic.invalid/chat/completions", "file:///chat/completions",
    "https://user:secret@synthetic.invalid/chat/completions", "https://synthetic.invalid/chat/completions?key=secret",
    "https://synthetic.invalid/chat/completions#secret", "https://synthetic.invalid/v1",
    "https://synthetic.invalid:99999/chat/completions", "https://bad host/chat/completions",
    "https://synthetic.invalid\\evil/chat/completions", "https://synthetic.invalid/\nchat/completions"])
def test_unsafe_endpoints_fail_without_network_or_secret_reflection(model, endpoint):
    with pytest.raises(model.ObservationModelError) as error:
        model.ObservationModelConfig(endpoint=endpoint, model="synthetic", api_key=KEY, enabled=True)
    assert error.value.code == "invalid_config"
    assert "secret" not in str(error.value) and endpoint not in str(error.value)


@pytest.mark.parametrize("field,value", [("model", ""), ("model", "x\r\ny"), ("api_key", ""),
    ("api_key", "secret\r\nX-Header: injected"), ("enabled", 1), ("timeout_seconds", 0),
    ("timeout_seconds", float("inf")), ("timeout_seconds", True), ("max_response_bytes", True),
    ("max_response_bytes", 0), ("max_response_bytes", 10**9)])
def test_configuration_limits(model, field, value):
    data = dict(endpoint="https://synthetic.invalid/chat/completions", model="synthetic", api_key=KEY, enabled=True)
    data[field] = value
    with pytest.raises(model.ObservationModelError):
        model.ObservationModelConfig(**data)


@pytest.mark.parametrize("mutation", ["empty", "too_many", "duplicate_time", "unsorted", "boolean_time",
    "negative_time", "nan_time", "infinite_time", "huge_time", "outside_duration", "remote_url", "image_too_large", "mime", "magic"])
def test_invalid_samples_rejected_before_transport(model, config, monkeypatch, mutation):
    frames = samples(model)
    if mutation == "empty": frames = []
    elif mutation == "too_many": frames = [model.SampleFrame(t, PNG, "image/png") for t in range(model.MAX_FRAMES + 1)]
    elif mutation == "duplicate_time": frames[1] = frames[0]
    elif mutation == "unsorted": frames.reverse()
    else:
        timestamp, data, mime = 0, PNG, "image/png"
        if mutation == "boolean_time": timestamp = True
        elif mutation == "negative_time": timestamp = -1
        elif mutation == "nan_time": timestamp = float("nan")
        elif mutation == "infinite_time": timestamp = float("inf")
        elif mutation == "huge_time": timestamp = 10**1000
        elif mutation == "outside_duration": timestamp = 4000
        elif mutation == "remote_url": data = "https://real-data.invalid/student.jpg"
        elif mutation == "image_too_large": data = PNG + b"x" * model.MAX_IMAGE_BYTES
        elif mutation == "mime": mime = "image/svg+xml"
        elif mutation == "magic": data = b"not an image"
        frames[0] = model.SampleFrame(timestamp, data, mime)
    monkeypatch.setattr(model, "_https_post", lambda *_: pytest.fail("Invalid input reached transport"))
    with pytest.raises(model.ObservationModelError) as error:
        model.ObservationModelClient(config).analyze(frames, **SOURCE)
    assert error.value.code == "invalid_input"


@pytest.mark.parametrize("field,value", [("task_id", "../private"), ("source_sha256", "not-a-hash"),
    ("frame_revision", "stale"), ("media_duration_sec", True), ("media_duration_sec", float("inf"))])
def test_invalid_source_metadata(model, config, field, value):
    with pytest.raises(model.ObservationModelError) as error:
        model.ObservationModelClient(config).analyze(samples(model), **{**SOURCE, field: value})
    assert error.value.code == "invalid_input"


@pytest.mark.parametrize("behavior", ["happy", "stressed", "autism", "attentive", "distracted", "anxious",
    "learning_mastery", "teacher_quality", "recognized_student", "no_response"])
def test_psychological_clinical_identity_and_scoring_claims_are_rejected(model, config, monkeypatch, behavior):
    data = document()
    data["frames"][0]["observations"][0]["behavior"] = behavior
    with pytest.raises(model.ObservationModelError) as error:
        invoke(model, config, monkeypatch, response(data))
    assert error.value.code == "invalid_response"


@pytest.mark.parametrize("mutation", ["name", "score", "emotion", "advice", "full_lesson", "new_time",
    "boolean_time", "missing_frame", "duplicate_frame", "reordered", "invalid_bbox", "zero_bbox",
    "boolean_bbox", "extra_bbox", "too_many_observations", "duplicate_observation", "markdown", "duplicate_json", "nan"])
def test_strict_schema_cannot_smuggle_free_text_identity_or_new_timestamps(model, config, monkeypatch, mutation):
    data = document()
    item = data["frames"][0]["observations"][0]
    if mutation in {"name", "score", "emotion", "advice"}: item[mutation] = "forbidden free text"
    elif mutation == "full_lesson": data["full_lesson"] = True
    elif mutation == "new_time": data["frames"][0]["timestamp_sec"] = 1
    elif mutation == "boolean_time": data["frames"][0]["timestamp_sec"] = False
    elif mutation == "missing_frame": data["frames"].pop()
    elif mutation == "duplicate_frame": data["frames"][1] = copy.deepcopy(data["frames"][0])
    elif mutation == "reordered": data["frames"].reverse()
    elif mutation == "invalid_bbox": item["person_index"] = 4
    elif mutation == "zero_bbox": item["person_index"] = 0
    elif mutation == "boolean_bbox": item["person_index"] = True
    elif mutation == "extra_bbox": item["bbox"] = {**BOX, "student_id": "invented"}
    elif mutation == "too_many_observations": data["frames"][0]["observations"] *= model.MAX_OBSERVATIONS_PER_FRAME + 1
    elif mutation == "duplicate_observation": data["frames"][0]["observations"].append(copy.deepcopy(item))
    raw = response(data)
    if mutation in {"markdown", "duplicate_json", "nan"}:
        envelope = json.loads(raw)
        text = {"markdown": "```json\n{}\n```", "duplicate_json": '{"frames":[],"frames":[]}',
                "nan": '{"frames":[{"timestamp_sec":NaN,"observations":[]}]}'}[mutation]
        envelope["choices"][0]["message"]["content"] = text
        raw = json.dumps(envelope).encode()
    with pytest.raises(model.ObservationModelError) as error:
        invoke(model, config, monkeypatch, raw)
    assert error.value.code == "invalid_response"


def test_unknown_is_empty_not_no_behavior_and_advice_is_locally_derived(model, config, monkeypatch):
    data = document()
    data["frames"][0]["observations"] = []
    result, _ = invoke(model, config, monkeypatch, response(data))
    assert result["teacher_suggestions"] == []
    assert all(row["observations"] == [] for row in result["frames"])
    data["frames"][0]["observations"] = [{"behavior": b, "person_index": None} for b in ("writing", "manipulating_materials", "standing")]
    result, _ = invoke(model, config, monkeypatch, response(data), media_duration_sec=None)
    assert result["coverage"]["media_duration_sec"] is None
    assert len(result["teacher_suggestions"]) == 2
    assert result["teacher_suggestions"][0]["evidence_behaviors"] == ["manipulating_materials", "writing"]
    assert result["frames"][0]["observations"][0]["bbox"] is None


def test_three_anonymous_regions_support_nine_actions_without_identity_or_continuity(model, config, monkeypatch):
    boxes = [{"x": x, "y": 0.1, "width": 0.1, "height": 0.2} for x in (0.1, 0.4, 0.7)]
    different = {"x": 0.2, "y": 0.6, "width": 0.1, "height": 0.2}
    data = {"frames": [{"timestamp_sec": 0, "observations": [
        {"behavior": behavior, "person_index": index} for index, box in enumerate(boxes, 1)
        for behavior in ("writing", "hand_raised", "seated")]},
        {"timestamp_sec": 2.5, "observations": [{"behavior": "standing", "person_index": 1}]}]}
    frames = [model.SampleFrame(0, PNG, "image/png", person_boxes=boxes),
              model.SampleFrame(2.5, PNG, "image/png", person_boxes=[different])]
    result, calls = invoke(model, config, monkeypatch, response(data), frames=frames)
    assert len(result["frames"][0]["observations"]) == 9
    assert [o["bbox"] for o in result["frames"][0]["observations"]] == [box for box in boxes for _ in range(3)]
    assert result["frames"][1]["observations"][0]["bbox"] == different
    assert result["identity_recognition_performed"] is False and result["scoring_performed"] is False
    assert result["coverage"]["continuous_coverage"] is False
    assert "no continuity" in calls[0]["messages"][0]["content"]
    assert all(set(observation) == {"behavior", "bbox"} for frame in result["frames"] for observation in frame["observations"])


@pytest.mark.parametrize("mutation", ["four_people", "four_behaviors", "four_group_actions", "ten_actions", "invented_box", "other_frame_box"])
def test_person_action_and_local_region_bounds_are_enforced_not_prompt_only(model, config, monkeypatch, mutation):
    data = document()
    if mutation == "four_people":
        data["frames"][0]["observations"] = [{"behavior": "seated", "person_index": index} for index in (1, 2, 3, 4)]
    elif mutation == "four_behaviors":
        data["frames"][0]["observations"] = [{"behavior": behavior, "person_index": 1}
                                               for behavior in ("writing", "hand_raised", "seated", "standing")]
    elif mutation == "four_group_actions":
        data["frames"][0]["observations"] = [{"behavior": behavior, "person_index": None}
                                               for behavior in ("writing", "hand_raised", "seated", "standing")]
    elif mutation == "ten_actions":
        data["frames"][0]["observations"] *= 10
    elif mutation == "invented_box":
        data["frames"][0]["observations"][0]["bbox"] = {**BOX, "x": 0.11}
    else:
        data["frames"][1]["observations"] = [{"behavior": "writing", "person_index": 2}]
    frames = samples(model)
    if mutation == "other_frame_box":
        frames[1] = model.SampleFrame(2.5, PNG, "image/png", person_boxes=[{**BOX, "x": 0.2}])
    with pytest.raises(model.ObservationModelError) as error:
        invoke(model, config, monkeypatch, response(data), frames=frames)
    assert error.value.code == "invalid_response"


def test_no_local_proposal_cannot_create_individual_evidence_but_retains_group_only(model, config, monkeypatch):
    frames = [model.SampleFrame(0, PNG, "image/png")]
    data = {"frames": [{"timestamp_sec": 0, "observations": [{"behavior": "writing", "person_index": 1}]}]}
    with pytest.raises(model.ObservationModelError) as error:
        invoke(model, config, monkeypatch, response(data), frames=frames)
    assert error.value.code == "invalid_response"
    assert error.value.diagnostic_code == "person_index_not_proposed"
    data["frames"][0]["observations"][0]["person_index"] = None
    result, _ = invoke(model, config, monkeypatch, response(data), frames=frames)
    assert result["frames"] == [{"timestamp_sec": 0, "observations": [{"behavior": "writing", "bbox": None}]}]
    assert result["requires_teacher_review"] is True and result["identity_recognition_performed"] is False


def test_integer_index_maps_full_precision_proposal_without_model_reproducing_floats(model, config, monkeypatch):
    box = {"x": 0.12345678901234567, "y": 0.20781234567890123, "width": 0.03123456789012345, "height": 0.04234567890123456}
    frames = [model.SampleFrame(0, PNG, "image/png", person_boxes=[box])]
    raw = response({"frames": [{"timestamp_sec": 0, "observations": [{"behavior": "writing", "person_index": 1}]}]})
    result, _ = invoke(model, config, monkeypatch, raw, frames=frames)
    assert result["frames"][0]["observations"] == [{"behavior": "writing", "bbox": box}]
    assert result["frames"][0]["observations"][0]["bbox"] is not box


@pytest.mark.parametrize("index", [True, 1.0, "1", 0, -1, 4])
def test_wire_person_index_must_be_a_supplied_integer_not_coerced(model, config, monkeypatch, index):
    raw = response({"frames": [{"timestamp_sec": 0, "observations": [{"behavior": "writing", "person_index": index}]}]})
    with pytest.raises(model.ObservationModelError) as error:
        invoke(model, config, monkeypatch, raw, frames=[samples(model)[0]])
    assert error.value.code == "invalid_response" and error.value.diagnostic_code == "person_index_not_proposed"


def test_twelve_candidates_allow_later_indices_but_no_more_than_three_output_people(model, config, monkeypatch):
    boxes = [{"x": 0.02 + (n % 6) * 0.16, "y": 0.1 + (n // 6) * 0.4, "width": 0.08, "height": 0.1} for n in range(12)]
    frames = [model.SampleFrame(0, PNG, "image/png", person_boxes=boxes)]
    data = {"frames": [{"timestamp_sec": 0, "observations": [{"behavior": behavior, "person_index": index}
        for index in (4, 8, 12) for behavior in ("writing", "hand_raised", "seated")]}]}
    result, calls = invoke(model, config, monkeypatch, response(data), frames=frames)
    assert [item["bbox"] for item in result["frames"][0]["observations"]] == [boxes[index - 1] for index in (4, 8, 12) for _ in range(3)]
    wire_item = calls[0]["response_format"]["json_schema"]["schema"]["properties"]["frames"]["items"]["properties"]["observations"]["items"]
    assert wire_item["properties"]["person_index"]["anyOf"][0]["enum"] == list(range(1, 13))
    data["frames"][0]["observations"] = [{"behavior": "seated", "person_index": index} for index in (1, 2, 3, 4)]
    with pytest.raises(model.ObservationModelError) as error:
        invoke(model, config, monkeypatch, response(data), frames=frames)
    assert error.value.diagnostic_code == "response_schema"


@pytest.mark.parametrize("failure,expected", [("json", "response_json"), ("envelope", "response_envelope"),
    ("schema", "response_schema"), ("bbox", "person_index_not_proposed"), ("truncated", "completion_truncated")])
def test_model_diagnostics_distinguish_response_stages_without_raw_text(model, config, monkeypatch, failure, expected):
    raw = response()
    if failure == "json": raw = (KEY + " not JSON").encode()
    elif failure == "envelope": raw = json.dumps({"choices": [], "private": KEY}).encode()
    elif failure == "schema": raw = response({"frames": []})
    elif failure == "bbox":
        data = document()
        data["frames"][0]["observations"][0]["person_index"] = 2
        raw = response(data)
    elif failure == "truncated": raw = response(finish_reason="length")
    with pytest.raises(model.ObservationModelError) as error:
        invoke(model, config, monkeypatch, raw)
    assert error.value.diagnostic_code == expected
    assert error.value.code == ("model_refused" if failure == "truncated" else "invalid_response")
    assert KEY not in str(error.value) and KEY not in repr(error.value)
    sanitized = model.ObservationModelError("invalid_response", diagnostic_code=KEY)
    assert sanitized.diagnostic_code == "invalid_response"


@pytest.mark.parametrize("boxes", [[BOX] * 4, [{**BOX, "student_id": "PRIVATE"}], [{**BOX, "width": 0}], [BOX, BOX]])
def test_roi_hints_reject_names_identifiers_invalid_or_excess_regions_before_send(model, config, monkeypatch, boxes):
    monkeypatch.setattr(model, "_https_post", lambda *_: pytest.fail("Invalid ROI reached provider"))
    with pytest.raises(model.ObservationModelError) as error:
        model.analyze_frames([{"timestamp_sec": 0, "image_bytes": PNG, "mime_type": "image/png", "person_boxes": boxes}], config)
    assert error.value.code == "invalid_input"


@pytest.mark.parametrize("mutation", ["truncated", "refused", "tool_call", "multiple_choices", "invalid_json", "oversize"])
def test_incomplete_and_invalid_provider_envelopes_fail_closed(model, config, monkeypatch, mutation):
    data = json.loads(response())
    if mutation == "truncated": data["choices"][0]["finish_reason"] = "length"
    elif mutation == "refused": data["choices"][0]["message"]["refusal"] = KEY
    elif mutation == "tool_call": data["choices"][0]["message"]["tool_calls"] = [{"name": "send_data"}]
    elif mutation == "multiple_choices": data["choices"] *= 2
    raw = json.dumps(data).encode()
    if mutation == "invalid_json": raw = b"not JSON"
    elif mutation == "oversize": raw = b"x" * (config.max_response_bytes + 1)
    with pytest.raises(model.ObservationModelError) as error:
        invoke(model, config, monkeypatch, raw)
    assert error.value.code in {"model_refused", "invalid_response", "response_too_large"}
    assert KEY not in str(error.value)


class FakeSocket:
    def __init__(self): self.timeouts = []
    def settimeout(self, value): self.timeouts.append(value)


class FakeResponse:
    status = 200

    def __init__(self, body):
        self.body, self.reads = body, 0
        self.headers = {"Content-Type": "application/json"}

    def getheader(self, name, default=None): return self.headers.get(name, default)

    def read1(self, limit):
        self.reads += 1
        block, self.body = self.body[:limit], self.body[limit:]
        return block


def fake_connection(model, monkeypatch, response, failure=None):
    captured = {}

    class Connection:
        def __init__(self, host, port, **kwargs):
            captured.update(host=host, port=port, **kwargs)
            self.sock, self.closed = FakeSocket(), False
            captured["connection"] = self

        def connect(self):
            if failure: raise failure

        def request(self, method, path, **kwargs): captured.update(method=method, path=path, **kwargs)
        def getresponse(self): return response
        def close(self): self.closed = True
    monkeypatch.setattr(model.http.client, "HTTPSConnection", Connection)
    return captured


def test_https_verifies_tls_and_uses_only_explicit_host_credential(model, config, monkeypatch, caplog):
    raw = response()
    captured = fake_connection(model, monkeypatch, FakeResponse(raw))
    assert model._https_post(config, b"synthetic-body") == raw
    assert captured["context"].check_hostname is True
    assert captured["context"].verify_mode == ssl.CERT_REQUIRED
    assert (captured["host"], captured["port"], captured["path"]) == ("synthetic.invalid", 443, "/v1/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer " + KEY
    assert all(0 < value <= config.timeout_seconds for value in captured["connection"].sock.timeouts)
    assert captured["connection"].closed and not caplog.records


@pytest.mark.parametrize("status", [301, 302, 307, 308, 401, 429, 500])
def test_no_redirects_retries_or_error_body_read(model, config, monkeypatch, status):
    reply = FakeResponse(KEY.encode())
    reply.status = status
    captured = fake_connection(model, monkeypatch, reply)
    with pytest.raises(model.ObservationModelError) as error:
        model._https_post(config, b"synthetic")
    assert error.value.code == ("redirect_blocked" if 300 <= status < 400 else "upstream_status")
    assert reply.reads == 0 and captured["connection"].closed
    assert KEY not in str(error.value)


@pytest.mark.parametrize("mutation", ["content_length", "streamed_size", "bad_length", "gzip", "mime"])
def test_response_limits_before_json_parsing(model, config, monkeypatch, mutation):
    reply = FakeResponse(response())
    if mutation == "content_length": reply.headers["Content-Length"] = str(config.max_response_bytes + 1)
    elif mutation == "streamed_size": reply.body = b"x" * (config.max_response_bytes + 1)
    elif mutation == "bad_length": reply.headers["Content-Length"] = "1, 2"
    elif mutation == "gzip": reply.headers["Content-Encoding"] = "gzip"
    elif mutation == "mime": reply.headers["Content-Type"] = "text/html"
    captured = fake_connection(model, monkeypatch, reply)
    with pytest.raises(model.ObservationModelError) as error:
        model._https_post(config, b"synthetic")
    assert error.value.code in {"response_too_large", "invalid_response"}
    assert captured["connection"].closed


@pytest.mark.parametrize("failure,code", [(TimeoutError(KEY), "timeout"), (ssl.SSLError(KEY), "transport_error"),
                                           (OSError(KEY), "transport_error")])
def test_timeout_and_transport_errors_never_log_or_expose_secrets(model, config, monkeypatch, caplog, failure, code):
    captured = fake_connection(model, monkeypatch, FakeResponse(b""), failure)
    with pytest.raises(model.ObservationModelError) as error:
        model._https_post(config, b"synthetic")
    assert error.value.code == code and captured["connection"].closed
    assert KEY not in "".join(traceback.format_exception(error.type, error.value, error.tb))
    assert not caplog.records


def test_deadline_during_response(model, config, monkeypatch):
    captured = fake_connection(model, monkeypatch, FakeResponse(response()))
    clock = iter([0, 0, 0, 0, config.timeout_seconds + 1])
    monkeypatch.setattr(model.time, "monotonic", lambda: next(clock))
    with pytest.raises(model.ObservationModelError) as error:
        model._https_post(config, b"synthetic")
    assert error.value.code == "timeout" and captured["connection"].closed


def test_request_budget(model, config, monkeypatch):
    monkeypatch.setattr(model, "MAX_REQUEST_BYTES", 10)
    monkeypatch.setattr(model, "_https_post", lambda *_: pytest.fail("Oversize request reached transport"))
    with pytest.raises(model.ObservationModelError) as error:
        model.ObservationModelClient(config).analyze(samples(model), **SOURCE)
    assert error.value.code == "request_too_large"
