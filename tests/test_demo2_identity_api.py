"""Identity HTTP contracts: synthetic stores, loopback servers, no face model or DB."""

from __future__ import annotations

import base64
import http.client
import json
import sys
import threading
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from urllib.parse import urlencode

import pytest

from src.rehab_affect import demo2_manager_gateway as gateway
from src.rehab_affect import scenario_lab_server as backend


PREFIX = "/api/v1/demo2/identity"
FRAME_QUERY = "task_id=task-one&frame_key=s0_f0&frame_revision=revision-1"
JPEG = b"\xff\xd8synthetic-test-frame\xff\xd9"
STUDENT = {"display_name": "Synthetic pupil", "student_code": "S1", "class_name": "Class A", "note": ""}
BINDING = {"task_id": "task-one", "frame_key": "s0_f0", "frame_revision": "revision-1",
           "role": "student", "student_id": "student-one", "bbox": {"x": .1, "y": .2, "width": .3, "height": .4}}
REVOKE = {"task_id": "task-one", "binding_id": "binding-one", "reason": "Correction"}
TASK_SCHOOL = {"task_id": "task-one", "expected_scope_key": "account-one", "confirmed": True}
WRITES = [("students", STUDENT, "create_student", "student"),
          ("bindings", BINDING, "save_binding", "binding"),
          ("bindings/revoke", REVOKE, "revoke_binding", "binding"),
          ("task-school", TASK_SCHOOL, "confirm_task_school", "workspace")]
READS = ["roster", "workspace?task_id=task-one", "frame?" + FRAME_QUERY,
         "export?task_id=task-one", "detect?" + FRAME_QUERY]


class IdentityError(ValueError):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class Records:
    """Deliberately has no _connect: accidental production store use must fail."""

    def __init__(self):
        self.accounts = {
            "school": {"account_id": "account-one", "username": "fixture-t1", "role": "school_uploader", "bound_channel_id": "channel_1"},
            "other": {"account_id": "account-two", "username": "fixture-t2", "role": "school_uploader", "bound_channel_id": "channel_2"},
            "admin": {"account_id": "account-admin", "username": "fixture-admin", "role": "company_admin"},
            "member": {"account_id": "account-member", "username": "fixture-member", "role": "registered_member"},
        }

    def account_from_session(self, token):
        role = token.removeprefix("session-")
        if role not in self.accounts:
            raise ValueError("Session expired or unknown")
        return dict(self.accounts[role])

    def account_upload_workspace(self, token, course_id):
        return {"course_id": course_id, "tasks": [], "students": [{"student_id": "GLOBAL-LEGACY-SECRET"}],
                "channel": {"channel_id": self.account_from_session(token)["bound_channel_id"]}}


class Identities:
    def __init__(self, records, frame):
        self.records, self.frame = records, frame
        self.calls, self.errors = [], {}

    def _call(self, name, token, *args):
        self.calls.append((name, token, *args))
        if name in self.errors:
            raise self.errors[name]
        return self.records.account_from_session(token)

    @staticmethod
    def _task(account, task_id):
        if task_id == "expired-task":
            raise IdentityError(410, "media_expired", "原视频已到期")
        if task_id != "task-one":
            raise IdentityError(404, "task_not_found", "任务不存在")
        if account["role"] != "company_admin" and account["account_id"] != "account-one":
            raise IdentityError(403, "task_forbidden", "无权访问此任务")

    def roster(self, token):
        account = self._call("roster", token)
        return {"students": [{"student_id": "student-one", "display_name": "Scoped pupil"}],
                "scope_key": account["account_id"], "school_context": {"school_name": "Synthetic school"}}

    def create_student(self, token, payload):
        self._call("create_student", token, payload)
        return {"student_id": "student-one", **payload}

    def workspace(self, token, task_id):
        account = self._call("workspace", token, task_id)
        self._task(account, task_id)
        return {"task_id": task_id, "students": [], "bindings": [], "frames": [],
                "frame_revision": "revision-1", "can_edit": account["role"] == "school_uploader",
                "media_available": True, "summary": {}}

    def save_binding(self, token, payload):
        account = self._call("save_binding", token, payload)
        self._task(account, payload["task_id"])
        return {"binding_id": "binding-one", **payload, "confirmed_by": account["username"], "status": "active"}

    def revoke_binding(self, token, payload):
        account = self._call("revoke_binding", token, payload)
        self._task(account, payload["task_id"])
        return {**payload, "status": "revoked"}

    def confirm_task_school(self, token, payload):
        account = self._call("confirm_task_school", token, payload)
        self._task(account, payload["task_id"])
        if payload.get("confirmed") is not True:
            raise IdentityError(400, "school_confirmation_required", "请明确确认任务所属学校")
        return {"task_id": payload["task_id"], "scope_key": payload["expected_scope_key"],
                "school_context": {"school_name": "Synthetic school"}, "can_edit": True}

    def frame_file(self, token, task_id, frame_key, revision):
        account = self._call("frame_file", token, task_id, frame_key, revision)
        self._task(account, task_id)
        if frame_key != "s0_f0" or revision != "revision-1":
            raise IdentityError(409, "frame_revision_conflict", "采样帧版本无效")
        return self.frame, "image/jpeg"

    def export(self, token, task_id):
        account = self._call("export", token, task_id)
        self._task(account, task_id)
        return {"task_id": task_id, "bindings": [], "identity_scope": "single_sample_frame"}


