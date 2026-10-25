// Real Edge interactions against the Python harness's fresh localhost server.
// No API response mocking, production URL, stored login state or paid fixture.
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const config = JSON.parse(fs.readFileSync(0, 'utf8'));
const origin = new URL(config.base);
assert.equal(config.isolated, true, 'Launch only from the isolated Python harness');
assert.equal(origin.protocol, 'http:');
assert.equal(origin.hostname, '127.0.0.1');
assert.ok(Number(origin.port) > 1024 && Number(origin.port) !== 8792, 'Never target the live service');
assert.ok(config.guard && config.source_video_is_stub);
const output = path.resolve(config.output);
fs.mkdirSync(output, { recursive: true });
const api = '/api/v1/demo2/identity';
const report = { fixture_only: true, source_video_is_stub: true,
  detector: 'server-side position-only fixture; no identity matching',
  browser: 'Microsoft Edge', mode: config.school_repair_only ? 'school-repair-only' : 'full-identity',
  widths: config.school_repair_only ? [320] : [1440, 390, 320], checks: [], screenshots: [],
  page_errors: [], external_requests: [], server_errors: [], cleanup: [], completed: false };
let browser;

function checkpoint() {
  report.check_group_count = report.checks.length;
  fs.writeFileSync(path.join(output, 'browser_report.json'), JSON.stringify(report, null, 2));
}

async function boundedClose(target, name) {
  let timer;
  try {
    await Promise.race([target.close(), new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(`${name} close exceeded 8000 ms`)), 8000);
    })]);
    report.cleanup.push({ name, closed: true });
    return true;
  } catch (error) {
    report.cleanup.push({ name, closed: false, error: error.message });
    return false;
  } finally { clearTimeout(timer); checkpoint(); }
}

function record(name, evidence = {}) {
  report.checks.push({ name, ok: true, ...evidence });
  checkpoint();
  process.stdout.write(JSON.stringify({ check: name, ok: true }) + '\n');
}

async function contextFor(width) {
  const context = await browser.newContext({ viewport: { width, height: width > 600 ? 1000 : 844 },
    isMobile: width < 600, hasTouch: width < 600, deviceScaleFactor: 1, reducedMotion: 'reduce',
    locale: 'zh-CN', acceptDownloads: true });
  await context.route('**/*', async route => {
    const target = new URL(route.request().url());
    if (target.origin === origin.origin || ['data:', 'blob:'].includes(target.protocol)) return route.continue();
    report.external_requests.push(target.origin + target.pathname);
    return route.abort('blockedbyclient');
  });
  const page = await context.newPage();
  page.setDefaultTimeout(12000);
  page.on('pageerror', error => report.page_errors.push(error.message));
  page.on('response', response => {
    if (response.status() >= 500) report.server_errors.push({ status: response.status(), path: new URL(response.url()).pathname });
  });
  return { context, page };
}

async function capture(page, name) {
  // DOM reads supplement actual screenshots; they do not stand in for visual QA.
  await page.evaluate(() => { window.scrollTo(0, 0); });
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const metrics = await page.evaluate(() => ({ width: innerWidth, scrollWidth: document.documentElement.scrollWidth,
    image: (() => { const image = document.getElementById('frameImage'); return image && {
      naturalWidth: image.naturalWidth, naturalHeight: image.naturalHeight,
      displayedWidth: image.getBoundingClientRect().width, displayedHeight: image.getBoundingClientRect().height }; })() }));
  const filename = `${name}.png`;
  await page.screenshot({ path: path.join(output, filename), fullPage: true });
  report.screenshots.push({ name, file: filename, ...metrics });
  assert.ok(metrics.scrollWidth <= metrics.width + 1, `${name}: horizontal overflow ${metrics.scrollWidth}/${metrics.width}`);
  if (metrics.image?.displayedWidth > 0) {
    assert.equal(metrics.image.naturalWidth, 640);
    assert.equal(metrics.image.naturalHeight, 360);
    assert.ok(Math.abs(metrics.image.displayedWidth / metrics.image.displayedHeight - 640 / 360) < 0.02,
      `${name}: source frame distorted`);
  }
}

