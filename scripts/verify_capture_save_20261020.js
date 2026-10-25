// Exercise the recording page's save path with a synthetic Blob, not a real camera.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const runtime = path.join(root, '.runtime');
const state = JSON.parse(fs.readFileSync(path.join(runtime, 'manager_share_state.json'), 'utf8').replace(/^\uFEFF/, ''));
const fixture = path.join(runtime, 'upload_reliability_20261020/run_20261020_141329_f0654096/SYNTHETIC-six-seconds-transport.mp4');
const report = { checked_at: new Date().toISOString(), synthetic_only: true, real_camera_tested: false, passed: false, checks: [] };
let browser, step = 'login';
function check(value, code) { if (!value) { const e = new Error(code); e.safeCode = code; throw e; } report.checks.push(code); }
(async () => {
  const row = fs.readFileSync(path.join(runtime, 'demo2_pilot_accounts_20260908.md'), 'utf8')
    .split(/\r?\n/).map(line => line.split('|').map(s => s.trim())).find(row => row[2] === 't1');
  browser = await chromium.launch({ channel: 'msedge', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage(); page.setDefaultTimeout(60000);
  await page.goto(state.invite_url); await page.waitForURL(state.origin + '/demo2/login');
  await page.locator('#username').fill('t1'); await page.locator('#password').fill(row[3]);
  await page.locator('#loginButton').click(); await page.waitForURL(state.origin + '/demo2/school');
  step = 'synthetic_recording_blob';
  await page.goto(state.origin + '/demo2/capture');
  await page.evaluate(() => { const input = document.createElement('input'); input.type = 'file'; input.id = 'qaSyntheticFile'; document.body.append(input); });
  await page.locator('#qaSyntheticFile').setInputFiles(fixture);
  await page.evaluate(() => {
    blob = document.getElementById('qaSyntheticFile').files[0]; clipType = 'video/mp4';
    blobUrl = URL.createObjectURL(blob); document.getElementById('download').href = blobUrl;
    document.getElementById('download').download = 'SYNTHETIC-recording-save.mp4';
    document.getElementById('download').hidden = false; controls();
  });
  const course = 'SYNTHETIC-capture-save-' + Date.now();
  await page.locator('#courseId').fill(course); await page.locator('#courseName').fill('Synthetic recording save');
  await page.locator('#uploadConsent').check();
  let chunks = 0;
  await page.route('**/api/v1/demo2/upload/chunks?*', async route => {
    chunks++; if (chunks === 1) return route.abort('failed');
    await route.continue();
  });
  step = 'save';
  await page.locator('#upload').click();
  await page.waitForFunction(() => saved === true, null, { timeout: 300000 });
  report.task_id = await page.evaluate(() => task.task_id);
  const response = await context.request.get(state.origin + '/api/v1/demo2/upload/task?id=' + report.task_id);
  const data = (await response.json()).task;
  check(data.upload_status === 'completed' && data.total_chunks === 4, 'four_mib_chunks_saved');
  check(data.sha256 === crypto.createHash('sha256').update(fs.readFileSync(fixture)).digest('hex'), 'recording_source_hash_matches');
  check(chunks >= 5, 'recording_save_retry_recovered');
  const workspace = (await (await context.request.get(state.origin + '/api/v1/demo2/upload/workspace?course_id=' + course)).json()).workspace;
  check(workspace.tasks.length === 1, 'recording_save_no_duplicate_task');
  report.passed = true;
})().catch(error => { report.failure = { step, code: error.safeCode || 'browser_or_network_failure', type: error.name }; process.exitCode = 1; }).finally(async () => {
  if (browser) await browser.close();
  fs.writeFileSync(path.join(runtime, 'capture_save_acceptance_20261020.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
});