def request(httpd, path, *, role=None, method="GET", payload=None, headers=None, raw=None):
    outgoing = {"Host": f"127.0.0.1:{httpd.server_port}", "Connection": "close",
                "Content-Type": "application/json", **(headers or {})}
    if role is not None:
        outgoing["Cookie"] = f"rehab_demo2_session=session-{role}"
    body = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else b"")
    outgoing["Content-Length"] = str(len(body))
    wire = (f"{method} {path} HTTP/1.1\r\n" +
            "".join(f"{key}: {value}\r\n" for key, value in outgoing.items()) + "\r\n").encode("ascii") + body
    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
    try:
        # Send one small request atomically: immediate 401/403 must not race
        # http.client's separate header/body writes on Windows. Never retry.
        connection.connect()
        connection.sock.sendall(wire)
        response = http.client.HTTPResponse(connection.sock, method=method)
        response.begin()
        data = response.read()
        result = json.loads(data) if data and "application/json" in response.getheader("Content-Type", "") else data
        return response.status, dict(response.getheaders()), result
    finally:
        connection.close()


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    # Keep inference-budget tests independent of cache hits; upgrade tests cover caching.
    monkeypatch.setattr(backend, "DEMO2_IDENTITY_DETECT_CACHE_TTL", 0)
    records = Records()
    frame = tmp_path / "trusted-frame.jpg"
    frame.write_bytes(JPEG)
    identities = Identities(records, frame)
    constructed, detections, rendered, servers, threads = [], [], [], [], []
    module = ModuleType("src.rehab_affect.demo2_identity_store")
    module.IdentityError = IdentityError

    def factory(store):
        constructed.append(store)
        assert store is records
        return identities

    module.Demo2IdentityStore = factory
    monkeypatch.setitem(sys.modules, module.__name__, module)
    pages = ModuleType("src.rehab_affect.demo2_identity")

    def render(page, account):
        rendered.append((page, account["role"]))
        return f"<html>{page}</html>"

    pages.render_students = lambda account: render("students", account)
    pages.render_identity = lambda account: render("identity", account)
    monkeypatch.setitem(sys.modules, pages.__name__, pages)
    detector = ModuleType("src.rehab_affect.demo2_face_detection")

    def detect(path):
        detections.append(path)
        assert path == frame
        return {"available": True, "faces": [], "identity_recognition": False}

    detector.detect_faces = detect
    monkeypatch.setitem(sys.modules, detector.__name__, detector)
    monkeypatch.setattr(backend, "get_demo2_student_store", lambda: records)

    def serve(httpd):
        servers.append(httpd)
        thread = threading.Thread(target=lambda: httpd.serve_forever(poll_interval=.01), daemon=True)
        threads.append(thread)
        thread.start()
        return httpd

    def start(*, inject=True):
        kwargs = {"identity_store": identities} if inject else {}
        handler = backend.create_handler(scenario_dir=tmp_path, model_path=tmp_path / "unused", policy_name="rule", **kwargs)
        return serve(backend.ThreadingHTTPServer(("127.0.0.1", 0), handler))

    httpd = start()
    result = SimpleNamespace(httpd=httpd, records=records, identities=identities, constructed=constructed,
                             detections=detections, rendered=rendered, detector=detector, frame=frame,
                             start=start, serve=serve)
    try:
        yield result
    finally:
        for httpd in reversed(servers):
            httpd.shutdown()
            httpd.server_close()
        for thread in threads:
            thread.join(3)


