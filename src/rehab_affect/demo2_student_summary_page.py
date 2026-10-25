"""Authorized summaries and automatic course history; no storage or inference here."""
from __future__ import annotations

from typing import Any

from .demo2_portal import _BOOK_ICON, _WORKSPACE_STYLE, _account_payload, _document


DOMAINS = (("cognition", "认知"), ("communication", "沟通"), ("motor", "运动"),
           ("sensory", "感知"), ("social_adaptation", "社会适应"))
STYLE = _WORKSPACE_STYLE + """
.skip-link:not(:focus-visible){width:1px;height:1px;padding:0;margin:0;overflow:hidden;clip-path:inset(50%);opacity:0;pointer-events:none;transform:none}
.skip-link:focus-visible{position:fixed;top:8px;left:8px;width:auto;height:auto;max-width:calc(100vw - 16px);padding:10px 14px;clip-path:none;opacity:1;pointer-events:auto;transform:none}
.header-inner,.page-shell{width:min(1120px,calc(100% - 32px))}.site-header{position:static}
h1{font-size:26px}h2{font-size:19px}h3{font-size:16px}.lead{font-size:14px}
.summary-nav,.actions{display:flex;flex-wrap:wrap;gap:10px;align-items:center}.summary-nav{margin-left:auto}
.summary-section{padding:24px 0;border-top:1px solid var(--line)}.summary-section p{overflow-wrap:anywhere}
.summary-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:28px}.summary-grid>*{min-width:0}
.summary-form,.summary-form fieldset{display:grid;gap:16px}.summary-form fieldset{border:0;padding:0;margin:0;min-width:0}
.summary-form fieldset:disabled{opacity:.65}.field{min-width:0}.field label{font-size:14px}
input,select,textarea{width:100%;max-width:100%;min-width:0;font:inherit}textarea{min-height:96px;resize:vertical;border:1px solid var(--line-strong);border-radius:5px;padding:10px}
.summary-check{display:flex;gap:10px;align-items:flex-start;font-size:14px;line-height:1.7;min-height:44px;padding:10px 0}
.summary-check input{width:18px;height:18px;min-height:18px;flex:0 0 18px;margin-top:3px;padding:0}
.summary-check span{min-width:0;overflow-wrap:anywhere}.summary-note{font-size:13px;line-height:1.8;color:var(--muted)}
.summary-gate{border-left:3px solid var(--blue);padding:12px 16px;background:var(--blue-pale);margin:16px 0}
.summary-record{padding:16px 0;border-bottom:1px solid var(--line)}.summary-record p,.summary-record pre{white-space:pre-wrap;overflow-wrap:anywhere}
.lesson-summary{border-left:3px solid var(--blue);padding:12px 16px;background:var(--blue-pale);margin-top:14px}.lesson-summary h4{margin:0 0 8px;font-size:15px}.lesson-summary ul{margin:8px 0 0;padding-left:20px}.lesson-summary li{margin:5px 0}.lesson-summary-note{color:var(--muted);font-size:12px}.trend-empty{color:var(--muted);font-size:13px}.trend-grid{display:grid;gap:12px;margin-top:12px}.trend-point{padding:12px 0;border-bottom:1px solid var(--line)}.trend-point header{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font-weight:600}.trend-metric{display:grid;grid-template-columns:150px minmax(80px,1fr) 54px;gap:10px;align-items:center;margin-top:8px;font-size:13px}.trend-bar{height:8px;background:#e6edf4;border-radius:4px;overflow:hidden}.trend-bar span{display:block;height:100%;background:var(--blue);border-radius:4px}.trend-caveat{color:var(--muted);font-size:12px;line-height:1.7;margin:14px 0 0}
.summary-record h3{margin-bottom:10px}.summary-preview{border-left:3px solid var(--success);padding-left:20px}
pre{font:13px/1.7 Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere;max-width:100%;margin:12px 0}
.search-form{display:flex;flex-wrap:wrap;gap:12px;align-items:end}.search-form .field{flex:1 1 240px}
.summary-pagination{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-top:18px}
.summary-pagination button{width:44px;height:44px;padding:0;font-size:20px;flex:0 0 44px}
.summary-pagination span{font-size:13px;overflow-wrap:anywhere}.button{white-space:normal;overflow-wrap:anywhere;border-radius:5px}
.button.danger{color:var(--danger);border-color:#d8b2af}.page-message{margin:16px 0}
[hidden]{display:none!important}:focus-visible{outline:3px solid var(--blue);outline-offset:3px}
@media(max-width:720px){.summary-grid{grid-template-columns:minmax(0,1fr)}.header-inner{display:grid;gap:12px}.summary-nav{margin:0}.summary-section{padding:20px 0}h1{font-size:23px}}
"""


def _shell(content: str, *, admin: bool = False) -> str:
    back, label = ("/demo2/admin", "返回公司后台") if admin else ("/demo2/students", "返回本校名册")
    return f"""<header class="site-header"><div class="header-inner"><a class="brand" href="{back}">{_BOOK_ICON}<span class="brand-copy"><strong>RehabAffect</strong><span>授权学生摘要</span></span></a><nav class="summary-nav" aria-label="摘要导航"><a class="button quiet" href="{back}">{label}</a><button class="button" id="reloadButton" type="button">重新读取</button></nav></div></header>
<main class="page-shell" id="mainContent" tabindex="-1"><div class="page-message" id="pageMessage" role="alert" tabindex="-1"></div>{content}<footer class="summary-section summary-note">仅限实际授权覆盖的教育支持摘要，不授予研究或模型训练权限。校方资料不会自动导入。本摘要不作诊断、专业结论或预测，也不代表预测能力已获验证。公开编号不等于匿名化，自由文字仍可能导致再识别；请勿录入姓名、联系方式或其他身份线索。撤回不代表已删除下载副本或所有备份。原视频仍按原有 60 天策略保存；本摘要授权与原视频授权分开管理。</footer></main>"""


