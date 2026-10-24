"""Run rendered upload JavaScript with synthetic Files and controlled HTTP failures."""
import json

import pytest

from rehab_affect.demo2_portal import render_demo2_upload_html
from test_demo2_portal_html import _run_page_js


SETUP = r"""
location.search='';replies.push({context:{city:'Synthetic City',district:'Synthetic District',school_name:'Synthetic School'}},{account:{username:'teacher',bound_channel_id:'channel_1'}});
const sends=[];let mode='normal',serverNext=0,attempts=0,sessionUnderTest;
let metadataMode='ready',metadataDuration=1800;const metadataVideos=[],revokedURLs=[];
URL.createObjectURL=()=>`blob:synthetic-${metadataVideos.length}`;
URL.revokeObjectURL=url=>revokedURLs.push(url);
document.createElement=tag=>{
  assert.equal(tag,'video');const video=new Element('metadata');video.duration=metadataDuration;
  video.load=()=>{if(video.src)queueMicrotask(()=>{if(metadataMode==='ready')video.onloadedmetadata?.();else if(metadataMode==='error')video.onerror?.();});};
  metadataVideos.push(video);return video;
};
class XMLHttpRequest {
  constructor(){this.upload={};}
  open(method,url){this.url=url;this.method=method;}
  setRequestHeader(key,value){assert.equal(key,'Content-Type');assert.equal(value,'application/octet-stream');}
  abort(){this.onabort();this.onloadend?.();}
  send(chunk){
    assert.ok(chunk instanceof Blob);assert.equal(this.timeout,180000);assert.equal(this.withCredentials,true);
    const index=Number(new URL(this.url,'https://synthetic.test').searchParams.get('chunk_index'));
    sends.push(index);attempts++;
    this.upload.onprogress({loaded:chunk.size,lengthComputable:true});
    if(mode==='offline'||mode==='fail-first'&&attempts===1){this.onerror();return;}
    serverNext=index+1;
    if(mode==='lost-final'&&serverNext===sessionUnderTest.total){this.onerror();return;}
    if(mode==='pause'&&attempts===1){pauseUpload();return;}
    this.status=200;this.responseText=JSON.stringify({task:serverTask()});this.onload();this.onloadend?.();
  }
}
function serverTask(){const s=sessionUnderTest;return {task_id:s.taskId,course_id:s.courseId,
  original_filename:s.file.name,byte_size:s.file.size,next_chunk_index:serverNext,
  received_bytes:Math.min(serverNext*4*1024*1024,s.file.size),upload_status:serverNext===s.total?'completed':'uploading'};}
"""

COMMON = r"""
workspace={course_id:'course-1',remaining_slots:0,tasks:[]};byId('courseId').value='course-1';
const file=new File([new Uint8Array(4*1024*1024+9)],'synthetic.mp4',{type:'video/mp4'});
const s={file,courseId:'course-1',taskId:'video-1',next:0,sentThrough:0,total:2,acknowledged:0,paused:false,running:false,completed:false};
sessionUnderTest=s;uploadSession=s;setUploadBusy(true);
loadWorkspace=async()=>{};scheduleTaskPoll=()=>{};retryDelay=async()=>{};
const realApi=api;api=async(url,options)=>{assert.ok(url.startsWith(API_ROUTES.task+'?id='));return {task:serverTask()};};
"""


@pytest.mark.parametrize('mode', ['normal', 'fail-first', 'lost-final'])
def test_binary_retry_and_final_response_reconciliation(mode):
    _run_page_js(render_demo2_upload_html(), SETUP, COMMON + f"mode={mode!r};" + r"""
    await runUpload(s);
    assert.equal(s.completed,true);assert.equal(s.acknowledged,file.size);
    assert.equal(uploadSession,null);assert.equal(uploadInProgress,false);
    assert.equal(byId('progressPercent').textContent,'100%');
    assert.deepEqual(sends,mode==='fail-first'?[0,0,1]:[0,1]);
    """)


def test_pause_reconciles_abort_then_resumes_same_file():
    _run_page_js(render_demo2_upload_html(), SETUP, COMMON + r"""
    mode='pause';await runUpload(s);
    assert.equal(s.paused,true);assert.equal(s.next,1);assert.equal(s.acknowledged,CHUNK_SIZE);
    assert.equal(uploadSession,s);assert.equal(uploadInProgress,true);assert.equal(byId('courseId').disabled,true);
    assert.equal(byId('resumeUploadButton').hidden,false);assert.equal(byId('resumeUploadButton').disabled,false);
    let warned=false;listeners.get('beforeunload')({preventDefault(){warned=true;}});assert.equal(warned,true);
    mode='normal';await runUpload(s);assert.deepEqual(sends,[0,1]);assert.equal(s.completed,true);
    """)