@pytest.mark.parametrize("suffix", READS)
@pytest.mark.parametrize("role,status", [(None, 401), ("expired", 401), ("member", 403)])
def test_identity_reads_fail_closed_before_store_or_detector(rig, suffix, role, status):
    actual, _, body = request(rig.httpd, PREFIX + "/" + suffix, role=role)
    assert actual == status
    assert body["ok"] is False and body["error"]["code"]
    assert rig.identities.calls == []
    assert rig.detections == []


@pytest.mark.parametrize("suffix,payload,method,envelope", WRITES)
@pytest.mark.parametrize("role,status", [(None, 401), ("member", 403), ("admin", 403)])
def test_identity_writes_reject_non_uploaders_before_store(rig, suffix, payload, method, envelope, role, status):
    actual, _, body = request(rig.httpd, PREFIX + "/" + suffix, role=role, method="POST", payload=payload)
    assert actual == status
    assert body["ok"] is False
    assert rig.identities.calls == []


@pytest.mark.parametrize("suffix,payload,method,envelope", WRITES)
def test_uploader_write_payloads_and_envelopes(rig, suffix, payload, method, envelope):
    status, headers, body = request(rig.httpd, PREFIX + "/" + suffix, role="school", method="POST", payload=payload)
    assert status in {200, 201}
    assert body["ok"] is True and isinstance(body[envelope], dict)
    assert rig.identities.calls == [(method, "session-school", payload)]
    assert "no-store" in headers["Cache-Control"]


@pytest.mark.parametrize("confirmed", [None, False, "true", 1])
def test_task_school_does_not_invent_explicit_confirmation(rig, confirmed):
    payload = {key: value for key, value in TASK_SCHOOL.items() if key != "confirmed"}
    if confirmed is not None:
        payload["confirmed"] = confirmed
    status, _, body = request(rig.httpd, PREFIX + "/task-school", role="school", method="POST", payload=payload)
    assert status == 400 and body["error"]["code"] == "school_confirmation_required"
    assert rig.identities.calls == [("confirm_task_school", "session-school", payload)]


@pytest.mark.parametrize("status,code", [(409, "school_scope_changed"), (409, "task_school_locked"),
                                        (410, "media_unavailable")])
def test_task_school_preserves_repository_conflict_and_expiry_errors(rig, status, code):
    rig.identities.errors["confirm_task_school"] = IdentityError(status, code, "请刷新任务后重新确认")
    actual, _, body = request(rig.httpd, PREFIX + "/task-school", role="school", method="POST", payload=TASK_SCHOOL)
    assert actual == status and body["error"]["code"] == code and "workspace" not in body
    assert rig.identities.calls == [("confirm_task_school", "session-school", TASK_SCHOOL)]


@pytest.mark.parametrize("suffix", ["workspace?task_id=task-one", "frame?" + FRAME_QUERY,
                                   "export?task_id=task-one", "detect?" + FRAME_QUERY])
def test_task_scoped_reads_delegate_ownership_and_admin_is_read_only(rig, suffix):
    status, _, body = request(rig.httpd, PREFIX + "/" + suffix, role="other")
    assert status == 403 and body["error"]["code"] == "task_forbidden"
    assert not rig.detections
    for role in ("school", "admin"):
        status, _, body = request(rig.httpd, PREFIX + "/" + suffix, role=role)
        assert status == 200
        if suffix.startswith("workspace"):
            assert body["workspace"]["can_edit"] is (role == "school")


@pytest.mark.parametrize("suffix,payload,method,envelope", WRITES[1:])
def test_foreign_task_mutations_are_rejected_by_repository(rig, suffix, payload, method, envelope):
    status, _, body = request(rig.httpd, PREFIX + "/" + suffix, role="other", method="POST", payload=payload)
    assert status == 403
    assert body["error"]["code"] == "task_forbidden"