COMMON = r"""
const ACCOUNT=__ACCOUNT__,API='/api/v1/demo2/student-summaries',byId=id=>document.getElementById(id);
const domainLabels={cognition:'认知',communication:'沟通',motor:'运动',sensory:'感知',social_adaptation:'社会适应'};
const levelLabels={unknown:'未记录',with_support:'需支持',developing:'发展中',independent:'独立完成'};
let workspace=null,loading=false,writing=false,uncertain=false,dirty=false;
const make=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=String(text??'');return node;};
function notice(text,error=false){const node=byId('pageMessage');node.textContent=text;node.className='page-message visible '+(error?'error':'success');}
function today(){const parts=new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());const p=Object.fromEntries(parts.map(x=>[x.type,x.value]));return p.year+'-'+p.month+'-'+p.day;}
function dayAfter(days){const date=new Date(today()+'T00:00:00Z');date.setUTCDate(date.getUTCDate()+days);return date.toISOString().slice(0,10);}
function beijingTime(value){
  if(typeof value!=='string'||!/T.*(?:Z|[+-][0-9]{2}:[0-9]{2})$/.test(value))return '未返回';
  const date=new Date(value);if(!Number.isFinite(date.getTime()))return '未返回';
  const parts=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(date);
  const p=Object.fromEntries(parts.map(part=>[part.type,part.value]));return p.year+'-'+p.month+'-'+p.day+' '+p.hour+':'+p.minute;
}
function shortCourseId(value){return value.length>20?value.slice(0,11)+'...'+value.slice(-4):value;}
function future(value){const date=String(value||'');if(!/^[0-9]{4}-[0-9]{2}-[0-9]{2}(?:T.*)?$/.test(date))return false;const time=Date.parse(date.length===10?date+'T00:00:00+08:00':date);return Number.isFinite(time)&&time>Date.now();}
async function request(path,payload){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000);
  try{
    const response=await fetch(API+path,{credentials:'same-origin',cache:'no-store',signal:controller.signal,
      ...(payload===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})});
    if(response.status===401||response.status===403){const error=new Error(response.status===401?'登录已过期，请重新登录。':'当前账号无权访问这些摘要。');error.denied=true;throw error;}
    const data=await response.json();
    if(!data||typeof data!=='object'||Array.isArray(data))throw new Error('返回数据不完整。');
    if(!response.ok||data.ok===false||data.error){const messages={identifiers_not_permitted:'学习目标或支持方法含已知身份线索，请删除姓名或编号后重新核对。',sensitive_text_not_permitted:'仅可录入无身份线索的教学目标与支持方法，请核对选定内容。',authorization_exists:'请先撤回现有授权，再登记新授权。',measurement_stale:'测量记录已过期、撤回或失效，请重新核对记录 ID。',measurement_unavailable:'测量记录不可用，请核对是否属于本学生。'};throw new Error(response.status===410?'授权已到期或撤回，请重新读取。':messages[data.error?.code]||'请求未完成，请重新读取后核对。');}
    return data;
  }catch(error){if(error.name==='AbortError')throw new Error('请求超时，结果待核对，请重新读取。');if(error instanceof TypeError)throw new Error('网络连接失败，结果待核对，请重新读取。');throw error;}
  finally{clearTimeout(timer);}
}
function requireWorkspace(data){if(!data.workspace||typeof data.workspace!=='object'||Array.isArray(data.workspace))throw new Error('工作区数据不完整。');return data.workspace;}
function showSnapshots(target,records,adminView=false){
  const list=byId(target);list.replaceChildren();
  if(!records.length){list.appendChild(make('p','尚无已保存摘要。'));return;}
  for(const row of records){
    const article=make('article');article.className='summary-record';
    article.appendChild(make('h3',row.recorded_on||'日期未返回'));
    article.appendChild(make('p','学习目标：'+String(row.learning_goals||'未记录')));
    article.appendChild(make('p','支持方法：'+String(row.support_methods||'未记录')));
    for(const [key,label] of Object.entries(domainLabels))article.appendChild(make('p',label+'：'+(levelLabels[row.domains?.[key]]||'未记录')));
    const provenance=safeProvenance(row.provenance);
    if(row.measurement!=null&&provenance.source_status!=='withheld')article.appendChild(make('p','已关联课堂观察：'+JSON.stringify(safeMeasurement(row.measurement))));
    const sourceStatusLabels={withheld:'原测量已失效，仅保留教师核对摘要',current:'原测量已核验，当前有效',manual_reviewed:'教师已核对摘要，未关联测量记录'};
    if(provenance.source_status)article.appendChild(make('p',sourceStatusLabels[provenance.source_status]));
    const sourceLabels={manual_pedagogic_summary:'教师核对教学摘要',classroom_observation:'课堂观察',video_review:'视频复核'};
    if(provenance.source_type)article.appendChild(make('p','来源：'+sourceLabels[provenance.source_type]+' · 规则 '+String(provenance.rule_version||'未返回')+' · 日期 '+String(provenance.source_date||'未返回')));
    article.appendChild(make('p',row.reviewed===true?'教师已复核':'教师复核状态未确认'));
    if(!adminView&&row.source_ref)article.appendChild(make('p','校内记录来源：'+row.source_ref));
    list.appendChild(article);
  }
}
function safeMeasurement(value){
  // Only structured scalar observation fields; never pass through free-text source/identity fields.
  if(!value||typeof value!=='object'||Array.isArray(value))return {};
  const numeric=(obj,keys)=>Object.fromEntries(keys.filter(key=>obj&&Object.hasOwn(obj,key)&&(obj[key]===null||typeof obj[key]==='number'&&Number.isFinite(obj[key]))).map(key=>[key,obj[key]]));
  const flags=Object.fromEntries(['passed','insufficient_evidence'].filter(key=>typeof value.assessment?.[key]==='boolean').map(key=>[key,value.assessment[key]]));
  return {...numeric(value,['opportunities','observed']),scores:numeric(value.scores,['accuracy','independence','consistency','transfer']),assessment:{...numeric(value.assessment,['overall_score','provisional_score','confidence']),...flags}};
}
function safeProvenance(value){
  if(!value||typeof value!=='object'||Array.isArray(value))return {};
  const result={};
  if(['manual_pedagogic_summary','classroom_observation','video_review','automatic_course_archive'].includes(value.source_type))result.source_type=value.source_type;
  if(Number.isInteger(value.source_version)&&value.source_version>=0)result.source_version=value.source_version;
  if(typeof value.rule_version==='string'&&value.rule_version.length<=128)result.rule_version=value.rule_version;
  if(typeof value.source_date==='string'&&/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(value.source_date))result.source_date=value.source_date;
  if(['withheld','current','manual_reviewed','pending_review','technical_only','historical_reviewed'].includes(value.source_status))result.source_status=value.source_status;
  if(value.identity_scope==='confirmed_sample_frame')result.identity_scope=value.identity_scope;
  for(const key of ['whole_lesson_tracking','scene_metrics_attributed_to_student','live_evidence_available'])if(value[key]===false)result[key]=false;
  return result;
}
function safeLessonSummary(value){
  if(!value||typeof value!=='object'||Array.isArray(value))return null;
  const text=(item,max)=>typeof item==='string'&&item.length<=max?item:null;
  if(text(value.title,120)===null||text(value.summary,2000)===null||value.source_type!=='automatic_course_archive'||value.source_status!=='machine_observation_draft'||value.teacher_review_status!=='not_reviewed')return null;
  const list=(item,max,count)=>Array.isArray(item)&&item.length<=count&&item.every(v=>typeof v==='string'&&v.length<=max)?item:[];
  const sample=Number.isInteger(value.sample_count)&&value.sample_count>0&&value.sample_count<=1000?value.sample_count:null;
  if(sample===null)return null;
  const times=Array.isArray(value.key_times_sec)&&value.key_times_sec.length<=5&&value.key_times_sec.every(v=>typeof v==='number'&&Number.isFinite(v)&&v>=0)?value.key_times_sec:[];
  const result={title:value.title,summary:value.summary,key_findings:list(value.key_findings,500,4),support_suggestions:list(value.support_suggestions,500,3),sample_count:sample,key_times_sec:times,source_type:value.source_type,source_status:value.source_status,teacher_review_status:'not_reviewed',archive_scope:text(value.archive_scope,500)||'仅保存本节课总结，不保存逐时刻状态。'};
  return result;
}
function safeTrendPoint(value){
  if(!value||typeof value!=='object'||Array.isArray(value)||value.source_status!=='machine_observation_draft')return null;
  const sample=Number.isInteger(value.sample_count)&&value.sample_count>0&&value.sample_count<=1000?value.sample_count:null;
  if(sample===null)return null;
  const numeric={};
  for(const key of ['participation_rate','attention_oriented_rate','interaction_rate'])if(typeof value[key]==='number'&&Number.isFinite(value[key])&&value[key]>=0&&value[key]<=1)numeric[key]=value[key];
  if(Object.keys(numeric).length!==3)return null;
  return {...numeric,sample_count:sample,source_status:value.source_status,note:typeof value.note==='string'&&value.note.length<=500?value.note:'仅为已确认采样点中的可见线索比例，不是学习成绩或教育评分。'};
}
function historicalCourse(row){return row.reviewed===true&&row.status==='historical_reviewed'&&row.provenance?.source_status==='historical_reviewed'&&row.live_evidence_available!==true&&row.provenance?.live_evidence_available!==true&&(row.live_evidence_available===false||row.provenance?.live_evidence_available===false);}
function safeCourseHistory(value){
  if(value===undefined)return []; // Older authorizations do not opt into automatic archiving.
  if(!Array.isArray(value))throw new Error('课程历史数据不完整，请重新读取。');
  const date=value=>typeof value==='string'&&/^[0-9]{4}-[0-9]{2}-[0-9]{2}(?:T[0-9:.+Z-]+)?$/.test(value)&&Number.isFinite(Date.parse(value))?value:null;
  return value.map(row=>{
    if(!row||typeof row.entry_id!=='string'||!row.entry_id||row.entry_id.length>128||!['pending_review','reviewed','source_withheld','historical_reviewed'].includes(row.status))throw new Error('课程编号或状态不完整，请重新读取。');
    const provenance=safeProvenance(row.provenance),current=row.reviewed===true&&row.status==='reviewed'&&provenance.source_status==='current';
    const historical=historicalCourse(row),measurementStatus=historical?'historical_reviewed':'current';
    const contradictoryEvidence=row.live_evidence_available===true||row.provenance?.live_evidence_available===true;
    if(contradictoryEvidence)delete provenance.live_evidence_available;
    if(row.measurements!==undefined&&!Array.isArray(row.measurements))throw new Error('课程测量数据不完整，请重新读取。');
    const media={};
    if(typeof row.media?.duration_sec==='number'&&Number.isFinite(row.media.duration_sec)&&row.media.duration_sec>=0)media.duration_sec=row.media.duration_sec;
    if(typeof row.media?.has_audio==='boolean')media.has_audio=row.media.has_audio;
    const lessonSummary=safeLessonSummary(row.lesson_summary),trendPoint=safeTrendPoint(row.trend_point);
    return {entry_id:row.entry_id,recorded_on:date(row.recorded_on),date_basis:['upload_date','lesson_date'].includes(row.date_basis)?row.date_basis:null,
      revision:Number.isInteger(row.revision)&&row.revision>=1?row.revision:null,status:row.status,reviewed:row.reviewed===true,media,
      measurements:current||historical?(row.measurements||[]).map(item=>{
        const source=safeProvenance(item?.provenance);
        const result={measurement:source.source_status===measurementStatus&&(!historical||item?.provenance?.live_evidence_available!==true)&&item?.reviewed!==false&&item?.measurement!=null?safeMeasurement(item.measurement):null,provenance:source};
        if(typeof item?.goal_key==='string'&&/^goal_[0-9a-f]{64}$/.test(item.goal_key))result.goal_key=item.goal_key;
        if(typeof item?.context_key==='string'&&/^ctx_[0-9a-f]{64}$/.test(item.context_key))result.context_key=item.context_key;
        return result;
      }):[],provenance,...(row.live_evidence_available===false&&!contradictoryEvidence?{live_evidence_available:false}:{}),
      ...(lessonSummary?{lesson_summary:lessonSummary}:{}),...(trendPoint?{trend_point:trendPoint}:{}),created_at:date(row.created_at),updated_at:date(row.updated_at)};
  });
}
function showLessonSummary(article,summary){
  if(!summary)return;
  const box=make('section');box.className='lesson-summary';box.appendChild(make('h4',summary.title));box.appendChild(make('p',summary.summary));
  if(summary.key_findings.length){box.appendChild(make('strong','本课关键发现'));const list=make('ul');for(const value of summary.key_findings)list.appendChild(make('li',value));box.appendChild(list);}
  if(summary.support_suggestions.length){box.appendChild(make('strong','支持建议'));const list=make('ul');for(const value of summary.support_suggestions)list.appendChild(make('li',value));box.appendChild(list);}
  box.appendChild(make('p','已纳入 '+summary.sample_count+' 个确认采样点的总结。'+(summary.key_times_sec.length?' 关键时间点：'+summary.key_times_sec.map(value=>Math.round(value)+' 秒').join('、')+'。':'')));
  const note=make('p',summary.archive_scope);note.className='lesson-summary-note';box.appendChild(note);
  article.appendChild(box);
}
function showObservationTrend(target,records){
  const list=byId(target);list.replaceChildren();
  const points=records.filter(row=>row.trend_point&&row.lesson_summary&&row.recorded_on);
  if(points.length<2){const note=make('p',points.length?'已累计 1 节带课堂线索总结的课程；再有至少 1 节同类课程后显示趋势。':'暂未累计足够的课堂线索总结；完成学生身份绑定和观察任务后才会计入。');note.className='trend-empty';list.appendChild(note);return;}
  const section=make('section');section.className='trend-grid';
  const labels={participation_rate:'参与线索',attention_oriented_rate:'注意方向朝向',interaction_rate:'互动 / 求助线索'};
  for(const point of points){const item=make('article');item.className='trend-point';const header=make('header');header.appendChild(make('span',point.recorded_on));header.appendChild(make('span','确认采样点 '+point.trend_point.sample_count+' 个'));item.appendChild(header);
    for(const [key,label] of Object.entries(labels)){const row=make('div');row.className='trend-metric';row.appendChild(make('span',label));const bar=make('div');bar.className='trend-bar';const fill=make('span');fill.style.width=Math.round(point.trend_point[key]*100)+'%';bar.appendChild(fill);row.appendChild(bar);row.appendChild(make('strong',Math.round(point.trend_point[key]*100)+'%'));item.appendChild(row);}section.appendChild(item);}
  const caveat=make('p',points[0].trend_point.note);caveat.className='trend-caveat';section.appendChild(caveat);list.appendChild(section);
}
function showCourseHistory(target,records){
  const list=byId(target);list.replaceChildren();
  if(!records.length){list.appendChild(make('p','尚无已归档课程。'));return;}
  const labels={pending_review:'本课身份已绑定 · 待复核',reviewed:'已复核',source_withheld:'依据失效',historical_reviewed:'历史已核准 · 原视频已按期清理，无法回看原始证据'};
  for(const row of records){
    const article=make('article');article.className='summary-record';article.setAttribute('data-entry-id',row.entry_id);article.setAttribute('data-course-status',row.status);
    const heading=make('h3','课程 '+shortCourseId(row.entry_id));heading.title=row.entry_id;article.appendChild(heading);
    article.appendChild(make('p',(row.date_basis==='lesson_date'?'课程日期：':row.date_basis==='upload_date'?'上传日期：':'日期依据未返回：')+(row.recorded_on||'未返回')));
    const historical=historicalCourse(row);
    const statusLabel=row.status==='historical_reviewed'&&!historical?'历史核准状态待确认':row.status==='reviewed'&&row.reviewed!==true?labels.pending_review:labels[row.status];
    article.appendChild(make('p','状态：'+statusLabel+' · 修订 '+(row.revision??'未返回')));
    article.appendChild(make('p','身份绑定仅经单帧人工确认，不代表整段持续追踪或全课学习状态已识别。'));
    const technical=[];
    if(row.media.duration_sec!==undefined)technical.push('时长 '+row.media.duration_sec+' 秒');
    if(row.media.has_audio!==undefined)technical.push(row.media.has_audio?'含音轨':'无音轨');
    article.appendChild(make('p','技术信息（不代表学生表现）：'+(technical.join(' · ')||'未返回')));
    if(row.status==='source_withheld'||row.provenance.source_status==='withheld')article.appendChild(make('p','原测量已失效，仅保留授权内课程记录，不展示分数。'));
    let displayed=false;
    const measurementLabels={opportunities:'机会次数',observed:'观察次数',accuracy:'准确性',independence:'独立性',consistency:'一致性',transfer:'迁移',overall_score:'总分',provisional_score:'暂定分数',confidence:'置信度',passed:'达标',insufficient_evidence:'证据不足'};
    for(const item of row.measurements){if(item.measurement!==null){
      const values={...item.measurement,...item.measurement.scores,...item.measurement.assessment};
      const parts=Object.entries(measurementLabels).filter(([key])=>values[key]!==undefined&&values[key]!==null).map(([key,label])=>label+'：'+(typeof values[key]==='boolean'?(values[key]?'是':'否'):values[key]));
      if(parts.length){article.appendChild(make('p',(historical?'历史已核准测量（非当前证据、非预测）：':'已核验测量（非预测）：')+parts.join(' · ')));displayed=true;}
    }}
    if(!displayed&&row.status!=='source_withheld')article.appendChild(make('p',row.status==='historical_reviewed'?'暂无可展示的已核准历史测量，不展示掌握度或得分。':'暂无当前有效的已复核测量，不展示掌握度或得分。'));
    showLessonSummary(article,row.lesson_summary);
    if(row.provenance.source_type==='automatic_course_archive')article.appendChild(make('p','来源：自动课程归档 · 规则 '+String(row.provenance.rule_version||'未返回')));
    article.appendChild(make('p','归档时间（北京时间）：'+beijingTime(row.created_at)+' · 更新时间：'+beijingTime(row.updated_at)));
    list.appendChild(article);
  }
}
function safePolicy(value){
  if(!value||value.purpose!=='educational_followup'||value.research!==false||value.training!==false||value.pseudonymous_not_anonymous!==true||value.expiry_exclusive!==true)throw new Error('导出用途、权限或期限策略不完整，请重新读取。');
  const result={purpose:value.purpose,research:false,training:false,pseudonymous_not_anonymous:true,expiry_exclusive:true};
  for(const key of ['raw_retention_days','maximum_authorization_days'])if(Number.isInteger(value[key])&&value[key]>0)result[key]=value[key];
  if(typeof value.free_text_requires_no_identifiers==='boolean')result.free_text_requires_no_identifiers=value.free_text_requires_no_identifiers;
  if(typeof value.stale_measurement_snapshots==='string'&&value.stale_measurement_snapshots.length<=128)result.stale_measurement_snapshots=value.stale_measurement_snapshots;
  if(value.cleanup_scope==='logical_database_blobs_only')result.cleanup_scope=value.cleanup_scope;
  return result;
}
window.addEventListener('beforeunload',event=>{if(dirty||writing){event.preventDefault();event.returnValue='';}});
"""