def test_retry_bound_preserves_acknowledged_bytes():
    _run_page_js(render_demo2_upload_html(), SETUP, COMMON + r"""
    serverNext=1;s.next=1;s.sentThrough=1;s.acknowledged=CHUNK_SIZE;mode='offline';
    await runUpload(s);assert.equal(attempts,5);assert.equal(s.paused,true);
    assert.equal(s.acknowledged,CHUNK_SIZE);assert.notEqual(byId('progressPercent').textContent,'0%');
    assert.equal(uploadSession,s);assert.equal(uploadInProgress,true);
    """)


@pytest.mark.parametrize('mutation', ["task_id:'other'", "course_id:'other'", "received_bytes:1", "next_chunk_index:2", "upload_status:'cancelled'"])
def test_reconciliation_rejects_inconsistent_or_other_task(mutation):
    _run_page_js(render_demo2_upload_html(), SETUP, COMMON + f"assert.throws(()=>acceptUploadTask(s,{{...serverTask(),{mutation}}}));assert.equal(s.next,0);")


@pytest.mark.parametrize('case', ['success', 'wrong_name', 'wrong_size', 'prefix_rejected', 'offset_changed'])
def test_reselected_file_verifies_prefix_before_resume_without_quota(case):
    _run_page_js(render_demo2_upload_html(), SETUP, COMMON + f"const scenario={case!r};" + r"""
    uploadSession=null;setUploadBusy(false);serverNext=1;
    resumeTaskId='video-1';byId('resumeVideoFile').files=[scenario==='wrong_name'?new File([file],'other.mp4'):
      scenario==='wrong_size'?new File([new Uint8Array(2)],file.name):file];
    let validated=false,resumed=false;
    api=async(url,options)=>{
      if(url.startsWith(API_ROUTES.task+'?'))return {task:serverTask()};
      assert.equal(url,API_ROUTES.resume);
      const data=JSON.parse(options.body);assert.equal(data.task_id,'video-1');assert.equal(data.course_id,'course-1');
      assert.equal(data.filename,file.name);assert.equal(data.byte_size,file.size);assert.equal(data.chunk_sha256.length,1);
      const expected=require('node:crypto').createHash('sha256').update(new Uint8Array(CHUNK_SIZE)).digest('hex');
      assert.equal(data.chunk_sha256[0],expected);validated=true;
      if(scenario==='prefix_rejected')throw new Error('prefix mismatch');
      return {task:scenario==='offset_changed'?{...serverTask(),next_chunk_index:2,received_bytes:file.size}:serverTask()};
    };
    runUpload=async session=>{resumed=true;assert.equal(validated,true);assert.equal(session.next,1);assert.equal(session.file,file);};
    await resumeSelectedFile();assert.equal(resumed,scenario==='success');
    if(scenario!=='success'){assert.equal(uploadSession,null);assert.equal(uploadInProgress,false);}
    assert.equal(sends.length,0);
    """)


def test_uploading_task_never_claims_safe_to_leave():
    _run_page_js(render_demo2_upload_html(), SETUP, r"""
    workspace={course_id:'course-1',remaining_slots:0,tasks:[{...baseTask,upload_status:'uploading',analysis_status:'waiting_upload'}]};
    byId('courseId').value='course-1';renderTasks();scheduleTaskPoll();
    assert.match(byId('taskList').innerHTML,/data-resume-task/);
    assert.doesNotMatch(byId('taskPollStatus').textContent,/可离开/);
    assert.match(byId('taskPollStatus').textContent,/请勿关闭/);
    """)


def test_no_base64_or_persisted_file_identity_shortcut():
    html = render_demo2_upload_html()
    assert 'content_base64' not in html and 'readAsDataURL' not in html
    assert "crypto.subtle.digest('SHA-256',buffer)" in html
    assert "xhr.timeout=180000" in html
    assert "Math.random()" in html


def test_webcrypto_unavailable_does_not_offer_unverified_resume():
    _run_page_js(render_demo2_upload_html(), SETUP, r"""
    const descriptor=Object.getOwnPropertyDescriptor(globalThis,'crypto');
    Object.defineProperty(globalThis,'crypto',{value:undefined,configurable:true});
    chooseResumeFile('video-1');assert.equal(resumeTaskId,null);
    assert.match(byId('pageMessage').textContent,/WebCrypto/);
    Object.defineProperty(globalThis,'crypto',descriptor);
    """)


