// Browser workflow check. Uses only the temporary database created by the harness.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const base = process.env.DEMO2_ENTRY_URL;
if (!base) throw new Error('Run through scripts.qa_demo2_entry to isolate test data.');
const output = path.resolve('output/playwright/entry_20260908');
fs.mkdirSync(output, { recursive: true });

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const errors = [];
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  async function capture(name) {
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${name}: horizontal overflow`);
    await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true });
  }
  async function login(username, password, role = '用户登录') {
    await page.goto(`${base}/demo2/login`);
    await page.getByRole('radio', { name: role, exact: true }).click();
    await page.getByLabel('账号', { exact: true }).fill(username);
    await page.getByLabel('密码', { exact: true }).fill(password);
    await page.getByRole('button', { name: '登录', exact: true }).click();
  }
  try {
    await page.goto(`${base}/demo2/login`);
    await capture('01_login');
    await page.getByRole('radio', { name: '管理员登录' }).click();
    await capture('02_admin_login');
    await login('t1', 'UITest01', '管理员登录');
    await page.locator('#formError.visible').waitFor();
    assert.match(await page.locator('#formError').textContent(), /身份|role/);
    assert.equal((await context.cookies()).filter(item => item.name.includes('session')).length, 0);
    await login('t1', 'UITest01');
    await page.waitForURL('**/demo2/school');
    await page.locator('#schoolButton:not([disabled])').waitFor();
    await capture('03_school_empty');
    await page.getByLabel('城市', { exact: true }).fill('上海市');
    await page.getByLabel('区县', { exact: true }).fill('演示区');
    await page.getByLabel('学校', { exact: true }).fill('学校内测演示（虚构）');
    await capture('04_school_form');
    await page.getByRole('button', { name: '进入课程工作台' }).click();
    await page.waitForURL('**/demo2/upload');
    await page.getByText('上海市 / 演示区 / 学校内测演示（虚构）', { exact: true }).waitFor();
    await capture('05_upload');
    assert.equal((await page.request.get(`${base}/api/v1/demo2/admin/summary`)).status(), 403);
    await page.getByRole('link', { name: '学校设置' }).click();
    await page.locator('#schoolButton:not([disabled])').waitFor();
    assert.equal(await page.getByLabel('学校', { exact: true }).inputValue(), '学校内测演示（虚构）');
    await page.getByRole('button', { name: '退出登录' }).click();
    await page.waitForURL('**/demo2/login');
    await page.getByRole('link', { name: '会员注册', exact: true }).click();
    await capture('06_registration');
    await page.getByLabel('联系人', { exact: true }).fill('演示联系人');
    await page.getByLabel('手机或邮箱').fill('demo@example.invalid');
    await page.getByLabel('城市', { exact: true }).fill('上海市');
    await page.getByLabel('区县', { exact: true }).fill('演示区');
    await page.getByLabel('学校名称').fill('注册申请演示（虚构）');
    await page.getByRole('button', { name: '同意并提交申请' }).click();
    await page.locator('#registrationSuccess:not([hidden])').waitFor();
    assert.ok(!/已记录$/.test(await page.locator('#requestReference').textContent()), 'Registration must return an actual reference');
    await capture('07_registration_submitted');
    await login('admin', 'UIAdmin1', '管理员登录');
    await page.waitForURL('**/demo2/admin');
    await page.locator('#registrationRequests').getByText('演示联系人', { exact: true }).waitFor();
    await page.locator('#schoolContexts').getByText('学校内测演示（虚构）', { exact: true }).waitFor();
    await capture('08_admin');
    await page.goto(`${base}/demo2/privacy`);
    await capture('09_privacy');
    for (const route of ['login', 'school', 'register', 'upload', 'admin']) {
      await page.setViewportSize({ width: 390, height: 844 });
      if (route === 'school' || route === 'upload') {
        await login('t1', 'UITest01');
        await page.waitForURL('**/demo2/school');
      } else if (route === 'admin') {
        await login('admin', 'UIAdmin1', '管理员登录');
        await page.waitForURL('**/demo2/admin');
      }
      await page.goto(`${base}/demo2/${route}`);
      await page.waitForLoadState('networkidle');
      await capture(`mobile_${route}`);
    }
    // A single-file share preview must neither contact a server nor fake success.
    await page.goto(`file://${path.resolve('deliverables/20260908_platform_entry/login.html').replace(/\\/g, '/')}`);
    await page.getByLabel('账号', { exact: true }).fill('preview');
    await page.getByLabel('密码', { exact: true }).fill('preview');
    await page.getByRole('button', { name: '登录', exact: true }).click();
    assert.match(await page.locator('#formError').textContent(), /仅供页面预览/);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ ok: true, screenshots: output, checks: ['role isolation', 'school persistence', 'registration to admin', 'privacy', 'desktop and mobile layout', 'offline preview'] }));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