def test_roster_is_school_only_and_keeps_roster_envelope(rig):
    assert request(rig.httpd, PREFIX + "/roster", role="admin")[0] == 403
    assert not rig.identities.calls
    status, _, body = request(rig.httpd, PREFIX + "/roster", role="school")
    assert status == 200
    assert body["roster"]["students"][0]["student_id"] == "student-one"
    assert rig.identities.calls == [("roster", "session-school")]


@pytest.mark.parametrize("page", ["/demo2/students", "/demo2/identity?task_id=task-one"])
def test_identity_pages_require_login_and_deny_members(rig, page):
    status, headers, _ = request(rig.httpd, page)
    assert status == 302 and headers["Location"] == "/demo2/login"
    assert request(rig.httpd, page, role="member")[0] == 403
    assert not rig.rendered


def test_page_renderers_are_lazy_and_task_page_checks_ownership(rig):
    assert request(rig.httpd, "/demo2/students", role="admin")[0] == 403
    assert request(rig.httpd, "/demo2/students", role="school")[0] == 200
    assert request(rig.httpd, "/demo2/identity?task_id=task-one", role="other")[0] == 403
    assert rig.rendered == [("students", "school_uploader")]
    assert request(rig.httpd, "/demo2/identity?task_id=task-one", role="admin")[0] == 200
    assert rig.rendered[-1] == ("identity", "company_admin")
    assert rig.identities.calls[-1] == ("workspace", "session-admin", "task-one")


def test_frame_is_protected_no_store_jpeg_and_export_is_json_attachment(rig):
    status, headers, body = request(rig.httpd, PREFIX + "/frame?" + FRAME_QUERY, role="school")
    assert status == 200 and body == JPEG
    assert headers["Content-Type"] == "image/jpeg"
    assert "no-store" in headers["Cache-Control"]
    status, headers, body = request(rig.httpd, PREFIX + "/export?task_id=task-one", role="school")
    assert status == 200
    assert body == {"task_id": "task-one", "bindings": [], "identity_scope": "single_sample_frame"}
    assert "attachment" in headers["Content-Disposition"]
    assert "no-store" in headers["Cache-Control"]
    assert str(rig.frame) not in json.dumps(body)


@pytest.mark.parametrize("suffix", ["frame", "detect"])
def test_frame_expiry_is_checked_before_read_or_detection(rig, suffix):
    path = PREFIX + "/" + suffix + "?" + FRAME_QUERY.replace("task-one", "expired-task")
    status, _, body = request(rig.httpd, path, role="school")
    assert status == 410
    assert body["error"]["code"] == "media_expired"
    assert not rig.detections


def test_repository_revision_conflict_survives_json_translation(rig):
    rig.identities.errors["save_binding"] = IdentityError(409, "frame_revision_conflict", "请刷新采样帧")
    status, _, body = request(rig.httpd, PREFIX + "/bindings", role="school", method="POST", payload=BINDING)
    assert status == 409
    assert body["error"] == {"code": "frame_revision_conflict", "message": "请刷新采样帧"}


@pytest.mark.parametrize("suffix,payload,method,envelope", WRITES)
def test_identity_post_body_is_bounded_before_repository(rig, suffix, payload, method, envelope):
    status, _, body = request(rig.httpd, PREFIX + "/" + suffix, role="school", method="POST",
                              payload={**payload, "note": "x" * (16 * 1024)})
    assert status in {400, 413}
    assert body["ok"] is False
    assert not rig.identities.calls


def test_workspace_replaces_global_legacy_students_with_scoped_roster(rig):
    status, _, body = request(rig.httpd, "/api/v1/demo2/upload/workspace?course_id=course-one", role="school")
    assert status == 200
    assert body["workspace"]["students"] == [{"student_id": "student-one", "display_name": "Scoped pupil"}]
    assert "GLOBAL-LEGACY-SECRET" not in json.dumps(body)


def test_legacy_fake_store_has_no_identity_initialization_or_student_leak(rig):
    httpd = rig.start(inject=False)
    assert rig.constructed == []
    status, _, body = request(httpd, "/api/v1/demo2/upload/workspace?course_id=course-one", role="school")
    assert status == 200 and body["workspace"]["students"] == []
    assert rig.constructed == [] and rig.identities.calls == []
    assert "GLOBAL-LEGACY-SECRET" not in json.dumps(body)


