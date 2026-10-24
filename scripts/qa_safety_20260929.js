const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const c=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{const b=await chromium.launch({channel:'msedge',headless:true});const errors=[];fs.mkdirSync(c.output,{recursive:true});try{
async function pageFor(token){const ctx=await b.newContext({viewport:{width:1440,height:1000}});await ctx.addCookies([{name:'rehab_demo2_session',value:token,url:c.base}]);const p=await ctx.newPage();p.on('pageerror',e=>errors.push(e.message));return p;}
const owner=await pageFor(c.teacher), reviewer=await pageFor(c.other),admin=await pageFor(c.admin);
await owner.goto(c.base+'/demo2/safety?task_id='+c.task_id);
await owner.waitForFunction(()=>document.querySelector('#task').value!=='');
await owner.waitForFunction(()=>document.querySelector('#source').readyState>=1);
await owner.locator('#start').fill('1');await owner.locator('#end').fill('3');
await owner.locator('#observation').fill('合成验收：出现快速肢体动作，需核对前后情境，尚无定性结论。');
await owner.locator('#action').fill('合成记录：确认现场安全后提交核查。');
await owner.evaluate(async()=>{const v=document.querySelector('#source');await v.play();});await owner.waitForFunction(()=>document.querySelector('#source').currentTime>.2);await owner.evaluate(()=>{document.querySelector('#source').pause();window.scrollTo(0,0);});
await owner.screenshot({path:path.join(c.output,'01_create.png')});
await owner.locator('#create').screenshot({path:path.join(c.output,'01b_create_form.png')});
await owner.locator('#create button.primary').click();await owner.locator('#detail').waitFor({state:'visible'});
const event=await owner.evaluate(async()=>(await(await fetch('/api/v1/demo2/safety')).json()).workspace.events[0]);
await reviewer.goto(c.base+'/demo2/safety');
assert.equal(await reviewer.evaluate(async id=>(await fetch('/api/v1/demo2/safety/media?id='+id)).status,event.id),404);
await owner.locator('#reviewer').selectOption(c.reviewer_id);await owner.locator('#assignNote').fill('合成授权：指定同校独立核查人，允许回看本课完整录像。');await owner.locator('#authorization').check();
await owner.locator('#assign').screenshot({path:path.join(c.output,'01c_assignment.png')});
await owner.locator('#assign button').click();await owner.waitForFunction(()=>document.querySelector('#meta').textContent.includes('版本 2'));
await reviewer.reload();await reviewer.locator('.entry').click();await reviewer.waitForFunction(()=>document.querySelector('#reviewVideo').readyState>=1);
await reviewer.locator('#clip').click();await reviewer.waitForFunction(()=>document.querySelector('#reviewVideo').currentTime>.2);assert(await reviewer.locator('#review').isVisible());
await reviewer.locator('#status').selectOption('ruled_out');await reviewer.locator('#reviewNote').fill('合成核查：回看前后情境及现场说明后排除本次疑似风险；非真实事件。');await reviewer.locator('#conflict').check();await reviewer.locator('#review button').click();await reviewer.waitForFunction(()=>document.querySelector('#title').textContent==='已排除');
await reviewer.screenshot({path:path.join(c.output,'02_review.png'),fullPage:true});
await reviewer.locator('#review').screenshot({path:path.join(c.output,'02b_review_form.png')});await reviewer.locator('#history').screenshot({path:path.join(c.output,'02c_history.png')});
await owner.reload();await owner.locator('.entry').click();assert.equal(await owner.locator('#review').isVisible(),false);
await owner.locator('#reviewer').selectOption('');await owner.locator('#assignNote').fill('合成测试：撤销该次视频访问授权');await owner.locator('#authorization').check();await owner.locator('#assign button').click();await owner.waitForFunction(()=>document.querySelector('#meta').textContent.includes('版本 4'));
assert.equal(await reviewer.evaluate(async id=>(await fetch('/api/v1/demo2/safety/media?id='+id)).status,event.id),404);
await admin.goto(c.base+'/demo2/login');assert.equal(await admin.evaluate(async()=>(await fetch('/api/v1/demo2/safety')).status),403);
for(const width of [390,320]){await owner.setViewportSize({width,height:900});assert.equal(await owner.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await owner.screenshot({path:path.join(c.output,`mobile_${width}.png`)});}
assert.deepEqual(errors,[]);fs.writeFileSync(path.join(c.output,'acceptance.json'),JSON.stringify({passed:true,synthetic:true,checks:['create real video event','explicit delegation','reviewer playback','human conclusion','owner cannot resolve','revoke blocks media','admin denied','mobile no overflow'],errors},null,2));console.log('Safety browser acceptance passed');
}finally{await b.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
