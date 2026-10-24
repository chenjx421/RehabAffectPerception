'use strict';

// An isolated pointer-drag -> real HTTP save -> reload workflow. Never live.
const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');
const { performance } = require('node:perf_hooks');

function validateConfig(config) {
  const base = new URL(config.base);
  assert.equal(config.isolated, true);
  assert.equal(base.protocol, 'http:');
  assert.equal(base.hostname, '127.0.0.1');
  assert(base.port && !['8792', '8796'].includes(base.port));
  assert.equal(base.pathname, '/');
  assert(config.guard && config.token && config.task_id && config.student_id);
  assert(path.basename(config.output).startsWith('qa_teacher_flow_browser_'));
  return base.origin;
}

async function main(config) {
  const base = validateConfig(config);
  const { chromium } = require('playwright');
  const executablePath = path.join(process.env.LOCALAPPDATA, 'ms-playwright', 'chromium_headless_shell-1243',
    'chrome-headless-shell-win64', 'chrome-headless-shell.exe');
  assert(fs.existsSync(executablePath), 'Installed headless-shell 1243 is required; no downloads');
  const report = { isolated: true, sourceVideoIsStub: true, detectorUnavailableObserved: false,
    browserProcesses: 1, blockedRequests: 0, savedThroughPointerAndForm: false, screenshots: [],
    stage: 'launch', complete: false };
  let browser;
  try {
    browser = await chromium.launch({ executablePath, headless: true,
      args: ['--disable-background-networking', '--disable-component-update', '--disable-sync',
        '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1'] });
    const context = await browser.newContext({ viewport: { width: 1366, height: 900 },
      serviceWorkers: 'block', acceptDownloads: false });
    try {
      const health = await context.request.get(base + '/__identity_qa__/health', {
        headers: { 'X-Identity-QA': config.guard }, maxRedirects: 0,
      });
      assert.equal(health.status(), 200);
      assert.equal((await health.json()).isolated_identity_qa, true);
      await health.dispose();
      await context.addCookies([{ name: 'rehab_demo2_session', value: config.token,
        url: base, httpOnly: true, sameSite: 'Lax' }]);
      let lastDetect = 0;
      let queue = Promise.resolve();
      await context.route('**/*', async route => {
        const request = route.request();
        const url = new URL(request.url());
        let allowed = url.origin === base && request.method() === 'GET';
        if (url.origin === base && request.method() === 'POST' && url.pathname === '/api/v1/demo2/identity/bindings') {
          const data = request.postDataJSON();
          allowed = data.task_id === config.task_id && data.student_id === config.student_id;
        }
        if (!allowed) {
          report.blockedRequests += 1;
          return route.abort('blockedbyclient');
        }
        if (url.pathname.endsWith('/identity/detect')) {
          queue = queue.then(async () => {
            const wait = Math.max(0, 2200 - (performance.now() - lastDetect));
            if (wait) await new Promise(resolve => setTimeout(resolve, wait));
            lastDetect = performance.now();
            await route.continue();
          });
          return queue;
        }
        return route.continue();
      });
      if (context.routeWebSocket) await context.routeWebSocket('**/*', socket => socket.close());
      const page = await context.newPage();
      report.pageErrors = 0;
      page.on('pageerror', () => { report.pageErrors += 1; });
      const screenshot = async name => {
        await page.evaluate(() => {
          if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
          window.scrollTo(0, 0);
        });
        await page.waitForTimeout(250);
        await page.screenshot({ path: path.join(config.output, name), fullPage: true });
        report.screenshots.push(name);
      };
      const ready = () => page.waitForFunction(() => {
        const image = document.getElementById('frameImage');
        const draw = document.getElementById('drawButton');
        return image && image.complete && image.naturalWidth > 0 && draw && !draw.disabled;
      }, null, { timeout: 20000 });
      const readWorkspace = async () => {
        const response = await context.request.get(base + '/api/v1/demo2/identity/workspace?task_id=' + config.task_id,
          { maxRedirects: 0 });
        assert.equal(response.status(), 200);
        const body = await response.json();
        await response.dispose();
        return body.workspace;
      };
      report.stage = 'load-frame-and-unavailable-detector';
      const detectionResponse = page.waitForResponse(response =>
        new URL(response.url()).pathname === '/api/v1/demo2/identity/detect');
      await page.goto(base + '/demo2/identity?task_id=' + config.task_id, { waitUntil: 'domcontentloaded' });
      await ready();
      const detected = await detectionResponse;
      assert.equal(detected.status(), 200);
      assert.equal((await detected.json()).detection.available, false);
      report.detectorUnavailableObserved = true;
      assert.equal((await readWorkspace()).bindings.length, 0);
      report.stage = 'pointer-draw-and-select-student';
      await page.locator('#drawButton').click();
      const image = page.locator('#frameImage');
      await image.scrollIntoViewIfNeeded();
      const rect = await image.boundingBox();
      assert(rect && rect.width > 0 && rect.height > 0);
      await page.mouse.move(rect.x + rect.width * .10, rect.y + rect.height * .20);
      await page.mouse.down();
      await page.mouse.move(rect.x + rect.width * .35, rect.y + rect.height * .70, { steps: 10 });
      await page.mouse.up();
      await page.locator('#studentSelect').selectOption(config.student_id);
      assert.equal(await page.locator('#personRole').inputValue(), 'student');
      await page.waitForFunction(() => !document.getElementById('saveBinding').disabled);
      report.stage = 'save-real-binding';
      const savedResponse = page.waitForResponse(response =>
        new URL(response.url()).pathname === '/api/v1/demo2/identity/bindings' && response.request().method() === 'POST');
      await page.locator('#saveBinding').click();
      const response = await savedResponse;
      assert.equal(response.status(), 200);
      const binding = (await response.json()).binding;
      assert.equal(binding.student_id, config.student_id);
      for (const [key, expected] of Object.entries({ x: .1, y: .2, width: .25, height: .5 })) {
        assert(Math.abs(binding.bbox[key] - expected) < .012, 'Saved coordinates must match the actual pointer drag');
      }
      report.savedThroughPointerAndForm = true;
      report.savedBBox = binding.bbox;
      await page.waitForTimeout(500);
      await screenshot('manual_saved.png');
      report.stage = 'reload-and-verify-persisted-name';
      const reloadDetection = page.waitForResponse(response =>
        new URL(response.url()).pathname === '/api/v1/demo2/identity/detect');
      await page.reload({ waitUntil: 'domcontentloaded' });
      await ready();
      const rechecked = await reloadDetection;
      assert.equal(rechecked.status(), 200);
      assert.equal((await rechecked.json()).detection.available, false);
      const refreshed = await readWorkspace();
      assert.equal(refreshed.bindings.length, 1);
      assert.deepEqual(refreshed.bindings[0].bbox, binding.bbox);
      assert.equal(refreshed.bindings[0].student_id, config.student_id);
      const student = refreshed.students.find(student => student.student_id === config.student_id);
      assert(student.display_name);
      assert((await page.locator('#bindingList').innerText()).includes(student.display_name));
      report.savedNameVisibleAfterReload = true;
      await screenshot('manual_reloaded.png');
      report.stage = 'mobile-layout';
      await page.setViewportSize({ width: 390, height: 844 });
      await page.waitForTimeout(300);
      report.mobileOverflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
      await screenshot('manual_mobile.png');
      assert.equal(report.pageErrors, 0);
      assert.equal(report.blockedRequests, 0);
      assert.equal(report.mobileOverflow, false);
      report.stage = 'complete';
      report.complete = true;
    } finally {
      await context.close();
    }
  } finally {
    if (browser) await browser.close();
    fs.writeFileSync(path.join(config.output, 'teacher_flow.json'), JSON.stringify(report, null, 2) + '\n');
  }
}

module.exports = { validateConfig };
if (require.main === module) {
  (async () => {
    let raw = '';
    for await (const chunk of process.stdin) {
      raw += chunk;
      assert(raw.length <= 16384, 'Fixture configuration is too large');
    }
    await main(JSON.parse(raw));
  })().catch(() => {
    console.error('Isolated teacher-flow QA failed; sanitized report retained. No live service was used.');
    process.exitCode = 1;
  });
}
