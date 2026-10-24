// Internal, local-only live screenshots. Passwords are supplied only by environment.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { chromium } = require('playwright');
const sharp = require('sharp');
const ROOT = path.resolve(__dirname, '..');
const MEMBERSHIP = process.env.DEMO2_GUIDE_MEMBERSHIP === '1';
const OUT = path.join(ROOT, MEMBERSHIP ? 'output/playwright/demo2_membership_guide_20260909' : 'output/playwright/demo2_current_guide_20260909');
const BASE = 'http://127.0.0.1:8792';
const TASK = 'a5ded3bc97c54d949961b130e6f18ca2';
const COURSE = 'media-validation-20260908';
const viewport = { width: 1360, height: 880 };
const manifest = { created_at: new Date().toISOString(), base_url: BASE, viewport, device_scale_factor: 1.5, local_only: true, pages: [], errors: [], blocked_requests: [], capture_only_actions: [], tabs_expected: 17, tabs_captured: [] };
fs.mkdirSync(OUT, { recursive: true });
const saveManifest = () => fs.writeFileSync(path.join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 2));
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
let browser;

async function newPage(role) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1.5, locale: 'zh-CN', serviceWorkers: 'block', acceptDownloads: false });
  await context.route('**/*', async route => {
    const request = route.request(); const url = new URL(request.url());
    if (url.origin !== BASE) { manifest.blocked_requests.push({ method: request.method(), path: url.pathname, reason: 'external_request_blocked' }); return route.abort('blockedbyclient'); }
    if (request.method() === 'POST' && url.pathname === '/api/seewo_demo2/security_acceptance') {
      const payload = request.postDataJSON();
      manifest.capture_only_actions.push({ type: 'security_acceptance_route_fulfill', server_write: false, role });
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, acceptance: { acceptance_id: 'capture-only-not-persisted', allow_company_archive: false, course_id: payload.course_id } }) });
    }
    if (request.method() === 'POST' && url.pathname === '/api/seewo_demo2_reviews') {
      const payload=request.postDataJSON();
      manifest.capture_only_actions.push({type:'review_request_intercepted_no_write',server_write:false});
      return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ok:true,course_id:payload.course_id,reviews:payload.reviews})});
    }
    if (request.method() === 'POST' && url.pathname === '/api/seewo_demo2_long_report') {
      const payload=request.postDataJSON();
      if(payload.use_llm)throw new Error('LLM is forbidden in screenshot capture');
      const directory=path.join(ROOT,'outputs/seewo_demo2/reports');
      const candidates=fs.readdirSync(directory).filter(name=>name.startsWith(payload.course_id+'_')&&name.endsWith('.json')).sort().reverse();
      for(const name of candidates){
        const source=path.join(directory,name);const report=JSON.parse(fs.readFileSync(source,'utf8'));
        if(report.engine!=='evidence_template'||!Array.isArray(report.sections))continue;
        page._reportSource=source;
        manifest.capture_only_actions.push({type:'existing_report_replay',source_report_path:source,server_write:false,llm:false});
        return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(report)});
      }
      throw new Error('No existing local-rule report matches this course');
    }
    if (!['GET', 'HEAD'].includes(request.method()) && url.pathname !== '/api/v1/demo2/auth/login') {
      manifest.blocked_requests.push({ method: request.method(), path: url.pathname, reason: 'read_only_capture' });
      return route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ error: { message: '截图模式禁止写入' } }) });
    }
    return route.continue();
  });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  page._captureErrors = [];
  page.on('pageerror', error => page._captureErrors.push({ type: 'pageerror', message: error.message }));
  page.on('response', response => { if (response.status() >= 400) page._captureErrors.push({ type: 'http', status: response.status(), path: new URL(response.url()).pathname }); });
  return page;
}

