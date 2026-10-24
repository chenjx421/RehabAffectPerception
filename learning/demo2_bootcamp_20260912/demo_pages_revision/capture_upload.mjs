import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';
const dir=path.dirname(fileURLToPath(import.meta.url));
const account={account_id:'teaching-account',username:'teaching-account',login_alias:'教学演示账号',role:'school_uploader',bound_channel_id:'channel_1',course_upload_limit:5,status:'active'};
const workspace={account,course_id:'TEACHING-001',channel:{channel_id:'channel_1',channel_name:'教学演示通道 1'},max_slots:5,used_slots:3,remaining_slots:2,students:[],tasks:[
 {task_id:'teaching-queued',original_filename:'教学片段A.mp4',byte_size:12582912,upload_status:'completed',analysis_status:'queued',progress_percent:100,processing_progress:0},
 {task_id:'teaching-processing',original_filename:'教学片段B.mp4',byte_size:18874368,upload_status:'completed',analysis_status:'processing',progress_percent:100,processing_progress:45},
 {task_id:'teaching-ready',original_filename:'教学片段C.mp4',byte_size:20971520,upload_status:'completed',analysis_status:'evidence_ready',progress_percent:100,processing_progress:100}
]};
const html=await fs.readFile(dir+'/assets/upload.html','utf8');
const browser=await chromium.launch({executablePath:process.argv[2],headless:true,args:['--disable-background-networking','--disable-component-update','--disable-sync','--host-resolver-rules=MAP * ~NOTFOUND']});
const report={actual_frontend:'src/rehab_affect/demo2_portal.py::render_demo2_upload_html',data:'fictional browser fixture',live_service_used:false,db_access:false,upload_submitted:false,requests:[],pageErrors:[]};
try {
 const context=await browser.newContext({viewport:{width:1366,height:950},deviceScaleFactor:2,serviceWorkers:'block',acceptDownloads:false});
 await context.route('**/*',async route=>{
   const u=new URL(route.request().url()); report.requests.push({path:u.pathname,method:route.request().method()});
   if(u.hostname!=='demo2-learning.invalid'||route.request().method()!=='GET')return route.abort();
   if(u.pathname==='/demo2/upload')return route.fulfill({status:200,contentType:'text/html',body:html});
   let body;
   if(u.pathname==='/api/v1/demo2/auth/me')body={ok:true,account};
   else if(u.pathname==='/api/v1/demo2/school/context')body={ok:true,context:{city:'教学示例市',district:'教学示例区',school_name:'虚构教学学校'}};
   else if(u.pathname==='/api/v1/demo2/upload/workspace')body={ok:true,workspace};
   else return route.abort();
   return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
 });
 const page=await context.newPage();page.on('pageerror',e=>report.pageErrors.push(e.message));
 await page.goto('http://demo2-learning.invalid/demo2/upload?course_id=TEACHING-001');
 await page.locator('#taskList').getByText('证据已就绪',{exact:true}).waitFor();
 await fs.writeFile(dir+'/qa/upload-snapshot.txt',await page.locator('body').innerText());
 await page.getByLabel('课程名称',{exact:true}).fill('图形配对课堂（教学示例）');
 await page.screenshot({path:dir+'/assets/upload_page.png',fullPage:true});
 await page.locator('.task-section').screenshot({path:dir+'/assets/task_states.png'});
 report.screenshots=['upload_page.png','task_states.png'];
 await fs.writeFile(dir+'/qa/capture_report.json',JSON.stringify(report,null,2));
 console.log(JSON.stringify({screenshots:report.screenshots,pageErrors:report.pageErrors,allRequestsMocked:true}));
} finally {await browser.close();}