async function login(page, alias) {
  await page.goto(`${config.base}/demo2/login`, { waitUntil: 'domcontentloaded' });
  await page.getByRole('radio', { name: alias === 'admin' ? '管理员登录' : '用户登录', exact: true }).click();
  await page.getByLabel('账号', { exact: true }).fill(config.usernames[alias]);
  await page.getByLabel('密码', { exact: true }).fill(config.users[alias]);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.waitForURL(alias === 'admin' ? '**/demo2/admin' : alias === 'member' ? '**/demo2/membership' : '**/demo2/school');
}

async function workspace(page, taskId = config.task_ids.t1) {
  const response = await page.request.get(`${config.base}${api}/workspace?task_id=${encodeURIComponent(taskId)}`);
  assert.equal(response.status(), 200, 'Identity workspace API is not ready');
  const body = await response.json();
  assert.equal(body.workspace.task_id, taskId);
  return body.workspace;
}

async function openIdentity(page) {
  await page.goto(`${config.base}/demo2/identity?task_id=${encodeURIComponent(config.task_ids.t1)}`);
  await page.locator('#refreshWorkspace:not([disabled])').waitFor();
  const data = await workspace(page);
  if (!data.media_available || data.frames.length !== 2) {
    await capture(page, 'BLOCKED_actual_finish_manifest');
    throw new Error(`Real finish_video_analysis -> identity frames failed: ${data.summary?.media_unavailable_reason || 'wrong frame count'}`);
  }
  await page.locator('#frameSurface:not([hidden])').waitFor();
  await page.locator('#drawButton:not([disabled])').waitFor();
  return data;
}

async function selectFrame(page, index) {
  await page.locator('#frameSelect').selectOption(String(index));
  await page.waitForFunction(index => document.getElementById('frameSelect').value === String(index)
    && !document.getElementById('drawButton').disabled, index);
}

async function createSameNameStudents(page) {
  await page.goto(`${config.base}/demo2/students?returntask=${encodeURIComponent(config.task_ids.t1)}`);
  await page.locator('#studentFields:not([disabled])').waitFor();
  assert.match(await page.locator('#rosterCount').innerText(), /0 人/);
  assert.match(await page.locator('#rosterList').innerText(), /名册为空/);
  await capture(page, '1440_roster_initially_empty');
  const students = [];
  for (const code of ['QA-001', 'QA-002']) {
    await page.locator('#displayName').fill('虚构同名学生');
    await page.locator('#studentCode').fill(code);
    await page.locator('#className').fill('QA虚拟班');
    await page.locator('#studentNote').fill('隔离QA虚拟资料，无真实儿童信息');
    if (students.length) page.once('dialog', dialog => dialog.accept());
    const response = page.waitForResponse(response => response.request().method() === 'POST'
      && new URL(response.url()).pathname === `${api}/students`);
    await page.locator('#createStudent').click();
    const saved = await response;
    assert.equal(saved.status(), 200);
    students.push((await saved.json()).student);
    await page.locator('#createStudent:not([disabled])').waitFor();
  }
  assert.notEqual(students[0].student_id, students[1].student_id);
  assert.equal(students[0].display_name, students[1].display_name);
  await page.reload();
  await page.getByText('校内编号 QA-002', { exact: false }).waitFor();
  await capture(page, '1440_roster_same_name_distinct_codes');
  record('empty_roster_to_same_name_students_real_ui', { count: students.length });
  return students;
}

