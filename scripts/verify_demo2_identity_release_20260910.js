// Read-only feature verification through the existing private invitation gateway.
// Authentication creates sessions; no student, binding, upload or report is created.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const state = JSON.parse(fs.readFileSync(path.join(root, '.runtime/manager_share_state.json'), 'utf8').replace(/^\uFEFF/, ''));
const localUrl = process.env.REHAB_VERIFY_LOCAL_URL || '';
if (localUrl) {
  const local = new URL(localUrl);
  assert.ok(local.protocol === 'http:' && local.hostname === '127.0.0.1', 'Local verification must stay on loopback');
}
const origin = new URL(localUrl || state.origin).origin;
const entryUrl = localUrl ? origin + '/demo2/login' : state.invite_url;
const taskId = process.env.REHAB_VERIFY_TASK_ID || 'a5ded3bc97c54d949961b130e6f18ca2';
assert.match(taskId, /^[A-Za-z0-9_-]{1,128}$/);
const output = path.join(root, 'output/playwright/identity_release_20260910');
fs.mkdirSync(output, { recursive: true });
const report = { origin, checked_at: new Date().toISOString(), task_id: taskId, checks: [], page_errors: [], live_data_written: false, local_only: !!localUrl };
const check = (name, value) => { assert.ok(value, name); report.checks.push({ name, passed: true }); };
const capture = async (page, filename) => {
  await page.evaluate(() => {
    document.activeElement?.blur();
    window.scrollTo({ top: 0, behavior: 'instant' });
  });
  await page.waitForFunction(() => window.scrollY === 0);
  await page.screenshot({ path: path.join(output, filename), fullPage: true });
};

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    for (const user of [
      { name: 't1', password: process.env.REHAB_TEACHER_PASSWORD, admin: false },
      { name: 'admin', password: process.env.REHAB_ADMIN_PASSWORD, admin: true },
    ]) {
      assert.ok(user.password, 'Supply pilot passwords through environment');
      const context = await browser.newContext({ viewport: { width: 1440, height: 1080 } });
      const page = await context.newPage();
      page.setDefaultTimeout(30000);
      page.on('pageerror', error => report.page_errors.push(error.name));
      try {
        await page.goto(entryUrl, { waitUntil: 'domcontentloaded', timeout: 90000 });
        await page.waitForURL(origin + '/demo2/login');
        if (user.admin) await page.locator('#adminRole').click();
        await page.locator('#username').fill(user.name);
        await page.locator('#password').fill(user.password);
        await page.locator('#loginButton').click();
        await page.waitForURL(origin + (user.admin ? '/demo2/admin' : '/demo2/school'));

        const response = await context.request.get(origin + '/api/v1/demo2/identity/workspace?task_id=' + taskId);
        check(user.name + ' identity workspace', response.status() === 200);
        const workspace = (await response.json()).workspace;
        check(user.name + ' real frame manifest', workspace.task_id === taskId && workspace.frames.length > 0 && workspace.media_available === true);
        check(user.name + ' explicit scope boundaries', workspace.summary.identity_scope === 'single_sample_frame' && workspace.summary.tracking_performed === false);
        check(user.name + ' correct editing permissions', workspace.can_edit === (!user.admin && !!workspace.scope_key && workspace.media_available) && workspace.can_revoke === !user.admin);
        if (!workspace.scope_key && !user.admin) {
          check('legacy school attribution requires teacher confirmation', workspace.needs_school_confirmation === true && workspace.can_confirm_school === true);
        }
        const frame = await context.request.get(origin + workspace.frames[0].image_url);
        check(user.name + ' protected real frame readable', frame.status() === 200 && frame.headers()['content-type'].startsWith('image/'));
        check(user.name + ' frame not public-cached', frame.headers()['cache-control'].includes('no-store'));
        const exported = await context.request.get(origin + '/api/v1/demo2/identity/export?task_id=' + taskId);
        check(user.name + ' binding export', exported.status() === 200 && exported.headers()['content-disposition'].includes('attachment'));

        if (!user.admin) {
          const rosterResponse = await context.request.get(origin + '/api/v1/demo2/identity/roster');
          check('teacher own roster', rosterResponse.status() === 200 && Array.isArray((await rosterResponse.json()).roster.students));
          await page.goto(origin + '/demo2/students', { waitUntil: 'domcontentloaded' });
          await page.waitForFunction(() => !document.getElementById('rosterCount').textContent.includes('正在读取'));
          await capture(page, 'student_roster.png');
        }

        const detected = !user.admin ? page.waitForResponse(r => r.url().includes('/identity/detect?'), { timeout: 40000 }) : null;
        await page.goto(origin + '/demo2/identity?task_id=' + taskId, { waitUntil: 'domcontentloaded' });
        await page.waitForFunction(() => {
          const image = document.getElementById('frameImage');
          return image && image.naturalWidth > 0 && !document.getElementById('frameSurface').hidden;
        });
        if (detected) {
          const result = await detected;
          check('real detector route', result.status() === 200);
          const body = (await result.json()).detection;
          check('local detector operational', body.available === true && Array.isArray(body.faces));
          report.first_frame_face_candidates = body.faces.length;
          report.detection_is_not_identity_matching = true;
          await page.waitForFunction(() => !document.getElementById('detectionStatus').textContent.includes('正在'));
          // This is a position-only demonstration, not an accuracy benchmark.
          // Keep the source task untouched and respect the endpoint rate limit.
          await page.waitForTimeout(2200);
          await page.locator('#jumpTime').fill('1200');
          const laterDetection = page.waitForResponse(r => r.url().includes('/identity/detect?'), { timeout: 30000 });
          await page.locator('#jumpFrame').click();
          const later = await laterDetection;
          check('later sampled frame detection', later.status() === 200);
          const laterBody = (await later.json()).detection;
          check('later local detector operational', laterBody.available === true);
          report.sample_1200_sec_candidates = laterBody.faces.length;
          await page.waitForFunction(() => !document.getElementById('detectionStatus').textContent.includes('正在'));
        }
        check(user.name + ' identity UI rendered', await page.locator('#bindingList').count() === 1);
        await capture(page, user.admin ? 'identity_admin.png' : 'identity_teacher.png');
        if (!user.admin) {
          await page.setViewportSize({ width: 390, height: 844 });
          check('mobile has no horizontal overflow', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
          await capture(page, 'identity_mobile.png');
        }
        const logout = await context.request.post(origin + '/api/v1/demo2/auth/logout', { data: {}, headers: { Origin: origin } });
        check(user.name + ' logout', logout.status() === 200);
      } finally { await context.close(); }
    }
    check('no JavaScript errors', report.page_errors.length === 0);
    fs.writeFileSync(path.join(output, 'verification.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
  } finally { await browser.close(); }
})().catch(error => {
  console.error(String(error.message || error).replaceAll(state.invite_url, origin + '/invite#[redacted]'));
  process.exitCode = 1;
});
