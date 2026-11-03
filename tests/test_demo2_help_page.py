"""Help page: content in sync with the redesigned pages, unified header, section-view debug log."""

from __future__ import annotations

import json
import re
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pytest

from rehab_affect import demo2_help_page as help_page
from rehab_affect import demo2_manager_gateway as gateway
from rehab_affect import scenario_lab_server as server
from test_demo2_dossier_store import env, template  # noqa: F401

TEACHER = {"account_id": "acct_t1", "username": "school_uploader_01", "login_alias": "t1", "role": "school_uploader"}
ADMIN = {"account_id": "acct_admin", "username": "admin", "login_alias": "admin", "role": "company_admin"}


@pytest.fixture(autouse=True)
def _fresh_budget(monkeypatch, tmp_path):
    monkeypatch.setitem(help_page._BUDGET, "window_start", 0.0)
    monkeypatch.setitem(help_page._BUDGET, "count", 0)
    monkeypatch.setenv(help_page.HELP_DEBUG_LOG_DIR_ENV, str(tmp_path / "help_logs"))


def _log_entries(folder: Path) -> list[dict]:
    return [json.loads(line) for path in sorted(folder.glob("help_debug_*.jsonl"))
            for line in path.read_text(encoding="utf-8").splitlines()]


def _home_step_titles() -> list[tuple[str, str]]:
    source = Path(server.__file__).with_name("demo2_home.py").read_text(encoding="utf-8")
    seen: dict[str, str] = {}
    for key, title in re.findall(r'_step\("([a-z]+)", "([^"]+)"', source):
        seen.setdefault(key, title)
    return list(seen.items())


def test_loop_steps_match_home_page_names_and_order():
    assert [(key, title) for key, title, _hint in help_page.HELP_LOOP_STEPS] == _home_step_titles()
    html = help_page.render_help()
    for block_id in ("helpLoopSteps", "helpFlow"):
        block = re.search(rf'id="{block_id}"[^>]*>(.*?)</ol>', html, re.S).group(1)
        keys = re.findall(r'data-step-key="([a-z]+)"', block)
        assert keys == [key for key, _title, _hint in help_page.HELP_LOOP_STEPS]
        for _key, title, _hint in help_page.HELP_LOOP_STEPS:
            assert f"<strong>{title}</strong>" in block


def test_new_sections_toc_targets_and_faq():
    html = help_page.render_help(TEACHER)
    for section_id in ("home", "analysis-list", "identity", "upload", "measurement", "evaluation", "admin", "faq"):
        assert f'id="{section_id}"' in html
    toc = re.search(r'<nav class="help-toc" id="helpToc".*?</nav>', html, re.S).group(0)
    targets = re.findall(r'href="#([a-z-]+)"', toc)
    assert targets == [section_id for section_id, _label, _group in help_page.HELP_SECTIONS]
    for target in targets:
        assert html.count(f'id="{target}"') == 1
    assert "工作台首页与下一步引导" in html and "我的课堂分析列表" in html
    for question in ("为什么趋势图不显示？", "报告为什么显示「已过期」？", "上传失败怎么办？"):
        assert question in html
    # Redesigned-page details that must stay documented.
    for phrase in ("把视频拖到这里", 'id="uploadFailureTable"', "在画面中点选或框选人物", "至少需要 2 次已复核记录才能看趋势",
                   "3 步分步表单", "通道设置", "查询任务", "符合条件 x / y 项"):
        assert phrase in html


def test_unified_header_by_role():
    anonymous = help_page.render_help()
    assert 'data-rx-scope="public"' in anonymous and 'href="/demo2/login"' in anonymous
    teacher = help_page.render_help(TEACHER)
    assert 'data-rx-scope="teacher"' in teacher
    assert re.search(r'id="rxNavHelp"[^>]*aria-current="page"', teacher)
    admin = help_page.render_help(ADMIN)
    assert 'data-rx-scope="admin"' in admin and 'href="#admin">公司后台怎么用' in admin
    for html in (anonymous, teacher, admin):
        assert html.count('<header class="rx-header"') == 1
        assert ".help-layout > * { min-width:0; }" in html
        assert help_page.HELP_EVENT_PATH in html