async function drawBox(page, context, width) {
  await page.locator('#drawButton').click();
  const surface = page.locator('#frameSurface');
  await surface.scrollIntoViewIfNeeded();
  const rect = await surface.boundingBox();
  assert.ok(rect && rect.width > 0);
  const start = { x: rect.x + rect.width * 0.15, y: rect.y + rect.height * 0.2 };
  const end = { x: rect.x + rect.width * 0.35, y: rect.y + rect.height * 0.8 };
  if (width > 600) {
    await page.mouse.move(start.x, start.y);
    await page.mouse.down();
    await page.mouse.move(end.x, end.y, { steps: 8 });
    await page.mouse.up();
  } else {
    // Native Chromium touch input, not dispatchEvent or a fabricated DOM box.
    const cdp = await context.newCDPSession(page);
    try {
      const point = position => [{ ...position, id: 1, radiusX: 2, radiusY: 2, force: 1 }];
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: point(start) });
      for (let step = 1; step <= 6; step++) await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove',
        touchPoints: point({ x: start.x + (end.x - start.x) * step / 6, y: start.y + (end.y - start.y) * step / 6 }) });
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    } finally { await cdp.detach(); }
  }
  for (const [id, expected] of [['bboxX', 15], ['bboxY', 20], ['bboxWidth', 20], ['bboxHeight', 60]]) {
    assert.ok(Math.abs(Number(await page.locator(`#${id}`).inputValue()) - expected) <= 1,
      `${width}: pointer box coordinate mapping ${id}`);
  }
}

async function save(page, role, studentId) {
  if (role !== await page.locator('#personRole').inputValue() && !await page.locator('#annotationAdvanced').evaluate(node=>node.open)) {
    await page.locator('#annotationAdvanced summary').click();
  }
  if (role !== await page.locator('#personRole').inputValue()) await page.locator('#personRole').selectOption(role);
  if (role === 'student') await page.locator('#studentSelect').selectOption(studentId);
  const before = (await workspace(page)).bindings.length;
  const response = page.waitForResponse(response => response.request().method() === 'POST'
    && new URL(response.url()).pathname === `${api}/bindings`);
  await page.locator('#saveBinding').click();
  const saved = await response;
  assert.equal(saved.status(), 200, `Binding failed: ${await saved.text()}`);
  const binding = (await saved.json()).binding;
  assert.equal(binding.role, role);
  assert.equal(binding.student_id, role === 'student' ? studentId : null);
  await page.locator('#pageMessage.success').waitFor();
  assert.equal((await workspace(page)).bindings.length, before + 1);
  return binding;
}

async function revoke(page, binding) {
  if (!await page.locator(`[data-revoke="${binding.binding_id}"]`).count()) {
    await page.locator('label:has(#recordsAll)').click();
  }
  await page.locator(`[data-revoke="${binding.binding_id}"]`).click();
  await page.locator('#revokeDialog[open]').waitFor();
  await page.locator('#confirmRevoke').click();
  assert.equal(await page.locator('#revokeDialog').evaluate(dialog => dialog.open), true);
  await page.locator('#revokeReason').fill('QA纠正人工误绑定；保留原始帧和审计记录');
  const response = page.waitForResponse(response => response.request().method() === 'POST'
    && new URL(response.url()).pathname === `${api}/bindings/revoke`);
  await page.locator('#confirmRevoke').click();
  const revoked = await response;
  assert.equal(revoked.status(), 200);
  assert.equal((await revoked.json()).binding.status, 'revoked');
  await page.locator('#revokeDialog').waitFor({ state: 'hidden' });
  await page.locator('#pageMessage.success').waitFor();
}

