'use strict';
// One installed browser, real UI/HTTP, fictional data. Never target live8792.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const rawAssert = require('node:assert/strict');
let assertions = 0;
const assert = new Proxy(rawAssert, { get(target, key) {
  const value = target[key];
  return typeof value === 'function' ? (...args) => { const answer = value(...args); assertions++; return answer; } : value;
} });
const { chromium } = require('playwright');
const config = JSON.parse(fs.readFileSync(0, 'utf8'));
const origin = new URL(config.base);
assert.equal(config.isolated, true);
assert.equal(origin.hostname, '127.0.0.1');
assert.equal(origin.protocol, 'http:');
assert.ok(Number(origin.port) > 1024 && !['8792', '8796'].includes(origin.port));
assert.ok(config.guard && config.fictional_authorization.startsWith('FICTIONAL'));
const executablePath = path.join(process.env.LOCALAPPDATA, 'ms-playwright', 'chromium_headless_shell-1243',
  'chrome-headless-shell-win64', 'chrome-headless-shell.exe');
assert.ok(fs.existsSync(executablePath), 'Installed 1243 required; no download');
const output = path.resolve(config.output);
const api = '/api/v1/demo2/dossier';
const report = { fixture_only: true, fictional_authorization: true, browser: 'headless-shell1243',
  inference_tested: false, checks: [], screenshots: [], downloads: [], dialogs: [],
  page_errors: [], server_errors: [], external_requests: [], cleanup: [], completed: false };
