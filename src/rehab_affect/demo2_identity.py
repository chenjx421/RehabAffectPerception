"""School-scoped rosters and exact-frame teacher identity confirmation views.

These views only display protected server images and persist teacher annotations;
they do not crop images, produce face templates, or infer cross-frame identities.
"""

from __future__ import annotations

from typing import Any

from .demo2_portal import _BOOK_ICON, _account_payload, _document


STYLE = r"""
:root { --blue:#2163C4; --blue-deep:#184E9D; --blue-soft:#EBF2FD; --blue-pale:#F7F9FC; --ink:#30343B; --muted:#616873; --line:#DFE3E8; --line-strong:#B9C1CD; --success:#237A53; --warning:#A36016; }
body { background:#fff; font-size:15px; }
*,*::before,*::after { letter-spacing:0; }
[hidden] { display:none !important; }
.header-inner,.page-shell { width:min(1720px,calc(100% - 48px)); }
.header-inner { min-height:64px; }
.page-shell { padding-top:20px; }
.page-heading { margin-bottom:16px; align-items:center; }
.page-heading>div { min-width:0; }
.identity-nav { margin-left:auto; display:flex; flex-wrap:wrap; gap:8px; }
.button,.identity-nav .button { font-size:14px; font-weight:500; border-radius:4px; white-space:normal; text-align:center; }
.button.icon-button { width:44px; height:44px; padding:10px; flex:none; }
.button[aria-pressed=true] { border-color:var(--blue); background:var(--blue-soft); color:var(--blue-deep); }
:focus-visible { outline:3px solid var(--blue); outline-offset:3px; }
h1 { font:600 24px/1.4 "Microsoft YaHei UI","PingFang SC",sans-serif; }
h2 { font:600 20px/1.4 "Microsoft YaHei UI","PingFang SC",sans-serif; }
.lead,.identity-copy { font-size:14px; color:var(--muted); line-height:1.65; }
.lead { margin-top:4px; }
.identity-copy { margin-top:8px; }
.scope-band { display:flex; flex-wrap:wrap; gap:8px 28px; border-block:1px solid var(--line); padding:12px 0; font-size:14px; }
.scope-band strong { color:var(--ink); font-weight:600; }
.scope-band span { overflow-wrap:anywhere; min-width:0; }
.scope-details { margin:0 0 16px; border-bottom:1px solid var(--line); padding:6px 0; }
details summary { cursor:pointer; min-height:44px; align-content:center; font-size:14px; color:var(--muted); }
details[open]>summary { margin-bottom:8px; }
.scope-details summary { color:var(--ink); }
.scope-details .scope-warning { margin:0 0 8px; }
.permission-state::before { content:''; display:inline-block; width:8px; height:8px; border-radius:50%; background:var(--warning); margin-right:8px; }
.permission-state[data-state=editable]::before { background:var(--success); }
.work-layout { display:grid; grid-template-columns:minmax(0,1fr) 328px; gap:24px; align-items:start; }
.work-layout>*,.roster-layout>* { min-width:0; }
.side-pane { padding-left:20px; border-left:1px solid var(--line); }
.tool-row { display:flex; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:12px; }
.tool-row .field { flex:1 1 160px; }
.tool-row h2 { margin-right:auto; }
.page-heading .tool-row { margin:0; }
.frame-navigation { display:grid; grid-template-columns:44px minmax(0,1fr) 44px; gap:8px; align-items:end; margin-bottom:8px; }
.viewer-toolbar { display:flex; flex-wrap:wrap; gap:8px; align-items:center; background:var(--blue-pale); border-block:1px solid var(--line); padding:8px; }
.zoom-tools { display:flex; align-items:center; gap:8px; }
.zoom-value { width:48px; text-align:center; font:14px Consolas,monospace; }
.viewer-toolbar #previewButton { margin-left:auto; }
.frame-viewport { max-width:100%; max-height:680px; overflow:auto; background:#F0F2F5; overscroll-behavior:contain; }
.frame-surface { position:relative; width:100%; background:var(--blue-pale); line-height:0; overflow:hidden; touch-action:pan-x pan-y; }
.frame-surface img { display:block; width:100%; height:auto; object-fit:contain; user-select:none; -webkit-user-drag:none; }
.frame-surface.is-drawing { touch-action:none; cursor:crosshair; }
.frame-overlay { position:absolute; inset:0; pointer-events:none; }
.roi { position:absolute; border:2px solid var(--blue); background:#2163C410; box-sizing:border-box; pointer-events:none; }
.roi.candidate { border-style:dashed; border-color:var(--warning); background:transparent; }
.roi.confirmed { border-color:var(--success); background:transparent; }
.roi.selected { border-width:3px; }
.roi span { position:absolute; left:0; top:0; max-width:100%; background:#fff; color:var(--ink); font-size:11px; line-height:1.5; overflow:hidden; white-space:nowrap; padding:1px 3px; }
.frame-empty { padding:64px 20px; background:var(--blue-pale); border:1px dashed var(--line); text-align:center; color:var(--muted); font-size:14px; }
.frame-caption { display:flex; flex-wrap:wrap; gap:8px 24px; padding-block:12px; color:var(--muted); font-size:14px; }
.frame-caption strong { color:var(--blue-deep); font:600 14px Consolas,monospace; }
.legend { display:flex; flex-wrap:wrap; gap:14px; font-size:14px; color:var(--muted); }
.legend i { display:inline-block; width:14px; height:10px; border:2px solid var(--blue); margin-right:5px; }
.legend .candidate { border-style:dashed; border-color:var(--warning); }.legend .confirmed { border-color:var(--success); }
.time-jump { display:flex; align-items:end; gap:10px; margin-block:8px; }.time-jump .field { flex:1; }
.side-pane h2 { margin:0 0 10px; }
.candidate-list { display:flex; flex-wrap:wrap; gap:8px; margin:12px 0 18px; }
.candidate-list button { min-height:44px; padding:8px 12px; background:#fff; color:var(--blue-deep); border:1px solid var(--line); border-radius:4px; font-size:14px; }
.candidate-list button[aria-pressed=true] { border-color:var(--blue); background:var(--blue-soft); }
.annotation-form { display:grid; gap:12px; margin-top:12px; }
fieldset { border:0; padding:0; margin:0; min-width:0; }
fieldset:disabled { opacity:.65; }
.coordinate-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
.coordinate-grid legend { grid-column:1/-1; margin-bottom:10px; font-size:13px; color:var(--blue-deep); }
.coordinate-grid input { padding:8px; }
.field label,.field-label { color:var(--ink); font-size:14px; font-weight:500; }
.field small,.selection-note { color:var(--muted); font-size:14px; margin-top:6px; }
.button.danger { color:var(--danger); border-color:#dbb2af; }
.annotation-form .button.primary { width:100%; }
.frame-records { margin-top:24px; border-top:1px solid var(--line); padding-top:20px; }
.frame-records,.frame-viewport { scroll-margin-top:88px; }
.record-filters { display:flex; flex-wrap:wrap; gap:8px; border:0; }
.record-filters label { position:relative; min-height:44px; display:flex; align-items:center; padding:8px 12px; border-bottom:2px solid transparent; cursor:pointer; font-size:14px; }
.record-filters label:has(:checked) { border-color:var(--blue); color:var(--blue-deep); background:var(--blue-soft); }
.record-filters label:has(:focus-visible) { outline:2px solid var(--blue); outline-offset:2px; }
.record-filters input { position:absolute; inset:0; width:100%; height:100%; opacity:0; margin:0; clip:auto; cursor:pointer; }
.record-actions { display:flex; gap:8px; flex-wrap:wrap; }
.record-status { color:var(--success); font-weight:500; }
.record-status.history { color:var(--warning); }
.binding-list,.roster-list { display:grid; gap:10px; margin-top:16px; }
.record-row { display:flex; align-items:flex-start; justify-content:space-between; gap:16px; padding:14px 0; border-bottom:1px solid var(--line); font-size:14px; }
.record-row>div { min-width:0; }.record-row strong,.record-row small { display:block; overflow-wrap:anywhere; }.record-row small { font-size:14px; margin-top:5px; color:var(--muted); }
.record-row .button { flex:none; font-size:14px; }
.scope-warning { margin-bottom:16px; padding:8px 12px; border-left:3px solid var(--warning); background:#FFF8EE; font-size:14px; color:#805014; overflow-wrap:anywhere; }
.school-confirmation { margin-bottom:20px; padding:16px 0; border-block:1px solid var(--line); background:#fff; }
.school-confirmation dl { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin:16px 0; }
.school-confirmation dt { color:var(--muted); font-size:12px; }.school-confirmation dd { margin:4px 0 0; font-size:14px; overflow-wrap:anywhere; }
.school-confirmation .tool-row { margin:14px 0 0; }.school-confirmation .button { white-space:normal; text-align:center; }
.roster-layout { display:grid; grid-template-columns:minmax(0,1fr) 360px; gap:32px; }
.roster-form { display:grid; gap:16px; margin-top:18px; }
textarea { font:inherit; width:100%; min-width:0; resize:vertical; min-height:88px; border:1px solid var(--line-strong); border-radius:6px; padding:10px 12px; color:var(--ink); }
.roster-search { margin-top:18px; }
.form-status { font-size:14px; color:var(--muted); line-height:1.65; }
dialog { width:min(460px,calc(100% - 32px)); max-height:calc(100svh - 32px); overflow:auto; border:1px solid var(--line); border-radius:6px; padding:24px; color:var(--ink); }
dialog::backdrop { background:#20252B88; }
dialog h2 { margin-bottom:12px; }dialog .field { margin-block:16px; }dialog .tool-row { margin:20px 0 0; justify-content:flex-end; }
.preview-dialog { width:min(1280px,calc(100% - 32px)); padding:20px; }
.preview-dialog .tool-row { display:grid; grid-template-columns:minmax(0,1fr) 44px; gap:12px; margin:0; align-items:start; }
.preview-dialog h2 { margin:0; }
.preview-caption { font-size:14px; color:var(--muted); overflow-wrap:anywhere; margin:8px 0; }
.preview-image { display:block; max-width:100%; max-height:calc(100svh - 240px); width:auto; height:auto; object-fit:contain; margin:12px auto 0; }
.preview-status { min-height:24px; font-size:14px; color:var(--muted); }
.preview-status[data-error=true] { color:var(--danger); }
.save-gate { margin:12px 0; padding:10px 12px; border-left:3px solid var(--warning); background:#FFF8EE; font-size:14px; }
.save-gate .button { margin-top:8px; }
.annotation-advanced { margin-top:12px; border-top:1px solid var(--line); }
.annotation-advanced .coordinate-grid { margin:12px 0; }
.identity-steps { margin:0 0 12px; font-size:14px; color:var(--muted); }
.identity-steps strong { color:var(--blue-deep); font-weight:600; }
#continueToResults { width:100%; margin:8px 0 4px; }
.result-shortcut-note { margin:0 0 14px; color:var(--muted); font-size:13px; line-height:1.6; }
.student-actions { display:flex; flex-wrap:wrap; align-items:center; gap:8px; margin-top:8px; }
.annotation-form #studentChoice { display:grid; gap:12px; }
.track-dialog { width:min(900px,calc(100% - 32px)); }
.track-view { max-width:760px; margin:12px auto; }
.track-view .frame-surface { margin:12px auto; }
.track-dialog .tool-row { justify-content:space-between; }
@media(max-width:1000px) { .work-layout { grid-template-columns:minmax(0,1fr) 300px; gap:20px; }.side-pane { padding-left:20px; }.roster-layout { gap:24px; grid-template-columns:minmax(0,1fr) 310px; } }
@media(max-width:760px) { .work-layout,.roster-layout { grid-template-columns:minmax(0,1fr); }.side-pane { padding:24px 0 0; border-left:0; border-top:1px solid var(--line); }.header-inner { flex-wrap:wrap; }.identity-nav { margin:8px 0 0; }.header-inner,.page-shell { width:calc(100% - 28px); }h1 { font-size:24px; }.record-row { flex-wrap:wrap; }.frame-empty { padding:40px 18px; } }
@media(max-width:400px) { .header-inner,.page-shell { width:calc(100% - 24px); }.identity-nav { gap:4px; }.identity-nav .button { padding-inline:9px; }.tool-row { gap:8px; }.scope-band { display:grid; }.page-heading { gap:12px; } }
@media(max-width:600px) { .school-confirmation dl { grid-template-columns:minmax(0,1fr); } }
@media(max-width:760px) { .frame-viewport { max-height:520px; }.viewer-toolbar #previewButton { margin-left:0; }.preview-dialog { padding:14px; }.page-heading { align-items:flex-start; }.page-heading .tool-row { width:100%; }.scope-band { gap:6px 16px; } }
@media(prefers-reduced-motion:reduce) { *,*::before,*::after { transition:none !important; scroll-behavior:auto !important; } }
"""


