"""Company-admin channel settings backed exclusively by the protected API."""

from __future__ import annotations

import json
from typing import Any

from .demo2_portal import _account_payload, _document
from .demo2_ui_kit import admin_header, drawer, empty_state, kpi


# Lucide SlidersHorizontal and ArrowLeft geometry, consistent with portal icons.
_SETTINGS_ICON = '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M21 4h-7M10 4H3M21 12h-9M8 12H3M21 20h-5M12 20H3M14 2v4M8 10v4M16 18v4"/></svg>'

_STYLE = r"""
:root { --canvas:#fff; --blue:#2163C4; --blue-deep:#214e87; --ink:#30343b; --muted:#616873; --line:#e1e6ec; --shadow:none; }
body { background:#fff; font-family:"Segoe UI","Microsoft YaHei",sans-serif; font-size:15px; }
*,*::before,*::after { letter-spacing:0; }
[hidden] { display:none !important; }
.header-inner { min-height:64px; }
.page-shell { padding-top:24px; }
.page-heading { align-items:center; gap:12px; margin-bottom:16px; }
.heading-actions { display:flex; gap:8px; flex-wrap:wrap; }
h1 { font-size:24px; } h2 { font-size:18px; }
.page-heading p,.scope-note { color:var(--muted); font-size:13px; }
.scope-note { padding:12px 0 18px; border-bottom:1px solid var(--line); }
.scope-note strong { color:var(--ink); font-weight:600; }
.channel-kpis { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; margin:18px 0 4px; }
.channel-kpis .rx-kpi-value { color:var(--blue-deep); }
.channel-layout { margin-top:20px; }
.channel-list { min-width:0; }
.channel-list-head { display:flex; justify-content:space-between; align-items:center; gap:12px; margin-bottom:10px; }
.channel-list-head span { font-size:12px; color:var(--muted); }
.channel-table { width:100%; min-width:0; table-layout:fixed; }
.channel-table th,.channel-table td { padding:12px 8px; overflow-wrap:anywhere; vertical-align:middle; }
.channel-table th:first-child { width:27%; }.channel-table th:nth-child(2) { width:22%; }
.channel-table th:nth-child(3) { width:20%; }.channel-table th:nth-child(4) { width:13%; }
.channel-table th:last-child { width:18%; }
.channel-table td strong { display:block; font-size:14px; font-weight:600; }
.channel-table td small { display:block; margin-top:2px; color:var(--muted); font-size:12px; }
.channel-table tr[aria-selected=true] { background:#f4f8fe; }
.owner-unset { color:#8a94a3; }
.settings-button { padding:6px 8px; font-size:13px; gap:5px; white-space:nowrap; }
.settings-button svg { width:16px; height:16px; }
.settings-form { display:grid; gap:16px; margin-top:14px; }
.settings-form .field label { font-size:13px; }
.settings-form input,.settings-form select { font-size:14px; }
.settings-form .field-help { display:block; margin-top:4px; color:var(--muted); font-size:12px; }
.settings-form .field-error { margin:4px 0 0; color:var(--danger); font-size:12px; font-weight:700; }
.settings-form .field.has-error input { border-color:var(--danger); }
.form-actions { display:flex; gap:10px; flex-wrap:wrap; }
.form-status { min-height:24px; margin:0; font-size:13px; color:var(--muted); overflow-wrap:anywhere; }
.form-status.success { color:var(--success); }.form-status.error { color:var(--danger); }
.form-status.pending { color:var(--warning); }
.comparison { margin-top:18px; padding:14px; border:1px solid #ecc98e; border-radius:8px; background:#fff8ec; }
.comparison h3 { font-size:14px; }
.comparison p { margin:8px 0; font-size:13px; color:var(--ink); }
.comparison dl { margin:12px 0; font-size:13px; }
.comparison dt { font-weight:600; margin-top:10px; }
.comparison dd { margin:3px 0; color:var(--muted); overflow-wrap:anywhere; }
.comparison .button { width:100%; font-size:13px; margin-top:8px; }
.channel-list .empty-state { border:0; background:#f7f9fc; font-size:14px; }
.page-message { margin-bottom:18px; }
@media (max-width:680px) {
  .site-header { position:static; }
  .page-heading { align-items:flex-start; } h1 { font-size:22px; }
  .channel-kpis { grid-template-columns:minmax(0,1fr); }
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

_DRAWER_BODY = """<p class="form-status" id="formStatus" role="status" aria-live="polite">尚未修改</p>
      <form class="settings-form" id="channelForm" novalidate>
        <div class="field"><label for="channelName">通道名称</label><input id="channelName" required maxlength="120" autocomplete="off" /><small class="field-help">学校老师在上传页看到的通道名称。</small></div>
        <div class="field"><label for="ownerLabel">负责人</label><input id="ownerLabel" maxlength="120" autocomplete="off" placeholder="例如：教务处 王老师（可留空）" /><small class="field-help">留空时列表显示「未设置」。</small></div>
        <div class="field"><label for="channelStatus">开放状态</label><select id="channelStatus"><option value="active">开放上传</option><option value="paused">已暂停（仅停止新建上传）</option></select><small class="field-help">暂停后不会把账号换到其他通道；历史视频和已开始任务不受影响。</small></div>
        <div class="field" id="limitField"><label for="courseUploadLimit">每课程上传名额</label><input id="courseUploadLimit" type="number" inputmode="numeric" min="3" max="5" step="1" required aria-describedby="limitHelp limitError" /><small class="field-help" id="limitHelp">可填 3~5 个，同一课程最多上传这么多段视频。</small><p class="field-error" id="limitError" role="alert" hidden></p></div>
        <div class="form-actions"><button class="button primary" id="saveChannel" type="submit" disabled>保存设置</button><button class="button" id="cancelEdit" type="button">取消</button></div>
      </form>
      <section class="comparison" id="comparison" aria-labelledby="comparisonTitle" hidden><h3 id="comparisonTitle">重新核对配置</h3><p id="comparisonNotice"></p><dl id="comparisonValues"></dl><button class="button" id="readBeforeRetry" type="button">重新读取核对</button><button class="button" id="acceptComparison" type="button" hidden>已核对，保留我的修改</button></section>"""


def render_channel_admin(account: Any | None = None) -> str:
    kpis = "".join((
        kpi("上传通道", "--", hint="每个学校账号绑定一个通道", value_id="kpiChannelTotal"),
        kpi("开放上传", "--", hint="老师可以新建上传", value_id="kpiChannelActive", tone="success"),
        kpi("已暂停", "--", hint="只停止新建上传，不删除历史任务", value_id="kpiChannelPaused", tone="warning"),
    ))
    settings_drawer = drawer(_DRAWER_BODY, title="通道设置", element_id="settingsPanel", title_id="settingsTitle",
                             subtitle="修改后会重新读取服务器数据确认保存结果。", close_id="closeDrawer")
    body = r"""
