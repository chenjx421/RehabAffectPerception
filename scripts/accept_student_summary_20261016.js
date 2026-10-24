/* Real browser acceptance; all data and sessions belong to a disposable fixture. */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');

(async () => {
  const base = process.env.SUMMARY_ACCEPTANCE_BASE;
  const output = process.env.SUMMARY_ACCEPTANCE_OUTPUT;
  const student = process.env.SUMMARY_ACCEPTANCE_STUDENT;
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const errors = [];
  try {
    const contexts = {};
    for (const role of ['teacher', 'admin']) {
      const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
      await context.addCookies([{ name: 'rehab_demo2_session', value: process.env['SUMMARY_ACCEPTANCE_' + role.toUpperCase()], url: base }]);
      const invited = await context.request.post(base + '/__manager/authorize', {
        data: { secret: process.env.SUMMARY_ACCEPTANCE_INVITE }, headers: { Origin: base }, maxRedirects: 0
      });
      assert.equal(invited.status(), 303);
      // This disposable fixture is HTTP loopback, not the HTTPS production entry.
      const signed = invited.headers()['set-cookie'].split(';', 1)[0].split('=', 2);
      await context.addCookies([{ name: signed[0], value: signed[1], url: base }]);
      contexts[role] = context;
    }
    const teacher = await contexts.teacher.newPage();
    teacher.on('pageerror', error => errors.push(error.message));
    teacher.on('dialog', dialog => dialog.accept());
    await teacher.goto(base + '/demo2/student-summary?student_id=' + encodeURIComponent(student));
    await teacher.locator('#studentName').filter({ hasText: '合成测试学生' }).waitFor();
    await teacher.locator('#studentVerified').check();
    await teacher.locator('#authorizationReference').fill('SYNTHETIC permission reference');
    await teacher.locator('#authorizationConfirmed').check();
    await teacher.locator('#authorizationForm button[type=submit]').click();
    await teacher.locator('#reviewConfirmed').check();
    await teacher.locator('#commitButton').click();
    await teacher.locator('#authorizationStatus').filter({ hasText: '授权有效' }).waitFor();
    await teacher.locator('#studentVerified').check();
    await teacher.locator('#sourceRef').fill('SYNTHETIC teacher record');
    await teacher.locator('#learningGoals').fill('用图片提示完成两类物品配对');
    await teacher.locator('#supportMethods').fill('提供图片提示并留出等待时间');
    await teacher.locator('#domain_communication').selectOption('with_support');
    await teacher.locator('#snapshotReviewed').check();
    await teacher.locator('#snapshotForm button[type=submit]').click();
    await teacher.locator('#reviewConfirmed').check();
    await teacher.locator('#commitButton').click();
    await teacher.locator('#snapshotList').filter({ hasText: '用图片提示完成两类物品配对' }).waitFor();
    await teacher.reload();
    await teacher.locator('#snapshotList').filter({ hasText: '用图片提示完成两类物品配对' }).waitFor();
    await teacher.screenshot({ path: path.join(output, 'teacher-desktop.png'), fullPage: true });

    const admin = await contexts.admin.newPage();
    admin.on('pageerror', error => errors.push(error.message));
    await admin.goto(base + '/demo2/admin/student-summaries');
    await admin.locator('#archiveRows button').first().waitFor();
    await admin.locator('#archiveRows button').first().click();
    await admin.locator('#detailRecords').filter({ hasText: '用图片提示完成两类物品配对' }).waitFor();
    const visible = await admin.locator('body').innerText();
    assert(!visible.includes('合成测试学生') && !visible.includes('SYNTHETIC-001'));
    const downloadPromise = admin.waitForEvent('download');
    await admin.locator('#exportButton').click();
    const download = await downloadPromise;
    const downloaded = await download.path();
    const text = fs.readFileSync(downloaded, 'utf8');
    const data = JSON.parse(text);
    assert.equal(data.snapshots.length, 1);
    assert.equal(data.policy.research, false);
    assert.equal(data.policy.training, false);
    for (const forbidden of [student, '合成测试学生', 'SYNTHETIC-001', 'SYNTHETIC teacher record', 'SYNTHETIC permission reference']) assert(!text.includes(forbidden));
    await admin.screenshot({ path: path.join(output, 'company-desktop.png'), fullPage: true });
    for (const [role, page] of [['teacher', teacher], ['company', admin]]) {
      await page.setViewportSize({ width: 390, height: 844 });
      const sizes = await page.evaluate(() => ({ full: document.documentElement.scrollWidth, view: innerWidth }));
      assert(sizes.full <= sizes.view + 1, role + ' horizontal overflow');
      await page.screenshot({ path: path.join(output, role + '-mobile.png'), fullPage: true });
    }
    await teacher.locator('#studentVerified').check();
    await teacher.locator('#withdrawButton').click();
    await teacher.locator('#reviewConfirmed').check();
    await teacher.locator('#commitButton').click();
    await teacher.locator('#authorizationStatus').filter({ hasText: '已撤回' }).waitFor();
    await admin.locator('#reloadButton').click();
    await admin.waitForFunction(() => document.querySelector('#archiveRows').querySelectorAll('button').length === 0 && document.querySelector('#detailSection').hidden);
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify({
      synthetic_only: true, teacher_authorization: true, snapshot_save_reload: true,
      company_read_export: true, identifier_minimization: true, mobile_no_overflow: true,
      revoke_denies_company_read: true, browser_errors: errors
    }, null, 2));
    console.log('Synthetic browser summary lifecycle passed.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
