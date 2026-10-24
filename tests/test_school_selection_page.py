"""Isolated school selection UI tests; all browser HTTP is locally intercepted."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from rehab_affect.school_directory import school_directory
from rehab_affect.school_selection_page import render_school_selection_html


def test_html_has_no_external_runtime_requests_or_legacy_write_fallback():
    html = render_school_selection_html()
    assert '/api/v1/demo2/school/selection' not in html
    assert "request('/api/v1/demo2/school/context',{...selection," in html
    assert 'id="street" maxlength="80" autocomplete="address-level3"' in html
    assert 'id="address" maxlength="300"' in html
    assert "selection_enabled===true" in html
    assert "expected_context:currentContext" in html
    assert "待核验" in html and "不代表教师身份认证" in html
    assert "localStorage" not in html and "sessionStorage" not in html
    assert not re.search(r'<script[^>]+src=', html)
    assert "referrerpolicy=\"no-referrer\"" in html
    assert "'/demo2/identity?task_id='+encodeURIComponent(returnTask)" in html
    assert "/identity/task-school" not in html
    ids = re.findall(r'\bid="([^"]+)"', html)
    assert len(ids) == len(set(ids))


def test_inline_scripts_parse():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is not installed")
    scripts = re.findall(r'<script>(.*?)</script>', render_school_selection_html(), re.S)
    assert scripts
    result = subprocess.run([node, "-e", "JSON.parse(require('fs').readFileSync(0,'utf8')).forEach(s=>new Function(s))"],
                            input=json.dumps(scripts), encoding="utf-8", capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr


_BROWSER = r"""
const fs=require('node:fs'),assert=require('node:assert/strict');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const {chromium}=require(input.playwright);
const browser=await chromium.launch({headless:true,...(input.executable?{executablePath:input.executable}:{})});
try {
  const page=await browser.newPage();const posts=[],errors=[],external=[];
  page.on('pageerror',error=>errors.push(error.message));
  let context={city:'',district:'',school_name:''}, enabled=true, changeAllowed=true, failRead=false, failWrite=false;
  await page.route('**/*',async route=>{
    const req=route.request(),url=new URL(req.url());
    if(url.origin!=='http://schools.test'){external.push(req.url());return route.abort();}
    if(url.pathname==='/demo2/school')return route.fulfill({contentType:'text/html',body:input.html});
    if(url.pathname==='/api/v1/demo2/school/context'&&req.method()==='GET')return route.fulfill({status:failRead?503:200,contentType:'application/json',body:JSON.stringify(failRead?{error:{message:'读取失败'}}:{context,directory:input.directory,selection_enabled:enabled,context_change_allowed:changeAllowed})});
    if(url.pathname==='/api/v1/demo2/school/context'&&req.method()==='POST'){
      const payload=req.postDataJSON();posts.push(payload);
      if(failWrite)return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({error:{code:'school_migration_required',message:'已有名册，更换学校需管理员迁移'}})});
      const selected=payload.selection_source==='directory'?input.directory.entries.find(row=>row.directory_id===payload.directory_id):payload;
      context={city:selected.city,district:selected.district,school_name:selected.school_name};
      return route.fulfill({contentType:'application/json',body:JSON.stringify({context})});
    }
    return route.fulfill({contentType:'text/html',body:'<!doctype html><title>Local destination</title>'});
  });
  async function open(query=''){await page.goto('http://schools.test/demo2/school'+query);await page.waitForFunction(()=>!document.getElementById('reloadSchool').disabled);}
  async function noOverflow(){assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
  await open();assert.equal(posts.length,0);assert.equal(await page.locator('#directorySchool').inputValue(),'');
  const ordinary=input.directory.entries.find(row=>row.directory_id==='sh-qp-dongfang');
  await page.locator('#directorySchool').selectOption(input.directory.entries[0].directory_id);
  assert.match(await page.locator('#directoryAddress').textContent(),/西井街77号/);
  assert.match(await page.locator('#sourceNote').textContent(),/2022-10-27/);
  assert.match(await page.locator('#sourceNote').textContent(),/现状待复核/);
  assert.equal(await page.locator('#sourceLink').getAttribute('href'),input.directory.entries[0].source_url);
  await page.locator('#schoolSearch').fill('不存在的学校');assert.equal(await page.locator('#directorySchool option').count(),1);
  await page.locator('#schoolSearch').fill('东方');assert.equal(await page.locator('#directorySchool option').count(),2);
  await page.locator('#directorySchool').selectOption(ordinary.directory_id);
  assert.match(await page.locator('#directoryAddress').textContent(),/未收录，待补充/);
  assert.match(await page.locator('#sourceNote').textContent(),/2026-04-07/);
  assert.equal(await page.locator('#sourceLink').getAttribute('href'),ordinary.source_url);
  await page.locator('#schoolButton').click();assert.equal(posts.length,0);
  await page.locator('#confirmed').check();
  for(const width of [320,768,1366]){
    await page.setViewportSize({width,height:900});await noOverflow();
    await page.screenshot({path:input.shots+'/directory-'+width+'.png',fullPage:true});
  }
  await page.locator('#schoolButton').click();await page.waitForURL('**/demo2/upload');
  assert.deepEqual(posts[0],{selection_source:'directory',directory_id:ordinary.directory_id,expected_context:{city:'',district:'',school_name:''},confirmed:true});
  changeAllowed=false;await open();assert.equal(await page.locator('#selectionSource').inputValue(),'existing');
  assert.equal(await page.locator('#selectionSource').isDisabled(),true);assert.equal(posts.length,1);
  assert.match(await page.locator('#scopeNotice').textContent(),/迁移/);
  await page.locator('#continueLink').click();await page.waitForURL('**/demo2/upload');assert.equal(posts.length,1);
  // Existing names are plain text, never HTML, and retain the original spelling.
  context={city:'上海',district:'青浦',school_name:'<img src=x onerror=alert(1)> 测试学校'};
  await open('?returntask=task-test');assert.equal(await page.locator('#currentName img').count(),0);
  await page.locator('#confirmed').check();await page.locator('#schoolButton').click();await page.waitForURL('**/demo2/identity?task_id=task-test');
  assert.equal(posts[1].selection_source,'existing');assert.equal(posts[1].school_name,context.school_name);
  context={city:'',district:'',school_name:''};changeAllowed=true;await open('?returntask=task-other');
  await page.locator('#selectionSource').selectOption('other');
  for(const [id,value] of Object.entries({province:'测试省',city:'测试市',district:'测试区',street:'测试街道',schoolName:'测试学校'}))await page.locator('#'+id).fill(value);
  await page.locator('#confirmed').check();await page.locator('#schoolButton').click();assert.equal(posts.length,2);
  await page.locator('#address').fill('测试路1号');
  await page.locator('#confirmed').check();await page.locator('#schoolName').fill('结构化测试学校');assert.equal(await page.locator('#confirmed').isChecked(),false);
  await page.locator('#confirmed').check();await page.setViewportSize({width:320,height:900});await noOverflow();
  await page.screenshot({path:input.shots+'/other-320.png',fullPage:true});
  await page.locator('#schoolButton').click();await page.waitForURL('**/demo2/identity?task_id=task-other');
  assert.equal(posts[2].selection_source,'other');assert.equal(posts[2].province,'测试省');assert.equal(posts[2].school_name,'结构化测试学校');
  assert.equal(posts[2].street,'测试街道');assert.equal(posts[2].address,'测试路1号');
  // No fall-through to unguarded save, including migration conflict and unavailable API.
  failWrite=true;await open();await page.locator('#confirmed').check();await page.locator('#schoolButton').click();
  await page.waitForFunction(()=>document.getElementById('formError').textContent.includes('管理员迁移'));
  assert.equal(await page.locator('#schoolButton').isDisabled(),true);assert.equal(posts.length,4);
  failWrite=false;enabled=false;await open();assert.equal(await page.locator('#schoolButton').isDisabled(),true);
  assert.equal(posts.length,4);assert.equal(await page.locator('#continueLink').isVisible(),true);
  enabled=true;context={city:'',district:'',school_name:''};changeAllowed=false;
  await open();assert.equal(await page.locator('#schoolButton').isDisabled(),true);
  assert.equal(await page.locator('#continueLink').isVisible(),false);
  failRead=true;await open();assert.equal(await page.locator('#schoolButton').isDisabled(),true);
  assert.equal(await page.locator('#continueLink').isVisible(),false);failRead=false;
  for(const task of ['//outside.test','../task','a'.repeat(129),'task&next=bad']){
    await open('?returntask='+encodeURIComponent(task));assert.equal(await page.locator('#continueLink').getAttribute('href'),'/demo2/upload');
  }
  assert.deepEqual(errors,[]);assert.deepEqual(external,[]);
} finally {await browser.close();}
"""


def test_browser_directory_other_scope_safety_and_responsive_layout(tmp_path):
    node = shutil.which("node")
    candidates = [os.environ.get("DEMO2_PLAYWRIGHT_MODULE", ""),
                  str(Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright"),
                  str(Path.home() / "AppData/Local/npm-cache/_npx/31e32ef8478fbf80/node_modules/playwright")]
    module = next((path for path in candidates if path and Path(path).exists()), None)
    if not node or not module:
        pytest.skip("Installed Node.js and Playwright required; no downloads")
    cache = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or str(Path.home() / "AppData/Local/ms-playwright"))
    executables = [os.environ.get("DEMO2_BROWSER_EXECUTABLE", ""),
                   *(str(p) for p in sorted(cache.glob("chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"), reverse=True)),
                   "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"]
    executable = next((p for p in executables if p and Path(p).exists()), None)
    data = {"playwright": module, "executable": executable, "html": render_school_selection_html(),
            "directory": school_directory(), "shots": str(tmp_path)}
    result = subprocess.run([node, "-e", "(async()=>{" + _BROWSER + "})().catch(e=>{console.error(e);process.exit(1)});"],
                            input=json.dumps(data), encoding="utf-8", capture_output=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