def test_identity_store_initializes_on_first_real_identity_request_only(rig, monkeypatch):
    def never_connect():
        raise AssertionError("Synthetic identity factory must never open a database")

    monkeypatch.setattr(rig.records, "_connect", never_connect, raising=False)
    httpd = rig.start(inject=False)
    assert request(httpd, "/api/v1/demo2/auth/me", role="school")[0] == 200
    assert rig.constructed == []
    assert request(httpd, PREFIX + "/roster", role="school")[0] == 200
    assert request(httpd, PREFIX + "/roster", role="school")[0] == 200
    assert rig.constructed == [rig.records]


def test_missing_school_context_returns_empty_students_with_error(rig):
    rig.identities.errors["roster"] = IdentityError(409, "school_context_required", "请先填写学校信息")
    status, _, body = request(rig.httpd, "/api/v1/demo2/upload/workspace?course_id=course-one", role="school")
    assert status == 200
    workspace = body["workspace"]
    assert workspace["students"] == [] and workspace["roster_error"]["code"] == "school_context_required"
    assert "GLOBAL-LEGACY-SECRET" not in json.dumps(body)


@pytest.mark.parametrize("query", [
    FRAME_QUERY + "&url=https%3A%2F%2Fexample.invalid%2Fportrait.jpg",
    FRAME_QUERY + "&path=D%3A%5Cprivate%5Cportrait.jpg",
    FRAME_QUERY + "&file_path=%2Fetc%2Fpasswd",
    FRAME_QUERY + "&task_id=task-two",
    FRAME_QUERY + "&frame_key=s1_f0",
    FRAME_QUERY + "&frame_revision=revision-2",
    "task_id=task-one&frame_key=s0_f0",
    "task_id=task-one&frame_key=s0_f0&frame_revision=",
])
def test_detect_requires_exact_single_value_frame_query(rig, query):
    status, _, body = request(rig.httpd, PREFIX + "/detect?" + query, role="school")
    assert status == 400
    assert body["ok"] is False
    assert rig.detections == []


@pytest.mark.parametrize("field,value", [("task_id", "../../private"), ("frame_key", "file:///private.jpg"),
                                          ("frame_revision", "D:\\private\\portrait.jpg")])
def test_request_paths_can_never_select_detector_input(rig, field, value):
    query = {"task_id": "task-one", "frame_key": "s0_f0", "frame_revision": "revision-1", field: value}
    assert request(rig.httpd, PREFIX + "/detect?" + urlencode(query), role="school")[0] in {400, 404, 409}
    assert rig.detections == []


def test_detector_receives_only_authorized_trusted_frame_path(rig):
    status, _, body = request(rig.httpd, PREFIX + "/detect?" + FRAME_QUERY, role="school")
    assert status == 200 and body["ok"] is True
    assert body["detection"]["available"] is True
    assert rig.detections == [rig.frame]
    assert rig.identities.calls == [("frame_file", "session-school", "task-one", "s0_f0", "revision-1")] * 2
    assert str(rig.frame) not in json.dumps(body)


def test_missing_detector_model_is_a_safe_unavailable_response(rig, monkeypatch):
    monkeypatch.setattr(rig.detector, "detect_faces", lambda path: {"available": False, "reason": "model_unavailable", "faces": []})
    status, _, body = request(rig.httpd, PREFIX + "/detect?" + FRAME_QUERY, role="school")
    assert status == 200 and body["detection"]["available"] is False
    assert body["detection"]["faces"] == []


def test_detect_per_account_minimum_interval_precedes_model_call(rig):
    path = PREFIX + "/detect?" + FRAME_QUERY
    assert request(rig.httpd, path, role="school")[0] == 200
    status, _, body = request(rig.httpd, path, role="school")
    assert status == 429 and body["error"]["code"] == "detection_rate_limited"
    assert len(rig.detections) == 1
    assert request(rig.httpd, path, role="admin")[0] == 200
    assert len(rig.detections) == 2


def test_detect_window_limit_is_enforced_without_real_waits(rig, monkeypatch):
    monkeypatch.setattr(backend, "DEMO2_IDENTITY_DETECT_MIN_INTERVAL", 0.0)
    httpd = rig.start()
    path = PREFIX + "/detect?" + FRAME_QUERY
    for _ in range(backend.DEMO2_IDENTITY_DETECT_LIMIT):
        assert request(httpd, path, role="school")[0] == 200
    status, _, body = request(httpd, path, role="school")
    assert status == 429 and body["error"]["code"] == "detection_rate_limited"
    assert len(rig.detections) == backend.DEMO2_IDENTITY_DETECT_LIMIT


