// Uses private local credentials, never logs passwords or student task details.
const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const state=JSON.parse(fs.readFileSync('.runtime/manager_share_state.json','utf8').replace(/^\uFEFF/,''));
const credentials=fs.readFileSync('.runtime/demo2_pilot_accounts_20260908.md','utf8');
const password=user=>{const row=credentials.split('\n').find(l=>l.split('|').map(x=>x.trim())[2]===user);assert(row,'credential missing');return row.split('|')[3].trim();};
const report={checked_at:new Date().toISOString(),origin:state.origin,accounts:[],synthetic_upload:false,network_resolver_override:true};
(async()=>{const b=await chromium.launch({channel:'msedge',headless:true,args:['--host-resolver-rules=MAP '+new URL(state.origin).hostname+' 104.16.230.132']});try{
for(const user of ['t1','t2','t3','t4']){
 const ctx=await b.newContext();const page=await ctx.newPage();
 // Verify every actual credential locally before using the remote entry.
 await page.goto('http://127.0.0.1:8793/demo2/login');
 const login=await page.evaluate(async p=>{const r=await fetch('/api/v1/demo2/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(p)});return {status:r.status,data:await r.json()};},{username:user,password:password(user)});
 assert.equal(login.status,200,user+' login');
 const ws=await page.evaluate(async()=>{const r=await fetch('/api/v1/demo2/upload/workspace?course_id=manager-preflight-20260929');return {status:r.status,data:await r.json()};});
 assert.equal(ws.status,200,user+' upload workspace');
 report.accounts.push({username:user,login:true,upload_workspace:true});
 console.log(user+' local login and upload workspace passed');
 await ctx.close();
}
const ctx=await b.newContext({viewport:{width:1440,height:1000}});const page=await ctx.newPage();page.setDefaultTimeout(60000);page.on('response',r=>{if(r.url().includes('/__manager/')||r.url().endsWith('/demo2/login'))console.log(new URL(r.url()).pathname,r.status());});
await page.goto(state.origin+'/invite',{waitUntil:'domcontentloaded',timeout:60000});await page.goto('about:blank');
await page.goto(state.invite_url,{waitUntil:'domcontentloaded',timeout:60000});console.log('Remote initial path',new URL(page.url()).pathname);await page.waitForURL('**/demo2/login',{waitUntil:'domcontentloaded'});console.log('Remote invitation passed');
await page.locator('#username').fill('t1');await page.locator('#password').fill(password('t1'));await page.locator('#loginButton').click();await page.waitForURL('**/demo2/school',{waitUntil:'domcontentloaded'});console.log('Remote account login passed');
await page.goto(state.origin+'/demo2/upload');await page.locator('#uploadTitle').waitFor();
if(process.argv.includes('--read-only')){
 const tasks=await page.evaluate(async()=>(await(await fetch('/api/v1/demo2/course-analysis/tasks')).json()).tasks||[]);
 const task=tasks.find(t=>t.course_id==='manager-preflight-20260929');assert(task,'synthetic preflight task available');
 const response=await page.goto(state.origin+'/demo2/analysis?task_id='+encodeURIComponent(task.task_id),{waitUntil:'domcontentloaded'});
 console.log('Analysis page HTTP',response.status());
 if(response.status()!==200)throw Error('Analysis page HTTP '+response.status());
 try{await page.locator('#applicabilitySection').waitFor({state:'visible',timeout:20000});}catch(e){console.log('Analysis message',await page.locator('#message').textContent().catch(()=> 'Page not rendered'));throw e;}
 const gate=await page.evaluate(async id=>(await(await fetch('/api/v1/demo2/applicability?task_id='+id)).json()).result,task.task_id);
 assert.equal(gate.automatic_scene_recognition,false);report.applicability_available=true;
 fs.writeFileSync('.runtime/manager_applicability_acceptance_20260929.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));return;
}
await page.locator('#courseId').fill('manager-preflight-20260929');await page.locator('#courseName').fill('技术连通测试（合成素材，非学校课程）');await page.locator('#loadCourseButton').click();
await page.locator('#videoFile').setInputFiles(path.resolve('.runtime/upload_smoke_20260929.mp4'));
await page.waitForFunction(()=>!document.querySelector('#uploadButton').disabled);
let taskId='';page.on('response',async r=>{if(r.url().endsWith('/upload/tasks')&&r.request().method()==='POST'){try{taskId=(await r.json()).task?.task_id||'';}catch{}}});
await page.locator('#uploadButton').click();
await page.waitForFunction(()=>document.querySelector('#progressPercent').textContent==='100%',{},{timeout:120000});
assert(taskId,'uploaded task ID');report.synthetic_upload=true;
for(let i=0;i<30;i++){
 const task=await page.evaluate(async id=>{const r=await fetch('/api/v1/demo2/upload/task?id='+encodeURIComponent(id));const j=await r.json();return j.task||{};},taskId);
 report.analysis_status=task.analysis_status;
 if(['evidence_ready','completed','failed'].includes(task.analysis_status))break;
 await page.waitForTimeout(2000);
}
assert(['evidence_ready','completed'].includes(report.analysis_status),'processing did not complete: '+report.analysis_status);
fs.writeFileSync('.runtime/manager_upload_acceptance_20260929.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report));
}finally{await b.close();}})().catch(e=>{console.error(String(e).replace(/\/invite#[^\s"']+/g,'/invite#[REDACTED]'));process.exitCode=1;});
