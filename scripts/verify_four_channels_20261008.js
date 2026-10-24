// Real browser / API acceptance. Credentials and results stay in .runtime.
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const base=process.env.DEMO2_TEST_BASE||'http://127.0.0.1:8793';
const privateDir=path.resolve(base.startsWith('https:')?'.runtime/four_channel_acceptance_public':'.runtime/four_channel_acceptance');fs.mkdirSync(privateDir,{recursive:true});
const creds=fs.readFileSync('.runtime/demo2_pilot_accounts_20260908.md','utf8');
const password=user=>{const row=creds.split('\n').find(l=>l.split('|').map(x=>x.trim())[2]===user);assert(row,'credential missing');return row.split('|')[3].trim();};
const run='technical-acceptance-'+Date.now();
const report={run,base,synthetic_only:true,automatic_classroom_scoring:false,accounts:[],admin:{},errors:[]};
const save=()=>fs.writeFileSync(path.join(privateDir,'latest.json'),JSON.stringify(report,null,2));
async function request(page,url){
 let data;for(let attempt=0;attempt<3;attempt++){try{data=await page.evaluate(async u=>{const r=await fetch(u);const b=new Uint8Array(await r.arrayBuffer());let s='';for(let i=0;i<b.length;i+=8192)s+=String.fromCharCode(...b.subarray(i,i+8192));return {status:r.status,bytes:btoa(s)};},url);break;}catch(e){if(attempt===2)throw e;await page.waitForTimeout(1000);}}
 const body=Buffer.from(data.bytes,'base64');return {status:()=>data.status,ok:()=>data.status>=200&&data.status<300,body:async()=>body,json:async()=>JSON.parse(body.toString())};
}
async function json(page,url){const r=await request(page,url);return {status:r.status(),body:await r.json()};}
async function invitation(page){if(!base.startsWith('https:'))return;const s=JSON.parse(fs.readFileSync('.runtime/manager_share_state.json','utf8').replace(/^\uFEFF/,''));assert.equal(s.origin,base);await page.goto(s.invite_url,{waitUntil:'domcontentloaded',timeout:60000});await page.waitForURL('**/demo2/login',{waitUntil:'domcontentloaded',timeout:60000});}
(async()=>{const browser=await chromium.launch({channel:'msedge',headless:true});const contexts=[];
try{
 for(const user of ['t1','t2','t3','t4']){
  const ctx=await browser.newContext({viewport:{width:1440,height:1000}});contexts.push(ctx);const page=await ctx.newPage();page.setDefaultTimeout(45000);
  page.on('pageerror',e=>report.errors.push({user,error:e.message}));
  await invitation(page);
  await page.goto(base+'/demo2/login',{waitUntil:'domcontentloaded'});
  await page.locator('#username').fill(user);await page.locator('#password').fill(password(user));await page.locator('#loginButton').click();
  await page.waitForURL('**/demo2/school',{waitUntil:'domcontentloaded'});
  const item={user,login:true};report.accounts.push(item);save();
  await page.goto(base+'/demo2/upload');await page.locator('#uploadTitle').waitFor();
  await page.locator('#courseId').fill(run);await page.locator('#courseName').fill('四通道技术验收（合成视频，非课堂评分）');await page.locator('#loadCourseButton').click();
  await page.locator('#videoFile').setInputFiles(path.resolve('.runtime/four_channel_acceptance/synthetic_av.mp4'));
  await page.waitForFunction(()=>!document.querySelector('#uploadButton').disabled);
  const created=page.waitForResponse(r=>r.url().endsWith('/upload/tasks')&&r.request().method()==='POST');
  await page.locator('#uploadButton').click();const response=await created;const body=await response.json();assert(response.ok(),'task creation failed');
  item.task_id=body.task?.task_id;assert(item.task_id,'task ID missing');
  await page.waitForFunction(()=>document.querySelector('#progressPercent').textContent==='100%',null,{timeout:180000});item.upload=true;
  const deadline=Date.now()+180000;
  while(Date.now()<deadline){const r=await json(page,'/api/v1/demo2/upload/task?id='+item.task_id);assert.equal(r.status,200);item.analysis_status=r.body.task.analysis_status;
   if(['evidence_ready','completed','failed'].includes(item.analysis_status))break;await page.waitForTimeout(2000);}
  assert(['evidence_ready','completed'].includes(item.analysis_status),'worker failed or timed out: '+item.analysis_status);
  for(const asset of ['source','audio']){const r=await request(page,'/api/v1/demo2/upload/media?id='+item.task_id+'&asset='+asset);assert(r.ok(),asset+' unavailable '+r.status());item[asset+'_bytes']=(await r.body()).length;assert(item[asset+'_bytes']>0);}
  const download=await request(page,'/api/v1/demo2/upload/result?id='+item.task_id);assert(download.ok(),'result download');
  const result=await download.json();assert(result&&typeof result==='object');item.result_download=true;item.result_keys=Object.keys(result);
  fs.writeFileSync(path.join(privateDir,user+'_result.json'),JSON.stringify(result,null,2));
  const analysis=await page.goto(base+'/demo2/analysis?task_id='+item.task_id);assert.equal(analysis.status(),200);await page.locator('#applicabilitySection').waitFor();item.analysis_page=true;
  await page.screenshot({path:path.join(privateDir,user+'_analysis.png'),fullPage:true});
  if(report.accounts.length>1){const other=report.accounts[0].task_id;const denied=await request(page,'/api/v1/demo2/upload/result?id='+other);assert([403,404].includes(denied.status()),'cross-account data exposure');item.cross_account_denied=true;}
  save();console.log(user+' upload, processing, source/audio playback endpoints, result download and analysis page passed');
 }
 const ctx=await browser.newContext({viewport:{width:1440,height:1000}});const page=await ctx.newPage();await invitation(page);await page.goto(base+'/demo2/login');
 const login=await page.evaluate(async p=>{const r=await fetch('/api/v1/demo2/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});return r.status;},{username:'admin',password:password('admin'),role:'company_admin'});assert.equal(login,200);report.admin.login=true;
 const response=await page.goto(base+'/demo2/admin');assert.equal(response.status(),200);await page.locator('#recentUploads').waitFor();
 const summary=await json(page,'/api/v1/demo2/admin/summary');assert.equal(summary.status,200);
 const serialized=JSON.stringify(summary.body);for(const item of report.accounts)assert(serialized.includes(item.task_id),'admin task not listed');report.admin.four_tasks_visible=true;
 const channels=await json(page,'/api/v1/demo2/admin/channels');assert.equal(channels.status,200);report.admin.channels=true;
 for(const item of report.accounts){const r=await request(page,'/api/v1/demo2/upload/result?id='+item.task_id);assert(r.ok(),'admin result download');assert((await r.body()).length>0);}
 report.admin.four_results_downloadable=true;
 await page.screenshot({path:path.join(privateDir,'admin.png'),fullPage:true});
 const anon=await browser.newContext();const anonPage=await anon.newPage();await anonPage.goto(base+(base.startsWith('https:')?'/invite':'/demo2/login'));const denied=await request(anonPage,'/api/v1/demo2/upload/result?id='+report.accounts[0].task_id);assert([401,403].includes(denied.status()));report.anonymous_download_denied=true;
 assert.equal(report.errors.length,0,'browser JavaScript errors');report.passed=true;save();console.log('ALL FOUR CHANNELS AND ADMIN PASSED');
}catch(e){report.failure=String(e).split('\n')[0];save();throw e;}finally{await browser.close();}})().catch(e=>{console.error(String(e).split('\n')[0]);process.exitCode=1;});
