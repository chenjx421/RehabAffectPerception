"""Cloud HTTP contracts using synthetic stores and loopback only; no DB/model."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import socket
import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest

from test_demo2_identity_api import IdentityError, Records, request


ROOT = Path(__file__).resolve().parents[1]
OVERRIDE = ROOT / ".runtime" / "cloud_release_overrides" / "scenario_lab_server.py"
PREFIX = "/api/v1/demo2/observations"
LINK = {"task_id": "task-one", "job_id": "job-one", "person_id": "person-one",
        "binding_id": "binding-one", "frame_keys": ["s0_f0"], "confirmed": True}
READS = [("", "task_id", "task-one", "workspace"),
         ("/download", "task_id", "task-one", "workspace"),
         ("/student", "student_id", "student-one", "student_history")]
WRITES = [("", {"task_id": "task-one"}), ("/link", LINK)]


class ObservationError(IdentityError):
    pass


class Observations:
    def __init__(self, records):
        self.records = records
        self.calls, self.errors = [], {}
        self.value = {"job_id": "job-one", "task_id": "task-one", "status": "ready",
                      "source_sha256": "a" * 64, "frame_revision": "b" * 64,
                      "reviewed": False, "teacher_review_status": "not_reviewed",
                      "observations": [{"frame_key": "s0_f0", "person_id": "person-one",
                                        "observation": "hand_raised", "reviewed": False}]}

    def _call(self, method, token, *args, **kwargs):
        self.calls.append((method, token, args, kwargs))
        if method in self.errors:
            raise self.errors[method]
        account = self.records.account_from_session(token)
        if account["role"] != "school_uploader":
            raise IdentityError(403, "identity_forbidden", "School role required")
        if account["account_id"] != "account-one":
            raise IdentityError(404, "task_unavailable", "Resource is outside this owner")

    @staticmethod
    def _task(task_id):
        if task_id == "expired-task":
            raise IdentityError(410, "media_expired", "Synthetic media expired")
        if task_id not in {"task-one", "task-two"}:
            raise IdentityError(404, "task_unavailable", "Unknown task")

    def workspace(self, token, task_id):
        self._call("workspace", token, task_id)
        self._task(task_id)
        value = copy.deepcopy(self.value)
        if task_id == "task-two":
            value.update(task_id=task_id, job_id="job-two")
        return value

    def student_history(self, token, student_id):
        self._call("student_history", token, student_id)
        if student_id != "student-one":
            raise IdentityError(404, "student_unavailable", "Unknown student")
        return {"student_id": student_id, "observations": copy.deepcopy(self.value["observations"]),
                "reviewed": False, "teacher_review_status": "not_reviewed"}

    def request(self, token, payload):
        self._call("request", token, payload)
        if not isinstance(payload, dict) or set(payload) != {"task_id"}:
            raise ObservationError(400, "invalid_request", "Only a selected task ID is allowed")
        self._task(payload["task_id"])
        return {**copy.deepcopy(self.value), "status": "pending"}

    def link_person(self, token, job_id, person_id, binding_id, *, frame_keys=None, confirmed=False):
        self._call("link_person", token, job_id, person_id, binding_id,
                   frame_keys=frame_keys, confirmed=confirmed)
        if job_id != "job-one" or person_id != "person-one" or binding_id != "binding-one":
            raise ObservationError(409, "identity_unavailable", "Unknown person or binding")
        if frame_keys != ["s0_f0"] or confirmed is not True:
            raise ObservationError(400, "invalid_samples", "Confirm one exact observed frame")
        return {"job_id": job_id, "person_id": person_id, "binding_id": binding_id,
                "frame_keys": frame_keys, "identity_confirmed": True, "reviewed": False,
                "teacher_review_status": "not_reviewed"}


@pytest.fixture()
def rig(tmp_path, monkeypatch):
    # A separate package-qualified name resolves relative imports without
    # replacing the Windows server module used by the identity API tests.
    name = "src.rehab_affect._observation_api_cloud_server"
    spec = importlib.util.spec_from_file_location(name, OVERRIDE)
    backend = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, backend)
    spec.loader.exec_module(backend)
    assert Path(backend.__file__).resolve() == OVERRIDE

    records = Records()
    assert not hasattr(records, "_connect")
    observations = Observations(records)
    constructed = []
    store_module = ModuleType("src.rehab_affect.demo2_observation_store")
    store_module.ObservationError = ObservationError

    def factory(store):
        assert store is records
        constructed.append(store)
        return observations

    store_module.Demo2ObservationStore = factory
    monkeypatch.setitem(sys.modules, store_module.__name__, store_module)
    identity_module = ModuleType("src.rehab_affect.demo2_identity_store")
    identity_module.IdentityError = IdentityError
    monkeypatch.setitem(sys.modules, identity_module.__name__, identity_module)
    monkeypatch.setattr(backend, "get_demo2_student_store", lambda: records)

    handler = backend.create_handler(scenario_dir=tmp_path, model_path=tmp_path / "unused", policy_name="rule")
    httpd = backend.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    connect = socket.create_connection

    def loopback_only(address, *args, **kwargs):
        assert address == ("127.0.0.1", httpd.server_port), "Only the isolated HTTP fixture may be contacted"
        return connect(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", loopback_only)
    thread = threading.Thread(target=lambda: httpd.serve_forever(poll_interval=.01), daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(httpd=httpd, records=records, observations=observations,
                              constructed=constructed, backend=backend,
                              origin=f"http://127.0.0.1:{httpd.server_port}")
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(3)
        assert not thread.is_alive()


@pytest.mark.parametrize("suffix,field,value,method", READS)
@pytest.mark.parametrize("role,status", [(None, 401), ("expired", 401), ("member", 403)])
def test_reads_deny_unauthenticated_and_members_before_store(rig, suffix, field, value, method, role, status):
    actual, _, body = request(rig.httpd, PREFIX + suffix + f"?{field}={value}", role=role)
    assert actual == status and body["ok"] is False
    assert not rig.observations.calls and not rig.constructed


@pytest.mark.parametrize("suffix,payload", WRITES)
@pytest.mark.parametrize("role,status", [(None, 401), ("expired", 401), ("member", 403), ("admin", 403)])
def test_writes_require_school_role_before_store(rig, suffix, payload, role, status):
    actual, _, body = request(rig.httpd, PREFIX + suffix, role=role, method="POST", payload=payload)
    assert actual == status and body["ok"] is False
    assert not rig.observations.calls and not rig.constructed


@pytest.mark.parametrize("suffix,field,value,method", READS)
@pytest.mark.parametrize("role,status,code", [("other", 404, "task_unavailable"), ("admin", 403, "identity_forbidden")])
def test_reads_delegate_cross_owner_and_admin_denial(rig, suffix, field, value, method, role, status, code):
    actual, headers, body = request(rig.httpd, PREFIX + suffix + f"?{field}={value}", role=role)
    assert actual == status and body["error"]["code"] == code
    assert rig.observations.calls == [(method, "session-" + role, (value,), {})]
    assert "Content-Disposition" not in headers
    assert "observations" not in body and "workspace" not in body


@pytest.mark.parametrize("suffix,payload", WRITES)
def test_cross_owner_writes_never_link_a_person(rig, suffix, payload):
    status, _, body = request(rig.httpd, PREFIX + suffix, role="other", method="POST", payload=payload)
    assert status == 404 and body["error"]["code"] == "task_unavailable"
    assert [call[0] for call in rig.observations.calls] == (["workspace"] if suffix else ["request"])


def test_workspace_and_student_reads_keep_private_unreviewed_envelopes(rig):
    status, headers, body = request(rig.httpd, PREFIX + "?task_id=task-one", role="school")
    assert status == 200 and body == {"ok": True, "workspace": rig.observations.value}
    assert "no-store" in headers["Cache-Control"]
    status, headers, body = request(rig.httpd, PREFIX + "/student?student_id=student-one", role="school")
    assert status == 200 and body["workspace"]["student_id"] == "student-one"
    assert body["workspace"]["reviewed"] is False
    assert body["workspace"]["observations"] == rig.observations.value["observations"]
    assert "no-store" in headers["Cache-Control"]
    assert rig.observations.calls == [("workspace", "session-school", ("task-one",), {}),
                                      ("student_history", "session-school", ("student-one",), {})]
    assert rig.constructed == [rig.records]


def test_download_is_exact_workspace_json_attachment_not_an_envelope(rig):
    status, headers, body = request(rig.httpd, PREFIX + "/download?task_id=task-one", role="school")
    assert status == 200 and body == rig.observations.value
    assert headers["Content-Type"].startswith("application/json")
    assert headers["Content-Disposition"] == 'attachment; filename="classroom-ai-observations.json"'
    assert "no-store" in headers["Cache-Control"] and "private" in headers["Cache-Control"]
    assert "ok" not in body and "workspace" not in body
    assert str(ROOT) not in json.dumps(body)
    assert rig.observations.calls == [("workspace", "session-school", ("task-one",), {})]


def test_post_request_forwards_only_payload_and_session(rig):
    payload = {"task_id": "task-one"}
    status, headers, body = request(rig.httpd, PREFIX, role="school", method="POST", payload=payload)
    assert status == 200 and body["workspace"]["status"] == "pending"
    assert body["workspace"]["reviewed"] is False and "no-store" in headers["Cache-Control"]
    assert rig.observations.calls == [("request", "session-school", (payload,), {})]


def test_link_checks_current_task_job_then_forwards_keyword_only_confirmation(rig):
    status, headers, body = request(rig.httpd, PREFIX + "/link", role="school", method="POST", payload=LINK)
    assert status == 200 and body["ok"] is True
    assert body["record"] == {key: LINK[key] for key in ("job_id", "person_id", "binding_id", "frame_keys")} | {
        "identity_confirmed": True, "reviewed": False, "teacher_review_status": "not_reviewed"}
    assert "workspace" not in body and "no-store" in headers["Cache-Control"]
    assert rig.observations.calls == [
        ("workspace", "session-school", ("task-one",), {}),
        ("link_person", "session-school", ("job-one", "person-one", "binding-one"),
         {"frame_keys": ["s0_f0"], "confirmed": True}),
    ]
    assert rig.constructed == [rig.records]


@pytest.mark.parametrize("suffix,payload", WRITES)
@pytest.mark.parametrize("origin", ["https://attacker.invalid", "http://127.0.0.1:1"])
def test_foreign_origin_is_denied_before_store(rig, suffix, payload, origin):
    status, _, body = request(rig.httpd, PREFIX + suffix, role="school", method="POST", payload=payload,
                              headers={"Origin": origin})
    assert status == 403 and body["error"]["code"] == "origin_forbidden"
    assert not rig.observations.calls and not rig.constructed


@pytest.mark.parametrize("suffix,payload", WRITES)
def test_same_origin_json_command_is_accepted(rig, suffix, payload):
    status, _, body = request(rig.httpd, PREFIX + suffix, role="school", method="POST", payload=payload,
                              headers={"Origin": rig.origin, "Content-Type": "application/json; charset=utf-8"})
    assert status == 200 and body["ok"] is True


@pytest.mark.parametrize("suffix,payload", WRITES)
@pytest.mark.parametrize("mime", ["text/plain", "application/x-www-form-urlencoded"])
def test_simple_form_or_text_commands_rejected_before_store(rig, suffix, payload, mime):
    status, _, body = request(rig.httpd, PREFIX + suffix, role="school", method="POST", payload=payload,
                              headers={"Content-Type": mime})
    assert status == 415 and body["error"]["code"] == "json_required"
    assert not rig.observations.calls and not rig.constructed


INVALID_LINKS = [
    *({key: value for key, value in LINK.items() if key != missing} for missing in LINK),
    {**LINK, "student_id": "invented"},
    *({**LINK, "confirmed": value} for value in (False, "true", 1, None)),
    *({**LINK, "frame_keys": value} for value in ([], ["s0_f0", "s0_f1"], "s0_f0", [1], None)),
    *({**LINK, field: value} for field in ("task_id", "job_id", "person_id", "binding_id")
      for value in ("", 1, "x" * 161)),
]


@pytest.mark.parametrize("payload", INVALID_LINKS)
def test_link_payload_is_exact_typed_single_frame_and_explicitly_confirmed(rig, payload):
    status, _, body = request(rig.httpd, PREFIX + "/link", role="school", method="POST", payload=payload)
    assert status == 400 and body["error"]["code"] == "invalid_request"
    assert not rig.observations.calls and not rig.constructed


@pytest.mark.parametrize("payload", [dict(LINK, job_id="job-old"), dict(LINK, task_id="task-two")])
def test_link_cannot_apply_a_job_to_a_different_or_replaced_task(rig, payload):
    status, _, body = request(rig.httpd, PREFIX + "/link", role="school", method="POST", payload=payload)
    assert status == 409 and body["error"]["code"] == "source_changed"
    assert rig.observations.calls == [("workspace", "session-school", (payload["task_id"],), {})]


@pytest.mark.parametrize("payload", [{}, {"task_id": "task-one", "reviewed": True}])
def test_request_payload_validation_is_delegated_and_errors_preserved(rig, payload):
    status, _, body = request(rig.httpd, PREFIX, role="school", method="POST", payload=payload)
    assert status == 400 and body["error"]["code"] == "invalid_request"
    assert rig.observations.calls == [("request", "session-school", (payload,), {})]


@pytest.mark.parametrize("suffix,payload", WRITES)
@pytest.mark.parametrize("raw", [b"{not-json", b"[]", b'"not-an-object"', b"\xff", b"x" * 4097])
def test_malformed_or_oversized_json_never_reaches_store(rig, suffix, payload, raw):
    status, _, body = request(rig.httpd, PREFIX + suffix, role="school", method="POST", raw=raw)
    assert status in {400, 413} and body["ok"] is False
    assert not rig.observations.calls and not rig.constructed


@pytest.mark.parametrize("suffix,field,value,method", READS)
@pytest.mark.parametrize("kind", ["missing", "blank", "duplicate", "extra", "path", "malformed", "excessive"])
def test_reads_require_exact_single_identifier_query(rig, suffix, field, value, method, kind):
    query = {"missing": "", "blank": f"{field}=", "duplicate": f"{field}={value}&{field}={value}",
             "extra": f"{field}={value}&path=%2Fetc%2Fpasswd", "path": f"{field}=..%2Fprivate",
             "malformed": f"{field}={value}&orphan",
             "excessive": "&".join(f"field{i}=value" for i in range(9))}[kind]
    status, _, body = request(rig.httpd, PREFIX + suffix + "?" + query, role="school")
    assert status == 400 and body["error"]["code"] == "invalid_request"
    assert not rig.observations.calls and not rig.constructed


@pytest.mark.parametrize("error_type", [ObservationError, IdentityError])
@pytest.mark.parametrize("suffix,method,payload,store_method,status,code", [
    ("?task_id=task-one", "GET", None, "workspace", 410, "media_expired"),
    ("/download?task_id=task-one", "GET", None, "workspace", 409, "source_changed"),
    ("/student?student_id=student-one", "GET", None, "student_history", 404, "student_unavailable"),
    ("", "POST", {"task_id": "task-one"}, "request", 503, "model_not_configured"),
    ("/link", "POST", LINK, "link_person", 409, "identity_unavailable"),
])
def test_repository_errors_preserve_status_code_and_message(rig, error_type, suffix, method, payload,
                                                           store_method, status, code):
    rig.observations.errors[store_method] = error_type(status, code, "Synthetic safe error")
    actual, headers, body = request(rig.httpd, PREFIX + suffix, role="school", method=method, payload=payload)
    assert actual == status and body == {"ok": False, "error": {"code": code, "message": "Synthetic safe error"}}
    assert "Content-Disposition" not in headers and "no-store" in headers["Cache-Control"]
    assert rig.observations.calls[-1][0] == store_method
