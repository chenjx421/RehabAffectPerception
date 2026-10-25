from __future__ import annotations

import base64
import http.client
import io
import json
import sqlite3
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse

import pytest

from src.rehab_affect import scenario_lab_server as server_module
from src.rehab_affect.student_record_store import Demo2StudentRecordStore


class FakePortalStore:
    def __init__(self, result_dir: Path) -> None:
        self.accounts = {
            "uploader_a": {
                "account_id": "account_a",
                "username": "uploader_a",
                "display_name": "学校上传员甲",
                "role": "school_uploader",
                "bound_channel_id": "channel_1",
                "password_hash": "must-not-leak",
            },
            "uploader_b": {
                "account_id": "account_b",
                "username": "uploader_b",
                "display_name": "学校上传员乙",
                "role": "school_uploader",
                "bound_channel_id": "channel_2",
            },
            "admin": {
                "account_id": "account_admin",
                "username": "admin",
                "display_name": "公司管理员",
                "role": "company_admin",
            },
        }
        self.passwords = {"uploader_a": "pass-a", "uploader_b": "pass-b", "admin": "admin-pass"}
        self.sessions: dict[str, str] = {}
        self.tasks: dict[str, dict[str, Any]] = {}
        self.last_created_payload: dict[str, Any] = {}
        self.last_chunk_actor = ""
        self.last_cancel_actor = ""
        self.result_dir = result_dir
        self.security_acceptances: list[dict[str, Any]] = []
        self.call_order: list[str] = []
        self.fail_acceptance = False
        self.quota_full = False
        self.raise_quota_on_create = False

    def authenticate_account(self, username: str, password: str) -> dict[str, Any]:
        if self.passwords.get(username) != password:
            raise ValueError("bad credentials")
        return dict(self.accounts[username])

    def create_account_session(self, account_id: str) -> str:
        token = f"token-{account_id}"
        self.sessions[token] = account_id
        return token

    def account_from_session(self, token: str) -> dict[str, Any] | None:
        account_id = self.sessions.get(token)
        return next(
            (dict(account) for account in self.accounts.values() if account["account_id"] == account_id),
            None,
        )

    def revoke_account_session(self, token: str) -> None:
        self.sessions.pop(token, None)

    def account_school_context(self, token: str) -> dict[str, Any]:
        account = self.account_from_session(token)
        assert account is not None
        return {"context": {"city": "Test City", "district": "Test District",
                            "school_name": "Test School " + account["account_id"]}}

    def account_upload_workspace(self, token: str, course_id: str) -> dict[str, Any]:
        account = self.account_from_session(token)
        assert account is not None
        account_id = account["account_id"]
        tasks = [task for task in self.tasks.values() if task["account_id"] == account_id]
        remaining_slots = 0 if self.quota_full else max(0, 4 - len(tasks))
        return {
            "course_id": course_id,
            "upload_channel": {"channel_id": account.get("bound_channel_id", "")},
            "tasks": tasks,
            "quota": {"used_slots": len(tasks), "max_slots": 4, "remaining_slots": remaining_slots},
        }

    def admin_platform_summary(self, token: str, *, upload_page: int = 1) -> dict[str, Any]:
        account = self.account_from_session(token)
        assert account is not None
        if upload_page != 1:
            return {"requested_by": account["account_id"], "page": upload_page}
        return {"requested_by": account["account_id"], "account_count": len(self.accounts)}

    def record_security_acceptance(self, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        self.call_order.append("acceptance")
        if self.fail_acceptance:
            raise ValueError("security acceptance failed")
        acceptance = {**payload, "actor": actor, "acceptance_id": f"acceptance-{len(self.security_acceptances) + 1}"}
        self.security_acceptances.append(acceptance)
        return dict(acceptance)

    def create_video_task(self, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        self.call_order.append("create")
        if self.raise_quota_on_create:
            raise ValueError("该课程上传名额已满（最多 4 段）")
        self.last_created_payload = dict(payload)
        task = {**payload, "task_id": f"task-{len(self.tasks) + 1}", "created_by": actor}
        self.tasks[task["task_id"]] = task
        return dict(task)

    def append_video_chunk(self, payload: dict[str, Any], *, actor: str) -> dict[str, Any]:
        self.last_chunk_actor = actor
        return {**self.tasks[payload["task_id"]], "upload_status": "uploading", "next_chunk_index": 1}

    def cancel_video_task(self, token: str, task_id: str) -> dict[str, Any]:
        account = self.account_from_session(token)
        assert account is not None
        task = self.tasks.get(task_id)
        if task is None:
            raise ValueError("未找到视频任务")
        if task["account_id"] != account["account_id"]:
            raise ValueError("无权取消其他账号的视频任务")
        self.last_cancel_actor = account["account_id"]
        task.update({"upload_status": "cancelled", "analysis_status": "cancelled"})
        return dict(task)

    def account_video_result_for_download(self, token: str, task_id: str) -> tuple[Path, str]:
        account = self.account_from_session(token)
        assert account is not None
        task = self.tasks.get(task_id)
        if task is None:
            raise ValueError("未找到视频任务")
        if account["role"] != "company_admin" and task["account_id"] != account["account_id"]:
            raise ValueError("无权下载其他账号的视频结果")
        if not task.get("result_ready"):
            raise ValueError("该任务尚无可下载结果")
        path = self.result_dir / f"{task_id}.json"
        path.write_text(json.dumps({"task_id": task_id}), encoding="utf-8")
        return path, f"{task_id}.json"

    def ensure_students(self, _students: list[dict[str, Any]]) -> None:
        return None

    def storage_summary(self) -> dict[str, Any]:
        return {
            "database": {"engine": "SQLite 3", "location": "D:/private/demo.sqlite3"},
            "document_storage": {"location": "D:/private/documents", "byte_size": 12},
            "recent_documents": [
                {
                    "document_id": "doc-1",
                    "file_path": "D:/private/documents/doc-1.pdf",
                    "result_path": "D:/private/results/doc-1.json",
                    "download_url": "/safe-download",
                }
            ],
            "nested": {"report_path": "D:/private/report.json", "status": "ready"},
        }


@pytest.fixture()
def portal_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    store = FakePortalStore(tmp_path)
    public_asset_dir = tmp_path / "seewo_demo2_assets"
    (public_asset_dir / "course-1").mkdir(parents=True)
    (public_asset_dir / "course-1" / "group_reference.jpg").write_bytes(b"jpeg")
    monkeypatch.setattr(server_module, "get_demo2_student_store", lambda: store)
    monkeypatch.setattr(server_module, "SEEWO_DEMO2_OUTPUT_DIR", public_asset_dir)
    monkeypatch.setattr(
        server_module,
        "_render_demo2_portal_page",
        lambda page, account=None: f"<html>{page}:{(account or {}).get('account_id', '')}</html>",
    )
    monkeypatch.setattr(server_module, "render_seewo_demo2_html", lambda: "<html>analysis</html>")
    monkeypatch.setattr(
        server_module,
        "load_seewo_demo2",
        lambda force=False: {"students": [], "legacy_demo2": True, "force": force},
    )
    handler = server_module.create_handler(
        scenario_dir=tmp_path,
        model_path=tmp_path / "unused.json",
        policy_name="rule",
    )
    httpd = server_module.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_port, store
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


def _request(
    port: int,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    cookie: str = "",
) -> tuple[int, dict[str, str], Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        response_headers = {key.lower(): value for key, value in response.getheaders()}
        content_type = response_headers.get("content-type", "")
        parsed = json.loads(raw.decode("utf-8")) if "application/json" in content_type else raw.decode("utf-8")
        return response.status, response_headers, parsed
    finally:
        connection.close()


def _login(port: int, username: str, password: str) -> str:
    status, headers, _ = _request(
        port,
        "POST",
        "/api/v1/demo2/auth/login",
        {"username": username, "password": password},
    )
    assert status == 200
    return headers["set-cookie"].split(";", 1)[0]


def test_login_me_logout_and_cookie_contract(portal_server) -> None:
    port, store = portal_server
    status, _, body = _request(
        port,
        "POST",
        "/api/v1/demo2/auth/login",
        {"username": "uploader_a", "password": "wrong"},
    )
    assert status == 401
    assert body["error"]["code"] == "invalid_credentials"

    status, headers, body = _request(
        port,
        "POST",
        "/api/v1/demo2/auth/login",
        {"username": "uploader_a", "password": "pass-a"},
    )
    assert status == 200
    assert "password_hash" not in body["account"]
    set_cookie = headers["set-cookie"]
    for attribute in ("HttpOnly", "SameSite=Lax", "Path=/", "Max-Age=28800"):
        assert attribute in set_cookie
    cookie = set_cookie.split(";", 1)[0]

    status, _, body = _request(port, "GET", "/api/v1/demo2/auth/me", cookie=cookie)
    assert status == 200
    assert body["account"]["account_id"] == "account_a"

    status, headers, body = _request(port, "POST", "/api/v1/demo2/auth/logout", cookie=cookie)
    assert status == 200 and body["ok"] is True
    assert "Max-Age=0" in headers["set-cookie"]
    assert store.sessions == {}
    status, _, body = _request(port, "GET", "/api/v1/demo2/auth/me", cookie=cookie)
    assert status == 401
    assert body["error"]["code"] == "authentication_required"


@pytest.mark.parametrize("username,password,role,next_url", [
    ("uploader_a", "pass-a", "school_uploader", "/demo2/school"),
    ("admin", "admin-pass", "company_admin", "/demo2/admin"),
])
def test_login_optional_role_rejects_mismatch_before_session_creation(
    portal_server, username, password, role, next_url
) -> None:
    port, store = portal_server
    credentials = {"username": username, "password": password}
    for invalid_role in ("admin", "", None, [], {}):
        status, headers, body = _request(port, "POST", "/api/v1/demo2/auth/login",
                                         {**credentials, "role": invalid_role})
        assert status == 400 and body["error"]["code"] == "invalid_request"
        assert body["error"]["message"] == "请选择用户登录或管理员登录"
        assert "set-cookie" not in headers and store.sessions == {}
    wrong_role = "company_admin" if role == "school_uploader" else "school_uploader"
    status, headers, body = _request(port, "POST", "/api/v1/demo2/auth/login",
                                     {**credentials, "role": wrong_role})
    assert status == 403 and body["error"]["code"] == "role_mismatch"
    assert body["error"]["message"] == "账号与所选登录身份不匹配"
    assert "set-cookie" not in headers and store.sessions == {}
    status, headers, body = _request(port, "POST", "/api/v1/demo2/auth/login",
                                     {**credentials, "role": role})
    assert status == 200 and body["next_url"] == next_url
    assert "set-cookie" in headers and headers["cache-control"] == "no-store"
    assert password not in json.dumps(body) and "must-not-leak" not in json.dumps(body)


def test_entry_page_roles_and_public_privacy_register(portal_server) -> None:
    port, _ = portal_server
    for page in ("register", "privacy"):
        status, _, body = _request(port, "GET", f"/demo2/{page}")
        assert status == 200 and page in body
    status, headers, _ = _request(port, "GET", "/demo2/school")
    assert status == 302 and headers["location"] == "/demo2/login"
    uploader_cookie = _login(port, "uploader_a", "pass-a")
    status, _, body = _request(port, "GET", "/demo2/school", cookie=uploader_cookie)
    assert status == 200 and "school:account_a" in body
    admin_cookie = _login(port, "admin", "admin-pass")
    status, _, _ = _request(port, "GET", "/demo2/school", cookie=admin_cookie)
    assert status == 403


def test_entry_renderer_dispatch_uses_agreed_portal_wrappers(monkeypatch) -> None:
    portal = SimpleNamespace(
        render_demo2_register_html=lambda: "register",
        render_demo2_privacy_html=lambda: "privacy",
        render_demo2_school_html=lambda account: account["account_id"],
    )
    monkeypatch.setattr(server_module.importlib, "import_module", lambda *args, **kwargs: portal)
    assert server_module._render_demo2_portal_page("register") == "register"
    assert server_module._render_demo2_portal_page("privacy") == "privacy"
    assert server_module._render_demo2_portal_page("school", {"account_id": "test-account"}) == "test-account"


@pytest.fixture()
def onboarding_server(monkeypatch, tmp_path):
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "onboarding-test-")
    store = Demo2StudentRecordStore(tmp_path / "onboarding.sqlite3", tmp_path / "documents")
    monkeypatch.setattr(server_module, "get_demo2_student_store", lambda: store)
    monkeypatch.setattr(server_module, "load_seewo_demo2", lambda force=False: {"students": []})
    handler = server_module.create_handler(scenario_dir=tmp_path, model_path=tmp_path / "unused.json", policy_name="rule")
    httpd = server_module.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_port, store
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


def test_real_login_alias_school_context_and_summary_contract(onboarding_server) -> None:
    port, store = onboarding_server
    endpoint = "/api/v1/demo2/school/context"
    context = {"city": "Test City", "district": "Test District", "school_name": "Test School"}
    for path in ("/demo2/register", "/demo2/privacy"):
        status, _, page = _request(port, "GET", path)
        assert status == 200 and "<html" in page
    for method in ("GET", "POST"):
        status, _, _ = _request(port, method, endpoint, context if method == "POST" else None)
        assert status == 401
    status, headers, body = _request(port, "POST", "/api/v1/demo2/auth/login", {
        "username": "t1", "password": "onboarding-test-school_uploader_01", "role": "school_uploader",
    })
    assert status == 200 and body["account"]["login_alias"] == "t1"
    assert body["account"]["username"] == "school_uploader_01" and body["next_url"] == "/demo2/school"
    cookie = headers["set-cookie"].split(";", 1)[0]
    status, _, page = _request(port, "GET", "/demo2/school", cookie=cookie)
    assert status == 200 and "schoolForm" in page
    status, _, body = _request(port, "GET", endpoint, cookie=cookie)
    assert status == 200 and body['ok'] and body['context'] == {key: "" for key in context} and body['options'] == []
    assert body['selection_enabled'] and body['directory']['coverage']['complete'] is False
    status, _, body = _request(port, "POST", endpoint, context, cookie=cookie)
    assert status == 200 and body['ok'] and body['context'] == context and body['options'] == [context]
    assert body['details']['source_status'] == 'pending'
    status, _, body = _request(port, "GET", endpoint, cookie=cookie)
    assert status == 200 and body["context"] == context
    for invalid in ({**context, "account_id": "someone-else"}, {**context, "city": ""}, {**context, "school_name": "x" * 201}):
        status, _, _ = _request(port, "POST", endpoint, invalid, cookie=cookie)
        assert status == 400
    other_cookie = _login(port, "t2", "onboarding-test-school_uploader_02")
    status, _, body = _request(port, "GET", endpoint, cookie=other_cookie)
    assert status == 200 and body["options"] == []
    status, _, _ = _request(port, "GET", "/api/v1/demo2/admin/summary", cookie=cookie)
    assert status == 403
    admin_cookie = _login(port, "admin", "onboarding-test-company_admin")
    for method in ("GET", "POST"):
        status, _, _ = _request(port, method, endpoint, context if method == "POST" else None, cookie=admin_cookie)
        assert status == 403
    status, _, body = _request(port, "GET", "/api/v1/demo2/admin/summary", cookie=admin_cookie)
    assert status == 200 and body["summary"]["registration_requests"] == []
    assert len(body["summary"]["school_contexts"]) == 1
    assert body["summary"]["school_contexts"][0]["school_name"] == context["school_name"]
    status, _, body = _request(port, "POST", "/api/v1/demo2/upload/tasks", {
        "channel_id": "channel_1", "course_id": "test-course", "course_name": "Test Course",
        "uploader_name": "Test Uploader", "session_id": "test-session", "filename": "test.mp4",
        "byte_size": 1, "total_chunks": 1, "security_confirmed": True,
        "school_context": {"school_name": "Forged"},
    }, cookie=cookie)
    assert status == 200 and body["task"]["school_context"] == context


def _registration_payload():
    return {"phone": "13800000000", "code": "123456", "password": "OnboardingPass123",
            "agreement_version": "2026-09-09", "accepted": True}


def test_registration_without_sms_returns_503_without_account_or_application(onboarding_server) -> None:
    port, store = onboarding_server
    payload = _registration_payload()
    status, headers, body = _request(port, "POST", "/api/v1/demo2/auth/register", payload)
    assert status == 503 and body["ok"] is False
    assert body["error"]["code"] == "sms_not_configured"
    assert "request" not in body and "account" not in body
    assert "set-cookie" not in headers and headers["cache-control"] == "no-store"
    with sqlite3.connect(store.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM platform_accounts").fetchone()[0] == 5
        assert connection.execute("SELECT COUNT(*) FROM account_sessions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM school_contexts").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM data_security_acceptances").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM registration_requests").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM demo2_memberships").fetchone()[0] == 0
    status, _, _ = _request(port, "GET", "/api/v1/demo2/auth/register")
    assert status == 401
    cookie = _login(port, "admin", "onboarding-test-company_admin")
    status, _, summary = _request(port, "GET", "/api/v1/demo2/admin/summary", cookie=cookie)
    assert status == 200
    assert summary["summary"]["registration_requests"] == []
    status, _, summary = _request(port, "GET", "/api/v1/demo2/admin/memberships", cookie=cookie)
    assert status == 200 and summary["summary"]["members"] == [] and summary["summary"]["orders"] == []


def test_registration_validation_and_body_bounds_before_sms_provider(onboarding_server) -> None:
    port, store = onboarding_server
    payload = _registration_payload()
    for invalid, expected_code in (
        ({**payload, "accepted": 1}, "agreement_required"),
        ({**payload, "role": "company_admin"}, "invalid_request"),
        ({**payload, "agreement_version": "old"}, "agreement_required"),
        ({**payload, "password": "x" * 9000}, "invalid_request"), ([], "invalid_request"),
    ):
        status, headers, body = _request(port, "POST", "/api/v1/demo2/auth/register", invalid)
        assert status == 400 and body["error"]["code"] == expected_code
        assert "set-cookie" not in headers
    status, headers, body = _request(port, "POST", "/api/v1/demo2/auth/register", payload)
    assert status == 503 and body["error"]["code"] == "sms_not_configured"
    with sqlite3.connect(store.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM registration_requests").fetchone()[0] == 0


def test_registration_phone_and_malformed_json_return_chinese_errors(onboarding_server) -> None:
    port, _ = onboarding_server
    endpoint = "/api/v1/demo2/auth/register"
    status, _, body = _request(port, "POST", "/api/v1/demo2/auth/sms-code", {"phone": "not-a-phone"})
    assert status == 400 and body["error"]["code"] == "invalid_phone"
    assert "手机" in body["error"]["message"]
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("POST", endpoint, body=b"{broken-json", headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        body = json.loads(response.read().decode("utf-8"))
        assert response.status == 400 and body["error"]["message"] == "请求内容格式无效，请刷新后重试"
    finally:
        connection.close()
    status, headers, body = _request(port, "POST", "/api/v1/demo2/auth/sms-code", {"phone": "13800000000"})
    assert status == 503 and body["error"]["code"] == "sms_not_configured"
    assert "set-cookie" not in headers


@pytest.fixture()
def response_handler(monkeypatch, tmp_path):
    store = FakePortalStore(tmp_path)
    token = store.create_account_session("account_admin")
    monkeypatch.setattr(server_module, "get_demo2_student_store", lambda: store)
    handler_type = server_module.create_handler(scenario_dir=tmp_path, model_path=tmp_path / "unused.json", policy_name="rule")
    handler = handler_type.__new__(handler_type)
    handler.headers = {"Cookie": f"rehab_demo2_session={token}"}
    handler.request_version = "HTTP/1.1"
    handler.command = "GET"
    handler.path = "/api/v1/demo2/admin/summary"
    handler.requestline = f"GET {handler.path} HTTP/1.1"
    handler.close_connection = False
    handler.wfile = io.BytesIO()
    statuses = []
    send_response = handler.send_response

    def record_response(code, message=None):
        statuses.append(code)
        send_response(code, message)

    monkeypatch.setattr(handler, "send_response", record_response)
    return handler, store, statuses


@pytest.mark.parametrize("error_type", [ConnectionAbortedError, ConnectionResetError, BrokenPipeError])
@pytest.mark.parametrize("failed_write", [1, 2])
def test_disconnected_summary_response_never_attempts_fallback_500(response_handler, error_type, failed_write) -> None:
    handler, _, statuses = response_handler

    class DisconnectedWriter:
        calls = 0

        def write(self, data):
            self.calls += 1
            if self.calls == failed_write:
                raise error_type(10053, "simulated disconnected peer")
            return len(data)

    handler.wfile = DisconnectedWriter()
    handler._handle_demo2_api_get(urlparse(handler.path))
    assert statuses == [200]
    assert handler._peer_disconnected is True and handler.close_connection is True
    handler._write_response(b"must not retry")
    handler.send_error(500)
    assert handler.wfile.calls == failed_write
    assert statuses == [200]


def test_backend_connection_error_is_not_mistaken_for_peer_disconnect(response_handler, monkeypatch) -> None:
    handler, store, statuses = response_handler

    def failing_summary(token):
        raise ConnectionAbortedError("simulated upstream service failure")

    monkeypatch.setattr(store, "admin_platform_summary", failing_summary)
    handler._handle_demo2_api_get(urlparse(handler.path))
    assert statuses == [500]
    assert handler._peer_disconnected is False
    assert b'"internal_error"' in handler.wfile.getvalue()


def test_response_writer_does_not_swallow_unrelated_io_errors(response_handler) -> None:
    handler, _, _ = response_handler

    class FailingWriter:
        def write(self, data):
            raise OSError(5, "simulated unrelated I/O failure")

    handler.wfile = FailingWriter()
    with pytest.raises(OSError, match="unrelated I/O"):
        handler._write_response(b"response")
    handler._headers_buffer = [b"headers"]
    with pytest.raises(OSError, match="unrelated I/O"):
        handler.flush_headers()
    assert handler._peer_disconnected is False


def test_inherited_error_response_handles_disconnected_body(response_handler) -> None:
    handler, _, statuses = response_handler

    class DisconnectedWriter:
        calls = 0

        def write(self, data):
            self.calls += 1
            if self.calls == 2:
                raise ConnectionAbortedError(10053, "simulated disconnected peer")
            return len(data)

    handler.wfile = DisconnectedWriter()
    handler.send_error(404)
    assert statuses == [404]
    assert handler.close_connection is True and handler._peer_disconnected is True


def test_request_flush_disconnect_closes_connection(response_handler, monkeypatch) -> None:
    handler, _, statuses = response_handler

    def disconnected_request(self):
        raise ConnectionResetError("simulated final flush failure")

    monkeypatch.setattr(server_module.BaseHTTPRequestHandler, "handle_one_request", disconnected_request)
    handler.handle_one_request()
    assert handler.close_connection is True and handler._peer_disconnected is True
    assert statuses == []


def test_repeated_school_and_admin_http_requests_release_sqlite_handles(onboarding_server, monkeypatch) -> None:
    port, store = onboarding_server
    connect = sqlite3.connect
    connections = []

    class TrackedConnection(sqlite3.Connection):
        closed_for_test = False

        def close(self):
            super().close()
            self.closed_for_test = True

    def tracked_connect(*args, **kwargs):
        connection = connect(*args, **kwargs, factory=TrackedConnection)
        connections.append(connection)
        return connection

    monkeypatch.setattr(sqlite3, "connect", tracked_connect)
    school_cookie = _login(port, "t1", "onboarding-test-school_uploader_01")
    admin_cookie = _login(port, "admin", "onboarding-test-company_admin")
    context = {"city": "Test City", "district": "Test District", "school_name": "Test School"}
    for _ in range(3):
        assert _request(port, "POST", "/api/v1/demo2/school/context", context, cookie=school_cookie)[0] == 200
        assert _request(port, "GET", "/api/v1/demo2/school/context", cookie=school_cookie)[0] == 200
        assert _request(port, "GET", "/api/v1/demo2/admin/summary", cookie=admin_cookie)[0] == 200
    assert len(connections) > 20
    assert all(connection.closed_for_test for connection in connections)
    store.db_path.unlink()
    assert not store.db_path.exists()


def test_portal_pages_redirect_and_enforce_roles(portal_server) -> None:
    port, _ = portal_server
    status, headers, _ = _request(port, "GET", "/demo2/upload")
    assert status == 302
    assert headers["location"] == "/demo2/login"
    status, _, body = _request(port, "GET", "/demo2/login")
    assert status == 200 and "login" in body

    uploader_cookie = _login(port, "uploader_a", "pass-a")
    assert _request(port, "GET", "/demo2/upload", cookie=uploader_cookie)[0] == 200
    assert _request(port, "GET", "/demo2/admin", cookie=uploader_cookie)[0] == 403
    assert _request(port, "GET", "/demo2/analysis", cookie=uploader_cookie)[0] == 200

    admin_cookie = _login(port, "admin", "admin-pass")
    assert _request(port, "GET", "/demo2/admin", cookie=admin_cookie)[0] == 200
    assert _request(port, "GET", "/demo2/upload", cookie=admin_cookie)[0] == 403
    # An administrator may open the legacy route only to receive a safe
    # task-selection guide; it must not read an unscoped classroom task.
    status, _, body = _request(port, "GET", "/demo2/analysis", cookie=admin_cookie)
    assert status == 200
    assert "请选择课堂任务" in body


@pytest.mark.parametrize("confirmed_by", ["uploader_a", "uploader_b"])
def test_workspace_omits_unscoped_acceptance(response_handler, monkeypatch, confirmed_by) -> None:
    handler, store, statuses = response_handler
    token = store.create_account_session("account_a")
    handler.headers = {"Cookie": f"rehab_demo2_session={token}"}
    handler.path = "/api/v1/demo2/upload/workspace?course_id=shared-course"
    acceptance = {
        "confirmed_by": confirmed_by,
        "allow_company_archive": True,
        "course_name": "private-course-note",
        "authorized_scope": {"private_note": "must-not-leak-through-workspace"},
    }
    workspace = store.account_upload_workspace(token, "shared-course")
    workspace.update(security_acceptance=acceptance, latest_security_acceptance=acceptance)
    monkeypatch.setattr(store, "account_upload_workspace", lambda *_: workspace)

    handler._handle_demo2_api_get(urlparse(handler.path))

    assert statuses == [200]
    raw = handler.wfile.getvalue().split(b"\r\n\r\n", 1)[1]
    public = json.loads(raw)["workspace"]
    assert "security_acceptance" not in public
    assert "latest_security_acceptance" not in public
    assert b"private-course-note" not in raw
    assert b"must-not-leak-through-workspace" not in raw
    assert public["upload_channel"]["channel_id"] == "channel_1"
    assert public["tasks"] == []
    # Filtering the HTTP response must not alter repository data or consent.
    assert workspace["security_acceptance"] is acceptance
    assert workspace["latest_security_acceptance"] is acceptance


def test_workspace_consent_isolation_sqlite(onboarding_server) -> None:
    port, store = onboarding_server
    acceptance = store.record_security_acceptance({
        "security_confirmed": True,
        "course_id": "shared-course",
        "course_name": "private-other-school-course",
        "confirmed_by": "school_uploader_02",
        "allow_company_archive": True,
    }, actor="synthetic-test")
    for index in range(1, 5):
        cookie = _login(port, f"t{index}", f"onboarding-test-school_uploader_{index:02d}")
        status, headers, body = _request(
            port, "GET", "/api/v1/demo2/upload/workspace?course_id=shared-course", cookie=cookie,
        )
        assert status == 200
        assert "no-store" in headers["cache-control"]
        assert body["workspace"]["channel"]["channel_id"] == f"channel_{index}"
        assert body["workspace"]["tasks"] == []
        assert body["workspace"]["quota"]["used_slots"] == 0
        assert "security_acceptance" not in body["workspace"]
        assert "latest_security_acceptance" not in body["workspace"]
        assert "private-other-school-course" not in json.dumps(body)
        assert acceptance["acceptance_id"] not in json.dumps(body)
    with store._connect() as connection:
        row = connection.execute(
            "SELECT confirmed_by, allow_company_archive FROM data_security_acceptances WHERE acceptance_id = ?",
            (acceptance["acceptance_id"],),
        ).fetchone()
        assert tuple(row) == ("school_uploader_02", 1)


def test_upload_workspace_channel_binding_and_task_ownership(portal_server) -> None:
    port, store = portal_server
    uploader_cookie = _login(port, "uploader_a", "pass-a")
    status, _, body = _request(
        port,
        "GET",
        "/api/v1/demo2/upload/workspace?course_id=course-1",
        cookie=uploader_cookie,
    )
    assert status == 200
    assert body["workspace"]["upload_channel"]["channel_id"] == "channel_1"

    task_payload = {
        "account_id": "attacker-controlled",
        "security_confirmed": True,
        "confirmed_by": "attacker-controlled",
        "allow_company_archive": True,
        "channel_id": "channel_2",
        "course_id": "course-1",
        "course_name": "测试课程",
    }
    status, _, body = _request(
        port, "POST", "/api/v1/demo2/upload/tasks", task_payload, cookie=uploader_cookie
    )
    assert status == 403
    assert body["error"]["code"] == "channel_forbidden"

    task_payload["channel_id"] = "channel_1"
    status, _, body = _request(
        port, "POST", "/api/v1/demo2/upload/tasks", task_payload, cookie=uploader_cookie
    )
    assert status == 200
    task_id = body["task"]["task_id"]
    assert store.last_created_payload["account_id"] == "account_a"
    assert store.last_created_payload["security_confirmed"] is True
    assert store.last_created_payload["confirmed_by"] == "uploader_a"
    assert store.call_order[-2:] == ["acceptance", "create"]
    acceptance = store.security_acceptances[-1]
    assert acceptance["security_confirmed"] is True
    assert acceptance["confirmed_by"] == "uploader_a"
    assert acceptance["course_id"] == "course-1"
    assert acceptance["course_name"] == "测试课程"
    assert acceptance["allow_company_archive"] is True

    other_cookie = _login(port, "uploader_b", "pass-b")
    chunk = {
        "task_id": task_id,
        "course_id": "course-1",
        "chunk_index": 0,
        "content_base64": "YQ==",
    }
    status, _, body = _request(
        port, "POST", "/api/v1/demo2/upload/chunks", chunk, cookie=other_cookie
    )
    assert status == 403
    assert body["error"]["code"] == "task_forbidden"

    status, _, body = _request(
        port, "POST", "/api/v1/demo2/upload/chunks", chunk, cookie=uploader_cookie
    )
    assert status == 200
    assert body["task"]["task_id"] == task_id
    assert store.last_chunk_actor == "account_a"

    admin_cookie = _login(port, "admin", "admin-pass")
    status, _, body = _request(
        port, "POST", "/api/v1/demo2/upload/chunks", chunk, cookie=admin_cookie
    )
    assert status == 403
    assert body["error"]["code"] == "forbidden"
    assert store.last_chunk_actor == "account_a"


def test_incomplete_task_cancel_requires_owner_and_admin_remains_read_only(
    portal_server,
) -> None:
    port, store = portal_server
    owner_cookie = _login(port, "uploader_a", "pass-a")
    other_cookie = _login(port, "uploader_b", "pass-b")
    admin_cookie = _login(port, "admin", "admin-pass")
    store.tasks["task-cancel"] = {
        "task_id": "task-cancel",
        "account_id": "account_a",
        "course_id": "course-cancel",
        "upload_status": "uploading",
    }

    for cookie in (other_cookie, admin_cookie):
        status, _, body = _request(
            port,
            "POST",
            "/api/v1/demo2/upload/tasks/cancel",
            {"task_id": "task-cancel"},
            cookie=cookie,
        )
        assert status == 403
        assert body["error"]["code"] in {"task_forbidden", "forbidden"}
    assert store.last_cancel_actor == ""

    status, _, body = _request(
        port,
        "POST",
        "/api/v1/demo2/upload/tasks/cancel",
        {"task_id": "task-cancel"},
        cookie=owner_cookie,
    )
    assert status == 200
    assert body["task"]["upload_status"] == "cancelled"
    assert store.last_cancel_actor == "account_a"

@pytest.mark.parametrize("context", [None, {}, {"school_name": "Test School"},
    {"city": "Test City", "district": " ", "school_name": "Test School"},
    {"city": "Test City", "district": "Test District", "school_name": None}])
def test_upload_requires_complete_stored_school_before_any_writes(portal_server, monkeypatch, context) -> None:
    port, store = portal_server
    cookie = _login(port, "uploader_a", "pass-a")
    monkeypatch.setattr(store, "account_school_context", lambda token: {"context": context})
    status, _, body = _request(port, "POST", "/api/v1/demo2/upload/tasks", {
        "security_confirmed": True, "channel_id": "channel_1", "course_id": "school-required",
        "course_name": "Test Course", "school_context": {
            "city": "Forged City", "district": "Forged District", "school_name": "Forged School"},
    }, cookie=cookie)
    assert status == 409
    assert body["error"] == {"code": "school_context_required", "message": "请先选择并保存学校信息，再上传视频"}
    assert store.tasks == {} and store.security_acceptances == [] and store.call_order == []


def test_school_selection_unblocks_new_upload_using_real_store(onboarding_server) -> None:
    port, store = onboarding_server
    cookie = _login(port, "t2", "onboarding-test-school_uploader_02")
    context = {"city": "Test City", "district": "Test District", "school_name": "Test School"}
    payload = {"channel_id": "channel_2", "course_id": "school-guard", "course_name": "Test Course",
               "uploader_name": "Test Uploader", "session_id": "synthetic", "filename": "test.mp4",
               "byte_size": 3, "total_chunks": 1, "security_confirmed": True, "school_context": context}
    status, _, body = _request(port, "POST", "/api/v1/demo2/upload/tasks", payload, cookie=cookie)
    assert status == 409 and body["error"]["code"] == "school_context_required"
    with store._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM video_analysis_tasks").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM data_security_acceptances").fetchone()[0] == 0
    assert list(store.video_task_dir.rglob("*.part")) == []
    assert _request(port, "POST", "/api/v1/demo2/school/context", context, cookie=cookie)[0] == 200
    status, _, body = _request(port, "POST", "/api/v1/demo2/upload/tasks", payload, cookie=cookie)
    assert status == 200 and body["task"]["school_context"] == context
    with store._connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM video_analysis_tasks").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM data_security_acceptances").fetchone()[0] == 1


def test_upload_task_requires_explicit_client_security_confirmation(portal_server) -> None:
    port, store = portal_server
    cookie = _login(port, "uploader_a", "pass-a")
    payload = {
        "channel_id": "channel_1",
        "course_id": "course-confirmation",
        "course_name": "显式确认课程",
    }
    for supplied in (None, False):
        request_payload = dict(payload)
        if supplied is not None:
            request_payload["security_confirmed"] = supplied
        status, _, body = _request(
            port,
            "POST",
            "/api/v1/demo2/upload/tasks",
            request_payload,
            cookie=cookie,
        )
        assert status == 400
        assert body["error"]["code"] == "security_confirmation_required"
    assert store.security_acceptances == []
    assert store.tasks == {}
    assert store.call_order == []


def test_security_acceptance_failure_prevents_task_creation(portal_server) -> None:
    port, store = portal_server
    store.fail_acceptance = True
    cookie = _login(port, "uploader_a", "pass-a")
    status, _, body = _request(
        port,
        "POST",
        "/api/v1/demo2/upload/tasks",
        {
            "security_confirmed": True,
            "channel_id": "channel_1",
            "course_id": "course-acceptance-failure",
            "course_name": "安全确认失败课程",
        },
        cookie=cookie,
    )
    assert status == 400
    assert body["error"]["code"] == "invalid_request"
    assert store.tasks == {}
    assert store.call_order == ["acceptance"]


def test_upload_quota_maps_to_stable_conflict_error(portal_server) -> None:
    port, store = portal_server
    cookie = _login(port, "uploader_a", "pass-a")
    payload = {
        "security_confirmed": True,
        "channel_id": "channel_1",
        "course_id": "course-full",
        "course_name": "配额测试课程",
    }

    store.quota_full = True
    status, _, body = _request(
        port, "POST", "/api/v1/demo2/upload/tasks", payload, cookie=cookie
    )
    assert status == 409
    assert body["error"]["code"] == "quota_exceeded"
    assert store.call_order == []

    store.quota_full = False
    store.raise_quota_on_create = True
    status, _, body = _request(
        port, "POST", "/api/v1/demo2/upload/tasks", payload, cookie=cookie
    )
    assert status == 409
    assert body["error"]["code"] == "quota_exceeded"
    assert store.call_order == ["acceptance", "create"]


def test_video_result_download_requires_owner_or_admin(portal_server) -> None:
    port, store = portal_server
    store.tasks["task-download"] = {
        "task_id": "task-download",
        "account_id": "account_a",
        "course_id": "course-download",
        "result_ready": True,
    }

    status, _, body = _request(
        port, "GET", "/api/v1/demo2/upload/result?id=task-download"
    )
    assert status == 401
    assert body["error"]["code"] == "authentication_required"

    other_cookie = _login(port, "uploader_b", "pass-b")
    status, _, body = _request(
        port,
        "GET",
        "/api/v1/demo2/upload/result?id=task-download",
        cookie=other_cookie,
    )
    assert status == 403
    assert body["error"]["code"] == "result_forbidden"

    owner_cookie = _login(port, "uploader_a", "pass-a")
    status, headers, body = _request(
        port,
        "GET",
        "/api/v1/demo2/upload/result?id=task-download",
        cookie=owner_cookie,
    )
    assert status == 200
    assert body["task_id"] == "task-download"
    assert "attachment" in headers["content-disposition"]

    admin_cookie = _login(port, "admin", "admin-pass")
    status, _, body = _request(
        port,
        "GET",
        "/api/v1/demo2/upload/result?id=task-download",
        cookie=admin_cookie,
    )
    assert status == 200
    assert body["task_id"] == "task-download"


def test_admin_summary_requires_company_admin(portal_server) -> None:
    port, _ = portal_server
    status, _, body = _request(port, "GET", "/api/v1/demo2/admin/summary")
    assert status == 401
    assert body["error"]["code"] == "authentication_required"

    uploader_cookie = _login(port, "uploader_a", "pass-a")
    status, _, body = _request(
        port, "GET", "/api/v1/demo2/admin/summary", cookie=uploader_cookie
    )
    assert status == 403
    assert body["error"]["code"] == "forbidden"

    admin_cookie = _login(port, "admin", "admin-pass")
    status, _, body = _request(port, "GET", "/api/v1/demo2/admin/summary", cookie=admin_cookie)
    assert status == 200
    assert body["summary"]["requested_by"] == "account_admin"


def test_admin_summary_history_page_contract(portal_server) -> None:
    port, _ = portal_server
    cookie = _login(port, "admin", "admin-pass")
    status, _, body = _request(port, "GET", "/api/v1/demo2/admin/summary?upload_page=2", cookie=cookie)
    assert status == 200
    assert body["summary"]["page"] == 2
    for query in ("upload_page=0", "upload_page=-1", "upload_page=", "upload_page=1&upload_page=2", "upload_page=x", "unknown=1"):
        status, _, _ = _request(port, "GET", "/api/v1/demo2/admin/summary?" + query, cookie=cookie)
        assert status == 400
    school_cookie = _login(port, "uploader_a", "pass-a")
    status, _, _ = _request(port, "GET", "/api/v1/demo2/admin/summary?upload_page=2", cookie=school_cookie)
    assert status == 403


def test_legacy_demo2_page_api_and_assets_require_login(portal_server) -> None:
    port, _ = portal_server
    status, headers, _ = _request(port, "GET", "/seewo_student_demo2")
    assert status == 302
    assert headers["location"] == "/demo2/login"

    for path in (
        "/api/seewo_student_demo2",
        "/api/seewo_demo2_reviews?course_id=course-1",
        "/api/seewo_demo2/storage",
        "/assets/seewo_demo2/private/result.json",
    ):
        status, _, body = _request(port, "GET", path)
        assert status == 401
        assert body["error"]["code"] == "authentication_required"

    status, _, body = _request(
        port,
        "POST",
        "/api/seewo_demo2_reviews",
        {"course_id": "course-1", "reviews": {}},
    )
    assert status == 401
    assert body["error"]["code"] == "authentication_required"

    cookie = _login(port, "uploader_a", "pass-a")
    status, headers, body = _request(
        port,
        "GET",
        "/assets/seewo_demo2/course-1/group_reference.jpg",
        cookie=cookie,
    )
    assert status == 410
    assert headers["content-type"].startswith("application/json")
    assert body["error"]["code"] == "legacy_data_reimport_required"
    assert "private" in headers["cache-control"]
    for forbidden_path in (
        "/assets/seewo_demo2/analysis.json",
        "/assets/seewo_demo2/rehab_affect_demo2.sqlite3",
        "/assets/seewo_demo2/video_tasks/private.mp4",
        "/assets/seewo_demo2/course-1/private.json",
    ):
        assert _request(port, "GET", forbidden_path, cookie=cookie)[0] == 410
    status, _, page = _request(port, "GET", "/seewo_student_demo2", cookie=cookie)
    assert status == 200 and "旧资料未迁移" in page
    assert "/demo2/students" in page and "/demo2/upload" in page
    status, _, body = _request(port, "GET", "/api/seewo_student_demo2", cookie=cookie)
    assert status == 410
    assert body["error"]["code"] == "legacy_data_reimport_required"
    assert "legacy_demo2" not in body

    status, _, body = _request(
        port,
        "POST",
        "/api/seewo_demo2/security_acceptance",
        {
            "course_id": "course-1",
            "course_name": "测试课程",
            "security_confirmed": True,
            "confirmed_by": "伪造确认人",
        },
        cookie=cookie,
    )
    assert status == 200
    assert body["acceptance"]["confirmed_by"] == "uploader_a"
    assert body["acceptance"]["actor"] == "account_a"

    admin_cookie = _login(port, "admin", "admin-pass")
    for path, payload in (
        ("/api/seewo_demo2_reviews", {"course_id": "course-1", "reviews": {}}),
        (
            "/api/seewo_demo2/security_acceptance",
            {"course_id": "course-1", "security_confirmed": True},
        ),
    ):
        status, _, body = _request(port, "POST", path, payload, cookie=admin_cookie)
        retired = path == "/api/seewo_demo2_reviews"
        assert status == (410 if retired else 403)
        assert body["error"]["code"] == ("legacy_data_reimport_required" if retired else "forbidden")
    status, _, body = _request(
        port,
        "POST",
        "/api/seewo_demo2/video_chunk",
        {"task_id": "any-task", "chunk_index": 0, "content_base64": "YQ=="},
        cookie=admin_cookie,
    )
    assert status == 403
    assert body["error"]["code"] == "forbidden"


def test_legacy_storage_summary_is_retired_without_reading_private_data(portal_server, monkeypatch) -> None:
    port, store = portal_server
    def forbidden_read():
        pytest.fail("retired storage must not read legacy global data")
    monkeypatch.setattr(store, "storage_summary", forbidden_read)
    cookie = _login(port, "uploader_a", "pass-a")
    status, _, body = _request(
        port,
        "GET",
        "/api/seewo_demo2/storage",
        cookie=cookie,
    )
    assert status == 410
    assert body["error"]["code"] == "legacy_data_reimport_required"
    assert set(body) == {"ok", "error"}
    assert "D:/private" not in json.dumps(body)


def test_api_integrates_with_sqlite_account_workspace_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "test-only-")
    store = Demo2StudentRecordStore(tmp_path / "portal.sqlite3", tmp_path / "documents")
    monkeypatch.setattr(server_module, "get_demo2_student_store", lambda: store)
    handler = server_module.create_handler(
        scenario_dir=tmp_path,
        model_path=tmp_path / "unused.json",
        policy_name="rule",
    )
    httpd = server_module.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        cookie = _login(
            httpd.server_port,
            "school_uploader_01",
            "test-only-school_uploader_01",
        )
        assert _request(httpd.server_port, "POST", "/api/v1/demo2/school/context", {
            "city": "Test City", "district": "Test District", "school_name": "Test School",
        }, cookie=cookie)[0] == 200
        status, _, body = _request(
            httpd.server_port,
            "GET",
            "/api/v1/demo2/upload/workspace?course_id=course-real-store",
            cookie=cookie,
        )
        assert status == 200
        assert body["workspace"]["channel"]["channel_id"] == "channel_1"
        account_id = body["workspace"]["account"]["account_id"]

        video = b"test-video-bytes"
        status, _, body = _request(
            httpd.server_port,
            "POST",
            "/api/v1/demo2/upload/tasks",
            {
                "security_confirmed": True,
                "channel_id": "channel_1",
                "session_id": "session-real-store",
                "uploader_name": "测试上传员",
                "course_id": "course-real-store",
                "course_name": "接口联调课程",
                "filename": "clip.mp4",
                "mime_type": "video/mp4",
                "byte_size": len(video),
                "total_chunks": 1,
            },
            cookie=cookie,
        )
        assert status == 200
        task_id = body["task"]["task_id"]
        assert body["task"]["account_id"] == account_id

        status, _, body = _request(
            httpd.server_port,
            "POST",
            "/api/v1/demo2/upload/chunks",
            {
                "task_id": task_id,
                "course_id": "course-real-store",
                "chunk_index": 0,
                "content_base64": base64.b64encode(video).decode("ascii"),
            },
            cookie=cookie,
        )
        assert status == 200
        assert body["task"]["upload_status"] == "completed"

        assert body["task"]["analysis_status"] == "queued"
        assert body["task"]["processing_progress"] == 0
        status, _, pending = _request(
            httpd.server_port,
            "GET",
            f"/api/v1/demo2/upload/result?id={task_id}",
            cookie=cookie,
        )
        assert status == 409
        assert pending["error"]["code"] == "result_not_ready"

        # This contract test has synthetic bytes, so explicitly simulate only
        # the worker completion boundary. The media QA harness runs real FFmpeg.
        claimed = store.claim_next_video_analysis()
        assert claimed is not None and claimed["task_id"] == task_id
        status, _, pending = _request(
            httpd.server_port,
            "GET",
            f"/api/v1/demo2/upload/result?id={task_id}",
            cookie=cookie,
        )
        assert status == 409
        assert pending["error"]["code"] == "result_not_ready"
        finished = store.finish_video_analysis(task_id, {
            "task_id": task_id,
            "analysis_version": "test_worker_boundary_v1",
            "content": {"simulated_worker_completion": True},
        })
        assert finished["analysis_status"] == "evidence_ready"
        assert finished["processing_progress"] == 100

        status, headers, result = _request(
            httpd.server_port,
            "GET",
            f"/api/v1/demo2/upload/result?id={task_id}",
            cookie=cookie,
        )
        assert status == 200
        assert result["task_id"] == task_id
        assert "attachment" in headers["content-disposition"]

        admin_cookie = _login(
            httpd.server_port,
            "company_admin",
            "test-only-company_admin",
        )
        status, _, result = _request(
            httpd.server_port,
            "GET",
            f"/api/v1/demo2/upload/result?id={task_id}",
            cookie=admin_cookie,
        )
        assert status == 200
        assert result["task_id"] == task_id
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


def test_legacy_video_routes_keep_account_channel_quota_and_result_isolation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "legacy-test-")
    store = Demo2StudentRecordStore(tmp_path / "legacy.sqlite3", tmp_path / "documents")
    monkeypatch.setattr(server_module, "get_demo2_student_store", lambda: store)
    monkeypatch.setattr(server_module, "load_seewo_demo2", lambda force=False: {"students": []})
    handler = server_module.create_handler(
        scenario_dir=tmp_path,
        model_path=tmp_path / "unused.json",
        policy_name="rule",
    )
    httpd = server_module.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        owner_cookie = _login(
            httpd.server_port,
            "school_uploader_01",
            "legacy-test-school_uploader_01",
        )
        assert _request(httpd.server_port, "POST", "/api/v1/demo2/school/context", {
            "city": "Test City", "district": "Test District", "school_name": "Test School",
        }, cookie=owner_cookie)[0] == 200
        other_cookie = _login(
            httpd.server_port,
            "school_uploader_02",
            "legacy-test-school_uploader_02",
        )

        status, _, channel_body = _request(
            httpd.server_port,
            "GET",
            "/api/seewo_demo2/video_channels",
            cookie=owner_cookie,
        )
        assert status == 410
        assert channel_body["error"]["code"] == "legacy_data_reimport_required"
        assert "channels" not in channel_body
        status, _, channel_body = _request(
            httpd.server_port, "GET", "/api/v1/demo2/upload/workspace?course_id=legacy-course", cookie=owner_cookie,
        )
        assert status == 200 and channel_body["workspace"]["channel"]["channel_id"] == "channel_1"

        base_payload = {
            "security_confirmed": True,
            "session_id": "legacy-session",
            "uploader_name": "校方上传员",
            "course_id": "legacy-course",
            "course_name": "旧页面兼容课程",
            "filename": "legacy.mp4",
            "mime_type": "video/mp4",
            "byte_size": 1,
            "total_chunks": 1,
        }
        status, _, body = _request(
            httpd.server_port,
            "POST",
            "/api/seewo_demo2/video_task",
            {**base_payload, "channel_id": "channel_2"},
            cookie=owner_cookie,
        )
        assert status == 200
        assert body["task"]["channel_id"] == "channel_2"

        status, _, body = _request(
            httpd.server_port,
            "POST",
            "/api/seewo_demo2/video_task",
            {**base_payload, "channel_id": "channel_1"},
            cookie=owner_cookie,
        )
        assert status == 200
        task_id = body["task"]["task_id"]

        chunk_payload = {
            "task_id": task_id,
            "course_id": "legacy-course",
            "chunk_index": 0,
            "content_base64": "YQ==",
        }
        status, _, body = _request(
            httpd.server_port,
            "POST",
            "/api/seewo_demo2/video_chunk",
            chunk_payload,
            cookie=other_cookie,
        )
        assert status == 403
        assert body["error"]["code"] == "task_forbidden"

        status, _, body = _request(
            httpd.server_port,
            "POST",
            "/api/seewo_demo2/video_chunk",
            chunk_payload,
            cookie=owner_cookie,
        )
        assert status == 200
        assert body["task"]["upload_status"] == "completed"
        assert body["task"]["analysis_status"] == "queued"
        assert body["task"]["processing_progress"] == 0

        status, _, body = _request(
            httpd.server_port,
            "GET",
            f"/api/seewo_demo2/video_result_download?id={task_id}",
            cookie=other_cookie,
        )
        assert status == 403
        assert body["error"]["code"] == "result_forbidden"

        status, headers, body = _request(
            httpd.server_port,
            "GET",
            f"/api/seewo_demo2/video_result_download?id={task_id}",
            cookie=owner_cookie,
        )
        assert status == 409
        assert body["error"]["code"] == "result_not_ready"
        claimed = store.claim_next_video_analysis()
        assert claimed is not None and claimed["task_id"] == task_id
        finished = store.finish_video_analysis(task_id, {
            "task_id": task_id,
            "analysis_version": "test_worker_boundary_v1",
            "content": {"simulated_worker_completion": True},
        })
        assert finished["analysis_status"] == "evidence_ready"
        assert finished["processing_progress"] == 100

        status, _, denied = _request(
            httpd.server_port,
            "GET",
            f"/api/seewo_demo2/video_result_download?id={task_id}",
            cookie=other_cookie,
        )
        assert status == 403
        assert denied["error"]["code"] == "result_forbidden"
        status, headers, body = _request(
            httpd.server_port,
            "GET",
            f"/api/seewo_demo2/video_result_download?id={task_id}",
            cookie=owner_cookie,
        )
        assert status == 200
        assert body["task_id"] == task_id
        assert "attachment" in headers["content-disposition"]
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)
