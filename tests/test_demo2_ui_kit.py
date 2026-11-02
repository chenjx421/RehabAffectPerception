from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone

import pytest

from rehab_affect import demo2_ui_kit as kit
from rehab_affect.demo2_batch_page import render_batch_review
from rehab_affect.demo2_capture import render_capture
from rehab_affect.demo2_channel_admin import render_channel_admin
from rehab_affect.demo2_course_page import render_course_analysis
from rehab_affect.demo2_dossier import render_admin as render_dossier_admin
from rehab_affect.demo2_dossier import render_student as render_dossier_student
from rehab_affect.demo2_dossier import render_task as render_dossier_task
from rehab_affect.demo2_entry import render_membership, render_school
from rehab_affect.demo2_evaluation import render_evaluation
from rehab_affect.demo2_home import render_home
from rehab_affect.demo2_identity import render_identity, render_students
from rehab_affect.demo2_measurement import render_measurement
from rehab_affect.demo2_portal import render_demo2_admin_html, render_demo2_upload_html
from rehab_affect.demo2_safety_page import render_safety
from rehab_affect.demo2_simple_result import render_simple_result
from rehab_affect.demo2_student_summary_page import (
    render_admin_student_summaries_html,
    render_student_summary_html,
)
from rehab_affect.demo2_support_page import render_support
from rehab_affect.demo2_video_review import render_video_review
from rehab_affect.scenario_lab_server import _render_admin_analysis_guide
from rehab_affect.school_selection_page import render_school_selection_html

TEACHER = {"username": "school_uploader_01", "login_alias": "t1", "role": "school_uploader"}
ADMIN = {"username": "admin", "role": "company_admin"}

TEACHER_PAGES = {
    "home": (lambda: render_home(TEACHER), "home"),
    "upload": (lambda: render_demo2_upload_html(TEACHER), "upload"),
    "school": (lambda: render_school(TEACHER), "school"),
    "school_selection": (lambda: render_school_selection_html(TEACHER), "school"),
    "membership": (lambda: render_membership(TEACHER), "membership"),
    "students": (lambda: render_students(TEACHER), "students"),
    "identity": (lambda: render_identity(TEACHER), "upload"),
    "measurement": (lambda: render_measurement(TEACHER), "measurement"),
    "evaluation": (lambda: render_evaluation(TEACHER), "evaluation"),
    "capture": (lambda: render_capture(TEACHER), "capture"),
    "dossier": (lambda: render_dossier_student(TEACHER), "students"),
    "course_dossier": (lambda: render_dossier_task(TEACHER), "upload"),
    "student_summary": (lambda: render_student_summary_html(TEACHER), "students"),
    "video": (lambda: render_video_review(TEACHER), "upload"),
    "analysis": (lambda: render_course_analysis(TEACHER), "upload"),
    "course_batch": (lambda: render_batch_review(TEACHER), "upload"),
    "teaching_support": (lambda: render_support(TEACHER), "upload"),
    "safety": (lambda: render_safety(TEACHER), "evaluation"),
    "simple_result": (lambda: render_simple_result(TEACHER), "upload"),
}
ADMIN_PAGES = {
    "admin": (lambda: render_demo2_admin_html(ADMIN), "overview"),
    "channels": (lambda: render_channel_admin(ADMIN), "channels"),
    "dossiers": (lambda: render_dossier_admin(ADMIN), "dossiers"),
    "measurements": (lambda: render_measurement(ADMIN), "measurements"),
    "student_summaries": (lambda: render_admin_student_summaries_html(ADMIN), "overview"),
    "analysis_guide": (lambda: _render_admin_analysis_guide(ADMIN), "tasks"),
    "analysis_task": (lambda: render_course_analysis(ADMIN), "tasks"),
    "video": (lambda: render_video_review(ADMIN), "tasks"),
    "membership": (lambda: render_membership(ADMIN), "membership"),
}


def _nav_labels(html: str) -> list[str]:
    nav = re.search(r'<nav class="rx-nav".*?</nav>', html, re.S).group()
    return re.findall(r">([^<>]+)</a>", nav)


@pytest.mark.parametrize("name", sorted(TEACHER_PAGES))
def test_every_teacher_page_has_one_shared_navigation(name):
    render, active = TEACHER_PAGES[name]
    html = render()
    assert html.count('class="rx-header"') == 1
    assert html.count('<nav class="rx-nav"') == 1
    assert not re.search(r'class="(?:workspace-nav|site-header|topbar|entry-header)', html)
    assert _nav_labels(html) == ["首页", "上传任务", "学生名册", "学生测量", "课程评价", "课堂录制",
                                 "学校信息", "会员中心", "使用帮助"]
    assert re.findall(r'data-rx-nav-key="(\w+)" aria-current="page"', html) == [active]
    assert 'aria-controls="rxNavPanel"' in html and 'aria-label="打开导航菜单"' in html
    assert 'aria-label="退出登录"' in html and ">t1<" in html
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids)), "duplicate element ids"
    assert "<script data-rx-kit>" in html and "<style data-rx-kit>" in html


