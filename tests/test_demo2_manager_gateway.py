"""Private manager gateway contract; loopback servers and synthetic data only."""

from __future__ import annotations

import http.client
import io
import json
import socket
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from src.rehab_affect import demo2_manager_gateway as gateway


INVITE = "qa-invite-" + "a1B2c3D4e5F6g7H8" * 3
SIGNING_KEY = "qa-signing-" + "9h8G7f6E5d4C3b2A" * 3
SESSION_NAME = "rehab_demo2_session"
INVITE_NAME = "rehab_manager_invite"
MEDIA = bytes(range(256)) * 2048


@pytest.fixture()
def rig():
    calls = []
    responses = {}
    first_chunk = threading.Event()
    release_stream = threading.Event()
    stream_finished = threading.Event()
    release_stream.set()

    class Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def respond(self, status, data, headers=None):
            self.send_response(status)
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def handle_request(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            calls.append({"method": self.command, "path": self.path,
                          "headers": dict(self.headers), "body": body})
            cookies = SimpleCookie()
            cookies.load(self.headers.get("Cookie", ""))
            session = cookies.get(SESSION_NAME)
            token = session.value if session else ""
            if self.path == "/api/v1/demo2/auth/me":
                valid = token in {"qa-manager-session", "qa-uploader-session"}
                payload = {"ok": valid, "account": {"account_id": "synthetic-account",
                           "role": "company_admin" if token == "qa-manager-session" else "school_uploader"}} if valid else {"ok": False}
                self.respond(200 if valid else 401, json.dumps(payload).encode(), {"Content-Type": "application/json"})
            elif self.path in responses:
                status, data = responses[self.path]
                self.respond(status, data, {"Content-Type": "application/json"})
            elif self.path == "/api/v1/demo2/auth/login":
                payload = json.loads(body)
                if payload == {"username": "qa-user", "password": "synthetic-pass"}:
                    self.respond(200, b'{"ok":true}', {"Content-Type": "application/json",
                        "Set-Cookie": f"{SESSION_NAME}=qa-manager-session; HttpOnly; SameSite=Lax; Path=/"})
                else:
                    self.respond(401, b'{"ok":false}', {"Content-Type": "application/json"})
            elif self.path.startswith("/api/v1/demo2/admin/") and token != "qa-manager-session":
                self.respond(403, b'{"ok":false,"error":{"code":"forbidden"}}', {"Content-Type": "application/json"})
            elif self.path.startswith("/api/v1/demo2/identity/preview?"):
                self.respond(200, b"\xff\xd8synthetic-preview\xff\xd9", {"Content-Type": "image/jpeg",
                    "Cache-Control": "public, max-age=3600"})
            elif self.path.startswith("/api/v1/demo2/upload/media"):
                start, end = 0, len(MEDIA) - 1
                range_value = self.headers.get("Range")
                if range_value:
                    start, end = map(int, range_value.removeprefix("bytes=").split("-"))
                data = MEDIA[start:end + 1]
                self.send_response(206 if range_value else 200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(len(data)))
                if range_value:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{len(MEDIA)}")
                self.end_headers()
                if self.command == "HEAD":
                    return
                self.wfile.write(data[:131072])
                self.wfile.flush()
                first_chunk.set()
                release_stream.wait(5)
                self.wfile.write(data[131072:])
                stream_finished.set()
            else:
                # Deliberately unguarded: the gateway must protect this data.
                self.respond(200, b"synthetic-student-resource", {"Content-Type": "text/plain",
                    "Cache-Control": "public, max-age=3600", "Referrer-Policy": "unsafe-url"})

        do_GET = handle_request
        do_POST = handle_request
        do_HEAD = handle_request

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    servers = [upstream]
    threads = []

    def serve(server):
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.02), daemon=True)
        thread.start()
        threads.append(thread)

    serve(upstream)
    config = {"invite_secret": INVITE, "cookie_secret": SIGNING_KEY,
              "expires_at": int(time.time()) + 172800,
              "upstream_port": upstream.server_port, "listen_port": 0}

    def start(**overrides):
        server = gateway.make_server({**config, **overrides}, host="127.0.0.1", port=0)
        servers.append(server)
        serve(server)
        return server

    proxy = start()
    result = SimpleNamespace(proxy=proxy, config=config, start=start, calls=calls, responses=responses,
        first_chunk=first_chunk, release_stream=release_stream, stream_finished=stream_finished)
    try:
        yield result
    finally:
        release_stream.set()
        for server in reversed(servers):
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(3)


def request(proxy, path, *, method="GET", payload=None, cookie="", headers=None):
    host = f"127.0.0.1:{proxy.server_port}"
    outgoing = {"Host": host, **(headers or {})}
    if cookie:
        outgoing["Cookie"] = cookie
    if method == "POST" and "Origin" not in outgoing:
        outgoing["Origin"] = "https://" + host
    body = json.dumps(payload).encode() if payload is not None else None
    if body is not None:
        outgoing["Content-Type"] = "application/json"
    connection = http.client.HTTPConnection("127.0.0.1", proxy.server_port, timeout=3)
    try:
        connection.request(method, path, body=body, headers=outgoing)
        response = connection.getresponse()
        return response.status, response.getheaders(), response.read()
    finally:
        connection.close()


