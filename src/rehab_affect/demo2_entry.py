"""Account entry and school onboarding views for the classroom platform."""

from __future__ import annotations

from typing import Any

from .demo2_portal import _BOOK_ICON, _WORKSPACE_STYLE, _account_payload, _document, _workspace_nav


ENTRY_STYLE = _WORKSPACE_STYLE + r"""
:root { --canvas:#f6f9fd; --ink:#263746; --muted:#627386; --line:#dce5ee; --blue-deep:#244f83; --shadow:none; }
body { background:#fff; font-family:"Segoe UI","Microsoft YaHei",sans-serif; font-size:15px; letter-spacing:0; }
.entry-shell { min-height:100svh; display:flex; flex-direction:column; border-top:4px solid var(--blue); }
.entry-header { min-height:72px; width:min(1200px,calc(100% - 64px)); margin:0 auto; display:flex; align-items:center; justify-content:space-between; gap:20px; }
.entry-shell>.workspace-nav { width:min(1200px,calc(100% - 64px)); margin:0 auto; border-top:1px solid var(--line); }
.entry-header .brand { width:auto; }
.entry-header .brand-copy strong { font-size:19px; font-weight:600; }
.entry-header .brand-copy span { font-size:11px; margin-top:3px; }
.entry-header .brand-icon { background:#edf4fe; color:var(--blue); width:44px; height:44px; }
.entry-header nav { display:flex; flex-shrink:0; align-items:center; gap:20px; font-size:13px; color:var(--muted); white-space:nowrap; }
.entry-header nav a { text-underline-offset:5px; text-decoration:none; }
.entry-header nav a:hover { color:var(--blue); text-decoration:underline; }
.pilot-label { padding-left:13px; border-left:1px solid var(--line); font-size:12px; color:var(--muted); }
.entry-main { flex:1; display:grid; place-items:center; padding:32px 24px 44px; background:#fff; border-block:1px solid #e7edf5; }
.entry-form-area { width:min(432px,100%); }
.entry-kicker { color:var(--blue); font-size:12px; font-weight:600; margin-bottom:10px; }
.entry-form-area h1 { font-size:26px; line-height:1.4; font-weight:600; color:#263b53; letter-spacing:0; }
.entry-subtitle { margin-top:10px; color:var(--muted); font-size:14px; line-height:1.8; }
.role-switch { display:grid; grid-template-columns:1fr 1fr; margin:22px 0; border-bottom:1px solid #cad8e8; }
.role-switch button { min-height:47px; background:transparent; border:0; border-bottom:3px solid transparent; margin-bottom:-1px; color:var(--muted); font-weight:500; }
.role-switch button[aria-checked="true"] { color:var(--blue); border-bottom-color:var(--blue); font-weight:700; }
.entry-form { display:grid; gap:16px; }
.entry-form .field label { color:#364b62; font-weight:500; font-size:14px; }
.entry-form input,.entry-form select { min-height:50px; border-color:#ccd8e5; padding:12px 14px; border-radius:6px; }
.entry-form .button.primary { min-height:50px; width:100%; font-weight:600; box-shadow:0 4px 10px #2265bd14; }
.entry-form .form-error { margin:0; }
.password-field { position:relative; }
.password-field input { padding-right:56px; }
.reveal-password { position:absolute; right:4px; top:3px; width:44px; height:44px; display:grid; place-items:center; background:transparent; border:0; color:#667b92; }
.reveal-password:hover { color:var(--blue); }
.entry-links { display:flex; justify-content:center; gap:8px; margin-top:24px; font-size:13px; color:var(--muted); }
.entry-links a { color:var(--blue); font-weight:600; text-underline-offset:4px; }
.entry-terms { font-size:12px; color:var(--muted); line-height:1.9; margin-top:24px; }
.entry-terms a { text-underline-offset:3px; color:#486588; }
.entry-footer { width:min(1200px,calc(100% - 64px)); margin:0 auto; min-height:68px; display:flex; align-items:center; justify-content:space-between; gap:12px; color:#7b8898; font-size:12px; }
.entry-footer a { text-decoration:none; text-underline-offset:3px; }
.entry-footer a:hover { text-decoration:underline; }
.school-area { width:min(640px,100%); }
.school-area .entry-form { margin-top:22px; }
.form-pair { display:grid; grid-template-columns:1fr 1fr; gap:18px; }
.school-summary { border-left:3px solid var(--blue); padding:12px 16px; background:#eaf2fc; margin-top:26px; }
.school-summary strong { display:block; font-size:15px; font-weight:600; }
.school-summary span { font-size:12px; color:var(--muted); }
.school-steps { display:flex; align-items:center; gap:14px; margin-bottom:30px; font-size:12px; color:var(--muted); }
.school-steps b { color:var(--blue); font-weight:600; }
.school-steps i { width:28px; height:1px; background:#c5d5e9; }
.registration-success { padding:24px 0; border-top:2px solid #327a69; }
.registration-success h2 { font-size:23px; margin:16px 0 10px; }
.registration-success p { margin-bottom:18px; color:var(--muted); line-height:1.9; }
.request-reference { font-family:Consolas,monospace; font-size:13px; word-break:break-all; color:#3e596f; }
.policy-article { width:min(760px,100%); }
.policy-article h1 { font-size:30px; }
.policy-article h2 { margin-top:30px; margin-bottom:10px; font-size:18px; }
.policy-article p { margin-top:8px; color:#4c6073; line-height:1.95; }
.policy-article .policy-date { font-size:12px; color:var(--muted); margin-top:12px; }
[hidden] { display:none !important; }
.entry-header nav,.entry-footer { flex-wrap:wrap; }
.entry-header nav a,.entry-footer a { display:inline-flex; align-items:center; min-height:44px; }
.entry-header .brand-copy { overflow-wrap:anywhere; }
.entry-form .field-error { color:var(--danger); font-size:12px; min-height:0; }
.entry-form input[aria-invalid=true] { border-color:var(--danger); }
.registration-layout { display:grid; grid-template-columns:minmax(0,440px) minmax(0,300px); gap:64px; width:min(900px,100%); align-items:start; }
.registration-layout .entry-form-area { width:100%; }
.registration-layout .entry-form { margin-top:26px; gap:17px; }
.phone-field { display:flex; align-items:center; position:relative; }
.phone-prefix { position:absolute; left:14px; padding-right:12px; border-right:1px solid var(--line); color:var(--blue-deep); font-size:14px; }
.phone-field input { padding-left:70px; }
.code-field { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; }
.code-field .button { font-size:13px; min-width:126px; font-weight:500; }
.entry-status { display:flex; align-items:flex-start; gap:10px; padding:12px 14px; background:#eef5ff; border:0; border-left:3px solid var(--blue); border-radius:0; font-size:13px; color:var(--blue-deep); margin-top:20px; }
.entry-status p { min-width:0; }
.entry-status svg { width:18px; height:18px; margin-top:2px; }
.entry-status.unavailable { background:#f0f3f7; border-color:var(--line); color:var(--muted); }
.registration-aside { margin-top:7px; border-left:1px solid var(--line); padding-left:28px; }
.registration-aside h2 { font-size:17px; margin-bottom:18px; }
.account-steps { margin:0; padding-left:20px; }
.account-steps li { padding:0 0 22px 8px; color:var(--muted); font-size:13px; }
.account-steps strong { display:block; color:var(--ink); margin-bottom:5px; font-size:14px; }
.aside-note { padding-top:18px; border-top:1px solid var(--line); font-size:12px; color:var(--muted); line-height:1.9; }
.config-refresh { min-height:44px; border:0; padding:8px 0; background:transparent; color:var(--blue); font-size:13px; text-decoration:underline; text-underline-offset:4px; }
.member-area { width:min(1020px,100%); min-width:0; }
.member-heading { display:flex; align-items:flex-start; justify-content:space-between; flex-wrap:wrap; gap:16px; margin-bottom:26px; }
.member-heading h1 { font-size:28px; font-weight:600; }
.member-heading .entry-subtitle { max-width:620px; }
.member-status-card { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:20px; border:0; border-block:1px solid var(--line); border-radius:0; padding:20px 0; background:#fff; }
.member-status-card h2 { font-size:19px; margin:0 0 16px; }
.member-facts { display:flex; flex-wrap:wrap; gap:18px 40px; margin:0; }
.member-facts dt { color:var(--muted); font-size:12px; }
.member-facts dd { margin:4px 0 0; font-size:15px; font-weight:600; overflow-wrap:anywhere; }
.member-section { margin-top:30px; }
.member-section h2 { font-size:19px; margin-bottom:8px; }
.member-section>p { font-size:13px; color:var(--muted); margin-bottom:16px; }
.plan-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
.plan-option { min-width:0; position:relative; display:block; cursor:pointer; }
.plan-option input { position:absolute; width:1px; height:1px; min-height:0; opacity:0; }
.plan-body { display:block; min-height:150px; padding:20px; border:1px solid var(--line); border-radius:6px; background:#fff; }
.plan-option input:checked + .plan-body { border-color:var(--blue); box-shadow:inset 0 0 0 1px var(--blue); background:#f7fbff; }
.plan-option input:focus-visible + .plan-body { outline:3px solid #8bb7ee; outline-offset:3px; }
.plan-option input:disabled + .plan-body { color:var(--muted); background:#f8fafc; cursor:not-allowed; }
.plan-body strong,.plan-body small,.plan-price { display:block; overflow-wrap:anywhere; }
.plan-body strong { font-size:15px; }.plan-body small { margin-top:8px; color:var(--muted); font-size:12px; }
.plan-price { font:600 24px/1.4 "Segoe UI","Microsoft YaHei UI",sans-serif; color:var(--blue-deep); margin-top:14px; }
.membership-command { display:flex; align-items:center; gap:16px; flex-wrap:wrap; margin-top:16px; }
.membership-command p { flex:1 1 240px; font-size:13px; color:var(--muted); }
.member-orders { display:grid; gap:10px; }
.member-order { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:12px; background:#fff; border:0; border-bottom:1px solid var(--line); border-radius:0; padding:16px 0; }
.member-order strong,.member-order small { display:block; overflow-wrap:anywhere; }
.member-order small { margin-top:5px; color:var(--muted); font-size:12px; }
.member-order .order-meta { text-align:right; }
@media(max-width:600px) {
  .entry-header { width:calc(100% - 32px); min-height:76px; gap:10px; }
  .entry-header .brand-copy strong { font-size:16px; }
  .entry-header .brand-copy span { font-size:10px; }
  .entry-header nav { gap:12px; font-size:12px; }
  .pilot-label { display:none; }
  .entry-main { padding:32px 24px 42px; }
  .entry-form-area h1,.policy-article h1 { font-size:26px; }
  .entry-footer { width:calc(100% - 40px); align-items:flex-start; padding:20px 0; font-size:11px; flex-wrap:wrap; }
  .form-pair { grid-template-columns:1fr; }
  .role-switch { margin-top:24px; }
  .entry-header { align-items:flex-start; flex-direction:column; padding:16px 0; }
  .entry-header nav { white-space:normal; justify-content:flex-start; }
  .entry-main { padding-inline:18px; }
  .entry-shell>.workspace-nav { width:calc(100% - 32px); }
  .registration-layout { grid-template-columns:minmax(0,1fr); gap:30px; }
  .registration-aside { border-left:0; border-top:1px solid var(--line); padding:24px 0 0; }
  .member-status-card,.member-order { grid-template-columns:minmax(0,1fr); padding:18px; }
  .member-order .order-meta { text-align:left; }
  .plan-grid { grid-template-columns:minmax(0,1fr); }
  .member-heading h1 { font-size:25px; }
}
"""