def test_detect_window_rollover_preserves_minimum_interval(rig, monkeypatch):
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(backend, "time", SimpleNamespace(monotonic=lambda: clock.now))
    path = PREFIX + "/detect?" + FRAME_QUERY
    assert request(rig.httpd, path, role="school")[0] == 200
    clock.now = 59.9
    assert request(rig.httpd, path, role="school")[0] == 200
    clock.now = 60.0
    status, _, body = request(rig.httpd, path, role="school")
    assert status == 429 and body["error"]["code"] == "detection_rate_limited"
    assert len(rig.detections) == 2
    clock.now = 61.9
    assert request(rig.httpd, path, role="school")[0] == 200
    assert len(rig.detections) == 3


def test_detector_exception_releases_slot_and_returns_safe_error(rig, monkeypatch):
    def flaky_detector(path):
        rig.detections.append(path)
        if len(rig.detections) == 1:
            raise RuntimeError("D:/fixture-private/portrait.jpg must never reach clients")
        return {"available": True, "faces": []}

    monkeypatch.setattr(rig.detector, "detect_faces", flaky_detector)
    path = PREFIX + "/detect?" + FRAME_QUERY
    status, _, body = request(rig.httpd, path, role="school")
    assert status == 500 and body["error"]["code"] == "internal_error"
    assert "fixture-private" not in json.dumps(body)
    status, _, body = request(rig.httpd, path, role="admin")
    assert status == 200 and body["detection"]["available"] is True
    assert rig.detections == [rig.frame, rig.frame]


@pytest.mark.parametrize("path", ["/demo2/identity", PREFIX + "/workspace", PREFIX + "/detect"])
@pytest.mark.parametrize("query", ["&".join(f"field{i}=value" for i in range(9)),
                                   "task_id", "task_id=task-one&orphan"])
def test_identity_malformed_or_excessive_query_returns_400_before_store(rig, path, query):
    status, _, body = request(rig.httpd, path + "?" + query, role="school")
    assert status == 400
    assert body["ok"] is False and body["error"]["code"] == "invalid_request"
    assert not rig.identities.calls and not rig.detections and not rig.rendered


def test_detect_concurrency_limit_is_nonblocking_and_released(rig, monkeypatch):
    monkeypatch.setattr(backend, "DEMO2_IDENTITY_DETECT_MIN_INTERVAL", 0.0)
    httpd = rig.start()
    entered, release = threading.Event(), threading.Event()
    outcomes = []

    def blocking_detector(path):
        rig.detections.append(path)
        entered.set()
        assert release.wait(4)
        return {"available": True, "faces": []}

    monkeypatch.setattr(rig.detector, "detect_faces", blocking_detector)
    path = PREFIX + "/detect?" + FRAME_QUERY
    thread = threading.Thread(target=lambda: outcomes.append(request(httpd, path, role="school")), daemon=True)
    thread.start()
    try:
        assert entered.wait(2)
        started = time.monotonic()
        status, _, body = request(httpd, path, role="admin")
        assert time.monotonic() - started < 2
        assert status == 429 and body["error"]["code"] == "detection_busy"
        assert len(rig.detections) == 1
    finally:
        release.set()
        thread.join(5)
    assert outcomes and outcomes[0][0] == 200
    assert request(httpd, path, role="admin")[0] == 200
    assert len(rig.detections) == 2


