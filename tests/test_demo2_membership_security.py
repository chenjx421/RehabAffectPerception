"""Independent membership/legacy authorization QA on disposable loopback servers.

No production account, order, media, SMS transport, or running service is used.
SMS is captured in memory; all legacy assets below contain a synthetic marker.
"""

from __future__ import annotations

import http.client
import hashlib
import importlib
import importlib.util
import itertools
import json
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.rehab_affect import scenario_lab_server as server
from src.rehab_affect.student_record_store import Demo2StudentRecordStore


API = "/api/v1/demo2"
MARKER = "QA_SYNTHETIC_STUDENT_DATA_MUST_NOT_REACH_MEMBERS"
PASSWORD = "MembershipQA9"
AGREEMENT = "2026-09-09"
PILOT_PREFIX = "membership-security-qa-"

LEGACY_GET = (
    "/api/seewo_student_demo",
    "/api/seewo_student_demo?force=1",
    "/api/seewo_student_demo2",
    "/api/seewo_student_demo2?force=1",
    "/api/seewo_demo2_reviews?course_id=fixture",
    "/api/seewo_demo2_report_status",
    "/api/seewo_demo2/student_record?student_id=fixture",
    "/api/seewo_demo2/storage",
    "/api/seewo_demo2/video_channels",
    "/api/seewo_demo2/document_download?id=fixture",
    "/api/seewo_demo2/video_result_download?id=fixture",
    "/assets/seewo_demo2/fixture/frame.jpg",
    "/assets/seewo_xiaoyudi_demo/analysis.json",
    "/assets/seewo_xiaoyudi_demo/lesson_audio_8k_mono.wav",
    "/assets/seewo_xiaoyudi_demo/lesson_sample_contact_sheet.jpg",
    "/assets/seewo_xiaoyudi_demo/frames/frame.jpg",
)
SCHOOL_PAGES = (
    "/seewo_student_demo", "/seewo_student_demo2", "/demo2/school",
    "/demo2/upload", "/demo2/admin", "/demo2/analysis", "/demo2/video",
)
SCHOOL_GET = (
    "/school/context", "/upload/workspace?course_id=fixture",
    "/upload/task?id=fixture", "/upload/media?id=fixture",
    "/upload/media?id=fixture&asset=audio", "/upload/result?id=fixture",
    "/admin/summary", "/admin/memberships",
)
LEGACY_POST = (
    "/api/seewo_demo2_reviews", "/api/seewo_demo2_long_report",
    "/api/seewo_demo2/student_document", "/api/seewo_demo2/support_profile",
    "/api/seewo_demo2/storage_policy", "/api/seewo_demo2/document_delete",
    "/api/seewo_demo2/video_task", "/api/seewo_demo2/video_chunk",
    "/api/seewo_demo2/security_acceptance", "/api/seewo_demo2/archive_video_result",
)
SCHOOL_POST = (
    "/school/context", "/upload/tasks", "/upload/tasks/cancel",
    "/upload/tasks/retry", "/upload/tasks/enqueue", "/upload/chunks",
)


class CapturingSMS:
    def __init__(self):
        self.messages: dict[str, str] = {}

    def __call__(self, phone, code):
        self.messages[str(phone)] = str(code)


def request(port, method, path, payload=None, *, cookie=""):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    try:
        # Coalesce these small fixture requests. Separate header/body writes can
        # race an early authentication rejection and TCP close on Windows.
        # This helper does not retry requests or conceal HTTP error responses.
        body_bytes = json.dumps(payload).encode() if payload is not None else b""
        headers.update({"Host": f"127.0.0.1:{port}", "Connection": "close", "Content-Length": str(len(body_bytes))})
        wire = (f"{method} {path} HTTP/1.1\r\n" + "".join(f"{k}: {v}\r\n" for k, v in headers.items()) + "\r\n").encode("ascii") + body_bytes
        connection.connect()
        connection.sock.sendall(wire)
        response = http.client.HTTPResponse(connection.sock, method=method)
        response.begin()
        raw = response.read()
        head = {k.lower(): v for k, v in response.getheaders()}
        body = json.loads(raw) if "application/json" in head.get("content-type", "") else raw.decode(errors="replace")
        return response.status, head, body
    finally:
        connection.close()