def test_progress_speed_uses_acknowledgements_not_inflight_bytes():
    _run_page_js(render_demo2_upload_html(), SETUP, COMMON + r"""
    performance.now=()=>10000;s.speedBaseTime=0;s.speedBaseBytes=0;s.speedReady=true;
    s.next=1;s.sentThrough=1;s.acknowledged=CHUNK_SIZE;
    transferProgress(s,4);assert.equal(s.acknowledged,CHUNK_SIZE);
    assert.match(byId('transferDetails').textContent,/409\.6 KB\/秒/);assert.match(byId('transferDetails').textContent,/分钟/);
    const estimate=byId('transferDetails').textContent;
    transferProgress(s,0);assert.equal(s.acknowledged,CHUNK_SIZE);
    assert.equal(byId('transferDetails').textContent,estimate);
    assert.notEqual(byId('progressPercent').textContent,'0%');
    performance.now=()=>20000;transferProgress(s,0);assert.match(byId('transferDetails').textContent,/204\.8 KB\/秒/);
    s.paused=true;transferProgress(s);assert.doesNotMatch(byId('transferDetails').textContent,/\/秒|约剩/);
    """)


def test_pendingxhr_fast_no_ack_has_no_bogus_speed_or_eta():
    _run_page_js(render_demo2_upload_html(), SETUP, COMMON + r"""
    performance.now=()=>10;s.speedBaseTime=0;s.speedBaseBytes=0;s.speedReady=true;
    transferProgress(s,CHUNK_SIZE);
    assert.match(byId('progressLabel').textContent,/已发出，等待服务器确认/);
    assert.match(byId('transferDetails').textContent,/正在测速/);
    assert.doesNotMatch(byId('transferDetails').textContent,/\/秒|约剩/);
    assert.equal(s.acknowledged,0);assert.notEqual(byId('progressPercent').textContent,'100%');
    performance.now=()=>120000;transferProgress(s,CHUNK_SIZE);
    assert.doesNotMatch(byId('transferDetails').textContent,/\/秒|约剩/);
    s.next=1;s.acknowledged=CHUNK_SIZE;transferProgress(s);
    assert.match(byId('transferDetails').textContent,/34\.1 KB\/秒/);
    """)


def test_first_ack_too_early_has_no_rate_and_resume_rebases_after_reconciliation():
    _run_page_js(render_demo2_upload_html(), SETUP, COMMON + r"""
    performance.now=()=>10;s.speedBaseTime=0;s.speedBaseBytes=0;s.speedReady=true;
    s.acknowledged=CHUNK_SIZE;transferProgress(s);assert.doesNotMatch(byId('transferDetails').textContent,/\/秒|约剩/);
    performance.now=()=>100000;s.acknowledged=0;serverNext=1;
    sendBinaryChunk=async current=>{
      assert.equal(current.speedBaseBytes,CHUNK_SIZE);assert.equal(current.speedBaseTime,100000);
      assert.match(byId('transferDetails').textContent,/正在测速/);
      assert.doesNotMatch(byId('transferDetails').textContent,/\/秒|约剩/);
      current.paused=true;throw new Error('synthetic pause');
    };
    s.sentThrough=1;await runUpload(s);
    assert.equal(s.paused,true);assert.equal(s.acknowledged,CHUNK_SIZE);
    performance.now=()=>200000;
    sendBinaryChunk=async current=>{
      assert.equal(current.speedBaseBytes,CHUNK_SIZE);assert.equal(current.speedBaseTime,200000);
      assert.doesNotMatch(byId('transferDetails').textContent,/\/秒|约剩/);
      current.paused=true;throw new Error('synthetic pause');
    };
    await runUpload(s);assert.doesNotMatch(byId('transferDetails').textContent,/\/秒|约剩/);
    """)


def test_real_api_401_preserves_file_without_navigation():
    _run_page_js(render_demo2_upload_html(), SETUP, COMMON + r"""
    api=realApi;replies.push({status:401});
    await assert.rejects(reconcileUpload(s),error=>error.status===401);
    assert.equal(location.assigned,undefined);assert.equal(uploadSession.file,file);
    assert.equal(uploadInProgress,true);
    """)