# Lucide eye icon geometry (ISC license), matching the existing outline icons.
EYE_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy="12" r="3"/></svg>'
SHIELD_ICON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m12 3 8 4v5c0 5-8 9-8 9s-8-4-8-9V7z"/><path d="m8 12 3 3 5-6"/></svg>'


def _shell(content: str, *, nav: str = '<a href="/demo2/help">使用帮助</a><a href="/demo2/register">会员注册</a>', workspace_active: str = "") -> str:
    return f"""<div class="entry-shell">
<header class="entry-header"><a class="brand" href="/demo2/login">{_BOOK_ICON}<span class="brand-copy"><strong>课堂学习分析平台</strong><span>RehabAffect · 云图智航</span></span></a><nav aria-label="入口导航">{nav}<span class="pilot-label">学校内测</span></nav></header>
{_workspace_nav(workspace_active) if workspace_active else ""}
<main class="entry-main" id="mainContent">{content}</main>
<footer class="entry-footer"><span>云图智航 · 课堂学习与个体成长</span><a href="/demo2/privacy#membership">会员服务说明</a><a href="/demo2/privacy">数据安全与隐私说明</a></footer></div>"""


COMMON_SCRIPT = r"""
const byId=id=>document.getElementById(id);
function showError(message) { const node=byId('formError'); node.textContent=message; node.className='form-error visible'; }
function clearError(){byId('formError').textContent='';byId('formError').className='form-error';}
function safeNextUrl(value,fallback,role){
  const allowed=role==='registered_member'?['/demo2/membership']:role==='company_admin'?['/demo2/admin','/demo2/membership']:['/demo2/school','/demo2/upload','/demo2/membership'];
  if(typeof value!=='string'||!value.startsWith('/')||value.startsWith('//')||/[\\\u0000-\u0020]/.test(value))return fallback;
  try{const next=new URL(value,location.origin);return next.origin===location.origin&&allowed.includes(next.pathname)?next.pathname+next.search+next.hash:fallback;}catch(_){return fallback;}
}
function bindPassword(inputId,buttonId){const input=byId(inputId),button=byId(buttonId);button.addEventListener('click',()=>{const visible=input.type==='password';input.type=visible?'text':'password';button.setAttribute('aria-pressed',String(visible));button.setAttribute('aria-label',visible?'隐藏密码':'显示密码');button.title=visible?'隐藏密码':'显示密码';});}
async function request(url,payload) {
  const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),20000);
  try{
    const response=await fetch(url,{credentials:'same-origin',signal:controller.signal,...(payload===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})});
    const data=await response.json().catch(error=>{if(error.name==='AbortError'||error instanceof TypeError)throw error;return {};});
    if(!response.ok||data.error){const error=new Error(data.error?.message||({401:'登录已过期，请重新登录。',403:'当前账号无权进行此操作。',429:'操作较频繁，请稍后重试。',503:'服务暂未配置，请稍后查看。'}[response.status])||'服务暂时不可用，请稍后重试。');error.status=response.status;error.retryAfter=Number(response.headers.get('Retry-After'))||0;throw error;}
    return data;
  }catch(error){if(error.name==='AbortError')throw new Error('请求超时，请检查网络后重试。');if(error instanceof TypeError)throw new Error('网络连接失败，请检查网络后重试。');throw error;}finally{clearTimeout(timer);}
}
"""


