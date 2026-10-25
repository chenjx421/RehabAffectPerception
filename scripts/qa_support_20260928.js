const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium}=require('playwright');
async function main(){let input='';for await(const chunk of process.stdin)input+=chunk;const c=JSON.parse(input);
fs.mkdirSync(c.output,{recursive:true});const browser=await chromium.launch({channel:'msedge',headless:true});
try{const context=await browser.newContext({viewport:{width:1440,height:1000},deviceScaleFactor:1.5});
await context.addCookies([{name:'rehab_demo2_session',value:c.teacher,url:c.base}]);const page=await context.newPage(),errors=[],shots=[];
page.on('pageerror',e=>errors.push(e.message));
const snap=async(name,selector)=>{await (selector?page.locator(selector):page).screenshot({path:path.join(c.output,name+'.png'),...(selector?{}:{fullPage:true})});shots.push(name)};
await page.goto(c.base+'/demo2/teaching-support?task_id='+c.task_id);await page.locator('#steps .step').first().waitFor();
await snap('01_upload_readiness','#readiness');await snap('02_support','#support');
await page.fill('#lessonDate','2026-09-21');await page.fill('#goal','合成示例：用图卡选择同类物品');
await page.fill('#strength','保留学生使用图卡回应的机会');await page.fill('#nextAction','下一节维持同样材料和等待时间');
await page.fill('#nextCheck','记录独立回应与提示后回应，不以未说话判定失败');
await page.click('#save');await page.waitForFunction(()=>document.querySelector('#message').textContent.includes('已保存'));
await page.reload();await page.waitForFunction(()=>document.querySelector('#goal').value.length>0);
assert.match(await page.locator('#history').textContent(),/图卡/);await snap('03_teacher_growth','#growth');
await page.click('#preview');await snap('04_deepseek','#ai');
const j=await (await context.request.get(c.base+'/api/v1/demo2/teaching-support?task_id='+c.task_id)).json();
assert.equal(j.workspace.plan.version,1);assert.equal(j.workspace.preview.network_sent,false);
assert(!JSON.stringify(j.workspace.preview).includes('合成示例'));
for(const width of [390,320]){await page.setViewportSize({width,height:844});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));await snap('mobile_'+width)}
await page.setViewportSize({width:1440,height:1000});
await page.goto(c.base+'/demo2/analysis?task_id='+c.task_id);await page.locator('#groupStats .stat').first().waitFor();await page.click('#tab-review');await page.locator('#editPanel summary').first().click();await snap('05_communication_review');
for(const [name,url] of [['06_upload','/demo2/upload'],['07_students','/demo2/students'],['08_identity','/demo2/identity?task_id='+c.task_id],['09_measurement','/demo2/measurement'],['10_evaluation','/demo2/evaluation']]){await page.goto(c.base+url);await page.waitForTimeout(700);await snap(name)}
assert.deepEqual(errors,[]);fs.writeFileSync(path.join(c.output,'acceptance.json'),JSON.stringify({screenshots:shots,errors,plan_saved_reloaded:true,preview_no_network:true,synthetic:true},null,2));
console.log(JSON.stringify({screenshots:shots,errors}));
}finally{await browser.close()}}
main().catch(e=>{console.error(e);process.exitCode=1});
