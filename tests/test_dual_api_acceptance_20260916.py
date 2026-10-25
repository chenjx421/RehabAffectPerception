"""HTTP acceptance coverage for the classroom dual-track evaluation API.

These tests use the synthetic account/database fixture from the existing evaluation
tests. They intentionally exercise the server boundary rather than rubric math or
store implementation details.
"""

from concurrent.futures import ThreadPoolExecutor
import json
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

import pytest
from http.server import ThreadingHTTPServer

from rehab_affect import scenario_lab_server as server
from test_demo2_evaluation_store import env, payload


@pytest.fixture
def api_env(env, monkeypatch):
    monkeypatch.setattr(server, "get_demo2_student_store", lambda: env.records)
    handler = server.create_handler(
        scenario_dir=Path("configs/scenarios"),
        model_path=server.DEFAULT_LEARNED_POLICY_PATH,
        policy_name="rule",
    )
    http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()

    def request(path, method="GET", data=None, user="t1", headers=None, raw=None):
        outgoing = {"Content-Type": "application/json", "Connection": "close"}
        if user:
            outgoing["Cookie"] = "rehab_demo2_session=" + env.tokens[user]
        outgoing.update(headers or {})
        body = raw if raw is not None else (
            json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
        )
        connection = HTTPConnection("127.0.0.1", http.server_port, timeout=10)
        try:
            connection.request(method, path, body=body, headers=outgoing)
            response = connection.getresponse()
            response_body = response.read()
            content_type = response.getheader("Content-Type", "")
            decoded = json.loads(response_body) if "json" in content_type else response_body
            return response.status, dict(response.getheaders()), decoded
        finally:
            connection.close()

    yield request
    http.shutdown()
    http.server_close()
    thread.join(3)


def assert_error(response, status, code=None):
    actual_status, _, body = response
    assert actual_status == status
    assert body["ok"] is False
    assert set(body["error"]) == {"code", "message"}
    if code is not None:
        assert body["error"]["code"] == code


def test_auth_roles_scope_and_page_boundary(api_env):
    request = api_env
    api = "/api/v1/demo2/evaluations"

    assert_error(request(api, user=None), 401, "authentication_required")
    assert_error(request(api, user="admin"), 403, "evaluation_forbidden")
    page_status, page_headers, page_body = request("/demo2/evaluation")
    assert page_status == 200
    assert page_headers["Content-Type"].startswith("text/html")
    assert "课堂双轨评价" in page_body.decode("utf-8")

    saved = request(api, "POST", payload())[2]["record"]
    assert saved["record_id"] == "fixture-1"
    assert request(api, user="t2")[2]["workspace"]["records"] == []
    assert_error(request(api, "POST", payload(), user="t2"), 404, "record_unavailable")
    assert_error(
        request(
            api + "/withdraw",
            "POST",
            {"record_id": "fixture-1", "expected_version": 1, "reason": "越权撤销"},
            user="t2",
        ),
        404,
        "record_unavailable",
    )


def test_malformed_json_and_write_contract_errors_are_structured(api_env):
    request = api_env
    api = "/api/v1/demo2/evaluations"

    assert_error(
        request(api + "/preview", "POST", raw=b"{not-json"),
        400,
        "invalid_request",
    )
    assert_error(
        request(api + "/preview", "POST", raw=b"[]"),
        400,
        "invalid_request",
    )
    assert_error(
        request(api + "/preview", "POST", payload(), headers={"Content-Type": "text/plain"}),
        415,
        "json_required",
    )
    assert_error(
        request(
            api,
            "POST",
            payload(reviewed="true"),
            headers={"Origin": "https://external.invalid"},
        ),
        403,
        "origin_forbidden",
    )
    assert_error(request(api, "POST", payload(record_id="new", expected_version=1)), 409, "version_conflict")
    assert request(api)[2]["workspace"]["records"] == []


def test_preview_is_read_only_and_conflicts_preserve_the_form_contract(api_env):
    request = api_env
    api = "/api/v1/demo2/evaluations"

    preview_status, _, preview = request(api + "/preview", "POST", payload())
    assert preview_status == 200
    assert set(preview) == {"ok", "result"}
    assert request(api)[2]["workspace"]["records"] == []

    request(api, "POST", payload())
    conflict = request(api, "POST", payload(expected_version=1, course_name="并发旧版本"))
    assert_error(conflict, 409, "version_conflict")
    workspace = request(api)[2]["workspace"]
    assert len(workspace["records"]) == 1
    assert workspace["records"][0]["version"] == 1


def test_same_version_posts_have_one_winner_and_one_conflict(api_env):
    request = api_env
    api = "/api/v1/demo2/evaluations"
    request(api, "POST", payload())

    def update(course_name):
        return request(
            api,
            "POST",
            payload(expected_version=1, course_name=course_name),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(update, ["并发修订甲", "并发修订乙"]))

    statuses = sorted(response[0] for response in responses)
    assert statuses == [200, 409]
    winner = next(response for response in responses if response[0] == 200)[2]["record"]
    loser = next(response for response in responses if response[0] == 409)
    assert winner["version"] == 2
    assert_error(loser, 409, "version_conflict")
    current = request(api)[2]["workspace"]["records"]
    assert len(current) == 1 and current[0]["version"] == 2
