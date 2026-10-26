"""Dossier HTTP contract: synthetic stores/files only, no live service access."""
from __future__ import annotations

import io
import json
import threading
from email.message import Message
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from src.rehab_affect import scenario_lab_server as server
from src.rehab_affect import demo2_manager_gateway as gateway
from src.rehab_affect.demo2_dossier_store import DossierError


API = "/api/v1/demo2/dossier"
GETS = {"/student?student_id=s1": "student_workspace", "/task?task_id=t1": "task_workspace",
        "/document?document_id=d1": "document_download", "/reference?reference_id=r1": "reference_export",
        "/admin": "admin_summary"}
POSTS = {
    "/authorization": ("save_authorization", "authorization", {
        "student_id": "s1", "reference": "synthetic authorization", "storage_mode": "summary_only",
        "valid_until": "2099-01-01", "confirmed": True}),
    "/authorization/withdraw": ("withdraw_authorization", "result", {
        "student_id": "s1", "authorization_id": "a1", "confirmed": True}),
    "/documents": ("create_document", "document", {
        "student_id": "s1", "authorization_id": "a1", "document_type": "iep", "document_date": "2020-01-01",
        "source_ref": "synthetic source", "retain_until": "2099-01-01",
        "summary": {key: "" for key in ("learning_goals", "support_methods", "safety_notes", "professional_conclusion")},
        "filename": "", "content_base64": "", "supersedes_id": ""}),
    "/documents/delete": ("delete_document", "result", {"student_id": "s1", "document_id": "d1", "confirmed": True}),
    "/references": ("create_reference", "reference", {
        "task_id": "t1", "student_id": "s1", "frame_revision": "v1", "document_ids": ["d1"], "confirmed": True}),
}


class Records:
    def account_from_session(self, token):
        roles = {"teacher": "school_uploader", "other": "school_uploader", "admin": "company_admin", "member": "registered_member"}
        if token not in roles:
            raise ValueError("expired or invalid session")
        return {"account_id": token, "username": token, "role": roles[token], "password_hash": "not-public"}


class Dossiers:
    def __init__(self):
        self.calls = []
        self.failure = None
        totals = ("authorization_count", "active_authorization_count", "document_count", "available_document_count",
                  "expired_document_count", "deletion_pending_count", "reference_count", "encrypted_file_bytes")
        self.summary = {"totals": dict.fromkeys(totals, 0), "channels": [{"channel_no": 1, "document_count": 0,
            "available_document_count": 0, "deletion_pending_count": 0, "encrypted_file_bytes": 0}],
            "policy": {"max_retention_days": 60, "training_allowed": False, "raw_documents_visible": False},
            "vault": {"available": True, "mode": "env_fernet"}}
        self.document = (b"synthetic document", "test.txt", "text/plain; charset=utf-8")

    def cleanup_expired(self):
        self.calls.append(("cleanup_expired",))
        if self.failure:
            raise self.failure
        return {"deleted_count": 0}

    def __getattr__(self, method):
        def call(token, *args):
            self.calls.append((method, token, *args))
            if token == "other":
                raise DossierError(404, "dossier_unavailable", "资料不存在或无权访问")
            if method == "admin_summary":
                return self.summary
            if method == "document_download":
                return self.document
            return {"repository_method": method}
        return call


