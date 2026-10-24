"""Backend membership contracts and fail-closed classroom role boundaries."""

from __future__ import annotations

import http.client
import json
import sys
import threading
from types import ModuleType
from types import SimpleNamespace

import pytest

from src.rehab_affect import scenario_lab_server as server_module
from src.rehab_affect import demo2_manager_gateway as gateway


class MembershipError(Exception):
    def __init__(self, status, code, message):
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


class Records:
    def __init__(self):
        self.accounts = {
            "member": {"account_id": "member-id", "username": "13800000000", "role": "registered_member"},
            "school": {"account_id": "school-id", "username": "t1", "role": "school_uploader", "bound_channel_id": "channel_1"},
            "admin": {"account_id": "admin-id", "username": "admin", "role": "company_admin"},
        }
        self.sessions = {f"session-{key}": key for key in self.accounts}
        self.created_sessions = []

    def account_from_session(self, token):
        key = self.sessions.get(token)
        return dict(self.accounts[key]) if key else None

    def authenticate_account(self, username, password):
        for account in self.accounts.values():
            if account["username"] == username and password == "fixture-password":
                return dict(account)
        raise ValueError("Invalid credentials")

    def create_account_session(self, account_id):
        self.created_sessions.append(account_id)
        key = next(key for key, value in self.accounts.items() if value["account_id"] == account_id)
        self.sessions["new-session"] = key
        return {"token": "new-session"}

    def revoke_account_session(self, token):
        self.sessions.pop(token, None)

    def admin_platform_summary(self, token):
        return {"account_count": 3}


class Memberships:
    def __init__(self, records):
        self.records = records
        self.calls = []
        self.sms_configured = False
        self.status = "unpaid"

    def public_config(self):
        return {"sms_available": self.sms_configured, "payment_available": False, "plans": []}

    def request_code(self, phone, source_key):
        self.calls.append(("sms", phone, source_key))
        if not self.sms_configured:
            raise MembershipError(503, "sms_unavailable", "短信服务尚未配置")
        return {"sent": True, "retry_after": 60}

    def register(self, payload, source_key):
        self.calls.append(("register", dict(payload), source_key))
        if not self.sms_configured:
            raise MembershipError(503, "sms_unavailable", "短信服务尚未配置")
        if payload.get("code") != "123456":
            raise MembershipError(400, "invalid_code", "验证码无效")
        return {**self.records.accounts["member"], "password_hash": "must-not-leak"}

    def membership(self, account_id):
        self.calls.append(("membership", account_id))
        return {"account_id": account_id, "status": self.status}

    def create_order(self, account_id, payload):
        self.calls.append(("order", account_id, dict(payload)))
        raise MembershipError(503, "payment_unavailable", "支付服务尚未配置，不能完成购买")

    def admin_summary(self):
        self.calls.append(("admin_summary",))
        return {"registered_accounts": 1, "paid_accounts": 0}


@pytest.fixture()
def backend(tmp_path, monkeypatch):
    records = Records()
    memberships = Memberships(records)
    module = ModuleType("src.rehab_affect.demo2_membership_store")
    module.MembershipError = MembershipError
    module.Demo2MembershipStore = lambda store: memberships
    monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(server_module, "get_demo2_student_store", lambda: records)
    monkeypatch.setattr(server_module, "_render_demo2_portal_page", lambda page, account=None: f"<html>{page}</html>")
    monkeypatch.setattr(server_module, "render_seewo_demo2_html", lambda: "<html>legacy analysis</html>")
    handler = server_module.create_handler(scenario_dir=tmp_path, model_path=tmp_path / "unused", policy_name="rule")
    server = server_module.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    try:
        yield server, records, memberships
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


def request(backend, path, *, role=None, method="GET", payload=None, headers=None):
    server, _, _ = backend
    outgoing = {"Content-Type": "application/json", **(headers or {})}
    if role:
        outgoing["Cookie"] = f"rehab_demo2_session=session-{role}"
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
    try:
        connection.request(method, path, body=json.dumps(payload).encode() if payload is not None else None, headers=outgoing)
        response = connection.getresponse()
        raw = response.read()
        result = json.loads(raw) if "application/json" in response.getheader("Content-Type", "") else raw.decode()
        return response.status, dict(response.getheaders()), result
    finally:
        connection.close()