def render_student_summary_html(account: Any | None = None) -> str:
    domain_fields = "".join(
        f'<div class="field"><label for="domain_{key}">{label}</label><select id="domain_{key}" required>'
        + '<option value="unknown">未记录</option><option value="with_support">需支持</option><option value="developing">发展中</option><option value="independent">独立完成</option></select></div>'
        for key, label in DOMAINS
    )
    content = """<div class="page-heading"><div><h1>学生授权摘要</h1><p class="lead">教师核对的学习目标、支持方法与五领域课堂观察。</p></div></div>
<section class="summary-section"><h2 id="studentName">正在核对学生</h2><p id="studentMeta"></p><label class="summary-check"><input id="studentVerified" type="checkbox" disabled><span>已核对学生姓名、校内编号和班级，以下记录确属此学生。</span></label><p class="summary-gate" id="workspaceStatus" role="status">正在读取授权与记录。</p></section>
<section class="summary-section"><h2>自动课程归档</h2><p id="automaticStatus" role="status">正在读取自动归档状态。</p><p class="summary-note">开启后，本学生后续已绑定身份且处理完成的课程将在当前独立摘要授权范围和期限内自动归入同一档案，并向公司展示课程编号、日期、技术信息及当前有效的已复核测量。无需每课手填摘要。身份绑定仅经单帧人工确认，不代表整段持续追踪。技术信息不代表学生表现，未复核记录不显示掌握度或得分。不授予研究或训练权限。</p><form id="automaticForm" class="summary-form"><fieldset id="automaticFields" disabled><label class="summary-check"><input id="autoEnabled" type="checkbox"><span>自动归入后续课程</span></label><label class="summary-check"><input id="includeExisting" type="checkbox" disabled><span>同时补录本学生已有课程（默认不选；须在实际授权覆盖范围内）</span></label><p class="summary-note">旧授权不会自动开启。暂停新增归档不删除当前授权内已存历史；依据失效的分数仍会撤下。撤回摘要授权后，公司不可继续读取。</p><button class="button primary" id="automaticReviewButton" type="submit">核对归档设置</button></fieldset></form></section>
<section class="summary-section"><h2>课程历史</h2><div id="courseHistoryList">正在读取课程历史。</div></section>
<section class="summary-section"><h2>课堂线索趋势</h2><p class="summary-note">仅在累计至少两节带身份确认的课程后显示，用于查看可见线索变化，不替代教师判断或十分制评分。</p><div id="courseTrendList">正在读取趋势。</div></section>
<div class="summary-grid"><section class="summary-section"><h2>摘要归档授权</h2><p id="authorizationStatus" role="status">正在读取授权。</p><p class="summary-note">公司可读取本次明确核对的学习目标、支持方法、五领域观察及可选测量摘要。授权依据由校方保管，不包含姓名、原文资料或原视频授权。默认 60 天，最长 365 天；以实际授权的较短期限为准。</p>
<form id="authorizationForm" class="summary-form"><fieldset id="authorizationFields" disabled><div class="field"><label for="authorizationReference">授权依据 / 校内记录编号</label><input id="authorizationReference" required maxlength="500" autocomplete="off"></div><div class="field"><label for="validUntil">授权有效期至（北京时间）</label><input id="validUntil" type="date" required><small>所选日期 00:00 起失效。已有有效授权需先撤回后重新登记。</small></div><label class="summary-check"><input id="authorizationConfirmed" type="checkbox" required><span>已核实实际授权，允许公司在指定期限内读取上述选定摘要字段；不授予研究或训练权限。</span></label><button class="button primary" type="submit">核对授权内容</button></fieldset></form><button class="button danger" id="withdrawButton" type="button" disabled>撤回摘要授权</button></section>
<section class="summary-section"><h2>新增教师核对记录</h2><form id="snapshotForm" class="summary-form"><fieldset id="snapshotFields" disabled><div class="field"><label for="recordedOn">记录日期</label><input id="recordedOn" type="date" required></div><div class="field"><label for="sourceRef">校内记录来源 / 编号</label><input id="sourceRef" required maxlength="200" autocomplete="off"></div><div class="field"><label for="learningGoals">学习目标</label><textarea id="learningGoals" required maxlength="2000"></textarea></div><div class="field"><label for="supportMethods">支持方法</label><textarea id="supportMethods" required maxlength="2000"></textarea></div><div class="summary-grid">__DOMAINS__</div><div class="field"><label for="measurementId">已核验测量记录 ID（可选）</label><input id="measurementId" maxlength="128" autocomplete="off"><small>仅关联本学生已有的课堂观察；不是预测指标，不自动生成或补齐测量。</small></div><label class="summary-check"><input id="snapshotReviewed" type="checkbox" required><span>已逐项核对以上内容，可在当前授权下向公司展示；无诊断、专业结论及未经核验的预测。</span></label><button class="button primary" type="submit">核对选定摘要</button></fieldset></form></section></div>
<section class="summary-section summary-preview" id="reviewPanel" hidden aria-labelledby="reviewTitle"><h2 id="reviewTitle">保存前核对</h2><p class="summary-note">以下是本次提交内容。摘要授权不改变原视频保存期限，也不授权研究或训练。</p><pre id="reviewPayload"></pre><label class="summary-check"><input id="reviewConfirmed" type="checkbox"><span>我已再次核对选定字段、学生和授权期限。</span></label><div class="actions"><button class="button primary" id="commitButton" type="button" disabled>确认保存</button><button class="button quiet" id="cancelReview" type="button">返回修改</button></div></section>
<section class="summary-section"><h2>已保存摘要</h2><div id="snapshotList">正在读取记录。</div></section>""".replace("__DOMAINS__", domain_fields)
    script = COMMON.replace("__ACCOUNT__", _account_payload(account)) + r"""
const teacher=ACCOUNT.role==='school_uploader';
const studentId=new URLSearchParams(location.search).get('student_id')||'';
let pending=null;
const activeAuthorization=()=>workspace?.authorization?.status==='active'&&!!workspace.authorization.authorization_id&&future(workspace.authorization.valid_until);
function controls(){
  const ready=teacher&&!!workspace&&!loading&&!writing&&!uncertain&&byId('studentVerified').checked;
  byId('studentVerified').disabled=!teacher||!workspace||loading||writing||uncertain;
  byId('authorizationFields').disabled=!ready||activeAuthorization();byId('snapshotFields').disabled=!ready||!activeAuthorization();
  byId('automaticFields').disabled=!ready||!activeAuthorization();byId('includeExisting').disabled=!ready||!activeAuthorization()||!byId('autoEnabled').checked;
  byId('automaticReviewButton').textContent=workspace?.authorization?.automatic_archiving?.enabled===true&&!byId('autoEnabled').checked?'核对暂停新增归档':'核对归档设置';
  byId('withdrawButton').disabled=!ready||!workspace?.authorization?.authorization_id||['withdrawn','revoked'].includes(workspace.authorization.status);
  byId('reloadButton').disabled=loading||writing;
  byId('commitButton').disabled=!ready||!pending||!byId('reviewConfirmed').checked;
}
function clearPending(){pending=null;byId('reviewPanel').hidden=true;byId('reviewConfirmed').checked=false;controls();}
function prepare(kind,path,payload){
  pending={kind,path,payload};byId('reviewTitle').textContent=kind==='withdraw'?'核对撤回授权':kind==='automatic'?(payload.enabled?'确认开启自动课程归档':'确认暂停新增归档'):'保存前核对';
  byId('reviewPayload').textContent=JSON.stringify(payload,null,2);byId('reviewPanel').hidden=false;
  byId('reviewConfirmed').checked=false;controls();byId('reviewTitle').setAttribute('tabindex','-1');byId('reviewTitle').focus();
}
function readyToWrite(){controls();return teacher&&workspace&&!loading&&!writing&&!uncertain&&byId('studentVerified').checked;}
async function load(){
  if(loading||writing)return false;
  if(!teacher){notice('仅本校获授权教师可登记学生摘要。',true);controls();return false;}
  if(!studentId||studentId.length>128||/[\x00-\x1f]/.test(studentId)){notice('缺少有效学生编号，请从本校名册进入。',true);controls();return false;}
  loading=true;byId('studentVerified').checked=false;clearPending();byId('workspaceStatus').textContent='正在读取授权与记录。';controls();
  try{
    const next=requireWorkspace(await request('/student?student_id='+encodeURIComponent(studentId)));
    if(!next.student||next.student.student_id!==studentId||!Array.isArray(next.snapshots))throw new Error('学生或摘要数据不完整。');
    const courses=safeCourseHistory(next.course_history);
    workspace=next;uncertain=false;
    byId('studentName').textContent=String(next.student.display_name||'姓名未返回');
    byId('studentMeta').textContent='校内编号：'+String(next.student.student_code||'未返回')+' · 班级：'+String(next.student.class_name||'未返回');
    const auth=next.authorization;
    byId('authorizationStatus').textContent=auth?(activeAuthorization()?'授权有效，截止 '+auth.valid_until:auth.status==='withdrawn'||auth.status==='revoked'?'授权已撤回':'授权已到期或不可用'):'尚未登记摘要归档授权';
    byId('workspaceStatus').textContent=activeAuthorization()?'请核对学生后管理自动归档；教师摘要可按需补充。':'摘要保存已锁定；请先核对学生与授权。';
    const automatic=auth?.automatic_archiving;
    byId('autoEnabled').checked=activeAuthorization()&&automatic?.enabled===true;byId('includeExisting').checked=false;
    byId('automaticStatus').textContent=!activeAuthorization()?'当前无有效摘要授权，自动归档不可用。':automatic?.enabled===true?'自动归档已开启'+(automatic.enabled_at?' · 开启时间（北京时间）：'+beijingTime(automatic.enabled_at):'')+(automatic.include_existing===true?' · 已授权补录已有课程':' · 仅后续课程'):(automatic?.enabled_at?'已暂停新增归档':'自动归档未开启')+'；授权内已存历史继续保留，依据失效的分数仍会撤下。';
    // The backend must also redact inaccessible snapshots; the UI never displays them without active authority.
    if(activeAuthorization()){showSnapshots('snapshotList',next.snapshots);showCourseHistory('courseHistoryList',courses);showObservationTrend('courseTrendList',courses);}
    else{byId('snapshotList').textContent='授权未生效、已到期或撤回，摘要内容不可访问。';byId('courseHistoryList').textContent='授权未生效、已到期或撤回，课程历史不可访问。';byId('courseTrendList').textContent='授权未生效、已到期或撤回，趋势不可访问。';}
    return true;
  }catch(error){workspace=null;byId('studentName').textContent='学生信息未能读取';byId('studentMeta').textContent='';byId('authorizationStatus').textContent='授权状态未确认';byId('snapshotList').textContent='记录读取失败，不能据此判断没有摘要。';byId('courseHistoryList').textContent='课程历史读取失败，不能据此判断没有课程。';byId('courseTrendList').textContent='趋势读取失败，不能据此判断没有趋势。';byId('automaticStatus').textContent='自动归档状态未确认，请重新读取。';byId('workspaceStatus').textContent='请重新读取后再核对。';notice(error.message,true);return false;}
  finally{loading=false;controls();}
}
byId('validUntil').min=dayAfter(1);byId('validUntil').max=dayAfter(365);byId('validUntil').value=dayAfter(60);
byId('recordedOn').value=today();byId('recordedOn').max=today();
byId('studentVerified').addEventListener('change',()=>{clearPending();controls();});
for(const id of ['authorizationForm','snapshotForm','automaticForm'])byId(id).addEventListener('input',()=>{dirty=true;clearPending();});
byId('autoEnabled').addEventListener('change',()=>{if(!byId('autoEnabled').checked)byId('includeExisting').checked=false;clearPending();controls();});
byId('automaticForm').addEventListener('submit',event=>{
  event.preventDefault();if(!readyToWrite()||!activeAuthorization())return;
  const enabled=byId('autoEnabled').checked,includeExisting=enabled&&byId('includeExisting').checked;
  if(enabled===(workspace.authorization.automatic_archiving?.enabled===true)&&!includeExisting){notice('归档设置未改变。');return;}
  prepare('automatic','/automatic',{student_id:studentId,authorization_id:workspace.authorization.authorization_id,enabled,confirmed:true,include_existing:includeExisting});
});
byId('authorizationForm').addEventListener('submit',event=>{
  event.preventDefault();if(!readyToWrite()||activeAuthorization()||!byId('authorizationForm').reportValidity())return;
  const reference=byId('authorizationReference').value.trim(),validUntil=byId('validUntil').value;
  if(!reference||!byId('authorizationConfirmed').checked||validUntil<dayAfter(1)||validUntil>dayAfter(365)){notice('请核对授权依据、确认项和 1 至 365 天内的有效期。',true);return;}
  prepare('authorization','/authorization',{student_id:studentId,reference,valid_until:validUntil,confirmed:true});
});
byId('snapshotForm').addEventListener('submit',event=>{
  event.preventDefault();if(!readyToWrite()||!activeAuthorization()||!byId('snapshotForm').reportValidity())return;
  const domains=Object.fromEntries(Object.keys(domainLabels).map(key=>[key,byId('domain_'+key).value]));
  const recorded=byId('recordedOn').value;
  if(!byId('snapshotReviewed').checked||!byId('sourceRef').value.trim()||!byId('learningGoals').value.trim()||!byId('supportMethods').value.trim()||!recorded||recorded>today()||Object.values(domains).some(value=>!Object.hasOwn(levelLabels,value))){notice('请核对日期、来源、选定字段与教师复核项。',true);return;}
  prepare('snapshot','/snapshots',{student_id:studentId,authorization_id:workspace.authorization.authorization_id,recorded_on:recorded,
    source_ref:byId('sourceRef').value.trim(),learning_goals:byId('learningGoals').value.trim(),support_methods:byId('supportMethods').value.trim(),domains,
    measurement_id:byId('measurementId').value.trim(),reviewed:true});
});
byId('withdrawButton').addEventListener('click',()=>{
  if(!readyToWrite()||byId('withdrawButton').disabled)return;
  prepare('withdraw','/authorization/withdraw',{student_id:studentId,authorization_id:workspace.authorization.authorization_id,confirmed:true});
});
byId('reviewConfirmed').addEventListener('change',controls);
byId('cancelReview').addEventListener('click',clearPending);
byId('commitButton').addEventListener('click',async()=>{
  if(!pending||!readyToWrite()||!byId('reviewConfirmed').checked)return;
  if(['snapshot','automatic'].includes(pending.kind)&&(!activeAuthorization()||pending.payload.authorization_id!==workspace.authorization.authorization_id)){clearPending();notice('授权状态已变化，请重新读取。',true);return;}
  const confirmation=pending.kind==='withdraw'?'确认撤回本学生摘要的公司读取授权？':pending.kind==='automatic'?(pending.payload.enabled?'确认在当前授权范围和期限内自动归档后续课程，并向公司展示选定字段？'+(pending.payload.include_existing?' 同时补录本学生已有课程。':' 不补录已有课程。'):'确认暂停新增归档？当前授权内已存历史不会删除，依据失效的分数仍会撤下。'):'确认按已核对的学生、字段和期限保存？';
  if(!window.confirm(confirmation))return;
  const action=pending;writing=true;uncertain=true;controls();
  try{
    await request(action.path,action.payload);writing=false;
    const reloaded=await load();
    if(!reloaded){notice('提交已返回，但重新读取失败；保存状态待核对，请勿重复提交。',true);return;}
    dirty=false;byId('authorizationConfirmed').checked=false;byId('snapshotReviewed').checked=false;
    if(action.kind==='snapshot'){for(const id of ['sourceRef','learningGoals','supportMethods','measurementId'])byId(id).value='';for(const key of Object.keys(domainLabels))byId('domain_'+key).value='unknown';}
    notice(action.kind==='withdraw'?'撤回已提交并重新读取，请核对当前授权状态。':'提交完成并已重新读取，请核对已保存记录。');
  }catch(error){notice(error.message+' 提交结果待核对；请重新读取，勿重复保存。',true);if(error.denied){workspace=null;byId('snapshotList').replaceChildren();byId('courseHistoryList').replaceChildren();}}
  finally{writing=false;controls();}
});
byId('reloadButton').addEventListener('click',()=>{if(!loading&&!writing&&(!dirty||window.confirm('重新读取会重置学生核对与提交预览，未提交文字仍保留，继续吗？')))return load();});
load();
"""
    return _document(title="学生授权摘要 · RehabAffect", body=_shell(content), page_style=STYLE, script=script)