def header(headers, name):
    return ", ".join(value for key, value in headers if key.lower() == name.lower())


def authorize(proxy):
    status, headers, body = request(proxy, "/__manager/authorize", method="POST", payload={"secret": INVITE})
    assert status == 303, body
    assert header(headers, "Location") == "/demo2/login"
    cookie = SimpleCookie()
    cookie.load(header(headers, "Set-Cookie"))
    assert INVITE_NAME in cookie
    return f"{INVITE_NAME}={cookie[INVITE_NAME].value}", cookie[INVITE_NAME]


def dual_cookie(proxy, session="qa-manager-session"):
    invite, _ = authorize(proxy)
    return f"{invite}; {SESSION_NAME}={session}"


def assert_private_headers(headers):
    assert "no-store" in header(headers, "Cache-Control").lower()
    assert header(headers, "Referrer-Policy") == "no-referrer"
    assert header(headers, "X-Frame-Options") == "DENY"


def test_preview_uses_exact_private_gateway_route_and_keeps_both_gates(rig):
    path = "/api/v1/demo2/identity/preview?task_id=t&frame_key=f&frame_revision=r"
    assert request(rig.proxy, path)[0] in {401, 403}
    assert not rig.calls
    invite, _ = authorize(rig.proxy)
    assert request(rig.proxy, path, cookie=invite)[0] == 401
    cookie = dual_cookie(rig.proxy)
    status, headers, body = request(rig.proxy, path, cookie=cookie)
    assert status == 200 and body == b"\xff\xd8synthetic-preview\xff\xd9"
    assert header(headers, "Content-Type") == "image/jpeg"
    assert_private_headers(headers)
    assert request(rig.proxy, path.replace("preview?", "preview/extra?"), cookie=cookie)[0] == 404
    assert request(rig.proxy, path, method="POST", payload={}, cookie=cookie)[0] == 404


def test_invite_fragment_page_and_secure_signed_cookie(rig):
    status, headers, body = request(rig.proxy, "/invite")
    assert status == 200
    assert_private_headers(headers)
    html = body.decode()
    assert "location.hash" in html and "replaceState" in html
    assert html.index("replaceState") < html.index("fetch(")
    assert INVITE not in html and SIGNING_KEY not in html
    invite, cookie = authorize(rig.proxy)
    assert cookie["secure"] and cookie["httponly"]
    assert cookie["samesite"].lower() == "lax" and cookie["path"] == "/"
    assert 0 < int(cookie["max-age"]) <= 172800
    assert INVITE not in invite and SIGNING_KEY not in invite
    assert rig.calls == []


@pytest.mark.parametrize("secret", ["incorrect-secret", "", None, 123, {"secret": INVITE}])
def test_wrong_or_non_string_secret_is_rejected(rig, secret):
    status, headers, body = request(rig.proxy, "/__manager/authorize", method="POST", payload={"secret": secret})
    assert 400 <= status < 500
    assert not header(headers, "Set-Cookie")
    assert INVITE.encode() not in body
    assert_private_headers(headers)
    assert rig.calls == []


@pytest.mark.parametrize("cookie", ["", f"{INVITE_NAME}=forged", f"{INVITE_NAME}={INVITE}", f"{SESSION_NAME}=qa-manager-session"])
def test_no_invite_or_fake_cookie_never_reaches_upstream(rig, cookie):
    status, headers, body = request(rig.proxy, "/api/v1/demo2/dossier/student?student_id=synthetic", cookie=cookie)
    assert 400 <= status < 500
    assert b"synthetic-student-resource" not in body
    assert_private_headers(headers)
    assert rig.calls == []


def test_tampered_signed_cookie_is_rejected(rig):
    invite, _ = authorize(rig.proxy)
    name, value = invite.split("=", 1)
    offset = len(value) // 2
    tampered = value[:offset] + ("A" if value[offset] != "A" else "B") + value[offset + 1:]
    status, _, _ = request(rig.proxy, "/demo2/login", cookie=f"{name}={tampered}")
    assert status != 200
    assert rig.calls == []


@pytest.mark.parametrize("path", ["/api/v1/demo2/dossier/student?student_id=synthetic", "/api/v1/demo2/dossier/document?document_id=synthetic",
    "/api/v1/demo2/upload/media?id=qa", "/api/v1/demo2/upload/result?id=qa"])
@pytest.mark.parametrize("session", ["", "forged-session", "expired-upstream-session"])
def test_invite_without_valid_upstream_session_cannot_read_student_resources(rig, path, session):
    cookie = dual_cookie(rig.proxy, session)
    status, _, body = request(rig.proxy, path, cookie=cookie)
    assert status == 401
    assert b"synthetic-student-resource" not in body
    assert all(call["path"] == "/api/v1/demo2/auth/me" for call in rig.calls)


