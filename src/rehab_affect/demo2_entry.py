"""Account entry and school onboarding views for the classroom platform."""

from __future__ import annotations

from typing import Any

from .demo2_portal import _WORKSPACE_STYLE, _account_payload, _document
import json

from .demo2_ui_kit import BRAND_FULL_NAME, BRAND_NAME, BRAND_TAGLINE, BRAND_VERSION, empty_state, header_for, icon


ENTRY_STYLE = _WORKSPACE_STYLE + r"""
:root { --canvas:#f6f9fd; --ink:#263746; --muted:#627386; --line:#dce5ee; --blue-deep:#244f83; --shadow:none; }
body { background:#fff; font-family:"Segoe UI","Microsoft YaHei",sans-serif; font-size:15px; letter-spacing:0; }
.entry-shell { min-height:100svh; display:flex; flex-direction:column; border-top:4px solid var(--blue); border-image:linear-gradient(90deg,#123f86 0%,#1f5fbf 55%,#4fc3f7 100%) 1; }
.entry-shell-signed { border-top:0; }
.entry-header { min-height:72px; width:min(1200px,calc(100% - 64px)); margin:0 auto; display:flex; align-items:center; justify-content:space-between; gap:20px; }
.entry-header .brand { width:auto; }
.entry-header .brand-copy strong { font-size:19px; font-weight:600; }
.entry-header .brand-copy span { font-size:11px; margin-top:3px; }
.entry-header .brand-icon { background:#edf4fe; color:var(--blue); width:44px; height:44px; }
.entry-header .brand-icon.weglow-mark { padding:8px; border-radius:8px; background:linear-gradient(135deg,#1f5fbf 0%,#123f86 100%); color:#fff; box-shadow:0 0 0 3px rgba(79,195,247,.22),0 6px 14px rgba(31,95,191,.25); }
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
.register-state { display:grid; grid-template-columns:48px minmax(0,1fr); gap:16px; margin-top:24px; padding:22px; border:1px solid #c9dbf1; border-radius:8px; background:#f4f8fe; }
.register-state-icon { width:48px; height:48px; display:grid; place-items:center; border-radius:8px; background:#fff; color:var(--blue); border:1px solid #d6e4f5; }
.register-state-icon svg { width:24px; height:24px; }
.register-state h2 { font-size:18px; color:#1f3550; }
.register-state p { margin-top:8px; color:#4c6073; font-size:15px; line-height:1.85; }
.register-state.error { border-color:#efc1bd; background:var(--danger-soft); }
.register-state.error .register-state-icon { color:var(--danger); }
.register-state.loading .register-state-actions .button.primary { opacity:.9; }
.register-state-actions { display:flex; flex-wrap:wrap; gap:10px; margin-top:16px; }
.register-state-actions .button { min-width:120px; }
#registerFormArea .entry-form { margin-top:18px; }
.plan-price.pending { font-size:19px; color:#7b4708; }
.member-orders .rx-empty { width:100%; }
@media(max-width:600px) {
  .register-state { grid-template-columns:minmax(0,1fr); padding:18px; }
  .register-state-actions .button { flex:1 1 140px; }
}
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


def _shell(content: str, *, nav: str = '<a href="/demo2/help">使用帮助</a><a href="/demo2/register">会员注册</a>', header: str = "",
           main_class: str = "") -> str:
    # Signed-in pages pass the shared kit header; public entry pages keep the
    # lightweight entry header with login/registration links.
    top = header or f"""<header class="entry-header"><a class="brand" href="/demo2/login" aria-label="{BRAND_FULL_NAME} 登录" data-brand-version="{BRAND_VERSION}">{icon("glow", css_class="brand-icon weglow-mark")}<span class="brand-copy"><strong>{BRAND_FULL_NAME}</strong><span>{BRAND_NAME} · {BRAND_TAGLINE}</span></span></a><nav aria-label="入口导航">{nav}<span class="pilot-label">学校内测</span></nav></header>"""
    return f"""<div class="entry-shell{' entry-shell-signed' if header else ''}">
{top}
<main class="entry-main{(' ' + main_class) if main_class else ''}" id="mainContent">{content}</main>
<footer class="entry-footer"><span>{BRAND_FULL_NAME} · 课堂学习与个体成长</span><a href="/demo2/privacy#membership">会员服务说明</a><a href="/demo2/privacy">数据安全与隐私说明</a></footer></div>"""


COMMON_SCRIPT = r"""
const BRAND_VERSION='__WEGLOW_BRAND_VERSION__';
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
    const response=await fetch(url,{credentials:'same-origin',signal:controller.signal,...(payload===undefined?{headers:{'X-WeGlow-Brand':BRAND_VERSION}}:{method:'POST',headers:{'Content-Type':'application/json','X-WeGlow-Brand':BRAND_VERSION},body:JSON.stringify(payload)})});
    const data=await response.json().catch(error=>{if(error.name==='AbortError'||error instanceof TypeError)throw error;return {};});
    if(!response.ok||data.error){const error=new Error(data.error?.message||({401:'登录已过期，请重新登录。',403:'当前账号无权进行此操作。',429:'操作较频繁，请稍后重试。',503:'服务暂未配置，请稍后查看。'}[response.status])||'服务暂时不可用，请稍后重试。');error.status=response.status;error.code=String(data.error?.code||'');error.retryAfter=Number(response.headers.get('Retry-After'))||0;throw error;}
    return data;
  }catch(error){if(error.name==='AbortError')throw Object.assign(new Error('请求超时，请检查网络后重试。'),{network:true});if(error instanceof TypeError)throw Object.assign(new Error('网络连接失败，请检查网络后重试。'),{network:true});throw error;}finally{clearTimeout(timer);}
}
"""
COMMON_SCRIPT = COMMON_SCRIPT.replace("__WEGLOW_BRAND_VERSION__", BRAND_VERSION)



LOGIN_STYLE = r"""
.entry-main.login-main { place-items:stretch; padding:40px 32px 48px; background:linear-gradient(180deg,#f6f9fd 0%,#fff 70%); }
.login-layout { width:min(1080px,100%); margin:auto; display:grid; grid-template-columns:minmax(0,1.05fr) minmax(0,440px); gap:56px; align-items:center; }
.login-intro { position:relative; align-self:stretch; min-width:0; min-height:560px; overflow:hidden; isolation:isolate; border-radius:8px; background:radial-gradient(120% 90% at 18% 12%,rgba(79,195,247,.42) 0%,rgba(79,195,247,0) 46%),radial-gradient(90% 80% at 88% 92%,rgba(120,200,255,.30) 0%,rgba(120,200,255,0) 52%),linear-gradient(150deg,#2a74d6 0%,#1f5fbf 38%,#174a96 70%,#123f86 100%); box-shadow:0 18px 40px rgba(18,63,134,.22); }
.login-intro::before { content:""; position:absolute; inset:-20%; z-index:-1; background:conic-gradient(from 210deg at 50% 50%,rgba(255,255,255,0) 0deg,rgba(255,255,255,.10) 40deg,rgba(255,255,255,0) 90deg,rgba(79,195,247,.14) 200deg,rgba(255,255,255,0) 260deg); animation:weglowSpin 48s linear infinite; }
.login-intro::after { content:""; position:absolute; inset:0; z-index:-1; background-image:radial-gradient(rgba(255,255,255,.16) 1px,transparent 1.4px); background-size:22px 22px; -webkit-mask-image:linear-gradient(180deg,rgba(0,0,0,.65),rgba(0,0,0,0) 78%); mask-image:linear-gradient(180deg,rgba(0,0,0,.65),rgba(0,0,0,0) 78%); }
.login-art { position:absolute; inset:0; width:100%; height:100%; display:block; }
.login-art .glow-wave { fill:none; stroke:#fff; stroke-linecap:round; }
.login-art .glow-ring { fill:none; stroke:#bfe9ff; }
.login-art .spark { fill:#fff; animation:weglowTwinkle 4.8s ease-in-out infinite; transform-box:fill-box; transform-origin:center; }
.login-art .spark.s2 { animation-delay:1.2s; fill:#d5f2ff; }
.login-art .spark.s3 { animation-delay:2.4s; fill:#4fc3f7; }
.login-art .spark.s4 { animation-delay:3.6s; }
.login-art .orbit { animation:weglowFloat 9s ease-in-out infinite; transform-box:fill-box; transform-origin:center; }
.login-brand { position:absolute; left:50%; top:50%; transform:translate(-50%,-50%); display:flex; flex-direction:column; align-items:center; gap:18px; pointer-events:none; }
.login-brand-mark { position:relative; width:112px; height:112px; display:grid; place-items:center; border-radius:50%; background:radial-gradient(circle at 50% 45%,rgba(255,255,255,.98) 0%,rgba(214,242,255,.9) 34%,rgba(79,195,247,.42) 62%,rgba(79,195,247,0) 72%); box-shadow:0 0 60px 18px rgba(79,195,247,.35),0 0 140px 40px rgba(31,95,191,.35); animation:weglowPulse 5.6s ease-in-out infinite; }
.login-brand-mark svg { width:56px; height:56px; color:#1f5fbf; }
.login-brand-word { color:#fff; font:700 30px/1.1 "Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; letter-spacing:3px; text-shadow:0 0 18px rgba(79,195,247,.75),0 2px 6px rgba(18,63,134,.45); }
@keyframes weglowSpin { to { transform:rotate(360deg); } }
@keyframes weglowTwinkle { 0%,100% { opacity:.25; transform:scale(.7); } 50% { opacity:1; transform:scale(1.15); } }
@keyframes weglowFloat { 0%,100% { transform:translateY(0); } 50% { transform:translateY(-10px); } }
@keyframes weglowPulse { 0%,100% { box-shadow:0 0 60px 18px rgba(79,195,247,.32),0 0 140px 40px rgba(31,95,191,.32); } 50% { box-shadow:0 0 78px 26px rgba(79,195,247,.48),0 0 170px 54px rgba(31,95,191,.40); } }
.login-card { width:100%; padding:34px 34px 26px; border:1px solid #dce5ee; border-radius:8px; background:#fff; box-shadow:0 16px 38px rgba(29,75,122,.10); }
.login-card .entry-form-area { width:100%; }
.login-card .role-switch { margin:22px 0 18px; }
.login-card .form-error { margin:0 0 16px; border-radius:6px; }
.login-card .form-error.visible { display:flex; gap:8px; align-items:flex-start; }
.login-card .entry-form { gap:18px; }
.login-card .field small { line-height:1.7; }
.caps-hint { color:var(--warning) !important; font-weight:600; }
.button.primary.is-loading { cursor:progress; opacity:.92; }
.btn-spinner { width:18px; height:18px; border:2px solid rgba(255,255,255,.45); border-top-color:#fff; border-radius:50%; animation:loginSpin .8s linear infinite; }
@keyframes loginSpin { to { transform:rotate(360deg); } }
@media (max-width:1023px) {
  .login-layout { grid-template-columns:minmax(0,440px); justify-content:center; gap:0; }
  .login-intro { display:none; }
  .login-card { background:linear-gradient(90deg,#123f86 0%,#1f5fbf 55%,#4fc3f7 100%) top / 100% 3px no-repeat,#fff; }
}
@media (max-width:600px) {
  .entry-main.login-main { padding:20px 14px 32px; }
  .login-card { padding:24px 18px 20px; box-shadow:none; }
}
@media (prefers-reduced-motion:reduce) { .btn-spinner,.login-intro::before,.login-art .spark,.login-art .orbit,.login-brand-mark { animation:none; } }
"""

# Decorative particles for the login art: (cx, cy, r, variant). Fixed values
# keep the page byte-stable for caching and tests.
_LOGIN_SPARKS = (
    (72, 96, 2.6, 1), (148, 58, 1.6, 2), (236, 132, 2.2, 3), (402, 70, 1.8, 4), (468, 150, 2.8, 1),
    (520, 44, 1.4, 2), (96, 236, 1.8, 3), (54, 372, 2.4, 4), (138, 452, 1.6, 1), (212, 512, 2.6, 2),
    (338, 486, 1.8, 3), (446, 520, 2.2, 4), (522, 404, 1.6, 1), (548, 268, 2.4, 2), (486, 330, 1.4, 3),
    (300, 40, 2.0, 4), (30, 168, 1.4, 2), (262, 300, 1.2, 1), (396, 228, 1.4, 4), (176, 352, 1.2, 3),
)


def _login_art() -> str:
    sparks = "".join(
        f'<circle class="spark s{variant}" cx="{cx}" cy="{cy}" r="{r}"/>'
        for cx, cy, r, variant in _LOGIN_SPARKS
    )
    return (
        '<svg class="login-art" viewBox="0 0 580 560" preserveAspectRatio="xMidYMid slice" aria-hidden="true" focusable="false">'
        '<defs><radialGradient id="weglowHalo" cx="50%" cy="50%" r="50%">'
        '<stop offset="0%" stop-color="#bfe9ff" stop-opacity=".55"/><stop offset="55%" stop-color="#4fc3f7" stop-opacity=".16"/>'
        '<stop offset="100%" stop-color="#4fc3f7" stop-opacity="0"/></radialGradient>'
        '<linearGradient id="weglowBeam" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#ffffff" stop-opacity=".0"/>'
        '<stop offset="50%" stop-color="#ffffff" stop-opacity=".22"/><stop offset="100%" stop-color="#ffffff" stop-opacity="0"/></linearGradient></defs>'
        '<circle cx="290" cy="280" r="230" fill="url(#weglowHalo)"/>'
        '<g class="orbit"><circle class="glow-ring" cx="290" cy="280" r="120" stroke-opacity=".38" stroke-width="1.2"/>'
        '<circle class="glow-ring" cx="290" cy="280" r="168" stroke-opacity=".24" stroke-width="1" stroke-dasharray="2 7"/>'
        '<circle class="glow-ring" cx="290" cy="280" r="222" stroke-opacity=".14" stroke-width="1"/>'
        '<circle cx="410" cy="280" r="4" fill="#4fc3f7"/><circle cx="172" cy="196" r="3" fill="#fff" fill-opacity=".85"/></g>'
        '<path d="M-20 70 L260 -20 L600 120 L600 160 L250 30 L-20 120Z" fill="url(#weglowBeam)"/>'
        '<path class="glow-wave" d="M-10 430 C 90 388 170 470 280 432 S 470 380 600 424" stroke-opacity=".30" stroke-width="2"/>'
        '<path class="glow-wave" d="M-10 466 C 110 424 190 506 300 470 S 480 420 600 462" stroke-opacity=".20" stroke-width="1.6"/>'
        '<path class="glow-wave" d="M-10 504 C 120 468 210 540 320 508 S 490 462 600 500" stroke-opacity=".12" stroke-width="1.4"/>'
        '<path class="glow-wave" d="M-10 120 C 100 150 180 92 300 126 S 480 168 600 132" stroke-opacity=".10" stroke-width="1.2"/>'
        f'{sparks}</svg>'
    )


def render_login() -> str:
    # The left panel is purely visual (user request 2026-10-31): no headings,
    # steps or disclaimers, only brand art and the WeGlow wordmark.
    content = f"""<div class="login-layout" data-brand-version="{BRAND_VERSION}">
<aside class="login-intro" role="img" aria-label="{BRAND_NAME}">{_login_art()}<div class="login-brand" aria-hidden="true"><span class="login-brand-mark">{icon("glow", css_class="login-glow-icon")}</span><span class="login-brand-word">{BRAND_NAME}</span></div></aside>
<div class="login-card"><section class="entry-form-area" aria-labelledby="loginTitle">
<p class="entry-kicker">欢迎使用 {BRAND_FULL_NAME}</p><h1 id="loginTitle">登录课堂工作台</h1><p class="entry-subtitle" id="roleDescription">学校老师与注册用户在此登录课堂工作台。</p>
<div class="role-switch" role="radiogroup" aria-label="登录身份"><button type="button" role="radio" aria-checked="true" data-role="school_uploader" id="userRole">用户登录</button><button type="button" role="radio" aria-checked="false" data-role="company_admin" id="adminRole" tabindex="-1">管理员登录</button></div>
<div class="form-error" id="formError" role="alert" aria-live="assertive"></div>
<form id="loginForm" class="entry-form" novalidate>
<div class="field"><label for="username">账号</label><input id="username" name="username" autocomplete="username" maxlength="80" required placeholder="内测账号或手机号，例如 t1" aria-describedby="usernameHelp usernameError" /><small id="usernameHelp">学校老师使用学校分配的内测账号（如 t1）；已注册手机号的用户直接输入手机号。</small><small class="field-error" id="usernameError" role="status"></small></div>
<div class="field"><label for="password">密码</label><div class="password-field"><input id="password" name="password" type="password" autocomplete="current-password" maxlength="256" required placeholder="输入登录密码" aria-describedby="capsHint passwordError" /><button type="button" class="reveal-password" id="showPassword" aria-label="显示密码" title="显示密码" aria-pressed="false">{EYE_ICON}</button></div><small class="caps-hint" id="capsHint" role="status" hidden>大写锁定已开启，密码区分大小写。</small><small class="field-error" id="passwordError" role="status"></small></div>
<button class="button primary" id="loginButton" type="submit"><span id="loginButtonLabel">登录</span></button></form>
<p class="entry-links" id="registerLinks"><span>还没有账号？</span><a href="/demo2/register">手机号注册</a></p>
<p class="entry-terms">请阅读<a href="/demo2/privacy">数据安全与隐私说明</a>。注册账号与付费会员开通分别办理；登录本身不代表同意上传学生资料。</p>
</section></div></div>"""
    script = COMMON_SCRIPT + r"""
let selectedRole='school_uploader';
let loginPending=false,loginLeaving=false;
const roleButtons=[...document.querySelectorAll('[data-role]')];
const ROLE_TEXT={
  school_uploader:{placeholder:'内测账号或手机号，例如 t1',help:'学校老师使用学校分配的内测账号（如 t1）；已注册手机号的用户直接输入手机号。',description:'学校老师与注册用户在此登录课堂工作台。'},
  company_admin:{placeholder:'输入管理员账号，例如 admin',help:'仅限公司授权的管理员账号；选择此入口不会获得额外权限，身份由服务端核验。',description:'使用公司授权的管理员账号查看后台。'}
};
function selectRole(button) {
  if(loginPending)return;
  selectedRole=button.dataset.role;
  roleButtons.forEach(item=>{const active=item===button;item.setAttribute('aria-checked',String(active));item.tabIndex=active?0:-1;});
  const text=ROLE_TEXT[selectedRole];
  byId('username').placeholder=text.placeholder;
  byId('usernameHelp').textContent=text.help;
  byId('roleDescription').textContent=text.description;
  byId('registerLinks').hidden=selectedRole==='company_admin';
  clearError();
}
function loginErrorMessage(error){
  if(error.network)return '网络异常，请检查网络连接后重试。';
  if(error.code==='account_disabled')return '账号已停用，请联系项目服务人员恢复后再登录。';
  if(error.code==='role_mismatch')return selectedRole==='company_admin'?'该账号不是管理员账号，请切换到「用户登录」后再试。':'管理员账号请切换到「管理员登录」后再试。';
  if(error.status===401||error.code==='invalid_credentials')return '账号或密码不正确，请检查后重新输入。';
  if(error.status===429)return error.message||'登录尝试过于频繁，请稍后再试。';
  if(error.status===400)return '请填写账号和密码后再登录。';
  return '登录服务暂时不可用，请稍后重试。';
}
function setLoading(on){
  const button=byId('loginButton');
  button.disabled=on;button.classList.toggle('is-loading',on);button.setAttribute('aria-busy',String(on));
  button.innerHTML=on?'<span class="btn-spinner" aria-hidden="true"></span><span id="loginButtonLabel">正在登录…</span>':'<span id="loginButtonLabel">登录</span>';
  roleButtons.forEach(item=>item.disabled=on);
}
roleButtons.forEach(button=>{button.addEventListener('click',()=>selectRole(button));button.addEventListener('keydown',event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const next=event.key==='Home'?roleButtons[0]:event.key==='End'?roleButtons[1]:roleButtons.find(item=>item!==button);selectRole(next);next.focus();}});});
bindPassword('password','showPassword');
function loginFieldError(id,text){byId(id+'Error').textContent=text;if(text)byId(id).setAttribute('aria-invalid','true');else byId(id).removeAttribute('aria-invalid');}
['username','password'].forEach(id=>byId(id).addEventListener('input',()=>{loginFieldError(id,'');if(byId('formError').classList.contains('visible'))clearError();}));
byId('password').addEventListener('keyup',event=>{if(typeof event.getModifierState==='function')byId('capsHint').hidden=!event.getModifierState('CapsLock');});
byId('password').addEventListener('blur',()=>{byId('capsHint').hidden=true;});
try {const notice=sessionStorage.getItem('demo2_notice');if(notice){showError(notice);sessionStorage.removeItem('demo2_notice');}} catch(_) {}
byId('loginForm').addEventListener('submit',async event=>{
  event.preventDefault();if(loginPending||loginLeaving)return;clearError();
  const username=byId('username').value.trim(),password=byId('password').value;
  loginFieldError('username','');loginFieldError('password','');
  if(!username){showError('请输入账号。');loginFieldError('username','账号为必填项，请输入账号。');byId('username').focus();return;}
  if(!password){showError('请输入密码。');loginFieldError('password','密码为必填项，请输入密码。');byId('password').focus();return;}
  loginPending=true;setLoading(true);
  try {const data=await request('/api/v1/demo2/auth/login',{username,password,role:selectedRole});const role=data.account?.role;if(!['school_uploader','registered_member','company_admin'].includes(role))throw new Error('登录响应缺少账号身份，请重新登录。');const fallback=role==='registered_member'?'/demo2/membership':role==='company_admin'?'/demo2/admin':'/demo2/school';loginLeaving=true;byId('loginButtonLabel').textContent='登录成功，正在进入…';location.assign(safeNextUrl(data.next_url,fallback,role));}
  catch(error){showError(error.status||error.network?loginErrorMessage(error):error.message);const field=byId('password');field.setAttribute('aria-invalid','true');field.focus();field.select?.();}
  finally{loginPending=false;if(!loginLeaving)setLoading(false);}
});
window.addEventListener('pageshow',event=>{if(event.persisted){loginLeaving=false;loginPending=false;setLoading(false);}});
"""
    return _document(title="登录", body=_shell(content, main_class="login-main"), page_style=ENTRY_STYLE + LOGIN_STYLE, script=script)


def render_school(account: Any | None = None) -> str:
    """Same page as /demo2/school: national directory search, public-source list and manual entry.

    Kept as an entry-module name for older imports; both entry points must
    render identically, so this delegates instead of keeping a second form.
    """
    from .school_selection_page import render_school_selection_html

    return render_school_selection_html(account)


def render_register() -> str:
    content = """<div class="registration-layout"><section class="entry-form-area" aria-labelledby="registerTitle">
<p class="entry-kicker">WeGlow微光系统 · 账号与会员</p><h1 id="registerTitle">注册 WeGlow微光系统 账号</h1><p class="entry-subtitle">使用中国大陆手机号注册：验证手机号并设置登录密码，随后查看会员服务与开通状态。</p>
<section class="register-state loading" id="registerState" aria-labelledby="registerStateTitle"><span class="register-state-icon" aria-hidden="true">__SHIELD__</span><div class="register-state-copy"><h2 id="registerStateTitle" role="status">正在检查注册服务…</h2><p id="registerStateText">稍等片刻，正在确认手机号注册是否已开放。</p><div class="register-state-actions"><a class="button primary" id="backToLoginButton" href="/demo2/login">返回登录</a><button class="button" id="reloadConfigButton" type="button">重新检查服务状态</button></div></div></section>
<div id="registerFormArea" hidden><div class="entry-status" id="smsNotice">__SHIELD__<p id="smsStatus" role="status">短信注册已开放。完成验证后创建账号，会员需另行开通。</p></div>
<form id="registerForm" class="entry-form" novalidate>
<div class="field"><label for="phone">中国大陆手机号</label><div class="phone-field"><span class="phone-prefix" aria-hidden="true">+86</span><input id="phone" name="phone" type="tel" inputmode="numeric" autocomplete="tel-national" maxlength="11" placeholder="11 位手机号" aria-describedby="phoneHelp phoneError" required /></div><small id="phoneHelp">用于短信验证与后续登录，仅支持 +86 中国大陆号码。</small><small class="field-error" id="phoneError" role="status"></small></div>
<div class="field"><label for="code">短信验证码</label><div class="code-field"><input id="code" name="code" inputmode="numeric" autocomplete="one-time-code" maxlength="6" placeholder="6 位验证码" aria-describedby="codeError" required /><button class="button" id="sendCodeButton" type="button" disabled>获取验证码</button></div><small class="field-error" id="codeError" role="status"></small><small id="codeStatus" role="status"></small></div>
<div class="field"><label for="password">设置密码</label><div class="password-field"><input id="password" name="password" type="password" autocomplete="new-password" minlength="8" maxlength="72" aria-describedby="passwordHelp passwordError" placeholder="8–72 位字母与数字" required /><button type="button" class="reveal-password" id="showPassword" aria-label="显示密码" title="显示密码" aria-pressed="false">__EYE__</button></div><small id="passwordHelp">8–72 位，仅限英文字母和数字，且两者都需包含。</small><small class="field-error" id="passwordError" role="status"></small></div>
<div class="field"><label for="confirmPassword">确认密码</label><div class="password-field"><input id="confirmPassword" name="confirm_password" type="password" autocomplete="new-password" maxlength="72" aria-describedby="confirmPasswordError" placeholder="再次输入密码" required /><button type="button" class="reveal-password" id="showConfirmPassword" aria-label="显示确认密码" title="显示确认密码" aria-pressed="false">__EYE__</button></div><small class="field-error" id="confirmPasswordError" role="status"></small></div>
<div class="form-error" id="formError" role="alert" tabindex="-1"></div>
<p class="entry-terms" style="margin:0">点击注册即表示同意<a href="/demo2/privacy#registration" target="_blank" rel="noopener">账号注册与隐私说明</a>及<a href="/demo2/privacy#membership" target="_blank" rel="noopener">会员服务说明</a>（2026-09-09）。注册不会扣费，也不会自动开通会员。</p>
<button class="button primary" id="registerButton" type="submit" disabled>注册并前往会员开通</button></form></div>
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
const REGISTER_STATES={
  loading:['正在检查注册服务…','稍等片刻，正在确认手机号注册是否已开放。'],
  unavailable:['手机号注册即将开放','学校老师请使用学校分配的内测账号登录；需要新账号时，请联系学校管理员或项目服务人员。'],
  outdated:['注册协议已更新','注册说明有新版本，请刷新页面阅读最新说明后再注册。'],
  error:['暂时无法确认注册服务状态','请检查网络后点击「重新检查服务状态」；学校老师可先返回登录使用内测账号。']
};
function renderRegisterState(mode,detail){
  const card=byId('registerState'),available=mode==='available';
  card.hidden=available;byId('registerFormArea').hidden=!available;
  if(available)return;
  const [title,text]=REGISTER_STATES[mode]||REGISTER_STATES.error;
  card.className='register-state '+mode;byId('registerStateTitle').textContent=title;byId('registerStateText').textContent=detail?text+' （'+detail+'）':text;
}
async function loadConfig(){if(configBusy||sending||registering)return;configBusy=true;smsAvailable=false;syncControls();renderRegisterState('loading');try{const response=await request('/api/v1/demo2/membership/config');const config=response.config||response;const outdated=Boolean(config.agreement_version)&&config.agreement_version!==AGREEMENT_VERSION;smsAvailable=config.sms_available===true&&!outdated;renderRegisterState(smsAvailable?'available':outdated?'outdated':'unavailable');}catch(error){renderRegisterState('error',error.message);}finally{configBusy=false;syncControls();}}
bindPassword('password','showPassword');bindPassword('confirmPassword','showConfirmPassword');
['phone','code','password','confirmPassword'].forEach(id=>byId(id).addEventListener('blur',()=>validate(id)));
byId('phone').addEventListener('input',()=>{byId('code').value='';byId('codeStatus').textContent='';fieldError('phone','');fieldError('code','');});
byId('sendCodeButton').addEventListener('click',async()=>{if(!smsAvailable||sending||registering||Date.now()<cooldownUntil)return;if(!validate('phone')){byId('phone').focus();return;}sending=true;clearError();syncControls();byId('codeStatus').textContent='';try{const response=await request('/api/v1/demo2/auth/sms-code',{phone:byId('phone').value.trim()});const data=response.result||response;if(data.sent===false||data.sms_available===false)throw new Error('短信服务暂不可用，验证码未发送。');startCooldown(Number(data.retry_after)||60);byId('codeStatus').textContent='验证码请求已受理，请查看手机短信。';byId('code').focus();}catch(error){if(error.status===503){smsAvailable=false;renderRegisterState('unavailable');}if(error.status===429)startCooldown(error.retryAfter||60);showError(error.message);}finally{sending=false;syncControls();}});
byId('registerForm').addEventListener('submit',async event=>{event.preventDefault();if(registering||sending)return;if(!smsAvailable){showError('暂未开通短信注册，请先检查服务状态。');return;}const invalid=['phone','code','password','confirmPassword'].filter(id=>!validate(id));if(invalid.length){byId(invalid[0]).focus();return;}registering=true;clearError();syncControls();byId('registerButton').textContent='正在创建账号';try{const data=await request('/api/v1/demo2/auth/register',{phone:byId('phone').value.trim(),code:byId('code').value.trim(),password:byId('password').value,accepted:true,agreement_version:AGREEMENT_VERSION});if(!data.account)throw new Error('注册响应尚未确认账号创建，请检查后再登录。');byId('password').value='';byId('confirmPassword').value='';byId('code').value='';location.assign(safeNextUrl(data.next_url,'/demo2/membership','registered_member'));}catch(error){if(error.status===503){smsAvailable=false;renderRegisterState('unavailable');}showError(error.message);}finally{registering=false;byId('registerButton').textContent='注册并前往会员开通';syncControls();}});
byId('reloadConfigButton').addEventListener('click',()=>{clearError();loadConfig();});
window.addEventListener('pagehide',()=>{leaving=true;clearTimeout(cooldownTimer);});window.addEventListener('pageshow',event=>{if(event.persisted){leaving=false;tickCooldown();}});
loadConfig();
"""
    return _document(title="会员注册", body=_shell(content, nav='<a href="/demo2/login">返回登录</a>'), page_style=ENTRY_STYLE, script=script)


def render_membership(account: Any | None = None) -> str:
    content = """<section class="member-area" id="membershipCenter" aria-labelledby="membershipTitle">
<div class="member-heading"><div><p class="entry-kicker">账号与会员</p><h1 id="membershipTitle">会员中心</h1><p class="entry-subtitle">查看会员状态、服务套餐与订单。注册账号后，会员服务需另行开通。</p></div><button class="button" id="refreshMembershipButton" type="button">刷新状态</button></div>
<div class="form-error" id="formError" role="alert" tabindex="-1"></div>
<section class="member-status-card" aria-labelledby="membershipStatus"><div><h2 id="membershipStatus" role="status">正在读取会员状态</h2><dl class="member-facts"><div><dt>绑定手机号</dt><dd id="memberPhone">—</dd></div><div><dt>有效期至</dt><dd id="membershipExpiry">—</dd></div></dl></div><a class="button" id="schoolWorkspaceLink" href="/demo2/school" hidden>进入学校工作台</a></section>
<div class="entry-status unavailable">__SHIELD__<p id="schoolAccessStatus">会员状态与学校数据权限分别核验。正在读取账号权限…</p></div>
<section class="member-section" aria-labelledby="plansTitle"><h2 id="plansTitle">会员服务套餐</h2><p>服务内容与金额以实际公布的套餐为准。创建订单或完成注册均不代表支付成功。</p><div class="plan-grid" id="membershipPlans" role="radiogroup" aria-labelledby="plansTitle"><div class="empty-state">正在读取套餐信息…</div></div><div class="membership-command"><button class="button primary" id="orderButton" type="button" disabled>支付暂未开通</button><p id="paymentStatus" role="status">正在核对支付服务，当前不可支付。</p></div><p class="entry-terms">下单前请阅读<a href="/demo2/privacy#membership">会员服务说明</a>。支付开通、有效期和订单结果以系统确认的信息为准。</p></section>
<section class="member-section" aria-labelledby="ordersTitle"><h2 id="ordersTitle">订单记录</h2><p>仅显示当前账号的真实订单；未支付订单不会开通会员。</p><div class="member-orders" id="membershipOrders"><div class="empty-state">正在读取订单记录…</div></div></section>
</section>""".replace("__SHIELD__", SHIELD_ICON)
    orders_empty = json.dumps(empty_state("暂无订单。完成注册不会自动创建付费订单，开通会员后订单会显示在这里。"), ensure_ascii=False).replace("<", "\\u003c")
    script = COMMON_SCRIPT + f"\nconst MEMBER_ACCOUNT={_account_payload(account)};\n" + r"""
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
let membership=null,selectedPlan='',loadingMembership=false,creatingOrder=false;
const hasPrice=cents=>typeof cents==='number'&&Number.isFinite(cents)&&Number.isInteger(cents)&&cents>=0;
const money=cents=>hasPrice(cents)?`¥${(cents/100).toFixed(2)}`:'价格即将公布';
const ORDERS_EMPTY=__ORDERS_EMPTY__;
const dateText=value=>{if(!value)return '尚无有效期';const date=new Date(value);if(Number.isNaN(date.getTime()))return '时间待确认';return window.RxUI?RxUI.formatDate(value):date.toLocaleDateString('zh-CN');};
const maskedPhone=value=>{const phone=String(value||'');if(!phone)return '未绑定手机号';return /\d{7,}/.test(phone)?phone.replace(/(\d{3})\d{4}(\d{4})/g,'$1****$2'):phone;};
const orderStatus=value=>({pending:'待支付',pending_payment:'待支付',unpaid:'待支付',paid:'已支付',completed:'已完成',cancelled:'已取消',expired:'已关闭',closed:'已关闭',failed:'支付未完成',refunded:'已退款'}[value]||'状态待确认');
function plans(){return Array.isArray(membership?.plans)?membership.plans:[];}
function updateOrderButton(){const plan=plans().find(item=>item.plan_id===selectedPlan);const configured=membership?.payment_available===true;const canOrder=MEMBER_ACCOUNT.role==='registered_member';byId('orderButton').disabled=loadingMembership||creatingOrder||!canOrder||!configured||!plan||plan.available===false||!hasPrice(plan.price_cents);byId('orderButton').textContent=creatingOrder?'正在创建订单':!configured?'支付暂未开通':!canOrder?'内测账号不办理付费订单':'创建会员订单';byId('refreshMembershipButton').disabled=loadingMembership||creatingOrder;}
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
  byId('membershipPlans').innerHTML=plans().length?plans().map(plan=>`<label class="plan-option"><input type="radio" name="membershipPlan" value="${esc(plan.plan_id||'')}" ${plan.plan_id===selectedPlan?'checked':''} ${!plan.plan_id||plan.available===false?'disabled':''}/><span class="plan-body"><strong>${esc(plan.name||plan.plan_name||'服务套餐')}</strong><small>${esc(plan.description||'服务内容待公布')}</small><span class="plan-price${hasPrice(plan.price_cents)?'':' pending'}">${esc(money(plan.price_cents))}</span><small>${esc(plan.period_label||plan.duration_label||(Number.isInteger(plan.duration_days)&&plan.duration_days>0?`${plan.duration_days} 天`:'服务期限以套餐公布信息为准'))}</small>${plan.available===false?'<small>暂未开放购买</small>':''}</span></label>`).join(''):'<div class="empty-state">会员套餐与服务金额即将公布，届时会在这里展示。当前没有可购买的套餐。</div>';
  const orders=Array.isArray(data.orders)?data.orders:[];
  byId('membershipOrders').innerHTML=orders.length?orders.map(order=>`<article class="member-order"><div><strong>${esc(order.plan_name||order.name||'会员服务订单')}</strong><small>订单号 ${esc(order.order_id||'未返回')}</small><small>${esc(dateText(order.created_at))}</small></div><div class="order-meta"><strong>${esc(money(order.amount_cents??order.price_cents))}</strong><span class="status-badge">${esc(order.status_label||orderStatus(order.status))}</span></div></article>`).join(''):ORDERS_EMPTY;
  byId('paymentStatus').textContent=data.payment_available===true?'选择已公布金额的套餐后可创建订单；会员是否开通以实际支付确认结果为准。':'支付暂未开通：目前不能在线付款，也不会产生任何扣费。价格公布并开通支付后，可在这里选择套餐下单；如需了解会员服务，请联系项目服务人员。';
  updateOrderButton();
}
async function refreshMembership(){if(loadingMembership||creatingOrder)return;loadingMembership=true;clearError();updateOrderButton();try{const response=await request('/api/v1/demo2/membership');renderMembership(response.membership||response);}catch(error){if(error.status===401){location.assign('/demo2/login');return;}membership=null;byId('membershipStatus').textContent='暂时无法读取会员状态';byId('membershipPlans').innerHTML='<div class="empty-state">套餐信息暂不可用，请刷新状态。</div>';byId('membershipOrders').innerHTML='<div class="empty-state">订单记录暂不可用，请刷新状态。</div>';byId('schoolWorkspaceLink').hidden=true;byId('paymentStatus').textContent='尚未确认支付服务状态，当前不可下单。';showError(error.message);}finally{loadingMembership=false;updateOrderButton();}}
byId('membershipPlans').addEventListener('change',event=>{if(event.target.name==='membershipPlan'&&!creatingOrder){selectedPlan=event.target.value;updateOrderButton();}});
byId('orderButton').addEventListener('click',async()=>{if(byId('orderButton').disabled||creatingOrder)return;creatingOrder=true;clearError();updateOrderButton();try{const response=await request('/api/v1/demo2/membership/orders',{plan_id:selectedPlan});if(!response.order&&!response.order_id)throw new Error('尚未确认订单创建，请刷新订单记录后再试。');byId('paymentStatus').textContent='订单请求已受理，尚未确认支付成功。请刷新查看订单状态。';}catch(error){if(error.status===401){location.assign('/demo2/login');return;}if(error.status===503){membership.payment_available=false;byId('paymentStatus').textContent='支付暂未开通，本次未扣费，也未开通付费会员。';}showError(error.message);}finally{creatingOrder=false;updateOrderButton();}});
byId('refreshMembershipButton').addEventListener('click',refreshMembership);
byId('logoutButton').addEventListener('click',async()=>{try{await request('/api/v1/demo2/auth/logout',{});location.assign('/demo2/login');}catch(error){showError(error.message);}});
refreshMembership();
""".replace("__ORDERS_EMPTY__", orders_empty)
    return _document(title="会员中心", body=_shell(content, header=header_for(account, "membership", admin_active="membership", page="membership")), page_style=ENTRY_STYLE, script=script)


PRIVACY_STYLE = r"""
html { scroll-behavior:smooth; }
.entry-main.privacy-main { place-items:stretch; padding:36px 28px 56px; background:#f6f9fd; }
.policy-layout { width:min(1060px,100%); margin:0 auto; display:grid; grid-template-columns:220px minmax(0,1fr); gap:36px; align-items:start; }
.policy-toc { position:sticky; top:24px; padding:18px 14px; border:1px solid var(--line); border-radius:8px; background:#fff; }
.policy-toc-title { margin:0 0 10px 10px; color:var(--muted); font-size:12px; font-weight:700; }
.policy-toc ol { list-style:none; margin:0; padding:0; display:grid; gap:2px; }
.policy-toc a { display:flex; align-items:center; min-height:40px; padding:6px 10px; border-left:3px solid transparent; border-radius:0 6px 6px 0; color:#3d5269; font-size:14px; text-decoration:none; }
.policy-toc a:hover { background:#f1f6fd; color:var(--blue); }
.policy-toc a[aria-current="true"] { border-left-color:var(--blue); background:#eaf2fc; color:var(--blue); font-weight:700; }
.policy-toc-mobile { display:none; }
.policy-article { width:100%; min-width:0; }
.policy-article .policy-hero { padding:4px 0 6px; }
.policy-article h1 { font-size:30px; }
.policy-keyfacts { list-style:none; display:flex; flex-wrap:wrap; gap:10px; margin:18px 0 0; padding:0; }
.policy-keyfacts li { display:flex; align-items:center; gap:8px; min-height:40px; padding:8px 14px; border:1px solid #bcd3ee; border-radius:8px; background:#fff; color:#2f4a69; font-size:14px; }
.policy-keyfacts strong { color:var(--blue); font-size:17px; }
.policy-card { scroll-margin-top:24px; margin-top:18px; padding:24px 28px; border:1px solid var(--line); border-radius:8px; background:#fff; }
.policy-card:target { border-color:var(--blue); box-shadow:0 0 0 3px rgba(31,99,198,.12); }
.policy-card h2 { display:flex; align-items:center; gap:10px; margin:0 0 6px; font-size:19px; color:#1f3550; }
.policy-card h2 .policy-no { display:inline-grid; place-items:center; width:28px; height:28px; border-radius:6px; background:#eaf2fc; color:var(--blue); font-size:13px; }
.policy-card h2:focus { outline:none; }
.policy-card p { max-width:40em; margin-top:10px; color:#3f5367; font-size:16px; line-height:1.95; }
.term-tag { display:inline-block; margin:0 3px; padding:0 8px; border-radius:4px; background:#fff3dc; color:#7b4708; font-weight:700; line-height:1.8; }
.term-tag.blue { background:#e6f0fd; color:#164d99; }
@media (max-width:900px) {
  .entry-main.privacy-main { padding:16px 14px 40px; }
  .policy-layout { grid-template-columns:minmax(0,1fr); gap:12px; }
  .policy-toc { display:none; }
  .policy-toc-mobile { display:block; position:sticky; top:0; z-index:5; padding:10px 0; background:#f6f9fd; }
  .policy-toc-mobile label { display:block; margin-bottom:6px; color:var(--muted); font-size:13px; font-weight:700; }
  .policy-card { padding:18px; scroll-margin-top:96px; }
  .policy-article h1 { font-size:25px; }
}
"""

PRIVACY_VERSION = "2026-11-01"

POLICY_SECTIONS: tuple[tuple[str, str, str], ...] = (
    ("purpose", "课堂资料的用途", '<p>课堂视频、音频、课程目标及学生支持资料，用于获授权的课堂分析、教师复核和学习记录。上传人应确认本次资料已按校方要求取得相应授权。登录本身不代表同意上传学生资料。</p>'),
    ("retention", "保存时间与位置", '<p>当前内测版的课堂资料保存在运行本平台的受控目录及本地数据库内，不会因填写学校或创建账号自动上传云端。新上传原始视频默认保存<span class="term-tag">60天</span>，到期前<span class="term-tag">15天</span>在平台提醒，到期按设置清理。结构化结果、报告和审计记录另行管理，不承诺永久保存。</p><p>其中，教师保存的结构化测量记录默认保留<span class="term-tag blue">730天</span>（不含原始视频）；媒体、敏感档案和结构化测量不是同一类数据，不能笼统按60天全部删除。</p>'),
    ("upload-consent", "上传确认与长期归档", '<p>点击“确认授权并上传”即对当前课程、当前文件作出上传授权确认，系统保存确认人、课程和时间。经校方另行授权后，可选择允许教师复核后的脱敏结构化结果进入公司长期资源库；<span class="term-tag blue">默认不允许</span>，不包含原视频和姓名，不能将此选项视为学生资料的训练授权。</p>'),
    ("access", "谁可以访问", '<p>学校账号使用已分配的上传通道；管理员按权限查看任务、存储、会员与订单记录。新注册成员只能查看自己的会员状态与订单，不能访问既有学校的学生页面、课堂视频或档案。填写学校名称或开通会员不会自动获得其他学校的数据权限。下载和分享课堂资料仍需符合校方授权范围。</p>'),
    ("documents", "课程任务文件与 IEP 文件", '<p><strong>用途：</strong>教师上传的课程任务（教案）Word/PDF 仅用于识别本课课程任务目标，并在教师确认后用于本课的课堂评价、学生测量、片段复核和课堂报告；IEP 文件仅用于生成「最小 IEP 支持摘要」，在授权范围内用于本课 IEP 关联、测量与报告。上传前须已取得校方及监护人相应授权，IEP 须先登记有效的资料授权。</p>'
     '<p><strong>加密存储：</strong>两类文件的原件和识别结果均<span class="term-tag blue">加密保存</span>，只有上传账号可以读取；公司管理员查看或下载报告时不包含 IEP 关联细节。摘要中不收录学生姓名、出生日期、诊断原文、证件号和联系方式等身份信息。</p>'
     '<p><strong>保存期限：</strong>未确认的识别结果暂存<span class="term-tag">24小时</span>后自动清除；IEP 原件与摘要保存至教师填写的「资料保存至」日期，且不晚于授权截止日（授权最长<span class="term-tag">60天</span>），授权撤回、到期或资料删除后立即停止使用，引用它的报告标为过期；课程任务每次确认生成新版本，旧版本随本课评价与报告一同保留，需要删除时请联系项目服务人员。</p>'
     '<p><strong>自动摘要仅供教师确认：</strong>系统识别出的课程目标和 IEP 摘要只是建议，<span class="term-tag blue">必须由教师逐条核对并确认</span>后才保存；未确认的内容不会进入评分或报告。扫描件无法识别时由教师人工补充。自动摘要不构成专业评估或 IEP 决策。</p>'),
    ("person-screening", "学生人物自动筛查", '<p>视频分析时，系统根据画面特征（人脸大小、位置高度、走动范围、出现时长、清晰度和检测置信度）把疑似老师和空白、模糊的无效人选排除出学生列表，排除的人物不进入学生时间轴、测量、评价和报告。</p>'
     '<p>该筛查<span class="term-tag blue">不做身份识别结论</span>：不判断画面中任何人是谁，不建立人脸库，不用于考勤或评价教师；学生身份只由教师在名册中手动确认。教师可随时「恢复为学生」或「标记为老师/非学生」，系统按教师的选择处理。调试日志不记录人脸图像、姓名或坐标。</p>'),
    ("analysis", "分析结果如何使用", '<p>自动分析和模型建议供教师复核。学生未回应、画面模糊或人物被遮挡时，应标为证据不足；不能仅凭姿态或表情判定学生掌握程度、疾病或教师教学质量。新视频是否已完成实际分析，以任务状态和结果来源为准。</p>'),
    ("registration", "账号注册与隐私说明", '<p>本说明适用于平台注册名称为「WeGlow微光系统」（品牌 WeGlow）的账号与服务。使用中国大陆手机号（+86）、短信验证码和密码创建登录账号。手机号用于验证号码使用权、登录和必要的账号服务通知；验证码用于本次验证，密码用于身份认证。短信服务未配置时不提供短信注册，不会以申请登记代替账号创建。点击“注册并前往会员开通”表示同意本页2026-09-09版本的注册与会员服务说明。注册账号<span class="term-tag blue">不会扣费</span>，也不等于开通付费会员。</p><p>短信功能开放时，会通过所配置的短信服务发送验证码；该步骤不包含课堂视频或学生资料。需更正账号信息、申请导出或删除资料时，请联系项目服务人员，由管理员核对身份后处理。旧版学校开通申请仅作为历史记录保留，不再作为手机号注册流程。</p>'),
    ("membership", "会员服务说明", '<p>付费会员按实际公布的套餐、服务金额、期限和订单记录办理。金额未配置时显示“待公布”（页面提示为“价格即将公布”）；支付未配置时不提供付款，不生成支付二维码，也不会自动扣费或将账号标记为付费成功。创建订单不等于完成支付，会员有效状态以系统确认的实际开通结果为准。</p><p>购买前应确认具体服务范围、期限和售后安排；未公布或未配置的事项不作已上线承诺。既有教师内测权限与付费会员分开记录，不能将内测使用描述为购买成功。会员资格不替代学校授权，不能用于访问其他学校学生资料。</p>'),
    ("cloud", "后续云端与模型服务", '<p>如后续使用云存储或外部模型接口，将先明确服务提供方、数据传输范围与保存规则，再由校方确认。本版本的登录或注册操作不包含学生视频向外部模型传输的授权。</p>'),
)


def render_privacy() -> str:
    toc = "".join(f'<li><a href="#{key}" data-policy-link="{key}">{title}</a></li>' for key, title, _ in POLICY_SECTIONS)
    options = "".join(f'<option value="{key}">{index}. {title}</option>' for index, (key, title, _) in enumerate(POLICY_SECTIONS, start=1))
    sections = "".join(
        f'<section class="policy-card" id="{key}" aria-labelledby="{key}-title"><h2 id="{key}-title" tabindex="-1"><span class="policy-no" aria-hidden="true">{index}</span>{title}</h2>{body}</section>'
        for index, (key, title, body) in enumerate(POLICY_SECTIONS, start=1)
    )
    content = f"""<div class="policy-layout">
<nav class="policy-toc" aria-label="说明目录"><p class="policy-toc-title">目录</p><ol>{toc}</ol></nav>
<article class="policy-article"><div class="policy-toc-mobile"><label for="policyTocSelect">跳转到章节</label><select id="policyTocSelect" aria-label="跳转到章节">{options}</select></div>
<header class="policy-hero"><p class="entry-kicker">{BRAND_FULL_NAME} · 账号、会员与课堂资料</p><h1>数据安全与隐私说明</h1><p class="policy-date">平台注册名称：<strong id="platformRegisteredName">{BRAND_FULL_NAME}</strong>（品牌 {BRAND_NAME}） · 版本：<span id="policyVersion">{PRIVACY_VERSION}</span>（新增课程任务文件、IEP 文件与学生人物自动筛查说明；注册与会员服务条款仍为 2026-09-09 版本）</p>
<ul class="policy-keyfacts" aria-label="关键期限与约定"><li>原始视频默认保存 <strong>60 天</strong></li><li>到期前 <strong>15 天</strong> 提醒</li><li>结构化测量记录 <strong>730 天</strong></li><li>未确认的文件识别结果 <strong>24 小时</strong> 清除</li><li>注册账号 <strong>不扣费</strong></li></ul></header>
{sections}</article></div>"""
    script = r"""
const policyKeys=[...document.querySelectorAll('[data-policy-link]')].map(link=>link.dataset.policyLink);
let clickedKey='',clickedAt=0;
const reduceMotion=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
function markActive(key){document.querySelectorAll('[data-policy-link]').forEach(link=>link.setAttribute('aria-current',String(link.dataset.policyLink===key)));const select=document.getElementById('policyTocSelect');if(select&&select.value!==key)select.value=key;}
function goToSection(key){const section=document.getElementById(key);if(!section)return;clickedKey=key;clickedAt=Date.now();section.scrollIntoView({behavior:reduceMotion?'auto':'smooth',block:'start'});try{history.replaceState(null,'','#'+key);}catch(_){}markActive(key);const heading=document.getElementById(key+'-title');if(heading)heading.focus({preventScroll:true});}
document.querySelectorAll('[data-policy-link]').forEach(link=>link.addEventListener('click',event=>{event.preventDefault();goToSection(link.dataset.policyLink);}));
document.getElementById('policyTocSelect').addEventListener('change',event=>goToSection(event.target.value));
if('IntersectionObserver' in window){const visible=new Map();const observer=new IntersectionObserver(entries=>{entries.forEach(entry=>visible.set(entry.target.id,entry.isIntersecting?entry.boundingClientRect.top:null));const atBottom=window.innerHeight+window.scrollY>=document.documentElement.scrollHeight-4;if(clickedKey&&(Date.now()-clickedAt<1500||atBottom))return;clickedKey='';const current=policyKeys.find(key=>visible.get(key)!=null);if(current)markActive(current);},{rootMargin:'-10% 0px -65% 0px'});policyKeys.forEach(key=>{const node=document.getElementById(key);if(node)observer.observe(node);});}
const initial=decodeURIComponent(location.hash.slice(1));markActive(policyKeys.includes(initial)?initial:policyKeys[0]);
"""
    return _document(title="数据安全与隐私说明", body=_shell(content, nav='<a href="/demo2/login">返回登录</a>', main_class="privacy-main"), page_style=ENTRY_STYLE + PRIVACY_STYLE, script=script)