def render_login() -> str:
    content = f"""<section class="entry-form-area" aria-labelledby="loginTitle">
<p class="entry-kicker">欢迎使用 RehabAffect</p><h1 id="loginTitle">登录课堂工作台</h1><p class="entry-subtitle" id="roleDescription">使用手机号或已有内测账号登录。</p>
<div class="role-switch" role="radiogroup" aria-label="登录身份"><button type="button" role="radio" aria-checked="true" data-role="school_uploader" id="userRole">用户登录</button><button type="button" role="radio" aria-checked="false" data-role="company_admin" id="adminRole" tabindex="-1">管理员登录</button></div>
<form id="loginForm" class="entry-form">
<div class="field"><label for="username">账号</label><input id="username" name="username" autocomplete="username" maxlength="80" required placeholder="手机号或内测账号，例如 t1" /><small>新用户使用注册手机号；原学校内测账号继续有效。</small></div>
<div class="field"><label for="password">密码</label><div class="password-field"><input id="password" name="password" type="password" autocomplete="current-password" maxlength="256" required placeholder="输入登录密码" /><button type="button" class="reveal-password" id="showPassword" aria-label="显示密码" title="显示密码" aria-pressed="false">{EYE_ICON}</button></div></div>
<div class="form-error" id="formError" role="alert" aria-live="polite"></div>
<button class="button primary" id="loginButton" type="submit">登录</button></form>
<p class="entry-links"><span>还没有账号？</span><a href="/demo2/register">手机号注册</a></p>
<p class="entry-terms">请阅读<a href="/demo2/privacy">数据安全与隐私说明</a>。注册账号与付费会员开通分别办理；登录本身不代表同意上传学生资料。</p>
</section>"""
    script = COMMON_SCRIPT + r"""
let selectedRole='school_uploader';
let loginPending=false;
const roleButtons=[...document.querySelectorAll('[data-role]')];
function selectRole(button) {
  if(loginPending)return;
  selectedRole=button.dataset.role;
  roleButtons.forEach(item=>{const active=item===button;item.setAttribute('aria-checked',String(active));item.tabIndex=active?0:-1;});
  byId('username').placeholder=selectedRole==='company_admin'?'输入管理员账号，例如 admin':'手机号或内测账号，例如 t1';
  byId('roleDescription').textContent=selectedRole==='company_admin'?'使用公司授权的管理员账号查看后台。':'使用手机号或已有内测账号登录。';
  byId('formError').className='form-error';
}
roleButtons.forEach(button=>{button.addEventListener('click',()=>selectRole(button));button.addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const next=event.key==='Home'?roleButtons[0]:event.key==='End'?roleButtons[1]:roleButtons.find(item=>item!==button);selectRole(next);next.focus();}});});
bindPassword('password','showPassword');
try {const notice=sessionStorage.getItem('demo2_notice');if(notice){showError(notice);sessionStorage.removeItem('demo2_notice');}} catch(_) {}
byId('loginForm').addEventListener('submit',async event=>{
  event.preventDefault();if(loginPending)return;const button=byId('loginButton');loginPending=true;button.disabled=true;button.textContent='正在登录';roleButtons.forEach(item=>item.disabled=true);clearError();
  try {const data=await request('/api/v1/demo2/auth/login',{username:byId('username').value.trim(),password:byId('password').value,role:selectedRole});const role=data.account?.role;if(!['school_uploader','registered_member','company_admin'].includes(role))throw new Error('登录响应缺少账号身份，请重新登录。');const fallback=role==='registered_member'?'/demo2/membership':role==='company_admin'?'/demo2/admin':'/demo2/school';location.assign(safeNextUrl(data.next_url,fallback,role));}
  catch(error){showError(error.message);byId('password').focus();}
  finally{loginPending=false;button.disabled=false;button.textContent='登录';roleButtons.forEach(item=>item.disabled=false);}
});
"""
    return _document(title="登录 · 课堂学习分析平台", body=_shell(content), page_style=ENTRY_STYLE, script=script)


