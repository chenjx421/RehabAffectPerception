from __future__ import annotations

import json
from typing import Any


_API_PREFIX = "/api/v1/demo2"


def _account_payload(account: Any | None) -> str:
    if account is None:
        value: dict[str, Any] = {}
    elif isinstance(account, dict):
        value = {
            key: account.get(key)
            for key in (
                "account_id",
                "username",
                "role",
                "bound_channel_id",
                "course_upload_limit",
                "status",
                "login_alias",
            )
        }
    else:
        value = {
            key: getattr(account, key, None)
            for key in (
                "account_id",
                "username",
                "role",
                "bound_channel_id",
                "course_upload_limit",
                "status",
                "login_alias",
            )
        }
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )


_BOOK_ICON = """<svg class="brand-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 5.5A2.5 2.5 0 0 1 5.5 3H10a2 2 0 0 1 2 2v16a3 3 0 0 0-3-3H3Z"/><path d="M21 5.5A2.5 2.5 0 0 0 18.5 3H14a2 2 0 0 0-2 2v16a3 3 0 0 1 3-3h6Z"/><path d="m16 9 1.4 1.4L20 7.8"/></svg>"""


_COMMON_STYLE = r"""
:root {
  --canvas:#f3f8fe;
  --paper:#ffffff;
  --ink:#172b4d;
  --muted:#5b6b80;
  --line:#cfdcea;
  --line-strong:#aac4df;
  --blue:#1f63c6;
  --blue-deep:#123b70;
  --blue-soft:#e9f3ff;
  --blue-pale:#f7fbff;
  --success:#167451;
  --success-soft:#eaf7f2;
  --warning:#9a5a08;
  --warning-soft:#fff7e8;
  --danger:#b42318;
  --danger-soft:#fff1f0;
  --shadow:0 14px 34px rgba(29,75,122,.07);
}
* { box-sizing:border-box; }
html { min-width:320px; background:var(--canvas); color-scheme:light; }
body {
  margin:0;
  min-width:320px;
  min-height:100vh;
  overflow-x:hidden;
  background:var(--canvas);
  color:var(--ink);
  font-family:"Microsoft YaHei UI","PingFang SC","Segoe UI",sans-serif;
  font-size:16px;
  line-height:1.55;
}
button,input,select { font:inherit; }
button,a,input,select { -webkit-tap-highlight-color:transparent; }
button { cursor:pointer; }
a { color:inherit; }
svg { display:block; width:20px; height:20px; flex:none; }
.skip-link {
  position:fixed; top:8px; left:8px; z-index:100;
  padding:10px 14px; background:var(--blue-deep); color:#fff;
  border-radius:6px; transform:translateY(-150%);
}
.skip-link:focus { transform:none; }
:focus-visible { outline:3px solid rgba(31,99,198,.28); outline-offset:3px; }
.site-header {
  position:sticky; top:0; z-index:20; border-bottom:1px solid var(--line);
  background:rgba(255,255,255,.96);
}
.header-inner {
  width:min(1180px,calc(100% - 40px)); min-height:72px; margin:auto;
  display:flex; align-items:center; gap:18px;
}
.brand { display:flex; align-items:center; gap:12px; min-width:0; text-decoration:none; }
.brand-icon { width:42px; height:42px; padding:9px; color:#fff; background:var(--blue); border-radius:8px; }
.brand-copy { min-width:0; }
.brand-copy strong { display:block; font-size:18px; line-height:1.2; letter-spacing:0; }
.brand-copy span { display:block; color:var(--muted); font-size:12px; }
.header-actions { margin-left:auto; display:flex; align-items:center; justify-content:flex-end; gap:10px; min-width:0; }
.account-chip { min-width:0; padding:7px 11px; border-left:2px solid var(--blue); background:var(--blue-pale); }
.account-chip span,.account-chip strong { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.account-chip span { color:var(--muted); font-size:11px; }
.account-chip strong { font-size:13px; }
.page-shell { width:min(1180px,calc(100% - 40px)); margin:0 auto; padding:36px 0 64px; }
.page-heading { display:flex; align-items:flex-end; justify-content:space-between; gap:24px; margin-bottom:24px; }
.eyebrow { display:block; margin-bottom:8px; color:var(--blue); font-size:12px; font-weight:800; letter-spacing:0; }
h1,h2,h3,p { overflow-wrap:anywhere; }
h1 { margin:0; font-size:32px; line-height:1.3; letter-spacing:0; }
h2 { margin:0; font-size:22px; line-height:1.25; letter-spacing:0; }
h3 { margin:0; font-size:17px; line-height:1.35; }
p { margin:0; }
.lead { max-width:690px; margin-top:10px; color:var(--muted); }
.card { min-width:0; border:1px solid var(--line); border-radius:8px; background:var(--paper); box-shadow:var(--shadow); }
.card-head { padding:20px 22px; border-bottom:1px solid var(--line); }
.card-head p { margin-top:4px; color:var(--muted); font-size:14px; }
.card-body { padding:22px; }
.button {
  min-height:44px; display:inline-flex; align-items:center; justify-content:center; gap:8px;
  border:1px solid var(--line-strong); border-radius:6px; padding:9px 15px;
  background:#fff; color:var(--blue-deep); font-weight:700; text-decoration:none;
  transition:background-color .18s ease,border-color .18s ease,color .18s ease;
}
.button:hover { border-color:var(--blue); background:var(--blue-pale); }
.button.primary { border-color:var(--blue); background:var(--blue); color:#fff; }
.button.primary:hover { background:var(--blue-deep); }
.button.quiet { border-color:transparent; background:transparent; }
.button:disabled { cursor:not-allowed; opacity:.58; }
.button svg { width:18px; height:18px; }
.field { min-width:0; }
.field label,.field-label { display:block; margin-bottom:7px; color:var(--blue-deep); font-size:13px; font-weight:700; }
.field small { display:block; margin-top:6px; color:var(--muted); font-size:12px; }
input,select {
  width:100%; min-width:0; min-height:44px; border:1px solid var(--line-strong);
  border-radius:6px; padding:9px 12px; background:#fff; color:var(--ink);
}
input::placeholder { color:#8b99aa; }
input:hover,select:hover { border-color:#7fa7cf; }
input:focus,select:focus { border-color:var(--blue); outline:3px solid rgba(31,99,198,.14); }
.form-error,.page-message {
  display:none; margin-top:14px; border-left:3px solid var(--danger);
  padding:10px 12px; background:var(--danger-soft); color:#8b1d16; font-size:14px;
}
.form-error.visible,.page-message.visible { display:block; }
.form-error.info { border-left-color:var(--blue); background:var(--blue-soft); color:var(--blue-deep); }
.page-message.info { border-left-color:var(--blue); background:var(--blue-soft); color:var(--blue-deep); }
.page-message.success { border-left-color:var(--success); background:var(--success-soft); color:#0d5c3f; }
.security-note { border-left:3px solid var(--blue); padding:14px 16px; background:var(--blue-pale); color:#3f5570; }
.security-note strong { display:block; margin-bottom:3px; color:var(--blue-deep); }
.security-note p { font-size:13px; }
.status-dot { display:inline-block; width:8px; height:8px; margin-right:7px; border-radius:4px; background:var(--success); }
.status-badge { display:inline-flex; align-items:center; min-height:28px; padding:4px 9px; border:1px solid var(--line); border-radius:4px; background:var(--blue-pale); color:var(--blue-deep); font-size:12px; font-weight:700; }
.status-badge.success { border-color:#acd9c8; background:var(--success-soft); color:#0d6042; }
.status-badge.warning { border-color:#ead0a8; background:var(--warning-soft); color:#7b4708; }
.status-badge.danger { border-color:#efc1bd; background:var(--danger-soft); color:#8e2018; }
.empty-state { border:1px dashed var(--line-strong); padding:24px; background:var(--blue-pale); color:var(--muted); text-align:center; }
.loading-line { color:var(--muted); font-size:14px; }
.table-wrap { max-width:100%; overflow-x:auto; border:1px solid var(--line); border-radius:6px; }
table { width:100%; min-width:680px; border-collapse:collapse; background:#fff; }
th,td { padding:12px 14px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; font-size:13px; }
th { background:var(--blue-pale); color:var(--muted); font-size:12px; font-weight:800; }
tr:last-child td { border-bottom:0; }
.mono { font-family:"Cascadia Code",Consolas,monospace; font-size:.92em; }
.sr-only { position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; border:0; }
@media (max-width:780px) {
  .header-inner,.page-shell { width:min(100% - 28px,1180px); }
  .header-inner { min-height:64px; }
  .brand-copy span,.account-chip span { display:none; }
  .page-shell { padding-top:24px; }
  .page-heading { align-items:flex-start; flex-direction:column; gap:14px; }
  .header-actions .button span { display:none; }
  .header-actions .button { width:44px; padding:8px; }
}
@media (max-width:720px) {
  .header-inner { display:grid; grid-template-columns:minmax(0,1fr); gap:0; padding:10px 0 12px; }
  .brand { width:100%; }
  .brand-copy span { display:block; }
  .header-actions {
    width:100%; min-width:0; margin:9px 0 0; padding-top:9px;
    justify-content:flex-start; align-items:stretch; flex-wrap:wrap;
    border-top:1px solid var(--line);
  }
  .account-chip { flex:1 1 104px; max-width:none; min-width:0; padding:7px 9px; }
  .account-chip span { display:block; }
  .account-chip strong {
    overflow:visible; text-overflow:clip; white-space:normal;
    overflow-wrap:anywhere; word-break:break-word;
  }
  .header-actions .button { flex:0 0 44px; min-width:44px; align-self:center; }
  .header-actions .button:last-child { margin-left:auto; }
}
@media (max-width:480px) {
  .header-inner,.page-shell { width:min(100% - 20px,1180px); }
  .brand-icon { width:38px; height:38px; }
  .brand-copy strong { font-size:16px; }
  .account-chip { max-width:none; padding-inline:8px; }
  .card-head,.card-body { padding:18px; }
  h1 { font-size:28px; }
}
@media (prefers-reduced-motion:reduce) {
  *,*::before,*::after { scroll-behavior:auto !important; transition-duration:.01ms !important; }
}
"""


def _document(*, title: str, body: str, page_style: str = "", script: str = "") -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="theme-color" content="#f3f8fe" />
  <meta name="description" content="RehabAffect 辅读学校课堂分析内测平台" />
  <title>{title}</title>
  <style>{_COMMON_STYLE}{page_style}</style>
</head>
<body>
  <a class="skip-link" href="#mainContent">跳到主要内容</a>
  {body}
  <script>{script}</script>