def test_login_forwarding_and_real_upstream_session_dual_auth(rig):
    invite, _ = authorize(rig.proxy)
    status, _, _ = request(rig.proxy, "/demo2/login", cookie=invite)
    assert status == 200
    payload = {"username": "qa-user", "password": "synthetic-pass"}
    status, headers, body = request(rig.proxy, "/api/v1/demo2/auth/login", method="POST", payload=payload, cookie=invite)
    assert status == 200 and json.loads(body)["ok"] is True
    login_call = rig.calls[-1]
    assert json.loads(login_call["body"]) == payload
    assert INVITE_NAME not in login_call["headers"].get("Cookie", "")
    cookie = SimpleCookie()
    cookie.load(header(headers, "Set-Cookie"))
    assert cookie[SESSION_NAME]["secure"] and cookie[SESSION_NAME]["httponly"]
    assert_private_headers(headers)
    joined = f"{invite}; {SESSION_NAME}={cookie[SESSION_NAME].value}"
    rig.calls.clear()
    status, headers, body = request(rig.proxy, "/api/v1/demo2/dossier/student?student_id=synthetic", cookie=joined)
    assert status == 200 and body == b"synthetic-student-resource"
    assert [call["path"] for call in rig.calls] == ["/api/v1/demo2/auth/me", "/api/v1/demo2/dossier/student?student_id=synthetic"]
    assert_private_headers(headers)


def test_upstream_role_403_is_preserved(rig):
    status, headers, body = request(rig.proxy, "/api/v1/demo2/admin/summary", cookie=dual_cookie(rig.proxy, "qa-uploader-session"))
    assert status == 403 and json.loads(body)["error"]["code"] == "forbidden"
    assert_private_headers(headers)


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.invalid"}, {"Origin": "null"},
    {"Sec-Fetch-Site": "cross-site"}, {"Origin": "https://evil.invalid", "X-Forwarded-Host": "evil.invalid", "X-Forwarded-Proto": "https"}])
def test_cross_origin_post_is_rejected_before_forwarding(rig, headers):
    cookie = dual_cookie(rig.proxy)
    status, _, _ = request(rig.proxy, "/api/v1/demo2/upload/tasks", method="POST", payload={"synthetic": True}, cookie=cookie, headers=headers)
    assert status == 403
    assert rig.calls == []


def test_authorize_itself_rejects_cross_origin_post(rig):
    status, headers, _ = request(rig.proxy, "/__manager/authorize", method="POST", payload={"secret": INVITE}, headers={"Origin": "https://evil.invalid"})
    assert status == 403 and not header(headers, "Set-Cookie")


@pytest.mark.parametrize("path", ["/showcase", "/api/scenarios", "/assets/private.sqlite3", "/api/v1/demo2/unknown",
    "/demo2/login/", "/demo2/../demo2/login", "/demo2/%2e%2e/login", "/%64emo2/login", "//demo2/login",
    "/demo2\\login", "/demo2/login%00", "/assets/seewo_demo2/%2e%2e/private.sqlite3",
    "/assets/seewo_demo2/../../private.sqlite3", "http://evil.invalid/demo2/login"])
def test_route_and_encoding_variants_never_reach_upstream(rig, path):
    cookie = dual_cookie(rig.proxy)
    status, _, _ = request(rig.proxy, path, cookie=cookie)
    assert 400 <= status < 500
    assert rig.calls == []


def test_proxy_headers_are_not_trusted_or_forwarded(rig):
    status, _, _ = request(rig.proxy, "/api/v1/demo2/dossier/student?student_id=synthetic", cookie=dual_cookie(rig.proxy),
        headers={"X-Forwarded-For": "10.0.0.99", "X-Forwarded-Host": "evil.invalid", "Forwarded": "host=evil.invalid;proto=http", "Authorization": "Bearer forged"})
    assert status == 200
    for call in rig.calls:
        headers = {key.lower(): value for key, value in call["headers"].items()}
        assert "forwarded" not in headers and "authorization" not in headers
        assert "x-forwarded-for" not in headers and "x-forwarded-host" not in headers
        assert INVITE_NAME not in headers.get("cookie", "")


@pytest.mark.parametrize("path", ["/api/seewo_demo2/student_record?id=synthetic",
    "/api/seewo_demo2/document_download?id=synthetic", "/assets/seewo_demo2/course-qa/group_reference.jpg"])
def test_retired_global_student_resources_never_forward_even_with_valid_session(rig, path):
    cookie = dual_cookie(rig.proxy)
    status, headers, body = request(rig.proxy, path, cookie=cookie)
    assert status == 404
    assert b"synthetic-student-resource" not in body
    assert_private_headers(headers)
    assert rig.calls == []


