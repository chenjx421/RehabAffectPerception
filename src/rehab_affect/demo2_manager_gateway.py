"""Temporary, loopback-only Demo2 invitation gateway (standard library only).

Contract: make_server(config, *, host="127.0.0.1", port=None) returns an
unstarted HTTP server; port=0 is supported for isolated tests. The upstream
host is always 127.0.0.1. TLS must terminate at a separately authorized ingress;
this module never creates a tunnel, starts the upstream, or provisions users.

Config JSON: invite_secret, cookie_secret (independent, >=32 UTF-8 bytes),
expires_at (epoch seconds), upstream_port (default 8792), listen_port.
POST /__manager/authorize {"secret": ...} sets rehab_manager_invite and returns
303 /demo2/login. This gate does NOT replace the upstream account session.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import http.client
import ipaddress
import json
import math
import re
import secrets
import socket
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit


INVITE_COOKIE_NAME = "rehab_manager_invite"
SESSION_COOKIE_NAME = "rehab_demo2_session"
MAX_BODY_BYTES = 15 * 1024 * 1024
DOSSIER_MAX_BODY_BYTES = 12 * 1024 * 1024
DOSSIER_API_PREFIX = "/api/v1/demo2/dossier"
TIMEOUT_SECONDS = 10.0
BODY_TIMEOUT_SECONDS = 30.0
UPLOAD_BODY_TIMEOUT_SECONDS = 180.0
UPLOAD_IDLE_TIMEOUT_SECONDS = 60.0
UPLOAD_UPSTREAM_TIMEOUT_SECONDS = 120.0
_UPLOAD_CHUNK_PATHS = frozenset({"/api/v1/demo2/upload/chunks", "/api/seewo_demo2/video_chunk"})
_UPLOAD_RESUME_PATH = "/api/v1/demo2/upload/resume"
RESUME_MAX_BODY_BYTES = 128 * 1024
AUTH_PATH = "/api/v1/demo2/auth/me"
_PAGES = frozenset({
    "/demo2/safety",
    "/demo2/course-batch", "/demo2/teaching-support",
    "/demo2/login", "/demo2/school", "/demo2/upload", "/demo2/admin",
    "/demo2/analysis", "/demo2/video", "/demo2/privacy", "/demo2/help", "/demo2/register", "/demo2/membership",
    "/demo2/students", "/demo2/identity",
    "/demo2/simple-result",
    "/demo2/admin/channels",
    "/demo2/measurement", "/demo2/admin/measurements", "/demo2/capture", "/demo2/evaluation",
    "/demo2/dossier", "/demo2/course-dossier", "/demo2/admin/dossiers", "/seewo_student_demo2",
    "/demo2/student-summary", "/demo2/admin/student-summaries",
})
_GET_API = frozenset({
    "/api/v1/demo2/applicability",
    "/api/v1/demo2/safety", "/api/v1/demo2/safety/media",
    "/api/v1/demo2/course-analysis", "/api/v1/demo2/course-analysis/tasks",
    "/api/v1/demo2/course-batch", "/api/v1/demo2/teaching-support",
    AUTH_PATH, "/api/v1/demo2/school/context", "/api/v1/demo2/upload/workspace",
    "/api/v1/demo2/upload/task", "/api/v1/demo2/upload/media",
    "/api/v1/demo2/upload/result", "/api/v1/demo2/admin/summary",
    "/api/v1/demo2/simple-result", "/api/v1/demo2/simple-result/frame",
    "/api/v1/demo2/membership/config", "/api/v1/demo2/membership", "/api/v1/demo2/admin/memberships",
    "/api/v1/demo2/identity/roster", "/api/v1/demo2/identity/workspace",
    "/api/v1/demo2/identity/frame", "/api/v1/demo2/identity/export", "/api/v1/demo2/identity/detect",
    "/api/v1/demo2/identity/preview",
    "/api/v1/demo2/admin/channels",
    "/api/v1/demo2/dossier/student", "/api/v1/demo2/dossier/task", "/api/v1/demo2/dossier/admin",
    "/api/v1/demo2/dossier/document", "/api/v1/demo2/dossier/reference",
    "/api/seewo_demo2/video_result_download",
    "/api/v1/demo2/measurements", "/api/v1/demo2/admin/measurements", "/api/v1/demo2/evaluations",
    "/api/v1/demo2/student-summaries/student", "/api/v1/demo2/student-summaries/admin",
    "/api/v1/demo2/student-summaries/export",
})
_POST_API = frozenset({
    "/api/v1/demo2/applicability",
    "/api/v1/demo2/safety/create", "/api/v1/demo2/safety/update",
    "/api/v1/demo2/course-batch/confirm", "/api/v1/demo2/teaching-support/plan",
    "/api/v1/demo2/auth/login", "/api/v1/demo2/auth/logout", "/api/v1/demo2/auth/register",
    "/api/v1/demo2/auth/sms-code", "/api/v1/demo2/membership/orders",
    "/api/v1/demo2/school/context", "/api/v1/demo2/upload/tasks",
    "/api/v1/demo2/upload/chunks", "/api/v1/demo2/upload/tasks/cancel",
    _UPLOAD_RESUME_PATH,
    "/api/v1/demo2/upload/tasks/retry", "/api/v1/demo2/upload/tasks/enqueue",
    "/api/v1/demo2/identity/students", "/api/v1/demo2/identity/bindings",
    "/api/v1/demo2/identity/bindings/revoke",
    "/api/v1/demo2/identity/task-school",
    "/api/v1/demo2/identity/track", "/api/v1/demo2/admin/channels",
    "/api/v1/demo2/dossier/authorization", "/api/v1/demo2/dossier/authorization/withdraw",
    "/api/v1/demo2/dossier/documents", "/api/v1/demo2/dossier/documents/delete", "/api/v1/demo2/dossier/references",
    "/api/seewo_demo2/security_acceptance", "/api/seewo_demo2/video_task", "/api/seewo_demo2/video_chunk",
    "/api/v1/demo2/measurements", "/api/v1/demo2/measurements/withdraw",
    "/api/v1/demo2/evaluations", "/api/v1/demo2/evaluations/preview", "/api/v1/demo2/evaluations/withdraw",
    "/api/v1/demo2/student-summaries/authorization", "/api/v1/demo2/student-summaries/snapshots",
    "/api/v1/demo2/student-summaries/authorization/withdraw",
    "/api/v1/demo2/student-summaries/automatic",
})
_PUBLIC_UPSTREAM = frozenset({
    "/demo2/login", "/demo2/privacy", "/demo2/help", "/demo2/register", AUTH_PATH,
    "/api/v1/demo2/auth/login", "/api/v1/demo2/auth/logout", "/api/v1/demo2/auth/register",
    "/api/v1/demo2/auth/sms-code", "/api/v1/demo2/membership/config",
})
_RESPONSE_HEADERS = frozenset({
    "content-type", "content-length", "content-disposition", "content-encoding",
    "content-range", "accept-ranges", "etag", "last-modified", "retry-after",
})
_SECURITY_HEADERS = {
    "Cache-Control": "no-store, private", "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
}
_MEMBERSHIP_PUBLIC_FAILURES = {
    "sms_not_configured": "短信服务尚未配置，暂时无法完成手机号注册",
    "sms_send_failed": "短信发送未完成，请稍后重试",
    "payment_not_configured": "支付服务尚未配置，暂时无法创建订单",
    "membership_unavailable": "会员服务暂不可用，请稍后重试",
}


@dataclass(frozen=True)
class GatewayConfig:
    invite_secret: str
    cookie_secret: str
    expires_at: float
    upstream_port: int = 8792
    listen_port: int = 8793

    def __post_init__(self) -> None:
        for value in (self.invite_secret, self.cookie_secret):
            if not isinstance(value, str) or not 32 <= len(value.encode("utf-8")) <= 4096:
                raise ValueError("Gateway secrets must contain 32 to 4096 UTF-8 bytes")
        if hmac.compare_digest(self.invite_secret.encode(), self.cookie_secret.encode()):
            raise ValueError("Invitation and signing secrets must be independent")
        if isinstance(self.expires_at, bool) or not isinstance(self.expires_at, (int, float)) or not math.isfinite(self.expires_at):
            raise ValueError("expires_at must be a finite epoch timestamp")
        for port, minimum in ((self.upstream_port, 1), (self.listen_port, 0)):
            if isinstance(port, bool) or not isinstance(port, int) or not minimum <= port <= 65535:
                raise ValueError("Invalid gateway port")


def load_config(path: str | Path) -> GatewayConfig:
    with Path(path).open(encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("Gateway config must be a JSON object")
    return GatewayConfig(**value)


def _safe_target(target: str) -> tuple[str, str]:
    """No path decoding differences between ingress, proxy and upstream."""
    if not target.startswith("/") or target.startswith("//") or len(target) > 16384:
        raise ValueError("Invalid request target")
    if any(ord(char) < 33 or ord(char) > 126 for char in target) or "#" in target or "\\" in target:
        raise ValueError("Invalid request target")
    path, _, query = target.partition("?")
    # Our public paths/assets are ASCII. Reject all encoded path bytes rather
    # than normalizing double encoding, separators, dot segments or NULs.
    if "%" in path or ";" in path or "//" in path or any(part in {".", ".."} for part in path.split("/")):
        raise ValueError("Encoded or ambiguous path")
    if re.search(r"%(?![0-9a-fA-F]{2})", query):
        raise ValueError("Invalid query encoding")
    if any(ord(char) < 32 or ord(char) == 127 for char in unquote(query)):
        raise ValueError("Invalid query")
    return path, target


def _allowed(method: str, path: str) -> bool:
    if method == "GET":
        return path in _PAGES or path in _GET_API
    return method == "POST" and path in _POST_API


class _Failures:
    def __init__(self, *, limit: int = 10, window: int = 60) -> None:
        self.lock = threading.Lock()
        self.entries: OrderedDict[str, tuple[float, int]] = OrderedDict()
        self.limit = limit
        self.window = window

    def blocked(self, address: str, *, failure: bool = False) -> bool:
        now = time.monotonic()
        with self.lock:
            start, count = self.entries.get(address, (now, 0))
            if now - start >= self.window:
                start, count = now, 0
            blocked = count >= self.limit
            if failure:
                count += 1
            self.entries[address] = (start, count)
            self.entries.move_to_end(address)
            while len(self.entries) > 4096:
                self.entries.popitem(last=False)
            return blocked


class _GatewayServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, address: tuple[str, int], config: GatewayConfig):
        self.config = config
        self.failures = _Failures()
        # A global budget cannot be bypassed by obtaining another invitation
        # cookie or forging proxy IP headers. Gate failures use a separate bucket.
        self.login_attempts = _Failures(limit=20, window=300)
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(address, _GatewayHandler)

    def process_request(self, request: socket.socket, client_address: Any) -> None:
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request: socket.socket, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    def handle_error(self, request: Any, client_address: Any) -> None:
        # Never print requests, URLs, cookies, config contents or decoder traces.
        pass


class _InvalidFraming(ValueError):
    pass


class _IncompleteBody(ValueError):
    pass


class _UpstreamTimeout(TimeoutError):
    pass


class _GatewayHandler(BaseHTTPRequestHandler):
    server_version = "Demo2Gateway"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def setup(self) -> None:
        self.request.settimeout(TIMEOUT_SECONDS)
        super().setup()

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        self._error(code, "invalid_request", "Request rejected")

    def _headers(self, status: int, headers: list[tuple[str, str]]) -> None:
        self.send_response(status)
        for key, value in headers:
            self.send_header(key, value)
        for key, value in _SECURITY_HEADERS.items():
            self.send_header(key, value)
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def _respond(self, status: int, body: bytes = b"", *, content_type: str = "application/json; charset=utf-8",
                 headers: list[tuple[str, str]] | None = None) -> None:
        self._headers(status, [("Content-Type", content_type), ("Content-Length", str(len(body))), *(headers or [])])
        if self.command != "HEAD":
            self.wfile.write(body)

    def _error(self, status: int, code: str, message: str) -> None:
        body = json.dumps({"ok": False, "error": {"code": code, "message": message}}, ensure_ascii=False).encode()
        self._respond(status, body, headers=[("Retry-After", "60")] if status == 429 else None)

    def _expired(self) -> bool:
        return time.time() >= self.server.config.expires_at

    def _cookies(self) -> dict[str, str]:
        result = {}
        for header in self.headers.get_all("Cookie", []):
            for pair in header.split(";"):
                name, separator, value = pair.strip().partition("=")
                if name not in {INVITE_COOKIE_NAME, SESSION_COOKIE_NAME}:
                    continue
                if not separator or name in result or not re.fullmatch(r"[A-Za-z0-9._~=-]{1,1024}", value):
                    raise ValueError("Invalid or duplicate cookie")
                result[name] = value
        return result

    def _signature(self, payload: str) -> str:
        config = self.server.config
        scope = hashlib.sha256(config.invite_secret.encode()).hexdigest()
        return hmac.new(config.cookie_secret.encode(), f"{scope}:{payload}".encode(), hashlib.sha256).hexdigest()

    def _invited(self, cookies: dict[str, str]) -> bool:
        value = cookies.get(INVITE_COOKIE_NAME, "")
        match = re.fullmatch(r"(v1\.([0-9]{1,12})\.[A-Za-z0-9_-]{32})\.([a-f0-9]{64})", value)
        if not match:
            return False
        expiry = int(match[2])
        return hmac.compare_digest(match[3], self._signature(match[1])) and time.time() < expiry <= self.server.config.expires_at

    def _gate_failure(self) -> None:
        blocked = self.server.failures.blocked(self.client_address[0], failure=True)
        self._error(429 if blocked else 401, "rate_limited" if blocked else "invitation_required",
                    "邀请验证失败，请重新打开有效邀请链接")

    def _same_origin(self) -> bool:
        if len(self.headers.get_all("Origin", [])) != 1 or len(self.headers.get_all("Host", [])) != 1:
            return False
        if any(value.lower() not in {"same-origin", "none"} for value in self.headers.get_all("Sec-Fetch-Site", [])):
            return False
        origin = self.headers["Origin"]
        host = self.headers["Host"]
        if not re.fullmatch(r"(?:[A-Za-z0-9.-]+|\[[0-9A-Fa-f:]+\])(?::[0-9]{1,5})?", host):
            return False
        try:
            parsed = urlsplit(origin)
            if parsed.scheme not in {"https", "http"} or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
                return False
            # HTTP is useful only for loopback tests; externally shared entry
            # points must be HTTPS. Never trust X-Forwarded-Proto/Host here.
            if parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                return False
            return parsed.netloc.lower() == host.lower()
        except ValueError:
            return False

    def _body_length(self) -> int:
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get_all("Transfer-Encoding") or len(lengths) > 1 or self.headers.get_all("Expect"):
            raise _InvalidFraming("Ambiguous request framing")
        if len(self.headers.get_all("Content-Type", [])) > 1:
            raise _InvalidFraming("Ambiguous content type")
        if self.command == "POST" and not lengths:
            raise _InvalidFraming("Content-Length required")
        if lengths and not re.fullmatch(r"[0-9]{1,10}", lengths[0]):
            raise _InvalidFraming("Invalid Content-Length")
        length = int(lengths[0]) if lengths else 0
        if length > MAX_BODY_BYTES:
            raise OverflowError("Request body too large")
        if self.command != "POST" and length:
            raise _InvalidFraming("Body not allowed")
        return length

    def handle_expect_100(self) -> bool:
        self._error(400, "invalid_framing", "Expect and chunked requests are not supported")
        return False

    def _read_body(self, length: int, *, upload: bool = False, invite_expires_at: float | None = None) -> bytes:
        # Only authenticated chunk routes get the slow-upload budget. A hard,
        # monotonic deadline prevents a trickling client from holding a slot forever.
        deadline = time.monotonic() + (UPLOAD_BODY_TIMEOUT_SECONDS if upload else BODY_TIMEOUT_SECONDS)
        idle_timeout = UPLOAD_IDLE_TIMEOUT_SECONDS if upload else TIMEOUT_SECONDS
        expiry = min(self.server.config.expires_at, invite_expires_at or self.server.config.expires_at)
        blocks, remaining = [], length

        def time_left() -> float:
            return min(deadline - time.monotonic(), expiry - time.time(),
                       self.server.config.expires_at - time.time())

        try:
            while remaining:
                available = time_left()
                if available <= 0:
                    raise TimeoutError("Body deadline exceeded")
                self.connection.settimeout(min(idle_timeout, available))
                try:
                    block = self.rfile.read1(min(65536, remaining))
                except (ConnectionResetError, ConnectionAbortedError) as exc:
                    raise _IncompleteBody("Interrupted request body") from exc
                if time_left() <= 0:
                    raise TimeoutError("Body deadline exceeded")
                if not block:
                    raise _IncompleteBody("Incomplete request body")
                blocks.append(block)
                remaining -= len(block)
            return b"".join(blocks)
        finally:
            self.connection.settimeout(TIMEOUT_SECONDS)

    def _invite_page(self) -> None:
        nonce = secrets.token_urlsafe(18)
        page = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>经理访问验证</title>
<body><h1>经理访问验证</h1><p id="status">正在验证邀请，验证后仍需登录平台账号。</p>
<script nonce="NONCE">(async()=>{let raw=location.hash.slice(1);history.replaceState(null,'','/invite');
let secret=raw.startsWith('secret=')?new URLSearchParams(raw).get('secret'):raw;raw='';
try{if(!secret)throw new Error();const response=await fetch('/__manager/authorize',{
method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({secret}),credentials:'same-origin'});
secret='';if(!response.ok)throw new Error();location.replace('/demo2/login');}
catch(e){secret='';document.getElementById('status').textContent='邀请无效、已到期或暂时受限，请向邀请人申请新链接。';}})();
</script></body></html>""".replace("NONCE", nonce)
        self._respond(200, page.encode(), content_type="text/html; charset=utf-8", headers=[
            ("Content-Security-Policy", f"default-src 'none'; script-src 'nonce-{nonce}'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"),
        ])

    def _authorize(self, body: bytes) -> None:
        if len(body) > 8192 or self.headers.get_content_type() != "application/json":
            self._gate_failure()
            return
        try:
            value = json.loads(body)
            secret = value.get("secret") if isinstance(value, dict) else None
            supplied = hashlib.sha256(secret.encode()).digest() if isinstance(secret, str) else b""
        except (ValueError, UnicodeError):
            supplied = b""
        expected = hashlib.sha256(self.server.config.invite_secret.encode()).digest()
        if not hmac.compare_digest(supplied, expected):
            self._gate_failure()
            return
        now = time.time()
        expiry = math.floor(self.server.config.expires_at)
        max_age = math.floor(expiry - now)
        if max_age <= 0:
            self._error(410, "invitation_expired", "邀请已到期")
            return
        payload = f"v1.{expiry}.{secrets.token_urlsafe(24)}"
        cookie = f"{INVITE_COOKIE_NAME}={payload}.{self._signature(payload)}; HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age={max_age}"
        self._respond(303, headers=[("Set-Cookie", cookie), ("Location", "/demo2/login")])

    def _upstream_headers(self, cookies: dict[str, str]) -> dict[str, str]:
        result = {"Host": f"127.0.0.1:{self.server.config.upstream_port}", "Connection": "close"}
        for key in ("Accept", "Accept-Language", "Content-Type", "Range", "If-Range"):
            if self.headers.get(key):
                result[key] = self.headers[key]
        if cookies.get(SESSION_COOKIE_NAME):
            result["Cookie"] = f"{SESSION_COOKIE_NAME}={cookies[SESSION_COOKIE_NAME]}"
        return result

    def _connection(self, *, timeout: float = TIMEOUT_SECONDS) -> http.client.HTTPConnection:
        remaining = self.server.config.expires_at - time.time()
        if remaining <= 0:
            raise TimeoutError("Invitation expired")
        return http.client.HTTPConnection("127.0.0.1", self.server.config.upstream_port,
                                          timeout=min(timeout, remaining))

    def _authenticated(self, cookies: dict[str, str]) -> bool:
        if not cookies.get(SESSION_COOKIE_NAME):
            return False
        connection = self._connection()
        try:
            connection.request("GET", AUTH_PATH, headers={
                "Host": f"127.0.0.1:{self.server.config.upstream_port}", "Connection": "close",
                "Cookie": f"{SESSION_COOKIE_NAME}={cookies[SESSION_COOKIE_NAME]}", "Accept": "application/json",
            })
            response = connection.getresponse()
            if response.status in {401, 403}:
                return False
            if response.status != 200:
                raise http.client.HTTPException("Authentication service unavailable")
            try:
                raw = response.read(65537)
                if len(raw) > 65536:
                    raise http.client.HTTPException("Authentication response too large")
                value = json.loads(raw)
            except (ValueError, UnicodeError) as exc:
                raise http.client.HTTPException("Invalid authentication response") from exc
            return isinstance(value, dict) and value.get("ok") is True and isinstance(value.get("account"), dict) and bool(value["account"].get("role"))
        except (socket.timeout, TimeoutError) as exc:
            raise _UpstreamTimeout("Authentication service timed out") from exc
        finally:
            connection.close()

    def _proxy(self, target: str, body: bytes, cookies: dict[str, str]) -> None:
        path = target.split("?", 1)[0]
        upload = self.command == "POST" and (path in _UPLOAD_CHUNK_PATHS or path == _UPLOAD_RESUME_PATH)
        upstream_timeout = UPLOAD_UPSTREAM_TIMEOUT_SECONDS if upload else TIMEOUT_SECONDS
        connection = self._connection(timeout=upstream_timeout)
        started = False
        try:
            headers = self._upstream_headers(cookies)
            if self.command == "POST":
                headers["Content-Length"] = str(len(body))
            connection.request(self.command, target, body=body if self.command == "POST" else None, headers=headers)
            response = connection.getresponse()
            if self._expired():
                self._error(410, "invitation_expired", "邀请已到期")
                return
            if response.status >= 500:
                if response.status == 507 and self.command == "POST" and path in {
                    "/api/v1/demo2/upload/tasks", "/api/v1/demo2/upload/chunks", _UPLOAD_RESUME_PATH,
                }:
                    try:
                        raw = response.read(8193)
                        value = json.loads(raw) if len(raw) <= 8192 else None
                        error = value.get("error") if isinstance(value, dict) else None
                        if isinstance(error, dict) and error.get("code") == "insufficient_storage":
                            self._error(507, "insufficient_storage", "服务器存储空间不足，请联系管理员扩容后再重试上传。")
                            return
                    except (ValueError, UnicodeError):
                        pass
                # Known unavailable-provider failures are product states, not
                # decoder traces. Keep their stable code with OUR safe wording.
                if response.status == 503 and target.split("?", 1)[0] in {
                    "/api/v1/demo2/auth/sms-code", "/api/v1/demo2/auth/register",
                    "/api/v1/demo2/membership/config", "/api/v1/demo2/membership",
                    "/api/v1/demo2/membership/orders", "/api/v1/demo2/admin/memberships",
                }:
                    try:
                        raw = response.read(8193)
                        value = json.loads(raw) if len(raw) <= 8192 else None
                        error = value.get("error") if isinstance(value, dict) else None
                        code = error.get("code") if isinstance(error, dict) else None
                        if isinstance(code, str) and code in _MEMBERSHIP_PUBLIC_FAILURES:
                            self._error(503, code, _MEMBERSHIP_PUBLIC_FAILURES[code])
                            return
                    except (ValueError, UnicodeError):
                        pass
                self._error(response.status, "upstream_unavailable", "平台暂不可用，请稍后重试")
                return
            outgoing = []
            for key, value in response.getheaders():
                if "\r" in value or "\n" in value:
                    raise http.client.HTTPException("Invalid upstream header")
                if key.lower() in _RESPONSE_HEADERS:
                    outgoing.append((key, value))
                elif key.lower() == "set-cookie":
                    parsed = SimpleCookie()
                    parsed.load(value)
                    for name, morsel in parsed.items():
                        if name != SESSION_COOKIE_NAME:
                            continue
                        morsel["secure"] = True
                        morsel["httponly"] = True
                        morsel["samesite"] = "Lax"
                        morsel["path"] = "/"
                        morsel["domain"] = ""
                        outgoing.append(("Set-Cookie", morsel.OutputString()))
                elif key.lower() == "location":
                    path, _ = _safe_target(value)
                    if not _allowed("GET", path):
                        raise http.client.HTTPException("Upstream redirect outside allowed routes")
                    outgoing.append(("Location", value))
            self._headers(response.status, outgoing)
            started = True
            while not self._expired():
                if connection.sock is not None:
                    connection.sock.settimeout(min(upstream_timeout, max(.001, self.server.config.expires_at - time.time())))
                block = response.read1(65536)
                if not block or self._expired():
                    break
                self.wfile.write(block)
        except (socket.timeout, TimeoutError):
            if not started:
                self._error(410 if self._expired() else 504, "upstream_timeout", "平台响应超时，请核对分片状态后重试")
        except (OSError, http.client.HTTPException, ValueError, CookieError):
            if not started:
                self._error(502, "upstream_unavailable", "平台暂不可用，请稍后重试")
        finally:
            self.close_connection = True
            connection.close()

    def _dispatch(self) -> None:
        try:
            if self._expired():
                self._error(410, "invitation_expired", "邀请已到期")
                return
            # BaseHTTPRequestHandler collapses leading // in self.path. Validate
            # the original target so this normalization cannot bypass our gate.
            path, target = _safe_target(self.requestline.split()[1])
            length = self._body_length()
            if len(self.headers.get_all("Host", [])) != 1:
                raise ValueError("Exactly one Host required")
            if self.command == "POST" and not self._same_origin():
                self._error(403, "origin_forbidden", "只允许同源请求")
                return
            if path != "/invite" and any(value.lower() not in {"same-origin", "none"}
                                         for value in self.headers.get_all("Sec-Fetch-Site", [])):
                self._error(403, "origin_forbidden", "不允许跨站请求")
                return
            if self.command not in {"GET", "POST"}:
                self._error(405, "method_not_allowed", "Method not allowed")
                return
            if self.server.failures.blocked(self.client_address[0]):
                self._error(429, "rate_limited", "请求过于频繁，请稍后重试")
                return
            if path == "/invite" and self.command == "GET":
                if "?" in target:
                    raise ValueError("Secrets must not be placed in query strings")
                self._invite_page()
                return
            if path == "/__manager/authorize" and self.command == "POST":
                if "?" in target or length > 8192:
                    self._gate_failure()
                    return
                self._authorize(self._read_body(length))
                return
            try:
                cookies = self._cookies()
            except ValueError:
                self._gate_failure()
                return
            if not self._invited(cookies):
                self._gate_failure()
                return
            if path == "/favicon.ico" and self.command == "GET":
                self._respond(204)
                return
            legacy_return = self.command == "GET" and path == "/seewo_student_demo"
            if not _allowed(self.command, path) and not legacy_return:
                self._error(404, "route_not_allowed", "Not found")
                return
            if path == "/api/v1/demo2/auth/login" and self.server.login_attempts.blocked("global", failure=True):
                self._respond(429, json.dumps({"ok": False, "error": {
                    "code": "login_rate_limited", "message": "登录尝试过于频繁，请五分钟后重试",
                }}, ensure_ascii=False).encode(), headers=[("Retry-After", "300")])
                return
            if path not in _PUBLIC_UPSTREAM and not self._authenticated(cookies):
                if path in _PAGES or legacy_return:
                    self._respond(303, headers=[("Location", "/demo2/login")])
                else:
                    self._error(401, "authentication_required", "请先登录平台账号")
                return
            if path.startswith(DOSSIER_API_PREFIX + "/") and length > DOSSIER_MAX_BODY_BYTES:
                self._error(413, "body_too_large", "资料请求体不能超过 12 MiB")
                return
            if path == _UPLOAD_RESUME_PATH:
                if self.headers.get_content_type() != "application/json":
                    self._error(415, "unsupported_media_type", "续传验证仅支持 JSON 请求")
                    return
                if length > RESUME_MAX_BODY_BYTES:
                    self._error(413, "body_too_large", "续传验证请求体不能超过 128 KiB")
                    return
            if (path in _UPLOAD_CHUNK_PATHS or path == _UPLOAD_RESUME_PATH) and self.headers.get_all("Content-Encoding"):
                self._error(415, "unsupported_content_encoding", "上传分片不支持内容编码")
                return
            # Forward raw binary and legacy JSON unchanged, including the exact
            # query. The application retains task ownership and chunk validation.
            body = self._read_body(length, upload=path in _UPLOAD_CHUNK_PATHS,
                                   invite_expires_at=int(cookies[INVITE_COOKIE_NAME].split(".")[1])) if self.command == "POST" else b""
            if self._expired():
                self._error(410, "invitation_expired", "邀请已到期")
                return
            if not self._invited(cookies):
                self._gate_failure()
                return
            if legacy_return:
                self._respond(303, headers=[("Location", "/demo2/analysis")])
                return
            self._proxy(target, body, cookies)
        except OverflowError:
            self._error(413, "body_too_large", "请求体不能超过 15 MiB")
        except _UpstreamTimeout:
            self._error(410 if self._expired() else 504, "upstream_timeout", "平台验证超时，请稍后重试")
        except (socket.timeout, TimeoutError):
            self._error(410 if self._expired() else 408, "request_timeout", "请求已超时或邀请已到期")
        except _IncompleteBody:
            self._error(400, "incomplete_body", "请求体不完整，请重新上传该分片")
        except _InvalidFraming:
            self._error(400, "invalid_framing", "请求体长度或传输格式无效")
        except (ValueError, UnicodeError, CookieError):
            self._error(400, "invalid_request", "Request rejected")
        except (OSError, http.client.HTTPException):
            self._error(502, "upstream_unavailable", "平台暂不可用，请稍后重试")

    do_GET = _dispatch
    do_POST = _dispatch
    do_HEAD = _dispatch
    do_OPTIONS = _dispatch
    do_PUT = _dispatch
    do_PATCH = _dispatch
    do_DELETE = _dispatch
    do_TRACE = _dispatch
    do_CONNECT = _dispatch