__RX_HEADER__
<main class="page-shell" id="mainContent">
  <div class="page-heading"><div><h1>上传通道设置</h1><p id="roleNotice">仅公司管理员可修改通道配置。</p></div><div class="heading-actions"><a class="button quiet" id="schoolReviewLink" href="/demo2/admin/schools">学校目录审核</a><button class="button" id="refreshChannels" type="button">刷新通道</button></div></div>
  <p class="scope-note"><strong>暂停新建上传</strong>仅影响新建上传；历史视频和已开始任务不受影响。每课程名额按绑定账号执行，可设置 3~5 个。</p>
  <div class="page-message" id="pageMessage" role="alert"></div>
  <section class="channel-kpis" aria-label="通道概况">__KPIS__</section>
  <div class="channel-layout">
    <section class="channel-list" aria-labelledby="channelsTitle"><div class="channel-list-head"><h2 id="channelsTitle">上传通道</h2><span id="channelCount" role="status">尚未读取</span></div>
      <table class="channel-table" id="channelTable" aria-labelledby="channelsTitle" hidden><thead><tr><th scope="col">通道名称</th><th scope="col">负责人</th><th scope="col">状态</th><th scope="col">名额 / 课程</th><th scope="col">操作</th></tr></thead><tbody id="channelRows"></tbody></table>
      <div class="empty-state" id="channelsEmpty">正在读取通道配置</div>
    </section>
  </div>
  __DRAWER__
</main>
""".replace("__RX_HEADER__", admin_header("channels", account, logout_bound=False, page="admin_channels"))
    body = body.replace("__KPIS__", kpis).replace("__DRAWER__", settings_drawer)
    script = r"""
