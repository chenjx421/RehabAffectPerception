"""Teacher-facing help page for the Demo2 classroom analysis workflow.

The page is public (reachable before login). Signed-in users get the shared
navigation of their role from ``demo2_ui_kit.header_for``; anonymous visitors
get a minimal header with the same look.

Debug logging: the server writes ``help_page_open`` when the page is served,
and the page reports which section anchor was opened (initial hash, table of
contents click, in-page link, hash change) to ``HELP_EVENT_PATH``. Both go to
``help_debug_YYYYMMDD.jsonl`` (``<data>/logs`` or
``REHAB_DEMO2_HELP_DEBUG_LOG_DIR``) with a timestamp, the account role and the
section id. Only whitelisted ids are written – never free text, query strings
or student data.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .demo2_portal import _COMMON_STYLE, _document
from .demo2_ui_kit import BRAND_FULL_NAME, BRAND_NAME, BRAND_TAGLINE, BRAND_VERSION, account_field, account_role, header_for, history_buttons, icon
from .demo2_upload_debug import log_dir_for_store

HELP_PATH = "/demo2/help"
HELP_EVENT_PATH = "/api/v1/demo2/help/debug-event"
HELP_DEBUG_LOG_DIR_ENV = "REHAB_DEMO2_HELP_DEBUG_LOG_DIR"
HELP_LOGGER = logging.getLogger("rehab_affect.help")
_LOG_LOCK = threading.Lock()

# Must match the step titles and order of the home page loop (demo2_home.build_home_summary).
HELP_LOOP_STEPS: tuple[tuple[str, str, str], ...] = (
    ("school", "学校信息", "确认城市、区县和学校"),
    ("roster", "学生名册建档", "新增本节课要关注的学生"),
    ("dossier", "资料授权与 IEP", "先登记授权，再上传 IEP"),
    ("upload", "上传课堂视频", "拖入或选择视频并等待分析"),
    ("identity", "确认画面中的学生", "对应到名册并关联本课 IEP"),
    ("applicability", "确认视频适用性", "确认内容类型与教学目标"),
    ("assessment", "学生测量 / 评课", "复核测量并完成评课"),
    ("report", "查看并下载课堂报告", "生成图文报告并下载"),
)

# (anchor id, table-of-contents label, group). Group "" = shown before the groups.
HELP_SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("screenshots", "截图教学", ""),
    ("weglow", "WeGlow微光系统介绍", ""),
    ("map", "功能总览", ""),
    ("full-flow", "完整闭环 8 步", ""),
    ("home", "工作台首页与下一步", "日常使用"),
    ("lesson", "本课工作台（4 步入口）", "日常使用"),
    ("find", "找功能：一页搜到所有入口", "日常使用"),
    ("start", "登录与导航", "日常使用"),
    ("navigation", "页面前进与后退", "日常使用"),
    ("school-search", "全国学校搜索与手动填写", "日常使用"),
    ("upload", "上传视频", "日常使用"),
    ("course-task", "课程任务 Word/PDF 与目标确认", "日常使用"),
    ("capture", "录制课堂", "日常使用"),
    ("result", "查看学生状态", "日常使用"),
    ("person-filter", "学生人物自动筛查", "日常使用"),
    ("multi-student", "多学生切换与选择被检测学生", "日常使用"),
    ("analysis-list", "我的课堂分析列表", "日常使用"),
    ("archive", "绑定与归档", "日常使用"),
    ("roster", "学生名册与资料授权", "深入复核"),
    ("iep-summary", "IEP 文件与支持摘要", "深入复核"),
    ("long-term", "IEP 强制与长期观测", "深入复核"),
    ("identity", "确认画面中的学生", "深入复核"),
    ("manual-seats", "手动画框与按座位重新分析", "深入复核"),
    ("condition-confirm", "病况 / 健康与安全要点确认", "深入复核"),
    ("review", "课堂复核与图文报告", "深入复核"),
    ("measurement-links", "测量结果在哪里看", "深入复核"),
    ("evaluation", "课堂双轨评价", "深入复核"),
    ("course-evaluation", "评课（10 项指标）", "深入复核"),
    ("course-overview", "课程总览与结论", "深入复核"),
    ("measurement", "学生测量与趋势", "深入复核"),
    ("scoring-basis", "评分标准细则与查看依据", "深入复核"),
    ("report-word-pdf", "下载 Word/PDF 报告", "深入复核"),
    ("safety", "安全事件核查", "深入复核"),
    ("membership", "会员中心", "深入复核"),
    ("admin", "公司后台", "管理与规则"),
    ("privacy", "数据与隐私", "管理与规则"),
    ("faq", "常见问题", "管理与规则"),
)
HELP_SECTION_IDS = frozenset(["top", *(section_id for section_id, _label, _group in HELP_SECTIONS)])
HELP_EVENT_KINDS = frozenset({"open", "toc", "link", "hash"})
HELP_EVENT_BUDGET_PER_MINUTE = 240
_BUDGET = {"window_start": 0.0, "count": 0}
_ROLE_RE = re.compile(r"[A-Za-z0-9_]{1,40}")
_ID_RE = re.compile(r"[A-Za-z0-9_.:-]{1,128}")


class HelpEventRejected(ValueError):
    """The reported help event does not match the accepted shape."""


# --------------------------------------------------------------------------
# Debug log
# --------------------------------------------------------------------------


def help_log_dir(store: Any) -> Path:
    configured = os.getenv(HELP_DEBUG_LOG_DIR_ENV, "").strip()
    if configured:
        return Path(configured)
    return log_dir_for_store(store)


def _role_of(account: Any) -> str:
    if account is None:
        return "anonymous"
    role = account_role(account)
    return role if _ROLE_RE.fullmatch(role) else "unknown"


def _account_id_of(account: Any) -> str:
    if account is None:
        return ""
    for key in ("account_id", "id"):
        value = account_field(account, key)
        if value is not None and _ID_RE.fullmatch(str(value)):
            return str(value)
    return ""


def help_debug_event(store: Any, operation: str, result: str, *, account: Any = None, **fields: Any) -> dict[str, Any]:
    """Write one JSON line; a logging failure never blocks the page."""
    entry: dict[str, Any] = {
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "operation": operation if _ID_RE.fullmatch(operation) else "<invalid>",
        "result": result if _ID_RE.fullmatch(result) else "<invalid>",
        "page": "help",
        "role": _role_of(account),
    }
    account_id = _account_id_of(account)
    if account_id:
        entry["account_id"] = account_id
    for key in ("event", "section", "code"):
        value = fields.get(key)
        if value:
            entry[key] = str(value) if _ID_RE.fullmatch(str(value)) else "<invalid>"
    if isinstance(fields.get("elapsed_ms"), (int, float)) and not isinstance(fields.get("elapsed_ms"), bool):
        entry["elapsed_ms"] = round(float(fields["elapsed_ms"]), 2)
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    HELP_LOGGER.debug(line)
    try:
        folder = help_log_dir(store)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"help_debug_{entry['ts'][:10].replace('-', '')}.jsonl"
        with _LOG_LOCK, path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except (OSError, TypeError, ValueError):
        HELP_LOGGER.warning("help debug log write failed")
    return entry


def _budget_ok(now: float) -> bool:
    with _LOG_LOCK:
        if now - _BUDGET["window_start"] >= 60:
            _BUDGET["window_start"] = now
            _BUDGET["count"] = 0
        if _BUDGET["count"] >= HELP_EVENT_BUDGET_PER_MINUTE:
            return False
        _BUDGET["count"] += 1
        return True


def record_help_event(store: Any, payload: Any, account: Any = None, *, now: float | None = None) -> dict[str, Any] | None:
    """Validate a page-reported section view and log it.

    Returns the log entry, or ``None`` when the per-minute budget is spent.
    Raises ``HelpEventRejected`` for anything outside ``{event, section}``.
    """
    if not isinstance(payload, dict) or set(payload) != {"event", "section"}:
        raise HelpEventRejected("只接受 event 与 section 两个字段")
    event, section = payload.get("event"), payload.get("section")
    if not isinstance(event, str) or event not in HELP_EVENT_KINDS:
        raise HelpEventRejected("event 取值无效")
    if not isinstance(section, str) or section not in HELP_SECTION_IDS:
        raise HelpEventRejected("section 不是帮助页章节")
    if not _budget_ok(time.monotonic() if now is None else now):
        HELP_LOGGER.debug("help event dropped: budget exhausted")
        return None
    return help_debug_event(store, "help_section_view", "ok", account=account, event=event, section=section)


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

HELP_STYLE = _COMMON_STYLE + r"""
body { background:var(--rx-canvas,#f4f7fb); }
.help-main { width:min(1120px,calc(100% - 40px)); margin:0 auto; padding:34px 0 72px; }
.help-hero { display:grid; grid-template-columns:minmax(0,1fr) 330px; gap:30px; align-items:end; padding:26px 28px; background:#fff; border:1px solid var(--line); border-left:4px solid var(--blue); border-radius:8px; }
.help-hero > * { min-width:0; }
.help-hero h1 { max-width:700px; font-size:32px; line-height:1.25; margin:0; }
.help-hero p { max-width:720px; margin-top:12px; color:var(--muted); line-height:1.8; }
.help-steps { list-style:none; padding:0; display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:8px; margin:22px 0 32px; }
.help-step { min-width:0; min-height:92px; padding:14px; border:1px solid var(--line); border-top:3px solid var(--blue); border-radius:6px; background:#fff; }
.help-step b { display:block; color:var(--blue); font:700 20px/1 "Segoe UI",sans-serif; }
.help-step strong { display:block; margin-top:8px; font-size:14px; overflow-wrap:anywhere; }
.help-step span { display:block; margin-top:3px; color:var(--muted); font-size:12px; }
.help-steps-head { display:flex; flex-wrap:wrap; align-items:baseline; justify-content:space-between; gap:6px 16px; margin-top:28px; }
.help-steps-head h2 { margin:0; font-size:18px; }
.help-steps-head p { margin:0; color:var(--muted); font-size:13px; }
.help-layout { display:grid; grid-template-columns:210px minmax(0,1fr); gap:32px; align-items:start; }
.help-layout > * { min-width:0; }
.help-toc { position:sticky; top:84px; max-height:calc(100vh - 100px); overflow-y:auto; padding:4px 0; }
.help-toc strong { display:block; margin-bottom:9px; font-size:13px; color:var(--blue-deep); }
.help-toc a { display:block; padding:7px 10px; border-left:2px solid transparent; color:var(--muted); font-size:13px; text-decoration:none; }
.help-toc a:hover,.help-toc a[aria-current="true"] { border-left-color:var(--blue); color:var(--blue); background:var(--blue-pale); }
.help-toc .toc-group { display:block; margin:12px 0 4px; padding-left:10px; color:#8394a7; font-size:12px; font-weight:400; }
.help-section { padding:0 0 30px; margin-bottom:30px; border-bottom:1px solid var(--line); scroll-margin-top:84px; }
.help-section:last-child { margin-bottom:0; border-bottom:0; }
.help-section h2 { margin:0 0 8px; font-size:21px; }
.help-section > p { color:var(--muted); line-height:1.8; }
.help-card-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin-top:18px; }
.help-card { min-width:0; padding:18px; border:1px solid var(--line); border-radius:6px; background:#fff; }
.help-card h3 { margin:0 0 7px; font-size:16px; }
.help-card p { margin:0; color:#56687c; font-size:13px; line-height:1.75; }
.help-card p + p { margin-top:8px; }
.help-card ol,.help-card ul { margin:9px 0 0; padding-left:20px; color:#56687c; font-size:13px; line-height:1.8; }
.help-callout { margin-top:18px; padding:14px 16px; border-left:3px solid var(--blue); border-radius:0 6px 6px 0; background:var(--blue-soft); color:var(--blue-deep); font-size:13px; line-height:1.8; }
.help-callout strong { display:block; margin-bottom:3px; }
.help-callout.warn { border-left-color:#c27a12; background:#fff7e8; color:#6b4106; }
.help-shot-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; margin:18px 0 0; }
.help-shot { min-width:0; border:1px solid var(--line); border-radius:6px; background:#fff; padding:10px; }
.help-shot h3 { margin:10px 2px 3px; font-size:15px; }
.help-shot > p { margin:0 2px; color:var(--muted); font-size:12px; line-height:1.65; }
.shot-browser { min-height:230px; overflow:hidden; border:1px solid #cfd9e4; border-radius:5px; background:#f7f9fc; box-shadow:0 2px 7px #1b355a12; }
.shot-bar { display:flex; align-items:center; gap:5px; height:22px; padding:0 8px; background:#e9eef4; border-bottom:1px solid #d7e0e9; }
.shot-dot { width:6px; height:6px; border-radius:50%; background:#aab8c6; }
.shot-url { flex:1; min-width:0; overflow:hidden; white-space:nowrap; height:12px; margin-left:4px; border-radius:2px; background:#fff; color:#7c8998; font:9px/12px Consolas,monospace; padding-left:6px; }
.shot-content { min-height:208px; padding:16px; color:#263b52; font-size:10px; }
.shot-brand { color:var(--blue); font-size:13px; font-weight:800; margin-bottom:12px; }
.shot-login { width:70%; margin:0 auto; padding:12px; border:1px solid #dce5ee; background:#fff; }
.shot-login strong { display:block; font-size:14px; margin-bottom:10px; }
.shot-input { height:22px; margin:7px 0; padding:5px 7px; border:1px solid #cdd9e5; color:#9ba7b4; background:#fff; }
.shot-button { display:inline-flex; align-items:center; justify-content:center; min-height:23px; padding:0 9px; border-radius:3px; background:var(--blue); color:#fff; font-size:10px; font-weight:700; }
.shot-heading { display:flex; align-items:center; justify-content:space-between; gap:8px; border-bottom:1px solid #dce5ee; padding-bottom:8px; margin-bottom:10px; }
.shot-heading strong { font-size:14px; }
.shot-drop { display:flex; flex-direction:column; align-items:center; gap:4px; padding:12px 6px; border:1.5px dashed #9fb8d4; border-radius:5px; background:#f4f8fd; color:#4b6380; text-align:center; }
.shot-drop b { color:var(--blue); }
.shot-progress { height:8px; overflow:hidden; margin:10px 0 5px; border-radius:3px; background:#e5edf5; }
.shot-progress i { display:block; width:78%; height:100%; background:#2c7cc7; }
.shot-stage { display:flex; gap:4px; margin-top:8px; }
.shot-stage span { flex:1; padding:3px 2px; border-radius:3px; background:#e5edf5; color:#5b6f84; text-align:center; font-size:9px; }
.shot-stage span.on { background:#dbeafa; color:var(--blue-deep); font-weight:700; }
.shot-person-tabs { display:flex; gap:5px; margin:0 0 9px; }
.shot-person { flex:1; padding:5px; border:1px solid #d6e0ea; background:#fff; color:#31465c; text-align:center; font-size:10px; }
.shot-person.active { border-color:var(--blue); background:#eaf2fc; color:var(--blue-deep); font-weight:700; }
.shot-face { height:34px; margin-bottom:4px; background:#dbe7ef; position:relative; }
.shot-face:before { content:''; position:absolute; width:16px; height:18px; left:calc(50% - 8px); top:6px; border-radius:50%; background:#7d9ab1; }
.shot-face:after { content:''; position:absolute; width:25px; height:11px; left:calc(50% - 12px); bottom:0; border-radius:12px 12px 0 0; background:#54748f; }
.shot-event { display:grid; grid-template-columns:45px 1fr; gap:5px; align-items:center; min-height:22px; border-top:1px solid #e5ebf1; color:#53697c; font-size:9px; }
.shot-event b { color:#17684f; font-size:9px; }
.shot-download { margin-top:8px; text-align:right; }
.help-table-wrap { overflow-x:auto; -webkit-overflow-scrolling:touch; margin-top:18px; }
.help-table { width:100%; border-collapse:collapse; background:#fff; font-size:13px; }
.help-table th,.help-table td { padding:11px 12px; border:1px solid var(--line); text-align:left; vertical-align:top; line-height:1.7; }
.help-table th { background:var(--blue-pale); color:var(--blue-deep); font-weight:700; }
.help-table td:first-child { white-space:nowrap; font-weight:700; color:#28415e; }
.help-table code,.help-card code,.help-section > p code { padding:1px 5px; border-radius:3px; background:#eef3f8; color:#28415e; font:12px Consolas,monospace; word-break:break-all; }
.help-faq { border-top:1px solid var(--line); background:#fff; border-radius:6px; }
.help-faq details { padding:13px 14px; border-bottom:1px solid var(--line); }
.help-faq summary { cursor:pointer; color:var(--blue-deep); font-weight:700; }
.help-faq p { margin:9px 0 2px; color:var(--muted); font-size:13px; line-height:1.8; }
.help-faq ul { margin:6px 0 2px; padding-left:20px; color:var(--muted); font-size:13px; line-height:1.8; }
.help-footer { width:min(1120px,calc(100% - 40px)); margin:0 auto; padding:22px 0; color:var(--muted); font-size:12px; border-top:1px solid var(--line); }
.help-roles { display:flex; flex-wrap:wrap; gap:8px; margin-top:16px; }
.help-roles a { display:inline-flex; align-items:center; min-height:38px; padding:7px 14px; border:1px solid var(--line-strong); border-radius:4px; background:#fff; color:var(--blue-deep); font-size:13px; font-weight:700; text-decoration:none; }
.help-roles a:hover { border-color:var(--blue); background:var(--blue-pale); }
.help-tag { display:inline-block; margin-left:6px; padding:1px 7px; border-radius:3px; background:var(--blue-pale); color:var(--blue-deep); font-size:12px; font-weight:700; vertical-align:2px; }
.help-tag.admin { background:#fff7e8; color:#9a5a08; }
.help-tag.new { background:#e6f6ec; color:#17683b; }
.help-flow { margin:18px 0 0; padding:0; list-style:none; counter-reset:flow; display:grid; gap:8px; }
.help-flow li { counter-increment:flow; position:relative; padding:12px 14px 12px 52px; border:1px solid var(--line); border-radius:6px; background:#fff; font-size:13px; line-height:1.75; color:#56687c; }
.help-flow li:before { content:counter(flow,decimal-leading-zero); position:absolute; left:14px; top:12px; color:var(--blue); font:700 16px/1.6 "Segoe UI",sans-serif; }
.help-flow li strong { color:#28415e; }
.help-badges { display:flex; flex-wrap:wrap; gap:6px; margin-top:10px; }
.help-back { display:none; }
.rx-header[data-rx-scope="public"] .rx-nav-panel { margin-left:auto; }
@media (max-width:820px) {
  .help-hero { grid-template-columns:1fr; gap:18px; padding:22px 20px; }
  .help-steps { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .help-layout { grid-template-columns:1fr; gap:8px; }
  .help-toc { position:static; max-height:none; display:flex; gap:4px; overflow-x:auto; padding-bottom:10px; border-bottom:1px solid var(--line); -webkit-overflow-scrolling:touch; }
  .help-toc strong,.help-toc .toc-group { display:none; }
  .help-toc a { flex:0 0 auto; border-left:0; border-bottom:2px solid transparent; }
  .help-toc a:hover,.help-toc a[aria-current="true"] { border-bottom-color:var(--blue); border-left:0; }
  .help-section { scroll-margin-top:72px; }
  .help-back { position:fixed; right:14px; bottom:16px; z-index:40; display:inline-flex; align-items:center; min-height:40px; padding:8px 14px; border-radius:20px; background:var(--blue); color:#fff; font-size:13px; font-weight:700; text-decoration:none; box-shadow:0 4px 14px #1b355a33; }
}
@media (max-width:620px) {
  .help-main,.help-footer { width:min(100% - 28px,1120px); }
  .help-main { padding-top:20px; }
  .help-hero h1 { font-size:26px; }
  .help-card-grid,.help-shot-grid { grid-template-columns:1fr; }
  .help-step { min-height:84px; }
}
@media (max-width:360px) {
  .help-steps { grid-template-columns:1fr; }
}
"""

HELP_SCRIPT = r"""
(function(){
  var PATH='__HELP_EVENT_PATH__';
  var SECTIONS=__HELP_SECTIONS__;
  var sent=0, lastSection=null, LIMIT=60;
  function clean(id){ return SECTIONS.indexOf(id)>=0?id:'top'; }
  function fromHash(){ var raw=location.hash.slice(1); try{ raw=decodeURIComponent(raw); }catch(e){} return clean(raw||'top'); }
  function send(kind, section){
    if (sent>=LIMIT) return;
    sent++; lastSection=section;
    try {
      fetch(PATH,{method:'POST',credentials:'same-origin',keepalive:true,headers:{'Content-Type':'application/json'},
        body:JSON.stringify({event:kind,section:section})}).catch(function(){});
    } catch(e) {}
  }
  send('open', fromHash());
  document.addEventListener('click',function(e){
    var a=e.target && e.target.closest ? e.target.closest('a[href^="#"]') : null;
    if (!a) return;
    var id=clean(a.getAttribute('href').slice(1));
    if (id==='top' && a.getAttribute('href')!=='#top') return;
    send(a.closest('.help-toc')?'toc':'link', id);
  });
  window.addEventListener('hashchange',function(){ var id=fromHash(); if (id!==lastSection) send('hash', id); });
  var toc=document.getElementById('helpToc');
  if (toc && 'IntersectionObserver' in window) {
    var links={}; toc.querySelectorAll('a[href^="#"]').forEach(function(a){ links[a.getAttribute('href').slice(1)]=a; });
    var active=null;
    var observer=new IntersectionObserver(function(entries){
      entries.forEach(function(entry){
        if (!entry.isIntersecting) return;
        var link=links[entry.target.id]; if (!link || link===active) return;
        if (active) active.removeAttribute('aria-current');
        link.setAttribute('aria-current','true'); active=link;
        if (window.matchMedia('(max-width:820px)').matches && toc.scrollWidth>toc.clientWidth) {
          toc.scrollLeft=Math.max(0, link.offsetLeft-toc.offsetLeft-24);
        }
      });
    },{rootMargin:'-90px 0px -65% 0px'});
    document.querySelectorAll('.help-section[id]').forEach(function(s){ observer.observe(s); });
  }
})();
"""


def _public_header() -> str:
    """Header for visitors who have not signed in (same kit classes as the role headers)."""
    return f"""<header class="rx-header" data-rx-scope="public" data-rx-page="help">
  <div class="rx-header-inner">
    <a class="rx-brand" href="/demo2/login" aria-label="{BRAND_FULL_NAME} 登录" data-brand-version="{BRAND_VERSION}">{icon("glow", css_class="rx-brand-icon")}<span class="rx-brand-copy"><strong>{BRAND_NAME}<em>微光系统</em></strong><span>{BRAND_TAGLINE}</span></span></a>
    {history_buttons("/demo2/login")}
    <button class="rx-nav-toggle" type="button" aria-expanded="false" aria-controls="rxNavPanel" aria-label="打开导航菜单">{icon("menu")}<span>菜单</span></button>
    <div class="rx-nav-panel" id="rxNavPanel">
      <nav class="rx-nav" aria-label="帮助页导航"><a class="rx-nav-link" href="/demo2/login" id="helpLoginLink">登录</a><a class="rx-nav-link" href="/demo2/register" id="helpRegisterLink">手机号注册</a><a class="rx-nav-link" href="/demo2/privacy" id="helpPrivacyLink">数据安全与隐私</a><a class="rx-nav-link" href="/demo2/help" id="rxNavHelp" aria-current="page">使用帮助</a></nav>
    </div>
  </div>
</header>"""


def _header(account: Any) -> str:
    if account is None:
        return _public_header()
    return header_for(account, "help", admin_active="", page="help", logout_bound=False)


def _toc() -> str:
    parts = ['<strong>本页内容</strong>']
    current_group = ""
    for section_id, label, group in HELP_SECTIONS:
        if group and group != current_group:
            parts.append(f'<span class="toc-group">{group}</span>')
            current_group = group
        parts.append(f'<a href="#{section_id}">{label}</a>')
    return f'<nav class="help-toc" id="helpToc" aria-label="帮助内容目录">{"".join(parts)}</nav>'


def _loop_steps() -> str:
    items = "".join(
        f'<li class="help-step" data-step-key="{key}"><b>{index:02d}</b><strong>{title}</strong><span>{hint}</span></li>'
        for index, (key, title, hint) in enumerate(HELP_LOOP_STEPS, start=1)
    )
    return f'<ol class="help-steps" id="helpLoopSteps" aria-label="课堂分析闭环 8 步">{items}</ol>'


def _flow_list() -> str:
    details = {
        "school": "首次登录到顶部「学校信息」确认城市、区县和学校并保存。已有任务保留上传时的学校快照，改名不会自动迁移。",
        "roster": "顶部「学生名册」→「新增本校学生」，填写姓名（必填）、校内编号和班级。",
        "dossier": "需要报告引用 IEP 时：在学生的「资料与授权」先登记授权，再新增 IEP。授权 30 天内到期时首页会提醒续期。",
        "upload": "在「上传任务」拖入或选择课堂视频，点「确认授权并上传」，等待后台处理完成。"
                  "子步骤「上传课程任务」：在同一页「课程任务文件（Word/PDF）」上传本课教学任务/教案，系统自动识别课程名称、"
                  "上课日期和课程任务目标（编号 G-01、通过标准、测量条件、评分维度建议），在「课程任务目标确认」抽屉逐条核对、"
                  "编辑或删除，把「其他内容」加入为目标或备注后确认保存。确认后课堂评价自动带入本课目标、学生测量可下拉预填、"
                  "课堂复核页按目标标注相关片段、图文报告新增「本课任务目标与达成情况」。重新上传会生成新版本，旧版本保留，"
                  "引用旧版本的报告会显示已过期，重新打开报告页即按新版本生成。",
        "identity": "在「确认画面中的学生」页按右侧 3 步把人物和名册学生对应；所选画面时刻要落在要测量的片段内。学生已有 IEP 时，再到「课程关联资料」为本课勾选 IEP 版本，首页这一步才会变为已完成。",
        "applicability": "在「课堂复核与报告」页确认视频内容类型与教学目标，之后才能保存已复核或带分数的测量。",
        "assessment": "先在「学生测量」复核每名学生的测量记录（视频生成的建议分需老师勾选复核），再到「评课」按学校 4 类 10 项指标给这节课评分（系统建议分自动预填，可点「查看依据」）。两者都完成后，「课程总览」会给出本课的试行结论等级。",
        "report": "在「课堂复核与报告」的「图文报告」标签生成报告，点「下载 Word 报告」或「下载 PDF 报告」得到可直接阅读的中文文字报告；HTML / MD / JSON 只在「数据导出（技术人员用）」中。",
    }
    items = "".join(
        f'<li data-step-key="{key}"><strong>{title}</strong>：{details[key]}</li>' for key, title, _hint in HELP_LOOP_STEPS
    )
    return f'<ol class="help-flow" id="helpFlow">{items}</ol>'


def _sections() -> str:
    return f"""
      <section class="help-section" id="weglow"><h2>WeGlow微光系统介绍<span class="help-tag new">新</span></h2><p>平台品牌为 <strong>WeGlow</strong>，平台注册名称为 <strong>WeGlow微光系统</strong>。它面向特殊教育与融合教育课堂，把一节课的视频、课程任务、学生 IEP 支持摘要、测量记录、双轨评价和课堂报告用同一套编号串起来，方便老师课后回看、复核和留档。</p><div class="help-card-grid"><article class="help-card"><h3>一条主线</h3><p>学校信息 → 学生名册 → 资料授权与 IEP → 上传视频（可同时上传课程任务文件）→ 确认学生 → 确认适用性 → 测量 / 评价 → 报告。首页会按这条主线提示「下一步」。</p></article><article class="help-card"><h3>文件自动识别，老师最终确认</h3><p>课程任务和 IEP 都可以直接上传 Word 或 PDF。系统会把文件里的内容全部列出并给出建议摘要，但只有老师逐条核对、点确认后才会保存并用于评分和报告。</p></article><article class="help-card"><h3>只关注学生</h3><p>视频分析会自动把疑似老师和空白、模糊的无效人选排除出学生列表，老师随时可以恢复。筛查只看画面特征，不判断任何人的身份。</p></article><article class="help-card"><h3>结果的定位</h3><p>所有状态线索、测量分和评价分都用于课堂回看与教学改进，不替代专业诊断、IEP 决策或学校正式评价。</p></article></div></section>
      <section class="help-section" id="map"><h2>功能总览</h2><p>老师账号登录后，顶部导航依次是「首页、上传任务、学生名册、学生测量、评课、课堂录制、学校信息、会员中心、使用帮助」。手机上点右上角「菜单」展开。其余页面从首页、任务记录或学生名册里进入。</p><div class="help-table-wrap"><table class="help-table"><thead><tr><th>功能</th><th>从哪里进入</th><th>用来做什么</th></tr></thead><tbody>
<tr><td>工作台首页<span class="help-tag new">新</span></td><td>顶部「首页」；点左上角品牌标志</td><td>按真实数据显示闭环 8 步进度、高亮「下一步」，列出待办事项和最近 5 个任务。</td></tr>
<tr><td>本课工作台<span class="help-tag new">新</span></td><td>课堂分析页左侧「本课工作台」</td><td>一节课 4 步入口：视频与身份 / 学生测量 / 评课 / 报告；显示 IEP 完整度和学生卡片。</td></tr>
<tr><td>上传视频</td><td>顶部「上传任务」</td><td>拖入或选择课堂视频并自动分析；查看本课程任务、名额、处理状态和失败原因。</td></tr>
<tr><td>上传课程任务</td><td>「上传任务」页 · 课程任务文件（Word/PDF）</td><td>上传本课教学任务/教案，系统识别课程目标；逐条确认后用于课堂评价、学生测量、片段标注和课堂报告，每次重新确认生成新版本。</td></tr>
<tr><td>我的课堂分析<span class="help-tag new">新</span></td><td>上传页「更多功能」→「课堂复核与报告」；分析页「切换视频」</td><td>列出本账号在本校上传的课堂视频，显示处理状态和报告状态，点「查看分析」进入。</td></tr>
<tr><td>学生状态结果</td><td>上传完成自动跳转；首页最近任务「进入结果」</td><td>按人物查看截图、状态时间轴、本节课概览与分析报告，下载结果，绑定姓名并归档。</td></tr>
<tr><td>课堂录制</td><td>顶部「课堂录制」</td><td>用电脑摄像头和麦克风直接录一段课堂，保存到课程后自动分析。</td></tr>
<tr><td>学生名册</td><td>顶部「学生名册」</td><td>建立本校学生名单（姓名、校内编号、班级）。</td></tr>
<tr><td>资料与授权</td><td>学生名册中某位学生的「资料与授权」</td><td>登记授权、上传 IEP / 专业评估 / 五领域评估 / 安全与支持资料，查看课堂引用历史。</td></tr>
<tr><td>IEP 强制与长期观测<span class="help-tag new">新</span></td><td>学生测量总览「长期观测 / IEP」</td><td>查看 IEP 状态、课程时间轴和四维测量；没有当前 IEP 不能生成正式报告。</td></tr>
<tr><td>公司留存摘要</td><td>学生名册中某位学生的「公司留存摘要」</td><td>在授权范围内整理教师核对的学习目标、支持方法和五领域观察。</td></tr>
<tr><td>确认画面中的学生</td><td>首页第 5 步；复核页「确认学生身份」</td><td>按 3 步把视频中的人物与名册学生对应。</td></tr>
<tr><td>手动画框与按座位重新分析<span class="help-tag new">新</span></td><td>「确认画面中的学生」页</td><td>3 名学生确认后按这 3 个座位重新分析；结果只保留这 3 人，成人不再进入学生列表。</td></tr>
<tr><td>课堂复核与报告</td><td>我的课堂分析列表「查看分析」</td><td>群像概览、个体观察、片段复核、图文报告四个标签；确认视频适用性。</td></tr>
<tr><td>课程关联资料</td><td>复核页「课程关联资料」</td><td>为本节课已确认身份的学生选择要引用的资料版本（如 IEP）。</td></tr>
<tr><td>同课多视频汇总</td><td>复核页「同课多视频汇总」</td><td>同一课程批次的多个视频合并查看，核准本课学生目标结论。</td></tr>
<tr><td>教学支持</td><td>复核页「教学支持与上传测试」</td><td>试跑检查清单、按支持需求选择教学办法、记录每节课的改进点。</td></tr>
<tr><td>视频证据详情</td><td>任务记录点文件名；复核页「视频证据详情」</td><td>步骤条「已上传 → 已解码 → 证据已就绪 → 待教师复核」，按时间切片回看画面和声音，可重新处理。</td></tr>
<tr><td>评课</td><td>顶部「评课」、首页「为本课做评课」、我的课堂分析列表「评课」</td><td>按学校「课堂教学基本评价指标」4 个类目 10 个条目给整节课评分：学校分由教师录入，系统建议分按本课数据自动预填并附依据，查看类目得分、学校 vs 系统条形图与分差。</td></tr>
<tr><td>学生测量</td><td>顶部「学生测量」</td><td>按学习目标记录四维测量分，查看纵向趋势，生成单次记录报告。</td></tr>
<tr><td>安全事件核查</td><td>评课页顶部「安全核查」</td><td>记录课堂中的安全相关客观观察，指定核查人人工核查。</td></tr>
<tr><td>学校信息</td><td>顶部「学校信息」</td><td>确认所属地区和学校；首次使用需先完成。</td></tr>
<tr><td>会员中心</td><td>顶部「会员中心」</td><td>查看会员状态、服务套餐和订单记录。</td></tr>
<tr><td>公司后台<span class="help-tag admin">管理员</span></td><td>登录页选择「管理员登录」</td><td>总览、任务查询、上传通道、学生资料运行状态、测量记录汇总、会员与订单。</td></tr>
</tbody></table></div></section>
      <section class="help-section" id="full-flow"><h2>完整闭环 8 步</h2><p>下面 8 步与工作台首页「课堂分析闭环」的名称和顺序完全一致。只想看学生状态时，做第 1、4 步即可；要把一节课做成「有身份、有复核、有评分、有报告」的完整记录，就按顺序走完，前一步没做时后一步会提示无法保存。</p>{_flow_list()}<div class="help-callout"><strong>不确定做到哪一步了？</strong>打开顶部「首页」，系统会按本账号的真实数据标出每一步的状态，并高亮「下一步」，点按钮直接前往。</div></section>
      <section class="help-section" id="home"><h2>工作台首页与下一步引导<span class="help-tag new">新</span></h2><p>登录后点顶部「首页」或左上角品牌标志进入。首页只显示本账号自己的数据，打开时自动读取最新进度。</p><div class="help-card-grid"><article class="help-card"><h3>课堂分析闭环</h3><p>8 张步骤卡按顺序排列，每张显示状态、计数和说明，右上角显示「已完成 x / 8 步」。状态有四种：</p><div class="help-badges"><span class="rx-badge rx-badge-neutral">未开始</span><span class="rx-badge rx-badge-info">进行中</span><span class="rx-badge rx-badge-success">已完成</span><span class="rx-badge rx-badge-danger">需处理</span></div><p>「需处理」表示有失败任务、授权即将到期等问题，或该步数据暂时读不到（刷新页面即可重试）。</p></article><article class="help-card"><h3>下一步</h3><p>第一张还没完成的步骤会被标为「下一步」，按钮变为蓝色主按钮，点它直接到对应页面。第 7 步「学生测量 / 评课」同时提供学生测量和评课两个入口。上传页顶部也有一条可关闭的「下一步」提示条，内容与首页一致。</p></article><article class="help-card"><h3>待办事项</h3><ul><li>分析失败的任务 →「去处理」</li><li>待复核的测量记录 →「去复核」</li><li>已过期的报告 →「更新报告」</li><li>30 天内到期的资料授权 →「去续期」</li><li>已有复核测量但没有核对过的评课 →「去做评课」</li><li>课程总览已出结论 →「查看课程总览」</li><li>本课纳入学生少于 3 名 →「管理本课检测学生」</li></ul><p>没有待办时显示「暂无待办」。</p></article><article class="help-card"><h3>最近任务</h3><p>列出最近 5 个上传，显示课程、上传时间和处理状态。已处理完成的点「进入结果」，还在处理的点「查看进度」。右上角「全部任务」进入上传页任务记录。</p></article></div></section>
      <section class="help-section" id="find"><h2>找功能：一页搜到所有入口<span class="help-tag new">新</span></h2><p>顶部「找功能」入口（<code>/demo2/find</code>）是给老师的统一导航：不用记菜单，输入「评课 / 测量 / IEP / 报告 / 手动画框」就能直接跳到对应页面。</p><div class="help-card-grid"><article class="help-card"><h3>最近课堂</h3><p>列出最近上传的课堂，直接给「本课工作台」「手动画框」「结果」三个按钮。</p></article><article class="help-card"><h3>常用入口</h3><p>本课工作台、确认学生 / 手动画框、学生测量、评课、长期观测 / IEP、上传、学生名册、使用帮助、学校信息、会员中心。</p></article><article class="help-card"><h3>学生</h3><p>按学生直接进入「测量」「长期观测」「资料 / IEP」，不用先进入学生名册再找。</p></article></div><div class="help-callout"><strong>导航原则</strong>先问“我要做什么”，再给入口；搜索框和最近课堂都在同一页，减少在顶部菜单里反复找。</div></section>
      <section class="help-section" id="lesson"><h2>本课工作台：一节课的 4 步入口<span class="help-tag new">新</span></h2><p>从课堂分析页左侧「本课工作台」进入，地址形如 <code>/demo2/lesson?task_id=…</code>。它把一节课收成 4 张卡片，老师不用在分析、测量、评课、报告之间反复找入口。</p><div class="help-card-grid"><article class="help-card"><h3>1 视频与学生身份</h3><p>显示视频时长、已确认学生数、IEP 完整度（如 <strong>3/3</strong>），按钮「确认学生 / 手动画框」「回看原视频」。</p></article><article class="help-card"><h3>2 学生测量</h3><p>显示本课视频来源记录、已复核、已评分数量；按钮「进入学生测量」。没有视频来源记录时，也会提示现场观察记录在「学生测量」页查看。</p></article><article class="help-card"><h3>3 评课</h3><p>显示本课已保存的评价条数；按钮「去评课 / 查看评价」。评课评的是整节课，不评学生个人。</p></article><article class="help-card"><h3>4 课堂报告</h3><p>显示报告是否可生成，按钮「查看结果与报告」「课程总览」。</p></article></div><div class="help-callout"><strong>学生卡片</strong>工作台底部列出本课学生和 IEP 状态；点学生卡片进入该学生的「长期观测」页。IEP 缺失的学生仍可保存测量草稿，但正式报告会被阻断。</div></section>
      <section class="help-section" id="start"><h2>登录与导航</h2><p>打开网址后在登录页选择「用户登录」，输入学校测试账号和密码；新用户可「手机号注册」。公司人员请选择「管理员登录」。首次进入时按提示到「学校信息」确认城市、区县和学校。</p><div class="help-card-grid"><article class="help-card"><h3>统一的顶部导航</h3><p>所有老师页面使用同一条顶部导航，当前页面下方有蓝色标记；右侧显示登录账号和「退出」。屏幕较窄（手机、平板竖屏）时导航收进右上角「菜单」，点一下展开，按 Esc 或点空白处收起。</p></article><article class="help-card"><h3>学校信息怎么填</h3><p>默认使用「全国学校目录」：可按省 / 市 / 区县逐级筛选，也可以不选地区直接输入校名关键词或拼音首字母（如 tsjy）搜索全国，结果每页 20 条，点选学校后勾选确认并「保存学校信息」。目录里找不到时点「手动填写学校」，选择省市区并填写学校全称，保存后即可使用，同时提交管理员审核。确认学校信息不会让你看到其他学校的数据；已上传任务保留上传时的学校记录。</p></article><article class="help-card"><h3>出错提示</h3><p>保存失败、网络中断或登录过期时，页面顶部会出现中文提示和错误码（如 <code>409 · report_stale</code>）。登录过期时已填写的内容会暂存在本浏览器，重新登录回到本页可以恢复。</p></article><article class="help-card"><h3>退出登录</h3><p>在公共电脑上使用后请点右上角「退出」。改密码后旧登录会失效，需要重新登录。</p></article></div></section>
      <section class="help-section" id="navigation"><h2>页面前进与后退<span class="help-tag new">新</span></h2><p>每个页面左上角 WeGlow 标志右侧都有「← 后退」「前进 →」两个按钮，用于在本窗口看过的页面之间来回查看内容。</p><div class="help-card-grid"><article class="help-card"><h3>怎么用</h3><ul><li>点「后退」回到上一个看过的页面；点「前进」再回到刚才的页面。</li><li>键盘快捷键：Alt+← 后退、Alt+→ 前进（在输入框里打字时不会触发）。</li><li>学生测量、课堂分析、学生资料页里切换的标签也会被记住，后退可以回到上一个标签。</li></ul></article><article class="help-card"><h3>需要注意</h3><ul><li>从书签或其他网站直接打开时没有上一页，「后退」会回到首页（管理员回到后台总览）。</li><li>表单有未保存内容时，离开前会弹出提醒；可以先保存，或确认放弃后再后退。</li><li>手机上按钮只显示箭头，功能相同。</li></ul></article></div></section>
      <section class="help-section" id="school-search"><h2>全国学校搜索与手动填写<span class="help-tag new">新</span></h2><p>顶部「学校信息」进入。学校目录覆盖全国各省、自治区、直辖市，不再只限上海青浦。</p><div class="help-card-grid"><article class="help-card"><h3>从全国学校目录选择</h3><ol><li>依次选择「省 / 自治区 / 直辖市」「市」「区 / 县」。</li><li>在「学校名称筛选」输入校名关键词或拼音首字母（例如：特殊教育、海淀、tsjy），结果较多时用「上一页 / 下一页」翻看。</li><li>点选学校后核对「学校类型」，点「保存学校信息」。</li></ol></article><article class="help-card"><h3>找不到学校时手动填写</h3><ol><li>点「找不到？手动填写学校」。</li><li>填写「学校全称」（例如：某某区特殊教育学校），可补充街道 / 乡镇和详细地址。</li><li>保存后显示「手动填写学校（待审核）」，审核期间可以正常建名册和上传；管理员审核通过后自动归入全国学校目录。</li></ol></article></div><div class="help-callout"><strong>目录暂时打不开？</strong>页面会提示「全国学校目录暂不可用，可手动填写学校」，此时直接手动填写即可，之后可点「重新读取」。城市、区县和学校都确定后，才能建名册和上传视频。</div></section>
      <section class="help-section" id="upload"><h2>上传视频</h2><p>顶部「上传任务」进入。主线只需三件事：填写课程名称（可选）、确认上传通道、把视频拖进虚线框（或点「选择课堂视频」），然后点「确认授权并上传」。</p><div class="help-card-grid"><article class="help-card"><h3>拖拽上传</h3><ol><li>把视频文件直接拖到「把视频拖到这里」虚线框，框会变蓝表示可以松手。</li><li>一次只能上传一个视频；同时拖入多个时只取第一个，并给出提示。</li><li>选好后框下方显示文件名、大小和时长，核对无误再上传。</li><li>浏览器不支持拖拽时会提示，改点「选择课堂视频」即可。</li></ol></article><article class="help-card"><h3>上传与分析进度</h3><p>进度区有三个阶段：「上传视频 → 后台处理 → 学生状态结果」。文件到 100% 后进入后台处理，完成后自动跳到结果页。网络不稳时可点「暂停上传」，恢复后「继续上传」会从已上传的位置接着传。上传期间不要关闭或刷新页面。</p></article><article class="help-card"><h3>按钮为什么是灰的</h3><p>上传按钮旁会写明还差什么，例如「还差一步：请先选择或拖入课堂视频」「本课程 5 个名额已用完」「账号绑定的上传通道已暂停」「学校信息读取失败」。按提示处理后按钮自动变为可点。</p></article><article class="help-card"><h3>更多功能</h3><p>点「更多功能」展开课程批次号、计划关注学生、课程名额、任务筛选和「课堂复核与报告」入口。同一节课的多个视频用同一个批次号；每个课程最多 5 个视频，传错可「取消并释放名额」。</p></article></div><div class="help-table-wrap"><table class="help-table" id="uploadFailureTable"><thead><tr><th>任务记录里显示的失败原因</th><th>该怎么做</th></tr></thead><tbody>
<tr><td>视频文件损坏或没有可识别的画面</td><td>用播放器确认原文件能正常播放，重新导出后再上传。</td></tr>
<tr><td>视频文件不完整 / 校验未通过</td><td>上传过程中断或文件被改动，重新上传完整文件。</td></tr>
<tr><td>视频过长、过大或分辨率过高</td><td>裁剪到 60 分钟以内、压缩到 1 GiB 以内，推荐 720p 或 1080p 的 MP4。</td></tr>
<tr><td>画面方向不受支持 / 时间轴异常</td><td>用剪辑软件转为正常方向，重新导出为 MP4（H.264 / AAC）。</td></tr>
<tr><td>视频分析超时</td><td>稍后在任务记录重试，或把长视频拆成几段上传。</td></tr>
<tr><td>服务器重启导致分析中断 / 分析已取消</td><td>打开该任务点「重新处理」，不需要重新上传。</td></tr>
<tr><td>服务器缺少视频处理组件 / 存储异常</td><td>这是服务器问题，记下任务编号联系项目方，不要反复上传。</td></tr>
</tbody></table></div><div class="help-callout"><strong>视频建议</strong>支持 MP4、MOV、WebM；单节课不超过 60 分钟、单文件不超过 1 GiB，推荐 MP4（H.264 / AAC）、720p 或 1080p。学生正脸可见、光线充足的视频分析效果更好；建议先用一段短视频试跑。</div></section>
      <section class="help-section" id="course-task"><h2>课程任务 Word/PDF 上传与目标确认<span class="help-tag new">新</span></h2><p>在「上传任务」页的「课程任务文件（Word/PDF）」一栏上传本课教学任务或教案。系统自动识别课程目标，老师确认后，本课的课堂评价、学生测量、片段复核和课堂报告都会使用这些目标。</p><div class="help-card-grid"><article class="help-card"><h3>上传与识别</h3><ol><li>点「选择课程任务文件」，支持 PDF、Word（.docx / .doc），单个文件不超过 20 MB。</li><li>识别完成后右侧打开「课程任务目标确认」抽屉，显示课程名称、上课日期和课程任务目标（编号 G-01、G-02…，含通过标准、测量条件、评分维度建议）。</li><li>文件中没有归入目标的段落、表格和字段，全部按原文列在「其他内容」里，不会丢失；可一键「加入为目标」或「加入备注」。</li></ol></article><article class="help-card"><h3>确认与修改</h3><ol><li>逐条核对，可直接修改文字、删除或「新增目标」「新增备注」。目标里不要写学生姓名。</li><li>勾选「我已逐条核对识别结果…」，点「确认并保存课程任务」。</li><li>上传状态显示「已上传课程任务（版本 n）· x 个目标」即为成功。</li><li>需要修改时重新上传文件会生成新版本，旧版本保留；引用旧版本的报告会显示已过期，重新打开报告页即按新版本生成。</li></ol></article></div><div class="help-callout"><strong>确认后会自动打通</strong>课堂评价页自动带入本课目标；学生测量的「目标」可下拉预填；课堂复核页按目标标注相关片段；图文报告新增「本课任务目标与达成情况」。首页如提示「上传课程任务文件」，说明这节课还没有确认的课程任务。</div></section>
      <section class="help-section" id="capture"><h2>录制课堂</h2><p>没有现成视频时，点顶部「课堂录制」直接用电脑摄像头录制。</p><div class="help-card-grid"><article class="help-card"><h3>操作步骤</h3><ol><li>勾选「我已获准录制本次课堂画面与声音」。</li><li>点「检查摄像头与麦克风」，浏览器询问时选择允许。</li><li>点「开始录制」，结束时点「结束录制」。</li><li>回放确认后填写课程信息，勾选确认并「保存到课程」。</li></ol></article><article class="help-card"><h3>注意事项</h3><p>保存后与普通上传一样占用课程名额并自动分析。录制中不要关闭或刷新页面。</p></article></div></section>
      <section class="help-section" id="result"><h2>查看学生状态</h2><p>后台处理完成后自动跳到学生状态结果。结果页按检测到的人物分别整理课堂状态，不把整段视频压成一个分数。</p><div class="help-card-grid"><article class="help-card"><h3>本节课概览与报告</h3><p>上方显示课堂视频、本节课概览和「本节课分析报告」。显示「正在生成报告」时稍等几秒即可。</p></article><article class="help-card"><h3>学生切换与时间轴</h3><p>只列出学生，按画面从左到右编号。点「学生 1 / 学生 2」查看该学生的清晰头像、主要状态和参考分；时间轴每段包含时间、截图、状态和证据，点击跳到对应时刻。</p></article><article class="help-card"><h3>疑似老师与无效人选</h3><p>系统按人脸尺寸、站立高度、走动范围、出现时长和清晰度自动排除疑似老师与无效人选（没有清晰人脸的空白候选），放在下方「已排除人物」折叠区。认为排错时点「恢复为学生」；学生列表里混入老师时点「标记为老师/非学生」，其数据会移出时间轴、测量、评价和报告，已保存的本课归档也会撤销。身份确认页默认隐藏这些候选，可勾选「显示已排除候选」查看。自动筛查只是辅助，需要老师复核，不代表识别准确性已验证。</p></article><article class="help-card"><h3>下载结果</h3><p>页面显示分析完成、任务编号与本次上传一致后，点「下载结果」保存。</p></article><article class="help-card"><h3>结果怎么理解</h3><p>状态是视频中的可见线索；参考分用于课堂回看，不是诊断结论，也不是学校正式成绩。显示「0 已定位学生」说明没有识别到清晰的学生人脸，可检查「已排除人物」或调整拍摄角度。</p></article></div></section>
      <section class="help-section" id="person-filter"><h2>学生人物自动筛查<span class="help-tag new">新</span></h2><p>分析完成后，结果页只把学生列为「人物 1、人物 2…」。疑似老师（人脸明显偏大、站立高度、大范围走动、全程频繁出现）和无效人选（有效人脸帧太少、头像始终模糊、置信度低、人脸过小）会被自动排除，不进入学生时间轴、测量、评价和报告。</p><div class="help-card-grid"><article class="help-card"><h3>查看被排除的人物</h3><p>结果页下方「已排除人物（疑似老师 x / 无效 y）」折叠区列出每个被排除的人物和排除原因，例如「人脸明显大于学生」「头像始终不清晰」。</p></article><article class="help-card"><h3>排错了怎么恢复</h3><ul><li>学生被误排除：在「已排除人物」里点「恢复为学生」，学生列表会重新编号。</li><li>老师被当成学生：在该人物上点「标记为老师/非学生」，确认后其数据移出学生时间轴、测量、评价和报告，已保存的本课归档也会撤销。</li><li>你的修改会一直保留，重新打开结果页也不会被系统覆盖。</li></ul></article></div><div class="help-callout warn"><strong>筛查不是身份识别</strong>系统只根据画面特征做辅助筛选，不判断画面中任何人是谁；学生是谁要由老师在「确认画面中的学生」页对应到名册。</div></section>
      <section class="help-section" id="multi-student"><h2>多学生切换与选择被检测学生<span class="help-tag new">新</span></h2><p>一节课会同时检测画面中的多名学生（建议至少 3 名）。结果页、身份确认页、课堂复核「个体观察」和学生测量页顶部都有同样的「切换学生」头像条：点击头像卡片（或用 ← → 键）切换，时间轴、状态曲线、测量记录和报告段落一起切换；浏览器后退可回到上一名学生，地址里的 person_id / student_id 可以直接分享给同事打开同一名学生。</p><div class="help-card-grid"><article class="help-card"><h3>选择被检测的学生</h3><ol><li>打开结果页，向下找到「本课检测学生」面板，这里列出全部人物候选（含被排除的老师和空白候选）。</li><li>勾选「纳入本课检测」= 该人物进入学生时间轴、测量、评课和报告；取消勾选 = 移出本课，并撤销其视频测量记录（保留版本）和 IEP 课堂引用。</li><li>把老师误当学生时点「标记为老师/非学生」；学生被误排除时点「恢复为学生」。</li><li>再次勾选即可原样恢复，报告会自动重新生成。</li></ol></article><article class="help-card"><h3>少于 3 名学生时</h3><p>页面会提示「本视频仅识别到 N 名学生」并写明原因（只检出几张人脸、排除了几个老师或空白候选）。可以在「本课检测学生」中恢复被排除的人物，或点「手动画框添加学生」到身份确认页补框。首页待办「检测学生不足」会直接带你到这个面板。</p></article><article class="help-card"><h3>头像卡片上的标记</h3><ul><li>已绑定：已在名册中对应到学生，卡片显示姓名。</li><li>未绑定：还没有对应名册学生，显示「学生 1、学生 2…」。</li><li>已排除：疑似老师、空白候选或老师取消纳入的人物。</li></ul></article><article class="help-card"><h3>切换后什么会变</h3><p>头像、主要状态、参考分、时间轴、测量记录和报告段落都换成当前学生；课程级内容（评课、课程总览）不随学生切换。</p></article></div></section>
      <section class="help-section" id="analysis-list"><h2>我的课堂分析列表<span class="help-tag new">新</span></h2><p>打开不带任务编号的「课堂复核与报告」页面时，会先显示「课堂视频列表」：列出当前账号在本学校上传的最近 200 个未取消的课堂视频，方便找回以前的课。</p><div class="help-card-grid"><article class="help-card"><h3>从哪里进入</h3><ul><li>上传页「更多功能」→「课堂复核与报告」。</li><li>某节课的分析页顶部「切换视频」。</li><li>同课多视频汇总、教学支持页的「返回课堂视频 / 返回课堂列表」。</li></ul></article><article class="help-card"><h3>每一行显示什么</h3><p>课程名称和文件名、上传时间、处理状态，以及报告状态：</p><div class="help-badges"><span class="rx-badge rx-badge-neutral">未生成报告</span><span class="rx-badge rx-badge-success">已生成报告</span><span class="rx-badge rx-badge-warning">报告已过期</span><span class="rx-badge rx-badge-info">报告证据待补充</span></div><p>点「查看分析」进入该课的学生状态、片段复核和图文报告。</p></article><article class="help-card"><h3>查找课程</h3><p>在「查找课程或文件」里输入课程名或文件名，列表即时筛选，右侧显示「符合条件 x / y 项」。没有匹配时换个关键词即可。</p></article><article class="help-card"><h3>列表是空的</h3><p>显示「还没有课堂分析」时，说明本账号在本校还没有上传视频，点「去上传课堂视频」开始。报告状态读不到时会有提示，但仍可点「查看分析」进入。</p></article></div></section>
      <section class="help-section" id="archive"><h2>绑定姓名与归档本课表现</h2><p>结果页可以先看分析，再处理归档。选择当前人物后，在「绑定姓名并归档本课表现」区域输入学生姓名；还没有档案时系统会创建一个最小档案。</p><div class="help-card-grid"><article class="help-card"><h3>姓名绑定</h3><ol><li>看人物截图，确认当前人物。</li><li>输入或选择学生姓名。</li><li>点「绑定并保存本课记录」；已绑定的可「更新本课归档」。</li></ol></article><article class="help-card"><h3>本课总结与 IEP 支持摘要（必填）</h3><p>系统带出简短总结，可直接保存或修改。保存本课记录时「最小 IEP 支持摘要」为必填：点「上传 IEP 文件（Word/PDF）」，系统自动筛查长期/短期目标、支持方式、教学策略、注意事项和评估方式，生成带页码的「系统摘要（待确认）」，诊断原文、身份证号、手机号、住址不会进入摘要；逐条勾选保留、删除或修改后点「确认摘要」。文档里没有、但课堂需要的支持写在「人工补充」，会以「教师补充」单独显示。学生已有 IEP 时可选「沿用已有 IEP」或「上传新版本」。保存后 IEP 原件与摘要加密存入该学生的资料库（首次需填写授权依据和有效期），并自动建立本课 IEP 引用。暂时不想建档可点「暂不绑定，先看分析」。</p></article></div></section>
      <section class="help-section" id="condition-confirm"><h2>病况 / 健康与安全要点确认<span class="help-tag new">新</span></h2><p>在结果页「绑定并保存本课记录」里，老师关联 IEP 后，需要先确认一张「病况 / 健康与安全要点」卡片，才能连通档案并生成阶段性测量。当前为教师手动核对，AI 摘要尚未接入。</p><div class="help-card-grid"><article class="help-card"><h3>核对什么</h3><p>只记录会在课堂影响支持与安全的内容：发作/癫痫/急救、用药/过敏/健康限制、情绪/创伤/行为安全、感官/沟通/运动限制；可勾选多项。</p></article><article class="help-card"><h3>没有检测到怎么办</h3><p>在「其他病症 / 重要情况补充」里写 IEP 未覆盖但课堂需要知道的事项；确实没有相关病况时填写“已核对无相关病况”，并勾选确认。</p></article><article class="help-card"><h3>确认之后</h3><p>勾选「我已对照 IEP 原件确认」后，档案才连通，页面出现「进入阶段性测量」。未确认时保存会被拦截。</p></article><article class="help-card"><h3>数据边界</h3><p>病况要点单独加密保存，仅教师/授权临床可见；不进入课堂报告、课程评分或学生四维评分。AI 摘要后续接入时仍需逐条教师确认。</p></article></div><div class="help-callout"><strong>顺序</strong>先选/上传 IEP → 再确认病况/健康要点 → 确认档案连通 → 进入阶段性测量。不要跳过确认直接做正式测量或报告。</div></section>
      <section class="help-section" id="long-term"><h2>IEP 强制与长期观测<span class="help-tag new">新</span></h2><p>从学生测量总览的「长期观测 / IEP」进入，地址形如 <code>/demo2/long-term?student_id=…</code>。这个页面把一名学生的课程、IEP 和测量记录放在同一条时间轴上，用来看长期变化，而不是单节课。</p><div class="help-card-grid"><article class="help-card"><h3>IEP 强制校验</h3><p>没有当前有效 IEP 的学生：</p><ul><li>仍可保存测量草稿；</li><li>「单次报告」Tab 会显示阻断提示，不能下载正式报告；</li><li>报告下载接口返回 <code>iep_required</code>，页面提示去「学生资料 / 授权」上传 IEP。</li></ul><p>有 IEP 后，报告和长期观测才能使用当前目标与支持条件。</p></article><article class="help-card"><h3>长期时间轴</h3><p>顶部显示课程数、测量记录数、已复核数；下方按上课日期列出课程、目标、四维分数、复核状态和来源（现场观察 / 视频复核）。点「管理 IEP 与授权」可查看或更新 IEP。</p></article><article class="help-card"><h3>数据边界</h3><p>长期观测只汇总教师复核记录，不按视频出现次数推断能力，不做跨学生比较，不替代 IEP 决策或专业评估。IEP 更新保留历史版本，报告引用当时版本。</p></article></div><div class="help-callout"><strong>和报告的关系</strong>没有当前 IEP → 不能生成正式报告；有 IEP → 报告与长期时间轴都可引用当前目标和支持条件。测量草稿不会被删除。</div></section>
      <section class="help-section" id="roster"><h2>学生名册与资料授权</h2><p>需要长期跟踪某位学生、或希望报告引用 IEP 时使用。所有资料只在本校账号内可见。</p><div class="help-card-grid"><article class="help-card"><h3>学生名册</h3><p>「新增本校学生」填写姓名（必填）、校内编号、班级和备注，点「创建学生」。可按姓名、编号或班级查找。每位学生都有「资料与授权」和「公司留存摘要」入口。</p></article><article class="help-card"><h3>登记授权（第一步）</h3><ol><li>核对学生信息。</li><li>填写授权依据（授权记录编号、签署日期、保管部门）。</li><li>选择保存范围：仅摘要，或摘要及原件。</li><li>填写有效期（内测最多 60 天），勾选确认后「登记授权」。</li></ol></article><article class="help-card"><h3>新增资料（第二步）</h3><p>有效授权登记后才能新增资料。类型可选 IEP、专业评估、五领域评估、安全与支持资料；来源不超过 200 字，保存期限不能晚于授权截止日期。字段有误时会在该字段下给出中文提示并自动定位。每次更新新建版本，不覆盖旧版本。</p></article><article class="help-card"><h3>撤回、到期与多份 IEP</h3><p>撤回授权、到期或删除资料后，资料不再参与分析，相关报告标为「已过期」。同一学生同时有多份有效 IEP 时系统不会自动挑选，请保留一份当前有效版本。</p></article></div></section>
      <section class="help-section" id="iep-summary"><h2>IEP 文件上传与支持摘要确认<span class="help-tag new">新</span></h2><p>「最小 IEP 支持摘要」现在是<strong>必填</strong>项：在结果页绑定学生姓名、或在学生「资料与授权」页新增 IEP 时，都需要上传 IEP 文件并确认摘要后才能保存。</p><div class="help-card-grid"><article class="help-card"><h3>上传并生成摘要</h3><ol><li>先确认学生有有效的资料授权（填写授权依据和有效期，最长 60 天）。</li><li>点「上传 IEP 文件（Word/PDF）」。系统按「现有能力水平、长期目标、短期目标、支持需求、教学策略、评估方式、注意事项」等类别自动筛查出摘要条目，并标注所在页码。</li><li>姓名、出生日期、诊断原文、联系方式等身份信息不会进入摘要。</li></ol></article><article class="help-card"><h3>确认与人工补充</h3><ol><li>逐条核对：不需要的条目取消勾选，文字有误点「修改摘要」直接改。</li><li>文档里没有、但课堂需要的支持信息，写在「人工补充（文档中没有、但课堂需要的支持信息）」栏，最多 1000 字。</li><li>点「确认摘要」，状态变为已确认后再保存；原件按授权范围加密保存。</li></ol></article></div><div class="help-callout"><strong>确认后会自动打通</strong>摘要会作为该学生的 IEP 版本，用于本课 IEP 关联、学生测量的 IEP 要点、双轨评价和课堂报告。首页提示「补充 IEP 支持摘要」时，表示有已在课堂中确认的学生还没有有效 IEP 支持摘要。</div></section>
      <section class="help-section" id="identity"><h2>确认画面中的学生</h2><p>从首页第 5 步或复核页「确认学生身份」进入。左侧是课堂采样帧，右侧「匹配学生姓名」有一个 3 步引导，当前要做的那一步会高亮，下方写明还缺什么。</p><div class="help-card-grid"><article class="help-card"><h3>3 步完成确认</h3><ol><li><strong>在画面中点选或框选人物</strong>：点击虚线候选框；没有候选框时点「手动画框」，在画面中按住鼠标拖出一个框。</li><li><strong>选择学生姓名</strong>：在「学生姓名」里选择；名册里没有可点「新增本校学生」。教师或身份未知的人在「高级」里改角色，不需要选姓名。</li><li><strong>点击确认</strong>：前两步完成后「确认姓名」变为可点。</li></ol></article><article class="help-card"><h3>确认之后</h3><p>弹出「已确认：某某（第 x 帧）」并自动跳到下一张还没确认的帧；提示条上可一键回到刚才的帧，继续确认同一画面里的其他人。已确认的人显示实线框。</p></article><article class="help-card"><h3>看不清人物</h3><p>键盘 ← → 切换采样帧，「+ / −」放大缩小，「0」恢复 100%；也可点「原片彩色高清参考」查看原图，或展开「按秒数定位」跳到指定时间。</p></article><article class="help-card"><h3>为什么不能确认</h3><p>旧任务未记录学校时，需要先「确认此视频属于上述学校」；编辑权限未核验、采样帧未就绪时，引导里会直接写明原因。所选画面时刻要落在后续要测量的片段内。</p></article></div></section>
      <section class="help-section" id="manual-seats"><h2>手动画框与按座位重新分析<span class="help-tag new">新</span></h2><p>当自动找人把成人排进学生、或前排侧脸学生没被稳定跟到时，老师可以自己框定座位，再让系统只按这 3 个座位重新分析。入口：「确认画面中的学生」页。</p><div class="help-card-grid"><article class="help-card"><h3>画框并确认</h3><ol><li>在 05:00 等能看清三名学生的采样帧，点「手动画框」。</li><li>用鼠标拖出左 / 中 / 右 3 个框；画面里的成人不要框入。</li><li>依次选择 3 名学生姓名，点「确认姓名」；三个框变绿表示当前版本已确认。</li></ol></article><article class="help-card"><h3>按座位重新分析</h3><p>3 名当前版本学生都确认后，页面出现「按这 3 个座位重新分析」。点击并确认后：</p><ul><li>后台把 3 个座位框写入本课任务，重新排队处理；</li><li>追踪器只以这 3 个框为固定座位种子，不再全画面找人；</li><li>完成后结果页只保留这 3 名学生，成人不再进入学生列表。</li></ul></article><article class="help-card"><h3>重新分析之后</h3><p>重新分析会改变采样版本，旧的身份绑定不再“当前有效”，结果页先显示 3 名匿名学生；老师可重新绑定姓名，或在新版本上再确认一次。结果页若仍显示旧自动结果，请刷新页面或等待处理完成。</p></article><article class="help-card"><h3>边界</h3><p>手动画框是教师确认的座位区域，不是人脸身份识别；框错、遮挡或学生换座会导致状态线索偏差。重新分析只改变“跟踪哪 3 个座位”，不改变测量分数和评分标准。</p></article></div></section>
      <section class="help-section" id="review"><h2>课堂复核与图文报告</h2><p>在我的课堂分析列表点「查看分析」进入。顶部可「切换视频」，并提供「确认学生身份、课程关联资料、同课多视频汇总、教学支持与上传测试、视频证据详情」等入口。</p><div class="help-card-grid"><article class="help-card"><h3>视频适用性（必须先做）</h3><p>首次进入提示「视频适用性待确认」：选择视频内容类型（特教课堂、普通学校课堂、非课堂、无法判断、证据不足），核对教学目标后「保存适用性确认」。未确认时不能保存已复核或带分数的观察。</p></article><article class="help-card"><h3>四个标签页</h3><ul><li>群像概览：全班整体情况。</li><li>个体观察：单个学生的目标与支持。</li><li>片段复核：设定开始 / 结束时间回看片段，新增或编辑目标观察。</li><li>图文报告：自动生成本课报告。</li></ul></article><article class="help-card"><h3>图文报告下载</h3><p>点「下载 Word 报告」或「下载 PDF 报告」得到排版好的中文文字报告（封面、目录、课程总览与结论、评课、每名学生一节、本课任务目标、「评分标准细则」附录），文件名为「WeGlow_课堂报告_课程_日期」。网页存档 HTML、报告文本 MD、结构化记录 JSON 收在「数据导出（技术人员用）」中，不适合直接阅读。学生测量页「单次报告」同样可「下载 Word / 下载 PDF」。复核内容变化后点「重新生成报告」。</p></article><article class="help-card"><h3>其他入口</h3><p>「课程关联资料」为已确认身份的学生勾选 1–10 个资料版本；「同课多视频汇总」合并同批次视频并逐个学生核准结论；「视频证据详情」按时间切片回看画面和声音，可「重新处理」。</p></article></div></section>
      <section class="help-section" id="measurement-links"><h2>测量结果在哪里看<span class="help-tag new">新</span></h2><p>绑定学生并保存本课记录后，系统会按本课课程任务目标自动生成「视频来源测量记录（待教师复核）」。同一条记录在下面各处显示，修改一处，其他位置同步更新。</p><div class="help-table-wrap"><table class="help-table"><thead><tr><th>位置</th><th>能看到什么</th></tr></thead><tbody><tr><td>学生状态结果页</td><td>「测量结果录入核对」逐个学生核对课程任务目标、IEP 确认要点和视频关键指标是否已录入；缺失时点「一键补录」，或「去学生测量页复核」。</td></tr><tr><td>课堂复核 · 群像概览</td><td>全班已记录测量的综合分条形图。</td></tr><tr><td>课堂复核 · 个体观察</td><td>按学生查看每个目标的测量、复核状态和视频指标。</td></tr><tr><td>课堂复核 · 片段复核</td><td>证据片段列表，点片段跳到视频对应时刻；可直接编辑测量并保存。</td></tr><tr><td>课堂复核 · 图文报告</td><td>「已记录目标测量 · 10分制」和「本课任务目标与达成情况」。</td></tr><tr><td>学生测量页</td><td>总览、纵向趋势和单次报告里显示来源课程任务（版本）、课堂任务、上课日期和学习目标。</td></tr></tbody></table></div><div class="help-callout"><strong>记得复核</strong>视频生成的测量是建议分，需要老师在学生测量页勾选「教师已完成复核」后才计入趋势；首页会提示「复核本课测量（n 条）」。</div></section>
      <section class="help-section" id="evaluation"><h2>评课（课堂双轨评价）</h2><p>顶部「评课」进入；从首页或「我的课堂分析」列表点「评课」会直接绑定那一节课（视频任务 + 课程）。评价的是这节课的教学质量，不给学生个人能力打分；同一节课同时记录「学校标准」评分和「系统增强」评分，并说明两者差异。</p><div class="help-card-grid"><article class="help-card"><h3>新建评价：3 步分步表单</h3><ol><li><strong>课程信息与口径</strong>：课堂编号、上课日期、课程名称，以及学科、评价模板、评价方案、本课目标与分层支持约定（不要写学生姓名）。</li><li><strong>逐项评分</strong>：每个项目一张卡片，填学校分、证据摘要、改分理由和改进建议；点「评分参考」看各分值含义。没评的项目留空显示「未评」，不按 0 分计算。</li><li><strong>核对并保存</strong>：点「预览评分」看结果；预览页可直接点「保存记录」，不用再返回修改。勾选核对声明后保存。</li></ol></article><article class="help-card"><h3>在步骤之间切换</h3><p>顶部步骤条显示当前在第几步。本步必填项没填完时不能进入下一步，字段下方有红字提示；点步骤条可回到前面修改，已填内容不会丢失。右侧「评分小结」实时显示已评项数和预估分数。</p></article><article class="help-card"><h3>查看结果</h3><p>摘要条显示复核状态、学校折算分、系统增强分和总分差。下方「学校标准 / 系统增强 / 双轨对照 / 文献依据」四个视图；逐项分差图里蓝色「+」表示增强分更高，橙色「−」表示学校分更高。可「导出 JSON」或「打印」，错误记录可「撤销此记录」。</p></article><article class="help-card"><h3>系统建议分</h3><p>从某节课进入时，第 2 步每个条目下方显示「系统建议分」：目标适配看课程任务目标，全体参与看学生覆盖率，目标落实看各学生测量综合分，响应调节要视频片段和教师观察记录同时具备。点「查看依据」看数据来源、公式和引用的视频片段；没有数据的条目显示「证据不足，待教师评分」，系统不会编造分数。点「采纳建议分」直接采用；改成别的分数时必须填写修改理由。保存后结果页显示四个类目得分、学校 vs 系统条形图、类目分差、总分与等级。课程任务出新版本或本课测量变化后，已保存的评课会提示「依据数据已变化，建议重新核对」，原分数不会被自动改写。</p></article><article class="help-card"><h3>两个常见卡点</h3><p>改动任何字段后「我已逐项核对证据与情境…」勾选会自动取消，请改完后重新勾选，否则只保存为草稿、增强修正不计分。本课目标里出现名册学生姓名会被拒绝并标红，请改用「A组 / 需视觉提示的学生」等描述。</p></article></div></section>
      <section class="help-section" id="course-evaluation"><h2>评课（学校标准 4 类 10 项）<span class="help-tag new">新</span></h2><p>评课评的是这节课本身（教学质量），不是给学生个人打分。从顶部「评课」、首页待办「去做评课」或我的课堂分析列表的「评课」进入，会自动绑定那一节课。</p><div class="help-table-wrap"><table class="help-table"><thead><tr><th>类目</th><th>包含的条目</th><th>系统建议分看什么</th></tr></thead><tbody>
<tr><td>目标适配与分层要求</td><td>目标符合学生实际、分层要求清楚</td><td>本课已确认的课程任务目标（数量、是否有通过标准）。</td></tr>
<tr><td>内容设计与教学组织</td><td>联系生活经验、内容正确与容量适当、环节安排</td><td>生活经验与内容正确性由老师判断，系统不推算；环节安排参考课程目标与测量。</td></tr>
<tr><td>过程支持与目标达成</td><td>学生参与、目标落实、全体覆盖</td><td>视频片段中的稳定参与、各学生测量综合分、本课纳入学生的覆盖率。</td></tr>
<tr><td>教师表达与响应调节</td><td>语言示范与板书、响应调节</td><td>语言示范由老师判断；响应调节要视频片段（回应偏低后恢复参与）和教师观察记录同时具备。</td></tr>
</tbody></table></div><div class="help-card-grid"><article class="help-card"><h3>怎么做</h3><ol><li>第 2 步每个条目下方显示「系统建议分」，点「查看依据」看数据来源、公式和引用的视频片段。</li><li>认可就点「采纳建议分」；改成别的分数时必须填写修改理由。</li><li>没有数据的条目显示「证据不足，待教师评分」，系统不会编造分数，请老师按「评分参考」打分。</li><li>第 3 步勾选「我已逐项核对证据与情境…」后保存，状态才是「已核对」。</li></ol></article><article class="help-card"><h3>保存之后</h3><p>结果页显示 4 个类目得分、学校 vs 系统条形图、类目分差、总分与等级。只有「已核对」的评课才会进入课程总览的结论；课程任务出新版本或本课测量变化后，评价会提示「依据数据已变化，建议重新核对」，原分数不会被自动改写。</p></article></div><div class="help-callout"><strong>首页提醒</strong>某节课已有复核过的学生测量、但还没有核对过的评课时，首页待办会出现「做评课」，点「去做评课」直接进入该课。</div></section>
      <section class="help-section" id="course-overview"><h2>课程总览与结论<span class="help-tag new">新</span></h2><p>课程总览（系统大纲）把一节课的「每个学生的评价」和「整体课程指标」放在同一页，用来判断这节课上得好不好。从课堂复核页的「课程总览」标签（或其中的「单独打开课程总览」）、或首页待办「查看课程总览」进入（地址形如 <code>/demo2/course-overview?task_id=…</code>）。</p><div class="help-card-grid"><article class="help-card"><h3>页面上有什么</h3><ul><li>结论卡：试行等级、结论分、主要优点和主要待改进各最多 3 条。</li><li>整体课程指标：评课 4 个类目得分、学生覆盖率、各课程目标的达成情况。</li><li>学生评价矩阵：每名纳入学生的状态时间条、每个目标的已复核测量分和目标达成度。</li></ul></article><article class="help-card"><h3>什么时候才有结论</h3><p>需要同时具备：本课学生测量已复核且证据充分、评课已核对且依据没有变化。缺哪一项，结论卡会写「暂无结论，还缺：…」并给出跳转按钮，补齐后自动生成。数据不完整时不会给等级。</p></article></div><div class="help-callout warn"><strong>结论是试行口径</strong>只汇总本课老师已复核的测量和已核对的评课，用于课堂教学复盘，不构成教师绩效结论或学生能力定级。公司管理员只能看报告快照中的总览，学生显示为「学生1 / 学生2…」，不含 IEP 内容。</div></section>
      <section class="help-section" id="measurement"><h2>学生测量与趋势</h2><p>顶部「学生测量」进入，按学习目标长期记录学生表现。页面有「总览、记录测量、纵向趋势、单次报告、评分标准」五个视图。</p><p><strong>课堂视频自动生成的测量记录：</strong>在结果页「绑定并保存本课记录」后，系统按本课已确认的每个课程任务目标为该学生生成一条「课堂视频（系统生成）」记录，带入上课日期、课节、目标编号、通过标准、测量条件、IEP 支持条件、视频指标（稳定参与/回应偏低/离开或不可见/未观察片段数与时长占比、参与得分参考）和可点击跳转的证据片段。系统给出的四维分标注「建议·待复核」，不进入趋势得分线和报告综合分；在总览点「补全并复核」，可「采用系统建议分」后逐项核对、勾选「教师已完成复核」再保存（需先在分析页确认视频适用性）。结果页「测量结果录入核对」会列出尚未录入的课程目标、IEP 要点、视频指标或报告章节，点「一键补录」即可恢复。</p><div class="help-card-grid"><article class="help-card"><h3>新增测量记录</h3><ol><li>课堂信息：上课日期、课节编号、数据来源；视频复核来源需填任务编号和片段起止秒数。</li><li>目标与条件：学习目标编号、测量条件和通过标准。</li><li>四维评分：输入、拖动滑块或点「− / +」；没观察到的维度点「清空」，显示灰色「未观察」。</li><li>观察次数与复核：填写观察记录与证据摘要，勾选「教师已完成复核」后保存。</li></ol></article><article class="help-card"><h3>四维评分</h3><p>准确性 35%、独立性 30%、一致性 20%、泛化性 15%，每项 0–10 分。没观察到的维度留空，不要填 0；留空的记录标「证据不足」、不出综合分。</p></article><article class="help-card"><h3>趋势图什么时候显示</h3><ul><li>同一学生、同一学习目标、同一测量条件和通过标准下，至少有 <strong>2 次已复核且有综合得分</strong>的记录才画趋势图。</li><li>不够时显示空状态「至少需要 2 次已复核记录才能看趋势」，并写明目前有几次，可直接点「+ 新增测量记录」。</li><li>切换目标后，按该目标单独计数。</li></ul></article><article class="help-card"><h3>怎么读趋势图</h3><p>可切换逐课、周、月或 60 天滚动。实心点是已复核得分；空心点表示该次未复核或证据不足（不按 0 分）；虚线连接跨越空缺的两次得分。图下「无障碍数据表格」可看具体数值。「单次报告」可「打印 / PDF」或「下载 HTML」。</p></article></div></section>
      <section class="help-section" id="scoring-basis"><h2>评分标准细则与查看依据<span class="help-tag new">新</span></h2><p>每一个系统分数都有依据可查。学生测量页的「评分标准」视图列出全部细则；测量记录、单次报告和评课的每个分数旁都有「查看依据」按钮，打开右侧「评分依据」抽屉。</p><div class="help-card-grid"><article class="help-card"><h3>学生测量的分数怎么来</h3><ul><li>四个维度：准确性 35%、独立性 30%、一致性 20%、泛化性 15%，每项 0–10 分。</li><li>综合分 = 各维度分 × 权重后相加；没观察到的维度留空，不按 0 分计算，留空时记录标「证据不足」、不出综合分。</li><li>维度分依据观察次数、正确次数和提示层级（独立完成、口头提示、示范、肢体辅助等）对照细则锚点得出。</li></ul></article><article class="help-card"><h3>「查看依据」里能看到什么</h3><ul><li>代入真实数值的公式和计算结果。</li><li>命中的细则锚点（例如「观察 5 次中 4 次正确、口头提示」对应几分）。</li><li>引用的证据：视频时间点可点击跳到视频对应时刻，以及测量记录、课程任务目标。</li><li>没有给分时写明原因，例如观察次数不足或缺少证据。</li></ul></article><article class="help-card"><h3>评课的依据</h3><p>评课每个条目的「系统建议分」同样可点「查看依据」：显示数据来源（课程任务目标、学生覆盖率、测量综合分、视频片段、教师观察记录）、代入数值和命中锚点。只能由老师判断的条目会直接写明「需要教师判断」。</p></article><article class="help-card"><h3>报告里的评分标准</h3><p>下载的 Word / PDF 报告末尾附「评分标准细则」，列出本报告用到的量表版本和细则，打印存档时也能看到评分依据。</p></article></div></section>
      <section class="help-section" id="report-word-pdf"><h2>下载 Word/PDF 报告<span class="help-tag new">新</span></h2><p>课堂报告和学生测量单次报告都可以直接下载为可阅读的中文文字报告，不再是代码格式。</p><div class="help-card-grid"><article class="help-card"><h3>课堂报告</h3><ol><li>打开该课的「课堂复核与报告」页，切到「图文报告」标签。</li><li>点「下载 Word 报告」（.docx，可继续编辑）或「下载 PDF 报告」（适合打印与存档）。</li><li>报告包含封面、目录、课程总览与结论、评课、每名学生一节、本课任务目标与达成情况、「评分标准细则」附录；文件名为「WeGlow_课堂报告_课程_日期」。</li></ol></article><article class="help-card"><h3>学生测量单次报告</h3><p>学生测量页「单次报告」视图同样有「下载 Word」「下载 PDF」，内容是该学生本次测量的目标、四维分数、依据与教师观察。</p></article><article class="help-card"><h3>下载不了怎么办</h3><ul><li>提示「报告已过期」（409 · report_stale）：评分或资料变化了，点「重新生成报告」后再下载。</li><li>HTML / MD / JSON 收在「数据导出（技术人员用）」里，是给技术人员核对用的，老师一般不需要。</li></ul></article><article class="help-card"><h3>管理员下载</h3><p>公司管理员在后台任务查询中也可下载 Word / PDF，报告里不含 IEP 内容，学生显示为「学生1 / 学生2…」。</p></article></div></section>
      <section class="help-section" id="safety"><h2>安全事件核查</h2><p>从课堂评价页顶部「安全核查」进入，记录课堂视频里与安全相关的客观观察，由指定核查人人工给出结论。</p><div class="help-card-grid"><article class="help-card"><h3>记录观察</h3><ol><li>选择课堂视频，用「当前位置设为开始 / 结束」定位时间段。</li><li>填写观察到的具体情况和现场已采取的措施。</li><li>点「保存为待核查」。</li></ol></article><article class="help-card"><h3>核查流程</h3><p>指定同校账号为核查人（需填写授权依据），核查人记录「已核实 / 已排除 / 无法判断」和处理依据，所有处理记录都会保留。</p></article></div><div class="help-callout warn"><strong>重要</strong>现场存在即时危险时，请按学校安全流程立即处理，不要等待平台核查。本页不会自动认定伤害，也不会自动扣分。</div></section>
      <section class="help-section" id="membership"><h2>会员中心</h2><p>顶部「会员中心」查看会员状态、有效期、服务套餐和订单记录。内测阶段在线支付尚未开通，按钮显示「支付暂未开通」，不会产生任何扣费；开通事宜请联系项目方。</p></section>
      <section class="help-section" id="admin"><h2>公司后台<span class="help-tag admin">管理员</span></h2><p>在登录页选择「管理员登录」进入。顶部导航为「总览、任务查询、上传通道、学生资料运行状态、测量记录汇总、会员与订单」。后台只用于运营查询，不能修改学校的课堂数据。</p><div class="help-card-grid"><article class="help-card"><h3>总览</h3><p>显示账号与通道状态、账号所属学校、名额使用、任务状态、保存与到期提醒和近期上传。指标卡显示「较上次刷新」的变化；点「刷新数据」后显示「x 秒前已刷新」。</p></article><article class="help-card"><h3>任务查询</h3><ol><li>在「关键词」输入任务编号、课程或账号（可留空）。</li><li>在「处理状态」选择等待处理、后台处理中、证据已就绪、已完成、处理失败等。</li><li>点「查询任务」；不填条件即查询全部任务。</li></ol><p>结果列出课程名称、学校 / 通道、上传时间、状态、报告状态，用 ← → 翻页；每行可「查看报告」「下载报告」「查看视频」「下载视频」。</p></article><article class="help-card"><h3>上传通道与设置抽屉</h3><p>「上传通道」页顶部三张指标卡显示通道总数、开放上传和已暂停数量。列表中点「设置」，右侧滑出「通道设置」抽屉：</p><ul><li>通道名称、负责人（留空显示「未设置」）。</li><li>开放状态：暂停只停止新建上传，不会把账号换到其他通道。</li><li>每课程上传名额：只能填 3~5。</li></ul><p>点「保存设置」后会重新读取服务器确认；若他人同时修改，会显示「重新核对配置」对比两边的值，核对后再保存。有未保存修改时切换通道会先询问。</p></article><article class="help-card"><h3>报告、资料与测量汇总</h3><p>管理员看到的报告不包含 IEP 内容，学生显示为「学生1 / 学生2…」，可下载 Word / PDF 文字报告，MD / JSON 收在「数据导出」中。「学生资料运行状态」按资料数量、授权状态、存储与清理分组计数；「测量记录汇总」显示有效、已复核、待复核和 30 天内到期数量。「学生档案摘要库」从课程报告卡片头部进入。</p></article></div><div class="help-callout"><strong>访问边界</strong>管理员从「课堂分析」入口直接进入时只会看到「请从任务记录进入」的引导，不读取课堂数据；需要查看某个任务时，请从任务查询结果进入。管理员不能读取教师的课堂复核工作区。</div></section>
      <section class="help-section" id="privacy"><h2>数据与隐私</h2><div class="help-card-grid"><article class="help-card"><h3>数据只在本校可见</h3><p>学生、资料、任务和报告都按学校和账号隔离，访问其他学校的数据会被拒绝。</p></article><article class="help-card"><h3>不要上传多余敏感信息</h3><p>不要在课程名称、备注、评价目标里写学生姓名或诊断原文；IEP 只填本课需要的支持方式。</p></article><article class="help-card"><h3>课程任务与 IEP 文件</h3><p>上传的 Word/PDF 原件和识别结果加密保存；未确认的识别结果 24 小时后自动清除。自动摘要只是建议，必须由老师确认后才使用。</p></article><article class="help-card"><h3>人物筛查不识别身份</h3><p>自动排除疑似老师和无效人选只看画面特征，不判断任何人是谁，也不用于考勤或评价老师。</p></article><article class="help-card"><h3>授权有期限</h3><p>资料授权和摘要授权到期、撤回或删除后，资料立即停止使用，相关报告标为过期。</p></article><article class="help-card"><h3>结果的定位</h3><p>状态线索、参考分和评价结果用于课堂回看与教学改进，不替代专业诊断、IEP 决策或学校正式评价。</p></article></div><p style="margin-top:14px">完整说明见 <a href="/demo2/privacy">数据安全与隐私说明</a>。</p></section>
      <section class="help-section" id="faq"><h2>常见问题</h2><div class="help-faq">
<details id="faqBackForward"><summary>页面左上角的「后退」「前进」怎么用？</summary><p>每个页面标志右侧都有「← 后退」「前进 →」，用于在本窗口看过的页面之间来回查看，也可以按键盘 Alt+← / Alt+→（在输入框里打字时不会触发）。</p><ul><li>学生测量、课堂分析、学生资料页里切换的标签也会被记住，后退可以回到上一个标签。</li><li>没有上一页时（比如从收藏夹直接打开某页），「后退」显示为虚线框，点击回到首页；已在首页时显示「已是第一页」。</li><li>表单里有未保存的内容时，点后退 / 前进会先询问「有未保存内容，确定离开？」，选「留在本页」内容不会丢。</li></ul></details>
<details id="faqTrend"><summary>为什么趋势图不显示？</summary><p>趋势图需要同一学生、同一学习目标、同一测量条件和通过标准下至少 2 次「已复核且有综合得分」的记录。常见原因：</p><ul><li>只记录了 1 次，或其他记录没勾选「教师已完成复核」。</li><li>某次有维度留空，被标为「证据不足」，不出综合分，不计入次数。</li><li>两次记录的目标编号、测量条件或通过标准写法不一致，被当成两个不同的目标。</li></ul><p>空状态会写明当前有几次，补齐后趋势图自动出现。</p></details>
<details id="faqStaleReport"><summary>报告为什么显示「已过期」？</summary><p>报告生成后，它所依据的数据发生了变化：评分或复核内容被修改、引用的 IEP 资料授权被撤回 / 到期 / 删除，或资料出了新版本。过期报告不能下载（会提示 409 · report_stale）。重新打开该课的「图文报告」标签，或点「重新生成报告」，系统会按最新数据重新生成，报告编号不变。首页「待办事项」也会列出过期报告，点「更新报告」即可。</p></details>
<details id="faqUploadFailed"><summary>上传失败怎么办？</summary><p>先看失败发生在哪个阶段：</p><ul><li><strong>上传中断</strong>（网络问题）：点「继续上传」，会从已上传的位置接着传；页面已关闭时重新选择同一文件即可续传。</li><li><strong>后台分析失败</strong>：任务记录里会用红色「!」写明原因，按 <a href="#upload">上传视频</a> 章节的失败原因表处理；「中断 / 已取消」可直接「重新处理」。</li><li><strong>按钮不能点</strong>：按钮旁会写明原因，如名额已满、通道已暂停、学校信息未读取。</li></ul><p>仍无法解决时记下任务编号和页面提示联系项目方，不要反复上传同一个视频。</p></details>
<details id="faqScanned"><summary>上传的 PDF 是扫描件，系统识别不出文字怎么办？</summary><p>扫描件或图片型 PDF 里没有文字层。服务器启用了文字识别（OCR）时会自动识别（最多 40 页）；识别不到或未启用时，页面会提示「文件中没有可识别的文字（可能是扫描件或图片）」或「服务器未启用文字识别（OCR）」。处理方法：</p><ul><li>最好用原始 Word 文件或从 Word「另存为 PDF」的文件重新上传。</li><li>课程任务：在「课程任务目标确认」抽屉里点「新增目标」手工录入，再确认保存。</li><li>IEP：在「人工补充」栏录入本课需要的支持信息，再点「确认摘要」。</li><li>只有部分页识别不到时，会提示是第几页，请对照原件补充这些页的内容。</li><li>加密的 PDF 请先去掉密码；旧版 .doc 读取失败时请另存为 .docx 或 PDF。</li></ul></details>
<details id="faqWrongRecognition"><summary>系统识别错了，如何修改？</summary><ul><li><strong>课程任务目标识别错</strong>：确认前在抽屉里直接改文字、删除或新增；已确认后重新上传文件生成新版本，旧报告会标为过期并按新版本重新生成。</li><li><strong>IEP 摘要识别错</strong>：点「修改摘要」改文字，取消勾选不需要的条目，缺的内容写进「人工补充」；已保存的 IEP 可在学生「资料与授权」页上传新版本。</li><li><strong>学生被当成老师 / 老师被当成学生</strong>：在结果页「已排除人物」里点「恢复为学生」，或在人物上点「标记为老师/非学生」。</li><li><strong>学校识别错</strong>：到「学校信息」重新搜索选择或手动填写；已有任务保留上传时的学校快照。</li><li><strong>测量建议分不对</strong>：在学生测量页编辑该记录、修改分数和证据后勾选复核并保存，报告会自动更新。</li></ul></details>
<details id="faqFewStudents"><summary>为什么只识别到一名学生？</summary><p>常见原因有三个：</p><ul><li>画面里其他学生的人脸太小、太暗或一直侧脸，被当成无效候选排除了。</li><li>老师取消了某些人物的「纳入本课检测」，或把学生误标为老师。</li><li>这是旧版本分析的结果，后台正在按新规则重新计算（稍后刷新）。</li></ul><p>处理方法：打开结果页的「本课检测学生」面板，勾选被排除的人物「纳入本课检测」或点「恢复为学生」；仍然找不到时点「手动画框添加学生」。详见 <a href="#multi-student">多学生切换与选择被检测学生</a>。拍摄时让镜头覆盖全部学生的正脸，效果更好。</p></details>
<details id="faqScoreHow"><summary>分数是怎么算出来的？</summary><p>学生测量的综合分 = 准确性 × 35% + 独立性 × 30% + 一致性 × 20% + 泛化性 × 15%，每个维度按观察次数、正确次数和提示层级对照评分细则得出；没观察到的维度不按 0 分计算。评课的系统建议分按课程任务目标、学生覆盖率、测量综合分、视频片段和教师观察记录推算，数据不足时显示「证据不足，待教师评分」。任何分数旁点「查看依据」都能看到代入数值的公式、命中的细则和引用的证据。详见 <a href="#scoring-basis">评分标准细则与查看依据</a>。</p></details>
<details id="faqCourseGrade"><summary>课程等级怎么判定？</summary><p>课程总览的结论分 = 评课总分 × 60% + 学生目标达成度均值 × 40%（均为百分制）。等级（试行）：≥ 85 优秀，70 ~ 84.9 良好，60 ~ 69.9 合格，&lt; 60 待改进。只有评课已核对、学生测量已复核且证据充分时才给出等级，缺数据时只列出还缺的步骤。等级用于课堂教学复盘，不是教师绩效结论。详见 <a href="#course-overview">课程总览与结论</a>。</p></details>
<details><summary>上传到 100% 后为什么还要等？</summary><p>100% 表示文件传输完成，服务器还需要读取视频、抽取画面并生成每个人物的状态时间片，完成后才会进入结果页。</p></details>
<details><summary>结果页显示「0 已定位人物」怎么办？</summary><p>画面中没有识别到清晰的人脸。请换一段学生正脸可见、光线充足、镜头不过远的视频再试。</p></details>
<details><summary>提示名额已满，不能再上传？</summary><p>每个课程最多 5 个视频（由管理员设为 3~5）。对不需要的任务点「取消并释放名额」，或换一个课程批次号上传。</p></details>
<details><summary>上传通道显示「已暂停」？</summary><p>通道由公司后台统一管理，暂停时不能新建上传，也不会自动换成其他通道。请联系项目方重新开放。</p></details>
<details><summary>保存测量或片段观察时提示需要先确认适用性？</summary><p>先在「课堂复核与报告」页完成「视频适用性」确认，并在「确认画面中的学生」页确认学生，再回来保存。</p></details>
<details><summary>双轨评价保存后增强修正没有计分？</summary><p>改动字段后核对勾选会自动取消，记录被保存为草稿。请重新勾选「我已逐项核对证据与情境…」后再保存。</p></details>
<details><summary>首页某一步显示「需处理」？</summary><p>该步有需要老师处理的问题（如分析失败、授权即将到期），或数据暂时读不到。看卡片上的说明和下方待办事项；读不到时刷新页面重试。</p></details>
<details><summary>结果分数能不能直接当成诊断或正式评价？</summary><p>不能。当前结果用于课堂回看、状态线索整理和本课表现记录，不替代专业诊断、IEP 决策或学校正式评价。</p></details>
</div></section>"""


def render_help(account: Any | None = None) -> str:
    role = _role_of(account)
    if role == "company_admin":
        primary = '<a href="#admin">公司后台怎么用</a><a href="#faq">常见问题</a>'
    else:
        primary = ('<a href="#home">首页与下一步</a><a href="#screenshots">三步上手</a>'
                   '<a href="#full-flow">完整闭环 8 步</a><a href="#course-task">上传课程任务</a><a href="#iep-summary">IEP 支持摘要</a>'
                   '<a href="#course-overview">课程总览</a><a href="#report-word-pdf">下载 Word/PDF</a>'
                   '<a href="#analysis-list">找回以前的课</a><a href="#admin">我是公司管理员</a>')
    body = f"""
{_header(account)}
<main class="help-main" id="mainContent">
  <section class="help-hero" id="top" aria-labelledby="helpTitle">
    <div><span class="eyebrow">{BRAND_FULL_NAME} · 使用帮助</span><h1 id="helpTitle">从上传视频到看懂学生课堂状态</h1><p>平台把一节课堂视频整理成可回看的学生状态线索，并支持身份确认、课堂复核、双轨评价、学生测量和课堂报告。第一次使用只需走「登录 → 上传 → 查看学生状态」；之后打开「首页」，按「下一步」提示逐步完成整个闭环。</p><div class="help-roles" aria-label="快速跳转">{primary}</div></div>
    <div class="help-callout" style="margin:0"><strong>先记住一件事</strong>上传成功后不要关闭页面。后台处理完成会自动跳到「学生状态结果」，结果页才是本次使用的重点。</div>
  </section>
  <div class="help-steps-head"><h2>课堂分析闭环 8 步</h2><p>与工作台首页的步骤名称和顺序一致</p></div>
  {_loop_steps()}
  <section class="help-section" id="screenshots"><h2>三步上手</h2><p>老师只需要走完「登录 → 上传并等待 → 查看结果并下载」这条主线，姓名绑定和 IEP 摘要可以在需要时再补。</p><div class="help-shot-grid">
    <article class="help-shot"><div class="shot-browser" aria-hidden="true"><div class="shot-bar"><i class="shot-dot"></i><i class="shot-dot"></i><i class="shot-dot"></i><span class="shot-url">WeGlow / 登录</span></div><div class="shot-content"><div class="shot-brand">WeGlow</div><div class="shot-login"><strong>用户登录</strong><div class="shot-input">账号</div><div class="shot-input">密码</div><span class="shot-button">登录</span></div></div></div><h3>01 · 登录</h3><p>输入学校账号和密码，进入工作台首页。</p></article>
    <article class="help-shot"><div class="shot-browser" aria-hidden="true"><div class="shot-bar"><i class="shot-dot"></i><i class="shot-dot"></i><i class="shot-dot"></i><span class="shot-url">WeGlow / 上传任务</span></div><div class="shot-content"><div class="shot-heading"><strong>提交课堂视频</strong></div><div class="shot-drop"><span>把视频拖到这里，或<b>选择课堂视频</b></span><span>MP4 / MOV / WebM</span></div><div class="shot-progress"><i></i></div><div class="shot-stage"><span>上传视频</span><span class="on">后台处理</span><span>学生状态结果</span></div></div></div><h3>02 · 拖入视频并等待</h3><p>文件到 100% 后进入后台处理，完成后自动跳到结果页。</p></article>
    <article class="help-shot"><div class="shot-browser" aria-hidden="true"><div class="shot-bar"><i class="shot-dot"></i><i class="shot-dot"></i><i class="shot-dot"></i><span class="shot-url">WeGlow / 学生状态结果</span></div><div class="shot-content"><div class="shot-person-tabs"><div class="shot-person active"><div class="shot-face"></div>人物1</div><div class="shot-person"><div class="shot-face"></div>人物2</div><div class="shot-person"><div class="shot-face"></div>人物3</div></div><div class="shot-event"><span>00:00</span><b>持续活动线索</b></div><div class="shot-event"><span>00:30</span><b>安静 / 动作较少</b></div><div class="shot-event"><span>01:00</span><b>困惑 / 停滞</b></div><div class="shot-download"><span class="shot-button">下载结果</span></div></div></div><h3>03 · 查看并下载</h3><p>点击人物切换独立时间轴；确认结果后下载。</p></article>
  </div></section>
  <div class="help-layout">
    {_toc()}
    <div>{_sections()}
    </div>
  </div>
  <a class="help-back" href="#helpToc">回到目录</a>
</main>
<footer class="help-footer">{BRAND_FULL_NAME} · 课堂学习与个体成长 · 帮助内容对应当前测试版功能</footer>
"""
    script = (HELP_SCRIPT.replace("__HELP_EVENT_PATH__", HELP_EVENT_PATH)
              .replace("__HELP_SECTIONS__", json.dumps(sorted(HELP_SECTION_IDS))))
    return _document(title="使用帮助", body=body, page_style=HELP_STYLE, script=script)