def test_range_is_streamed_before_upstream_finishes(rig):
    cookie = dual_cookie(rig.proxy)
    rig.release_stream.clear()
    connection = http.client.HTTPConnection("127.0.0.1", rig.proxy.server_port, timeout=2)
    try:
        connection.request("GET", "/api/v1/demo2/upload/media?id=qa", headers={"Cookie": cookie, "Range": "bytes=0-262143"})
        response = connection.getresponse()
        assert response.status == 206
        assert response.getheader("Content-Range") == f"bytes 0-262143/{len(MEDIA)}"
        assert response.getheader("Content-Length") == "262144"
        assert response.read(1024) == MEDIA[:1024]
        assert rig.first_chunk.is_set() and not rig.stream_finished.is_set()
        assert_private_headers(response.getheaders())
        rig.release_stream.set()
        assert response.read() == MEDIA[1024:262144]
    finally:
        rig.release_stream.set()
        connection.close()


def test_gateway_expiry_rejects_old_invite_and_new_authorization(rig, monkeypatch):
    cookie = dual_cookie(rig.proxy)
    deadline = rig.config["expires_at"]
    monkeypatch.setattr(gateway.time, "time", lambda: deadline + 1)
    for path in ("/invite", "/demo2/login", "/api/v1/demo2/upload/media?id=qa"):
        status, _, _ = request(rig.proxy, path, cookie=cookie)
        assert 400 <= status < 500
    status, headers, _ = request(rig.proxy, "/__manager/authorize", method="POST", payload={"secret": INVITE})
    assert 400 <= status < 500 and not header(headers, "Set-Cookie")
    assert rig.calls == []


def test_expired_signed_cookie_stays_invalid_if_gateway_deadline_is_extended(rig, monkeypatch):
    cookie = dual_cookie(rig.proxy)
    extended = rig.start(expires_at=rig.config["expires_at"] + 3600)
    monkeypatch.setattr(gateway.time, "time", lambda: rig.config["expires_at"] + 1)
    status, _, _ = request(extended, "/demo2/login", cookie=cookie)
    assert status == 401
    assert rig.calls == []


@pytest.mark.parametrize("rotation", [{"invite_secret": INVITE + "rotated"}, {"cookie_secret": SIGNING_KEY + "rotated"}])
def test_rotating_either_secret_invalidates_old_invitation(rig, rotation):
    cookie = dual_cookie(rig.proxy)
    rotated = rig.start(**rotation)
    assert request(rotated, "/demo2/login", cookie=cookie)[0] == 401
    assert rig.calls == []


def test_secret_in_query_rejected_without_reflection_or_access_log(rig, capsys):
    status, _, body = request(rig.proxy, "/invite?secret=" + INVITE)
    assert status == 400
    assert INVITE.encode() not in body
    logged = capsys.readouterr()
    assert INVITE not in logged.out + logged.err
    assert rig.calls == []


def test_invitation_failures_are_rate_limited(rig):
    statuses = [request(rig.proxy, "/__manager/authorize", method="POST", payload={"secret": "wrong"})[0]
                for _ in range(10)]
    # Ten failed attempts consume the budget; request eleven is throttled.
    assert statuses == [401] * 10
    status, headers, _ = request(rig.proxy, "/__manager/authorize", method="POST", payload={"secret": INVITE})
    assert status == 429 and header(headers, "Retry-After") == "60"
    assert not header(headers, "Set-Cookie")
    assert rig.calls == []


@pytest.mark.parametrize("extra_headers, expected", [
    ([("Content-Length", "0"), ("Content-Length", "0")], 400),
    ([("Content-Length", "0"), ("Content-Length", "2")], 400),
    ([("Transfer-Encoding", "chunked")], 400),
    ([("Transfer-Encoding", "chunked"), ("Content-Length", "0")], 400),
    ([("Content-Length", str(15 * 1024 * 1024 + 1))], 413),
    ([("Content-Length", "-1")], 400),
    ([("Content-Length", "0"), ("Expect", "100-continue")], 400),
])
def test_ambiguous_framing_and_oversize_rejected_without_reading_body(rig, extra_headers, expected):
    cookie = dual_cookie(rig.proxy)
    connection = http.client.HTTPConnection("127.0.0.1", rig.proxy.server_port, timeout=2)
    try:
        connection.putrequest("POST", "/api/v1/demo2/upload/tasks")
        connection.putheader("Origin", f"https://127.0.0.1:{rig.proxy.server_port}")
        connection.putheader("Cookie", cookie)
        for name, value in extra_headers:
            connection.putheader(name, value)
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == expected
        response.read()
        assert_private_headers(response.getheaders())
        assert rig.calls == []
    finally:
        connection.close()


def test_missing_origin_cannot_forward_post(rig):
    cookie = dual_cookie(rig.proxy)
    connection = http.client.HTTPConnection("127.0.0.1", rig.proxy.server_port, timeout=2)
    try:
        connection.request("POST", "/api/v1/demo2/upload/tasks", body=b"{}", headers={"Cookie": cookie})
        response = connection.getresponse()
        assert response.status == 403
        response.read()
        assert rig.calls == []
    finally:
        connection.close()