async function goto(page, route) {
  await page.goto(BASE + route, { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => {});
  await page.evaluate(() => document.fonts.ready);
}

async function align(page, selector, offset = 100) {
  await page.locator(selector).first().waitFor({ state: 'visible' });
  await page.locator(selector).first().evaluate((node, margin) => window.scrollTo({ top: node.getBoundingClientRect().top + scrollY - margin, behavior: 'instant' }), offset);
  await pause(200);
}

async function shot(page, id, title, section, description, boundary, captureOnly = false) {
  await page.evaluate(() => Promise.all([...document.images].filter(image => image.offsetParent !== null).map(image => image.decode().catch(() => {}))));
  await pause(150);
  const filename = `${String(manifest.pages.length + 1).padStart(2, '0')}_${id}.png`;
  const destination = path.join(OUT, filename);
  const buffer = await page.screenshot({ path: destination, animations: 'disabled', fullPage: false });
  const image = sharp(buffer); const stats = await image.stats(); const metadata = await image.metadata();
  const ui = await page.evaluate(() => ({ scroll_y: scrollY, horizontal_overflow: document.documentElement.scrollWidth > innerWidth, broken_images: [...document.images].filter(image => image.offsetParent !== null && (!image.complete || !image.naturalWidth)).length, active_tab: document.querySelector('#resultTabs [aria-selected="true"]')?.dataset.tab || null }));
  const errors = page._captureErrors.splice(0);
  const notBlank = stats.channels.slice(0, 3).some(channel => channel.stdev > 8);
  if (!notBlank) errors.push({ type: 'blank_image' });
  if (ui.broken_images) errors.push({ type: 'broken_images', count: ui.broken_images });
  manifest.pages.push({ id, title, source_path: new URL(page.url()).pathname + new URL(page.url()).search, section, filename, png_path: destination, feature_description: description, actual_boundary: boundary, capture_only: captureOnly, errors, captured_at: new Date().toISOString(), width: metadata.width, height: metadata.height, not_blank: notBlank, sha256: crypto.createHash('sha256').update(buffer).digest('hex'), tab:ui.active_tab, existing_report_replay:!!page._reportSource&&id.startsWith('report_'), ...(id.startsWith('report_')?{source_report_path:page._reportSource}:{}), ...ui });
  saveManifest();
  console.log(`captured ${manifest.pages.length}: ${id}`);
}

async function login(page, username, password, role) {
  await goto(page, '/demo2/login');
  await page.locator(role === 'company_admin' ? '#adminRole' : '#userRole').click();
  await page.locator('#username').fill(username);
  await page.locator('#password').fill(password);
  await page.locator('#loginButton').click();
  await page.waitForURL(`**/demo2/${role === 'company_admin' ? 'admin' : 'school'}`);
}

const tabs = [
  ['profile', '一人一案', '查看当前学生的课堂证据与支持概览。'],
  ['tracking', '历史记录', '查看已有跨课记录与历史基线。'],
  ['profileImport', '资料导入', '查看资料分类、档案与支持信息填写入口；不提交。'],
  ['state', '状态时间线', '查看时间段、待复核项及状态筛选。'],
  ['interaction', '师生互动', '查看学生表现与教师支持的对应证据。'],
  ['evidence', '教师复核', '查看关键片段、提示等级与人工复核表单；不保存。'],
  ['teacher', '支持效果', '查看历史演示中的教师支持比较。'],
  ['mastery', '学习判断', '展示历史示例学习判断及待复核边界。'],
  ['specialSupport', '支持工具', '查看低刺激等待、提示与课堂辅助工具。'],
  ['action', '动作方案', '查看人审后的动作建议入口；不向设备发送。'],
  ['growth', '五域趋势', '查看已有示例的五域趋势。'],
  ['courseReport', '课程分析', '查看当前示例课程的汇总报告与打印入口。'],
  ['feedback', '深度报告', '查看约一千字报告入口、本地模板及可选LLM开关；不调用LLM。'],
  ['summary', '数据来源', '查看数据来源、课程资料与统计口径。'],
  ['json', '结构化数据', '查看当前历史示例的结构化JSON。'],
  ['videoUpload', '四路上传', '查看当前账号可访问通道与已有视频任务；不上传。'],
  ['storage', '数据存储', '查看存储、保存周期、到期提醒和已有文件；不修改策略。'],
];
const historicalBoundary = '历史固定课程示例，不是本轮真实上传任务的学生学习结论。首次课程授权仅截图context模拟，未保存授权或教师复核。';
manifest.planned_pages=[
  ...['login_user','login_admin','register','privacy','privacy_bottom','school','upload','upload_tasks','video_evidence','video_audio','video_window_detail','admin_top','admin_middle','admin_bottom'].map(id=>({id,tab:null})),
  ...Array.from({length:8},(_,index)=>({id:'entry_step_'+index,tab:null,capture_only:true})),
  ...['course_standards','historical_group','historical_portrait','analysis_navigation'].map(id=>({id,tab:null,capture_only:true})),
  ...tabs.map(([tab,title])=>({id:'tab_'+tab,title,tab,capture_only:true})),
  {id:'report_top',tab:'feedback',existing_report_replay:true,capture_only:true},
  {id:'report_bottom',tab:'feedback',existing_report_replay:true,capture_only:true},
];
saveManifest();

(async () => {
  if (!process.env.DEMO2_GUIDE_TEACHER_PASSWORD || !process.env.DEMO2_GUIDE_ADMIN_PASSWORD) throw new Error('Supply teacher/admin passwords using environment variables');
  browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await newPage('teacher');
  try {
    await goto(page, '/demo2/login');
    await shot(page, 'login_user', '用户登录', '入口', '教师或上传人员账号登录，提供密码显示与申请入口。', '未显示或截图密码；登录成功需真实后端验证。');
    await page.locator('#adminRole').click();
    await shot(page, 'login_admin', '管理员登录', '入口', '切换公司管理员登录身份。', '管理员入口不代表已通过角色验证。');
    await goto(page, '/demo2/register');
    if (MEMBERSHIP) await page.waitForFunction(() => document.getElementById('smsStatus')?.textContent.trim());
    await shot(page, 'register', MEMBERSHIP ? '手机号注册' : '会员开通申请', '入口', MEMBERSHIP ? '手机号、短信验证码和密码注册；进入会员开通流程。' : '填写联系人、学校和联系方式，申请开通账号。', '只展示实际表单与配置状态，不提交或发送短信。');
    if (MEMBERSHIP) {
      await align(page, '#registerButton', 650);
      await shot(page, 'register_bottom', '手机号注册·密码与协议', '入口', '查看密码确认、注册协议及前往会员开通的按钮。', '当前未接通短信，不填写真人手机号、不请求验证码、不创建账号。');
    }
    await goto(page, '/demo2/privacy');
    await shot(page, 'privacy', '数据安全与隐私说明·上', '入口', '阅读平台资料用途和授权边界。', '阅读或登录不等于上传授权。');
    await page.evaluate(() => scrollTo(0, document.documentElement.scrollHeight));
    await shot(page, 'privacy_bottom', '数据安全与隐私说明·下', '入口', '阅读保存、删除、注册申请和外部服务说明。', '说明文本是当前界面内容，不是本轮新增合规认证。');
    await login(page, 't1', process.env.DEMO2_GUIDE_TEACHER_PASSWORD, 'school_uploader');
    await page.locator('#schoolButton:not([disabled])').waitFor();
    await shot(page, 'school', '学校选择与账号归属', '教师工作台', '显示真实账号已有学校信息及城市区县选择。', '未保存或修改学校信息；后续直接访问工作台。');
    if (MEMBERSHIP) {
      await goto(page, '/demo2/membership');
      await page.waitForFunction(() => document.getElementById('membershipStatus')?.textContent.trim() && !['--','加载中'].includes(document.getElementById('membershipStatus').textContent.trim()));
      await shot(page, 'membership', '会员中心', '账号与会员', '查看账号会员状态、服务方案和支付配置状态。', '使用已有内测账号，只读展示；不代表该账号完成过真实购买。');
      await align(page, '#membershipOrders', 260);
      await shot(page, 'membership_orders', '会员订单记录', '账号与会员', '查看当前账号订单记录与支付开放状态。', '未创建订单、未发起扣费；没有订单则如实为空。');
    }
    await goto(page, '/demo2/upload?course_id=' + COURSE);
    await page.waitForFunction(() => document.getElementById('taskList')?.textContent.includes('a5ded3bc'));
    await shot(page, 'upload', '真实课程上传工作台', '教师工作台', '账号通道、课程批次、上传名额、文件选择和授权设置。', '加载现有完成任务，不上传新文件或创建任务。');
    await align(page, '.task-section');
    await shot(page, 'upload_tasks', '真实课程任务与结果入口', '教师工作台', '查看真实完成任务、处理状态与视频证据入口。', '上传完成与证据就绪分开显示。');
    await goto(page, '/demo2/video?id=' + TASK);
    await page.waitForFunction(() => document.getElementById('stageLabel')?.textContent.includes('证据已就绪'));
    await page.waitForFunction(() => document.getElementById('classVideo')?.readyState >= 2);
    await page.locator('#seekSlider').fill('600');
    await page.waitForFunction(() => {const v=document.getElementById('classVideo');return v.currentTime>=599 && !v.seeking && v.readyState>=2;});
    await shot(page, 'video_evidence', '真实录像处理与回放', '视频证据', '显示真实录像、处理进度、切片和画面技术记录。', '亮度、清晰度和运动值不是注意力或学习成绩。');
    await page.locator('#audioPlayer').evaluate(audio => { audio.preload='metadata'; audio.load(); });
    await page.waitForFunction(() => document.getElementById('audioPlayer').readyState >= 1, null, {timeout:30000});
    await page.locator('#audioPlayer').evaluate(audio => {audio.currentTime=600;audio.pause();});
    await align(page, '.timeline-section', 140);
    await shot(page, 'video_audio', '时间切片与同期音轨', '视频证据', '真实视频10分钟附近的切片、同期音轨与当前片段记录。', '音轨已加载并定位但未自动播放；无语音识别或学生结论承诺。');
    await align(page, '.evidence-pane', 130);
    await shot(page, 'video_window_detail', '当前时间窗口技术证据', '视频证据', '当前窗口的采样、画面质量、变化幅度、音轨与能量记录。', '技术指标仅供回看定位，仍待教师复核。');

    const admin = await newPage('admin');
    await login(admin, 'admin', process.env.DEMO2_GUIDE_ADMIN_PASSWORD, 'company_admin');
    await admin.waitForFunction(() => document.getElementById('taskCount')?.textContent !== '--');
    await shot(admin, 'admin_top', '公司后台·账号与通道', '公司后台', '查看真实账号、通道、任务与存储总览。', '仅截图接口返回数据，不调整账号或系统配置。');
    if (MEMBERSHIP) {
      await admin.waitForFunction(() => document.getElementById('membershipSummary')?.textContent.trim());
      await align(admin, '#membershipSummary', 150);
      await shot(admin, 'admin_membership', '公司后台·会员账户', '公司后台', '查看手机号会员账户与短信、支付服务状态。', '真实接口只读汇总，不创建会员，不展示验证码和完整手机号。');
      await align(admin, '#membershipOrdersSummary', 260);
      await shot(admin, 'admin_orders', '公司后台·会员订单', '公司后台', '查看独立于上传账号的会员订单记录。', '无真实支付时不展示虚构成交或收入。');
    }
    await align(admin, 'section[aria-labelledby="quotaTitle"]');
    await shot(admin, 'admin_middle', '公司后台·课程名额与保存策略', '公司后台', '查看每课程名额、任务状态、保存周期和到期提醒。', '不修改保存策略或删除文件。');
    await align(admin, 'section[aria-labelledby="recentTitle"]');
    await shot(admin, 'admin_bottom', '公司后台·授权与近期上传', '公司后台', '查看授权记录、近期真实视频任务与证据链接。', '账号及任务数据仅用于内部介绍。');
    await admin.context().close();

    await goto(page, '/demo2/analysis');
    await page.locator('#entryGate').waitFor({state:'visible'});
    const gateTitles = ['安全与课程准备','选择课程','课程类型','课程名称','课程标准','教案要求','校方考核标准','最终课程确认'];
    for (let step=0; step<8; step++) {
      await shot(page, `entry_step_${step}`, gateTitles[step], '历史分析·首次确认', '当前首次课程配置流程的第'+(step+1)+'步。', '本次操作仅截图演示；不提交真实授权记录。', true);
      if (step < 7) await page.locator('#entryNextButton').click();
    }
    await page.locator('#entryConfirmed').check();
    await page.locator('#enterDemoButton').click();
    await page.locator('#entryGate').waitFor({state:'hidden'});
    await page.locator('#courseSetup > summary').click();
    await align(page, '#courseSetup');
    await shot(page, 'course_standards', '课程基线与评价口径', '历史分析·工作区', '展开查看课程类型、课程标准与校方考核口径。', historicalBoundary, true);
    await page.locator('#courseSetup > summary').click();
    await align(page, '#workbench');
    await shot(page, 'historical_group', '历史课程群像模式', '历史分析·工作区', '查看既有示例的座位关系、群像与学生切换入口。', historicalBoundary, true);
    await page.locator('#portraitMode').click();
    await shot(page, 'historical_portrait', '历史课程个体模式', '历史分析·工作区', '切换同一既有示例的个体画面。', historicalBoundary, true);
    await page.locator('#groupMode').click();
    await align(page, '.analysis-studio');
    await shot(page, 'analysis_navigation', '分析功能导航与学生选择', '历史分析·工作区', '展示当前17项功能分组、学生选择和当前页定位。', historicalBoundary, true);
    for (const [tab,title,description] of tabs) {
      await page.locator(`[data-tab="${tab}"]`).click();
      await pause(500);
      await align(page, '.analysis-layout');
      await shot(page, 'tab_'+tab, title, '历史分析·17功能', description, historicalBoundary, true);
      manifest.tabs_captured.push(tab);saveManifest();
      if (['evidence','profileImport','courseReport','summary','videoUpload','storage'].includes(tab)) {
        const box = await page.locator('#tabBody').boundingBox();
        await page.evaluate(bottom => scrollTo({top:bottom-innerHeight+40,behavior:'instant'}), box.y+box.height+await page.evaluate(()=>scrollY));
        await shot(page, 'tab_'+tab+'_bottom', title+'·下半区', '历史分析·补充', description+' 展示页面末段。', historicalBoundary, true);
      }
    }
    await page.locator('[data-tab="feedback"]').click();
    await page.locator('#generateReport').click();
    await page.locator('#copyReport').waitFor({state:'visible'});
    await align(page,'.report-toolbar');
    await shot(page,'report_top','深度报告正文·开头','历史分析·报告','在当前真实界面中回放磁盘已有本地规则报告，展示章节和正文。',historicalBoundary+' 报告为已有JSON只读回放，不是本轮生成；未提交教师复核、未写服务端、未调用LLM。',true);
    const lastSection=page.locator('.report-section').last();
    await lastSection.evaluate(node=>scrollTo({top:node.getBoundingClientRect().top+scrollY-250,behavior:'instant'}));
    await shot(page,'report_bottom','深度报告正文·末段','历史分析·报告','显示已有本地规则报告末段与下一课建议，便于完整阅读。',historicalBoundary+' existing_report_replay：只读回放已有报告，不是本轮生成。',true);
    manifest.report_generation = { performed:false,existing_report_replay:true,capture_only:true,source_report_path:page._reportSource };
    manifest.tabs_complete = manifest.tabs_captured.length===17;
  } catch(error) {
    manifest.errors.push({type:'capture_failure',message:error.message,stack:error.stack});process.exitCode=1;
  } finally {
    if(browser)await browser.close();
    manifest.completed_at=new Date().toISOString();manifest.total=manifest.pages.length;
    saveManifest();console.log(JSON.stringify({screenshots:manifest.total,tabs:manifest.tabs_captured.length,errors:manifest.errors,output:OUT}));
  }
})().catch(error => {manifest.errors.push({message:error.message});saveManifest();console.error(error.message);process.exitCode=1;});
