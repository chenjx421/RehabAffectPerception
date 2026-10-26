"""Measurement workspace for Demo2 – teacher-entered classroom observation data.

render_measurement(account) -> standalone HTML page.
school_uploader : full workspace at /demo2/measurement
company_admin   : aggregate summary at /demo2/admin/measurements
No synthetic scores, invented dates, or fabricated confidence values.
"""
from __future__ import annotations

import json
from typing import Any

from .assessment_rubric import rubric_contract
from .demo2_portal import (
    _BOOK_ICON,
    _WORKSPACE_STYLE,
    _account_payload,
    _document,
)

_API = "/api/v1/demo2"


def _meas_nav(active: str) -> str:
    items = [
        ("upload", "上传任务"),
        ("students", "学生名册"),
        ("measurement", "测量记录"),
        ("evaluation", "课堂双轨评价"),
        ("school", "学校信息"),
        ("membership", "会员中心"),
    ]
    links = "".join(
        f'<a href="/demo2/{r}"{" aria-current=page" if r == active else ""}>{label}</a>'
        for r, label in items
    )
    return f'<nav class="workspace-nav" aria-label="账号工作台">{links}</nav>'


_MEAS_STYLE = """
.ws-layout{display:grid;grid-template-columns:256px minmax(0,1fr);min-height:calc(100vh - 64px);}
.ws-sidebar{border-right:1px solid var(--line);background:#fafcff;overflow-y:auto;position:sticky;top:64px;max-height:calc(100vh - 64px);}
.ws-sidebar-head{padding:14px 16px 10px;border-bottom:1px solid var(--line);}
.ws-sidebar-head h2{font-size:13px;color:var(--muted);font-weight:700;margin:0;text-transform:uppercase;letter-spacing:.03em;}
.student-list{padding:6px 0;}
.student-item{display:flex;align-items:center;gap:10px;padding:9px 16px;cursor:pointer;border-left:3px solid transparent;font-size:14px;transition:background .12s;}
.student-item:hover{background:var(--blue-soft);}
.student-item.active{background:var(--blue-soft);border-left-color:var(--blue);color:var(--blue-deep);font-weight:600;}
.s-code{color:var(--muted);font-size:11px;font-family:Consolas,monospace;margin-left:auto;}
.s-dot{width:8px;height:8px;border-radius:4px;background:var(--line-strong);flex:none;}
.has-records .s-dot{background:var(--blue);}
.ws-main{min-width:0;display:flex;flex-direction:column;}
.view-tabs{display:flex;gap:0;border-bottom:1px solid var(--line);background:#fff;position:sticky;top:64px;z-index:10;overflow-x:auto;}
.view-tab{min-height:44px;padding:10px 16px;border:0;border-bottom:3px solid transparent;background:transparent;color:var(--muted);font-size:13px;font-weight:500;white-space:nowrap;cursor:pointer;transition:color .14s,border-color .14s;}
.view-tab:hover{color:var(--blue);}
.view-tab[aria-selected=true]{color:var(--blue);border-bottom-color:var(--blue);font-weight:600;}
.view-pane{padding:20px 24px;flex:1;}
.overview-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px;margin-top:16px;}
.ov-card{border:1px solid var(--line);border-radius:6px;padding:14px 16px;background:#fff;}
.ov-card .label{font-size:11px;color:var(--muted);font-weight:700;text-transform:uppercase;}
.ov-card .val{font-size:28px;font-weight:700;color:var(--blue-deep);line-height:1.2;margin-top:4px;font-family:"Segoe UI",sans-serif;}
.rec-list{display:grid;gap:8px;margin-top:12px;}
.rec-row{display:flex;align-items:flex-start;gap:10px;padding:12px 14px;border:1px solid var(--line);border-radius:6px;background:#fff;font-size:13px;}
.rec-row-meta{flex:1;min-width:0;}
.rec-row-meta strong{display:block;margin-bottom:2px;}
.rec-row-meta span{color:var(--muted);font-size:12px;}
.rec-row-actions{display:flex;gap:6px;flex:none;}
.score-bar-wrap{margin-top:10px;}
.score-bar-row{display:flex;align-items:center;gap:8px;margin-bottom:5px;font-size:12px;}
.score-bar-label{width:52px;flex:none;color:var(--muted);}
.score-bar-track{flex:1;height:8px;border-radius:4px;background:var(--line);overflow:hidden;}
.score-bar-fill{height:100%;border-radius:4px;background:var(--blue);transition:width .3s;}
.score-bar-val{width:28px;flex:none;text-align:right;color:var(--ink);}
.form-section{margin-top:20px;}
.form-section h3{font-size:14px;font-weight:700;color:var(--blue-deep);margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid var(--line);}
.form-row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-bottom:12px;}
.form-row.three{grid-template-columns:repeat(3,minmax(0,1fr));}
.field-wide{grid-column:1/-1;}
.score-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:12px;}
.notice-pilot{padding:10px 14px;border-left:3px solid var(--warning);background:var(--warning-soft);color:var(--warning);font-size:12px;margin-bottom:12px;border-radius:0 4px 4px 0;}
.chart-wrap{position:relative;margin:16px 0;}
.chart-svg{width:100%;overflow:visible;}
.chart-legend{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:6px;font-size:12px;color:var(--muted);}
.chart-note{font-size:11px;color:var(--muted);margin-top:4px;}
.trend-controls{display:flex;flex-wrap:wrap;gap:8px 14px;margin-bottom:14px;align-items:flex-end;}
.withdraw-note{font-size:13px;color:var(--muted);margin-bottom:8px;}
@media(max-width:780px){
  .ws-layout{grid-template-columns:1fr;}
  .ws-sidebar{position:static;max-height:none;border-right:0;border-bottom:1px solid var(--line);}
  .student-list{display:flex;flex-wrap:wrap;gap:4px;padding:8px;}
  .student-item{border-radius:20px;border-left:0;border:1px solid var(--line);padding:6px 12px;font-size:13px;}
  .student-item.active{border-color:var(--blue);background:var(--blue-soft);}
  .score-grid{grid-template-columns:repeat(2,1fr);}
  .form-row,.form-row.three{grid-template-columns:1fr;}
  .view-pane{padding:14px 16px;}
}
@media print{
  .ws-sidebar,.site-header,.view-tabs,.rec-row-actions,.form-section,.ws-sidebar-head{display:none!important;}
  .ws-layout{display:block;}
  .ws-main{display:block;}
  .view-pane{padding:0;}
}
"""

_ADMIN_STYLE = _WORKSPACE_STYLE + """
.admin-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px;margin:20px 0;}
.stat-tile{border:1px solid var(--line);border-radius:6px;padding:16px 18px;background:#fff;}
.stat-tile .t-label{font-size:11px;color:var(--muted);font-weight:700;text-transform:uppercase;}
.stat-tile .t-val{font-size:32px;font-weight:700;color:var(--blue-deep);line-height:1.2;margin-top:4px;font-family:"Segoe UI",sans-serif;}
.channel-table-wrap{margin-top:20px;}
"""