def test_public_config_and_sms_fail_honestly_without_provider(backend):
    assert request(backend, "/api/v1/demo2/membership/config")[2] == {
        "ok": True, "config": {"sms_available": False, "payment_available": False, "plans": []},
    }
    status, _, body = request(backend, "/api/v1/demo2/auth/sms-code", method="POST", payload={"phone": "13800000000"},
                              headers={"X-Forwarded-For": "forged-source"})
    assert status == 503 and body["error"]["code"] == "sms_unavailable"
    assert backend[2].calls[-1] == ("sms", "13800000000", "127.0.0.1")
    assert "code" not in body.get("result", {})


def test_registration_creates_only_member_session_and_routes_to_membership(backend):
    backend[2].sms_configured = True
    payload = {"phone": "13800000000", "code": "123456", "password": "fixture-password", "accepted": True,
               "agreement_version": "2026-09-09"}
    status, headers, body = request(backend, "/api/v1/demo2/auth/register", method="POST", payload=payload)
    assert status == 200 and body["next_url"] == "/demo2/membership"
    assert body["account"]["role"] == "registered_member"
    assert not any(key in body["account"] for key in ("password_hash", "bound_channel_id"))
    assert backend[1].created_sessions == ["member-id"]
    assert "HttpOnly" in headers["Set-Cookie"] and "Max-Age=28800" in headers["Set-Cookie"]
    assert request(backend, "/api/v1/demo2/auth/me", headers={"Cookie": headers["Set-Cookie"].split(";")[0]})[2]["account"]["role"] == "registered_member"


@pytest.mark.parametrize("configured, code, status", [(False, "123456", 503), (True, "wrong", 400)])
def test_failed_registration_does_not_create_session(backend, configured, code, status):
    backend[2].sms_configured = configured
    result, headers, _ = request(backend, "/api/v1/demo2/auth/register", method="POST", payload={
        "phone": "13800000000", "password": "fixture-password", "code": code,
        "agreement_version": "2026-09-09", "accepted": True,
    })
    assert result == status and "Set-Cookie" not in headers
    assert backend[1].created_sessions == []


@pytest.mark.parametrize("key, selection, next_url", [
    ("member", "school_uploader", "/demo2/membership"),
    ("school", "school_uploader", "/demo2/school"),
    ("admin", "company_admin", "/demo2/admin"),
])
def test_existing_login_selector_accepts_members_without_changing_old_roles(backend, key, selection, next_url):
    status, _, body = request(backend, "/api/v1/demo2/auth/login", method="POST", payload={
        "username": backend[1].accounts[key]["username"], "password": "fixture-password", "role": selection,
    })
    assert status == 200 and body["next_url"] == next_url
    assert body["account"]["role"] == backend[1].accounts[key]["role"]


def test_member_cannot_select_admin_login(backend):
    status, _, body = request(backend, "/api/v1/demo2/auth/login", method="POST", payload={
        "username": "13800000000", "password": "fixture-password", "role": "company_admin",
    })
    assert status == 403 and body["error"]["code"] == "role_mismatch"
    assert backend[1].created_sessions == []


@pytest.mark.parametrize("extra", [{"role": "company_admin"}, {"account_id": "admin-id"}, {"accepted": 1},
                                    {"agreement_version": "old-version"}, {"bound_channel_id": "channel_1"}])
def test_registration_rejects_privilege_fields_and_non_explicit_consent(backend, extra):
    payload = {"phone": "13800000000", "password": "fixture-password", "code": "123456",
               "agreement_version": "2026-09-09", "accepted": True, **extra}
    assert request(backend, "/api/v1/demo2/auth/register", method="POST", payload=payload)[0] == 400
    assert backend[2].calls == [] and backend[1].created_sessions == []


@pytest.mark.parametrize("extra", [{"price": 1}, {"status": "paid"}, {"account_id": "admin-id"}, {"plan_id": []}])
def test_order_rejects_client_price_status_and_account_overrides(backend, extra):
    assert request(backend, "/api/v1/demo2/membership/orders", role="member", method="POST",
                   payload={"plan_id": "monthly", **extra})[0] == 400
    assert backend[2].calls == []