def render_admin_student_summaries_html(account: Any | None = None) -> str:
    content = """<div class="page-heading"><div><h1>授权学生摘要归档</h1><p class="lead">仅显示仍在授权范围内的摘要，使用公开编号与上传通道定位。</p></div></div>
<section class="summary-section"><form id="searchForm" class="search-form"><div class="field"><label for="archiveQuery">公开编号 / 通道</label><input id="archiveQuery" type="search" maxlength="80" autocomplete="off"></div><button class="button primary" id="searchButton" type="submit">查询</button></form><p class="summary-note" id="policyStatus">正在读取授权范围。</p><p id="resultStatus" role="status">正在读取归档记录。</p><div class="table-wrap"><table><thead><tr><th>公开编号</th><th>通道</th><th>课程数</th><th>最近课程</th><th>摘要数</th><th>最近摘要</th><th>有效期至</th><th>操作</th></tr></thead><tbody id="archiveRows"><tr><td colspan="8">正在读取记录。</td></tr></tbody></table></div><nav class="summary-pagination" aria-label="摘要归档分页"><button class="button" id="previousPage" type="button" title="上一页" aria-label="上一页" disabled>&larr;</button><span id="pageStatus">分页尚未读取</span><button class="button" id="nextPage" type="button" title="下一页" aria-label="下一页" disabled>&rarr;</button></nav></section>
<section class="summary-section" id="detailSection" hidden aria-labelledby="detailTitle"><h2 id="detailTitle">选定摘要</h2><p id="detailStatus" role="status"></p><p class="summary-note">仅可用于已获授权的教育支持。不包含学生姓名、原文来源或原视频，不授予研究或训练权限。撤回或到期后不可继续读取；已下载副本仍需按授权管理。</p><h3>课程历史</h3><div id="detailCourseHistory"></div><h3>课堂线索趋势</h3><div id="detailCourseTrend"></div><h3>教师核对摘要</h3><div id="detailRecords"></div><button class="button" id="exportButton" type="button" disabled>导出授权 JSON</button></section>"""
    script = COMMON.replace("__ACCOUNT__", _account_payload(account)) + r"""
const admin=ACCOUNT.role==='company_admin';
let page=1,pages=1,query='',detail=null,detailLoading=false;
function controls(){byId('reloadButton').disabled=loading||detailLoading;byId('searchButton').disabled=loading||detailLoading;
  byId('previousPage').disabled=loading||detailLoading||!workspace||page<=1;byId('nextPage').disabled=loading||detailLoading||!workspace||page>=pages;
  byId('exportButton').disabled=loading||detailLoading||!detail||!future(detail.valid_until);}
function clearDetail(){detail=null;byId('detailRecords').replaceChildren();byId('detailCourseHistory').replaceChildren();byId('detailCourseTrend').replaceChildren();byId('detailSection').hidden=true;controls();}
function cleanExport(data){
  if(!data||typeof data.public_id!=='string'||!future(data.valid_until)||!Array.isArray(data.snapshots))throw new Error('摘要已到期或导出数据不完整。');
  return {public_id:data.public_id,valid_until:data.valid_until,policy:safePolicy(data.policy),course_history:safeCourseHistory(data.course_history),snapshots:data.snapshots.map(row=>({
    snapshot_id:row.snapshot_id,recorded_on:row.recorded_on,learning_goals:row.learning_goals,support_methods:row.support_methods,
    domains:Object.fromEntries(Object.keys(domainLabels).map(key=>[key,Object.hasOwn(levelLabels,row.domains?.[key])?row.domains[key]:'unknown'])),
    provenance:safeProvenance(row.provenance),reviewed:row.reviewed===true,
    measurement:row.measurement==null||row.provenance?.source_status==='withheld'?null:safeMeasurement(row.measurement)}))};
}
async function load(nextPage=page,nextQuery=query){
  if(loading||detailLoading)return;
  if(!admin){notice('仅公司管理员可访问授权摘要归档。',true);byId('archiveRows').replaceChildren();controls();return;}
  loading=true;clearDetail();controls();byId('resultStatus').textContent='正在读取归档记录。';
  try{
    const next=requireWorkspace(await request('/admin?page='+nextPage+'&query='+encodeURIComponent(nextQuery)));
    const p=next.pagination;
    if(!Array.isArray(next.items)||!p||!Number.isInteger(p.page)||p.page<1||!Number.isInteger(p.total)||p.total<0||!Number.isInteger(p.total_pages)||p.total_pages<0)throw new Error('归档列表或分页数据不完整。');
    workspace=next;page=p.page;pages=Math.max(1,p.total_pages);query=nextQuery;
    const body=byId('archiveRows');body.replaceChildren();
    for(const item of next.items){const row=make('tr');for(const value of [item.public_id,item.channel_id,item.course_count,item.latest_course_at,item.snapshot_count,item.latest_recorded_on,item.valid_until])row.appendChild(make('td',value??'未返回'));
      const cell=make('td'),button=make('button','查看摘要');button.type='button';button.className='button';button.disabled=!future(item.valid_until);
      button.addEventListener('click',()=>openDetail(item.public_id));cell.appendChild(button);row.appendChild(cell);body.appendChild(row);}
    if(!next.items.length){const row=make('tr'),cell=make('td','暂无符合条件的有效授权摘要。');cell.setAttribute('colspan','8');row.appendChild(cell);body.appendChild(row);}
    byId('pageStatus').textContent='共 '+p.total+' 条 · 第 '+page+' / '+pages+' 页';
    byId('resultStatus').textContent=query?'当前结果：'+query:'当前结果：全部有效授权';
    byId('policyStatus').textContent='仅限选定摘要字段及授权期限；不授予研究、训练、原文资料或原视频读取权限。';
    notice('已重新读取授权归档。');
  }catch(error){if(error.denied){workspace=null;byId('archiveRows').replaceChildren();byId('pageStatus').textContent='访问受限';}
    byId('resultStatus').textContent=workspace?'读取失败，保留上次列表；请重新读取。':'列表读取失败，不能据此判断没有归档。';notice(error.message,true);}
  finally{loading=false;controls();}
}
async function readExport(publicId){const data=await request('/export?public_id='+encodeURIComponent(publicId));const result=cleanExport(data);if(result.public_id!==publicId)throw new Error('摘要公开编号不一致，请重新读取。');return result;}
async function openDetail(publicId){
  if(!admin||loading||detailLoading||!workspace||!workspace.items.some(item=>item.public_id===publicId&&future(item.valid_until)))return;
  detailLoading=true;clearDetail();byId('detailSection').hidden=false;byId('detailStatus').textContent='正在重新核对授权。';controls();
  try{detail=await readExport(publicId);byId('detailTitle').textContent='摘要 '+detail.public_id;byId('detailStatus').textContent='有效期至 '+detail.valid_until;showSnapshots('detailRecords',detail.snapshots,true);showCourseHistory('detailCourseHistory',detail.course_history);showObservationTrend('detailCourseTrend',detail.course_history);}
  catch(error){detail=null;byId('detailRecords').replaceChildren();byId('detailCourseHistory').replaceChildren();byId('detailCourseTrend').replaceChildren();byId('detailStatus').textContent='摘要读取失败，授权可能已到期或撤回。';notice(error.message,true);if(error.denied){workspace=null;byId('archiveRows').replaceChildren();}}
  finally{detailLoading=false;controls();}
}
byId('exportButton').addEventListener('click',async()=>{
  if(!admin||loading||detailLoading||!detail||!future(detail.valid_until))return;
  const id=detail.public_id;detailLoading=true;controls();
  try{
    // Recheck server authority even after a successful preview; withdrawal may intervene.
    const fresh=await readExport(id),blob=new Blob([JSON.stringify(fresh,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob);
    try{const link=make('a');link.href=url;link.download='authorized-student-summary.json';document.body.appendChild(link);link.click();link.remove();}
    finally{URL.revokeObjectURL(url);}
    notice('授权 JSON 已生成；下载副本仍受原授权期限与用途约束。');
  }catch(error){clearDetail();notice(error.message,true);}
  finally{detailLoading=false;controls();}
});
byId('searchForm').addEventListener('submit',event=>{event.preventDefault();const value=byId('archiveQuery').value.trim();if(value.length<=80)return load(1,value);notice('公开编号或通道查询最多 80 字符。',true);});
byId('previousPage').addEventListener('click',()=>{if(!byId('previousPage').disabled)return load(page-1);});
byId('nextPage').addEventListener('click',()=>{if(!byId('nextPage').disabled)return load(page+1);});
byId('reloadButton').addEventListener('click',()=>load());
load();
"""
    return _document(title="授权学生摘要归档 · RehabAffect", body=_shell(content, admin=True), page_style=STYLE, script=script)


__all__ = ["render_student_summary_html", "render_admin_student_summaries_html"]
