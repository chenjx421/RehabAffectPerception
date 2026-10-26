"""Rejected gateway requests: drain small bodies, never read upload or oversize bodies."""

from __future__ import annotations

import json
import logging
import socket
import threading
import time

import pytest

from src.rehab_affect import demo2_manager_gateway as gateway
from test_demo2_manager_gateway import authorize, dual_cookie, rig  # noqa: F401  (pytest fixture)


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.entries: list[dict] = []
        self.entries_lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            value = json.loads(record.getMessage())
        except ValueError:
            return
        with self.entries_lock:
            self.entries.append(value)

    def wait_for(self, path: str, timeout: float = 5.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.entries_lock:
                for entry in self.entries:
                    if entry.get("path") == path:
                        return entry
            time.sleep(.02)
        raise AssertionError(f"no rejection log for {path}: {self.entries}")


@pytest.fixture()
def reject_log():
    collector = _Collector()
    previous = gateway.REJECT_LOGGER.level
    gateway.REJECT_LOGGER.addHandler(collector)
    gateway.REJECT_LOGGER.setLevel(logging.DEBUG)
    try:
        yield collector
    finally:
        gateway.REJECT_LOGGER.removeHandler(collector)
        gateway.REJECT_LOGGER.setLevel(previous)


def _head(proxy, method: str, path: str, length: int, cookie: str = "", extra: str = "") -> bytes:
    host = f"127.0.0.1:{proxy.server_port}"
    lines = [f"{method} {path} HTTP/1.1", f"Host: {host}", f"Origin: https://{host}",
             "Content-Type: application/json", f"Content-Length: {length}"]
    if cookie:
        lines.append(f"Cookie: {cookie}")
    if extra:
        lines.append(extra)
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


def _read_response(sock: socket.socket) -> tuple[int, dict[str, str], bytes]:
    """Read until EOF; a reset before the full response fails the test."""
    data = b""
    while True:
        block = sock.recv(65536)
        if not block:
            break
        data += block
    head, separator, body = data.partition(b"\r\n\r\n")
    assert separator, data
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split()[1])
    headers = {}
    for line in lines[1:]:
        key, _, value = line.partition(":")
        headers[key.strip().lower()] = value.strip()
    assert len(body) == int(headers["content-length"]), "truncated rejection response"
    return status, headers, body


def _send_full(proxy, method: str, path: str, body: bytes, cookie: str = "") -> tuple[int, dict, bytes]:
    with socket.create_connection(("127.0.0.1", proxy.server_port), timeout=5) as sock:
        sock.sendall(_head(proxy, method, path, len(body), cookie) + body)
        return _read_response(sock)


@pytest.mark.parametrize("size", [1, 2048, 32 * 1024, gateway.REJECT_BODY_DRAIN_MAX_BYTES])
def test_small_unauthenticated_post_is_drained_then_gets_complete_401(rig, reject_log, size):
    body = b"{" + b" " * (size - 2) + b"}" if size > 1 else b"0"
    status, headers, payload = _send_full(rig.proxy, "POST", "/api/v1/demo2/evaluations", body)
    assert status == 401
    assert json.loads(payload)["error"]["code"] == "invitation_required"
    assert headers["connection"] == "close"
    entry = reject_log.wait_for("/api/v1/demo2/evaluations")
    assert entry["drain"] == "drained" and entry["drained"] is True
    assert entry["body_bytes_read"] == size
    assert entry["content_length"] == size and entry["status"] == 401
    assert rig.calls == []


def test_invited_but_unauthenticated_small_post_gets_complete_401(rig, reject_log):
    invite, _ = authorize(rig.proxy)
    body = json.dumps({"student_id": "synthetic", "note": "x" * 4000}).encode()
    status, _, payload = _send_full(rig.proxy, "POST", "/api/v1/demo2/measurements", body, invite)
    assert status == 401
    assert json.loads(payload)["error"]["code"] == "authentication_required"
    entry = reject_log.wait_for("/api/v1/demo2/measurements")
    assert entry["drain"] == "drained" and entry["body_bytes_read"] == len(body)
    assert all(call["path"] != "/api/v1/demo2/measurements" for call in rig.calls)


