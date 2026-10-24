"""Protected review surface for evidence extracted from a newly uploaded video."""

from __future__ import annotations

from typing import Any

from .demo2_portal import _BOOK_ICON, _WORKSPACE_STYLE, _account_payload, _document, _workspace_nav


def render_video_review(account: Any | None = None) -> str:
    style = _WORKSPACE_STYLE + r"""
body { background:#fff; }
.header-inner,.page-shell { width:min(1360px,calc(100% - 48px)); }
.page-shell { padding-top:20px; }
.page-heading { margin-bottom:18px; }
.page-heading h1 { font-size:22px; }
.quiet-meta { color:var(--muted); font-size:13px; margin-top:7px; }
.review-actions { display:flex; gap:8px; flex-wrap:wrap; }
.process-band { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px 24px; padding:17px 0 20px; border-block:1px solid var(--line); }
.page-heading>div,.review-actions { min-width:0; }
.quiet-meta,.eyebrow,.segment strong,.segment span,.period,.review-actions a { overflow-wrap:anywhere; }
.poll-status { margin-top:8px; font-size:12px; color:var(--muted); }
.process-band strong { font-size:14px; }
.process-band p { font-size:13px; color:var(--muted); margin-top:4px; }
progress { grid-column:1/-1; width:100%; height:5px; accent-color:var(--blue); border:0; }
progress::-webkit-progress-bar { background:#e9eff6; }
progress::-webkit-progress-value { background:var(--blue); }
.review-layout { display:grid; grid-template-columns:minmax(0,1fr) 310px; gap:28px; margin-top:24px; align-items:start; }
.recording { min-width:0; }
.video-stage { position:relative; aspect-ratio:16/9; background:#edf2f7; overflow:hidden; border-radius:4px; }
video { display:block; width:100%; height:100%; object-fit:contain; background:#182128; }
.media-empty { position:absolute; inset:0; display:grid; place-items:center; text-align:center; padding:24px; color:var(--muted); font-size:14px; }
.media-empty[hidden] { display:none; }
.transport { display:flex; align-items:center; gap:12px; min-height:58px; }
.transport input { flex:1; min-width:40px; min-height:44px; padding:0; accent-color:var(--blue); border:0; }
.transport output { flex:none; min-width:108px; font:13px/1.4 Consolas,monospace; color:var(--muted); }
.clip-controls { display:flex; align-items:center; flex-wrap:wrap; gap:4px 20px; margin:0 0 12px; }
.clip-controls label { display:inline-flex; align-items:center; gap:8px; min-height:44px; font-size:13px; color:var(--ink); cursor:pointer; }
.clip-controls input { width:18px; height:18px; min-height:18px; margin:0; accent-color:var(--blue); }
.clip-controls label:has(input:disabled) { color:var(--muted); cursor:default; }
.clip-controls output { font-size:12px; color:var(--muted); overflow-wrap:anywhere; }
.icon-button { display:inline-grid; place-items:center; width:44px; height:44px; min-width:44px; padding:8px; background:#fff; border:1px solid var(--line); border-radius:5px; color:var(--blue); }
.icon-button:hover { background:var(--blue-soft); }
.icon-button:disabled { opacity:.4; cursor:default; }
.recording-meta { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); margin:0; padding:15px 0; border-block:1px solid var(--line); gap:16px; }
dt { font-size:12px; color:var(--muted); margin-bottom:4px; }
dd { margin:0; font-size:14px; font-weight:600; overflow-wrap:anywhere; }
.evidence-pane { min-width:0; border-left:1px solid var(--line); padding-left:24px; }
.evidence-pane h2 { font-size:18px; }
.evidence-pane h3 { font-size:13px; margin:22px 0 10px; }
.evidence-pane .period { font:600 22px/1.4 Consolas,monospace; margin:12px 0; color:var(--blue-deep); }
.evidence-pane dl { display:grid; gap:12px; margin:0; }
.evidence-pane dl>div { display:flex; justify-content:space-between; align-items:baseline; gap:14px; }
.evidence-pane dd { font-size:13px; text-align:right; }
.evidence-pane dt { margin:0; }
.boundary-note { margin-top:20px; padding-top:16px; border-top:1px solid var(--line); font-size:12px; color:var(--muted); line-height:1.8; }
.audio-player { width:100%; min-width:0; max-width:100%; height:44px; margin-top:8px; }
.timeline-section { margin-top:28px; }
.section-line { display:flex; align-items:center; justify-content:space-between; gap:14px; margin-bottom:14px; }
.section-line h2 { font-size:18px; }
.section-line span { font-size:12px; color:var(--muted); }
.segment-grid { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:6px; }
.segment { min-width:0; min-height:76px; padding:10px; border:0; border-bottom:1px solid var(--line); background:#f8fafc; color:var(--ink); text-align:left; border-radius:4px; }
.segment:hover { background:#f5f9ff; }
.segment[aria-pressed=true] { background:var(--blue-soft); box-shadow:inset 0 3px 0 var(--blue); }
.segment strong { display:block; font:600 13px/1.5 Consolas,monospace; }
.segment span { display:block; color:var(--muted); font-size:12px; margin-top:6px; }
.pagination { display:flex; justify-content:flex-end; gap:12px; align-items:center; margin-top:16px; font-size:12px; color:var(--muted); }
.limitations { font-size:12px; color:var(--muted); margin-top:26px; border-top:1px solid var(--line); padding-top:16px; }
.limitations summary { cursor:pointer; padding-block:4px; }
.limitations li { margin-block:7px; line-height:1.7; }
.scope-status { font-size:12px; color:#6c5421; background:#fff8e7; padding:7px 10px; margin-top:16px; }
.student-state-panel { margin-top:22px; padding:18px 0 6px; border-block:1px solid var(--line); }
.student-state-panel h2 { margin:0; font-size:18px; }
.student-state-panel > p { margin:6px 0 14px; color:var(--muted); font-size:13px; }
.student-state-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; }
.student-state-card { min-width:0; padding:13px 14px; border:1px solid var(--line); border-radius:5px; background:#fbfdff; }
.student-state-card strong,.student-state-card span { display:block; overflow-wrap:anywhere; }
.student-state-card strong { font-size:16px; }
.student-state-card span { margin-top:4px; color:var(--muted); font-size:12px; }
.state-pill { display:inline-flex !important; width:max-content; margin-top:9px; padding:3px 9px; border-radius:14px; font-size:12px !important; font-weight:700; }
.state-engaged { color:#17684f !important; background:#e5f6ed; }
.state-low_attention { color:#8c5b10 !important; background:#fff1c9; }
.state-confused_or_stuck { color:#5e4b96 !important; background:#eee9ff; }
.state-not_visible { color:#697785 !important; background:#edf1f4; }
.state-uncertain { color:#943e3e !important; background:#ffe9e9; }
.student-state-empty { padding:10px 0; color:var(--muted); font-size:13px; }
.identity-summary { margin-top:20px; padding:16px 0; border-block:1px solid var(--line); }
.identity-summary p { font-size:13px; color:var(--muted); line-height:1.8; margin-top:8px; }
.identity-summary .button { font-size:13px; margin:10px 8px 0 0; }
[hidden] { display:none !important; }
@media(max-width:1050px) { .review-layout { grid-template-columns:minmax(0,1fr) 260px; gap:20px; } .evidence-pane { padding-left:20px; } .segment-grid { grid-template-columns:repeat(4,minmax(0,1fr)); } }
@media(max-width:780px) { .header-inner,.page-shell { width:calc(100% - 28px); } .review-layout { grid-template-columns:1fr; } .evidence-pane { border-left:0; border-top:1px solid var(--line); padding:20px 0 0; } .recording-meta { gap:10px; } .segment-grid { grid-template-columns:repeat(3,minmax(0,1fr)); } .header-actions .button { width:auto; } .page-heading h1 { font-size:23px; } }
@media(max-width:720px) { .header-actions .button { flex:0 1 auto; } .review-actions { width:100%; } .review-actions .button { flex:1 1 auto; } }
@media(max-width:460px) { .segment-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .recording-meta { grid-template-columns:repeat(2,minmax(0,1fr)); } .transport { gap:8px; } .transport output { min-width:96px; font-size:12px; } }
@media(max-width:650px) { .student-state-grid { grid-template-columns:1fr; } }
"""
    # Arrow, RotateCcw and Download paths are from Lucide (ISC).
    back_icon = '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m12 19-7-7 7-7M5 12h14"/></svg>'
    body = r"""
<header class="site-header"><div class="header-inner">
  <a class="brand" href="/demo2/upload">__BOOK__<span class="brand-copy"><strong>RehabAffect</strong><span>课堂视频证据</span></span></a>
  __WORKSPACE_NAV__
  <div class="header-actions"><a class="button quiet" id="backLink" href="/demo2/upload">__BACK__返回工作台</a><button class="button quiet" id="logoutButton" type="button">退出</button></div>
</div></header>
<main class="page-shell" id="mainContent">
  <div class="page-heading"><div><span class="eyebrow" id="courseBatch">课堂记录</span><h1 id="courseTitle">正在读取视频任务</h1><p class="quiet-meta" id="fileMeta"></p></div>
  <div class="review-actions"><button class="button" id="refreshButton" type="button">刷新任务</button><button class="button" id="retryButton" type="button" hidden>重新处理</button><a class="button" id="downloadResult" hidden><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/></svg><span id="downloadLabel">下载证据记录</span></a></div></div>
  <div class="page-message" id="pageMessage" role="alert" tabindex="-1"></div>
  <section class="process-band" aria-label="视频处理进度"><div><strong id="stageLabel">读取任务</strong><p id="stageDetail" aria-live="polite">正在连接本地工作区</p></div><span class="status-badge" id="stagePercent">--</span><progress id="processingProgress" max="100" value="0" aria-label="视频处理进度"></progress></section>
  <p class="poll-status" id="pollStatus" role="status">处理进度会自动更新；分析完成后直接显示学生课堂状态。</p>
  <p class="poll-status">当前任务视频证据，不是历史演示；原视频与音轨均需登录授权。</p>
  <section class="student-state-panel" id="studentStatePanel" aria-labelledby="studentStateTitle"><h2 id="studentStateTitle">学生课堂状态</h2><p>系统按本次视频中的可见人物生成时间段状态，先看结果即可；姓名和 IEP 关联放在后续档案操作。</p><div class="student-state-grid" id="studentStateCards"><div class="student-state-empty">后台分析完成后显示学生状态。</div></div></section>
  <details class="identity-summary" aria-labelledby="identityTitle"><summary id="identityTitle">后续：身份绑定与学生档案</summary><p id="identitySummary" role="status">尚未读取本任务已确认帧与学校名册。</p><p>身份确认只对精确采样帧有效。全画面的动作变化与同期音轨不能归因于某位学生，不代表个人学习结论。</p><a class="button primary" id="identityLink" hidden>确认画面中的学生</a><button class="button" id="refreshIdentitySummary" type="button" disabled>刷新身份摘要</button><a class="button" id="courseDossierLink" hidden>关联学生资料</a></details>
  <div class="review-layout">
    <section class="recording" aria-label="课堂录像">
      <div class="video-stage"><video id="classVideo" aria-label="本任务课堂录像" controls playsinline preload="metadata" hidden></video><div class="media-empty" id="mediaEmpty">视频尚未就绪</div></div>
      <div class="transport"><button class="icon-button" id="replayButton" title="回到当前片段开头" aria-label="回到当前片段开头" disabled><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11a9 9 0 1 1 9 9 9.75 9.75 0 0 1-6.74-2.74L3 15M3 3v8h8"/></svg></button><input id="seekSlider" type="range" min="0" max="1" step="0.1" value="0" aria-label="录像时间" disabled><output id="playTime">00:00 / 00:00</output></div>
      <div class="clip-controls" role="group" aria-label="当前片段回看"><label><input id="clipOnly" type="checkbox" disabled />只看当前片段</label><label><input id="loopClip" type="checkbox" disabled />循环本片段</label><output id="clipRange" aria-live="polite">尚未选择片段</output></div>
      <dl class="recording-meta"><div><dt>录像时长</dt><dd id="durationMetric">--</dd></div><div><dt>画面分辨率</dt><dd id="resolutionMetric">--</dd></div><div><dt>音轨</dt><dd id="audioMetric">--</dd></div><div><dt>证据片段</dt><dd id="segmentMetric">--</dd></div></dl>
      <section class="timeline-section" aria-labelledby="timelineTitle"><div class="section-line"><h2 id="timelineTitle">时间切片</h2><span id="segmentCount">等待处理结果</span></div><div class="segment-grid" id="segments"></div><div class="empty-state" id="segmentsEmpty">处理结束后显示原片时间切片</div><div class="pagination" id="pagination" hidden><button class="icon-button" id="previousPage" title="上一页" aria-label="上一页">__BACK__</button><span id="pageCount"></span><button class="icon-button" id="nextPage" title="下一页" aria-label="下一页"><svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m12 5 7 7-7 7M5 12h14"/></svg></button></div></section>
    </section>
    <aside class="evidence-pane" aria-labelledby="evidenceTitle"><h2 id="evidenceTitle">当前片段</h2><div class="period" id="selectedPeriod">--:--</div><span class="status-badge warning" id="reviewState">等待分析</span>
      <h3>画面记录</h3><dl><div><dt>采样帧数</dt><dd id="sampleCount">--</dd></div><div><dt>平均亮度</dt><dd id="brightnessMetric">--</dd></div><div><dt>清晰度指标</dt><dd id="sharpnessMetric">--</dd></div><div><dt>画面变化幅度</dt><dd id="motionMetric">--</dd></div></dl>
      <h3>同期声音</h3><dl><div><dt>音轨状态</dt><dd id="segmentAudio">--</dd></div><div><dt>声音能量 RMS</dt><dd id="rmsMetric">--</dd></div></dl><audio class="audio-player" id="audioPlayer" aria-label="本任务同期音轨" controls preload="none" hidden></audio><p class="poll-status" id="audioNotice"></p>
      <p class="boundary-note">状态来自本次视频的可见画面与声音线索，不是诊断，也不是正式评价分数。学生姓名和 IEP 需要后续确认后再归档。</p><div class="scope-status" id="scopeStatus">等待学生状态分析</div>
    </aside>
  </div>
  <details class="limitations"><summary>处理范围与数据来源</summary><p>原视频保留60天，原视频及派生音轨均需登录授权后访问。</p><ul id="limitationsList"></ul><p id="versionMeta"></p></details>
</main>
""".replace("__BOOK__", _BOOK_ICON).replace("__BACK__", back_icon).replace("__WORKSPACE_NAV__", _workspace_nav("upload"))
    script = r"""
const ACCOUNT=__ACCOUNT__;
const id=new URLSearchParams(location.search).get('id')||'';
const $=id=>document.getElementById(id);
const video=$('classVideo'),audio=$('audioPlayer');
let task=null,result=null,segments=[],selected=-1,page=0,loadedResult=false,pollTimer=null;
let refreshing=false,changingTask=false,stopped=false,pollFailures=0,pendingVideoTime=null,pendingAudioTime=null;
let clipRevision=0;
const loopPending=new WeakSet();
const PAGE_SIZE=20;
const activeStatuses=['queued','processing','waiting_upload'];
const legacyStatuses=['precheck_complete','uploaded_pending_worker'];
const stateClass=value=>({engaged:'state-engaged',low_attention:'state-low_attention',confused_or_stuck:'state-confused_or_stuck',not_visible:'state-not_visible',uncertain:'state-uncertain'}[value]||'state-not_visible');
const simpleAnalysis=()=>result?.simple_student_analysis&&typeof result.simple_student_analysis==='object'?result.simple_student_analysis:null;
function stateWindowsFor(segment){
  const analysis=simpleAnalysis();if(!analysis?.available||!Array.isArray(analysis.persons))return [];
  return analysis.persons.flatMap(person=>(Array.isArray(person.windows)?person.windows:[]).filter(window=>Number(window.end_sec)>Number(segment.start_sec)&&Number(window.start_sec)<Number(segment.end_sec)).map(window=>({...window,person:person.display_name||'人物'})));
}
function segmentStateText(segment){
  const states=[...new Set(stateWindowsFor(segment).map(window=>window.state_zh||window.state).filter(Boolean))];
  return states.length?states.slice(0,2).join('、')+(states.length>2?' 等':''):'画面记录已生成';
}
function renderStudentStates(){
  const analysis=simpleAnalysis(),target=$('studentStateCards');
  if(!analysis?.available||!Array.isArray(analysis.persons)||!analysis.persons.length){target.innerHTML='<div class="student-state-empty">暂未生成稳定人物状态。请检查视频中学生是否可见、光线是否充足或稍后刷新。</div>';return;}
  target.innerHTML=analysis.persons.slice(0,3).map(person=>{
    const windows=Array.isArray(person.windows)?person.windows:[],latest=windows[0]||{};
    const score=person.average_score==null?'暂无参考分':Number(person.average_score).toFixed(1)+' / 10';
    return `<article class="student-state-card"><strong>${esc(person.display_name||'人物')}</strong><span>可见覆盖 ${Math.round(Number(person.visibility||0)*100)}% · ${windows.length} 个状态时间段</span><span class="state-pill ${stateClass(person.dominant_state)}">${esc(person.dominant_state_zh||latest.state_zh||'待观察')}</span><span>参考分：${esc(score)}</span></article>`;
  }).join('');
}
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time=value=>{const n=Math.max(0,Math.floor(Number(value)||0));return `${String(Math.floor(n/60)).padStart(2,'0')}:${String(n%60).padStart(2,'0')}`;};
const metric=(value,digits=1)=>typeof value==='number'&&Number.isFinite(value)?value.toFixed(digits):'未取得';
const stageNames={queued:'等待处理',processing:'处理中',validating:'检查任务文件',hashing:'核对原片',probing:'检查媒体',probe:'检查媒体',sampling_video:'读取画面',sampling:'读取画面',decoding:'读取画面',audio:'提取音轨',extracting_audio:'提取音轨',measuring_audio:'整理声音记录',audio_measured:'声音记录已整理',audio_absent:'原片无音轨，继续整理画面',summarizing:'整理时间切片',writing_result:'保存证据记录',finalizing:'保存证据',evidence_ready:'证据已就绪',failed:'处理未完成',waiting_upload:'等待上传',precheck_complete:'历史预检记录',uploaded_pending_worker:'历史预检记录',expired:'原片已到期',cancelled:'任务已取消'};
function notice(text,focus=false){$('pageMessage').textContent=text;$('pageMessage').className='page-message visible';if(focus)$('pageMessage').focus();}
function clearNotice(){$('pageMessage').className='page-message';$('pageMessage').textContent='';}
function sameOriginUrl(value){if(!value)return '';try{const url=new URL(value,location.origin);return url.origin===location.origin&&['http:','https:'].includes(url.protocol)?url.pathname+url.search+url.hash:'';}catch(_){return '';}}
function mediaExpired(){return !!task?.raw_media_deleted_at||['expired','deleted'].includes(task?.analysis_status)||['expired','deleted'].includes(task?.upload_status);}
function mediaAvailable(){return !!sameOriginUrl(task?.media_url)&&!mediaExpired()&&task?.upload_status!=='cancelled';}
async function api(path,options={}){
  const controller=new AbortController();const timeout=setTimeout(()=>controller.abort(),15000);
  try{
    const r=await fetch('/api/v1/demo2'+path,{...options,credentials:'same-origin',signal:controller.signal});
    const data=await r.json().catch(error=>{if(error.name==='AbortError'||error instanceof TypeError)throw error;return {};});
    const errors={401:'登录已过期，请重新登录。',403:'当前账号无权查看或处理这个视频，请返回自己的工作台。',404:'未找到该视频任务，请返回工作台重新选择。',410:'原片已到期或已清理，无法继续播放或处理。'};
    if(r.status===401){try{sessionStorage.setItem('demo2_notice',errors[401]);}catch(_){}location.assign('/demo2/login');}
    if(!r.ok||data.error){const error=new Error(errors[r.status]||data.error?.message||'请求未完成，请稍后重试。');error.status=r.status;throw error;}
    return data;
  }catch(error){if(error instanceof TypeError)throw new Error('网络连接失败，请检查网络后重试。');throw error;}finally{clearTimeout(timeout);}
}
let identityLoading=false;
async function refreshIdentity(){
  if(identityLoading||!id||!['school_uploader','company_admin'].includes(ACCOUNT.role))return;
  identityLoading=true;$('refreshIdentitySummary').disabled=true;
  try{const data=await api('/identity/workspace?task_id='+encodeURIComponent(id));const work=data.workspace;if(!work||work.task_id!==id||!Array.isArray(work.bindings)||!Array.isArray(work.students))throw new Error('接口未返回本任务身份记录。');const confirmed=work.bindings.filter(b=>['confirmed','active'].includes(b.status)&&b.current_revision!==false&&(b.frame_revision==null||String(b.frame_revision)===String(work.frame_revision)));const names=[...new Set(confirmed.filter(b=>b.role==='student').map(b=>work.students.find(s=>s.student_id===b.student_id)).filter(Boolean).map(s=>[s.display_name,s.student_code?'编号 '+s.student_code:'未填编号',s.class_name||'未填班级'].join(' · ')))];$('identitySummary').textContent=(work.school_context?.school_name||'任务学校未返回')+' · 本校名册 '+work.students.length+' 人 · 当前版本 '+new Set(confirmed.map(b=>b.frame_key)).size+' 个已确认帧。'+(names.length?'已确认学生：'+names.join('；'):'尚无已确认的学生身份。');$('identityLink').hidden=false;}
  catch(error){$('identitySummary').textContent=(error.name==='AbortError'?'身份摘要读取超时，请重试。':error.message)+' 不能据此判断没有确认记录。';if([401,403,404].includes(error.status))$('identityLink').hidden=true;}
  finally{identityLoading=false;$('refreshIdentitySummary').disabled=false;}
}
function seekMedia(player,value){const maximum=Number.isFinite(player.duration)?player.duration:Infinity;player.currentTime=Math.max(0,Math.min(Number(value)||0,maximum));}
function clipBounds(player){
  const segment=segments[selected];
  if(!segment||!mediaAvailable()||player.hidden||player.readyState<1)return null;
  const start=segment.start_sec,end=Math.min(segment.end_sec,Number.isFinite(player.duration)?player.duration:Infinity);
  return Number.isFinite(start)&&Number.isFinite(end)&&end>start?{start,end}:null;
}
function clipMode(){return $('clipOnly').checked||$('loopClip').checked;}
function syncClipControls(){
  const available=!!(clipBounds(video)||clipBounds(audio));
  $('clipOnly').disabled=!available;$('loopClip').disabled=!available;
  const segment=segments[selected];
  $('clipRange').textContent=segment?time(segment.start_sec)+' - '+time(segment.end_sec)+(available?'':' · 媒体未就绪'):'尚未选择片段';
}
function resetClipControls(){
  clipRevision++;$('clipOnly').checked=false;$('loopClip').checked=false;syncClipControls();
}
// Keep the selected evidence slice fixed while either bounded replay mode is on.
function enforceClip(player){
  const bounds=clipMode()&&!stopped?clipBounds(player):null;if(!bounds)return false;
  if(player.currentTime<bounds.start){seekMedia(player,bounds.start);return true;}
  if(player.currentTime>=bounds.end){
    if(player.ended&&$('loopClip').checked)return true;
    if($('loopClip').checked&&!player.paused)seekMedia(player,bounds.start);
    else {player.pause();if(player.currentTime>bounds.end)seekMedia(player,bounds.end);}
  }
  return true;
}
function replayEndedClip(player){
  const bounds=clipBounds(player);
  if(stopped||!$('loopClip').checked||!bounds||!player.ended||loopPending.has(player))return;
  const revision=clipRevision;loopPending.add(player);
  const failed=()=>{if(revision!==clipRevision||stopped)return;player.pause();$('loopClip').checked=false;notice('本片段循环播放未能继续，请手动播放后再开启循环。');};
  try{
    seekMedia(player,bounds.start);
    Promise.resolve(player.play()).then(()=>{if(revision!==clipRevision||stopped)player.pause();},failed).finally(()=>loopPending.delete(player));
  }catch(_){loopPending.delete(player);failed();}
}
function updatePlayback(){
  const known=Number(result?.media?.duration_sec);const duration=Number.isFinite(video.duration)?video.duration:Number.isFinite(known)?known:0;
  $('seekSlider').max=String(duration||1);$('seekSlider').value=String(video.currentTime||0);$('playTime').textContent=`${time(video.currentTime)} / ${time(duration)}`;
  $('seekSlider').setAttribute('aria-valuetext',`${time(video.currentTime)}，共 ${time(duration)}`);
}
function drawSegments(){
  page=Math.max(0,Math.min(page,Math.max(0,Math.ceil(segments.length/PAGE_SIZE)-1)));
  const visible=segments.slice(page*PAGE_SIZE,(page+1)*PAGE_SIZE);
  $('segments').innerHTML=visible.map((s,i)=>`<button type="button" class="segment" data-index="${page*PAGE_SIZE+i}" aria-pressed="${page*PAGE_SIZE+i===selected}"><strong>${time(s.start_sec)} - ${time(s.end_sec)}</strong><span>${Number(s.visual?.sampled_frames||0)} 帧 · ${esc(segmentStateText(s))}</span></button>`).join('');
  $('segmentsEmpty').hidden=segments.length>0;$('pagination').hidden=segments.length<=PAGE_SIZE;
  $('pageCount').textContent=`${page+1} / ${Math.max(1,Math.ceil(segments.length/PAGE_SIZE))}`;
  $('previousPage').disabled=page===0;$('nextPage').disabled=(page+1)*PAGE_SIZE>=segments.length;
}
function selectSegment(index,seek=true){
  const s=segments[index];if(!s)return;clipRevision++;selected=index;
  $('selectedPeriod').textContent=`${time(s.start_sec)} - ${time(s.end_sec)}`;
  const states=stateWindowsFor(s);$('reviewState').textContent=states.length?'学生状态已生成':'画面记录已生成';$('reviewState').className='status-badge '+(states.length?'success':'warning');
  $('sampleCount').textContent=s.visual?.sampled_frames==null?'未取得':String(s.visual.sampled_frames);
  $('brightnessMetric').textContent=metric(s.visual?.mean_brightness);
  $('sharpnessMetric').textContent=metric(s.visual?.mean_sharpness);
  $('motionMetric').textContent=metric(s.visual?.mean_motion,4);
  $('segmentAudio').textContent=s.audio?.available?'已提取同期音轨':result?.media?.has_audio===false?'原片无音轨':'未取得声音证据';
  $('rmsMetric').textContent=metric(s.audio?.rms,4);
  if(seek&&mediaAvailable()){
    pendingVideoTime=s.start_sec;pendingAudioTime=s.start_sec;audio.pause();
    if(video.readyState>=1&&!video.hidden){seekMedia(video,pendingVideoTime);pendingVideoTime=null;updatePlayback();}
    if(audio.readyState>=1&&!audio.hidden){seekMedia(audio,pendingAudioTime);pendingAudioTime=null;}
  }
  const nextPage=Math.floor(index/PAGE_SIZE);
  if(page!==nextPage){page=nextPage;drawSegments();}
  else $('segments').querySelectorAll('[data-index]').forEach(button=>button.setAttribute('aria-pressed',String(Number(button.dataset.index)===selected)));
  $('replayButton').disabled=video.hidden||video.readyState<1;
  syncClipControls();
}
function followPlayback(player){if(clipMode())return;const position=Number(player.currentTime)||0;const index=segments.findIndex((s,i)=>position>=s.start_sec&&(position<s.end_sec||(i===segments.length-1&&position===s.end_sec)));if(index>=0&&index!==selected)selectSegment(index,false);}
function clearEvidence(){
  result=null;segments=[];selected=-1;page=0;loadedResult=false;
  resetClipControls();
  ['durationMetric','resolutionMetric','audioMetric','segmentMetric','sampleCount','brightnessMetric','sharpnessMetric','motionMetric','segmentAudio','rmsMetric'].forEach(name=>$(name).textContent='--');
  $('selectedPeriod').textContent='--:--';$('reviewState').textContent='等待分析';$('segmentCount').textContent='等待处理结果';$('scopeStatus').textContent='等待学生状态分析';$('studentStateCards').innerHTML='<div class="student-state-empty">后台分析完成后显示学生状态。</div>';
  $('downloadResult').hidden=true;$('downloadResult').removeAttribute('href');$('downloadLabel').textContent='下载证据记录';$('limitationsList').innerHTML='';$('versionMeta').textContent='';
  audio.pause();audio.removeAttribute('src');audio.load();audio.hidden=true;$('audioNotice').textContent='';drawSegments();
}
function stopMedia(text){
  [video,audio].forEach(player=>{player.pause();if(player.getAttribute('src')){player.removeAttribute('src');player.load();}player.hidden=true;});
  pendingVideoTime=null;pendingAudioTime=null;$('mediaEmpty').hidden=false;$('mediaEmpty').textContent=text;$('audioNotice').textContent='';
  $('seekSlider').disabled=true;$('replayButton').disabled=true;updatePlayback();
  resetClipControls();
}
function syncMedia(){
  if(!mediaAvailable()){stopMedia(mediaExpired()?'原片与派生音轨已到期或清理；仍可查看接口保留的结构化记录。':task?.upload_status==='cancelled'?'任务已取消，原视频不可用。':'原视频尚未可用，请先完成上传或等待处理。');return;}
  const source=sameOriginUrl(task.media_url);
  if(video.getAttribute('src')!==source){video.src=source;video.hidden=false;$('mediaEmpty').hidden=true;}
  const audioReady=loadedResult&&result?.media?.has_audio&&segments.some(s=>s.audio?.available);
  if(audioReady){const source='/api/v1/demo2/upload/media?id='+encodeURIComponent(id)+'&asset=audio';if(audio.getAttribute('src')!==source){audio.src=source;audio.hidden=false;$('audioNotice').textContent='选择时间切片可同步定位音轨；播放音轨时暂停视频。';}}
  syncClipControls();
}
function displayResult(value){
  result=value;loadedResult=true;segments=value.segments.filter(s=>Number.isFinite(s.start_sec)&&Number.isFinite(s.end_sec)&&s.start_sec>=0&&s.end_sec>s.start_sec).sort((a,b)=>a.start_sec-b.start_sec);
  const media=value.media||{};
  $('durationMetric').textContent=Number.isFinite(media.duration_sec)?time(media.duration_sec):'未取得';
  $('resolutionMetric').textContent=media.width&&media.height?`${media.width} × ${media.height}`:'未取得';
  $('audioMetric').textContent=media.has_audio===true?'有音轨':media.has_audio===false?'无音轨':'未取得';
  $('segmentMetric').textContent=String(segments.length);
  $('segmentCount').textContent=`${segments.length} 个片段`;
  const limits=Array.isArray(value.limitations)?value.limitations:[];
  $('limitationsList').innerHTML=limits.map(v=>`<li>${esc(v)}</li>`).join('');
  $('versionMeta').textContent=`处理版本 ${value.analysis_version||'--'} · ${value.generated_at||''}`;
  renderStudentStates();
  const analysis=simpleAnalysis();$('scopeStatus').textContent=analysis?.available?`已生成 ${analysis.persons?.length||0} 名人物的课堂状态时间段，可直接查看。`:'暂未生成稳定人物状态，请检查画面后刷新。';
  $('downloadResult').hidden=false;$('downloadLabel').textContent='下载证据记录';$('downloadResult').href=sameOriginUrl(task.secure_result_download_url||task.result_download_url)||'/api/v1/demo2/upload/result?id='+encodeURIComponent(id);
  if(segments.length)selectSegment(0,false);else{$('reviewState').textContent='暂无可查看切片';$('selectedPeriod').textContent='--:--';}
  drawSegments();updatePlayback();
}
function schedulePoll(delay){clearTimeout(pollTimer);if(!stopped&&!document.hidden&&!changingTask)pollTimer=setTimeout(()=>refresh(),delay);}
async function refresh(){
  clearTimeout(pollTimer);if(refreshing||changingTask||stopped)return;
  if(!id){$('courseTitle').textContent='未选择视频任务';$('stageLabel').textContent='未选择任务';$('stageDetail').textContent='请返回上传工作台，打开一个视频任务。';$('pollStatus').textContent='请选择任务后查看处理进度。';$('segmentsEmpty').textContent='尚未选择视频，暂无时间切片。';$('refreshButton').disabled=true;return;}
  refreshing=true;$('refreshButton').disabled=true;$('retryButton').disabled=true;let nextPoll=0;
  try{
    const data=await api('/upload/task?id='+encodeURIComponent(id));if(stopped)return;
    if(!data.task)throw new Error('接口未返回任务，请稍后刷新。');task=data.task;pollFailures=0;clearNotice();
    $('courseTitle').textContent=task.course_name||'课堂录像';$('courseBatch').textContent=task.course_id||'课堂记录';
    $('fileMeta').textContent=task.original_filename||'课堂视频';
    $('backLink').href=ACCOUNT.role==='company_admin'?'/demo2/admin':'/demo2/upload?course_id='+encodeURIComponent(task.course_id||'');
    const status=task.analysis_status;const expired=mediaExpired();const cancelled=task.upload_status==='cancelled'||status==='cancelled';
    const numeric=Number(task.processing_progress);const known=task.processing_progress!=null&&Number.isFinite(numeric);const progress=Math.max(0,Math.min(100,numeric||0));
    $('stageLabel').textContent=expired?'原片已到期 / 清理':cancelled?'任务已取消':stageNames[status]||'等待后台状态';
    $('stagePercent').textContent=status==='evidence_ready'?'100%':known?progress+'%':'--';
    if(known||status==='evidence_ready')$('processingProgress').value=status==='evidence_ready'?100:progress;else $('processingProgress').removeAttribute('value');
    const error=typeof task.processing_error==='object'?task.processing_error?.message:task.processing_error;
    $('stageDetail').textContent=expired?'原视频与派生音轨不可播放，已有结构化记录仍可查看。':cancelled?'请返回工作台选择其他任务。':status==='failed'?(error||'处理未完成，请重新处理；再次失败时联系项目方并提供任务信息。'):status==='evidence_ready'?'学生课堂状态已生成，可直接查看。':status==='queued'?'视频已接收，正在排队。可离开本页，后台会继续处理。':legacyStatuses.includes(status)?'此任务仅完成旧版上传预检。点击“开始处理”生成真实视频证据。':status==='waiting_upload'?'视频尚未传完，请返回原上传页面完成上传。':stageNames[task.processing_stage]||'等待后台处理记录';
    $('retryButton').textContent=legacyStatuses.includes(status)?'开始处理':'重新处理';
    $('retryButton').hidden=!(status==='failed'||legacyStatuses.includes(status))||!mediaAvailable();
    const actualResult=data.result?.media&&Array.isArray(data.result?.segments);
    if(!expired&&activeStatuses.includes(status)&&loadedResult)clearEvidence();
    if(actualResult&&(status==='evidence_ready'||expired)&&!loadedResult)displayResult(data.result);
    if(legacyStatuses.includes(status)&&data.result&&!actualResult){$('downloadResult').hidden=false;$('downloadLabel').textContent='下载历史预检记录';$('downloadResult').href=sameOriginUrl(task.secure_result_download_url||task.result_download_url)||'/api/v1/demo2/upload/result?id='+encodeURIComponent(id);}
    syncMedia();
    $('segmentsEmpty').textContent=expired?'没有可保留的时间切片；原片已到期或清理。':cancelled?'任务已取消，没有可查看切片。':status==='failed'?'本次处理未完成，尚无可查看切片。':legacyStatuses.includes(status)?'开始处理后才会生成时间切片。':status==='evidence_ready'?(loadedResult?'处理结果中暂无有效时间切片。':'正在等待证据记录同步，请稍候。'):'处理结束后显示原片时间切片。';
    const pending=!expired&&!cancelled&&(activeStatuses.includes(status)||(status==='evidence_ready'&&!loadedResult));
    $('pollStatus').textContent=pending?'每 2 秒自动更新；后台处理无需保持页面打开。':'任务状态已更新，可手动刷新。';if(pending)nextPoll=2000;
  }catch(error){
    if(stopped)return;
    const fatal=[401,403,404,410].includes(error.status);notice(error.name==='AbortError'?'读取任务超时，将自动重试。':error.message);
    if(fatal){clearEvidence();stopMedia(error.message);$('retryButton').hidden=true;}
    if(fatal||!task){
      $('stageLabel').textContent=error.status===403?'无权访问':error.status===404?'任务不存在':error.status===410?'原片已到期':'暂时无法读取任务';
      $('stageDetail').textContent=fatal?'请返回工作台检查当前账号与任务。':'尚未取得任务状态，请检查网络或点击“刷新任务”。';
    }
    if(!fatal&&task)notice((error.name==='AbortError'?'读取任务超时。':error.message)+' 已保留上次成功读取的状态，当前状态未确认。');
    $('pollStatus').textContent=fatal?'自动更新已停止。':'连接暂时中断，正在等待自动重连。';
    if(!fatal)nextPoll=Math.min(30000,5000*++pollFailures);
  }finally{refreshing=false;$('refreshButton').disabled=false;$('retryButton').disabled=false;if(nextPoll)schedulePoll(nextPoll);}
}
$('segments').addEventListener('click',event=>{const button=event.target.closest('[data-index]');if(button)selectSegment(Number(button.dataset.index));});
$('previousPage').addEventListener('click',()=>{page--;drawSegments();});$('nextPage').addEventListener('click',()=>{page++;drawSegments();});
$('seekSlider').addEventListener('input',()=>{if(video.hidden||video.readyState<1)return;seekMedia(video,$('seekSlider').value);enforceClip(video);followPlayback(video);updatePlayback();});
$('replayButton').addEventListener('click',()=>selectSegment(selected));
video.addEventListener('loadedmetadata',()=>{if(!mediaAvailable())return;$('seekSlider').disabled=false;$('replayButton').disabled=selected<0;if(pendingVideoTime!==null){seekMedia(video,pendingVideoTime);pendingVideoTime=null;}syncClipControls();updatePlayback();});
video.addEventListener('timeupdate',()=>{enforceClip(video);updatePlayback();followPlayback(video);});
audio.addEventListener('timeupdate',()=>{enforceClip(audio);followPlayback(audio);});
[video,audio].forEach(player=>{
  player.addEventListener('play',()=>{
    (player===video?audio:video).pause();
    const bounds=clipMode()?clipBounds(player):null;
    if(bounds&&(player.currentTime<bounds.start||player.currentTime>=bounds.end))seekMedia(player,bounds.start);
  });
  player.addEventListener('seeking',()=>enforceClip(player));
  player.addEventListener('ended',()=>replayEndedClip(player));
});
['clipOnly','loopClip'].forEach(name=>$(name).addEventListener('change',()=>{
  clipRevision++;
  [video,audio].forEach(player=>{const bounds=clipMode()?clipBounds(player):null;if(bounds&&(player.currentTime<bounds.start||player.currentTime>=bounds.end))seekMedia(player,bounds.start);});
  syncClipControls();updatePlayback();
}));
audio.addEventListener('loadedmetadata',()=>{if(!mediaAvailable())return;seekMedia(audio,pendingAudioTime??segments[selected]?.start_sec??0);pendingAudioTime=null;syncClipControls();});
video.addEventListener('error',()=>{if(!video.getAttribute('src'))return;video.pause();video.hidden=true;resetClipControls();$('mediaEmpty').hidden=false;$('mediaEmpty').textContent='视频暂时无法播放。请刷新任务检查原片是否可用；若仍失败，可联系项目方确认浏览器支持的格式。';$('seekSlider').disabled=true;$('replayButton').disabled=true;});
audio.addEventListener('error',()=>{if(!audio.getAttribute('src'))return;audio.pause();audio.hidden=true;resetClipControls();$('audioNotice').textContent='同期音轨暂时无法播放，请刷新任务检查权限或保存期限。';});
$('refreshButton').addEventListener('click',()=>{if(video.error)video.removeAttribute('src');if(audio.error)audio.removeAttribute('src');refresh();refreshIdentity();});
$('retryButton').addEventListener('click',async()=>{
  if(refreshing||changingTask||!mediaAvailable())return;
  const endpoint=legacyStatuses.includes(task.analysis_status)?'/upload/tasks/enqueue':task.analysis_status==='failed'?'/upload/tasks/retry':null;if(!endpoint)return;
  clearTimeout(pollTimer);changingTask=true;$('retryButton').disabled=true;$('refreshButton').disabled=true;
  try{await api(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task_id:id})});clearEvidence();clearNotice();}
  catch(error){notice(error.message,true);return;}
  finally{changingTask=false;$('retryButton').disabled=false;$('refreshButton').disabled=false;}
  await refresh();
});
$('logoutButton').addEventListener('click',async()=>{try{await api('/auth/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});location.assign('/demo2/login');}catch(error){notice(error.message,true);}});
$('backLink').href=ACCOUNT.role==='company_admin'?'/demo2/admin':'/demo2/upload';
$('backLink').textContent=ACCOUNT.role==='company_admin'?'返回公司后台':'返回工作台';
$('identityLink').href='/demo2/identity?task_id='+encodeURIComponent(id);$('identityLink').textContent=ACCOUNT.role==='company_admin'?'查看已确认身份':'确认画面中的学生';
$('courseDossierLink').href='/demo2/course-dossier?task_id='+encodeURIComponent(id);$('courseDossierLink').hidden=ACCOUNT.role!=='school_uploader'||!id;
if(ACCOUNT.role==='school_uploader'&&id){const analysis=document.createElement('a');analysis.className='button primary';analysis.href='/demo2/analysis?task_id='+encodeURIComponent(id);analysis.textContent='课堂复核与图文报告';$('courseDossierLink').after(analysis);}
$('refreshIdentitySummary').addEventListener('click',refreshIdentity);
window.addEventListener('pagehide',()=>{stopped=true;clipRevision++;clearTimeout(pollTimer);video.pause();audio.pause();});
window.addEventListener('pageshow',event=>{if(event.persisted){stopped=false;refresh();}});
document.addEventListener('visibilitychange',()=>{clearTimeout(pollTimer);if(!document.hidden&&!stopped)refresh();});
refresh();
refreshIdentity();
""".replace("__ACCOUNT__", _account_payload(account))
    return _document(title="课堂视频证据 · RehabAffect", body=body, page_style=style, script=script)