def make_server(config: GatewayConfig | Mapping[str, Any], *, host: str = "127.0.0.1",
                port: int | None = None) -> ThreadingHTTPServer:
    """Build, but do not start, the loopback gateway. Use port=0 in tests."""
    if not isinstance(config, GatewayConfig):
        config = GatewayConfig(**dict(config))
    if host != "127.0.0.1" or not ipaddress.ip_address(host).is_loopback:
        raise ValueError("Gateway must bind to IPv4 loopback")
    listen_port = config.listen_port if port is None else port
    if isinstance(listen_port, bool) or not isinstance(listen_port, int) or not 0 <= listen_port <= 65535:
        raise ValueError("Invalid listen port")
    if listen_port and listen_port == config.upstream_port:
        raise ValueError("Gateway and upstream must use different ports")
    return _GatewayServer((host, listen_port), config)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local-only temporary Demo2 invitation gateway")
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if config.expires_at <= time.time():
            raise ValueError("Invitation configuration has expired")
        server = make_server(config)
    except (OSError, TypeError, ValueError):
        parser.exit(2, "Invalid or unreadable gateway configuration\n")
    try:
        # Local expiry-only renewal preserves invitation and cookie identities.
        def refresh_expiry():
            while not renewal_stop.wait(5):
                try:
                    updated = load_config(args.config)
                    current = server.config
                    if (updated.invite_secret == current.invite_secret
                            and updated.cookie_secret == current.cookie_secret
                            and updated.listen_port == current.listen_port
                            and updated.upstream_port == current.upstream_port):
                        server.config = updated
                except (OSError, TypeError, ValueError):
                    pass
        renewal_stop = threading.Event()
        threading.Thread(target=refresh_expiry, daemon=True).start()
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        renewal_stop.set()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