async function runWidth(width, students) {
  const { context, page } = await contextFor(width);
  try {
    await login(page, 't1');
    if (!students) students = await createSameNameStudents(page);
    let data = await openIdentity(page);
    await selectFrame(page, 0);
    // Clean only earlier iterations' active test bindings, through the actual UI.
    for (const binding of data.bindings.filter(item => item.status === 'confirmed' && item.current_revision)) await revoke(page, binding);
    data = await workspace(page);
    assert.equal(data.bindings.filter(item => item.status === 'confirmed').length, 0);
    assert.equal(await page.locator('#personRole').inputValue(), 'student');
    assert.equal(await page.locator('#studentSelect').inputValue(), '');
    assert.equal(await page.locator('#saveBinding').isDisabled(), true);
    await capture(page, `${width}_identity_unconfirmed`);
    if (width === 1440) {
      await page.locator('[data-candidate="0"]').waitFor();
      await page.locator('[data-candidate="0"]').click();
      assert.equal((await workspace(page)).bindings.filter(item => item.status === 'confirmed').length, 0);
      assert.equal(await page.locator('#personRole').inputValue(), 'student');
      assert.equal(await page.locator('#studentSelect').inputValue(), '');
      assert.equal(await page.locator('#saveBinding').isDisabled(), true);
      await page.locator('#clearSelection').click();
      record('detected_candidate_does_not_choose_or_confirm_student');
    }
    await drawBox(page, context, width);
    assert.equal(await page.locator('#personRole').inputValue(), 'student');
    const labels = await page.locator('#studentSelect option').allTextContents();
    assert.ok(labels.some(label => label.includes('QA-001')) && labels.some(label => label.includes('QA-002')));
    assert.equal(await page.locator('#saveBinding').isDisabled(), true, 'Selecting student role must not select first person');
    const wrong = await save(page, 'student', students[0].student_id);
    await page.reload();
    await page.locator('#drawButton:not([disabled])').waitFor();
    assert.equal((await workspace(page)).bindings.find(item => item.binding_id === wrong.binding_id).student_id, students[0].student_id);
    await capture(page, `${width}_binding_persists_after_reload`);
    await revoke(page, wrong);
    await drawBox(page, context, width);
    const corrected = await save(page, 'student', students[1].student_id);
    data = await workspace(page);
    assert.equal(data.bindings.find(item => item.binding_id === wrong.binding_id).status, 'revoked');
    assert.equal(data.bindings.find(item => item.binding_id === corrected.binding_id).student_id, students[1].student_id);
    await capture(page, `${width}_misbinding_revoked_and_corrected`);
    await selectFrame(page, 1);
    assert.equal(await page.locator('#frameOverlay .confirmed').count(), 0, 'Identity must not propagate to another frame');
    assert.equal(await page.locator('#personRole').inputValue(), 'student');
    // The accessible keyboard coordinate alternative works without a pointer.
    if (!await page.locator('#annotationAdvanced').evaluate(node=>node.open)) await page.locator('#annotationAdvanced summary').click();
    for (const [id, value] of [['bboxX', '15'], ['bboxY', '20'], ['bboxWidth', '20'], ['bboxHeight', '60']]) await page.locator(`#${id}`).fill(value);
    await save(page, 'unknown');
    const downloadEvent = page.waitForEvent('download');
    await page.locator('#exportBindings').click();
    const download = await downloadEvent;
    const exportFile = path.join(output, `${width}_identity_export.json`);
    await download.saveAs(exportFile);
    const exported = JSON.parse(fs.readFileSync(exportFile, 'utf8'));
    assert.equal(exported.task_id, config.task_ids.t1);
    assert.equal(exported.summary.tracking_performed, false);
    assert.equal(exported.summary.global_motion_attributed_to_student, false);
    assert.equal(exported.summary.global_audio_attributed_to_student, false);
    assert.ok(exported.bindings.some(item => item.role === 'unknown' && item.student_id === null));
    await capture(page, `${width}_unknown_second_frame`);
    record(`${width}_draw_bind_reload_revoke_correct_unknown_export`);
  } catch (error) {
    await page.screenshot({ path: path.join(output, `${width}_BLOCKED_teacher.png`), fullPage: true }).catch(() => {});
    throw error;
  } finally { await boundedClose(context, 'teacher context'); }

  const admin = await contextFor(width);
  try {
    await login(admin.page, 'admin');
    await admin.page.goto(`${config.base}/demo2/identity?task_id=${encodeURIComponent(config.task_ids.t1)}`);
    await admin.page.locator('#frameSurface:not([hidden])').waitFor();
    assert.notEqual(await admin.page.locator('#bindingFields').getAttribute('disabled'), null);
    assert.equal(await admin.page.locator('#bboxX').isDisabled(), true);
    assert.equal(await admin.page.locator('#drawButton').isDisabled(), true);
    assert.equal(await admin.page.locator('#retryDetection').isDisabled(), true);
    assert.equal(await admin.page.locator('[data-revoke]').count(), 0);
    await capture(admin.page, `${width}_admin_read_only`);
    record(`${width}_admin_read_only`);
  } catch (error) {
    await admin.page.screenshot({ path: path.join(output, `${width}_BLOCKED_admin.png`), fullPage: true }).catch(() => {});
    throw error;
  } finally { await boundedClose(admin.context, 'admin context'); }
  return students;
}

