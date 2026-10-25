// Real browser acceptance. Never run live before deployment AND admin rotation approval.
// node scripts/verify_pilot_20261016.js --self-test       (offline, no writes)
// node scripts/verify_pilot_20261016.js --prepare-fixtures (local synthetic files only)
// node scripts/verify_pilot_20261016.js --live-after-deployment-and-admin-change
// node scripts/verify_pilot_20261016.js --verify-existing (read-only supplemental; preserves latest.json)
// Optional --identity-readonly is PARTIAL acceptance, exit 2, never a full pass.
'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { isDeepStrictEqual } = require('node:util');
const { spawnSync } = require('node:child_process');
const root = path.resolve(__dirname, '..');
const output = path.join(root, '.runtime/pilot_acceptance_20261016');
const API = '/api/v1/demo2';
const WINDOW = 300000;
const LIMIT = 20;
const UI_TIMEOUT = 45000;
const USERS = ['t1', 't2', 't3', 't4'];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const readJson = file => JSON.parse(fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, ''));
function check(value, code) { if (!value) { const error = new Error(code); error.checkCode = code; throw error; } }
function school(context) {
  return Object.fromEntries(['city', 'district', 'school_name'].map(key => [key, String(context?.[key] || '')]));
}
function schoolValid(context) { return Object.values(school(context)).every(value => value.trim()); }
function schoolSnapshot(payload) {
  return { context: payload.context, details: payload.details || {} };
}
function retryDelay(header, fallback = 60000, now = Date.now()) {
  const seconds = Number(header);
  const delay = header && Number.isFinite(seconds) ? seconds * 1000 : Date.parse(header || '') - now;
  return Math.max(1000, Number.isFinite(delay) ? delay : fallback) + 1000;
}
function credentials(markdown) {
  return USERS.map(username => {
    const row = markdown.split(/\r?\n/).map(line => line.split('|').map(cell => cell.trim()))
      .find(cells => cells[2] === username);
    check(row && row[3], 'school_credentials_missing');
    return { username, password: row[3] };
  });
}
function liveState(state) {
  const base = new URL(state.origin);
  const invite = new URL(state.invite_url);
  check(base.protocol === 'https:' && !base.username && !base.password && !base.search && !base.hash,
    'public_https_origin_required');
  check(base.pathname === '/' && !['localhost', '127.0.0.1', '[::1]'].includes(base.hostname),
    'public_origin_required');
  check(invite.origin === base.origin && invite.pathname === '/invite' && invite.hash.length > 1
    && !invite.username && !invite.password && !invite.search, 'invitation_origin_or_format_invalid');
  return { base: base.origin, invite: invite.href };
}
function secretValues(accounts, admin, state) {
  const values = [...accounts.map(account => account.password), admin.password, state.invite];
  const fragment = new URL(state.invite).hash.slice(1);
  values.push(fragment, decodeURIComponent(fragment));
  for (const value of new URLSearchParams(fragment).values()) values.push(value);
  return [...new Set(values.filter(Boolean))];
}
function noSecrets(text, secrets) {
  check(!secrets.some(secret => text.includes(secret) || text.includes(encodeURIComponent(secret))), 'secret_in_artifact');
  check(!/"(?:password|cookie|set-cookie|authorization|invite_url|storageState)"\s*:/i.test(text), 'secret_field_in_artifact');
}
async function enterInvitation(page, state, cooldown) {
  for (let attempt = 0; attempt < 4; attempt++) {
    // /invite removes its hash with replaceState. A hash-only goto does NOT rerun its script.
    await page.goto('about:blank');
    let throttled;
    const observe = response => { if (response.status() === 429) throttled = response; };
    page.on('response', observe);
    try {
      const pending = page.waitForResponse(response => {
        const url = new URL(response.url());
        return url.origin === state.base && (response.status() === 429
          || (url.pathname === '/__manager/authorize' && response.request().method() === 'POST'));
      }, { timeout: 60000 });
      const [response] = await Promise.all([pending, page.goto(state.invite, { waitUntil: 'domcontentloaded' })]);
      if (response.status() !== 429) {
        check([200, 303].includes(response.status()), 'invitation_rejected');
        await page.waitForURL(state.base + '/demo2/login', { timeout: 60000 });
        await page.locator('#loginButton').waitFor();
        return;
      }
    } catch (error) { if (!throttled) throw error; }
    finally { page.off('response', observe); }
    check(attempt < 3, 'invitation_429_retry_budget_exhausted');
    await cooldown(throttled, 'invitation', 60000);
  }
}
function ffmpegArgs(index, destination) {
  const args = ['-hide_banner', '-loglevel', 'error', '-nostdin', '-n', '-f', 'lavfi', '-i',
    `testsrc2=size=640x360:rate=24,hue=h=${index * 65}`];
  if (index % 2 === 0) args.push('-f', 'lavfi', '-i', `sine=frequency=${440 + index * 110}:sample_rate=44100`);
  args.push('-t', String(6 + index), '-map', '0:v:0', '-c:v', 'libx264', '-preset', 'ultrafast',
    '-pix_fmt', 'yuv420p');
  if (index % 2 === 0) args.push('-map', '1:a:0', '-c:a', 'aac', '-b:a', '64k');
  else args.push('-an');
  return [...args, '-movflags', '+faststart', destination];
}
function findFfmpeg() {
  const candidates = [process.env.REHAB_FFMPEG, process.env.FFMPEG_PATH, path.join(root, '.tools/ffmpeg.exe'), 'ffmpeg'];
  for (const python of [path.join(root, '.venv/Scripts/python.exe'), 'python']) {
    const result = spawnSync(python, ['-c', 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())'],
      { encoding: 'utf8', windowsHide: true, timeout: 15000 });
    if (result.status === 0) candidates.push(result.stdout.trim());
  }
  for (const candidate of candidates.filter(Boolean)) {
    if (spawnSync(candidate, ['-version'], { windowsHide: true, timeout: 10000, stdio: 'ignore' }).status === 0) return candidate;
  }
  check(false, 'local_ffmpeg_required_set_REHAB_FFMPEG');
}
function fixtures() {
  const ffmpeg = findFfmpeg();
  const directory = path.join(output, 'fixtures');
  fs.mkdirSync(directory, { recursive: true });
  const files = USERS.map((user, index) => {
    const file = path.join(directory, `${user}_synthetic_${index % 2 === 0 ? 'av' : 'noaudio'}.mp4`);
    if (!fs.existsSync(file)) {
      const result = spawnSync(ffmpeg, ffmpegArgs(index, file), { windowsHide: true, timeout: 60000, stdio: 'ignore' });
      check(result.status === 0, 'synthetic_ffmpeg_generation_failed');
    }
    // Decode the cached fixture too; a truncated previous generation must not be uploaded.
    check(spawnSync(ffmpeg, ['-v', 'error', '-xerror', '-i', file, '-f', 'null', '-'],
      { windowsHide: true, timeout: 60000, stdio: 'ignore' }).status === 0, 'synthetic_fixture_decode_failed');
    const bytes = fs.readFileSync(file);
    check(bytes.length > 0 && bytes.length < 4 * 1024 * 1024, 'synthetic_fixture_size_invalid');
    return { file, sha256: hash(bytes), bytes: bytes.length, has_audio: index % 2 === 0, duration: 6 + index };
  });
  check(new Set(files.map(file => file.sha256)).size === 4, 'four_distinct_synthetic_sources_required');
  return files;
}