@pytest.fixture()
def rig(monkeypatch, tmp_path):
    store = Dossiers()
    monkeypatch.setattr(server, "get_demo2_student_store", lambda: Records())
    monkeypatch.setattr(server, "_render_demo2_portal_page", lambda page, account: f"<html>{page}</html>")
    cls = server.create_handler(scenario_dir=tmp_path, model_path=tmp_path / "unused", policy_name="rule", dossier_store=store)

    def request(path, *, method="GET", user="teacher", payload=None, raw=None, headers=()):
        handler = cls.__new__(cls)
        handler.command, handler.path = method, path
        handler.request_version, handler.requestline = "HTTP/1.1", f"{method} {path} HTTP/1.1"
        handler.headers = Message()
        if user:
            handler.headers["Cookie"] = f"rehab_demo2_session={user}"
        body = raw if raw is not None else json.dumps(payload).encode() if payload is not None else b""
        if method == "POST":
            handler.headers["Content-Length"] = str(len(body))
            handler.headers["Content-Type"] = "application/json"
        for key, value in headers:
            # None deletes a default; repeated fields otherwise stay repeated.
            if value is None:
                del handler.headers[key]
            else:
                handler.headers[key] = value
        handler.rfile, handler.wfile = io.BytesIO(body), io.BytesIO()
        (handler.do_POST if method == "POST" else handler.do_GET)()
        header, _, content = handler.wfile.getvalue().partition(b"\r\n\r\n")
        lines = header.decode("latin-1").split("\r\n")
        response_headers = dict(line.lower().split(": ", 1) for line in lines[1:] if ": " in line)
        result = json.loads(content) if "application/json" in response_headers.get("content-type", "") else content
        return int(lines[0].split()[1]), response_headers, result

    return SimpleNamespace(store=store, request=request, cls=cls)


def private(headers):
    assert "no-store" in headers["cache-control"] and "private" in headers["cache-control"]


@pytest.mark.parametrize("route", GETS)
@pytest.mark.parametrize("user,status", [(None, 401), ("expired", 401), ("member", 403)])
def test_get_auth_first(rig, route, user, status):
    result, headers, body = rig.request(API + route, user=user)
    assert result == status and body["ok"] is False
    private(headers)
    assert rig.store.calls == []


@pytest.mark.parametrize("route", POSTS)
@pytest.mark.parametrize("user,status", [(None, 401), ("expired", 401), ("member", 403), ("admin", 403)])
def test_post_auth_before_json(rig, route, user, status):
    result, headers, _ = rig.request(API + route, method="POST", user=user, raw=b"not json")
    assert result == status
    private(headers)
    assert rig.store.calls == []


@pytest.mark.parametrize("route", GETS)
def test_get_repository_contract_and_cleanup(rig, route):
    user = "admin" if route == "/admin" else "teacher"
    status, headers, body = rig.request(API + route, user=user)
    assert status == 200
    private(headers)
    assert rig.store.calls[0] == ("cleanup_expired",)
    assert rig.store.calls[1][0:2] == (GETS[route], user)
    if route.startswith(("/document", "/reference")):
        assert headers["content-disposition"].startswith("attachment;")
    if route.startswith("/document"):
        assert body == b"synthetic document"
    elif route.startswith("/reference"):
        assert body == {"repository_method": "reference_export"}


@pytest.mark.parametrize("route", POSTS)
def test_post_repository_contract_and_cleanup(rig, route):
    method, envelope, payload = POSTS[route]
    status, headers, body = rig.request(API + route, method="POST", payload=payload)
    assert status == 200 and body == {"ok": True, envelope: {"repository_method": method}}
    private(headers)
    assert rig.store.calls == [("cleanup_expired",), (method, "teacher", payload)]


@pytest.mark.parametrize("route", [path for path in GETS if path != "/admin"])
def test_admin_has_no_teacher_data_access(rig, route):
    assert rig.request(API + route, user="admin")[0] == 403
    assert rig.store.calls == []


@pytest.mark.parametrize("route", ["/student?student_id=", "/student", "/student?student_id=s1&student_id=s2",
    "/student?student_id=s1&path=a", "/student?student_id=..%2Fa", "/task?task_id=t1&", "/admin?extra=x"])
def test_exact_queries(rig, route):
    assert rig.request(API + route, user="admin" if route.startswith("/admin") else "teacher")[0] == 400
    assert rig.store.calls == []


@pytest.mark.parametrize("route", [r for r in POSTS if r != "/documents"])
@pytest.mark.parametrize("value", [False, None, "true", 1])
def test_literal_confirmation_required(rig, route, value):
    payload = {**POSTS[route][2], "confirmed": value}
    status, _, body = rig.request(API + route, method="POST", payload=payload)
    assert status == 400 and body["error"]["code"] == "confirmation_required"
    assert rig.store.calls == []


