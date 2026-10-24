"""Isolated channel-admin UI tests. No live services or real channel writes."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from rehab_affect.demo2_channel_admin import render_channel_admin, render_channels, render_demo2_channel_admin_html
from rehab_affect.demo2_portal import render_demo2_admin_html
from test_demo2_portal_html import _run_page_js


ADMIN = {"role": "company_admin", "username": "UI-test-admin"}
SETUP = r"""
const fixture={channel_id:'private-channel',channel_name:'Test channel',owner_label:'Test owner',status:'active',course_upload_limit:5,version:8,account_id:'private-account',username:'private-user'};
const submit={preventDefault(){}};
replies.push({ok:true,channels:[fixture]});
"""
EDIT = """
openSettings(0);$('channelName').value='Changed channel';await $('channelForm').fire('input');
"""


def test_exports_entry_and_inline_script_parse_without_external_resources():
    html = render_channel_admin(ADMIN)
    assert render_demo2_channel_admin_html(ADMIN) == html
    assert render_channels(ADMIN) == html
    assert 'id="manageChannelsLink" href="/demo2/admin/channels"' in render_demo2_admin_html(ADMIN)
    assert 'href="/demo2/admin"' in html
    assert 'name="viewport"' in html and "letter-spacing:0" in html
    assert "--blue:#2163C4" in html and "历史视频和已开始任务不受影响" in html
    assert 'id="courseUploadLimit"' in html
    assert "expected_version:baseline.version" in html
    body = html.split("<script>")[0]
    assert "expected_version" not in body and "channel_id" not in body
    assert not re.search(r'(?:src|href)=["\']https?://', html)
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js required")
    script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    result = subprocess.run([node, "--check"], input=script, text=True, encoding="utf-8",
                            capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_cancel_and_same_channel_click_never_post_or_lose_draft():
    _run_page_js(render_channel_admin(ADMIN), SETUP, EDIT + """
    assert.equal($('saveChannel').disabled,false);assert.equal($('formStatus').textContent,'待保存');
    openSettings(0);assert.equal($('channelName').value,'Changed channel');
    await $('cancelEdit').fire('click');assert.equal($('settingsPanel').hidden,true);
    assert.ok(!requests.some(r=>r.options.method==='POST'));
    openSettings(0);assert.equal($('channelName').value,'Test channel');
    assert.equal($('saveChannel').disabled,true);
    """)


def test_save_reloads_before_claiming_success_and_uses_latest_version():
    _run_page_js(render_channel_admin(ADMIN), SETUP, EDIT + r"""
    let finish;
    const updated={...fixture,channel_name:'Changed channel',version:9};
    replies.push({ok:true,channel:updated},()=>new Promise(resolve=>finish=()=>resolve({status:200,ok:true,json:async()=>({ok:true,channels:[updated]})})));
    const savingPromise=save(submit);await flush();
    assert.equal($('saveChannel').disabled,true);assert.equal($('channelName').disabled,true);
    assert.ok(!$('formStatus').textContent.includes('保存成功'));
    await save(submit);assert.equal(requests.filter(r=>r.options.method==='POST').length,1);
    finish();await savingPromise;
    const post=requests.find(r=>r.options.method==='POST');
    assert.equal(post.url,'/api/v1/demo2/admin/channels');
    assert.equal(post.options.headers['Content-Type'],'application/json');
    assert.deepEqual(JSON.parse(post.options.body),{channel_id:'private-channel',expected_version:8,channel_name:'Changed channel',owner_label:'Test owner',status:'active',course_upload_limit:5});
    assert.match($('formStatus').textContent,/保存成功.*重新读取/);
    assert.equal(baseline.version,9);assert.equal($('saveChannel').disabled,true);
    assert.ok(!$('channelRows').innerHTML.includes('private-channel'));
    assert.ok(!$('channelRows').innerHTML.includes('private-account'));
    """)


def test_conflict_requires_read_and_explicit_comparison_before_new_save():
    _run_page_js(render_channel_admin(ADMIN), SETUP, EDIT + r"""
    replies.push({status:409,body:{error:{}}});await save(submit);
    assert.match($('formStatus').textContent,/刷新重新核对/);
    assert.equal($('saveChannel').disabled,true);assert.equal($('acceptComparison').hidden,true);
    await save(submit);assert.equal(requests.filter(r=>r.options.method==='POST').length,1);
    const latest={...fixture,owner_label:'Another owner',version:9};
    replies.push({ok:true,channels:[latest]});await reload();
    assert.match($('comparisonValues').innerHTML,/Another owner/);
    assert.match($('comparisonValues').innerHTML,/Changed channel/);
    assert.equal($('saveChannel').disabled,true);
    await $('acceptComparison').fire('click');assert.equal($('saveChannel').disabled,false);
    const updated={...latest,channel_name:'Changed channel',owner_label:'Test owner',version:10};
    replies.push({ok:true,channel:updated},{ok:true,channels:[updated]});await save(submit);
    assert.equal(JSON.parse(requests.filter(r=>r.options.method==='POST')[1].options.body).expected_version,9);
    """)


@pytest.mark.parametrize("message", [None, "", "   ", {}])
def test_409_without_usable_message_keeps_version_conflict_fallback(message):
    response = json.dumps({"status": 409, "body": {"error": {"message": message}}})
    _run_page_js(render_channel_admin(ADMIN), SETUP, EDIT + "replies.push(" + response + ");await save(submit);" + """
    assert.equal($('formStatus').textContent,'配置已被其他管理员修改，请刷新重新核对。');
    assert.equal(pending.kind,'conflict');assert.equal($('saveChannel').disabled,true);
    """)


def test_409_preserves_server_message_and_version_conflict_guard():
    _run_page_js(render_channel_admin(ADMIN), SETUP, EDIT + """
    const explanation='另一位管理员刚刚更新了配置，请重新读取后核对。';
    replies.push({status:409,body:{error:{message:explanation}}});await save(submit);
    assert.equal($('formStatus').textContent,explanation);
    assert.equal($('pageMessage').textContent,explanation);
    assert.equal(pending.kind,'conflict');assert.equal($('saveChannel').disabled,true);
    assert.equal(requests.filter(r=>r.options.method==='POST').length,1);
    """)


def test_quota_in_use_shows_server_instruction_and_allows_correction_without_refresh():
    _run_page_js(render_channel_admin(ADMIN), SETUP, EDIT + """
    $('courseUploadLimit').value='3';await $('channelForm').fire('change');
    const explanation='已有课程使用了 4 个名额，不能降低为 3 个，请将名额设置为至少 4 个。';
    replies.push({status:409,body:{error:{code:'channel_quota_in_use',message:explanation}}});
    await save(submit);
    assert.equal($('formStatus').textContent,explanation);
    assert.equal($('pageMessage').textContent,explanation);
    assert.equal(pending,null);assert.equal($('comparison').hidden,true);
    assert.equal($('courseUploadLimit').disabled,false);
    assert.equal(rows[0].course_upload_limit,5);assert.equal($('courseUploadLimit').value,'3');
    assert.equal(requests.length,2);
    $('courseUploadLimit').value='4';await $('channelForm').fire('change');
    const updated={...fixture,channel_name:'Changed channel',course_upload_limit:4,version:9};
    replies.push({ok:true,channel:updated},{ok:true,channels:[updated]});await save(submit);
    const posts=requests.filter(r=>r.options.method==='POST');
    assert.equal(posts.length,2);
    assert.equal(JSON.parse(posts[1].options.body).course_upload_limit,4);
    assert.equal(JSON.parse(posts[1].options.body).expected_version,8);
    assert.match($('formStatus').textContent,/保存成功.*重新读取/);
    """)


@pytest.mark.parametrize("failure", [
    "new TypeError('offline')", "{status:503,body:{}}",
    "{ok:true}", "{status:201,body:{bad:true}}",
])
def test_uncertain_save_is_locked_until_reread_and_does_not_retry(failure):
    _run_page_js(render_channel_admin(ADMIN), SETUP, EDIT + f"""
    replies.push({failure});await save(submit);
    assert.ok(pending);assert.equal($('saveChannel').disabled,true);
    await save(submit);assert.equal(requests.filter(r=>r.options.method==='POST').length,1);
    replies.push({{ok:true,channels:[{{...fixture,channel_name:'Changed channel',version:9}}]}});
    await reload();assert.equal(pending,null);assert.match($('formStatus').textContent,/无需重复保存/);
    assert.equal(requests.filter(r=>r.options.method==='POST').length,1);
    """)


def test_failed_confirmation_read_keeps_attempt_locked_even_after_cancel():
    _run_page_js(render_channel_admin(ADMIN), SETUP, EDIT + """
    replies.push({ok:true,channel:{...fixture,channel_name:'Changed channel',version:9}},new TypeError('offline'));
    await save(submit);assert.equal($('saveChannel').disabled,true);assert.ok(pending);
    assert.match($('formStatus').textContent,/保存结果未确认/);
    assert.match($('channelRows').innerHTML,/Test channel/);
    await $('cancelEdit').fire('click');openSettings(0);assert.equal($('settingsPanel').hidden,true);
    replies.push({ok:true,channels:[fixture]});await reload();openSettings(0);
    assert.equal($('channelName').value,'Changed channel');assert.equal($('saveChannel').disabled,true);
    await $('acceptComparison').fire('click');assert.equal($('saveChannel').disabled,false);
    assert.equal(requests.filter(r=>r.options.method==='POST').length,1);
    """)


@pytest.mark.parametrize("role", ["school_uploader", "registered_member", ""])
def test_non_admin_never_requests_channels(role):
    _run_page_js(render_channel_admin({"role": role}), "", """
    assert.equal(requests.length,0);assert.equal($('refreshChannels').disabled,true);
    assert.match($('roleNotice').textContent,/不是公司管理员/);
    await reload();await save({preventDefault(){}});assert.equal(requests.length,0);
    """)


@pytest.mark.parametrize("status", [401, 403])
def test_permission_loss_clears_rows_and_blocks_mutation(status):
    _run_page_js(render_channel_admin(ADMIN), SETUP, EDIT + f"""
    replies.push({{status:{status},body:{{}}}});await save(submit);
    assert.equal(rows,null);assert.equal($('settingsPanel').hidden,true);
    assert.equal($('channelRows').innerHTML,'');assert.equal($('saveChannel').disabled,true);
    assert.equal(pending,null);assert.equal(denied,true);
    """)


def test_empty_and_malformed_get_do_not_fabricate_four_channels():
    _run_page_js(render_channel_admin(ADMIN), "replies.push({ok:true,channels:[]});", """
    assert.equal(rows.length,0);assert.equal($('channelTable').hidden,true);
    assert.match($('channelCount').textContent,/0 个通道/);
    replies.push({ok:true});await reload();assert.equal(readFailed,true);
    assert.match($('channelsEmpty').textContent,/读取失败/);
    """)


_BROWSER = r"""
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const {chromium}=require(input.playwright);
(async()=>{
 const browser=await chromium.launch({executablePath:input.executable,headless:true});
 try{
  const context=await browser.newContext();
  const page=await context.newPage(),errors=[],posts=[];
  page.setDefaultTimeout(7000);page.on('pageerror',error=>errors.push(error.message));
  let role='admin',mode='ok',readStatus=200,reads=0;
  let rows=Array.from({length:4},(_,i)=>({channel_id:'hidden-channel-'+i,channel_name:'测试通道 '+(i+1),owner_label:'负责人 '+(i+1),status:i===3?'paused':'active',course_upload_limit:5,version:1,account_id:'hidden-account-'+i,username:'hidden-username-'+i}));
  await context.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url());assert.equal(url.origin,'http://channels.test');
   if(url.pathname==='/demo2/admin/channels')return route.fulfill({contentType:'text/html',body:input[role]});
   assert.equal(url.pathname,'/api/v1/demo2/admin/channels');
   if(request.method()==='GET'){reads++;return route.fulfill({status:readStatus,json:readStatus===200?{ok:true,channels:rows}:{error:{message:'Unavailable'}}});}
   assert.equal(request.method(),'POST');const body=request.postDataJSON();posts.push(body);
   const index=rows.findIndex(row=>row.channel_id===body.channel_id);
   if(mode==='conflict'){rows[index]={...rows[index],owner_label:'另一位管理员',version:rows[index].version+1};return route.fulfill({status:409,json:{error:{message:'通道配置已更新，请刷新重新核对后保存。'}}});}
   if(mode==='forbidden')return route.fulfill({status:403,json:{error:{message:'Forbidden'}}});
   if(mode==='uncertain')return route.abort('failed');
   if(mode==='validation')return route.fulfill({status:400,json:{error:{message:'名称不符合要求'}}});
   if(mode==='slow')await new Promise(resolve=>setTimeout(resolve,300));
   assert.equal(body.expected_version,rows[index].version);
   rows[index]={...rows[index],channel_name:body.channel_name,owner_label:body.owner_label,status:body.status,course_upload_limit:body.course_upload_limit,version:rows[index].version+1};
   return route.fulfill({json:{ok:true,channel:rows[index]}});
  });
  const ready=async()=>{await page.goto('http://channels.test/demo2/admin/channels');await page.locator('[data-setting="0"]:not([disabled])').waitFor();};
  const open=async()=>{await page.locator('[data-setting="0"]').click();await page.locator('#settingsPanel').waitFor();};
  const change=async text=>{await page.locator('#channelName').fill(text);assert.equal(await page.locator('#saveChannel').isEnabled(),true);};
  for(const width of [1440,1024,768,390]){
   await page.setViewportSize({width,height:900});await ready();
   assert.equal(await page.locator('#channelRows tr').count(),4);
   assert.ok(!(await page.locator('body').innerText()).includes('hidden-'));
   await open();
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'overflow '+width);
   assert.deepEqual(await page.locator('button:visible,h1,h2').evaluateAll(nodes=>nodes.filter(n=>n.scrollWidth>n.clientWidth+1).map(n=>n.textContent)),[]);
   await page.evaluate(()=>window.scrollTo(0,0));
   await page.screenshot({path:path.join(input.output,'channels-'+width+'.png'),fullPage:true});
   await page.locator('#cancelEdit').click();assert.equal(posts.length,0);
  }
  await open();await change('更新后的通道');await page.locator('#ownerLabel').fill('新负责人');
  await page.locator('#channelStatus').selectOption('paused');await page.locator('#courseUploadLimit').selectOption('3');
  mode='slow';const beforeReads=reads;await page.locator('#saveChannel').click();
  assert.equal(await page.locator('#cancelEdit').isEnabled(),false);
  await page.waitForFunction(()=>document.getElementById('formStatus').textContent.includes('保存成功'));
  assert.equal(posts.length,1);assert.ok(reads>beforeReads);assert.equal(posts[0].expected_version,1);
  assert.equal(posts[0].course_upload_limit,3);assert.equal(posts[0].status,'paused');
  await change('冲突中的修改');mode='conflict';await page.locator('#saveChannel').click();
  await page.waitForFunction(()=>document.getElementById('formStatus').textContent.includes('刷新重新核对'));
  assert.equal(await page.locator('#formStatus').innerText(),'通道配置已更新，请刷新重新核对后保存。');
  assert.equal(await page.locator('#saveChannel').isEnabled(),false);
  await page.locator('#readBeforeRetry').click();await page.locator('#acceptComparison').waitFor();
  assert.ok((await page.locator('#comparisonValues').innerText()).includes('另一位管理员'));
  assert.equal(posts.length,2);
  await page.locator('#acceptComparison').click();mode='uncertain';await page.locator('#saveChannel').click();
  await page.waitForFunction(()=>document.getElementById('comparison').hidden===false);
  assert.equal(await page.locator('#saveChannel').isEnabled(),false);
  readStatus=503;await page.locator('#readBeforeRetry').click();
  await page.waitForFunction(()=>document.getElementById('formStatus').textContent.includes('未确认'));
  assert.equal(await page.locator('#saveChannel').isEnabled(),false);
  readStatus=200;await page.locator('#readBeforeRetry').click();await page.locator('#acceptComparison').waitFor();
  assert.equal(posts.length,3);await page.locator('#acceptComparison').click();
  mode='validation';await page.locator('#saveChannel').click();
  await page.waitForFunction(()=>document.getElementById('formStatus').textContent.includes('名称不符合要求'));
  assert.equal(await page.locator('#channelName').inputValue(),'冲突中的修改');
  mode='forbidden';await page.locator('#saveChannel').click();
  await page.waitForFunction(()=>document.getElementById('settingsPanel').hidden);
  assert.equal(await page.locator('#channelRows tr').count(),0);
  readStatus=403;await page.locator('#refreshChannels').click();
  await page.waitForFunction(()=>document.getElementById('pageMessage').textContent.includes('管理员权限'));
  const beforeRoleReads=reads;role='teacher';await page.goto('http://channels.test/demo2/admin/channels');
  assert.ok((await page.locator('#roleNotice').innerText()).includes('不是公司管理员'));
  assert.equal(reads,beforeRoleReads);assert.equal(await page.locator('#refreshChannels').isEnabled(),false);
  assert.deepEqual(errors,[]);console.log('Channel browser QA finished: '+input.output);
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
"""


def test_serial_chromium1243_channels_workflow_and_four_viewports(tmp_path):
    node = shutil.which("node")
    runtime = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright"
    cache = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "ms-playwright"
    candidates = [
        cache / "chromium_headless_shell-1243/chrome-headless-shell-win64/chrome-headless-shell.exe",
        cache / "chromium-1243/chrome-win64/chrome.exe",
    ]
    executable = next((path for path in candidates if path.exists()), None)
    if not node or not runtime.exists() or not executable:
        pytest.skip("Installed Chromium 1243 and Playwright required; no downloads")
    result = subprocess.run(
        [node, "-e", _BROWSER],
        input=json.dumps({"admin": render_channel_admin(ADMIN), "teacher": render_channel_admin({"role": "school_uploader"}),
                          "playwright": str(runtime), "executable": str(executable), "output": str(tmp_path)}),
        text=True, encoding="utf-8", capture_output=True, timeout=75,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    print(result.stdout)
