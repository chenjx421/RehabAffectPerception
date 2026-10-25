"""Workspace refresh contracts; all browser requests use isolated UI fixtures."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from rehab_affect.demo2_entry import render_login, render_membership, render_register, render_school
from rehab_affect.demo2_portal import render_demo2_upload_html
from rehab_affect.demo2_video_review import render_video_review
from test_demo2_portal_html import _run_page_js


UPLOAD_SETUP = """
location.search='';
replies.push({context:{}},{account:{username:'teacher',bound_channel_id:'channel_1'}});
"""
VIDEO_SETUP = """
Element.prototype.checked=false;
replies.push({task:{...baseTask,analysis_status:'evidence_ready'},result:evidence});
"""
VIDEO_READY = """
video.readyState=1;video.duration=750;await video.fire('loadedmetadata');
audio.readyState=1;audio.duration=750;await audio.fire('loadedmetadata');
"""


def test_refreshed_pages_parse_and_keep_local_resources_and_navigation():
    pages = [render_demo2_upload_html(), render_video_review(), render_school(),
             render_login(), render_register(), render_membership()]
    for html in pages:
        assert "--blue:#2163C4" in html
        assert '"Segoe UI","Microsoft YaHei",sans-serif' in html
        assert "letter-spacing:0" in html
        assert not re.search(r'<(?:script|link|img)[^>]+(?:src|href)=["\']https?://', html)
    for html in pages[:3]:
        nav = re.search(r'<nav class="workspace-nav".*?</nav>', html, re.S).group()
        assert re.findall(r'>([^<>]+)</a>', nav) == ["上传任务", "学生名册", "学校信息", "会员中心"]
        assert nav.count("aria-current=page") == 1
    assert '<h1>提交课堂视频</h1>' in pages[0]
    assert ".page-heading h1 { font-size:22px; }" in pages[0]
    assert 'id="analysisLink" href="/demo2/analysis"' in pages[0]
    assert 'href="/seewo_student_demo2"' not in pages[0]
    assert "security_confirmed:true" in pages[0]
    assert "不会自动补齐任务的学校记录" in pages[2]
    assert "管理员登录" in pages[3] and "手机号注册" in pages[3]
    assert "注册不会扣费，也不会自动开通会员" in pages[4]
    assert "注册或会员开通不会自动授予其他学校" in pages[5]
    for name in ("clipOnly", "loopClip"):
        control = re.search(r'<input id="' + name + r'"[^>]+>', pages[1]).group()
        assert "checked" not in control and "disabled" in control
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js required")
    scripts = [script for html in pages for script in re.findall(r"<script>(.*?)</script>", html, re.S)]
    result = subprocess.run(
        [node, "-e", "JSON.parse(require('fs').readFileSync(0,'utf8')).forEach(s=>new Function(s))"],
        input=json.dumps(scripts), capture_output=True, text=True, encoding="utf-8", timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_task_search_filters_only_loaded_tasks_and_clear_restores_all():
    _run_page_js(render_demo2_upload_html(), UPLOAD_SETUP, r"""
    byId('courseId').value='course-1';
    const rows=[
      {...baseTask,original_filename:'Math.MP4'},
      {...baseTask,task_id:'ready-id',original_filename:'数学课堂.mp4',analysis_status:'evidence_ready'},
      {...baseTask,task_id:'error-id',original_filename:'<img onerror=alert(1)>.mp4',analysis_status:'failed'}
    ];
    replies.push({workspace:{course_id:'course-1',tasks:rows,remaining_slots:2,used_slots:3}});
    await loadWorkspace();
    const calls=requests.length,original=JSON.stringify(workspace.tasks);
    byId('taskSearch').value='  MATH.mp4  ';await byId('taskSearch').fire('input');
    assert.equal((byId('taskList').innerHTML.match(/class="task-row"/g)||[]).length,1);
    assert.match(byId('taskResultCount').textContent,/1 \/ 已加载 3/);
    byId('taskStatusFilter').value='ready';await byId('taskStatusFilter').fire('change');
    assert.match(byId('taskList').innerHTML,/没有匹配/);
    byId('taskSearch').value='数学';await byId('taskSearch').fire('input');
    assert.match(byId('taskList').innerHTML,/确认画面中的学生/);
    assert.match(byId('taskList').innerHTML,/查看视频证据/);
    byId('taskStatusFilter').value='';byId('taskSearch').value='error-id';renderTasks();
    assert.match(byId('taskList').innerHTML,/&lt;img/);
    assert.ok(!byId('taskList').innerHTML.includes('<img'));
    await byId('clearTaskFilters').fire('click');
    assert.equal(byId('taskSearch').value,'');assert.equal(byId('taskStatusFilter').value,'');
    assert.equal(byId('clearTaskFilters').disabled,true);
    assert.equal((byId('taskList').innerHTML.match(/class="task-row"/g)||[]).length,3);
    assert.equal(document.activeElement,byId('taskSearch'));
    assert.equal(requests.length,calls);assert.equal(JSON.stringify(workspace.tasks),original);
    """)


@pytest.mark.parametrize("status,key", [
    ("queued", "queued"), ("processing", "processing"), ("evidence_ready", "ready"),
    ("failed", "failed"), ("precheck_complete", "legacy"),
    ("uploaded_pending_worker", "legacy"), ("expired", "expired"), ("deleted", "expired"),
    ("cancelled", "cancelled"),
])
def test_status_filter_uses_real_statuses(status, key):
    _run_page_js(render_demo2_upload_html(), UPLOAD_SETUP,
                 f"assert.equal(taskFilterKey({{...baseTask,analysis_status:{json.dumps(status)}}}),{json.dumps(key)});")


def test_upload_statuses_and_deleted_media_override_ready_filter():
    _run_page_js(render_demo2_upload_html(), UPLOAD_SETUP, """
    assert.equal(taskFilterKey({upload_status:'uploading'}),'uploading');
    assert.equal(taskFilterKey({upload_status:'completed'}),'uploaded');
    assert.equal(taskFilterKey({upload_status:'failed'}),'failed');
    assert.equal(taskFilterKey({upload_status:'cancelled',analysis_status:'evidence_ready'}),'cancelled');
    assert.equal(taskFilterKey({raw_media_deleted_at:'date',analysis_status:'evidence_ready'}),'expired');
    assert.equal(taskFilterKey({}),'unknown');
    assert.equal(taskStatus({})[0],'状态待确认');
    """)


@pytest.mark.parametrize("failure", [
    "new TypeError('offline')", "{status:403,body:{}}", "{workspace:{course_id:'course-1'}}",
])
def test_task_refresh_error_keeps_last_real_rows_filters_and_scope(failure):
    _run_page_js(render_demo2_upload_html(), UPLOAD_SETUP, r"""
    byId('courseId').value='course-1';
    const initial={course_id:'course-1',tasks:[baseTask],remaining_slots:4,used_slots:1};
    replies.push({workspace:initial});await loadWorkspace();
    byId('taskSearch').value='video-1';renderTasks();
    const html=byId('taskList').innerHTML;
    """ + f"replies.push({failure});await loadWorkspace({{silent:true}});" + r"""
    assert.equal(byId('taskList').innerHTML,html);
    assert.match(byId('taskResultCount').textContent,/上次成功读取/);
    assert.match(byId('taskPollStatus').textContent,/当前状态未确认/);
    assert.equal(byId('taskSearch').value,'video-1');
    const errorText=byId('taskPollStatus').textContent;
    scheduleTaskPoll();assert.equal(byId('taskPollStatus').textContent,errorText);
    byId('courseId').value='different-course';await byId('courseId').fire('input');
    assert.match(byId('taskResultCount').textContent,/course-1/);
    assert.equal(byId('uploadButton').disabled,true);
    byId('courseId').value='course-1';
    replies.push({workspace:{...initial,tasks:[]}});await loadWorkspace();
    assert.equal(taskRefreshError,'');assert.match(byId('taskList').innerHTML,/还没有上传任务/);
    """)


def test_first_task_failure_is_not_empty_success_and_recovers():
    _run_page_js(render_demo2_upload_html(), UPLOAD_SETUP, r"""
    byId('courseId').value='course-1';replies.push(new TypeError('offline'));await loadWorkspace();
    assert.equal(workspace,null);assert.match(byId('taskList').innerHTML,/读取失败/);
    assert.ok(!byId('taskList').innerHTML.includes('还没有上传任务'));
    replies.push({workspace:{course_id:'course-1',tasks:[],remaining_slots:5}});
    await loadWorkspace();assert.match(byId('taskList').innerHTML,/还没有上传任务/);
    """)


def test_clip_default_off_then_stops_at_actual_selected_end_and_follows_new_slice():
    _run_page_js(render_video_review(), VIDEO_SETUP, VIDEO_READY + r"""
    assert.equal($('clipOnly').checked,false);assert.equal($('loopClip').checked,false);
    assert.equal($('clipOnly').disabled,false);
    selectSegment(2);$('clipOnly').checked=true;await $('clipOnly').fire('change');
    video.currentTime=90.6;video.paused=false;await video.fire('timeupdate');
    assert.equal(video.paused,true);assert.equal(video.currentTime,90);assert.equal(selected,2);
    assert.match($('clipRange').textContent,/01:00 - 01:30/);
    selectSegment(4);assert.equal(video.currentTime,120);
    assert.match($('clipRange').textContent,/02:00 - 02:30/);
    video.currentTime=151;video.paused=false;await video.fire('timeupdate');
    assert.equal(video.currentTime,150);assert.equal(video.paused,true);assert.equal(selected,4);
    $('clipOnly').checked=false;await $('clipOnly').fire('change');
    video.currentTime=181;await video.fire('timeupdate');assert.equal(selected,6);
    """)


def test_loop_rewinds_without_repeated_play_and_respects_manual_pause():
    _run_page_js(render_video_review(), VIDEO_SETUP, VIDEO_READY + r"""
    let plays=0;video.play=()=>{plays++;return Promise.resolve();};
    selectSegment(1);$('loopClip').checked=true;await $('loopClip').fire('change');
    video.currentTime=60.1;video.paused=false;await video.fire('timeupdate');
    assert.equal(video.currentTime,30);assert.equal(selected,1);assert.equal(plays,0);
    video.currentTime=60;video.paused=true;await video.fire('timeupdate');
    await video.fire('timeupdate');assert.equal(plays,0);assert.equal(video.paused,true);
    assert.equal(video.currentTime,60);
    audio.currentTime=62;audio.paused=false;await audio.fire('timeupdate');
    assert.equal(audio.currentTime,30);assert.equal(selected,1);
    """)


@pytest.mark.parametrize("sync_throw", [False, True])
def test_ended_loop_play_failure_stops_without_unhandled_retries(sync_throw):
    reject = "throw new Error('denied');" if sync_throw else "return Promise.reject(new Error('denied'));"
    _run_page_js(render_video_review(), VIDEO_SETUP, VIDEO_READY + r"""
    let plays=0;video.play=()=>{plays++;
    """ + reject + r"""};
    selectSegment(24);$('loopClip').checked=true;await $('loopClip').fire('change');
    video.currentTime=750;video.ended=true;video.paused=true;
    await video.fire('timeupdate');assert.equal(plays,0);
    await video.fire('ended');await flush();
    assert.equal(plays,1);assert.equal($('loopClip').checked,false);assert.equal(video.paused,true);
    assert.match($('pageMessage').textContent,/循环播放未能继续/);
    for(let i=0;i<5;i++){await video.fire('timeupdate');await video.fire('ended');}
    assert.equal(plays,1);
    """)


def test_pending_loop_does_not_resume_after_navigation_or_change():
    _run_page_js(render_video_review(), VIDEO_SETUP, VIDEO_READY + r"""
    let plays=0,finish;video.play=()=>{plays++;return new Promise(resolve=>finish=resolve);};
    selectSegment(24);$('loopClip').checked=true;await $('loopClip').fire('change');
    video.currentTime=750;video.ended=true;await video.fire('ended');await video.fire('ended');
    assert.equal(plays,1);
    listeners.get('pagehide')();video.paused=false;finish();await flush();
    assert.equal(video.paused,true);
    await video.fire('ended');assert.equal(plays,1);
    """)


def test_clip_invalid_duration_and_access_loss_disable_controls():
    _run_page_js(render_video_review(), VIDEO_SETUP, VIDEO_READY + r"""
    selectSegment(3);video.duration=60;audio.duration=60;syncClipControls();
    assert.equal(clipBounds(video),null);assert.equal($('clipOnly').disabled,true);
    video.duration=100;audio.duration=100;syncClipControls();
    assert.deepEqual(clipBounds(video),{start:90,end:100});
    $('clipOnly').checked=true;$('loopClip').checked=true;
    replies.push({status:403,body:{}});await refresh();
    assert.equal($('clipOnly').checked,false);assert.equal($('loopClip').checked,false);
    assert.equal($('clipOnly').disabled,true);assert.equal($('loopClip').disabled,true);
    assert.equal(video.src,'');assert.equal(audio.src,'');assert.equal(timers.size,0);
    """)


def test_video_transient_error_keeps_processing_state_separate_from_request_state():
    _run_page_js(render_video_review(), VIDEO_SETUP, r"""
    const label=$('stageLabel').textContent,detail=$('stageDetail').textContent;
    replies.push(new TypeError('offline'));await refresh();
    assert.equal($('stageLabel').textContent,label);assert.equal($('stageDetail').textContent,detail);
    assert.match($('pageMessage').textContent,/上次成功读取/);
    assert.equal(segments.length,25);assert.equal($('downloadResult').hidden,false);
    """)


_BROWSER = r"""
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try{
    const context=await browser.newContext();
    const page=await context.newPage(),errors=[],requests=[];
    page.setDefaultTimeout(10000);
    page.on('pageerror',error=>errors.push(error.message));
    let failWorkspace=false;
    const tasks=[
      {task_id:'fixture-queued',course_id:'fixture-course',original_filename:'Math fixture.mp4',upload_status:'completed',analysis_status:'queued'},
      {task_id:'fixture-ready',course_id:'fixture-course',original_filename:'UI fixture evidence.mp4',upload_status:'completed',analysis_status:'evidence_ready'},
    ];
    await context.route('**/*',async route=>{
      const url=new URL(route.request().url());requests.push(url.href);
      assert.equal(url.hostname,'workspace.test');
      if(input.pages[url.pathname])return route.fulfill({contentType:'text/html',body:input.pages[url.pathname]});
      let data={};
      if(url.pathname.endsWith('/auth/me'))data={account:{role:'school_uploader',username:'UI fixture',bound_channel_id:'channel_1'}};
      else if(url.pathname.endsWith('/school/context'))data={context:{city:'UI fixture',district:'Test district',school_name:'Test school (no real data)'},options:[]};
      else if(url.pathname.endsWith('/upload/workspace')){
        if(failWorkspace)return route.fulfill({status:503,json:{error:{message:'Fixture connection failure'}}});
        data={workspace:{course_id:'fixture-course',remaining_slots:3,used_slots:2,max_slots:5,tasks}};
      }else if(url.pathname.endsWith('/upload/task')){
        data={task:{...tasks[1],course_name:'UI fixture video (no real classroom)',media_url:'/fixture.wav'},result:{media:{duration_sec:2,width:0,height:0,has_audio:false},segments:[{start_sec:0,end_sec:0.5},{start_sec:0.5,end_sec:1.0},{start_sec:1,end_sec:2}]}};
      }else if(url.pathname==='/fixture.wav'){
        const samples=16000,buffer=Buffer.alloc(44+samples*2);
        buffer.write('RIFF');buffer.writeUInt32LE(buffer.length-8,4);buffer.write('WAVEfmt ',8);
        buffer.writeUInt32LE(16,16);buffer.writeUInt16LE(1,20);buffer.writeUInt16LE(1,22);
        buffer.writeUInt32LE(8000,24);buffer.writeUInt32LE(16000,28);buffer.writeUInt16LE(2,32);buffer.writeUInt16LE(16,34);
        buffer.write('data',36);buffer.writeUInt32LE(samples*2,40);
        const range=/bytes=(\d+)-(\d*)/.exec(route.request().headers().range||'');
        if(range){
          const start=Number(range[1]),end=range[2]?Math.min(Number(range[2]),buffer.length-1):buffer.length-1;
          return route.fulfill({status:206,contentType:'audio/wav',headers:{'Accept-Ranges':'bytes','Content-Range':'bytes '+start+'-'+end+'/'+buffer.length},body:buffer.subarray(start,end+1)});
        }
        return route.fulfill({contentType:'audio/wav',headers:{'Accept-Ranges':'bytes'},body:buffer});
      }else if(url.pathname.endsWith('/identity/workspace')){
        data={workspace:{task_id:'fixture-ready',bindings:[],students:[],school_context:{school_name:'Test school'}}};
      }else if(url.pathname.endsWith('/membership/config')){
        data={config:{sms_available:false,agreement_version:'2026-09-09'}};
      }else if(url.pathname.endsWith('/membership')){
        data={membership:{status:'inactive',plans:[],orders:[],school_access:false,payment_available:false}};
      }else throw new Error('Unexpected fixture route '+url.pathname);
      return route.fulfill({json:data});
    });
    const waitForUpload=async()=>{
      await page.goto('http://workspace.test/demo2/upload?course_id=fixture-course');
      await page.waitForFunction(()=>document.getElementById('taskResultCount').textContent.includes('已加载 2'));
    };
    for(const width of [1440,768,390,320]){
      await page.setViewportSize({width,height:900});
      for(const name of ['upload','login','school','video','register','membership']){
        if(name==='upload')await waitForUpload();
        else await page.goto('http://workspace.test/demo2/'+name+(name==='video'?'?id=fixture-ready':''));
        if(name==='video')await page.waitForFunction(()=>document.getElementById('segmentCount').textContent==='3 个片段');
        assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),name+' overflow '+width);
        const clipped=await page.locator('button:visible,h1:visible,.workspace-nav a:visible').evaluateAll(nodes=>nodes.filter(n=>n.scrollWidth>n.clientWidth+1).map(n=>n.textContent));
        assert.deepEqual(clipped,[],name+' clipped controls '+width);
        if(width===1440||width===390)await page.screenshot({path:path.join(input.output,name+'-'+width+'.png'),fullPage:true});
      }
    }
    await waitForUpload();
    const calls=requests.length;
    await page.locator('#taskSearch').fill('not found');
    await page.getByText('没有匹配的任务。请更换关键词或清除筛选。',{exact:true}).waitFor();
    await page.locator('#clearTaskFilters').click();
    await page.locator('#taskStatusFilter').selectOption('ready');
    assert.equal(await page.locator('.task-row').count(),1);
    assert.equal(requests.length,calls);
    failWorkspace=true;await page.locator('#refreshTasksButton').click();
    await page.waitForFunction(()=>document.getElementById('taskPollStatus').textContent.includes('当前状态未确认'));
    assert.equal(await page.locator('.task-row').count(),1);
    await page.goto('http://workspace.test/demo2/video?id=fixture-ready');
    await page.waitForFunction(()=>!document.getElementById('clipOnly').disabled);
    await page.locator('#clipOnly').check();
    await page.evaluate(()=>{const v=document.getElementById('classVideo');window.mediaTrace=[];for(const name of ['play','pause','timeupdate','seeking','seeked','ended'])v.addEventListener(name,()=>window.mediaTrace.push([name,v.currentTime,v.paused]));v.muted=true;return v.play();});
    try{
      await page.waitForFunction(()=>{const v=document.getElementById('classVideo');return v.paused&&v.currentTime>=0.49;},null,{timeout:5000});
    }catch(error){
      console.log(await page.evaluate(()=>{const v=document.getElementById('classVideo');return {time:v.currentTime,paused:v.paused,ended:v.ended,ready:v.readyState,error:v.error?.message,checked:document.getElementById('clipOnly').checked,selected:document.querySelector('.segment[aria-pressed=true]')?.dataset.index,trace:window.mediaTrace,seekable:v.seekable.length};}));
      throw error;
    }
    assert.equal(await page.locator('.segment[aria-pressed=true]').getAttribute('data-index'),'0');
    await page.locator('.segment[data-index="1"]').click();
    await page.locator('#loopClip').check();
    await page.evaluate(()=>{const v=document.getElementById('classVideo');v.currentTime=0.9;return v.play();});
    await page.waitForFunction(()=>{const v=document.getElementById('classVideo');return !v.paused&&v.currentTime>=0.5&&v.currentTime<0.8;});
    await page.evaluate(()=>document.getElementById('classVideo').pause());
    assert.equal(await page.locator('.segment[aria-pressed=true]').getAttribute('data-index'),'1');
    await page.waitForTimeout(350);
    assert.equal(await page.locator('#classVideo').evaluate(v=>v.paused),true);
    assert.deepEqual(errors,[]);
    console.log('Isolated browser checks and screenshots: '+input.output);
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
"""


def test_isolated_browser_responsive_search_and_native_clip_playback(tmp_path: Path):
    if not shutil.which("node"):
        pytest.skip("Node.js required")
    teacher = {"role": "school_uploader", "username": "UI fixture"}
    pages = {
        "/demo2/upload": render_demo2_upload_html(teacher),
        "/demo2/video": render_video_review(teacher),
        "/demo2/school": render_school(teacher),
        "/demo2/login": render_login(),
        "/demo2/register": render_register(),
        "/demo2/membership": render_membership({"role": "registered_member"}),
    }
    env = os.environ.copy()
    bundled = Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'
    if not env.get('NODE_PATH') and (bundled / 'playwright').is_dir():
        env['NODE_PATH'] = str(bundled)
    result = subprocess.run(
        [shutil.which("node"), "-e", _BROWSER],
        input=json.dumps({"pages": pages, "output": str(tmp_path)}),
        capture_output=True, text=True, encoding="utf-8", timeout=90, env=env,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout)