async function run(identityReadonly, verifyExisting = false) {
  // Read all credentials before browser launch or network I/O. Never fall back to the old admin row.
  const state = liveState(readJson(path.join(root, '.runtime/manager_share_state.json')));
  const accounts = credentials(fs.readFileSync(path.join(root, '.runtime/demo2_pilot_accounts_20260908.md'), 'utf8'));
  const admin = readJson(path.join(root, '.runtime/admin_credentials_20261016.json'));
  check(typeof admin.username === 'string' && admin.username.trim() && typeof admin.password === 'string'
    && admin.password.length > 0, 'new_admin_credentials_required');
  const secrets = secretValues(accounts, admin, state);
  const originalPath = path.join(output, 'latest.json');
  const originalBytes = verifyExisting ? fs.readFileSync(originalPath) : null;
  const original = verifyExisting ? JSON.parse(originalBytes.toString()) : null;
  if (verifyExisting) {
    check(original.base === state.base && original.synthetic_only === true, 'existing_report_origin_or_scope_mismatch');
    check(original.accounts?.length === 4 && USERS.every(user => original.accounts.some(item => item.user === user
      && /^[A-Za-z0-9_-]{1,128}$/.test(item.task_id) && /^[a-f0-9]{64}$/.test(item.sha256))), 'existing_task_manifest_invalid');
  }
  const runId = `${verifyExisting ? 'supplemental-existing' : 'synthetic-pilot'}-20261016-${Date.now()}`;
  const courseId = original?.run || runId;
  const runDir = path.join(output, runId);
  fs.mkdirSync(runDir, { recursive: true });
  const report = { run: runId, base: state.base, started_at: new Date().toISOString(), synthetic_only: true,
    automatic_classroom_scoring: false, identity_mode: identityReadonly ? 'read_only_partial' : 'manual_unknown',
    accounts: [], admin: {}, checks: [], negative_cases: [], failures: [], throttles: [], page_errors: [], blocked_writes: [],
    passed: false, complete: false };
  if (verifyExisting) Object.assign(report, { mode: 'verify_existing_read_only', original_run: original.run,
    original_report_sha256: hash(originalBytes), original_failures_retained: original.failures,
    coverage: 'Existing synthetic tasks, page/download/playback and access-control coverage only; not universal scoring.',
    uploads_created: 0, anonymous: [] });
  let browser;
  let current = 'preflight';
  const budgetPath = path.join(output, 'login_budget.json');
  // This also preserves the rolling budget across sequential invocations. Concurrent runs are forbidden below.
  const lockPath = path.join(output, 'live.lock');
  let lock;
  const save = () => {
    const json = JSON.stringify(report, null, 2);
    noSecrets(json, secrets);
    fs.writeFileSync(path.join(runDir, 'report.json'), json);
    fs.writeFileSync(path.join(output, verifyExisting ? 'supplemental_latest.json' : 'latest.json'), json);
  };
  const step = name => { current = name; console.log(name); };
  const record = (name, evidence = {}) => { report.checks.push({ name, ...evidence }); save(); };
  const failure = error => {
    report.failures.push({ step: current, code: /^[a-zA-Z0-9_]+$/.test(error.checkCode || '')
      ? error.checkCode : error.name === 'TimeoutError' ? 'browser_timeout' : 'operation_failed' });
    save();
  };
  async function cooldown(response, label, fallback) {
    const ms = retryDelay(response.headers()['retry-after'], fallback);
    check(ms <= 10 * 60 * 1000, 'retry_after_exceeds_acceptance_wait_budget');
    report.throttles.push({ operation: label, wait_ms: ms }); save();
    console.log(`HTTP 429: waiting ${Math.ceil(ms / 1000)}s (${label})`);
    await sleep(ms);
  }
  async function budget() {
    let attempts = fs.existsSync(budgetPath) ? readJson(budgetPath) : [];
    check(Array.isArray(attempts) && attempts.every(Number.isFinite), 'invalid_login_budget_journal');
    attempts = attempts.filter(time => time > Date.now() - WINDOW);
    if (attempts.length >= LIMIT) {
      await sleep(Math.max(1000, Math.min(...attempts) + WINDOW - Date.now() + 1000));
      attempts = attempts.filter(time => time > Date.now() - WINDOW);
    }
    attempts.push(Date.now());
    fs.writeFileSync(budgetPath, JSON.stringify(attempts));
  }
  async function contextFor(alias) {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 },
      acceptDownloads: true, serviceWorkers: 'block' });
    // Fail closed on any accidental school/roster edits; never collect a trace, HAR, or storageState.
    await context.route('**/*', async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (['data:', 'blob:'].includes(url.protocol)) return route.continue();
      if (url.origin !== state.base) return route.abort('blockedbyclient');
      if (verifyExisting && !['GET', 'HEAD', 'OPTIONS'].includes(request.method())
        && ![API + '/auth/login', '/__manager/authorize'].includes(url.pathname)) {
        report.blocked_writes.push({ account: alias, path: url.pathname });
        return route.abort('blockedbyclient');
      }
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method()) &&
          ['/school/context', '/identity/students', '/identity/task-school'].some(suffix => url.pathname === API + suffix)) {
        report.blocked_writes.push({ account: alias, path: url.pathname });
        return route.abort('blockedbyclient');
      }
      // Only retry explicitly rejected upload writes. Never replay a timed-out/ambiguous mutation.
      if (request.method() === 'POST' && url.pathname.startsWith(API + '/upload/')) {
        let response;
        try {
          for (let attempt = 0; attempt < 4; attempt++) {
            response = await route.fetch({ timeout: 60000, maxRedirects: 0 });
            if (response.status() !== 429 || attempt === 3) break;
            await cooldown(response, 'upload', 60000);
            await response.dispose();
          }
          await route.fulfill({ response });
        } catch (_) {
          report.failures.push({ step: `${alias}_upload_transport`, code: 'upload_not_replayed_after_transport_failure' });
          await route.abort('failed').catch(() => {});
        } finally { if (response) await response.dispose().catch(() => {}); }
        return;
      }
      return route.continue();
    });
    const page = await context.newPage();
    page.setDefaultTimeout(UI_TIMEOUT);
    page.setDefaultNavigationTimeout(60000);
    page.on('pageerror', () => report.page_errors.push({ account: alias, step: current }));
    return page;
  }
  async function get(page, relative) {
    check(relative.startsWith(API + '/'), 'api_request_must_be_same_origin');
    for (let attempt = 0; attempt < 4; attempt++) {
      // In-page fetch preserves gateway same-origin behavior and uses the real browser session.
      const response = await page.evaluate(async url => {
        const r = await fetch(url, { cache: 'no-store', redirect: 'manual', signal: AbortSignal.timeout(60000) });
        const bytes = new Uint8Array(await r.arrayBuffer());
        let binary = '';
        for (let index = 0; index < bytes.length; index += 8192) binary += String.fromCharCode(...bytes.subarray(index, index + 8192));
        return { status: r.status, body: btoa(binary), type: r.headers.get('content-type') || '',
          retry: r.headers.get('retry-after'), disposition: r.headers.get('content-disposition') || '' };
      }, relative);
      if (response.status !== 429) return { ...response, body: Buffer.from(response.body, 'base64') };
      check(attempt < 3, 'http_429_retry_budget_exhausted');
      await cooldown({ headers: () => ({ 'retry-after': response.retry }) }, 'read', 60000);
    }
  }
  async function json(page, relative) {
    const response = await get(page, relative);
    check(response.status === 200, 'api_read_not_200');
    check(response.type.includes('json'), 'api_read_not_json');
    return JSON.parse(response.body.toString('utf8'));
  }
  async function navigate(page, relative, ready) {
    for (let attempt = 0; attempt < 4; attempt++) {
      let throttled = null;
      const observe = response => { if (response.status() === 429) throttled = response; };
      page.on('response', observe);
      try {
        const response = await page.goto(state.base + relative, { waitUntil: 'domcontentloaded' });
        if (response?.status() === 429) throttled = response;
        else {
          check(response?.status() === 200, 'page_not_200');
          check(new URL(page.url()).pathname === new URL(relative, state.base).pathname, 'unexpected_page_redirect');
          if (ready) await ready();
          return;
        }
      } catch (error) { if (!throttled) throw error; }
      finally { page.off('response', observe); }
      check(attempt < 3, 'page_429_retry_budget_exhausted');
      await cooldown(throttled, 'page', 60000);
    }
  }
  async function invitation(page) {
    return enterInvitation(page, state, cooldown);
  }
  async function login(page, account, isAdmin = false) {
    await invitation(page);
    for (let attempt = 0; attempt < 4; attempt++) {
      await budget();
      if (isAdmin) await page.locator('#adminRole').click();
      await page.locator('#username').fill(account.username);
      await page.locator('#password').fill(account.password);
      const pending = page.waitForResponse(response => new URL(response.url()).pathname === API + '/auth/login'
        && response.request().method() === 'POST');
      const [response] = await Promise.all([pending, page.locator('#loginButton').click()]);
      if (response.status() === 429) {
        check(attempt < 3, 'login_429_retry_budget_exhausted');
        await cooldown(response, 'login', WINDOW);
        continue;
      }
      // A bad password is not retried; only an explicit 429 permits another attempt.
      check(response.status() === 200, 'login_rejected_no_retry');
      await page.waitForURL(state.base + (isAdmin ? '/demo2/admin' : '/demo2/school'));
      return;
    }
  }
  async function download(page, selector, name, validate, project = bytes => bytes) {
    for (let attempt = 0; attempt < 4; attempt++) {
      let throttled = null;
      const observe = response => { if (response.status() === 429) throttled = response; };
      page.on('response', observe);
      try {
        const pending = page.waitForEvent('download', { timeout: UI_TIMEOUT });
        const [event] = await Promise.all([pending, page.locator(selector).click()]);
        check(!await event.failure(), 'browser_download_failed');
        const file = await event.path();
        const bytes = fs.readFileSync(file);
        check(bytes.length > 0, 'empty_browser_download');
        await validate(bytes);
        const saved = project(bytes);
        noSecrets(saved.toString('utf8'), secrets);
        fs.writeFileSync(path.join(runDir, name), saved);
        await event.delete();
        return { file: name, bytes: saved.length, sha256: hash(saved), downloaded_bytes: bytes.length };
      } catch (error) { if (!throttled) throw error; }
      finally { page.off('response', observe); }
      check(attempt < 3, 'download_429_retry_budget_exhausted');
      await cooldown(throttled, 'report_download', 60000);
    }
  }
  async function playback(page, selector, item) {
    await page.locator(selector).waitFor({ state: 'visible' });
    await page.waitForFunction(selector => {
      const video = document.querySelector(selector);
      return video && video.readyState >= 2 && video.videoWidth > 0 && Number.isFinite(video.duration) && video.duration > 0;
    }, selector);
    const media = await page.locator(selector).evaluate(async video => {
      video.muted = true; video.currentTime = 0;
      await Promise.race([video.play(), new Promise((_, reject) => setTimeout(() => reject(new Error('play_timeout')), 10000))]);
      return { source: video.currentSrc, duration: video.duration, width: video.videoWidth };
    });
    const source = new URL(media.source);
    check(source.origin === state.base && source.pathname === API + '/upload/media'
      && source.searchParams.get('id') === item.task_id, 'player_not_own_source');
    await page.waitForFunction(selector => {
      const video = document.querySelector(selector);
      return video.currentTime > 0.3 && !video.paused && !video.error;
    }, selector, { timeout: 15000 });
    await page.locator(selector).evaluate(video => video.pause());
    check(Math.abs(media.duration - item.duration) < 0.5, 'player_duration_not_own_source');
    return { ready_state_at_least_2: true, time_advanced: true, duration: media.duration, width: media.width };
  }
  function resultCheck(result, item) {
    check(result.task_id === item.task_id, 'result_wrong_task');
    check(result.source_sha256 === item.sha256, 'result_wrong_source_sha256');
    check(result.media?.has_audio === item.has_audio, 'result_audio_presence_mismatch');
    check(Math.abs(result.media.duration_sec - item.duration) < 0.5, 'result_duration_mismatch');
    check(Array.isArray(result.segments) && result.segments.length > 0, 'result_segments_missing');
    if (item.has_audio) check(result.segments.some(segment => segment.audio?.available === true), 'av_audio_evidence_missing');
    else check(result.media.audio_status === 'absent' && result.segments.every(segment => segment.audio?.available !== true),
      'noaudio_result_fabricates_audio');
  }
  async function negativeCases(page, item) {
    for (const [name, relative, expected] of [
      ['missing_task_parameter', '/upload/result', 400],
      ['unknown_task', '/upload/task?id=missing_' + runId, 404],
      ['invalid_media_asset', '/upload/media?id=' + item.task_id + '&asset=invalid_acceptance_asset', 404],
    ]) {
      const response = await get(page, API + relative);
      check(response.status === expected && response.type.includes('json'), 'negative_api_case_wrong_response');
      check(JSON.parse(response.body.toString()).error, 'negative_api_case_missing_error');
      report.negative_cases.push({ user: item.user, case: name, expected_status: expected, actual_status: response.status, passed: true });
    }
    await navigate(page, '/demo2/video?id=missing_' + runId, () => page.locator('#pageMessage.visible').waitFor());
    check((await page.locator('#pageMessage').textContent()).trim().length > 0, 'unknown_task_ui_error_missing');
    check(await page.locator('#classVideo').isHidden() && await page.locator('#downloadResult').isHidden(),
      'unknown_task_ui_exposes_player_or_result');
    report.negative_cases.push({ user: item.user, case: 'unknown_task_video_ui',
      visible_error: true, player_hidden: true, result_hidden: true, passed: true });
    record(`${item.user}_error_responses`);
  }
  async function identity(page, item, originalSchool) {
    step(`${item.user}_identity`);
    let workspace = (await json(page, API + '/identity/workspace?task_id=' + item.task_id)).workspace;
    check(workspace.task_id === item.task_id && workspace.media_available && workspace.frames.length > 0,
      'identity_own_frames_unavailable');
    check(workspace.summary.identity_scope === 'single_sample_frame' && workspace.summary.tracking_performed === false,
      'identity_scope_invalid');
    check(JSON.stringify(school(workspace.school_context)) === JSON.stringify(originalSchool), 'identity_school_snapshot_mismatch');
    await navigate(page, '/demo2/identity?task_id=' + item.task_id, async () => {
      await page.waitForFunction(() => document.querySelector('#frameImage')?.naturalWidth > 0);
      await page.locator('#bindingList').waitFor();
    });
    if (identityReadonly || !schoolValid(originalSchool)) {
      item.identity = { status: 'partial_read_only', reason: identityReadonly ? 'explicit_fallback' : 'existing_school_invalid' };
    } else {
      check(workspace.can_edit === true && workspace.scope_key, 'identity_edit_not_permitted');
      check(workspace.bindings.length === 0, 'new_task_has_unexpected_bindings');
      await page.locator('#drawButton:not([disabled])').click();
      const surface = page.locator('#frameSurface');
      await surface.scrollIntoViewIfNeeded();
      const rect = await surface.boundingBox();
      check(rect && rect.width > 0 && rect.height > 0, 'identity_surface_empty');
      await page.mouse.move(rect.x + rect.width * 0.15, rect.y + rect.height * 0.2);
      await page.mouse.down();
      await page.mouse.move(rect.x + rect.width * 0.35, rect.y + rect.height * 0.8, { steps: 8 });
      await page.mouse.up();
      if (!await page.locator('#annotationAdvanced').evaluate(node => node.open)) await page.locator('#annotationAdvanced summary').click();
      await page.locator('#personRole').selectOption('unknown');
      for (const [field, expected] of [['bboxX', 15], ['bboxY', 20], ['bboxWidth', 20], ['bboxHeight', 60]]) {
        check(Math.abs(Number(await page.locator('#' + field).inputValue()) - expected) <= 1, 'manual_bbox_coordinate_mismatch');
      }
      let binding;
      for (let attempt = 0; attempt < 4; attempt++) {
        const pending = page.waitForResponse(response => new URL(response.url()).pathname === API + '/identity/bindings'
          && response.request().method() === 'POST');
        const [response] = await Promise.all([pending, page.locator('#saveBinding').click()]);
        if (response.status() === 429) {
          check(attempt < 3, 'identity_429_retry_budget_exhausted');
          await cooldown(response, 'identity_binding', 60000); continue;
        }
        check(response.status() === 200, 'identity_binding_rejected_no_retry');
        binding = (await response.json()).binding; break;
      }
      check(binding?.role === 'unknown' && binding.student_id === null && binding.source_sha256 === item.sha256,
        'identity_unknown_binding_invalid');
      await page.locator('#pageMessage.success').waitFor();
      await navigate(page, '/demo2/identity?task_id=' + item.task_id,
        () => page.locator('#drawButton:not([disabled])').waitFor());
      workspace = (await json(page, API + '/identity/workspace?task_id=' + item.task_id)).workspace;
      check(workspace.bindings.some(row => row.binding_id === binding.binding_id && row.role === 'unknown'
        && row.student_id === null && row.status === 'confirmed' && row.source_sha256 === item.sha256),
      'identity_binding_not_persisted');
      item.identity = { status: 'passed', role: 'unknown', manual_bbox: true, persisted_after_reload: true };
    }
    item.identity.export = await download(page, '#exportBindings', `${item.user}_identity.json`, bytes => {
      const exported = JSON.parse(bytes.toString());
      check(exported.task_id === item.task_id && exported.summary.tracking_performed === false
        && exported.summary.global_motion_attributed_to_student === false
        && exported.summary.global_audio_attributed_to_student === false, 'identity_export_scope_invalid');
    }, bytes => {
      const exported = JSON.parse(bytes.toString());
      // The real export can contain the entire existing school roster. Do not retain it locally.
      delete exported.students;
      exported.roster_omitted_from_acceptance_artifact = true;
      return Buffer.from(JSON.stringify(exported, null, 2));
    });
    record(`${item.user}_identity_checked`, { status: item.identity.status });
  }
  async function analysis(page, item) {
    step(`${item.user}_analysis_tabs_reports`);
    const route = '/demo2/analysis?task_id=' + item.task_id;
    await navigate(page, route, () => page.locator('#applicabilitySection').waitFor());
    let workspace = (await json(page, API + '/course-analysis?task_id=' + item.task_id)).workspace;
    check(workspace.task_id === item.task_id && workspace.course_id === courseId, 'analysis_wrong_task');
    check(workspace.media.has_audio === item.has_audio && workspace.people.length === 0
      && workspace.records.length === 0 && workspace.summary.scored === 0, 'synthetic_analysis_contains_unexpected_student_data');
    item.analysis_playback = await playback(page, '#video', item);
    item.tabs = [];
    for (const tab of ['group', 'person', 'review', 'report']) {
      await page.locator('#tab-' + tab).click();
      check(await page.locator('#tab-' + tab).getAttribute('aria-selected') === 'true', 'tab_not_selected');
      check(await page.locator('#' + tab).isVisible(), 'tab_panel_not_visible');
      check(await page.locator('[role=tabpanel]:visible').count() === 1, 'multiple_tab_panels_visible');
      item.tabs.push(tab);
    }
    for (let attempt = 0; attempt < 4; attempt++) {
      const pending = page.waitForResponse(response => new URL(response.url()).pathname === API + '/course-analysis'
        && new URL(response.url()).searchParams.get('task_id') === item.task_id);
      const [response] = await Promise.all([pending, page.locator('#refresh').click()]);
      if (response.status() === 429) {
        check(attempt < 3, 'refresh_429_retry_budget_exhausted');
        await cooldown(response, 'refresh_result', 60000); continue;
      }
      check(response.status() === 200, 'refresh_result_failed');
      workspace = (await response.json()).workspace;
      check(workspace.task_id === item.task_id && workspace.course_id === courseId, 'refreshed_result_wrong_task');
      break;
    }
    resultCheck(await json(page, API + '/upload/result?id=' + item.task_id), item);
    item.refresh_result = true;
    await page.locator('#tab-report').click();
    item.report_json = await download(page, '#downloadJson', `${item.user}_report.json`, bytes => {
      const exported = JSON.parse(bytes.toString());
      check(exported.task_id === item.task_id && exported.course_id === courseId && exported.people.length === 0
        && exported.records.length === 0 && exported.summary.scored === 0, 'report_json_wrong_scope');
    });
    item.report_html = await download(page, '#downloadHtml', `${item.user}_report.html`, bytes => {
      const html = bytes.toString('utf8');
      check(/<!doctype html>/i.test(html) && html.includes(item.course_name) && html.includes('report-body'),
        'report_html_invalid_or_wrong_course');
    });
    await navigate(page, route, () => page.locator('#applicabilitySection').waitFor());
    check((await json(page, API + '/course-analysis?task_id=' + item.task_id)).workspace.task_id === item.task_id,
      'analysis_reload_wrong_task');
    record(`${item.user}_analysis_tabs_refresh_downloads`);
  }
  function protectedRoutes(item) {
    return ['/upload/task?id=' + item.task_id, '/upload/result?id=' + item.task_id,
      '/upload/media?id=' + item.task_id + '&asset=source', '/upload/media?id=' + item.task_id + '&asset=audio',
      '/identity/workspace?task_id=' + item.task_id, '/identity/export?task_id=' + item.task_id,
      '/course-analysis?task_id=' + item.task_id, ...(item.frame_routes || [])].map(route => route.startsWith(API) ? route : API + route);
  }
  async function anonymousChecks(items) {
    // Invited anonymous first: intentional gate denials must not starve subsequent authorization.
    for (const invited of [true, false]) {
      step(invited ? 'anonymous_with_invitation' : 'anonymous_without_invitation');
      const page = await contextFor(invited ? 'invited_anonymous' : 'uninvited_anonymous');
      const evidence = { invited, api_denials: [], page_denials: [] };
      let gateRequests = 0;
      const pace = async () => {
        if (!invited && gateRequests > 0 && gateRequests % 7 === 0) {
          console.log('Waiting 61s to respect invitation-gate denial budget');
          await sleep(61000);
        }
        gateRequests++;
      };
      try {
        if (invited) await invitation(page);
        else await navigate(page, '/invite');
        for (const [index, item] of items.entries()) {
          // All APIs for invited anonymous; every task source/result plus every route class without invitation.
          const routes = invited || index === 0 ? protectedRoutes(item) : [
            API + '/upload/result?id=' + item.task_id, API + '/upload/media?id=' + item.task_id + '&asset=source'];
          for (const route of routes) {
            await pace();
            const response = await get(page, route);
            check([401, 403].includes(response.status), 'anonymous_data_exposed');
            evidence.api_denials.push({ task_id: item.task_id, path: new URL(route, state.base).pathname, status: response.status });
          }
        }
        for (const relative of ['/demo2/analysis?task_id=' + items[0].task_id,
          '/demo2/video?id=' + items[0].task_id, '/demo2/identity?task_id=' + items[0].task_id, '/demo2/admin']) {
          await pace();
          for (let attempt = 0; attempt < 4; attempt++) {
            const response = await page.goto(state.base + relative, { waitUntil: 'domcontentloaded' });
            if (response.status() === 429) {
              check(attempt < 3, 'anonymous_page_429_retry_budget_exhausted');
              await cooldown(response, 'anonymous_page', 60000); continue;
            }
            const location = new URL(page.url());
            check([401, 403].includes(response.status()) || ['/demo2/login', '/invite'].includes(location.pathname),
              'anonymous_protected_page_accessible');
            evidence.page_denials.push({ path: new URL(relative, state.base).pathname, status: response.status(), redirected_to: location.pathname });
            break;
          }
        }
        (report.anonymous ||= []).push(evidence);
        record(invited ? 'invited_without_login_denied' : 'without_invitation_denied');
      } finally { await page.context().close(); }
    }
  }
  async function verifyExistingTasks() {
    for (const account of accounts) {
      const source = original.accounts.find(item => item.user === account.username);
      const item = Object.fromEntries(['user', 'task_id', 'sha256', 'has_audio', 'duration', 'course_name', 'frame_routes']
        .map(key => [key, source[key]]));
      report.accounts.push(item);
      const page = await contextFor(item.user);
      try {
        step(`${item.user}_existing_task_pages`);
        await login(page, account);
        const before = schoolSnapshot(await json(page, API + '/school/context'));
        const task = (await json(page, API + '/upload/task?id=' + item.task_id)).task;
        check(task.sha256 === item.sha256 && task.course_id === courseId, 'existing_task_hash_or_course_mismatch');
        resultCheck(await json(page, API + '/upload/result?id=' + item.task_id), item);
        await navigate(page, '/demo2/video?id=' + item.task_id, () => page.locator('#downloadResult').waitFor());
        item.video_playback = await playback(page, '#classVideo', item);
        await analysis(page, item);
        await navigate(page, '/demo2/identity?task_id=' + item.task_id,
          () => page.waitForFunction(() => document.querySelector('#frameImage')?.naturalWidth > 0));
        const workspace = (await json(page, API + '/identity/workspace?task_id=' + item.task_id)).workspace;
        check(workspace.task_id === item.task_id && workspace.media_available, 'existing_identity_workspace_invalid');
        item.identity_read_only = true;
        item.pages = ['/demo2/video', '/demo2/analysis', '/demo2/identity'];
        for (const relative of ['/demo2/students', '/demo2/teaching-support?task_id=' + item.task_id,
          '/demo2/course-batch?task_id=' + item.task_id]) {
          await navigate(page, relative, () => relative === '/demo2/students'
            ? page.waitForFunction(() => /\d/.test(document.querySelector('#rosterCount')?.textContent || ''))
            : page.waitForFunction(name => document.querySelector('#course')?.textContent.includes(name), item.course_name));
          item.pages.push(new URL(relative, state.base).pathname);
        }
        check(isDeepStrictEqual(before, schoolSnapshot(await json(page, API + '/school/context'))), 'existing_school_metadata_changed');
        item.school_metadata_unchanged = true; item.complete = true;
        record(`${item.user}_all_existing_task_pages`);
      } catch (error) { failure(error); }
      finally { await page.context().close(); }
    }
    step('admin_existing_media_playback_downloads');
    const page = await contextFor('admin');
    try {
      await login(page, admin, true);
      const summary = (await json(page, API + '/admin/summary')).summary;
      report.admin.tasks = [];
      for (const item of report.accounts) {
        check(summary.recent_uploads.some(task => task.task_id === item.task_id), 'admin_existing_task_not_listed');
        await navigate(page, '/demo2/video?id=' + item.task_id, () => page.locator('#downloadResult').waitFor());
        const evidence = { task_id: item.task_id, playback: await playback(page, '#classVideo', item), downloads: [] };
        for (const asset of ['source', 'audio']) {
          const response = await get(page, API + `/upload/media?id=${item.task_id}&asset=${asset}`);
          if (asset === 'audio' && !item.has_audio) {
            check(response.status === 404, 'admin_noaudio_task_exposes_audio');
            evidence.audio_absent_404 = true; continue;
          }
          check(response.status === 200 && response.body.length > 0, 'admin_media_download_failed');
          check(asset === 'source' ? hash(response.body) === item.sha256
            : response.body.subarray(0, 4).toString() === 'RIFF', 'admin_media_content_invalid');
          const file = `admin_${item.user}_${asset}.${asset === 'source' ? 'mp4' : 'wav'}`;
          fs.writeFileSync(path.join(runDir, file), response.body);
          evidence.downloads.push({ asset, file, bytes: response.body.length, sha256: hash(response.body) });
        }
        evidence.result = await download(page, '#downloadResult', `admin_${item.user}_result.json`,
          bytes => resultCheck(JSON.parse(bytes.toString()), item));
        await navigate(page, '/demo2/identity?task_id=' + item.task_id,
          () => page.waitForFunction(() => document.querySelector('#frameImage')?.naturalWidth > 0));
        check((await json(page, API + '/identity/workspace?task_id=' + item.task_id)).workspace.can_edit === false,
          'admin_identity_not_read_only');
        report.admin.tasks.push(evidence); record(`admin_${item.user}_media_and_identity`);
      }
      await navigate(page, '/demo2/admin/channels');
    } catch (error) { failure(error); }
    finally { await page.context().close(); }
    await anonymousChecks(report.accounts);
    check(report.blocked_writes.length === 0, 'supplemental_write_attempted');
    check(report.page_errors.length === 0, 'browser_javascript_errors');
    check(hash(fs.readFileSync(originalPath)) === hash(originalBytes), 'original_report_changed');
    report.original_report_preserved = true;
    report.passed = report.failures.length === 0 && report.accounts.every(item => item.complete)
      && report.admin.tasks?.length === 4 && report.anonymous.length === 2;
  }
  try {
    try { lock = fs.openSync(lockPath, 'wx'); } catch (_) { check(false, 'live_run_lock_exists_do_not_run_concurrently'); }
    const files = verifyExisting ? null : fixtures();
    const { chromium } = require('playwright');
    browser = await chromium.launch({ channel: process.env.PILOT_BROWSER_CHANNEL || 'msedge', headless: true });
    if (verifyExisting) { await verifyExistingTasks(); return; }
    const teachers = [];
    for (let index = 0; index < accounts.length; index++) {
      const account = accounts[index], fixture = files[index];
      const item = { user: account.username, fixture: path.basename(fixture.file), sha256: fixture.sha256,
        bytes: fixture.bytes, has_audio: fixture.has_audio, duration: fixture.duration,
        course_name: `SYNTHETIC TEST ONLY - ${runId} - ${account.username}` };
      report.accounts.push(item);
      const page = await contextFor(account.username);
      let originalSchool, originalSchoolMetadata;
      try {
        step(`${item.user}_login_school_read_only`);
        await login(page, account); item.login = true;
        let selectionUI;
        await navigate(page, '/demo2/school', async () => {
          selectionUI = await page.locator('#selectionSource').count() > 0;
          await page.locator(selectionUI ? '#reloadSchool:not([disabled])' : '#schoolButton:not([disabled])').waitFor();
        });
        const schoolPayload = await json(page, API + '/school/context');
        originalSchoolMetadata = schoolSnapshot(schoolPayload);
        originalSchool = school(schoolPayload.context);
        for (const [selector, field] of [['#city', 'city'], ['#district', 'district'], ['#schoolName', 'school_name']]) {
          check(await page.locator(selector).inputValue() === originalSchool[field], 'school_form_does_not_match_existing_data');
        }
        item.existing_school_valid = schoolValid(originalSchool);
        if (selectionUI) {
          const modes = await page.locator('#selectionSource option').evaluateAll(options => options.map(option => option.value));
          check(['existing', 'directory', 'other'].every(mode => modes.includes(mode)), 'school_selection_modes_missing');
          if (item.existing_school_valid) {
            check(await page.locator('#selectionSource').inputValue() === 'existing', 'existing_school_not_selected');
            check(await page.locator('#continueLink').isVisible(), 'existing_school_continue_missing');
          }
          item.school_selection = { modes_verified: true, existing_selection_preserved: item.existing_school_valid };
        } else item.school_selection = { legacy_renderer: true };
        teachers.push({ page, item, originalSchool });
        step(`${item.user}_upload`);
        await navigate(page, '/demo2/upload', () => page.locator('#uploadTitle').waitFor());
        await page.locator('#courseId').fill(runId);
        await page.locator('#courseName').fill(item.course_name);
        for (let attempt = 0; attempt < 4; attempt++) {
          const pending = page.waitForResponse(response => new URL(response.url()).pathname === API + '/upload/workspace'
            && new URL(response.url()).searchParams.get('course_id') === runId);
          const [response] = await Promise.all([pending, page.locator('#loadCourseButton').click()]);
          if (response.status() === 429) {
            check(attempt < 3, 'upload_workspace_429_retry_budget_exhausted');
            await cooldown(response, 'upload_workspace', 60000); continue;
          }
          check(response.status() === 200, 'upload_workspace_failed');
          break;
        }
        await page.locator('#videoFile').setInputFiles(fixture.file);
        await page.waitForFunction(() => !document.querySelector('#uploadButton').disabled);
        check(await page.locator('#studentSelect').inputValue() === '', 'upload_must_not_select_real_student');
        check(await page.locator('#allowCompanyArchive').inputValue() === 'no', 'archive_must_remain_disabled');
        const pending = page.waitForResponse(response => new URL(response.url()).pathname === API + '/upload/tasks'
          && response.request().method() === 'POST', { timeout: 10 * 60 * 1000 });
        const [created] = await Promise.all([pending, page.locator('#uploadButton').click()]);
        check(created.status() === 200 || created.status() === 201, 'upload_creation_failed');
        const task = (await created.json()).task;
        check(/^[A-Za-z0-9_-]{1,128}$/.test(task?.task_id || ''), 'task_id_missing_or_invalid');
        item.task_id = task.task_id; item.channel_id = task.channel_id; save();
        await page.waitForFunction(() => document.querySelector('#progressPercent').textContent === '100%',
          null, { timeout: 10 * 60 * 1000 });
        item.upload = true;
        step(`${item.user}_analysis_hash_and_media`);
        // Leave the upload page to stop its independent polling during worker acceptance.
        await navigate(page, '/demo2/school');
        const deadline = Date.now() + 10 * 60 * 1000;
        let completed;
        while (Date.now() < deadline) {
          const payload = await json(page, API + '/upload/task?id=' + item.task_id);
          check(payload.task.task_id === item.task_id && payload.task.course_id === runId, 'task_scope_mismatch');
          check(payload.task.sha256 === item.sha256, 'uploaded_hash_does_not_match_local_file');
          item.analysis_status = payload.task.analysis_status;
          check(!['failed', 'cancelled'].includes(item.analysis_status), 'analysis_worker_failed');
          if (['evidence_ready', 'completed'].includes(item.analysis_status)) { completed = payload; break; }
          await sleep(4000);
        }
        check(completed, 'analysis_worker_timeout');
        resultCheck(completed.result, item);
        resultCheck(await json(page, API + '/upload/result?id=' + item.task_id), item);
        for (const asset of ['source', 'audio']) {
          const response = await get(page, API + `/upload/media?id=${item.task_id}&asset=${asset}`);
          if (asset === 'audio' && !item.has_audio) {
            check(response.status === 404, 'noaudio_task_exposes_audio'); item.audio_absent_404 = true;
            report.negative_cases.push({ user: item.user, case: 'noaudio_download', expected_status: 404,
              actual_status: response.status, passed: true });
            continue;
          }
          check(response.status === 200 && response.body.length > 0, 'media_download_failed');
          check(asset === 'source' ? hash(response.body) === item.sha256
            : /^(audio\/|application\/octet-stream)/.test(response.type), 'media_download_content_invalid');
          if (asset === 'audio') check(response.body.subarray(0, 4).toString() === 'RIFF', 'audio_download_not_wave');
          const file = `${item.user}_${asset}.${asset === 'source' ? 'mp4' : 'wav'}`;
          fs.writeFileSync(path.join(runDir, file), response.body);
          item[asset + '_download'] = { file, bytes: response.body.length, sha256: hash(response.body) };
        }
        await navigate(page, '/demo2/video?id=' + item.task_id, () => page.locator('#downloadResult').waitFor());
        item.video_playback = await playback(page, '#classVideo', item);
        if (!item.has_audio) {
          check(await page.locator('#audioPlayer').isHidden(), 'noaudio_player_should_be_hidden');
          check((await page.locator('#audioMetric').textContent()).includes('\u65e0\u97f3\u8f68'), 'noaudio_ui_not_explicit');
          item.noaudio = { result_absence_verified: true, download_404: true, player_hidden: true, video_played: true };
          record(`${item.user}_noaudio_result_download_and_ui`);
        }
        item.result_download = await download(page, '#downloadResult', `${item.user}_evidence.json`,
          bytes => resultCheck(JSON.parse(bytes.toString()), item));
        const workspace = (await json(page, API + '/identity/workspace?task_id=' + item.task_id)).workspace;
        item.frame_routes = workspace.frames.slice(0, 1).map(frame => {
          const url = new URL(frame.image_url, state.base);
          check(url.origin === state.base && url.pathname.startsWith(API + '/identity/'), 'frame_url_not_protected');
          return url.pathname + url.search;
        });
        for (const frameRoute of item.frame_routes) {
          const frame = await get(page, frameRoute);
          check(frame.status === 200 && frame.type.startsWith('image/') && frame.body.length > 0, 'own_frame_unreadable');
        }
        await identity(page, item, originalSchool);
        await analysis(page, item);
        await negativeCases(page, item);
        step(`${item.user}_related_pages_read_only`);
        item.pages = [];
        for (const [relative, selector, expected] of [
          ['/demo2/students', '#rosterCount', null],
          ['/demo2/teaching-support?task_id=' + item.task_id, '#course', item.course_name],
          ['/demo2/course-batch?task_id=' + item.task_id, '#course', item.course_name],
        ]) {
          await navigate(page, relative, async () => {
            await page.locator(selector).waitFor();
            if (expected) await page.waitForFunction(({ selector, expected }) =>
              document.querySelector(selector)?.textContent.includes(expected), { selector, expected });
            else await page.waitForFunction(() => /\d/.test(document.querySelector('#rosterCount')?.textContent || ''));
          });
          item.pages.push(new URL(relative, state.base).pathname);
        }
        item.complete = true;
      } catch (error) { failure(error); }
      finally {
        if (originalSchool) {
          try {
            const after = schoolSnapshot(await json(page, API + '/school/context'));
            check(isDeepStrictEqual(after, originalSchoolMetadata), 'school_context_or_selection_metadata_changed');
            item.school_unchanged = true;
            item.school_metadata_unchanged = true;
          } catch (error) { failure(error); }
        }
        save();
      }
    }
    step('cross_account_and_cross_school_denials');
    let crossSchoolPairs = 0;
    for (const teacher of teachers) {
      for (const other of report.accounts.filter(item => item.task_id && item.user !== teacher.item.user)) {
        for (const route of protectedRoutes(other)) {
          const response = await get(teacher.page, route);
          check([403, 404].includes(response.status), 'cross_account_data_exposed');
        }
        const otherTeacher = teachers.find(value => value.item.user === other.user);
        if (schoolValid(teacher.originalSchool) && schoolValid(otherTeacher?.originalSchool)
          && JSON.stringify(teacher.originalSchool) !== JSON.stringify(otherTeacher.originalSchool)) crossSchoolPairs++;
      }
      record(`${teacher.item.user}_other_accounts_denied`);
    }
    report.cross_school_pairs = crossSchoolPairs;
    report.cross_school_status = crossSchoolPairs ? 'passed' : 'not_testable_no_distinct_existing_schools';

    step('admin_all_tasks');
    const adminPage = await contextFor('admin');
    await login(adminPage, admin, true); report.admin.login = true;
    await adminPage.locator('#recentUploads').waitFor();
    const summary = (await json(adminPage, API + '/admin/summary')).summary;
    const channels = await json(adminPage, API + '/admin/channels');
    check(Array.isArray(channels.channels), 'admin_channels_missing');
    check(report.accounts.length === 4 && report.accounts.every(item => item.task_id), 'not_all_four_tasks_created');
    check(new Set(report.accounts.map(item => item.channel_id)).size === 4
      && report.accounts.every(item => item.channel_id), 'four_distinct_channels_not_verified');
    for (const item of report.accounts) {
      check(summary.recent_uploads.some(task => task.task_id === item.task_id), 'admin_task_not_listed');
      await adminPage.locator(`#recentUploads a[href*="${item.task_id}"]`).first().waitFor();
      resultCheck(await json(adminPage, API + '/upload/result?id=' + item.task_id), item);
      const task = (await json(adminPage, API + '/upload/task?id=' + item.task_id)).task;
      check(task.sha256 === item.sha256, 'admin_result_wrong_hash');
    }
    report.admin.four_tasks_visible = true; report.admin.four_results_downloadable = true;
    await navigate(adminPage, '/demo2/admin/channels');
    record('admin_four_tasks_and_channels');

    step('anonymous_no_access');
    await anonymousChecks(report.accounts);
    check(report.blocked_writes.length === 0, 'forbidden_school_or_roster_write_attempted');
    check(report.page_errors.length === 0, 'browser_javascript_errors');
    report.partial = identityReadonly || !crossSchoolPairs || report.accounts.some(item => item.identity?.status !== 'passed');
    report.passed = !report.partial && report.failures.length === 0 && report.accounts.every(item => item.complete && item.school_unchanged);
  } catch (error) { failure(error); }
  finally {
    if (browser) {
      try { await browser.close(); } catch (_) { report.failures.push({ step: 'cleanup', code: 'browser_close_failed' }); }
    }
    if (lock !== undefined) { fs.closeSync(lock); fs.unlinkSync(lockPath); }
    report.complete = true; report.finished_at = new Date().toISOString();
    report.passed = report.passed && report.failures.length === 0;
    save();
    console.log(`Acceptance ${report.passed ? 'PASSED' : report.failures.length ? 'FAILED' : 'PARTIAL'}; report: ${path.join(runDir, 'report.json')}`);
    process.exitCode = report.passed ? 0 : report.failures.length ? 1 : 2;
  }
}