@pytest.mark.parametrize("overrides", [{"invite_secret": "short"}, {"cookie_secret": "short"},
    {"cookie_secret": INVITE}, {"expires_at": float("nan")}, {"expires_at": True}])
def test_config_rejects_weak_secrets_or_invalid_deadline(rig, overrides):
    with pytest.raises(ValueError):
        gateway.make_server({**rig.config, **overrides}, port=0)


def test_gateway_cannot_bind_public_interface(rig):
    with pytest.raises(ValueError):
        gateway.make_server(rig.config, host="0.0.0.0", port=0)


@pytest.mark.parametrize('path,method', [
    ('/demo2/student-summary?student_id=synthetic', 'GET'),
    ('/demo2/admin/student-summaries', 'GET'),
    ('/api/v1/demo2/student-summaries/student?student_id=synthetic', 'GET'),
    ('/api/v1/demo2/student-summaries/admin', 'GET'),
    ('/api/v1/demo2/student-summaries/export?public_id=synthetic', 'GET'),
    ('/api/v1/demo2/student-summaries/authorization', 'POST'),
    ('/api/v1/demo2/student-summaries/snapshots', 'POST'),
    ('/api/v1/demo2/student-summaries/authorization/withdraw', 'POST'),
    ('/api/v1/demo2/student-summaries/automatic', 'POST'),
])
def test_summary_routes_keep_invitation_and_account_gates(rig, path, method):
    payload = {} if method == 'POST' else None
    assert request(rig.proxy, path, method=method, payload=payload)[0] in (401, 403)
    assert not rig.calls
    invite, _ = authorize(rig.proxy)
    status, headers, _ = request(rig.proxy, path, method=method, payload=payload, cookie=invite)
    assert status == (303 if path.startswith('/demo2/') else 401)
    if status == 303:
        assert header(headers, 'Location') == '/demo2/login'
    rig.calls.clear()
    status, headers, _ = request(rig.proxy, path, method=method, payload=payload, cookie=dual_cookie(rig.proxy))
    assert status == 200
    assert_private_headers(headers)
    assert rig.calls[-1]['path'] == path


CHUNK_TARGET = '/api/v1/demo2/upload/chunks?task_id=synthetic-task&course_id=synthetic-course&chunk_index=0'
RESUME_TARGET = '/api/v1/demo2/upload/resume'


def begin_upload(rig, cookie, *, target=CHUNK_TARGET, length=4, content_type='application/octet-stream', extra=(), origin=True):
    connection = http.client.HTTPConnection('127.0.0.1', rig.proxy.server_port, timeout=3)
    connection.putrequest('POST', target)
    if origin:
        connection.putheader('Origin', f'https://127.0.0.1:{rig.proxy.server_port}')
    connection.putheader('Cookie', cookie)
    connection.putheader('Content-Type', content_type)
    connection.putheader('Content-Length', str(length))
    for key, value in extra:
        connection.putheader(key, value)
    connection.endheaders()
    return connection


@pytest.mark.parametrize('target,body,content_type', [
    (CHUNK_TARGET, bytes(range(256)) * 16384, 'application/octet-stream'),
    ('/api/v1/demo2/upload/chunks', b'{"task_id":"synthetic","chunk_index":0,"data":"AAEC/w=="}', 'application/json'),
    ('/api/seewo_demo2/video_chunk', b'{"data":"AAEC/w=="}', 'application/json'),
    (RESUME_TARGET, json.dumps({'task_id': 'synthetic-task', 'course_id': 'synthetic-course', 'byte_size': 5 * 1024 ** 3,
                               'filename': 'synthetic.mp4', 'chunk_sha256': ['a' * 64] * 1280}).encode(), 'application/json'),
], ids=['binary-4mib', 'legacy-json', 'legacy-route', 'resume-1280-hashes'])
def test_upload_binary_legacy_and_resume_are_forwarded_unchanged(rig, target, body, content_type):
    cookie = dual_cookie(rig.proxy, 'qa-uploader-session')
    connection = begin_upload(rig, cookie, target=target, length=len(body), content_type=content_type)
    try:
        connection.send(body)
        response = connection.getresponse()
        assert response.status == 200
        response.read()
        assert_private_headers(response.getheaders())
        call = rig.calls[-1]
        assert call['path'] == target and call['body'] == body
        assert call['headers']['Content-Type'] == content_type
        assert call['headers']['Content-Length'] == str(len(body))
        assert call['headers']['Cookie'] == f'{SESSION_NAME}=qa-uploader-session'
        assert INVITE_NAME not in str(call)
    finally:
        connection.close()


