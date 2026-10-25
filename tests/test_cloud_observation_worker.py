"""Real worker/store/client integration with synthetic data and fake HTTPS only."""
from __future__ import annotations

import base64
import copy
from dataclasses import replace
import hashlib
import importlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "rehab_affect"
OVERRIDES = ROOT / ".runtime" / "cloud_release_overrides"
SCRIPTS = ROOT / "scripts"
KEY = "synthetic-worker-key-not-real"
NAME = "PRIVATE_STUDENT_NAME_MUST_NOT_BE_SENT"
IEP = "PRIVATE_IEP_SUMMARY_MUST_NOT_BE_SENT"
BOX = {"x": 0.1, "y": 0.1, "width": 0.3, "height": 0.4}
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAIBAQEBAQIBAQECAgICAgQDAgICAgUEBAMEBgUGBgYFBgYG"
    "BwkIBgcJBwYGCAsICQoKCgoKBggLDAsKDAkKCgr/wAALCAAQABABAREA/8QAHwAAAQUBAQEBAQEAAAAA"
    "AAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEI"
    "I0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1"
    "dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ"
    "2uHi4+Tl5ufo6erx8vP09fb3+Pn6/9oACAEBAAA/ACiiiv/Z"
)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    if name.startswith("rehab_affect."):
        setattr(sys.modules["rehab_affect"], name.rsplit(".", 1)[1], module)
    assert Path(module.__file__).resolve() == path.resolve()
    return module


@pytest.fixture(scope="module")
def runtime():
    # Canonical imports are temporarily redirected, then restored for other tests.
    def owned(name):
        return name == "rehab_affect" or name.startswith("rehab_affect.") or name in {
            "cloud_observation_frames", "_cloud_observation_worker_integration"}
    saved = {name: module for name, module in sys.modules.items() if owned(name)}
    path = list(sys.path)
    for name in list(saved):
        del sys.modules[name]
    package = ModuleType("rehab_affect")
    package.__spec__ = importlib.machinery.ModuleSpec("rehab_affect", loader=None, is_package=True)
    package.__path__ = [str(SOURCE)]
    sys.modules["rehab_affect"] = package
    try:
        records = _load("rehab_affect.student_record_store", OVERRIDES / "student_record_store.py")
        model = _load("rehab_affect.demo2_observation_model", OVERRIDES / "demo2_observation_model.py")
        store = _load("rehab_affect.demo2_observation_store", OVERRIDES / "demo2_observation_store.py")
        identity = importlib.import_module("rehab_affect.demo2_identity_store")
        frames = _load("cloud_observation_frames", SCRIPTS / "cloud_observation_frames.py")
        worker = _load("_cloud_observation_worker_integration", SCRIPTS / "cloud_observation_worker.py")
        assert worker.ObservationModelClient is model.ObservationModelClient
        assert worker.SampleFrame is model.SampleFrame
        assert worker.Demo2ObservationStore is store.Demo2ObservationStore
        assert worker.get_demo2_student_store is records.get_demo2_student_store
        assert worker.load_job_frames is frames.load_job_frames
        yield SimpleNamespace(records=records, model=model, store=store, identity=identity, frames=frames, worker=worker)
    finally:
        for name in list(sys.modules):
            if owned(name):
                del sys.modules[name]
        sys.modules.update(saved)
        sys.path[:] = path


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Integration tests must not resolve hosts or open sockets")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


