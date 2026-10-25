// Capture local interfaces without changing school, student, or task records.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'output/playwright/demo2_version_guide_20260910');
const base = 'http://127.0.0.1:8792';
const task = 'a5ded3bc97c54d949961b130e6f18ca2';
const manifest = {captured_at:new Date().toISOString(),local_only:true,record_writes:false,shots:[],errors:[]};
fs.mkdirSync(out,{recursive:true});

(async()=>{
  const cache=path.join(process.env.LOCALAPPDATA,'ms-playwright');
  const installed=fs.readdirSync(cache).filter(name=>name.startsWith('chromium_headless_shell-')).sort().reverse().map(name=>path.join(cache,name,'chrome-headless-shell-win64/chrome-headless-shell.exe')).find(file=>fs.existsSync(file));
  const browser = await chromium.launch({headless:true,...(installed?{executablePath:installed}:{channel:'msedge'})});
  try {
    const context = await browser.newContext({viewport:{width:1200,height:700},deviceScaleFactor:1.5,locale:'zh-CN',serviceWorkers:'block'});
    await context.route('**/*', route=>{
      const request=route.request(),url=new URL(request.url());
      if(url.origin!==base || (!['GET','HEAD'].includes(request.method()) && !['/api/v1/demo2/auth/login','/api/v1/demo2/auth/logout'].includes(url.pathname))) {
        manifest.errors.push({blocked:url.pathname,method:request.method()});
        return route.abort('blockedbyclient');
      }
      return route.continue();
    });
    const page=await context.newPage();
    page.setDefaultTimeout(20000);
    page.on('pageerror',e=>manifest.errors.push({message:e.message}));
    const go=async route=>{await page.goto(base+route,{waitUntil:'domcontentloaded'});await page.evaluate(()=>document.fonts.ready);};
    const shot=async(name,selector)=>{
      await page.evaluate(()=>document.activeElement?.blur());
      if(selector)await page.locator(selector).first().evaluate(el=>scrollTo({top:el.getBoundingClientRect().top+scrollY-88,behavior:'instant'}));
      else await page.evaluate(()=>scrollTo({top:0,behavior:'instant'}));
      await page.waitForTimeout(200);
      const file=path.join(out,name+'.png');
      await page.screenshot({path:file,fullPage:false,animations:'disabled'});
      manifest.shots.push({name,file,route:new URL(page.url()).pathname,width:1800,height:1050});
      console.log('Captured '+name);
    };
    await go('/demo2/login');await shot('login');
    await page.locator('#adminRole').click();await shot('login_admin');
    await go('/demo2/register');
    await page.waitForFunction(()=>!document.getElementById('smsStatus').textContent.includes('正在'));
    await shot('register');await shot('register_fields','#registerButton');
    await go('/demo2/login');
    await page.locator('#username').fill('t1');
    await page.locator('#password').fill(process.env.REHAB_TEACHER_PASSWORD);
    await page.locator('#loginButton').click();await page.waitForURL('**/demo2/school');
    await page.waitForFunction(()=>!document.getElementById('schoolButton').disabled);await shot('school');
    await go('/demo2/upload?course_id=media-validation-20260908');
    await page.waitForFunction(()=>document.getElementById('taskList').textContent.includes('a5ded3bc'));
    await shot('upload');await shot('upload_file','.file-control');await shot('upload_tasks','.task-section');
    await go('/demo2/students');await page.waitForFunction(()=>!document.getElementById('rosterCount').textContent.includes('正在'));
    await shot('roster');
    await go('/demo2/video?id='+task);
    await page.waitForFunction(()=>document.getElementById('stageLabel').textContent.includes('证据已就绪'));
    await page.waitForFunction(()=>document.getElementById('classVideo').readyState>=2);
    await page.locator('#seekSlider').fill('1200');
    await page.waitForFunction(()=>{const v=document.getElementById('classVideo');return v.currentTime>=1199&&!v.seeking&&v.readyState>=2;});
    await shot('video','.video-stage');await shot('timeline','.timeline-section');
    await go('/demo2/identity?task_id='+task);
    await page.waitForFunction(()=>document.getElementById('frameImage').naturalWidth>0&&!document.getElementById('detectionStatus').textContent.includes('正在'));
    await shot('school_confirmation','#schoolConfirmation');
    await page.waitForTimeout(2200);
    const detected=page.waitForResponse(r=>r.url().includes('/identity/detect?'));
    await page.locator('#jumpTime').fill('1200');await page.locator('#jumpFrame').click();
    const detection=(await (await detected).json()).detection;
    assert.equal(detection.available,true);manifest.position_candidates=detection.faces.length;
    await page.waitForFunction(()=>!document.getElementById('detectionStatus').textContent.includes('正在'));
    await shot('identity','.work-layout');
    await page.locator('#frameSurface').screenshot({path:path.join(out,'detected_frame.png')});
    manifest.shots.push({name:'detected_frame',file:path.join(out,'detected_frame.png'),route:'/demo2/identity',element:'#frameSurface'});
    if(detection.faces.length){await page.locator('[data-candidate="0"]').click();await shot('identity_selected','.work-layout');await shot('identity_fields','#bindingForm');}
    await go('/demo2/membership');
    await page.waitForFunction(()=>document.getElementById('membershipStatus').textContent&&!document.getElementById('membershipStatus').textContent.includes('正在'));
    await shot('membership');
    await context.request.post(base+'/api/v1/demo2/auth/logout',{data:{},headers:{Origin:base}});
    await go('/demo2/login');await page.locator('#adminRole').click();
    await page.locator('#username').fill('admin');await page.locator('#password').fill(process.env.REHAB_ADMIN_PASSWORD);
    await page.locator('#loginButton').click();await page.waitForURL('**/demo2/admin');
    await page.waitForFunction(()=>document.getElementById('taskCount').textContent!=='--');
    await shot('admin');await shot('storage','section[aria-labelledby="taskTitle"]');
    await context.request.post(base+'/api/v1/demo2/auth/logout',{data:{},headers:{Origin:base}});
    await context.close();
    assert.deepEqual(manifest.errors,[]);
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(out,'manifest.json'),JSON.stringify(manifest,null,2));
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