@pytest.mark.parametrize("role", ["member", "school", "admin"])
def test_membership_page_and_status_are_available_to_every_authenticated_role(backend, role):
    assert request(backend, "/demo2/membership", role=role)[0] == 200
    status, _, body = request(backend, "/api/v1/demo2/membership?account_id=forged", role=role)
    assert status == 200 and body["membership"]["account_id"] == backend[1].accounts[role]["account_id"]
    status, _, body = request(backend, "/api/v1/demo2/membership/orders", role=role, method="POST", payload={"plan_id": "monthly"})
    assert status == 503 and body["error"]["code"] == "payment_unavailable"
    assert backend[2].calls[-1] == ("order", backend[1].accounts[role]["account_id"], {"plan_id": "monthly"})


@pytest.mark.parametrize("path, method", [
    ("/api/v1/demo2/membership", "GET"), ("/api/v1/demo2/membership/orders", "POST"),
    ("/api/v1/demo2/admin/memberships", "GET"),
])
def test_private_membership_api_requires_session(backend, path, method):
    assert request(backend, path, method=method, payload={} if method == "POST" else None)[0] == 401
    assert backend[2].calls == []


def test_membership_admin_summary_remains_admin_only(backend):
    for role in ("member", "school"):
        assert request(backend, "/api/v1/demo2/admin/memberships", role=role)[0] == 403
    assert backend[2].calls == []
    status, _, body = request(backend, "/api/v1/demo2/admin/memberships", role="admin")
    assert status == 200 and body["summary"]["paid_accounts"] == 0
    assert request(backend, "/api/v1/demo2/admin/summary", role="admin")[0] == 200


STUDENT_GET = [
    "/seewo_student_demo", "/api/seewo_student_demo?force=1",
    "/assets/seewo_xiaoyudi_demo/analysis.json", "/assets/seewo_xiaoyudi_demo/lesson.wav",
    "/demo2/school", "/demo2/upload", "/demo2/admin", "/demo2/analysis", "/demo2/video?id=owned",
    "/seewo_student_demo2", "/api/seewo_student_demo2", "/api/seewo_demo2_reviews",
    "/api/seewo_demo2_report_status", "/api/seewo_demo2/student_record?id=student",
    "/api/seewo_demo2/storage", "/api/seewo_demo2/video_channels",
    "/api/seewo_demo2/document_download?id=doc", "/api/seewo_demo2/video_result_download?id=owned",
    "/assets/seewo_demo2/course/group_reference.jpg",
    "/api/v1/demo2/school/context", "/api/v1/demo2/upload/workspace?course_id=course",
    "/api/v1/demo2/upload/task?id=owned", "/api/v1/demo2/upload/media?id=owned",
    "/api/v1/demo2/upload/result?id=owned", "/api/v1/demo2/admin/summary",
]
STUDENT_POST = [
    "/api/v1/demo2/school/context", "/api/v1/demo2/upload/tasks", "/api/v1/demo2/upload/chunks",
    "/api/v1/demo2/upload/tasks/cancel", "/api/v1/demo2/upload/tasks/retry", "/api/v1/demo2/upload/tasks/enqueue",
    "/api/seewo_demo2_reviews", "/api/seewo_demo2_long_report", "/api/seewo_demo2/student_document",
    "/api/seewo_demo2/support_profile", "/api/seewo_demo2/storage_policy", "/api/seewo_demo2/document_delete",
    "/api/seewo_demo2/video_task", "/api/seewo_demo2/video_chunk", "/api/seewo_demo2/security_acceptance",
    "/api/seewo_demo2/archive_video_result",
]


@pytest.mark.parametrize("membership_status", ["unpaid", "active"])
@pytest.mark.parametrize("path, method", [(path, "GET") for path in STUDENT_GET] + [(path, "POST") for path in STUDENT_POST])
def test_registered_member_never_gains_student_access_even_if_paid(backend, membership_status, path, method):
    backend[2].status = membership_status
    backend[1].accounts["member"]["membership_status"] = membership_status
    status, _, body = request(backend, path, role="member", method=method, payload={} if method == "POST" else None)
    assert status == 403 and body["error"]["code"] == "student_access_forbidden"
    assert backend[2].calls == []


