"""Upload-page pieces for course-task Word/PDF upload and the goal confirmation drawer.

Kept out of the upload page's f-string: plain HTML/CSS/JS constants that
``demo2_portal.render_demo2_upload_html`` inserts. The script only uses
``byId``/``message``/``esc``/``workspace`` from the upload page and guards
every element lookup so page harnesses without these nodes keep working.
"""
from __future__ import annotations

from .demo2_ui_kit import drawer, hint

COURSE_TASK_FIELD_HTML = (
    '<div class="field wide course-task-field" id="courseTaskField"><span class="field-label">课程任务文件（Word/PDF）'
    + hint("上传本课教学任务/教案，系统将自动识别课程目标。支持 PDF、Word（.docx/.doc），单个文件不超过 20 MB。"
           "识别结果需要您逐条确认后才会保存，并用于课堂评价、测量记录和课堂报告。",
           element_id="courseTaskHelp", label="课程任务文件")
    + '</span>'
    '<p class="course-task-lead">上传本课教学任务/教案，系统将自动识别课程目标</p>'
    '<div class="course-task-row"><input class="file-input-accessible" id="courseTaskFile" type="file" '
    'accept=".pdf,.docx,.doc,application/pdf,application/msword,'
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document" aria-describedby="courseTaskHelp" />'
    '<label class="button" for="courseTaskFile" id="courseTaskPick">选择课程任务文件</label>'
    '<span class="course-task-file-name" id="courseTaskFileName" aria-live="polite">尚未选择文件</span></div>'
    '<div class="course-task-status" id="courseTaskStatus" role="status" aria-live="polite">'
    '<span class="rx-badge rx-badge-neutral">尚未上传课程任务</span>'
    '<span class="course-task-sub">读取课程后显示本课课程任务的确认状态。</span></div>'
    '<p class="field-error" id="courseTaskError" role="alert" hidden></p></div>'
)

_DRAWER_BODY = (
    '<div class="ct-notice" id="ctNotice" role="status" hidden></div>'
    '<div class="ct-error" id="ctError" role="alert" tabindex="-1" hidden></div>'
    '<section class="ct-block" aria-labelledby="ctBasicTitle"><h3 id="ctBasicTitle">课程信息</h3>'
    '<div class="ct-grid"><div class="field"><label for="ctCourseName">课程名称</label>'
    '<input id="ctCourseName" maxlength="200" placeholder="识别不到时请手工填写" /></div>'
    '<div class="field"><label for="ctLessonDate">上课日期</label><input id="ctLessonDate" type="date" />'
    '<small class="ct-help" id="ctLessonDateRaw"></small></div></div>'
    '<p class="ct-help" id="ctCourseIdLine"></p></section>'
    '<section class="ct-block" aria-labelledby="ctGoalsTitle"><div class="ct-block-head"><h3 id="ctGoalsTitle">课程任务目标'
    ' <span class="ct-count" id="ctGoalCount">0</span></h3><button class="button quiet" type="button" id="ctAddGoal">'
    '新增目标</button></div><p class="ct-help">逐条核对目标描述、通过标准、测量条件和评分维度建议；目标中不要出现学生姓名。</p>'
    '<div class="ct-goals" id="ctGoals"></div></section>'
    '<section class="ct-block" aria-labelledby="ctOtherTitle"><h3 id="ctOtherTitle">其他内容 '
    '<span class="ct-count" id="ctOtherCount">0</span></h3>'
    '<p class="ct-help">文档中未归入目标的段落、表格单元格和字段，按原文完整列出；可一键加入为目标或备注。</p>'
    '<div class="ct-other" id="ctOther"></div></section>'
    '<section class="ct-block" aria-labelledby="ctNotesTitle"><div class="ct-block-head"><h3 id="ctNotesTitle">备注 '
    '<span class="ct-count" id="ctNoteCount">0</span></h3><button class="button quiet" type="button" id="ctAddNote">'
    '新增备注</button></div><div class="ct-notes" id="ctNotes"></div></section>'
    '<label class="ct-check"><input type="checkbox" id="ctReviewed" /> 我已逐条核对识别结果，目标中没有学生姓名或个人联系方式</label>'
    '<div class="ct-actions"><button class="button" type="button" id="ctCancel">取消</button>'
    '<button class="button primary" type="button" id="ctConfirm">确认并保存课程任务</button></div>'
)