</body>
</html>"""


def render_demo2_login_html() -> str:
    from .demo2_entry import render_login

    return render_login()


def render_demo2_register_html() -> str:
    from .demo2_entry import render_register

    return render_register()


def render_demo2_privacy_html() -> str:
    from .demo2_entry import render_privacy

    return render_privacy()


def render_demo2_school_html(account: Any | None = None) -> str:
    from .school_selection_page import render_school_selection_html as render_school

    return render_school(account)


def render_demo2_video_html(account: Any | None = None) -> str:
    from .demo2_video_review import render_video_review

    return render_video_review(account)


def render_demo2_membership_html(account: Any | None = None) -> str:
    from .demo2_entry import render_membership

    return render_membership(account)


_WORKSPACE_STYLE = r"""
:root { --canvas:#fff; --ink:#263746; --muted:#626e7b; --line:#e4e9ef; --blue:#2163C4; --blue-deep:#214e87; --shadow:none; }
body { background:#fff; font-family:"Segoe UI","Microsoft YaHei",sans-serif; letter-spacing:0; }
*,*::before,*::after { letter-spacing:0; }
[hidden] { display:none !important; }
.workspace-nav { display:flex; align-items:center; gap:24px; min-width:0; flex-wrap:wrap; }
.workspace-nav a { display:inline-flex; align-items:center; min-height:44px; padding:8px 0; border-bottom:2px solid transparent; color:var(--muted); font-size:14px; text-decoration:none; }
.workspace-nav a:hover { color:var(--blue); }
.workspace-nav a[aria-current=page] { color:var(--blue); border-bottom-color:var(--blue); font-weight:600; }
.workspace-tool-links { display:inline-flex; align-items:center; gap:10px; margin-left:auto; white-space:nowrap; }
.workspace-tool-links a { color:var(--blue); font-size:13px; text-decoration:none; }
.workspace-tool-links a:hover { text-decoration:underline; }
.site-header .header-inner { min-height:64px; gap:24px; flex-wrap:wrap; }
.site-header .brand-icon { width:36px; height:36px; padding:7px; }
.site-header .brand-copy strong { font-size:17px; }
.site-header .brand-copy span { font-size:11px; }
@media (max-width:1100px) {
  .site-header .header-inner { gap:4px 18px; padding-block:8px 0; }
  .site-header .workspace-nav { order:3; flex-basis:100%; }
}
@media (max-width:720px) {
  .site-header { position:static; }
  .site-header .header-inner { display:flex; }
  .site-header .brand { width:auto; }
  .site-header .header-actions { width:auto; margin:0 0 0 auto; padding:0; border:0; flex-wrap:wrap; }
  .workspace-nav { width:100%; justify-content:space-between; gap:8px; }
  .workspace-nav a { font-size:13px; }
  .workspace-tool-links { width:100%; justify-content:flex-end; margin:0; padding:0 0 6px; }
}
"""


def _workspace_nav(active: str, *, compact: bool = False) -> str:
    if compact:
        return ('<nav class="workspace-nav compact-workspace-nav" aria-label="账号工作台">'
                f'<a href="/demo2/upload" aria-current="page">上传视频</a>'
                '<a href="/demo2/upload?advanced=1">更多功能</a>'
                '<a href="/demo2/help">使用帮助</a></nav>')
    # Keep the upload screen focused on the teacher's main path. The roster
    # route remains available from its own page and direct links.
    items = [("upload", "上传任务", "")]
    if active != "upload":
        items.append(("students", "学生名册", ' id="studentRosterLink"'))
    items.extend((
        ("school", "学校信息", ""),
        ("membership", "会员中心", ' id="membershipLink"'),
    ))
    links = "".join(
        f'<a href="/demo2/{route}"{element_id}'
        f'{" aria-current=page" if route == active else ""}>{label}</a>'
        for route, label, element_id in items
    )
    # Keep the primary workflow compact; the new measurement and recording
    # tools remain directly reachable beside it without changing legacy nav
    # contracts used by embedded school pages.
    tools = '<span class="workspace-tool-links"><a href="/demo2/help">使用帮助</a><a href="/demo2/evaluation">课堂双轨评价</a><a href="/demo2/measurement">测量与报告</a><a href="/demo2/capture">录制课堂</a></span>'
    return f'<nav class="workspace-nav" aria-label="账号工作台">{links}</nav>{tools}'


def render_demo2_upload_html(account: Any | None = None) -> str:
    account_json = _account_payload(account)
    page_style = _WORKSPACE_STYLE + r"""
.page-shell { padding-top:20px; }
.advanced-only { display:none !important; }
body.advanced-mode .advanced-only { display:block !important; }
body:not(.advanced-mode) .task-section { display:block !important; }
.compact-workspace-nav { gap:18px; }
.compact-workspace-nav a { min-height:40px; }
.simple-workflow { margin-bottom:20px; }
.simple-workflow li { flex:0 1 auto; }
.simple-workflow li:last-child { color:var(--blue); font-weight:700; }
.page-heading { margin-bottom:12px; align-items:center; }
.page-heading h1 { font-size:22px; }
.page-heading .eyebrow { margin-bottom:2px; font-size:12px; }
.page-heading .button { font-size:13px; }
.workflow { display:flex; flex-wrap:wrap; gap:8px 20px; list-style:none; padding:10px 0 14px; margin:0 0 18px; border-bottom:1px solid var(--line); color:var(--muted); font-size:13px; }
.workflow li { display:flex; align-items:center; gap:8px; }
.workflow b { color:var(--blue); font-weight:600; }
.workflow a { color:var(--blue); text-underline-offset:4px; }
.workspace-grid { display:grid; grid-template-columns:minmax(0,1.48fr) minmax(280px,.52fr); gap:20px; align-items:start; }
.workspace-grid .card { border:0; border-radius:0; box-shadow:none; }
.workspace-grid .card-head { padding:0 0 12px; border:0; }
.workspace-grid .card-head h2 { font-size:18px; }
.workspace-grid .card-body { padding:0; }
.workspace-grid .quota-panel { padding-left:24px; border-left:1px solid var(--line); }
.form-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }
.field.wide { grid-column:1/-1; }
.quota-panel { position:sticky; top:94px; }
.quota-count { display:flex; align-items:flex-end; justify-content:space-between; gap:16px; }
.quota-count strong { font:700 42px/1 Bahnschrift,"Segoe UI",sans-serif; color:var(--blue-deep); }
.quota-count span { color:var(--muted); font-size:13px; }
.slot-rail { display:grid; grid-template-columns:repeat(5,1fr); gap:7px; margin-top:18px; }
.slot { min-height:36px; display:grid; place-items:center; border:0; border-bottom:2px solid var(--line); border-radius:0; background:var(--blue-pale); color:var(--muted); font:700 13px/1 "Segoe UI",sans-serif; }
.slot.used { border-color:#8cb9e7; background:var(--blue-soft); color:var(--blue-deep); }
.slot.uploading { border-color:var(--blue); box-shadow:inset 0 -4px var(--blue); }
.channel-ticket { margin-top:18px; border-left:4px solid var(--blue); padding:14px 16px; background:var(--blue-pale); }
.channel-ticket span { display:block; color:var(--muted); font-size:12px; }
.channel-ticket strong { display:block; margin-top:2px; color:var(--blue-deep); font-size:19px; }
.authorization-group { display:grid; gap:9px; margin-top:18px; }
.authorization { display:flex; align-items:flex-start; gap:10px; padding:14px; border:1px solid var(--line); background:var(--blue-pale); }
.authorization.optional { background:#fff; }
.authorization input { width:20px; min-height:20px; margin:2px 0 0; flex:none; }
.authorization label { color:#3d526d; font-size:13px; }
.authorization-details { margin-top:18px; font-size:12px; color:var(--muted); border-top:1px solid var(--line); padding-top:14px; }
.authorization-details summary { cursor:pointer; min-height:32px; color:#526980; }
.authorization-details p { line-height:1.9; margin:6px 0 12px; }
.authorization-details select { font-size:13px; min-height:40px; }
.upload-consent-note { font-size:12px; line-height:1.8; color:var(--muted); margin-top:12px; }
.upload-consent-note a { text-underline-offset:3px; }
.school-location { display:flex; flex-wrap:wrap; gap:12px; margin-bottom:2px; padding:0; font-size:13px; color:var(--muted); overflow-wrap:anywhere; }
.school-location a { color:var(--blue); white-space:nowrap; }
.school-location nav { display:flex; flex-wrap:wrap; gap:16px; }
.school-location nav a { display:inline-flex; align-items:center; min-height:44px; }
.security-ledger { margin-top:12px; border-left:3px solid var(--line-strong); padding:10px 12px; background:#fff; color:var(--muted); font-size:12px; }
.security-ledger strong { display:block; color:var(--blue-deep); font-size:13px; }
.security-ledger span { display:block; margin-top:2px; }
.file-control { position:relative; min-width:0; }
.file-input-accessible {
  position:absolute; width:1px; height:1px; padding:0; margin:-1px;
  overflow:hidden; clip:rect(0,0,0,0); clip-path:inset(50%);
  white-space:nowrap; border:0;
}
.file-picker {
  min-width:0; min-height:58px; display:grid; grid-template-columns:auto minmax(0,1fr);
  align-items:stretch; margin:0; overflow:hidden; border:1px solid var(--line-strong);
  border-radius:6px; background:#fff; color:var(--ink); cursor:pointer;
  transition:border-color .18s ease,box-shadow .18s ease;
}
.field .file-picker { display:grid; }
.file-picker:hover { border-color:var(--blue); }
.file-input-accessible:focus-visible + .file-picker { border-color:var(--blue); outline:3px solid rgba(31,99,198,.16); outline-offset:2px; }
.file-picker-action { display:flex; align-items:center; justify-content:center; gap:8px; padding:10px 16px; background:var(--blue-soft); color:var(--blue-deep); font-size:14px; font-weight:800; }
.file-picker-action svg { width:18px; height:18px; }
.file-picker-name { min-width:0; display:flex; align-items:center; padding:10px 14px; overflow:hidden; color:var(--muted); font-size:13px; text-overflow:ellipsis; white-space:nowrap; }
.upload-command { display:flex; align-items:center; gap:12px; margin-top:18px; }
.upload-command .button { min-width:148px; }
.file-preview { min-width:0; color:var(--muted); font-size:13px; }
.progress-block { display:none; margin-top:18px; }
.progress-block.visible { display:block; }
.progress-head { display:flex; justify-content:space-between; gap:14px; margin-bottom:7px; color:var(--muted); font-size:13px; }
.progress-head span { min-width:0; overflow-wrap:anywhere; }
.progress-head strong { flex-shrink:0; }
#transferDetails { font-size:13px; color:var(--muted); overflow-wrap:anywhere; }
.progress-track { height:9px; overflow:hidden; border-radius:4px; background:#dce8f3; }
.progress-track i { display:block; width:0; height:100%; background:var(--blue); transition:width .2s ease; }
.task-section { margin-top:30px; padding-top:20px; border-top:1px solid var(--line) !important; }
.task-list { display:grid; }
.task-row { min-width:0; display:grid; grid-template-columns:minmax(0,1fr) 112px 126px; gap:16px; align-items:center; padding:16px 0; border-bottom:1px solid var(--line); background:#fff; }
.task-filters { display:grid; grid-template-columns:minmax(0,1fr) 142px auto; gap:12px; align-items:end; margin-top:14px; }
.task-filters input,.task-filters select { font-size:14px; }
.task-result-count { margin-top:10px; color:var(--muted); font-size:12px; overflow-wrap:anywhere; }
.task-list .empty-state { border:0; border-radius:0; background:#f7f9fc; margin-top:12px; }
.task-main { min-width:0; }
.task-main strong { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.task-main span,.task-meta span { display:block; color:var(--muted); font-size:12px; }
.task-main .task-detail { margin-top:7px; overflow-wrap:anywhere; }
.task-main .task-error { color:var(--danger); }
.task-toolbar { display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; }
.task-poll-status { margin-top:8px; color:var(--muted); font-size:12px; }
.mini-progress { height:6px; margin-top:7px; overflow:hidden; background:#dce8f3; }
.mini-progress i { display:block; height:100%; background:var(--blue); }
.task-action { justify-self:end; display:flex; align-items:center; flex-wrap:wrap; gap:8px; }
.task-action a,.task-action button { display:inline-flex; align-items:center; min-height:44px; color:var(--blue); font-size:13px; font-weight:700; overflow-wrap:anywhere; }
.task-action button { min-height:44px; border:1px solid var(--line-strong); border-radius:5px; padding:6px 10px; background:#fff; cursor:pointer; }
.task-action button:hover { border-color:var(--danger); color:var(--danger); background:var(--danger-soft); }
.side-note { margin-top:16px; padding:0; border:0; background:#fff; color:var(--muted); font-size:13px; }
@media (max-width:900px) {
  .workspace-grid { grid-template-columns:1fr; }
  .workspace-grid .quota-panel { position:static; padding:18px 0 0; border-left:0; border-top:1px solid var(--line); }
  .slot-rail { max-width:320px; }
}
@media (max-width:620px) {
  .page-heading { align-items:flex-start; }
  .form-grid { grid-template-columns:1fr; }
  .field.wide { grid-column:auto; }
  .file-picker { grid-template-columns:1fr; }
  .file-picker-action { min-height:46px; }
  .file-picker-name { min-height:44px; border-top:1px solid var(--line); white-space:normal; }
  .file-picker-name,.task-main strong,.task-main span,.file-preview { overflow:visible; white-space:normal; overflow-wrap:anywhere; text-overflow:clip; }
  .upload-command { align-items:stretch; flex-direction:column; }
  .task-row { grid-template-columns:1fr; gap:8px; }
  .task-action { justify-self:start; }
  .task-filters { grid-template-columns:minmax(0,1fr) 132px; }
  .task-filters .button { justify-self:start; grid-column:1/-1; }
  .site-header .header-actions { width:100%; margin-top:6px; }
}
"""
    body = f"""
<header class="site-header">
  <div class="header-inner">
    <a class="brand" href="/demo2/upload">{_BOOK_ICON}<span class="brand-copy"><strong>RehabAffect</strong><span>学校视频上传工作台</span></span></a>
    {_workspace_nav("upload")}
    <div class="header-actions">
      <div class="account-chip"><span>登录账号</span><strong id="accountName">读取中</strong></div>
      <div class="account-chip"><span>当前通道</span><strong id="channelName">读取中</strong></div>
      <button class="button quiet" id="logoutButton" type="button" aria-label="退出登录"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M10 17l5-5-5-5M15 12H3"/><path d="M14 3h5a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-5"/></svg><span>退出</span></button>
    </div>
  </div>
</header>
<main class="page-shell" id="mainContent">
  <div class="page-heading"><div><span class="eyebrow">教师上传入口</span><h1>提交课堂视频</h1><p class="lead">上传课堂视频，后台完成分析后查看学生状态结果。</p></div><a class="button quiet advanced-only" id="analysisLink" href="/demo2/analysis" aria-label="课堂复核与图文报告">课堂复核与报告</a></div>
  <div class="page-message" id="pageMessage" role="alert" aria-live="assertive" tabindex="-1"></div>
  <div class="school-location"><span id="schoolLocation" role="status">正在读取学校信息</span><a class="button quiet" id="completeSchoolLink" href="/demo2/school" target="_blank" rel="noopener noreferrer">补全学校信息</a><button class="button quiet" id="reloadSchoolButton" type="button">重新读取学校信息</button></div>
  <ol class="workflow simple-workflow" aria-label="视频分析流程"><li><b>1</b> 选择视频</li><li><b>2</b> 上传并分析</li><li><b>3</b> 查看学生状态</li></ol>
  <div class="workspace-grid">
    <div>
      <section class="card" aria-labelledby="uploadTitle">
        <div class="card-head"><h2 id="uploadTitle">课程与视频</h2></div>
        <div class="card-body">
          <div class="form-grid">
            <div class="field advanced-only"><label for="courseId">课程批次号</label><input id="courseId" maxlength="120" placeholder="系统自动生成" /><small>高级测试时可使用负责人提供的批次号。</small></div>
            <div class="field"><label for="courseName">课程名称（可选）</label><input id="courseName" maxlength="200" placeholder="例如：生活语文" /></div>
            <div class="field"><label for="channelSelect">上传通道</label><select id="channelSelect" aria-describedby="channelHelp"><option value="">正在读取可用通道</option></select><small id="channelHelp">请选择本次使用的可用通道；通道由管理员配置。</small></div>
            <div class="field advanced-only"><label for="studentSelect">计划关注学生</label><select id="studentSelect" aria-describedby="studentHelp"><option value="">暂不指定关注学生</option></select><small id="studentHelp">学生身份在分析结果页再确认。</small></div>
            <div class="field advanced-only"><span class="field-label">课程工作区</span><button class="button" id="loadCourseButton" type="button">读取课程工作区</button></div>
            <div class="field wide"><span class="field-label">课堂视频</span><div class="file-control"><input class="file-input-accessible" id="videoFile" type="file" accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm" /><label class="file-picker" for="videoFile"><span class="file-picker-action"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4M7 9l5-5 5 5M4 20h16"/></svg>选择课堂视频</span><span class="file-picker-name" id="selectedFileName" aria-live="polite">尚未选择视频</span></label></div><small id="videoRequirements">测试阶段：单节课不超过 60 分钟，单文件不超过 1 GiB。支持 MP4 / MOV / WebM，推荐 MP4（H.264 / AAC）、720p 或 1080p。上传及暂停期间请勿关闭或刷新页面。</small></div>
          </div>
          <details class="authorization-details"><summary id="authorizationTitle">数据使用与保存设置</summary><p>本次资料用于课堂分析，原视频保存60天，到期前15天提醒。点击下方按钮将记录本课程、本文件的授权确认。</p><label for="allowCompanyArchive">脱敏结构化结果长期归档（需另行获得校方授权）</label><select id="allowCompanyArchive"><option value="no">不允许，仅按本次课堂用途处理</option><option value="yes">已获授权，允许脱敏结构化结果长期归档（不含原视频）</option></select><div class="security-ledger" id="latestSecurityAcceptance" role="status" aria-live="polite"><strong>最近授权确认</strong><span>读取课程工作区后显示。</span></div></details>
          <p class="upload-consent-note">点击上传即确认资料已获校方授权，并按<a href="/demo2/privacy" target="_blank" rel="noopener">数据安全与隐私说明</a>处理。</p>
          <div class="upload-command"><button class="button primary" id="uploadButton" type="button" disabled><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4M7 9l5-5 5 5M4 20h16"/></svg>开始上传并分析</button><span class="file-preview" id="filePreview">请选择课堂视频。</span></div><input id="resumeVideoFile" type="file" accept=".mp4,.mov,.avi,.mkv,.webm" hidden />
          <div class="progress-block" id="uploadProgress"><div class="progress-head"><span id="progressLabel">准备上传</span><strong id="progressPercent">0%</strong></div><div class="progress-track" role="progressbar" aria-label="视频上传进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><i id="progressBar"></i></div><p id="transferDetails" role="status"></p><button class="button" id="pauseUploadButton" type="button" hidden>暂停上传</button><button class="button" id="resumeUploadButton" type="button" hidden>继续上传</button></div>
        </div>
      </section>
      <section class="card task-section advanced-only" aria-labelledby="taskTitle">
        <div class="card-head"><div class="task-toolbar"><h2 id="taskTitle" tabindex="-1">本课程任务</h2><button class="button" id="refreshTasksButton" type="button" disabled>刷新任务</button></div><p class="task-poll-status" id="taskPollStatus" role="status">读取课程后显示真实任务；上传完成与证据就绪分开记录。</p>
          <div class="task-filters" role="search" aria-label="筛选当前已加载任务">
            <div class="field"><label for="taskSearch">搜索当前任务</label><input id="taskSearch" type="search" maxlength="200" placeholder="文件名或任务编号" aria-controls="taskList" /></div>
            <div class="field"><label for="taskStatusFilter">任务状态</label><select id="taskStatusFilter" aria-controls="taskList"><option value="">全部状态</option><option value="uploading">上传中</option><option value="uploaded">上传完成</option><option value="queued">等待处理</option><option value="processing">后台处理中</option><option value="ready">证据已就绪</option><option value="failed">上传 / 处理失败</option><option value="legacy">历史预检</option><option value="expired">原片已清理</option><option value="cancelled">已取消</option><option value="unknown">状态待确认</option></select></div>
            <button class="button quiet" id="clearTaskFilters" type="button" disabled>清除筛选</button>
          </div><p class="task-result-count" id="taskResultCount" role="status" aria-live="polite">尚未加载课程任务</p>
          <details class="authorization-details"><summary>任务数据范围</summary><p>文件名、上传进度、处理状态和结果下载均来自当前账号的绑定通道。搜索仅筛选已加载任务，不查询其他学校或通道。</p></details>
        </div>
        <div class="card-body"><div class="task-list" id="taskList"><div class="empty-state">输入课程批次号并读取工作区后，这里会显示该课程的真实任务。</div></div></div>
      </section>
    </div>
    <aside class="card quota-panel advanced-only" aria-labelledby="quotaTitle">
      <div class="card-head"><h2 id="quotaTitle">五个视频名额</h2><p>每个课程独立计算，已用名额以接口返回为准。</p></div>
      <div class="card-body">
        <div class="quota-count"><div><strong id="usedSlots">--</strong><span> 已用</span></div><span>剩余 <b id="remainingSlots">--</b> / 共 <b id="maxSlots">5</b></span></div>
        <div class="slot-rail" id="slotRail" aria-label="视频名额使用情况"><div class="slot" aria-label="第 1 个名额未使用">01</div><div class="slot" aria-label="第 2 个名额未使用">02</div><div class="slot" aria-label="第 3 个名额未使用">03</div><div class="slot" aria-label="第 4 个名额未使用">04</div><div class="slot" aria-label="第 5 个名额未使用">05</div></div>
        <div class="channel-ticket"><span>本账号绑定通道</span><strong id="boundChannel">等待账号信息</strong></div>
        <div class="side-note"><strong>数据边界</strong><br />页面不会展示其他学校账号或其他上传通道的任务。学生课堂状态只来自当前上传视频。</div>
      </div>
    </aside>
  </div>
</main>"""
    script = f"""
const API_PREFIX = '{_API_PREFIX}';
const API_ROUTES = {{
  me:'{_API_PREFIX}/auth/me',
  logout:'{_API_PREFIX}/auth/logout',
  workspace:'{_API_PREFIX}/upload/workspace',
  tasks:'{_API_PREFIX}/upload/tasks',
  task:'{_API_PREFIX}/upload/task',
  resume:'{_API_PREFIX}/upload/resume',
  school:'{_API_PREFIX}/school/context',
  chunks:'{_API_PREFIX}/upload/chunks',
  cancel:'{_API_PREFIX}/upload/tasks/cancel'
}};
const CHUNK_SIZE = 4 * 1024 * 1024;
const MAX_VIDEO_SIZE = 1024 * 1024 * 1024;
const MAX_VIDEO_DURATION = 3600;
const ALLOWED_VIDEO_EXTENSIONS = ['.mp4','.mov','.webm'];
const SERVER_ACCOUNT = {account_json};
let account = SERVER_ACCOUNT;
const advancedMode = new URLSearchParams(location.search).get('advanced') === '1';
if(advancedMode) document.body.classList.add('advanced-mode');
let workspace = null;
let uploadInProgress = false;
let uploadSession = null;
let resumeTaskId = null;
let fileSelectionVersion = 0;
let schoolState = 'unloaded';
let schoolRequest = 0;
let taskPollTimer = null;
let workspaceRequest = 0;
let taskPollStopped = false;
let taskPollBusy = false;
let workspaceLoading = false;
let taskRefreshError = '';
let activeProcessingTaskId = '';
let processingRedirected = false;
const byId = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>\"']/g, char => ({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}}[char]));
const formatBytes = value => {{ const bytes=Number(value||0); if(bytes<1024)return `${{bytes}} B`; if(bytes<1048576)return `${{(bytes/1024).toFixed(1)}} KB`; if(bytes<1073741824)return `${{(bytes/1048576).toFixed(1)}} MB`; return `${{(bytes/1073741824).toFixed(2)}} GB`; }};
const channelLabel = value => {{ const text=String(value||'').trim(); const match=/^channel_(\\d+)$/.exec(text); return match?`上传通道 ${{Number(match[1])}}`:text; }};
function message(text,type='error') {{ const node=byId('pageMessage'); node.textContent=text; node.className=`page-message visible ${{type}}`; node.focus?.(); }}
function clearMessage() {{ byId('pageMessage').className='page-message'; }}
async function api(url,options={{}}) {{
  const {{timeoutMs=30000,signal,preservePage=false,...requestOptions}}=options;
  const controller=new AbortController(),abort=()=>controller.abort();
  if(signal?.aborted)abort();else signal?.addEventListener('abort',abort,{{once:true}});
  const timeout=setTimeout(abort,timeoutMs);
  try {{
  const response=await fetch(url,{{credentials:'same-origin',...requestOptions,signal:controller.signal}}).catch(error=>{{if(error instanceof TypeError)throw new Error('网络连接失败，请检查网络后重试。');if(error.name==='AbortError')throw new Error('请求超时，结果尚未确认，请核对任务状态后重试。');throw error;}});
  const payload=await response.json().catch(error=>{{if(error instanceof TypeError)throw new Error('网络连接失败，请检查网络后重试。');if(error.name==='AbortError')throw error;return {{}};}});
  if(response.status===401) {{ if(!uploadInProgress&&!preservePage){{try {{ sessionStorage.setItem('demo2_notice','登录状态已过期，请重新登录。'); }} catch (_) {{}} window.location.assign('/demo2/login');}} const error=new Error('登录已过期，请在另一标签页重新登录后继续，勿关闭此页。'); error.status=401; throw error; }}
  if(!response.ok || payload.error) {{ const error=new Error(response.status===403?'当前账号无权访问该通道或任务，请联系项目方核对账号绑定。':payload.error?.message || '请求失败，请稍后重试。'); error.status=response.status;error.code=payload.error?.code;throw error; }}
  return payload;
  }} finally {{clearTimeout(timeout);signal?.removeEventListener('abort',abort);}}
}}
function schoolUploadHint() {{
  if(schoolState==='error')return '学校信息读取失败，请点击“重新读取学校信息”后再新建上传。';
  if(schoolState==='incomplete')return '请点击“补全学校信息”，填写城市、区县和学校名称后返回本页重新读取。已选文件保留。';
  return '正在确认学校信息，请稍候；确认完整后才能新建上传。';
}}
function schoolRequired() {{
  schoolRequest+=1;schoolState='incomplete';
  byId('schoolLocation').textContent='学校信息不完整，不能新建上传任务';
  byId('completeSchoolLink').hidden=false;byId('reloadSchoolButton').disabled=false;updateUploadEnabled();
}}
async function loadSchoolContext() {{
  const request=++schoolRequest;schoolState='loading';
  byId('schoolLocation').textContent='正在读取学校信息';byId('reloadSchoolButton').disabled=true;updateUploadEnabled();
  try {{
    const payload=await api(API_ROUTES.school,{{cache:'no-store',preservePage:true}});
    if(request!==schoolRequest)return;
    const context=payload.context;
    if(!context||typeof context!=='object'||Array.isArray(context))throw new Error('学校信息响应不完整');
    const complete=['city','district','school_name'].every(key=>typeof context[key]==='string'&&context[key].trim().length>0);
    schoolState=complete?'ready':'incomplete';
    byId('schoolLocation').textContent=complete?[context.city,context.district,context.school_name].map(value=>value.trim()).join(' / '):'学校信息不完整，不能新建上传任务';
  }}catch(error){{if(request!==schoolRequest)return;schoolState='error';byId('schoolLocation').textContent=error.status===401?'登录已过期，请在另一标签页重新登录后重试':'学校信息读取失败，请重试；暂不能新建上传任务';}}
  finally{{if(request===schoolRequest){{byId('reloadSchoolButton').disabled=false;byId('completeSchoolLink').hidden=schoolState==='ready';updateUploadEnabled();}}}}
}}
function setAccount(value) {{
  account=value||{{}};
  byId('accountName').textContent=account.login_alias||account.username||'未识别账号';
  const boundChannel=String(account.bound_channel_id||'').trim();
  const channelSelect=byId('channelSelect');
  if(boundChannel&&channelSelect&&!channelSelect.value) {{
    channelSelect.innerHTML=`<option value="${{esc(boundChannel)}}">${{esc(channelLabel(boundChannel))}}</option>`;
    channelSelect.value=boundChannel;
  }}
  const channel=workspace?.channel?.channel_name||channelLabel(byId('channelSelect')?.value)||channelLabel(account.bound_channel_id)||'未配置';
  byId('channelName').textContent=channel;
  byId('boundChannel').textContent=channel;
  updateUploadEnabled();
}}
function updateUploadEnabled() {{
  const maximum=newVideoLimit();
  byId('videoRequirements').textContent=`测试阶段：单节课不超过 60 分钟，单文件不超过 ${{maximum===MAX_VIDEO_SIZE?'1 GiB':formatBytes(maximum)}}。支持 MP4 / MOV / WebM，推荐 MP4（H.264 / AAC）、720p 或 1080p。上传及暂停期间请勿关闭或刷新页面。`;
  const courseMatches=workspace && byId('courseId').value.trim()===String(workspace.course_id||'').trim();
  byId('uploadButton').disabled=schoolState!=='ready'||uploadInProgress || workspaceLoading || !(courseMatches && byId('channelSelect').value && byId('videoFile').files[0] && Number(workspace.remaining_slots)>0);
  byId('refreshTasksButton').disabled=uploadInProgress||workspaceLoading||!courseMatches;
  byId('filePreview').textContent=uploadHint();
}}
function newVideoLimit() {{
  const configured=workspace?.max_video_bytes;
  return Number.isSafeInteger(configured)&&configured>0?Math.min(configured,MAX_VIDEO_SIZE):MAX_VIDEO_SIZE;
}}
function preflightVideo(file) {{
  return new Promise((resolve,reject)=>{{
    let video,url,timer,settled=false,seekTried=false;
    const finish=(error,duration)=>{{
      if(settled)return;settled=true;clearTimeout(timer);
      if(video){{video.onloadedmetadata=null;video.onerror=null;video.ondurationchange=null;video.onseeked=null;try{{video.removeAttribute('src');video.load();}}catch(_){{}}}}
      if(url)URL.revokeObjectURL(url);
      if(error)reject(error);else resolve(duration);
    }};
    try {{
      video=document.createElement('video');video.preload='metadata';
      const inspectDuration=()=>{{
        const duration=video.duration;
        if(duration===Infinity){{
          if(!seekTried){{seekTried=true;try{{video.currentTime=1e10;}}catch(_){{finish(new Error('无法确定视频时长，请转换为 MP4（H.264 / AAC）后重新选择。'));}}}}
          return;
        }}
        if(!Number.isFinite(duration)||duration<=0)finish(new Error('无法读取有效视频时长，请转换为 MP4（H.264 / AAC）后重新选择。'));
        else if(duration>MAX_VIDEO_DURATION)finish(new Error('测试阶段每节课不超过 60 分钟，请裁剪为单节课视频后重新选择。'));
        else finish(null,duration);
      }};
      video.onloadedmetadata=inspectDuration;
      video.ondurationchange=()=>{{if(seekTried)inspectDuration();}};
      video.onseeked=inspectDuration;
      video.onerror=()=>finish(new Error('浏览器无法读取此视频，请转换为 MP4（H.264 / AAC）后重新选择。'));
      timer=setTimeout(()=>finish(new Error('读取视频时长超过 15 秒，请确认文件可本地播放，或转换为 MP4（H.264 / AAC）后重试。')),15000);
      url=URL.createObjectURL(file);video.src=url;video.load();
    }}catch(_){{finish(new Error('无法检查视频，请转换为 MP4（H.264 / AAC），并使用支持视频预览的浏览器重试。'));}}
  }});
}}
function uploadHint() {{
  if(uploadSession?.paused)return '上传已暂停，文件和已确认进度保留；点击“继续上传”。请勿关闭或刷新页面。';
  if(uploadInProgress)return uploadSession?'视频正在上传，请勿关闭或刷新页面。':'正在检查文件或准备上传，请勿关闭或刷新页面。';
  if(schoolState!=='ready')return schoolUploadHint();
  if(!workspace)return '请先读取课程名额并选择视频。';
  if(byId('courseId').value.trim()!==String(workspace.course_id||'').trim())return '课程批次号已修改，请重新读取课程工作区。';
  if(Number(workspace.remaining_slots)<=0)return '本课程名额已用完，请检查下方任务或联系项目方。';
  return byId('videoFile').files[0]?'文件已选择，点击“开始上传并分析”。':'请先选择课堂视频。';
}}
function setUploadBusy(value) {{
  uploadInProgress=value;
  ['courseId','courseName','channelSelect','studentSelect','videoFile','allowCompanyArchive','loadCourseButton','logoutButton'].forEach(id=>byId(id).disabled=value);
  updateUploadEnabled();
}}
function renderSlots() {{
  if(!workspace) {{
    byId('usedSlots').textContent='--'; byId('remainingSlots').textContent='--'; byId('maxSlots').textContent=String(account.course_upload_limit||5);
    byId('slotRail').innerHTML=Array.from({{length:Number(account.course_upload_limit||5)}},(_,index)=>`<div class="slot" aria-label="第 ${{index+1}} 个名额尚未读取">${{String(index+1).padStart(2,'0')}}</div>`).join('');
    return;
  }}
  const maximum=Math.max(1,Number(workspace?.max_slots ?? workspace?.quota?.max_slots ?? 5));
  const used=Math.max(0,Number(workspace?.used_slots ?? workspace?.quota?.used_slots ?? 0));
  const remaining=Math.max(0,Number(workspace?.remaining_slots ?? workspace?.quota?.remaining_slots ?? maximum-used));
  byId('usedSlots').textContent=String(used); byId('remainingSlots').textContent=String(remaining); byId('maxSlots').textContent=String(maximum);
  byId('slotRail').innerHTML=Array.from({{length:maximum}},(_,index)=>`<div class="slot ${{index<used?'used':''}}" aria-label="第 ${{index+1}} 个名额${{index<used?'已使用':'未使用'}}">${{String(index+1).padStart(2,'0')}}</div>`).join('');
}}
function taskStatus(task) {{
  if(task.upload_status==='cancelled'||task.analysis_status==='cancelled') return ['已取消','danger'];
  if(task.raw_media_deleted_at||['expired','deleted'].includes(task.analysis_status)||['expired','deleted'].includes(task.upload_status)) return ['原片已清理','warning'];
  if(task.analysis_status==='evidence_ready') return ['证据已就绪','success'];
  if(task.analysis_status==='processing') return ['后台处理中',''];
  if(task.analysis_status==='queued') return ['等待处理','warning'];
  if(task.analysis_status==='failed') return ['处理未完成','danger'];
  if(task.analysis_status==='precheck_complete') return ['历史预检','warning'];
  if(task.analysis_status==='uploaded_pending_worker') return ['历史预检','warning'];
  if(task.upload_status==='completed') return ['上传完成','success'];
  if(task.upload_status==='failed') return ['上传失败','danger'];
  if(task.upload_status==='uploading'||task.analysis_status==='waiting_upload') return ['上传中',''];
  return ['状态待确认','warning'];
}}
function taskFilterKey(task) {{
  if(task.upload_status==='cancelled'||task.analysis_status==='cancelled')return 'cancelled';
  if(task.raw_media_deleted_at||['expired','deleted'].includes(task.analysis_status)||['expired','deleted'].includes(task.upload_status))return 'expired';
  if(task.analysis_status==='failed'||task.upload_status==='failed')return 'failed';
  const known={{evidence_ready:'ready',processing:'processing',queued:'queued',precheck_complete:'legacy',uploaded_pending_worker:'legacy'}};
  return known[task.analysis_status]||(task.upload_status==='completed'?'uploaded':task.upload_status==='uploading'||task.analysis_status==='waiting_upload'?'uploading':'unknown');
}}
function renderTasks() {{
  const received=Array.isArray(workspace?.tasks)?workspace.tasks:[];
  const query=byId('taskSearch').value.trim().toLocaleLowerCase();
  const statusFilter=byId('taskStatusFilter').value;
  const tasks=received.filter(task=>(!statusFilter||taskFilterKey(task)===statusFilter)&&(!query||[task.original_filename,task.filename,task.task_id].some(value=>String(value??'').toLocaleLowerCase().includes(query))));
  byId('clearTaskFilters').disabled=!byId('taskSearch').value&&!statusFilter;
  byId('taskResultCount').textContent=workspace?`课程 ${{workspace.course_id||''}} · 显示 ${{tasks.length}} / 已加载 ${{received.length}} 个任务${{taskRefreshError?'（上次成功读取）':''}}`:'尚未加载课程任务';
  if(!tasks.length) {{
    const empty=!workspace?(taskRefreshError?'任务读取失败，请重新读取课程工作区。':'输入课程批次号并读取工作区后，这里会显示该课程的真实任务。'):received.length?'没有匹配的任务。请更换关键词或清除筛选。':taskRefreshError?'上次读取时没有任务，当前状态未确认，请刷新重试。':'该课程在当前账号通道下还没有上传任务。';
    byId('taskList').innerHTML=`<div class="empty-state">${{empty}}</div>`;return;
  }}
  const html=tasks.map(task=>{{
    const status=taskStatus(task); const progress=Number(task.progress_percent||0); const resultUrl=task.secure_result_download_url||task.result_download_url;
    const cancellable=task.upload_status==='uploading';
    const reviewUrl='/demo2/video?id='+encodeURIComponent(task.task_id||'');
    const expired=!!task.raw_media_deleted_at||['expired','deleted'].includes(task.analysis_status)||['expired','deleted'].includes(task.upload_status);
    const identityUrl='/demo2/identity?task_id='+encodeURIComponent(task.task_id||'');
    const identityAction=task.task_id&&task.analysis_status==='evidence_ready'&&!expired?`<a href="${{esc(identityUrl)}}">确认画面中的学生</a>`:'';
    const simpleResultAction=task.task_id&&task.analysis_status==='evidence_ready'&&!expired?`<a class="task-primary-action" href="/demo2/simple-result?task_id=${{encodeURIComponent(task.task_id)}}">查看学生状态结果</a>`:'';
    const teacherAction=task.task_id&&task.analysis_status==='evidence_ready'&&!expired?`<a href="/demo2/evaluation?task_id=${{encodeURIComponent(task.task_id)}}">教师评分</a>`:'';
    const analysisAction=task.task_id&&task.analysis_status==='evidence_ready'?`<a href="/demo2/analysis?task_id=${{encodeURIComponent(task.task_id)}}">课堂复核与报告</a>`:'';
    const action=cancellable?`<button type="button" data-resume-task="${{esc(task.task_id||'')}}">继续上传</button><button type="button" data-cancel-task="${{esc(task.task_id||'')}}">取消并释放名额</button>`:task.task_id&&task.upload_status!=='cancelled'?`${{simpleResultAction}}<a href="${{esc(reviewUrl)}}">${{expired?'查看保留记录':task.analysis_status==='evidence_ready'?'查看视频证据':'查看处理任务'}}</a>${{teacherAction}}${{identityAction}}${{analysisAction}}`:resultUrl?`<a href="${{esc(resultUrl)}}">下载记录</a>`:'';
    const processing=Math.max(0,Math.min(100,Number(task.processing_progress)||0));
    const finished=task.analysis_status==='evidence_ready';const uploaded=task.upload_status==='completed';
    const known=task.processing_progress!=null&&Number.isFinite(Number(task.processing_progress));
    const shownProgress=finished?100:uploaded?processing:progress;
    const progressLabel=expired?'原片不可播放':finished?'学生状态结果可查看':uploaded?(known?`处理 ${{processing}}%`:'等待处理记录'):`上传 ${{Math.max(0,Math.min(100,progress))}}%`;
    const failure=typeof task.processing_error==='object'?task.processing_error?.message:task.processing_error;
    const detail=expired?'原片与派生音轨不可用，仅展示接口保留的记录。':task.analysis_status==='failed'?(failure||'处理未完成，请打开任务查看原因或重新处理。'):task.analysis_status==='queued'?'已上传，正在排队；后台处理无需保持页面打开。':task.analysis_status==='processing'?'正在提取画面、声音与匿名人物状态，完成后可直接查看结果。':['precheck_complete','uploaded_pending_worker'].includes(task.analysis_status)?'旧版预检记录，请打开任务后点击“开始处理”。':finished?'已生成学生课堂状态时间片段，可直接查看。':'';
    return `<article class="task-row"><div class="task-main"><strong>${{esc(task.original_filename||task.filename||'未命名视频')}}</strong><span>${{formatBytes(task.byte_size)}} · 任务 <span class="mono">${{esc(task.task_id||'')}}</span></span><div class="mini-progress" aria-hidden="true"><i style="width:${{Math.max(0,Math.min(100,shownProgress))}}%"></i></div><span class="task-detail ${{task.analysis_status==='failed'?'task-error':''}}">${{esc(detail)}}</span></div><div class="task-meta"><span class="status-badge ${{status[1]}}">${{status[0]}}</span><span>${{esc(progressLabel)}}</span></div><div class="task-action">${{action}}</div></article>`;
  }}).join('');
  if(byId('taskList').innerHTML!==html) {{
    const focused=document.activeElement;const taskId=focused?.dataset?.cancelTask;const href=focused?.getAttribute('href');
    byId('taskList').innerHTML=html;
    if(taskId||href) [...byId('taskList').querySelectorAll('a,button')].find(node=>taskId?node.dataset.cancelTask===taskId:node.getAttribute('href')===href)?.focus({{preventScroll:true}});
  }}
  syncProcessingProgress();
}}
function syncProcessingProgress() {{
  if(!activeProcessingTaskId||uploadInProgress)return;
  const task=(workspace?.tasks||[]).find(item=>item.task_id===activeProcessingTaskId);
  if(!task)return;
  const status=task.analysis_status;
  if(status==='evidence_ready'||status==='completed') {{
    setProgress(100,'分析完成，正在打开学生状态结果');
    byId('transferDetails').textContent='视频与学生课堂状态分析已完成。';
    if(!processingRedirected) {{
      processingRedirected=true;
      window.setTimeout(()=>window.location.assign('/demo2/simple-result?task_id='+encodeURIComponent(activeProcessingTaskId)),250);
    }}
    return;
  }}
  if(status==='failed'||status==='cancelled') {{
    byId('progressLabel').textContent=status==='failed'?'后台分析失败':'任务已取消';
    byId('transferDetails').textContent=typeof task.processing_error==='object'?String(task.processing_error?.message||'请打开任务查看原因。'):'请打开任务查看原因。';
    return;
  }}
  if(task.upload_status==='completed' && !['queued','processing','uploaded_pending_worker','precheck_complete'].includes(status)) return;
  const backend=Number(task.processing_progress);
  const combined=90+(Number.isFinite(backend)?Math.max(0,Math.min(100,backend))*0.1:0);
  setProgress(combined,`上传完成，正在后台分析${{Number.isFinite(backend)?` · ${{Math.round(backend)}}%`:''}}`);
  byId('transferDetails').textContent='后台会继续处理，当前页面无需重复点击。';
}}
function renderStudents() {{
  const students=Array.isArray(workspace?.students)?workspace.students:[];
  const select=byId('studentSelect'); const previous=select.value;
  select.innerHTML='<option value="">暂不指定关注学生</option>'+students.map(item=>`<option value="${{esc(item.student_id||item.id)}}">${{esc([item.display_name||item.name||item.student_id,item.student_code?'编号 '+item.student_code:'未填编号',item.class_name||'未填班级'].join(' · '))}}</option>`).join('');
  if([...select.options].some(option=>option.value===previous)) select.value=previous;
}}
function renderChannels() {{
  let channels=Array.isArray(workspace?.channels)?workspace.channels:(workspace?.channel?[workspace.channel]:[]);
  if(!channels.length&&account?.bound_channel_id) channels=[{{channel_id:account.bound_channel_id,channel_name:channelLabel(account.bound_channel_id),status:'active'}}];
  const select=byId('channelSelect');
  const previous=select.value;
  select.innerHTML=channels.length?channels.map(item=>`<option value="${{esc(item.channel_id||'')}}">${{esc(item.channel_name||channelLabel(item.channel_id)||'未命名通道')}}</option>`).join(''):'<option value="">暂无可用通道</option>';
  const preferred=channels.find(item=>item.channel_id===previous)||channels.find(item=>item.channel_id===workspace?.selected_channel_id)||channels[0];
  if(preferred) select.value=preferred.channel_id;
  setAccount(account);
  updateUploadEnabled();
}}
function renderSecurityAcceptance() {{
  const acceptance=workspace?.latest_security_acceptance||workspace?.security_acceptance;
  const node=byId('latestSecurityAcceptance');
  if(!acceptance) {{ node.innerHTML='<strong>最近授权确认</strong><span>本课程尚未留存确认。</span>'; return; }}
  const time=acceptance.accepted_at||acceptance.confirmed_at||acceptance.created_at;
  const shownTime=time?new Date(time).toLocaleString('zh-CN',{{hour12:false}}):'接口未返回确认时间';
  node.innerHTML=`<strong>最近授权确认</strong><span>${{esc(shownTime)}} · 确认人：${{esc(acceptance.confirmed_by||'接口未返回')}} · 脱敏结果长期归档：${{acceptance.allow_company_archive?'已允许':'未允许'}}</span>`;
}}
async function loadWorkspace({{silent=false}}={{}}) {{
  const courseId=byId('courseId').value.trim();
  if(!courseId) {{ message('请先填写课程批次号。'); byId('courseId').focus(); return; }}
  const request=++workspaceRequest;clearTimeout(taskPollTimer);workspaceLoading=true;
  if(!silent)clearMessage(); byId('loadCourseButton').disabled=true;updateUploadEnabled();
  byId('taskPollStatus').textContent='正在刷新课程任务…';
  try {{
    const payload=await api(`${{API_ROUTES.workspace}}?course_id=${{encodeURIComponent(courseId)}}`);
    if(request!==workspaceRequest||byId('courseId').value.trim()!==courseId)return;
    if(!payload.workspace||!Array.isArray(payload.workspace.tasks))throw new Error('接口未返回课程工作区或任务列表，请稍后重试。');
    taskRefreshError='';
    workspace=payload.workspace||{{}}; setAccount(workspace.account||account); renderSlots(); renderChannels(); renderStudents(); renderSecurityAcceptance(); renderTasks();
    if(!uploadInProgress&&!silent) {{
      byId('uploadProgress').classList.remove('visible');
      setProgress(0,'准备上传'); byId('uploadProgress').classList.remove('visible');
      byId('filePreview').textContent=uploadHint();
    }}
    history.replaceState(null,'',`/demo2/upload?course_id=${{encodeURIComponent(courseId)}}`);
    updateUploadEnabled();
    scheduleTaskPoll();
  }} catch(error) {{ if(request===workspaceRequest){{ taskRefreshError=error.message;renderTasks();byId('taskPollStatus').textContent=error.message+(workspace?' 已保留上次成功读取的任务；当前状态未确认。':' 尚未取得任务状态。')+' 可重新读取课程工作区。';if(!silent)message(error.message); }} }} finally {{ if(request===workspaceRequest){{workspaceLoading=false;byId('loadCourseButton').disabled=uploadInProgress;updateUploadEnabled();}} }}
}}
function scheduleTaskPoll(delay=4000,announce=true) {{
  clearTimeout(taskPollTimer);
  if(!workspace||taskPollStopped)return;
  const waiting=(workspace.tasks||[]).some(task=>task.upload_status==='uploading'||task.analysis_status==='waiting_upload');
  const active=waiting||(workspace.tasks||[]).some(task=>['queued','processing'].includes(task.analysis_status)&&!task.raw_media_deleted_at);
  if(announce&&!taskRefreshError)byId('taskPollStatus').textContent=waiting?'视频尚未传完，上传或暂停期间请勿关闭、刷新或离开上传页面。':active?'后台处理每 4 秒自动更新。已完成上传的任务可离开页面，处理会继续。':'任务状态已更新；上传完成与证据就绪分开记录。';
  if(!active||document.hidden)return;
  taskPollTimer=setTimeout(async()=>{{
    if(workspace && !workspaceLoading && !taskPollBusy && !uploadInProgress && !document.hidden && !taskPollStopped) {{
      const course=String(workspace.course_id||'');
      if(byId('courseId').value.trim()!==course)return;
      const request=workspaceRequest;taskPollBusy=true;let failed=false;
      try {{
        const data=await api(`${{API_ROUTES.workspace}}?course_id=${{encodeURIComponent(course)}}`);
        if(request===workspaceRequest&&workspace?.course_id===course&&byId('courseId').value.trim()===course&&!taskPollStopped) {{
          if(!data.workspace||!Array.isArray(data.workspace.tasks))throw new Error('接口未返回课程任务。');
          taskRefreshError='';
          workspace=data.workspace;renderChannels();renderTasks();renderSlots();renderSecurityAcceptance();updateUploadEnabled();
        }}
      }} catch(error) {{
        failed=true;if(request===workspaceRequest){{taskRefreshError=error.message;renderTasks();byId('taskPollStatus').textContent=[401,403,404,410].includes(error.status)?error.message+' 已显示任务为上次成功读取的记录。':'任务更新暂时中断，已保留上次记录，5 秒后自动重试；也可点击“刷新任务”。';}}
        if([401,403,404,410].includes(error.status))return;
      }} finally {{ taskPollBusy=false; }}
      if(failed){{scheduleTaskPoll(5000,false);return;}}
    }}
    if(workspace&&!taskPollStopped) scheduleTaskPoll();
  }},delay);
}}
function setProgress(value,label) {{ const safe=Math.max(0,Math.min(100,Math.round(value))); byId('uploadProgress').classList.add('visible'); byId('progressBar').style.width=`${{safe}}%`; byId('progressPercent').textContent=`${{safe}}%`; byId('progressLabel').textContent=label; byId('uploadProgress').querySelector('[role="progressbar"]').setAttribute('aria-valuenow',String(safe)); }}
function transferProgress(s,loaded=0,label='正在上传，请勿关闭或刷新页面') {{
  const bytes=Math.min(s.file.size,s.acknowledged+loaded);
  const waiting=loaded>0&&loaded>=Math.min(CHUNK_SIZE,s.file.size-s.acknowledged);
  setProgress(Math.min(99,bytes*100/s.file.size),waiting&&!s.paused?'本分片已发出，等待服务器确认；请勿关闭或刷新页面':label);
  const elapsed=(performance.now()-s.speedBaseTime)/1000,confirmed=s.acknowledged-s.speedBaseBytes;
  const speed=!s.paused&&s.speedReady&&confirmed>0&&elapsed>=1?confirmed/elapsed:0;
  const seconds=speed>0?Math.ceil((s.file.size-s.acknowledged)/speed):null;
  const estimate=s.paused?'已暂停，不估算剩余时间':speed>0?`服务器确认均速 ${{formatBytes(speed)}}/秒 · 约剩 ${{Math.ceil(seconds/60)}} 分钟`:'正在测速，等待服务器确认';
  byId('transferDetails').textContent=`已确认 ${{formatBytes(s.acknowledged)}} / ${{formatBytes(s.file.size)}} · ${{estimate}}`;
}}
function transferControls(s) {{
  byId('pauseUploadButton').hidden=!s||s.paused;
  byId('resumeUploadButton').hidden=!s||!s.paused;
  byId('resumeUploadButton').disabled=!!s?.running;
  byId('filePreview').textContent=uploadHint();
}}
function pauseUpload() {{
  const s=uploadSession;if(!s)return;
  s.paused=true;s.xhr?.abort();s.wake?.();transferControls(s);
  transferProgress(s,0,'已暂停，已确认进度保留；请勿关闭或刷新页面');
}}
function reflectUploadTask(task,created=false) {{
  if(!workspace||workspace.course_id!==task.course_id)return;
  const tasks=Array.isArray(workspace.tasks)?workspace.tasks:[];
  const index=tasks.findIndex(item=>item.task_id===task.task_id);
  if(index<0){{
    tasks.push(task);if(created){{workspace.used_slots=Number(workspace.used_slots||0)+1;
    workspace.remaining_slots=Math.max(0,Number(workspace.remaining_slots||0)-1);}}
  }}else tasks[index]={{...tasks[index],...task}};
  workspace.tasks=tasks;renderTasks();renderSlots();updateUploadEnabled();
}}
function acceptUploadTask(s,task) {{
  const next=task?.next_chunk_index, received=task?.received_bytes;
  if(!task||task.task_id!==s.taskId||task.course_id!==s.courseId||task.byte_size!==s.file.size||
     !Number.isInteger(next)||next<s.next||next>s.sentThrough||next>s.total||
     received!==Math.min(next*CHUNK_SIZE,s.file.size)||
     !['uploading','completed'].includes(task.upload_status)||task.raw_media_deleted_at||
     (task.upload_status==='completed'&&next!==s.total)) {{
    const error=new Error('上传状态不一致或任务已失效，已暂停并保留本页文件，请联系项目方核查。');error.status=409;throw error;
  }}
  s.next=next;s.acknowledged=received;s.completed=task.upload_status==='completed';
  reflectUploadTask(task);
  transferProgress(s);return task;
}}
async function reconcileUpload(s) {{
  const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),20000);
  try {{const payload=await api(`${{API_ROUTES.task}}?id=${{encodeURIComponent(s.taskId)}}`,{{cache:'no-store',signal:controller.signal}});return acceptUploadTask(s,payload.task);}}
  finally {{clearTimeout(timeout);}}
}}
function sendBinaryChunk(s) {{
  const index=s.next,chunk=s.file.slice(index*CHUNK_SIZE,Math.min(s.file.size,(index+1)*CHUNK_SIZE));
  s.sentThrough=Math.max(s.sentThrough,index+1);
  return new Promise((resolve,reject)=>{{
    const xhr=new XMLHttpRequest();s.xhr=xhr;
    const fail=(text,status=0)=>{{const error=new Error(text);error.status=status;reject(error);}};
    xhr.open('POST',`${{API_ROUTES.chunks}}?task_id=${{encodeURIComponent(s.taskId)}}&course_id=${{encodeURIComponent(s.courseId)}}&chunk_index=${{index}}`);
    xhr.withCredentials=true;xhr.timeout=180000;xhr.setRequestHeader('Content-Type','application/octet-stream');
    xhr.upload.onprogress=event=>{{if(!s.paused)transferProgress(s,Math.min(event.loaded,chunk.size));}};
    xhr.onload=()=>{{let payload;try{{payload=JSON.parse(xhr.responseText);}}catch(_){{fail('服务器响应未确认，正在核对进度。',xhr.status);return;}}
      if(xhr.status<200||xhr.status>=300||payload.error){{fail(payload.error?.message||'上传请求未完成。',xhr.status);return;}}resolve(payload.task);}};
    xhr.onerror=()=>fail('网络中断，已确认进度保留。');xhr.ontimeout=()=>fail('上传超时，正在核对已收分片。');xhr.onabort=()=>fail('上传已暂停。');
    xhr.onloadend=()=>{{if(s.xhr===xhr)s.xhr=null;}};xhr.send(chunk);
  }});
}}
function retryDelay(s,attempt) {{return new Promise(resolve=>{{const timer=setTimeout(done,Math.min(16000,1000*2**(attempt-1))*(.8+Math.random()*.4));function done(){{clearTimeout(timer);s.wake=null;resolve();}}s.wake=done;}});}}
async function runUpload(s) {{
  if(s.running)return;s.running=true;s.paused=false;clearMessage();transferControls(s);
  s.speedBaseBytes=s.acknowledged;s.speedBaseTime=performance.now();s.speedReady=false;transferProgress(s);
  let failures=0,needsReconcile=true;
  try {{
    while(!s.paused&&!s.completed) {{
      try {{
        const before=s.next;
        if(needsReconcile){{
          await reconcileUpload(s);needsReconcile=false;if(s.next>before)failures=0;
          // The first reconciliation may acknowledge a previous run's bytes.
          if(!s.speedReady){{s.speedBaseBytes=s.acknowledged;s.speedBaseTime=performance.now();s.speedReady=true;transferProgress(s);}}
        }}
        if(s.paused||s.completed)break;
        if(s.next>=s.total)throw new Error('所有分片已接收，正在确认完成状态。');
        const index=s.next;
        acceptUploadTask(s,await sendBinaryChunk(s));
        if(s.next<=index)throw new Error('分片尚未确认接收。');
        failures=0;
      }} catch(error) {{
        if(s.paused)break;
        needsReconcile=true;failures+=1;
        if([400,401,403,404,409,410,413,415,422].includes(error.status)||failures>4)throw error;
        transferProgress(s,0,`连接暂时中断，正在核对进度并重试（${{failures}}/4）；请勿关闭页面`);
        await retryDelay(s,failures);
      }}
    }}
    if(s.paused){{try{{await reconcileUpload(s);}}catch(_){{}}if(!s.completed)transferProgress(s,0,'已暂停，已确认进度保留；请勿关闭或刷新页面');}}
    if(s.completed) {{
      setProgress(100,'上传完成，等待后台处理');byId('transferDetails').textContent=`已确认 ${{formatBytes(s.file.size)}}`;
      uploadSession=null;setUploadBusy(false);transferControls(null);
      byId('videoFile').value='';byId('selectedFileName').textContent='尚未选择视频';byId('allowCompanyArchive').value='no';
      byId('filePreview').textContent='如需继续上传，请重新选择视频并确认授权。';
      const finishedTaskId=s.taskId;activeProcessingTaskId=finishedTaskId;processingRedirected=false;
      await loadWorkspace({{silent:true}});message('视频已上传，正在后台分析；分析完成后会自动打开学生状态结果。','success');
      syncProcessingProgress();scheduleTaskPoll(1500,false);
    }}
  }} catch(error) {{
    s.paused=true;transferProgress(s,0,'上传已暂停，已确认进度保留；请勿关闭或刷新页面');
    message(`${{error.status===401?'登录已过期，请在另一标签页重新登录。':error.message}} 网络恢复后点击“继续上传”，不会重新创建任务。`);
  }} finally {{s.running=false;if(uploadSession===s)transferControls(s);scheduleTaskPoll();}}
}}
function chooseResumeFile(taskId) {{
  if(uploadInProgress){{if(uploadSession?.taskId===taskId&&uploadSession.paused)runUpload(uploadSession);return;}}
  if(!globalThis.crypto?.subtle){{message('当前浏览器无法安全校验续传文件。请使用 HTTPS 入口和支持 WebCrypto 的浏览器；本页只能新建上传，不能跳过旧文件校验。');return;}}
  resumeTaskId=taskId;byId('resumeVideoFile').value='';byId('resumeVideoFile').click();
}}
async function resumeSelectedFile() {{
  const taskId=resumeTaskId,file=byId('resumeVideoFile').files[0];resumeTaskId=null;
  if(!taskId||!file||uploadInProgress)return;
  setUploadBusy(true);clearTimeout(taskPollTimer);clearMessage();
  try {{
    if(!globalThis.crypto?.subtle)throw new Error('当前浏览器不支持安全续传校验，请使用支持 WebCrypto 的 HTTPS 入口。');
    const payload=await api(`${{API_ROUTES.task}}?id=${{encodeURIComponent(taskId)}}`,{{cache:'no-store'}}),task=payload.task;
    const next=task?.next_chunk_index,received=task?.received_bytes;
    if(!task||task.task_id!==taskId||task.upload_status!=='uploading'||task.raw_media_deleted_at||
       task.course_id!==String(workspace?.course_id||'')||file.name!==(task.original_filename||task.filename)||file.size!==task.byte_size||
       !Number.isInteger(next)||next<0||next>Math.ceil(file.size/CHUNK_SIZE)||received!==Math.min(next*CHUNK_SIZE,file.size))
      throw new Error('请选择该任务原来的视频文件，文件名、大小和上传状态必须一致。未创建新任务。');
    const hashes=[];
    for(let index=0;index<next;index++){{
      setProgress(Math.min(99,received*100/file.size),`正在校验原文件已收分片 ${{index+1}}/${{next}}，请勿关闭页面`);
      const buffer=await file.slice(index*CHUNK_SIZE,Math.min(file.size,(index+1)*CHUNK_SIZE)).arrayBuffer();
      const digest=await crypto.subtle.digest('SHA-256',buffer);
      hashes.push(Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join(''));
    }}
    const verified=await api(API_ROUTES.resume,{{method:'POST',timeoutMs:60000,headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{task_id:taskId,course_id:task.course_id,byte_size:file.size,filename:file.name,chunk_sha256:hashes}})}});
    const s={{file,courseId:task.course_id,taskId,total:Math.ceil(file.size/CHUNK_SIZE),next,sentThrough:next,acknowledged:received,paused:false,running:false,completed:false}};
    acceptUploadTask(s,verified.task);uploadSession=s;
    byId('selectedFileName').textContent=file.name;await runUpload(s);
  }}catch(error){{message(error.message+' 原任务与已确认进度保留，未新建上传任务。');}}
  finally{{byId('resumeVideoFile').value='';if(!uploadSession)setUploadBusy(false);scheduleTaskPoll();}}
}}
async function uploadVideo() {{
  if(uploadInProgress)return;
  if(schoolState!=='ready')return message(schoolUploadHint());
  const file=byId('videoFile').files[0]; const courseId=byId('courseId').value.trim(); const courseName=byId('courseName').value.trim(); const channelId=byId('channelSelect').value.trim();
  if(!workspace) return message('请先读取课程工作区。');
  if(!channelId) return message('暂无可用上传通道，请联系管理员配置。');
  if(!file) return message('请选择要上传的视频。');
  const extension=file.name.includes('.')?file.name.slice(file.name.lastIndexOf('.')).toLowerCase():'';
  if(!ALLOWED_VIDEO_EXTENSIONS.includes(extension)) return message('新上传仅支持 MP4、MOV 和 WebM；建议转换为 MP4（H.264 / AAC）。已有任务仍可选择原文件继续上传。');
  if(file.size<=0) return message('所选视频为空，请重新选择。');
  if(file.size>newVideoLimit()) return message(`测试阶段单文件不能超过 ${{newVideoLimit()===MAX_VIDEO_SIZE?'1 GiB':formatBytes(newVideoLimit())}}，请降低码率或裁剪为单节课后重试。`);
  if(courseId!==String(workspace.course_id||'').trim()) return message('课程批次号已修改，请重新读取课程工作区。');
  const selectionVersion=fileSelectionVersion,totalChunks=Math.ceil(file.size/CHUNK_SIZE);let createAttempted=false;
  setUploadBusy(true);clearTimeout(taskPollTimer);clearMessage();setProgress(0,'正在检查视频时长，尚未创建任务');
  try {{
    await preflightVideo(file);
    if(schoolState!=='ready')throw new Error(schoolUploadHint());
    if(fileSelectionVersion!==selectionVersion||byId('videoFile').files[0]!==file||byId('courseId').value.trim()!==courseId||String(workspace?.course_id||'')!==courseId)
      throw new Error('所选视频或课程已变化，请核对后重新点击上传。');
    if(file.size>newVideoLimit())throw new Error('当前课程上传大小上限已变化，请重新核对文件。');
    setProgress(0,'正在创建上传任务');createAttempted=true;
    const displayCourseName=courseName||'课堂视频分析';
    const created=await api(API_ROUTES.tasks,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{channel_id:channelId,uploader_name:account.username||'学校上传账号',course_id:courseId,course_name:displayCourseName,session_id:`${{courseId}}-${{new Date().toISOString().slice(0,10)}}`,subject_id:byId('studentSelect').value,filename:file.name,mime_type:file.type,byte_size:file.size,total_chunks:totalChunks,security_confirmed:true,allow_company_archive:byId('allowCompanyArchive').value==='yes'}})}});
    if(!created.task?.task_id)throw new Error('任务创建响应未确认，请先刷新任务列表核查，勿重复提交。');
    uploadSession={{file,courseId,taskId:created.task.task_id,total:totalChunks,next:0,sentThrough:0,acknowledged:0,paused:false,running:false,completed:false}};
    reflectUploadTask(created.task,true);
    await runUpload(uploadSession);
  }} catch(error) {{
    if(error.code==='school_context_required'){{schoolRequired();message(schoolUploadHint());byId('progressLabel').textContent='学校信息待补全，未创建任务';}}
    else{{message(createAttempted?`${{error.message}} 请先核对本课程任务列表，勿重复提交。`:error.message);if(createAttempted&&!uploadSession)await loadWorkspace({{silent:true}});if(!createAttempted)byId('progressLabel').textContent='上传条件检查未通过，未创建任务';}}
  }}
  finally {{if(!uploadSession)setUploadBusy(false);scheduleTaskPoll();}}
}}
async function cancelTask(taskId) {{
  if(!taskId || (uploadInProgress&&!(uploadSession?.taskId===taskId&&uploadSession.paused&&!uploadSession.running))) return;
  if(!window.confirm('确定取消这个未完成任务并释放一个上传名额吗？已上传分片会被删除。')) return;
  clearMessage();
  try {{ await api(API_ROUTES.cancel,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{task_id:taskId}})}});if(uploadSession?.taskId===taskId){{uploadSession=null;setUploadBusy(false);transferControls(null);}} await loadWorkspace({{silent:true}});message('未完成任务已取消，上传名额已释放。','success'); }}
  catch(error) {{ message(error.message); }}
}}
byId('loadCourseButton').addEventListener('click',loadWorkspace);
byId('reloadSchoolButton').addEventListener('click',loadSchoolContext);
byId('refreshTasksButton').addEventListener('click',()=>loadWorkspace({{silent:true}}));
byId('taskSearch').addEventListener('input',renderTasks);
byId('taskStatusFilter').addEventListener('change',renderTasks);
byId('clearTaskFilters').addEventListener('click',()=>{{byId('taskSearch').value='';byId('taskStatusFilter').value='';renderTasks();byId('taskSearch').focus();}});
byId('courseId').addEventListener('input',()=>{{
  clearTimeout(taskPollTimer);
  if(workspace && byId('courseId').value.trim()!==String(workspace.course_id||'').trim()) {{
    byId('filePreview').textContent='课程批次号已修改，请重新读取课程工作区。';
    byId('allowCompanyArchive').value='no';
    byId('uploadProgress').classList.remove('visible');
  }}
  updateUploadEnabled();
  renderTasks();
}});
byId('videoFile').addEventListener('change',()=>{{fileSelectionVersion+=1;const file=byId('videoFile').files[0];const description=file?`${{file.name}} · ${{formatBytes(file.size)}}`:'尚未选择视频';byId('selectedFileName').textContent=description;byId('filePreview').textContent=uploadHint();updateUploadEnabled();}});
byId('channelSelect').addEventListener('change',()=>{{setAccount(account);updateUploadEnabled();}});
byId('uploadButton').addEventListener('click',uploadVideo);
byId('pauseUploadButton').addEventListener('click',pauseUpload);
byId('resumeUploadButton').addEventListener('click',()=>{{if(uploadSession)runUpload(uploadSession);}});
byId('resumeVideoFile').addEventListener('change',resumeSelectedFile);
byId('taskList').addEventListener('click',event=>{{const resume=event.target.closest('[data-resume-task]');if(resume){{chooseResumeFile(resume.dataset.resumeTask);return;}}const button=event.target.closest('[data-cancel-task]');if(button)cancelTask(button.dataset.cancelTask);}});
byId('logoutButton').addEventListener('click',async()=>{{ try {{ await api(API_ROUTES.logout,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:'{{}}'}}); }} finally {{ window.location.assign('/demo2/login'); }} }});
window.addEventListener('beforeunload',event=>{{ if(!uploadInProgress) return; event.preventDefault(); event.returnValue=''; }});
window.addEventListener('pagehide',()=>{{taskPollStopped=true;clearTimeout(taskPollTimer);}});
window.addEventListener('pageshow',event=>{{if(event.persisted){{taskPollStopped=false;if(workspace)loadWorkspace({{silent:true}});}}}});
document.addEventListener('visibilitychange',()=>{{clearTimeout(taskPollTimer);if(!document.hidden&&!taskPollStopped&&workspace&&!uploadInProgress&&!workspaceLoading&&byId('courseId').value.trim()===String(workspace.course_id||''))loadWorkspace({{silent:true}});}});
const initialCourse=new URLSearchParams(location.search).get('course_id')||`demo2-${{new Date().toISOString().slice(0,10)}}`; byId('courseId').value=initialCourse;
setAccount(account); renderSlots();
let automaticWorkspaceStarted=false;
let identityReady=!!account?.role;
function loadAutomaticWorkspace() {{ if(automaticWorkspaceStarted||!identityReady||schoolState!=='ready')return; automaticWorkspaceStarted=true; loadWorkspace(); }}
loadSchoolContext().then(loadAutomaticWorkspace);
api(API_ROUTES.me).then(payload=>{{ setAccount(payload.account); identityReady=!!payload.account?.role; loadAutomaticWorkspace(); }}).catch(error=>message(error.message));
"""
    return _document(title="视频上传 · RehabAffect 学校内测平台", body=body, page_style=page_style, script=script)


def render_demo2_admin_html(account: Any | None = None) -> str:
    account_json = _account_payload(account)
    page_style = r"""
