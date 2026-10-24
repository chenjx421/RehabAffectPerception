// Private acceptance for the three user-designated source videos.
// Reads local credentials only; never prints passwords or invitation secrets.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('playwright');

const ROOT = path.resolve(__dirname, '..');
const ORIGIN = 'https://YOUR_SERVER_IP';
const API = ORIGIN + '/api/v1/demo2';
const CHUNK = 4 * 1024 * 1024;
const OUTPUT = path.join(ROOT, 'output/playwright/full-real-v32-20261022');
const SOURCES = [
  ['math', 'C:/Path/To/Developer/Desktop/3名不同障碍类型学生基础数据/课堂视频/数学/得数是3的加法 Student D-学生机.mp4'],
  ['chinese', 'C:/Path/To/Developer/Desktop/3名不同障碍类型学生基础数据/课堂视频/语文/3.操场上4.28-学生机.mp4'],
  ['lesson', 'C:/Path/To/Developer/Desktop/杂七杂八/教学视频.mp4'],
];

const report = {
  scope: 'three original user-designated videos; complete WAN upload and worker processing',
  uploads: [], checks: [], passed: false,
};
const check = (value, code) => {
  if (!value) throw new Error(code);
  report.checks.push(code);
};

function readCredentials() {
  const invitation = fs.readFileSync(path.join(ROOT, '.runtime/cloud_deploy_20261020/cloud_invitation.private.txt'), 'utf8');
  const invitationMatch = invitation.match(/\/invite#([^\s<>"']+)/);
  check(Boolean(invitationMatch), 'private_invitation_loaded');
  const rows = fs.readFileSync(path.join(ROOT, '.runtime/demo2_pilot_accounts_20260908.md'), 'utf8')
    .split(/\r?\n/)
    .map(line => line.split('|').map(value => value.trim()))
    .filter(row => /^t[1-4]$/.test(row[2] || ''));
  check(rows.length > 0, 'school_account_loaded');
  const token = invitationMatch[1].startsWith('secret=')
    ? new URLSearchParams(invitationMatch[1]).get('secret')
    : decodeURIComponent(invitationMatch[1]);
  return { secret: token, username: rows[0][2], password: rows[0][3] };
}

async function json(response, code) {
  check(response.ok(), code + '_http_' + response.status());
  return response.json();
}

async function uploadFile(context, channel, course, label, file) {
  const stat = fs.statSync(file);
  const totalChunks = Math.ceil(stat.size / CHUNK);
  const created = await json(await context.request.post(API + '/upload/tasks', {
    data: {
      channel_id: channel.channel_id,
      course_id: course,
      course_name: '三段原始视频完整验收-' + label,
      session_id: course,
      uploader_name: 'Authorized full real-video acceptance',
      filename: path.basename(file),
      mime_type: 'video/mp4',
      byte_size: stat.size,
      total_chunks: totalChunks,
      security_confirmed: true,
      allow_company_archive: false,
    },
  }), label + '_task');
  const taskId = created.task.task_id;
  const hash = crypto.createHash('sha256');
  const handle = fs.openSync(file, 'r');
  const buffer = Buffer.alloc(CHUNK);
  let offset = 0;
  let index = 0;
  let lastLog = Date.now();
  const started = Date.now();
  try {
    while (offset < stat.size) {
      const read = fs.readSync(handle, buffer, 0, Math.min(CHUNK, stat.size - offset), offset);
      const block = Buffer.from(buffer.subarray(0, read));
      hash.update(block);
      const response = await context.request.post(
        API + '/upload/chunks?task_id=' + encodeURIComponent(taskId)
          + '&course_id=' + encodeURIComponent(course)
          + '&chunk_index=' + index,
        { data: block, headers: { 'Content-Type': 'application/octet-stream' }, timeout: 330000 },
      );
      check(response.ok(), label + '_chunk_' + index);
      offset += read;
      index += 1;
      if (Date.now() - lastLog >= 15000 || offset === stat.size) {
        console.log(JSON.stringify({ label, stage: 'upload', mib: +(offset / 1048576).toFixed(1), total_mib: +(stat.size / 1048576).toFixed(1), chunks: index, total_chunks: totalChunks }));
        lastLog = Date.now();
      }
    }
  } finally {
    fs.closeSync(handle);
  }
  const sha256 = hash.digest('hex');
  report.uploads.push({ label, task_id: taskId, source: file, bytes: stat.size, total_chunks: totalChunks, sha256, upload_seconds: +((Date.now() - started) / 1000).toFixed(2) });
  return report.uploads[report.uploads.length - 1];
}

async function pollReady(context) {
  const deadline = Date.now() + 70 * 60 * 1000;
  while (Date.now() < deadline) {
    let allReady = true;
    for (const item of report.uploads) {
      const payload = await json(await context.request.get(API + '/upload/task?id=' + encodeURIComponent(item.task_id), { timeout: 60000 }), item.label + '_poll');
      const task = payload.task;
      item.analysis_status = task.analysis_status;
      item.processing_stage = task.processing_stage;
      item.processing_progress = task.processing_progress;
      if (task.analysis_status === 'failed' || task.analysis_status === 'cancelled') {
        throw new Error(item.label + '_processing_failed');
      }
      if (!['evidence_ready', 'completed'].includes(task.analysis_status)) allReady = false;
    }
    if (allReady) return;
    await new Promise(resolve => setTimeout(resolve, 10000));
  }
  throw new Error('full_real_video_worker_timeout');
}

async function verifyResult(context, item, page) {
  const payload = await json(await context.request.get(API + '/simple-result?task_id=' + encodeURIComponent(item.task_id), { timeout: 60000 }), item.label + '_simple_result');
  const analysis = payload.analysis;
  check(analysis.analysis_version === 'simple_student_seats_v3_2', item.label + '_latest_analysis_version');
  check(Array.isArray(analysis.persons) && analysis.persons.length === 3, item.label + '_three_persons');
  check(analysis.persons.every(person => person.windows?.length > 0), item.label + '_timelines_present');
  check(analysis.persons.every(person => typeof person.average_score === 'number'), item.label + '_scores_present');
  check(analysis.persons.every(person => person.windows.some(window => typeof window.score === 'number')), item.label + '_window_scores_present');
  check(typeof analysis.lesson_report?.text === 'string' && analysis.lesson_report.text.length >= 300, item.label + '_report_300_chars');
  const signatures = analysis.persons.map(person => JSON.stringify(person.windows.map(window => ({
    state: window.state, label: window.state_zh, score: window.score, movement: window.movement,
    frame: window.frame, bbox: window.bbox,
  }))));
  check(new Set(signatures).size === 3, item.label + '_person_results_differ');
  const firstBoxes = analysis.persons.map(person => JSON.stringify(person.windows.find(window => window.bbox)?.bbox || null));
  check(new Set(firstBoxes).size === 3, item.label + '_person_boxes_differ');
  item.duration_sec = payload.task?.duration_sec || payload.task?.media?.duration_sec || null;
  item.analysis = {
    version: analysis.analysis_version,
    person_count: analysis.persons.length,
    timeline_windows: analysis.persons.map(person => person.windows.length),
    scores: analysis.persons.map(person => person.average_score),
    states: analysis.persons.map(person => person.dominant_state_zh),
    report_chars: analysis.lesson_report.text.length,
  };

  const downloadUrl = payload.task?.secure_result_download_url || payload.task?.result_download_url || ('/api/v1/demo2/upload/result?id=' + item.task_id);
  const downloaded = await json(await context.request.get(ORIGIN + downloadUrl, { timeout: 60000 }), item.label + '_result_download');
  check(downloaded.task_id === item.task_id, item.label + '_download_task_matches');
  check(downloaded.source_sha256 === item.sha256, item.label + '_download_source_hash_matches');
  check(downloaded.simple_student_analysis?.analysis_version === 'simple_student_seats_v3_2', item.label + '_download_version_matches');
  check(downloaded.simple_student_analysis?.lesson_report?.text?.length >= 300, item.label + '_download_report_matches');
  item.download = { ok: true, source_sha256_matches: true, version_matches: true, report_chars: downloaded.simple_student_analysis.lesson_report.text.length };

  const errors = [];
  page.on('pageerror', error => errors.push(error.name));
  await page.goto(ORIGIN + '/demo2/simple-result?task_id=' + encodeURIComponent(item.task_id), { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.locator('#personTabs .person-tab').first().waitFor({ timeout: 60000 });
  await page.waitForFunction(() => [...document.querySelectorAll('#personTabs img')].every(image => image.complete && image.naturalWidth > 0));
  check(await page.locator('#personTabs .person-tab').count() === 3, item.label + '_browser_three_tabs');
  check((await page.locator('#lessonReportText').innerText()).length >= 300, item.label + '_browser_report_visible');
  const states = [];
  for (let index = 0; index < 3; index += 1) {
    await page.locator('#personTabs .person-tab').nth(index).click();
    await page.waitForFunction(() => document.querySelector('.hero-frame')?.complete && document.querySelector('.hero-frame')?.naturalWidth > 0);
    const image = page.locator('.hero-frame');
    const src = await image.getAttribute('src');
    check(Boolean(src && src.includes('crop=person')), item.label + '_browser_person_' + (index + 1) + '_crop');
    const text = await page.locator('.timeline').innerText();
    states.push(text);
    await page.locator('#personPanel').screenshot({ path: path.join(OUTPUT, item.label + '-person-' + (index + 1) + '.png') });
  }
  check(new Set(states).size === 3, item.label + '_browser_timeline_text_differs');
  check(errors.length === 0, item.label + '_browser_no_page_errors');
  await page.screenshot({ path: path.join(OUTPUT, item.label + '-result-overview.png'), fullPage: true });
  item.browser = { result_page: true, person_tabs: 3, screenshots: 4, timeline_texts_differ: true, page_errors: 0 };
}

async function main() {
  fs.mkdirSync(OUTPUT, { recursive: true });
  const credentials = readCredentials();
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, extraHTTPHeaders: { Origin: ORIGIN } });
  try {
    let response = await context.request.post(ORIGIN + '/__manager/authorize', { data: { secret: credentials.secret } });
    check(response.ok(), 'invitation_authorized');
    response = await context.request.post(API + '/auth/login', { data: { username: credentials.username, password: credentials.password, role: 'school_uploader' } });
    check(response.ok(), 'school_login');
    const course = 'full-real-v32-20261022-' + crypto.randomBytes(5).toString('hex');
    const workspace = await json(await context.request.get(API + '/upload/workspace?course_id=' + course), 'workspace');
    check(Boolean(workspace.workspace?.channel?.channel_id), 'channel_available');
    for (const [label, source] of SOURCES) {
      const file = path.resolve(source);
      check(fs.statSync(file).isFile(), label + '_source_exists');
      await uploadFile(context, workspace.workspace.channel, course, label, file);
    }
    await pollReady(context);
    const page = await context.newPage();
    for (const item of report.uploads) await verifyResult(context, item, page);
    report.passed = true;
  } finally {
    await context.request.post(API + '/auth/logout', { data: {} }).catch(() => {});
    await browser.close();
    fs.writeFileSync(path.join(OUTPUT, 'acceptance.json'), JSON.stringify(report, null, 2));
  }
  console.log(JSON.stringify(report, null, 2));
}

main().catch(error => {
  report.failure = /^[a-z0-9_]+$/.test(error.message) ? error.message : 'full_real_video_acceptance_failed';
  fs.mkdirSync(OUTPUT, { recursive: true });
  fs.writeFileSync(path.join(OUTPUT, 'acceptance.json'), JSON.stringify(report, null, 2));
  console.error(JSON.stringify(report, null, 2));
  process.exitCode = 1;
});