@pytest.mark.parametrize("name", sorted(ADMIN_PAGES))
def test_every_admin_page_has_one_shared_navigation(name):
    render, active = ADMIN_PAGES[name]
    html = render()
    assert html.count('<nav class="rx-nav"') == 1
    assert _nav_labels(html) == ["总览", "任务查询", "上传通道", "学生资料运行状态", "测量记录汇总", "会员与订单"]
    assert re.findall(r'data-rx-nav-key="(\w+)" aria-current="page"', html) == [active]
    hrefs = re.findall(r'class="rx-nav-link" href="([^"]+)"', html)
    assert hrefs == ["/demo2/admin", "/demo2/admin#taskQueryTitle", "/demo2/admin/channels",
                     "/demo2/admin/dossiers", "/demo2/admin/measurements", "/demo2/admin#membershipSummaryTitle"]


def test_admin_nav_anchors_exist_on_the_overview_page():
    html = render_demo2_admin_html(ADMIN)
    assert 'id="taskQueryTitle"' in html and 'id="membershipSummaryTitle"' in html


def test_registered_member_only_sees_member_navigation():
    html = render_membership({"role": "registered_member", "username": "13800000000"})
    assert _nav_labels(html) == ["会员中心", "使用帮助"]


def test_preserved_page_ids_and_logout_binding():
    upload = render_demo2_upload_html(TEACHER)
    for element_id in ("accountName", "channelName", "logoutButton", "studentRosterLink", "membershipLink",
                       "analysisLink"):
        assert f'id="{element_id}"' in upload
    measurement = render_measurement(TEACHER)
    assert 'id="logoutBtn"' in measurement and "/auth/logout" in measurement
    assert 'id="refreshBtn"' in render_measurement(ADMIN)
    identity = render_students(TEACHER)
    for element_id in ("brandLink", "accountLabel", "backLink", "secondaryLink", "logoutButton"):
        assert f'id="{element_id}"' in identity
    # Pages without their own logout handler delegate to the kit.
    assert re.search(r"<button[^>]*rx-logout[^>]*data-rx-logout", render_capture(TEACHER))
    assert not re.search(r"<button[^>]*rx-logout[^>]*data-rx-logout", upload)


def test_status_badges_use_one_chinese_vocabulary():
    expected = {
        "uploading": "上传中", "queued": "排队中", "processing": "分析中", "evidence_ready": "证据已就绪",
        "needs_review": "待复核", "reviewed": "已复核", "failed": "失败", "stale": "已过期",
    }
    for code, label in expected.items():
        assert kit.status_label(code)[0] == label
    assert set(expected.values()) == set(kit.CANONICAL_STATUS_NAMES)
    assert ">证据已就绪<" in kit.status_badge("evidence_ready")


def test_unknown_status_logs_warning_without_value(caplog):
    with caplog.at_level(logging.WARNING, logger="rehab_affect.ui_kit"):
        badge = kit.status_badge("张三的私密状态", page="unit")
    assert "未知状态" in badge
    record = json.loads(caplog.records[-1].getMessage())
    assert record["page"] == "unit" and record["component"] == "status_badge"
    assert record["input_type"] == "str" and record["fallback"] == "未知状态" and record["ts"]
    assert "张三" not in caplog.text


def test_formatters_and_degraded_values(caplog, tmp_path, monkeypatch):
    assert kit.format_bytes(0) == "0 B"
    assert kit.format_bytes(1536) == "1.5 KB"
    assert kit.format_bytes(6_600_000) == "6.3 MB"
    assert kit.format_bytes(3 * 1024 ** 3) == "3.00 GB"
    local = datetime(2026, 10, 29, 14, 30, tzinfo=timezone.utc).astimezone()
    assert kit.format_time(local.isoformat()) == local.strftime("%Y-%m-%d %H:%M")
    now = datetime(2026, 10, 29, 14, 30, tzinfo=timezone.utc)
    assert kit.relative_time((now - timedelta(minutes=3)).isoformat(), now=now) == "3 分钟前"
    assert kit.relative_time((now - timedelta(seconds=5)).isoformat(), now=now) == "刚刚"
    assert kit.relative_time((now - timedelta(days=2)).isoformat(), now=now) == "2 天前"
    full = "9f3c2b7a5d1e4f60a1b2c3d4e5f60718"
    snippet = kit.short_id_html(full)
    assert ">9f3c2b7a<" in snippet and f'data-rx-copy="{full}"' in snippet and f'title="{full}"' in snippet
    assert "复制完整编号" in snippet and 'aria-label="复制完整编号"' in snippet
    assert kit.short_id("task_0123456789abcdef") == "01234567"
    monkeypatch.setenv(kit.UI_DEBUG_LOG_DIR_ENV, str(tmp_path))
    with caplog.at_level(logging.WARNING, logger="rehab_affect.ui_kit"):
        assert kit.format_bytes("not-a-number", page="unit") == "—"
        assert kit.format_time("昨天下午", page="unit") == "时间未返回"
    entries = [json.loads(line) for path in tmp_path.glob("ui_debug_*.jsonl")
               for line in path.read_text(encoding="utf-8").splitlines()]
    assert [entry["component"] for entry in entries] == ["format_bytes", "format_time"]
    assert all(entry["level"] == "WARNING" and entry["page"] == "unit" for entry in entries)
    assert "昨天下午" not in json.dumps(entries, ensure_ascii=False)


