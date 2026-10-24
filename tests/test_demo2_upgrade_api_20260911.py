"""Independent upgrade contracts. No live ports, production DBs or browser use.

Only fixture HTTP listeners on ephemeral loopback ports are permitted. Detection
and extraction are disclosed stubs; preview bytes are a decodable synthetic JPEG.
Run this file explicitly after implementation, not alongside full browser QA.
"""

from __future__ import annotations

import copy
import hashlib
import http.client
import importlib.util
import json
import socket
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode
from uuid import uuid4

import pytest

from scripts import qa_demo2_upgrade_20260911 as qa


API = qa.API


def request(env, endpoint, *, user="t1", query=None, method="GET", token=None):
    assert env.port not in {8792, 8796}
    query = env.query if query is None else query
    path = API + "/" + endpoint + ("?" + urlencode(query) if query else "")
    headers = {"Host": f"127.0.0.1:{env.port}", "Connection": "close", "Content-Length": "0"}
    token = token if token is not None else (env.tokens[user] if user else "")
    if token:
        headers["Cookie"] = "rehab_demo2_session=" + token
    wire = (f"{method} {path} HTTP/1.1\r\n" +
            "".join(f"{key}: {value}\r\n" for key, value in headers.items()) + "\r\n").encode("ascii")
    connection = http.client.HTTPConnection("127.0.0.1", env.port, timeout=20)
    try:
        connection.connect()
        connection.sock.sendall(wire)
        response = http.client.HTTPResponse(connection.sock, method=method)
        response.begin()
        data = response.read()
        received = {key.lower(): value for key, value in response.getheaders()}
        parsed = json.loads(data) if "application/json" in received.get("content-type", "") else data
        return response.status, received, parsed
    finally:
        connection.close()


def update_task(env, **changes):
    assert set(changes) <= {"expires_at", "processing_result_json", "sha256", "analysis_status", "account_id"}
    with env.records._connect() as connection:
        connection.execute("UPDATE video_analysis_tasks SET " + ",".join(key + "=?" for key in changes) +
                           " WHERE task_id=?", (*changes.values(), env.task_ids["t1"]))


def business_snapshot(env):
    with env.records._connect() as connection:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {name: sorted((tuple(row) for row in connection.execute('SELECT * FROM "' + name + '"')), key=repr)
                for name in tables if name not in {"audit_logs", "account_sessions", "sqlite_sequence"}}