def assert_public(body, *, code=""):
    text = json.dumps(body, ensure_ascii=False)
    for forbidden in ("password_hash", "password_salt", "token_hash", "code_hash", "otp_hash"):
        assert forbidden not in text
    if code:
        assert code not in text


def login(env, username, password, **fields):
    status, headers, body = request(env.port, "POST", API + "/auth/login",
                                    {"username": username, "password": password, **fields})
    assert status == 200, body
    assert_public(body)
    return headers["set-cookie"].split(";", 1)[0], body


def register(env, **extra):
    phone = f"139{next(env.phone_sequence):08d}"
    status, _, sent = request(env.port, "POST", API + "/auth/sms-code", {"phone": phone})
    assert status == 200, sent
    code = env.sms.messages[phone]
    assert code and code.isdigit()
    assert_public(sent, code=code)
    status, headers, body = request(env.port, "POST", API + "/auth/register", {
        "phone": phone, "code": code, "password": PASSWORD,
        "accepted": True, "agreement_version": AGREEMENT, **extra,
    })
    assert status == 200, body
    assert body["account"]["role"] == "registered_member"
    assert not body["account"].get("bound_channel_id")
    assert body["next_url"] == "/demo2/membership"
    assert_public(body, code=code)
    cookie = headers["set-cookie"].split(";", 1)[0]
    assert "HttpOnly" in headers["set-cookie"]
    assert "SameSite=Lax" in headers["set-cookie"]
    return SimpleNamespace(phone=phone, code=code, cookie=cookie, account=body["account"])


@contextmanager
def isolated_server(root: Path, *, configured_sms: bool):
    membership_module = importlib.import_module("src.rehab_affect.demo2_membership_store")
    # Each handler needs its own globals while both module-scoped fixtures live.
    # Patching the imported server module lets requests cross-wire their loaders
    # and assets, and non-LIFO fixture teardown can restore another fixture's stub.
    # Load the same production source into a private namespace; do not replace
    # the canonical module in sys.modules or modify process-wide environment.
    spec = importlib.util.spec_from_file_location(
        f"{server.__package__}._membership_security_server", server.__file__
    )
    assert spec is not None and spec.loader is not None
    private_server = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(private_server)
    records = Demo2StudentRecordStore(root / "qa.sqlite3", root / "documents")
    records.set_seeded_pilot_passwords(records.db_path, {
        **{f"t{i}": PILOT_PREFIX + f"school_uploader_{i:02d}" for i in range(1, 5)},
        "admin": PILOT_PREFIX + "company_admin",
    })
    sms = CapturingSMS()
    membership = membership_module.Demo2MembershipStore(records, sms_sender=sms if configured_sms else None)
    private_server.get_demo2_student_store = lambda: records
    reads = []

    def legacy_payload(*args, **kwargs):
        reads.append("legacy_payload")
        return {"students": [], "qa_marker": MARKER}

    private_server.load_seewo_demo2 = legacy_payload
    private_server.load_seewo_student_demo = legacy_payload
    private_server.load_teacher_reviews = legacy_payload
    private_server.report_writer_status = legacy_payload
    private_server.render_seewo_demo2_html = lambda: f"<html>{MARKER}</html>"
    private_server.render_seewo_student_demo_html = lambda: f"<html>{MARKER}</html>"
    # Separate route/role checks from the frontend's concurrent implementation.
    private_server._render_demo2_portal_page = lambda page, account=None: f"<html>{page}</html>"
    asset1, asset2 = root / "legacy_assets", root / "demo2_assets"
    for relative in ("analysis.json", "lesson_audio_8k_mono.wav", "lesson_sample_contact_sheet.jpg", "frames/frame.jpg"):
        target = asset1 / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(json.dumps({"marker": MARKER}).encode() if target.suffix == ".json" else MARKER.encode())
    target = asset2 / "fixture/frame.jpg"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(f"{MARKER}:{root.name}".encode())
    private_server.SEEWO_STUDENT_DEMO_OUTPUT_DIR = asset1
    private_server.SEEWO_DEMO2_OUTPUT_DIR = asset2
    handler = private_server.create_handler(scenario_dir=root, model_path=root / "unused.json",
                                           policy_name="rule", membership_store=membership)
    httpd = private_server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    env = SimpleNamespace(port=httpd.server_port, records=records, membership=membership,
                          sms=sms, reads=reads, phone_sequence=itertools.count(1001))
    try:
        yield env
    finally:
        httpd.shutdown()
        httpd.server_close()
        worker.join(timeout=5)
        assert not worker.is_alive()


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    with isolated_server(tmp_path_factory.mktemp("membership_security"), configured_sms=True) as value:
        value.member = register(value)
        value.pilot_cookie, _ = login(value, "t1", PILOT_PREFIX + "school_uploader_01")
        value.admin_cookie, _ = login(value, "admin", PILOT_PREFIX + "company_admin")
        yield value