.metric-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; margin-bottom:20px; }
.metric-card { min-width:0; border:1px solid var(--line); border-radius:8px; padding:18px; background:#fff; }
.metric-card span { display:block; color:var(--muted); font-size:12px; }
.metric-card strong { display:block; margin-top:7px; color:var(--blue-deep); font:700 28px/1.2 Bahnschrift,"Segoe UI",sans-serif; overflow-wrap:anywhere; }
.metric-card small { display:block; margin-top:5px; color:var(--muted); }
.admin-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:20px; }
.admin-grid .wide { grid-column:1/-1; }
.entity-list { display:grid; gap:10px; }
.entity-row { display:flex; align-items:center; justify-content:space-between; gap:18px; min-width:0; padding:13px 0; border-bottom:1px solid var(--line); }
.entity-row:last-child { border-bottom:0; }
.entity-row > div { min-width:0; }
.entity-row strong,.entity-row span { display:block; overflow-wrap:anywhere; }
.entity-row span { color:var(--muted); font-size:12px; }
.status-columns { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }
.status-list { margin:10px 0 0; padding:0; list-style:none; }
.status-list li { display:flex; justify-content:space-between; gap:10px; padding:8px 0; border-bottom:1px solid var(--line); font-size:13px; }
.status-list li:last-child { border:0; }
.retention-band { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:1px; overflow:hidden; border:1px solid var(--line); border-radius:8px; background:var(--line); }
.retention-item { padding:18px; background:var(--blue-pale); }
.retention-item span { display:block; color:var(--muted); font-size:12px; }
.retention-item strong { display:block; margin-top:5px; color:var(--blue-deep); font-size:21px; }
.membership-overview { display:flex; flex-wrap:wrap; gap:12px 24px; margin-bottom:20px; padding:14px 16px; border:1px solid var(--line); border-radius:6px; background:var(--blue-pale); font-size:13px; overflow-wrap:anywhere; }
.membership-admin-section h3 { margin:24px 0 12px; font-size:16px; }
.membership-admin-section .card-head a { color:var(--blue); display:inline-flex; align-items:center; min-height:44px; }
.membership-admin-section table:has(tbody > tr:only-child > td[colspan]) { min-width:0; table-layout:fixed; }
.membership-admin-section table:has(tbody > tr:only-child > td[colspan]) thead { display:none; }
.membership-admin-section td[colspan] { white-space:normal; overflow-wrap:anywhere; }
.admin-refresh-status { min-height:20px; color:var(--muted); font-size:12px; overflow-wrap:anywhere; }
.upload-pagination { display:flex; flex-wrap:wrap; align-items:center; gap:12px; margin-top:16px; }
.upload-pagination .button { width:44px; height:44px; flex:0 0 44px; padding:0; font-size:20px; }
.upload-pagination span { min-width:0; color:var(--muted); font-size:13px; overflow-wrap:anywhere; }
@media (max-width:920px) { .metric-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } }
@media (max-width:720px) { .admin-grid { grid-template-columns:1fr; } .admin-grid .wide { grid-column:auto; } .status-columns { grid-template-columns:1fr; } }
@media (max-width:460px) { .metric-grid { grid-template-columns:1fr; } .retention-band { grid-template-columns:1fr; } }
"""
    body = f"""