@pytest.mark.parametrize("role", ["school", "admin"])
def test_legacy_authorized_roles_still_enter_analysis(backend, role):
    assert request(backend, "/demo2/analysis", role=role)[0] == 200
    assert request(backend, "/seewo_student_demo2", role=role)[0] == 200


@pytest.mark.parametrize("path", ["/api/seewo_student_demo", "/api/seewo_student_demo2",
                                  "/assets/seewo_xiaoyudi_demo/analysis.json", "/assets/seewo_demo2/course/frame.jpg"])
def test_legacy_student_data_is_not_public_to_anonymous_requests(backend, path):
    assert request(backend, path)[0] == 401


@pytest.mark.parametrize("path, method, public", [
    ("/api/v1/demo2/membership/config", "GET", True), ("/api/v1/demo2/auth/sms-code", "POST", True),
    ("/api/v1/demo2/auth/register", "POST", True), ("/demo2/membership", "GET", False),
    ("/api/v1/demo2/membership", "GET", False), ("/api/v1/demo2/membership/orders", "POST", False),
    ("/api/v1/demo2/admin/memberships", "GET", False),
])
def test_gateway_exact_membership_routes_and_account_gate(path, method, public):
    assert gateway._allowed(method, path)
    assert (path in gateway._PUBLIC_UPSTREAM) is public
    assert not gateway._allowed(method, path + "/unexpected")


@pytest.mark.parametrize("path, code, expected", [
    ("/api/v1/demo2/auth/sms-code", "sms_not_configured", "sms_not_configured"),
    ("/api/v1/demo2/auth/register", "sms_not_configured", "sms_not_configured"),
    ("/api/v1/demo2/membership/orders", "payment_not_configured", "payment_not_configured"),
    ("/api/v1/demo2/membership/orders", "private_database_error", "upstream_unavailable"),
])
def test_gateway_preserves_safe_provider_unavailable_codes_without_internal_text(path, code, expected):
    class Response:
        status = 503

        def read(self, limit):
            return json.dumps({"ok": False, "error": {"code": code, "message": "D:/private/provider-key"}}).encode()

    results = []
    handler = object.__new__(gateway._GatewayHandler)
    handler.command = "POST"
    handler._connection = lambda: SimpleNamespace(request=lambda *args, **kwargs: None,
                                                  getresponse=Response, close=lambda: None)
    handler._upstream_headers = lambda cookies: {}
    handler._expired = lambda: False
    handler._error = lambda status, code, message: results.append((status, code, message))
    handler._proxy(path, b"{}", {})
    assert results[0][:2] == (503, expected)
    assert "private" not in results[0][2] and "provider-key" not in results[0][2]


def test_membership_renderer_uses_entry_module_without_portal_changes(monkeypatch):
    from src.rehab_affect import demo2_entry

    account = {"account_id": "member", "role": "registered_member"}
    monkeypatch.setattr(demo2_entry, "render_membership", lambda account: f"membership:{account['account_id']}", raising=False)
    assert server_module._render_demo2_portal_page("membership", account) == "membership:member"