@pytest.fixture(scope="module")
def disabled_env(tmp_path_factory):
    with isolated_server(tmp_path_factory.mktemp("membership_unconfigured"), configured_sms=False) as value:
        yield value


@pytest.fixture(scope="module")
def active_member(env):
    """Local entitlement-state fixture, not a provider payment or production order."""
    member = register(env)
    with sqlite3.connect(env.records.db_path) as connection:
        connection.execute("UPDATE demo2_memberships SET status='active', expires_at='2099-01-01T00:00:00+00:00' WHERE account_id=?", (member.account["account_id"],))
    return member


@pytest.mark.parametrize("close_first", [0, 1], ids=["creation_order", "reverse_order"])
def test_isolated_servers_do_not_crosswire_or_leak_globals(tmp_path, close_first):
    global_names = (
        "get_demo2_student_store", "load_seewo_demo2", "load_seewo_student_demo",
        "load_teacher_reviews", "report_writer_status", "render_seewo_demo2_html",
        "render_seewo_student_demo_html", "_render_demo2_portal_page",
        "SEEWO_STUDENT_DEMO_OUTPUT_DIR", "SEEWO_DEMO2_OUTPUT_DIR",
    )
    originals = {name: getattr(server, name) for name in global_names}
    original_prefix = os.environ.get("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX")

    def assert_unchanged():
        for name, original in originals.items():
            assert getattr(server, name) is original, name
        assert os.environ.get("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX") == original_prefix

    with ExitStack() as cleanup:
        lifetimes = [cleanup.enter_context(ExitStack()) for _ in range(2)]
        values = [lifetime.enter_context(isolated_server(tmp_path / str(i), configured_sms=i == 0))
                  for i, lifetime in enumerate(lifetimes)]
        assert_unchanged()
        cookies = [login(value, "t1", PILOT_PREFIX + "school_uploader_01")[0] for value in values]
        for i, value in enumerate(values):
            other = values[1 - i]
            assert request(value.port, "GET", API + "/auth/me", cookie=cookies[1 - i])[0] == 401
            before_own, before_other = len(value.reads), len(other.reads)
            assert request(value.port, "GET", "/api/seewo_student_demo2", cookie=cookies[i])[0] == 410
            assert len(value.reads) == before_own
            assert len(other.reads) == before_other
            context = {"city": "上海市", "district": "青浦区", "school_name": f"隔离验收学校{i}"}
            assert request(value.port, "POST", API + "/school/context", context, cookie=cookies[i])[0] == 200
            scoped = request(value.port, "GET", API + "/school/context", cookie=cookies[i])
            assert scoped[0] == 200 and scoped[2]["context"]["school_name"] == context["school_name"]
            config = request(value.port, "GET", API + "/membership/config")[2]["config"]
            assert config["sms_available"] is (i == 0)
            status, _, asset = request(value.port, "GET", "/assets/seewo_demo2/fixture/frame.jpg", cookie=cookies[i])
            assert status == 410 and MARKER not in json.dumps(asset)
        lifetimes[close_first].close()
        assert_unchanged()
        survivor = 1 - close_first
        assert request(values[survivor].port, "GET", "/seewo_student_demo2", cookie=cookies[survivor])[0] == 200
        before = len(values[survivor].reads)
        assert request(values[survivor].port, "GET", "/api/seewo_student_demo2", cookie=cookies[survivor])[0] == 410
        assert len(values[survivor].reads) == before
        scoped = request(values[survivor].port, "GET", API + "/school/context", cookie=cookies[survivor])
        assert scoped[0] == 200 and scoped[2]["context"]["school_name"] == f"隔离验收学校{survivor}"
        status, _, asset = request(values[survivor].port, "GET", "/assets/seewo_demo2/fixture/frame.jpg", cookie=cookies[survivor])
        assert status == 410 and MARKER not in json.dumps(asset)
    assert_unchanged()