<header class="site-header">
  <div class="header-inner">
    <a class="brand" href="/demo2/admin">{_BOOK_ICON}<span class="brand-copy"><strong>RehabAffect</strong><span>公司内测管理后台</span></span></a>
    <div class="header-actions">
      <div class="account-chip"><span>公司账号</span><strong id="accountName">读取中</strong></div>
      <a class="button quiet" href="/demo2/admin/measurements" aria-label="查看测量记录运营汇总"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19V9M10 19V5M16 19v-7M22 19V2"/></svg><span>测量记录汇总</span></a>
      <button class="button quiet" id="logoutButton" type="button" aria-label="退出登录"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M10 17l5-5-5-5M15 12H3"/><path d="M14 3h5a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-5"/></svg><span>退出</span></button>
    </div>
  </div>
</header>
<main class="page-shell" id="mainContent">
  <div class="page-heading"><div><span class="eyebrow">公司后台 · 只读运营总览</span><h1>学校内测运行状态</h1><p class="lead">账号、通道、课程名额、任务和存储数据全部来自后台汇总接口。</p></div><button class="button primary" id="refreshButton" type="button"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M20 11a8 8 0 1 0-2.3 5.7L20 19"/><path d="M20 13v6h-6"/></svg>刷新数据</button></div>
  <div class="page-message" id="pageMessage" role="alert" aria-live="assertive"></div>
  <p style="margin-bottom:20px"><a class="button" id="dossierAdminLink" href="/demo2/admin/dossiers">学生资料运行状态（仅元数据）</a> <a class="button" href="/demo2/admin/student-summaries">学生档案摘要库</a> <a class="button" href="/demo2/admin/measurements">测量记录与保存状态</a></p>
  <section class="metric-grid" aria-label="平台关键指标">
    <article class="metric-card"><span>学校上传账号</span><strong id="accountCount">--</strong><small>账号状态见下方明细</small></article>
    <article class="metric-card"><span>视频通道</span><strong id="channelCount">--</strong><small>绑定关系来自接口</small></article>
    <article class="metric-card"><span>任务总数</span><strong id="taskCount">--</strong><small>包含已完成、上传中和已取消</small></article>
    <article class="metric-card"><span>总存储</span><strong id="totalStorage">--</strong><small>数据库、资料、报告与视频任务</small></article>
  </section>
  <div class="admin-grid">
    <section class="card" aria-labelledby="accountTitle"><div class="card-head"><h2 id="accountTitle">4 账号 / 4 通道状态</h2><p>实际数量与状态按接口返回展示。</p></div><div class="card-body"><div class="entity-list" id="accountList"><div class="loading-line">正在读取账号状态…</div></div></div></section>
    <section class="card" aria-labelledby="channelTitle"><div class="card-head"><h2 id="channelTitle">通道运行状态</h2><p>账号绑定、通道状态和有效任务数量。</p><a class="button" id="manageChannelsLink" href="/demo2/admin/channels">管理上传通道</a></div><div class="card-body"><div class="entity-list" id="channelList"><div class="loading-line">正在读取通道状态…</div></div></div></section>
    <section class="card wide" aria-labelledby="schoolsTitle"><div class="card-head"><h2 id="schoolsTitle">账号所属学校</h2><p>公开名录与自填资料分开标记，不代表教师身份已认证。</p></div><div class="card-body"><div class="table-wrap"><table><thead><tr><th>账号</th><th>城市</th><th>区县</th><th>学校</th><th>地址</th><th>资料来源</th></tr></thead><tbody id="schoolContexts"><tr><td colspan="6">正在读取学校信息</td></tr></tbody></table></div></div></section>
    <section class="card wide membership-admin-section" aria-labelledby="membershipSummaryTitle"><div class="card-head"><h2 id="membershipSummaryTitle">会员与订单</h2><p>手机号注册账号与既有学校内测账号分开管理；仅显示会员接口返回记录，不将内测权限计为付费成功。</p><a href="/demo2/membership">查看当前账号会员中心</a></div><div class="card-body"><div class="membership-overview" id="membershipSummary" role="status">正在读取会员与支付服务状态…</div><h3 id="membershipAccountsTitle">注册会员</h3><div class="table-wrap"><table aria-labelledby="membershipAccountsTitle"><thead><tr><th>手机号</th><th>会员状态</th><th>有效期至</th><th>注册时间</th></tr></thead><tbody id="membershipAccounts"><tr><td colspan="4">正在读取注册会员…</td></tr></tbody></table></div><h3 id="membershipOrdersTitle">近期会员订单</h3><div class="table-wrap"><table aria-labelledby="membershipOrdersTitle"><thead><tr><th>订单号</th><th>所属账号</th><th>套餐</th><th>金额</th><th>状态</th><th>创建时间</th></tr></thead><tbody id="membershipOrdersSummary"><tr><td colspan="6">正在读取会员订单…</td></tr></tbody></table></div></div></section>
    <section class="card wide" aria-labelledby="registrationTitle"><div class="card-head"><h2 id="registrationTitle">历史学校开通申请</h2><p>保留旧版学校申请记录；不属于当前手机号注册与会员开通流程。</p></div><div class="card-body"><div class="table-wrap"><table><thead><tr><th>联系人</th><th>联系方式</th><th>地区</th><th>学校</th><th>申请时间</th><th>状态</th></tr></thead><tbody id="registrationRequests"><tr><td colspan="6">正在读取历史申请记录</td></tr></tbody></table></div></div></section>
    <section class="card wide" aria-labelledby="quotaTitle"><div class="card-head"><h2 id="quotaTitle">每课程名额使用</h2><p>按账号与课程拆分，避免不同上传主体或课程互相占用名额。</p></div><div class="card-body"><div class="table-wrap"><table><thead><tr><th>课程批次号</th><th>账号</th><th>已用</th><th>剩余</th><th>上限</th></tr></thead><tbody id="courseUsage"><tr><td colspan="5">正在读取课程名额…</td></tr></tbody></table></div></div></section>
    <section class="card" aria-labelledby="taskTitle"><div class="card-head"><h2 id="taskTitle">任务状态</h2><p>分别查看上传与后台处理状态。</p></div><div class="card-body"><div class="status-columns"><div><h3>上传状态</h3><ul class="status-list" id="uploadStatuses"></ul></div><div><h3>处理状态</h3><ul class="status-list" id="analysisStatuses"></ul></div></div></div></section>
    <section class="card" aria-labelledby="retentionTitle"><div class="card-head"><h2 id="retentionTitle">保存与到期提醒</h2><p>展示接口返回的保存、提醒与自动清理策略；原视频删除后保留结构化结果和审计记录。</p></div><div class="card-body"><div class="retention-band"><div class="retention-item"><span>保存周期</span><strong id="retentionDays">-- 天</strong></div><div class="retention-item"><span>提前提醒</span><strong id="reminderDays">-- 天</strong></div><div class="retention-item"><span>近期到期</span><strong id="dueSoonCount">--</strong></div><div class="retention-item"><span>到期处理</span><strong id="autoDeleteState">--</strong></div></div></div></section>
    <section class="card wide" aria-labelledby="acceptanceTitle"><div class="card-head"><h2 id="acceptanceTitle">近期安全授权确认</h2><p>显示接口返回的课程、确认人、确认时间与脱敏结果长期归档选择。</p></div><div class="card-body"><div class="table-wrap"><table><thead><tr><th>课程</th><th>确认人</th><th>确认时间</th><th>脱敏结果归档</th></tr></thead><tbody id="recentSecurityAcceptances"><tr><td colspan="4">正在读取安全授权记录…</td></tr></tbody></table></div></div></section>
    <section class="card wide" aria-labelledby="recentTitle"><div class="card-head"><h2 id="recentTitle">近期上传</h2><p>只列出后台接口返回的近期任务，不补造统计。</p><p class="admin-refresh-status" id="adminRefreshStatus" role="status" aria-live="polite">尚未更新</p></div><div class="card-body"><div class="table-wrap"><table><thead><tr><th>文件</th><th>账号 / 通道</th><th>课程</th><th>上传</th><th>处理</th><th>时间</th></tr></thead><tbody id="recentUploads"><tr><td colspan="6">正在读取近期上传…</td></tr></tbody></table></div><nav class="upload-pagination" aria-label="近期上传分页"><button class="button" id="previousUploads" type="button" aria-label="上一页" title="上一页" disabled>&larr;</button><span id="uploadPageStatus" role="status" aria-live="polite">正在读取分页信息</span><button class="button" id="nextUploads" type="button" aria-label="下一页" title="下一页" disabled>&rarr;</button></nav></div></section>
    <section class="card wide" aria-labelledby="reportsTitle"><div class="card-head"><h2 id="reportsTitle">课程报告</h2><p>教师课堂复核时自动留存的报告快照，按课程、任务与稳定报告ID关联；可下载 Markdown 或 JSON 留档。</p><p class="admin-refresh-status" id="reportsRefreshStatus" role="status" aria-live="polite">尚未更新</p></div><div class="card-body"><div class="table-wrap"><table><thead><tr><th>报告标题</th><th>课程</th><th>任务</th><th>所属账号</th><th>学生/记录/评价</th><th>生成时间</th><th>操作</th></tr></thead><tbody id="recentReports"><tr><td colspan="7">正在读取课程报告…</td></tr></tbody></table></div><nav class="upload-pagination" aria-label="课程报告分页"><button class="button" id="previousReports" type="button" aria-label="上一页" title="上一页" disabled>&larr;</button><span id="reportPageStatus" role="status" aria-live="polite">正在读取分页信息</span><button class="button" id="nextReports" type="button" aria-label="下一页" title="下一页" disabled>&rarr;</button></nav></div></section>
  </div>
