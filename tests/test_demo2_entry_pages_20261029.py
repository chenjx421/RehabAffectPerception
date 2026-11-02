"""Login / register / privacy / membership redesign and auth debug log (2026-10-29)."""

from __future__ import annotations

import http.client
import json
import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest

from src.rehab_affect import scenario_lab_server as server_module
from src.rehab_affect.demo2_auth_debug import account_hint, source_digest
from src.rehab_affect.demo2_entry import (
    POLICY_SECTIONS,
    render_login,
    render_membership,
    render_privacy,
    render_register,
)
from src.rehab_affect.student_record_store import AccountInactiveError, Demo2StudentRecordStore

PREFIX = "entry-test-"


@pytest.fixture()
def auth_server(monkeypatch, tmp_path):
    monkeypatch.setenv("REHAB_DEMO2_ACCOUNT_PASSWORD_PREFIX", PREFIX)
    log_dir = tmp_path / "auth-logs"
    monkeypatch.setenv("REHAB_DEMO2_AUTH_DEBUG_LOG_DIR", str(log_dir))
    store = Demo2StudentRecordStore(tmp_path / "entry.sqlite3", tmp_path / "documents")
    monkeypatch.setattr(server_module, "get_demo2_student_store", lambda: store)
    monkeypatch.setattr(server_module, "load_seewo_demo2", lambda force=False: {"students": []})
    handler = server_module.create_handler(scenario_dir=tmp_path, model_path=tmp_path / "unused.json", policy_name="rule")
    httpd = server_module.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_port, store, log_dir
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=3)