def test_real_otp_registration_phone_login_and_automatic_session(env):
    member = env.member
    status, _, body = request(env.port, "GET", API + "/auth/me", cookie=member.cookie)
    assert status == 200
    assert body["account"]["account_id"] == member.account["account_id"]
    assert body["account"]["role"] == "registered_member"
    phone_cookie, logged_in = login(env, member.phone, PASSWORD, role="school_uploader")
    assert logged_in["next_url"] == "/demo2/membership"
    assert request(env.port, "GET", "/demo2/membership", cookie=phone_cookie)[0] == 200
    status, _, body = request(env.port, "GET", API + "/membership", cookie=phone_cookie)
    assert status == 200
    assert body["membership"]["status"] == "inactive"
    assert body["membership"]["school_access"] is False
    assert body["membership"]["orders"] == []
    assert_public(body)
    with sqlite3.connect(env.records.db_path) as connection:
        row = connection.execute("SELECT role,bound_channel_id,password_hash FROM platform_accounts WHERE username=?", (member.phone,)).fetchone()
    assert row and row[0] == "registered_member" and row[1] is None
    assert row[2] != PASSWORD


def test_registered_member_wrong_password_and_admin_role_cannot_login(env):
    for password, role, expected in (("wrong-password", "school_uploader", 401), (PASSWORD, "company_admin", 403)):
        status, headers, _ = request(env.port, "POST", API + "/auth/login", {
            "username": env.member.phone, "password": password, "role": role,
        })
        assert status == expected
        assert "set-cookie" not in headers


@pytest.mark.parametrize("path", LEGACY_GET + SCHOOL_PAGES + tuple(API + p for p in SCHOOL_GET))
@pytest.mark.parametrize("active", [False, True], ids=["inactive", "active"])
def test_registered_member_cannot_read_school_or_legacy_student_data(env, active_member, path, active):
    before = len(env.reads)
    member = active_member if active else env.member
    status, _, body = request(env.port, "GET", path, cookie=member.cookie)
    assert status == 403, (path, status)
    assert MARKER not in json.dumps(body)
    assert len(env.reads) == before, "Authorization must precede analysis loading/rebuilding"


@pytest.mark.parametrize("path", LEGACY_GET)
def test_anonymous_legacy_student_api_and_assets_require_authentication(env, path):
    before = len(env.reads)
    status, _, body = request(env.port, "GET", path)
    assert status == 401, (path, status)
    assert MARKER not in json.dumps(body)
    assert len(env.reads) == before


@pytest.mark.parametrize("path", LEGACY_POST + tuple(API + p for p in SCHOOL_POST))
@pytest.mark.parametrize("identity", ["anonymous", "inactive", "active"])
def test_membership_never_grants_student_writes(env, active_member, path, identity):
    cookie = {"anonymous": "", "inactive": env.member.cookie, "active": active_member.cookie}[identity]
    status, _, body = request(env.port, "POST", path, {
        "course_id": "fixture", "student_id": "fixture", "task_id": "fixture",
        "security_confirmed": True, "channel_id": "channel_1", "role": "company_admin",
        "account_id": env.member.account["account_id"], "reviews": {}, "paid": True,
    }, cookie=cookie)
    assert status == (401 if identity == "anonymous" else 403), (path, status)
    assert MARKER not in json.dumps(body)


