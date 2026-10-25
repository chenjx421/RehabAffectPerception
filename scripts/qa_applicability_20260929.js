const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');const c=JSON.parse(fs.readFileSync(0,'utf8'));
(async()=>{const b=await chromium.launch({channel:'msedge',headless:true});const errors=[];try{
fs.mkdirSync(c.output,{recursive:true});const ctx=await b.newContext({viewport:{width:1440,height:1000}});await ctx.addCookies([{name:'rehab_demo2_session',value:c.teacher,url:c.base}]);const p=await ctx.newPage();p.on('pageerror',e=>errors.push(e.message));
await p.goto(c.base+'/demo2/analysis?task_id='+c.task_id);await p.locator('#applicabilitySection').waitFor({state:'visible'});assert.match(await p.locator('#applicabilityLabel').textContent(),/待确认/);
await p.screenshot({path:path.join(c.output,'01_pending.png')});
for(const [category,label] of [['irrelevant','非课堂'],['general','普通课堂'],['insufficient','证据不足'],['special','已人工确认']]){
await p.locator('#applicabilityDetails').evaluate(el=>el.open=true);await p.locator('#applicabilityCategory').selectOption(category);await p.locator('#applicabilityGoal').fill('合成验收：按指令分类');await p.locator('#applicabilityReason').fill('合成流程测试：人工核对片段与背景，不是模型场景分类。');await p.locator('#applicabilityConfirmed').check();await p.locator('#applicabilitySave').click();await p.waitForFunction(l=>document.querySelector('#applicabilityLabel').textContent.includes(l),label);
const work=await p.evaluate(async tid=>(await(await fetch('/api/v1/demo2/course-analysis?task_id='+tid)).json()).workspace,c.task_id);assert.equal(work.applicability.allowed,category==='special');if(category!=='special'){assert.equal(work.report.ready,false);assert.equal(work.summary.scored,0);}
await p.locator('#tab-report').click();await p.evaluate(()=>window.scrollTo(0,0));await p.screenshot({path:path.join(c.output,category+'.png')});}
await p.reload();await p.waitForFunction(()=>document.querySelector('#applicabilityLabel').textContent.includes('已人工确认'));
for(const width of [390,320]){await p.setViewportSize({width,height:900});await p.locator('#applicabilityDetails').evaluate(el=>el.open=true);assert.equal(await p.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await p.screenshot({path:path.join(c.output,'mobile_'+width+'.png')});}
assert.deepEqual(errors,[]);fs.writeFileSync(path.join(c.output,'acceptance.json'),JSON.stringify({passed:true,synthetic:true,automatic_scene_recognition:false,checks:['pending blocks score','nonclassroom blocks report','general classroom blocked','insufficient evidence blocked','manual confirmation persists','320/390 no overflow'],errors},null,2));console.log('Applicability browser acceptance passed');
}finally{await b.close();}})().catch(e=>{console.error(e);process.exitCode=1;});
