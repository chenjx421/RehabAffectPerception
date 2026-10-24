import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath,pathToFileURL} from 'node:url';
import sharp from 'sharp';
import {FileBlob,PresentationFile} from '@oai/artifact-tool';

const ROOT='D:/GIT/RehabAffectPerception';
const DIR=path.dirname(fileURLToPath(import.meta.url));
const SKILL='C:/Path/To/Developer/.codex/plugins/cache/openai-primary-runtime/presentations/26.909.11814/skills/presentations';
const PY='C:/Path/To/Developer/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
process.env.RUNTIME_NODE_MODULES='C:/Path/To/Developer/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
process.env.RUNTIME_NODE=process.execPath;
const SOURCE=ROOT+'/output/presentations/Demo2_实习项目三天学习_20260912_讲解版.pptx';
const FINAL=ROOT+'/output/presentations/Demo2_实习项目三天学习_20260912_Demo页面版_定稿.pptx';
const FONT='Microsoft YaHei';
const manual=ROOT+'/output/playwright/demo2_teacher_flow_20260911_isolated/manual_reloaded.png';
const dossier=ROOT+'/output/playwright/demo2_dossier_20260911_isolated/run_20260911_163930_425447/';
const colors=['#205ABD','#087C72','#7B4D99'];
const chapters=['第一天  图像与人脸定位','第二天  跟随与模型评价','第三天  工程与实习表达'];
const modelScope='当前YuNet为固定预训练face_detection_yunet_2023mar.onnx，由OpenCV DNN在CPU上推理，本项目没有微调。姓名由教师确认；Shi–Tomasi和LK是传统算法。媒体处理完成、找到人脸、确认身份、理解状态、判断掌握度是不同能力。';
const screenDefs=[
 {after:4,key:'upload',title:'Demo 页面：提交课堂视频',chapter:1,image:DIR+'/assets/upload_page.png',rect:[168,432,2390,1160],layout:'wide',
  points:[['页面操作','填写课程批次，读取名额，再选择视频。'],['对应代码','demo2_portal.py:312\nuploadVideo → 分片请求'],['实习讲述','说明账号、课程和上传任务如何关联。']],
  caption:'填写课程批次并读取名额，再选择视频。此截图未选择文件、未提交上传。',
  source:'demo2_portal.py:312; scenario_lab_server.py:1347; student_record_store.py:1543',
  notes:'页面：/demo2/upload。读取课程通过GET /api/v1/demo2/upload/workspace?course_id=...，上传通过POST /api/v1/demo2/upload/tasks建立任务，再POST /api/v1/demo2/upload/chunks接收4MB分片。输入是课程批次、文件元信息与账号绑定通道；输出是持久化任务与进度，尚非模型结果。失败时分别处理名额不足、文件不合规、权限不足、分片错误。截图直接使用现有render_demo2_upload_html输出，在浏览器中拦截请求并提供虚构数据，不连接服务或数据库。小练习：为什么上传时“计划关注学生”不能代替画面身份确认？'},
 {after:4,key:'tasks',title:'Demo 页面：上传后的三种任务状态',chapter:1,image:DIR+'/assets/task_states.png',rect:[0,570,1718,792],layout:'wide',
  caption:'等待处理 → 后台处理中 → 证据已就绪；最后一步仍标注“待教师复核”。',
  source:'demo2_portal.py:559; demo2_media_worker.py:107; demo2_media_analysis.py:351',
  notes:'页面：上传工作台的本课程任务。截图中三个任务均为教学模拟数据，45%是模拟处理进度，不是一次新处理实测。真实前端renderTasks根据upload_status与analysis_status分开显示上传、排队、处理和证据就绪；worker从数据库领取任务，调用process_video_task，使用FFmpeg解码采样、提取音轨。成功输出时间证据，不能据此声明掌握度模型已完成。失败可查看处理任务中的具体原因。小练习：哪一条任务允许进入“确认画面中的学生”，为什么？'},
 {after:4,key:'identity-entry',title:'Demo 页面：人物确认与自动定位入口',chapter:1,image:manual,rect:[1030,404,312,419],layout:'portrait',
  points:[['你实际点击什么','选择采样帧，点“重新检测”\n或“手动画框”。'],['请求进入哪里','GET /api/v1/demo2/identity/detect\n→ _detect_identity_faces'],['返回什么','人脸候选框与检测分数；姓名仍由教师从名册确认。']],
  caption:'隔离测试中的真实界面：此处模拟检测不可用，保留手动画框入口。',
  source:'demo2_identity.py:245; scenario_lab_server.py:1637; demo2_face_detection.py:328',
  notes:'完整接口为GET /api/v1/demo2/identity/detect，带task_id、frame_key、frame_revision。路由先经frame_file检查权限、原片期限与版本，再调用_detect_identity_faces和detect_faces。界面源码在demo2_identity.py::render_identity。截图来自2026-09-11隔离测试，检测引擎被显式替换为不可用，展示的是实际失败分支，不是YuNet在合成图形上的准确率测试。小练习：模型返回一个框后，为什么还要选择姓名并确认？'},
 {after:18,key:'tracking-entry',title:'Demo 页面：确认记录与短时跟随入口',chapter:2,image:manual,rect:[24,1158,1318,310],layout:'wide',
  caption:'先保存当前帧的身份确认，再从这条记录点击“查看后续5秒”。',
  source:'demo2_identity.py:245; scenario_lab_server.py:1654; demo2_identity_store.py:645',
  notes:'页面：人物确认页底部身份确认记录。此截图证明按钮和已保存的当前帧记录存在，不证明跟踪结果成功。真实POST /api/v1/demo2/identity/track先调用tracking_seed核对授权与初始绑定，再调用demo2_roi_tracking.py::track_frames。输入是已确认初始框与最多6张采样图；输出约5秒位置建议和失败原因。Shi–Tomasi挑选角点，金字塔LK估计位移，跟丢即停止，不自动搜索另一人接续，不自动写入新姓名。小练习：如果初始框的人离开画面，应停止还是改跟旁边的人？'},
 {before:29,key:'versions',title:'Demo 页面：IEP 资料与版本',chapter:3,image:dossier+'student_documents.png',rect:[80,657,590,475],secondRect:[80,1138,590,467],layout:'two-crops',
  points:[['页面操作','在“资料与版本”中查看版本1、版本2，按需录入新版本。'],['数据库含义','每次更新新增document_id，保留既有课堂引用。'],['能力边界','资料内容来自已获授权的记录；当前不由模型补写。']],
  caption:'虚构资料的隔离验收截图；版本更新与历史课堂引用分别保存。',
  source:'demo2_dossier.py:87; demo2_dossier_store.py:476; demo2_dossier_store.py:657',
  notes:'页面：/demo2/dossier?student_id=... 的资料与版本区域。create_document检查学生、授权、期限、类型、摘要与可选原件，新增版本；create_reference关联指定版本。截图包含虚构IEP版本1和2及“录入新版本”按钮，学生与资料均为fixture。左右截图分别放大同一页面的两个版本记录，未改变记录内容。失败包括授权失效、期限超范围和对象不属于当前账号。小练习：创建版本2以后，昨天的课堂是否应自动改用版本2？'},
 {after:32,key:'withdrawn',title:'Demo 页面：撤回后的访问状态',chapter:3,image:dossier+'authorization_withdrawn.png',rect:[80,588,1204,420],layout:'wide',
  caption:'已撤回的版本隐藏正文，新增资料暂停；已删除版本也不再提供内容。',
  source:'demo2_dossier_store.py:461; demo2_dossier_store.py:374; demo2_dossier_store.py:381',
  notes:'这是2026-09-11隔离测试中先删除版本2、再撤回授权之后的页面，所以版本1显示已撤回，版本2保持已删除，不能误述成撤回把版本2删除。withdraw_authorization撤回授权并停用关联资料，cleanup_expired处理清理，_require_available阻止访问。页面禁用只是可见反馈，后端对象级检查才控制下载与读取。历史引用保留失效状态，不应继续用于有效结论。小练习：只把下载按钮隐藏，是否足以阻止直接请求旧下载地址？'}
];
const replacements={
 18:{key:'manual',title:'Demo 页面：漏检后的手动画框',chapter:2,image:manual,rect:[24,280,1318,655],layout:'wide',caption:'左侧画框选人 → 右侧选择姓名 → 确认；绿色框表示当前帧已保存的确认。',source:'demo2_identity.py:245; demo2_identity_store.py:536',notes:'截图来自合成图像隔离测试，无真实人脸。使用当前已保存结果讲解手动画框的兜底路径：输入归一化bbox、角色、student_id、task_id与frame_revision，POST /api/v1/demo2/identity/bindings后保存一条binding。后端复核学校、对象权限、框范围、重叠冲突和版本。小练习：模型没有检测成功时，为什么人工确认仍可完成？'},
 29:{key:'reference',title:'Demo 页面：关联本次课堂的资料版本',chapter:3,image:dossier+'course_reference.png',rect:[80,368,1208,650],layout:'wide',caption:'选择已确认学生与具体资料版本，再保存课堂引用；已保存引用可以导出核对。',source:'demo2_dossier.py:132; demo2_dossier_store.py:657',notes:'页面：本次课堂关联学生资料。create_reference验证当前视频身份绑定、学生、资料授权与版本，保存课堂引用；reference_export再次检查有效性。截图是隔离测试中的虚构资料。引用JSON尚未自动进入新视频千字报告，保存引用不代表生成学生评估。小练习：为什么引用中必须存资料版本？'},
 30:{key:'authorization',title:'Demo 页面：登记资料授权',chapter:3,image:dossier+'student_authorization.png',rect:[714,522,580,617],layout:'portrait',points:[['先填写三项','授权依据、获准保存范围、授权有效期。'],['再核对并登记','声明必须覆盖这位学生、资料范围与教育支持用途。'],['服务端验证','save_authorization检查对象、期限与重复授权。']],caption:'隔离测试表单中的授权依据明确标注为虚构，不可作为真实授权证明。',source:'demo2_dossier.py:87; demo2_dossier_store.py:438',notes:'教师必须依据实际获准文件填写授权，页面勾选不等于法律证明。summary_only和original_and_summary是不同保存范围；本项目内测上限60天，15天内站内提示。输入为student_id、reference、storage_mode、valid_until、confirmed，保存加密授权元信息并返回状态。小练习：教师账号登录后，是否就自动获得保存所有学生IEP原件的授权？'},
 31:{key:'admin',title:'Demo 页面：公司后台可见的资料状态',chapter:3,image:dossier+'admin_dossiers.png',rect:[80,98,1210,625],layout:'wide',caption:'公司运维查看数量、期限和密文占用；学生资料正文由独立授权控制。',source:'demo2_dossier.py:148; demo2_dossier_store.py:698',notes:'页面：公司后台学生资料运行状态。admin_summary只返回统计与通道汇总，不能按管理员角色默认开放学生姓名、专业结论、授权依据正文和原件。截图中有效授权与可用版本均为0，反映隔离测试撤回/删除后的状态，不是实际学校统计。小练习：加密落盘是否可以替代接口授权检查？'}
};