def render_school(account: Any | None = None) -> str:
    content = """<section class="entry-form-area school-area" aria-labelledby="schoolTitle">
<p class="entry-kicker" id="accountGreeting">学校工作台</p><h1 id="schoolTitle">学校信息</h1><p class="entry-subtitle">确认本次课程的学校归属。</p>
<form id="schoolForm" class="entry-form">
<div class="form-pair"><div class="field"><label for="city">城市</label><input id="city" name="city" list="cityOptions" maxlength="80" placeholder="例如：上海市" autocomplete="address-level1" required /><datalist id="cityOptions"></datalist></div>
<div class="field"><label for="district">区县</label><input id="district" name="district" list="districtOptions" maxlength="80" placeholder="填写所在区县" autocomplete="address-level2" required /><datalist id="districtOptions"></datalist></div></div>
<div class="field"><label for="schoolName">学校</label><input id="schoolName" name="school_name" list="schoolOptions" maxlength="160" placeholder="填写学校全称" autocomplete="organization" required /><datalist id="schoolOptions"></datalist></div>
<div class="form-error" id="formError" role="alert"></div><button class="button primary" id="schoolButton" type="submit" disabled>进入课程工作台</button>
</form><div class="school-summary" id="schoolSummary" hidden><strong id="savedSchool"></strong><span id="savedRegion"></span></div>
<p class="entry-terms">学校信息用于整理课程资料。账号可访问的上传通道由管理员分配。</p><p class="entry-terms" id="returnTaskNotice" hidden>此处仅保存当前账号的学校信息。返回旧视频后，请核对并显式确认视频归属；不会自动补齐任务的学校记录。</p></section>"""
    script = COMMON_SCRIPT + f"\nconst SCHOOL_ACCOUNT={_account_payload(account)};\n" + r"""
let options=[];
const returnTaskCandidate=new URLSearchParams(location.search).get('returntask')||'';
const returnTask=/^[A-Za-z0-9_-]{1,128}$/.test(returnTaskCandidate)?returnTaskCandidate:'';
const schoolNextUrl=returnTask?'/demo2/identity?task_id='+encodeURIComponent(returnTask):'/demo2/upload';
const schoolButtonLabel=returnTask?'保存并返回视频身份确认':'进入课程工作台';
byId('schoolButton').textContent=schoolButtonLabel;byId('returnTaskNotice').hidden=!returnTask;
function setOptions(id,values){byId(id).replaceChildren(...[...new Set(values.filter(Boolean))].map(value=>{const item=document.createElement('option');item.value=value;return item;}));}
function refreshOptions(){setOptions('cityOptions',options.map(item=>item.city));setOptions('districtOptions',options.filter(item=>item.city===byId('city').value.trim()).map(item=>item.district));setOptions('schoolOptions',options.filter(item=>item.city===byId('city').value.trim()&&item.district===byId('district').value.trim()).map(item=>item.school_name));}
byId('accountGreeting').textContent='学校工作台 · '+(SCHOOL_ACCOUNT.login_alias||SCHOOL_ACCOUNT.username||'');
byId('city').addEventListener('change',()=>{byId('district').value='';byId('schoolName').value='';refreshOptions();});
byId('district').addEventListener('change',()=>{byId('schoolName').value='';refreshOptions();});
request('/api/v1/demo2/school/context').then(data=>{const context=data.context||{};byId('city').value=context.city||'';byId('district').value=context.district||'';byId('schoolName').value=context.school_name||'';options=data.options||[];refreshOptions();if(context.school_name){byId('schoolSummary').hidden=false;byId('savedSchool').textContent=context.school_name;byId('savedRegion').textContent=[context.city,context.district].filter(Boolean).join(' · ');}byId('schoolButton').disabled=false;}).catch(error=>showError(error.message+' 请重新登录后重试。'));
byId('schoolForm').addEventListener('submit',async event=>{event.preventDefault();const button=byId('schoolButton');button.disabled=true;button.textContent='正在保存';try{await request('/api/v1/demo2/school/context',{city:byId('city').value.trim(),district:byId('district').value.trim(),school_name:byId('schoolName').value.trim()});location.assign(schoolNextUrl);}catch(error){showError(error.message);}finally{button.disabled=false;button.textContent=schoolButtonLabel;}});
byId('logoutButton').addEventListener('click',async()=>{try{await request('/api/v1/demo2/auth/logout',{});}finally{location.assign('/demo2/login');}});
"""
    return _document(title="学校选择 · 课堂学习分析平台", body=_shell(content, nav='<button class="button quiet" id="logoutButton" type="button">退出登录</button>', workspace_active="school"), page_style=ENTRY_STYLE, script=script)