def _teacher_body_html(account_json: str) -> str:
    """Static HTML skeleton for the teacher measurement workspace."""
    return f"""
<header class="site-header" role="banner">
  <div class="header-inner">
    <a class="brand" href="/demo2/upload">
      {_BOOK_ICON}
      <div class="brand-copy"><strong>RehabAffect</strong><span>内测平台</span></div>
    </a>
    {_meas_nav("measurement")}
    <div class="header-actions">
      <div class="account-chip"><span>教师账号</span><strong id="accountName">读取中</strong></div>
      <a class="button" href="/demo2/capture" id="captureLink">
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="3"/><path d="M3 9a2 2 0 0 1 2-2h.5L7 5h10l1.5 2H19a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z"/></svg>
        <span>课堂录制</span></a>
      <a class="button" href="/demo2/upload" id="uploadLink">
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><path d="M4 16v1a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-1M12 12V4m0 0-4 4m4-4 4 4"/></svg>
        <span>上传视频</span></a>
      <button class="button quiet" id="logoutBtn">退出</button>
    </div>
  </div>
</header>
<div class="ws-layout" id="wsLayout">
  <aside class="ws-sidebar" aria-label="学生列表">
    <div class="ws-sidebar-head">
      <h2>学生名册 <span id="sCount" style="font-weight:400;color:var(--muted)"></span></h2>
    </div>
    <div class="student-list" id="studentList" role="list" aria-label="选择学生"></div>
  </aside>
  <div class="ws-main">
    <div class="view-tabs" role="tablist" aria-label="工作区视图">
      <button role="tab" class="view-tab" data-tab="overview" aria-selected="false" aria-controls="paneOverview">总览</button>
      <button role="tab" class="view-tab" data-tab="form"     aria-selected="false" aria-controls="paneForm">记录测量</button>
      <button role="tab" class="view-tab" data-tab="trends"   aria-selected="false" aria-controls="paneTrends">纵向趋势</button>
      <button role="tab" class="view-tab" data-tab="report"   aria-selected="false" aria-controls="paneReport">单次报告</button>
      <button role="tab" class="view-tab" data-tab="standard" aria-selected="false" aria-controls="paneStandard">评分标准</button>
    </div>
    <div id="mainContent">
      <div id="pageMsg" class="page-message" role="alert" style="margin:12px 24px 0"></div>
      <div class="view-pane" id="paneOverview"  role="tabpanel" hidden></div>
      <div class="view-pane" id="paneForm"      role="tabpanel" hidden></div>
      <div class="view-pane" id="paneTrends"    role="tabpanel" hidden></div>
      <div class="view-pane" id="paneReport"    role="tabpanel" hidden></div>
      <div class="view-pane" id="paneStandard"  role="tabpanel" hidden></div>
    </div>
  </div>
</div>"""


def _admin_body(account_json: str) -> str:
    return f"""
<header class="site-header" role="banner">
  <div class="header-inner">
    <a class="brand" href="/demo2/admin">
      {_BOOK_ICON}
      <div class="brand-copy"><strong>RehabAffect</strong><span>公司后台</span></div>
    </a>
    <div class="header-actions">
      <div class="account-chip"><span>公司管理员</span><strong id="accountName">读取中</strong></div>
      <button class="button" id="refreshBtn" aria-label="刷新数据">刷新</button>
      <button class="button quiet" id="logoutBtn">退出</button>
    </div>
  </div>
</header>
<main id="mainContent" class="page-shell">
  <div class="page-heading">
    <div>
      <span class="eyebrow">运营统计</span>
      <h1>测量记录汇总</h1>
      <p class="lead" id="scopeNote">仅显示聚合数量；不含学生姓名、分数或原文。</p>
    </div>
  </div>
  <div id="pageMsg" class="page-message" role="alert"></div>
  <div class="admin-grid" id="statGrid">
    <div class="stat-tile"><div class="t-label">有效记录</div><div class="t-val" id="statTotal">—</div></div>
    <div class="stat-tile"><div class="t-label">已复核</div><div class="t-val" id="statReviewed">—</div></div>
    <div class="stat-tile"><div class="t-label">待复核</div><div class="t-val" id="statPending">—</div></div>
    <div class="stat-tile"><div class="t-label">30天内到期</div><div class="t-val" id="statDue">—</div></div>
  </div>
  <div class="channel-table-wrap">
    <h2 style="font-size:15px;margin-bottom:10px;">渠道明细</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>渠道</th><th>记录总数</th><th>已复核</th><th>待复核</th></tr></thead>
        <tbody id="channelBody"><tr><td colspan="4" class="loading-line">加载中…</td></tr></tbody>
      </table>
    </div>
  </div>
  <p style="margin-top:20px;font-size:12px;color:var(--muted);">原始媒体保留60天，结构化记录保留730天。记录到期仅提醒，人工归档后处理。</p>
</main>
<script>
const SA={account_json};
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const byId=id=>document.getElementById(id);
async function api(url,opts){{
  const r=await fetch(url,{{credentials:'include',...opts}});
  if(r.status===401){{window.location.assign('/demo2/login');throw new Error('请重新登录');}}
  const j=await r.json();if(!j.ok)throw new Error(j.error?.message||j.message||'请求失败');return j;
}}
function msg(text,type=''){{const el=byId('pageMsg');el.textContent=text;el.className='page-message'+(type?' '+type:'')+(text?' visible':'');}}
async function refresh(){{
  const btn=byId('refreshBtn');btn.disabled=true;
  try{{
    const d=await api('{_API}/admin/measurements');
    const s=d.summary||{{}};
    byId('statTotal').textContent=s.records??'—';
    byId('statReviewed').textContent=s.reviewed??'—';
    byId('statPending').textContent=s.pending??'—';
    byId('statDue').textContent=s.due_30_days??'—';
    const ch=Array.isArray(s.channels)?s.channels:[];
    byId('channelBody').innerHTML=ch.length
      ?ch.map(c=>`<tr><td class="mono">${{esc(c.channel_id)}}</td><td>${{esc(c.records)}}</td><td>${{esc(c.reviewed)}}</td><td>${{esc(c.pending)}}</td></tr>`).join('')
      :'<tr><td colspan="4">暂无渠道数据。</td></tr>';
    if(s.scope)byId('scopeNote').textContent=s.scope;
    msg('数据已刷新。','success');
  }}catch(e){{msg(e.message);}}finally{{btn.disabled=false;}}
}}
byId('accountName').textContent=SA.login_alias||SA.username||'管理员';
byId('refreshBtn').addEventListener('click',refresh);
byId('logoutBtn').addEventListener('click',async()=>{{try{{await api('{_API}/logout',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:'{{}}'}})}}finally{{window.location.assign('/demo2/login');}}}});
refresh();
</script>"""


