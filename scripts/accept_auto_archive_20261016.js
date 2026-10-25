/* HTTP + browser lifecycle using generated test patterns, not student images. */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');

(async () => {
  const base = process.env.SUMMARY_ACCEPTANCE_BASE, output = process.env.SUMMARY_ACCEPTANCE_OUTPUT;
  const student = process.env.SUMMARY_ACCEPTANCE_STUDENT, prefix = '/api/v1/demo2';
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const contexts = {}, errors = [];
  try {
    for (const role of ['teacher', 'admin']) {
      const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
      await context.addCookies([{ name: 'rehab_demo2_session', value: process.env['SUMMARY_ACCEPTANCE_' + role.toUpperCase()], url: base }]);
      const invited = await context.request.post(base + '/__manager/authorize', {
        data: { secret: process.env.SUMMARY_ACCEPTANCE_INVITE }, headers: { Origin: base }, maxRedirects: 0 });
      assert.equal(invited.status(), 303);
      const signed = invited.headers()['set-cookie'].split(';', 1)[0].split('=', 2);
      await context.addCookies([{ name: signed[0], value: signed[1], url: base }]);
      contexts[role] = context;
    }
    async function api(route, data, role = 'teacher') {
      const response = await contexts[role].request.fetch(base + prefix + route, {
        method: data === undefined ? 'GET' : 'POST', ...(data === undefined ? {} : { data }), headers: { Origin: base }
      });
      const result = await response.json();
      assert(response.ok(), 'Synthetic API failed: ' + route + ' ' + JSON.stringify(result));
      return result;
    }
    const teacher = await contexts.teacher.newPage();
    teacher.on('pageerror', error => errors.push(error.message));
    teacher.on('dialog', dialog => dialog.accept());
    await teacher.goto(base + '/demo2/student-summary?student_id=' + student);
    await teacher.locator('#studentName').filter({ hasText: '合成测试学生' }).waitFor();
    await teacher.locator('#studentVerified').check();
    await teacher.locator('#authorizationReference').fill('SYNTHETIC permission for educational followup');
    await teacher.locator('#authorizationConfirmed').check();
    await teacher.locator('#authorizationForm button[type=submit]').click();
    await teacher.locator('#reviewConfirmed').check();
    await teacher.locator('#commitButton').click();
    await teacher.locator('#authorizationStatus').filter({ hasText: '授权有效' }).waitFor();
    await teacher.locator('#studentVerified').check();
    await teacher.locator('#autoEnabled').check();
    await teacher.locator('#automaticForm button[type=submit]').click();
    await teacher.locator('#reviewConfirmed').check();
    await teacher.locator('#commitButton').click();
    await teacher.waitForFunction(() => !document.querySelector('#reloadButton').disabled);
    let workspace = (await api('/student-summaries/student?student_id=' + student)).workspace;
    assert.equal(workspace.authorization.automatic_archiving.enabled, true);
    const content = fs.readFileSync(process.env.SUMMARY_ACCEPTANCE_VIDEO);
    async function uploadAndBind(number) {
      const task = (await api('/upload/tasks', { course_id: 'synthetic-auto-' + number, course_name: 'SYNTHETIC COURSE ' + number,
        session_id: 'synthetic-auto-' + number, uploader_name: 'SYNTHETIC OPERATOR', channel_id: 'channel_1',
        filename: 'generated-test-pattern.mp4', byte_size: content.length, total_chunks: 1, mime_type: 'video/mp4',
        security_confirmed: true, allow_company_archive: false })).task;
      await api('/upload/chunks', { task_id: task.task_id, course_id: task.course_id, chunk_index: 0, content_base64: content.toString('base64') });
      let ready;
      for (let attempt = 0; attempt < 60; attempt++) {
        ready = (await api('/upload/task?id=' + task.task_id)).task;
        if (ready.analysis_status === 'evidence_ready') break;
        assert.notEqual(ready.analysis_status, 'failed');
        await new Promise(resolve => setTimeout(resolve, 500));
      }
      assert.equal(ready.analysis_status, 'evidence_ready');
      const identity = (await api('/identity/workspace?task_id=' + task.task_id)).workspace;
      const binding = (await api('/identity/bindings', { task_id: task.task_id, frame_key: identity.frames[0].frame_key,
        frame_revision: identity.frame_revision, role: 'student', student_id: student,
        bbox: { x: 0.1, y: 0.1, width: 0.3, height: 0.4 } })).binding;
      return { task, binding };
    }
    const first = await uploadAndBind(1);
    const second = await uploadAndBind(2);
    workspace = (await api('/student-summaries/student?student_id=' + student)).workspace;
    assert.equal(workspace.snapshots.length, 0, 'No manual snapshot should be needed');
    assert.equal(workspace.course_history.length, 2);
    assert(workspace.course_history.every(row => row.status === 'pending_review' && row.measurements.length === 0));
    const ids = workspace.course_history.map(row => row.entry_id).sort();
    for (let attempt = 0; attempt < 3; attempt++) await api('/student-summaries/student?student_id=' + student);
    assert.deepEqual((await api('/student-summaries/student?student_id=' + student)).workspace.course_history.map(row => row.entry_id).sort(), ids);

    const suitability = (await api('/applicability?task_id=' + second.task.task_id)).result;
    await api('/applicability', { task_id: second.task.task_id, version: suitability.version, revision: suitability.revision,
      category: 'special', goal: 'Synthetic engineering fixture only; no educational validation',
      reason: 'Synthetic fixture scope for integration assertions, not a real classroom', confirmed: true });
    const measured = await api('/measurements', { record_id: 'synthetic-auto-measurement', expected_version: 0,
      student_id: student, lesson_date: new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Shanghai' }),
      lesson_id: 'synthetic-auto-2', course_name: 'SYNTHETIC COURSE 2', goal_id: 'synthetic-match', measurement_context: 'classroom',
      criterion: 'Synthetic two-shape criterion', evidence: 'SYNTHETIC engineering evidence only',
      scores: { accuracy: 8, independence: 7, consistency: 6, transfer: 5 }, opportunities: 3, observed: 2,
      reviewed: true, source_type: 'video_review', task_id: second.task.task_id, start_sec: 0, end_sec: 3 });
    assert.equal(measured.archive_sync.status, 'synced');
    workspace = (await api('/student-summaries/student?student_id=' + student)).workspace;
    assert.equal(workspace.course_history.length, 2);
    assert(workspace.course_history.some(row => row.status === 'reviewed' && row.measurements.length === 1));
    assert.deepEqual(workspace.course_history.map(row => row.entry_id).sort(), ids);
    await teacher.reload();
    await teacher.locator('#courseHistoryList').filter({ hasText: '6.85' }).waitFor();
    await teacher.screenshot({ path: path.join(output, 'teacher-course-history-desktop.png'), fullPage: true });

    const admin = await contexts.admin.newPage();
    admin.on('pageerror', error => errors.push(error.message));
    await admin.goto(base + '/demo2/admin/student-summaries');
    await admin.locator('#archiveRows button').first().click();
    await admin.locator('#detailCourseHistory').filter({ hasText: '6.85' }).waitFor();
    const downloadPromise = admin.waitForEvent('download');
    await admin.locator('#exportButton').click();
    const download = await downloadPromise;
    const text = fs.readFileSync(await download.path(), 'utf8'), exported = JSON.parse(text);
    assert.equal(exported.course_history.length, 2);
    for (const secret of [student, first.task.task_id, second.task.task_id, 'SYNTHETIC-001', '合成测试学生', 'SYNTHETIC engineering evidence only']) assert(!text.includes(secret));
    await admin.screenshot({ path: path.join(output, 'company-course-history-desktop.png'), fullPage: true });
    for (const [name, page] of [['teacher', teacher], ['company', admin]]) {
      await page.setViewportSize({ width: 390, height: 844 });
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      await page.screenshot({ path: path.join(output, name + '-course-history-mobile.png'), fullPage: true });
    }
    await api('/measurements/withdraw', { record_id: measured.record.record_id, expected_version: measured.record.version, reason: 'Synthetic invalidation check' });
    workspace = (await api('/student-summaries/student?student_id=' + student)).workspace;
    assert(workspace.course_history.every(row => row.measurements.length === 0));
    await api('/identity/bindings/revoke', { task_id: first.task.task_id, binding_id: first.binding.binding_id, reason: 'Synthetic identity invalidation' });
    workspace = (await api('/student-summaries/student?student_id=' + student)).workspace;
    assert(workspace.course_history.some(row => row.status === 'source_withheld'));
    await api('/student-summaries/authorization/withdraw', { student_id: student,
      authorization_id: workspace.authorization.authorization_id, confirmed: true });
    assert.equal((await api('/student-summaries/admin', undefined, 'admin')).workspace.items.length, 0);
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'report.json'), JSON.stringify({ synthetic_only: true,
      real_http_uploads: 2, actual_ffmpeg_processing: true, confirmed_identity_linkage: true,
      no_manual_snapshot_required: true, per_student_course_history: 2, idempotent_sync: true,
      reviewed_measurement_auto_update: true, company_history_export: true, stale_score_withheld: true,
      identity_withdrawal_withheld: true, authorization_withdrawal_denies_access: true,
      mobile_no_overflow: true, browser_errors: errors }, null, 2));
    console.log('Automatic course history acceptance passed with two generated videos.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
