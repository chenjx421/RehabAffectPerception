"""Company-admin review of manually entered schools (/demo2/admin/schools).

Teachers whose school is missing from the national directory save it as a
pending manual school. Approving adds it to directory search results;
rejecting only marks it. Neither rewrites any account context or task snapshot.
"""

from __future__ import annotations

import json
from typing import Any

from .demo2_portal import _account_payload, _document
from .demo2_ui_kit import admin_header, empty_state

_TYPES = ("特殊教育学校", "辅读学校", "小学", "初中", "九年一贯制", "中学", "高中", "职校")

_STYLE = r"""
body { background:#fff; }
[hidden] { display:none !important; }
.page-shell { padding-top:24px; }
.page-heading { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; flex-wrap:wrap; margin-bottom:12px; }
.page-heading h1 { margin:0; font-size:22px; }
.page-heading p { margin:6px 0 0; color:#616873; font-size:13px; max-width:720px; line-height:1.7; }
.heading-actions { display:flex; gap:8px; flex-wrap:wrap; }
.review-tabs { margin:12px 0; }
.page-message { min-height:22px; margin:0 0 8px; font-size:13px; color:#616873; }
.page-message.error { color:#a32020; font-weight:700; }
.review-table { width:100%; border-collapse:collapse; table-layout:fixed; }
.review-table th,.review-table td { padding:10px 8px; border-bottom:1px solid #e1e6ec; text-align:left; vertical-align:top; overflow-wrap:anywhere; font-size:13px; }
.review-table th { color:#616873; font-weight:600; font-size:12px; }
.review-table th:nth-child(1) { width:26%; }.review-table th:nth-child(2) { width:20%; }
.review-table th:nth-child(3) { width:16%; }.review-table th:nth-child(4) { width:12%; }
.review-table td strong { display:block; font-size:14px; color:#172b4d; }
.review-table td small { display:block; color:#616873; font-size:12px; margin-top:2px; }
.review-actions { display:grid; gap:6px; }
.review-actions select,.review-actions input { width:100%; min-height:34px; font-size:13px; }
.review-actions .row { display:flex; gap:6px; flex-wrap:wrap; }
.review-actions .button { min-height:34px; padding:4px 10px; font-size:13px; }
.status-pill { display:inline-block; padding:1px 8px; border-radius:8px; font-size:12px; font-weight:700; }
.status-pill.pending { background:#fff5e3; color:#8a4b06; }
.status-pill.approved { background:#e8f6ef; color:#146c4b; }
.status-pill.rejected { background:#fdf1f1; color:#a32020; }
@media (max-width:900px) {
  .review-table thead { display:none; }
  .review-table tr { display:block; border:1px solid #e1e6ec; border-radius:8px; margin-bottom:10px; padding:6px; }
  .review-table td { display:block; border:0; padding:6px; }
}
"""


