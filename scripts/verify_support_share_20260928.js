const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium}=require('playwright');
async function main(){const s=JSON.parse(fs.readFileSync('.runtime/manager_share_state.json','utf8').replace(/^\uFEFF/,''));
const ip=process.env.DEMO_SHARE_VERIFY_IP;
if(ip&&!/^\d{1,3}(\.\d{1,3}){3}$/.test(ip))throw new Error('Invalid resolver override');
const browser=await chromium.launch({channel:'msedge',headless:true,args:ip?['--host-resolver-rules=MAP '+new URL(s.origin).hostname+' '+ip]:[]});
try{const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();
page.on('response',r=>{if(r.url().includes('/__manager/')||r.url().endsWith('/demo2/login'))console.log(new URL(r.url()).pathname,r.status())});
await page.goto(s.origin+'/invite',{timeout:60000});
for(const url of ['/api/v1/demo2/admin/summary','/api/v1/demo2/teaching-support?task_id=unavailable']){
 const status=await page.evaluate(async u=>(await fetch(u)).status,url);assert([401,403,404,410].includes(status));}
await page.goto('about:blank');
await page.goto(s.invite_url,{waitUntil:'domcontentloaded',timeout:60000});
try{await page.waitForURL('**/demo2/login',{timeout:20000,waitUntil:'domcontentloaded'});}catch(e){console.log(await page.locator('body').innerText());throw e;}
assert((await context.cookies()).some(x=>x.name==='rehab_manager_invite'&&x.secure&&x.httpOnly));
const p='output/playwright/support_20260928';fs.mkdirSync(p,{recursive:true});
await page.screenshot({path:path.join(p,'00_external_login.png'),fullPage:true});
const status=await page.evaluate(async()=>(await fetch('/api/v1/demo2/teaching-support?task_id=unavailable')).status);
assert([401,403].includes(status));
fs.writeFileSync(path.join(p,'external_acceptance.json'),JSON.stringify({origin:s.origin,invite_login:true,secure_cookie:true,anonymous_data_denied:true,account_login_not_tested:true,dns_override:ip||null},null,2));
console.log(JSON.stringify({origin:s.origin,invite_login:true,anonymous_data_denied:true}));
}finally{await browser.close()}}
main().catch(e=>{console.error(String(e).replace(/\/invite#[^\s"']+/g,'/invite#[REDACTED]'));process.exitCode=1});