function txt(s,value,x,y,w,h,size=24,color='#29394C',bold=false){
 const o=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
 o.text=value;o.text.style={typeface:FONT,fontSize:size,color,bold,autoFit:'none',verticalAlignment:'top',wrap:true};return o;
}
const p=await PresentationFile.importPptx(await FileBlob.load(SOURCE));
const originals=[...p.slides.items];
const provenance=[];
async function screen(s,d){
 const oldNotes=s.speakerNotes.text;
 s.shapes.deleteAll();s.background.fill='#FFFFFF';
 txt(s,d.title,64,40,1152,76,42,'#20334D',true);
 txt(s,chapters[d.chapter-1]+' · 实际界面 / 虚构数据',66,123,1140,34,19,colors[d.chapter-1]);
 const raw=await fs.readFile(d.image),[l,t,w,h]=d.rect;
 const cropped=await sharp(raw).extract({left:l,top:t,width:w,height:h}).png().toBuffer();
 let box=d.layout==='two-crops'?{x:64,y:173,w:550,h:438}:d.layout==='portrait'?{x:64,y:173,w:500,h:438}:d.layout==='side'?{x:64,y:173,w:800,h:438}:{x:64,y:167,w:1152,h:442};
 const k=Math.min(box.w/w,box.h/h);
 const frame={left:box.x+(box.w-w*k)/2,top:box.y+(box.h-h*k)/2,width:w*k,height:h*k};
 const existing=s.images.items[0];
 if(existing){existing.replace({blob:new Uint8Array(cropped),contentType:'image/png',alt:d.caption,fit:'contain'});existing.frame=frame;}
 else s.images.add({blob:new Uint8Array(cropped),contentType:'image/png',alt:d.caption,fit:'contain',position:frame});
 if(d.secondRect){const [ll,tt,ww,hh]=d.secondRect;const bytes=await sharp(raw).extract({left:ll,top:tt,width:ww,height:hh}).png().toBuffer();const scale=Math.min(550/ww,438/hh);s.images.add({blob:new Uint8Array(bytes),contentType:'image/png',alt:'同一页面的资料版本2局部',fit:'contain',position:{left:666+(550-ww*scale)/2,top:173+(438-hh*scale)/2,width:ww*scale,height:hh*scale}});}
 if(d.points&&['portrait','side'].includes(d.layout)){const x=d.layout==='portrait'?610:903,ww=1215-x;
  d.points.forEach((v,j)=>{const yy=179+j*141;txt(s,v[0],x,yy,ww,38,26,colors[d.chapter-1],true);txt(s,v[1],x,yy+41,ww,99,24);});
 }
 txt(s,d.caption,66,622,1144,49,22,'#43566F');
 txt(s,'源码：'+d.source,66,677,1090,25,16,'#63758A');
 txt(s,'00',1181,678,55,25,17,'#63758A');
 const digest=crypto.createHash('sha256').update(raw).digest('hex');
 const notes=[oldNotes&&oldNotes!=='[object Object]'?oldNotes:'',d.notes,modelScope,'实际源码：'+d.source.split('; ').map(n=>ROOT+'/src/rehab_affect/'+n).join('\n'),'截图来源：'+d.image,'SHA256：'+digest,'裁剪区域（原截图像素）：'+JSON.stringify(d.rect),'截图数据均为虚构或隔离fixture。截图证明界面与相应状态，不证明真实课堂模型准确率。','教学：每次先问学习者一个问题，依据本人回答纠错，不代答、不提前记为掌握。'].filter(Boolean).join('\n\n');
 s.speakerNotes.textFrame.setText(notes);
 provenance.push({key:d.key,slideId:s.id,image:d.image,sha256:digest,rect:d.rect,secondRect:d.secondRect,source:d.source,caption:d.caption});
 return s;
}
const desired=[];
for(let i=0;i<originals.length;i++){
 const n=i+1;
 for(const d of screenDefs.filter(x=>x.before===n))desired.push(await screen(p.slides.add(),d));
 if(replacements[n])await screen(originals[i],replacements[n]);
 desired.push(originals[i]);
 for(const d of screenDefs.filter(x=>x.after===n))desired.push(await screen(p.slides.add(),d));
}
desired.forEach((s,i)=>s.moveTo(i));
if(p.slides.items.map(s=>s.id).join(',')!==desired.map(s=>s.id).join(','))throw new Error('Slide ordering mismatch');
const map=[];
for(let i=0;i<p.slides.items.length;i++){
 const s=p.slides.items[i];const page=s.shapes.items.find(x=>x.position.left>1170&&x.position.top>665);
 if(!page)throw new Error('Missing slide number '+(i+1));page.text=String(i+1).padStart(2,'0');
 const record=provenance.find(x=>x.slideId===s.id);if(record)record.page=i+1;
 map.push({page:i+1,originalPage:originals.indexOf(s)>=0?originals.indexOf(s)+1:null,title:s.shapes.items[0].text.toString(),hasDemoScreenshot:!!record});
}
const sourceHash=crypto.createHash('sha256').update(await fs.readFile(SOURCE)).digest('hex');
const finalMap={sourceDeck:SOURCE,sourceSha256:sourceHash,outputDeck:FINAL,slides:42,newPages:6,screenshotPages:provenance.map(x=>x.page),assets:provenance,pageMap:map};
await fs.writeFile(DIR+'/SCREENSHOT_MANIFEST.json',JSON.stringify(finalMap,null,2));
const candidate=DIR+'/qa/candidate.pptx';
await (await PresentationFile.exportPptx(p)).save(candidate);
const {finalizePresentation}=await import(pathToFileURL(SKILL+'/container_tools/artifact_tool_utils.mjs').href);
const result=await finalizePresentation({workspaceDir:ROOT,candidatePath:candidate,finalPath:FINAL,pythonExecutable:PY,integrityValidatorPath:SKILL+'/container_tools/inspect_presentation_package_integrity.py',layoutValidatorPath:SKILL+'/container_tools/inspect_presentation_layout_geometry.py',layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit'],explicitTotalSlideCount:42,fontPolicy:{basis:'reference',families:[FONT],referencePath:SOURCE,referenceSha256:sourceHash},verifyArtifactToolImport:true,receiptPath:DIR+'/qa/validation_final.json'});
console.log(JSON.stringify(result));
const rendered=await PresentationFile.importPptx(await FileBlob.load(FINAL));
await fs.mkdir(DIR+'/qa/rendered',{recursive:true});
for(let i=0;i<rendered.slides.items.length;i++){
 const s=rendered.slides.items[i];const blob=await rendered.export({slide:s,format:'png',scale:1});
 await fs.writeFile(DIR+`/qa/rendered/slide-${String(i+1).padStart(2,'0')}.png`,new Uint8Array(await blob.arrayBuffer()));
 console.log('Rendered '+(i+1)+'/42');
}
const thumbs=[];for(let i=1;i<=42;i++)thumbs.push({input:await sharp(DIR+`/qa/rendered/slide-${String(i).padStart(2,'0')}.png`).resize(320,180).toBuffer(),left:((i-1)%4)*320,top:Math.floor((i-1)/4)*180});
await sharp({create:{width:1280,height:1980,channels:3,background:'#e6ecf3'}}).composite(thumbs).png().toFile(DIR+'/qa/final-montage.png');
console.log(JSON.stringify({final:FINAL,screenshotPages:finalMap.screenshotPages}));