@pytest.fixture()
def sqlite_backend(tmp_path, monkeypatch):
    from src.rehab_affect.student_record_store import Demo2StudentRecordStore
    from src.rehab_affect.demo2_membership_store import Demo2MembershipStore

    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "MembershipFixture-")
    records = Demo2StudentRecordStore(tmp_path / "members.sqlite3", tmp_path / "documents")
    delivered = []
    memberships = Demo2MembershipStore(records, sms_sender=lambda phone, code: delivered.append((phone, code)))
    monkeypatch.setattr(server_module, "get_demo2_student_store", lambda: records)
    handler = server_module.create_handler(scenario_dir=tmp_path, model_path=tmp_path / "unused", policy_name="rule",
                                           membership_store=memberships)
    server = server_module.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    try:
        yield (server, records, memberships), delivered
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_real_sqlite_sms_registration_login_and_unpaid_isolation(sqlite_backend):
    backend, delivered = sqlite_backend
    status, _, body = request(backend, "/api/v1/demo2/auth/sms-code", method="POST", payload={"phone": "13800000000"})
    assert status == 200 and body["result"]["expires_in"] == 300
    assert len(delivered) == 1 and "code" not in body["result"]
    payload = {"phone": "13800000000", "code": delivered[0][1], "password": "FixturePass123", "accepted": True,
               "agreement_version": "2026-09-09"}
    status, headers, body = request(backend, "/api/v1/demo2/auth/register", method="POST", payload=payload)
    assert status == 200 and body["account"]["role"] == "registered_member"
    assert body["account"]["bound_channel_id"] is None
    cookie = {"Cookie": headers["Set-Cookie"].split(";")[0]}
    status, _, member = request(backend, "/api/v1/demo2/membership", headers=cookie)
    assert status == 200 and member["membership"]["status"] == "inactive"
    assert member["membership"]["school_access"] is False
    status, _, error = request(backend, "/api/v1/demo2/membership/orders", method="POST", payload={"plan_id": "monthly"}, headers=cookie)
    assert status == 503 and error["error"]["code"] == "payment_not_configured"
    for path in STUDENT_GET:
        assert request(backend, path, headers=cookie)[0] == 403
    for path in STUDENT_POST:
        assert request(backend, path, method="POST", payload={}, headers=cookie)[0] == 403
    status, _, body = request(backend, "/api/v1/demo2/auth/login", method="POST", payload={
        "username": "13800000000", "password": "FixturePass123", "role": "school_uploader",
    })
    assert status == 200 and body["next_url"] == "/demo2/membership"
    assert request(backend, "/api/v1/demo2/auth/register", method="POST", payload=payload)[0] == 400


def test_real_unconfigured_sms_is_503_and_never_registers(sqlite_backend):
    from src.rehab_affect.demo2_membership_store import Demo2MembershipStore

    backend, delivered = sqlite_backend
    # Exercise the default, unconfigured service without changing any runtime configuration.
    backend[2]._sms_sender = None
    config = request(backend, "/api/v1/demo2/membership/config")[2]["config"]
    assert config["sms_available"] is False and config["payment_available"] is False
    assert all(plan["price_cents"] is None and plan["available"] is False for plan in config["plans"])
    status, _, body = request(backend, "/api/v1/demo2/auth/sms-code", method="POST", payload={"phone": "13800000001"})
    assert status == 503 and body["error"]["code"] == "sms_not_configured"
    status, headers, body = request(backend, "/api/v1/demo2/auth/register", method="POST", payload={
        "phone": "13800000001", "code": "123456", "password": "FixturePass123", "accepted": True,
        "agreement_version": "2026-09-09",
    })
    assert status == 503 and body["error"]["code"] == "sms_not_configured" and "Set-Cookie" not in headers
    assert delivered == []
    assert Demo2MembershipStore(backend[1]).admin_summary()["members"] == []


@pytest.mark.parametrize("username, role", [("t1", "school_uploader"), ("admin", "company_admin")])
def test_existing_sqlite_accounts_view_internal_trial_without_creating_members(sqlite_backend, username, role):
    backend, _ = sqlite_backend
    password_name = "school_uploader_01" if username == "t1" else "company_admin"
    status, headers, body = request(backend, "/api/v1/demo2/auth/login", method="POST", payload={
        "username": username, "password": "MembershipFixture-" + password_name, "role": role,
    })
    assert status == 200 and body["account"]["role"] == role
    cookie = {"Cookie": headers["Set-Cookie"].split(";")[0]}
    status, _, body = request(backend, "/api/v1/demo2/membership", headers=cookie)
    assert status == 200 and body["membership"]["status"] == "internal_trial"
    assert body["membership"]["orders"] == [] and body["membership"]["payment_available"] is False
    status, _, page = request(backend, "/demo2/membership", headers=cookie)
    assert status == 200 and 'id="membershipCenter"' in page
    assert backend[2].admin_summary()["members"] == []