# Lucide icon geometry (ISC); inline assets keep these protected pages offline-ready.
_ICON_PATHS = {
    "previous": '<path d="m15 18-6-6 6-6"/>',
    "next": '<path d="m9 18 6-6-6-6"/>',
    "close": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "zoom_in": '<circle cx="11" cy="11" r="8"/><line x1="21" x2="16.65" y1="21" y2="16.65"/><line x1="11" x2="11" y1="8" y2="14"/><line x1="8" x2="14" y1="11" y2="11"/>',
    "zoom_out": '<circle cx="11" cy="11" r="8"/><line x1="21" x2="16.65" y1="21" y2="16.65"/><line x1="8" x2="14" y1="11" y2="11"/>',
    "reset": '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    "image": '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>',
    "up": '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
    "refresh": '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
}


def _shell(content: str) -> str:
    for name, paths in _ICON_PATHS.items():
        content = content.replace(f"__ICON_{name}__", f'<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{paths}</svg>')
    return f"""<header class="site-header"><div class="header-inner">
<a class="brand" id="brandLink" href="/demo2/login">{_BOOK_ICON}<span class="brand-copy"><strong>课堂学习分析平台</strong><span id="accountLabel">学校名册与画面确认</span></span></a>
<nav class="identity-nav" aria-label="工作台导航"><a class="button quiet" id="backLink" href="/demo2/login">返回登录</a><a class="button quiet" id="secondaryLink" href="/demo2/school" hidden>学校信息</a><button class="button quiet" id="logoutButton" type="button">退出</button></nav>
</div></header><main class="page-shell" id="mainContent">{content}</main>"""


COMMON = r"""
const ACCOUNT=__ACCOUNT__;
const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const isTeacher=ACCOUNT.role==='school_uploader',isAdmin=ACCOUNT.role==='company_admin';
let dirty=false,writing=false;
const schoolName=context=>[context?.city,context?.district,context?.school_name].filter(Boolean).join(' / ')||'接口尚未提供学校信息';
const studentName=student=>[student.display_name||'未命名学生',student.student_code?'编号 '+student.student_code:'未填校内编号',student.class_name||'未填班级'].join(' · ');
const seconds=value=>{const n=Number(value);if(!Number.isFinite(n)||n<0)return '时间未返回';return `${String(Math.floor(n/60)).padStart(2,'0')}:${(n%60).toFixed(2).padStart(5,'0')}`;};
function notice(text,type='error'){const node=$('pageMessage');node.textContent=text;node.className='page-message visible '+type;}
function clearNotice(){$('pageMessage').textContent='';$('pageMessage').className='page-message';}
function safeImage(value){try{const url=new URL(value,location.origin);return value&&url.origin===location.origin&&['http:','https:'].includes(url.protocol)?url.pathname+url.search:'';}catch(_){return '';}}
async function request(path,payload,externalSignal){
  const controller=new AbortController();let timedOut=false;
  const abort=()=>controller.abort();if(externalSignal){if(externalSignal.aborted)abort();else externalSignal.addEventListener('abort',abort,{once:true});}
  const timer=setTimeout(()=>{timedOut=true;controller.abort();},12000);
  try{
    const response=await fetch('/api/v1/demo2/identity'+path,{credentials:'same-origin',signal:controller.signal,...(payload===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})});
    const data=await response.json().catch(error=>{if(error.name==='AbortError'||error instanceof TypeError)throw error;throw new Error('服务返回格式不完整，请刷新核对。');});
    if(!response.ok||data.error){const error=new Error(data.error?.message||({401:'登录已过期，请重新登录。',403:'当前账号无权访问本校名册或此任务，请返回工作台核对。',404:'未找到这条记录，请刷新或返回工作台重新选择。',409:'记录或学校归属已变化，请刷新核对后再操作。',410:'原视频或采样帧已到期，无法新增确认。'}[response.status])||'请求未完成，请稍后重试。');error.status=response.status;error.code=data.error?.code;if(response.status===401)location.assign('/demo2/login');throw error;}
    if(data.ok!==true)throw new Error('接口尚未确认操作结果，请刷新核对。');return data;
  }catch(error){if(timedOut)throw new Error('请求超时，请检查网络并刷新重试。');if(error instanceof TypeError)throw new Error('网络连接失败，请检查网络后重试。');throw error;}
  finally{clearTimeout(timer);externalSignal?.removeEventListener('abort',abort);}
}
function allowLeave(){if(writing){notice('正在保存，请稍候再离开。');return false;}return !dirty||window.confirm('当前内容尚未保存。离开会放弃本次选择，确定继续吗？');}
$('accountLabel').textContent=(ACCOUNT.login_alias||ACCOUNT.username||'当前账号')+' · '+(isAdmin?'管理员只读':'学校工作台');
$('brandLink').href=isAdmin?'/demo2/admin':'/demo2/upload';$('backLink').href=isAdmin?'/demo2/admin':'/demo2/upload';$('backLink').textContent=isAdmin?'返回公司后台':'返回上传工作台';$('secondaryLink').hidden=!isTeacher;
window.addEventListener('beforeunload',event=>{if(dirty||writing){event.preventDefault();event.returnValue='';}});
document.addEventListener('click',event=>{const link=event.target.closest?.('a[href]');const safeResultLink=link&&['studentStatusLink','continueToResults'].includes(link.id);if(link&&!safeResultLink&&!link.hasAttribute('download')&&!allowLeave())event.preventDefault();});
$('logoutButton').addEventListener('click',async()=>{if(!allowLeave())return;try{const response=await fetch('/api/v1/demo2/auth/logout',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:'{}',signal:AbortSignal.timeout(12000)});if(!response.ok)throw new Error('退出未完成，请重试。');dirty=false;location.assign('/demo2/login');}catch(error){notice(error instanceof TypeError?'网络连接失败，请检查网络后重试。':error.name==='TimeoutError'?'退出请求超时，请重试。':error.message);}});
"""


def render_students(account: Any | None = None) -> str:
    body = """
<div class="page-heading"><div><h1>本校学生名册</h1><p class="lead">姓名、校内编号与班级</p></div><div class="tool-row"><a class="button" id="returnTaskLink" hidden>__ICON_previous__返回画面身份确认</a><button class="button" id="refreshRoster" type="button">__ICON_refresh__刷新名册</button></div></div>
<div class="scope-band"><span>当前学校：<strong id="schoolName">正在读取</strong></span><span id="rosterCount" role="status">正在读取本校名单</span></div>
<div id="pageMessage" class="page-message" role="alert" tabindex="-1"></div>
<details class="scope-details"><summary><span class="permission-state" id="permissionState" role="status">正在核验权限</span> · 学校与名册边界</summary><p class="scope-warning" id="scopeNotice" role="status">正在核验学校归属与编辑权限。</p><p class="identity-copy">加入名册不代表已确认视频中的身份。同名学生请核对校内编号和班级；这里只显示本校接口返回的记录，不预置演示学生。</p></details>
<div class="roster-layout"><section aria-labelledby="rosterTitle"><h2 id="rosterTitle">已有名单</h2><div class="field roster-search"><label for="rosterSearch">查找姓名、校内编号或班级</label><input id="rosterSearch" type="search" autocomplete="off" placeholder="输入姓名或编号" disabled></div><div class="roster-list" id="rosterList" aria-live="polite"><div class="empty-state">正在读取本校名册…</div></div></section>
<section class="side-pane" aria-labelledby="createTitle"><h2 id="createTitle">新增本校学生</h2><p class="identity-copy">仅填写课堂工作必需的信息，请勿在备注中填写诊断或其他敏感资料。</p><form id="studentForm" class="roster-form"><fieldset id="studentFields" disabled><div class="roster-form"><div class="field"><label for="displayName">学生姓名（必填）</label><input id="displayName" required maxlength="80" autocomplete="off"></div><div class="field"><label for="studentCode">校内编号</label><input id="studentCode" maxlength="64" autocomplete="off"><small>建议填写，便于区分同名学生。</small></div><div class="field"><label for="className">班级</label><input id="className" maxlength="80" autocomplete="off"></div><div class="field"><label for="studentNote">备注（可选）</label><textarea id="studentNote" maxlength="500"></textarea></div><button class="button primary" id="createStudent" type="submit">创建学生</button></div></fieldset><p class="form-status" id="createStatus" role="status">正在核验编辑权限。</p></form></section></div>
"""
    script = COMMON.replace("__ACCOUNT__", _account_payload(account)) + r"""
const returnTask=new URLSearchParams(location.search).get('returntask')||'';
let roster=null,rosterLoading=false,canEditRoster=false,uncertainWrite=false;
if(returnTask){$('returnTaskLink').href='/demo2/identity?task_id='+encodeURIComponent(returnTask);$('returnTaskLink').hidden=false;}
function rosterControls(){$('studentFields').disabled=!canEditRoster||rosterLoading||writing||uncertainWrite;$('refreshRoster').disabled=rosterLoading||writing;$('rosterSearch').disabled=!roster;$('createStudent').textContent=writing?'正在创建':'创建学生';$('permissionState').textContent=rosterLoading?'正在核验学校':writing?'正在创建学生':uncertainWrite?'创建结果待核对':canEditRoster?'本校名册可编辑':isAdmin?'管理员只读':'名册只读 / 学校待核对';$('permissionState').dataset.state=canEditRoster&&!uncertainWrite?'editable':'readonly';}
function renderRoster(){
  const students=Array.isArray(roster?.students)?roster.students:[];const query=$('rosterSearch').value.trim().toLocaleLowerCase();const filtered=students.filter(s=>studentName(s).toLocaleLowerCase().includes(query));
  $('rosterCount').textContent=`本校名册 ${students.length} 人`;
  $('rosterList').innerHTML=filtered.length?filtered.map(s=>`<article class="record-row"><div><strong>${esc(s.display_name||'未命名学生')}</strong><small>${esc(s.student_code?'校内编号 '+s.student_code:'未填校内编号')} · ${esc(s.class_name||'未填班级')}</small>${s.note?`<small>${esc(s.note)}</small>`:''}</div>${isTeacher?`<div class="tool-row"><a class="button" href="/demo2/dossier?student_id=${encodeURIComponent(s.student_id)}">资料与授权</a><a class="button" href="/demo2/student-summary?student_id=${encodeURIComponent(s.student_id)}">公司留存摘要</a></div>`:''}</article>`).join(''):`<div class="empty-state">${query?'没有找到匹配学生，请更换姓名、编号或班级查询。':'本校名册为空。请先新增学生，再回到采样帧确认画面中的身份。'}</div>`;
}
async function loadRoster(){
  if(rosterLoading||writing||!allowLeave())return;rosterLoading=true;canEditRoster=false;clearNotice();rosterControls();
  try{
    const data=await request('/roster');if(!data.roster||!Array.isArray(data.roster.students))throw new Error('接口未返回完整名册，请刷新重试。');
    roster=data.roster;$('schoolName').textContent=schoolName(roster.school_context);canEditRoster=isTeacher&&roster.can_edit===true&&!!roster.scope_key;renderRoster();
    if(returnTask&&isTeacher){const data=await request('/workspace?task_id='+encodeURIComponent(returnTask));if(!data.workspace?.scope_key||data.workspace.scope_key!==roster.scope_key){canEditRoster=false;$('scopeNotice').textContent='当前学校与该视频任务的学校快照不一致，已停止新增。请返回任务核对学校归属；不会自动迁移学生。';}else $('scopeNotice').textContent='学校归属与返回任务一致。创建后可点击“返回画面身份确认”继续。';}
    else $('scopeNotice').textContent=isAdmin?'管理员只读查看名册，不在此创建或绑定学生。':canEditRoster?'名册归属当前学校；创建学生不会将其自动绑定到任何视频。':'当前学校名册为只读，请返回工作台核对学校归属与权限。';
    uncertainWrite=false;dirty=false;$('createStatus').textContent=canEditRoster?'填写姓名，核对编号与班级后创建。':'当前不可新增学生。';
  }catch(error){canEditRoster=false;notice(error.message);$('createStatus').textContent='尚未确认学校归属，已停止新增。请刷新名册重试。';if(!roster){$('rosterCount').textContent='读取失败';$('rosterList').innerHTML='<div class="empty-state">无法读取名册，不能据此判断本校没有学生。</div>';}}
  finally{rosterLoading=false;rosterControls();}
}
$('rosterSearch').addEventListener('input',renderRoster);$('refreshRoster').addEventListener('click',loadRoster);
$('studentForm').addEventListener('input',()=>{dirty=true;});
$('studentForm').addEventListener('submit',async event=>{
  event.preventDefault();if(!canEditRoster||writing||rosterLoading||uncertainWrite)return;
  const payload={display_name:$('displayName').value.trim(),student_code:$('studentCode').value.trim(),class_name:$('className').value.trim(),note:$('studentNote').value.trim()};
  if(!payload.display_name){notice('请填写学生姓名。');$('displayName').focus();return;}
  const same=roster.students.filter(s=>s.display_name===payload.display_name);if(same.length&&!window.confirm('已有同名学生：\n'+same.map(studentName).join('\n')+'\n请核对编号与班级。仍要新建吗？'))return;
  writing=true;clearNotice();rosterControls();
  try{const data=await request('/students',payload);if(!data.student?.student_id)throw new Error('创建结果尚未确认，请刷新名册核对。');roster.students.push(data.student);$('studentForm').reset();dirty=false;renderRoster();notice('学生已加入本校名册，尚未绑定任何视频画面。','success');}
  catch(error){notice(error.message);if(!error.status){uncertainWrite=true;$('createStatus').textContent='创建结果尚未确认，请先刷新名册核对，避免重复创建。';}if([403,409].includes(error.status))canEditRoster=false;}
  finally{writing=false;rosterControls();}
});
loadRoster();
"""
    return _document(title="本校学生名册 · 课堂学习分析平台", body=_shell(body), page_style=STYLE, script=script)