async function guardedControl(page, action) {
  const response = await page.request.post(`${config.base}/__identity_qa__/control`, {
    headers: { 'X-Identity-QA': config.guard }, data: { action, task_id: config.task_ids.t1 } });
  assert.equal(response.status(), 200, 'Isolated test-state control rejected');
  return response.json();
}

async function revisionExpiryAndVideoReturn() {
  const { context, page } = await contextFor(320);
  try {
    await login(page, 't1');
    await openIdentity(page);
    await page.locator('#videoLink').click();
    await page.waitForURL(`**/demo2/video?id=${config.task_ids.t1}`);
    await page.locator('#identityLink:not([hidden])').waitFor();
    assert.match(await page.locator('#identitySummary').innerText(), /已确认学生/);
    await capture(page, '320_return_video_workspace');
    await page.locator('#identityLink').click();
    await page.waitForURL(`**/demo2/identity?task_id=${config.task_ids.t1}`);
    await page.locator('#drawButton:not([disabled])').waitFor();
    record('identity_to_video_workspace_and_back', { stub_video_playback_not_validated: true });
    let before = await workspace(page);
    await drawBox(page, context, 320);
    if (!await page.locator('#annotationAdvanced').evaluate(node=>node.open)) await page.locator('#annotationAdvanced summary').click();
    await page.locator('#personRole').selectOption('unknown');
    assert.equal(await page.locator('#saveBinding').isDisabled(), false);
    const fresh = await guardedControl(page, 'refresh_revision');
    assert.notEqual(fresh.frame_revision, before.frame_revision);
    let responseEvent = page.waitForResponse(response => response.request().method() === 'POST'
      && new URL(response.url()).pathname === `${api}/bindings`);
    await page.locator('#saveBinding').click();
    let response = await responseEvent;
    assert.equal(response.status(), 409);
    assert.equal((await response.json()).error.code, 'stale_frame_revision');
    assert.equal((await workspace(page)).bindings.length, before.bindings.length);
    await page.locator('#pageMessage.error').waitFor();
    assert.equal(await page.locator('#saveBinding').isDisabled(), true);
    await capture(page, '320_stale_revision_rejected');
    page.once('dialog', dialog => dialog.accept());
    await page.locator('#refreshWorkspace').click();
    await page.locator('#drawButton:not([disabled])').waitFor();
    await page.locator('label:has(#recordsAll)').click();
    assert.match(await page.locator('#bindingList').innerText(), /历史版本/);
    record('stale_page_submit_409_no_binding_side_effect');
    before = await workspace(page);
    await drawBox(page, context, 320);
    if (!await page.locator('#annotationAdvanced').evaluate(node=>node.open)) await page.locator('#annotationAdvanced summary').click();
    await page.locator('#personRole').selectOption('unknown');
    assert.equal(await page.locator('#saveBinding').isDisabled(), false);
    await guardedControl(page, 'expire');
    responseEvent = page.waitForResponse(response => response.request().method() === 'POST'
      && new URL(response.url()).pathname === `${api}/bindings`);
    await page.locator('#saveBinding').click();
    response = await responseEvent;
    assert.equal(response.status(), 410);
    assert.equal((await workspace(page)).bindings.length, before.bindings.length);
    await page.locator('#pageMessage.error').waitFor();
    assert.equal(await page.locator('#saveBinding').isDisabled(), true);
    await capture(page, '320_expired_during_confirmation');
    page.once('dialog', dialog => dialog.accept());
    await page.locator('#refreshWorkspace').click();
    await page.locator('#refreshWorkspace:not([disabled])').waitFor();
    await page.locator('#frameSurface').waitFor({ state: 'hidden' });
    assert.equal(await page.locator('#drawButton').isDisabled(), true);
    assert.equal(await page.locator('#bboxX').isDisabled(), true);
    assert.match(await page.locator('#frameEmpty').innerText(), /不可用|到期/);
    await capture(page, '320_expired_refresh_read_only');
    record('expired_page_submit_410_no_binding_refresh_disables_confirmation');
  } catch (error) {
    await page.screenshot({ path: path.join(output, '320_BLOCKED_boundary.png'), fullPage: true }).catch(() => {});
    throw error;
  } finally { await boundedClose(context, 'boundary context'); }
}

