'use strict';
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const root=path.resolve(__dirname,'..');
const out=path.join(root,'.runtime/admin_history_acceptance_20261016');
const read=p=>JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''));
(async()=>{
  fs.mkdirSync(out,{recursive:true});
  const credential=read(path.join(root,'.runtime/admin_credentials_20261016.json'));
  const origin='http://127.0.0.1:8793';
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try{
    const context=await browser.newContext({viewport:{width:1440,height:1000}});
    const login=await context.request.post(origin+'/api/v1/demo2/auth/login',{
      data:{...credential,role:'company_admin'},headers:{Origin:origin}});
    assert.equal(login.status(),200);
    const page=await context.newPage(),errors=[];
    page.on('pageerror',e=>errors.push(e.name));
    await page.goto(origin+'/demo2/admin');
    await page.waitForFunction(()=>document.querySelector('#uploadPageStatus').textContent.includes('1 / 2'));
    const first=await page.locator('#recentUploads a').evaluateAll(a=>a.map(x=>x.getAttribute('href')));
    assert.equal(first.length,20);
    await page.locator('#nextUploads').click();
    await page.waitForFunction(()=>document.querySelector('#uploadPageStatus').textContent.includes('2 / 2'));
    const second=await page.locator('#recentUploads a').evaluateAll(a=>a.map(x=>x.getAttribute('href')));
    assert(second.length>0);
    assert(!second.some(id=>first.includes(id)));
    const updated=await page.locator('#adminRefreshStatus').textContent();
    await page.waitForResponse(r=>r.url().includes('/admin/summary?upload_page=2'),{timeout:45000});
    await page.waitForFunction(old=>document.querySelector('#adminRefreshStatus').textContent!==old,updated);
    assert((await page.locator('#uploadPageStatus').textContent()).includes('2 / 2'));
    await page.locator('#accountName').evaluate(node=>{node.textContent='Company administrator';});
    await page.locator('#recentTitle').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(out,'admin-history-desktop.png')});
    await page.setViewportSize({width:390,height:844});
    await page.locator('#recentTitle').scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(out,'admin-history-mobile.png')});
    assert.equal(errors.length,0);
    const result={passed:true,pages:2,total_reachable:first.length+second.length,
      auto_refresh_observed:true,selected_page_preserved:true,browser_errors:errors,
      local_only:true,new_uploads_created:false};
    fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(result,null,2));
    console.log(JSON.stringify(result));
    await context.close();
  }finally{await browser.close();}
})().catch(e=>{console.error(e.name+': '+e.message);process.exitCode=1;});
