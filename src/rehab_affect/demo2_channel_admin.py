"""Company-admin channel settings backed exclusively by the protected API."""

from __future__ import annotations

import json
from typing import Any

from .demo2_portal import _BOOK_ICON, _account_payload, _document


# Lucide SlidersHorizontal and ArrowLeft geometry, consistent with portal icons.
_SETTINGS_ICON = '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M21 4h-7M10 4H3M21 12h-9M8 12H3M21 20h-5M12 20H3M14 2v4M8 10v4M16 18v4"/></svg>'
_BACK_ICON = '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="m12 19-7-7 7-7M5 12h14"/></svg>'

_STYLE = r"""
:root { --canvas:#fff; --blue:#2163C4; --blue-deep:#214e87; --ink:#30343b; --muted:#616873; --line:#e1e6ec; --shadow:none; }
body { background:#fff; font-family:"Segoe UI","Microsoft YaHei",sans-serif; font-size:15px; }
*,*::before,*::after { letter-spacing:0; }
[hidden] { display:none !important; }
.header-inner { min-height:64px; }
.page-shell { padding-top:24px; }
.page-heading { align-items:center; gap:12px; margin-bottom:16px; }
h1 { font-size:24px; } h2 { font-size:18px; }
.page-heading p,.scope-note { color:var(--muted); font-size:13px; }
.scope-note { padding:12px 0 18px; border-bottom:1px solid var(--line); }
.channel-layout { display:grid; grid-template-columns:minmax(0,1fr); gap:28px; align-items:start; margin-top:20px; }
.channel-layout:has(.settings-panel:not([hidden])) { grid-template-columns:minmax(0,1fr) 340px; }
.channel-list { min-width:0; }
.channel-list-head { display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:10px; }
.channel-list-head span { font-size:12px; color:var(--muted); }
.channel-table { width:100%; min-width:0; table-layout:fixed; }
.channel-table th,.channel-table td { padding:12px 8px; overflow-wrap:anywhere; vertical-align:middle; }
.channel-table th:first-child { width:27%; }.channel-table th:nth-child(2) { width:22%; }
.channel-table th:nth-child(3) { width:20%; }.channel-table th:nth-child(4) { width:13%; }
.channel-table th:last-child { width:18%; }
.channel-table td strong { font-size:14px; font-weight:600; }
.channel-table tr[aria-selected=true] { background:#f4f8fe; }
.settings-button { padding:6px 8px; font-size:13px; gap:5px; white-space:nowrap; }
.settings-button svg { width:16px; height:16px; }
.settings-panel { min-width:0; border-left:1px solid var(--line); padding-left:24px; }
.settings-panel h2 { margin-bottom:6px; }
.settings-form { display:grid; gap:16px; margin-top:18px; }
.settings-form .field label { font-size:13px; }
.settings-form input,.settings-form select { font-size:14px; }
.form-actions { display:flex; gap:10px; flex-wrap:wrap; }
.form-status { min-height:24px; font-size:13px; color:var(--muted); overflow-wrap:anywhere; }
.form-status.success { color:var(--success); }.form-status.error { color:var(--danger); }
.form-status.pending { color:var(--warning); }
.scope-note strong { color:var(--ink); font-weight:600; }
.comparison { margin-top:18px; padding-top:16px; border-top:1px solid var(--line); }
.comparison h3 { font-size:14px; }
.comparison p { margin:8px 0; font-size:13px; color:var(--muted); }
.comparison dl { margin:12px 0; font-size:13px; }
.comparison dt { font-weight:600; margin-top:10px; }
.comparison dd { margin:3px 0; color:var(--muted); overflow-wrap:anywhere; }
.comparison .button { width:100%; font-size:13px; }
.channel-list .empty-state { border:0; background:#f7f9fc; font-size:14px; }
.page-message { margin-bottom:18px; }
@media (max-width:1000px) {
  .channel-layout:has(.settings-panel:not([hidden])) { grid-template-columns:minmax(0,1fr); }
  .settings-panel { border-left:0; border-top:1px solid var(--line); padding:20px 0 0; max-width:580px; width:100%; }
}
@media (max-width:680px) {
  .site-header { position:static; }
  .page-heading { align-items:flex-start; } h1 { font-size:22px; }
  .channel-table thead { display:none; }
  .channel-table,.channel-table tbody { display:block; }
  .channel-table tbody tr { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1fr); gap:6px 12px; padding:14px 0; border-bottom:1px solid var(--line); }
  .channel-table td { display:block; border:0; padding:2px 0; min-width:0; }
  .channel-table td:first-child { grid-column:1/-1; }
  .channel-table td::before { content:attr(data-label); display:block; margin-bottom:3px; font-size:12px; color:var(--muted); }
  .channel-table td:last-child { align-self:end; }
  .header-actions .button { width:auto; flex:0 1 auto; }
}
"""