async function schoolRepairOnly() {
  const { context, page } = await contextFor(320);
  try {
    await login(page, 't1');
    await page.goto(`${config.base}/demo2/identity?task_id=${encodeURIComponent(config.task_ids.t1)}`);
    await page.locator('#confirmTaskSchool:not([disabled]):not([hidden])').waitFor();
    let data = await workspace(page);
    assert.deepEqual(data.school_context, { city: '', district: '', school_name: '' });
    assert.deepEqual(data.bindings, []);
    assert.equal(data.needs_school_confirmation, true);
    assert.equal(data.can_confirm_school, true);
    assert.equal(data.can_edit, false);
    assert.equal(await page.locator('#saveBinding').isDisabled(), true);
    const rosterResponse = await page.request.get(`${config.base}${api}/roster`);
    assert.equal(rosterResponse.status(), 200);
    const roster = (await rosterResponse.json()).roster;
    assert.deepEqual(roster.school_context, config.school_context);
    for (const [id, key] of [['confirmationCity', 'city'], ['confirmationDistrict', 'district'], ['confirmationSchoolName', 'school_name']]) {
      assert.equal(await page.locator(`#${id}`).innerText(), config.school_context[key]);
    }
    await capture(page, '320_school_repair_01_full_school_confirmation');
    record('school_repair_empty_snapshot_readonly_full_city_district_school');
    let confirmationText = '';
    page.once('dialog', async dialog => { confirmationText = dialog.message(); await dialog.accept(); });
    const repairedEvent = page.waitForResponse(response => response.request().method() === 'POST'
      && new URL(response.url()).pathname === `${api}/task-school`);
    await page.locator('#confirmTaskSchool').click();
    const repaired = await repairedEvent;
    assert.equal(repaired.status(), 200);
    assert.deepEqual(repaired.request().postDataJSON(), { task_id: config.task_ids.t1,
      expected_scope_key: roster.scope_key, confirmed: true });
    for (const value of Object.values(config.school_context)) assert.ok(confirmationText.includes(value));
    data = (await repaired.json()).workspace;
    assert.deepEqual(data.school_context, config.school_context);
    assert.equal(data.scope_key, roster.scope_key);
    assert.equal(data.needs_school_confirmation, false);
    assert.equal(data.can_edit, true);
    await page.locator('#drawButton:not([disabled])').waitFor();
    await page.locator('#schoolConfirmation').waitFor({ state: 'hidden' });
    await capture(page, '320_school_repair_02_snapshot_restored');
    record('school_repair_real_ui_post_restores_snapshot_and_editing');
    if (!await page.locator('#annotationAdvanced').evaluate(node=>node.open)) await page.locator('#annotationAdvanced summary').click();
    for (const [id, value] of [['bboxX', '15'], ['bboxY', '20'], ['bboxWidth', '20'], ['bboxHeight', '60']]) await page.locator(`#${id}`).fill(value);
    const binding = await save(page, 'student', config.students.t1[0].student_id);
    await page.reload();
    await page.locator('#drawButton:not([disabled])').waitFor();
    data = await workspace(page);
    assert.deepEqual(data.school_context, config.school_context);
    assert.equal(data.bindings.length, 1);
    assert.equal(data.bindings[0].binding_id, binding.binding_id);
    assert.equal(data.bindings[0].student_id, config.students.t1[0].student_id);
    const ordering = await page.evaluate(() => {
      const form = document.getElementById('bindingForm').getBoundingClientRect();
      const records = document.querySelector('.frame-records').getBoundingClientRect();
      return { form_bottom: form.bottom, records_top: records.top };
    });
    assert.ok(ordering.form_bottom <= ordering.records_top + 1, '320px confirmation form must precede saved records');
    await capture(page, '320_school_repair_03_binding_and_form_before_records');
    record('school_repair_binding_persists_form_precedes_records', { ordering });
    await guardedControl(page, 'expire');
    await page.locator('#refreshWorkspace').click();
    await page.locator('#refreshWorkspace:not([disabled])').waitFor();
    await page.locator('#frameSurface').waitFor({ state: 'hidden' });
    assert.equal(await page.locator('#saveBinding').isDisabled(), true);
    assert.equal(await page.locator('#retryDetection').isDisabled(), true);
    const detectionStatus = await page.locator('#detectionStatus').innerText();
    assert.doesNotMatch(detectionStatus, /正在读取|正在检测|读取采样帧后显示候选/);
    assert.match(detectionStatus, /不可用|停止|无法|到期/);
    assert.equal((await workspace(page)).bindings.length, 1);
    await capture(page, '320_school_repair_04_expired_status_settled');
    record('school_repair_expired_status_not_stuck_loading', { detection_status: detectionStatus });
  } catch (error) {
    await page.screenshot({ path: path.join(output, '320_BLOCKED_school_repair.png'), fullPage: true }).catch(() => {});
    throw error;
  } finally { await boundedClose(context, 'school repair context'); }
}

