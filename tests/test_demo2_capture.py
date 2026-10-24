"""Recording-page upload contracts; synthetic blobs and isolated browser only."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from rehab_affect.demo2_capture import render_capture
from test_demo2_portal_html import _run_page_js


ENV = r"""
const confirm=()=>true,intervals=new Map();let intervalId=0;
const setInterval=(fn,delay)=>{intervals.set(++intervalId,{fn,delay});return intervalId;};
const clearInterval=id=>intervals.delete(id);
class MediaRecorder{
 static isTypeSupported(){return true;}
 constructor(stream,options){this.state='inactive';this.mimeType=options.mimeType;}
 start(){this.state='recording';}
 stop(){this.state='inactive';this.onstop?.();}
}
const revoked=[];URL.createObjectURL=()=> 'blob:synthetic-recording';URL.revokeObjectURL=value=>revoked.push(value);
const event={preventDefault(){}};
const prepareClip=(size=5*1024*1024)=>{
 blob=new Blob([new Uint8Array(size)],{type:'video/webm'});blobUrl='blob:synthetic-recording';clipType='video/webm';
 $('download').href=blobUrl;$('download').hidden=false;$('download').download='synthetic.webm';
 $('courseId').value='course-1';$('courseName').value='Synthetic course';$('uploadConsent').checked=true;controls();
};
const workspaceReply=(tasks=[])=>({ok:true,workspace:{account:{username:'synthetic',bound_channel_id:'channel-1'},channel:{channel_id:'channel-1'},tasks,chunk_size_bytes:4*1024*1024}});
const ack=(next,overrides={})=>({task_id:'task-1',course_id:'course-1',byte_size:blob.size,total_chunks:Math.ceil(blob.size/CHUNK_SIZE),
 next_chunk_index:next,received_bytes:Math.min(next*CHUNK_SIZE,blob.size),upload_status:next===Math.ceil(blob.size/CHUNK_SIZE)?'completed':'uploading',...overrides});