def render_channel_admin(account: Any | None = None) -> str:
    body = r"""
<header class="site-header"><div class="header-inner"><a class="brand" href="/demo2/admin">__BOOK__<span class="brand-copy"><strong>RehabAffect</strong><span>公司管理后台</span></span></a><div class="header-actions"><a class="button quiet" href="/demo2/admin">__BACK__返回概览</a></div></div></header>
<main class="page-shell" id="mainContent">
  <div class="page-heading"><div><h1>上传通道设置</h1><p id="roleNotice">仅公司管理员可修改通道配置。</p></div><button class="button" id="refreshChannels" type="button">刷新通道</button></div>
  <p class="scope-note"><strong>暂停新建上传</strong>仅影响新建上传；历史视频和已开始任务不受影响。每课程名额按绑定账号执行。</p>
  <div class="page-message" id="pageMessage" role="alert"></div>
  <div class="channel-layout">
    <section class="channel-list" aria-labelledby="channelsTitle"><div class="channel-list-head"><h2 id="channelsTitle">上传通道</h2><span id="channelCount" role="status">尚未读取</span></div>
      <table class="channel-table" id="channelTable" aria-labelledby="channelsTitle" hidden><thead><tr><th scope="col">通道名称</th><th scope="col">负责人</th><th scope="col">状态</th><th scope="col">名额 / 课程</th><th scope="col">操作</th></tr></thead><tbody id="channelRows"></tbody></table>
      <div class="empty-state" id="channelsEmpty">正在读取通道配置</div>
    </section>
    <section class="settings-panel" id="settingsPanel" aria-labelledby="settingsTitle" hidden>
      <h2 id="settingsTitle" tabindex="-1">通道设置</h2><p class="form-status" id="formStatus" role="status" aria-live="polite">尚未修改</p>
      <form class="settings-form" id="channelForm">
        <div class="field"><label for="channelName">通道名称</label><input id="channelName" required maxlength="120" autocomplete="off" /></div>
        <div class="field"><label for="ownerLabel">负责人</label><input id="ownerLabel" maxlength="120" autocomplete="off" /></div>
        <div class="field"><label for="channelStatus">上传状态</label><select id="channelStatus"><option value="active">启用新建上传</option><option value="paused">暂停新建上传</option></select></div>
        <div class="field"><label for="courseUploadLimit">每课程上传名额</label><select id="courseUploadLimit"><option value="3">3 个</option><option value="4">4 个</option><option value="5">5 个</option></select></div>
        <div class="form-actions"><button class="button primary" id="saveChannel" type="submit" disabled>保存设置</button><button class="button" id="cancelEdit" type="button">取消</button></div>
      </form>
      <section class="comparison" id="comparison" aria-labelledby="comparisonTitle" hidden><h3 id="comparisonTitle">重新核对配置</h3><p id="comparisonNotice"></p><dl id="comparisonValues"></dl><button class="button" id="readBeforeRetry" type="button">重新读取核对</button><button class="button" id="acceptComparison" type="button" hidden>已核对，保留我的修改</button></section>
    </section>
  </div>
</main>
""".replace("__BOOK__", _BOOK_ICON).replace("__BACK__", _BACK_ICON)
    script = r"""
const ACCOUNT=__ACCOUNT__,SETTINGS_ICON=__SETTINGS_ICON__;
const API='/api/v1/demo2/admin/channels';
const $=id=>document.getElementById(id);
const isAdmin=ACCOUNT.role==='company_admin';
const fields=['channel_name','owner_label','status','course_upload_limit'];
const labels={channel_name:'通道名称',owner_label:'负责人',status:'上传状态',course_upload_limit:'每课程名额'};
let rows=null,selectedId='',baseline=null,loading=false,saving=false,denied=false,readFailed=false,pending=null;
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const statusText=value=>value==='active'?'启用新建上传':value==='paused'?'暂停新建上传':'状态未确认';
const display=(key,value)=>key==='status'?statusText(value):key==='course_upload_limit'?value+' 个':value||'未填写';
const same=(a,b)=>fields.every(key=>a?.[key]===b?.[key]);
function values(){return {channel_name:$('channelName').value.trim(),owner_label:$('ownerLabel').value.trim(),status:$('channelStatus').value,course_upload_limit:Number($('courseUploadLimit').value)};}
function fill(row){$('channelName').value=row.channel_name;$('ownerLabel').value=row.owner_label;$('channelStatus').value=row.status;$('courseUploadLimit').value=String(row.course_upload_limit);}
function validRow(row){return row&&typeof row.channel_id==='string'&&row.channel_id.length>0&&typeof row.channel_name==='string'&&row.channel_name.trim()&&typeof row.owner_label==='string'&&['active','paused'].includes(row.status)&&[3,4,5].includes(row.course_upload_limit)&&((Number.isInteger(row.version)&&row.version>=0)||(typeof row.version==='string'&&row.version.length>0));}
function tell(text,kind='error'){$('pageMessage').textContent=text;$('pageMessage').className='page-message visible '+kind;}
function formState(text,kind=''){$('formStatus').textContent=text;$('formStatus').className='form-status '+kind;}
function controls(){
  const busy=loading||saving,blocked=!isAdmin||denied||readFailed;
  ['channelName','ownerLabel','channelStatus','courseUploadLimit'].forEach(id=>$(id).disabled=busy||blocked||!!pending);
  $('saveChannel').disabled=busy||blocked||!!pending||!baseline||same(values(),baseline)||!values().channel_name;
  $('saveChannel').textContent=saving?'保存中…':'保存设置';
  $('cancelEdit').disabled=busy;
  $('refreshChannels').disabled=busy||!isAdmin;
  $('readBeforeRetry').disabled=busy||!isAdmin;
  $('acceptComparison').disabled=busy||blocked||!pending?.latest;
  $('channelRows').querySelectorAll('[data-setting]').forEach(button=>button.disabled=busy||blocked||!!pending&&rows[Number(button.dataset.setting)]?.channel_id!==pending.id);
}
function renderRows(){
  $('channelTable').hidden=!rows?.length;$('channelsEmpty').hidden=!!rows?.length;
  $('channelCount').textContent=rows?rows.length+' 个通道'+(readFailed?' · 上次读取':''):'尚未取得配置';
  $('channelsEmpty').textContent=denied?'当前账号无权查看通道配置。':readFailed?'通道配置读取失败，请刷新重试。':rows?'接口未返回可管理的通道。':'正在读取通道配置';
  $('channelRows').innerHTML=(rows||[]).map((row,index)=>'<tr aria-selected="'+(row.channel_id===selectedId)+'"><td data-label="通道名称"><strong>'+esc(row.channel_name)+'</strong></td><td data-label="负责人">'+esc(row.owner_label||'未填写')+'</td><td data-label="状态"><span class="status-badge '+(row.status==='active'?'success':'warning')+'">'+statusText(row.status)+'</span></td><td data-label="名额 / 课程">'+row.course_upload_limit+' 个</td><td><button class="button quiet settings-button" type="button" data-setting="'+index+'" aria-label="设置 '+esc(row.channel_name)+'">'+SETTINGS_ICON+'设置</button></td></tr>').join('');
  controls();
}
async function api(method='GET',payload){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000);
  try{
    const response=await fetch(API,{method,credentials:'same-origin',signal:controller.signal,...(payload?{headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}:{})});
    const data=await response.json().catch(()=>null);
    if(!response.ok||data?.ok!==true){
      const serverMessage=typeof data?.error?.message==='string'?data.error.message.trim():'';
      const error=new Error(({401:'登录已过期，请重新登录。',403:'当前账号没有公司管理员权限。'}[response.status])||serverMessage||(response.status===409?'配置已被其他管理员修改，请刷新重新核对。':'请求未能确认，请重新读取配置。'));
      error.status=response.status;error.code=data?.error?.code;throw error;
    }
    return data;
  }catch(error){if(error.name==='AbortError')throw new Error('请求超时，结果尚未确认。');if(error instanceof TypeError)throw new Error('网络连接失败，结果尚未确认。');throw error;}finally{clearTimeout(timer);}
}
function revoke(error){
  if(![401,403].includes(error.status))return false;
  denied=true;rows=null;baseline=null;selectedId='';pending=null;$('settingsPanel').hidden=true;renderRows();
  $('roleNotice').textContent=error.message;
  tell(error.message);return true;
}
function showComparison(){
  $('comparison').hidden=!pending;
  if(!pending)return;
  $('readBeforeRetry').hidden=false;$('acceptComparison').hidden=!pending.latest;
  $('comparisonNotice').textContent=pending.latest?'服务器当前配置与本次修改不同。请核对后决定是否保留修改；不会自动再次提交。':'保存结果尚未核对，重新读取前不能再次保存。';
  $('comparisonValues').innerHTML=pending.latest?fields.filter(key=>pending.latest[key]!==pending.draft[key]).map(key=>'<dt>'+labels[key]+'</dt><dd>服务器当前：'+esc(display(key,pending.latest[key]))+'</dd><dd>本次修改：'+esc(display(key,pending.draft[key]))+'</dd>').join(''):'';
}
function openSettings(index){
  const row=rows?.[index];if(!row||loading||saving||denied||readFailed||!isAdmin||pending&&pending.id!==row.channel_id)return;
  if(selectedId===row.channel_id&&!$('settingsPanel').hidden){$('settingsTitle').focus();return;}
  if(baseline&&!same(values(),baseline)&&!pending&&selectedId!==row.channel_id&&!window.confirm('切换通道将放弃未保存修改，继续吗？'))return;
  selectedId=row.channel_id;baseline=row;fill(pending?.draft||row);
  $('settingsPanel').hidden=false;$('settingsTitle').textContent='设置 '+row.channel_name;
  formState(pending?'请重新核对后再保存':'尚未修改',pending?'pending':'');
  showComparison();renderRows();$('settingsTitle').focus();
}
function reconcile(){
  if(!pending)return;
  const latest=rows.find(row=>row.channel_id===pending.id);
  if(!latest){formState('原通道已不在本次返回列表中，不能再次保存。','error');pending.latest=null;showComparison();return;}
  if(same(latest,pending.draft)){
    if(selectedId===pending.id){baseline=latest;fill(latest);}
    const text=pending.kind==='saved'?'保存成功，已重新读取确认。':'重新读取的配置已与本次修改一致，无需重复保存。';
    pending=null;showComparison();formState(text,'success');tell(text,'success');
  }else{
    pending.latest=latest;if(selectedId===pending.id)baseline=latest;
    formState('配置不同，请核对后再保存。','pending');showComparison();
    tell('已读取最新配置，请在设置面板核对差异；没有再次提交。','info');
  }
}
async function reload({afterSave=false}={}){
  if(!isAdmin||loading||saving)return;
  if(baseline&&!pending&&!same(values(),baseline)&&!window.confirm('重新读取将放弃未保存修改，继续吗？'))return;
  loading=true;controls();tell(afterSave?'保存请求已受理，正在重新读取确认。':'正在读取通道配置。','info');
  try{
    const data=await api();
    if(!Array.isArray(data.channels)||!data.channels.every(validRow)||new Set(data.channels.map(row=>row.channel_id)).size!==data.channels.length)throw new Error('接口未返回完整通道配置，请重新读取。');
    rows=data.channels;denied=false;readFailed=false;$('roleNotice').textContent='仅公司管理员可修改通道配置。';
    tell('已读取最新通道配置。','success');
    if(pending)reconcile();
    else if(selectedId){baseline=rows.find(row=>row.channel_id===selectedId)||null;if(baseline){fill(baseline);formState('已读取最新配置');}else{$('settingsPanel').hidden=true;selectedId='';}}
  }catch(error){
    readFailed=true;if(!revoke(error)){tell(error.message+(rows?' 已保留上次读取的配置，不能据此确认本次保存结果。':''));if(pending){pending.latest=null;showComparison();formState('保存结果未确认，请重新读取核对。','error');}}
  }finally{loading=false;renderRows();}
}
async function save(event){
  event.preventDefault();if($('saveChannel').disabled||!baseline||pending||!isAdmin)return;
  const draft=values();if(!draft.channel_name||!['active','paused'].includes(draft.status)||![3,4,5].includes(draft.course_upload_limit))return;
  saving=true;controls();formState('保存中…');
  const attempt={id:baseline.channel_id,draft,latest:null,kind:'uncertain'};
  let accepted=false;
  try{
    const data=await api('POST',{channel_id:baseline.channel_id,expected_version:baseline.version,...draft});
    if(!validRow(data.channel)||data.channel.channel_id!==baseline.channel_id)throw new Error('保存响应未能确认本通道，请重新读取。');
    attempt.kind='saved';pending=attempt;accepted=true;formState('正在重新读取确认');
  }catch(error){
    if(!revoke(error)){
      if(error.status===409&&error.code!=='channel_quota_in_use'){attempt.kind='conflict';pending=attempt;}
      else if(!error.status||error.status>=500||(error.status>=200&&error.status<300))pending=attempt;
      formState(error.message,'error');tell(error.message);
    }
  }finally{saving=false;showComparison();controls();}
  if(accepted)await reload({afterSave:true});
}
$('channelRows').addEventListener('click',event=>{const button=event.target.closest('[data-setting]');if(button&&!button.disabled)openSettings(Number(button.dataset.setting));});
$('channelForm').addEventListener('input',()=>{if(!pending&&!saving&&!loading)formState(same(values(),baseline)?'尚未修改':'待保存',same(values(),baseline)?'':'pending');controls();});
$('channelForm').addEventListener('change',()=>{if(!pending&&!saving&&!loading)formState(same(values(),baseline)?'尚未修改':'待保存',same(values(),baseline)?'':'pending');controls();});
$('channelForm').addEventListener('submit',save);
$('cancelEdit').addEventListener('click',()=>{if(saving||loading)return;const previous=selectedId;selectedId='';baseline=null;$('settingsPanel').hidden=true;renderRows();const index=rows?.findIndex(row=>row.channel_id===previous);$('channelRows').querySelector('[data-setting="'+index+'"]')?.focus();});
$('refreshChannels').addEventListener('click',()=>reload());
$('readBeforeRetry').addEventListener('click',()=>reload());
$('acceptComparison').addEventListener('click',()=>{if(!pending?.latest||loading||saving||denied||readFailed)return;baseline=pending.latest;fill(pending.draft);pending=null;showComparison();formState(same(values(),baseline)?'无需修改':'待保存','pending');controls();});
window.addEventListener('beforeunload',event=>{if(pending||saving||baseline&&!same(values(),baseline)){event.preventDefault();event.returnValue='';}});
if(isAdmin)reload();else{denied=true;readFailed=true;$('roleNotice').textContent='当前账号不是公司管理员，不能查看或修改通道配置。';tell($('roleNotice').textContent);renderRows();}
""".replace("__ACCOUNT__", _account_payload(account))
    script = script.replace("__SETTINGS_ICON__", json.dumps(_SETTINGS_ICON))
    return _document(title="上传通道设置 · RehabAffect 公司后台", body=body, page_style=_STYLE, script=script)


render_demo2_channel_admin_html = render_channel_admin
render_channels = render_channel_admin