def render_register() -> str:
    content = """<div class="registration-layout"><section class="entry-form-area" aria-labelledby="registerTitle">
<p class="entry-kicker">RehabAffect · 账号与会员</p><h1 id="registerTitle">手机号注册</h1><p class="entry-subtitle">验证手机号并设置登录密码，随后查看会员服务与开通状态。</p>
<div class="entry-status unavailable" id="smsNotice">__SHIELD__<p id="smsStatus" role="status">正在读取短信注册服务状态…</p></div><button class="config-refresh" id="reloadConfigButton" type="button">重新检查服务状态</button>
<form id="registerForm" class="entry-form" novalidate>
<div class="field"><label for="phone">中国大陆手机号</label><div class="phone-field"><span class="phone-prefix" aria-hidden="true">+86</span><input id="phone" name="phone" type="tel" inputmode="numeric" autocomplete="tel-national" maxlength="11" placeholder="11 位手机号" aria-describedby="phoneHelp phoneError" required /></div><small id="phoneHelp">用于短信验证与后续登录，仅支持 +86 中国大陆号码。</small><small class="field-error" id="phoneError" role="status"></small></div>
<div class="field"><label for="code">短信验证码</label><div class="code-field"><input id="code" name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="6 位验证码" aria-describedby="codeError" required /><button class="button" id="sendCodeButton" type="button" disabled>获取验证码</button></div><small class="field-error" id="codeError" role="status"></small><small id="codeStatus" role="status"></small></div>
<div class="field"><label for="password">设置密码</label><div class="password-field"><input id="password" name="password" type="password" autocomplete="new-password" minlength="8" maxlength="72" aria-describedby="passwordHelp passwordError" placeholder="8–72 位字母与数字" required /><button type="button" class="reveal-password" id="showPassword" aria-label="显示密码" title="显示密码" aria-pressed="false">__EYE__</button></div><small id="passwordHelp">8–72 位，仅限英文字母和数字，且两者都需包含。</small><small class="field-error" id="passwordError" role="status"></small></div>
<div class="field"><label for="confirmPassword">确认密码</label><div class="password-field"><input id="confirmPassword" name="confirm_password" type="password" autocomplete="new-password" maxlength="72" aria-describedby="confirmPasswordError" placeholder="再次输入密码" required /><button type="button" class="reveal-password" id="showConfirmPassword" aria-label="显示确认密码" title="显示确认密码" aria-pressed="false">__EYE__</button></div><small class="field-error" id="confirmPasswordError" role="status"></small></div>
<div class="form-error" id="formError" role="alert" tabindex="-1"></div>
<p class="entry-terms" style="margin:0">点击注册即表示同意<a href="/demo2/privacy#registration" target="_blank" rel="noopener">账号注册与隐私说明</a>及<a href="/demo2/privacy#membership" target="_blank" rel="noopener">会员服务说明</a>（2026-09-09）。注册不会扣费，也不会自动开通会员。</p>
<button class="button primary" id="registerButton" type="submit" disabled>注册并前往会员开通</button></form>
<p class="entry-links"><span>已有账号？</span><a href="/demo2/login">返回登录</a></p></section>
<aside class="registration-aside" aria-label="注册后的使用步骤"><h2>从账号到会员服务</h2><ol class="account-steps"><li><strong>验证手机号</strong>通过短信验证码确认号码由你使用。</li><li><strong>创建登录账号</strong>设置密码，后续使用手机号登录。</li><li><strong>查看会员开通</strong>套餐、服务金额和支付状态以会员中心实际显示为准。</li></ol><p class="aside-note">注册账号不等于购买成功。学校通道与学生资料需单独授权，新注册成员不会自动获得既有学校数据。已有学校内测账号可继续从登录页进入。</p></aside></div>""".replace("__EYE__", EYE_ICON).replace("__SHIELD__", SHIELD_ICON)
    script = COMMON_SCRIPT + r"""
const AGREEMENT_VERSION='2026-09-09';
let smsAvailable=false,configBusy=false,sending=false,registering=false,cooldownUntil=0,cooldownTimer=null,leaving=false;
function fieldError(id,text){byId(id+'Error').textContent=text;byId(id).setAttribute('aria-invalid',String(!!text));return !text;}
function validate(id){const value=byId(id).value;let error='';if(id==='phone'&&!/^1[3-9]\d{9}$/.test(value.trim()))error='请输入有效的 11 位中国大陆手机号。';if(id==='code'&&!/^\d{6}$/.test(value.trim()))error='请输入短信中的 6 位验证码。';if(id==='password'&&(!/^[A-Za-z0-9]{8,72}$/.test(value)||!/[A-Za-z]/.test(value)||!/[0-9]/.test(value)))error='密码应为 8–72 位英文字母与数字，且必须同时包含两者。';if(id==='confirmPassword'&&(!value||value!==byId('password').value))error='两次输入的密码不一致。';return fieldError(id,error);}
function syncControls(){const seconds=Math.max(0,Math.ceil((cooldownUntil-Date.now())/1000));byId('sendCodeButton').disabled=!smsAvailable||configBusy||sending||registering||seconds>0;byId('sendCodeButton').textContent=sending?'正在请求':seconds?`${seconds} 秒后重新获取`:'获取验证码';byId('registerButton').disabled=!smsAvailable||configBusy||sending||registering;byId('reloadConfigButton').disabled=configBusy||sending||registering;['phone','code','password','confirmPassword'].forEach(id=>byId(id).disabled=registering||(id==='phone'&&sending));}
function tickCooldown(){clearTimeout(cooldownTimer);syncControls();if(cooldownUntil>Date.now()&&!leaving)cooldownTimer=setTimeout(tickCooldown,1000);}
function startCooldown(seconds=60){cooldownUntil=Date.now()+Math.max(60,seconds)*1000;tickCooldown();}
async function loadConfig(){if(configBusy||sending||registering)return;configBusy=true;smsAvailable=false;syncControls();byId('smsStatus').textContent='正在读取短信注册服务状态…';try{const response=await request('/api/v1/demo2/membership/config');const config=response.config||response;smsAvailable=config.sms_available===true&&config.agreement_version===AGREEMENT_VERSION;byId('smsNotice').className='entry-status'+(smsAvailable?'':' unavailable');byId('smsStatus').textContent=config.agreement_version&&config.agreement_version!==AGREEMENT_VERSION?'注册协议已更新，请刷新页面后再试。':smsAvailable?'短信注册已开放。完成验证后创建账号，会员需另行开通。':'暂未开通短信注册。已有内测账号可返回登录，新用户请稍后查看。';}catch(error){byId('smsStatus').textContent='暂时无法读取注册服务状态，请重新检查。';showError(error.message);}finally{configBusy=false;syncControls();}}
bindPassword('password','showPassword');bindPassword('confirmPassword','showConfirmPassword');
['phone','code','password','confirmPassword'].forEach(id=>byId(id).addEventListener('blur',()=>validate(id)));
byId('phone').addEventListener('input',()=>{byId('code').value='';byId('codeStatus').textContent='';fieldError('phone','');fieldError('code','');});
byId('sendCodeButton').addEventListener('click',async()=>{if(!smsAvailable||sending||registering||Date.now()<cooldownUntil)return;if(!validate('phone')){byId('phone').focus();return;}sending=true;clearError();syncControls();byId('codeStatus').textContent='';try{const response=await request('/api/v1/demo2/auth/sms-code',{phone:byId('phone').value.trim()});const data=response.result||response;if(data.sent===false||data.sms_available===false)throw new Error('短信服务暂不可用，验证码未发送。');startCooldown(Number(data.retry_after)||60);byId('codeStatus').textContent='验证码请求已受理，请查看手机短信。';byId('code').focus();}catch(error){if(error.status===503){smsAvailable=false;byId('smsStatus').textContent='暂未开通短信注册，请稍后查看。';}if(error.status===429)startCooldown(error.retryAfter||60);showError(error.message);}finally{sending=false;syncControls();}});
byId('registerForm').addEventListener('submit',async event=>{event.preventDefault();if(registering||sending)return;if(!smsAvailable){showError('暂未开通短信注册，请先检查服务状态。');return;}const invalid=['phone','code','password','confirmPassword'].filter(id=>!validate(id));if(invalid.length){byId(invalid[0]).focus();return;}registering=true;clearError();syncControls();byId('registerButton').textContent='正在创建账号';try{const data=await request('/api/v1/demo2/auth/register',{phone:byId('phone').value.trim(),code:byId('code').value.trim(),password:byId('password').value,accepted:true,agreement_version:AGREEMENT_VERSION});if(!data.account)throw new Error('注册响应尚未确认账号创建，请检查后再登录。');byId('password').value='';byId('confirmPassword').value='';byId('code').value='';location.assign(safeNextUrl(data.next_url,'/demo2/membership','registered_member'));}catch(error){if(error.status===503){smsAvailable=false;byId('smsStatus').textContent='短信注册暂不可用，请稍后查看。';}showError(error.message);}finally{registering=false;byId('registerButton').textContent='注册并前往会员开通';syncControls();}});
byId('reloadConfigButton').addEventListener('click',()=>{clearError();loadConfig();});
window.addEventListener('pagehide',()=>{leaving=true;clearTimeout(cooldownTimer);});window.addEventListener('pageshow',event=>{if(event.persisted){leaving=false;tickCooldown();}});
loadConfig();
"""
    return _document(title="会员注册 · 课堂学习分析平台", body=_shell(content, nav='<a href="/demo2/login">返回登录</a>'), page_style=ENTRY_STYLE, script=script)