@pytest.fixture()
def env(runtime, tmp_path, monkeypatch, request):
    frame_count = getattr(request, "param", 4)
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "WorkerSynthetic-")
    monkeypatch.setenv("REHAB_DEMO2_COURSE_UPLOAD_LIMIT", "5")
    monkeypatch.setenv("REHAB_OBSERVATION_API_BASE", "https://synthetic.invalid/v1")
    monkeypatch.setenv("REHAB_OBSERVATION_MODEL", "synthetic-vision")
    monkeypatch.setenv("REHAB_OBSERVATION_API_KEY", KEY)
    records = runtime.records.Demo2StudentRecordStore(tmp_path / "records.sqlite3", tmp_path / "documents")
    with records._connect() as db:
        owner = db.execute("SELECT account_id FROM platform_accounts WHERE username='school_uploader_01'").fetchone()[0]
        db.execute("INSERT INTO school_contexts (account_id,city,district,school_name,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                   (owner, "Synthetic City", "Synthetic District", "Synthetic School", runtime.records._iso(), runtime.records._iso()))
    token = records.create_account_session(owner)["token"]
    identities = runtime.identity.Demo2IdentityStore(records)
    pupil = identities.create_student(token, {"display_name": NAME, "student_code": "synthetic-code", "class_name": "Private Synthetic Class"})
    content = b"synthetic uploaded source, not real school media"
    task = records.create_video_task({"account_session_token": token, "account_id": owner, "channel_id": "channel_1",
        "course_id": "private-course", "course_name": "Private course " + NAME, "session_id": "private-session",
        "uploader_name": "Private synthetic teacher", "filename": "synthetic.mp4", "byte_size": len(content), "total_chunks": 1})
    records.append_video_chunk({"task_id": task["task_id"], "account_session_token": token,
                                "course_id": task["course_id"], "chunk_index": 0}, chunk=content)
    claimed = records.claim_next_video_analysis()
    assert claimed["task_id"] == task["task_id"]
    directory, paths, samples = Path(claimed["analysis_dir"]), {}, []
    for index in range(frame_count):
        relative = f"media_synthetic/frames/frame_{index:06d}.jpg"
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(JPEG)
        paths[f"s0_f{index}"] = path
        samples.append({"timestamp_sec": index, "image_path": relative})
    manifest = {"task_id": task["task_id"], "source_sha256": hashlib.sha256(content).hexdigest(),
        "analysis_version": "demo2_media_evidence_v1.1", "analysis_status": "evidence_ready",
        "media": {"duration_sec": frame_count, "has_video": True, "has_audio": False},
        "sampling": {"fps": 1, "window_sec": 20},
        "segments": [{"segment_id": "segment_0000", "start_sec": 0, "end_sec": frame_count, "visual": {"samples": samples}}],
        "artifacts": {"frames": "media_synthetic/frames", "result": "media_synthetic/analysis.json"},
        "private_iep_context": {"student_name": NAME, "approved_summary": IEP}}
    records.finish_video_analysis(task["task_id"], manifest)
    with records._connect() as db:
        raw = dict(db.execute("SELECT * FROM video_analysis_tasks WHERE task_id=?", (task["task_id"],)).fetchone())
    revision = identities._revision(raw)
    binding = identities.save_binding(token, {"task_id": task["task_id"], "frame_key": "s0_f0", "frame_revision": revision,
        "role": "student", "student_id": pupil["student_id"], "bbox": dict(BOX)})
    store = runtime.store.Demo2ObservationStore(records, identities)
    monkeypatch.setenv("REHAB_OBSERVATION_ALLOWED_SHA256", raw["sha256"])
    client = runtime.model.ObservationModelClient(runtime.model.ObservationModelConfig.from_env())
    # The real offline detector is bounded separately; integration fixtures use no real faces.
    monkeypatch.setattr(runtime.frames, "_face_boxes", lambda path: [dict(BOX)])
    events = {"claims": [], "claim_options": [], "finishes": [], "failures": [], "load_attempts": [], "manifests": []}
    claim_next, finish, fail = store.claim_next, store.finish, store.fail
    load_frames = runtime.worker.load_job_frames

    def load_spy(*args):
        events["load_attempts"].append(args[2])
        result = load_frames(*args)
        events["manifests"].append(copy.deepcopy(result[1]))
        return result

    def claim_spy(**kwargs):
        events["claim_options"].append(kwargs)
        job = claim_next(**kwargs)
        if job is not None:
            # Sensitive job metadata is never provider input, even if attached upstream.
            job.update(student_name=NAME, iep_summary=IEP)
            events["claims"].append(job)
        return job

    def finish_spy(job, result, input_manifest=None):
        events["finishes"].append((job, copy.deepcopy(result)))
        assert input_manifest == events['manifests'][-1]
        return finish(job, result, input_manifest=input_manifest)

    def fail_spy(job, code):
        events["failures"].append((job, code))
        return fail(job, code)

    monkeypatch.setattr(store, "claim_next", claim_spy)
    monkeypatch.setattr(store, "finish", finish_spy)
    monkeypatch.setattr(store, "fail", fail_spy)
    monkeypatch.setattr(runtime.worker, "load_job_frames", load_spy)
    return SimpleNamespace(runtime=runtime, records=records, identities=identities, store=store, client=client,
        task_id=task["task_id"], raw=raw, manifest=manifest, revision=revision, token=token, pupil=pupil,
        binding=binding, paths=paths, events=events)


def _enqueue(env):
    return env.store.enqueue(env.task_id, frame_keys=list(env.paths), model=env.client.config.model)


def _job_row(env):
    with env.records._connect() as db:
        return dict(db.execute("SELECT * FROM demo2_observation_jobs WHERE task_id=?", (env.task_id,)).fetchone())


def _source_row(env):
    with env.records._connect() as db:
        return dict(db.execute("SELECT * FROM video_analysis_tasks WHERE task_id=?", (env.task_id,)).fetchone())


def _mutate(env, mutation):
    if mutation == "source_missing":
        Path(env.raw["file_path"]).unlink()
    elif mutation == "frame_missing":
        env.paths["s0_f0"].unlink()
    else:
        with env.records._connect() as db:
            if mutation == "expired":
                db.execute("UPDATE video_analysis_tasks SET expires_at='2000-01-01T00:00:00+00:00' WHERE task_id=?", (env.task_id,))
            elif mutation == "revision":
                changed = json.dumps({**env.manifest, "processing_revision": "changed"}, separators=(",", ":"))
                db.execute("UPDATE video_analysis_tasks SET processing_result_json=? WHERE task_id=?", (changed, env.task_id))
            else:
                raise AssertionError("Unknown synthetic source mutation")


class _Socket:
    def settimeout(self, timeout):
        assert 0 < timeout <= 90


class _Response:
    def __init__(self, body, status=200):
        self.body, self.status, self.reads = body, status, 0

    def getheader(self, name, default=None):
        return {"Content-Type": "application/json"}.get(name, default)

    def read1(self, size):
        self.reads += 1
        block, self.body = self.body[:size], self.body[size:]
        return block


@pytest.fixture()
def https(runtime, monkeypatch):
    wire = SimpleNamespace(connections=[], requests=[], responses=[], before_reply=None, failure=None,
                           mutation=None, status=200, batch_failures={}, batch_mutations={})

    class Connection:
        def __init__(self, host, port, *, timeout, context):
            assert (host, port) == ("synthetic.invalid", 443)
            assert 0 < timeout <= 90
            assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
            self.sock, self.closed, self.request_body = _Socket(), False, None
            wire.connections.append(self)

        def connect(self):
            if wire.failure is not None:
                raise wire.failure

        def request(self, method, path, *, body, headers):
            assert (method, path) == ("POST", "/v1/chat/completions")
            assert headers["Authorization"] == "Bearer " + KEY
            self.request_body = json.loads(body)
            wire.requests.append(self.request_body)

        def getresponse(self):
            if wire.before_reply:
                wire.before_reply()
            times = self.request_body["response_format"]["json_schema"]["schema"]["properties"]["frames"]["items"]["properties"]["timestamp_sec"]["enum"]
            if times[0] in wire.batch_failures:
                raise wire.batch_failures[times[0]]
            mutation = wire.batch_mutations.get(times[0], wire.mutation)
            frames = [{"timestamp_sec": t, "observations": [{"behavior": "hand_raised" if t == 0 else "writing", "person_index": 1}]
                       if index % 2 == 0 else []} for index, t in enumerate(times)]
            result = {"frames": frames}
            if mutation == "timestamp": frames[0]["timestamp_sec"] = 0.5
            elif mutation == "score": frames[0]["observations"][0]["score"] = 10
            elif mutation == "identity": frames[0]["observations"][0]["student_name"] = NAME
            elif mutation == "emotion": frames[0]["observations"][0]["behavior"] = "attentive"
            elif mutation == "unlocalized":
                for frame in frames:
                    for observation in frame["observations"]:
                        observation["person_index"] = None
            envelope = {"choices": [{"finish_reason": "length" if mutation == "truncated" else "stop",
                                     "message": {"role": "assistant", "content": json.dumps(result)}}]}
            body = b"not JSON" if mutation == "json" else json.dumps(envelope).encode()
            if wire.status != 200:
                body = (KEY + NAME + IEP).encode()
            reply = _Response(body, wire.status)
            wire.responses.append(reply)
            return reply

        def close(self):
            self.closed = True

    monkeypatch.setattr(runtime.model.http.client, "HTTPSConnection", Connection)
    return wire


def _failed(env, *, worker_code="source_unavailable"):
    row = _job_row(env)
    assert row["status"] == "failed" and row["error_code"] == worker_code
    assert row["result_json"] is None and row["normalized_json"] is None
    assert row["claim_hash"] is None and row["lease_until"] is None
    assert len(env.events["failures"]) == 1
    assert env.events["failures"][0] == (env.events["claims"][0], worker_code)
    assert not env.events["finishes"]


def test_actual_worker_imports_overrides_not_src(runtime):
    for module in (runtime.records, runtime.model, runtime.store):
        assert Path(module.__file__).resolve().parent == OVERRIDES
    assert runtime.worker.process_one.__globals__["ObservationModelError"] is runtime.model.ObservationModelError
    assert runtime.worker.process_one.__globals__["ObservationError"] is runtime.store.ObservationError
    assert Path(runtime.worker.__file__).resolve() == SCRIPTS / "cloud_observation_worker.py"


def test_real_processor_job_finishes_exact_provenance_without_private_provider_input(env, https, capsys):
    queued = _enqueue(env)
    assert env.runtime.worker.process_one(env.records, env.store, env.client) is True
    assert len(https.requests) == 1 and all(c.closed for c in https.connections)
    assert not env.events["failures"] and len(env.events["finishes"]) == 1
    assert len(env.events["load_attempts"]) == len(env.events["manifests"]) == 2
    assert env.events["manifests"][0] == env.events["manifests"][1]
    assert all(sample["image_sha256"] == hashlib.sha256(JPEG).hexdigest() for sample in env.events["manifests"][0])
    job, result = env.events["finishes"][0]
    assert job is env.events["claims"][0] and job["job_id"] == queued["job_id"]
    for field, expected in {"task_id": env.task_id, "source_sha256": env.raw["sha256"], "frame_revision": env.revision}.items():
        assert job[field] == result[field] == expected
    row = _job_row(env)
    assert row["status"] == "ready" and row["attempts"] == 1 and row["error_code"] == ""
    assert row["claim_hash"] is None and row["lease_until"] is None
    assert json.loads(row["result_json"]) == result
    normalized = json.loads(row["normalized_json"])["observations"]
    assert [(o["frame_key"], o["time_sec"], o["behavior"]) for o in normalized] == [
        ("s0_f0", 0, "hand_raised"), ("s0_f2", 2, "writing")]
    assert all(o["bbox"] == BOX and not o["reviewed"] for o in normalized)
    workspace = env.store.workspace(env.token, env.task_id)
    assert workspace["status"] == "ready" and workspace["result"] == result
    assert workspace["teacher_review_status"] == "not_reviewed" and not workspace["reviewed"]
    assert result["requires_teacher_review"] and not result["identity_recognition_performed"] and not result["scoring_performed"]
    assert _source_row(env) == env.raw
    binding = env.identities.workspace(env.token, env.task_id)["bindings"][0]
    assert binding["binding_id"] == env.binding["binding_id"] and binding["current_revision"]
    history = env.store.student_history(env.token, env.pupil["student_id"])["observations"]
    assert len(history) == 1 and history[0]["binding_id"] == env.binding["binding_id"]
    request = https.requests[0]
    assert request["max_tokens"] == 5000 and request["response_format"]["json_schema"]["strict"] is True
    sent = json.dumps(request)
    for private in (KEY, NAME, IEP, env.pupil["student_id"], env.binding["binding_id"], env.task_id, env.token, env.revision, env.raw["sha256"]):
        assert private not in sent
    content = request["messages"][1]["content"]
    images = [v["image_url"]["url"] for v in content if v["type"] == "image_url"]
    assert len(images) == 4 and all(base64.b64decode(v.split(",", 1)[1]) == JPEG for v in images)
    assert result["coverage"]["sample_timestamps_sec"] == [0, 1, 2, 3]
    assert result["coverage"]["media_duration_sec"] == 4 and not result["coverage"]["full_lesson"]
    output = capsys.readouterr()
    assert json.loads(output.out)["event"] == "observation_ready" and not output.err
    assert not any(private in output.out for private in (KEY, NAME, IEP))


def test_empty_queue_does_not_call_model_or_persist_any_result(env, https, capsys):
    assert env.runtime.worker.process_one(env.records, env.store, env.client) is False
    assert not https.connections and not env.events["claims"]
    assert not env.events["finishes"] and not env.events["failures"]
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("mutation", ["expired", "revision"])
def test_pending_source_invalidated_before_claim_never_reaches_provider(env, https, mutation):
    _enqueue(env)
    _mutate(env, mutation)
    assert env.runtime.worker.process_one(env.records, env.store, env.client) is False
    assert not https.connections and not env.events["claims"] and not env.events["finishes"]
    assert _job_row(env)["status"] == "failed" and _job_row(env)["result_json"] is None


@pytest.mark.parametrize("stage,mutation", [
    (stage, mutation) for stage in ("after_claim", "after_frame_load")
    for mutation in ("expired", "revision", "source_missing", "frame_missing")
    if (stage, mutation) != ("after_frame_load", "frame_missing")
])
def test_invalid_source_before_send_calls_store_fail_without_provider(env, https, monkeypatch, capsys, stage, mutation):
    _enqueue(env)
    if stage == "after_claim":
        claim = env.store.claim_next

        def invalidate_claim(**kwargs):
            job = claim(**kwargs)
            _mutate(env, mutation)
            return job
        monkeypatch.setattr(env.store, "claim_next", invalidate_claim)
    else:
        load = env.runtime.worker.load_job_frames

        def invalidate_after_load(*args):
            loaded = load(*args)
            _mutate(env, mutation)
            return loaded
        monkeypatch.setattr(env.runtime.worker, "load_job_frames", invalidate_after_load)
    assert env.runtime.worker.process_one(env.records, env.store, env.client) is True
    assert not https.connections and not https.requests
    _failed(env)
    assert json.loads(capsys.readouterr().out)["event"] == "observation_failed"


@pytest.mark.parametrize("mutation", ["expired", "revision"])
def test_source_changes_while_provider_is_running_cannot_be_marked_ready(env, https, mutation):
    _enqueue(env)
    https.before_reply = lambda: _mutate(env, mutation)
    assert env.runtime.worker.process_one(env.records, env.store, env.client) is True
    assert len(https.requests) == 1
    _failed(env)


@pytest.mark.parametrize("mutation", ["replace_bytes", "delete_image"])
def test_second_real_frame_load_rejects_changed_image_hash_without_publishing(env, https, mutation):
    _enqueue(env)
    path = env.paths["s0_f0"]
    stamp = path.stat()

    def change_image():
        if mutation == "delete_image":
            path.unlink()
        else:
            changed = bytearray(JPEG)
            # Change a JPEG quantization value without changing size or geometry.
            changed[25] = 3 if changed[25] != 3 else 4
            path.write_bytes(changed)
            os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            assert path.stat().st_size == stamp.st_size
            assert path.stat().st_mtime_ns == stamp.st_mtime_ns
    https.before_reply = change_image
    assert env.runtime.worker.process_one(env.records, env.store, env.client) is True
    assert len(https.requests) == 1 and len(env.events["load_attempts"]) == 2
    assert _source_row(env) == env.raw  # The image check cannot rely on DB revision changes.
    _failed(env)
    if mutation == "replace_bytes":
        assert len(env.events["manifests"]) == 2
        first, second = env.events["manifests"]
        assert first[0]["frame_key"] == second[0]["frame_key"] == "s0_f0"
        assert first[0]["timestamp_sec"] == second[0]["timestamp_sec"] == 0
        assert first[0]["image_sha256"] != second[0]["image_sha256"]
        assert first[1:] == second[1:]
    else:
        assert len(env.events["manifests"]) == 1


@pytest.mark.parametrize("failure,expected", [
    ("401", "upstream_status"), ("429", "upstream_status"), ("500", "upstream_status"),
    ("timeout", "timeout"), ("tls", "transport_error"),
    ("json", "invalid_response"), ("timestamp", "invalid_response"), ("score", "invalid_response"),
    ("identity", "invalid_response"), ("emotion", "invalid_response"), ("truncated", "model_refused"),
])
def test_provider_failure_calls_real_store_fail_never_ready_or_secret_logs(env, https, capsys, failure, expected):
    _enqueue(env)
    if failure.isdigit(): https.status = int(failure)
    elif failure == "timeout": https.failure = TimeoutError(KEY + IEP)
    elif failure == "tls": https.failure = ssl.SSLError(KEY + IEP)
    else: https.mutation = failure
    assert env.runtime.worker.process_one(env.records, env.store, env.client) is True
    _failed(env, worker_code=expected)
    reopened = env.runtime.store.Demo2ObservationStore(env.records)
    visible = reopened.workspace(env.token, env.task_id)
    assert visible["status"] == "failed" and visible["error_code"] == expected
    assert visible["result"] is None
    assert len(https.connections) == (2 if failure == 'timeout' else 1)
    assert all(connection.closed for connection in https.connections)
    assert len(env.events["load_attempts"]) == 1
    if failure.isdigit(): assert https.responses[0].reads == 0
    assert _source_row(env) == env.raw
    output = capsys.readouterr()
    event = json.loads(output.out)
    assert event["event"] == "observation_failed" and event["code"] == expected and not output.err
    adapter_code = ("upstream_status" if failure.isdigit() else "transport_error" if failure == "tls"
                    else "model_refused" if failure == "truncated" else "timeout" if failure == "timeout" else "invalid_response")
    assert event["adapter_error_code"] == adapter_code
    detail = {"json": "response_json", "timestamp": "response_schema", "score": "response_schema",
              "identity": "response_schema", "emotion": "response_schema", "truncated": "completion_truncated"}.get(failure, adapter_code)
    assert event["adapter_error_detail"] == detail
    assert not any(value in output.out + json.dumps(_job_row(env)) for value in (KEY, NAME, IEP))


@pytest.mark.parametrize("field", ["task_id", "source_sha256", "frame_revision"])
def test_real_finish_rejects_wrong_provenance_and_worker_marks_failed(env, https, monkeypatch, field):
    _enqueue(env)
    real_finish = env.store.finish

    def wrong_provenance(job, result, input_manifest=None):
        result = {**result, field: "another-task" if field == "task_id" else "c" * 64}
        return real_finish(job, result, input_manifest=input_manifest)
    monkeypatch.setattr(env.store, "finish", wrong_provenance)
    assert env.runtime.worker.process_one(env.records, env.store, env.client) is True
    assert len(https.requests) == 1
    row = _job_row(env)
    assert row["status"] == "failed" and row["result_json"] is None and row["normalized_json"] is None
    assert len(env.events["failures"]) == 1 and env.events["failures"][0][1] == "source_unavailable"
    assert _source_row(env) == env.raw


@pytest.mark.parametrize("env", [5, 8], indirect=True)
def test_split_requests_overlap_and_merge_exact_canonical_without_private_input(env, https, monkeypatch, capsys):
    _enqueue(env)
    real_analyze = env.client.analyze
    rendezvous = threading.Barrier(2, timeout=5)
    second_done = threading.Event()
    calls, completed = [], []

    def analyze(samples, **provenance):
        calls.append(([sample.timestamp_sec for sample in samples], provenance))
        if samples[0].timestamp_sec < 4:
            rendezvous.wait()
        if samples[0].timestamp_sec == 0:
            assert second_done.wait(5), "Second batch must run without waiting for the first"
        try:
            result = real_analyze(samples, **provenance)
            completed.append(samples[0].timestamp_sec)
            return result
        finally:
            if samples[0].timestamp_sec == 2:
                second_done.set()

    monkeypatch.setattr(env.client, "analyze", analyze)
    assert env.runtime.worker.process_one(env.records, env.store, env.client) is True
    count = len(env.paths)
    assert len(calls) == len(https.requests) == (count + 1) // 2
    assert completed.index(2) < completed.index(0)
    assert sorted(times for times, _ in calls) == [list(range(start, min(start + 2, count))) for start in range(0, count, 2)]
    assert all(provenance == {"task_id": env.task_id, "source_sha256": env.raw["sha256"],
        "frame_revision": env.revision, "media_duration_sec": count} for _, provenance in calls)
    assert env.events["claim_options"] == [{"lease_seconds": 300}]
    assert len(env.events["load_attempts"]) == 2 and env.events["manifests"][0] == env.events["manifests"][1]
    assert len(env.events["finishes"]) == 1 and not env.events["failures"]
    result = env.events["finishes"][0][1]
    assert set(result) == {"schema_version", "task_id", "source_sha256", "frame_revision", "model", "coverage",
                          "frames", "teacher_suggestions", "requires_teacher_review", "identity_recognition_performed", "scoring_performed"}
    assert result["schema_version"] == env.runtime.model.SCHEMA_VERSION and result["model"] == env.client.config.model
    assert result["coverage"] == {"scope": "sampled_frames_only", "sample_timestamps_sec": list(range(count)),
        "sample_count": count, "media_duration_sec": count, "continuous_coverage": False, "full_lesson": False}
    assert [frame["timestamp_sec"] for frame in result["frames"]] == list(range(count))
    assert result["teacher_suggestions"] == env.runtime.model._suggestions(result["frames"])
    assert result["requires_teacher_review"] is True and result["identity_recognition_performed"] is False and result["scoring_performed"] is False
    assert _job_row(env)["status"] == "ready" and json.loads(_job_row(env)["result_json"]) == result
    assert _source_row(env) == env.raw and all(c.closed for c in https.connections)
    sent = json.dumps(https.requests)
    for private in (KEY, NAME, IEP, env.pupil["student_id"], env.binding["binding_id"], env.task_id, env.token, env.revision, env.raw["sha256"]):
        assert private not in sent
    images = [item["image_url"]["url"] for request in https.requests for item in request["messages"][1]["content"] if item["type"] == "image_url"]
    assert len(images) == count and all(base64.b64decode(url.split(",", 1)[1]) == JPEG for url in images)
    assert all(request["max_tokens"] == 5000 and request["response_format"]["json_schema"]["strict"] is True for request in https.requests)
    assert json.loads(capsys.readouterr().out)["event"] == "observation_ready"


@pytest.mark.parametrize("env", [8], indirect=True)
@pytest.mark.parametrize("first_timestamp", [0, 6])
@pytest.mark.parametrize("failure", ["timeout", "truncated"])
def test_either_batch_failure_is_bounded_and_does_not_publish_partial_job(env, https, capsys, first_timestamp, failure):
    _enqueue(env)
    if failure == "timeout":
        https.batch_failures[first_timestamp] = TimeoutError(KEY + NAME + IEP)
    else:
        https.batch_mutations[first_timestamp] = "truncated"
    assert env.runtime.worker.process_one(env.records, env.store, env.client) is True
    _failed(env, worker_code="timeout" if failure == "timeout" else "model_refused")
    assert 1 <= len(https.requests) <= (5 if failure == 'timeout' else 4)
    assert len(https.requests) == len(https.connections)
    assert all(c.closed for c in https.connections)
    request_times = [request["response_format"]["json_schema"]["schema"]["properties"]["frames"]["items"]["properties"]["timestamp_sec"]["enum"][0] for request in https.requests]
    assert first_timestamp in request_times
    assert request_times.count(first_timestamp) == (2 if failure == 'timeout' else 1)
    assert all(request_times.count(timestamp) == 1 for timestamp in set(request_times) - {first_timestamp})
    assert len(env.events["load_attempts"]) == 1 and _source_row(env) == env.raw
    event = json.loads(capsys.readouterr().out)
    assert event["adapter_error_code"] == ("timeout" if failure == "timeout" else "model_refused")
    assert not any(secret in json.dumps(event) for secret in (KEY, NAME, IEP))


@pytest.mark.parametrize("count", [1, 4])
def test_small_fake_client_keeps_single_call_contract(runtime, count):
    calls = []
    marker = object()

    def analyze(samples, **kwargs):
        calls.append((samples, kwargs))
        return marker

    job = {"task_id": "synthetic-task", "source_sha256": "a" * 64, "frame_revision": "b" * 64, "duration_sec": 8}
    frames = [{"timestamp_sec": n, "image_bytes": JPEG, "mime_type": "image/jpeg"} for n in range(count)]
    assert runtime.worker._analyze_job(SimpleNamespace(analyze=analyze), frames, job) is marker
    assert len(calls) == 1 and len(calls[0][0]) == count
    assert calls[0][1] == {key: value for key, value in job.items() if key != "duration_sec"} | {"media_duration_sec": 8}


@pytest.mark.parametrize("mutation", ["task_id", "source_sha256", "frame_revision", "model", "schema_version",
    "missing_provenance", "extra_field", "safety_flag", "coverage_count", "coverage_timestamp", "coverage_duration",
    "coverage_full_lesson", "duplicate_frame", "too_many_actions", "invalid_behavior", "suggestions"])
def test_split_rejects_noncanonical_batch_metadata_or_content(runtime, mutation):
    job = {"task_id": "synthetic-task", "source_sha256": "a" * 64, "frame_revision": "b" * 64,
           "duration_sec": 8, "model": "synthetic-vision"}
    frames = [{"timestamp_sec": n, "image_bytes": JPEG, "mime_type": "image/jpeg"} for n in range(8)]

    def analyze(samples, **kwargs):
        times = [float(sample.timestamp_sec) for sample in samples]
        result = {"schema_version": runtime.model.SCHEMA_VERSION, **{k: job[k] for k in ("task_id", "source_sha256", "frame_revision", "model")},
            "coverage": {"scope": "sampled_frames_only", "sample_timestamps_sec": times, "sample_count": len(samples),
                "media_duration_sec": 8, "continuous_coverage": False, "full_lesson": False},
            "frames": [{"timestamp_sec": t, "observations": []} for t in times], "teacher_suggestions": [],
            "requires_teacher_review": True, "identity_recognition_performed": False, "scoring_performed": False}
        if times[0] != 4:
            return result
        if mutation in ("task_id", "source_sha256", "frame_revision", "model", "schema_version"): result[mutation] = "wrong"
        elif mutation == "missing_provenance": del result["source_sha256"]
        elif mutation == "extra_field": result["private_text"] = IEP
        elif mutation == "safety_flag": result["requires_teacher_review"] = 1
        elif mutation == "coverage_count": result["coverage"]["sample_count"] = 8
        elif mutation == "coverage_timestamp": result["coverage"]["sample_timestamps_sec"] = list(range(4))
        elif mutation == "coverage_duration": result["coverage"]["media_duration_sec"] = 4
        elif mutation == "coverage_full_lesson": result["coverage"]["full_lesson"] = True
        elif mutation == "duplicate_frame": result["frames"][1] = copy.deepcopy(result["frames"][0])
        elif mutation == "too_many_actions": result["frames"][0]["observations"] = [{"behavior": "writing", "bbox": None}] * 17
        elif mutation == "invalid_behavior": result["frames"][0]["observations"] = [{"behavior": "attentive", "bbox": None}]
        elif mutation == "suggestions": result["teacher_suggestions"] = [{"timestamp_sec": 4, "code": "made_up_score", "evidence_behaviors": ["writing"]}]
        return result

    with pytest.raises(runtime.model.ObservationModelError) as error:
        config = runtime.model.ObservationModelConfig(endpoint="https://synthetic.invalid/v1/chat/completions",
            model="synthetic-vision", api_key=KEY, enabled=True)
        runtime.worker._analyze_job(SimpleNamespace(analyze=analyze, config=config), frames, job)
    assert error.value.code == "invalid_response"


@pytest.mark.parametrize("env", [8], indirect=True)
def test_split_accepts_api_job_with_blank_queued_model_using_configured_model(env, https):
    env.store.enqueue(env.token, env.task_id, frame_keys=list(env.paths))
    assert _job_row(env)["model"] == ""
    assert env.runtime.worker.process_one(env.records, env.store, env.client) is True
    assert env.events["claims"][0]["model"] == ""
    assert not env.events["failures"] and len(env.events["finishes"]) == 1
    result = env.events["finishes"][0][1]
    assert result["model"] == env.client.config.model and result["coverage"]["sample_count"] == 8
    assert _job_row(env)["status"] == "ready" and len(https.requests) == 4
    assert all(request["model"] == env.client.config.model for request in https.requests)


@pytest.mark.parametrize("env", [8], indirect=True)
def test_nonempty_queued_model_mismatch_fails_before_provider(env, https):
    env.store.enqueue(env.task_id, frame_keys=list(env.paths), model="different-configured-model")
    assert env.runtime.worker.process_one(env.records, env.store, env.client) is True
    _failed(env, worker_code="invalid_input")
    assert not https.connections and not https.requests


@pytest.mark.parametrize("env", [8], indirect=True)
@pytest.mark.parametrize("mutation", ["expired", "revision", "image_hash"])
def test_split_still_rechecks_source_and_evidence_before_publish(env, https, monkeypatch, mutation):
    _enqueue(env)
    analyze = env.client.analyze

    def change_after_second_batch(samples, **kwargs):
        result = analyze(samples, **kwargs)
        if samples[0].timestamp_sec == 6:
            if mutation == "image_hash":
                image = bytearray(JPEG)
                image[25] = 3 if image[25] != 3 else 4
                env.paths["s0_f0"].write_bytes(image)
            else:
                _mutate(env, mutation)
        return result

    monkeypatch.setattr(env.client, "analyze", change_after_second_batch)
    assert env.runtime.worker.process_one(env.records, env.store, env.client) is True
    _failed(env)
    assert len(https.requests) == 4
    if mutation == "image_hash":
        assert len(env.events["load_attempts"]) == 2 and env.events["manifests"][0] != env.events["manifests"][1]


def test_worker_caps_real_adapter_timeout_at_90_without_mutating_client(env, https):
    _enqueue(env)
    client = env.runtime.model.ObservationModelClient(replace(env.client.config, timeout_seconds=120))
    assert env.runtime.worker.process_one(env.records, env.store, client) is True
    assert client.config.timeout_seconds == 120
    assert len(https.requests) == 1 and _job_row(env)["status"] == "ready"


def test_transient_timeout_retries_once_and_preserves_actual_input(env, https, monkeypatch):
    _enqueue(env)
    original = env.client.analyze
    calls = []
    def once(samples, **kwargs):
        calls.append(([sample.image_bytes for sample in samples], kwargs))
        if len(calls) == 1:
            raise env.runtime.model.ObservationModelError('timeout')
        return original(samples, **kwargs)
    monkeypatch.setattr(env.client, 'analyze', once)
    assert env.runtime.worker.process_one(env.records, env.store, env.client)
    assert len(calls) == 2 and calls[0] == calls[1]
    assert _job_row(env)['status'] == 'ready'


def test_expired_batch_budget_does_not_contact_model(env, monkeypatch):
    monkeypatch.setattr(env.client, 'analyze', lambda *args, **kwargs: pytest.fail('Budget exceeded'))
    with pytest.raises(env.runtime.model.ObservationModelError) as error:
        env.runtime.worker._analyze_batch(env.client, [], {}, 0)
    assert error.value.code == 'timeout'


def test_unknown_adapter_error_code_is_never_logged_as_raw_text(env, monkeypatch, capsys):
    _enqueue(env)

    def fail(*args, **kwargs):
        error = env.runtime.model.ObservationModelError("timeout")
        error.code = KEY + NAME + IEP
        error.diagnostic_code = KEY + NAME + IEP
        raise error

    monkeypatch.setattr(env.client, "analyze", fail)
    assert env.runtime.worker.process_one(env.records, env.store, env.client) is True
    _failed(env, worker_code="invalid_result")
    output = capsys.readouterr()
    assert json.loads(output.out)["adapter_error_code"] == "unknown_error"
    assert json.loads(output.out)["adapter_error_detail"] == "unknown_error"
    assert not any(secret in output.out + output.err for secret in (KEY, NAME, IEP))


def test_local_regions_are_cached_by_exact_image_and_do_not_send_binding_metadata(env, https, monkeypatch, capsys):
    detected = []

    def proposals(path):
        detected.append(path)
        return [dict(BOX)]

    monkeypatch.setattr(env.runtime.frames, "_face_boxes", proposals)
    _enqueue(env)
    assert env.runtime.worker.process_one(env.records, env.store, env.client) is True
    assert len(detected) == 3  # Frame zero already has a confirmed ROI; second load reuses proposals.
    assert env.events["manifests"][0] == env.events["manifests"][1]
    first = env.events["manifests"][0]
    assert first[0]["person_box_source"] == "confirmed_frame_roi"
    assert all(item["person_box_source"] == "local_face_detection" for item in first[1:])
    assert all(item["person_boxes"] == [BOX] for item in first)
    event = json.loads(capsys.readouterr().out)
    assert event["localized_observations"] == 2 and event["group_only_observations"] == 0
    sent = json.dumps(https.requests)
    assert "anonymous same-frame person regions=" in sent
    assert all(value not in sent for value in (NAME, IEP, env.pupil["student_id"], env.binding["binding_id"]))


def test_group_only_result_is_preserved_without_automatic_student_attribution(env, https, capsys):
    _enqueue(env)
    https.mutation = "unlocalized"
    assert env.runtime.worker.process_one(env.records, env.store, env.client) is True
    assert _job_row(env)["status"] == "ready"
    result = env.events["finishes"][0][1]
    assert all(observation["bbox"] is None for frame in result["frames"] for observation in frame["observations"])
    assert env.store.student_history(env.token, env.pupil["student_id"])["observations"] == []
    event = json.loads(capsys.readouterr().out)
    assert event["localized_observations"] == 0 and event["group_only_observations"] == 2


def test_offline_face_proposals_are_bounded_validated_and_anonymous(runtime, monkeypatch, tmp_path):
    detector = importlib.import_module("rehab_affect.demo2_face_detection")
    boxes = [{"x": 0.02 + (n % 6) * 0.16, "y": 0.1 + (n // 6) * 0.25, "width": 0.08, "height": 0.1} for n in range(13)]
    faces = [{"bbox": {**BOX, "student_id": NAME}}, {"bbox": {**BOX, "width": 0}},
             *[{"bbox": box, "candidate_id": IEP, "score": 0.9} for box in boxes]]
    monkeypatch.setattr(detector, "detect_faces", lambda path: {"available": True, "faces": faces})
    assert runtime.frames._face_boxes(tmp_path / "synthetic.jpg") == boxes[:12]
    monkeypatch.setattr(detector, "detect_faces", lambda path: {"available": False, "faces": faces})
    assert runtime.frames._face_boxes(tmp_path / "synthetic.jpg") == []


def test_numbered_copy_preserves_original_geometry_bytes_and_proposal_coordinates(runtime, tmp_path):
    cv = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    source = np.zeros((360, 640), dtype=np.uint8)
    ok, encoded = cv.imencode(".jpg", source)
    assert ok
    original = encoded.tobytes()
    path = tmp_path / "synthetic.jpg"
    path.write_bytes(original)
    boxes = [{"x": 0.02 + (n % 6) * 0.16, "y": 0.1 + (n // 6) * 0.4, "width": 0.08, "height": 0.1} for n in range(12)]
    saved = copy.deepcopy(boxes)
    annotated = runtime.frames._numbered_copy(original, path, boxes)
    assert isinstance(annotated, bytes) and annotated != original
    assert path.read_bytes() == original and boxes == saved
    pixels = cv.imdecode(np.frombuffer(annotated, np.uint8), cv.IMREAD_COLOR)
    assert pixels.shape == (360, 640, 3)
    assert (pixels.max(axis=2) - pixels.min(axis=2) > 30).sum() > 200
    assert runtime.frames._numbered_copy(original, path, boxes) == annotated


def test_worker_supplies_numbered_model_copy_but_hashes_immutable_source(env, https):
    cv = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    ok, encoded = cv.imencode(".jpg", np.zeros((360, 640), dtype=np.uint8))
    assert ok
    original = encoded.tobytes()
    env.paths["s0_f0"].write_bytes(original)
    _enqueue(env)
    assert env.runtime.worker.process_one(env.records, env.store, env.client) is True
    assert _job_row(env)["status"] == "ready"
    image_url = next(item["image_url"]["url"] for item in https.requests[0]["messages"][1]["content"] if item["type"] == "image_url")
    sent = base64.b64decode(image_url.split(",", 1)[1])
    assert sent != original and env.paths["s0_f0"].read_bytes() == original
    first = env.events["manifests"][0][0]
    assert first["image_sha256"] == hashlib.sha256(original).hexdigest()
    assert first["model_image_sha256"] == hashlib.sha256(sent).hexdigest()
    assert env.events["manifests"][0] == env.events["manifests"][1]
    assert env.events["finishes"][0][1]["frames"][0]["observations"][0]["bbox"] == BOX