COURSE_TASK_DRAWER_HTML = drawer(
    _DRAWER_BODY, title="课程任务目标确认", element_id="courseTaskDrawer", title_id="courseTaskDrawerTitle",
    subtitle="系统已从文件中识别课程目标，请编辑、删除或新增后确认保存。", close_id="ctClose",
)

COURSE_TASK_STYLE = r"""
.course-task-field .course-task-lead { margin:2px 0 8px; color:var(--muted); font-size:13px; }
.course-task-row { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
.course-task-file-name { color:var(--muted); font-size:13px; overflow-wrap:anywhere; }
.course-task-status { display:flex; align-items:center; gap:8px 12px; flex-wrap:wrap; margin-top:10px; padding:10px 12px; border:1px dashed var(--line-strong); border-radius:8px; background:#f7faff; }
.course-task-status[data-state="confirmed"] { border-style:solid; border-color:#9fd3bd; background:#f3fbf7; }
.course-task-status a, .course-task-status button { font-size:13px; }
.course-task-sub { color:var(--muted); font-size:13px; }
.course-task-goals { flex-basis:100%; margin:4px 0 0; padding-left:18px; color:var(--ink,#172b4d); font-size:13px; }
#courseTaskDrawer { width:min(760px,100vw); }
#courseTaskDrawer .rx-drawer-body { overflow-y:auto; padding:16px 24px 24px; }
.ct-block { margin:0 0 18px; padding:0 0 14px; border-bottom:1px solid var(--line); }
.ct-block h3 { margin:0 0 8px; font-size:16px; }
.ct-block-head { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.ct-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
.ct-help { margin:4px 0 8px; color:var(--muted); font-size:12px; }
.ct-count { display:inline-block; min-width:22px; padding:0 6px; border-radius:8px; background:#e8f0fb; color:#1f5fbf; font-size:12px; text-align:center; }
.ct-goal { margin:0 0 12px; padding:12px; border:1px solid var(--line); border-left:4px solid #1f5fbf; border-radius:8px; background:#fff; }
.ct-goal-head { display:flex; align-items:center; gap:10px; margin-bottom:8px; }
.ct-goal-head input { width:96px; font-weight:700; }
.ct-goal-head .ct-src { color:var(--muted); font-size:12px; flex:1; }
.ct-goal-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px; }
.ct-goal-grid .wide { grid-column:1/-1; }
.ct-goal textarea, .ct-note textarea { width:100%; min-height:56px; resize:vertical; }
.ct-goal label, .ct-note label { font-size:12px; font-weight:700; color:var(--blue-deep,#174a96); }
.ct-invalid { border-color:var(--danger,#c0392b) !important; box-shadow:0 0 0 2px rgba(192,57,43,.15); }
.ct-field-error { margin:4px 0 0; color:var(--danger,#c0392b); font-size:12px; }
.ct-other-item { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; align-items:start; padding:8px 10px; border:1px solid var(--line); border-radius:8px; margin-bottom:6px; background:#fbfcfe; }
.ct-other-item[data-used="1"] { opacity:.55; }
.ct-other-text { white-space:pre-wrap; overflow-wrap:anywhere; font-size:13px; }
.ct-other-meta { display:block; color:var(--muted); font-size:12px; margin-top:2px; }
.ct-other-actions { display:flex; gap:6px; flex-wrap:wrap; }
.ct-other-actions button { font-size:12px; min-height:30px; padding:0 8px; }
.ct-sensitive { color:#a15c00; font-weight:700; }
.ct-note { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; margin-bottom:8px; }
.ct-check { display:flex; gap:8px; align-items:center; margin:8px 0 14px; font-weight:700; }
.ct-actions { display:flex; justify-content:flex-end; gap:10px; position:sticky; bottom:0; padding:12px 0 0; background:#fff; }
.ct-notice { margin:0 0 12px; padding:10px 12px; border-radius:8px; background:#fff7e6; color:#7a4b00; font-size:13px; }
.ct-error { margin:0 0 12px; padding:10px 12px; border-radius:8px; background:#fdecea; color:#a12a1d; font-size:13px; }
.ct-empty { padding:12px; border:1px dashed var(--line); border-radius:8px; color:var(--muted); font-size:13px; }
.task-course-task { color:#1d7a55; font-weight:700; }
@media (max-width:720px) { .ct-grid, .ct-goal-grid { grid-template-columns:1fr; } #courseTaskDrawer .rx-drawer-body { padding:12px 14px 18px; } }
"""