def test_paced_chunk_outlasts_normal_json_deadline_without_partial_forwarding(rig, monkeypatch):
    cookie = dual_cookie(rig.proxy)
    monkeypatch.setattr(gateway, 'BODY_TIMEOUT_SECONDS', .08)
    monkeypatch.setattr(gateway, 'UPLOAD_BODY_TIMEOUT_SECONDS', 2)
    monkeypatch.setattr(gateway, 'UPLOAD_IDLE_TIMEOUT_SECONDS', 1)
    body = b'abcdefgh'
    connection = begin_upload(rig, cookie, length=len(body))
    try:
        for value in body[:-1]:
            connection.send(bytes([value]))
            time.sleep(.04)
            assert not any(call['method'] == 'POST' for call in rig.calls)
        connection.send(body[-1:])
        response = connection.getresponse()
        assert response.status == 200
        response.read()
        assert rig.calls[-1]['body'] == body
    finally:
        connection.close()


@pytest.mark.parametrize('target', [CHUNK_TARGET, RESUME_TARGET])
def test_truncated_upload_is_400_never_forwarded_and_does_not_log_body(rig, target, capsys):
    cookie = dual_cookie(rig.proxy)
    connection = begin_upload(rig, cookie, target=target, length=100, content_type='application/json')
    try:
        connection.send(b'PRIVATE-SYNTHETIC-BODY')
        connection.sock.shutdown(socket.SHUT_WR)
        response = connection.getresponse()
        body = response.read()
        assert response.status == 400 and json.loads(body)['error']['code'] == 'incomplete_body'
        assert response.getheader('Connection') == 'close'
        assert not any(call['method'] == 'POST' for call in rig.calls)
        output = capsys.readouterr()
        assert 'PRIVATE-SYNTHETIC-BODY' not in body.decode() + output.out + output.err
        assert INVITE not in output.out + output.err
    finally:
        connection.close()


@pytest.mark.parametrize('target,timeout_name', [
    (CHUNK_TARGET, 'UPLOAD_IDLE_TIMEOUT_SECONDS'),
    (CHUNK_TARGET, 'UPLOAD_BODY_TIMEOUT_SECONDS'),
    (RESUME_TARGET, 'BODY_TIMEOUT_SECONDS'),
    ('/api/v1/demo2/upload/tasks', 'BODY_TIMEOUT_SECONDS'),
])
def test_stalled_or_deadline_upload_returns_408_and_closes(rig, monkeypatch, target, timeout_name):
    cookie = dual_cookie(rig.proxy)
    monkeypatch.setattr(gateway, timeout_name, .12)
    connection = begin_upload(rig, cookie, target=target, content_type='application/json')
    try:
        connection.send(b'{')
        response = connection.getresponse()
        assert response.status == 408
        assert json.loads(response.read())['error']['code'] == 'request_timeout'
        assert response.getheader('Connection') == 'close'
        assert not any(call['method'] == 'POST' for call in rig.calls)
    finally:
        connection.close()


@pytest.mark.parametrize('target,length,content_type,extra,expected,code', [
    (CHUNK_TARGET, gateway.MAX_BODY_BYTES + 1, 'application/octet-stream', (), 413, 'body_too_large'),
    (RESUME_TARGET, gateway.RESUME_MAX_BODY_BYTES + 1, 'application/json', (), 413, 'body_too_large'),
    (RESUME_TARGET, 4, 'application/octet-stream', (), 415, 'unsupported_media_type'),
    (CHUNK_TARGET, 4, 'application/octet-stream', (('Content-Length', '4'),), 400, 'invalid_framing'),
    (CHUNK_TARGET, 4, 'application/octet-stream', (('Transfer-Encoding', 'chunked'),), 400, 'invalid_framing'),
    (CHUNK_TARGET, 4, 'application/octet-stream', (('Expect', '100-continue'),), 400, 'invalid_framing'),
    (CHUNK_TARGET, 4, 'application/octet-stream', (('Content-Type', 'application/json'),), 400, 'invalid_framing'),
    (CHUNK_TARGET, 4, 'application/octet-stream', (('Content-Encoding', 'gzip'),), 415, 'unsupported_content_encoding'),
    (RESUME_TARGET, 4, 'application/json', (('Content-Encoding', 'gzip'),), 415, 'unsupported_content_encoding'),
    ('/api/v1/demo2/dossier/documents', gateway.DOSSIER_MAX_BODY_BYTES + 1, 'application/json', (), 413, 'body_too_large'),
])
def test_upload_limits_and_framing_fail_before_body_read(rig, target, length, content_type, extra, expected, code):
    connection = begin_upload(rig, dual_cookie(rig.proxy), target=target, length=length, content_type=content_type, extra=extra)
    try:
        response = connection.getresponse()
        assert response.status == expected
        assert json.loads(response.read())['error']['code'] == code
        assert_private_headers(response.getheaders())
        assert not any(call['method'] == 'POST' for call in rig.calls)
    finally:
        connection.close()