@pytest.mark.parametrize("raw", [b'[]', b'{}{}', b'{"x":NaN}', b'{"confirmed":true,"confirmed":false}',
    b'{"summary":{"x":1,"x":2}}', b'\xff', b'', b'[' * 1500])
def test_malformed_and_duplicate_json(rig, raw):
    assert rig.request(API + "/authorization", method="POST", raw=raw)[0] == 400
    assert rig.store.calls == []


@pytest.mark.parametrize("headers,status", [
    ([("Content-Type", None), ("Content-Type", "text/plain")], 415),
    ([("Content-Type", "application/json")], 415),
    ([("Content-Encoding", "gzip")], 415),
    ([("Content-Length", "0")], 400), ([("Content-Length", None)], 400),
    ([("Transfer-Encoding", "chunked")], 400), ([("Expect", "100-continue")], 400),
    ([("Content-Length", None), ("Content-Length", str(12 * 1024 * 1024 + 1))], 413),
    ([("Content-Length", None), ("Content-Length", "100")], 400),
])
def test_body_framing_and_limits(rig, headers, status):
    result, outgoing, _ = rig.request(API + "/authorization", method="POST", raw=b"{}", headers=headers)
    assert result == status
    private(outgoing)
    assert rig.store.calls == []


def test_errors_are_safe_and_cleanup_failures_block_operations(rig):
    rig.store.failure = RuntimeError("D:/secret/key and confidential source")
    status, headers, body = rig.request(API + "/student?student_id=s1")
    assert status == 503 and body["error"]["code"] == "dossier_unavailable"
    private(headers)
    assert "secret" not in json.dumps(body)
    assert rig.store.calls == [("cleanup_expired",)]


def test_admin_summary_is_strict_projection(rig):
    rig.store.summary.update(student_name="private-student", source_ref="private-source")
    rig.store.summary["channels"][0]["filename"] = "private-file"
    rig.store.summary["vault"]["location"] = "D:/private/key"
    status, _, body = rig.request(API + "/admin", user="admin")
    assert status == 200 and "private" not in json.dumps(body)
    assert set(body["summary"]) == {"totals", "channels", "policy", "vault"}


@pytest.mark.parametrize("document", [(b"data", "../private.txt", "text/plain"),
    (b"data", "ok.txt", "text/html"), ("D:/secret/file", "ok.txt", "text/plain"),
    (b"data", "bad\r\n.txt", "text/plain"), (b"", "ok.txt", "text/plain")])
def test_downloads_never_accept_paths_or_unsafe_headers(rig, document):
    rig.store.document = document
    status, _, body = rig.request(API + "/document?document_id=d1")
    assert status == 503 and "secret" not in json.dumps(body)


@pytest.mark.parametrize("path,owner,page,method", [
    ("/demo2/dossier?student_id=s1", "teacher", "dossier", "student_workspace"),
    ("/demo2/course-dossier?task_id=t1", "teacher", "course-dossier", "task_workspace"),
    ("/demo2/admin/dossiers", "admin", "admin-dossiers", "cleanup_expired"),
])
def test_page_contract(rig, path, owner, page, method):
    status, headers, _ = rig.request(path, user=None)
    assert status == 302 and headers["location"] == "/demo2/login"
    private(headers)
    wrong = "teacher" if owner == "admin" else "admin"
    assert rig.request(path, user=wrong)[0] == 403
    assert rig.store.calls == []
    status, headers, html = rig.request(path, user=owner)
    assert status == 200 and html == f"<html>{page}</html>".encode()
    private(headers)
    assert any(call[0] == method for call in rig.store.calls)


def test_cross_owner_page_fails_before_render(rig):
    assert rig.request("/demo2/dossier?student_id=s1", user="other")[0] == 404


def test_legacy_notice_has_mobile_and_keyboard_support():
    html = server._legacy_dossier_notice()
    assert 'name="viewport"' in html and "Microsoft YaHei" in html
    assert "focus-visible" in html and "min-height:44px" in html
    assert "@media(max-width:520px)" in html and "760px" in html
    assert "旧源码与数据完整保留" in html and "暂不在线开放" in html
    assert "旧资料未迁移" in html and "仅凭姓名不能关联" in html
    assert "https://" not in html and "<script" not in html