def test_resume_fetch_timeout_is_bounded_and_cleans_timer():
    _run_page_js(render_demo2_upload_html(), SETUP, COMMON + r"""
    api=realApi;replies.push((url,options)=>new Promise((resolve,reject)=>{
      options.signal.addEventListener('abort',()=>{const error=new Error('aborted');error.name='AbortError';reject(error);});
    }));
    const pending=api(API_ROUTES.resume,{method:'POST',timeoutMs:60000});
    const timer=[...timers.values()].find(item=>item.delay===60000);assert.ok(timer);timer.fn();
    await assert.rejects(pending);assert.ok(![...timers.values()].some(item=>item.delay===60000));
    assert.equal(uploadSession.file,file);
    """)


def test_new_task_visible_and_paused_cancellation_stops_session():
    _run_page_js(render_demo2_upload_html(), SETUP, COMMON + r"""
    uploadSession=null;setUploadBusy(false);workspace.remaining_slots=5;workspace.used_slots=0;
    byId('videoFile').files=[file];byId('courseName').value='Synthetic lesson';
    const routes=[];
    api=async(url,options)=>{routes.push(url);if(url===API_ROUTES.tasks)return {task:serverTask()};assert.equal(url,API_ROUTES.cancel);return {};};
    runUpload=async current=>{current.paused=true;current.running=false;};
    await uploadVideo();assert.equal(workspace.tasks.length,1);assert.equal(workspace.remaining_slots,4);
    assert.match(byId('taskList').innerHTML,/data-cancel-task="video-1"/);
    assert.equal(uploadSession.file,file);await cancelTask('video-1');
    assert.equal(uploadSession,null);assert.equal(uploadInProgress,false);
    assert.deepEqual(routes,[API_ROUTES.tasks,API_ROUTES.cancel]);
    """)


def test_uncertain_create_refreshes_workspace_without_creating_again():
    _run_page_js(render_demo2_upload_html(), SETUP, COMMON + r"""
    uploadSession=null;setUploadBusy(false);workspace.remaining_slots=5;
    byId('videoFile').files=[file];byId('courseName').value='Synthetic lesson';
    let created=0,refreshed=0;
    api=async(url)=>{assert.equal(url,API_ROUTES.tasks);created++;throw new Error('response lost');};
    loadWorkspace=async()=>{refreshed++;workspace.tasks=[serverTask()];};
    await uploadVideo();assert.equal(created,1);assert.equal(refreshed,1);
    assert.equal(uploadSession,null);assert.equal(byId('videoFile').files[0],file);
    """)


@pytest.mark.parametrize('duration', ['3600', '1800', '0', '-1', 'NaN', '3600.01'])
def test_metadata_duration_boundary_and_url_cleanup(duration):
    _run_page_js(render_demo2_upload_html(), SETUP, f"metadataDuration={duration};" + r"""
    const file=new File(['synthetic'],'lesson.mp4');
    if(Number.isFinite(metadataDuration)&&metadataDuration>0&&metadataDuration<=3600)
      assert.equal(await preflightVideo(file),metadataDuration);
    else await assert.rejects(preflightVideo(file));
    assert.equal(metadataVideos[0].preload,'metadata');assert.equal(metadataVideos[0].src,'');
    assert.equal(metadataVideos[0].onloadedmetadata,null);assert.equal(metadataVideos[0].onerror,null);
    assert.equal(revokedURLs.length,1);assert.ok(![...timers.values()].some(t=>t.delay===15000));
    """)


@pytest.mark.parametrize('mode', ['error', 'timeout', 'too_long'])
def test_metadata_failure_creates_no_task_and_releases_controls(mode):
    _run_page_js(render_demo2_upload_html(), SETUP, COMMON + f"const failure={mode!r};" + r"""
    uploadSession=null;setUploadBusy(false);workspace.remaining_slots=5;workspace.max_video_bytes=1024**3;
    byId('videoFile').files=[file];byId('courseName').value='Synthetic lesson';
    metadataMode=failure==='timeout'?'pending':failure==='error'?'error':'ready';
    if(failure==='too_long')metadataDuration=3601;
    let created=0,refreshed=0;api=async()=>{created++;throw new Error('Unexpected request');};
    loadWorkspace=async()=>{refreshed++;};
    const pending=uploadVideo();
    if(failure==='timeout'){assert.ok([...timers.values()].find(t=>t.delay===15000));[...timers.values()].find(t=>t.delay===15000).fn();}
    await pending;assert.equal(created,0);assert.equal(refreshed,0);assert.equal(uploadInProgress,false);
    assert.equal(uploadSession,null);assert.equal(revokedURLs.length,1);assert.equal(byId('videoFile').files[0],file);
    assert.match(byId('pageMessage').textContent,failure==='too_long'?/60 分钟/:/MP4/);
    """)