@pytest.mark.parametrize('target', [CHUNK_TARGET, RESUME_TARGET])
@pytest.mark.parametrize('gate', ['no_invite', 'no_session', 'invalid_session', 'missing_origin', 'cross_origin', 'cross_site'])
def test_new_upload_transports_preserve_all_gates_before_read(rig, target, gate):
    cookie = dual_cookie(rig.proxy)
    if gate == 'no_invite':
        cookie = f'{SESSION_NAME}=qa-uploader-session'
    elif gate == 'no_session':
        cookie = cookie.split(';')[0]
    elif gate == 'invalid_session':
        cookie = cookie.replace('qa-manager-session', 'invalid-session')
    extra = (('Sec-Fetch-Site', 'cross-site'),) if gate == 'cross_site' else ()
    if gate == 'cross_origin':
        extra = (('Origin', 'https://evil.invalid'), ('X-Forwarded-Host', 'evil.invalid'))
    connection = begin_upload(rig, cookie, target=target, content_type='application/json', extra=extra, origin=gate not in {'missing_origin', 'cross_origin'})
    try:
        response = connection.getresponse()
        assert response.status in {401, 403}
        response.read()
        assert not any(call['method'] == 'POST' for call in rig.calls)
    finally:
        connection.close()


def fake_body_reader(monkeypatch, steps, *, expiry=1000, wall_jump=0):
    clock = {'elapsed': 0.0, 'wall': 0.0}
    timeouts = []
    monkeypatch.setattr(gateway.time, 'monotonic', lambda: clock['elapsed'])
    monkeypatch.setattr(gateway.time, 'time', lambda: clock['wall'])
    handler = object.__new__(gateway._GatewayHandler)
    handler.server = SimpleNamespace(config=SimpleNamespace(expires_at=expiry))
    handler.connection = SimpleNamespace(settimeout=timeouts.append)
    iterator = iter(steps)

    def read1(size):
        delay, block = next(iterator)
        clock['elapsed'] += delay
        clock['wall'] += delay + wall_jump
        assert len(block) <= size
        return block

    handler.rfile = SimpleNamespace(read1=read1)
    return handler, timeouts


def test_slow_upload_budget_180_seconds_idle_60_and_normal_json_30(monkeypatch):
    assert gateway.UPLOAD_BODY_TIMEOUT_SECONDS == 180
    assert gateway.UPLOAD_IDLE_TIMEOUT_SECONDS == 60
    assert gateway.BODY_TIMEOUT_SECONDS == 30
    handler, timeouts = fake_body_reader(monkeypatch, [(40, b'a'), (40, b'b'), (40, b'c')])
    assert handler._read_body(3, upload=True) == b'abc'
    assert timeouts == [60, 60, 60, gateway.TIMEOUT_SECONDS]
    handler, _ = fake_body_reader(monkeypatch, [(31, b'a')])
    with pytest.raises(TimeoutError):
        handler._read_body(1)


@pytest.mark.parametrize('expiry,invite_expiry,steps,wall_jump', [
    (1000, None, [(50, b'a')] * 4, 0),
    (45, None, [(20, b'a'), (26, b'b')], 0),
    (1000, 45, [(20, b'a'), (26, b'b')], 0),
    (1000, None, [(50, b'a')] * 4, -100),
])
def test_upload_total_deadline_and_invite_expiry_cannot_be_extended_by_trickle_or_clock_change(monkeypatch, expiry, invite_expiry, steps, wall_jump):
    handler, timeouts = fake_body_reader(monkeypatch, steps, expiry=expiry, wall_jump=wall_jump)
    with pytest.raises(TimeoutError):
        handler._read_body(len(steps), upload=True, invite_expires_at=invite_expiry)
    assert timeouts[-1] == gateway.TIMEOUT_SECONDS


@pytest.mark.parametrize('target,expected', [(CHUNK_TARGET, 120), (RESUME_TARGET, 120), ('/api/v1/demo2/upload/tasks', 10)])
def test_upload_upstream_budget_does_not_change_auth_or_other_routes(rig, monkeypatch, target, expected):
    cookie = dual_cookie(rig.proxy)
    original = gateway._GatewayHandler._connection
    budgets = []

    def connection(handler, *, timeout=gateway.TIMEOUT_SECONDS):
        budgets.append(timeout)
        return original(handler, timeout=timeout)

    monkeypatch.setattr(gateway._GatewayHandler, '_connection', connection)
    result = request(rig.proxy, target, method='POST', payload={}, cookie=cookie)
    assert result[0] == 200
    assert budgets == [10, expected]


@pytest.mark.parametrize('stage', ['auth', 'proxy'])
def test_upstream_timeout_is_504_not_client_body_408(rig, monkeypatch, stage):
    cookie = dual_cookie(rig.proxy)
    original = gateway._GatewayHandler._connection

    def connection(handler, *, timeout=gateway.TIMEOUT_SECONDS):
        if (stage == 'auth' and timeout == 10) or (stage == 'proxy' and timeout == 120):
            def timed_out():
                raise socket.timeout('PRIVATE-UPSTREAM-DETAIL')
            return SimpleNamespace(request=lambda *a, **kw: None, getresponse=timed_out, close=lambda: None)
        return original(handler, timeout=timeout)

    monkeypatch.setattr(gateway._GatewayHandler, '_connection', connection)
    status, headers, body = request(rig.proxy, CHUNK_TARGET, method='POST', payload={}, cookie=cookie)
    assert status == 504 and json.loads(body)['error']['code'] == 'upstream_timeout'
    assert b'PRIVATE-UPSTREAM-DETAIL' not in body
    assert_private_headers(headers)


