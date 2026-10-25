'use strict';

// Opt-in live screenshots only after an explicit service update notice.
// One Chromium, sequential contexts/pages, no saved auth/trace/HAR or writes.
const fs = require('fs');
const os = require('os');
const path = require('path');
const { performance } = require('perf_hooks');

const BASE = 'http://127.0.0.1:8792';
const TASK = 'a5ded3bc97c54d949961b130e6f18ca2';
const PASSWORD_ENV = { t1: 'QA_DEMO2_TEACHER_PASSWORD', admin: 'QA_DEMO2_ADMIN_PASSWORD' };
const DEFAULT_EXECUTABLE = path.join(process.env.LOCALAPPDATA || '', 'ms-playwright',
  'chromium_headless_shell-1243', 'chrome-headless-shell-win64', 'chrome-headless-shell.exe');

function allowedRead(rawUrl, method) {
  const url = new URL(rawUrl);
  return url.origin === BASE && method === 'GET' &&
    ['/demo2/', '/api/v1/demo2/', '/assets/'].some(prefix => url.pathname.startsWith(prefix)) &&
    !/\/(logout|cancel|retry|delete|revoke)$/.test(url.pathname);
}

function requireOptions(args, env) {
  if (args.length !== 1 || args[0] !== '--service-updated') {
    throw new Error('Screenshots are gated until the main task confirms the service update');
  }
  for (const variable of Object.values(PASSWORD_ENV)) {
    if (!env[variable]) throw new Error('Missing required password environment variable');
  }
  const executablePath = env.QA_DEMO2_CHROMIUM_EXECUTABLE || DEFAULT_EXECUTABLE;
  if (!executablePath.includes('headless_shell-1243') || !fs.existsSync(executablePath)) {
    throw new Error('Installed headless-shell 1243 executablePath is required; no download attempted');
  }
  return { executablePath };
}

