"""Identity UI contracts plus isolated Playwright interactions (no live API writes)."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from rehab_affect.demo2_identity import render_identity, render_students
from rehab_affect.demo2_entry import render_school
from rehab_affect.demo2_portal import render_demo2_upload_html
from rehab_affect.demo2_video_review import render_video_review


TEACHER = {"role": "school_uploader", "username": "teacher-contract-test"}


def test_identity_pages_are_separate_protected_and_script_safe():
    for render in (render_students, render_identity):
        html = render({"role": "school_uploader", "username": "</script><script>alert(1)</script>"})
        assert '<html lang="zh-CN">' in html
        assert 'name="viewport"' in html
        assert 'href="#mainContent"' in html
        assert "credentials:'same-origin'" in html
        assert "AbortController" in html
        assert "网络连接失败，请检查网络后重试" in html
        assert "</script><script>alert(1)</script>" not in html
        assert "\\u003c/script\\u003e" in html
        assert "<script src=" not in html
        assert "<canvas" not in html and "toDataURL" not in html
        assert "localStorage" not in html
        assert "beforeunload" in html
        assert "@media(max-width:400px)" in html
    html = render_identity(TEACHER)
    for value in ("frame_revision", "student_id:studentId", "bbox:normalizedBox(box)", "setPointerCapture",
                  "pointercancel", "current_revision", "getBoundingClientRect", "returntask=",
                  "撤销原因", "仅对应当前采样帧", "object-fit:contain", "!validBox(box)",
                  "continueToResults", "下一步：查看学生状态"):
        assert value in html
    assert "role==='student'?$('studentSelect').value:null" in html
    assert "item.display_name" not in html
    assert 'id="bboxX"' in html and 'id="bboxHeight"' in html
    assert "display_name" in render_students(TEACHER)
    assert 'id="studentCode" maxlength="64"' in render_students(TEACHER)


def test_upload_and_video_entry_distinguish_planning_from_confirmed_identity():
    upload = render_demo2_upload_html(TEACHER)
    video = render_video_review(TEACHER)
    assert "计划关注学生" in upload
    assert 'id="channelSelect"' in upload
    assert "/demo2/students" not in upload
    assert "/demo2/identity?task_id=" in upload
    assert "确认画面中的学生" in upload and "查看视频证据" in upload
    assert "workspace?.available_students" not in upload
    assert "/identity/workspace?task_id=" in video
    assert "全画面的动作变化与同期音轨不能归因于某位学生" in video
    assert "work.students.find(s=>s.student_id===b.student_id)" in video
    assert "查看已确认身份" in video and "返回公司后台" in video


def test_identity_and_integration_inline_javascript_parses():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js required")
    html_pages = [render_students(TEACHER), render_identity(TEACHER),
                  render_demo2_upload_html(TEACHER), render_video_review(TEACHER), render_school(TEACHER)]
    scripts = [s for html in html_pages for s in re.findall(r"<script>(.*?)</script>", html, re.S)]
    result = subprocess.run([node, "-e", "JSON.parse(require('fs').readFileSync(0,'utf8')).forEach(s=>new Function(s))"],
                            input=json.dumps(scripts), text=True, encoding="utf-8", capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_identity_reference_and_layout_contracts():
    html = render_identity(TEACHER)
    for value in ("--blue:#2163C4", "letter-spacing:0", "24px/1.4", "20px/1.4",
                  'id="frameViewport"', 'id="previewDialog"', 'id="previewButton"',
                  "URL.createObjectURL(blob)", "URL.revokeObjectURL(previewUrl)",
                  "workspace?.media_available===true", "response.blob()", "image/jpeg",
                  "currentBinding(item)&&item.frame_key===frame()?.frame_key",
                  "按相近时刻解码，未必与采样帧逐帧一致", "<details", "prefers-reduced-motion"):
        assert value in html
    assert "__ICON_" not in html
    assert "先框选区域，再选择人员角色" not in html
    for rendered in (html, render_students(TEACHER)):
        ids = re.findall(r'\bid="([^"]+)"', rendered)
        assert len(ids) == len(set(ids))
    dialog = re.search(r'<dialog class="preview-dialog".*?</dialog>', html, re.S).group()
    assert '<img ' in dialog and '只读' in dialog
    assert not any(token in dialog for token in ("frameOverlay", "roi", "download", "<form", 'type="submit"'))


# Only the invented .test host is served. All records and the labelled geometry
# image below are test fixtures, never screenshots represented as real classrooms.
_BROWSER = r"""
const fs=require('node:fs'),assert=require('node:assert/strict');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const {chromium}=require(input.playwright);
const browser=await chromium.launch({headless:true,...(input.browser_executable?{executablePath:input.browser_executable}:{})});
try {
const context=await browser.newContext({viewport:{width:1440,height:1000}});
const page=await context.newPage();const errors=[],calls=[];page.on('pageerror',error=>errors.push(String(error)));
page.setDefaultTimeout(12000);page.setDefaultNavigationTimeout(15000);
await page.addInitScript(()=>{
 const stats=window.previewStats={created:[],revoked:[],aborted:0};window.trackAborted=0;const original=window.fetch;
 window.fetch=(url,options)=>{if(options?.credentials!=='same-origin')throw new Error('Missing same-origin credentials');if(String(url).includes('/identity/preview?')){if(options.cache!=='no-store')throw new Error('Preview must not use browser cache');options.signal.addEventListener('abort',()=>stats.aborted++);}if(String(url).endsWith('/identity/track'))options.signal.addEventListener('abort',()=>window.trackAborted++);return original(url,options);};
 const create=URL.createObjectURL.bind(URL),revoke=URL.revokeObjectURL.bind(URL);
 URL.createObjectURL=blob=>{const url=create(blob);stats.created.push(url);return url;};URL.revokeObjectURL=url=>{stats.revoked.push(url);return revoke(url);};
});
let students=[{student_id:'s1',display_name:'测试同名',student_code:'A01',class_name:'一班'}, {student_id:'s2',display_name:'测试同名',student_code:'B02',class_name:'二班'}];
let bindings=[],currentScope='scope-a',canEdit=true,mediaAvailable=true,frameList=[
{frame_key:'s0_f0',time_sec:0,segment_start_sec:0,segment_end_sec:10,image_url:'/api/v1/demo2/identity/frame?frame_key=s0_f0'},
{frame_key:'s1_f0',time_sec:10,segment_start_sec:10,segment_end_sec:20,image_url:'/api/v1/demo2/identity/frame?frame_key=s1_f0'}];
let detectionMode='faces',writeMode='success',workspaceStatus=200,detectWait=null,releaseOldDetection=null;
let needsSchoolConfirmation=false,canConfirmSchool=true,currentSchoolContext={city:'测试城市',district:'测试区县',school_name:'当前测试学校'};
let rosterMissing=false;
let previewStatus=200,previewMode='jpeg',previewWait=false,pendingPreviews=[];
let trackStatus=200,trackMode='completed',trackWait=false,pendingTrack=null,rosterCanEdit=true;
let taskSchoolContext={school_name:'测试学校（接口夹具）'},taskScope='scope-a';
const bindingTemplate={binding_id:'b0',role:'student',student_id:'s1',display_name:'不可信的错误姓名',frame_key:'s0_f0',frame_revision:'rev-1',current_revision:true,time_sec:0,status:'confirmed',bbox:{x:.1,y:.2,width:.25,height:.3}};
function workspace(){return {task_id:'task-1',course_id:'course-test',course_name:'前端契约测试课程',school_context:needsSchoolConfirmation?{city:'',district:'',school_name:''}:taskSchoolContext,scope_key:needsSchoolConfirmation?'':taskScope,students:needsSchoolConfirmation?[]:students,bindings,frames:frameList,frame_revision:'rev-1',summary:{},can_edit:canEdit,media_available:mediaAvailable,needs_school_confirmation:needsSchoolConfirmation,can_confirm_school:canConfirmSchool};}
await context.route('**/*',async route=>{
 const request=route.request(),url=new URL(request.url());if(url.origin!=='http://identity.test')throw new Error('Unexpected network origin');
 const data=request.postDataJSON();calls.push({path:url.pathname,query:url.search,method:request.method(),data});
 const json=(body,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
 if(url.pathname==='/demo2/identity')return route.fulfill({contentType:'text/html',body:input.identity});
 if(url.pathname==='/demo2/students')return route.fulfill({contentType:'text/html',body:input.students});
 if(url.pathname==='/demo2/video')return route.fulfill({contentType:'text/html',body:input.video});
 if(url.pathname==='/demo2/school')return route.fulfill({contentType:'text/html',body:input.school});
 if(url.pathname==='/demo2/upload')return route.fulfill({contentType:'text/html',body:'<h1>测试上传入口</h1>'});
 if(url.pathname==='/demo2/login')return route.fulfill({contentType:'text/html',body:'<h1>测试登录入口</h1>'});
 if(url.pathname==='/demo2/simple-result')return route.fulfill({contentType:'text/html',body:'<h1 id="studentStatusResult">student-status-result</h1>'});
 if(url.pathname.endsWith('/identity/roster'))return json({ok:true,roster:rosterMissing?null:{scope_key:currentScope,school_context:currentSchoolContext,students,can_edit:canEdit&&rosterCanEdit}});
 if(url.pathname.endsWith('/school/context')){if(request.method()==='POST'){currentSchoolContext={...data};currentScope='scope-updated';rosterMissing=false;canConfirmSchool=['city','district','school_name'].every(key=>!!data[key]);}return json({ok:true,context:currentSchoolContext,options:[]});}
 if(url.pathname.endsWith('/identity/task-school')){if(writeMode==='disconnect')return route.abort('internetdisconnected');if(writeMode==='stale'||data.expected_scope_key!==currentScope)return json({error:{message:'当前学校归属已变化，请刷新核对'}},409);assert.equal(needsSchoolConfirmation,true);assert.equal(data.confirmed,true);needsSchoolConfirmation=false;taskSchoolContext={...currentSchoolContext};taskScope=currentScope;return json({ok:true});}
 if(url.pathname.endsWith('/identity/workspace'))return workspaceStatus===200?json({ok:true,workspace:workspace()}):workspaceStatus===0?route.abort('internetdisconnected'):json({error:{message:workspaceStatus===409?'请刷新帧版本':'服务返回的具体错误'}},workspaceStatus);
 if(url.pathname.endsWith('/identity/frame')){const portrait=url.searchParams.get('frame_key')==='s1_f0';return route.fulfill({contentType:'image/svg+xml',body:`<svg xmlns="http://www.w3.org/2000/svg" width="${portrait?600:1280}" height="${portrait?900:720}"><rect width="100%" height="100%" fill="#eaf2fa"/><path d="M0 0L600 600M0 600L600 0" stroke="#cad7e6"/><text x="30" y="60" fill="#365779" font-size="22">TEST GEOMETRY FRAME (NOT CLASSROOM DATA)</text></svg>`});}
 if(url.pathname.endsWith('/identity/preview')){
   if(previewWait)await new Promise(resolve=>pendingPreviews.push(resolve));
   if(previewMode==='disconnect')return route.abort('internetdisconnected');
   if(previewStatus!==200)return json({error:{code:'preview_error',message:'Untrusted English error'}},previewStatus).catch(()=>{});
   const body=previewMode==='empty'?Buffer.alloc(0):previewMode==='invalid'||previewMode==='corrupt'?Buffer.from('invalid fixture'):Buffer.from(input.preview_image,'base64');
   return route.fulfill({contentType:previewMode==='invalid'?'application/json':'image/jpeg',headers:{'X-Preview-Cache':'hit'},body}).catch(()=>{});
 }
 if(url.pathname.endsWith('/identity/detect')){if(detectWait&&url.searchParams.get('frame_key')==='s0_f0')await new Promise(resolve=>releaseOldDetection=resolve);if(detectionMode==='error')return json({error:{message:'检测服务暂不可用'}},503);return json({ok:true,detection:{available:detectionMode!=='unavailable',reason:detectionMode==='unavailable'?'尚未配置检测模型':'',faces:detectionMode==='faces'?[{candidate_id:'candidate-1',bbox:{x:.1,y:.2,width:.25,height:.3},score:.8}]:[]}}).catch(()=>{});}
 if(url.pathname.endsWith('/identity/students')){if(writeMode==='disconnect')return route.abort('internetdisconnected');const student={student_id:'s'+(students.length+1),scope_key:currentScope,...data};students.push(student);return json({ok:true,student});}
 if(url.pathname.endsWith('/identity/track')){
   if(trackWait)await new Promise(resolve=>pendingTrack=resolve);
   if(trackStatus!==200)return json({error:{code:'track_error',message:'Untranslated failure'}},trackStatus).catch(()=>{});
   const points=[{frame_key:'s0_f0',time_sec:0,bbox:bindingTemplate.bbox,status:'seed',quality:1,reason:''},
     {frame_key:'s1_f0',time_sec:2,bbox:trackMode==='lost'?null:{x:.2,y:.3,width:.2,height:.2},status:trackMode==='lost'?'lost':'suggested',quality:trackMode==='lost'?null:.8,reason:trackMode==='lost'?'lost':''}];
   return json({ok:true,track:{binding_id:data.binding_id,student_id:'s1',display_name:'untrusted auto-name',frame_revision:data.frame_revision,scope:'short_window_suggestion',window_sec:5,algorithm:'opencv_lk',status:trackMode,points:trackMode==='insufficient'?[]:points,reason:trackMode,automatic_identity:false}}).catch(()=>{});
 }
 if(url.pathname.endsWith('/identity/bindings/revoke')){bindings=bindings.map(b=>b.binding_id===data.binding_id?{...b,status:'revoked',revoked_reason:data.reason}:b);return json({ok:true});}
 if(url.pathname.endsWith('/identity/bindings')){if(writeMode==='disconnect')return route.abort('internetdisconnected');if(writeMode==='stale')return json({error:{message:'采样帧版本已变化，请刷新后重新确认'}},409);if(writeMode==='indistinguishable')return json({error:{code:'indistinguishable_student_binding',message:'框几乎相同'}},409);if(writeMode==='overlap'&&!data.overlap_confirmed)return json({error:{code:'overlapping_student_binding',message:'部分重叠，请核对'}},409);const binding={...bindingTemplate,...data,binding_id:'b'+(bindings.length+1),time_sec:frameList.find(f=>f.frame_key===data.frame_key).time_sec};bindings.push(binding);return json({ok:true,binding});}
 if(url.pathname.endsWith('/upload/task'))return json({task:{task_id:'task-1',course_id:'course-test',analysis_status:'evidence_ready',upload_status:'completed'},result:{media:{duration_sec:20},segments:[]}});
 return route.fulfill({status:404,body:'Test route not provided'});
});
const openIdentity=async()=>{await page.goto('http://identity.test/demo2/identity?task_id=task-1');await page.waitForFunction(()=>!document.getElementById('refreshWorkspace').disabled);};
const imageReady=async()=>{await page.locator('#frameSurface').waitFor({state:'visible'});};
const candidatesReady=async()=>{await imageReady();await page.locator('[data-candidate="0"]').waitFor();};
const chooseCandidate=async()=>{await candidatesReady();await page.locator('[data-candidate="0"]').click();};
const advanced=async()=>{if(!await page.locator('#annotationAdvanced').evaluate(el=>el.open))await page.locator('#annotationAdvanced > summary').click();};
const selectRole=async role=>{await advanced();await page.locator('#personRole').selectOption(role);};
const coordinateBox=async()=>{await advanced();for(const [id,value]of Object.entries({bboxX:'10',bboxY:'20',bboxWidth:'25',bboxHeight:'30'}))await page.locator('#'+id).fill(value);};
const drawDraft=async()=>{await imageReady();await page.locator('#drawButton').click();await page.locator('#frameViewport').evaluate(el=>{el.scrollTop=0;el.scrollLeft=0;el.scrollIntoView({block:'center'});});const b=await page.locator('#frameImage').boundingBox();await page.mouse.move(b.x+b.width*.3,b.y+b.height*.2);await page.mouse.down();await page.mouse.move(b.x+b.width*.5,b.y+b.height*.4);await page.mouse.up();};
const saved=async(count)=>{await page.waitForFunction(n=>document.getElementById('bindingSummary').textContent.includes(n+' 条确认'),count);await page.waitForFunction(()=>!document.getElementById('refreshWorkspace').disabled);};
const postCalls=()=>calls.filter(c=>c.method==='POST');
const previewCalls=()=>calls.filter(c=>c.path.endsWith('/identity/preview'));
const noOverflow=async()=>{const sizes=await page.evaluate(()=>({width:innerWidth,scroll:document.documentElement.scrollWidth}));assert.ok(sizes.scroll<=sizes.width,JSON.stringify(sizes));};
const capture=async name=>{if(input.screenshot_dir){fs.mkdirSync(input.screenshot_dir,{recursive:true});await page.screenshot({path:require('path').join(input.screenshot_dir,name+'.png'),fullPage:true});}};
__SCENARIO__
assert.deepEqual(errors,[]);
await context.close();
} finally {await browser.close();}
"""


def _browser(scenario: str, *, account=None):
    import cv2
    import numpy as np

    node = shutil.which("node")
    candidates = [os.environ.get("DEMO2_PLAYWRIGHT_MODULE", ""),
                  str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright"),
                  str(Path.home() / "AppData/Local/npm-cache/_npx/31e32ef8478fbf80/node_modules/playwright")]
    module = next((path for path in candidates if path and Path(path).exists()), None)
    if not node or not module:
        pytest.skip("Installed Node.js and Playwright required; no automatic downloads")
    account = account or TEACHER
    # A labelled color JPEG, generated in memory; no classroom media is read.
    reference = np.full((540, 960, 3), (240, 245, 250), dtype=np.uint8)
    cv2.rectangle(reference, (60, 130), (460, 450), (60, 150, 40), -1)
    cv2.rectangle(reference, (500, 130), (900, 450), (25, 120, 220), -1)
    cv2.putText(reference, "SYNTHETIC COLOR REFERENCE - NOT CLASSROOM DATA", (25, 70),
                cv2.FONT_HERSHEY_SIMPLEX, .75, (40, 40, 40), 2)
    ok, encoded = cv2.imencode(".jpg", reference)
    assert ok
    data = {"preview_image": base64.b64encode(encoded).decode("ascii"),
            "playwright": module, "identity": render_identity(account), "students": render_students(account),
            "video": render_video_review(account), "school": render_school(account), "screenshot_dir": os.environ.get("DEMO2_IDENTITY_QA_DIR")}
    browser_cache = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or
                         str(Path(os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData/Local")) / "ms-playwright"))
    # Prefer an installed automation browser; keep an explicit override and Edge fallback.
    installed_chromium = [*sorted(browser_cache.glob("chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"), reverse=True),
                          *sorted(browser_cache.glob("chromium-*/chrome-win64/chrome.exe"), reverse=True)]
    browser_paths = [os.environ.get("DEMO2_BROWSER_EXECUTABLE", ""),
                     *(str(path) for path in installed_chromium),
                     "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"]
    data["browser_executable"] = next((path for path in browser_paths if path and Path(path).exists()), None)
    source = "(async()=>{" + _BROWSER.replace("__SCENARIO__", scenario) + "})().catch(e=>{console.error(e);process.exit(1)});"
    result = subprocess.run([node, "-e", source], input=json.dumps(data), text=True, encoding="utf-8",
                            capture_output=True, timeout=75)
    assert result.returncode == 0, result.stdout + result.stderr


def test_browser_student_default_and_direct_candidate_selection():
    _browser(r"""
    await openIdentity();await candidatesReady();assert.equal(await page.locator('#personRole').inputValue(),'student');
    assert.equal(await page.locator('#annotationAdvanced').evaluate(el=>el.open),false);assert.equal(await page.locator('#bboxX').isVisible(),false);
    assert.equal(await page.locator('#studentSelect').isVisible(),true);assert.equal(await page.locator('#saveBinding').isEnabled(),false);
    const b=await page.locator('#frameImage').boundingBox();await page.mouse.click(b.x+b.width*.2,b.y+b.height*.3);
    assert.equal(await page.locator('#bboxX').inputValue(),'10');assert.equal(await page.locator('#saveBinding').isEnabled(),false);
    await page.locator('#studentSelect').selectOption('s2');await page.locator('#saveBinding').click();await saved(1);
    assert.equal(postCalls()[0].data.role,'student');assert.equal(postCalls()[0].data.student_id,'s2');assert.match(await page.locator('#pageMessage').textContent(),/测试同名.*继续选择下一人/);
    assert.match(await page.locator('.roi.confirmed').textContent(),/B02/);assert.equal(await page.locator('#frameSelect').inputValue(),'0');
    assert.equal(await page.locator('#studentSelect').inputValue(),'');assert.equal(await page.locator('#saveBinding').isEnabled(),false);
    await capture('simple-student-desktop');await page.setViewportSize({width:320,height:900});await noOverflow();await capture('simple-student-320');
    """)


def test_browser_empty_roster_can_continue_to_student_results_after_candidate_selection():
    _browser(r"""
    students=[];await openIdentity();await chooseCandidate();
    assert.equal(await page.locator('#continueToResults').isVisible(),true);
    assert.match(await page.locator('#continueToResults').getAttribute('href'),/\/demo2\/simple-result\?task_id=task-1/);
    await page.locator('#continueToResults').click();await page.waitForURL(/\/demo2\/simple-result\?task_id=task-1/);
    assert.equal(await page.locator('#studentStatusResult').textContent(),'student-status-result');
    """)


def test_browser_school_draft_during_detection_preserves_roi_without_name_writes():
    _browser(r"""
    needsSchoolConfirmation=true;detectWait=true;await openIdentity();await imageReady();
    assert.equal(await page.locator('#drawButton').isEnabled(),true);assert.equal(await page.locator('#studentSelect').isEnabled(),false);
    assert.equal(await page.locator('#personRole').isEnabled(),false);assert.match(await page.locator('#saveGateReason').textContent(),/可画草稿.*确认学校/);
    await drawDraft();assert.ok(Math.abs(Number(await page.locator('#bboxX').inputValue())-30)<1);
    const before=await page.locator('.roi.selected').getAttribute('style');releaseOldDetection?.();await candidatesReady();
    assert.equal(await page.locator('.roi.selected').getAttribute('style'),before);assert.equal(await page.locator('#saveBinding').isEnabled(),false);
    await page.locator('#bindingForm').evaluate(el=>el.dispatchEvent(new Event('submit',{cancelable:true,bubbles:true})));assert.equal(postCalls().length,0);
    await page.locator('#schoolGateLink').click();assert.equal(await page.locator('#confirmTaskSchool').evaluate(el=>el===document.activeElement),true);
    detectWait=false;page.once('dialog',d=>d.accept());await page.locator('#confirmTaskSchool').click();await candidatesReady();
    assert.ok(Math.abs(Number(await page.locator('#bboxX').inputValue())-30)<1);assert.equal(await page.locator('#saveBinding').isEnabled(),false);
    await page.locator('#studentSelect').selectOption('s1');await page.locator('#saveBinding').click();await saved(1);
    assert.equal(postCalls().length,2);assert.ok(postCalls()[0].path.endsWith('/task-school'));assert.equal(postCalls()[1].data.role,'student');
    """)


def test_browser_inline_student_creation_keeps_draft_and_checks_scope():
    _browser(r"""
    await openIdentity();await drawDraft();const before=await page.locator('.roi.selected').getAttribute('style');
    await page.locator('#addStudent').click();await page.locator('#inlineStudentName').fill('新增真实姓名测试');await page.locator('#confirmNewStudent').click();
    await page.locator('#newStudentDialog').waitFor({state:'hidden'});assert.equal(await page.locator('.roi.selected').getAttribute('style'),before);
    assert.equal(await page.locator('#studentSelect').inputValue(),'s3');assert.equal(postCalls().length,1);assert.ok(postCalls()[0].path.endsWith('/students'));
    assert.deepEqual(postCalls()[0].data,{display_name:'新增真实姓名测试',student_code:'',class_name:'',note:''});
    assert.equal(await page.locator('#saveBinding').isEnabled(),true);assert.equal(bindings.length,0);
    await page.locator('#addStudent').click();currentScope='other-school';await page.locator('#inlineStudentName').fill('不能错校新增');await page.locator('#confirmNewStudent').click();
    await page.waitForFunction(()=>document.getElementById('newStudentError').textContent.includes('不一致'));assert.equal(postCalls().length,1);
    assert.equal(await page.locator('.roi.selected').getAttribute('style'),before);page.once('dialog',d=>d.accept());await page.locator('#cancelNewStudent').click();
    assert.equal(await page.locator('#addStudent').isEnabled(),false);
    """)


def test_browser_inline_unknown_result_blocks_duplicate_creation_not_roi():
    _browser(r"""
    await openIdentity();await drawDraft();writeMode='disconnect';await page.locator('#addStudent').click();await page.locator('#inlineStudentName').fill('网络断开测试');await page.locator('#confirmNewStudent').click();
    await page.waitForFunction(()=>document.getElementById('newStudentError').textContent.includes('网络'));
    assert.equal(postCalls().length,1);assert.equal(await page.locator('#confirmNewStudent').isEnabled(),false);
    page.once('dialog',d=>d.accept());await page.locator('#cancelNewStudent').click();assert.ok(await page.locator('.roi.selected').count());assert.equal(await page.locator('#addStudent').isEnabled(),false);
    """)


def test_browser_overlapping_students_require_explicit_consent_and_exact_boxes_never_bypass():
    _browser(r"""
    bindings=[bindingTemplate];writeMode='overlap';await openIdentity();await chooseCandidate();await page.locator('#studentSelect').selectOption('s2');
    page.once('dialog',d=>d.dismiss());await page.locator('#saveBinding').click();await page.waitForFunction(()=>!document.getElementById('refreshWorkspace').disabled);
    assert.equal(postCalls().length,1);assert.equal(postCalls()[0].data.overlap_confirmed,undefined);assert.equal(bindings.length,1);assert.equal(await page.locator('#saveBinding').isEnabled(),true);
    page.once('dialog',d=>{assert.match(d.message(),/部分遮挡/);d.accept();});await page.locator('#saveBinding').click();await saved(2);
    assert.equal(postCalls().length,3);assert.equal(postCalls()[1].data.overlap_confirmed,undefined);assert.equal(postCalls()[2].data.overlap_confirmed,true);
    assert.equal(bindings[0].student_id,'s1');assert.equal(bindings[1].student_id,'s2');
    writeMode='indistinguishable';await chooseCandidate();await page.locator('#studentSelect').selectOption('s2');let dialogs=0;page.on('dialog',d=>{dialogs++;d.dismiss();});
    await page.locator('#saveBinding').click();await page.waitForFunction(()=>document.getElementById('pageMessage').textContent.includes('几乎相同'));
    assert.equal(dialogs,0);assert.equal(postCalls().length,4);assert.equal(postCalls()[3].data.overlap_confirmed,undefined);assert.equal(bindings.length,2);
    assert.match(await page.locator('#pageMessage').textContent(),/可见部分.*完全遮挡/);assert.equal(await page.locator('#drawButton').isEnabled(),true);
    """)


def test_browser_track_suggestions_need_manual_adoption_and_save():
    _browser(r"""
    bindings=[bindingTemplate];frameList[1].time_sec=2;await openIdentity();await candidatesReady();
    await page.locator('[data-track]').click();await page.locator('#trackView').waitFor({state:'visible'});
    assert.deepEqual(postCalls()[0].data,{task_id:'task-1',binding_id:'b0',frame_revision:'rev-1'});assert.ok(postCalls()[0].path.endsWith('/identity/track'));
    assert.doesNotMatch(await page.locator('#trackDialog').textContent(),/untrusted auto-name/);assert.match(await page.locator('#trackBoundary').textContent(),/不是自动识别/);
    assert.equal(await page.locator('#adoptTrackPoint').isEnabled(),false);await page.locator('#nextTrackPoint').click();await page.waitForFunction(()=>!document.getElementById('adoptTrackPoint').disabled);
    await capture('track-suggestion');assert.match(await page.locator('#trackImage').getAttribute('src'),/identity\/frame\?/);assert.equal(bindings.length,1);
    for(const width of [1440,390,320]){await page.setViewportSize({width,height:1000});await noOverflow();const image=await page.locator('#trackImage').boundingBox(),roi=await page.locator('#trackOverlay .roi').boundingBox();assert.ok(Math.abs(roi.width/image.width-.2)<.01);const adopt=await page.locator('#adoptTrackPoint').boundingBox();assert.ok(adopt.y>=0&&adopt.y+adopt.height<=1000);}
    await page.locator('#adoptTrackPoint').click();await candidatesReady();assert.equal(await page.locator('#frameSelect').inputValue(),'1');
    assert.equal(await page.locator('#studentSelect').inputValue(),'s1');assert.equal(await page.locator('#bboxX').inputValue(),'20');assert.equal(postCalls().length,1);assert.equal(bindings.length,1);
    await page.locator('#saveBinding').click();await saved(2);assert.equal(postCalls()[1].data.student_id,'s1');assert.equal(postCalls()[1].data.frame_key,'s1_f0');
    """)


def test_browser_track_lost_errors_and_abort_never_write_identity():
    _browser(r"""
    bindings=[bindingTemplate];frameList[1].time_sec=2;trackMode='lost';await openIdentity();await candidatesReady();
    await page.locator('[data-track]').click();await page.locator('#trackView').waitFor({state:'visible'});await page.locator('#nextTrackPoint').click();
    assert.equal(await page.locator('#adoptTrackPoint').isEnabled(),false);assert.equal(await page.locator('#trackOverlay .roi').count(),0);assert.match(await page.locator('#trackPointStatus').textContent(),/丢失.*重新框选/);
    await page.locator('#closeTrack').click();trackMode='insufficient';await page.locator('[data-track]').click();await page.waitForFunction(()=>document.getElementById('trackStatus').textContent.includes('暂无'));
    assert.equal(await page.locator('#trackView').isVisible(),false);await page.locator('#closeTrack').click();
    for(const [status,word]of [[429,'繁忙'],[409,'失效'],[410,'到期']]){trackStatus=status;await page.locator('[data-track]').click();await page.waitForFunction(w=>document.getElementById('trackStatus').textContent.includes(w),word);assert.equal(await page.locator('#trackView').isVisible(),false);await page.locator('#closeTrack').click();}
    trackStatus=200;trackMode='completed';trackWait=true;await page.locator('[data-track]').click();while(!pendingTrack)await new Promise(r=>setTimeout(r,10));
    await page.evaluate(()=>changeFrame(1));await candidatesReady();pendingTrack();assert.equal(await page.evaluate(()=>window.trackAborted),1);assert.equal(await page.locator('#trackDialog').isVisible(),false);
    await page.evaluate(()=>new Promise(r=>setTimeout(r,30)));assert.equal(await page.locator('#trackImage').getAttribute('src'),null);assert.equal(await page.locator('.roi.selected').count(),0);
    assert.ok(postCalls().every(c=>c.path.endsWith('/identity/track')));assert.equal(bindings.length,1);
    """)


def test_browser_reference_is_explicit_readonly_and_releases_urls():
    _browser(r"""
    await openIdentity();await chooseCandidate();await selectRole('unknown');assert.equal(previewCalls().length,0);
    const original=await page.locator('#frameImage').getAttribute('src');
    await page.locator('#previewButton').focus();await page.keyboard.press('Enter');await page.locator('#previewImage').waitFor({state:'visible'});
    assert.equal(previewCalls().length,1);assert.equal(previewCalls()[0].method,'GET');
    assert.deepEqual(Object.fromEntries(new URLSearchParams(previewCalls()[0].query)),{task_id:'task-1',frame_key:'s0_f0',frame_revision:'rev-1'});
    assert.ok((await page.locator('#previewImage').getAttribute('src')).startsWith('blob:'));
    assert.equal(await page.locator('#previewImage').evaluate(el=>el.naturalWidth),960);
    assert.equal(await page.locator('#previewDialog .roi, #previewDialog [type=submit], #previewDialog [download]').count(),0);
    assert.match(await page.locator('#previewBoundary').textContent(),/按相近时刻解码，未必与采样帧逐帧一致/);
    assert.match(await page.locator('#previewCaption').textContent(),/00:00.00.*s0_f0/);
    await capture('reference-desktop');await page.setViewportSize({width:320,height:820});await noOverflow();await capture('reference-320');
    const sizes=await page.locator('#previewDialog').evaluate(el=>({w:el.clientWidth,s:el.scrollWidth}));assert.equal(sizes.w,sizes.s);
    await page.keyboard.press('Escape');assert.equal(await page.locator('#previewDialog').isVisible(),false);
    assert.equal(await page.locator('#previewImage').getAttribute('src'),null);assert.equal(await page.locator('#previewCaption').textContent(),'');
    assert.equal(await page.locator('#bboxX').inputValue(),'10');assert.equal(await page.locator('#saveBinding').isEnabled(),true);
    assert.equal(await page.locator('#frameImage').getAttribute('src'),original);assert.equal(await page.locator('#personRole').inputValue(),'unknown');
    assert.equal(await page.locator('#previewButton').evaluate(el=>el===document.activeElement),true);
    await page.locator('#previewButton').click();await page.locator('#previewImage').waitFor({state:'visible'});assert.equal(previewCalls().length,2);
    await page.locator('#closePreview').click();const stats=await page.evaluate(()=>window.previewStats);assert.deepEqual(stats.created,stats.revoked);
    assert.equal(postCalls().length,0);
    """)


def test_browser_reference_cancellation_frame_change_refresh_and_pagehide():
    _browser(r"""
    previewWait=true;await openIdentity();await candidatesReady();await page.locator('#previewButton').click();
    await page.waitForFunction(()=>document.getElementById('previewStatus').textContent.includes('正在读取'));
    while(!pendingPreviews.length)await new Promise(resolve=>setTimeout(resolve,10));
    await page.locator('#closePreview').click();assert.equal(await page.evaluate(()=>window.previewStats.aborted),1);pendingPreviews.shift()();
    await page.locator('#nextFrame').click();await candidatesReady();assert.equal(previewCalls().length,1);
    previewWait=false;await page.locator('#previewButton').click();await page.locator('#previewImage').waitFor({state:'visible'});
    assert.match(await page.locator('#previewCaption').textContent(),/00:10.00.*s1_f0/);
    assert.equal(new URLSearchParams(previewCalls()[1].query).get('frame_key'),'s1_f0');
    await page.evaluate(()=>changeFrame(0));await candidatesReady();assert.equal(await page.locator('#previewDialog').isVisible(),false);
    assert.equal(await page.locator('#previewImage').getAttribute('src'),null);
    await page.locator('#previewButton').click();await page.locator('#previewImage').waitFor({state:'visible'});
    await page.evaluate(()=>loadWorkspace());await candidatesReady();assert.equal(await page.locator('#previewImage').getAttribute('src'),null);
    previewWait=true;await page.locator('#previewButton').click();while(!pendingPreviews.length)await new Promise(resolve=>setTimeout(resolve,10));
    await page.evaluate(()=>changeFrame(1));await candidatesReady();pendingPreviews.shift()();
    assert.equal(await page.locator('#previewDialog').isVisible(),false);assert.equal(await page.locator('#previewCaption').textContent(),'');
    previewWait=false;await page.locator('#previewButton').click();await page.locator('#previewImage').waitFor({state:'visible'});
    await page.evaluate(()=>window.dispatchEvent(new PageTransitionEvent('pagehide')));
    const stats=await page.evaluate(()=>window.previewStats);assert.deepEqual(stats.created,stats.revoked);assert.ok(stats.aborted>=2);
    assert.equal(await page.locator('#previewImage').getAttribute('src'),null);assert.equal(postCalls().length,0);
    """)


def test_browser_reference_errors_are_chinese_without_retries():
    _browser(r"""
    await openIdentity();await candidatesReady();let count=0;
    for(const [status,text]of [[401,'登录已过期'],[403,'无权'],[404,'未找到'],[409,'原片或采样帧版本已变化'],[410,'已到期'],[422,'此时刻'],[429,'繁忙'],[503,'暂不可用']]){
      previewStatus=status;await page.locator('#previewButton').click();await page.waitForFunction(()=>document.getElementById('previewStatus').dataset.error==='true');
      assert.ok((await page.locator('#previewStatus').textContent()).includes(text));assert.equal(await page.locator('#previewImage').isVisible(),false);
      assert.equal(previewCalls().length,++count);assert.equal(await page.locator('#previewImage').getAttribute('src'),null);
      await page.locator('#closePreview').click();
    }
    previewStatus=200;
    for(const [mode,text]of [['invalid','格式不正确'],['empty','为空'],['corrupt','无法显示'],['disconnect','网络连接失败']]){
      previewMode=mode;await page.locator('#previewButton').click();await page.waitForFunction(()=>document.getElementById('previewStatus').dataset.error==='true');
      assert.ok((await page.locator('#previewStatus').textContent()).includes(text));assert.equal(previewCalls().length,++count);await page.locator('#closePreview').click();
    }
    const stats=await page.evaluate(()=>window.previewStats);assert.deepEqual(stats.created,stats.revoked);assert.equal(postCalls().length,0);
    """)


def test_browser_reference_timeout_and_quick_reopen_ignore_old_response():
    _browser(r"""
    await openIdentity();await candidatesReady();previewWait=true;await page.clock.install();
    await page.locator('#previewButton').click();while(!pendingPreviews.length)await new Promise(resolve=>setTimeout(resolve,10));
    await page.clock.fastForward(12001);await page.waitForFunction(()=>document.getElementById('previewStatus').textContent.includes('超时'));
    assert.equal(previewCalls().length,1);assert.equal(await page.evaluate(()=>window.previewStats.aborted),1);
    await page.evaluate(()=>{closeReference(true);openReference();openReference();});
    while(pendingPreviews.length<2)await new Promise(resolve=>setTimeout(resolve,10));
    pendingPreviews.shift()();pendingPreviews.shift()();await page.locator('#previewImage').waitFor({state:'visible'});
    assert.equal(previewCalls().length,2);assert.equal(await page.evaluate(()=>window.previewStats.created.length),1);
    await page.locator('#closePreview').click();const stats=await page.evaluate(()=>window.previewStats);assert.deepEqual(stats.created,stats.revoked);
    assert.equal(postCalls().length,0);
    """)


def test_browser_reference_requires_media_and_does_not_grant_editing():
    _browser(r"""
    needsSchoolConfirmation=true;await openIdentity();await candidatesReady();
    await page.locator('#previewButton').click();await page.locator('#previewImage').waitFor({state:'visible'});await page.locator('#closePreview').click();
    assert.equal(await page.locator('#bindingFields').evaluate(el=>el.disabled),true);assert.equal(await page.locator('#saveBinding').isEnabled(),false);
    for(const available of [false,null,undefined]){
      mediaAvailable=available;await page.locator('#refreshWorkspace').click();await page.waitForFunction(()=>!document.getElementById('refreshWorkspace').disabled);
      assert.equal(await page.locator('#previewButton').isEnabled(),false);await page.evaluate(()=>openReference());
    }
    assert.equal(previewCalls().length,1);assert.equal(postCalls().length,0);
    """)


def test_browser_zoom_keeps_original_coordinates_and_supports_keyboard_touch():
    _browser(r"""
    await openIdentity();await chooseCandidate();const before=calls.length;
    for(const width of [1440,768,390,320]){
      await page.setViewportSize({width,height:1000});await page.locator('#resetZoom').click();await page.locator('#zoomIn').click();await page.locator('#zoomIn').click();
      const image=await page.locator('#frameImage').boundingBox(),overlay=await page.locator('.roi.selected').boundingBox();
      assert.ok(Math.abs((overlay.x-image.x)/image.width-.1)<.005);assert.ok(Math.abs((overlay.y-image.y)/image.height-.2)<.005);
      assert.ok(Math.abs(overlay.width/image.width-.25)<.005);assert.ok(Math.abs(overlay.height/image.height-.3)<.005);
      assert.equal(await page.locator('#bboxX').inputValue(),'10');await noOverflow();
    }
    assert.equal(calls.length,before);await page.locator('#frameViewport').focus();await page.keyboard.press('0');
    assert.equal(await page.locator('#zoomValue').textContent(),'100%');await page.keyboard.press('+');assert.equal(await page.locator('#zoomValue').textContent(),'125%');
    await page.keyboard.press('-');assert.equal(await page.locator('#zoomValue').textContent(),'100%');
    await page.locator('#clearSelection').click();await page.locator('#zoomIn').click();await page.locator('#drawButton').click();
    await page.locator('#frameViewport').evaluate(el=>{el.scrollLeft=0;el.scrollTop=0;});await page.locator('#frameViewport').scrollIntoViewIfNeeded();
    let bounds=await page.locator('#frameSurface').boundingBox();const client=await context.newCDPSession(page);
    await client.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:bounds.x+bounds.width*.2,y:bounds.y+bounds.height*.2}]});
    await client.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:bounds.x+bounds.width*.5,y:bounds.y+bounds.height*.5}]});await client.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
    assert.ok(Math.abs(Number(await page.locator('#bboxWidth').inputValue())-30)<1);assert.ok(Math.abs(Number(await page.locator('#bboxHeight').inputValue())-30)<1);
    await page.locator('#resetZoom').click();assert.ok(Math.abs(Number(await page.locator('#bboxWidth').inputValue())-30)<1);
    await page.locator('#clearSelection').click();await page.locator('#nextFrame').click();await chooseCandidate();await page.locator('#zoomIn').click();
    const image=await page.locator('#frameImage').boundingBox(),roi=await page.locator('.roi.selected').boundingBox();
    assert.ok(Math.abs(image.width/image.height-600/900)<.01);assert.ok(Math.abs(roi.height/image.height-.3)<.01);
    await selectRole('unknown');await page.locator('#saveBinding').click();await saved(1);assert.equal(await page.locator('#frameSelect').inputValue(),'1');
    assert.equal(await page.locator('#zoomValue').textContent(),'100%');assert.equal(postCalls()[0].data.bbox.width,.25);
    """)


def test_browser_history_filters_revision_status_and_returns_without_reloading():
    _browser(r"""
    bindings=[bindingTemplate,{...bindingTemplate,binding_id:'b-old',frame_revision:'old-rev',current_revision:false},
      {...bindingTemplate,binding_id:'b-revoked',status:'revoked'},
      {...bindingTemplate,binding_id:'b-mismatch',frame_revision:'old-rev'},
      {...bindingTemplate,binding_id:'b-next',frame_key:'s1_f0',time_sec:10}];
    await openIdentity();await candidatesReady();const before=calls.length;
    assert.equal(await page.locator('#bindingList article').count(),1);assert.equal(await page.locator('.roi.confirmed').count(),1);
    await page.locator('#showRecords').click();await page.locator('#recordsAll').check();assert.equal(await page.locator('#bindingList article').count(),5);
    assert.match(await page.locator('#bindingList').textContent(),/已撤销/);assert.match(await page.locator('#bindingList').textContent(),/历史版本/);
    await page.locator('#recordsCurrent').check();assert.equal(await page.locator('#bindingList article').count(),1);
    await page.locator('#backToFrame').click();assert.equal(calls.length,before);assert.equal(await page.locator('#frameViewport').evaluate(el=>el===document.activeElement),true);
    await page.locator('#recordsAll').check();await page.locator('[data-frame="1"]').click();await candidatesReady();assert.equal(await page.locator('#frameSelect').inputValue(),'1');
    assert.equal(calls.slice(before).filter(c=>c.path.endsWith('/identity/workspace')||c.path.endsWith('/identity/roster')).length,0);
    await page.locator('#recordsCurrent').check();assert.equal(await page.locator('#bindingList article').count(),1);assert.match(await page.locator('#bindingList').textContent(),/00:10.00/);
    assert.equal(postCalls().length,0);
    """)


def test_browser_layout_roi_proportions_keyboard_and_mobile():
    _browser(r"""
    await openIdentity();await chooseCandidate();await selectRole('unknown');
    for(const width of [1440,768,390,320]){
      await page.setViewportSize({width,height:1000});await noOverflow();
      const image=await page.locator('#frameImage').boundingBox(),overlay=await page.locator('.roi.selected').boundingBox();
      assert.ok(Math.abs(image.width/image.height-1280/720)<.01);
      assert.ok(Math.abs((overlay.x-image.x)/image.width-.1)<.01);assert.ok(Math.abs(overlay.width/image.width-.25)<.01);
      await capture('identity-'+width);
    }
    assert.ok((await page.locator('main').ariaSnapshot()).includes('原始课堂采样帧'));
    await page.locator('#bboxX').fill('90');assert.equal(await page.locator('#saveBinding').isEnabled(),false);
    await page.locator('#bboxX').fill('10');assert.equal(await page.locator('#saveBinding').isEnabled(),true);
    await page.locator('#clearSelection').click();assert.equal(await page.locator('#saveBinding').isEnabled(),false);
    assert.equal(postCalls().length,0);
    await coordinateBox();await selectRole('unknown');await page.locator('#bboxX').fill('90');await page.locator('#bboxWidth').fill('10');await page.locator('#saveBinding').click();await saved(1);
    const edge=postCalls()[0].data.bbox;assert.ok(edge.width<=1-edge.x);assert.ok(edge.width>0);
    """)


def test_browser_confirm_same_student_on_multiple_frames_and_revoke():
    _browser(r"""
    await openIdentity();await chooseCandidate();await selectRole('student');
    assert.equal(await page.locator('#saveBinding').isEnabled(),false);
    assert.ok((await page.locator('#studentSelect').textContent()).includes('B02 · 二班'));
    await page.locator('#studentSelect').selectOption('s1');await page.locator('#saveBinding').click();await saved(1);
    assert.equal(await page.locator('#frameSelect').inputValue(),'0');
    assert.equal(postCalls()[0].data.student_id,'s1');assert.equal(postCalls()[0].data.frame_revision,'rev-1');assert.equal(postCalls()[0].data.bbox.x,.1);
    assert.ok(!(await page.locator('#bindingList').textContent()).includes('不可信的错误姓名'));
    await page.locator('#nextFrame').click();await chooseCandidate();await selectRole('student');await page.locator('#studentSelect').selectOption('s1');await page.locator('#saveBinding').click();await saved(2);
    await page.reload();await saved(2);assert.equal(bindings.length,2);assert.equal(bindings[1].frame_key,'s1_f0');
    await page.locator('[data-revoke]').first().click();await page.locator('#cancelRevoke').click();assert.equal(postCalls().length,2);
    await page.locator('[data-revoke]').first().click();await page.locator('#confirmRevoke').click();assert.equal(postCalls().length,2);
    await page.locator('#revokeReason').fill('教师核对后发现选择错误');await page.locator('#confirmRevoke').click();await saved(1);
    assert.equal(postCalls()[2].data.reason,'教师核对后发现选择错误');await page.locator('#recordsAll').check();assert.ok((await page.locator('#bindingList').textContent()).includes('已撤销'));
    """)


def test_browser_dirty_frame_change_mouse_and_touch_roi():
    _browser(r"""
    await openIdentity();await chooseCandidate();page.once('dialog',d=>d.dismiss());await page.locator('#nextFrame').click();assert.equal(await page.locator('#frameSelect').inputValue(),'0');
    page.once('dialog',d=>d.accept());await page.locator('#nextFrame').click();await candidatesReady();assert.equal(await page.locator('#frameSelect').inputValue(),'1');
    assert.equal(await page.locator('#saveBinding').isEnabled(),false);
    await page.locator('#drawButton').click();await page.locator('#frameViewport').evaluate(el=>el.scrollIntoView({block:'center'}));let bounds=await page.locator('#frameSurface').boundingBox();
    await page.mouse.move(bounds.x+bounds.width*.2,bounds.y+bounds.height*.1);await page.mouse.down();await page.mouse.move(bounds.x+bounds.width*.5,bounds.y+bounds.height*.4);await page.mouse.up();
    assert.ok(Math.abs(Number(await page.locator('#bboxWidth').inputValue())-30)<.3);
    assert.ok(Math.abs(bounds.width/bounds.height-600/900)<.01);
    await page.locator('#clearSelection').click();await page.setViewportSize({width:320,height:900});await page.locator('#drawButton').click();await page.locator('#frameViewport').evaluate(el=>{el.scrollTop=0;el.scrollLeft=0;el.scrollIntoView({block:'center'});});bounds=await page.locator('#frameSurface').boundingBox();
    const client=await context.newCDPSession(page);await client.send('Input.dispatchTouchEvent',{type:'touchStart',touchPoints:[{x:bounds.x+bounds.width*.2,y:bounds.y+bounds.height*.2}]});await client.send('Input.dispatchTouchEvent',{type:'touchMove',touchPoints:[{x:bounds.x+bounds.width*.5,y:bounds.y+bounds.height*.5}]});await client.send('Input.dispatchTouchEvent',{type:'touchEnd',touchPoints:[]});
    assert.ok(Math.abs(Number(await page.locator('#bboxHeight').inputValue())-30)<1,JSON.stringify({bounds,height:await page.locator('#bboxHeight').inputValue()}));
    await noOverflow();await selectRole('teacher');await page.locator('#saveBinding').click();await saved(1);assert.equal(postCalls()[0].data.student_id,null);assert.equal(postCalls()[0].data.role,'teacher');
    """)


@pytest.mark.parametrize("mode", ["empty", "unavailable", "error"])
def test_browser_detection_empty_or_failed_allows_manual_unknown(mode):
    _browser("detectionMode=" + json.dumps(mode) + r""";
    await openIdentity();await imageReady();await page.waitForFunction(()=>!document.getElementById('retryDetection').disabled);
    assert.equal(await page.locator('[data-candidate]').count(),0);await coordinateBox();await selectRole('unknown');await page.locator('#saveBinding').click();await saved(1);
    assert.equal(postCalls()[0].data.role,'unknown');assert.equal(postCalls()[0].data.student_id,null);
    """)


def test_browser_admin_is_read_only_and_does_not_use_untrusted_binding_name():
    _browser(r"""
    bindings=[bindingTemplate];await openIdentity();await imageReady();
    assert.equal(await page.locator('#bindingFields').evaluate(el=>el.disabled),true);assert.equal(await page.locator('#drawButton').isEnabled(),false);assert.equal(await page.locator('[data-revoke]').count(),0);
    assert.equal(await page.locator('[data-track]').count(),0);assert.equal(await page.locator('#addStudent').isEnabled(),false);
    assert.equal(await page.locator('#backLink').getAttribute('href'),'/demo2/admin');assert.equal(await page.locator('#rosterLink').isVisible(),false);
    assert.ok(!(await page.locator('#bindingList').textContent()).includes('不可信的错误姓名'));
    assert.ok(!calls.some(c=>c.path.endsWith('/identity/detect')));assert.equal(postCalls().length,0);
    await page.locator('#previewButton').click();await page.locator('#previewImage').waitFor({state:'visible'});await page.locator('#closePreview').click();
    assert.equal(await page.locator('#bindingFields').evaluate(el=>el.disabled),true);assert.equal(await page.locator('[data-revoke]').count(),0);
    assert.equal(postCalls().length,0);assert.ok(!calls.some(c=>c.path.endsWith('/identity/detect')));
    await page.setViewportSize({width:320,height:900});await noOverflow();await capture('identity-admin-320');
    """, account={"role": "company_admin", "username": "admin-test"})


def test_browser_task_scope_remains_authoritative_without_wrong_roster_creation():
    _browser(r"""
    currentScope='other-school';await openIdentity();await chooseCandidate();
    assert.equal(await page.locator('#bindingFields').evaluate(el=>el.disabled),false);assert.equal(await page.locator('#rosterLink').isVisible(),false);
    assert.ok((await page.locator('#scopeNotice').textContent()).includes('任务学校快照'));
    await page.locator('#clearSelection').click();await page.goto('http://identity.test/demo2/students?returntask=task-1');await page.waitForFunction(()=>!document.getElementById('refreshRoster').disabled);
    assert.equal(await page.locator('#studentFields').evaluate(el=>el.disabled),true);assert.equal(postCalls().length,0);
    """)


def test_browser_empty_roster_create_search_and_return_task():
    _browser(r"""
    students=[];await openIdentity();await candidatesReady();assert.ok((await page.locator('#rosterLink').textContent()).includes('创建本校学生名册'));await page.locator('details').filter({has:page.locator('#rosterLink')}).locator('summary').click();await page.locator('#rosterLink').click();await page.locator('#studentFields').waitFor();await page.waitForFunction(()=>!document.getElementById('studentFields').disabled);
    assert.ok((await page.locator('#rosterList').textContent()).includes('本校名册为空'));
    await page.locator('#displayName').fill('测试学生');await page.locator('#studentCode').fill('C03');await page.locator('#className').fill('三班');await page.locator('#studentNote').fill('<script>不作为HTML执行</script>');await page.locator('#createStudent').click();await page.waitForFunction(()=>document.getElementById('rosterList').textContent.includes('C03'));
    assert.deepEqual(Object.keys(postCalls()[0].data).sort(),['class_name','display_name','note','student_code']);
    await page.locator('#rosterSearch').fill('C03');assert.ok((await page.locator('#rosterList').textContent()).includes('测试学生'));
    await capture('students-desktop');
    await page.setViewportSize({width:320,height:900});await noOverflow();await capture('students-320');await page.locator('#returnTaskLink').click();await candidatesReady();assert.equal(students.length,1);
    """)


@pytest.mark.parametrize("failure", ["stale", "disconnect"])
def test_browser_write_failure_stops_duplicate_binding_until_refresh(failure):
    _browser("writeMode=" + json.dumps(failure) + r""";
    await openIdentity();await chooseCandidate();await selectRole('unknown');await page.locator('#saveBinding').click();await page.waitForFunction(()=>document.getElementById('pageMessage').className.includes('visible'));
    assert.equal(await page.locator('#saveBinding').isEnabled(),false);assert.equal(postCalls().length,1);
    assert.ok(!(await page.locator('#pageMessage').textContent()).includes('Failed to fetch'));
    """)


def test_browser_late_detection_does_not_override_current_frame():
    _browser(r"""
    detectWait=true;await openIdentity();await imageReady();await page.locator('#nextFrame').click();await candidatesReady();releaseOldDetection?.();
    assert.equal(await page.locator('#frameSelect').inputValue(),'1');assert.equal(await page.locator('#frameTime').textContent(),'00:10.00');assert.equal(await page.locator('[data-candidate]').count(),1);
    """)


def test_browser_missing_media_failure_and_missing_task_are_not_empty_success():
    _browser(r"""
    frameList=[];mediaAvailable=false;await openIdentity();assert.equal(await page.locator('#saveBinding').isEnabled(),false);assert.equal(await page.locator('#frameSurface').isVisible(),false);
    workspaceStatus=0;await page.locator('#refreshWorkspace').click();await page.waitForFunction(()=>!document.getElementById('refreshWorkspace').disabled);assert.ok((await page.locator('#pageMessage').textContent()).includes('网络连接失败'));
    const before=calls.length;await page.goto('http://identity.test/demo2/identity');assert.ok((await page.locator('#frameEmpty').textContent()).includes('未选择视频任务'));assert.equal(calls.slice(before).filter(c=>c.path.startsWith('/api/')).length,0);
    """)


def test_browser_video_identity_summary_uses_only_task_roster():
    _browser(r"""
    bindings=[bindingTemplate];await page.goto('http://identity.test/demo2/video?id=task-1');await page.waitForFunction(()=>document.getElementById('identitySummary').textContent.includes('1 个已确认帧'));
    assert.ok((await page.locator('#identitySummary').textContent()).includes('A01'));assert.ok(!(await page.locator('#identitySummary').textContent()).includes('不可信的错误姓名'));
    assert.equal(await page.locator('#identityLink').getAttribute('href'),'/demo2/identity?task_id=task-1');await page.setViewportSize({width:320,height:900});await noOverflow();
    """)


@pytest.mark.parametrize("unavailable", ["expired", "missing_url"])
def test_browser_expired_media_and_old_revision_allow_reasoned_revocation(unavailable):
    setup = "mediaAvailable=false;" if unavailable == "expired" else "frameList=frameList.map(f=>({...f,image_url:''}));"
    _browser(setup + r"""
    bindings=[{...bindingTemplate,current_revision:false,frame_revision:'old-revision'}];canEdit=false;
    await openIdentity();assert.equal(await page.locator('#saveBinding').isEnabled(),false);
    assert.equal(await page.locator('#detectionStatus').textContent(),'原片或采样图已不可用，无法检测；可复核保留记录。');
    assert.equal(await page.locator('#retryDetection').isEnabled(),false);
    assert.equal(await page.locator('.work-layout + .frame-records').count(),1);
    await page.setViewportSize({width:320,height:900});await noOverflow();
    const form=await page.locator('#bindingForm').boundingBox(),records=await page.locator('.frame-records').boundingBox();assert.ok(records.y>form.y+form.height);
    await page.locator('#recordsAll').check();assert.equal(await page.locator('[data-revoke]').count(),1);await page.locator('[data-revoke]').click();await page.locator('#revokeReason').fill('旧版本教师身份标错，撤销原记录');await page.locator('#confirmRevoke').click();
    await page.waitForFunction(()=>document.getElementById('bindingList').textContent.includes('已撤销'));
    assert.equal(postCalls().length,1);assert.ok(postCalls()[0].path.endsWith('/bindings/revoke'));
    """)


def test_detection_reason_codes_are_localized_without_absence_claims():
    _browser(r"""
    detectionMode='unavailable';await openIdentity();await imageReady();
    const labels=await page.evaluate(()=>['model_missing; no_network_download','detector_busy','detector_timeout','new_unknown_code'].map(detectionReason));
    assert.ok(labels[0].includes('模型未就绪'));assert.ok(labels[1].includes('繁忙'));assert.ok(labels[2].includes('超时'));assert.ok(labels[3].includes('暂不可用'));
    assert.ok(labels.every(text=>!/[a-z_]/.test(text)));
    detectionMode='empty';await page.locator('#retryDetection').click();await page.waitForFunction(()=>document.getElementById('detectionStatus').textContent.includes('不代表学生缺席'));
    """)


def test_browser_school_confirmation_requires_explicit_confirmation_and_workspace_reread():
    _browser(r"""
    needsSchoolConfirmation=true;await openIdentity();await chooseCandidate();
    assert.equal(await page.locator('#schoolConfirmation').isVisible(),true);
    assert.equal(await page.locator('#confirmationCity').textContent(),'测试城市');assert.equal(await page.locator('#confirmationDistrict').textContent(),'测试区县');assert.equal(await page.locator('#confirmationSchoolName').textContent(),'当前测试学校');
    assert.equal(await page.locator('#bindingFields').evaluate(el=>el.disabled),true);assert.equal(await page.locator('#saveBinding').isEnabled(),false);
    assert.ok((await page.locator('#detectionStatus').textContent()).includes('位置预览'));assert.ok((await page.locator('#selectionStatus').textContent()).includes('仅预览'));
    assert.equal(postCalls().length,0);assert.ok(calls.some(c=>c.path.endsWith('/identity/detect')));
    page.once('dialog',dialog=>dialog.dismiss());await page.locator('#confirmTaskSchool').click();assert.equal(postCalls().length,0);
    await page.setViewportSize({width:320,height:900});await noOverflow();await capture('school-confirmation-320');
    page.once('dialog',dialog=>{assert.ok(dialog.message().includes('测试城市'));assert.ok(dialog.message().includes('当前测试学校'));dialog.accept();});
    await page.locator('#confirmTaskSchool').click();await page.locator('#schoolConfirmation').waitFor({state:'hidden'});await candidatesReady();
    assert.deepEqual(postCalls()[0].data,{task_id:'task-1',expected_scope_key:'scope-a',confirmed:true});
    const posted=calls.findIndex(c=>c.path.endsWith('/identity/task-school'));assert.ok(calls.slice(posted+1).some(c=>c.path.endsWith('/identity/workspace')));
    assert.ok((await page.locator('#taskSchool').textContent()).includes('当前测试学校'));assert.equal(await page.locator('#bindingFields').evaluate(el=>el.disabled),false);
    await chooseCandidate();await selectRole('student');await page.locator('#studentSelect').selectOption('s1');await page.locator('#saveBinding').click();await saved(1);
    assert.equal(postCalls()[1].data.student_id,'s1');
    """)


@pytest.mark.parametrize("failure", ["stale", "disconnect"])
def test_browser_school_confirmation_failure_preserves_readonly_state(failure):
    _browser("writeMode=" + json.dumps(failure) + r""";needsSchoolConfirmation=true;
    await openIdentity();await candidatesReady();page.once('dialog',dialog=>dialog.accept());await page.locator('#confirmTaskSchool').click();
    await page.waitForFunction(()=>document.getElementById('schoolConfirmationStatus').textContent.includes('仍保持只读'));
    assert.equal(needsSchoolConfirmation,true);assert.equal(await page.locator('#confirmTaskSchool').isEnabled(),false);assert.equal(await page.locator('#saveBinding').isEnabled(),false);
    assert.ok(!(await page.locator('#taskSchool').textContent()).includes('当前测试学校'));assert.equal(postCalls().length,1);
    assert.ok(!postCalls().some(c=>c.path.endsWith('/identity/bindings')));
    """)


def test_browser_school_confirmation_incomplete_context_and_existing_snapshots():
    _browser(r"""
    needsSchoolConfirmation=true;canConfirmSchool=false;currentSchoolContext={city:'测试城市',district:'',school_name:''};await openIdentity();await candidatesReady();
    assert.equal(await page.locator('#confirmTaskSchool').isEnabled(),false);assert.equal(await page.locator('#completeSchoolLink').getAttribute('href'),'/demo2/school?returntask=task-1');
    assert.ok((await page.locator('#schoolConfirmationStatus').textContent()).includes('信息不完整'));assert.equal(postCalls().length,0);
    needsSchoolConfirmation=false;await page.locator('#refreshWorkspace').click();await page.locator('#schoolConfirmation').waitFor({state:'hidden'});assert.equal(postCalls().length,0);
    """)


def test_browser_school_confirmation_admin_never_gets_confirmation_controls():
    _browser(r"""
    needsSchoolConfirmation=true;await openIdentity();await imageReady();
    assert.equal(await page.locator('#confirmTaskSchool').isVisible(),false);assert.equal(await page.locator('#completeSchoolLink').isVisible(),false);
    assert.equal(await page.locator('#bindingFields').evaluate(el=>el.disabled),true);assert.equal(await page.locator('#retryDetection').isEnabled(),false);
    assert.ok(!calls.some(c=>c.path.endsWith('/identity/roster')||c.path.endsWith('/identity/detect')));assert.equal(postCalls().length,0);
    """, account={"role":"company_admin","username":"admin-test"})


def test_school_returntask_is_only_a_valid_task_id():
    html = render_school(TEACHER)
    assert "/^[A-Za-z0-9_-]{1,128}$/" in html
    assert "'/demo2/identity?task_id='+encodeURIComponent(returnTask)" in html
    assert "location.assign(schoolNextUrl)" in html
    assert "/identity/task-school" not in html
    assert "不会自动补齐任务的学校记录" in html


@pytest.mark.parametrize("missing_school", ["empty_fields", "empty_context", "missing_roster"])
def test_browser_school_confirmation_school_page_returns_without_confirming_video(missing_school):
    setup = {
        "empty_fields": "currentSchoolContext={city:'',district:'',school_name:''};",
        "empty_context": "currentSchoolContext={};",
        "missing_roster": "currentSchoolContext={};rosterMissing=true;",
    }[missing_school]
    _browser(setup + r"""
    needsSchoolConfirmation=true;canConfirmSchool=false;currentScope='';await openIdentity();await candidatesReady();
    assert.equal(await page.locator('#completeSchoolLink').isVisible(),true);assert.equal(await page.locator('#completeSchoolLink').getAttribute('href'),'/demo2/school?returntask=task-1');
    assert.equal(await page.locator('#confirmTaskSchool').isEnabled(),false);assert.equal(await page.locator('#bindingFields').evaluate(el=>el.disabled),true);assert.equal(await page.locator('#saveBinding').isEnabled(),false);
    assert.match(await page.locator('#schoolConfirmationStatus').textContent(),/信息不完整/);assert.doesNotMatch(await page.locator('#schoolConfirmationStatus').textContent(),/当前任务不允许/);assert.equal(postCalls().length,0);
    await page.setViewportSize({width:320,height:820});await noOverflow();await page.locator('#completeSchoolLink').click();await page.waitForURL('**/demo2/school?returntask=task-1');
    await page.waitForFunction(()=>!document.getElementById('schoolButton').disabled);await page.locator('#city').fill('测试城市');await page.locator('#district').fill('测试区县');await page.locator('#schoolName').fill('完整测试学校');
    assert.ok((await page.locator('#schoolButton').textContent()).includes('返回视频身份确认'));await page.locator('#schoolButton').click();await page.waitForURL('**/demo2/identity?task_id=task-1');await candidatesReady();
    assert.equal(needsSchoolConfirmation,true);assert.equal(await page.locator('#confirmTaskSchool').isEnabled(),true);assert.equal(await page.locator('#saveBinding').isEnabled(),false);
    assert.ok((await page.locator('#confirmationSchoolName').textContent()).includes('完整测试学校'));assert.equal(postCalls().length,1);assert.ok(postCalls()[0].path.endsWith('/school/context'));
    for(const value of ['', '//external.test','../task-1','a'.repeat(129),'task-1&next=external']){
      await page.goto('http://identity.test/demo2/school?returntask='+encodeURIComponent(value));await page.waitForFunction(()=>!document.getElementById('schoolButton').disabled);
      assert.equal(await page.locator('#schoolButton').textContent(),'进入课程工作台');await page.locator('#schoolButton').click();await page.waitForURL('http://identity.test/demo2/upload');
    }
    assert.ok(!postCalls().some(c=>c.path.endsWith('/identity/task-school')));
    """)