</main>"""
    script = f"""
const API_PREFIX='{_API_PREFIX}';
const API_ROUTES={{me:'{_API_PREFIX}/auth/me',summary:'{_API_PREFIX}/admin/summary',memberships:'{_API_PREFIX}/admin/memberships',reports:'{_API_PREFIX}/admin/reports',reportDownload:'{_API_PREFIX}/reports/download',logout:'{_API_PREFIX}/auth/logout'}};
const SERVER_ACCOUNT={account_json};
const byId=id=>document.getElementById(id);
const ADMIN_REFRESH_MS=30000,ADMIN_MAX_BACKOFF_MS=300000;
let adminPollTimer=null,adminRefreshing=false,adminPollFailures=0,adminPollStopped=false;
let adminLastUpdated='',adminNextRefreshAt=0,adminInitialLoaded=false,adminUploadPage=1,adminUploadPages=1,adminReportPage=1,adminReportPages=1;
const adminPageVisible=()=>document.visibilityState==='visible';
const esc=value=>String(value??'').replace(/[&<>\"']/g,char=>({{'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}}[char]));
const formatBytes=value=>{{const bytes=Number(value||0);if(bytes<1024)return `${{bytes}} B`;if(bytes<1048576)return `${{(bytes/1024).toFixed(1)}} KB`;if(bytes<1073741824)return `${{(bytes/1048576).toFixed(1)}} MB`;return `${{(bytes/1073741824).toFixed(2)}} GB`;}};
const formatTime=value=>{{if(!value)return '未返回';const date=new Date(value);return Number.isNaN(date.getTime())?String(value):date.toLocaleString('zh-CN',{{hour12:false}});}};
const STATUS_LABELS={{active:'启用',inactive:'停用',completed:'已完成',uploaded_pending_worker:'历史预检',uploading:'上传中',failed:'处理失败',cancelled:'已取消',deleted:'已清理',precheck_complete:'历史预检',pending:'待处理',expired:'已到期',queued:'等待处理',processing:'后台处理中',evidence_ready:'证据已就绪'}};
const statusLabel=value=>STATUS_LABELS[String(value||'')]||String(value||'未返回');
function message(text,type='error'){{const node=byId('pageMessage');node.textContent=text;node.className=`page-message visible ${{type}}`;}}
async function api(url,options={{}}){{
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),10000);
  try{{
    const response=await fetch(url,{{credentials:'same-origin',...options,signal:controller.signal}});
    const payload=await response.json().catch(error=>{{if(error.name==='AbortError'||error instanceof TypeError)throw error;return {{}};}});
    if(response.status===401){{stopAdminPolling();try{{sessionStorage.setItem('demo2_notice','登录状态已过期，请重新登录。');}}catch(_){{}}window.location.assign('/demo2/login');throw new Error('登录已过期，正在返回登录页。');}}
    if(response.status===403){{stopAdminPolling();throw new Error('当前账号没有公司后台访问权限，请使用项目方授权的公司账号。');}}
    if(!response.ok||payload.error)throw new Error(payload.error?.message||'后台数据读取失败。');
    return payload;
  }}catch(error){{if(error.name==='AbortError')throw new Error('请求超时，请点击“刷新数据”重试。');if(error instanceof TypeError)throw new Error('网络连接失败，请检查网络后重试。');throw error;}}finally{{clearTimeout(timer);}}
}}
function badge(status){{const value=String(status||'未返回');const kind=['active','completed','precheck_complete'].includes(value)?'success':['inactive','failed','expired'].includes(value)?'danger':'warning';return `<span class="status-badge ${{kind}}">${{esc(statusLabel(value))}}</span>`;}}
function renderPairs(target,data){{const entries=Object.entries(data||{{}});byId(target).innerHTML=entries.length?entries.map(([key,value])=>`<li><span>${{esc(statusLabel(key))}}</span><strong>${{esc(value)}}</strong></li>`).join(''):'<li><span>接口未返回状态项</span><strong>0</strong></li>';}}
function storageTotal(storage){{return Object.values(storage||{{}}).reduce((sum,item)=>sum+Number(item?.byte_size||0),0);}}
function renderSummary(summary){{
  const requests=Array.isArray(summary.registration_requests)?summary.registration_requests:[];
  byId('registrationRequests').innerHTML=requests.length?requests.map(item=>`<tr><td>${{esc(item.name)}}</td><td>${{esc(item.contact)}}</td><td>${{esc([item.city,item.district].filter(Boolean).join(' / '))}}</td><td>${{esc(item.school_name)}}</td><td>${{esc(formatTime(item.created_at))}}</td><td><span class="status-badge warning">${{item.status==='pending'?'待审核':esc(item.status)}}</span></td></tr>`).join(''):'<tr><td colspan="6">暂无历史学校开通申请。</td></tr>';
  const schools=Array.isArray(summary.school_contexts)?summary.school_contexts:[];
  byId('schoolContexts').innerHTML=schools.length?schools.map(item=>{{const d=item.selection_details||{{}};const publicSource=d.source_status==='public_source';return `<tr><td>${{esc(item.login_alias||item.username||item.account_id)}}</td><td>${{esc(item.city)}}</td><td>${{esc(item.district)}}</td><td>${{esc(item.school_name)}}</td><td>${{esc(d.address||'未收录')}}</td><td>${{publicSource?'公开名录（非教师认证）':'待核实'}}${{d.source_url&&/^https:\/\//.test(d.source_url)?`<br><a href="${{esc(d.source_url)}}" target="_blank" rel="noopener noreferrer">公开来源</a>`:''}}</td></tr>`;}}).join(''):'<tr><td colspan="6">上传账号尚未填写学校信息。</td></tr>';
  const accounts=Array.isArray(summary.upload_accounts)?summary.upload_accounts:[];const channels=Array.isArray(summary.channels)?summary.channels:[];const usage=Array.isArray(summary.course_usage)?summary.course_usage:[];const retention=summary.retention||{{}};
  byId('accountList').innerHTML=accounts.length?accounts.map(item=>`<div class="entity-row"><div><strong>${{esc(item.login_alias||item.username||item.account_id)}}</strong><span>绑定 ${{esc(item.bound_channel_id||'未绑定')}} · 每课程 ${{esc(item.course_upload_limit??'--')}} 个名额</span></div>${{badge(item.status)}}</div>`).join(''):'<div class="empty-state">接口未返回学校上传账号。</div>';
  byId('channelList').innerHTML=channels.length?channels.map(item=>`<div class="entity-row"><div><strong>${{esc(item.channel_name||item.channel_id)}}</strong><span>${{esc(item.username||'未绑定账号')}} · ${{esc(item.task_count??0)}} 个有效任务</span></div>${{badge(item.status||item.account_status)}}</div>`).join(''):'<div class="empty-state">接口未返回视频通道。</div>';
  byId('courseUsage').innerHTML=usage.length?usage.map(item=>`<tr><td class="mono">${{esc(item.course_id)}}</td><td>${{esc(item.username||item.account_id)}}</td><td>${{esc(item.used_slots)}}</td><td>${{esc(item.remaining_slots)}}</td><td>${{esc(item.max_slots)}}</td></tr>`).join(''):'<tr><td colspan="5">接口未返回课程名额记录。</td></tr>';
  byId('retentionDays').textContent=retention.raw_media_retention_days==null?'未返回':`${{retention.raw_media_retention_days}} 天`;byId('reminderDays').textContent=retention.expiry_reminder_days==null?'未返回':`${{retention.expiry_reminder_days}} 天`;byId('dueSoonCount').textContent=retention.due_soon_count==null?'未返回':String(retention.due_soon_count);byId('autoDeleteState').textContent=retention.auto_delete===true?'自动清理':retention.auto_delete===false?'人工处理':'未返回';
  const acceptances=Array.isArray(summary.recent_security_acceptances)?summary.recent_security_acceptances:[];
  byId('recentSecurityAcceptances').innerHTML=acceptances.length?acceptances.map(item=>`<tr><td>${{esc(item.course_name||item.course_id||'接口未返回课程')}}</td><td>${{esc(item.confirmed_by||'接口未返回')}}</td><td>${{esc(formatTime(item.accepted_at||item.confirmed_at||item.created_at))}}</td><td>${{item.allow_company_archive?'已允许':'未允许'}}</td></tr>`).join(''):'<tr><td colspan="4">接口未返回近期安全授权确认。</td></tr>';
  renderActivitySummary(summary);
}}
// Timer and page navigation never replace account/channel panels or editor forms.
function renderActivitySummary(summary){{
  const accounts=Array.isArray(summary.upload_accounts)?summary.upload_accounts:[],channels=Array.isArray(summary.channels)?summary.channels:[],taskStatus=summary.task_status||{{}};
  byId('accountCount').textContent=String(accounts.length);byId('channelCount').textContent=String(channels.length);byId('taskCount').textContent=String(taskStatus.total??0);byId('totalStorage').textContent=formatBytes(storageTotal(summary.storage));
  renderPairs('uploadStatuses',taskStatus.by_upload_status);renderPairs('analysisStatuses',taskStatus.by_analysis_status);
  const recent=Array.isArray(summary.recent_uploads)?summary.recent_uploads:[];
  byId('recentUploads').innerHTML=recent.length?recent.map(task=>`<tr><td><a href="/demo2/video?id=${{encodeURIComponent(task.task_id||'')}}">${{esc(task.original_filename||task.filename||task.task_id||'接口未返回文件名')}}</a></td><td>${{esc(task.username||task.account_id||'未返回')}} / ${{esc(task.channel_id||'未返回')}}</td><td>${{esc(task.course_name||task.course_id||'未返回')}}</td><td>${{esc(statusLabel(task.upload_status))}}</td><td>${{esc(statusLabel(task.analysis_status))}}</td><td>${{esc(formatTime(task.created_at||task.updated_at))}}</td></tr>`).join(''):'<tr><td colspan="6">汇总接口暂未返回近期上传明细。</td></tr>';
  const pagination=summary.upload_pagination;
  if(pagination&&Number.isInteger(pagination.page)&&pagination.page>=1&&Number.isInteger(pagination.total_pages)&&pagination.total_pages>=0&&Number.isInteger(pagination.total)&&pagination.total>=0){{
    adminUploadPage=pagination.page;adminUploadPages=Math.max(1,pagination.total_pages);
    byId('uploadPageStatus').textContent=`共 ${{pagination.total}} 条 · 第 ${{adminUploadPage}} / ${{adminUploadPages}} 页`;
  }}else{{adminUploadPages=adminUploadPage;byId('uploadPageStatus').textContent='分页信息暂不可用';}}
  updateAdminControls();
}}
async function downloadReport(reportId,fmt){{
  const response=await fetch(`${{API_ROUTES.reportDownload}}?report_id=${{encodeURIComponent(reportId)}}&fmt=${{fmt}}`,{{credentials:'same-origin',cache:'no-store'}});
  if(response.status===401){{window.location.assign('/demo2/login');throw new Error('登录已过期，正在返回登录页。');}}
  if(!response.ok){{const payload=await response.json().catch(()=>null);throw new Error(payload?.error?.message||'报告下载失败。');}}
  const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');
  link.href=url;link.download=fmt==='json'?`report_${{reportId}}.json`:`report_${{reportId}}.md`;
  document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}}