def test_section_event_is_validated_and_logged(tmp_path):
    entry = help_page.record_help_event(None, {"event": "toc", "section": "analysis-list"}, TEACHER, now=10.0)
    assert entry["section"] == "analysis-list" and entry["role"] == "school_uploader"
    anonymous = help_page.record_help_event(None, {"event": "open", "section": "top"}, None, now=11.0)
    assert anonymous["role"] == "anonymous" and "account_id" not in anonymous
    for bad in ({"event": "toc"}, {"event": "toc", "section": "<script>"}, {"event": "scroll", "section": "faq"},
                {"event": "toc", "section": "faq", "q": "张三"}, ["toc"]):
        with pytest.raises(help_page.HelpEventRejected):
            help_page.record_help_event(None, bad, TEACHER, now=12.0)
    logged = _log_entries(tmp_path / "help_logs")
    assert [(item["event"], item["section"], item["role"]) for item in logged] == [
        ("toc", "analysis-list", "school_uploader"), ("open", "top", "anonymous")]
    assert all(re.match(r"\d{4}-\d{2}-\d{2}T", item["ts"]) for item in logged)


def test_section_event_budget():
    for _ in range(help_page.HELP_EVENT_BUDGET_PER_MINUTE):
        assert help_page.record_help_event(None, {"event": "hash", "section": "faq"}, None, now=100.0)
    assert help_page.record_help_event(None, {"event": "hash", "section": "faq"}, None, now=120.0) is None
    assert help_page.record_help_event(None, {"event": "hash", "section": "faq"}, None, now=161.0) is not None


def test_gateway_forwards_help_event_without_session():
    assert help_page.HELP_EVENT_PATH in gateway._POST_API
    assert help_page.HELP_EVENT_PATH in gateway._PUBLIC_UPSTREAM
    assert "/demo2/help" in gateway._PUBLIC_UPSTREAM


@pytest.fixture
def http_env(env, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(server, "get_demo2_student_store", lambda: env.records)
    handler = server.create_handler(scenario_dir=Path("configs/scenarios"),
                                    model_path=server.DEFAULT_LEARNED_POLICY_PATH, policy_name="rule")
    http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=http.serve_forever, daemon=True)
    thread.start()

    def request(method, path, token=None, body=None, content_type="application/json"):
        headers = {"Connection": "close"}
        if token:
            headers["Cookie"] = "rehab_demo2_session=" + token
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = content_type
        conn = HTTPConnection("127.0.0.1", http.server_port, timeout=20)
        try:
            conn.request(method, path, body=payload, headers=headers)
            response = conn.getresponse()
            raw = response.read()
            data = json.loads(raw) if "json" in response.getheader("Content-Type", "") else raw.decode("utf-8", "replace")
            return response.status, data
        finally:
            conn.close()

    yield SimpleNamespace(request=request, env=env, logs=tmp_path / "help_logs")
    http.shutdown()
    http.server_close()
    thread.join(3)