@pytest.mark.parametrize("path", sorted(server.DEMO2_LEGACY_PRIVATE_PATHS) + [
    "/api/seewo_student_demo", "/api/seewo_student_demo2", "/assets/seewo_demo2/a.jpg", "/assets/seewo_xiaoyudi_demo/a.jpg"])
def test_legacy_data_fails_closed_without_loading_global_store(rig, monkeypatch, path):
    def never(*args, **kwargs):
        pytest.fail("must never read legacy global cases")
    monkeypatch.setattr(server, "load_seewo_demo2", never)
    monkeypatch.setattr(server, "load_seewo_student_demo", never)
    for user in ("teacher", "admin"):
        for method in ("GET", "POST"):
            status, headers, body = rig.request(path, user=user, method=method, payload={})
            assert status == 410 and body["error"]["code"] == "legacy_data_reimport_required"
            private(headers)
    assert rig.request(path, user=None)[0] == 401


def test_gateway_exact_private_dossier_allowlist():
    for route in GETS:
        path = API + route.split("?", 1)[0]
        assert gateway._allowed("GET", path) and path not in gateway._PUBLIC_UPSTREAM
        assert not gateway._allowed("GET", path + "/extra")
    for route in POSTS:
        assert gateway._allowed("POST", API + route) and API + route not in gateway._PUBLIC_UPSTREAM
    for path in ("/demo2/dossier", "/demo2/course-dossier", "/demo2/admin/dossiers"):
        assert gateway._allowed("GET", path) and path not in gateway._PUBLIC_UPSTREAM
    for path in server.DEMO2_LEGACY_PRIVATE_PATHS | {"/assets/seewo_demo2/a.jpg"}:
        assert not gateway._allowed("GET", path) and not gateway._allowed("POST", path)
    assert gateway._allowed("POST", "/api/seewo_demo2/video_chunk")
    assert gateway._allowed("GET", "/api/v1/demo2/upload/result")


def test_periodic_cleanup_retries_and_stops_cleanly(capsys):
    calls, reached = [], threading.Event()
    def sweep():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("private-sensitive-path")
        reached.set()
    worker = server._DossierMaintenance(sweep, interval=.01)
    try:
        worker.start()
        assert reached.wait(2)
    finally:
        worker.stop()
    assert len(calls) >= 2 and not worker.thread.is_alive()
    assert "private-sensitive-path" not in capsys.readouterr().err


def test_periodic_cleanup_is_available_on_handler(rig):
    assert rig.cls.cleanup_expired_dossiers() == {"deleted_count": 0}
    assert rig.store.calls == [("cleanup_expired",)]


@pytest.mark.parametrize("authenticated,expected", [(False, 401), (True, 413)])
def test_gateway_dossier_body_limit_precedes_read(monkeypatch, authenticated, expected):
    handler = gateway._GatewayHandler.__new__(gateway._GatewayHandler)
    handler.command, handler.requestline = "POST", f"POST {API}/documents HTTP/1.1"
    handler.headers = Message()
    handler.headers["Host"] = "example.test"
    handler.headers["Origin"] = "https://example.test"
    handler.headers["Content-Length"] = str(12 * 1024 * 1024 + 1)
    handler.client_address = ("127.0.0.1", 1)
    handler.server = SimpleNamespace(failures=SimpleNamespace(blocked=lambda *_: False))
    monkeypatch.setattr(handler, "_expired", lambda: False)
    monkeypatch.setattr(handler, "_cookies", lambda: {gateway.SESSION_COOKIE_NAME: "test-only"})
    monkeypatch.setattr(handler, "_invited", lambda *_: True)
    monkeypatch.setattr(handler, "_authenticated", lambda *_: authenticated)
    errors = []
    monkeypatch.setattr(handler, "_error", lambda status, code, message: errors.append((status, code)))
    monkeypatch.setattr(handler, "_read_body", lambda *_: pytest.fail("must reject before body read"))
    handler._dispatch()
    assert errors == [(expected, "body_too_large" if authenticated else "authentication_required")]