def test_gateway_identity_routes_are_exact_private_and_keep_invite_session_csrf(rig):
    invite = "identity-fixture-invite-" + "a1B2c3D4" * 6
    proxy = rig.serve(gateway.make_server({"invite_secret": invite,
        "cookie_secret": "identity-fixture-signing-" + "X9y8Z7w6" * 6,
        "expires_at": int(time.time()) + 3600, "upstream_port": rig.httpd.server_port,
        "listen_port": 0}, host="127.0.0.1", port=0))
    origin = f"https://127.0.0.1:{proxy.server_port}"
    for suffix in READS:
        assert request(proxy, PREFIX + "/" + suffix, role="school")[0] in {401, 403}
    assert not rig.identities.calls and not rig.detections
    status, headers, _ = request(proxy, "/__manager/authorize", method="POST", payload={"secret": invite}, headers={"Origin": origin})
    assert status == 303
    invite_cookie = headers["Set-Cookie"].split(";", 1)[0]
    assert request(proxy, PREFIX + "/roster", headers={"Cookie": invite_cookie})[0] == 401
    cookies = invite_cookie + "; rehab_demo2_session=session-school"
    accepted = {"Cookie": cookies, "Origin": origin}
    for suffix in READS:
        assert request(proxy, PREFIX + "/" + suffix, headers=accepted)[0] == 200
    for page in ("/demo2/students", "/demo2/identity?task_id=task-one"):
        assert request(proxy, page, headers=accepted)[0] == 200
    for suffix, payload, _, _ in WRITES:
        before = len(rig.identities.calls)
        status, _, _ = request(proxy, PREFIX + "/" + suffix, method="POST", payload=payload,
                                headers={"Cookie": cookies, "Origin": "https://attacker.invalid"})
        assert status == 403 and len(rig.identities.calls) == before
        assert request(proxy, PREFIX + "/" + suffix, method="POST", payload=payload, headers=accepted)[0] in {200, 201}
    for path in (PREFIX + "/unknown", PREFIX + "/roster/extra", "/demo2/identity/extra"):
        assert request(proxy, path, headers=accepted)[0] == 404


@pytest.fixture()
def real_identity_http(tmp_path, monkeypatch):
    """Exercise real lazy schema creation in a disposable, explicitly named DB."""
    from src.rehab_affect.student_record_store import Demo2StudentRecordStore

    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", "SyntheticIdentityOnly-")
    records = Demo2StudentRecordStore(tmp_path / "identity-fixture.sqlite3", tmp_path / "documents")
    accounts, tokens = {}, {}
    for role, username in (("school", "school_uploader_01"), ("other", "school_uploader_02"),
                           ("admin", "company_admin")):
        accounts[role] = records.authenticate_account(username, "SyntheticIdentityOnly-" + username)
        tokens[role] = records.create_account_session(accounts[role])["token"]
    context = {"city": "Fixture city", "district": "Fixture district", "school_name": "Fixture school"}
    records.save_account_school_context(tokens["school"], context)
    records.save_account_school_context(tokens["other"], context)
    records.ensure_students([{"student_id": "GLOBAL-LEGACY-SECRET", "display_name": "Legacy demo only"}])
    monkeypatch.setattr(backend, "get_demo2_student_store", lambda: records)
    detections = []
    detector = ModuleType("src.rehab_affect.demo2_face_detection")

    def detect(path):
        path = Path(path)
        assert path.is_relative_to(records.video_task_dir)
        assert path.read_bytes() == JPEG
        detections.append(path)
        return {"available": True, "faces": [], "identity_recognition": False}

    detector.detect_faces = detect
    monkeypatch.setitem(sys.modules, detector.__name__, detector)
    handler = backend.create_handler(scenario_dir=tmp_path, model_path=tmp_path / "unused", policy_name="rule")
    httpd = backend.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=lambda: httpd.serve_forever(poll_interval=.01), daemon=True)
    thread.start()

    def api(path, *, role="school", method="GET", payload=None):
        cookie = {"Cookie": f"rehab_demo2_session={tokens[role]}"}
        return request(httpd, path, method=method, payload=payload, headers=cookie)

    try:
        yield SimpleNamespace(httpd=httpd, records=records, accounts=accounts, tokens=tokens,
                              api=api, detections=detections)
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(3)