def test_small_post_to_unknown_protected_route_gets_complete_404(rig, reject_log):
    cookie = dual_cookie(rig.proxy)
    body = b'{"synthetic":true}' + b" " * 8000
    status, _, payload = _send_full(rig.proxy, "POST", "/api/v1/demo2/not-a-route", body, cookie)
    assert status == 404
    assert json.loads(payload)["error"]["code"] == "route_not_allowed"
    entry = reject_log.wait_for("/api/v1/demo2/not-a-route")
    assert entry["drain"] == "drained" and entry["status"] == 404
    assert rig.calls == []


@pytest.mark.parametrize("method", ["PUT", "DELETE", "PATCH"])
def test_small_body_with_illegal_method_is_drained_and_rejected(rig, reject_log, method):
    cookie = dual_cookie(rig.proxy)
    body = b'{"synthetic":true}'
    status, _, payload = _send_full(rig.proxy, method, "/api/v1/demo2/evaluations", body, cookie)
    assert status == 400
    assert json.loads(payload)["ok"] is False
    entry = reject_log.wait_for("/api/v1/demo2/evaluations")
    assert entry["method"] == method and entry["drain"] == "drained"
    assert rig.calls == []


@pytest.mark.parametrize("path, length", [
    ("/api/v1/demo2/upload/chunks", 4 * 1024 * 1024),
    ("/api/v1/demo2/upload/chunks", 1024),
    ("/api/v1/demo2/upload/resume", 2048),
    ("/api/seewo_demo2/video_chunk", 1024 * 1024),
])
def test_unauthenticated_upload_body_is_never_read(rig, reject_log, path, length):
    # The client withholds the body: a response proves no body byte was needed.
    with socket.create_connection(("127.0.0.1", rig.proxy.server_port), timeout=5) as sock:
        sock.sendall(_head(rig.proxy, "POST", path, length))
        status, _, payload = _read_response(sock)
    assert status == 401
    assert json.loads(payload)["error"]["code"] == "invitation_required"
    entry = reject_log.wait_for(path)
    assert entry["drain"] == "upload_unread" and entry["upload_route"] is True
    assert entry["body_bytes_read"] == 0 and entry["lingered_bytes"] == 0
    assert rig.calls == []


def test_invited_but_unauthenticated_upload_chunk_is_never_read(rig, reject_log):
    invite, _ = authorize(rig.proxy)
    path = "/api/v1/demo2/upload/chunks?task_id=synthetic&index=0"
    with socket.create_connection(("127.0.0.1", rig.proxy.server_port), timeout=5) as sock:
        sock.sendall(_head(rig.proxy, "POST", path, 2 * 1024 * 1024, invite))
        status, _, _ = _read_response(sock)
    assert status == 401
    entry = reject_log.wait_for("/api/v1/demo2/upload/chunks")
    assert entry["drain"] == "upload_unread" and entry["body_bytes_read"] == 0
    assert all(not call["path"].startswith("/api/v1/demo2/upload/") for call in rig.calls)


def test_oversize_non_upload_rejection_is_not_buffered_and_closes_safely(rig, reject_log):
    declared = 8 * 1024 * 1024
    sent = {"bytes": 0}

    with socket.create_connection(("127.0.0.1", rig.proxy.server_port), timeout=5) as sock:
        sock.sendall(_head(rig.proxy, "POST", "/api/v1/demo2/evaluations", declared))

        def pump():
            block = b" " * 65536
            try:
                while sent["bytes"] < declared:
                    sock.sendall(block)
                    sent["bytes"] += len(block)
            except OSError:
                pass  # The gateway stops reading; a broken pipe here is expected.

        sender = threading.Thread(target=pump, daemon=True)
        sender.start()
        status, _, payload = _read_response(sock)
        sender.join(5)
    assert status == 401
    assert json.loads(payload)["error"]["code"] == "invitation_required"
    entry = reject_log.wait_for("/api/v1/demo2/evaluations")
    assert entry["drain"] == "oversize_unread" and entry["drained"] is False
    assert entry["body_bytes_read"] == 0
    assert entry["lingered_bytes"] <= gateway.REJECT_LINGER_MAX_BYTES
    assert entry["content_length"] == declared
    assert rig.calls == []