const reply=task=>({ok:true,task});
const submitSave=async()=>{
 let done=false;const saving=$('saveForm').onsubmit(event).finally(()=>done=true);
 for(let round=0;!done&&round<100;round++){
   await flush();for(const [id,t] of [...timers])if(t.delay<=4000){timers.delete(id);t.fn();}
 }
 assert.equal(done,true,'Save did not settle');await saving;
};
const chunks=()=>requests.filter(r=>r.url.includes('/upload/chunks?'));
const creates=()=>requests.filter(r=>r.url.endsWith('/upload/tasks'));
"""


def run(assertions):
    _run_page_js(render_capture({'role': 'school_uploader'}), ENV, assertions)


def test_generated_capture_javascript_limits_and_school_link():
    html = render_capture({'role': 'school_uploader'})
    assert '单段最多15分钟 / 256MB' in html
    assert 'sec>=900' in html and 'MAX_RECORD_BYTES=256*1024*1024' in html
    assert 'id="schoolLink"' in html and 'href="/demo2/school" target="_blank" rel="noopener"' in html
    assert 'content_base64' not in html and 'readAsDataURL' not in html
    node = shutil.which('node')
    if not node:
        pytest.skip('Node required')
    script = '\n'.join(re.findall(r'<script>(.*?)</script>', html, re.S))
    result = subprocess.run([node, '--check'], input=script, encoding='utf-8', capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('size', [2 * 1024 * 1024, 5 * 1024 * 1024])
def test_recording_over_one_mib_uses_exact_binary_chunks(size):
    run(r"""
    prepareClip(__SIZE__);const original=blob;
    replies.push(workspaceReply(),reply(ack(0)),reply(ack(0)),reply(ack(1)));
    if(blob.size>CHUNK_SIZE)replies.push(reply(ack(2)));
    await submitSave();assert.equal(saved,true);assert.equal(blob,original);assert.equal(creates().length,1);
    const payload=JSON.parse(creates()[0].options.body);assert.equal(payload.total_chunks,Math.ceil(blob.size/CHUNK_SIZE));
    assert.equal(payload.allow_company_archive,false);assert.equal(payload.security_confirmed,true);
    assert.equal(chunks().length,payload.total_chunks);
    for(const [index,request] of chunks().entries()){
      assert.equal(request.options.headers['Content-Type'],'application/octet-stream');assert.ok(request.options.body instanceof Blob);
      assert.equal(request.options.body.size,Math.min(CHUNK_SIZE,blob.size-index*CHUNK_SIZE));
      assert.equal(request.url,API+'/upload/chunks?task_id=task-1&course_id=course-1&chunk_index='+index);
      assert.equal(request.options.credentials,'same-origin');
    }
    assert.equal($('progress').value,100);assert.equal($('upload').disabled,true);assert.equal(timers.size,0);
    """.replace('__SIZE__', str(size)))


def test_lost_ack_reconciles_before_next_chunk_no_duplicate_task_or_chunk():
    run(r"""
    prepareClip();replies.push(workspaceReply(),reply(ack(0)),reply(ack(0)),new TypeError('network lost'),reply(ack(1)),reply(ack(2)));
    await submitSave();assert.equal(saved,true);assert.equal(creates().length,1);
    assert.deepEqual(chunks().map(r=>new URL(r.url,'http://synthetic').searchParams.get('chunk_index')),['0','1']);
    assert.equal(requests[4].url,API+'/upload/task?id=task-1');assert.equal(timers.size,0);
    """)


def test_bounded_retry_then_manual_click_uses_current_next_and_preserves_blob():
    run(r"""
    prepareClip();const original=blob;replies.push(workspaceReply(),reply(ack(0)),reply(ack(0)));
    for(let i=0;i<4;i++){replies.push(new TypeError('offline'));if(i<3)replies.push(reply(ack(0)));}
    await submitSave();assert.equal(chunks().length,4);assert.equal(saved,false);assert.equal(uploading,false);
    assert.equal(blob,original);assert.equal($('download').href,'blob:synthetic-recording');assert.deepEqual(revoked,[]);
    assert.equal($('upload').disabled,false);assert.match($('saveState').textContent,/再次点击保存/);
    replies.push(reply(ack(1)),reply(ack(2)));await submitSave();
    assert.equal(saved,true);assert.equal(creates().length,1);assert.equal(chunks().length,5);
    assert.match(chunks().at(-1).url,/chunk_index=1$/);
    """)


def test_final_ack_loss_recognizes_completed_task_without_resending():
    run(r"""
    prepareClip(2*1024*1024);replies.push(workspaceReply(),reply(ack(0)),reply(ack(0)),new TypeError('lost'),reply(ack(1)));
    await submitSave();assert.equal(saved,true);assert.equal(chunks().length,1);
    """)


def test_chunk_timeout_180_seconds_and_double_submit_guard():
    run(r"""
    prepareClip(2*1024*1024);replies.push(workspaceReply(),reply(ack(0)),reply(ack(0)),
      (_url,options)=>new Promise((resolve,reject)=>options.signal.addEventListener('abort',()=>reject(Object.assign(new Error(),{name:'AbortError'})))),reply(ack(1)));
    const saving=$('saveForm').onsubmit(event);await flush();
    const timeout=[...timers.values()].find(t=>t.delay===180000);assert.ok(timeout);
    await $('saveForm').onsubmit(event);assert.equal(creates().length,1);assert.equal(chunks().length,1);
    timeout.fn();await flush();for(const [id,t] of [...timers])if(t.delay<=4000){timers.delete(id);t.fn();}await saving;
    assert.equal(saved,true);assert.equal(chunks().length,1);assert.equal(timers.size,0);
    """)


@pytest.mark.parametrize('status,code', [(401, 'authentication_required'), (403, 'forbidden'), (409, 'chunk_size_conflict'),
                                      (410, 'expired'), (413, 'too_large'), (507, 'insufficient_storage')])
def test_nonretryable_chunk_failures_keep_local_recording(status, code):
    run(r"""
    prepareClip();const original=blob;replies.push(workspaceReply(),reply(ack(0)),reply(ack(0)),{status:__STATUS__,body:{error:{code:__CODE__,message:'Synthetic failure'}}});
    await submitSave();assert.equal(saved,false);assert.equal(blob,original);assert.equal(chunks().length,1);
    assert.equal($('upload').disabled,false);assert.equal($('download').hidden,false);assert.equal(timers.size,0);
    """.replace('__STATUS__', str(status)).replace('__CODE__', json.dumps(code)))


def test_missing_school_409_new_tab_link_and_retry_do_not_destroy_blob():
    run(r"""
    prepareClip(2*1024*1024);const original=blob;
    replies.push(workspaceReply(),{status:409,body:{error:{code:'school_context_required',message:'请先保存学校信息'}}});
    await submitSave();assert.equal($('schoolLink').hidden,false);assert.equal(blob,original);assert.equal(uploadSession,null);
    assert.equal(chunks().length,0);assert.equal($('courseId').disabled,false);assert.match($('saveState').textContent,/不要刷新/);
    replies.push(workspaceReply(),reply(ack(0)),reply(ack(0)),reply(ack(1)));await submitSave();
    assert.equal(saved,true);assert.equal(blob,original);assert.equal($('schoolLink').hidden,true);
    """)


def test_uncertain_creation_is_recovered_by_session_not_recreated():
    run(r"""
    prepareClip(2*1024*1024);replies.push(workspaceReply(),new TypeError('creation response lost'));
    await submitSave();assert.equal(saved,false);assert.equal(uploadSession.creationUncertain,true);assert.equal(creates().length,1);
    replies.push(workspaceReply());await submitSave();assert.equal(creates().length,1);assert.match($('saveState').textContent,/未重复创建/);
    const found=ack(0,{session_id:uploadSession.sessionId});replies.push(workspaceReply([found]),reply(ack(0)),reply(ack(1)));
    await submitSave();assert.equal(saved,true);assert.equal(creates().length,1);
    """)


@pytest.mark.parametrize('change', ["value.task_id='other'", "value.course_id='other'", "value.byte_size+=1",
                                  "value.next_chunk_index=2", "value.received_bytes=10", "value.upload_status='cancelled'",
                                  "value.raw_media_deleted_at='2026-10-20'", "delete value.next_chunk_index"])
def test_inconsistent_task_never_uploads_or_claims_success(change):
    run(r"""
    prepareClip();const value=ack(0);__CHANGE__;
    replies.push(workspaceReply(),reply(ack(0)),reply(value));await submitSave();
    assert.equal(saved,false);assert.equal(chunks().length,0);assert.match($('saveState').textContent,/不一致|失效/);
    """.replace('__CHANGE__', change))


def test_no_consent_oversize_and_mismatched_workspace_size_never_create():
    run(r"""
    prepareClip();$('uploadConsent').checked=false;await submitSave();assert.equal(requests.length,0);
    $('uploadConsent').checked=true;blob={size:MAX_RECORD_BYTES+1};await submitSave();assert.equal(requests.length,0);
    prepareClip();const mismatch=workspaceReply();mismatch.workspace.chunk_size_bytes=1024*1024;
    replies.push(mismatch);await submitSave();assert.equal(creates().length,0);assert.equal(saved,false);
    """)


def test_new_recording_resets_upload_state_and_original_time_size_limits():
    run(r"""
    prepareClip();uploadSession={taskId:'old'};task={task_id:'old'};stream={getTracks:()=>[]};
    $('record').onclick();assert.equal(uploadSession,null);assert.equal(task,null);assert.equal(blob,null);
    assert.equal(recorder.state,'recording');started=Date.now()-900000;
    [...intervals.values()].find(t=>t.delay===1000).fn();assert.equal(recorder.state,'inactive');
    stream={getTracks:()=>[]};$('record').onclick();let stopped=false;
    recorder.stop=()=>{stopped=true;recorder.state='inactive';};recorder.ondataavailable({data:{size:MAX_RECORD_BYTES}});
    assert.equal(stopped,true);assert.equal(bytes,MAX_RECORD_BYTES);
    """)


def test_isolated_browser_school_blocker_lost_ack_and_binary_recording(tmp_path):
    node = shutil.which('node')
    candidates = [os.environ.get('DEMO2_PLAYWRIGHT_MODULE', ''),
                  str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'),
                  str(Path.home() / 'AppData/Local/npm-cache/_npx/31e32ef8478fbf80/node_modules/playwright')]
    module = next((value for value in candidates if value and Path(value).exists()), None)
    if not node or not module:
        pytest.skip('Installed Node/Playwright required; no downloads')
    cache = Path(os.environ.get('PLAYWRIGHT_BROWSERS_PATH', str(Path.home() / 'AppData/Local/ms-playwright')))
    candidates = [os.environ.get('DEMO2_BROWSER_EXECUTABLE', ''),
                  *(str(p) for p in sorted(cache.glob('chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe'), reverse=True)),
                  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe']
    executable = next((value for value in candidates if value and Path(value).exists()), None)
    data = {'module': module, 'executable': executable, 'shots': str(tmp_path),
            'html': render_capture({'role': 'school_uploader'})}
    script = r"""