def render_school_review(account: Any | None = None) -> str:
    body = admin_header("channels", account, page="school_review") + """
<main class="page-shell" id="mainContent">
  <div class="page-heading"><div><h1>学校目录审核</h1><p>老师在全国学校目录中找不到学校时会手动填写（待审核）。通过后该校出现在全国目录搜索结果中；驳回只标记状态，不会修改老师已保存的学校信息和已上传任务的学校快照。</p></div>
  <div class="heading-actions"><a class="button quiet" id="backToChannels" href="/demo2/admin/channels">返回上传通道</a><button class="button" id="refreshSchools" type="button">刷新</button></div></div>
  <div class="rx-tabs review-tabs" role="tablist" aria-label="审核状态">
    <button class="rx-tab" type="button" role="tab" id="tabPending" data-status="pending" aria-selected="true">待审核 <span class="rx-tab-count" id="countPending">0</span></button>
    <button class="rx-tab" type="button" role="tab" id="tabApproved" data-status="approved" aria-selected="false">已通过 <span class="rx-tab-count" id="countApproved">0</span></button>
    <button class="rx-tab" type="button" role="tab" id="tabRejected" data-status="rejected" aria-selected="false">已驳回 <span class="rx-tab-count" id="countRejected">0</span></button>
  </div>
  <p class="page-message" id="pageMessage" role="status" aria-live="polite">正在读取…</p>
  <table class="review-table" id="reviewTable" hidden><thead><tr><th scope="col">学校</th><th scope="col">省市区</th><th scope="col">提交</th><th scope="col">状态</th><th scope="col">审核</th></tr></thead><tbody id="reviewRows"></tbody></table>
  <div id="reviewEmpty" hidden></div>
</main>"""
    script = r"""
const ACCOUNT=__ACCOUNT__;const TYPE_OPTIONS=__TYPES__;const EMPTY=__EMPTY__;
const $=id=>document.getElementById(id);
let status='pending',loading=false;
const STATUS_LABEL={pending:'待审核',approved:'已通过',rejected:'已驳回'};
async function api(url,payload){
  const response=await fetch(url,{credentials:'same-origin',...(payload?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}:{})});
  const data=await response.json().catch(()=>({}));
  if(!response.ok||data.error){const error=new Error(data.error?.message||'服务暂时不可用，请稍后重试');error.status=response.status;error.code=data.error?.code||'';throw error;}
  return data;
}
function message(text,isError){$('pageMessage').textContent=text;$('pageMessage').className='page-message'+(isError?' error':'');}
function cell(text,small){const td=document.createElement('td');const strong=document.createElement('strong');strong.textContent=text;td.append(strong);if(small){const s=document.createElement('small');s.textContent=small;td.append(s);}return td;}
function time(value){return value?(window.RxUI?.formatTime?window.RxUI.formatTime(value):String(value).slice(0,16).replace('T',' ')):'—';}
function render(data){
  for(const [key,id] of [['pending','countPending'],['approved','countApproved'],['rejected','countRejected']])$(id).textContent=String(data.counts?.[key]||0);
  const rows=Array.isArray(data.schools)?data.schools:[];const body=$('reviewRows');body.replaceChildren();
  $('reviewTable').hidden=!rows.length;$('reviewEmpty').hidden=!!rows.length;
  $('reviewEmpty').innerHTML=EMPTY.replace('__TEXT__',status==='pending'?'暂无待审核的学校。':'暂无记录。');
  for(const row of rows){
    const tr=document.createElement('tr');
    tr.append(cell(row.school_name,row.school_type?'类型：'+row.school_type:''),cell([row.province,row.city,row.district].filter((v,i,a)=>v&&a.indexOf(v)===i).join(' / ')),
      cell(row.submitted_by||'—',time(row.submitted_at)));
    const st=document.createElement('td');const pill=document.createElement('span');pill.className='status-pill '+row.status;pill.textContent=STATUS_LABEL[row.status]||row.status;st.append(pill);
    if(row.reviewed_at){const s=document.createElement('small');s.textContent=(row.reviewed_by||'')+' · '+time(row.reviewed_at)+(row.review_note?' · '+row.review_note:'');st.append(s);}
    tr.append(st);
    const actions=document.createElement('td');
    if(row.status==='pending'){
      const box=document.createElement('div');box.className='review-actions';
      const type=document.createElement('select');type.setAttribute('aria-label','学校类型');type.add(new Option('选择学校类型（通过时必选）',''));TYPE_OPTIONS.forEach(t=>type.add(new Option(t,t)));
      const note=document.createElement('input');note.maxLength=200;note.placeholder='驳回原因（驳回时必填）';note.setAttribute('aria-label','审核说明');
      const line=document.createElement('div');line.className='row';
      const ok=document.createElement('button');ok.type='button';ok.className='button primary';ok.textContent='通过并归入目录';
      const no=document.createElement('button');no.type='button';no.className='button quiet';no.textContent='驳回';
      ok.addEventListener('click',()=>{if(!type.value){message('通过前请选择学校类型',true);type.focus();return;}review(row,'approve',type.value,note.value.trim());});
      no.addEventListener('click',()=>{if(!note.value.trim()){message('驳回时请填写原因',true);note.focus();return;}review(row,'reject','',note.value.trim());});
      line.append(ok,no);box.append(type,note,line);actions.append(box);
    }else{actions.textContent='—';}
    tr.append(actions);body.append(tr);
  }
}
async function load(){
  if(loading)return;loading=true;message('正在读取…');
  try{const data=await api('/api/v1/demo2/admin/schools?status='+encodeURIComponent(status));render(data);message(data.schools?.length?'共 '+data.schools.length+' 条':'');}
  catch(error){message(error.message+(error.code?'（'+error.code+'）':''),true);}
  finally{loading=false;}
}
async function review(row,decision,schoolType,note){
  try{
    const payload={school_code:row.school_code,decision,expected_version:row.version,review_note:note};
    if(schoolType)payload.school_type=schoolType;
    await api('/api/v1/demo2/admin/schools/review',payload);
    window.RxUI?.toast?.(decision==='approve'?'已通过：'+row.school_name:'已驳回：'+row.school_name,'success',3200);
    await load();
  }catch(error){message(error.message+(error.code?'（'+error.code+'）':''),true);if(error.status===409)load();}
}
for(const tab of document.querySelectorAll('.rx-tab[data-status]'))tab.addEventListener('click',()=>{status=tab.dataset.status;for(const t of document.querySelectorAll('.rx-tab[data-status]'))t.setAttribute('aria-selected',String(t===tab));load();});
$('refreshSchools').addEventListener('click',load);
if(ACCOUNT.role==='company_admin')load();else message('当前账号不是公司管理员，不能审核学校。',true);
""".replace("__ACCOUNT__", _account_payload(account)).replace("__TYPES__", json.dumps(list(_TYPES), ensure_ascii=False))
    empty_template = json.dumps(empty_state("__TEXT__", compact=True), ensure_ascii=False).replace("</", "<\\/")
    script = script.replace("__EMPTY__", empty_template)
    return _document(title="学校目录审核", body=body, page_style=_STYLE, script=script)