def _teacher_script(account_json: str) -> str:
    # Same contract the backend scores with; '</' escaped so it cannot close the script tag.
    rubric_json = json.dumps(rubric_contract(), ensure_ascii=False).replace("</", "<\\/")
    init = (
        f"const ACCT={account_json};\n"
        f"const API='{_API}';\n"
        f"const RUBRIC={rubric_json};\n"
    )
    # JS uses raw braces; no f-string needed for the bulk
    rest = r"""
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const byId=id=>document.getElementById(id);
async function api(url,opts){
  const r=await fetch(url,{credentials:'include',...opts});
  if(r.status===401){window.location.assign('/demo2/login');throw new Error('请重新登录');}
  const j=await r.json();if(!j.ok)throw new Error(j.error?.message||j.message||'请求失败');return j;
}
function msg(text,type=''){const el=byId('pageMsg');el.textContent=text;el.className='page-message'+(type?' '+type:'')+(text?' visible':'');}
function fmtDate(s){if(!s)return'—';const d=new Date(s);return isNaN(d)?s:`${d.getFullYear()}/${String(d.getMonth()+1).padStart(2,'0')}/${String(d.getDate()).padStart(2,'0')}`;}
function scoreLabel(v){return v==null?'—':String(v);}
const DIM_LABELS=Object.fromEntries(RUBRIC.dimensions.map(d=>[d.key,d.label]));
const DIM_WEIGHTS=Object.fromEntries(RUBRIC.dimensions.map(d=>[d.key,d.weight_percent+'%']));
const EVIDENCE_INSUFFICIENT=RUBRIC.evidence_status.insufficient;
function fmtScore(v){return v==null?'—':Number(v).toFixed(RUBRIC.decimals);}
function formalScore(a){return a&&a.evidence_status!==EVIDENCE_INSUFFICIENT&&a.score!=null?a.score:null;}
let state={students:[],records:[],trends:[],stdStatus:'',selectedId:null,currentTab:'overview',saving:false};

async function loadWorkspace(){
  msg('加载中…','info');
  try{
    const d=await api(API+'/measurements');
    const ws=d.workspace||{};
    state.students=ws.students||[];
    state.records=ws.records||[];
    state.trends=ws.trends||[];
    state.stdStatus=ws.standard_status||'';
    renderSidebar();
    if(state.students.length)selectStudent(state.students[0].student_id,false);
    switchTab('overview');
    msg('');
  }catch(e){msg(e.message);}
}

function renderSidebar(){
  const sc=byId('sCount');if(sc)sc.textContent='（'+state.students.length+'人）';
  const list=byId('studentList');if(!list)return;
  const cnt={};for(const r of state.records)cnt[r.student_id]=(cnt[r.student_id]||0)+1;
  list.innerHTML=state.students.length?state.students.map(s=>`<div class="student-item${cnt[s.student_id]?' has-records':''}" data-id="${esc(s.student_id)}" role="listitem" tabindex="0" aria-label="${esc(s.display_name)}"><span class="s-dot"></span><span>${esc(s.display_name)}</span><span class="s-code">${esc(s.class_name||s.student_code||'')}</span></div>`).join(''):'<div style="padding:16px;color:var(--muted);font-size:13px;">暂无学生名册，请先完成身份确认。</div>';
  list.querySelectorAll('.student-item').forEach(el=>{
    el.addEventListener('click',()=>selectStudent(el.dataset.id));
    el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' ')selectStudent(el.dataset.id);});
  });
}

function selectStudent(id,switchToOverview=true){
  state.selectedId=id;
  document.querySelectorAll('.student-item').forEach(el=>el.classList.toggle('active',el.dataset.id===id));
  if(switchToOverview)switchTab('overview');else refreshCurrentPane();
}

function refreshCurrentPane(){switchTab(state.currentTab);}

function switchTab(tab){
  state.currentTab=tab;
  document.querySelectorAll('.view-tab').forEach(t=>t.setAttribute('aria-selected',String(t.dataset.tab===tab)));
  ['overview','form','trends','report','standard'].forEach(t=>{const el=byId('pane'+t.charAt(0).toUpperCase()+t.slice(1));if(el)el.hidden=t!==tab;});
  if(tab==='overview')renderOverview();
  else if(tab==='form')renderForm(null);
  else if(tab==='trends')renderTrends();
  else if(tab==='report')renderReport(null);
  else if(tab==='standard')renderStandard();
}

function studentName(id){const s=state.students.find(x=>x.student_id===id);return s?s.display_name:id;}
function studentRecords(id){return state.records.filter(r=>r.student_id===id);}

function renderOverview(){
  const pane=byId('paneOverview');if(!pane)return;
  const sid=state.selectedId;
  if(!sid){pane.innerHTML='<p style="color:var(--muted)">请从左侧选择学生。</p>';return;}
  const recs=studentRecords(sid);
  const reviewed=recs.filter(r=>formalScore(r.assessment)!=null).length;
  const pending=recs.length-reviewed;
  pane.innerHTML=`<h2 style="font-size:17px;margin-bottom:4px">${esc(studentName(sid))}</h2>
<div class="overview-cards">
  <div class="ov-card"><div class="label">有效记录</div><div class="val">${recs.length}</div></div>
  <div class="ov-card"><div class="label">已复核得分</div><div class="val">${reviewed}</div></div>
  <div class="ov-card"><div class="label">待复核</div><div class="val">${pending}</div></div>
</div>
<div style="margin-top:18px;display:flex;gap:10px;flex-wrap:wrap">
  <button class="button primary" onclick="switchTab('form')">+ 新增记录</button>
  <button class="button" onclick="switchTab('trends')">查看趋势</button>
</div>
<div class="rec-list" id="ovRecList" style="margin-top:20px"></div>`;
  const recList=byId('ovRecList');
  if(!recs.length){recList.innerHTML='<p style="color:var(--muted);font-size:14px">该学生暂无记录。</p>';return;}
  recList.innerHTML=recs.slice().reverse().map(r=>{
    const sc=formalScore(r.assessment);
    const reasons=(r.assessment?.evidence_reasons||[]).join('；');
    const badge=sc!=null?`<span class="status-badge success">得分 ${fmtScore(sc)}</span>`:`<span class="status-badge warning" title="${esc(reasons)}">${esc(EVIDENCE_INSUFFICIENT)}</span>`;
    return `<div class="rec-row"><div class="rec-row-meta"><strong>${esc(fmtDate(r.lesson_date))} · ${esc(r.course_name||r.lesson_id)}</strong><span>${esc(r.goal_id)} / ${esc(r.measurement_context)}</span></div>${badge}<div class="rec-row-actions"><button class="button" style="font-size:12px;min-height:36px;padding:6px 10px" onclick="editRecord(${esc(JSON.stringify(r.record_id))})">编辑</button><button class="button" style="font-size:12px;min-height:36px;padding:6px 10px;color:var(--danger)" onclick="promptWithdraw(${esc(JSON.stringify(r.record_id))},${Number(r.version)})">撤销</button></div></div>`;
  }).join('');
}

let _editingRecord=null;

function renderForm(existing){
  const pane=byId('paneForm');if(!pane)return;
  const sid=state.selectedId;
  if(!sid){pane.innerHTML='<p style="color:var(--muted)">请先从左侧选择学生。</p>';return;}
  _editingRecord=existing||null;
  const prev=existing||{};
  const isEdit=!!existing;
  const recs=studentRecords(sid);
  const prevGoals=[...new Set(recs.map(r=>r.goal_id).filter(Boolean))];
  const prevContexts=[...new Set(recs.map(r=>r.measurement_context).filter(Boolean))];
  const prevCriterions=[...new Set(recs.map(r=>r.criterion).filter(Boolean))];
  const prevCourses=[...new Set(recs.map(r=>r.course_name).filter(Boolean))];
  function datalistHtml(id,vals){return `<datalist id="${id}">${vals.map(v=>`<option value="${esc(v)}">`).join('')}</datalist>`;}
  pane.innerHTML=`
<h2 style="font-size:16px;margin-bottom:4px">${isEdit?'编辑记录':'新增测量记录'} — ${esc(studentName(sid))}</h2>
<p style="font-size:13px;color:var(--muted);margin-bottom:14px">${isEdit?`记录编号 <code>${esc(prev.record_id)}</code>，当前版本 ${prev.version}`:'填写本课真实观察数据，不得使用虚构日期。'}</p>
<div class="notice-pilot">试行量表说明：准确性35%、独立性30%、一致性20%、泛化性15%为设计参考，尚待校方确认，不是官方验证权重。6分为参考合格线，不具法定效力。</div>
<div id="formErr" class="form-error" role="alert"></div>
<form id="measForm" novalidate autocomplete="off">
<div class="form-section"><h3>课程信息</h3>
<div class="form-row">
  <div class="field"><label for="fLessonDate">上课日期 <span aria-hidden="true" style="color:var(--danger)">*</span></label><input type="date" id="fLessonDate" name="lesson_date" required max="${new Date().toISOString().slice(0,10)}" value="${esc(prev.lesson_date||'')}"><small>必须为真实上课日期，不接受未来日期。</small></div>
  <div class="field"><label for="fLessonId">课节编号 <span aria-hidden="true" style="color:var(--danger)">*</span></label><input type="text" id="fLessonId" name="lesson_id" required maxlength="120" value="${esc(prev.lesson_id||'')}" placeholder="如 L2025-11-03-A"></div>
</div>
<div class="form-row">
  <div class="field"><label for="fCourseName">课程名称</label><input type="text" id="fCourseName" name="course_name" maxlength="200" value="${esc(prev.course_name||'')}" list="courseList" placeholder="如 生活自理技能训练">${datalistHtml('courseList',prevCourses)}</div>
  <div class="field"><label for="fSourceType">数据来源 <span aria-hidden="true" style="color:var(--danger)">*</span></label><select id="fSourceType" name="source_type" required><option value="">请选择</option><option value="classroom_observation"${prev.source_type==='classroom_observation'?' selected':''}>现场观察</option><option value="video_review"${prev.source_type==='video_review'?' selected':''}>视频复核</option></select></div>
</div></div>
<div class="form-section" id="videoSection" style="display:none"><h3>视频信息（视频复核必填）</h3>
<div class="form-row three">
  <div class="field"><label for="fTaskId">上传任务编号</label><input type="text" id="fTaskId" name="task_id" maxlength="120" value="${esc(prev.task_id||'')}"><small>需已完成身份确认。<a href="/demo2/identity">去确认</a></small></div>
  <div class="field"><label for="fStartSec">片段起始（秒）</label><input type="number" id="fStartSec" name="start_sec" min="0" max="10800" step="0.1" value="${prev.start_sec!=null?prev.start_sec:''}"></div>
  <div class="field"><label for="fEndSec">片段结束（秒）</label><input type="number" id="fEndSec" name="end_sec" min="0" max="10800" step="0.1" value="${prev.end_sec!=null?prev.end_sec:''}"></div>
</div></div>
<div class="form-section"><h3>学习目标与测量条件</h3>
<div class="form-row">
  <div class="field"><label for="fGoalId">学习目标编号 <span aria-hidden="true" style="color:var(--danger)">*</span></label><input type="text" id="fGoalId" name="goal_id" required maxlength="200" value="${esc(prev.goal_id||'')}" list="goalList" placeholder="如 G-ADL-03">${datalistHtml('goalList',prevGoals)}</div>
  <div class="field"><label for="fMeasCtx">测量条件（可比条件） <span aria-hidden="true" style="color:var(--danger)">*</span></label><input type="text" id="fMeasCtx" name="measurement_context" required maxlength="200" value="${esc(prev.measurement_context||'')}" list="ctxList" placeholder="如 独立进餐/勺子/教室">${datalistHtml('ctxList',prevContexts)}</div>
</div>
<div class="form-row">
  <div class="field field-wide"><label for="fCriterion">具体通过标准（6分参考） <span aria-hidden="true" style="color:var(--danger)">*</span></label><textarea id="fCriterion" name="criterion" required maxlength="2000" rows="2" style="width:100%;border:1px solid var(--line-strong);border-radius:6px;padding:9px 12px;font:inherit;resize:vertical">${esc(prev.criterion||'')}</textarea><small>描述可量化、重复测量的行为标准，不要写教学计划。</small></div>
</div></div>
<div class="form-section"><h3>四维评分（留空表示本次未观察，不得填写0代替）</h3>
<div class="notice-pilot" style="margin-bottom:10px">以下权重为试行参考，尚未经过校方数据校准。0分表示真实的零成功，缺乏观察机会时请留空。</div>
<div class="score-grid">
  <div class="field"><label for="fAcc">准确性（0–10，权重35%）</label><input type="number" id="fAcc" name="acc" min="0" max="10" step="0.1" placeholder="留空=未观察" value="${prev.scores?.accuracy!=null?prev.scores.accuracy:''}"></div>
  <div class="field"><label for="fInd">独立性（0–10，权重30%）</label><input type="number" id="fInd" name="ind" min="0" max="10" step="0.1" placeholder="留空=未观察" value="${prev.scores?.independence!=null?prev.scores.independence:''}"></div>
  <div class="field"><label for="fCon">一致性（0–10，权重20%）</label><input type="number" id="fCon" name="con" min="0" max="10" step="0.1" placeholder="留空=未观察" value="${prev.scores?.consistency!=null?prev.scores.consistency:''}"></div>
  <div class="field"><label for="fTrf">泛化性（0–10，权重15%）</label><input type="number" id="fTrf" name="trf" min="0" max="10" step="0.1" placeholder="留空=未观察" value="${prev.scores?.transfer!=null?prev.scores.transfer:''}"></div>
</div></div>
<div class="form-section"><h3>观察次数与复核</h3>
<div class="form-row three">
  <div class="field"><label for="fOpps">提供机会次数</label><input type="number" id="fOpps" name="opportunities" min="0" max="9999" step="1" value="${prev.opportunities!=null?prev.opportunities:''}"><small>本课安排的练习机会总数。</small></div>
  <div class="field"><label for="fObs">实际观察次数</label><input type="number" id="fObs" name="observed" min="0" max="9999" step="1" value="${prev.observed!=null?prev.observed:''}"><small>教师实际记录的次数。</small></div>
  <div class="field" style="display:flex;align-items:flex-end;gap:10px;padding-bottom:4px"><label style="display:flex;align-items:center;gap:8px;font-size:13px;font-weight:700;color:var(--blue-deep);cursor:pointer"><input type="checkbox" id="fReviewed" name="reviewed" style="width:20px;min-height:20px;flex:none"${prev.reviewed?' checked':''}> 教师已完成复核</label></div>
</div>
<div class="form-row">
  <div class="field field-wide"><label for="fEvidence">观察记录与证据摘要</label><textarea id="fEvidence" name="evidence" maxlength="2000" rows="3" style="width:100%;border:1px solid var(--line-strong);border-radius:6px;padding:9px 12px;font:inherit;resize:vertical">${esc(prev.evidence||'')}</textarea><small>描述具体行为表现，作为评分依据。视频复核请注明片段时间点。</small></div>
</div></div>
<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:8px">
  <button type="submit" class="button primary" id="saveBtn">保存记录</button>
  <button type="button" class="button" onclick="switchTab('overview')">取消</button>
</div>
</form>`;
  const srcSel=byId('fSourceType');
  const videoSec=byId('videoSection');
  function toggleVideo(){if(videoSec)videoSec.style.display=srcSel.value==='video_review'?'':'none';}
  srcSel.addEventListener('change',toggleVideo);toggleVideo();
  byId('measForm').addEventListener('submit',async e=>{
    e.preventDefault();
    if(state.saving)return;
    const errEl=byId('formErr');errEl.className='form-error';errEl.textContent='';
    const fd=new FormData(e.target);
    function fv(n){const v=fd.get(n);return typeof v==='string'?v.trim():v;}
    function fnum(n){const v=fv(n);return v===''||v==null?null:parseFloat(v);}
    function fint(n){const v=fv(n);return v===''||v==null?null:parseInt(v,10);}
    const lessonDate=fv('lesson_date');
    if(!lessonDate){errEl.textContent='请选择上课日期。';errEl.className='form-error visible';return;}
    const today=new Date().toISOString().slice(0,10);
    if(lessonDate>today){errEl.textContent='上课日期不能是未来日期。';errEl.className='form-error visible';return;}
    const lessonId=fv('lesson_id');
    if(!lessonId){errEl.textContent='请填写课节编号。';errEl.className='form-error visible';return;}
    const goalId=fv('goal_id');if(!goalId){errEl.textContent='请填写学习目标编号。';errEl.className='form-error visible';return;}
    const measCtx=fv('measurement_context');if(!measCtx){errEl.textContent='请填写测量条件。';errEl.className='form-error visible';return;}
    const criterion=fv('criterion');if(!criterion){errEl.textContent='请填写通过标准。';errEl.className='form-error visible';return;}
    const sourceType=fv('source_type');if(!sourceType){errEl.textContent='请选择数据来源。';errEl.className='form-error visible';return;}
    const scores={accuracy:fnum('acc'),independence:fnum('ind'),consistency:fnum('con'),transfer:fnum('trf')};
    for(const[k,v]of Object.entries(scores)){if(v!=null&&(v<0||v>10)){errEl.textContent=`${DIM_LABELS[k]}分数须在0到10之间。`;errEl.className='form-error visible';return;}}
    const opportunities=fint('opportunities'),observed=fint('observed');
    if(opportunities==null||opportunities<0){errEl.textContent='请填写提供机会次数（非负整数）。';errEl.className='form-error visible';return;}
    if(observed==null||observed<0){errEl.textContent='请填写实际观察次数（非负整数）。';errEl.className='form-error visible';return;}
    if(observed>opportunities){errEl.textContent='实际观察次数不能大于提供机会次数。';errEl.className='form-error visible';return;}
    const payload={
      record_id:isEdit?prev.record_id:crypto.randomUUID(),
      expected_version:isEdit?prev.version:0,
      student_id:sid,lesson_date:lessonDate,lesson_id:lessonId,
      course_name:fv('course_name')||lessonId,
      goal_id:goalId,measurement_context:measCtx,criterion,
      scores,
      opportunities,observed,
      reviewed:byId('fReviewed').checked,
      evidence:fv('evidence')||'',
      source_type:sourceType,
      task_id:sourceType==='video_review'?fv('task_id'):undefined,
      start_sec:sourceType==='video_review'?fnum('start_sec'):undefined,
      end_sec:sourceType==='video_review'?fnum('end_sec'):undefined,
    };
    if(sourceType!=='video_review'){delete payload.task_id;delete payload.start_sec;delete payload.end_sec;}
    state.saving=true;
    const btn=byId('saveBtn');if(btn)btn.disabled=true;
    try{
      const d=await api(API+'/measurements',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      const saved=d.record;
      if(isEdit){const idx=state.records.findIndex(r=>r.record_id===saved.record_id);if(idx>=0)state.records[idx]=saved;else state.records.push(saved);}
      else state.records.push(saved);
      msg(d.archive_sync?.status==='pending_retry'?'记录已保存，学生档案同步稍后自动重试。':'记录已保存。','success');switchTab('overview');
    }catch(e){
      if(e.message&&e.message.includes('身份')){errEl.innerHTML=`${esc(e.message)} <a href="/demo2/identity?task_id=${encodeURIComponent(payload.task_id||'')}">去确认身份</a>`;}
      else errEl.textContent=e.message;
      errEl.className='form-error visible';
    }finally{state.saving=false;if(btn)btn.disabled=false;}
  });
}

function editRecord(recordId){
  const r=state.records.find(x=>x.record_id===recordId);
  if(!r){msg('记录未找到。');return;}
  state.selectedId=r.student_id;
  document.querySelectorAll('.student-item').forEach(el=>el.classList.toggle('active',el.dataset.id===r.student_id));
  switchTab('form');
  renderForm(r);
}

async function promptWithdraw(recordId,version){
  const reason=window.prompt('请输入撤销原因（必填，将进入审计日志）：');
  if(!reason||!reason.trim())return;
  try{
    const d=await api(API+'/measurements/withdraw',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({record_id:recordId,expected_version:version,reason:reason.trim()})});
    state.records=state.records.filter(r=>r.record_id!==recordId);
    msg('记录已撤销。','success');switchTab('overview');
  }catch(e){msg(e.message);}
}

function renderTrends(){
  const pane=byId('paneTrends');if(!pane)return;
  const sid=state.selectedId;
  if(!sid){pane.innerHTML='<p style="color:var(--muted)">请从左侧选择学生。</p>';return;}
  const studentTrends=state.trends.filter(t=>t.student_id===sid);
  if(!studentTrends.length){pane.innerHTML='<p style="color:var(--muted)">该学生暂无可比较趋势数据。需要至少两条相同目标和条件的记录。</p>';return;}
  let selIndex=typeof pane._selIndex==='number'?pane._selIndex:0;
  if(selIndex>=studentTrends.length)selIndex=0;
  const t=studentTrends[selIndex];
  const seriesKeys=['lesson','week','month','rolling_60_days'].filter(k=>t.series&&k in t.series);
  let selSeries=pane._selSeries||seriesKeys[0]||'lesson';
  if(!seriesKeys.includes(selSeries))selSeries=seriesKeys[0]||'lesson';
  const SERIES_LABELS={lesson:'逐课',week:'周汇总',month:'月汇总',rolling_60_days:'60天滚动'};
  const trendOpts=studentTrends.map((tr,i)=>`<option value="${i}"${i===selIndex?' selected':''}>${esc(tr.goal_id)} / ${esc(tr.measurement_context)}</option>`).join('');
  const seriesOpts=seriesKeys.map(k=>`<option value="${k}"${k===selSeries?' selected':''}>${SERIES_LABELS[k]||k}</option>`).join('');
  pane.innerHTML=`
<h2 style="font-size:16px;margin-bottom:12px">纵向趋势 — ${esc(studentName(sid))}</h2>
<div class="trend-controls">
  <div class="field" style="min-width:260px;max-width:400px"><label for="trendSel" style="font-size:12px">目标 / 条件</label>
    <select id="trendSel">${trendOpts}</select></div>
  <div class="field"><label for="seriesSel" style="font-size:12px">粒度</label>
    <select id="seriesSel">${seriesOpts}</select></div>
</div>
<p style="font-size:12px;color:var(--muted);margin-bottom:4px">标准：${esc(t.criterion||'—')}　版本：${esc(t.rubric_version||'—')}</p>
<p style="font-size:11px;color:var(--warning);margin-bottom:10px">注意：仅相同目标、条件、标准及量表版本的记录可比较；混合不同版本数据无意义。</p>
<div class="chart-wrap" id="chartWrap"></div>
<div class="chart-legend" id="chartLegend"></div>
<p class="chart-note" id="chartNote"></p>
<details style="margin-top:16px"><summary style="font-size:13px;cursor:pointer;color:var(--blue)">无障碍数据表格</summary>
<div class="table-wrap" style="margin-top:8px" id="trendTable"></div></details>`;
  pane._selIndex=selIndex;pane._selSeries=selSeries;
  byId('trendSel').addEventListener('change',e=>{pane._selIndex=parseInt(e.target.value);renderTrends();});
  byId('seriesSel').addEventListener('change',e=>{pane._selSeries=e.target.value;renderTrends();});
  const rawPts=t.series[selSeries];
  const pts=selSeries==='rolling_60_days'
    ? (Array.isArray(rawPts)?rawPts:(rawPts&&typeof rawPts==='object'?[rawPts]:[]))
    : (Array.isArray(rawPts)?rawPts:[]);
  renderTrendChart(byId('chartWrap'),byId('chartLegend'),byId('chartNote'),byId('trendTable'),pts,selSeries);
}

function renderTrendChart(wrap,legend,note,tableWrap,pts,seriesKey){
  if(!pts.length){wrap.innerHTML='<p style="color:var(--muted);font-size:13px">本粒度暂无数据。</p>';return;}
  const W=Math.min(680,wrap.clientWidth||560),H=220,PL=40,PR=16,PT=14,PB=36;
  const IW=W-PL-PR,IH=H-PT-PB;
  const hasScore=pts.some(p=>p.score!=null);
  if(!hasScore){wrap.innerHTML='<p style="color:var(--muted);font-size:13px">本段无已复核综合得分。评分需教师复核且满足量表最低条件。</p>';return;}
  const labels=pts.map(p=>seriesKey==='lesson'?(p.date||'').slice(5):seriesKey==='rolling_60_days'?(p.from||'').slice(5):p.period||'');
  const n=pts.length;
  const xStep=n>1?IW/(n-1):IW/2;
  const yScale=v=>PT+IH-(v/10)*IH;
  let pathD='',dots='';let prev=null;
  pts.forEach((p,i)=>{
    const x=PL+(n>1?i*xStep:IW/2);
    if(p.score==null){prev=null;return;}
    const y=yScale(p.score);
    if(prev===null)pathD+=`M${x.toFixed(1)},${y.toFixed(1)}`;
    else pathD+=` L${x.toFixed(1)},${y.toFixed(1)}`;
    prev=p;
    dots+=`<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4" fill="var(--blue)" aria-label="${esc(labels[i]||'')} 得分${fmtScore(p.score)}"/>`;
  });
  const passY=yScale(6);
  const yLines=[0,2,4,6,8,10].map(v=>{
    const y=yScale(v);
    return `<line x1="${PL}" y1="${y.toFixed(1)}" x2="${(W-PR).toFixed(1)}" y2="${y.toFixed(1)}" stroke="${v===6?'#e8a020':'var(--line)'}" stroke-width="${v===6?1.5:1}" stroke-dasharray="${v===6?'4,3':''}"/>
<text x="${(PL-6).toFixed(1)}" y="${(y+4).toFixed(1)}" text-anchor="end" font-size="10" fill="var(--muted)">${v}</text>`;
  }).join('');
  const xTicks=pts.map((p,i)=>{
    if(n<=10||i%(Math.ceil(n/8))===0){
      const x=PL+(n>1?i*xStep:IW/2);
      return `<text x="${x.toFixed(1)}" y="${(H-4).toFixed(1)}" text-anchor="middle" font-size="10" fill="var(--muted)">${esc(labels[i]||'')}</text>`;
    }return '';
  }).join('');
  const nonNull=pts.filter(p=>p.score!=null);
  wrap.innerHTML=`<svg class="chart-svg" viewBox="0 0 ${W} ${H}" aria-label="纵向得分趋势图" role="img" style="max-width:100%">
  <title>纵向趋势</title>${yLines}
  ${pathD?`<path d="${pathD}" fill="none" stroke="var(--blue)" stroke-width="2" stroke-linejoin="round"/>`:''}
  ${dots}${xTicks}
  <text x="${PL}" y="${(passY-4).toFixed(1)}" font-size="10" fill="#c07010">参考合格线 6分（试行）</text>
</svg>`;
  legend.innerHTML=`<span style="display:inline-flex;align-items:center;gap:4px"><span style="width:16px;height:3px;background:var(--blue);display:inline-block;border-radius:2px"></span>综合得分（已复核）</span><span style="display:inline-flex;align-items:center;gap:4px"><span style="width:16px;height:2px;background:#e8a020;display:inline-block;border-radius:1px;border-top:1px dashed #e8a020"></span>参考合格线（试行）</span>`;
  note.textContent=`共${pts.length}个时间点，其中${nonNull.length}个有已复核得分；空白表示该时间点未达到评分条件或尚未复核，非得分为零。`;
  const tableRows=pts.map(p=>{
    const sessions=p.sessions!=null?p.sessions:'—';
    return `<tr><td>${esc(seriesKey==='lesson'?p.date||'—':seriesKey==='rolling_60_days'?`${p.from||''}~${p.to||''}`:p.period||'—')}</td><td>${p.score!=null?fmtScore(p.score):'（未评分）'}</td><td>${sessions}</td></tr>`;
  }).join('');
  tableWrap.innerHTML=`<table><thead><tr><th>${seriesKey==='lesson'?'日期':seriesKey==='rolling_60_days'?'区间':'周期'}</th><th>综合得分</th><th>课次</th></tr></thead><tbody>${tableRows}</tbody></table>`;
}

function renderReport(recordId){
  const pane=byId('paneReport');if(!pane)return;
  const sid=state.selectedId;
  if(!sid){pane.innerHTML='<p style="color:var(--muted)">请从左侧选择学生。</p>';return;}
  const recs=studentRecords(sid).filter(r=>formalScore(r.assessment)!=null);
  if(!recs.length){pane.innerHTML='<p style="color:var(--muted)">该学生暂无已复核且有综合得分的记录，无法生成报告。</p>';return;}
  let selId=recordId||pane._selId||recs[recs.length-1].record_id;
  if(!recs.find(r=>r.record_id===selId))selId=recs[recs.length-1].record_id;
  pane._selId=selId;
  const r=recs.find(x=>x.record_id===selId);
  const recOpts=recs.slice().reverse().map(x=>`<option value="${esc(x.record_id)}"${x.record_id===selId?' selected':''}>${esc(fmtDate(x.lesson_date))} ${esc(x.goal_id)}</option>`).join('');
  const asmnt=r.assessment||{};
  const dims=asmnt.dimensions||{};
  const overallScore=formalScore(asmnt);
  const passed=asmnt.passed;
  const scaledMax=asmnt.scale?.max||10;
  const passScore=asmnt.scale?.pass_score||6;
  const insufficientEvidence=asmnt.evidence_status===EVIDENCE_INSUFFICIENT||overallScore==null;
  function dimBar(key){
    const d=dims[key];if(!d||d.score==null)return`<div class="score-bar-row"><span class="score-bar-label">${esc(DIM_LABELS[key]||key)}</span><span style="color:var(--muted);font-size:12px">未观察</span></div>`;
    const pct=Math.min(100,Math.max(0,(d.score/scaledMax)*100));
    return`<div class="score-bar-row"><span class="score-bar-label">${esc(DIM_LABELS[key]||key)}</span><div class="score-bar-track"><div class="score-bar-fill" style="width:${pct.toFixed(1)}%"></div></div><span class="score-bar-val">${d.score}</span><span style="color:var(--muted);font-size:11px">(${esc(DIM_WEIGHTS[key]||'')})</span></div>`;
  }
  let scoreBlock='';
  if(insufficientEvidence){scoreBlock=`<div class="notice-pilot" style="border-color:var(--warning)">${esc(EVIDENCE_INSUFFICIENT)}：${esc((asmnt.evidence_reasons||[]).join('；')||'未达到最低评分条件')}。不生成综合得分，避免基于不充分证据给出数字。</div>`;}
  else{
    const passedStr=passed===true?'（达到参考合格线）':passed===false?'（未达参考合格线）':'';
    scoreBlock=`<div style="display:flex;align-items:flex-end;gap:12px;margin-bottom:8px"><span style="font-size:42px;font-weight:700;color:var(--blue-deep);line-height:1">${fmtScore(overallScore)}</span><span style="font-size:13px;color:var(--muted)">/ ${scaledMax}分 ${passedStr}</span></div>`;
  }
  const histTrend=state.trends.find(t=>t.student_id===sid&&t.goal_id===r.goal_id&&t.measurement_context===r.measurement_context&&t.criterion===r.criterion&&t.rubric_version===r.rubric_version);
  const histPts=histTrend?(histTrend.series.lesson||[]):[];
  const sourceLink=r.source_type==='video_review'&&r.task_id?`<a href="/demo2/video?id=${encodeURIComponent(r.task_id)}&t=${r.start_sec||0}" style="color:var(--blue);font-size:13px">查看视频片段 (${r.start_sec||0}s – ${r.end_sec||''}s)</a>`:'<span style="color:var(--muted);font-size:13px">数据来源：现场课堂观察</span>';
  pane.innerHTML=`
<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:16px">
  <h2 style="font-size:16px">${esc(studentName(sid))} · 单次记录报告</h2>
  <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
    <select id="reportSel" style="font-size:13px;min-height:36px">${recOpts}</select>
    <button class="button" style="font-size:12px;min-height:36px" onclick="printReport()">打印 / PDF</button>
    <button class="button" style="font-size:12px;min-height:36px" onclick="downloadReport()">下载 HTML</button>
  </div>
</div>
<div id="reportContent">
<div class="card" style="margin-bottom:16px"><div class="card-body">
  <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;font-size:13px;margin-bottom:12px">
    <div><span style="color:var(--muted)">日期：</span>${esc(fmtDate(r.lesson_date))}</div>
    <div><span style="color:var(--muted)">课节：</span>${esc(r.lesson_id)}</div>
    <div><span style="color:var(--muted)">课程：</span>${esc(r.course_name||'—')}</div>
    <div><span style="color:var(--muted)">目标：</span>${esc(r.goal_id)}</div>
    <div><span style="color:var(--muted)">条件：</span>${esc(r.measurement_context)}</div>
    <div><span style="color:var(--muted)">来源：</span>${r.source_type==='video_review'?'视频复核':'现场观察'}</div>
    <div><span style="color:var(--muted)">机会次数：</span>${r.opportunities!=null?r.opportunities:'—'}</div>
    <div><span style="color:var(--muted)">观察次数：</span>${r.observed!=null?r.observed:'—'}</div>
  </div>
  <p style="font-size:13px;color:var(--muted);margin-bottom:4px">通过标准：</p>
  <p style="font-size:13px;border-left:3px solid var(--blue);padding-left:10px">${esc(r.criterion||'—')}</p>
</div></div>
<div class="card" style="margin-bottom:16px"><div class="card-body">
  <h3 style="font-size:14px;margin-bottom:12px">综合评分</h3>
  ${scoreBlock}
  <div class="score-bar-wrap">${['accuracy','independence','consistency','transfer'].map(dimBar).join('')}</div>
  <p style="font-size:11px;color:var(--warning);margin-top:10px">准确性35%·独立性30%·一致性20%·泛化性15%为试行设计权重，尚待校方确认。6分参考合格线不具法定效力。评分由教师人工依照量表复核，视频处理不自动给分。</p>
  <div style="margin-top:10px">${sourceLink}</div>
</div></div>
${r.evidence?`<div class="card" style="margin-bottom:16px"><div class="card-body"><h3 style="font-size:14px;margin-bottom:8px">观察记录摘要</h3><p style="font-size:13px;white-space:pre-wrap;word-break:break-word">${esc(r.evidence)}</p></div></div>`:''}
${histPts.length>1?`<div class="card" style="margin-bottom:16px"><div class="card-body"><h3 style="font-size:14px;margin-bottom:8px">历史趋势（同目标/条件/标准）</h3><div id="reportChart"></div><p style="font-size:11px;color:var(--muted);margin-top:6px">仅相同目标、测量条件、通过标准及量表版本的记录参与比较。空缺表示该课次未达评分条件或未复核，非得分为零。</p></div></div>`:''}
<div class="card"><div class="card-body">
  <h3 style="font-size:14px;margin-bottom:8px">评分说明</h3>
  <p style="font-size:13px;line-height:1.8;color:#3d526d">本报告呈现教师逐课手工记录数据，经教师依量表复核后生成综合得分。量表采用10分制，6分为试行参考合格线。四个维度为：准确性（目标行为完成正确率）、独立性（完成行为所需提示级别）、一致性（在相同条件下重复出现的稳定程度）、泛化性（在新材料或新场景中是否出现，少于2次观察机会时应留空而非填0）。各维度权重为试行参考，尚待校方结合实际数据校准，不应引用为官方验证结论。本次得分仅反映所记录课次的表现，不代表该学生的整体能力评价；跨课比较需保持相同目标、条件与通过标准，混合不同测量条件的数据不具可比性。视频处理系统不自动给分，所有得分均由教师人工判断后填写。</p>
  <p style="font-size:11px;color:var(--muted);margin-top:8px">量表版本：${esc(r.rubric_version||'—')}　更新时间：${esc(r.updated_at||'—')}</p>
</div></div>
</div>`;
  byId('reportSel').addEventListener('change',e=>{pane._selId=e.target.value;renderReport(e.target.value);});
  if(histPts.length>1){
    const cWrap=byId('reportChart');
    if(cWrap){
      const leg=document.createElement('div');leg.className='chart-legend';cWrap.after(leg);
      const note=document.createElement('p');note.className='chart-note';leg.after(note);
      renderTrendChart(cWrap,leg,note,document.createElement('div'),histPts,'lesson');
    }
  }
}

function printReport(){window.print();}

function downloadReport(){
  const sid=state.selectedId;
  const pane=byId('paneReport');
  const content=byId('reportContent');
  if(!content){return;}
  const sname=esc(studentName(sid||''));
  const html=`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>测量报告 ${sname}</title><style>body{font-family:"Microsoft YaHei UI","Segoe UI",sans-serif;font-size:14px;line-height:1.6;color:#172b4d;max-width:800px;margin:auto;padding:20px}h2,h3{color:#1f63c6}.card{border:1px solid #cfdcea;border-radius:8px;padding:16px;margin-bottom:16px}.score-bar-row{display:flex;align-items:center;gap:8px;margin-bottom:5px;font-size:12px}.score-bar-track{flex:1;height:8px;border-radius:4px;background:#e4e9ef;overflow:hidden}.score-bar-fill{height:100%;border-radius:4px;background:#1f63c6}.notice-pilot{padding:8px 12px;border-left:3px solid #9a5a08;background:#fff7e8;color:#9a5a08;font-size:12px;margin:8px 0}</style></head><body>${content.innerHTML}</body></html>`;
  const blob=new Blob([html],{type:'text/html'});
  const a=document.createElement('a');
  a.href=URL.createObjectURL(blob);
  a.download=`report_${(sid||'').slice(0,8)}_${new Date().toISOString().slice(0,10)}.html`;
  a.click();URL.revokeObjectURL(a.href);
}

function renderStandard(){
  const pane=byId('paneStandard');if(!pane)return;
  const td='padding:8px 10px;border:1px solid #cfdcea';
  const dimRows=RUBRIC.dimensions.map(d=>`<tr data-dim="${esc(d.key)}"><td style="${td}">${esc(d.label)}</td><td style="${td}">${esc(d.weight_percent)}%</td><td style="${td}">${esc(d.description)}</td></tr>`).join('');
  const principles=RUBRIC.principles.map(p=>`<li>${esc(p.title)}：${esc(p.text)}</li>`).join('');
  const dimNames=RUBRIC.dimensions.map(d=>d.label).join('、');
  const formula=RUBRIC.dimensions.map(d=>`${d.label}×${d.weight.toFixed(2)}`).join(' + ');
  pane.innerHTML=`\
<h2 style="font-size:16px;margin-bottom:16px">评分标准说明</h2>
<div class="notice-pilot" style="margin-bottom:16px">试行说明：以下量表为内测期间设计参考，权重与合格线尚待校方基于实际数据确认，不应作为官方验证标准引用或对外传播。</div>
<div class="card" style="margin-bottom:14px" id="stdScoring"><div class="card-body">
  <h3 style="font-size:14px;margin-bottom:8px">计分方式</h3>
  <p style="font-size:13px;line-height:1.8">采用${esc(RUBRIC.scale.max)}分制，${esc(RUBRIC.scale.pass_score)}分为参考合格线（试行）。综合得分由四个维度加权合成，仅在满足最低观察条件且教师已完成复核后生成。</p>
  <table style="margin-top:10px;width:100%;border-collapse:collapse;font-size:13px">
    <thead><tr style="background:#f7fbff"><th style="${td};text-align:left">维度</th><th style="${td};text-align:left">权重（试行）</th><th style="${td};text-align:left">说明</th></tr></thead>
    <tbody>${dimRows}</tbody>
  </table>
  <p style="font-size:12px;color:var(--muted);margin-top:8px" id="stdFormula">综合得分 = ${esc(formula)}，结果保留${esc(RUBRIC.decimals)}位小数。</p>
</div></div>
<div class="card" style="margin-bottom:14px" id="stdPrinciples"><div class="card-body">
  <h3 style="font-size:14px;margin-bottom:8px">评分原则</h3>
  <ul style="font-size:13px;line-height:2;padding-left:20px;margin:0">${principles}</ul>
</div></div>
<div class="card" id="stdMinimum"><div class="card-body">
  <h3 style="font-size:14px;margin-bottom:8px">最低评分条件</h3>
  <ul style="font-size:13px;line-height:2;padding-left:20px;margin:0">
    <li>教师须勾选"已完成复核"，否则不生成综合得分。</li>
    <li>${esc(dimNames)}四个维度都须有有效分数（非空）。</li>
    <li>观察次数至少为${esc(RUBRIC.min_observed)}次（observed &ge; ${esc(RUBRIC.min_observed)}）。</li>
    <li>不满足上述任一条件，系统标注"${esc(EVIDENCE_INSUFFICIENT)}"，不输出得分数字，不使用置信度作为替代。</li>
  </ul>
  <p style="font-size:12px;color:var(--muted);margin-top:10px">如需查看官方相关文献，请联系管理员在后台添加外部链接。</p>
</div></div>`;
}

// Boot
document.querySelectorAll('.view-tab').forEach(btn=>{
  btn.addEventListener('click',()=>switchTab(btn.dataset.tab));
});
byId('logoutBtn').addEventListener('click',async()=>{
  try{await api(API+'/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});}
  finally{window.location.assign('/demo2/login');}
});
byId('accountName').textContent=ACCT.login_alias||ACCT.username||'教师';
loadWorkspace();
"""
    # _document owns the script element; return JavaScript source only.
    return init + rest


def render_measurement(account: Any = None) -> str:
    account_json = _account_payload(account)
    role = (account or {}).get("role", "")
    if role == "company_admin":
        return _document(
            title="测量记录汇总 — RehabAffect",
            body=_admin_body(account_json),
            page_style=_ADMIN_STYLE,
            script="",
        )
    # school_uploader (or unauthenticated — server should have already 401'd)
    return _document(
        title="测量记录 — RehabAffect",
        body=_teacher_body_html(account_json),
        page_style=_MEAS_STYLE,
        script=_teacher_script(account_json),
    )