@pytest.mark.parametrize('size,limit,allowed', [
    (round(669.7 * 1024**2), 1024**3, True),
    (1024**3, 1024**3, True),
    (1024**3 + 1, 1024**3, False),
    (1024**3 + 1, 5 * 1024**3, False),
    (600 * 1024**2, 512 * 1024**2, False),
])
def test_new_task_uses_workspace_limit_capped_at_one_gib(size, limit, allowed):
    _run_page_js(render_demo2_upload_html(), SETUP, COMMON + f"const size={size},limit={limit},allowed={str(allowed).lower()};" + r"""
    uploadSession=null;setUploadBusy(false);workspace.remaining_slots=5;workspace.max_video_bytes=limit;
    const selected={name:'synthetic.mp4',size,type:'video/mp4'};
    byId('videoFile').files=[selected];byId('courseName').value='Synthetic lesson';
    let created=0;api=async(url,options)=>{assert.equal(url,API_ROUTES.tasks);created++;
      assert.equal(JSON.parse(options.body).byte_size,size);return {task:{task_id:'large',course_id:'course-1',byte_size:size,upload_status:'uploading'}};};
    runUpload=async()=>{};await uploadVideo();assert.equal(created,allowed?1:0);
    assert.equal(metadataVideos.length,allowed?1:0);
    """)


def test_file_change_during_metadata_prevents_stale_task_creation():
    _run_page_js(render_demo2_upload_html(), SETUP, COMMON + r"""
    uploadSession=null;setUploadBusy(false);workspace.remaining_slots=5;
    byId('videoFile').files=[file];byId('courseName').value='Synthetic lesson';metadataMode='pending';
    let created=0;api=async()=>{created++;throw new Error('Unexpected request');};
    const pending=uploadVideo();
    byId('videoFile').files=[new File(['different'],'different.mp4')];await byId('videoFile').fire('change');
    metadataVideos[0].onloadedmetadata();await pending;
    assert.equal(created,0);assert.equal(uploadInProgress,false);assert.equal(revokedURLs.length,1);
    assert.match(byId('pageMessage').textContent,/已变化/);
    """)


def test_legacy_large_avi_resume_bypasses_new_file_preflight():
    _run_page_js(render_demo2_upload_html(), SETUP, COMMON + r"""
    uploadSession=null;setUploadBusy(false);workspace.max_video_bytes=1024**3;serverNext=1;schoolState='error';
    const oldFile={name:'legacy.avi',size:5*1024**3,slice:()=>new Blob([new Uint8Array(CHUNK_SIZE)])};
    s.file=oldFile;s.total=Math.ceil(oldFile.size/CHUNK_SIZE);resumeTaskId='video-1';byId('resumeVideoFile').files=[oldFile];
    let resumed=false,verified=false;
    api=async(url,options)=>{if(url.startsWith(API_ROUTES.task+'?'))return {task:serverTask()};
      assert.equal(url,API_ROUTES.resume);assert.equal(JSON.parse(options.body).byte_size,oldFile.size);
      assert.equal(JSON.parse(options.body).chunk_sha256.length,1);verified=true;return {task:serverTask()};};
    runUpload=async current=>{assert.equal(verified,true);assert.equal(current.file,oldFile);resumed=true;};
    await resumeSelectedFile();assert.equal(resumed,true);assert.equal(metadataVideos.length,0);
    """)


@pytest.mark.parametrize('context', [None, [], {}, {'city':'City','district':'District'},
    {'city':'City','district':' ','school_name':'School'}, {'city':123,'district':'District','school_name':'School'}])
def test_incomplete_or_malformed_school_blocks_only_new_tasks(context):
    _run_page_js(render_demo2_upload_html(), SETUP, COMMON + 'const context=' + json.dumps(context) + ';' + r"""
    uploadSession=null;setUploadBusy(false);workspace.remaining_slots=5;byId('videoFile').files=[file];
    api=realApi;replies.push({context});await loadSchoolContext();
    assert.notEqual(schoolState,'ready');assert.equal(byId('uploadButton').disabled,true);
    assert.equal(byId('completeSchoolLink').hidden,false);assert.equal(byId('reloadSchoolButton').disabled,false);
    const count=requests.length;await uploadVideo();assert.equal(requests.length,count);
    assert.equal(byId('videoFile').files[0],file);assert.equal(location.assigned,undefined);
    """)