def render_identity(account: Any | None = None) -> str:
    body = """
<div class="page-heading"><div><h1>确认画面中的人员</h1><p class="lead">这是身份关联页面；学生状态结果请从右侧入口查看。</p></div><div class="tool-row"><a class="button primary" id="studentStatusLink" href="#" hidden>查看学生状态</a><button class="button" id="showRecords" type="button">查看确认记录</button><button class="button" id="refreshWorkspace" type="button">__ICON_refresh__刷新记录</button><a class="button" id="exportBindings" download hidden>下载身份确认 JSON</a></div></div>
<div class="scope-band"><span>任务学校：<strong id="taskSchool">正在读取</strong></span><span>课程：<strong id="taskCourse">正在读取</strong></span><span id="bindingSummary" role="status">正在读取确认记录</span></div>
<div class="page-message" id="pageMessage" role="alert" tabindex="-1"></div>
<details class="scope-details"><summary><span class="permission-state" id="permissionState" role="status">正在核验任务权限</span> · 权限与确认边界</summary><p class="scope-warning" id="scopeNotice" role="status">正在核验任务学校与当前账号权限。</p><p class="identity-copy">检测只定位人脸候选，不会自动识别姓名。确认仅对应当前采样帧，不代表整段跟踪；全画面的动作变化和音轨不归因于所选学生。保存教师确认的框、角色及本校学生标识，不在浏览器生成或保存人脸模板。原片或采样图不可用时停止新增，保留记录以服务器返回内容为准。</p></details>
<section class="school-confirmation" id="schoolConfirmation" aria-labelledby="schoolConfirmationTitle" hidden><h2 id="schoolConfirmationTitle">确认旧视频的学校归属</h2><p class="identity-copy">此旧任务未记录学校。请先核对视频实际归属，再决定是否使用当前账号填写的学校；系统不会自动补齐，也不会迁移已有学校快照。</p><dl id="confirmationSchoolDetails"><div><dt>城市</dt><dd id="confirmationCity">正在读取</dd></div><div><dt>区县</dt><dd id="confirmationDistrict">正在读取</dd></div><div><dt>学校</dt><dd id="confirmationSchoolName">正在读取</dd></div></dl><p class="form-status" id="schoolConfirmationStatus" role="status">正在读取当前学校信息。</p><div class="tool-row"><button class="button primary" id="confirmTaskSchool" type="button" disabled hidden>确认此视频属于上述学校</button><a class="button" id="completeSchoolLink" href="/demo2/school" hidden>先填写或核对学校信息</a></div></section>
<div class="work-layout"><section aria-labelledby="frameTitle"><div class="tool-row"><h2 id="frameTitle">原始课堂采样帧</h2><a class="button quiet" id="videoLink" hidden>查看视频证据</a></div>
<div class="frame-navigation"><button class="button icon-button" id="previousFrame" type="button" aria-label="上一帧" title="上一帧" disabled>__ICON_previous__</button><div class="field"><label for="frameSelect">采样时间</label><select id="frameSelect" disabled><option value="">尚无采样帧</option></select></div><button class="button icon-button" id="nextFrame" type="button" aria-label="下一帧" title="下一帧" disabled>__ICON_next__</button></div>
<div class="viewer-toolbar" role="toolbar" aria-label="画面查看工具"><div class="zoom-tools"><button class="button icon-button" id="zoomOut" type="button" title="缩小画面" aria-label="缩小画面" disabled>__ICON_zoom_out__</button><output class="zoom-value" id="zoomValue" aria-live="polite">100%</output><button class="button icon-button" id="zoomIn" type="button" title="放大画面" aria-label="放大画面" disabled>__ICON_zoom_in__</button><button class="button icon-button" id="resetZoom" type="button" title="复位画面" aria-label="复位画面" disabled>__ICON_reset__</button></div><button class="button" id="previewButton" type="button" aria-haspopup="dialog" disabled>__ICON_image__原片彩色高清参考</button></div>
<div class="frame-viewport" id="frameViewport" tabindex="0" role="region" aria-label="采样帧标注画面"><div class="frame-empty" id="frameEmpty" role="status">正在读取任务采样帧…</div><div class="frame-surface" id="frameSurface" hidden><img id="frameImage" alt="当前任务的原始课堂采样帧" draggable="false"><div class="frame-overlay" id="frameOverlay" aria-hidden="true"></div></div></div>
<div class="frame-caption"><strong id="frameTime">--:--</strong><span id="framePeriod">采样片段时间待返回</span><span id="framePosition"></span></div><div class="legend" aria-label="标注图例"><span><i class="candidate"></i>检测候选（未确认）</span><span><i></i>当前选择（未保存）</span><span><i class="confirmed"></i>本帧已确认</span></div>
<details><summary>按秒数定位</summary><div class="time-jump"><div class="field"><label for="jumpTime">最近采样帧（秒）</label><input id="jumpTime" type="number" min="0" step="0.1" disabled></div><button class="button" id="jumpFrame" type="button" disabled>定位采样帧</button></div></details>
</section>
<aside class="side-pane" aria-labelledby="confirmTitle"><h2 id="confirmTitle">匹配学生姓名</h2><p class="identity-steps"><strong>选中人</strong> → 选姓名 → 确认</p><p class="form-status" id="detectionStatus" role="status">读取采样帧后显示候选。</p><div class="candidate-list" id="candidateList"></div><div class="tool-row"><button class="button" id="drawButton" type="button" aria-pressed="false" disabled>手动画框</button><button class="button" id="retryDetection" type="button" disabled>重新检测</button><button class="button icon-button" id="clearSelection" type="button" aria-label="取消选择" title="取消选择" disabled>__ICON_close__</button></div><p class="selection-note" id="selectionStatus" role="status">先选中画面中的一人。</p><a class="button primary" id="continueToResults" href="#" hidden>下一步：查看学生状态</a><p class="result-shortcut-note" id="resultShortcutNote" hidden>姓名绑定可以跳过。结果页会直接展示本视频中检测到的人物及各自的课堂状态。</p>
<div class="save-gate" id="saveGate" role="status"><p id="saveGateReason">正在核验编辑权限。</p><button class="button" id="schoolGateLink" type="button" hidden>核对并确认学校</button></div>
<form class="annotation-form" id="bindingForm"><fieldset id="bindingFields" disabled><div class="annotation-form"><div id="studentChoice"><div class="field"><label for="studentSearch">查找本校学生</label><input id="studentSearch" type="search" autocomplete="off" placeholder="姓名、编号或班级"></div><div class="field"><label for="studentSelect">学生姓名</label><select id="studentSelect"><option value="">请选择本校学生</option></select></div><div class="student-actions"><button class="button quiet" id="addStudent" type="button" disabled>新增本校学生</button></div></div><button class="button primary" id="saveBinding" type="submit" disabled>确认姓名</button></div></fieldset><p class="form-status" id="saveStatus" role="status">尚未确认编辑权限。</p>
<details class="annotation-advanced" id="annotationAdvanced"><summary>高级：坐标与其他人员角色</summary><p class="selection-note" id="drawingHelp">可在图中拖动画框，也可填写相对原图的百分比坐标。</p><div class="coordinate-grid"><div class="field"><label for="bboxX">左侧 x %</label><input id="bboxX" type="number" min="0" max="100" step="0.1" placeholder="0" disabled></div><div class="field"><label for="bboxY">顶部 y %</label><input id="bboxY" type="number" min="0" max="100" step="0.1" placeholder="0" disabled></div><div class="field"><label for="bboxWidth">宽度 %</label><input id="bboxWidth" type="number" min="0.1" max="100" step="0.1" placeholder="0" disabled></div><div class="field"><label for="bboxHeight">高度 %</label><input id="bboxHeight" type="number" min="0.1" max="100" step="0.1" placeholder="0" disabled></div></div><div class="field"><label for="personRole">人员角色</label><select id="personRole" disabled><option value="student" selected>学生</option><option value="teacher">教师</option><option value="unknown">身份未知</option></select><small>未知不必选姓名；教师不会挂入学生档案。</small></div></details></form><details><summary>本校名册</summary><p class="identity-copy" id="rosterNotice"></p><a class="button" id="rosterLink" href="/demo2/students" hidden>打开本校名册</a></details>
</aside></div>
<section class="frame-records" id="recordsSection" aria-labelledby="bindingsTitle"><div class="tool-row"><h2 id="bindingsTitle" tabindex="-1">身份确认记录</h2><button class="button quiet" id="backToFrame" type="button">__ICON_up__返回当前画面</button></div><fieldset class="record-filters"><legend class="sr-only">记录范围</legend><label><input class="sr-only" id="recordsCurrent" type="radio" name="recordFilter" value="current" checked>当前帧记录</label><label><input class="sr-only" id="recordsAll" type="radio" name="recordFilter" value="all">全部历史</label></fieldset><p class="form-status" id="recordCount" role="status"></p><details><summary>记录与撤销边界</summary><p class="identity-copy">同一学生可在多帧分别确认；撤销仅影响所选记录，需要填写原因。历史版本不会叠加到当前采样画面。</p></details><div class="binding-list" id="bindingList"><div class="empty-state">正在读取记录…</div></div></section>
<dialog class="preview-dialog" id="previewDialog" aria-labelledby="previewTitle" aria-describedby="previewBoundary"><div class="tool-row"><h2 id="previewTitle">原片彩色高清参考 · 只读</h2><button class="button icon-button" id="closePreview" type="button" aria-label="关闭原片参考" title="关闭原片参考" autofocus>__ICON_close__</button></div><p class="preview-caption" id="previewCaption"></p><p class="identity-copy" id="previewBoundary">按相近时刻解码，未必与采样帧逐帧一致。时间戳与画面名称仅标记当前参考来源；不显示或沿用采样框，此处不能保存身份确认。</p><p class="preview-status" id="previewStatus" role="status" aria-live="polite"></p><img class="preview-image" id="previewImage" alt="原片彩色高清只读参考" draggable="false" hidden></dialog>
<dialog id="revokeDialog" aria-labelledby="revokeTitle"><form id="revokeForm"><h2 id="revokeTitle">撤销一条身份确认</h2><p class="identity-copy" id="revokeTarget"></p><div class="field"><label for="revokeReason">撤销原因（必填）</label><textarea id="revokeReason" required maxlength="500"></textarea></div><p id="revokeError" class="form-status" role="alert"></p><div class="tool-row"><button class="button" id="cancelRevoke" type="button">保留记录</button><button class="button danger" id="confirmRevoke" type="submit">确认撤销本条记录</button></div></form></dialog>
<dialog id="newStudentDialog" aria-labelledby="newStudentTitle"><form id="newStudentForm"><h2 id="newStudentTitle">新增本校学生</h2><p class="identity-copy" id="newStudentSchool"></p><div class="field"><label for="inlineStudentName">学生姓名（必填）</label><input id="inlineStudentName" required maxlength="80" autocomplete="off"></div><details><summary>校内编号与班级</summary><div class="field"><label for="inlineStudentCode">校内编号</label><input id="inlineStudentCode" maxlength="64" autocomplete="off"></div><div class="field"><label for="inlineStudentClass">班级</label><input id="inlineStudentClass" maxlength="80" autocomplete="off"></div></details><p class="form-status" id="newStudentError" role="alert"></p><div class="tool-row"><button class="button" id="cancelNewStudent" type="button">取消</button><button class="button primary" id="confirmNewStudent" type="submit">加入名册并选中</button></div></form></dialog>
<dialog class="track-dialog" id="trackDialog" aria-labelledby="trackTitle" aria-describedby="trackBoundary"><div class="tool-row"><h2 id="trackTitle">后续 5 秒位置建议</h2><button class="button icon-button" id="closeTrack" type="button" aria-label="关闭后续建议" title="关闭后续建议">__ICON_close__</button></div><p class="identity-copy" id="trackBoundary">姓名仅来自已确认的起始帧，不是自动识别。建议尚未保存，须逐帧核对并确认。</p><p class="form-status" id="trackStatus" role="status"></p><div class="track-view" id="trackView" hidden><div class="frame-navigation"><button class="button icon-button" id="previousTrackPoint" type="button" aria-label="上一个建议时刻" title="上一个建议时刻">__ICON_previous__</button><p id="trackPointTime"></p><button class="button icon-button" id="nextTrackPoint" type="button" aria-label="下一个建议时刻" title="下一个建议时刻">__ICON_next__</button></div><div class="frame-surface" id="trackSurface"><img id="trackImage" alt="后续采样帧的位置建议" draggable="false"><div class="frame-overlay" id="trackOverlay" aria-hidden="true"></div></div><p class="form-status" id="trackPointStatus" role="status"></p><button class="button primary" id="adoptTrackPoint" type="button" disabled>在此时刻核对</button></div></dialog>
"""
    script = COMMON.replace("__ACCOUNT__", _account_payload(account)) + IDENTITY_SCRIPT
    return _document(title="逐帧身份确认 · 课堂学习分析平台", body=_shell(body), page_style=STYLE, script=script)