async function main() {
  const options = requireOptions(process.argv.slice(2), process.env);
  const { chromium } = require('playwright');
  const output = fs.mkdtempSync(path.join(os.tmpdir(), 'qa_demo2_upgrade_20260911_browser_'));
  const report = { browserProcesses: 1, sequentialPages: true, externalRequestsSent: 0,
    businessWritesSent: 0, authenticationSessionCreation: true, blockedExternal: 0,
    blockedWrites: 0, pages: [], complete: false };
  let browser;
  let lastInferenceStart = 0;
  let inferenceQueue = Promise.resolve();
  try {
    browser = await chromium.launch({ executablePath: options.executablePath, headless: true,
      args: ['--disable-background-networking', '--disable-component-update', '--disable-sync',
        '--disable-default-apps', '--no-first-run', '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'] });
    for (const role of Object.keys(PASSWORD_ENV)) {
      const context = await browser.newContext({ serviceWorkers: 'block', acceptDownloads: false });
      try {
        await context.route('**/*', async route => {
          const request = route.request();
          const url = new URL(request.url());
          if (url.origin !== BASE) {
            report.blockedExternal += 1;
            return route.abort('blockedbyclient');
          }
          if (!allowedRead(request.url(), request.method())) {
            if (request.method() !== 'GET') report.blockedWrites += 1;
            return route.abort('blockedbyclient');
          }
          if (/\/identity\/(detect|preview)$/.test(url.pathname)) {
            inferenceQueue = inferenceQueue.then(async () => {
              const pause = Math.max(0, 2200 - (performance.now() - lastInferenceStart));
              if (pause) await new Promise(resolve => setTimeout(resolve, pause));
              lastInferenceStart = performance.now();
              await route.continue();
            });
            return inferenceQueue;
          }
          return route.continue();
        });
        if (context.routeWebSocket) {
          await context.routeWebSocket('**/*', socket => socket.close());
        }
        const login = await context.request.post(BASE + '/api/v1/demo2/auth/login', {
          data: { username: role, password: process.env[PASSWORD_ENV[role]] },
          maxRedirects: 0, timeout: 20000,
        });
        if (login.status() !== 200) throw new Error('Authorized QA login failed');
        await login.dispose();
        const routes = role === 't1'
          ? [['upload', '/demo2/upload'], ['students', '/demo2/students'],
            ['identity', '/demo2/identity?task_id=' + TASK], ['video', '/demo2/video?id=' + TASK]]
          : [['admin', '/demo2/admin'], ['channels', '/demo2/admin/channels'], ['identity', '/demo2/identity?task_id=' + TASK],
            ['video', '/demo2/video?id=' + TASK]];
        for (const viewport of [{ width: 1366, height: 900 }, { width: 390, height: 844 }]) {
          for (const [name, route] of routes) {
            const page = await context.newPage();
            const item = { role, page: name, width: viewport.width, height: viewport.height,
              pageErrors: 0, httpErrors: 0, screenshots: [] };
            report.pages.push(item);
            page.on('pageerror', () => { item.pageErrors += 1; });
            page.on('response', response => { if (response.status() >= 400) item.httpErrors += 1; });
            try {
              await page.setViewportSize(viewport);
              const started = performance.now();
              const response = await page.goto(BASE + route, { waitUntil: 'domcontentloaded', timeout: 30000 });
              item.status = response.status();
              item.domContentLoadedMs = Math.round(performance.now() - started);
              if (!page.url().startsWith(BASE + route) || item.status !== 200) {
                throw new Error('A QA page redirected or did not load successfully');
              }
              if (name === 'identity') {
                await page.waitForFunction(() => {
                  const image = document.getElementById('frameImage');
                  return image && image.complete && image.naturalWidth > 0;
                }, null, { timeout: 30000 });
              }
              if (name === 'channels') {
                await page.locator('#channelRows [data-setting]').first().waitFor({ state: 'visible' });
                await page.locator('#channelRows [data-setting]').first().click();
                if (!await page.locator('#channelName').isEnabled()) throw new Error('Admin settings are not editable');
                if (!await page.locator('#saveChannel').isDisabled()) throw new Error('Unchanged settings should not submit');
              }
              await page.waitForTimeout(1500);
              item.layout = await page.evaluate(() => ({
                documentWidth: document.documentElement.scrollWidth,
                viewportWidth: innerWidth,
                bodyHeight: document.body.scrollHeight,
                brokenImages: Array.from(document.images).filter(image =>
                  image.getBoundingClientRect().width && image.src && image.complete && !image.naturalWidth).length,
              }));
              const filename = `${role}_${name}_${viewport.width}.png`;
              await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); });
              await page.screenshot({ path: path.join(output, filename), fullPage: true });
              item.screenshots.push(filename);
              if (name === 'identity') {
                const button = page.locator('#previewButton');
                await button.waitFor({ state: 'visible', timeout: 10000 });
                if (await button.isDisabled()) throw new Error('Preview remains disabled after frame load');
                await button.click();
                await page.waitForFunction(() => {
                  const image = document.getElementById('previewImage');
                  return image && !image.hidden && image.complete && image.naturalWidth > 0;
                }, null, { timeout: 30000 });
                item.preview = await page.locator('#previewImage').evaluate(image => ({
                  width: image.naturalWidth, height: image.naturalHeight,
                  renderedWidth: image.getBoundingClientRect().width,
                }));
                const previewName = `${role}_preview_${viewport.width}.png`;
                await page.screenshot({ path: path.join(output, previewName), fullPage: false });
                item.screenshots.push(previewName);
                await page.locator('#closePreview').click();
                if (role === 't1') {
                  const draw = page.locator('#drawButton');
                  if (!await draw.isEnabled()) throw new Error('Manual ROI remains disabled on an available teacher frame');
                  await draw.click();
                  await page.locator('#frameSurface').scrollIntoViewIfNeeded();
                  const box = await page.locator('#frameSurface').boundingBox();
                  await page.mouse.move(box.x + box.width * .3, box.y + box.height * .3);
                  await page.mouse.down();
                  await page.mouse.move(box.x + box.width * .5, box.y + box.height * .6, { steps: 8 });
                  await page.mouse.up();
                  item.manualDraft = await page.locator('#bboxWidth').inputValue();
                  if (!(Number(item.manualDraft) > 0)) throw new Error('Manual ROI did not produce coordinates');
                  const draftName = `${role}_manual_draft_${viewport.width}.png`;
                  await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); });
                  await page.screenshot({ path: path.join(output, draftName), fullPage: true });
                  item.screenshots.push(draftName);
                  await page.locator('#clearSelection').click();
                }
              }
              item.passed = item.pageErrors === 0 && item.httpErrors === 0 &&
                item.layout.documentWidth <= item.layout.viewportWidth + 1 && item.layout.brokenImages === 0;
            } finally {
              await page.close();
            }
          }
        }
      } finally {
        await context.close();
      }
    }
    report.complete = report.pages.every(item => item.passed) && report.blockedWrites === 0;
  } finally {
    if (browser) await browser.close();
    fs.writeFileSync(path.join(output, 'screenshots.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify({ output, ...report }, null, 2));
  }
  if (!report.complete) process.exitCode = 1;
}

module.exports = { allowedRead, requireOptions };
if (require.main === module) {
  main().catch(() => {
    // Do not log Playwright errors: call logs may include request credentials.
    console.error('QA screenshots failed; sanitized partial report retained. No service changes made.');
    process.exitCode = 1;
  });
}