@pytest.fixture
def env(tmp_path, monkeypatch, request):
    from scripts import qa_demo2_identity_20260910 as harness

    # Reject any accidental production or external connection from the fixture.
    connect = socket.socket.connect

    def only_fixture_connect(sock, address):
        assert isinstance(address, tuple) and address[0] == "127.0.0.1"
        assert address[1] not in {8792, 8796}
        return connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", only_fixture_connect)
    original_loader = harness._private_server_module
    clock = SimpleNamespace(now=1000.0)
    settings = getattr(request, "param", {})
    detect_cache_writes = []

    def load_private():
        server = original_loader()
        server.DEMO2_IDENTITY_DETECT_CACHE_TTL = settings.get("detect_ttl", 120.0)
        server.DEMO2_IDENTITY_PREVIEW_CACHE_TTL = 60.0
        server.time = SimpleNamespace(**{key: getattr(time, key) for key in dir(time) if not key.startswith("__")})
        server.time.monotonic = lambda: clock.now
        cache_path = Path(server.__file__).with_name("demo2_media_cache.py")
        spec = importlib.util.spec_from_file_location("_upgrade_qa_cache_" + uuid4().hex, cache_path)
        cache_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cache_module)
        cache_module.time = server.time

        class ObservedCache(cache_module.MediaResultCache):
            def put(self, key, value, *, size):
                if self.max_entries == 128:
                    detect_cache_writes.append(key)
                return super().put(key, value, size=size)

        server.MediaResultCache = ObservedCache
        return server

    monkeypatch.setattr(harness, "_private_server_module", load_private)
    with harness.isolated_identity_server(tmp_path / "upgrade", seed_students=True) as value:
        assert value.root.resolve().is_relative_to(tmp_path.resolve())
        value.clock = clock
        value.detect_calls = []
        value.detect_cache_writes = detect_cache_writes
        value.on_detect = None
        value.detector_result = {"available": True, "model": "qa-position-only-stub", "faces": [],
                                 "recognition_performed": False, "fixture_only": True}
        value.model_file = value.root / "synthetic-model-identity.bin"
        value.model_file.write_bytes(b"QA MODEL IDENTITY ONLY")

        def detect(path):
            assert Path(path).resolve().is_relative_to(value.root.resolve())
            value.detect_calls.append(Path(path))
            if value.on_detect:
                value.on_detect()
            return copy.deepcopy(value.detector_result)

        detector = SimpleNamespace(detect_faces=detect, MODEL_PATH=value.model_file,
                                   MODEL_NAME="qa-position-only-stub", EXPECTED_MODEL_SHA256="qa-model-v1")
        original_import = value.server.importlib.import_module

        def isolated_import(name, package=None):
            if name == ".demo2_face_detection":
                return detector
            return original_import(name, package)

        value.server.importlib = SimpleNamespace(import_module=isolated_import)
        value.detector = detector
        current = value.identity.workspace(value.tokens["t1"], value.task_ids["t1"])
        value.query = {"task_id": value.task_ids["t1"], "frame_key": current["frames"][0]["frame_key"],
                       "frame_revision": current["frame_revision"]}
        value.frame = value.identity.frame_file(value.tokens["t1"], *value.query.values())[0]
        value.source = value.identity.preview_source(value.tokens["t1"], *value.query.values())["source_path"]
        value.preview_calls = []
        value.preview_bytes = value.frame.read_bytes()
        value.preview_error = None
        value.on_extract = None

        class PreviewError(ValueError):
            def __init__(self, code, message):
                super().__init__(message)
                self.code, self.message = code, message

        def extract_preview(path, timestamp):
            assert path.resolve().is_relative_to(value.root.resolve())
            value.preview_calls.append((path, timestamp))
            if value.on_extract:
                value.on_extract()
            if value.preview_error:
                raise PreviewError(*value.preview_error)
            return {"image_bytes": value.preview_bytes, "width": 640, "height": 360}

        extractor = SimpleNamespace(extract_preview=extract_preview, PreviewError=PreviewError)
        detector_import = value.server.importlib.import_module

        def import_with_preview(name, package=None):
            if name == ".demo2_frame_preview":
                return extractor
            return detector_import(name, package)

        value.server.importlib = SimpleNamespace(import_module=import_with_preview)
        yield value


def detection(env, *, cached, **options):
    status, headers, body = request(env, "detect", **options)
    assert status == 200, body
    assert body["detection"]["cached"] is cached
    assert "no-store" in headers["cache-control"]
    return body["detection"]