def test_school_read_failure_retry_requires_successful_full_response():
    _run_page_js(render_demo2_upload_html(), SETUP, COMMON + r"""
    uploadSession=null;setUploadBusy(false);workspace.remaining_slots=5;byId('videoFile').files=[file];
    api=realApi;replies.push(new Error('offline'));await loadSchoolContext();
    assert.equal(schoolState,'error');assert.equal(byId('uploadButton').disabled,true);
    replies.push({context:{city:'City',district:'District',school_name:'School'}});await loadSchoolContext();
    assert.equal(schoolState,'ready');assert.equal(byId('uploadButton').disabled,false);
    assert.equal(byId('completeSchoolLink').hidden,true);assert.equal(byId('videoFile').files[0],file);
    """)


def test_school_401_reload_preserves_selected_file_and_page():
    _run_page_js(render_demo2_upload_html(), SETUP, COMMON + r"""
    uploadSession=null;setUploadBusy(false);byId('videoFile').files=[file];api=realApi;
    replies.push({status:401});await loadSchoolContext();assert.equal(schoolState,'error');
    assert.equal(location.assigned,undefined);assert.equal(byId('videoFile').files[0],file);
    """)


def test_create_school_required_has_clear_link_and_does_not_refresh_or_create_again():
    _run_page_js(render_demo2_upload_html(), SETUP, COMMON + r"""
    uploadSession=null;setUploadBusy(false);workspace.remaining_slots=5;
    byId('videoFile').files=[file];byId('courseName').value='Synthetic';api=realApi;
    loadWorkspace=async()=>assert.fail('School rejection is not uncertain creation');
    replies.push({status:409,body:{error:{code:'school_context_required',message:'school_context_required'}}});
    await uploadVideo();assert.equal(schoolState,'incomplete');assert.equal(uploadInProgress,false);
    assert.equal(byId('completeSchoolLink').hidden,false);assert.match(byId('pageMessage').textContent,/补全学校信息/);
    assert.doesNotMatch(byId('pageMessage').textContent,/school_context_required/);
    assert.equal(byId('videoFile').files[0],file);assert.equal(location.assigned,undefined);
    assert.equal(requests.filter(r=>r.url===API_ROUTES.tasks).length,1);
    """)


def test_school_stale_response_cannot_overwrite_newer_result():
    _run_page_js(render_demo2_upload_html(), SETUP, COMMON + r"""
    let first,second;api=()=>new Promise(resolve=>{if(!first)first=resolve;else second=resolve;});
    const a=loadSchoolContext(),b=loadSchoolContext();
    second({context:{city:'City',district:'District',school_name:'School'}});await b;
    first({context:{}});await a;assert.equal(schoolState,'ready');
    """)


def test_busy_and_paused_hint_does_not_invite_new_upload():
    _run_page_js(render_demo2_upload_html(), SETUP, COMMON + r"""
    updateUploadEnabled();assert.match(byId('filePreview').textContent,/正在上传/);
    assert.doesNotMatch(byId('filePreview').textContent,/点击.*确认授权/);
    pauseUpload();assert.match(byId('filePreview').textContent,/已暂停/);
    assert.match(byId('filePreview').textContent,/继续上传/);
    s.paused=false;transferControls(s);assert.match(byId('filePreview').textContent,/正在上传/);
    """)


@pytest.mark.parametrize('duration', ['1800', '3601', 'Infinity'])
def test_infinite_webm_seek_is_bounded_and_still_enforces_duration(duration):
    _run_page_js(render_demo2_upload_html(), SETUP, f"const recovered={duration};" + r"""
    metadataMode='pending';metadataDuration=Infinity;
    const pending=preflightVideo(new File(['synthetic'],'recording.webm'));
    const video=metadataVideos[0];video.onloadedmetadata();assert.equal(video.currentTime,1e10);
    video.duration=recovered;
    if(recovered===Infinity)[...timers.values()].find(t=>t.delay===15000).fn();
    else video.ondurationchange();
    if(recovered<=3600)assert.equal(await pending,recovered);else await assert.rejects(pending);
    assert.equal(revokedURLs.length,1);assert.equal(video.onseeked,null);assert.equal(video.ondurationchange,null);
    """)


def test_school_completion_link_opens_separately():
    html=render_demo2_upload_html()
    assert 'id="completeSchoolLink" href="/demo2/school" target="_blank" rel="noopener noreferrer"' in html
