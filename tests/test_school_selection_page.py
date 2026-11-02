"""Isolated school selection UI tests; all browser HTTP is locally intercepted."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

from rehab_affect.demo2_school_directory import dataset, public_entry, search
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
    # Only the shared kit's back/forward stack (rx_nav_stack) touches sessionStorage; no form data is stored.
    assert "localStorage" not in html and html.count("sessionStorage") <= 1 and "RxDraftStore={get:" not in html
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
  const page=await browser.newPage();const posts=[],errors=[],external=[],searches=[];
  page.on('pageerror',error=>errors.push(error.message));
  let context={city:'',district:'',school_name:''}, enabled=true, changeAllowed=true, failRead=false, failWrite=false, searchStatus=200;
  const regions={'':[{code:'11',name:'北京市'},{code:'31',name:'上海市'}],'11':[{code:'1101',name:'北京市'}],'1101':[{code:'110108',name:'海淀区'}],'31':[{code:'3101',name:'上海市'}],'3101':[{code:'310118',name:'青浦区'}]};
  const all=input.entries;
  await page.route('**/*',async route=>{
    const req=route.request(),url=new URL(req.url());
    if(url.origin!=='http://schools.test'){external.push(req.url());return route.abort();}
    const json=(body,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
    if(url.pathname==='/demo2/school')return route.fulfill({contentType:'text/html',body:input.html});
    if(url.pathname==='/api/v1/demo2/schools/regions')return json({ok:true,regions:(regions[url.searchParams.get('parent')||'']||[]).map(r=>({...r,level:'x',has_children:true}))});
    if(url.pathname==='/api/v1/demo2/schools/search'){
      searches.push(Object.fromEntries(url.searchParams));
      if(searchStatus!==200)return json({ok:false,error:{code:'school_search_rate_limited',message:'学校搜索过于频繁'}},searchStatus);
      const q=url.searchParams.get('q')||'',scope=url.searchParams.get('scope'),p=url.searchParams.get('province');
      const rows=all.filter(r=>(!q||r.school_name.includes(q))&&(scope!=='public_source'||r.origin==='curated')&&(!p||r.province_code===p));
      const page=Number(url.searchParams.get('page')||1);
      return json({ok:true,items:rows.slice((page-1)*20,page*20),total:rows.length,page,page_size:20,total_pages:Math.max(1,Math.ceil(rows.length/20))});
    }
    if(url.pathname==='/api/v1/demo2/school/context'&&req.method()==='GET')return route.fulfill({status:failRead?503:200,contentType:'application/json',body:JSON.stringify(failRead?{error:{message:'读取失败'}}:{context,details:{},national_directory:{label:'全国学校目录：测试'},selection_enabled:enabled,context_change_allowed:changeAllowed})});
    if(url.pathname==='/api/v1/demo2/school/context'&&req.method()==='POST'){
      const payload=req.postDataJSON();posts.push(payload);
      if(failWrite)return json({error:{code:'school_migration_required',message:'已有名册，更换学校需管理员迁移'}},409);
      let selected=payload;
      if(payload.selection_source==='national'||payload.selection_source==='directory')selected=all.find(row=>row.directory_id===payload.directory_id);
      if(payload.selection_source==='manual')selected={city:'北京市',district:'海淀区',school_name:payload.school_name};
      context={city:selected.city,district:selected.district,school_name:selected.school_name};
      return json({context});
    }
    return route.fulfill({contentType:'text/html',body:'<!doctype html><title>Local destination</title>'});
  });
  async function open(query=''){await page.goto('http://schools.test/demo2/school'+query);await page.waitForFunction(()=>!document.getElementById('reloadSchool').disabled);}
  async function results(){await page.waitForFunction(()=>!/正在搜索/.test(document.getElementById('resultInfo').textContent));}
  async function noOverflow(){assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
  await open();await results();assert.equal(posts.length,0);
  assert.equal(await page.locator('#selectionSource').inputValue(),'national');
  assert.equal(await page.locator('#regionProvince').inputValue(),'');
  assert.match(await page.locator('#coverage').textContent(),/全国学校目录/);
  // Debounced search: typing several characters issues one request after 300 ms.
  const before=searches.length;await page.locator('#schoolSearch').pressSequentially('学校',{delay:30});
  await page.waitForTimeout(450);await results();assert.equal(searches.length,before+1);assert.equal(searches.at(-1).q,'学校');
  assert.ok(await page.locator('.school-option').count()>=2);
  assert.match(await page.locator('.school-option').first().textContent(),/ · .+ · /);
  const beijing=all.find(row=>row.province_code==='11');
  await page.locator(`.school-option[data-code="${beijing.directory_id}"]`).click();
  assert.match(await page.locator('#selectedMeta').textContent(),/北京市海淀区/);
  assert.match(await page.locator('#sourceNote').textContent(),/来源/);
  await page.locator('#schoolButton').click();assert.equal(posts.length,0);
  await page.locator('#confirmed').check();
  for(const width of [320,768,1366]){
    await page.setViewportSize({width,height:900});await noOverflow();
    await page.screenshot({path:input.shots+'/national-'+width+'.png',fullPage:true});
  }
  await page.locator('#schoolButton').click();await page.locator('#saveSuccess').waitFor({state:'visible'});
  assert.equal(await page.locator('#nextStepStudents').getAttribute('href'),'/demo2/students');
  assert.deepEqual(posts[0],{selection_source:'national',directory_id:beijing.directory_id,expected_context:{city:'',district:'',school_name:''},confirmed:true});
  // Public-source list keeps the curated Qingpu entries and their dated evidence.
  context={city:'',district:'',school_name:''};await open();await results();
  await page.locator('#selectionSource').selectOption('directory');await results();
  const fudu=all.find(row=>row.directory_id==='sh-qp-fudu');
  assert.equal(searches.at(-1).scope,'public_source');
  await page.locator('.school-option[data-code="sh-qp-fudu"]').click();
  assert.match(await page.locator('#directoryAddress').textContent(),/西井街77号/);
  assert.match(await page.locator('#sourceNote').textContent(),/2022-10-27/);
  assert.equal(await page.locator('#sourceLink').getAttribute('href'),fudu.source_url);
  // Rate limit is shown inline, not as a crash.
  searchStatus=429;await page.locator('#schoolSearch').fill('东方');await page.waitForTimeout(450);await results();
  assert.match(await page.locator('#resultInfo').textContent(),/频繁/);searchStatus=200;
  // Locked owner keeps the existing school.
  context={city:'北京市',district:'海淀区',school_name:beijing.school_name};changeAllowed=false;await open();
  assert.equal(await page.locator('#selectionSource').inputValue(),'existing');
  assert.equal(await page.locator('#selectionSource').isDisabled(),true);
  assert.match(await page.locator('#scopeNotice').textContent(),/迁移/);
  await page.locator('#continueLink').click();await page.waitForURL('**/demo2/upload');assert.equal(posts.length,1);
  // Existing names are plain text, never HTML, and retain the original spelling.
  context={city:'上海',district:'青浦',school_name:'<img src=x onerror=alert(1)> 测试学校'};
  await open('?returntask=task-test');assert.equal(await page.locator('#currentName img').count(),0);
  assert.match(await page.locator('#schoolButton').textContent(),/返回视频身份确认/);
  await page.locator('#confirmed').check();await page.locator('#schoolButton').click();await page.waitForURL('**/demo2/identity?task_id=task-test');
  assert.equal(posts[1].selection_source,'existing');assert.equal(posts[1].school_name,context.school_name);
  // Manual entry: province/city/district cascade + full name, saved as pending.
  context={city:'',district:'',school_name:''};changeAllowed=true;await open('?returntask=task-other');await results();
  await page.locator('#schoolSearch').fill('不存在的学校');await page.waitForTimeout(450);await results();
  assert.match(await page.locator('#schoolResults').textContent(),/手动填写/);
  await page.locator('#regionProvince').selectOption('11');await results();
  await page.locator('#toManual').click();
  assert.equal(await page.locator('#selectionSource').inputValue(),'manual');
  assert.equal(await page.locator('#province').inputValue(),'11');
  assert.equal(await page.locator('#schoolName').inputValue(),'不存在的学校');
  await page.locator('#city').selectOption('1101');await page.waitForFunction(()=>document.getElementById('district').options.length>1);
  await page.locator('#district').selectOption('110108');
  await page.locator('#schoolName').fill('海淀区结构化测试学校');await page.locator('.extra-fields summary').click();await page.locator('#street').fill('测试街道');
  await page.locator('#confirmed').check();await page.locator('#schoolName').fill('海淀区结构化测试特教学校');assert.equal(await page.locator('#confirmed').isChecked(),false);
  await page.locator('#confirmed').check();await page.setViewportSize({width:320,height:900});await noOverflow();
  await page.screenshot({path:input.shots+'/manual-320.png',fullPage:true});
  await page.locator('#schoolButton').click();await page.waitForURL('**/demo2/identity?task_id=task-other');
  assert.deepEqual(posts[2],{selection_source:'manual',province_code:'11',city_code:'1101',district_code:'110108',school_name:'海淀区结构化测试特教学校',street:'测试街道',address:'',expected_context:{city:'',district:'',school_name:''},confirmed:true});
  // No fall-through to unguarded save, including migration conflict and unavailable API.
  context={city:'北京市',district:'海淀区',school_name:beijing.school_name};
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
    cache = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or str(
        Path.home() / ("Library/Caches/ms-playwright" if sys.platform == "darwin" else "AppData/Local/ms-playwright")))
    executables = [os.environ.get("DEMO2_BROWSER_EXECUTABLE", ""),
                   *(str(p) for p in sorted(cache.glob("chromium-*/chrome-mac*/*.app/Contents/MacOS/*"), reverse=True)),
                   *(str(p) for p in sorted(cache.glob("chromium_headless_shell-*/chrome-headless-shell-win64/chrome-headless-shell.exe"), reverse=True)),
                   "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"]
    executable = next((p for p in executables if p and Path(p).exists()), None)
    curated = [public_entry(row) for row in dataset().entries if row["origin"] == "curated"]
    special = (search("盲人学校", province="11", district="110108")["items"][:1]
               + search("特殊教育学校", province="31")["items"][:1])
    assert special[0]["region_label"] == "北京市海淀区"
    data = {"playwright": module, "executable": executable, "html": render_school_selection_html(),
            "entries": special + curated, "shots": str(tmp_path)}
    result = subprocess.run([node, "-e", "(async()=>{" + _BROWSER + "})().catch(e=>{console.error(e);process.exit(1)});"],
                            input=json.dumps(data), encoding="utf-8", capture_output=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
