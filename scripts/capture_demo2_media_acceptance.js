// Capture the authorized local acceptance task without publishing student media.
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const { chromium } = require('playwright');

(async () => {
  const root = path.resolve(__dirname, '..');
  const summary = JSON.parse(fs.readFileSync(path.join(root, '.runtime/media_real_acceptance_20260908.json'), 'utf8'));
  const url = new URL(summary.local_url);
  assert.equal(url.hostname, '127.0.0.1');
  assert.ok(process.env.REHAB_ACCEPTANCE_PASSWORD);
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
    const login = await context.request.post(url.origin + '/api/v1/demo2/auth/login', {
      data: { username: 't1', password: process.env.REHAB_ACCEPTANCE_PASSWORD, role: 'school_uploader' },
    });
    assert.equal(login.status(), 200);
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(summary.local_url, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => document.getElementById('stageLabel').textContent.includes('证据已就绪'));
    await page.waitForFunction(() => document.getElementById('classVideo').readyState >= 2);
    await page.locator('#seekSlider').evaluate(node => {
      node.value = '600';
      node.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await page.waitForFunction(() => {
      const video = document.getElementById('classVideo');
      return video.currentTime >= 599 && video.readyState >= 2 && !video.seeking;
    });
    const pixels = await page.locator('#classVideo').evaluate(video => {
      const canvas = document.createElement('canvas');
      canvas.width = 160; canvas.height = 90;
      const ctx = canvas.getContext('2d');
      ctx.drawImage(video, 0, 0, 160, 90);
      const data = ctx.getImageData(0, 0, 160, 90).data;
      let sum = 0, sumSquared = 0;
      for (let i = 0; i < data.length; i += 4) { const x = (data[i] + data[i + 1] + data[i + 2]) / 3; sum += x; sumSquared += x * x; }
      return { mean: sum / (160 * 90), variance: sumSquared / (160 * 90) - (sum / (160 * 90)) ** 2, width: video.videoWidth, height: video.videoHeight };
    });
    assert.ok(pixels.mean > 5 && pixels.variance > 25);
    assert.equal(pixels.width, 1920);
    await page.locator('#audioPlayer').evaluate(audio => audio.load());
    await page.waitForFunction(() => document.getElementById('audioPlayer').readyState >= 1);
    const audioDuration = await page.locator('#audioPlayer').evaluate(audio => {
      audio.currentTime = 600;
      return audio.duration;
    });
    assert.ok(Math.abs(audioDuration - summary.media.duration_sec) < .1);
    await page.screenshot({ path: path.join(root, '.runtime/media_review_desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(300);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    await page.screenshot({ path: path.join(root, '.runtime/media_review_mobile.png'), fullPage: true });
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ real_recording: true, local_only: true, pixels, audio_duration_sec: audioDuration, desktop_and_mobile: 'passed', page_errors: errors }));
    await context.close();
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
