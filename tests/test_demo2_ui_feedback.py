from __future__ import annotations

import json
import logging
import shutil
import subprocess

import pytest

from rehab_affect import demo2_manager_gateway as gateway
from rehab_affect import demo2_ui_kit as kit
from rehab_affect.demo2_dossier import render_student as render_dossier_student
from rehab_affect.demo2_dossier import render_task as render_dossier_task
from rehab_affect.demo2_evaluation import render_evaluation
from rehab_affect.demo2_measurement import render_measurement

TEACHER = {"username": "school_uploader_01", "login_alias": "t1", "role": "school_uploader"}

VALID = {
    "client_ts": "2026-10-29T08:00:00.123Z",
    "page": "analysis",
    "api_path": "/api/v1/demo2/reports/download",
    "method": "GET",
    "status": 409,
    "error_code": "report_stale",
    "kind": "http_error",
}


@pytest.fixture(autouse=True)
def _fresh_budget(monkeypatch):
    monkeypatch.setitem(kit._CLIENT_BUDGET, "window_start", 0.0)
    monkeypatch.setitem(kit._CLIENT_BUDGET, "count", 0)


def test_client_error_is_logged_with_metadata_only(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv(kit.UI_DEBUG_LOG_DIR_ENV, str(tmp_path))
    with caplog.at_level(logging.WARNING, logger="rehab_affect.ui_kit"):
        entry = kit.ui_client_error(dict(VALID), now=1000.0)
    assert entry["component"] == "api_error" and entry["status"] == 409 and entry["error_code"] == "report_stale"
    assert entry["api_path"] == "/api/v1/demo2/reports/download" and entry["method"] == "GET"
    assert entry["ts"] and entry["client_ts"] == VALID["client_ts"] and entry["page"] == "analysis"
    lines = [json.loads(line) for path in tmp_path.glob("ui_debug_*.jsonl") for line in path.read_text("utf-8").splitlines()]
    assert lines == [entry]
    assert any("report_stale" in record.getMessage() for record in caplog.records)


@pytest.mark.parametrize("change", [
    {"api_path": "/api/v1/demo2/dossier/student?student_id=abc"},
    {"api_path": "/demo2/analysis"},
    {"api_path": "/api/../etc/passwd"},
    {"error_code": "学生张三"},
    {"status": 700},
    {"status": "401"},
    {"method": "TRACE"},
    {"kind": "free_text"},
    {"page": "<script>"},
    {"client_ts": "yesterday"},
    {"body": "{\"name\":\"张三\"}"},
    {"message": "服务器原文"},
])
def test_client_error_rejects_anything_outside_the_shape(change):
    with pytest.raises(kit.ClientErrorRejected):
        kit.ui_client_error({**VALID, **change}, now=1000.0)


def test_client_error_budget_limits_log_volume():
    for _ in range(kit.CLIENT_ERROR_BUDGET_PER_MINUTE):
        assert kit.ui_client_error(dict(VALID), now=50.0) is not None
    assert kit.ui_client_error(dict(VALID), now=55.0) is None
    assert kit.ui_client_error(dict(VALID), now=111.0) is not None


def test_gateway_forwards_client_error_without_session():
    assert kit.CLIENT_ERROR_PATH in gateway._POST_API
    assert kit.CLIENT_ERROR_PATH in gateway._PUBLIC_UPSTREAM
    assert kit.CLIENT_ERROR_PATH not in gateway._GET_API


def test_error_vocabulary_in_node():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js required")
    source = """
const stub={addEventListener(){},querySelector(){return null},querySelectorAll(){return []},readyState:'complete',
  body:{appendChild(){}},createElement(){return {setAttribute(){},style:{}}},getElementById(){return null}};
global.window=globalThis;global.document=stub;global.location={pathname:'/demo2/test',href:'http://x/demo2/test'};
console.warn=()=>{};
""" + kit.UI_KIT_JS + """
const ui=window.RxUI,assert=require('assert');
const cases=[[401,'authentication_required','x','登录已过期，请重新登录','401 · authentication_required'],
  [403,'report_forbidden','Forbidden','你没有查看此内容的权限','403 · report_forbidden'],
  [404,'','Not found','内容不存在或已被删除','HTTP 404'],
  [409,'report_stale','Report stale','报告已过期，请刷新后再下载','409 · report_stale'],
  [409,'applicability_required','需要确认','请先在分析页确认视频适用性','409 · applicability_required'],
  [0,'network_error','','网络连接不稳定，请稍后重试','network_error'],
  [400,'invalid_field','课节编号不能为空。','课节编号不能为空','400 · invalid_field'],
  [500,'','Traceback','服务器暂时出错，请稍后重试','HTTP 500']];
for(const [status,code,msg,text,label] of cases){const d=ui.describeError(status,code,msg);assert.equal(d.text,text);assert.equal(d.label,label);assert.equal(d.full,text+'（错误码：'+label+'）');}
assert.equal(ui.fromError(new TypeError('Failed to fetch')).text,'网络连接不稳定，请稍后重试');
const t=new Error('x');t.name='TimeoutError';assert.equal(ui.fromError(t).code,'timeout');
const e=new Error('Report stale');e.status=409;e.code='report_stale';assert.ok(ui.errorHtml(ui.fromError(e)).includes('<small class="rx-error-code">错误码：409 · report_stale</small>'));
assert.ok(ui.errorHtml(ui.describeError(400,'','<b>x</b>中文')).includes('&lt;b&gt;'));
assert.equal(typeof ui.confirmDialog,'function');assert.equal(typeof ui.trackForm,'function');assert.equal(typeof ui.notice,'function');
"""
    completed = subprocess.run([node, "-e", source], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_pages_use_shared_dialog_guard_and_toast():
    measurement = render_measurement(TEACHER)
    assert "RxUI.trackForm('#measForm')" in measurement and "formGuard.clean()" in measurement
    assert "title:'撤销这条测量记录？'" in measurement and "input:{label:'撤销原因',required:true" in measurement
    assert "okToast('测量记录已撤销')" in measurement and "e.code==='applicability_required'" in measurement
    assert "window.location.assign('/demo2/login');throw" not in measurement
    evaluation = render_evaluation(TEACHER)
    assert 'RxUI.trackForm("#formCard")' in evaluation and 'title:"撤销这条课堂评价？"' in evaluation
    assert 'okToast("课堂评价已撤销")' in evaluation and "formGuard.clean();" in evaluation
    dossier = render_dossier_student(TEACHER)
    for title in ("撤回这位学生的资料授权？", "删除这个资料版本？"):
        assert title in dossier
    assert "撤回本课的资料引用？" in render_dossier_task(TEACHER)
    assert "confirmDanger(" in dossier and "beforeunload" in dossier
    for html in (measurement, evaluation, dossier):
        assert "rx-btn-danger-solid" in html and "/api/v1/demo2/ui/client-error" in html


def test_draft_persistence_is_opt_in_per_page():
    from rehab_affect.school_selection_page import render_school_selection_html
    # The shared kit only keeps the page back/forward stack (URLs, key rx_nav_stack) in sessionStorage; form drafts stay opt-in.
    assert "localStorage" not in kit.UI_KIT_SCRIPT and "RxDraftStore={get:" not in kit.UI_KIT_SCRIPT
    assert kit.UI_KIT_SCRIPT.count("sessionStorage") == kit.UI_NAV_JS.count("sessionStorage") == 1
    assert "KEY='rx_nav_stack'" in kit.UI_NAV_JS and "store.setItem(KEY," in kit.UI_NAV_JS
    school = render_school_selection_html(TEACHER)
    assert school.count("sessionStorage") == 1 and "RxDraftStore={get:" not in school and "localStorage" not in school
    for html in (render_measurement(TEACHER), render_evaluation(TEACHER), render_dossier_student(TEACHER)):
        assert html.count("window.RxDraftStore={get:") == 1 and "localStorage" not in html