function renderReports(){{
  return api(`${{API_ROUTES.reports}}?page=${{adminReportPage}}`,{{cache:'no-store'}}).then(payload=>{{
    const reports=Array.isArray(payload.reports)?payload.reports:[];
    byId('recentReports').innerHTML=reports.length?reports.map(item=>{{
      const counts=[item.student_count==null?'-':item.student_count+' 生',item.record_count==null?'-':item.record_count+' 条',item.evaluation_count==null?'-':item.evaluation_count+' 评'].join(' / ');
      return `<tr><td><strong>${{esc(item.title||'课堂观察与学习支持报告')}}</strong><br><span class="mono">${{esc(item.report_id||'')}}</span></td><td>${{esc(item.course_name||item.course_id||'未返回')}}</td><td><a href="/demo2/video?id=${{encodeURIComponent(item.task_id||'')}}">${{esc(item.task_id||'未返回')}}</a></td><td>${{esc(item.owner_username||'未返回')}}</td><td>${{esc(counts)}}</td><td>${{esc(formatTime(item.generated_at))}}</td><td><button class="button quiet" type="button" data-report-download="${{esc(item.report_id)}}" data-fmt="md">下载 MD</button> <button class="button quiet" type="button" data-report-download="${{esc(item.report_id)}}" data-fmt="json">下载 JSON</button></td></tr>`;
    }}).join(''):'<tr><td colspan="7">还没有已保存的课程报告。教师完成课堂复核后会自动留存报告快照。</td></tr>';
    const pagination=payload.pagination;
    if(pagination&&Number.isInteger(pagination.page)&&pagination.page>=1&&Number.isInteger(pagination.total_pages)){{
      adminReportPage=pagination.page;adminReportPages=Math.max(1,pagination.total_pages);
      byId('reportPageStatus').textContent=`共 ${{pagination.total}} 份 · 第 ${{adminReportPage}} / ${{adminReportPages}} 页`;
    }}else{{adminReportPages=adminReportPage;byId('reportPageStatus').textContent='分页信息暂不可用';}}
    byId('reportsRefreshStatus').textContent=`最近更新：${{formatTime(new Date().toISOString())}}`;
    updateAdminControls();
  }}).catch(error=>{{
    byId('recentReports').innerHTML='<tr><td colspan="7">报告读取失败：'+esc(error.message)+'</td></tr>';
    byId('reportsRefreshStatus').textContent='报告读取失败，请点击“刷新数据”重试。';
    throw error;
  }});
}}
document.addEventListener('click',event=>{{
  const button=event.target.closest('[data-report-download]');
  if(button){{downloadReport(button.dataset.reportDownload,button.dataset.fmt||'md').catch(error=>message(error.message));}}
}});
const membershipMoney=cents=>typeof cents==='number'&&Number.isInteger(cents)&&cents>=0?`¥${{(cents/100).toFixed(2)}}`:'待公布';
const memberLabel=item=>item.status_label||({{inactive:'未开通',active:'已开通',expired:'已到期',suspended:'已暂停',internal_trial:'内测账号'}}[item.status]||'状态待确认');
const orderLabel=item=>item.status_label||({{pending:'待支付',pending_payment:'待支付',paid:'已支付',completed:'已完成',cancelled:'已取消',expired:'已关闭',closed:'已关闭',failed:'支付未完成',refunded:'已退款'}}[item.status]||'状态待确认');
function renderMembershipSummary(summary){{
  const members=Array.isArray(summary.members)?summary.members:null,orders=Array.isArray(summary.orders)?summary.orders:null;
  const sms=summary.sms_available===true?'已配置':summary.sms_available===false?'暂未配置':'接口未返回';const payment=summary.payment_available===true?'已配置':summary.payment_available===false?'暂未配置，不可付款':'接口未返回';
  byId('membershipSummary').innerHTML=`<span>短信服务：${{esc(sms)}}</span><span>支付服务：${{esc(payment)}}</span><span>本次返回会员：${{members?members.length:'未返回'}}</span><span>本次返回近期订单：${{orders?orders.length:'未返回'}}</span>`;
  byId('membershipAccounts').innerHTML=members?.length?members.map(item=>`<tr><td>${{esc(item.phone_masked||'未绑定手机号')}}</td><td>${{esc(memberLabel(item))}}</td><td>${{esc(item.expires_at?formatTime(item.expires_at):'尚无有效期')}}</td><td>${{esc(formatTime(item.created_at))}}</td></tr>`).join(''):`<tr><td colspan="4">${{members?'暂无注册会员。':'接口未返回会员记录，请刷新数据。'}}</td></tr>`;
  const phones=new Map((members||[]).map(item=>[item.account_id,item.phone_masked]));
  byId('membershipOrdersSummary').innerHTML=orders?.length?orders.map(item=>`<tr><td class="mono">${{esc(item.order_id||'未返回')}}</td><td>${{esc(item.phone_masked||phones.get(item.account_id)||item.account_id||'未返回')}}</td><td>${{esc(item.plan_name||item.plan_id||'未返回')}}</td><td>${{esc(membershipMoney(item.amount_cents??item.price_cents))}}</td><td>${{esc(orderLabel(item))}}</td><td>${{esc(formatTime(item.created_at))}}</td></tr>`).join(''):`<tr><td colspan="6">${{orders?'暂无会员订单；不会将注册或内测使用算作付费成功。':'接口未返回订单记录，请刷新数据。'}}</td></tr>`;
}}
function membershipUnavailable(error){{byId('membershipSummary').textContent=`会员与订单暂时无法读取：${{error.message}}`;byId('membershipAccounts').innerHTML='<tr><td colspan="4">会员记录读取失败，请刷新数据重试。</td></tr>';byId('membershipOrdersSummary').innerHTML='<tr><td colspan="6">订单记录读取失败，不能据此判断没有订单。</td></tr>';}}
function updateAdminControls(){{
  byId('refreshButton').disabled=adminRefreshing;
  byId('previousUploads').disabled=adminRefreshing||adminPollStopped||adminUploadPage<=1;
  byId('nextUploads').disabled=adminRefreshing||adminPollStopped||adminUploadPage>=adminUploadPages;
  byId('previousReports').disabled=adminRefreshing||adminPollStopped||adminReportPage<=1;
  byId('nextReports').disabled=adminRefreshing||adminPollStopped||adminReportPage>=adminReportPages;
}}
function stopAdminPolling(){{adminPollStopped=true;clearTimeout(adminPollTimer);adminPollTimer=null;}}
function adminRefreshStatus(failed=false){{
  const last=adminLastUpdated?`最近更新：${{formatTime(adminLastUpdated)}}`:'尚未更新';
  byId('adminRefreshStatus').textContent=failed?`${{last}} · 暂时无法更新`:last;
}}
function scheduleAdminRefresh(){{
  clearTimeout(adminPollTimer);adminPollTimer=null;
  if(adminPollStopped||adminRefreshing||!adminPageVisible())return;
  adminPollTimer=setTimeout(()=>refresh({{partial:true,automatic:true}}),Math.max(0,adminNextRefreshAt-Date.now()));
}}
async function refresh({{partial=false,automatic=false,page=adminUploadPage}}={{}}){{
  if(adminRefreshing||adminPollStopped||(automatic&&!adminPageVisible()))return;
  clearTimeout(adminPollTimer);adminPollTimer=null;adminRefreshing=true;adminInitialLoaded=true;updateAdminControls();
  if(!partial)byId('pageMessage').className='page-message';
  const loadSummary=async()=>{{
    const payload=await api(`${{API_ROUTES.summary}}?upload_page=${{page}}`,{{cache:'no-store'}});
    if(!payload.summary||typeof payload.summary!=='object'||Array.isArray(payload.summary))throw new Error('后台汇总数据格式不完整。');
    if(adminPollStopped||(automatic&&!adminPageVisible()))return;
    if(partial)renderActivitySummary(payload.summary);else renderSummary(payload.summary);
    adminPollFailures=0;adminLastUpdated=new Date().toISOString();adminRefreshStatus();
  }};
  const summaryFailed=()=>{{adminPollFailures=Math.min(adminPollFailures+1,4);adminRefreshStatus(true);}};
  try{{
    if(partial){{await loadSummary();return;}}
    const me=await api(API_ROUTES.me);byId('accountName').textContent=me.account?.login_alias||me.account?.username||SERVER_ACCOUNT.login_alias||SERVER_ACCOUNT.username||'公司账号';
    const errors=[];
    // Each panel renders as soon as its own request resolves, including partial success.
    const schoolRequest=loadSummary().catch(error=>{{summaryFailed();errors.push(`学校汇总：${{error.message}}`);message(errors.join('；'));}});
    const membershipRequest=api(API_ROUTES.memberships).then(payload=>renderMembershipSummary(payload.summary||{{}})).catch(error=>{{membershipUnavailable(error);errors.push(`会员汇总：${{error.message}}`);message(errors.join('；'));}});
    const reportsRequest=renderReports().catch(error=>{{errors.push(`课程报告：${{error.message}}`);byId('recentReports').innerHTML=`<tr><td colspan="7">报告读取失败：${{esc(error.message)}}</td></tr>`;}});
    await Promise.all([schoolRequest,membershipRequest,reportsRequest]);
    if(errors.length)message(`部分后台数据未能刷新：${{errors.join('；')}}`);else message('后台数据已刷新。','success');
  }}catch(error){{summaryFailed();if(!partial){{membershipUnavailable(error);message(error.message);}}}}finally{{
    adminRefreshing=false;updateAdminControls();
    adminNextRefreshAt=Date.now()+Math.min(ADMIN_MAX_BACKOFF_MS,ADMIN_REFRESH_MS*2**adminPollFailures);scheduleAdminRefresh();
  }}
}}
byId('refreshButton').addEventListener('click',()=>refresh());
byId('previousUploads').addEventListener('click',()=>{{if(!byId('previousUploads').disabled)return refresh({{partial:true,page:adminUploadPage-1}});}});
byId('nextUploads').addEventListener('click',()=>{{if(!byId('nextUploads').disabled)return refresh({{partial:true,page:adminUploadPage+1}});}});
async function reportPage(delta){{
  if(adminRefreshing||adminPollStopped)return;
  const previous=adminReportPage;
  adminReportPage=Math.max(1,Math.min(adminReportPages,adminReportPage+delta));
  adminRefreshing=true;updateAdminControls();
  try{{await renderReports();}}catch(error){{adminReportPage=previous;message(error.message);}}
  finally{{adminRefreshing=false;updateAdminControls();scheduleAdminRefresh();}}
}}
byId('previousReports').addEventListener('click',()=>{{if(!byId('previousReports').disabled)return reportPage(-1);}});
byId('nextReports').addEventListener('click',()=>{{if(!byId('nextReports').disabled)return reportPage(1);}});
document.addEventListener('visibilitychange',()=>{{if(!adminInitialLoaded&&adminPageVisible())refresh();else scheduleAdminRefresh();}});
window.addEventListener('pagehide',stopAdminPolling);
window.addEventListener('pageshow',event=>{{if(event.persisted){{adminPollStopped=false;if(!adminInitialLoaded&&adminPageVisible())refresh();else scheduleAdminRefresh();}}}});
byId('logoutButton').addEventListener('click',async()=>{{stopAdminPolling();try{{await api(API_ROUTES.logout,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:'{{}}'}});}}finally{{window.location.assign('/demo2/login');}}}});byId('accountName').textContent=SERVER_ACCOUNT.username||'读取中';if(document.visibilityState!=='hidden')refresh();
"""
    return _document(title="公司后台 · RehabAffect 学校内测平台", body=body, page_style=page_style, script=script)


__all__ = [
    "render_demo2_login_html",
    "render_demo2_register_html",
    "render_demo2_school_html",
    "render_demo2_privacy_html",
    "render_demo2_membership_html",
    "render_demo2_upload_html",
    "render_demo2_admin_html",
]