def test_http_help_page_and_event_logging(http_env):
    request, env = http_env.request, http_env.env
    status, html = request("GET", "/demo2/help")
    assert status == 200 and 'data-rx-scope="public"' in html
    status, html = request("GET", "/demo2/help", env.tokens["a"])
    assert status == 200 and 'data-rx-scope="teacher"' in html
    status, body = request("POST", help_page.HELP_EVENT_PATH, env.tokens["a"], {"event": "toc", "section": "faq"})
    assert status == 200 and body["logged"] is True
    status, body = request("POST", help_page.HELP_EVENT_PATH, None, {"event": "open", "section": "home"})
    assert status == 200 and body["logged"] is True
    assert request("POST", help_page.HELP_EVENT_PATH, None, {"event": "open", "section": "nope"})[0] == 400
    assert request("POST", help_page.HELP_EVENT_PATH, None, {"event": "open", "section": "faq"},
                   content_type="text/plain")[0] == 415
    entries = _log_entries(http_env.logs)
    opens = [item for item in entries if item["operation"] == "help_page_open"]
    assert {item["role"] for item in opens} == {"anonymous", "school_uploader"}
    views = [(item["result"], item.get("section"), item["role"]) for item in entries
             if item["operation"] == "help_section_view"]
    assert ("ok", "faq", "school_uploader") in views and ("ok", "home", "anonymous") in views
    assert any(result == "rejected" for result, _section, _role in views)


def test_phase_three_sections_and_faq():
    html = help_page.render_help(TEACHER)
    toc = re.search(r'<nav class="help-toc" id="helpToc".*?</nav>', html, re.S).group(0)
    for section_id in ("weglow", "navigation", "course-task", "iep-summary", "person-filter", "school-search",
                       "measurement-links"):
        assert f'href="#{section_id}"' in toc and html.count(f'id="{section_id}"') == 1
        assert section_id in help_page.HELP_SECTION_IDS
    assert "WeGlow微光系统" in html and "RehabAffect" not in html and "云图智航" not in html
    for phrase in ("「← 后退」「前进 →」", "课程任务目标确认", "必填", "人工补充", "恢复为学生", "标记为老师/非学生",
                   "不判断画面中任何人是谁", "全国学校目录", "找不到？手动填写学校", "一键补录", "片段复核"):
        assert phrase in html, phrase
    assert 'id="faqScanned"' in html and "扫描件" in html
    assert 'id="faqWrongRecognition"' in html and "识别错了" in html
    # The new anchors are accepted by the section-view logger.
    entry = help_page.record_help_event(None, {"event": "toc", "section": "iep-summary"}, TEACHER, now=5.0)
    assert entry["section"] == "iep-summary" and entry["operation"] == "help_section_view"


def test_phase_four_sections_faq_and_loop_rename():
    html = help_page.render_help(TEACHER)
    toc = re.search(r'<nav class="help-toc" id="helpToc".*?</nav>', html, re.S).group(0)
    for section_id in ("multi-student", "scoring-basis", "course-evaluation", "course-overview", "report-word-pdf"):
        assert f'href="#{section_id}"' in toc and html.count(f'id="{section_id}"') == 1
        assert section_id in help_page.HELP_SECTION_IDS
    for faq_id, question in (("faqFewStudents", "为什么只识别到一名学生？"), ("faqScoreHow", "分数是怎么算出来的？"),
                             ("faqCourseGrade", "课程等级怎么判定？")):
        assert f'id="{faq_id}"' in html and question in html
    # 第 7 步改名为「课程评价」，并与首页一致。
    assessment = dict((key, title) for key, title, _hint in help_page.HELP_LOOP_STEPS)["assessment"]
    assert assessment == "学生测量 / 评课"
    for phrase in ("本课检测学生", "纳入本课检测", "查看依据", "下载 Word 报告", "下载 PDF 报告", "试行", "学生评价矩阵",
                   "去做评课", "查看课程总览", "管理本课检测学生"):
        assert phrase in html, phrase
    # In-page links point at existing anchors only.
    for target in set(re.findall(r'href="#([a-z-]+)"', html)):
        assert html.count(f'id="{target}"') == 1, target
    # Every new anchor is accepted by the section-view logger.
    for section_id in ("multi-student", "scoring-basis", "course-evaluation", "course-overview", "report-word-pdf"):
        entry = help_page.record_help_event(None, {"event": "toc", "section": section_id}, TEACHER, now=7.0)
        assert entry["section"] == section_id and entry["result"] == "ok" and entry["ts"]