def _post(port: int, path: str, payload: Any) -> tuple[int, Any]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("POST", path, body=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        return response.status, json.loads(response.read().decode())
    finally:
        connection.close()


def _get(port: int, path: str) -> tuple[int, Any]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        raw = response.read().decode()
        return response.status, json.loads(raw) if raw.startswith("{") else raw
    finally:
        connection.close()


def _log_lines(log_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for path in sorted(log_dir.glob("auth_debug_*.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines()]


def test_login_success_and_failures_are_logged_without_secrets(auth_server) -> None:
    port, store, log_dir = auth_server
    status, body = _post(port, "/api/v1/demo2/auth/login",
                         {"username": "t1", "password": "wrong-secret-pass", "role": "school_uploader"})
    assert status == 401 and body["error"]["code"] == "invalid_credentials"
    status, body = _post(port, "/api/v1/demo2/auth/login",
                         {"username": "t1", "password": f"{PREFIX}school_uploader_01", "role": "company_admin"})
    assert status == 403 and body["error"]["code"] == "role_mismatch"
    status, body = _post(port, "/api/v1/demo2/auth/login",
                         {"username": "13812345678", "password": "phone-secret-1", "role": "school_uploader"})
    assert status == 401
    status, body = _post(port, "/api/v1/demo2/auth/login",
                         {"username": "t1", "password": f"{PREFIX}school_uploader_01", "role": "school_uploader"})
    assert status == 200 and body["next_url"] == "/demo2/school"

    lines = _log_lines(log_dir)
    assert [line["operation"] for line in lines] == ["login_failure", "login_failure", "login_failure", "login_success"]
    assert [line.get("code") for line in lines[:3]] == ["invalid_credentials", "role_mismatch", "invalid_credentials"]
    assert lines[0]["login_role"] == "school_uploader" and lines[1]["login_role"] == "company_admin"
    assert lines[0]["http_status"] == 401 and lines[1]["http_status"] == 403
    assert lines[2]["account_hint"] == "138****5678"
    assert lines[3]["account_role"] == "school_uploader" and lines[3]["account_id"]
    for line in lines:
        assert re.fullmatch(r"loopback:[0-9a-f]{12}", line["source"])
        assert line["ts"] and isinstance(line["duration_ms"], int)
    raw = "".join(path.read_text(encoding="utf-8") for path in log_dir.glob("auth_debug_*.jsonl"))
    for secret in ("wrong-secret-pass", PREFIX, "phone-secret-1", "13812345678", "127.0.0.1"):
        assert secret not in raw


def test_disabled_account_is_reported_only_with_correct_password(auth_server) -> None:
    port, store, log_dir = auth_server
    with sqlite3.connect(store.db_path) as connection:
        connection.execute("UPDATE platform_accounts SET status='inactive' WHERE username='school_uploader_02'")
    status, body = _post(port, "/api/v1/demo2/auth/login",
                         {"username": "t2", "password": "not-the-password", "role": "school_uploader"})
    assert status == 401 and body["error"]["code"] == "invalid_credentials"
    status, body = _post(port, "/api/v1/demo2/auth/login",
                         {"username": "t2", "password": f"{PREFIX}school_uploader_02", "role": "school_uploader"})
    assert status == 403 and body["error"]["code"] == "account_disabled"
    assert "停用" in body["error"]["message"]
    with pytest.raises(AccountInactiveError):
        store.authenticate_account("t2", f"{PREFIX}school_uploader_02")
    assert _log_lines(log_dir)[-1]["code"] == "account_disabled"


def test_register_config_check_is_logged(auth_server) -> None:
    port, _, log_dir = auth_server
    status, body = _get(port, "/api/v1/demo2/membership/config")
    assert status == 200 and body["config"]["sms_available"] is False
    line = _log_lines(log_dir)[-1]
    assert line["operation"] == "register_config_check" and line["result"] == "sms_unavailable"
    assert line["sms_available"] is False and line["payment_available"] is False
    assert line["agreement_version"] == "2026-09-09"


def test_log_helpers_mask_inputs() -> None:
    assert account_hint("t1") == "t1"
    assert account_hint("admin") == "ad***(len=5)"
    assert account_hint("13812345678") == "138****5678"
    assert account_hint("密码写错地方了") == "*****(len=7)"
    assert source_digest("not-an-ip") == "unknown"
    assert source_digest("10.1.2.3").startswith("private:")
    assert source_digest("8.8.8.8") != source_digest("8.8.4.4")


def test_login_page_split_layout_and_role_specific_hints() -> None:
    html = render_login()
    assert 'class="login-layout"' in html and 'class="login-intro"' in html and 'class="login-card"' in html
    # The left panel is purely visual: only the WeGlow wordmark is text.
    intro = re.search(r'<aside class="login-intro".*?</aside>', html, re.S).group(0)
    intro_text = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", intro))
    assert intro_text == "WeGlow"
    for removed in ("课堂视频", "学生状态", "双轨评价", "课堂报告", "把一节课", "intro-foot", "intro-flow", "不替代教师"):
        assert removed not in html
    assert '<svg class="login-art"' in html and "xmlns" not in html
    assert "RehabAffect" not in html and "云图智航" not in html
    assert "<title>WeGlow微光系统 · 登录</title>" in html and "欢迎使用 WeGlow微光系统" in html
    assert 'id="usernameError"' in html and 'id="passwordError"' in html
    assert 'id="userRole"' in html and 'id="adminRole"' in html and 'href="/demo2/register">手机号注册' in html
    assert 'href="/demo2/privacy"' in html and "'X-WeGlow-Brand':BRAND_VERSION" in html
    assert "@media (max-width:1023px)" in html and ".login-intro { display:none; }" in html
    # The register-phone hint lives only in the user-tab copy, never in the admin text.
    admin_text = re.search(r"company_admin:\{(.*?)\}", html).group(1)
    assert "注册手机号" not in admin_text and "手机号" not in admin_text
    assert "新用户使用注册手机号" not in html
    assert 'id="usernameHelp"' in html and 'id="loginForm" class="entry-form" novalidate' in html
    # The error banner precedes the fields so it shows above the form.
    assert html.index('id="formError"') < html.index('id="username"')
    for message in ("账号或密码不正确", "账号已停用", "网络异常"):
        assert message in html
    assert "aria-busy" in html and "btn-spinner" in html and "field.focus()" in html


def test_register_page_shows_friendly_state_card() -> None:
    html = render_register()
    assert 'id="registerState"' in html and 'id="backToLoginButton" href="/demo2/login"' in html
    assert "手机号注册即将开放" in html and "学校老师请使用学校分配的内测账号登录" in html
    assert 'id="registerFormArea" hidden' in html
    assert '<h1 id="registerTitle">注册 WeGlow微光系统 账号</h1>' in html
    assert "<title>WeGlow微光系统 · 会员注册</title>" in html
    assert "renderRegisterState('unavailable')" in html


def test_privacy_page_has_toc_cards_and_keeps_every_clause() -> None:
    html = render_privacy()
    for key, title, _ in POLICY_SECTIONS:
        assert f'href="#{key}"' in html and f'id="{key}"' in html and f'<option value="{key}">' in html
        assert title in html
    assert 'id="registration"' in html and 'id="membership"' in html
    assert '<strong id="platformRegisteredName">WeGlow微光系统</strong>' in html
    assert "RehabAffect" not in html and "云图智航" not in html
    assert "scrollIntoView" in html and "smooth" in html
    plain = re.sub(r"<[^>]+>", "", html)
    for clause in (
        "新上传原始视频默认保存60天，到期前15天在平台提醒",
        "不会因填写学校或创建账号自动上传云端",
        "登录本身不代表同意上传学生资料",
        "默认不允许，不包含原视频和姓名",
        "注册账号不会扣费，也不等于开通付费会员",
        "本版本的登录或注册操作不包含学生视频向外部模型传输的授权",
        "会员资格不替代学校授权",
    ):
        assert clause in plain
    assert "730" in html and "max-width:40em" in html and "font-size:16px" in html


def test_membership_humane_copy_and_single_logout() -> None:
    html = render_membership({"role": "school_uploader", "username": "t1"})
    assert html.count('aria-label="退出登录"') == 1
    assert "返回登录" not in re.search(r"<header.*?</header>", html, re.S).group(0)
    assert "价格即将公布" in html and "支付暂未开通" in html
    assert "'待公布'" not in html
    assert "rx-empty" in html and "暂无订单" in html


def _post_with_headers(port: int, path: str, payload: Any, headers: dict[str, str]) -> tuple[int, Any]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        connection.request("POST", path, body=json.dumps(payload).encode(),
                           headers={"Content-Type": "application/json", **headers})
        response = connection.getresponse()
        return response.status, json.loads(response.read().decode())
    finally:
        connection.close()


def test_auth_log_carries_brand_versions_for_cache_diagnosis(auth_server) -> None:
    from src.rehab_affect.demo2_ui_kit import BRAND_VERSION

    port, _store, log_dir = auth_server
    status, _ = _post(port, "/api/v1/demo2/auth/login", {"username": "t1", "password": "wrong-pass", "role": "school_uploader"})
    assert status == 401
    status, _ = _post_with_headers(port, "/api/v1/demo2/auth/login",
                                   {"username": "t1", "password": f"{PREFIX}school_uploader_01", "role": "school_uploader"},
                                   {"X-WeGlow-Brand": BRAND_VERSION})
    assert status == 200
    lines = _log_lines(log_dir)
    assert [line["operation"] for line in lines] == ["login_failure", "login_success"]
    assert all(line["brand_version"] == BRAND_VERSION for line in lines)
    # No header = page built before the WeGlow brand (stale cache).
    assert lines[0]["page_brand_version"] == "missing"
    assert lines[1]["page_brand_version"] == BRAND_VERSION
    raw = "".join(path.read_text(encoding="utf-8") for path in log_dir.glob("auth_debug_*.jsonl"))
    assert "wrong-pass" not in raw and f"{PREFIX}school_uploader_01" not in raw


def test_login_page_render_failure_serves_fallback_and_is_logged(auth_server, monkeypatch) -> None:
    port, _store, log_dir = auth_server
    status, html = _get(port, "/demo2/login")
    assert status == 200 and "<title>WeGlow微光系统 · 登录</title>" in html and 'class="login-intro"' in html
    assert _log_lines(log_dir) == []

    def broken(page: str, account: Any = None) -> str:
        raise RuntimeError("render boom")

    monkeypatch.setattr(server_module, "_render_demo2_portal_page", broken)
    status, html = _get(port, "/demo2/login")
    assert status == 200 and "WeGlow微光系统" in html and 'id="loginForm" novalidate' in html
    assert 'id="usernameError"' in html and 'id="passwordError"' in html and "xmlns" not in html
    line = _log_lines(log_dir)[-1]
    assert line["operation"] == "login_page_render" and line["result"] == "degraded"
    assert line["code"] == "RuntimeError" and "boom" not in json.dumps(line)


def test_brand_title_normalizes_legacy_titles() -> None:
    from src.rehab_affect.demo2_ui_kit import brand_document_title, brand_title

    assert brand_title("登录") == "WeGlow微光系统 · 登录"
    assert brand_title("视频上传 · RehabAffect 学校内测平台") == "WeGlow微光系统 · 视频上传"
    assert brand_title("测量记录 — RehabAffect") == "WeGlow微光系统 · 测量记录"
    assert brand_title("WeGlow微光系统 · 帮助") == "WeGlow微光系统 · 帮助"
    assert brand_title("") == "WeGlow微光系统"
    page = "<html><head><title>课堂复核与分析</title></head><body><svg><title>趋势</title></svg></body></html>"
    branded = brand_document_title(page)
    assert "<title>WeGlow微光系统 · 课堂复核与分析</title>" in branded and "<title>趋势</title>" in branded


def test_privacy_page_covers_documents_and_person_screening() -> None:
    from src.rehab_affect.demo2_entry import PRIVACY_VERSION
    html = render_privacy()
    plain = re.sub(r"<[^>]+>", "", html)
    assert PRIVACY_VERSION == "2026-11-01" and f'<span id="policyVersion">{PRIVACY_VERSION}</span>' in html
    assert 'id="documents"' in html and 'href="#documents"' in html
    assert 'id="person-screening"' in html and 'href="#person-screening"' in html
    for clause in ("课程任务（教案）Word/PDF 仅用于识别本课课程任务目标", "加密保存", "24小时后自动清除",
                   "必须由教师逐条核对并确认后才保存", "不做身份识别结论", "不判断画面中任何人是谁",
                   "注册与会员服务条款仍为 2026-09-09 版本"):
        assert clause in plain, clause
    assert 'href="/demo2/privacy"' in render_login()