def test_oversize_without_body_bytes_gets_response_without_waiting_for_body(rig, reject_log):
    started = time.monotonic()
    with socket.create_connection(("127.0.0.1", rig.proxy.server_port), timeout=5) as sock:
        sock.sendall(_head(rig.proxy, "POST", "/api/v1/demo2/dossier/documents", 128 * 1024))
        status, _, _ = _read_response(sock)
    assert status == 401
    assert time.monotonic() - started < gateway.REJECT_LINGER_SECONDS + 2
    entry = reject_log.wait_for("/api/v1/demo2/dossier/documents")
    assert entry["drain"] == "oversize_unread" and entry["body_bytes_read"] == 0


def test_truncated_small_body_is_bounded_and_not_forwarded(rig, reject_log, monkeypatch):
    monkeypatch.setattr(gateway, "REJECT_DRAIN_TIMEOUT_SECONDS", .4)
    monkeypatch.setattr(gateway, "REJECT_DRAIN_IDLE_SECONDS", .2)
    with socket.create_connection(("127.0.0.1", rig.proxy.server_port), timeout=5) as sock:
        sock.sendall(_head(rig.proxy, "POST", "/api/v1/demo2/evaluations", 4096) + b"{" * 100)
        status, _, _ = _read_response(sock)
    assert status == 401
    entry = reject_log.wait_for("/api/v1/demo2/evaluations")
    assert entry["drain"] == "drain_failed" and entry["body_bytes_read"] == 100
    assert rig.calls == []


def test_rejection_log_has_debug_fields_and_never_query_or_cookie(rig, reject_log, tmp_path, monkeypatch):
    monkeypatch.setenv(gateway.REJECT_DEBUG_LOG_DIR_ENV, str(tmp_path))
    invite, _ = authorize(rig.proxy)
    body = b'{"secret":"must-not-be-logged"}'
    status, _, _ = _send_full(rig.proxy, "POST", "/api/v1/demo2/evaluations?token=query-secret", body,
                              f"{invite}; rehab_demo2_session=forged-session")
    assert status == 401
    entry = reject_log.wait_for("/api/v1/demo2/evaluations")
    for field in ("ts", "method", "path", "content_length", "drain", "drained", "status", "code",
                  "body_bytes_read", "upload_route", "lingered_bytes", "duration_ms"):
        assert field in entry
    assert entry["ts"][:4].isdigit() and "T" in entry["ts"]
    assert entry["method"] == "POST" and entry["content_length"] == len(body)
    files = list(tmp_path.glob("gateway_reject_*.jsonl"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    for secret in ("query-secret", "must-not-be-logged", "forged-session", "rehab_manager_invite"):
        assert secret not in text
    assert json.loads(text.strip().splitlines()[-1])["status"] == 401


def test_authenticated_post_is_still_forwarded_and_not_logged_as_rejection(rig, reject_log):
    cookie = dual_cookie(rig.proxy)
    body = b'{"synthetic":true}'
    status, _, payload = _send_full(rig.proxy, "POST", "/api/v1/demo2/evaluations", body, cookie)
    assert status == 200 and payload == b"synthetic-student-resource"
    assert any(call["path"] == "/api/v1/demo2/evaluations" and call["body"] == body for call in rig.calls)
    time.sleep(.1)
    assert all(entry.get("path") != "/api/v1/demo2/evaluations" for entry in reject_log.entries)