# Plain (non f-string) JavaScript appended to the upload page script.
COURSE_TASK_UPLOAD_SCRIPT = r"""
const CT_API='/api/v1/demo2';
const CT_MAX_BYTES=20*1024*1024;
let ctDraft=null, ctBusy=false, ctUsedOther=new Set();
function ctEl(id){try{return byId(id);}catch(_){return null;}}
function ctCourseId(){const node=ctEl('courseId');return node?String(node.value||'').trim():'';}
function ctSummary(){return workspace&&workspace.course_task&&String(workspace.course_id||'')===ctCourseId()?workspace.course_task:null;}
function courseTaskBadge(){const s=ctSummary();return s?`<span class="task-course-task">课程任务已确认（版本 ${Number(s.version)}）</span>`:'';}
function renderCourseTaskStatus(){
  const box=ctEl('courseTaskStatus');if(!box)return;const s=ctSummary();
  if(!s){box.dataset.state='empty';box.innerHTML='<span class="rx-badge rx-badge-neutral">尚未上传课程任务</span><span class="course-task-sub">'+(workspace?'上传后系统识别目标，确认后用于本课评价、测量与报告。':'读取课程后显示本课课程任务的确认状态。')+'</span>';return;}
  const id=encodeURIComponent(s.course_task_doc_id);
  const goals=(s.goals||[]).slice(0,6).map(g=>`<li><strong>${esc(g.goal_code)}</strong> ${esc(g.description)}</li>`).join('');
  box.dataset.state='confirmed';
  box.innerHTML=`<span class="rx-badge rx-badge-success" id="courseTaskConfirmedBadge">课程任务已确认（版本 ${Number(s.version)}）</span><span class="course-task-sub">${Number(s.goal_count)} 个目标${s.version_count>1?` · 共 ${Number(s.version_count)} 个版本，历史版本保留`:''}</span><a href="${CT_API}/course-tasks/original?course_task_doc_id=${id}" download>下载原件</a><a href="${CT_API}/course-tasks/summary?course_task_doc_id=${id}" download>目标摘要</a>${goals?`<ol class="course-task-goals">${goals}</ol>`:''}`;
}
function ctShowFieldError(text){const node=ctEl('courseTaskError');if(!node)return;node.textContent=text||'';node.hidden=!text;}
async function ctRequest(path,options){
  let response;
  try{response=await fetch(path,{credentials:'same-origin',cache:'no-store',...(options||{})});}
  catch(_){const e=new Error('网络连接失败，请检查网络后重试。');e.status=0;throw e;}
  const payload=await response.json().catch(()=>({}));
  if(response.status===401){const e=new Error('登录已过期，请重新登录后再上传课程任务。');e.status=401;throw e;}
  if(!response.ok||payload.ok===false||payload.error){const e=new Error(payload.error?.message||'请求失败，请稍后重试。');e.status=response.status;e.code=payload.error?.code||'';e.field=payload.error?.field||'';throw e;}
  return payload;
}
function ctSetBusy(value,label){ctBusy=value;const pick=ctEl('courseTaskPick');const input=ctEl('courseTaskFile');if(input)input.disabled=value;if(pick)pick.textContent=label||'选择课程任务文件';const confirm=ctEl('ctConfirm');if(confirm){confirm.disabled=value;confirm.textContent=value&&ctDraft?'正在保存…':'确认并保存课程任务';}}
async function ctUpload(file){
  ctShowFieldError('');
  if(!file)return;
  const name=String(file.name||'');const ext=name.toLowerCase().slice(name.lastIndexOf('.'));
  if(!['.pdf','.docx','.doc'].includes(ext)){ctShowFieldError('仅支持上传 PDF、Word（.docx / .doc）格式的课程任务文件。');return;}
  if(file.size>CT_MAX_BYTES){ctShowFieldError('课程任务文件不能超过 20 MB。');return;}
  if(!file.size){ctShowFieldError('文件为空，请重新选择。');return;}
  if(!ctCourseId()){ctShowFieldError('请先读取课程工作区，再上传课程任务文件。');return;}
  const nameNode=ctEl('courseTaskFileName');if(nameNode)nameNode.textContent=name;
  ctSetBusy(true,'正在识别文件…');
  try{
    const form=new FormData();form.append('purpose','course_task');form.append('file',file,name);
    const parsed=await ctRequest(CT_API+'/documents/parse',{method:'POST',body:form});
    const drafted=await ctRequest(CT_API+'/course-tasks/draft',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({parse_id:parsed.result.parse_id})});
    ctDraft=drafted.draft;ctDraft.goals=(ctDraft.goals||[]).map(g=>({...g}));ctDraft.notes=[];ctUsedOther=new Set();
    ctOpenDrawer();
  }catch(error){ctShowFieldError(error.message);}
  finally{ctSetBusy(false);const input=ctEl('courseTaskFile');if(input)input.value='';}
}
function ctDimensionOptions(selected){return (ctDraft.dimensions||[]).map(d=>`<option value="${esc(d.id)}"${d.id===selected?' selected':''}>${esc(d.label)}</option>`).join('');}
function ctSourceText(g){const s=g.source||{};if(s.manual)return '教师新增';const parts=[];if(s.page)parts.push(`第 ${s.page} 页`);if(s.cell_id)parts.push('表格');else if(s.paragraph_index)parts.push(`第 ${s.paragraph_index} 段`);return parts.length?'来自原文 '+parts.join(' · '):'来自原文';}
function ctGoalHtml(g,i){
  const f=(key,label,rows,wide,required)=>`<div class="field${wide?' wide':''}"><label for="ctGoal_${i}_${key}">${label}${required?' *':''}</label><textarea id="ctGoal_${i}_${key}" data-goal="${i}" data-key="${key}" rows="${rows}" maxlength="1000">${esc(g[key]||'')}</textarea></div>`;
  return `<article class="ct-goal" data-goal-card="${i}"><div class="ct-goal-head"><input id="ctGoal_${i}_goal_code" data-goal="${i}" data-key="goal_code" maxlength="8" value="${esc(g.goal_code||'')}" aria-label="目标编号"><span class="ct-src">${esc(ctSourceText(g))}</span><button class="button quiet" type="button" data-ct-remove-goal="${i}">删除</button></div><div class="ct-goal-grid">${f('description','目标描述',2,true,true)}${f('pass_criteria','通过标准',2,false,false)}${f('measurement_conditions','测量条件',2,false,false)}${f('evaluation_criteria','评价标准（选填）',2,false,false)}<div class="field"><label for="ctGoal_${i}_rubric_dimension">对应评分维度建议</label><select id="ctGoal_${i}_rubric_dimension" data-goal="${i}" data-key="rubric_dimension">${ctDimensionOptions(g.rubric_dimension||'process')}</select></div></div></article>`;
}
function ctSyncFromDom(){
  if(!ctDraft)return;
  ctDraft.goals.forEach((g,i)=>{['goal_code','description','pass_criteria','measurement_conditions','evaluation_criteria','rubric_dimension'].forEach(key=>{const node=ctEl(`ctGoal_${i}_${key}`);if(node)g[key]=node.value;});});
  ctDraft.notes.forEach((n,i)=>{const node=ctEl(`ctNote_${i}`);if(node)n.text=node.value;});
  const name=ctEl('ctCourseName'),date=ctEl('ctLessonDate');if(name)ctDraft.course_name=name.value;if(date)ctDraft.lesson_date=date.value;
}
function ctNextCode(){const used=new Set(ctDraft.goals.map(g=>String(g.goal_code||'')));for(let n=1;n<1000;n++){const code='G-'+String(n).padStart(2,'0');if(!used.has(code))return code;}return 'G-999';}
function ctRender(){
  if(!ctDraft)return;
  const goals=ctEl('ctGoals');if(goals)goals.innerHTML=ctDraft.goals.length?ctDraft.goals.map(ctGoalHtml).join(''):'<div class="ct-empty">文件中没有识别到课程目标，请点击「新增目标」手工填写，或从下方「其他内容」加入。</div>';
  const other=ctEl('ctOther');const items=ctDraft.other_content||[];
  if(other)other.innerHTML=items.length?items.map((o,i)=>`<div class="ct-other-item" data-used="${ctUsedOther.has(i)?1:0}"><div><span class="ct-other-text">${esc(o.text)}</span><span class="ct-other-meta">${o.page?`第 ${Number(o.page)} 页 · `:''}${o.kind==='table_cell'?'表格单元格':o.kind==='field'?'已识别字段':'段落'}${o.sensitive?` · <span class="ct-sensitive">含${esc((o.sensitive_labels||['个人信息']).join('、'))}，请勿加入</span>`:''}${ctUsedOther.has(i)?' · 已加入':''}</span></div><div class="ct-other-actions"><button type="button" class="button quiet" data-ct-other-goal="${i}">加入为目标</button><button type="button" class="button quiet" data-ct-other-note="${i}">加入备注</button></div></div>`).join(''):'<div class="ct-empty">文件内容已全部归入课程信息或目标。</div>';
  const notes=ctEl('ctNotes');if(notes)notes.innerHTML=ctDraft.notes.length?ctDraft.notes.map((n,i)=>`<div class="ct-note"><div class="field"><label for="ctNote_${i}">备注 ${i+1}</label><textarea id="ctNote_${i}" maxlength="2000">${esc(n.text||'')}</textarea></div><button class="button quiet" type="button" data-ct-remove-note="${i}">删除</button></div>`).join(''):'<div class="ct-empty">暂无备注。可从「其他内容」加入，或点击「新增备注」。</div>';
  const set=(id,value)=>{const node=ctEl(id);if(node)node.textContent=String(value);};
  set('ctGoalCount',ctDraft.goals.length);set('ctOtherCount',items.length);set('ctNoteCount',ctDraft.notes.length);
}
function ctOpenDrawer(){
  const drawerNode=ctEl('courseTaskDrawer'),backdrop=ctEl('courseTaskDrawerBackdrop');if(!drawerNode)return;
  const name=ctEl('ctCourseName'),date=ctEl('ctLessonDate');
  if(name)name.value=ctDraft.course_name||(ctEl('courseName')?.value||'');
  if(date)date.value=ctDraft.lesson_date||'';
  const raw=ctEl('ctLessonDateRaw');if(raw)raw.textContent=ctDraft.lesson_date_text&&!ctDraft.lesson_date?`原文：${ctDraft.lesson_date_text}（无法识别为日期，请手工选择）`:'';
  const line=ctEl('ctCourseIdLine');if(line)line.textContent=`课程批次号：${ctCourseId()} · 文件共 ${Number(ctDraft.page_count||0)} 页 · 识别目标 ${ctDraft.goals.length} 条 · 其他内容 ${(ctDraft.other_content||[]).length} 条`;
  const notice=ctEl('ctNotice');if(notice){notice.textContent=ctDraft.notice||'';notice.hidden=!ctDraft.notice;}
  const error=ctEl('ctError');if(error){error.textContent='';error.hidden=true;}
  const reviewed=ctEl('ctReviewed');if(reviewed)reviewed.checked=false;
  ctRender();drawerNode.hidden=false;if(backdrop)backdrop.hidden=false;
  const title=ctEl('courseTaskDrawerTitle');if(title&&title.focus)title.focus();
}
function ctCloseDrawer(){const drawerNode=ctEl('courseTaskDrawer'),backdrop=ctEl('courseTaskDrawerBackdrop');if(drawerNode)drawerNode.hidden=true;if(backdrop)backdrop.hidden=true;}
function ctClearInvalid(){const root=ctEl('courseTaskDrawer');if(!root||!root.querySelectorAll)return;root.querySelectorAll('.ct-invalid').forEach(node=>{node.classList.remove('ct-invalid');node.removeAttribute('aria-invalid');});root.querySelectorAll('.ct-field-error').forEach(node=>node.remove());}
function ctMarkField(field,text){
  const map={course_name:'ctCourseName',lesson_date:'ctLessonDate'};let id=map[field]||'';
  const goal=/^goals\.(\d+)\.([a-z_]+)$/.exec(field||'');if(goal)id=`ctGoal_${goal[1]}_${goal[2]}`;
  const goalCard=/^goals\.(\d+)$/.exec(field||'');if(goalCard)id=`ctGoal_${goalCard[1]}_description`;
  const note=/^notes\.(\d+)$/.exec(field||'');if(note)id=`ctNote_${note[1]}`;
  const node=id?ctEl(id):null;if(!node)return false;
  node.classList.add('ct-invalid');node.setAttribute('aria-invalid','true');
  const tip=document.createElement('p');tip.className='ct-field-error';tip.textContent=text;node.insertAdjacentElement('afterend',tip);
  if(node.scrollIntoView)node.scrollIntoView({block:'center'});node.focus();return true;
}
function ctFail(text,field){const error=ctEl('ctError');if(error){error.textContent=text;error.hidden=false;}if(!(field&&ctMarkField(field,text))&&error&&error.focus)error.focus();}
function ctValidate(){
  if(!ctDraft.goals.length)return ['请至少保留一个课程任务目标。',''];
  const codes=new Set();
  for(let i=0;i<ctDraft.goals.length;i++){const g=ctDraft.goals[i];const code=String(g.goal_code||'').trim();
    if(!/^G-\d{2,3}$/.test(code))return [`第 ${i+1} 个目标的编号应为 G-01 这样的格式。`,`goals.${i}.goal_code`];
    if(codes.has(code))return [`目标编号 ${code} 重复，请修改。`,`goals.${i}.goal_code`];codes.add(code);
    if(!String(g.description||'').trim())return [`请填写 ${code} 的目标描述。`,`goals.${i}.description`];}
  for(let i=0;i<ctDraft.notes.length;i++){if(!String(ctDraft.notes[i].text||'').trim())return [`备注 ${i+1} 为空，请填写或删除。`,`notes.${i}`];}
  if(!ctEl('ctReviewed')?.checked)return ['请勾选「我已逐条核对识别结果」后再保存。',''];
  return null;
}
async function ctConfirm(){
  if(!ctDraft||ctBusy)return;ctSyncFromDom();ctClearInvalid();
  const problem=ctValidate();if(problem){ctFail(problem[0],problem[1]);return;}
  const current=ctSummary();
  const payload={parse_id:ctDraft.parse_id,course_id:ctCourseId(),course_name:String(ctDraft.course_name||'').trim(),lesson_date:ctDraft.lesson_date||'',
    goals:ctDraft.goals.map(g=>({goal_code:String(g.goal_code).trim(),description:g.description||'',pass_criteria:g.pass_criteria||'',measurement_conditions:g.measurement_conditions||'',evaluation_criteria:g.evaluation_criteria||'',rubric_dimension:g.rubric_dimension||'process',...(g.source?{source:g.source}:{})})),
    notes:ctDraft.notes.map(n=>({text:n.text})),expected_version:current?Number(current.version):0};
  ctSetBusy(true);
  try{
    const saved=await ctRequest(CT_API+'/course-tasks/confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const doc=saved.course_task;
    if(workspace&&String(workspace.course_id||'')===doc.course_id){workspace.course_task={course_task_doc_id:doc.course_task_doc_id,course_task_doc_short:doc.course_task_doc_short,version:doc.version,goal_count:doc.goal_count,course_name:doc.course_name,lesson_date:doc.lesson_date,confirmed_at:doc.confirmed_at,original_extension:doc.original_extension,goals:doc.goals.map(g=>({goal_code:g.goal_code,description:g.description})),version_count:doc.version};}
    ctDraft=null;ctCloseDrawer();renderCourseTaskStatus();if(typeof renderTasks==='function')renderTasks();
    const text=`课程任务已确认（版本 ${doc.version}），${doc.goal_count} 个目标将用于本课评价、测量与报告。`;
    if(window.RxUI&&RxUI.toast)RxUI.toast(text);else message(text,'success');
  }catch(error){
    if(error.code==='course_task_version_conflict'){ctFail(error.message+'（已有其他版本，请关闭后刷新课程工作区）','');}
    else ctFail(error.message,error.field);
  }finally{ctSetBusy(false);}
}
function ctSetup(){
  const input=ctEl('courseTaskFile');if(!input||!input.addEventListener)return;
  input.addEventListener('change',()=>ctUpload(input.files&&input.files[0]));
  const on=(id,handler)=>{const node=ctEl(id);if(node&&node.addEventListener)node.addEventListener('click',handler);};
  on('ctClose',()=>{ctCloseDrawer();});on('ctCancel',()=>{ctCloseDrawer();});on('ctConfirm',ctConfirm);
  const backdrop=ctEl('courseTaskDrawerBackdrop');if(backdrop&&backdrop.addEventListener)backdrop.addEventListener('click',ctCloseDrawer);
  on('ctAddGoal',()=>{ctSyncFromDom();ctDraft.goals.push({goal_code:ctNextCode(),description:'',pass_criteria:'',measurement_conditions:'',evaluation_criteria:'',rubric_dimension:'process',source:{manual:true}});ctRender();const node=ctEl(`ctGoal_${ctDraft.goals.length-1}_description`);if(node)node.focus();});
  on('ctAddNote',()=>{ctSyncFromDom();ctDraft.notes.push({text:''});ctRender();const node=ctEl(`ctNote_${ctDraft.notes.length-1}`);if(node)node.focus();});
  const drawerNode=ctEl('courseTaskDrawer');
  if(drawerNode&&drawerNode.addEventListener){
    drawerNode.addEventListener('click',event=>{
      const target=event.target&&event.target.closest?event.target.closest('button'):null;if(!target||!ctDraft)return;
      const d=target.dataset||{};
      if(d.ctRemoveGoal!==undefined){ctSyncFromDom();ctDraft.goals.splice(Number(d.ctRemoveGoal),1);ctRender();}
      else if(d.ctRemoveNote!==undefined){ctSyncFromDom();ctDraft.notes.splice(Number(d.ctRemoveNote),1);ctRender();}
      else if(d.ctOtherGoal!==undefined){ctSyncFromDom();const item=ctDraft.other_content[Number(d.ctOtherGoal)];ctDraft.goals.push({goal_code:ctNextCode(),description:String(item.text||'').slice(0,1000),pass_criteria:'',measurement_conditions:'',evaluation_criteria:'',rubric_dimension:'process',source:{page:item.page||'',kind:item.kind||''}});ctUsedOther.add(Number(d.ctOtherGoal));ctRender();}
      else if(d.ctOtherNote!==undefined){ctSyncFromDom();const item=ctDraft.other_content[Number(d.ctOtherNote)];ctDraft.notes.push({text:String(item.text||'').slice(0,2000)});ctUsedOther.add(Number(d.ctOtherNote));ctRender();}
    });
    drawerNode.addEventListener('keydown',event=>{if(event.key==='Escape')ctCloseDrawer();});
  }
  renderCourseTaskStatus();
}
try{ctSetup();}catch(_){}
"""
