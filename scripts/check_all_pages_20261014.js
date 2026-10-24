const fs = require('fs');
const {chromium} = require('playwright');
const base = 'http://127.0.0.1:8793';
const rows = fs.readFileSync('.runtime/demo2_pilot_accounts_20260908.md','utf8').split('\n');
const password = user => rows.find(r=>r.split('|').map(s=>s.trim())[2]===user).split('|')[3].trim();
const accepted = JSON.parse(fs.readFileSync('.runtime/four_channel_acceptance/latest.json','utf8'));
const task = accepted.accounts[0].task_id;
(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  const report={pages:[],errors:[],checked_at:new Date().toISOString()};
  try {
    for(const user of ['t1','admin']) {
      const context=await browser.newContext(); const page=await context.newPage();
      page.on('pageerror',e=>report.errors.push({user,error:e.message}));
      await page.goto(base+'/demo2/login');
      const auth=await context.request.post(base+'/api/v1/demo2/auth/login',{data:{username:user,password:password(user),role:user==='admin'?'company_admin':'school_uploader'}});
      if(auth.status()!==200) throw Error('Login failed '+user);
      const paths=user==='admin'?['/demo2/admin','/demo2/admin/channels','/demo2/admin/dossiers','/demo2/admin/measurements']:
        ['/demo2/login','/demo2/register','/demo2/privacy','/demo2/school','/demo2/upload','/demo2/students','/demo2/measurement','/demo2/capture','/demo2/evaluation','/demo2/safety','/demo2/video','/demo2/membership',...['analysis','identity','course-batch','teaching-support','course-dossier'].map(p=>'/demo2/'+p+'?task_id='+task)];
      for(const path of paths){
        const response=await page.goto(base+path,{waitUntil:'networkidle',timeout:30000});
        report.pages.push({user,path,status:response.status(),final_path:new URL(page.url()).pathname});
      }
      if(user==='t1'){
        const roster=await context.request.get(base+'/api/v1/demo2/identity/roster');
        if(roster.ok()){
          const data=await roster.json();
          if(data.students?.length){
            const r=await page.goto(base+'/demo2/dossier?student_id='+data.students[0].student_id,{waitUntil:'networkidle'});
            report.pages.push({user,path:'/demo2/dossier?student_id=[existing]',status:r.status()});
          } else report.dossier_note='No roster student in tested account; per-student page not exercised.';
        }
      }
      await context.close();
    }
    report.passed=report.pages.every(p=>p.status===200)&&report.errors.length===0;
    fs.writeFileSync('.runtime/page_audit_20261014.json',JSON.stringify(report,null,2));
    console.log(JSON.stringify(report));
  } finally {await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1;});
