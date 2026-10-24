"""Directory selection UI for the guarded /school/context integration.

The GET school/context response must explicitly set selection_enabled=true.
Absent that capability the page is read-only: it never falls back to the legacy
unguarded POST. Keep authorization/CSRF enforcement in the server. Import this
renderer from the portal's deferred school renderer, not at entry module import.
"""

from __future__ import annotations

from typing import Any


def render_school_selection_html(account: Any | None = None) -> str:
    # Deferred imports let the entry/portal renderer dispatch here without cycles.
    from .demo2_entry import COMMON_SCRIPT, ENTRY_STYLE, _shell
    from .demo2_portal import _document

    body = """<section class="entry-form-area school-area" aria-labelledby="schoolTitle">
<p class="entry-kicker">学校工作台</p><h1 id="schoolTitle">学校信息</h1>
<p class="entry-subtitle" id="coverage">正在读取学校目录</p>
<p class="entry-subtitle">学校名称不代表教师身份认证或数据访问授权。</p>
<div class="school-summary" id="currentSummary" hidden><strong id="currentName"></strong><span id="currentRegion"></span></div>
<p class="entry-subtitle" id="scopeNotice" role="status"></p>
<form id="schoolForm" class="entry-form">
<fieldset id="selectionFields" disabled>
<div class="field"><label for="selectionSource">学校来源</label><select id="selectionSource">
<option value="existing" id="existingOption" hidden>保留当前学校</option>
<option value="directory" selected>公开来源目录</option><option value="other">其他学校（待核验）</option>
</select></div>
<div id="directoryFields">
<div class="field"><label for="directoryRegion">地区</label><select id="directoryRegion"></select></div>
<div class="field"><label for="schoolSearch">学校名称筛选</label><input id="schoolSearch" type="search" maxlength="200" autocomplete="off" /></div>
<div class="field"><label for="directorySchool">学校</label><select id="directorySchool" required></select></div>
<p class="source-note" id="directoryAddress" role="status"></p>
<p class="source-note" id="sourceNote" role="status"></p>
<a id="sourceLink" hidden target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">公开来源原文</a>
</div>
<div id="otherFields" hidden>
<p class="pending-note">自行填写，待核验；不会加入公开来源目录。</p>
<div class="form-pair"><div class="field"><label for="province">省 / 直辖市</label><input id="province" maxlength="80" autocomplete="address-level1" /></div>
<div class="field"><label for="city">城市 / 直辖市</label><input id="city" maxlength="80" autocomplete="address-level2" /></div></div>
<div class="field"><label for="district">区 / 县</label><input id="district" maxlength="80" /></div>
<div class="field"><label for="street">街道 / 乡镇</label><input id="street" maxlength="80" autocomplete="address-level3" /></div>
<div class="field"><label for="schoolName">学校全称</label><input id="schoolName" maxlength="200" autocomplete="organization" /></div>
<div class="field"><label for="address">详细地址</label><input id="address" maxlength="300" autocomplete="street-address" /></div>
</div>
<label class="school-confirm"><input id="confirmed" type="checkbox" required />确认上述学校信息；此操作不授予其他学校的数据访问权限。</label>
</fieldset>
<p class="entry-subtitle" id="returnTaskNotice" hidden>保存后返回视频身份确认，不会自动补齐任务的学校记录。</p>
<div class="form-error" id="formError" role="alert"></div>
<button class="button primary" id="schoolButton" type="submit" disabled>保存学校信息</button>
<a class="button" id="continueLink" href="/demo2/upload" hidden>保留当前学校并进入工作台</a>
<button class="button quiet" id="reloadSchool" type="button">重新读取</button>
</form></section>"""
    style = ENTRY_STYLE + """
.school-area fieldset { border:0; padding:0; margin:0; min-width:0; display:grid; gap:16px; }
.school-area .field { min-width:0; }.school-area select,.school-area input { width:100%; min-width:0; max-width:100%; }
#directoryFields,#otherFields { display:grid; gap:16px; }
.school-area p,.school-area a,.school-area label { overflow-wrap:anywhere; }
.source-note,.pending-note { font-size:13px; line-height:1.7; color:#526273; }
.pending-note { border-left:3px solid #9b751f; padding-left:12px; color:#725616; }
.school-confirm { display:flex; gap:10px; align-items:flex-start; font-size:13px; line-height:1.8; }
.school-area .school-confirm input { width:18px; height:18px; min-height:18px; flex:0 0 18px; margin-top:3px; }
.school-area :focus-visible { outline:3px solid #398269; outline-offset:3px; }
"""
    script = COMMON_SCRIPT + r"""
let currentContext=null, entries=[], regions=[], ready=false, busy=false, changeAllowed=false;
const contextKeys=['city','district','school_name'];
const rawTask=new URLSearchParams(location.search).get('returntask')||'';
const returnTask=/^[A-Za-z0-9_-]{1,128}$/.test(rawTask)?rawTask:'';
const nextUrl=returnTask?'/demo2/identity?task_id='+encodeURIComponent(returnTask):'/demo2/upload';
byId('returnTaskNotice').hidden=!returnTask;
byId('continueLink').href=nextUrl;
byId('continueLink').textContent=returnTask?'保留当前学校并返回视频身份确认':'保留当前学校并进入工作台';
function complete(){return currentContext&&contextKeys.every(k=>currentContext[k].trim());}
function sameContext(a,b){return a&&b&&contextKeys.every(k=>a[k]===b[k]);}
function selectedEntry(){return entries.find(row=>row.directory_id===byId('directorySchool').value);}
function sourceNote(){
  const row=selectedEntry(), link=byId('sourceLink');link.hidden=true;link.removeAttribute('href');
  byId('directoryAddress').textContent=row?'街道 / 乡镇：'+(row.street||'未收录，待补充')+'；地址：'+(row.address||'未收录，待补充'):'';
  byId('sourceNote').textContent=row?'公开来源：'+row.source_title+'；发布 '+row.source_published_on+'；查阅 '+row.source_checked_on+'。'+(row.source_note||''):'未选择学校';
  if(row){try{const url=new URL(row.source_url);if(url.protocol==='https:'&&['www.shqp.gov.cn','cms.qpedu.cn'].includes(url.hostname)&&!url.username&&!url.password){link.href=url.href;link.hidden=false;}}catch(_){}}
}
function filterSchools(){
  const region=regions[Number(byId('directoryRegion').value)], query=byId('schoolSearch').value.trim().toLocaleLowerCase();
  const previous=byId('directorySchool').value;
  const rows=entries.filter(row=>region&&row.province===region.province&&row.city===region.city&&row.district===region.district&&row.school_name.toLocaleLowerCase().includes(query));
  byId('directorySchool').replaceChildren(new Option(rows.length?'请选择学校':'未找到学校，可选择其他学校',''));
  rows.forEach(row=>byId('directorySchool').add(new Option(row.school_name,row.directory_id)));
  if(rows.some(row=>row.directory_id===previous))byId('directorySchool').value=previous;
  byId('confirmed').checked=false;sourceNote();
}
function refreshMode(){
  const mode=byId('selectionSource').value;
  byId('directoryFields').hidden=mode!=='directory';byId('otherFields').hidden=mode!=='other';
  for(const id of ['directoryRegion','directorySchool','schoolSearch'])byId(id).disabled=mode!=='directory';
  byId('directorySchool').required=mode==='directory';
  for(const id of ['province','city','district','street','schoolName','address']){byId(id).disabled=mode!=='other';byId(id).required=mode==='other';}
  byId('confirmed').checked=false;clearError();
}
function setBusy(value){busy=value;byId('selectionFields').disabled=value||!ready;byId('schoolButton').disabled=value||!ready;byId('reloadSchool').disabled=value;}
async function loadContext(){
  ready=false;setBusy(true);clearError();byId('continueLink').hidden=true;
  try{
    const data=await request('/api/v1/demo2/school/context');
    if(!data.context||contextKeys.some(k=>typeof data.context[k]!=='string'))throw new Error('学校信息响应不完整，请重新读取。');
    currentContext=Object.fromEntries(contextKeys.map(k=>[k,data.context[k]]));
    entries=Array.isArray(data.directory?.entries)?data.directory.entries:[];
    regions=Array.isArray(data.directory?.regions)?data.directory.regions:[];
    byId('coverage').textContent=data.directory?.coverage?.label||'公开来源目录暂不可用';
    byId('directoryRegion').replaceChildren(...regions.map((r,i)=>new Option([r.province,r.city,r.district].filter((v,j,a)=>a.indexOf(v)===j).join(' / '),String(i))));
    byId('currentSummary').hidden=!contextKeys.some(k=>currentContext[k]);
    byId('currentName').textContent=currentContext.school_name;
    byId('currentRegion').textContent=[currentContext.city,currentContext.district].filter(Boolean).join(' / ');
    byId('existingOption').hidden=!complete();
    byId('selectionSource').value=complete()?'existing':entries.length?'directory':'other';
    changeAllowed=data.context_change_allowed===true;
    byId('selectionSource').disabled=!changeAllowed;
    for(const [id,key] of [['city','city'],['district','district'],['schoolName','school_name']])byId(id).value=currentContext[key];
    for(const id of ['province','street','address'])byId(id).value=data.details?.[id]||'';
    byId('continueLink').hidden=!complete();
    ready=data.selection_enabled===true&&(changeAllowed||!!complete());
    byId('scopeNotice').textContent=!ready?'学校保存接口尚未启用或归属状态待确认。':!changeAllowed?'该账号学校归属已锁定，更换学校需管理员核验迁移。':'学校信息将用于后续名册归属；历史任务的学校记录保持不变。';
    filterSchools();refreshMode();
  }catch(error){currentContext=null;showError(error.message);}
  finally{setBusy(false);}
}
byId('selectionSource').addEventListener('change',refreshMode);
byId('directoryRegion').addEventListener('change',filterSchools);
byId('schoolSearch').addEventListener('input',filterSchools);
byId('directorySchool').addEventListener('change',()=>{byId('confirmed').checked=false;sourceNote();});
byId('otherFields').addEventListener('input',()=>{byId('confirmed').checked=false;});
byId('reloadSchool').addEventListener('click',loadContext);
byId('schoolForm').addEventListener('submit',async event=>{
  event.preventDefault();if(!ready||busy||!byId('schoolForm').reportValidity())return;
  const mode=byId('selectionSource').value;
  let selection={selection_source:mode}, expected=currentContext;
  if(mode==='directory'){
    const row=selectedEntry();if(!row){showError('请选择学校');return;}
    selection.directory_id=row.directory_id;expected=Object.fromEntries(contextKeys.map(k=>[k,row[k]]));
  }else if(mode==='other'){
    selection={...selection,province:byId('province').value.trim(),city:byId('city').value.trim(),district:byId('district').value.trim(),school_name:byId('schoolName').value.trim(),street:byId('street').value.trim(),address:byId('address').value.trim()};
    expected=Object.fromEntries(contextKeys.map(k=>[k,selection[k]]));
  }else if(mode==='existing'){selection={...selection,...currentContext};}else{return;}
  if(!changeAllowed&&!sameContext(expected,currentContext)){showError('更换学校需管理员核验迁移。');return;}
  setBusy(true);clearError();
  try{
    const data=await request('/api/v1/demo2/school/context',{...selection,expected_context:currentContext,confirmed:byId('confirmed').checked});
    if(!sameContext(data.context,expected))throw new Error('保存响应不一致，请重新读取学校信息。');
    location.assign(nextUrl);
  }catch(error){ready=false;showError(error.message+' 请重新读取后再试。');}
  finally{setBusy(false);}
});
loadContext();
"""
    return _document(
        title="学校选择 · 课堂学习分析平台",
        body=_shell(body, nav='<a href="/demo2/login">返回登录</a>', workspace_active="school"),
        page_style=style, script=script,
    )


render_school = render_school_selection_html