def render_membership(account: Any | None = None) -> str:
    content = """<section class="member-area" id="membershipCenter" aria-labelledby="membershipTitle">
<div class="member-heading"><div><p class="entry-kicker">账号与会员</p><h1 id="membershipTitle">会员中心</h1><p class="entry-subtitle">查看会员状态、服务套餐与订单。注册账号后，会员服务需另行开通。</p></div><button class="button" id="refreshMembershipButton" type="button">刷新状态</button></div>
<div class="form-error" id="formError" role="alert" tabindex="-1"></div>
<section class="member-status-card" aria-labelledby="membershipStatus"><div><h2 id="membershipStatus" role="status">正在读取会员状态</h2><dl class="member-facts"><div><dt>绑定手机号</dt><dd id="memberPhone">—</dd></div><div><dt>有效期至</dt><dd id="membershipExpiry">—</dd></div></dl></div><a class="button" id="schoolWorkspaceLink" href="/demo2/school" hidden>进入学校工作台</a></section>
<div class="entry-status unavailable">__SHIELD__<p id="schoolAccessStatus">会员状态与学校数据权限分别核验。正在读取账号权限…</p></div>
<section class="member-section" aria-labelledby="plansTitle"><h2 id="plansTitle">会员服务套餐</h2><p>服务内容与金额以实际公布的套餐为准。创建订单或完成注册均不代表支付成功。</p><div class="plan-grid" id="membershipPlans" role="radiogroup" aria-labelledby="plansTitle"><div class="empty-state">正在读取套餐信息…</div></div><div class="membership-command"><button class="button primary" id="orderButton" type="button" disabled>支付暂未配置</button><p id="paymentStatus" role="status">正在核对支付服务，当前不可支付。</p></div><p class="entry-terms">下单前请阅读<a href="/demo2/privacy#membership">会员服务说明</a>。支付开通、有效期和订单结果以系统确认的信息为准。</p></section>
<section class="member-section" aria-labelledby="ordersTitle"><h2 id="ordersTitle">订单记录</h2><p>仅显示当前账号的真实订单；未支付订单不会开通会员。</p><div class="member-orders" id="membershipOrders"><div class="empty-state">正在读取订单记录…</div></div></section>
</section>""".replace("__SHIELD__", SHIELD_ICON)
    script = COMMON_SCRIPT + f"\nconst MEMBER_ACCOUNT={_account_payload(account)};\n" + r"""
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
let membership=null,selectedPlan='',loadingMembership=false,creatingOrder=false;
const money=cents=>typeof cents==='number'&&Number.isFinite(cents)&&Number.isInteger(cents)&&cents>=0?`¥${(cents/100).toFixed(2)}`:'待公布';
const dateText=value=>{if(!value)return '尚无有效期';const date=new Date(value);return Number.isNaN(date.getTime())?'时间待确认':date.toLocaleDateString('zh-CN');};
const maskedPhone=value=>{const phone=String(value||'');if(!phone)return '未绑定手机号';return /\d{7,}/.test(phone)?phone.replace(/(\d{3})\d{4}(\d{4})/g,'$1****$2'):phone;};
const orderStatus=value=>({pending:'待支付',pending_payment:'待支付',unpaid:'待支付',paid:'已支付',completed:'已完成',cancelled:'已取消',expired:'已关闭',closed:'已关闭',failed:'支付未完成',refunded:'已退款'}[value]||'状态待确认');
function plans(){return Array.isArray(membership?.plans)?membership.plans:[];}
function updateOrderButton(){const plan=plans().find(item=>item.plan_id===selectedPlan);const configured=membership?.payment_available===true;const canOrder=MEMBER_ACCOUNT.role==='registered_member';byId('orderButton').disabled=loadingMembership||creatingOrder||!canOrder||!configured||!plan||plan.available===false||money(plan.price_cents)==='待公布';byId('orderButton').textContent=creatingOrder?'正在创建订单':!configured?'支付暂未配置':!canOrder?'内测账号不办理付费订单':'创建会员订单';byId('refreshMembershipButton').disabled=loadingMembership||creatingOrder;}
function renderMembership(data){
  membership=data;
  byId('membershipStatus').textContent=data.status_label||({inactive:'会员未开通',not_activated:'会员未开通',not_active:'会员未开通',none:'会员未开通',registered:'会员未开通',active:'会员已开通',expired:'会员已到期',trial:'内测授权',internal_trial:'内测账号'}[data.status]||'会员状态待确认');
  byId('memberPhone').textContent=maskedPhone(data.phone_masked);byId('membershipExpiry').textContent=dateText(data.expires_at);
  const schoolAccess=data.school_access===true&&MEMBER_ACCOUNT.role==='school_uploader';
  const adminAccess=MEMBER_ACCOUNT.role==='company_admin';
  byId('schoolWorkspaceLink').hidden=!(schoolAccess||adminAccess);
  byId('schoolWorkspaceLink').href=adminAccess?'/demo2/admin':'/demo2/school';
  byId('schoolWorkspaceLink').textContent=adminAccess?'返回公司后台':'进入学校工作台';
  byId('schoolAccessStatus').textContent=adminAccess?'当前公司管理员的原有管理权限保留，请返回公司后台使用。内测账号不代表已购买付费会员。':schoolAccess?'当前账号具有既有学校工作台权限；这项权限不代表已购买付费会员。':'当前账号不具备学校资料访问权限。注册或会员开通不会自动授予其他学校的学生数据权限。';
  if(!plans().some(plan=>plan.plan_id===selectedPlan))selectedPlan='';
  byId('membershipPlans').innerHTML=plans().length?plans().map(plan=>`<label class="plan-option"><input type="radio" name="membershipPlan" value="${esc(plan.plan_id||'')}" ${plan.plan_id===selectedPlan?'checked':''} ${!plan.plan_id||plan.available===false?'disabled':''}/><span class="plan-body"><strong>${esc(plan.name||plan.plan_name||'服务套餐')}</strong><small>${esc(plan.description||'服务内容待公布')}</small><span class="plan-price">${esc(money(plan.price_cents))}</span><small>${esc(plan.period_label||plan.duration_label||(Number.isInteger(plan.duration_days)&&plan.duration_days>0?`${plan.duration_days} 天`:'服务期限以套餐公布信息为准'))}</small>${plan.available===false?'<small>暂未开放购买</small>':''}</span></label>`).join(''):'<div class="empty-state">会员套餐与服务金额待公布。当前没有可购买的套餐。</div>';
  const orders=Array.isArray(data.orders)?data.orders:[];
  byId('membershipOrders').innerHTML=orders.length?orders.map(order=>`<article class="member-order"><div><strong>${esc(order.plan_name||order.name||'会员服务订单')}</strong><small>订单号 ${esc(order.order_id||'未返回')}</small><small>${esc(dateText(order.created_at))}</small></div><div class="order-meta"><strong>${esc(money(order.amount_cents??order.price_cents))}</strong><span class="status-badge">${esc(order.status_label||orderStatus(order.status))}</span></div></article>`).join(''):'<div class="empty-state">暂无订单。完成注册不会自动创建付费订单。</div>';
  byId('paymentStatus').textContent=data.payment_available===true?'选择已公布金额的套餐后可创建订单；会员是否开通以实际支付确认结果为准。':'支付暂未配置，当前无法付款或开通付费会员。套餐金额未公布时显示“待公布”，不会自动扣费。';
  updateOrderButton();
}
async function refreshMembership(){if(loadingMembership||creatingOrder)return;loadingMembership=true;clearError();updateOrderButton();try{const response=await request('/api/v1/demo2/membership');renderMembership(response.membership||response);}catch(error){if(error.status===401){location.assign('/demo2/login');return;}membership=null;byId('membershipStatus').textContent='暂时无法读取会员状态';byId('membershipPlans').innerHTML='<div class="empty-state">套餐信息暂不可用，请刷新状态。</div>';byId('membershipOrders').innerHTML='<div class="empty-state">订单记录暂不可用，请刷新状态。</div>';byId('schoolWorkspaceLink').hidden=true;byId('paymentStatus').textContent='尚未确认支付服务状态，当前不可下单。';showError(error.message);}finally{loadingMembership=false;updateOrderButton();}}
byId('membershipPlans').addEventListener('change',event=>{if(event.target.name==='membershipPlan'&&!creatingOrder){selectedPlan=event.target.value;updateOrderButton();}});
byId('orderButton').addEventListener('click',async()=>{if(byId('orderButton').disabled||creatingOrder)return;creatingOrder=true;clearError();updateOrderButton();try{const response=await request('/api/v1/demo2/membership/orders',{plan_id:selectedPlan});if(!response.order&&!response.order_id)throw new Error('尚未确认订单创建，请刷新订单记录后再试。');byId('paymentStatus').textContent='订单请求已受理，尚未确认支付成功。请刷新查看订单状态。';}catch(error){if(error.status===401){location.assign('/demo2/login');return;}if(error.status===503){membership.payment_available=false;byId('paymentStatus').textContent='支付暂未配置，未完成付费会员开通。';}showError(error.message);}finally{creatingOrder=false;updateOrderButton();}});
byId('refreshMembershipButton').addEventListener('click',refreshMembership);
byId('logoutButton').addEventListener('click',async()=>{try{await request('/api/v1/demo2/auth/logout',{});location.assign('/demo2/login');}catch(error){showError(error.message);}});
refreshMembership();
"""
    return _document(title="会员中心 · 课堂学习分析平台", body=_shell(content, nav='<a href="/demo2/login">返回登录</a><button class="button quiet" id="logoutButton" type="button">退出登录</button>'), page_style=ENTRY_STYLE, script=script)


