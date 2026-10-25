// Read-only browser acceptance of the recovered entry; secrets stay in memory.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const runtime = path.join(root, '.runtime');
const read = name => JSON.parse(fs.readFileSync(path.join(runtime, name), 'utf8').replace(/^\uFEFF/, ''));
const state = read('manager_share_state.json');
const manifest = read('pilot_acceptance_20261016/latest.json');
const report = { origin: state.origin, checked_at: new Date().toISOString(),
  accounts: [], admin: {}, page_errors: [], new_uploads: 0, passed: false };
const output = path.join(runtime, process.env.REHAB_ACCEPTANCE_OUTPUT || 'recovered_entry_acceptance_20261017.json');
const check = (value, code) => { if (!value) { const error = new Error(code); error.safeCode = code; throw error; } };
let step = 'preflight';

(async () => {
  const markdown = fs.readFileSync(path.join(runtime, 'demo2_pilot_accounts_20260908.md'), 'utf8');
  const accounts = ['t1', 't2', 't3', 't4'].map(username => {
    const row = markdown.split(/\r?\n/).map(line => line.split('|').map(s => s.trim())).find(row => row[2] === username);
    check(row && row[3], 'school_credentials_missing');
    return { username, password: row[3] };
  });
  const admin = read('admin_credentials_20261016.json');
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  async function enter(user, isAdmin = false) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const page = await context.newPage();
    page.setDefaultTimeout(45000);
    page.on('pageerror', error => report.page_errors.push({ step, type: error.name }));
    await page.goto(state.invite_url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForURL(state.origin + '/demo2/login');
    check(new URL(page.url()).hash === '', 'invitation_fragment_not_removed');
    if (isAdmin) await page.locator('#adminRole').click();
    await page.locator('#username').fill(user.username);
    await page.locator('#password').fill(user.password);
    await page.locator('#loginButton').click();
    await page.waitForURL(isAdmin ? state.origin + '/demo2/admin' : state.origin + '/demo2/school');
    const response = await context.request.get(state.origin + '/api/v1/demo2/auth/me');
    check(response.status() === 200 && (await response.json()).account.role === (isAdmin ? 'company_admin' : 'school_uploader'), 'role_login_failed');
    return { context, page };
  }
  try {
    for (const user of accounts) {
      step = user.username + '_login_and_existing_task';
      const { context, page } = await enter(user);
      try {
        const result = { account: user.username, login: true, pages: [], task: false, evidence: false,
          identity: false, media_range: false, admin_denied: false };
        let item = manifest.accounts.find(item => item.user === user.username);
        if (process.env.REHAB_ACCEPTANCE_FRESH_T1 === '1' && user.username === 't1') {
          const recent = read('browser_upload_acceptance_20261020/report.json');
          const fixture = path.join(runtime, 'upload_reliability_20261020/run_20261020_141329_f0654096/SYNTHETIC-six-seconds-transport.mp4');
          check(recent.passed === true, 'fresh_browser_upload_not_passed');
          item = { ...item, task_id: recent.task_id, sha256: crypto.createHash('sha256').update(fs.readFileSync(fixture)).digest('hex') };
        }
        check(item && /^[a-f0-9]{64}$/.test(item.sha256), 'synthetic_task_manifest_missing');
        const rosterReply = await context.request.get(state.origin + '/api/v1/demo2/identity/roster');
        const rosterPayload = await rosterReply.json();
        const students = rosterPayload.roster?.students || rosterPayload.students || [];
        result.student_dossier_coverage = students.length ? 'existing_authorized_student' : 'no_existing_student_to_open';
        const extraPages = process.env.REHAB_ACCEPTANCE_ALL_PAGES === '1' && user.username === 't1' ? [
          '/demo2/school', '/demo2/course-dossier?task_id=' + item.task_id, '/demo2/student-summary',
          '/demo2/course-batch?task_id=' + item.task_id, '/demo2/teaching-support?task_id=' + item.task_id, '/demo2/measurement',
          '/demo2/evaluation?task_id=' + item.task_id, '/demo2/safety?task_id=' + item.task_id, '/demo2/privacy', '/demo2/capture',
          ...(students.length ? ['/demo2/dossier?student_id=' + encodeURIComponent(students[0].student_id)] : []),
        ] : [];
        result.extended_pages_scope = extraPages.length ? 'current_school_task' : 'not_tested_requires_school_setup';
        for (const route of [...extraPages, '/demo2/upload', '/demo2/students', '/demo2/video?id=' + item.task_id,
          '/demo2/analysis?task_id=' + item.task_id, '/demo2/identity?task_id=' + item.task_id]) {
          report.current_route = new URL(route, state.origin).pathname;
          const response = await page.goto(state.origin + route, { waitUntil: 'domcontentloaded' });
          report.current_status = response.status();
          check(response.status() === 200, 'page_unavailable');
          result.pages.push(new URL(route, state.origin).pathname);
        }
        const get = relative => context.request.get(state.origin + relative, { timeout: 45000 });
        const task = await get('/api/v1/demo2/upload/task?id=' + item.task_id);
        check(task.status() === 200 && (await task.json()).task.sha256 === item.sha256, 'saved_task_mismatch');
        result.task = true;
        const evidence = await get('/api/v1/demo2/upload/result?id=' + item.task_id);
        check(evidence.status() === 200 && (await evidence.json()).source_sha256 === item.sha256, 'saved_result_mismatch');
        result.evidence = true;
        const identity = await get('/api/v1/demo2/identity/workspace?task_id=' + item.task_id);
        check(identity.status() === 200 && (await identity.json()).workspace.task_id === item.task_id, 'identity_unavailable');
        result.identity = true;
        const media = await context.request.get(state.origin + '/api/v1/demo2/upload/media?id=' + item.task_id + '&asset=source',
          { headers: { Range: 'bytes=0-1023' }, timeout: 45000 });
        check(media.status() === 206 && (await media.body()).length === 1024, 'video_range_unavailable');
        result.media_range = true;
        const denied = await get('/api/v1/demo2/admin/summary');
        check(denied.status() === 403, 'teacher_admin_access_exposed');
        result.admin_denied = true;
        const other = manifest.accounts.find(row => row.user !== user.username);
        const otherTask = await get('/api/v1/demo2/upload/task?id=' + other.task_id);
        check([403,404].includes(otherTask.status()), 'cross_channel_task_exposed');
        result.other_channel_denied = true;
        report.accounts.push(result);
      } finally { await context.close(); }
    }
    step = 'company_admin';
    const { context, page } = await enter(admin, true);
    try {
      const response = await context.request.get(state.origin + '/api/v1/demo2/admin/summary');
      check(response.status() === 200, 'admin_summary_unavailable');
      const summary = (await response.json()).summary;
      for (const item of manifest.accounts) check(summary.recent_uploads.some(task => task.task_id === item.task_id), 'admin_cannot_find_channel_task');
      report.admin = { login: true, four_channel_tasks_visible: true, pages: [], downloads: [] };
      for (const route of ['/demo2/admin/channels', '/demo2/admin/dossiers', '/demo2/admin/student-summaries',
        ...(process.env.REHAB_ACCEPTANCE_ALL_PAGES === '1' ? ['/demo2/admin/measurements'] : [])]) {
        const response = await page.goto(state.origin + route, { waitUntil: 'domcontentloaded' });
        check(response.status() === 200, 'admin_page_unavailable');
        report.admin.pages.push(route);
      }
      for (const item of manifest.accounts) {
        const source = await context.request.get(state.origin + '/api/v1/demo2/upload/media?id=' + item.task_id + '&asset=source', { timeout: 60000 });
        check(source.status() === 200, 'admin_download_failed');
        const bytes = await source.body();
        check(crypto.createHash('sha256').update(bytes).digest('hex') === item.sha256, 'admin_download_hash_mismatch');
        report.admin.downloads.push({ channel: item.user, original_source_hash_matched: true, bytes: bytes.length });
      }
      const anon = await browser.newContext();
      const denied = await anon.request.get(state.origin + '/api/v1/demo2/admin/summary');
      check([401,403].includes(denied.status()), 'anonymous_not_blocked');
      await anon.close();
      report.anonymous_denied = true;
    } finally { await context.close(); }
    check(report.page_errors.length === 0, 'browser_script_errors');
    report.passed = report.accounts.length === 4;
  } finally { await browser.close(); }
})().catch(error => {
  report.failure = { step, code: error.safeCode || 'browser_or_network_failure', type: error.name };
  process.exitCode = 1;
}).finally(() => {
  fs.writeFileSync(output, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
});
