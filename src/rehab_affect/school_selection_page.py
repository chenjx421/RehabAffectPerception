"""Directory selection UI for the guarded /school/context integration.

The GET school/context response must explicitly set selection_enabled=true.
Absent that capability the page is read-only: it never falls back to the legacy
unguarded POST. Keep authorization/CSRF enforcement in the server. Import this
renderer from the portal's deferred school renderer, not at entry module import.

Sources: the national directory (default; province/city/district cascade and
server-side paged search via /api/v1/demo2/schools/*), the curated public-source
list (same search, scope=public_source) and a manual entry that is saved as a
pending school for administrator review. demo2_entry.render_school delegates
here so both entry points render the same page.
"""

from __future__ import annotations

from typing import Any


def render_school_selection_html(account: Any | None = None) -> str:
    # Deferred imports let the entry/portal renderer dispatch here without cycles.
    from .demo2_entry import COMMON_SCRIPT, ENTRY_STYLE, _shell
    from .demo2_portal import _document
    from .demo2_ui_kit import steps, teacher_header

    setup_steps = steps(("填写学校信息", "建立学生名册", "上传课堂视频"), 0, aria_label="开始使用的三个步骤",
                        element_id="schoolSetupSteps")
    type_options = "".join(f'<option value="{t}">{t}</option>' for t in
                           ("特殊教育学校", "辅读学校", "小学", "初中", "九年一贯制", "中学", "高中", "职校"))
    body = """<section class="entry-form-area school-area" aria-labelledby="schoolTitle">
<p class="entry-kicker">学校工作台</p><h1 id="schoolTitle">学校信息</h1>
<p class="entry-subtitle">确认本账号课程的学校归属：可在全国学校目录中搜索选择；城市、区县和学校都确定后，才能建名册和上传视频。</p>
""" + setup_steps + """
<section class="school-card" id="currentSummary" aria-labelledby="currentSummaryTitle" hidden>
<div class="school-card-head"><h2 id="currentSummaryTitle">当前学校</h2><span class="school-card-badge" id="currentState">已填写</span></div>
<dl class="school-tiles"><div class="school-tile"><dt>城市</dt><dd id="currentCity">—</dd></div><div class="school-tile"><dt>区县</dt><dd id="currentDistrict">—</dd></div><div class="school-tile school-tile-wide"><dt>学校</dt><dd id="currentName">—</dd></div></dl>
<p class="school-card-note" id="currentRegion"></p>
<p class="school-review" id="currentReview" hidden></p>
</section>
<section class="school-done" id="saveSuccess" role="status" aria-live="polite" hidden>
<div class="school-done-icon" aria-hidden="true">✓</div>
<div class="school-done-copy"><strong>学校信息已保存</strong><span id="saveSuccessDetail">接下来建立本校学生名册，上传视频后才能确认画面中的学生。</span></div>
<div class="school-done-actions"><a class="button primary" id="nextStepStudents" href="/demo2/students">下一步：建立学生名册</a><a class="button quiet" id="nextStepUpload" href="/demo2/upload">直接去上传视频</a></div>
</section>
<p class="entry-subtitle scope-notice" id="scopeNotice" role="status"></p>
<form id="schoolForm" class="entry-form school-form-card" novalidate>
<div class="school-form-head"><h2>选择或修改学校</h2><p id="coverage">正在读取全国学校目录</p></div>
<fieldset id="selectionFields" disabled>
<div class="field"><label for="selectionSource">学校来源</label><select id="selectionSource">
<option value="existing" id="existingOption" hidden>保留当前学校</option>
<option value="national" selected>全国学校目录</option><option value="directory">公开来源目录</option><option value="manual">手动填写学校（待审核）</option>
</select></div>
<div id="directoryFields">
<fieldset class="region-group"><legend>地区（可不选，直接搜索全国）</legend>
<div class="region-row"><div class="field"><label for="regionProvince">省 / 自治区 / 直辖市</label><select id="regionProvince"><option value="">不限</option></select></div>
<div class="field"><label for="regionCity">市</label><select id="regionCity" disabled><option value="">不限</option></select></div>
<div class="field"><label for="regionDistrict">区 / 县</label><select id="regionDistrict" disabled><option value="">不限</option></select></div></div>
</fieldset>
<div class="search-row"><div class="field"><label for="schoolSearch">学校名称筛选</label><input id="schoolSearch" type="search" maxlength="50" autocomplete="off" placeholder="输入校名关键词或拼音首字母，如：特殊教育 / 海淀 / tsjy" aria-describedby="searchHint" /></div>
<div class="field type-field"><label for="schoolType">学校类型</label><select id="schoolType"><option value="">不限</option>""" + type_options + """</select></div></div>
<p class="source-note" id="searchHint">不选地区也能搜；结果每页 20 条，显示「学校名 · 省市区 · 类型」。</p>
<div class="result-head"><span id="resultInfo" role="status" aria-live="polite">正在搜索…</span><span class="result-pager"><button class="button quiet" id="resultPrev" type="button" disabled>上一页</button><button class="button quiet" id="resultNext" type="button" disabled>下一页</button></span></div>
<ul class="school-results" id="schoolResults" role="listbox" aria-label="学校搜索结果"></ul>
<div class="selected-school" id="selectedSchool" hidden><span class="selected-label">已选择</span><strong id="selectedName"></strong><span id="selectedMeta"></span></div>
<p class="source-note" id="directoryAddress" role="status"></p>
<p class="source-note" id="sourceNote" role="status"></p>
<a id="sourceLink" hidden target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">公开来源原文</a>
<p class="manual-entry">目录里找不到？<button class="link-button" id="toManual" type="button">手动填写学校</button></p>
</div>
<div id="otherFields" hidden>
<p class="pending-note">自行填写，待核验：保存后可正常使用，同时提交管理员审核，审核通过后归入全国学校目录。</p>
<fieldset class="core-fields"><legend>必填：省市区 + 学校全称</legend>
<div class="region-row"><div class="field"><label for="province">省 / 自治区 / 直辖市</label><select id="province"><option value="">请选择</option></select></div>
<div class="field"><label for="city">市</label><select id="city" disabled><option value="">请选择</option></select></div>
<div class="field"><label for="district">区 / 县</label><select id="district" disabled><option value="">请选择</option></select></div></div>
<div class="field"><label for="schoolName">学校全称</label><input id="schoolName" maxlength="200" autocomplete="organization" placeholder="请填写学校的完整名称，例如：某某区特殊教育学校" /></div>
</fieldset>
<details class="extra-fields"><summary>补充地址（选填）</summary>
<div class="field"><label for="street">街道 / 乡镇</label><input id="street" maxlength="80" autocomplete="address-level3" /></div>
<div class="field"><label for="address">详细地址</label><input id="address" maxlength="300" autocomplete="street-address" /></div>
</details>
</div>
<label class="school-confirm"><input id="confirmed" type="checkbox" />确认上述学校信息；此操作不授予其他学校的数据访问权限。</label>
<p class="boundary-note">学校名称不代表教师身份认证或数据访问授权；已上传的任务保留上传时的学校记录，不随修改自动迁移。</p>
</fieldset>
<p class="entry-subtitle" id="returnTaskNotice" hidden>保存后返回视频身份确认，不会自动补齐任务的学校记录。</p>
<div class="form-error" id="formError" role="alert"></div>
<div class="school-actions"><button class="button primary" id="schoolButton" type="submit" disabled>保存学校信息</button>
<a class="button" id="continueLink" href="/demo2/upload" hidden>保留当前学校并进入工作台</a>
<button class="button quiet" id="reloadSchool" type="button">重新读取</button></div>
<p class="school-button-hint" id="schoolButtonHint" role="status"></p>
</form></section>"""
    style = ENTRY_STYLE + """
.school-area fieldset { border:0; padding:0; margin:0; min-width:0; display:grid; gap:16px; }
.school-area .field { min-width:0; }.school-area select,.school-area input { width:100%; min-width:0; max-width:100%; }
#directoryFields,#otherFields { display:grid; gap:14px; }
#directoryFields[hidden],#otherFields[hidden] { display:none; }
.school-area p,.school-area a,.school-area label { overflow-wrap:anywhere; }
.source-note,.pending-note { margin:0; font-size:13px; line-height:1.7; color:#526273; }
.source-note:empty { display:none; }
.pending-note { border-left:3px solid #9b751f; padding-left:12px; color:#725616; }
.school-confirm { display:flex; gap:10px; align-items:flex-start; font-size:13px; line-height:1.8; }
.school-area .school-confirm input { width:18px; height:18px; min-height:18px; flex:0 0 18px; margin-top:3px; }
.school-area :focus-visible { outline:3px solid #398269; outline-offset:3px; }
.entry-form-area.school-area { width:min(720px,100%); }
.school-area .rx-steps { margin:18px 0 6px; }
.school-area .rx-step { min-width:0; }
.school-card,.school-done,.school-form-card { margin-top:18px; border:1px solid #d3deea; border-radius:8px; background:#fff; box-shadow:0 1px 2px rgba(23,43,77,.05); }
.school-card { padding:16px 18px; }
.school-card-head { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:12px; }
.school-card-head h2,.school-form-head h2 { margin:0; font-size:17px; color:#172b4d; }
.school-card-badge { padding:2px 10px; border-radius:8px; background:#e8f6ef; color:#146c4b; font-size:12px; font-weight:700; white-space:nowrap; }
.school-card-badge.incomplete { background:#fff5e3; color:#8a4b06; }
.school-tiles { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; margin:0; }
.school-tile { min-width:0; padding:10px 14px; border-radius:8px; background:#f6f9fe; border:1px solid #e3ebf5; }
.school-tile-wide { grid-column:1/-1; }
.school-tile dt { color:#56657a; font-size:12px; }
.school-tile dd { margin:4px 0 0; color:#172b4d; font-size:16px; font-weight:700; overflow-wrap:anywhere; }
.school-tile dd.empty { color:#8a4b06; font-weight:600; font-size:14px; }
.school-card-note { margin:10px 0 0; color:#56657a; font-size:12px; }
.school-card-note:empty { display:none; }
.school-review { margin:10px 0 0; padding:8px 12px; border-radius:8px; font-size:13px; background:#fff8ec; color:#8a4b06; border:1px solid #ecc98e; }
.school-review.approved { background:#f2fbf6; color:#146c4b; border-color:#a9d8c2; }
.school-review.rejected { background:#fdf1f1; color:#a32020; border-color:#efb9b9; }
.school-done { display:grid; grid-template-columns:auto minmax(0,1fr); gap:10px 14px; align-items:center; padding:16px 18px; border-color:#a9d8c2; background:#f2fbf6; }
.school-done[hidden] { display:none; }
.school-done-icon { display:inline-flex; align-items:center; justify-content:center; width:36px; height:36px; border-radius:50%; background:#146c4b; color:#fff; font-size:18px; font-weight:800; }
.school-done-copy strong { display:block; color:#146c4b; font-size:16px; }
.school-done-copy span { color:#26364a; font-size:13px; }
.school-done-actions { grid-column:1/-1; display:flex; flex-wrap:wrap; gap:10px; }
.school-form-card { padding:18px; display:grid; gap:16px; }
.school-form-head p { margin:4px 0 0; color:#56657a; font-size:13px; line-height:1.6; }
.region-group { gap:8px !important; }
.region-group legend,.core-fields legend { padding:0 0 6px; color:#172b4d; font-size:13px; font-weight:700; }
.region-row { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }
.search-row { display:grid; grid-template-columns:minmax(0,1fr) 180px; gap:10px; align-items:end; }
.result-head { display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap; font-size:13px; color:#526273; }
.result-pager { display:inline-flex; gap:6px; }
.result-pager .button { min-height:34px; padding:4px 12px; font-size:13px; }
.school-results { list-style:none; margin:0; padding:0; max-height:360px; overflow:auto; border:1px solid #d3deea; border-radius:8px; background:#fff; }
.school-results:empty { display:none; }
.school-results li { border-bottom:1px solid #edf1f6; }
.school-results li:last-child { border-bottom:0; }
.school-option { display:block; width:100%; text-align:left; padding:10px 14px; border:0; background:none; cursor:pointer; font:inherit; color:#172b4d; }
.school-option:hover { background:#f4f8fe; }
.school-option[aria-selected=true] { background:#e9f1fd; box-shadow:inset 3px 0 0 #1f5fbf; }
.school-option strong { font-size:14px; font-weight:700; }
.school-option .meta { color:#56657a; font-size:13px; }
.school-option .type-tag { display:inline-block; padding:0 6px; border-radius:4px; background:#eef3fa; color:#174a96; font-size:11px; font-weight:600; }
.school-option .type-tag.special { background:#fff1e0; color:#8a4b06; }
.school-empty { padding:16px; color:#56657a; font-size:13px; text-align:center; }
.selected-school { display:flex; flex-wrap:wrap; gap:6px 10px; align-items:baseline; padding:10px 14px; border-radius:8px; background:#f2fbf6; border:1px solid #a9d8c2; }
.selected-school[hidden] { display:none; }
.selected-label { color:#146c4b; font-size:12px; font-weight:700; }
.selected-school strong { color:#172b4d; }
.selected-school span:last-child { color:#526273; font-size:12px; }
.manual-entry { margin:0; font-size:13px; color:#526273; }
.link-button { border:0; background:none; padding:0; color:#174a96; font:inherit; font-weight:700; text-decoration:underline; cursor:pointer; }
.core-fields { display:grid; gap:14px; margin:0; padding:14px; border:1px solid #d3deea; border-radius:8px; background:#f6f9fe; min-width:0; }
.extra-fields { border-top:1px dashed #d3deea; padding-top:10px; }
.extra-fields summary { min-height:40px; display:flex; align-items:center; cursor:pointer; color:#174a96; font-size:13px; font-weight:700; }
.extra-fields[open] { display:grid; gap:14px; }
.boundary-note { margin:0; color:#56657a; font-size:12px; line-height:1.7; }
.school-actions { display:flex; flex-wrap:wrap; gap:10px; }
.school-button-hint { margin:0; color:#8a4b06; font-size:13px; }
.school-button-hint:empty { display:none; }
.scope-notice:empty { display:none; }
@media (max-width:640px) {
  .region-row,.search-row { grid-template-columns:1fr; }
}
@media (max-width:520px) {
  .school-area .rx-steps { flex-direction:column; }
  .school-area .rx-step { border-right:0; border-bottom:1px solid #d3deea; }
  .school-area .rx-step:last-child { border-bottom:0; }
  .school-tiles { grid-template-columns:1fr; }
  .school-form-card,.school-card,.school-done { padding:14px; }
  .school-actions .button,.school-done-actions .button { flex:1 1 100%; }
}
"""
    script = COMMON_SCRIPT + r"""
let currentContext=null, currentDetails={}, ready=false, busy=false, changeAllowed=false;
let results=[], selectedRow=null, searchPage=1, totalPages=1, searchSeq=0, searchTimer=0;
const regionCache=new Map();
const contextKeys=['city','district','school_name'];
const SPECIAL_TYPES=['特殊教育学校','辅读学校'];
const rawTask=new URLSearchParams(location.search).get('returntask')||'';
const returnTask=/^[A-Za-z0-9_-]{1,128}$/.test(rawTask)?rawTask:'';
const nextUrl=returnTask?'/demo2/identity?task_id='+encodeURIComponent(returnTask):'/demo2/upload';
byId('returnTaskNotice').hidden=!returnTask;
byId('continueLink').href=nextUrl;
byId('continueLink').textContent=returnTask?'保留当前学校并返回视频身份确认':'保留当前学校并进入工作台';
byId('schoolButton').textContent=returnTask?'保存并返回视频身份确认':'保存学校信息';
function complete(){return currentContext&&contextKeys.every(k=>currentContext[k].trim());}
function mode(){return byId('selectionSource').value;}
function renderCurrent(){
  const any=!!currentContext&&contextKeys.some(k=>currentContext[k]);
  if(window.RxUI?.setStep)window.RxUI.setStep('schoolSetupSteps',complete()?1:0);
  byId('currentSummary').hidden=!any;if(!any)return;
  for(const [id,key] of [['currentCity','city'],['currentDistrict','district'],['currentName','school_name']]){
    const value=String(currentContext[key]||'').trim();byId(id).textContent=value||'未填写';byId(id).className=value?'':'empty';
  }
  byId('currentState').textContent=complete()?'已填写':'待补全';byId('currentState').className='school-card-badge'+(complete()?'':' incomplete');
  byId('currentRegion').textContent=complete()?[currentDetails.province,currentDetails.school_type].filter(Boolean).join(' · '):'城市、区县、学校三项都填好后，才能建名册和上传视频。';
  const review=currentDetails.selection_source==='manual'?currentDetails.review_status:'';
  const node=byId('currentReview');node.hidden=!review;
  node.className='school-review'+(review==='approved'?' approved':review==='rejected'?' rejected':'');
  node.textContent=review==='approved'?'手动填写的学校已通过管理员审核，已归入全国学校目录。':review==='rejected'?'手动填写的学校未通过审核'+(currentDetails.review_note?'：'+currentDetails.review_note:'')+'。可在下方重新搜索或修改。':review?'手动填写的学校待管理员审核；审核期间可正常使用。':'';
}
function buttonHint(){
  const node=byId('schoolButtonHint');if(!node)return;
  if(busy){node.textContent='';return;}
  if(!ready){node.textContent=currentContext?'学校保存暂不可用，请点击“重新读取”或联系管理员。':'';return;}
  const m=mode();
  if((m==='national'||m==='directory')&&!selectedRow){node.textContent='还差一步：请在搜索结果中点选学校。';return;}
  if(m==='manual'&&!manualReady()){node.textContent='还差一步：请选择省、市、区县并填写学校全称。';return;}
  node.textContent=byId('confirmed').checked?'':'还差一步：请勾选“确认上述学校信息”。';
}
function sameContext(a,b){return a&&b&&contextKeys.every(k=>a[k]===b[k]);}
function manualReady(){return ['province','city','district'].every(id=>byId(id).value)&&byId('schoolName').value.trim().length>=4;}
function regionText(row){return [row.province,row.city,row.district].filter((v,i,a)=>v&&a.indexOf(v)===i).join('');}
async function regions(parent){
  if(regionCache.has(parent))return regionCache.get(parent);
  const data=await request('/api/v1/demo2/schools/regions?parent='+encodeURIComponent(parent));
  const list=Array.isArray(data.regions)?data.regions:[];regionCache.set(parent,list);return list;
}
function fillSelect(id,list,emptyLabel){
  const select=byId(id);select.replaceChildren(new Option(emptyLabel,''));
  list.forEach(node=>select.add(new Option(node.name,node.code)));select.disabled=!list.length;
}
async function cascade(prefix,level,emptyLabel){
  const ids=prefix==='region'?{province:'regionProvince',city:'regionCity',district:'regionDistrict'}:{province:'province',city:'city',district:'district'};
  try{
    if(level==='province'){
      fillSelect(ids.city,[],emptyLabel);fillSelect(ids.district,[],emptyLabel);
      if(byId(ids.province).value)fillSelect(ids.city,await regions(byId(ids.province).value),emptyLabel);
    }else if(level==='city'){
      fillSelect(ids.district,[],emptyLabel);
      if(byId(ids.city).value)fillSelect(ids.district,await regions(byId(ids.city).value),emptyLabel);
    }
  }catch(error){showError(error.status===429?'地区读取过于频繁，请稍后再试。':error.message);}
}
function selectRow(row){
  selectedRow=row;byId('confirmed').checked=false;
  for(const node of byId('schoolResults').querySelectorAll('.school-option'))node.setAttribute('aria-selected',String(node.dataset.code===(row&&row.directory_id)));
  byId('selectedSchool').hidden=!row;
  if(row){byId('selectedName').textContent=row.school_name;byId('selectedMeta').textContent=regionText(row)+' · '+row.school_type;}
  sourceNote();buttonHint();
}
function sourceNote(){
  const row=selectedRow, link=byId('sourceLink');link.hidden=true;link.removeAttribute('href');
  byId('directoryAddress').textContent=row?'街道 / 乡镇：'+(row.street||'未收录，待补充')+'；地址：'+(row.address||'未收录，待补充'):'';
  byId('sourceNote').textContent=row?'来源：'+(row.source_title||'全国学校目录')+(row.source_published_on?'；发布 '+row.source_published_on:'')+(row.source_checked_on?'；查阅 '+row.source_checked_on:'')+'。'+(row.source_note||''):'';
  if(row&&row.source_url){try{const url=new URL(row.source_url);if(url.protocol==='https:'&&!url.username&&!url.password){link.href=url.href;link.textContent=row.origin==='curated'?'公开来源原文':'数据来源说明';link.hidden=false;}}catch(_){}}
}
function renderResults(data){
  const list=byId('schoolResults');list.replaceChildren();
  results=Array.isArray(data.items)?data.items:[];
  totalPages=Math.max(1,Number(data.total_pages)||1);searchPage=Math.min(Number(data.page)||1,totalPages);
  if(!results.length){
    const empty=document.createElement('li');empty.className='school-empty';empty.textContent='没有找到匹配的学校。可换个关键词、放宽地区，或点击下方「手动填写学校」。';list.append(empty);
  }
  for(const row of results){
    const item=document.createElement('li');const button=document.createElement('button');
    button.type='button';button.className='school-option';button.setAttribute('role','option');button.dataset.code=row.directory_id;
    button.setAttribute('aria-selected',String(!!selectedRow&&selectedRow.directory_id===row.directory_id));
    const name=document.createElement('strong');name.textContent=row.school_name;
    const tag=document.createElement('span');tag.className='type-tag'+(SPECIAL_TYPES.includes(row.school_type)?' special':'');tag.textContent=row.school_type;
    const meta=document.createElement('span');meta.className='meta';meta.textContent=' · '+regionText(row)+' · ';
    button.append(name,meta,tag);button.addEventListener('click',()=>selectRow(row));
    item.append(button);list.append(item);
  }
  byId('resultInfo').textContent=data.total?'共 '+data.total+' 所 · 第 '+searchPage+' / '+totalPages+' 页':'未找到学校';
  byId('resultPrev').disabled=searchPage<=1;byId('resultNext').disabled=searchPage>=totalPages;
}
async function runSearch(page=1){
  if(mode()!=='national'&&mode()!=='directory')return;
  const seq=++searchSeq;clearTimeout(searchTimer);
  const keyword=byId('schoolSearch').value.trim();
  if(keyword.length>50){
    clearResultList('搜索词最多 50 个字（当前 '+keyword.length+' 字），请缩短后再搜索。');
    return;
  }
  const params=new URLSearchParams({q:keyword,province:byId('regionProvince').value,city:byId('regionCity').value,district:byId('regionDistrict').value,type:byId('schoolType').value,page:String(page),scope:mode()==='directory'?'public_source':'national'});
  byId('resultInfo').textContent='正在搜索…';
  try{
    const data=await request('/api/v1/demo2/schools/search?'+params.toString());
    if(seq!==searchSeq)return;
    renderResults(data);
  }catch(error){
    if(seq!==searchSeq)return;
    if(error.status===429){byId('resultInfo').textContent='搜索过于频繁，请'+(error.retryAfter||60)+' 秒后再试。';return;}
    clearResultList('搜索失败：'+error.message);
  }
}
function clearResultList(text){
  results=[];searchPage=1;totalPages=1;
  byId('schoolResults').replaceChildren();
  byId('resultInfo').textContent=text;
  byId('resultPrev').disabled=true;byId('resultNext').disabled=true;
}
function scheduleSearch(){clearTimeout(searchTimer);searchTimer=setTimeout(()=>runSearch(1),300);}
function refreshMode(){
  const m=mode();
  byId('directoryFields').hidden=!(m==='national'||m==='directory');byId('otherFields').hidden=m!=='manual';
  for(const id of ['regionProvince','schoolSearch','schoolType'])byId(id).disabled=byId('directoryFields').hidden;
  byId('regionCity').disabled=byId('directoryFields').hidden||byId('regionCity').options.length<2;
  byId('regionDistrict').disabled=byId('directoryFields').hidden||byId('regionDistrict').options.length<2;
  for(const id of ['province','schoolName','street','address'])byId(id).disabled=m!=='manual';
  byId('city').disabled=m!=='manual'||byId('city').options.length<2;
  byId('district').disabled=m!=='manual'||byId('district').options.length<2;
  byId('confirmed').checked=false;clearError();selectRow(null);
  if(m==='national'||m==='directory')runSearch(1);
}
function setBusy(value){busy=value;byId('selectionFields').disabled=value||!ready;byId('schoolButton').disabled=value||!ready;byId('reloadSchool').disabled=value;buttonHint();}
async function loadContext(){
  ready=false;setBusy(true);clearError();byId('continueLink').hidden=true;
  try{
    const data=await request('/api/v1/demo2/school/context');
    if(!data.context||contextKeys.some(k=>typeof data.context[k]!=='string'))throw new Error('学校信息响应不完整，请重新读取。');
    currentContext=Object.fromEntries(contextKeys.map(k=>[k,data.context[k]]));
    currentDetails=data.details&&typeof data.details==='object'?data.details:{};
    byId('coverage').textContent=data.national_directory?.label||'全国学校目录暂不可用，可手动填写学校。';
    renderCurrent();
    byId('existingOption').hidden=!complete();
    byId('selectionSource').value=complete()?'existing':'national';
    changeAllowed=data.context_change_allowed===true;
    byId('selectionSource').disabled=!changeAllowed;
    for(const id of ['street','address'])byId(id).value=currentDetails[id]||'';
    byId('continueLink').hidden=!complete();
    ready=data.selection_enabled===true&&(changeAllowed||!!complete());
    byId('scopeNotice').textContent=!ready?'学校保存接口尚未启用或归属状态待确认。':!changeAllowed?'该账号学校归属已锁定，更换学校需管理员核验迁移。':'学校信息将用于后续名册归属；历史任务的学校记录保持不变。';
    if(changeAllowed&&byId('regionProvince').options.length<2){
      try{const provinces=await regions('');fillSelect('regionProvince',provinces,'不限');fillSelect('province',provinces,'请选择');byId('regionProvince').disabled=false;}
      catch(error){byId('coverage').textContent='地区列表暂不可用：'+error.message;}
    }
    refreshMode();
  }catch(error){currentContext=null;showError(error.message);}
  finally{setBusy(false);}
}
byId('selectionSource').addEventListener('change',()=>{refreshMode();buttonHint();});
byId('regionProvince').addEventListener('change',async()=>{await cascade('region','province','不限');runSearch(1);});
byId('regionCity').addEventListener('change',async()=>{await cascade('region','city','不限');runSearch(1);});
byId('regionDistrict').addEventListener('change',()=>runSearch(1));
byId('schoolType').addEventListener('change',()=>runSearch(1));
byId('schoolSearch').addEventListener('input',scheduleSearch);
byId('schoolSearch').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();runSearch(1);}});
byId('resultPrev').addEventListener('click',()=>{if(searchPage>1)runSearch(searchPage-1);});
byId('resultNext').addEventListener('click',()=>{if(searchPage<totalPages)runSearch(searchPage+1);});
byId('province').addEventListener('change',()=>{byId('confirmed').checked=false;cascade('manual','province','请选择').then(buttonHint);});
byId('city').addEventListener('change',()=>{byId('confirmed').checked=false;cascade('manual','city','请选择').then(buttonHint);});
byId('district').addEventListener('change',()=>{byId('confirmed').checked=false;buttonHint();});
byId('toManual').addEventListener('click',async()=>{
  const keyword=byId('schoolSearch').value.trim();
  byId('selectionSource').value='manual';refreshMode();
  if(byId('regionProvince').value){
    byId('province').value=byId('regionProvince').value;await cascade('manual','province','请选择');
    if(byId('regionCity').value){byId('city').value=byId('regionCity').value;await cascade('manual','city','请选择');}
    if(byId('regionDistrict').value)byId('district').value=byId('regionDistrict').value;
  }
  if(keyword.length>=2&&!byId('schoolName').value)byId('schoolName').value=keyword;
  byId('schoolName').focus();buttonHint();
});
byId('otherFields').addEventListener('input',()=>{byId('confirmed').checked=false;buttonHint();});
byId('reloadSchool').addEventListener('click',()=>{byId('saveSuccess').hidden=true;loadContext();});
byId('confirmed').addEventListener('change',()=>{if(byId('confirmed').checked)clearError();buttonHint();});
byId('schoolForm').addEventListener('submit',async event=>{
  event.preventDefault();if(!ready||busy)return;
  const m=mode();
  let selection={selection_source:m}, expected=currentContext;
  if(m==='national'||m==='directory'){
    if(!selectedRow){showError('请在搜索结果中点选学校');buttonHint();return;}
    selection.directory_id=selectedRow.directory_id;expected=Object.fromEntries(contextKeys.map(k=>[k,selectedRow[k]]));
  }else if(m==='manual'){
    if(!manualReady()){showError('请选择省、市、区县并填写学校全称（至少 4 个字）');buttonHint();return;}
    const cityName=byId('city').selectedOptions[0].text, districtName=byId('district').selectedOptions[0].text;
    selection={...selection,province_code:byId('province').value,city_code:byId('city').value,district_code:byId('district').value,school_name:byId('schoolName').value.trim(),street:byId('street').value.trim(),address:byId('address').value.trim()};
    expected={city:/直辖县级行政区划$/.test(cityName)?districtName:cityName,district:districtName,school_name:selection.school_name};
  }else if(m==='existing'){selection={...selection,...currentContext};}else{return;}
  if(!byId('confirmed').checked){showError('请勾选“确认上述学校信息”');buttonHint();return;}
  if(!changeAllowed&&!sameContext(expected,currentContext)){showError('更换学校需管理员核验迁移。');return;}
  setBusy(true);clearError();
  try{
    const data=await request('/api/v1/demo2/school/context',{...selection,expected_context:currentContext,confirmed:byId('confirmed').checked});
    if(!sameContext(data.context,expected))throw new Error('保存响应不一致，请重新读取学校信息。');
    if(returnTask){location.assign(nextUrl);return;}
    window.RxUI?.toast?.(m==='manual'?'学校信息已保存，已提交管理员审核':'学校信息已保存','success',3200);
    await loadContext();
    byId('saveSuccess').hidden=false;byId('nextStepStudents').focus?.();
  }catch(error){ready=false;showError(error.message+' 请重新读取后再试。');}
  finally{setBusy(false);}
});
loadContext();
"""
    return _document(
        title="学校选择",
        body=_shell(body, header=teacher_header("school", account, logout_bound=False, page="school")),
        page_style=style, script=script,
    )


render_school = render_school_selection_html