def preview(env, **options):
    import cv2
    import numpy as np

    status, headers, body = request(env, "preview", **options)
    assert status == 200
    assert headers["content-type"].split(";", 1)[0] == "image/jpeg"
    assert "no-store" in headers["cache-control"]
    assert body.startswith(b"\xff\xd8") and body.endswith(b"\xff\xd9")
    decoded = cv2.imdecode(np.frombuffer(body, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None and decoded.shape[0] > 0 and decoded.shape[1] > 0
    assert float(decoded.std()) > 5, "Preview must show nonblank synthetic content"
    return headers, body


def test_baseline_allowlist_rejects_writes_and_other_tasks_without_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid live requests must be rejected before opening a connection")

    monkeypatch.setattr(qa.http.client, "HTTPConnection", forbidden)
    client = qa.ReadOnlyLiveClient()
    for endpoint in ("students", "bindings", "task-school", "../admin", "https://example.invalid"):
        with pytest.raises(qa.SafeQAError):
            client.request("t1", endpoint, query={"task_id": qa.TASK_ID})
    with pytest.raises(qa.SafeQAError):
        client.request("t1", "workspace", query={"task_id": "unauthorized-task"})


def test_baseline_requires_environment_passwords_without_network(monkeypatch):
    for variable in qa.PASSWORD_ENV.values():
        monkeypatch.delenv(variable, raising=False)
    with pytest.raises(qa.SafeQAError, match="Missing password environment"):
        qa.collect("before")


def test_baseline_summary_retains_three_samples():
    rows = [{"role": "t1", "endpoint": "frame", "status": 200, "response_bytes": 100,
             "elapsed_ms": value} for value in (10, 40, 20)]
    summary = qa.summarize(rows)[0]
    assert summary["count"] == 3 and summary["median_ms"] == 20
    assert summary["elapsed_ms"] == [10, 40, 20]


def test_detect_hit_skips_inference_but_miss_keeps_rate_limit(env):
    detection(env, cached=False)
    for _ in range(3):
        detection(env, cached=True)
    assert len(env.detect_calls) == 1
    status, _, _ = request(env, "detect", query={**env.query, "frame_key": "s0_f1"})
    assert status == 429
    env.clock.now += 2.21
    detection(env, cached=False, query={**env.query, "frame_key": "s0_f1"})
    assert len(env.detect_calls) == 2


def test_detect_cache_is_account_not_session_scoped(env):
    detection(env, cached=False)
    token = env.records.create_account_session(env.accounts["t1"])["token"]
    detection(env, cached=True, token=token)
    detection(env, cached=False, user="admin")
    detection(env, cached=True, user="admin")
    assert len(env.detect_calls) == 2


@pytest.mark.parametrize("user,status", [(None, 401), ("member", 403), ("t2", 404)])
@pytest.mark.parametrize("endpoint", ["detect", "preview"])
def test_warm_cache_never_bypasses_account_authorization(env, endpoint, user, status):
    if endpoint == "detect":
        detection(env, cached=False)
    else:
        preview(env)
    actual, _, body = request(env, endpoint, user=user)
    assert actual == status
    assert isinstance(body, dict) and body.get("ok") is False
    assert env.task_ids["t1"] not in json.dumps(body)


@pytest.mark.parametrize("endpoint", ["detect", "preview"])
def test_warm_cache_rechecks_session_expiry(env, endpoint):
    assert request(env, endpoint)[0] == 200
    token_hash = hashlib.sha256(env.tokens["t1"].encode()).hexdigest()
    with env.records._connect() as connection:
        connection.execute("UPDATE account_sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE token_hash=?",
                           (token_hash,))
    assert request(env, endpoint)[0] == 401


@pytest.mark.parametrize("endpoint", ["frame", "detect", "preview"])
def test_warm_manifest_and_response_cache_recheck_task_expiry(env, endpoint):
    assert request(env, endpoint)[0] == 200
    update_task(env, expires_at="2000-01-01T00:00:00+00:00")
    assert request(env, endpoint)[0] == 410


@pytest.mark.parametrize("endpoint", ["frame", "detect", "preview"])
def test_warm_manifest_and_response_cache_recheck_revision(env, endpoint):
    assert request(env, endpoint)[0] == 200
    with env.records._connect() as connection:
        raw = connection.execute("SELECT processing_result_json FROM video_analysis_tasks WHERE task_id=?",
                                 (env.task_ids["t1"],)).fetchone()[0]
    update_task(env, processing_result_json=raw + " ")
    assert request(env, endpoint)[0] == 409
    env.query["frame_revision"] = hashlib.sha256((raw + " ").encode()).hexdigest()
    env.clock.now += 2.21
    assert request(env, endpoint)[0] == 200
    if endpoint == "detect":
        assert len(env.detect_calls) == 2


@pytest.mark.parametrize("endpoint", ["frame", "detect", "preview"])
def test_warm_manifest_cache_rechecks_selected_file(env, endpoint):
    assert request(env, endpoint)[0] == 200
    env.frame.unlink()
    status, _, body = request(env, endpoint)
    assert status in {404, 410}, body


def test_detect_cache_expires_at_ttl(env):
    detection(env, cached=False)
    env.clock.now += 119.99
    detection(env, cached=True)
    env.clock.now += 0.02
    detection(env, cached=False)
    assert len(env.detect_calls) == 2


@pytest.mark.parametrize("env", [{"detect_ttl": 0}], indirect=True)
def test_detect_ttl_zero_disables_cache(env):
    detection(env, cached=False)
    env.clock.now += 2.21
    detection(env, cached=False)
    assert len(env.detect_calls) == 2


def test_unavailable_detection_is_never_cached(env):
    env.detector_result["available"] = False
    detection(env, cached=False)
    env.clock.now += 2.21
    detection(env, cached=False)
    assert len(env.detect_calls) == 2


@pytest.mark.parametrize("change", ["frame_stat", "model_identity"])
def test_detect_cache_invalidates_trusted_file_and_model_changes(env, change):
    detection(env, cached=False)
    if change == "frame_stat":
        env.frame.write_bytes(env.frame.read_bytes() + b"\n")
    else:
        env.model_file.write_bytes(b"REPLACED SYNTHETIC MODEL IDENTITY")
        env.detector.EXPECTED_MODEL_SHA256 = "qa-model-v2"
    env.clock.now += 2.21
    detection(env, cached=False)
    assert len(env.detect_calls) == 2


def assert_detection_rejected_without_cache(env, status, code):
    actual, headers, body = request(env, "detect")
    assert actual == status, body
    assert headers["content-type"].startswith("application/json")
    assert body["ok"] is False and body["error"]["code"] == code
    assert "detection" not in body
    assert len(env.detect_calls) == 1
    assert env.detect_cache_writes == [], "Rejected inference must never be inserted into the cache"


def assert_detection_recovers_with_cache_miss(env):
    env.on_detect = None
    env.clock.now += 2.21
    detection(env, cached=False)
    assert len(env.detect_calls) == 2
    assert len(env.detect_cache_writes) == 1
    detection(env, cached=True)
    assert len(env.detect_calls) == 2
    assert len(env.detect_cache_writes) == 1


def test_detect_during_inference_expiry_rejects_without_caching(env):
    with env.records._connect() as connection:
        original = connection.execute("SELECT expires_at FROM video_analysis_tasks WHERE task_id=?",
                                      (env.task_ids["t1"],)).fetchone()[0]
    env.on_detect = lambda: update_task(env, expires_at="2000-01-01T00:00:00+00:00")
    assert_detection_rejected_without_cache(env, 410, "media_unavailable")
    update_task(env, expires_at=original)
    assert_detection_recovers_with_cache_miss(env)


def test_detect_during_inference_frame_replacement_rejects_without_caching(env):
    other_frame = env.identity.frame_file(env.tokens["t1"], env.task_ids["t1"], "s0_f1",
                                          env.query["frame_revision"])[0]
    replacement = env.frame.with_name("r.jpg")
    assert replacement.resolve().is_relative_to(env.root.resolve())
    replacement.write_bytes(other_frame.read_bytes())
    env.on_detect = lambda: replacement.replace(env.frame)
    assert_detection_rejected_without_cache(env, 409, "frame_source_changed")
    assert_detection_recovers_with_cache_miss(env)


@pytest.mark.parametrize("field,status,code", [
    ("processing_result_json", 409, "stale_frame_revision"),
    ("account_id", 404, "task_unavailable"),
])
def test_detect_during_inference_task_change_rejects_without_caching(env, field, status, code):
    with env.records._connect() as connection:
        original = dict(connection.execute("SELECT processing_result_json, account_id FROM video_analysis_tasks "
                                           "WHERE task_id=?", (env.task_ids["t1"],)).fetchone())[field]
    changed = original + " " if field == "processing_result_json" else env.accounts["t2"]["account_id"]
    env.on_detect = lambda: update_task(env, **{field: changed})
    assert_detection_rejected_without_cache(env, status, code)
    # Restoring the exact manifest/owner reuses the old key, exposing poisoned entries.
    update_task(env, **{field: original})
    assert_detection_recovers_with_cache_miss(env)


def test_preview_jpeg_cache_is_read_only_and_expires(env, monkeypatch):
    before = business_snapshot(env)
    files = {path: path.read_bytes() for path in (env.source, env.frame)}
    calls = []
    original = env.identity.preview_source

    def checked(*args):
        calls.append(args)
        return original(*args)

    monkeypatch.setattr(env.identity, "preview_source", checked)
    first_headers, first = preview(env)
    assert len(calls) >= 2, "Preview generation must be followed by a fresh authorization check"
    count = len(calls)
    second_headers, second = preview(env)
    assert len(calls) > count, "Preview hit must reauthorize its source"
    assert first == second
    assert first_headers["x-preview-cache"] == "miss"
    assert second_headers["x-preview-cache"] == "hit"
    assert len(env.preview_calls) == 1
    env.clock.now += 60.01
    expired_headers, _ = preview(env)
    assert expired_headers["x-preview-cache"] == "miss"
    assert len(env.preview_calls) == 2
    assert business_snapshot(env) == before
    assert all(path.read_bytes() == data for path, data in files.items())
    assert env.detect_calls == [], "Preview must not trigger identity inference"


def test_preview_rechecks_expiry_after_generation(env):
    env.on_extract = lambda: update_task(env, expires_at="2000-01-01T00:00:00+00:00")
    status, headers, body = request(env, "preview")
    assert status == 410
    assert headers["content-type"].startswith("application/json")
    assert isinstance(body, dict) and body.get("ok") is False


def test_preview_cache_hit_skips_inference_but_miss_retains_limit(env):
    preview(env)
    for _ in range(3):
        headers, _ = preview(env)
        assert headers["x-preview-cache"] == "hit"
    assert len(env.preview_calls) == 1
    assert request(env, "preview", query={**env.query, "frame_key": "s0_f1"})[0] == 429
    env.clock.now += 2.21
    preview(env, query={**env.query, "frame_key": "s0_f1"})
    assert len(env.preview_calls) == 2


@pytest.mark.parametrize("code", ["timeout", "decode_failed", "unrecognized_error"])
def test_preview_error_is_sanitized_not_cached_and_slot_is_released(env, code):
    secret = "PRIVATE_EXTRACTOR_PATH_AND_TOKEN"
    env.preview_error = (code, secret)
    status, _, body = request(env, "preview")
    assert status == 422
    assert secret not in json.dumps(body)
    assert body["error"]["code"].startswith("preview_")
    assert any("\u4e00" <= character <= "\u9fff" for character in body["error"]["message"])
    env.clock.now += 2.21
    env.preview_error = None
    headers, _ = preview(env)
    assert headers["x-preview-cache"] == "miss"
    assert len(env.preview_calls) == 2


def test_admin_preview_is_read_only(env):
    before = business_snapshot(env)
    preview(env, user="admin")
    assert business_snapshot(env) == before
    assert request(env, "preview", method="POST", user="admin", query={})[0] in {403, 404, 405}


@pytest.mark.parametrize("endpoint", ["frame", "detect", "preview"])
@pytest.mark.parametrize("bad", ["missing", "extra", "path", "duplicate"])
def test_media_query_requires_exact_three_identifiers(env, endpoint, bad):
    query = dict(env.query)
    if bad == "missing":
        query.pop("frame_revision")
    elif bad == "extra":
        query["source_path"] = "not-allowed"
    elif bad == "path":
        query["frame_key"] = "../outside"
    else:
        query = [*query.items(), ("task_id", env.task_ids["t1"])]
    status, _, _ = request(env, endpoint, query=query)
    assert status == 400
    assert env.detect_calls == []