@pytest.mark.parametrize("failure", [None, "retention", "dossier", "worker"])
def test_server_dossier_maintenance_lifecycle(monkeypatch, failure):
    from src.rehab_affect import demo2_media_worker
    events = []
    def start(name):
        events.append(name + "_start")
        if failure == name:
            raise RuntimeError("synthetic startup failure")
    class Retention:
        ident = None
        def __init__(self, **_):
            pass
        def start(self):
            start("retention")
            self.ident = 1
        def join(self, **_):
            events.append("retention_join")
    class Maintenance:
        def __init__(self, cleanup):
            assert cleanup is sentinel
        def start(self):
            start("dossier")
        def stop(self):
            events.append("dossier_stop")
    class Worker:
        def __init__(self, *_):
            pass
        def start(self):
            start("worker")
        def stop(self):
            events.append("worker_stop")
    class Server:
        def __init__(self, *_):
            pass
        def serve_forever(self):
            events.append("serve")
        def server_close(self):
            events.append("close")
    def sentinel():
        pytest.fail("fake lifecycle must not touch a real store")
    monkeypatch.setattr(server, "create_handler", lambda **_: SimpleNamespace(cleanup_expired_dossiers=sentinel))
    monkeypatch.setattr(server, "get_demo2_student_store", lambda: object())
    monkeypatch.setattr(server, "Thread", Retention)
    monkeypatch.setattr(server, "_DossierMaintenance", Maintenance)
    monkeypatch.setattr(server, "ThreadingHTTPServer", Server)
    monkeypatch.setattr(demo2_media_worker, "VideoAnalysisWorker", Worker)
    monkeypatch.setenv("REHAB_DEMO2_MEDIA_WORKER", "1")
    if failure:
        with pytest.raises(RuntimeError, match="synthetic startup failure"):
            server.run_server(port=0)
        assert "serve" not in events
    else:
        server.run_server(port=0)
        assert events[:4] == ["retention_start", "dossier_start", "worker_start", "serve"]
    assert "worker_stop" in events and "dossier_stop" in events and events[-1] == "close"


def test_real_sqlite_api_lifecycle(tmp_path):
    from scripts.qa_demo2_dossier_20260911 import (
        isolated_dossier_server, http, authorization_payload, document_payload, FAKE_TEXT,
    )
    with isolated_dossier_server(tmp_path) as env:
        sid = env.students["a"]["student_id"]
        def call(method, route, payload=None, **options):
            status, headers, body = http(env, method, API + route, payload, **options)
            private(headers)
            return status, body
        status, body = call("POST", "/authorization", authorization_payload(env))
        assert status == 200
        auth = body["authorization"]
        status, body = call("POST", "/documents", document_payload(env, auth))
        assert status == 200
        document = body["document"]
        did = document["document_id"]
        assert call("GET", f"/document?document_id={did}")[1] == FAKE_TEXT + b" V1"
        assert call("GET", f"/document?document_id={did}", user="admin")[0] == 403
        assert call("GET", f"/document?document_id={did}", user="t2")[0] == 403
        env.bind()
        reference_payload = {"task_id": env.task_ids["t1"], "student_id": sid,
            "frame_revision": env.binding_payload["frame_revision"], "document_ids": [did], "confirmed": True}
        status, body = call("POST", "/references", reference_payload)
        assert status == 200
        rid = body["reference"]["reference_id"]
        assert call("GET", f"/reference?reference_id={rid}")[0] == 200
        assert call("GET", f"/task?task_id={env.task_ids['t1']}")[0] == 200
        status, summary = call("GET", "/admin", user="admin")
        assert status == 200 and summary["summary"]["totals"]["document_count"] == 1
        assert "FICTIONAL" not in json.dumps(summary)
        assert call("POST", "/authorization/withdraw", {
            "student_id": sid, "authorization_id": auth["authorization_id"], "confirmed": True})[0] == 200
        assert call("GET", f"/document?document_id={did}")[0] == 410
        assert call("GET", f"/reference?reference_id={rid}")[0] == 200
        assert call("GET", f"/student?student_id={sid}")[0] == 200