const input=JSON.parse(require('node:fs').readFileSync(0,'utf8')),assert=require('node:assert/strict');
const {chromium}=require(input.module),browser=await chromium.launch({headless:true,...(input.executable?{executablePath:input.executable}:{})});
try{
 const page=await browser.newPage(),errors=[],external=[],uploads=[];
 let school=false,created=0,createCalls=0,next=0;
 const task=()=>({task_id:'t1',course_id:'c1',byte_size:5*1024*1024,total_chunks:2,next_chunk_index:next,
   received_bytes:Math.min(next*4*1024*1024,5*1024*1024),upload_status:next===2?'completed':'uploading'});
 page.on('pageerror',error=>errors.push(error.message));
 await page.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url());
   if(url.origin!=='https://capture.test'){external.push(request.url());return route.abort();}
   const json=(value,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(value)});
   if(url.pathname==='/demo2/capture')return route.fulfill({contentType:'text/html',body:input.html});
   if(url.pathname.endsWith('/workspace'))return json({ok:true,workspace:{account:{username:'synthetic',bound_channel_id:'ch1'},channel:{channel_id:'ch1'},tasks:[]}});
   if(url.pathname.endsWith('/tasks')){
     createCalls++;if(!school)return json({error:{code:'school_context_required',message:'请先保存学校信息'}},409);
     const payload=request.postDataJSON();assert.equal(payload.total_chunks,2);assert.equal(payload.allow_company_archive,false);
     created++;return json({ok:true,task:task()});
   }
   if(url.pathname.endsWith('/task'))return json({ok:true,task:task()});
   if(url.pathname.endsWith('/chunks')){
     assert.equal(request.headers()['content-type'],'application/octet-stream');assert.equal(url.searchParams.get('task_id'),'t1');assert.equal(url.searchParams.get('course_id'),'c1');
     const index=Number(url.searchParams.get('chunk_index')),bytes=request.postDataBuffer();
     assert.equal(index,next);assert.equal(bytes.length,index===0?4*1024*1024:1024*1024);uploads.push(index);next++;
     if(index===0)return route.abort('failed');return json({ok:true,task:task()});
   }
   external.push(request.url());return route.abort();
 });
 await page.goto('https://capture.test/demo2/capture');
 await page.evaluate(()=>{
   blob=new Blob([new Uint8Array(5*1024*1024)],{type:'video/webm'});clipType='video/webm';blobUrl=URL.createObjectURL(blob);
   $('download').href=blobUrl;$('download').download='synthetic.webm';$('download').hidden=false;
   $('clipInfo').textContent='Synthetic recording: 5 MB';controls();
 });
 await page.locator('#courseId').fill('c1');await page.locator('#courseName').fill('Synthetic course');await page.locator('#uploadConsent').check();
 await page.locator('#upload').click();await page.locator('#schoolLink').waitFor({state:'visible'});
 assert.equal(await page.locator('#schoolLink').getAttribute('target'),'_blank');assert.equal(await page.locator('#schoolLink').getAttribute('href'),'/demo2/school');
 assert.equal(await page.evaluate(()=>blob.size),5*1024*1024);assert.equal(created,0);assert.deepEqual(uploads,[]);
 assert.equal(await page.locator('#download').isVisible(),true);school=true;
 await page.locator('#upload').click();await page.waitForFunction(()=>saved===true);
 assert.equal(created,1);assert.equal(createCalls,2);assert.deepEqual(uploads,[0,1]);
 assert.equal(await page.locator('#progress').getAttribute('value'),'100');assert.equal(await page.locator('#upload').isDisabled(),true);
 assert.equal(await page.evaluate(()=>blob.size),5*1024*1024);
 for(const width of [390,1366]){await page.setViewportSize({width,height:900});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:input.shots+'/capture-'+width+'.png',fullPage:true});}
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
}finally{await browser.close();}
"""
    result = subprocess.run([node, '-e', '(async()=>{' + script + '})().catch(e=>{console.error(e);process.exit(1)});'],
                            input=json.dumps(data), encoding='utf-8', capture_output=True, timeout=55)
    assert result.returncode == 0, result.stdout + result.stderr