async function selfTestInvitation() {
  const http = require('node:http');
  const { chromium } = require('playwright');
  let attempts = 0, documents = 0, waits = 0, browser;
  const server = http.createServer((request, response) => {
    if (request.url === '/invite') {
      documents++;
      response.writeHead(200, { 'Content-Type': 'text/html' });
      response.end(`<script>history.replaceState(null,'','/invite');fetch('/__manager/authorize',{method:'POST'})
        .then(r=>{if(r.ok)location.replace('/demo2/login')})</script>`);
    } else if (request.url === '/__manager/authorize') {
      attempts++;
      response.writeHead(attempts === 1 ? 429 : 200, { 'Retry-After': '0' }); response.end();
    } else {
      response.writeHead(200, { 'Content-Type': 'text/html' }); response.end('<button id="loginButton">Login</button>');
    }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  try {
    browser = await chromium.launch({ channel: 'msedge', headless: true });
    const page = await browser.newPage();
    const base = `http://127.0.0.1:${server.address().port}`;
    await enterInvitation(page, { base, invite: base + '/invite#offline-fixture' }, async response => {
      assert.equal(response.status(), 429); waits++;
      await sleep(retryDelay(response.headers()['retry-after']));
    });
    assert.equal(attempts, 2); assert.equal(documents, 2); assert.equal(waits, 1);
    console.log('Local browser regression passed: 429 retry loads a new invitation document and reaches login.');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
}

function selfTest() {
  assert.equal(retryDelay('300', 60000), 301000);
  assert.equal(retryDelay(null, 60000), 61000);
  assert.equal(retryDelay('invalid', WINDOW), 301000);
  assert.equal(retryDelay('Thu, 01 Jan 1970 00:00:10 GMT', 60000, 0), 11000);
  assert.equal(schoolValid({ city: 'x', district: 'y', school_name: 'z' }), true);
  assert.equal(schoolValid({ city: 'x' }), false);
  const metadata = { context: { city: 'x', district: 'y', school_name: 'z' }, details: { selection_source: 'directory', address: 'test' } };
  assert.equal(isDeepStrictEqual(schoolSnapshot(metadata), schoolSnapshot(JSON.parse(JSON.stringify(metadata)))), true);
  assert.equal(isDeepStrictEqual(schoolSnapshot(metadata), schoolSnapshot({ ...metadata, details: { selection_source: 'existing' } })), false);
  assert.deepEqual(credentials(USERS.map(user => `| test | ${user} | offline-${user} |`).join('\n')),
    USERS.map(username => ({ username, password: 'offline-' + username })));
  assert.throws(() => credentials(''), /school_credentials_missing/);
  const state = liveState({ origin: 'https://example.test', invite_url: 'https://example.test/invite#secret=offline-secret' });
  assert.equal(state.base, 'https://example.test');
  assert.throws(() => liveState({ origin: state.base, invite_url: 'https://evil.test/invite#secret=x' }));
  assert.throws(() => liveState({ origin: 'http://127.0.0.1', invite_url: 'http://127.0.0.1/invite#x' }));
  const secrets = secretValues([{ password: 'offline-school-password' }], { password: 'offline-admin-password' }, state);
  assert.throws(() => noSecrets('offline-secret', secrets));
  assert.throws(() => noSecrets('{"cookie":"value"}', secrets));
  noSecrets('{"passed":true}', secrets);
  for (let index = 0; index < 4; index++) {
    const args = ffmpegArgs(index, `offline-${index}.mp4`);
    assert.equal(args.includes('-an'), index % 2 !== 0);
    assert.equal(args.includes('aac'), index % 2 === 0);
    assert.equal(args.at(-1), `offline-${index}.mp4`);
  }
  assert.equal(new Set([0, 1, 2, 3].map(index => JSON.stringify(ffmpegArgs(index, 'same.mp4')))).size, 4);
  console.log('Offline self-tests passed. No credentials read, files written, or network requests made.');
}

async function main() {
  const args = process.argv.slice(2);
  const modes = ['--self-test', '--prepare-fixtures', '--live-after-deployment-and-admin-change', '--verify-existing', '--self-test-invitation'];
  const known = [...modes, '--identity-readonly', '--help'];
  check(args.every(arg => known.includes(arg)), 'unknown_argument');
  check(args.filter(arg => modes.includes(arg)).length <= 1, 'choose_one_execution_mode');
  if (args.includes('--verify-existing')) return run(true, true);
  if (args.includes('--self-test-invitation')) return selfTestInvitation();
  if (args.includes('--self-test')) return selfTest();
  if (args.includes('--prepare-fixtures')) { fixtures(); console.log('Four distinct local synthetic fixtures prepared. No live requests made.'); return; }
  if (!args.includes('--live-after-deployment-and-admin-change') || args.includes('--help')) {
    console.log('Live execution is disabled by default. After main confirms deployment AND admin change, run:\n'
      + 'node scripts/verify_pilot_20261016.js --live-after-deployment-and-admin-change\n'
      + 'Read-only live supplement: --verify-existing. Local browser regression: --self-test-invitation.\n'
      + 'Offline: --self-test or --prepare-fixtures. Optional --identity-readonly produces PARTIAL acceptance (exit 2).');
    return;
  }
  await run(args.includes('--identity-readonly'));
}
if (require.main === module) main().catch(error => {
  // Playwright errors can embed invite URLs, post bodies and credentials. Never print raw errors/stacks.
  console.error('Acceptance stopped: ' + (/^[a-zA-Z0-9_]+$/.test(error.checkCode || '') ? error.checkCode : 'preflight_or_runtime_failure'));
  process.exitCode = 1;
});
