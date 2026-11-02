"""Header back/forward navigation (修改意见 2)."""
from __future__ import annotations

import json
import re

import pytest

from rehab_affect import demo2_manager_gateway as gateway
from rehab_affect import demo2_ui_kit as kit
from rehab_affect.demo2_course_page import render_course_analysis
from rehab_affect.demo2_dossier import render_student as render_dossier_student
from rehab_affect.demo2_help_page import render_help
from rehab_affect.demo2_measurement import render_measurement

TEACHER = {"role": "school_uploader", "username": "school_uploader_01", "login_alias": "t1"}
ADMIN = {"role": "company_admin", "username": "admin", "login_alias": "admin"}
MEMBER = {"role": "registered_member", "username": "13800000000"}

VALID = {"client_ts": "2026-10-31T10:00:00.000Z", "page": "/demo2/measurement", "event": "nav_back",
         "result": "ok", "trigger": "button", "direction": "back", "index": 2, "depth": 4}


@pytest.mark.parametrize("header,home", [
    (kit.teacher_header("measurement", TEACHER), "/demo2/home"),
    (kit.admin_header("overview", ADMIN), "/demo2/admin"),
    (kit.member_header("membership", MEMBER), "/demo2/membership"),
])
def test_every_role_header_has_back_forward_next_to_brand(header, home):
    brand_end = header.index("</a>", header.index('class="rx-brand"'))
    history = header.index('data-rx-history')
    assert brand_end < history < header.index('class="rx-nav-toggle"')
    assert f'data-rx-home="{home}"' in header
    for element_id, label, shortcut in (("rxNavBack", "后退", "Alt+ArrowLeft"), ("rxNavForward", "前进", "Alt+ArrowRight")):
        button = re.search(rf'<button[^>]*id="{element_id}"[^>]*>', header).group(0)
        assert 'aria-label="' in button and 'title="' in button and f'aria-keyshortcuts="{shortcut}"' in button
        assert f"<span>{label}</span>" in header


def test_public_help_header_and_pages_carry_the_buttons():
    assert 'data-rx-home="/demo2/login"' in render_help(None)
    for html in (render_measurement(TEACHER), render_dossier_student(TEACHER), render_course_analysis(TEACHER)):
        assert html.count('id="rxNavBack"') == 1 and html.count('id="rxNavForward"') == 1


def test_kit_script_keeps_contracts():
    js = kit.UI_NAV_JS
    assert "KEY='rx_nav_stack'" in js and "history" in kit.UI_KIT_JS
    assert "setTimeout" not in js and "setInterval" not in js  # admin_refresh counts timers
    assert "classList.toggle" not in js and "classList.contains" not in js
    assert "old" not in kit.UI_KIT_JS and "old" not in kit.UI_KIT_CSS
    assert all(int(v) <= 8 for v in re.findall(r"border-radius:(\d+)px", kit.UI_KIT_CSS))
    assert kit.NAV_EVENT_PATH in js and "__NAV_PATH__" not in js and "__BUTTONS__" not in js
    # Dirty forms prompt before leaving; Alt+arrows skip editable fields.
    assert "有未保存内容，确定离开？" in js and "input,textarea,select,[contenteditable]" in js
    assert "R.toast('已是第一页')" in js and "没有可前进的页面" in js


def test_tabs_write_url_hash():
    assert "tabHash({names:['overview','form','trends','report','standard']" in render_measurement(TEACHER)
    assert "tabHash({names:['overview','group','person','review','report']" in render_course_analysis(TEACHER)
    dossier = render_dossier_student(TEACHER)
    assert "tabNav.set(TAB_HASH[id]" in dossier and "switchTab(button.id,true)" in dossier


def test_nav_event_logs_only_whitelisted_shape(tmp_path, monkeypatch):
    monkeypatch.setenv(kit.UI_DEBUG_LOG_DIR_ENV, str(tmp_path))
    monkeypatch.setitem(kit._NAV_BUDGET, "window_start", 0.0)
    monkeypatch.setitem(kit._NAV_BUDGET, "count", 0)
    for event, result in (("nav_back", "ok"), ("nav_forward", "disabled"), ("nav_blocked", "cancelled"),
                          ("nav_home_fallback", "redirected")):
        entry = kit.ui_nav_event({**VALID, "event": event, "result": result}, now=1000.0)
        assert entry["operation"] == event and entry["result"] == result and entry["page"] == "/demo2/measurement"
    lines = [json.loads(line) for line in next(tmp_path.glob("ui_debug_*.jsonl")).read_text().splitlines()]
    assert [line["operation"] for line in lines] == ["nav_back", "nav_forward", "nav_blocked", "nav_home_fallback"]
    assert all(line["ts"] and line["component"] == "page_nav" for line in lines)


@pytest.mark.parametrize("change", [
    {"page": "/demo2/measurement?student_id=x"}, {"page": "/demo2/x#tab-form"}, {"page": "demo2"},
    {"event": "nav_jump"}, {"result": "maybe"}, {"trigger": "mouse"}, {"index": -1}, {"depth": True},
    {"client_ts": "yesterday"}, {"note": "表单内容"},
])
def test_nav_event_rejects_anything_else(change):
    with pytest.raises(kit.ClientErrorRejected):
        kit.ui_nav_event({**VALID, **change}, now=1000.0)


def test_nav_event_budget_and_gateway_whitelist(monkeypatch):
    monkeypatch.setitem(kit._NAV_BUDGET, "window_start", 50.0)
    monkeypatch.setitem(kit._NAV_BUDGET, "count", kit.NAV_EVENT_BUDGET_PER_MINUTE)
    assert kit.ui_nav_event(dict(VALID), now=55.0) is None
    assert kit.ui_nav_event(dict(VALID), now=111.0) is not None
    assert kit.NAV_EVENT_PATH in gateway._POST_API and kit.NAV_EVENT_PATH in gateway._PUBLIC_UPSTREAM
    assert kit.NAV_EVENT_PATH not in gateway._GET_API
