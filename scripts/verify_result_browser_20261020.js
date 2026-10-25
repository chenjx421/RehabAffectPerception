// Read-only checks on a freshly uploaded synthetic classroom task.
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const runtime = path.join(root, '.runtime');
const read = name => JSON.parse(fs.readFileSync(path.join(runtime, name), 'utf8').replace(/^\uFEFF/, ''));
const state = read('manager_share_state.json');
const source = read('browser_upload_acceptance_20261020/report.json');
const output = path.join(runtime, 'result_browser_acceptance_20261020');
fs.mkdirSync(output, { recursive: true });
const report = { task_id: source.task_id, checked_at: new Date().toISOString(), checks: [], errors: [], passed: false };
let browser, step = 'login';
function check(value, code) { if (!value) { const e = new Error(code); e.safeCode = code; throw e; } report.checks.push(code); }
(async () => {
  check(source.passed, 'source_upload_verified');
  const row = fs.readFileSync(path.join(runtime, 'demo2_pilot_accounts_20260908.md'), 'utf8')
    .split(/\r?\n/).map(line => line.split('|').map(s => s.trim())).find(row => row[2] === 't1');
  browser = await chromium.launch({ channel: 'msedge', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  const page = await context.newPage();
  page.setDefaultTimeout(60000);
  page.on('pageerror', e => report.errors.push({ step, type: e.name }));
  await page.goto(state.invite_url);
  await page.waitForURL(state.origin + '/demo2/login');
  await page.locator('#username').fill('t1'); await page.locator('#password').fill(row[3]);
  await page.locator('#loginButton').click(); await page.waitForURL(state.origin + '/demo2/school');
  step = 'results';
  const route = state.origin + '/demo2/analysis?task_id=' + source.task_id;
  await page.goto(route, { waitUntil: 'domcontentloaded' });
  await page.locator('#applicabilitySection').waitFor();
  const response = await context.request.get(state.origin + '/api/v1/demo2/course-analysis?task_id=' + source.task_id);
  const workspace = (await response.json()).workspace;
  check(response.status() === 200 && workspace.task_id === source.task_id && workspace.course_id === source.course_id, 'result_matches_uploaded_task');
  check(workspace.people.length === 0 && workspace.records.length === 0 && workspace.summary.scored === 0, 'synthetic_video_does_not_invent_pupil_scores');
  await page.locator('#video').evaluate(video => { video.muted = true; return video.play(); });
  await page.waitForFunction(() => document.getElementById('video').currentTime > 0.3);
  check(await page.locator('#video').evaluate(v => !v.error && v.videoWidth > 0), 'video_actual_playback');
  await page.locator('#video').evaluate(v => v.pause());
  for (const tab of ['group', 'person', 'review', 'report']) {
    await page.locator('#tab-' + tab).click();
    check(await page.locator('#' + tab).isVisible() && await page.locator('[role=tabpanel]:visible').count() === 1, 'tab_' + tab);
  }
  for (const [id, name] of [['downloadJson', 'report.json'], ['downloadHtml', 'report.html']]) {
    const pending = page.waitForEvent('download');
    await page.locator('#' + id).click();
    const download = await pending;
    const file = path.join(output, name); await download.saveAs(file);
    const text = fs.readFileSync(file, 'utf8');
    if (name.endsWith('.json')) {
      const record = JSON.parse(text);
      check(record.task_id === source.task_id && record.course_id === source.course_id, 'report_json_matches_task');
    } else check(/<!doctype html>/i.test(text) && text.includes('report-body') && text.length > 1000, 'report_html_downloaded');
  }
  await page.screenshot({ path: path.join(output, 'report.png'), fullPage: true });
  step = 'refresh';
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator('#applicabilitySection').waitFor();
  check((await (await context.request.get(state.origin + '/api/v1/demo2/upload/task?id=' + source.task_id)).json()).task.analysis_status === 'evidence_ready', 'result_persisted_after_refresh');
  check(report.errors.length === 0, 'no_script_errors');
  report.passed = true;
})().catch(error => { report.failure = { step, code: error.safeCode || 'browser_or_network_failure', type: error.name }; process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  fs.writeFileSync(path.join(output, 'acceptance.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
});