let browser;
function checkpoint() {
  report.assertions_passed = assertions;
  fs.writeFileSync(path.join(output, 'browser_report.json'), JSON.stringify(report, null, 2));
}
function record(name, evidence = {}) { report.checks.push({ name, ok: true, ...evidence }); checkpoint(); process.stdout.write(name + ': PASS\n'); }
async function close(target, name) {
  let timer;
  try { await Promise.race([target.close(), new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('close_timeout')), 12000); })]); report.cleanup.push({ name, closed: true }); }
  catch (error) { report.cleanup.push({ name, closed: false, error: error.message }); }
  finally { clearTimeout(timer); checkpoint(); }
}
async function session(alias) {
  const context = await browser.newContext({ viewport: { width: 1366, height: 900 }, acceptDownloads: true,
    serviceWorkers: 'block', locale: 'zh-CN', reducedMotion: 'reduce' });
  await context.route('**/*', route => {
    const target = new URL(route.request().url());
    if (target.origin === origin.origin || ['blob:', 'data:'].includes(target.protocol)) return route.continue();
    report.external_requests.push(target.origin + target.pathname);
    return route.abort('blockedbyclient');
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.on('pageerror', error => report.page_errors.push(error.message));
  page.on('response', response => { if (response.status() >= 500) report.server_errors.push({ path: new URL(response.url()).pathname, status: response.status() }); });
  page.on('dialog', async dialog => { report.dialogs.push({ type: dialog.type(), message: dialog.message() }); await dialog.accept(); });
  await page.goto(config.base + '/demo2/login');
  await page.getByRole('radio', { name: alias === 'admin' ? '管理员登录' : '用户登录', exact: true }).click();
  await page.getByLabel('账号', { exact: true }).fill(config.usernames[alias]);
  await page.getByLabel('密码', { exact: true }).fill(config.users[alias]);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.waitForURL(alias === 'admin' ? '**/demo2/admin' : '**/demo2/school');
  return { context, page };
}
async function capture(page, name) {
  for (const [width, suffix] of [[1366, ''], [390, '_mobile'], [320, '_mobile320']]) {
    await page.setViewportSize({ width, height: 900 });
    await page.evaluate(() => { document.activeElement?.blur(); scrollTo(0, 0); });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const geometry = await page.evaluate(() => ({ width: innerWidth, scrollWidth: document.documentElement.scrollWidth }));
    const filename = name + suffix + '.png';
    await page.screenshot({ path: path.join(output, filename), fullPage: true });
    report.screenshots.push({ filename, ...geometry });
    assert.ok(geometry.scrollWidth <= width + 1, `${filename}: horizontal overflow`);
  }
  await page.setViewportSize({ width: 1366, height: 900 });
  checkpoint();
}
async function studentWorkspace(page) {
  const response = await page.request.get(`${config.base}${api}/student?student_id=${config.students.a.student_id}`);
  assert.equal(response.status(), 200);
  return (await response.json()).workspace;
}
async function openDossier(page, student = 'a') {
  await page.goto(`${config.base}/demo2/dossier?student_id=${config.students[student].student_id}`);
  await page.locator('#studentVerified:not([disabled])').waitFor();
  assert.match(await page.locator('#studentMeta').innerText(), new RegExp(config.students[student].student_code));
  assert.equal(await page.locator('#studentVerified').isChecked(), false);
  await page.locator('#studentVerified').check();
}
async function postByClick(page, button, route, field) {
  const waiting = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === api + route);
  await page.locator(button).click();
  const response = await waiting;
  assert.equal(response.status(), 200, `POST ${route} failed: ${await response.text()}`);
  const data = await response.json();
  await page.locator('#pageMessage.success').waitFor();
  return data[field];
}
async function fillDocument(page, version) {
  await page.locator('#documentDate').fill(config.today);
  await page.locator('#retainUntil').fill(config.retain_until);
  await page.locator('#sourceRef').fill(`虚构校内资料记录-QA-版本${version}`);
  await page.locator('#learning_goals').fill(`虚构示例：按教师提示完成课堂任务（第${version}版）。`);
  await page.locator('#support_methods').fill('虚构示例：提供清晰步骤与短休息。');
  await page.locator('#safety_notes').fill('虚构示例：由教师核对课堂支持安排。');
  await page.locator('#professional_conclusion').fill('虚构资料，无个人医学信息，不用于诊断。');
  await page.locator('#documentFile').setInputFiles({ name: `虚构_IEP_V${version}.txt`, mimeType: 'text/plain',
    buffer: Buffer.from(config.document_base64, 'base64') });
}
async function download(page, selector, name, expected) {
  const waiting = page.waitForEvent('download');
  await page.locator(selector).click();
  const item = await waiting;
  await item.saveAs(path.join(output, name));
  const bytes = fs.readFileSync(path.join(output, name));
  if (expected) assert.deepEqual(bytes, expected);
  report.downloads.push({ filename: name, byte_size: bytes.length, sha256: crypto.createHash('sha256').update(bytes).digest('hex') });
  return bytes;
}

(async () => {
  try {
    browser = await chromium.launch({ executablePath, headless: true, args: ['--disable-background-networking',
      '--disable-component-update', '--disable-sync', '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'] });
    const teacher = await session('t1');
    try {
      const { page } = teacher;
      const health = await page.request.get(config.base + '/__identity_qa__/health', { headers: { 'X-Identity-QA': config.guard } });
      assert.equal(health.status(), 200);
      await health.dispose();
      await openDossier(page);
      assert.equal(await page.locator('#authorizationConfirmed').isChecked(), false);
      assert.equal(await page.locator('#storageMode').inputValue(), '');
      assert.equal(await page.locator('#authorizationUntil').inputValue(), '');
      await page.locator('#authorizationReference').fill(config.fictional_authorization);
      await page.locator('#storageMode').selectOption('original_and_summary');
      await page.locator('#authorizationUntil').fill(config.valid_until);
      await capture(page, 'student_authorization');
      await page.locator('#authorizationConfirmed').check();
      const authorization = await postByClick(page, '#saveAuthorization', '/authorization', 'authorization');
      assert.equal(authorization.purpose, 'education_support');
      record('explicit_fictional_authorization_no_prechecked_consent');
      await page.locator('#tabDocuments').click();
      await page.locator('#documentType').selectOption('iep');
      await fillDocument(page, 1);
      const v1 = await postByClick(page, '#saveDocument', '/documents', 'document');
      assert.equal(v1.version, 1);
      await download(page, `[data-document="${v1.document_id}"]`, 'fictional_original_v1.txt', Buffer.from(config.document_base64, 'base64'));
      await capture(page, 'original_download');
      await page.locator(`[data-version="${v1.document_id}"]`).click();
      await fillDocument(page, 2);
      const v2 = await postByClick(page, '#saveDocument', '/documents', 'document');
      assert.equal(v2.version, 2);
      assert.equal(v2.family_id, v1.family_id);
      for (const details of await page.locator('#documentList details').all()) await details.locator('summary').click();
      await capture(page, 'student_documents');
      await download(page, `[data-document="${v2.document_id}"]`, 'fictional_original_v2.txt', Buffer.from(config.document_base64, 'base64'));
      record('real_original_download_and_immutable_two_versions');

      await page.goto(`${config.base}/demo2/identity?task_id=${config.task_id}`);
      await page.locator('#annotationAdvanced > summary').click();
      await page.locator('#bboxX:not([disabled])').waitFor();
      for (const [id, value] of [['bboxX', '15'], ['bboxY', '20'], ['bboxWidth', '20'], ['bboxHeight', '60']]) await page.locator('#' + id).fill(value);
      await page.locator('#personRole').selectOption('student');
      await page.locator('#studentSelect').selectOption(config.students.a.student_id);
      const bindingReply = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/v1/demo2/identity/bindings');
      await page.locator('#saveBinding').click();
      assert.equal((await bindingReply).status(), 200);
      await page.locator('#pageMessage.success').waitFor();
      const taskReply = page.waitForResponse(response => response.request().method() === 'GET' && new URL(response.url()).pathname === api + '/task');
      await page.goto(`${config.base}/demo2/course-dossier?task_id=${config.task_id}`);
      const taskResponse = await taskReply;
      assert.equal(taskResponse.status(), 200);
      const taskWorkspace = (await taskResponse.json()).workspace;
      assert.equal(taskWorkspace.students.length, 1);
      assert.equal(taskWorkspace.students[0].student_id, config.students.a.student_id);
      await page.locator('#referenceFields:not([disabled])').waitFor();
      const options = await page.locator('#referenceStudent option').allTextContents();
      assert.equal(options.length, 2, 'Only the confirmed student appears, not the same-name student B');
      await page.locator('#referenceStudent').selectOption(config.students.a.student_id);
      assert.equal(await page.locator('#referenceConfirmed').isChecked(), false);
      await page.locator(`[data-doc-id="${v1.document_id}"]`).check();
      await page.locator('#referenceConfirmed').check();
      const reference = await postByClick(page, '#saveReference', '/references', 'reference');
      // Re-select through the real UI after its successful reread resets the form.
      // Keep confirmation unchecked; this only exposes the full student identity
      // and available versions alongside the already-saved reference for review.
      await page.locator('#referenceStudent').selectOption(config.students.a.student_id);
      const selectedContext = await page.locator('#selectedStudentContext').innerText();
      assert.ok(selectedContext.includes(config.students.a.display_name));
      assert.ok(selectedContext.includes(config.students.a.student_id));
      assert.equal(await page.locator('#referenceConfirmed').isChecked(), false);
      await capture(page, 'course_reference');
      const bytes = await download(page, `[data-reference="${reference.reference_id}"]`, 'fictional_course_reference_v1.json');
      const exported = JSON.parse(bytes);
      assert.ok(JSON.stringify(exported).includes(v1.document_id));
      assert.ok(!JSON.stringify(exported).includes(v2.document_id));
      record('real_manual_identity_binding_and_explicit_version_reference');

      await openDossier(page);
      await page.locator('#tabDocuments').click();
      await postByClick(page, `[data-delete="${v2.document_id}"]`, '/documents/delete', 'result');
      assert.equal((await studentWorkspace(page)).documents.find(item => item.document_id === v2.document_id).available, false);
      await capture(page, 'document_deleted');
      await page.locator('#tabAuthorization').click();
      await postByClick(page, '#withdrawAuthorization', '/authorization/withdraw', 'result');
      await page.locator('#tabDocuments').click();
      assert.equal(await page.locator('[data-document]').count(), 0);
      const text = await page.locator('#documentList').innerText();
      assert.ok(!text.includes('虚构校内资料记录') && !text.includes('虚构_IEP'));
      await capture(page, 'authorization_withdrawn');
      await page.locator('#tabReferences').click();
      const withdrawn = JSON.parse(await download(page, `[data-reference="${reference.reference_id}"]`, 'fictional_reference_after_withdrawal.json'));
      assert.ok(!JSON.stringify(withdrawn).includes('按教师提示完成课堂任务'));
      const denied = await page.request.get(`${config.base}${api}/document?document_id=${v1.document_id}`);
      assert.ok([404, 410].includes(denied.status()));
      await denied.dispose();
      record('real_delete_withdraw_and_export_cannot_restore_content');
    } finally { await close(teacher.context, 'teacher_context'); }

    const admin = await session('admin');
    try {
      await admin.page.goto(config.base + '/demo2/admin/dossiers');
      await admin.page.locator('#adminTotals .metric').first().waitFor();
      const text = await admin.page.locator('body').innerText();
      for (const marker of ['虚构同名学生', config.fictional_authorization, '虚构_IEP', '虚构校内资料记录']) assert.ok(!text.includes(marker));
      await capture(admin.page, 'admin_dossiers');
      const denied = await admin.page.request.get(`${config.base}${api}/student?student_id=${config.students.a.student_id}`);
      assert.equal(denied.status(), 403);
      await denied.dispose();
      record('admin_operational_metadata_only');
    } finally { await close(admin.context, 'admin_context'); }
    assert.deepEqual(report.page_errors, []);
    assert.deepEqual(report.external_requests, []);
    assert.deepEqual(report.server_errors, []);
    report.functional_ok = true;
  } catch (error) {
    report.functional_ok = false;
    report.failure = { name: error.name, message: error.message };
    process.exitCode = 1;
  } finally {
    checkpoint();
    if (browser) await close(browser, 'browser');
    report.completed = true;
    report.ok = report.functional_ok && report.cleanup.every(item => item.closed);
    if (!report.ok) process.exitCode = 1;
    checkpoint();
    process.stdout.write(JSON.stringify({ ok: report.ok, checks: report.checks.length,
      assertions, report: path.join(output, 'browser_report.json') }) + '\n');
  }
})();