def test_components_render_accessible_markup():
    assert 'disabled' in kit.button("保存", disabled=True)
    assert 'aria-busy="true"' in kit.button("保存", loading=True)
    field = kit.form_field("course_name", "课程名称", '<input id="course_name" name="course_name">',
                           required=True, help_text="不超过 200 字")
    assert 'for="course_name"' in field and "rx-required" in field and 'id="course_nameError"' in field
    block = kit.disclosure("使用边界与说明", ["不是诊断", "不是正式评分"])
    assert block.startswith('<details class="rx-disclosure"') and " open" not in block.split(">", 1)[0]
    assert "使用边界与说明" in block
    empty = kit.empty_state("还没有上传任务", action_label="上传第一节课", action_href="/demo2/upload")
    assert "还没有上传任务" in empty and 'href="/demo2/upload"' in empty
    assert 'aria-current="step"' in kit.steps(["选择视频", "上传", "查看结果"], 1)
    assert "rx-kpi-value" in kit.kpi("任务总数", 3, hint="含已完成")
    assert 'aria-live="polite"' in kit.toast_region()


def _luminance(hex_color: str) -> float:
    channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(foreground: str, background: str) -> float:
    lighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def test_token_text_colors_meet_wcag_aa():
    tokens = dict(re.findall(r"--rx-([a-z-]+):(#[0-9a-f]{6})", kit.TOKENS_CSS))
    pairs = [
        ("ink", "surface"), ("text", "surface"), ("muted", "surface"), ("muted", "canvas"),
        ("muted", "primary-pale"), ("primary", "surface"), ("primary-hover", "primary-soft"),
        ("success", "success-soft"), ("warning", "warning-soft"), ("danger", "danger-soft"),
        ("neutral", "neutral-soft"),
    ]
    for foreground, background in pairs:
        assert _contrast(tokens[foreground], tokens[background]) >= 4.5, (foreground, background)
    assert _contrast("#ffffff", tokens["primary"]) >= 4.5
    assert "focus-visible" in kit.UI_KIT_CSS and "outline:3px solid var(--rx-focus)" in kit.UI_KIT_CSS


def test_kit_css_keeps_shared_visual_limits():
    radii = [int(value) for value in re.findall(r"border-radius:(\d+)px", kit.UI_KIT_CSS)]
    assert not radii or max(radii) <= 8
    assert "https://" not in kit.UI_KIT_CSS + kit.UI_KIT_JS
    assert "@media (max-width:480px)" in kit.NAV_CSS


def test_kit_script_formatters_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js required")
    source = """
const warnings=[];console.warn=(...args)=>warnings.push(args.join(' '));
const stub={addEventListener(){},querySelector(){return null},querySelectorAll(){return []},readyState:'complete',
  body:{appendChild(){}},createElement(){return {setAttribute(){},style:{}}},getElementById(){return null}};
global.window=globalThis;global.document=stub;global.location={pathname:'/demo2/test',href:'http://x/demo2/test'};
""" + kit.UI_KIT_JS + """
const ui=window.RxUI;const assert=require('assert');
assert.equal(ui.formatBytes(6600000),'6.3 MB');assert.equal(ui.formatBytes(512),'512 B');
assert.equal(ui.formatBytes(3*1024**3),'3.00 GB');
const d=new Date(2026,9,29,14,30);assert.equal(ui.formatTime(d.toISOString()),'2026-10-29 14:30');
assert.equal(ui.relativeTime(new Date(Date.now()-180000).toISOString()),'3 分钟前');
assert.equal(ui.shortId('9f3c2b7a5d1e4f60a1b2c3d4e5f60718'),'9f3c2b7a');
assert.ok(ui.shortIdHtml('9f3c2b7a5d1e4f60').includes('data-rx-copy="9f3c2b7a5d1e4f60"'));
assert.ok(ui.statusBadge('evidence_ready').includes('证据已就绪'));
assert.equal(ui.statusLabel('mystery')[0],'未知状态');
assert.equal(ui.formatBytes('abc'),'—');
const logged=warnings.map(w=>JSON.parse(w.replace('[rx-ui] ','')));
assert.deepEqual(logged.map(e=>e.component),['status_badge','format_bytes']);
assert.ok(logged.every(e=>e.level==='WARNING'&&e.ts&&e.page==='/demo2/test'&&e.input_type));
assert.ok(!JSON.stringify(logged).includes('mystery'));
"""
    completed = subprocess.run([node, "-"], input=source, text=True, encoding="utf-8",
                               capture_output=True, timeout=20)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_inject_kit_swaps_first_header_and_is_idempotent():
    page = "<html><head></head><body><header>old</header><main><header>inner</header></main></body></html>"
    once = kit.inject_kit(page, header="<header class='rx-header'>new</header>", page="unit")
    assert "old" not in once and "inner" in once and once.count("data-rx-kit>") == 2
    assert kit.inject_kit(once, page="unit").count("<script data-rx-kit>") == 1
