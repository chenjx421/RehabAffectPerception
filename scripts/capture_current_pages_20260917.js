const fs=require('fs'),path=require('path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
const sharp=require('sharp');
const config=JSON.parse(fs.readFileSync(0,'utf8'));
const manifest={date:'2026-09-17',synthetic:true,api_mocked:false,pages:[],errors:[],checks:[]};
async function main(){
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try{
    const ctx=await browser.newContext({viewport:{width:1440,height:1000},deviceScaleFactor:1.5,locale:'zh-CN'});
    await ctx.route('**/*',route=>new URL(route.request().url()).origin===config.base?route.continue():route.abort());
    const page=await ctx.newPage();page.setDefaultTimeout(12000);
    page.on('pageerror',e=>manifest.errors.push({page:new URL(page.url()).pathname,error:e.message}));
    async function role(name){await ctx.clearCookies();if(name)await ctx.addCookies([{name:'rehab_demo2_session',value:config.tokens[name],url:config.base}]);}
    async function go(url){await page.goto(config.base+url,{waitUntil:'networkidle'});await page.evaluate(()=>document.fonts.ready);}
    async function align(selector){await page.locator(selector).first().evaluate(el=>window.scrollTo(0,el.getBoundingClientRect().top+scrollY-90));}
    async function shot(id,title,section,description,boundary,change='现有功能',selector){
      await page.waitForTimeout(120);
      const file=id+'.png';
      const buffer=selector?await page.locator(selector).screenshot({path:path.join(config.output,file),animations:'disabled'}):await page.screenshot({path:path.join(config.output,file),animations:'disabled'});
      const info=await sharp(buffer).metadata(),stats=await sharp(buffer).stats();assert(stats.channels.some(c=>c.stdev>8),'blank '+id);
      const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
      manifest.pages.push({id,title,section,description,boundary,change,file,width:info.width,height:info.height,overflow,path:new URL(page.url()).pathname});
      fs.writeFileSync(path.join(config.output,'manifest.json'),JSON.stringify(manifest,null,2));console.log('captured '+id);
    }
    await role(null);await go('/demo2/login');
    await shot('01_login','用户登录','账号与入口','学校上传人员通过账号密码登录；登录身份由服务端校验。','截图不包含密码；本地访问不等于已有公网部署。');
    await page.locator('#adminRole').click();
    await shot('02_login_admin','管理员登录','账号与入口','管理员入口进入公司后台，权限与学校账号分开。','选择管理员选项不能自行获得管理员权限。');
    await go('/demo2/register');
    await shot('03_register','手机号注册','账号与入口','提供手机号、短信验证码、密码和协议确认表单。','当前短信服务未配置；页面存在不代表可以真实注册或付费。');
    await go('/demo2/privacy');
    await shot('04_privacy','数据安全与隐私说明','账号与入口','说明视频、学生资料、账号信息的用途与保存边界。','阅读协议不替代具体上传授权，IEP资料需单独授权。');
    await page.evaluate(()=>scrollTo(0,document.documentElement.scrollHeight));
    await shot('05_privacy_retention','数据期限与删除说明','账号与入口','展示数据保留、访问、删除和外部服务的说明。','媒体、敏感档案和结构化测量不是同一类数据，不能笼统承诺全部60天删除。');
    await role('teacher');await go('/demo2/school');
    await shot('06_school','学校归属','教师工作台','填写城市、区县和学校，作为账号工作区归属。','展示虚构学校；已有任务保留上传时学校快照，不随改名自动迁移。');
    await go('/demo2/membership');
    await shot('07_membership','会员中心与订单','账号与入口','查看当前账号会员状态、拟定套餐与订单。','支付与正式价格未配置；会员身份不自动授予学校学生资料权限。');
    await go('/demo2/upload?course_id=synthetic-guide');
    await shot('08_upload','课程上传与名额','教师工作台','选择课程批次和视频，查看所属通道、已用名额与剩余名额；上传前确认授权。','四个账号分别绑定通道，管理员可调整每课程名额；此页不自动从希沃抓取数据。');
    await align('#taskTitle');
    await shot('09_upload_tasks','上传任务与结果入口','教师工作台','查看上传、处理状态及视频结果入口，区分上传成功与分析就绪。','本册任务为真实解码的6秒合成视频，不代表实际课堂分析效果。');
    await go('/demo2/capture');
    await shot('10_capture','课堂录制','教师工作台','提供摄像头与麦克风预览、录制、回放、下载及保存入口。','本轮未请求真实摄像头或麦克风权限；实际录制依赖浏览器权限与安全访问环境。');
    await go('/demo2/students');
    await shot('11_students','本校学生名册','学生与视频','姓名、校内编号、班级与备注建立学生记录；同名通过编号区分。','新建名册不会自动识别人脸，不包含真实姓名或诊断。');
    await go('/demo2/video?id='+config.task_id);
    await page.waitForFunction(()=>document.querySelector('#classVideo')?.readyState>=2);
    await shot('12_video','视频回放与处理结果','学生与视频','查看原片、处理状态、身份确认摘要，并进入画面绑定和资料引用。','画面为合成图形，视频和音轨经真实处理；场景变化指标不等于注意力。');
    await align('.timeline-section');
    await shot('13_segments','时间切片与同期音轨','学生与视频','按时间窗口回看画面与音轨，查看采样、画面质量及声音能量。','本例声音为合成测试音，不是教师语音；当前未完成说话人识别或自动学习判断。');
    await go('/demo2/identity?task_id='+config.task_id);
    await page.waitForFunction(()=>document.querySelector('#frameImage')?.naturalWidth>0);
    await shot('14_identity','逐帧身份确认与手动画框','学生与视频','将画面位置与本校名册关联；自动候选不可用时可手动画框，区分学生、教师与未知人物。','本册采用人工框选的合成图形。确认仅对应具体采样帧，后续位置建议需要再次核对。');
    await go('/demo2/dossier?student_id='+config.student_id);
    await shot('15_authorization','学生资料授权与期限','学生档案','登记授权依据、允许保存范围与有效期，支持只保留摘要或同时保存原件。','本册授权是隔离测试记录；实际授权不可由系统代签，内测期限最多60天。');
    await page.locator('#tabDocuments').click();
    await shot('16_documents','IEP与专业资料导入','学生档案','支持IEP、专业评估、五领域评估和安全支持资料；记录来源、摘要、日期与版本。','原件加密存储；专业结论只能摘录已有资料，不能自动诊断。');
    await page.locator('#tabReferences').click();
    await shot('17_reference_history','学生资料引用历史','学生档案','查看某个资料版本被哪次课堂引用，保留历史依据。','资料更新不自动覆盖旧课堂引用；到期或撤回后需重新核验可用性。');
    await go('/demo2/course-dossier?task_id='+config.task_id);
    await shot('18_course_dossier','课堂关联学生资料','学生档案','从当前已确认学生中选择具体资料版本，保存课程引用记录。','绑定资料不是生成掌握度或自动学习报告，仍需教师解释课堂证据。');
    await go('/demo2/measurement');
    await page.locator('.student-item').first().waitFor();await page.locator('.student-item').first().click();
    for(const [tab,id,title,desc,bound] of [
      ['overview','19_measure_overview','学生测量总览','查看所选学生的逐课观察记录、复核状态与汇总。','仅展示教师录入的合成测量，不是视频自动推断。'],
      ['form','20_measure_form','教师观察与复核录入','按准确性、独立性、一致性、泛化性记录分数、机会数、目标与支持条件。','没有观察或缺少证据时保留缺失；教师复核不能被模型代替。'],
      ['trends','21_measure_trends','纵向趋势','展示每次课、每周、每月与滚动窗口结果，保留缺失和未复核状态。','合成趋势仅演示图表，不能用于证明真实学生进步；比较前需确认目标和条件一致。'],
      ['report','22_measure_report','单次测量报告','显示单次目标、四维结果、证据与复核状态，并提供报告操作。','此报告不等同于旧版自动千字报告，当前没有接通DeepSeek。'],
      ['standard','23_measure_standard','学生测量评分标准','公开四维评分含义、权重、观察条件与有效记录规则。','学生表现评分与教师课堂质量评分分开，不将能力差异直接扣给教师。'],
    ]){await page.locator(`[data-tab="${tab}"]`).click();await page.evaluate(()=>scrollTo(0,0));await shot(id,title,'学生测量',desc,bound);}
    await go('/demo2/evaluation');
    await page.waitForFunction(()=>document.querySelectorAll('#fTemplate option').length>1);
    await page.locator('#fLessonId').fill('guide-class');await page.locator('#fLessonDate').fill('2026-09-16');
    await page.locator('#fCourseName').fill('合成演示 · 生活数学课堂');await page.locator('#fSubject').selectOption('math');
    await page.locator('#fTemplate').selectOption('basic_100');await page.locator('#fWeightPolicy').selectOption('subject_trial');
    await page.locator('#domainChoices input[value=cognition]').check();
    await page.locator('#fGoalContext').fill('合成课堂：以实物与图卡支持分类，允许指认和辅助表达。按约定提示条件核对表现。');
    await page.locator('#fSchoolRater').fill('演示复核员');
    await page.evaluate(()=>scrollTo(0,0));
    await shot('24_evaluation_setup','课程口径与学科目标权重','双轨评价','选择学校模板、学科、本课目标与重点支持领域；增强轨按公开公式计算权重，学校轨不变。','学科及五领域映射为试行设计，未自动读取IEP，尚未进行真实数据校准。','本次新增');
    const scores=[8,8,8,8,8,9,6,6,8,9];
    for(let n=1;n<=10;n++){
      await page.locator(`[name=school_i${n}]`).fill('8');await page.locator(`[name=enhanced_i${n}]`).fill(String(scores[n-1]));
      await page.locator(`[name=evidence_i${n}]`).fill('合成片段与教案记录：核对学习机会、允许的表达方式和提示条件。');
      if(scores[n-1]!==8){await page.locator(`[name=reason_i${n}]`).fill(n===7?'少数学生重复回应，不能代表全体都有独立机会。':n===8?'示范后正确完成与约定条件下独立完成需区分。':'复核补充了可及性支持或教师调整的证据。');await page.locator(`[name=suggestion_i${n}]`).fill('下一课记录每名学生的回应机会与提示程度，保留调整前后证据。');}
    }
    await page.locator('#anchorList').evaluate(el=>el.parentElement.open=true);await align('#anchorList');
    await shot('25_anchors','逐项录入与评分锚点','双轨评价','公开0、2、4、6、8、10分的通用判定含义，缺失不按0分处理。','仍需教师逐项录分，通用锚点不能替代校方具体行为标准。','本次新增');
    await page.locator('#fReviewed').check();await page.locator('#saveBtn').click();
    await page.waitForFunction(()=>!document.querySelector('#exportJsonBtn').disabled);
    await page.evaluate(()=>scrollTo(0,0));
    await shot('26_school_score','学校标准评分','双轨评价','保留100分原表、折算10分、70分制教学得分及原表分类图。','6分仅为项目参考线，不冒充校方正式合格认证；截图为合成评分。','本次调整');
    await page.locator('#tabEnhanced').click();
    await shot('27_enhanced_score','系统增强评分','双轨评价','展示增强总分、候选权重、分类图与差异理由，支持与学校轨切换。','分差并不证明系统优于教师，当前两轨分数均以人工录入证据为输入。','本次调整');
    await page.locator('#policyDetails details').evaluate(el=>el.open=true);await align('#policyDetails');
    await shot('28_weight_formula','学科与目标领域的逐项权重','双轨评价','显示基础权重、调整倍率、最终权重与计算公式；保存后锁定配置，保留规则版本。','学科与领域各最多增加10%的基础倍率，再归一化；幅度不是文献推导值。','本次新增');
    await align('#sensitivityDetails');
    await shot('29_sensitivity','敏感性检查与改进建议','双轨评价','小幅扰动分类权重，显示分数范围和是否跨越6分线；下方按项目列出证据与建议。','范围不是置信区间；建议当前由教师录入，DeepSeek解释助手尚未接通。','本次新增');
    await page.locator('#tabCompare').click();await page.evaluate(()=>scrollTo(0,0));
    await shot('30_compare','双轨分差分解','双轨评价','分别计算证据差、权重差及总差，逐项关联理由、证据和建议。','采用先复核证据再调权重的固定分解顺序，属于数值归因，不是因果证明。','本次调整');
    await page.locator('#tabRefs').click();await page.evaluate(()=>scrollTo(0,0));
    await shot('31_references','文献支持与局限','双轨评价','提供教育质量评价政策、反馈研究、目标达成方法与UDL指导的来源链接。','这些来源支持评价方向，不直接验证本项目权重或评分准确率。','本次调整');
    const downloaded=page.waitForEvent('download');await page.locator('#exportJsonBtn').click();
    const download=await downloaded;const saved=JSON.parse(fs.readFileSync(await download.path(),'utf8'));
    assert.equal(saved.weight_policy,'subject_trial');assert.deepEqual(saved.focus_domains,['cognition']);
    assert.equal(saved.result.school.score_10,8);assert(saved.result.sensitivity.available);
    await page.reload();await page.locator('#resultCard').waitFor({state:'visible'});
    await page.locator('#editRecordBtn').click();assert(await page.locator('#fWeightPolicy').isDisabled());
    manifest.checks.push('学科方案真实保存、导出、刷新恢复、配置锁定通过');
    for(const width of [390,320]){await page.setViewportSize({width,height:844});await page.evaluate(()=>scrollTo(0,0));assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);}
    manifest.checks.push('新增表单390与320宽度无整页横向溢出');await page.setViewportSize({width:1440,height:1000});
    await go('/demo2/analysis');
    await shot('32_legacy_boundary','历史分析入口的当前状态','兼容与边界','历史固定课堂、群像、个体分析与千字报告入口当前转为资料核对提示。','本册不将旧版页面冒充已在当前独立账号流程中重新打通的功能。','待整合');
    await role('admin');await go('/demo2/admin');
    await shot('33_admin','公司后台总览','公司后台','汇总账号、上传通道、任务数量和存储情况，并提供管理入口。','管理员汇总权限不等于学校教师的档案正文访问权限。');
    await align('#membershipSummary');
    await shot('34_admin_membership','会员与订单管理','公司后台','展示会员账号及订单记录，与学校内测账号分开管理。','本册会员为虚构测试账号；短信和支付未接通，不表示已有真实交易。');
    await align('#retentionTitle');
    await shot('35_admin_retention','存储、到期与授权留痕','公司后台','汇总上传状态、保留期限、到期提醒和安全授权记录。','原媒体保留与结构化记录保留需分别治理；公司长期保存不是默认授权。');
    await go('/demo2/admin/channels');
    await shot('36_channels','四路上传通道管理','公司后台','管理通道名称、归属显示、开放状态与每课程3至5个上传名额。','截图未修改生产通道；暂停上传不代表删除既有任务。');
    await go('/demo2/admin/dossiers');
    await shot('37_admin_dossiers','学生资料运行状态','公司后台','查看资料数量、加密存储占用、授权与清理状态。','后台不展示学生姓名、诊断原件或IEP正文。');
    await go('/demo2/admin/measurements');
    await shot('38_admin_measurements','测量记录汇总','公司后台','按通道汇总教师测量与复核记录数量。','不在管理员汇总页开放学生个人测量正文。');
    assert.deepEqual(manifest.errors,[]);
  }finally{await browser.close();fs.writeFileSync(path.join(config.output,'manifest.json'),JSON.stringify(manifest,null,2));}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