def test_real_isolated_store_roster_binding_frame_export_and_permissions(real_identity_http):
    fixture = real_identity_http
    api, records = fixture.api, fixture.records
    upload = "/api/v1/demo2/upload/workspace?course_id=fixture-course"
    status, _, body = api(upload)
    assert status == 200 and body["workspace"]["students"] == []
    assert "GLOBAL-LEGACY-SECRET" not in json.dumps(body)
    status, _, body = api(PREFIX + "/students", method="POST", payload=STUDENT)
    assert status in {200, 201}
    student_id = body["student"]["student_id"]
    for path, envelope in ((PREFIX + "/roster", "roster"), (upload, "workspace")):
        status, _, body = api(path)
        assert status == 200
        assert [student["student_id"] for student in body[envelope]["students"]] == [student_id]
        assert "GLOBAL-LEGACY-SECRET" not in json.dumps(body)
        assert api(path, role="other")[2][envelope]["students"] == []
    raw_source = b"Synthetic video source, never decoded by a model"
    task = records.create_video_task({"account_id": fixture.accounts["school"]["account_id"],
        "channel_id": "channel_1", "session_id": "fixture-batch", "course_id": "fixture-course",
        "course_name": "Fixture course", "uploader_name": "Fixture uploader", "filename": "fixture.mp4",
        "byte_size": len(raw_source), "total_chunks": 1})
    task_id = task["task_id"]
    records.append_video_chunk({"task_id": task_id, "account_session_token": fixture.tokens["school"],
        "chunk_index": 0, "content_base64": base64.b64encode(raw_source).decode()})
    claim = records.claim_next_video_analysis()
    assert claim["task_id"] == task_id
    relative_image = "media_fixture/frames/frame_000000.jpg"
    frame = Path(claim["analysis_dir"]) / relative_image
    frame.parent.mkdir(parents=True)
    frame.write_bytes(JPEG)
    records.finish_video_analysis(task_id, {
        "analysis_version": "demo2_media_evidence_v1.1", "task_id": task_id, "source_sha256": claim["sha256"],
        "media": {}, "sampling": {"fps": 1, "window_sec": 20}, "artifacts": {"frames": "media_fixture/frames"},
        "segments": [{"start_sec": 0, "end_sec": 1, "visual": {"samples": [
            {"timestamp_sec": 0, "image_path": relative_image}]}}],
    })
    workspace_path = PREFIX + "/workspace?task_id=" + task_id
    status, _, body = api(workspace_path)
    assert status == 200
    workspace = body["workspace"]
    assert workspace["media_available"] is True and workspace["can_edit"] is True
    assert len(workspace["frames"]) == 1
    image_url = workspace["frames"][0]["image_url"]
    assert image_url.startswith(PREFIX + "/frame?")
    status, headers, body = api(image_url)
    assert status == 200 and body == JPEG and "no-store" in headers["Cache-Control"]
    detection_url = image_url.replace("/frame?", "/detect?", 1)
    assert api(detection_url)[0] == 200
    assert fixture.detections == [frame]
    payload = {**BINDING, "task_id": task_id, "student_id": student_id,
               "frame_revision": workspace["frame_revision"]}
    for path in (workspace_path, image_url, PREFIX + "/export?task_id=" + task_id, detection_url):
        assert api(path, role="other")[0] == 404
        assert api(path, role="admin")[0] == 200
    assert api(workspace_path, role="admin")[2]["workspace"]["can_edit"] is False
    for role in ("other", "admin"):
        assert api(PREFIX + "/bindings", role=role, method="POST", payload=payload)[0] in {403, 404}
    assert api(PREFIX + "/students", role="admin", method="POST", payload=STUDENT)[0] == 403
    status, _, body = api(PREFIX + "/bindings", method="POST", payload=payload)
    assert status == 200 and body["binding"]["status"] == "confirmed"
    binding_id = body["binding"]["binding_id"]
    assert body["binding"]["confirmed_by"] == fixture.accounts["school"]["username"]
    status, headers, exported = api(PREFIX + "/export?task_id=" + task_id)
    assert status == 200 and exported["bindings"][0]["binding_id"] == binding_id
    assert "attachment" in headers["Content-Disposition"]
    assert "ok" not in exported and str(records.db_path) not in json.dumps(exported)
    revoke = {"task_id": task_id, "binding_id": binding_id, "reason": "Fixture correction"}
    assert api(PREFIX + "/bindings/revoke", role="admin", method="POST", payload=revoke)[0] == 403
    assert api(PREFIX + "/bindings/revoke", role="other", method="POST", payload=revoke)[0] == 404
    status, _, body = api(PREFIX + "/bindings/revoke", method="POST", payload=revoke)
    assert status == 200 and body["binding"]["status"] == "revoked"
    assert api(workspace_path)[2]["workspace"]["summary"]["revoked_count"] == 1
