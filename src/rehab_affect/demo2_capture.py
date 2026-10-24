"""Browser-local camera + microphone recording, then explicit normal upload."""
from .demo2_portal import _document, _workspace_nav, _WORKSPACE_STYLE


def render_capture(account=None):
    body = '''<header class="site-header"><div class="header-inner"><a class="brand" href="/demo2/upload">RehabAffect · 课堂工作台</a>__NAV__</div></header>
<main id="mainContent" class="page-shell"><div class="page-heading"><div><h1>录制课堂</h1><p class="lead">检查画面与声音，录制完成后回放，再保存到课程。</p></div><a class="button" href="/demo2/upload">上传已有视频</a></div>
<div class="capture-layout"><section class="card"><div class="card-body"><video id="preview" autoplay muted playsinline aria-label="实时画面预览"></video><video id="playback" controls playsinline hidden aria-label="录制结果回放"></video>
<p id="state" role="status" aria-live="polite">尚未启用设备。请先确认已获得本次课堂录制授权。</p><label class="check"><input type="checkbox" id="consent">我已获准录制本次课堂画面与声音</label>
<div class="actions"><button class="button" id="enable">检查摄像头与麦克风</button><button class="button primary" id="record" disabled>开始录制</button><button class="button" id="stop" disabled>结束录制</button></div>
<p><span id="clock">00:00</span> · 单段最多15分钟 / 256MB，到达上限自动停止。长课请分段保存。</p>
<label for="level">麦克风输入</label><meter id="level" min="0" max="1" value="0"></meter><span id="levelText">尚未检查</span>
<details><summary>设备与部署条件</summary><p>使用 HTTPS 或本机 localhost，允许浏览器访问摄像头和麦克风；支持带音轨的 WebM 或 MP4。设备断开会结束当前录制。浏览器关闭前请先下载或上传录像。</p><p>摄像头拍到学生及教学材料，外接麦克风尽量靠近师生互动区。先录制10秒并回放确认画面和声音，再开始课堂。麦克风电平只说明存在声音，不识别说话人或答案。</p><p>上传后沿用课程视频60天保留和音轨回放流程；学生测量由教师另行记录和复核。</p></details></div></section>
<section class="card"><div class="card-head"><h2>保存这段课堂</h2><p>回放确认完整后，选择保存方式。</p></div><div class="card-body"><p id="clipInfo">尚无录制文件</p><a id="download" class="button" hidden download>下载视频与声音</a>
<form id="saveForm"><label for="courseId">课程批次号</label><input id="courseId" required maxlength="120" placeholder="例如 math-20260915-01"><label for="courseName">课程名称</label><input id="courseName" required maxlength="200" placeholder="本次课堂名称"><label class="check"><input type="checkbox" id="uploadConsent" required>确认上传到当前账号课程并按60天保存</label><button id="upload" class="button primary" disabled>保存到课程</button></form>
<progress id="progress" max="100" value="0" hidden></progress><p id="saveState" role="status" aria-live="polite"></p><a id="schoolLink" class="button" href="/demo2/school" target="_blank" rel="noopener" hidden>在新标签页完善学校信息</a><a id="taskLink" class="button" hidden>查看视频处理任务</a><a class="button" href="/demo2/measurement">记录课堂测量</a></div></section></div></main>'''.replace('__NAV__',_workspace_nav('capture'))
    style = _WORKSPACE_STYLE + '''.capture-layout{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(300px,1fr);gap:22px}video{display:block;width:100%;max-height:480px;background:#163550;border-radius:8px}.actions{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0}form{display:grid;gap:10px;margin:22px 0}.check{display:flex;align-items:center;gap:8px;margin:14px 0}.check input{width:auto}meter{width:130px;vertical-align:middle;margin:8px}#clock{font:600 24px Consolas,monospace}#download{margin-bottom:8px}[hidden]{display:none!important}details{margin-top:22px;line-height:1.8}progress{width:100%}@media(max-width:820px){.capture-layout{grid-template-columns:1fr}}'''
    script = r'''
const $=id=>document.getElementById(id),API='/api/v1/demo2';
let stream=null,recorder=null,blob=null,blobUrl=null,parts=[],bytes=0,timer=null,started=0,busy=false,uploading=false,saved=false,task=null,audioContext=null,meterTimer=null,clipType='',failed=false;
const CHUNK_SIZE=4*1024*1024,MAX_RECORD_BYTES=256*1024*1024,MAX_UPLOAD_RETRIES=3;
let uploadSession=null;
const type=['video/webm;codecs=vp8,opus','video/webm','video/mp4'].find(t=>typeof MediaRecorder!=='undefined'&&MediaRecorder.isTypeSupported(t));
function tell(text){$('state').textContent=text;}
function closeDevices(){clearInterval(timer);clearInterval(meterTimer);if(stream)stream.getTracks().forEach(t=>t.stop());stream=null;$('preview').srcObject=null;if(audioContext)audioContext.close().catch(()=>{});audioContext=null;}
function controls(){const active=recorder?.state==='recording';$('enable').disabled=busy||active||uploading;$('record').disabled=busy||active||!stream||uploading;$('stop').disabled=!active;$('upload').disabled=!blob||active||uploading||saved||failed;$('consent').disabled=active||busy;$('courseId').disabled=uploading||!!uploadSession;$('courseName').disabled=uploading||!!uploadSession;}
function uploadError(message,status=0,code=''){return Object.assign(new Error(message),{status,code});}
async function api(path,data,{binary=false}={}){
  const controller=new AbortController(),t=setTimeout(()=>controller.abort(),binary?180000:30000);
  try{
    const r=await fetch(API+path,{credentials:'same-origin',cache:'no-store',signal:controller.signal,...(data!==undefined?{method:'POST',headers:{'Content-Type':binary?'application/octet-stream':'application/json'},body:binary?data:JSON.stringify(data)}:{})});
    let d;try{d=await r.json();}catch(_){throw uploadError('服务器响应未确认，请核对已保存进度。',r.ok?0:r.status);}
    if(!r.ok||d?.ok===false||d?.error)throw uploadError(d?.error?.message||'保存未完成，请重试',r.status,d?.error?.code||'');
    if(!d||typeof d!=='object'||Array.isArray(d))throw uploadError('服务器响应不完整。');
    return d;
  }catch(error){if(error.name==='AbortError')throw uploadError('请求超时，正在核对已保存进度。');throw error;}
  finally{clearTimeout(t);}
}
$('enable').onclick=async()=>{if(busy)return;if(!$('consent').checked)return tell('请先确认本次课堂录制授权。');if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia||!type)return tell('当前浏览器不能录制，请通过HTTPS或localhost使用最新版Chrome/Edge。');if(blob&&!saved&&!confirm('已有未上传录制，继续前请先下载。重新检查设备？'))return;busy=true;controls();closeDevices();try{stream=await navigator.mediaDevices.getUserMedia({video:{width:{ideal:1280},height:{ideal:720}},audio:{echoCancellation:true,noiseSuppression:true}});if(!stream.getVideoTracks().length||!stream.getAudioTracks().length)throw new Error('缺少可用画面或音轨');$('preview').hidden=false;$('playback').hidden=true;$('preview').srcObject=stream;await $('preview').play();stream.getTracks().forEach(track=>track.addEventListener('ended',()=>{failed=true;if(recorder?.state==='recording')recorder.stop();closeDevices();tell('设备已断开，已停止录制。请下载已有片段并检查设备，不能作为完整课堂上传。');controls();}));try{audioContext=new (window.AudioContext||window.webkitAudioContext)();const analyzer=audioContext.createAnalyser();analyzer.fftSize=256;audioContext.createMediaStreamSource(stream).connect(analyzer);const a=new Uint8Array(256);meterTimer=setInterval(()=>{analyzer.getByteTimeDomainData(a);const power=Math.sqrt(a.reduce((s,v)=>s+((v-128)/128)**2,0)/a.length);$('level').value=Math.min(1,power*4);$('levelText').textContent=power>.005?'检测到声音':'声音较弱，请说话检查';},200);}catch(_){$('levelText').textContent='电平不可用，请用回放检查声音';}tell('画面与麦克风已启用，尚未录制。');}catch(e){closeDevices();tell('设备不可用：'+(e.name==='NotAllowedError'?'请允许摄像头和麦克风权限。':e.message));}finally{busy=false;controls();}};
$('record').onclick=()=>{
  if(!stream||uploading||recorder?.state==='recording')return;
  if(blob&&!saved&&!confirm('开始新录制会替换上次片段，请确认已下载。继续？'))return;
  try{
    if(blobUrl)URL.revokeObjectURL(blobUrl);blob=null;parts=[];bytes=0;saved=false;task=null;uploadSession=null;failed=false;
    $('download').hidden=true;$('taskLink').hidden=true;$('schoolLink').hidden=true;$('saveState').textContent='';$('progress').value=0;
    recorder=new MediaRecorder(stream,{mimeType:type,videoBitsPerSecond:1200000});clipType=recorder.mimeType;
    recorder.ondataavailable=e=>{if(e.data.size){parts.push(e.data);bytes+=e.data.size;if(bytes>=MAX_RECORD_BYTES&&recorder.state==='recording')recorder.stop();}};
    recorder.onerror=()=>{failed=true;tell('录制发生错误，请保存可用片段并检查设备。');};
    recorder.onstop=()=>{const elapsed=Math.round((Date.now()-started)/1000);closeDevices();blob=new Blob(parts,{type:clipType});parts=[];if(!blob.size){blob=null;tell('没有生成有效录像，请检查设备。');controls();return;}blobUrl=URL.createObjectURL(blob);$('playback').src=blobUrl;$('playback').hidden=false;$('preview').hidden=true;$('download').href=blobUrl;$('download').download='classroom-'+new Date().toISOString().replace(/[:.]/g,'-')+(clipType.includes('mp4')?'.mp4':'.webm');$('download').hidden=false;$('clipInfo').textContent=`${elapsed}秒 · ${(blob.size/1048576).toFixed(1)}MB · 包含画面与音轨`;tell(failed?'录制有中断，请下载片段检查。':'录制完成。请打开回放确认声音和画面，再下载或保存到课程。');controls();};
    recorder.start(1000);started=Date.now();timer=setInterval(()=>{const sec=Math.floor((Date.now()-started)/1000);$('clock').textContent=String(Math.floor(sec/60)).padStart(2,'0')+':'+String(sec%60).padStart(2,'0');if(sec>=900&&recorder.state==='recording')recorder.stop();},1000);
    tell('正在录制画面与声音');controls();
  }catch(e){closeDevices();tell('无法开始录制：'+e.message);controls();}
};
$('stop').onclick=()=>{if(recorder?.state==='recording'){$('stop').disabled=true;recorder.stop();}};
function acceptTask(s,value){
  const next=value?.next_chunk_index;
  if(!value||typeof value.task_id!=='string'||!value.task_id||(s.taskId&&value.task_id!==s.taskId)||value.course_id!==s.courseId||value.byte_size!==s.file.size||value.total_chunks!==s.total||
     !Number.isInteger(next)||next<s.next||next>s.sentThrough||next>s.total||value.received_bytes!==Math.min(next*s.chunkSize,s.file.size)||
     !['uploading','completed'].includes(value.upload_status)||value.raw_media_deleted_at||(value.upload_status==='completed'&&next!==s.total))throw uploadError('任务状态不一致或已失效，请保留录像并联系管理员核查。',409,'upload_state_conflict');
  s.taskId=value.task_id;s.next=next;s.completed=value.upload_status==='completed';task=value;
  $('taskLink').href='/demo2/video?id='+encodeURIComponent(s.taskId);$('taskLink').hidden=false;
  $('progress').value=s.completed?100:Math.min(99,value.received_bytes*100/s.file.size);
  $('saveState').textContent=`已确认保存 ${Math.floor($('progress').value)}%`;
}
const retryable=error=>!error.status||[408,425,429,500,502,503,504].includes(error.status);
const retryWait=attempt=>new Promise(resolve=>setTimeout(resolve,1000*2**(attempt-1)));
async function prepareUpload(cid,name){
  if(uploadSession?.taskId)return uploadSession;
  const w=(await api('/upload/workspace?course_id='+encodeURIComponent(cid))).workspace;
  if(!w?.account||!Array.isArray(w.tasks))throw uploadError('上传工作区未能完整读取。',409);
  const size=w.chunk_size_bytes??CHUNK_SIZE;
  if(size!==CHUNK_SIZE)throw uploadError('录制页分片配置与平台不一致，请先下载录像并联系管理员。',409);
  if(!uploadSession)uploadSession={file:blob,courseId:cid,courseName:name,sessionId:crypto.randomUUID(),chunkSize:size,total:Math.ceil(blob.size/size),next:0,sentThrough:0,taskId:null,creationUncertain:false,completed:false};
  const s=uploadSession;
  if(s.creationUncertain){
    const matches=w.tasks.filter(value=>value.session_id===s.sessionId&&value.course_id===s.courseId);
    if(matches.length!==1)throw uploadError('任务创建结果仍待核对，未重复创建；请稍后再次保存或先下载录像。',409,'creation_uncertain');
    acceptTask(s,matches[0]);s.creationUncertain=false;return s;
  }
  s.creationUncertain=true;
  try{
    const result=await api('/upload/tasks',{channel_id:w.channel?.channel_id||w.account.bound_channel_id,course_id:s.courseId,course_name:s.courseName,session_id:s.sessionId,
      uploader_name:w.account.username,filename:$('download').download,mime_type:clipType,byte_size:s.file.size,total_chunks:s.total,security_confirmed:true,allow_company_archive:false});
    acceptTask(s,result.task);s.creationUncertain=false;return s;
  }catch(error){if(error.status&&!retryable(error)&&error.code!=='upload_state_conflict'){uploadSession=null;task=null;}throw error;}
}
async function saveRecording(s){
  let failures=0,reconcile=true;
  while(!s.completed){
    try{
      if(reconcile){const before=s.next;acceptTask(s,(await api('/upload/task?id='+encodeURIComponent(s.taskId))).task);reconcile=false;if(s.next>before)failures=0;}
      if(s.completed)break;
      if(s.next>=s.total)throw uploadError('分片已接收，正在核对完成状态。');
      const index=s.next,chunk=s.file.slice(index*s.chunkSize,Math.min(s.file.size,(index+1)*s.chunkSize));
      s.sentThrough=Math.max(s.sentThrough,index+1);
      acceptTask(s,(await api('/upload/chunks?'+new URLSearchParams({task_id:s.taskId,course_id:s.courseId,chunk_index:String(index)}),chunk,{binary:true})).task);
      if(s.next<=index)throw uploadError('分片接收尚未确认。');
      failures=0;
    }catch(error){
      reconcile=true;if(!retryable(error)||failures>=MAX_UPLOAD_RETRIES)throw error;
      failures+=1;$('saveState').textContent=`连接暂未确认，正在核对进度并重试（${failures}/${MAX_UPLOAD_RETRIES}）。录像仍保留在本页。`;
      await retryWait(failures);
    }
  }
}
$('saveForm').onsubmit=async e=>{
  e.preventDefault();if(uploading||!blob||failed||saved||recorder?.state==='recording')return;
  uploading=true;controls();$('progress').hidden=false;$('schoolLink').hidden=true;
  try{
    const cid=uploadSession?.courseId||$('courseId').value.trim(),name=uploadSession?.courseName||$('courseName').value.trim();
    if(!cid||!name||!$('uploadConsent').checked)throw uploadError('请填写课程并确认保存',400);
    if(blob.size>MAX_RECORD_BYTES)throw uploadError('录像超过256MB限制，请先下载并分段上传。',413);
    const s=await prepareUpload(cid,name);await saveRecording(s);
    saved=true;$('progress').value=100;$('saveState').textContent='视频和声音已保存。后台继续处理，可前往任务检查或确认学生身份。';
  }catch(error){
    const school=error.status===409&&error.code==='school_context_required';$('schoolLink').hidden=!school;
    $('saveState').textContent='保存未完成：'+error.message+' 录像仍在当前页，可先下载。'+(school?'请在新标签页完善学校信息，再回本页保存；不要刷新录制页。':'可再次点击保存以核对已确认进度；不要关闭或刷新本页。');
  }finally{uploading=false;controls();}
};
window.addEventListener('beforeunload',e=>{if(recorder?.state==='recording'||uploading||(blob&&!saved)){e.preventDefault();e.returnValue='';}});
window.addEventListener('pagehide',()=>{if(recorder?.state==='recording')recorder.stop();closeDevices();});
controls();
'''
    return _document(title='录制课堂 · RehabAffect', body=body, page_style=style, script=script)
