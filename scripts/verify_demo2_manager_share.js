// Verify the private remote entry without logging invitation secrets or student data.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const root = path.resolve(__dirname, '..');
const state = JSON.parse(fs.readFileSync(path.join(root, '.runtime/manager_share_state.json'), 'utf8').replace(/^\uFEFF/, ''));
const origin = new URL(state.origin).origin;
assert.equal(new URL(origin).protocol, 'https:');
assert.ok(new URL(origin).hostname.endsWith('.trycloudflare.com'));
const report = { checked_at: new Date().toISOString(), origin, checks: [], page_errors: [] };
const add = (name, value) => { assert.ok(value, name); report.checks.push({ name, passed: true }); };

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const anonymous = await browser.newContext();
    for (const route of ['/api/v1/demo2/auth/me', '/api/v1/demo2/admin/summary', '/api/seewo_student_demo', '/assets/seewo_xiaoyudi_demo/test.jpg']) {
      const response = await anonymous.request.get(origin + route, { maxRedirects: 0, timeout: 60000 });
      add('anonymous blocked: ' + route, [401, 403, 404, 410].includes(response.status()));
    }
    await anonymous.close();

    for (const user of [
      { username: 't1', password: process.env.REHAB_TEACHER_PASSWORD, role: 'school_uploader', landing: '/demo2/school' },
      { username: 'admin', password: process.env.REHAB_ADMIN_PASSWORD, role: 'company_admin', landing: '/demo2/admin' },
    ]) {
      assert.ok(user.password, 'Password must be supplied through environment');
      const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
      const page = await context.newPage();
      page.setDefaultTimeout(60000);
      page.on('pageerror', error => report.page_errors.push(error.name));
      try {
        await page.goto(state.invite_url, { waitUntil: 'domcontentloaded', timeout: 90000 });
        await page.waitForURL(origin + '/demo2/login', { timeout: 60000 });
        add(user.role + ' invitation opened login', new URL(page.url()).hash === '');
        const registration = await context.request.get(origin + '/demo2/register');
        const registrationHtml = await registration.text();
        add(user.role + ' phone registration page', registration.status() === 200 && registrationHtml.includes('id="phone"') && registrationHtml.includes('id="code"') && !registrationHtml.includes('同意并提交申请'));
        const configuration = await context.request.get(origin + '/api/v1/demo2/membership/config');
        const settings = (await configuration.json()).config;
        add(user.role + ' membership configuration available', configuration.status() === 200 && typeof settings.sms_available === 'boolean' && typeof settings.payment_available === 'boolean');
        await page.locator('#loginForm').waitFor();
        if (user.role === 'company_admin') await page.locator('#adminRole').click();
        await page.locator('#username').fill(user.username);
        await page.locator('#password').fill(user.password);
        await page.locator('#loginButton').click();
        await page.waitForURL(origin + user.landing);
        const response = await context.request.get(origin + '/api/v1/demo2/auth/me');
        const me = await response.json();
        add(user.role + ' real login', response.status() === 200 && me.account.role === user.role);
        const session = (await context.cookies()).find(cookie => cookie.name === 'rehab_demo2_session');
        add(user.role + ' protected session cookie', session && session.httpOnly && session.secure);
        if (user.role === 'school_uploader') {
          await page.locator('#schoolTitle').waitFor();
          await page.goto(origin + '/demo2/upload?course_id=media-validation-20260908', { waitUntil: 'domcontentloaded' });
          await page.locator('#uploadTitle').waitFor();
          const workspace = await context.request.get(origin + '/api/v1/demo2/upload/workspace?course_id=media-validation-20260908');
          add('teacher upload workspace', workspace.status() === 200 && (await workspace.json()).ok === true);
          const denied = await context.request.get(origin + '/api/v1/demo2/admin/summary');
          add('teacher cannot read company admin summary', denied.status() === 403);
          const history = await page.goto(origin + '/demo2/analysis', { waitUntil: 'domcontentloaded' });
          add('historical classroom analysis page', history.status() === 200);
          await page.goto(origin + '/demo2/membership', { waitUntil: 'domcontentloaded' });
          await page.locator('#membershipStatus').waitFor();
          const membership = await context.request.get(origin + '/api/v1/demo2/membership');
          const member = (await membership.json()).membership;
          add('pilot account keeps truthful membership state', membership.status() === 200 && member.status === 'internal_trial' && member.orders.length === 0);
        } else {
          await page.waitForFunction(() => document.getElementById('accountCount').textContent !== '--');
          const summary = await context.request.get(origin + '/api/v1/demo2/admin/summary');
          add('admin database summary', summary.status() === 200 && (await summary.json()).ok === true);
          const members = await context.request.get(origin + '/api/v1/demo2/admin/memberships');
          add('admin membership summary available', members.status() === 200 && Array.isArray((await members.json()).summary.members));
          const denied = await context.request.get(origin + '/demo2/upload');
          add('admin role cannot impersonate uploader', denied.status() === 403);
        }
        const crossSite = await context.request.post(origin + '/api/v1/demo2/auth/logout', { headers: { Origin: 'https://untrusted.example' }, data: {} });
        add(user.role + ' cross-site write rejected', crossSite.status() === 403);
        const logout = await context.request.post(origin + '/api/v1/demo2/auth/logout', { headers: { Origin: origin }, data: {} });
        add(user.role + ' logout', logout.status() === 200);
        await page.goto(origin + '/demo2/login', { waitUntil: 'domcontentloaded' });
        await page.locator('#loginForm').waitFor();
        if (user.role === 'company_admin') {
          await page.locator('#adminRole').click();
          await page.screenshot({ path: path.join(root, '.runtime/manager_remote_login.png'), fullPage: true });
        }
      } finally {
        await context.close();
      }
    }
    add('no browser script errors', report.page_errors.length === 0);
    fs.writeFileSync(path.join(root, '.runtime/manager_share_verification.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
  } finally {
    await browser.close();
  }
})().catch(error => {
  const text = String(error.message || error).replaceAll(state.invite_url, origin + '/invite#[redacted]');
  console.error(text);
  process.exitCode = 1;
});
