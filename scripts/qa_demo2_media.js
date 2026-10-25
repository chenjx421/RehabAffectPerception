// Real browser acceptance. Run only through the isolated Python media harness.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('playwright');

const base = process.env.DEMO2_MEDIA_URL;
const taskId = process.env.DEMO2_MEDIA_TASK;
const output = process.env.DEMO2_MEDIA_OUTPUT;
if (!base || !taskId || !output || new URL(base).hostname !== '127.0.0.1') {
  throw new Error('Run scripts.qa_demo2_media against an isolated loopback server.');
}
const report = { checks: [], screenshots: [], progress: [], pageErrors: [] };
const record = (name, ok, evidence) => {
  report.checks.push({ name, ok: !!ok, evidence });
  console.log(JSON.stringify({ name, ok: !!ok, evidence }));
};

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1050 }, acceptDownloads: true });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.on('pageerror', error => report.pageErrors.push(error.message));
  const external = [];
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.protocol.startsWith('http') && url.origin !== base) {
      external.push(url.origin);
      return route.abort();
    }
    return route.continue();
  });
  const api = '/api/v1/demo2';
  const taskPath = `${base}${api}/upload/task?id=${taskId}`;
  const mediaPath = `${base}${api}/upload/media?id=${taskId}`;
  const resultPath = `${base}${api}/upload/result?id=${taskId}`;
  async function capture(name) {
    // Normalize scroll/focus after native media controls and range interactions;
    // otherwise Edge full-page captures place sticky headers at the old offset.
    await page.evaluate(async () => {
      document.activeElement?.blur();
      window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
      await document.fonts.ready;
    });
    await page.waitForFunction(() => window.scrollY === 0);
    const dimensions = await page.evaluate(() => ({ viewport: innerWidth, scroll: document.documentElement.scrollWidth }));
    record(`${name}_layout`, dimensions.scroll <= dimensions.viewport + 1, dimensions);
    const file = path.join(output, `${name}.png`);
    await page.screenshot({ path: file, fullPage: true, animations: 'disabled' });
    report.screenshots.push(file);
  }
  async function login(username, password, role = '用户登录') {
    await page.goto(`${base}/demo2/login`);
    await page.getByRole('radio', { name: role, exact: true }).click();
    await page.getByLabel('账号', { exact: true }).fill(username);
    await page.getByLabel('密码', { exact: true }).fill(password);
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await page.waitForURL(role === '用户登录' ? '**/demo2/school' : '**/demo2/admin');
  }
  async function pixels() {
    await page.waitForFunction(() => {
      const v = document.querySelector('#classVideo');
      return v && v.readyState >= 2 && !v.seeking && v.videoWidth > 0;
    });
    return page.locator('#classVideo').evaluate(v => {
      const canvas = document.createElement('canvas');
      canvas.width = 64; canvas.height = 36;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(v, 0, 0, 64, 36);
      const data = ctx.getImageData(0, 0, 64, 36).data;
      let sum = 0, sq = 0, nonblack = 0;
      for (let i = 0; i < data.length; i += 4) {
        const p = (data[i] + data[i + 1] + data[i + 2]) / 3;
        sum += p; sq += p * p; if (p > 15) nonblack++;
      }
      const count = data.length / 4;
      return { width: v.videoWidth, height: v.videoHeight, time: v.currentTime, duration: v.duration,
        mean: sum / count, variance: sq / count - (sum / count) ** 2, nonblackRatio: nonblack / count };
    });
  }
  try {
    await login('t1', 'MediaQA01');
    await page.goto(`${base}/demo2/video?id=${taskId}`);
    await page.locator('#retryButton:not([hidden])').waitFor();
    record('failed_state_visible', /处理未完成/.test(await page.locator('#stageLabel').innerText()));
    await capture('01_desktop_failed');
    const retryResponse = page.waitForResponse(r => r.url().endsWith('/upload/tasks/retry') && r.request().method() === 'POST');
    await page.getByRole('button', { name: '重新处理', exact: true }).click();
    const retried = await retryResponse;
    const retryBody = await retried.json();
    record('ui_retry_202_queued', retried.status() === 202 && retryBody.task.analysis_status === 'queued', retryBody);
    const pending = await page.request.get(resultPath);
    record('retry_pending_download_409', pending.status() === 409, pending.status());
    await page.waitForFunction(() => document.querySelector('#stageLabel').textContent === '等待处理');
    await capture('02_desktop_queued');
    // The harness starts the real worker only after this deterministic UI/HTTP check.
    console.log(JSON.stringify({ event: 'retry_queued' }));
    let data;
    const deadline = Date.now() + 120000;
    while (Date.now() < deadline) {
      const response = await page.request.get(taskPath);
      assert.equal(response.status(), 200);
      data = await response.json();
      const state = { status: data.task.analysis_status, stage: data.task.processing_stage, progress: data.task.processing_progress };
      if (JSON.stringify(state) !== JSON.stringify(report.progress.at(-1))) report.progress.push(state);
      if (['evidence_ready', 'failed'].includes(state.status)) break;
      await new Promise(resolve => setTimeout(resolve, 150));
    }
    const ready = data?.task.analysis_status === 'evidence_ready';
    record('real_worker_ready', ready, data?.task);
    record('processing_progress_observed', report.progress.some(p => p.status === 'processing'), report.progress);
    record('processing_progress_monotonic', report.progress.every((p, i, a) => i === 0 || p.progress >= a[i - 1].progress));
    await page.reload();
    await page.waitForFunction(() => !document.querySelector('#classVideo').hidden);
    await page.locator('#classVideo').evaluate(v => { v.muted = true; return v.play(); });
    await page.waitForFunction(() => document.querySelector('#classVideo').currentTime > .4);
    await page.locator('#classVideo').evaluate(v => v.pause());
    const desktopPixels = await pixels();
    record('desktop_real_video_pixels', desktopPixels.variance > 100 && desktopPixels.nonblackRatio > .3 &&
      desktopPixels.width === 640 && Math.abs(desktopPixels.duration - 46) < .1, desktopPixels);

    if (ready) {
      const result = data.result;
      record('real_evidence_46s_three_windows', result.media.duration_sec === 46 &&
        result.summary.sampled_frames === 46 && result.summary.decoded_frames === 1150 &&
        JSON.stringify(result.segments.map(s => [s.start_sec, s.end_sec])) === '[[0,20],[20,40],[40,46]]', result.summary);
      record('no_inferred_learning_or_asr', result.summary.transcription_performed === false &&
        result.summary.unknown_fields.includes('learning_mastery') && result.segments.every(s => s.review_status === 'unreviewed'));
      await page.locator('#segments button').nth(1).click();
      await page.waitForFunction(() => Math.abs(document.querySelector('#classVideo').currentTime - 20) < .3);
      const segmentPixels = await pixels();
      record('segment_click_seeks_original', segmentPixels.variance > 100 && Math.abs(segmentPixels.time - 20) < .3, segmentPixels);
      await page.getByRole('slider', { name: '录像时间' }).fill('42');
      await page.waitForFunction(() => Math.abs(document.querySelector('#classVideo').currentTime - 42) < .3);
      record('seek_slider_42s', (await pixels()).time >= 41.7);
      const downloadEvent = page.waitForEvent('download');
      await page.getByRole('link', { name: '下载证据记录' }).click();
      const download = await downloadEvent;
      const downloadedPath = path.join(output, 'downloaded_evidence.json');
      await download.saveAs(downloadedPath);
      const downloaded = JSON.parse(fs.readFileSync(downloadedPath, 'utf8'));
      record('ui_evidence_json_download', downloaded.task_id === taskId && downloaded.source_sha256 === process.env.DEMO2_MEDIA_SHA256 &&
        downloaded.segments.length === 3, { filename: download.suggestedFilename(), bytes: fs.statSync(downloadedPath).size });
      const audio = await page.request.get(`${mediaPath}&asset=audio`);
      const audioBytes = await audio.body();
      record('protected_extracted_audio', audio.status() === 200 && audioBytes.subarray(0, 4).toString() === 'RIFF' && audioBytes.length > 1000,
        { status: audio.status(), bytes: audioBytes.length });
      if (audio.status() === 200) {
        record('audio_pcm_16khz_mono', audioBytes.readUInt16LE(22) === 1 && audioBytes.readUInt32LE(24) === 16000 &&
          audioBytes.readUInt16LE(34) === 16, { channels: audioBytes.readUInt16LE(22), sampleRate: audioBytes.readUInt32LE(24) });
        await page.locator('#audioPlayer').evaluate(a => { a.muted = true; return a.play(); });
        await page.waitForFunction(() => {
          const a = document.querySelector('#audioPlayer');
          return a.readyState >= 2 && a.currentTime > .2 && a.duration > 45;
        });
        record('browser_audio_plays_original_pauses', await page.locator('#classVideo').evaluate(v => v.paused));
        await page.locator('#audioPlayer').evaluate(a => a.pause());
        await page.locator('#segments button').nth(1).click();
        await page.waitForFunction(() => Math.abs(document.querySelector('#audioPlayer').currentTime - 20) < .3);
        record('segment_click_seeks_audio', await page.locator('#audioPlayer').evaluate(a => Math.abs(a.currentTime - 20) < .3 && a.paused));
        await page.locator('#segments button').nth(2).click();
        await page.waitForFunction(() => Math.abs(document.querySelector('#audioPlayer').currentTime - 40) < .3);
        await page.getByRole('slider', { name: '录像时间' }).fill('42');
        await page.waitForFunction(() => Math.abs(document.querySelector('#classVideo').currentTime - 42) < .3);
      }
      const raw = await page.request.get(mediaPath);
      record('source_download_checksum', raw.status() === 200 && crypto.createHash('sha256').update(await raw.body()).digest('hex') === process.env.DEMO2_MEDIA_SHA256);
      const publicJson = JSON.stringify(data);
      record('public_payload_no_physical_paths', !/[A-Za-z]:[\\/]/.test(publicJson) && !/password_hash|file_path|result_path/.test(publicJson));
    }
    await capture('03_desktop_video');
    await page.setViewportSize({ width: 390, height: 844 });
    await capture('04_mobile_video');
    const mobilePixels = await pixels();
    record('mobile_real_video_pixels', mobilePixels.variance > 100 && mobilePixels.nonblackRatio > .3, mobilePixels);
    const videoFile = path.join(output, '05_mobile_video_pixels.png');
    await page.locator('#classVideo').screenshot({ path: videoFile });
    report.screenshots.push(videoFile);

    // Use distinct cookies to test the browser API boundary, not a DOM-only hide.
    await login('t2', 'MediaQA02');
    for (const [name, url, expected] of [['task', taskPath, 404], ['source', mediaPath, 404],
      ['audio', `${mediaPath}&asset=audio`, 404], ['result', resultPath, 403]]) {
      const response = await page.request.get(url);
      record(`other_account_${name}_denied`, response.status() === expected, response.status());
    }
    await page.goto(`${base}/demo2/video?id=${taskId}`);
    await page.locator('#pageMessage.visible').waitFor();
    record('other_account_player_empty', await page.locator('#classVideo').isHidden());
    await capture('06_mobile_denied');
    await login('admin', 'MediaQAAdmin1', '管理员登录');
    const adminResult = await page.request.get(resultPath);
    record('admin_result_permission', adminResult.status() === (ready ? 200 : 409), adminResult.status());
    const adminSource = await page.request.get(mediaPath, { headers: { Range: 'bytes=0-15' } });
    record('admin_source_permission', adminSource.status() === 206);
    const adminChunk = await page.request.post(`${base}${api}/upload/chunks`, { data: { task_id: taskId, course_id: 'media-qa', chunk_index: 0, content_base64: 'YQ==' } });
    record('admin_upload_forbidden', adminChunk.status() === 403);
    record('no_external_requests', external.length === 0, external);
    record('no_uncaught_page_errors', report.pageErrors.length === 0, report.pageErrors);
  } catch (error) {
    record('browser_flow_completed', false, error.stack);
    try { await capture('99_failure'); } catch (_) { /* Preserve the original failure. */ }
  } finally {
    report.ok = report.checks.length > 0 && report.checks.every(c => c.ok);
    fs.writeFileSync(path.join(output, 'browser_report.json'), JSON.stringify(report, null, 2));
    await browser.close();
    if (!report.ok) process.exitCode = 1;
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