const ACCOUNT=__ACCOUNT__,SETTINGS_ICON=__SETTINGS_ICON__,EMPTY_TEMPLATE=__EMPTY__;
const API='/api/v1/demo2/admin/channels';
const $=id=>document.getElementById(id);
const isAdmin=ACCOUNT.role==='company_admin';
const fields=['channel_name','owner_label','status','course_upload_limit'];
const labels={channel_name:'通道名称',owner_label:'负责人',status:'开放状态',course_upload_limit:'每课程名额'};
const CONFLICT_TEXT='数据已被他人修改，已为你刷新最新值';
let rows=null,selectedId='',baseline=null,loading=false,saving=false,denied=false,readFailed=false,pending=null;
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const statusText=value=>value==='active'?'开放上传':value==='paused'?'已暂停':'状态未确认';
const display=(key,value)=>key==='status'?statusText(value):key==='course_upload_limit'?value+' 个':value||'未设置';
const same=(a,b)=>fields.every(key=>a?.[key]===b?.[key]);
const validLimit=value=>Number.isInteger(value)&&value>=3&&value<=5;
function limitValue(){const raw=String($('courseUploadLimit').value??'').trim();return raw===''?NaN:Number(raw);}
function values(){return {channel_name:$('channelName').value.trim(),owner_label:$('ownerLabel').value.trim(),status:$('channelStatus').value,course_upload_limit:limitValue()};}
function fill(row){$('channelName').value=row.channel_name;$('ownerLabel').value=row.owner_label;$('channelStatus').value=row.status;$('courseUploadLimit').value=String(row.course_upload_limit);limitCheck();}
function validRow(row){return row&&typeof row.channel_id==='string'&&row.channel_id.length>0&&typeof row.channel_name==='string'&&row.channel_name.trim()&&typeof row.owner_label==='string'&&['active','paused'].includes(row.status)&&[3,4,5].includes(row.course_upload_limit)&&((Number.isInteger(row.version)&&row.version>=0)||(typeof row.version==='string'&&row.version.length>0));}
function tell(text,kind='error'){$('pageMessage').textContent=text;$('pageMessage').className='page-message visible '+kind;}
function formState(text,kind=''){$('formStatus').textContent=text;$('formStatus').className='form-status '+kind;}
// Out-of-range quotas never reach the server from this page; the server still rejects them independently.
function limitCheck(){
  const raw=String($('courseUploadLimit').value??'').trim(),value=limitValue();
  const message=raw===''?'请填写每课程上传名额（3~5 个）。':validLimit(value)?'':'每课程上传名额只能是 3、4 或 5 个，请重新填写。';
  $('limitError').textContent=message;$('limitError').hidden=!message;
  $('limitField').className='field'+(message?' has-error':'');
  if(message)$('courseUploadLimit').setAttribute('aria-invalid','true');else $('courseUploadLimit').removeAttribute('aria-invalid');
  return !message;
}
function controls(){
  const busy=loading||saving,blocked=!isAdmin||denied||readFailed,draft=values();
  ['channelName','ownerLabel','channelStatus','courseUploadLimit'].forEach(id=>$(id).disabled=busy||blocked||!!pending);
  $('saveChannel').disabled=busy||blocked||!!pending||!baseline||same(draft,baseline)||!draft.channel_name||!validLimit(draft.course_upload_limit);
  $('saveChannel').textContent=saving?'保存中…':'保存设置';
  $('cancelEdit').disabled=busy;$('closeDrawer').disabled=busy;
  $('refreshChannels').disabled=busy||!isAdmin;
  $('readBeforeRetry').disabled=busy||!isAdmin;
  $('acceptComparison').disabled=busy||blocked||!pending?.latest;
  $('channelRows').querySelectorAll('[data-setting]').forEach(button=>button.disabled=busy||blocked||!!pending&&rows[Number(button.dataset.setting)]?.channel_id!==pending.id);
}
function renderKpis(){
  const list=rows||[];
  $('kpiChannelTotal').textContent=rows?String(list.length):'--';
  $('kpiChannelActive').textContent=rows?String(list.filter(row=>row.status==='active').length):'--';
  $('kpiChannelPaused').textContent=rows?String(list.filter(row=>row.status==='paused').length):'--';
}
function ownerCell(row){return row.owner_label?esc(row.owner_label):'<span class="owner-unset">未设置</span>';}
function taskNote(row){return Number.isInteger(row.active_task_count)?'<small>'+row.active_task_count+' 个有效任务</small>':'';}
function renderRows(){
  $('channelTable').hidden=!rows?.length;$('channelsEmpty').hidden=!!rows?.length;
  $('channelCount').textContent=rows?rows.length+' 个通道'+(readFailed?' · 上次读取':''):'尚未取得配置';
  const emptyText=denied?'当前账号无权查看通道配置。':readFailed?'通道配置读取失败，请刷新重试。':rows?'还没有可管理的上传通道。':'正在读取通道配置';
  $('channelsEmpty').textContent=emptyText;
  if(rows&&!rows.length&&!denied&&!readFailed)$('channelsEmpty').innerHTML=EMPTY_TEMPLATE.replace('__TEXT__',esc(emptyText));
  $('channelRows').innerHTML=(rows||[]).map((row,index)=>'<tr aria-selected="'+(row.channel_id===selectedId)+'"><td data-label="通道名称"><strong>'+esc(row.channel_name)+'</strong>'+taskNote(row)+'</td><td data-label="负责人">'+ownerCell(row)+'</td><td data-label="状态"><span class="status-badge '+(row.status==='active'?'success':'warning')+'">'+statusText(row.status)+'</span></td><td data-label="名额 / 课程">'+row.course_upload_limit+' 个</td><td><button class="button quiet settings-button" type="button" data-setting="'+index+'" aria-label="设置 '+esc(row.channel_name)+'">'+SETTINGS_ICON+'设置</button></td></tr>').join('');
  renderKpis();controls();
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
function setDrawer(open){$('settingsPanel').hidden=!open;$('settingsPanelBackdrop').hidden=!open;}
function revoke(error){
  if(![401,403].includes(error.status))return false;
  denied=true;rows=null;baseline=null;selectedId='';pending=null;setDrawer(false);renderRows();
  $('roleNotice').textContent=error.message;
  tell(error.message);return true;
}
function showComparison(){
  $('comparison').hidden=!pending;
  if(!pending)return;
  $('readBeforeRetry').hidden=false;$('acceptComparison').hidden=!pending.latest;
  const conflict=pending.kind==='conflict'&&pending.latest;
  $('comparisonTitle').textContent=conflict?'数据已被他人修改':'重新核对配置';
  $('comparisonNotice').textContent=conflict?CONFLICT_TEXT+'。下面是服务器最新值与你的修改，核对后可选择保留你的修改再保存；不会自动再次提交。'+(pending.reason?'（服务器提示：'+pending.reason+'）':''):pending.latest?'服务器当前配置与本次修改不同。请核对后决定是否保留修改；不会自动再次提交。':'保存结果尚未核对，重新读取前不能再次保存。';
  $('comparisonValues').innerHTML=pending.latest?fields.filter(key=>pending.latest[key]!==pending.draft[key]).map(key=>'<dt>'+labels[key]+'</dt><dd>服务器当前：'+esc(display(key,pending.latest[key]))+'</dd><dd>本次修改：'+esc(display(key,pending.draft[key]))+'</dd>').join(''):'';
}
function openSettings(index){
  const row=rows?.[index];if(!row||loading||saving||denied||readFailed||!isAdmin||pending&&pending.id!==row.channel_id)return;
  if(selectedId===row.channel_id&&!$('settingsPanel').hidden){$('settingsTitle').focus();return;}
  if(baseline&&!same(values(),baseline)&&!pending&&selectedId!==row.channel_id&&!window.confirm('切换通道将放弃未保存修改，继续吗？'))return;
  selectedId=row.channel_id;baseline=row;fill(pending?.draft||row);
  setDrawer(true);$('settingsTitle').textContent='设置 '+row.channel_name;
  formState(pending?'请重新核对后再保存':'尚未修改',pending?'pending':'');
  showComparison();renderRows();$('settingsTitle').focus();
}
function closeSettings(){
  if(saving||loading)return;const previous=selectedId;selectedId='';baseline=null;setDrawer(false);renderRows();
  const index=rows?.findIndex(row=>row.channel_id===previous);$('channelRows').querySelector('[data-setting="'+index+'"]')?.focus();
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
    if(pending.kind==='conflict'){
      formState(CONFLICT_TEXT+'，请核对差异后再保存。','pending');showComparison();
      tell(CONFLICT_TEXT+'。请在右侧设置面板核对差异；没有再次提交。','info');
    }else{
      formState('配置不同，请核对后再保存。','pending');showComparison();
      tell('已读取最新配置，请在设置面板核对差异；没有再次提交。','info');
    }
  }
}
async function reload({afterSave=false,afterConflict=false}={}){
  if(!isAdmin||loading||saving)return;
  if(baseline&&!pending&&!same(values(),baseline)&&!window.confirm('重新读取将放弃未保存修改，继续吗？'))return;
  loading=true;controls();tell(afterSave?'保存请求已受理，正在重新读取确认。':afterConflict?'数据已被他人修改，正在刷新最新值…':'正在读取通道配置。','info');
  try{
    const data=await api();
    if(!Array.isArray(data.channels)||!data.channels.every(validRow)||new Set(data.channels.map(row=>row.channel_id)).size!==data.channels.length)throw new Error('接口未返回完整通道配置，请重新读取。');
    rows=data.channels;denied=false;readFailed=false;$('roleNotice').textContent='仅公司管理员可修改通道配置。';
    tell('已读取最新通道配置。','success');
    if(pending)reconcile();
    else if(selectedId){baseline=rows.find(row=>row.channel_id===selectedId)||null;if(baseline){fill(baseline);formState('已读取最新配置');}else{setDrawer(false);selectedId='';}}
  }catch(error){
    readFailed=true;if(!revoke(error)){tell(error.message+(rows?' 已保留上次读取的配置，不能据此确认本次保存结果。':''));if(pending){pending.latest=null;showComparison();formState('保存结果未确认，请重新读取核对。','error');}}
  }finally{loading=false;renderRows();}
}
async function save(event){
  event.preventDefault();if(!baseline||pending||!isAdmin||saving||loading)return;
  const draft=values();
  if(!limitCheck()){formState($('limitError').textContent,'error');$('courseUploadLimit').focus();return;}
  if(!draft.channel_name){formState('请填写通道名称。','error');$('channelName').focus();return;}
  if($('saveChannel').disabled||!['active','paused'].includes(draft.status))return;
  saving=true;controls();formState('保存中…');
  const attempt={id:baseline.channel_id,draft,latest:null,kind:'uncertain',reason:''};
  let accepted=false,conflict=false;
  try{
    const data=await api('POST',{channel_id:baseline.channel_id,expected_version:baseline.version,...draft});
    if(!validRow(data.channel)||data.channel.channel_id!==baseline.channel_id)throw new Error('保存响应未能确认本通道，请重新读取。');
    attempt.kind='saved';pending=attempt;accepted=true;formState('正在重新读取确认');
  }catch(error){
    if(!revoke(error)){
      if(error.status===409&&error.code!=='channel_quota_in_use'){attempt.kind='conflict';attempt.reason=error.message;pending=attempt;conflict=true;}
      else if(!error.status||error.status>=500||(error.status>=200&&error.status<300))pending=attempt;
      formState(error.message,'error');tell(error.message);
    }
  }finally{saving=false;showComparison();controls();}
  if(accepted)await reload({afterSave:true});
  else if(conflict)await reload({afterConflict:true});
}
$('channelRows').addEventListener('click',event=>{const button=event.target.closest('[data-setting]');if(button&&!button.disabled)openSettings(Number(button.dataset.setting));});
function onFormEdit(){limitCheck();if(!pending&&!saving&&!loading)formState(same(values(),baseline)?'尚未修改':'待保存',same(values(),baseline)?'':'pending');controls();}
$('channelForm').addEventListener('input',onFormEdit);
$('channelForm').addEventListener('change',onFormEdit);
$('channelForm').addEventListener('submit',save);
$('cancelEdit').addEventListener('click',closeSettings);
$('closeDrawer').addEventListener('click',closeSettings);
$('settingsPanelBackdrop').addEventListener('click',closeSettings);
document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!$('settingsPanel').hidden)closeSettings();});
$('refreshChannels').addEventListener('click',()=>reload());
$('readBeforeRetry').addEventListener('click',()=>reload());
$('acceptComparison').addEventListener('click',()=>{if(!pending?.latest||loading||saving||denied||readFailed)return;baseline=pending.latest;fill(pending.draft);pending=null;showComparison();formState(same(values(),baseline)?'无需修改':'待保存','pending');controls();});
window.addEventListener('beforeunload',event=>{if(pending||saving||baseline&&!same(values(),baseline)){event.preventDefault();event.returnValue='';}});
if(isAdmin)reload();else{denied=true;readFailed=true;$('roleNotice').textContent='当前账号不是公司管理员，不能查看或修改通道配置。';tell($('roleNotice').textContent);renderRows();}
""".replace("__ACCOUNT__", _account_payload(account))
    empty_template = json.dumps(empty_state("__TEXT__", compact=True), ensure_ascii=False).replace("</", "<\\/")
    script = script.replace("__SETTINGS_ICON__", json.dumps(_SETTINGS_ICON)).replace("__EMPTY__", empty_template)
    return _document(title="上传通道设置", body=body, page_style=_STYLE, script=script)


render_demo2_channel_admin_html = render_channel_admin
render_channels = render_channel_admin
