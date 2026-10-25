const fs=require('fs');
const {chromium}=require('playwright');
(async()=>{
  const state=JSON.parse(fs.readFileSync('.runtime/manager_share_state.json','utf8').replace(/^\uFEFF/,''));
  const rows=fs.readFileSync('.runtime/demo2_pilot_accounts_20260908.md','utf8').split('\n');
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const result={checked_at:new Date().toISOString(),accounts:[],expires_at:state.expires_at};
  try{
    for(const user of ['t1','t2','t3','t4','admin']){
      const context=await browser.newContext();const page=await context.newPage();
      await page.goto(state.invite_url,{waitUntil:'domcontentloaded',timeout:60000});
      await page.waitForURL('**/demo2/login',{timeout:60000});
      const row=rows.find(r=>r.split('|').map(s=>s.trim())[2]===user);
      const status=await page.evaluate(async data=>{
        const response=await fetch('/api/v1/demo2/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
        return response.status;
      },{username:user,password:row.split('|')[3].trim(),role:user==='admin'?'company_admin':'school_uploader'});
      if(status!==200)throw Error('Login failed: '+user+' '+status);
      const response=await page.goto(state.origin+(user==='admin'?'/demo2/admin':'/demo2/upload'),{waitUntil:'networkidle',timeout:60000});
      if(response.status()!==200)throw Error('Workspace failed: '+user);
      result.accounts.push({user,login:true,workspace:true});await context.close();
    }
    result.passed=true;
  }finally{await browser.close();fs.writeFileSync('.runtime/delivery_entry_20261008.json',JSON.stringify(result,null,2));}
  console.log(JSON.stringify(result));
})().catch(e=>{console.error(e.message);process.exitCode=1});