def render_privacy() -> str:
    content = """<article class="policy-article"><p class="entry-kicker">账号、会员与课堂资料</p><h1>数据安全与隐私说明</h1><p class="policy-date">版本：2026-09-09</p>
<h2>课堂资料的用途</h2><p>课堂视频、音频、课程目标及学生支持资料，用于获授权的课堂分析、教师复核和学习记录。上传人应确认本次资料已按校方要求取得相应授权。登录本身不代表同意上传学生资料。</p>
<h2>保存时间与位置</h2><p>当前内测版的课堂资料保存在运行本平台的受控目录及本地数据库内，不会因填写学校或创建账号自动上传云端。新上传原始视频默认保存60天，到期前15天在平台提醒，到期按设置清理。结构化结果、报告和审计记录另行管理，不承诺永久保存。</p>
<h2>上传确认与长期归档</h2><p>点击“确认授权并上传”即对当前课程、当前文件作出上传授权确认，系统保存确认人、课程和时间。经校方另行授权后，可选择允许教师复核后的脱敏结构化结果进入公司长期资源库；默认不允许，不包含原视频和姓名，不能将此选项视为学生资料的训练授权。</p>
<h2>谁可以访问</h2><p>学校账号使用已分配的上传通道；管理员按权限查看任务、存储、会员与订单记录。新注册成员只能查看自己的会员状态与订单，不能访问既有学校的学生页面、课堂视频或档案。填写学校名称或开通会员不会自动获得其他学校的数据权限。下载和分享课堂资料仍需符合校方授权范围。</p>
<h2>分析结果如何使用</h2><p>自动分析和模型建议供教师复核。学生未回应、画面模糊或人物被遮挡时，应标为证据不足；不能仅凭姿态或表情判定学生掌握程度、疾病或教师教学质量。新视频是否已完成实际分析，以任务状态和结果来源为准。</p>
<h2 id="registration">账号注册与隐私说明</h2><p>使用中国大陆手机号（+86）、短信验证码和密码创建登录账号。手机号用于验证号码使用权、登录和必要的账号服务通知；验证码用于本次验证，密码用于身份认证。短信服务未配置时不提供短信注册，不会以申请登记代替账号创建。点击“注册并前往会员开通”表示同意本页2026-09-09版本的注册与会员服务说明。注册账号不会扣费，也不等于开通付费会员。</p><p>短信功能开放时，会通过所配置的短信服务发送验证码；该步骤不包含课堂视频或学生资料。需更正账号信息、申请导出或删除资料时，请联系项目服务人员，由管理员核对身份后处理。旧版学校开通申请仅作为历史记录保留，不再作为手机号注册流程。</p>
<h2 id="membership">会员服务说明</h2><p>付费会员按实际公布的套餐、服务金额、期限和订单记录办理。金额未配置时显示“待公布”；支付未配置时不提供付款，不生成支付二维码，也不会自动扣费或将账号标记为付费成功。创建订单不等于完成支付，会员有效状态以系统确认的实际开通结果为准。</p><p>购买前应确认具体服务范围、期限和售后安排；未公布或未配置的事项不作已上线承诺。既有教师内测权限与付费会员分开记录，不能将内测使用描述为购买成功。会员资格不替代学校授权，不能用于访问其他学校学生资料。</p>
<h2>后续云端与模型服务</h2><p>如后续使用云存储或外部模型接口，将先明确服务提供方、数据传输范围与保存规则，再由校方确认。本版本的登录或注册操作不包含学生视频向外部模型传输的授权。</p></article>"""
    return _document(title="数据安全与隐私说明 · 课堂学习分析平台", body=_shell(content, nav='<a href="/demo2/login">返回登录</a>'), page_style=ENTRY_STYLE)