IDENTITY_SCRIPT = r"""
const taskId=new URLSearchParams(location.search).get('task_id')||'';
let workspace=null,frames=[],frameIndex=-1,box=null,selectedCandidate='',candidates=[],imageReady=false;
let loading=false,editable=false,canRevoke=false,uncertainWrite=false,drawing=false,drag=null,detectionLoading=false,frameEpoch=0,detectController=null,revokeBinding=null;
let confirmationRoster=null,schoolConfirmationError='',rosterReadFailed=false,workspaceVerified=false;
let zoom=1,previewController=null,previewUrl='',previewEpoch=0;
let inlineUncertain=false,inlineDirty=false,inlinePreviousDirty=false;
let trackController=null,trackEpoch=0,trackResult=null,trackSeed=null,trackIndex=0,trackImageReady=false;
const QUICK_TEST_PROFILES=[['A','测试学生A'],['B','测试学生B'],['C','测试学生C']];
function installQuickTestProfiles(){
 const actions=$('addStudent')?.parentElement;if(!actions||$('quickTestProfiles'))return;
 const wrap=document.createElement('div');wrap.id='quickTestProfiles';wrap.className='quick-test-profiles';
 wrap.innerHTML='<small>没有正式学生档案？先建立本次测试用的最小档案</small><div class="student-actions">'+QUICK_TEST_PROFILES.map(([code,name])=>'<button class="button quiet" type="button" data-quick-test="'+code+'">'+name+'</button>').join('')+'</div>';
 actions.append(wrap);
 wrap.addEventListener('click',event=>{const button=event.target.closest('[data-quick-test]');if(!button||!mayAddStudent()||writing)return;const code=button.dataset.quickTest,name='测试学生'+code;
   const existing=(workspace?.students||[]).find(s=>s.student_code==='TEST-'+code||s.display_name===name);
   if(existing){$('studentSearch').value='';renderStudents();$('personRole').value='student';$('studentChoice').hidden=false;$('studentSelect').value=existing.student_id;dirty=dirty||!!box;controls();notice('已选中'+name+'，请点击“确认姓名”完成当前画面归档。','info');return;}
   inlinePreviousDirty=dirty;inlineDirty=false;$('newStudentForm').reset();$('inlineStudentName').value=name;$('inlineStudentCode').value='TEST-'+code;$('inlineStudentClass').value='本次视频测试';$('newStudentError').textContent='';$('newStudentSchool').textContent=schoolName(workspace?.school_context)+' · 仅用于本次测试，可后续替换正式资料';$('confirmNewStudent').disabled=false;$('newStudentDialog').showModal();$('inlineStudentName').focus();
 });
}
const coordinateIds=['bboxX','bboxY','bboxWidth','bboxHeight'];
const clamp=value=>Math.max(0,Math.min(1,value));
function validBox(value){return !!value&&['x','y','width','height'].every(k=>typeof value[k]==='number'&&Number.isFinite(value[k]))&&value.x>=0&&value.y>=0&&value.x<1&&value.y<1&&value.width>0&&value.height>0&&value.width<=1-value.x+Number.EPSILON&&value.height<=1-value.y+Number.EPSILON;}
function normalizedBox(value){return {x:value.x,y:value.y,width:Math.min(value.width,1-value.x),height:Math.min(value.height,1-value.y)};}
function frame(){return frames[frameIndex]||null;}
function bindings(){return Array.isArray(workspace?.bindings)?workspace.bindings:[];}
function currentBinding(item){return ['confirmed','active'].includes(item.status)&&item.current_revision!==false&&(item.frame_revision==null||String(item.frame_revision)===String(workspace?.frame_revision));}
function detectionReason(value){const code=String(value||'').toLowerCase();const reason=/model_missing|model_not|model_unavailable/.test(code)?'人脸检测模型未就绪。':/busy/.test(code)?'人脸检测服务繁忙。':/timeout|timed_out/.test(code)?'人脸检测超时。':'自动检测暂不可用。';return reason+(canDraft()?'可直接手动画框。':'当前仅可复核保留记录。');}
function canDraft(){return isTeacher&&workspaceVerified&&workspace?.media_available===true&&!!frame()&&workspace.frame_revision!=null&&imageReady&&!loading&&!writing;}
function canPreview(){return canDraft();}
function mayAddStudent(){return editable&&canDraft()&&!uncertainWrite&&!inlineUncertain&&confirmationRoster?.can_edit===true&&!!workspace.scope_key&&confirmationRoster.scope_key===workspace.scope_key;}
function canReference(){return (isTeacher||isAdmin)&&workspace?.media_available===true&&!!frame()&&workspace.frame_revision!=null&&!loading&&!writing;}
function clearReference(){
  previewEpoch++;previewController?.abort();previewController=null;
  const image=$('previewImage');image.onload=null;image.onerror=null;image.hidden=true;image.removeAttribute('src');
  if(previewUrl)URL.revokeObjectURL(previewUrl);previewUrl='';$('previewCaption').textContent='';$('previewStatus').textContent='';$('previewStatus').dataset.error='false';
}
function closeReference(restoreFocus=false){clearReference();if($('previewDialog').open)$('previewDialog').close();if(restoreFocus){controls();if(!$('previewButton').disabled)$('previewButton').focus();}}
async function openReference(){
  if(!canReference()||$('previewDialog').open||previewController)return;
  clearReference();const epoch=previewEpoch,controller=new AbortController();previewController=controller;
  const item=frame(),revision=workspace.frame_revision;let timedOut=false;
  $('previewCaption').textContent=`当前参考 ${seconds(item.time_sec)} · ${item.frame_key}`;
  $('previewStatus').textContent='正在读取这一张原片参考…';$('previewDialog').showModal();$('closePreview').focus();controls();
  const timer=setTimeout(()=>{timedOut=true;controller.abort();},12000);
  try{
    const query=new URLSearchParams({task_id:taskId,frame_key:item.frame_key,frame_revision:String(revision)});
    const response=await fetch('/api/v1/demo2/identity/preview?'+query,{credentials:'same-origin',cache:'no-store',signal:controller.signal});
    if(!response.ok){
      const messages={401:'登录已过期，请重新登录后查看原片参考。',403:'当前账号无权查看此原片参考，请返回工作台核对。',404:'未找到此帧的原片参考，请关闭后刷新记录核对。',409:'原片或采样帧版本已变化，请关闭后刷新记录核对。',410:'原片已到期，无法查看参考。',422:'无法读取此时刻的原片参考，请关闭后核对采样记录。',429:'原片参考服务繁忙或请求过于频繁，请稍后再点开。',503:'原片参考服务暂不可用，请稍后再试。'};
      throw new Error(messages[response.status]||'原片参考读取失败，请稍后再试。');
    }
    if(response.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase()!=='image/jpeg')throw new Error('原片参考格式不正确，请关闭后重试。');
    const blob=await response.blob();
    if(epoch!==previewEpoch||controller.signal.aborted||!$('previewDialog').open)return;
    if(!blob.size)throw new Error('原片参考为空，请关闭后重试。');
    previewUrl=URL.createObjectURL(blob);const url=previewUrl,image=$('previewImage');
    image.onload=()=>{if(epoch!==previewEpoch||previewUrl!==url)return;image.hidden=false;$('previewStatus').textContent='只读参考 · 未改变本帧选择或身份记录';};
    image.onerror=()=>{if(epoch!==previewEpoch||previewUrl!==url)return;image.hidden=true;image.removeAttribute('src');URL.revokeObjectURL(previewUrl);previewUrl='';$('previewStatus').dataset.error='true';$('previewStatus').textContent='原片参考图片无法显示，请关闭后重试。';};
    image.src=url;
  }catch(error){
    if(epoch!==previewEpoch||!$('previewDialog').open)return;
    $('previewStatus').dataset.error='true';$('previewStatus').textContent=timedOut?'原片参考读取超时，请关闭后稍后再试。':error instanceof TypeError?'网络连接失败，请检查网络后重新点开原片参考。':error.name==='AbortError'?'原片参考读取已取消。':error.message;
  }finally{clearTimeout(timer);if(previewController===controller)previewController=null;controls();}
}
function setZoom(value,reset=false){
  if(drag||(!reset&&(!imageReady||loading||writing)))return;
  const viewport=$('frameViewport'),previous=zoom;
  zoom=Math.max(1,Math.min(4,value));$('frameSurface').style.width=(zoom*100)+'%';$('zoomValue').value=Math.round(zoom*100)+'%';
  if(reset){viewport.scrollLeft=0;viewport.scrollTop=0;}
  else{viewport.scrollLeft=(viewport.scrollLeft+viewport.clientWidth/2)*zoom/previous-viewport.clientWidth/2;viewport.scrollTop=(viewport.scrollTop+viewport.clientHeight/2)*zoom/previous-viewport.clientHeight/2;}
  controls();
}
function closeTrack(){
  trackEpoch++;trackController?.abort();trackController=null;trackResult=null;trackSeed=null;trackImageReady=false;
  $('trackImage').onload=null;$('trackImage').onerror=null;$('trackImage').removeAttribute('src');$('trackOverlay').innerHTML='';$('trackView').hidden=true;$('trackStatus').textContent='';$('trackPointStatus').textContent='';$('trackPointTime').textContent='';
  if($('trackDialog').open)$('trackDialog').close();
}
function trackEligible(seed){return !!seed&&canDraft()&&currentBinding(seed)&&seed.role==='student'&&frames.some(f=>f.frame_key===seed.frame_key)&&(workspace.students||[]).some(s=>s.student_id===seed.student_id);}
function trackMessage(reason){return /lost|occlu|quality|feature|flow/.test(String(reason))?'位置已丢失或遮挡，请重新框选。':/insufficient|sample|frame/.test(String(reason))?'后续可用采样不足。':'仅为位置建议，请核对画面中的人。';}
function fitTrackImage(){const image=$('trackImage');if(image.naturalHeight)$('trackSurface').style.maxWidth=Math.max(100,(innerHeight-420)*image.naturalWidth/image.naturalHeight)+'px';}
function renderTrackPoint(){
  const point=trackResult?.points[trackIndex];if(!point)return;
  const item=frames.find(f=>f.frame_key===point.frame_key),epoch=++trackEpoch,index=trackIndex;
  trackImageReady=false;$('adoptTrackPoint').disabled=true;$('trackView').hidden=false;
  $('previousTrackPoint').disabled=index<=0;$('nextTrackPoint').disabled=index>=trackResult.points.length-1;
  $('trackPointTime').textContent=`${seconds(point.time_sec)} · ${index+1} / ${trackResult.points.length}`;
  $('trackPointStatus').textContent=point.status==='lost'?'此时刻已丢失，不能采用建议；请返回采样帧重新框选。':point.status==='seed'?'已确认的起始帧；姓名以该条记录为准。':'位置待核对，采用后仍需确认姓名。';
  const bbox=point.bbox;$('trackOverlay').innerHTML=point.status!=='lost'&&validBox(bbox)?`<div class="roi candidate" style="left:${bbox.x*100}%;top:${bbox.y*100}%;width:${bbox.width*100}%;height:${bbox.height*100}%"><span>位置建议</span></div>`:'';
  const image=$('trackImage');image.onload=()=>{if(epoch!==trackEpoch||index!==trackIndex||!$('trackDialog').open)return;trackImageReady=image.naturalWidth>0;fitTrackImage();$('adoptTrackPoint').disabled=!trackImageReady||point.status!=='suggested'||!validBox(bbox);};
  image.onerror=()=>{if(epoch!==trackEpoch)return;trackImageReady=false;$('adoptTrackPoint').disabled=true;$('trackPointStatus').textContent='采样图不可用，不能采用此建议。';};
  image.removeAttribute('src');const url=safeImage(item?.image_url);if(url)image.src=url;else image.onerror();
}
async function openTrack(bindingId){
  const seed=bindings().find(item=>item.binding_id===bindingId);if(!seed||!trackEligible(seed)||$('trackDialog').open)return;
  closeTrack();const epoch=trackEpoch,controller=new AbortController();trackController=controller;trackSeed={...seed};
  $('trackStatus').textContent='正在计算后续 5 秒位置建议…';$('trackDialog').showModal();$('closeTrack').focus();
  try{
    const data=await request('/track',{task_id:taskId,binding_id:seed.binding_id,frame_revision:workspace.frame_revision},controller.signal);
    if(controller.signal.aborted||epoch!==trackEpoch||!$('trackDialog').open)return;
    const result=data.track,start=frames.find(f=>f.frame_key===seed.frame_key)?.time_sec;
    if(!result||result.binding_id!==seed.binding_id||result.student_id!==seed.student_id||result.frame_revision!==workspace.frame_revision||result.scope!=='short_window_suggestion'||result.automatic_identity!==false||result.window_sec!==5||!['completed','lost','insufficient'].includes(result.status)||!Array.isArray(result.points)||result.points.length>6||result.points.some(p=>!['seed','suggested','lost'].includes(p.status)||!frames.some(f=>f.frame_key===p.frame_key&&f.time_sec===p.time_sec)||p.time_sec<start||p.time_sec>start+5||(p.status!=='lost'&&!validBox(p.bbox))))throw new Error('位置建议与当前记录不一致，请关闭后刷新核对。');
    trackResult=result;trackIndex=0;$('trackStatus').textContent=bindingName(seed)+' · '+(result.status==='completed'?'建议已返回，未保存任何新身份。':trackMessage(result.reason));
    if(result.points.length)renderTrackPoint();else $('trackStatus').textContent+=' 暂无可查看的后续采样。';
  }catch(error){if(controller.signal.aborted||epoch!==trackEpoch||!$('trackDialog').open)return;$('trackStatus').textContent=({429:'后续建议服务繁忙，请稍后主动重试。',409:'起始绑定或帧版本已失效，请关闭后刷新记录。',410:'视频已到期，无法查看后续建议。',403:'当前账号无权查看此建议。'}[error.status])||(/[\u3400-\u9fff]/.test(error.message)?error.message:'后续建议暂不可用，请稍后重试。');}
  finally{if(trackController===controller)trackController=null;}
}
function completeSchool(context){return ['city','district','school_name'].every(key=>typeof context?.[key]==='string'&&context[key].trim().length>0);}
function mayConfirmSchool(){return isTeacher&&workspace?.needs_school_confirmation===true&&workspace?.can_confirm_school===true&&['city','district','school_name'].every(key=>!String(workspace.school_context?.[key]||'').trim())&&bindings().length===0;}
function confirmationReady(){return mayConfirmSchool()&&completeSchool(confirmationRoster?.school_context)&&typeof confirmationRoster?.scope_key==='string'&&!!confirmationRoster.scope_key&&!schoolConfirmationError&&!rosterReadFailed;}
function renderSchoolConfirmation(){
  const needed=workspace?.needs_school_confirmation===true,offered=mayConfirmSchool();$('schoolConfirmation').hidden=!needed;$('confirmTaskSchool').hidden=!offered;
  $('confirmationSchoolDetails').hidden=!isTeacher;$('completeSchoolLink').hidden=!(isTeacher&&needed);$('completeSchoolLink').href='/demo2/school?returntask='+encodeURIComponent(taskId);$('secondaryLink').href='/demo2/school?returntask='+encodeURIComponent(taskId);
  const context=confirmationRoster?.school_context;for(const [id,key]of [['confirmationCity','city'],['confirmationDistrict','district'],['confirmationSchoolName','school_name']])$(id).textContent=context?.[key]||'未填写';
  $('schoolConfirmationStatus').textContent=schoolConfirmationError||(!isTeacher?'请由该视频所属学校的教师核对归属。管理员只读，不代为确认。':loading&&!confirmationRoster?'正在读取当前账号的学校信息…':rosterReadFailed?'无法读取当前学校，请先填写或核对学校信息，再刷新此任务。未确认前不能保存身份绑定。':!completeSchool(context)?'当前学校信息不完整。请先填写城市、区县和学校，返回此任务后再次核对。':!offered?'当前任务不允许补齐学校，请刷新核对；已有快照或确认记录不会迁移。':'请核对上述三个字段与视频的实际学校一致。点击按钮后还需再次确认；完成前仅可预览位置，不能保存姓名绑定。');
}
function bindingName(item){if(item.role==='teacher')return '教师（不关联学生档案）';if(item.role==='unknown')return '身份未知';const student=(workspace?.students||[]).find(s=>s.student_id===item.student_id);return student?studentName(student):'该学生已不在任务名册中（未显示姓名）';}
function controls(){
  const locked=loading||writing,canDraw=canDraft(),canSubmit=editable&&canDraw&&!uncertainWrite;
  $('refreshWorkspace').disabled=locked;$('frameSelect').disabled=locked||!frames.length;$('previousFrame').disabled=locked||frameIndex<=0;$('nextFrame').disabled=locked||frameIndex>=frames.length-1;
  $('jumpTime').disabled=locked||!frames.length;$('jumpFrame').disabled=locked||!frames.length;$('drawButton').disabled=!canDraw;$('clearSelection').disabled=!canDraw||(!box&&!dirty&&!drawing);$('bindingFields').disabled=!canSubmit;$('retryDetection').disabled=!canPreview()||detectionLoading;
  coordinateIds.forEach(id=>$(id).disabled=!canDraw);$('personRole').disabled=!canSubmit;$('addStudent').disabled=!mayAddStudent();
  $('retryDetection').textContent=editable?'重新检测':'检测人脸位置';$('confirmTaskSchool').disabled=locked||!confirmationReady();
  const studentValid=$('personRole').value!=='student'||(workspace?.students||[]).some(s=>s.student_id===$('studentSelect').value);
  $('saveBinding').disabled=!canSubmit||!validBox(box)||!studentValid;$('saveBinding').textContent=writing?'正在保存':$('personRole').value==='student'?'确认姓名':'确认角色';
  const reason=loading?'正在核验任务，请稍候。':writing?'正在保存，请稍候。':!workspaceVerified?'未能核验任务，请刷新记录。':isAdmin?'管理员只读，请由学校教师确认。':!isTeacher?'当前账号无权确认身份。':!imageReady||workspace?.media_available!==true?'采样图不可用，不能画框或新增确认。':workspace.needs_school_confirmation?'可画草稿；确认学校后才能选择姓名并保存。':!editable?'可画草稿；当前任务无保存权限，请核对学校归属。':uncertainWrite?'上次保存结果待核对，请刷新记录后再保存。':'';
  $('saveGate').hidden=!reason;$('saveGateReason').textContent=reason;$('schoolGateLink').hidden=!(isTeacher&&workspace?.needs_school_confirmation);$('schoolGateLink').disabled=locked;
  if(!reason)$('saveStatus').textContent=!validBox(box)?'请先选中一人，或手动画框。':!studentValid?'请选择这位学生的姓名。':'已选中，可确认。';else $('saveStatus').textContent=reason;
  $('candidateList').querySelectorAll('button').forEach(button=>button.disabled=!canPreview());
  $('bindingList').querySelectorAll('[data-revoke]').forEach(button=>button.disabled=locked||uncertainWrite||!canRevoke);
  $('bindingList').querySelectorAll('[data-frame]').forEach(button=>button.disabled=locked);
  $('bindingList').querySelectorAll('[data-track]').forEach(button=>button.disabled=!trackEligible(bindings().find(item=>item.binding_id===button.dataset.track)));
  $('exportBindings').hidden=!workspace;
  $('previewButton').disabled=!canReference()||!!previewController||$('previewDialog').open;
  $('zoomIn').disabled=locked||!imageReady||zoom>=4;$('zoomOut').disabled=locked||!imageReady||zoom<=1;$('resetZoom').disabled=locked||!imageReady;
  $('permissionState').textContent=loading?'正在核验任务':writing?'正在保存':uncertainWrite?'操作结果待核对':workspace?.needs_school_confirmation?'学校归属待确认':editable&&imageReady?'可确认当前帧':canRevoke?'仅可复核 / 撤销记录':isAdmin?'管理员只读':'当前只读';
  if(canDraw&&!editable&&!workspace.needs_school_confirmation)$('permissionState').textContent='可框选草稿 · 暂不可保存';
  $('permissionState').dataset.state=editable&&imageReady&&!uncertainWrite&&!locked?'editable':'readonly';
}
function paint(){
  const rect=(bbox,kind,label)=>validBox(bbox)?`<div class="roi ${kind}" style="left:${bbox.x*100}%;top:${bbox.y*100}%;width:${bbox.width*100}%;height:${bbox.height*100}%">${label?`<span>${esc(label)}</span>`:''}</div>`:'';
  $('frameOverlay').innerHTML=candidates.map((candidate,index)=>rect(candidate.bbox,'candidate',String(index+1))).join('')+bindings().filter(item=>currentBinding(item)&&item.frame_key===frame()?.frame_key).map(item=>rect(item.bbox,'confirmed',bindingName(item))).join('')+rect(box,'selected','');
}
function setBox(value,candidate=''){box=validBox(value)?{x:value.x,y:value.y,width:value.width,height:value.height}:null;selectedCandidate=candidate;coordinateIds.forEach((id,index)=>$(id).value=box?String(Math.round(box[['x','y','width','height'][index]]*1000)/10):'');dirty=isTeacher&&!!box;$('selectionStatus').textContent=box?(editable?'已选中一人，尚未保存。':'已框选草稿；仅预览，确认学校及权限后才能保存。'):'先选中画面中的一人。';$('candidateList').querySelectorAll('button').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.candidate===candidate)));paint();controls();}
function clearSelection(){box=null;dirty=false;selectedCandidate='';drawing=false;drag=null;$('frameSurface').classList.remove('is-drawing');$('drawButton').setAttribute('aria-pressed','false');coordinateIds.forEach(id=>$(id).value='');$('personRole').value='student';$('studentSelect').value='';$('studentChoice').hidden=false;$('selectionStatus').textContent='先选中画面中的一人。';paint();controls();}
function renderStudents(){const query=$('studentSearch').value.trim().toLocaleLowerCase();const previous=$('studentSelect').value;const students=(workspace?.students||[]).filter(s=>studentName(s).toLocaleLowerCase().includes(query));$('studentSelect').innerHTML='<option value="">请选择本校学生</option>'+students.map(s=>`<option value="${esc(s.student_id)}">${esc(studentName(s))}</option>`).join('');if(students.some(s=>s.student_id===previous))$('studentSelect').value=previous;controls();}
function renderBindings(){
  const all=bindings();const confirmed=all.filter(currentBinding);$('bindingSummary').textContent=`当前版本 ${confirmed.length} 条确认 · ${new Set(confirmed.map(b=>b.frame_key)).size} 个已确认帧`;
  const currentOnly=$('recordsCurrent').checked,visible=currentOnly?all.filter(item=>currentBinding(item)&&item.frame_key===frame()?.frame_key):all;
  $('recordCount').textContent=`${currentOnly?'当前帧':'全部历史'} ${visible.length} 条 · ${currentOnly?'仅当前版本有效确认':'含已撤销及历史版本'}`;
  $('bindingList').innerHTML=visible.length?visible.map(item=>{const active=currentBinding(item),revoked=item.status==='revoked',index=frames.findIndex(f=>f.frame_key===item.frame_key);return `<article class="record-row"><div><strong>${esc(bindingName(item))}</strong><small>${esc(seconds(item.time_sec))} · ${esc(item.frame_key)} · <span class="record-status ${active?'':'history'}">${revoked?'已撤销':active?'本帧已确认':'历史版本 / 不再有效'}</span></small></div><div class="record-actions">${index>=0?`<button class="button quiet" type="button" data-frame="${index}">${index===frameIndex?'返回画面':'查看采样帧'}</button>`:''}${isTeacher&&active&&item.role==='student'?`<button class="button" type="button" data-track="${esc(item.binding_id)}">查看后续5秒</button>`:''}${['confirmed','active'].includes(item.status)&&canRevoke?`<button class="button danger" type="button" data-revoke="${esc(item.binding_id)}">撤销</button>`:''}</div></article>`;}).join(''):`<div class="empty-state">${currentOnly?'当前帧暂无确认记录，可切换“全部历史”复核其他帧。':'本任务尚无身份确认。检测候选、上传时选择学生都不算已确认。'}</div>`;
  paint();controls();
}
async function detectFrame(){
  if(!frame()||!canPreview())return;detectController?.abort();const controller=new AbortController();detectController=controller;const epoch=frameEpoch;detectionLoading=true;controls();$('detectionStatus').textContent='正在检测本帧人脸位置，不识别姓名…';
  try{const data=await request('/detect?task_id='+encodeURIComponent(taskId)+'&frame_key='+encodeURIComponent(frame().frame_key)+'&frame_revision='+encodeURIComponent(workspace.frame_revision),undefined,controller.signal);if(epoch!==frameEpoch||controller.signal.aborted)return;
    const detection=data.detection;if(!detection)throw new Error('未返回候选结果，可手动画框。');candidates=detection.available===true&&Array.isArray(detection.faces)?detection.faces.filter(face=>validBox(face.bbox)):[];
    $('detectionStatus').textContent=detection.available!==true?detectionReason(detection.reason):candidates.length?`本帧 ${candidates.length} 个候选，均未确认姓名。`+(editable?'':'仅供位置预览，当前不能保存身份绑定。'): '本帧未检测到人脸候选，不代表学生缺席。'+(editable?'可手动画框，未知身份无需强行选名。':'当前仅可预览位置，不能保存身份绑定。');
    $('candidateList').innerHTML=candidates.map((face,index)=>`<button type="button" data-candidate="${index}" aria-pressed="false">候选 ${index+1}</button>`).join('');paint();
  }catch(error){if(epoch!==frameEpoch||controller.signal.aborted)return;candidates=[];$('candidateList').innerHTML='';$('detectionStatus').textContent=/[\u3400-\u9fff]/.test(error.message)?error.message+(editable?' 可手动画框，或重新检测。':' 可重新检测位置；当前不可保存身份绑定。'):detectionReason(error.code||error.message);paint();}
  finally{if(epoch===frameEpoch){detectionLoading=false;controls();}}
}
function displayFrame(index){
  closeReference();closeTrack();frameEpoch++;detectController?.abort();detectionLoading=false;frameIndex=index;imageReady=false;candidates=[];$('candidateList').innerHTML='';clearSelection();setZoom(1,true);renderBindings();
  const item=frame();$('frameSelect').value=String(index);$('frameSurface').hidden=true;$('frameEmpty').hidden=false;
  if(!item){$('frameImage').removeAttribute('src');$('frameTime').textContent='--:--';$('framePeriod').textContent='没有可用采样帧';$('framePosition').textContent='';$('recordsAll').checked=true;renderBindings();$('frameEmpty').textContent=workspace?.media_available===false?'原片或采样图不可用；不能新增确认，可查看服务器保留的记录。':'任务尚无可用采样帧，请先查看视频证据及处理状态。';$('detectionStatus').textContent=workspace?.media_available===false?'原片或采样图已不可用，无法检测；可复核保留记录。':'没有可用采样帧，无法检测。';controls();return;}
  $('frameTime').textContent=seconds(item.time_sec);$('framePeriod').textContent=`来源片段 ${seconds(item.segment_start_sec)} – ${seconds(item.segment_end_sec)}`;$('framePosition').textContent=`第 ${index+1} / ${frames.length} 帧`;$('jumpTime').value=String(item.time_sec);$('detectionStatus').textContent=isAdmin?'管理员仅查看已确认记录，不进行检测或绑定。':'正在读取原始采样图…';
  const url=safeImage(item.image_url);if(!url||workspace.media_available===false){$('frameImage').removeAttribute('src');$('frameEmpty').textContent='此帧原始图片不可用，不能新增确认。';$('detectionStatus').textContent='原片或采样图已不可用，无法检测；可复核保留记录。';controls();return;}
  const epoch=frameEpoch;const image=$('frameImage');image.onload=()=>{if(epoch!==frameEpoch)return;imageReady=image.naturalWidth>0&&image.naturalHeight>0;$('frameSurface').hidden=!imageReady;$('frameEmpty').hidden=imageReady;controls();paint();if(isTeacher&&imageReady)detectFrame();};
  image.onerror=()=>{if(epoch!==frameEpoch)return;imageReady=false;$('frameSurface').hidden=true;$('frameEmpty').hidden=false;$('frameEmpty').textContent='采样图读取失败或已到期，请刷新记录重试。';$('detectionStatus').textContent='图片不可用，已停止检测和新增确认。';controls();};
  $('frameEmpty').textContent='正在读取原始采样图…';image.alt=`课堂原始采样帧，${seconds(item.time_sec)}`;image.src=url;controls();
}
function changeFrame(index){if(loading||writing||index===frameIndex||index<0||index>=frames.length)return;if(!allowLeave()){$('frameSelect').value=String(frameIndex);return;}displayFrame(index);}
async function loadWorkspace(skipGuard=false,preserveDraft=false){
  if(loading||writing||(!skipGuard&&!allowLeave()))return;if(!taskId){$('frameEmpty').textContent='未选择视频任务，请返回上传工作台选择“确认画面中的学生”。';$('scopeNotice').textContent='没有任务时不会加载学生名册或发送绑定请求。';$('bindingList').innerHTML='<div class="empty-state">未选择任务。</div>';$('bindingSummary').textContent='未选择任务';$('taskCourse').textContent='未选择';$('taskSchool').textContent='未选择';return;}
  const previousKey=frame()?.frame_key,draft=preserveDraft&&box?{box:{...box},revision:workspace?.frame_revision}:null;closeReference();closeTrack();workspaceVerified=false;loading=true;editable=false;canRevoke=false;confirmationRoster=null;schoolConfirmationError='';rosterReadFailed=false;detectController?.abort();frameEpoch++;clearNotice();renderSchoolConfirmation();controls();
  try{
    const data=await request('/workspace?task_id='+encodeURIComponent(taskId));const next=data.workspace;if(!next||next.task_id!==taskId||!Array.isArray(next.students)||!Array.isArray(next.frames)||!Array.isArray(next.bindings))throw new Error('接口未返回完整的本任务工作区，请刷新重试。');
    workspace=next;workspaceVerified=true;inlineUncertain=false;renderSchoolConfirmation();frames=next.frames.filter(f=>f.frame_key&&Number.isFinite(f.time_sec));$('taskSchool').textContent=schoolName(next.school_context);$('taskCourse').textContent=[next.course_name,next.course_id].filter(Boolean).join(' · ')||'课程未返回';
    const resultsHref='/demo2/simple-result?task_id='+encodeURIComponent(taskId);$('studentStatusLink').href=resultsHref;$('continueToResults').href=resultsHref;
    const resultsReady=!next.task?.analysis_status||next.task.analysis_status==='evidence_ready';$('studentStatusLink').hidden=!resultsReady;$('continueToResults').hidden=!resultsReady;$('resultShortcutNote').hidden=!resultsReady;
    $('exportBindings').href='/api/v1/demo2/identity/export?task_id='+encodeURIComponent(taskId);$('videoLink').href='/demo2/video?id='+encodeURIComponent(taskId);$('videoLink').hidden=false;$('backLink').href=isAdmin?'/demo2/admin':'/demo2/upload?course_id='+encodeURIComponent(next.course_id||'');
    let scopeMatches=false;
    if(isTeacher){try{const response=await request('/roster');confirmationRoster=response.roster||null;scopeMatches=!!next.scope_key&&response.roster?.scope_key===next.scope_key&&response.roster?.can_edit===true;$('scopeNotice').textContent=scopeMatches?'学校归属一致。本次操作仅确认当前采样帧，不会自动关联其他帧。':'当前学校与任务的学校快照不一致或名册为只读，已停止新增及撤销。请核对学校归属；不会自动迁移学生。';}catch(error){rosterReadFailed=true;$('scopeNotice').textContent='无法核验当前学校，已停止新增及撤销。'+error.message;}}
    else $('scopeNotice').textContent=isAdmin?'管理员只读查看已确认记录。创建、检测、绑定及撤销请由该任务的学校教师完成。':'当前账号无权编辑本校身份确认。';
    editable=isTeacher&&next.can_edit===true&&!!next.scope_key&&next.frame_revision!=null&&next.needs_school_confirmation!==true;uncertainWrite=false;
    canRevoke=isTeacher&&!!next.scope_key&&next.can_revoke!==false;
    if(isTeacher&&!scopeMatches)$('scopeNotice').textContent='当前学校设置与任务归属不一致，或无法核验当前名册。本页仍按任务学校快照及原名册核对身份；不在此新增到当前学校，也不迁移学生。';
    if(next.needs_school_confirmation===true)$('scopeNotice').textContent=isTeacher?'此旧视频尚未确认学校归属，暂不能保存姓名绑定。请核对下方学校信息；真实帧仍可进行人脸位置预览。':'此旧视频尚未确认学校归属，请由所属学校教师核对。当前账号保持只读。';
    $('rosterNotice').textContent=next.students.length?`任务学校名册 ${next.students.length} 人；同名请核对编号和班级。`:scopeMatches?'任务学校名册为空。可先创建本校学生，未知或教师仍可按角色确认。':'任务学校名册为空。请先核对学校归属，再由任务学校建立名册。';$('rosterLink').hidden=!editable||!scopeMatches;$('rosterLink').href='/demo2/students?returntask='+encodeURIComponent(taskId);$('rosterLink').textContent=next.students.length?'打开本校名册':'创建本校学生名册';
    $('frameSelect').innerHTML=frames.length?frames.map((f,index)=>`<option value="${index}">${esc(seconds(f.time_sec))} · 第 ${index+1} 帧</option>`).join(''):'<option value="">尚无采样帧</option>';
    $('drawingHelp').textContent=isTeacher?'手动画框：点击按钮后，在图中拖动；也可填写百分比坐标。草稿不代表已确认姓名。':'管理员只读，不能画框或保存姓名。';
    renderStudents();renderBindings();loading=false;renderSchoolConfirmation();displayFrame(frames.length?Math.max(0,frames.findIndex(f=>f.frame_key===previousKey)):-1);
    if(draft&&frame()?.frame_key===previousKey&&workspace.frame_revision===draft.revision)setBox(draft.box);
  }catch(error){workspaceVerified=false;editable=false;schoolConfirmationError='工作区未能更新，学校归属尚未核实。请刷新记录重试。';notice(error.message);$('scopeNotice').textContent='工作区未能更新，已停止编辑。已显示内容可能不是最新记录，请刷新重试。';if(!workspace){$('frameEmpty').textContent='工作区读取失败，请刷新记录重试。';$('bindingList').innerHTML='<div class="empty-state">未能读取确认记录，不能据此判断没有记录。</div>';}}
  finally{loading=false;renderSchoolConfirmation();controls();}
}
$('confirmTaskSchool').addEventListener('click',async()=>{
  if(loading||writing||!confirmationReady())return;const context=confirmationRoster.school_context;const scope=confirmationRoster.scope_key;
  if(!window.confirm('请再次核对视频的实际学校：\n城市：'+context.city+'\n区县：'+context.district+'\n学校：'+context.school_name+'\n\n确认此视频属于上述学校吗？此操作只补齐这个旧任务的空白记录，不迁移已有学校快照。'))return;
  writing=true;editable=false;clearNotice();detectController?.abort();$('schoolConfirmationStatus').textContent='正在提交您的学校归属确认…';controls();let saved=false;
  try{await request('/task-school',{task_id:taskId,expected_scope_key:scope,confirmed:true});saved=true;}
  catch(error){schoolConfirmationError=error.message+' 学校归属未获确认，仍保持只读。请刷新记录核对后重试。';notice(schoolConfirmationError);}
  finally{writing=false;renderSchoolConfirmation();controls();}
  if(saved){await loadWorkspace(true,true);if(workspace?.needs_school_confirmation===false&&workspace?.scope_key&&!schoolConfirmationError)notice('学校已确认，请为框选的人选择姓名。','success');else{editable=false;schoolConfirmationError=schoolConfirmationError||'确认请求已提交，但工作区尚未确认更新。请刷新核对后再绑定姓名。';renderSchoolConfirmation();controls();}}
});
coordinateIds.forEach(id=>$(id).addEventListener('input',()=>{const values=coordinateIds.map(key=>$(key).value);const candidate=Object.fromEntries(['x','y','width','height'].map((key,index)=>[key,Number(values[index])/100]));box=values.every(v=>v.trim()!=='')&&validBox(candidate)?candidate:null;selectedCandidate='';dirty=values.some(v=>v!=='');$('selectionStatus').textContent=box?'当前坐标有效，尚未保存。':'请填写有效坐标：宽高大于 0，且框不能超出原图 100%。';paint();controls();}));
$('personRole').addEventListener('change',()=>{$('studentChoice').hidden=$('personRole').value!=='student';if($('personRole').value!=='student')$('studentSelect').value='';dirty=dirty||!!box;controls();});
$('studentSearch').addEventListener('input',renderStudents);$('studentSelect').addEventListener('change',()=>{dirty=dirty||!!box;controls();});
$('candidateList').addEventListener('click',event=>{const button=event.target.closest('[data-candidate]');if(!button||!canPreview())return;const candidate=candidates[Number(button.dataset.candidate)];if(candidate)setBox(candidate.bbox,button.dataset.candidate);});
$('retryDetection').addEventListener('click',detectFrame);$('clearSelection').addEventListener('click',()=>{if(!writing&&!loading)clearSelection();});
$('drawButton').addEventListener('click',()=>{if(!canDraft())return;drawing=!drawing;$('frameSurface').classList.toggle('is-drawing',drawing);$('drawButton').setAttribute('aria-pressed',String(drawing));$('selectionStatus').textContent=drawing?'画框已开启，请在图中拖动选中一人。':box?'已保留当前框选草稿。':'先选中画面中的一人。';$('drawingHelp').textContent=drawing?'在原图内拖动，完成后退出画框模式；Escape 取消。':'可手动画框，或填写百分比坐标。';if(drawing)returnToFrame();controls();});
function point(event){const bounds=$('frameSurface').getBoundingClientRect();return {x:clamp((event.clientX-bounds.left)/bounds.width),y:clamp((event.clientY-bounds.top)/bounds.height)};}
$('frameSurface').addEventListener('pointerdown',event=>{if(!canDraft()||event.button!==0)return;if(!drawing){const p=point(event);const index=candidates.findIndex(c=>p.x>=c.bbox.x&&p.x<=c.bbox.x+c.bbox.width&&p.y>=c.bbox.y&&p.y<=c.bbox.y+c.bbox.height);if(index>=0)setBox(candidates[index].bbox,String(index));return;}event.preventDefault();drag={start:point(event),pointer:event.pointerId,previous:box};$('frameSurface').setPointerCapture(event.pointerId);});
$('frameSurface').addEventListener('pointermove',event=>{if(!drag||drag.pointer!==event.pointerId)return;const end=point(event),start=drag.start;setBox({x:Math.min(start.x,end.x),y:Math.min(start.y,end.y),width:Math.abs(end.x-start.x),height:Math.abs(end.y-start.y)});});
$('frameSurface').addEventListener('pointerup',event=>{if(!drag||drag.pointer!==event.pointerId)return;const end=point(event),start=drag.start;setBox({x:Math.min(start.x,end.x),y:Math.min(start.y,end.y),width:Math.abs(end.x-start.x),height:Math.abs(end.y-start.y)});drag=null;drawing=false;$('frameSurface').classList.remove('is-drawing');$('drawButton').setAttribute('aria-pressed','false');$('frameSurface').releasePointerCapture(event.pointerId);});
$('frameSurface').addEventListener('pointercancel',()=>{if(drag)setBox(drag.previous);drag=null;drawing=false;$('frameSurface').classList.remove('is-drawing');$('drawButton').setAttribute('aria-pressed','false');});
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!$('revokeDialog').open&&!$('previewDialog').open&&!$('newStudentDialog').open&&!$('trackDialog').open&&!writing){clearSelection();}});
$('schoolGateLink').addEventListener('click',()=>{$('schoolConfirmation').scrollIntoView({block:'center'});(confirmationReady()?$('confirmTaskSchool'):$('completeSchoolLink')).focus({preventScroll:true});});
$('addStudent').addEventListener('click',()=>{if(!mayAddStudent())return;inlinePreviousDirty=dirty;inlineDirty=false;$('newStudentForm').reset();$('newStudentError').textContent='';$('newStudentSchool').textContent=schoolName(workspace.school_context);$('confirmNewStudent').disabled=false;$('newStudentDialog').showModal();$('inlineStudentName').focus();});
$('newStudentForm').addEventListener('input',()=>{inlineDirty=true;dirty=true;});
function closeNewStudent(){if(writing)return;if(inlineDirty&&!window.confirm('新增学生信息尚未保存，确定放弃吗？'))return;$('newStudentDialog').close();inlineDirty=false;dirty=inlinePreviousDirty||!!box;}
$('cancelNewStudent').addEventListener('click',closeNewStudent);$('newStudentDialog').addEventListener('cancel',event=>{event.preventDefault();closeNewStudent();});
$('newStudentForm').addEventListener('submit',async event=>{
  event.preventDefault();if(!mayAddStudent()||writing)return;
  const payload={display_name:$('inlineStudentName').value.trim(),student_code:$('inlineStudentCode').value.trim(),class_name:$('inlineStudentClass').value.trim(),note:''};
  if(!payload.display_name){$('newStudentError').textContent='请填写学生姓名。';return;}
  const scope=workspace.scope_key,same=(workspace.students||[]).filter(s=>s.display_name===payload.display_name);
  if(same.length&&!window.confirm('本校已有同名学生：\n'+same.map(studentName).join('\n')+'\n核对编号和班级后仍要新建吗？'))return;
  writing=true;controls();$('confirmNewStudent').disabled=true;$('cancelNewStudent').disabled=true;let submitted=false;
  try{
    const data=await request('/roster');confirmationRoster=data.roster;
    if(!confirmationRoster||confirmationRoster.scope_key!==scope||confirmationRoster.can_edit!==true)throw new Error('当前名册与任务学校不一致，已停止新增。请关闭后核对学校。');
    submitted=true;const result=await request('/students',payload),student=result.student;
    if(!student?.student_id||student.scope_key!==scope||typeof student.display_name!=='string'||!student.display_name.trim())throw new Error('创建结果或学校归属尚未确认，请刷新名册核对，避免重复创建。');
    workspace.students=workspace.students.filter(s=>s.student_id!==student.student_id).concat(student);confirmationRoster.students=workspace.students;
    $('studentSearch').value='';renderStudents();$('personRole').value='student';$('studentChoice').hidden=false;$('studentSelect').value=student.student_id;
    inlineDirty=false;dirty=inlinePreviousDirty||!!box;$('newStudentDialog').close();notice('已加入名册并选中「'+student.display_name+'」，框选区域已保留；尚未保存画面身份。','success');
  }catch(error){$('newStudentError').textContent=error.message;if(submitted&&!error.status)inlineUncertain=true;}
  finally{writing=false;$('cancelNewStudent').disabled=false;$('confirmNewStudent').disabled=!mayAddStudent();controls();}
});
$('closeTrack').addEventListener('click',closeTrack);$('trackDialog').addEventListener('cancel',event=>{event.preventDefault();closeTrack();});
$('trackDialog').addEventListener('close',()=>{if(!$('trackDialog').open)closeTrack();});
$('previousTrackPoint').addEventListener('click',()=>{if(trackResult&&trackIndex>0){trackIndex--;renderTrackPoint();}});
$('nextTrackPoint').addEventListener('click',()=>{if(trackResult&&trackIndex<trackResult.points.length-1){trackIndex++;renderTrackPoint();}});
window.addEventListener('resize',()=>{if($('trackDialog').open)fitTrackImage();});
$('bindingList').addEventListener('click',event=>{const button=event.target.closest('[data-track]');if(button)openTrack(button.dataset.track);});
$('adoptTrackPoint').addEventListener('click',()=>{
  const point=trackResult?.points[trackIndex],seed=trackSeed;
  if(!point||point.status!=='suggested'||!trackImageReady||!validBox(point.bbox)||!seed||!trackEligible(bindings().find(b=>b.binding_id===seed.binding_id))||trackResult.frame_revision!==workspace.frame_revision||!allowLeave())return;
  const index=frames.findIndex(f=>f.frame_key===point.frame_key);if(index<0)return;
  const bbox={...point.bbox},studentId=seed.student_id;closeTrack();if(index!==frameIndex)displayFrame(index);
  setBox(bbox);$('personRole').value='student';$('studentSearch').value='';renderStudents();$('studentChoice').hidden=false;$('studentSelect').value=studentId;dirty=true;controls();returnToFrame();notice('已采用位置建议为草稿，请核对这位学生后点击“确认姓名”；尚未写入记录。','info');
});
$('previewButton').addEventListener('click',openReference);$('closePreview').addEventListener('click',()=>closeReference(true));
$('previewDialog').addEventListener('cancel',event=>{event.preventDefault();closeReference(true);});
$('previewDialog').addEventListener('close',()=>{if(!$('previewDialog').open){clearReference();controls();}});
$('zoomIn').addEventListener('click',()=>setZoom(zoom+.25));$('zoomOut').addEventListener('click',()=>setZoom(zoom-.25));$('resetZoom').addEventListener('click',()=>setZoom(1,true));
$('frameViewport').addEventListener('keydown',event=>{if(event.target!==$('frameViewport')||event.ctrlKey||event.metaKey||event.altKey)return;if(['+','=','-','0'].includes(event.key)){event.preventDefault();setZoom(event.key==='0'?1:zoom+(event.key==='-'?-.25:.25),event.key==='0');}});
function returnToFrame(){$('frameViewport').scrollIntoView({block:'start'});$('frameViewport').focus({preventScroll:true});}
$('showRecords').addEventListener('click',()=>{$('recordsSection').scrollIntoView({block:'start'});$('bindingsTitle').focus({preventScroll:true});});
$('backToFrame').addEventListener('click',returnToFrame);
for(const id of ['recordsCurrent','recordsAll'])$(id).addEventListener('change',renderBindings);
$('bindingList').addEventListener('click',event=>{const button=event.target.closest('[data-frame]');if(!button||loading||writing)return;const index=Number(button.dataset.frame);changeFrame(index);if(index===frameIndex)returnToFrame();});
$('frameSelect').addEventListener('change',()=>changeFrame(Number($('frameSelect').value)));$('previousFrame').addEventListener('click',()=>changeFrame(frameIndex-1));$('nextFrame').addEventListener('click',()=>changeFrame(frameIndex+1));
$('jumpFrame').addEventListener('click',()=>{const target=Number($('jumpTime').value);if(!$('jumpTime').value||!Number.isFinite(target)||target<0){notice('请输入有效的秒数。');return;}const nearest=frames.reduce((best,f,index)=>Math.abs(f.time_sec-target)<Math.abs(frames[best].time_sec-target)?index:best,0);changeFrame(nearest);});
$('refreshWorkspace').addEventListener('click',()=>loadWorkspace());
$('bindingForm').addEventListener('submit',async event=>{
  event.preventDefault();if($('saveBinding').disabled||!editable||!imageReady||!validBox(box)||writing||loading||uncertainWrite||!frame())return;
  const role=$('personRole').value;if(!['student','teacher','unknown'].includes(role))return;const studentId=role==='student'?$('studentSelect').value:null;if(role==='student'&&!(workspace.students||[]).some(s=>s.student_id===studentId)){notice('请选择本校名册中的学生。');return;}
  const payload={task_id:taskId,frame_key:frame().frame_key,frame_revision:workspace.frame_revision,role,student_id:studentId,bbox:normalizedBox(box)};writing=true;detectController?.abort();clearNotice();controls();
  let saved=false,savedName='';try{
    let data;try{data=await request('/bindings',payload);}catch(error){
      if(error.status!==409||error.code!=='overlapping_student_binding'||role!=='student')throw error;
      if(!window.confirm('这个框与另一位学生的已确认区域高度重叠。请核对：确实是两位不同学生，且存在部分遮挡吗？\n确认后仅新增这条记录，不覆盖另一位学生。')){notice('未保存重叠区域，请核对姓名或重新框选。','info');return;}
      data=await request('/bindings',{...payload,overlap_confirmed:true});
    }
    if(!data.binding?.binding_id)throw new Error('保存结果尚未确认，请刷新记录核对。');savedName=bindingName(data.binding);workspace.bindings=bindings().filter(b=>b.binding_id!==data.binding.binding_id).concat(data.binding);saved=true;dirty=false;box=null;renderBindings();
  }catch(error){notice(error.status===409&&error.code==='indistinguishable_student_binding'?'两个框几乎相同，请框出各自可见部分或换一个时刻。完全遮挡时不能据此确认身份。':error.message);if(!error.status)uncertainWrite=true;if([403,409,410].includes(error.status)&&!(error.status===409&&['overlapping_student_binding','indistinguishable_student_binding'].includes(error.code)))editable=false;}
  finally{writing=false;controls();}if(saved){await loadWorkspace(true);if(editable)notice('已确认「'+savedName+'」。可继续选择下一人；仅保存当前帧身份。','success');}
});
$('bindingList').addEventListener('click',event=>{const button=event.target.closest('[data-revoke]');if(!button||!canRevoke||loading||writing||uncertainWrite||!allowLeave())return;revokeBinding=bindings().find(b=>b.binding_id===button.dataset.revoke&&['confirmed','active'].includes(b.status));if(!revokeBinding)return;clearSelection();$('revokeTarget').textContent=seconds(revokeBinding.time_sec)+' · '+bindingName(revokeBinding);$('revokeReason').value='';$('revokeError').textContent='';$('confirmRevoke').disabled=false;$('revokeDialog').showModal();$('revokeReason').focus();});
$('cancelRevoke').addEventListener('click',()=>{if(!writing){$('revokeDialog').close();revokeBinding=null;}});$('revokeDialog').addEventListener('cancel',event=>{if(writing)event.preventDefault();});
$('revokeForm').addEventListener('submit',async event=>{event.preventDefault();if(!canRevoke||!revokeBinding||writing||uncertainWrite)return;const reason=$('revokeReason').value.trim();if(!reason){$('revokeError').textContent='请填写撤销原因。';$('revokeReason').focus();return;}writing=true;controls();$('confirmRevoke').disabled=true;$('cancelRevoke').disabled=true;$('revokeReason').disabled=true;let saved=false;try{await request('/bindings/revoke',{task_id:taskId,binding_id:revokeBinding.binding_id,reason});saved=true;dirty=false;$('revokeDialog').close();}catch(error){$('revokeError').textContent=error.message;if(!error.status){uncertainWrite=true;$('revokeError').textContent+=' 操作结果尚未确认，请关闭弹窗后刷新记录核对。';}if([403,409].includes(error.status))canRevoke=false;}finally{writing=false;$('confirmRevoke').disabled=uncertainWrite||!canRevoke;$('cancelRevoke').disabled=false;$('revokeReason').disabled=false;controls();}if(saved){revokeBinding=null;await loadWorkspace(true);if(canRevoke)notice('该条身份确认已撤销，其余记录不受影响。','success');}});
window.addEventListener('pagehide',()=>{closeReference();closeTrack();frameEpoch++;detectController?.abort();});
window.addEventListener('pageshow',event=>{if(event.persisted&&!dirty&&!writing)loadWorkspace();});
installQuickTestProfiles();loadWorkspace();
"""


__all__ = ["render_students", "render_identity"]