def test_unconfigured_sms_returns_503_without_otp_or_account(disabled_env):
    with sqlite3.connect(disabled_env.records.db_path) as connection:
        before = connection.execute("SELECT COUNT(*) FROM platform_accounts").fetchone()[0]
    status, _, body = request(disabled_env.port, "POST", API + "/auth/sms-code", {"phone": "13900009001"})
    assert status == 503, body
    assert body["error"]["code"] == "sms_not_configured"
    assert body.get("ok") is not True
    assert disabled_env.sms.messages == {}
    assert_public(body)
    assert not any(k in body for k in ("otp", "sms_code", "verification_code"))
    with sqlite3.connect(disabled_env.records.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM platform_accounts").fetchone()[0] == before
        assert connection.execute("SELECT COUNT(*) FROM demo2_membership_otps").fetchone()[0] == 0


def test_membership_config_public_but_membership_and_admin_data_protected(env):
    status, _, body = request(env.port, "GET", API + "/membership/config")
    assert status == 200
    assert body["config"]["payment_available"] is False
    assert all(plan["available"] is False for plan in body["config"]["plans"])
    assert_public(body)
    assert request(env.port, "GET", API + "/membership")[0] == 401
    assert request(env.port, "GET", API + "/admin/memberships")[0] == 401
    assert request(env.port, "GET", API + "/admin/memberships", cookie=env.pilot_cookie)[0] == 403
    status, _, body = request(env.port, "GET", API + "/admin/memberships", cookie=env.admin_cookie)
    assert status == 200
    assert_public(body)


@pytest.mark.parametrize("identity", ["pilot", "admin"])
def test_existing_school_identities_use_scoped_routes_not_retired_global_data(env, identity):
    cookie = env.pilot_cookie if identity == "pilot" else env.admin_cookie
    assert request(env.port, "GET", "/seewo_student_demo2", cookie=cookie)[0] == 200
    for path in ("/api/seewo_student_demo2", "/assets/seewo_demo2/fixture/frame.jpg"):
        status, _, body = request(env.port, "GET", path, cookie=cookie)
        assert status == 410
        assert body["error"]["code"] == "legacy_data_reimport_required"
        assert MARKER not in json.dumps(body)
    if identity == "pilot":
        assert request(env.port, "GET", API + "/upload/workspace?course_id=fixture", cookie=cookie)[0] == 200
        assert request(env.port, "GET", "/demo2/admin", cookie=cookie)[0] == 403
    else:
        assert request(env.port, "GET", "/demo2/admin", cookie=cookie)[0] == 200
        assert request(env.port, "GET", "/demo2/upload", cookie=cookie)[0] == 403


def test_registered_member_logout_revokes_only_its_session(env):
    cookie, _ = login(env, env.member.phone, PASSWORD)
    assert request(env.port, "POST", API + "/auth/logout", {}, cookie=cookie)[0] == 200
    assert request(env.port, "GET", API + "/membership", cookie=cookie)[0] == 401
    assert request(env.port, "GET", API + "/auth/me", cookie=env.member.cookie)[0] == 200


@pytest.mark.parametrize("injected", [
    {"plan_id": "monthly"},
    {"plan_id": "monthly", "paid": True, "status": "paid", "price_cents": 1},
    {"plan_id": "yearly", "account_id": "company_admin", "membership_status": "active", "payment_available": True},
])
def test_unconfigured_payment_never_creates_order_or_accepts_client_paid(env, injected):
    status, _, body = request(env.port, "POST", API + "/membership/orders", injected, cookie=env.member.cookie)
    # Malformed payment/price overrides are rejected before provider availability.
    assert status == (503 if set(injected) == {"plan_id"} else 400), body
    assert body["error"]["code"] == ("payment_not_configured" if status == 503 else "invalid_request")
    assert body.get("ok") is not True
    assert "order" not in body
    current = request(env.port, "GET", API + "/membership", cookie=env.member.cookie)[2]["membership"]
    assert current["status"] == "inactive" and current["orders"] == []
    assert current["school_access"] is False and current["payment_available"] is False
    with sqlite3.connect(env.records.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM demo2_membership_orders").fetchone()[0] == 0


def test_orders_require_login_and_query_account_id_cannot_switch_members(env, active_member):
    assert request(env.port, "POST", API + "/membership/orders", {"plan_id": "monthly", "paid": True})[0] == 401
    status, _, body = request(env.port, "GET", API + "/membership?account_id=" + active_member.account["account_id"], cookie=env.member.cookie)
    assert status == 200
    assert body["membership"]["account_id"] == env.member.account["account_id"]
    assert body["membership"]["status"] == "inactive"


@pytest.mark.parametrize("phone", [None, 13900001001, "", "123", "+8613900001001", "12900001001", "13900001001' OR 1=1--"])
def test_bad_phone_never_calls_sms_sender(env, phone):
    before = dict(env.sms.messages)
    status, _, body = request(env.port, "POST", API + "/auth/sms-code", {"phone": phone})
    expected = "invalid_phone" if isinstance(phone, str) else "invalid_request"
    assert status == 400 and body["error"]["code"] == expected
    assert env.sms.messages == before


@pytest.mark.parametrize("change", [
    {"accepted": False}, {"accepted": "true"}, {"accepted": 1},
    {"agreement_version": "2026-09-08"}, {"role": "company_admin"},
    {"bound_channel_id": "channel_1"}, {"paid": True}, {"password": "12345678"},
    {"password": "abcdefgh"}, {"password": "short1"},
])
def test_registration_rejects_missing_consent_and_privilege_fields(env, change):
    payload = {"phone": env.member.phone, "code": env.member.code, "password": PASSWORD,
               "accepted": True, "agreement_version": AGREEMENT, **change}
    status, headers, body = request(env.port, "POST", API + "/auth/register", payload)
    assert status == 400, body
    assert "set-cookie" not in headers
    assert "account" not in body


def test_consumed_otp_cannot_create_second_account_or_session(env):
    status, headers, body = request(env.port, "POST", API + "/auth/register", {
        "phone": env.member.phone, "code": env.member.code, "password": PASSWORD,
        "accepted": True, "agreement_version": AGREEMENT,
    })
    assert status == 400 and body["error"]["code"] == "code_unavailable"
    assert "set-cookie" not in headers


def test_otp_wrong_attempt_budget_cooldown_and_expiry(env):
    phone = f"139{next(env.phone_sequence):08d}"
    assert request(env.port, "POST", API + "/auth/sms-code", {"phone": phone})[0] == 200
    code = env.sms.messages[phone]
    again = request(env.port, "POST", API + "/auth/sms-code", {"phone": phone})
    assert again[0] == 429 and again[2]["error"]["code"] == "code_cooldown"
    wrong = "000000" if code != "000000" else "111111"
    payload = {"phone": phone, "code": wrong, "password": PASSWORD, "accepted": True, "agreement_version": AGREEMENT}
    responses = [request(env.port, "POST", API + "/auth/register", payload) for _ in range(5)]
    assert [item[0] for item in responses] == [400, 400, 400, 400, 429]
    assert request(env.port, "POST", API + "/auth/register", {**payload, "code": code})[0] == 429
    with sqlite3.connect(env.records.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM platform_accounts WHERE username=?", (phone,)).fetchone()[0] == 0
    phone2 = f"139{next(env.phone_sequence):08d}"
    assert request(env.port, "POST", API + "/auth/sms-code", {"phone": phone2})[0] == 200
    with sqlite3.connect(env.records.db_path) as connection:
        connection.execute("UPDATE demo2_membership_otps SET expires_at=0 WHERE status='sent'")
    status, _, body = request(env.port, "POST", API + "/auth/register", {
        **payload, "phone": phone2, "code": env.sms.messages[phone2],
    })
    assert status == 400 and body["error"]["code"] == "code_expired"


def test_concurrent_same_otp_creates_only_one_member_and_session(env):
    phone = f"139{next(env.phone_sequence):08d}"
    assert request(env.port, "POST", API + "/auth/sms-code", {"phone": phone})[0] == 200
    payload = {"phone": phone, "code": env.sms.messages[phone], "password": PASSWORD,
               "accepted": True, "agreement_version": AGREEMENT}
    barrier = threading.Barrier(4)

    def attempt(_):
        barrier.wait()
        return request(env.port, "POST", API + "/auth/register", payload)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, range(4)))
    assert sorted(item[0] for item in results) == [200, 400, 400, 400]
    assert sum("set-cookie" in item[1] for item in results) == 1
    with sqlite3.connect(env.records.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM platform_accounts WHERE username=?", (phone,)).fetchone()[0] == 1


def test_otp_password_and_provider_data_absent_from_audit(env):
    with sqlite3.connect(env.records.db_path) as connection:
        logs = json.dumps(connection.execute("SELECT * FROM audit_logs").fetchall())
        membership_logs = json.dumps(connection.execute("SELECT * FROM audit_logs WHERE actor='membership_service'").fetchall())
        otp = connection.execute("SELECT code_hash,code_salt FROM demo2_membership_otps ORDER BY rowid LIMIT 1").fetchone()
    assert PASSWORD not in logs
    assert env.member.code not in logs
    assert env.member.phone not in membership_logs, "Membership audit events must mask phone numbers"
    assert otp[0] != env.member.code and otp[1]


def test_unconfigured_sms_does_not_allow_register_with_forged_code(disabled_env):
    status, headers, body = request(disabled_env.port, "POST", API + "/auth/register", {
        "phone": "13900009001", "code": "123456", "password": PASSWORD,
        "accepted": True, "agreement_version": AGREEMENT,
    })
    assert status == 503 and body["error"]["code"] == "sms_not_configured"
    assert "set-cookie" not in headers and "account" not in body
    with sqlite3.connect(disabled_env.records.db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM demo2_memberships").fetchone()[0] == 0


@pytest.mark.parametrize("spoof", [{"code": "123456"}, {"sms_available": True}, {"source_key": "unlimited"}])
def test_sms_client_cannot_supply_otp_configuration_or_abuse_source(env, spoof):
    before = dict(env.sms.messages)
    status, _, _ = request(env.port, "POST", API + "/auth/sms-code", {"phone": "13900009901", **spoof})
    assert status == 400
    assert env.sms.messages == before


def test_sms_provider_failure_is_safe_and_does_not_leave_usable_otp(env, monkeypatch):
    phone = f"139{next(env.phone_sequence):08d}"
    delivered = []

    def failing_sender(phone_number, code):
        delivered.append(code)
        raise RuntimeError(f"QA_PROVIDER_SECRET D:/private/{code}")

    monkeypatch.setattr(env.membership, "_sms_sender", failing_sender)
    status, _, body = request(env.port, "POST", API + "/auth/sms-code", {"phone": phone})
    assert status == 503 and body["error"]["code"] == "sms_send_failed"
    assert len(delivered) == 1
    assert_public(body, code=delivered[0])
    assert "QA_PROVIDER_SECRET" not in json.dumps(body)
    status, headers, body = request(env.port, "POST", API + "/auth/register", {
        "phone": phone, "code": delivered[0], "password": PASSWORD,
        "accepted": True, "agreement_version": AGREEMENT,
    })
    assert status == 400 and body["error"]["code"] == "code_unavailable"
    assert "set-cookie" not in headers


def test_expired_member_session_is_not_a_valid_membership_or_legacy_login(env):
    cookie, _ = login(env, env.member.phone, PASSWORD)
    token = cookie.split("=", 1)[1]
    with sqlite3.connect(env.records.db_path) as connection:
        connection.execute("UPDATE account_sessions SET expires_at='2000-01-01T00:00:00+00:00' WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
    for path in (API + "/auth/me", API + "/membership", "/api/seewo_student_demo", "/assets/seewo_xiaoyudi_demo/analysis.json"):
        assert request(env.port, "GET", path, cookie=cookie)[0] == 401
    status, headers, _ = request(env.port, "GET", "/demo2/membership", cookie=cookie)
    assert status == 302 and headers["location"] == "/demo2/login"