@pytest.mark.parametrize('target', ['/api/v1/demo2/upload/tasks', CHUNK_TARGET, RESUME_TARGET])
def test_known_storage_full_on_upload_routes_has_fixed_safe_message(rig, target, capsys):
    rig.responses[target] = (507, json.dumps({'ok': False, 'error': {
        'code': 'insufficient_storage', 'message': 'PRIVATE-DISK-PATH-and-student',
        'detail': 'PRIVATE-UPSTREAM-TRACE'}, 'free_bytes': 1234567}).encode())
    status, headers, body = request(rig.proxy, target, method='POST', payload={}, cookie=dual_cookie(rig.proxy))
    assert status == 507
    assert json.loads(body) == {'ok': False, 'error': {
        'code': 'insufficient_storage', 'message': '服务器存储空间不足，请联系管理员扩容后再重试上传。'}}
    assert_private_headers(headers)
    captured = capsys.readouterr()
    assert 'PRIVATE-' not in body.decode() + captured.out + captured.err
    assert '1234567' not in body.decode()


@pytest.mark.parametrize('target,method,status,payload', [
    (CHUNK_TARGET, 'POST', 507, {'error': {'code': 'other_storage_error', 'message': 'PRIVATE-TRACE'}}),
    (CHUNK_TARGET, 'POST', 500, {'error': {'code': 'insufficient_storage', 'message': 'PRIVATE-TRACE'}}),
    ('/api/v1/demo2/school/context', 'POST', 507, {'error': {'code': 'insufficient_storage'}}),
    ('/api/seewo_demo2/video_chunk', 'POST', 507, {'error': {'code': 'insufficient_storage'}}),
    ('/api/v1/demo2/upload/task?id=synthetic', 'GET', 507, {'error': {'code': 'insufficient_storage'}}),
    (RESUME_TARGET, 'POST', 507, {'error': 'PRIVATE-TRACE'}),
    (RESUME_TARGET, 'POST', 507, {'error': {'code': ['insufficient_storage']}}),
    (RESUME_TARGET, 'POST', 507, [{'error': {'code': 'insufficient_storage'}}]),
    (RESUME_TARGET, 'POST', 507, {'error': {'code': 'insufficient_storage'}, 'private': 'x' * 8192}),
], ids=['unknown-code', 'other-status', 'other-post', 'legacy-post', 'get', 'bad-error', 'bad-code', 'array', 'oversize'])
def test_other_upstream_errors_remain_sanitized(rig, target, method, status, payload):
    rig.responses[target] = status, json.dumps(payload).encode()
    actual, headers, body = request(rig.proxy, target, method=method, payload={} if method == 'POST' else None,
                                    cookie=dual_cookie(rig.proxy))
    assert actual == status
    assert json.loads(body) == {'ok': False, 'error': {'code': 'upstream_unavailable', 'message': '平台暂不可用，请稍后重试'}}
    assert_private_headers(headers)


@pytest.mark.parametrize('payload', [b'PRIVATE-not-json', b'\xffPRIVATE-invalid-utf8'])
def test_malformed_507_json_remains_sanitized(rig, payload):
    rig.responses[CHUNK_TARGET] = 507, payload
    status, _, body = request(rig.proxy, CHUNK_TARGET, method='POST', payload={}, cookie=dual_cookie(rig.proxy))
    assert status == 507 and json.loads(body)['error']['code'] == 'upstream_unavailable'
    assert b'PRIVATE' not in body


def test_long_download_has_read_idle_timeout_not_ten_second_total_deadline(monkeypatch):
    clock = {'now': 0}
    monkeypatch.setattr(gateway.time, 'time', lambda: clock['now'])
    blocks = iter([b'first', b'second', b'third', b''])
    budgets = []

    def read1(size):
        assert size == 65536
        clock['now'] += 6
        return next(blocks)

    response = SimpleNamespace(status=200, getheaders=lambda: [('Content-Length', '16')], read1=read1)
    upstream = SimpleNamespace(request=lambda *a, **kw: None, getresponse=lambda: response,
                               sock=SimpleNamespace(settimeout=budgets.append), close=lambda: None)
    handler = object.__new__(gateway._GatewayHandler)
    handler.server = SimpleNamespace(config=SimpleNamespace(expires_at=1000))
    handler.command = 'GET'
    handler.wfile = io.BytesIO()
    handler._upstream_headers = lambda cookies: {}
    handler._headers = lambda status, headers: None

    def connection(*, timeout):
        assert timeout == 10
        return upstream

    handler._connection = connection
    handler._proxy('/api/v1/demo2/upload/media?id=synthetic', b'', {})
    assert clock['now'] == 24
    assert handler.wfile.getvalue() == b'firstsecondthird'
    assert budgets == [10, 10, 10, 10]
    assert handler.close_connection is True