(async () => {
  try {
    browser = await chromium.launch({ channel: 'msedge', headless: true });
    const guard = await browser.newContext();
    try {
      const response = await guard.request.get(`${config.base}/__identity_qa__/health`, { headers: { 'X-Identity-QA': config.guard } });
      assert.equal(response.status(), 200);
      assert.equal((await response.json()).isolated_identity_qa, true);
    } finally { await boundedClose(guard, 'guard context'); }
    record('fresh_isolated_server_guard');
    if (config.school_repair_only) {
      await schoolRepairOnly();
    } else {
      let students;
      for (const width of report.widths) students = await runWidth(width, students);
      for (const alias of ['t2', 'member']) {
      const { context, page } = await contextFor(1440);
      try {
        await login(page, alias);
        const response = await page.request.get(`${config.base}${api}/workspace?task_id=${encodeURIComponent(config.task_ids.t1)}`);
        assert.equal(response.status(), alias === 't2' ? 404 : 403);
        if (alias === 't2') {
          const own = await workspace(page, config.task_ids.t2);
          assert.deepEqual(own.students, []);
          assert.deepEqual(own.bindings, []);
        }
        record(`${alias}_cannot_read_t1_identity`);
      } finally { await boundedClose(context, `${alias} context`); }
      }
      await revisionExpiryAndVideoReturn();
    }
    assert.deepEqual(report.page_errors, []);
    assert.deepEqual(report.external_requests, []);
    assert.deepEqual(report.server_errors, []);
    report.ok = true;
  } catch (error) {
    report.ok = false;
    report.failure = { name: error.name, message: error.message, stack: error.stack };
    process.exitCode = 1;
  } finally {
    report.functional_ok = report.ok === true;
    checkpoint();
    if (browser) await boundedClose(browser, 'browser');
    report.cleanup_complete = report.cleanup.every(item => item.closed === true);
    if (!report.cleanup_complete) { report.ok = false; process.exitCode = 1; }
    report.completed = true;
    checkpoint();
    process.stdout.write(JSON.stringify({ ok: report.ok, check_groups: report.checks.length,
      failure: report.failure?.message, report: path.join(output, 'browser_report.json') }) + '\n');
  }
})();
