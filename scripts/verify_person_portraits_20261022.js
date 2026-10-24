// Read-only verification of the user-designated cloud task. No roster writes.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const origin = 'https://YOUR_SERVER_IP';
const task = 'e7b22e477f8f48c0adddef6e05ce0612';
const output = path.join(root, 'output/playwright/tracking-20261022');
const report = { checks: [], portraits: [], errors: [], passed: false };
const check = (ok, code) => { if (!ok) throw new Error(code); if(!report.checks.includes(code))report.checks.push(code); };
let browser, context;
(async () => {
  fs.mkdirSync(output, { recursive: true });
  const invitation = fs.readFileSync(path.join(root, '.runtime/cloud_deploy_20261020/cloud_invitation.private.txt'), 'utf8');
  const secret = invitation.match(/\/invite#([^\s<>"']+)/)?.[1];
  check(Boolean(secret), 'local_invitation_loaded');
  const credentials = fs.readFileSync(path.join(root, '.runtime/demo2_pilot_accounts_20260908.md'), 'utf8')
    .split(/\r?\n/).map(line => line.split('|').map(x => x.trim())).filter(row => /^t[1-4]$/.test(row[2] || ''));
  browser = await chromium.launch({ channel: 'msedge', headless: true });
  context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, extraHTTPHeaders: { Origin: origin } });
  const inviteSecret = secret.startsWith('secret=') ? new URLSearchParams(secret).get('secret') : decodeURIComponent(secret);
  const authorized = await context.request.post(origin + '/__manager/authorize', { data: { secret: inviteSecret } });
  check(authorized.ok(), 'original_invitation_works');
  let result;
  for (const row of credentials) {
    const login = await context.request.post(origin + '/api/v1/demo2/auth/login', { data: { username: row[2], password: row[3], role: 'school_uploader' } });
    check(login.ok(), 'school_login_works');
    const response = await context.request.get(origin + '/api/v1/demo2/simple-result?task_id=' + task, { timeout: 60000 });
    if (response.ok()) { result = await response.json(); break; }
    await context.request.post(origin + '/api/v1/demo2/auth/logout');
  }
  check(Boolean(result), 'task_accessible_to_owner');
  for (let attempt=0; ['pending','retry_wait'].includes(result.analysis?.refresh_status) && attempt<100; attempt++) {
    await new Promise(resolve => setTimeout(resolve, 8000));
    const response = await context.request.get(origin + '/api/v1/demo2/simple-result?task_id=' + task, { timeout: 15000 });
    check(response.ok(), 'refresh_poll_available_status_' + response.status());
    result = await response.json();
  }
  check(result.analysis.analysis_version === 'simple_student_seats_v3_1', 'new_per_person_analysis_version');
  check(result.analysis.persons.length === 3, 'three_person_tracks');
  report.analysis = {version:result.analysis.analysis_version, observedFrames:result.analysis.observed_frames,
    persons:result.analysis.persons.map(p=>({id:p.person_id, windows:p.windows.length,
      pictures:p.windows.filter(w=>w.frame).length, visible:p.visibility,
      at16:p.windows.find(w=>w.start_sec===960)}))};
  check(result.analysis.observed_frames>2200, 'full_lesson_sampled_not_twelve_frames');
  const motions=result.analysis.persons.map(p=>JSON.stringify(p.windows.map(w=>w.movement)));
  check(new Set(motions).size===3, 'independent_person_pixel_measurements');
  for(const p of result.analysis.persons){
    check(p.windows.filter(w=>w.frame).length>60,'person_'+p.person_id+'_whole_lesson_coverage');
    for(const w of p.windows.filter(w=>w.frame)){
      check(w.frame_time_sec>=w.start_sec && w.frame_time_sec<w.end_sec,'same_time_evidence');
      const x=w.bbox.x+w.bbox.width/2, roi=p.observation_roi;
      check(x>=roi.x && x<=roi.x+roi.width,'no_neighbour_seat_substitution');
    }
  }
  const page = await context.newPage();
  page.on('pageerror', e => report.errors.push(e.name));
  page.setDefaultTimeout(60000);
  await page.goto(origin + '/demo2/simple-result?task_id=' + task, { waitUntil: 'domcontentloaded' });
  await page.locator('#personTabs .person-tab').first().waitFor();
  await page.waitForFunction(() => [...document.querySelectorAll('#personTabs img')].every(i => i.complete && i.naturalWidth > 0));
  const sources = await page.locator('#personTabs img').evaluateAll(imgs => imgs.map(i => i.src));
  check(new Set(sources).size === 3 && sources.every(x => x.includes('crop=person')), 'distinct_person_crops');
  await page.locator('#personTabs').screenshot({ path: path.join(output, 'cloud-person-tabs.png') });
  const stateSignatures = [];
  for (let i = 0; i < 3; i++) {
    await page.locator('#personTabs .person-tab').nth(i).click();
    await page.waitForFunction(() => { const im=document.querySelector('.hero-frame'); return im?.complete && im.naturalWidth > 0; });
    check(await page.locator('.person-title h3').innerText() === result.analysis.persons[i].display_name, 'person_' + (i+1) + '_switch');
    const image = page.locator('.hero-frame');
    check(await image.getAttribute('src') !== '', 'person_' + (i+1) + '_image_exists');
    const pixels = await image.evaluate(im => {
      const canvas = document.createElement('canvas'); canvas.width = im.naturalWidth; canvas.height = im.naturalHeight;
      const c = canvas.getContext('2d'); c.drawImage(im, 0, 0); const data = c.getImageData(0, 0, canvas.width, canvas.height).data;
      let colored = 0; for (let p = 0; p < data.length; p += 4) if (Math.max(data[p],data[p+1],data[p+2])-Math.min(data[p],data[p+1],data[p+2])>15) colored++;
      return { width: im.naturalWidth, height: im.naturalHeight, fit: getComputedStyle(im).objectFit, colorFraction: colored/(canvas.width*canvas.height) };
    });
    check(pixels.fit === 'contain' && pixels.colorFraction > .01, 'person_' + (i+1) + '_color_without_second_crop');
    const states = await page.locator('.timeline').innerText();
    stateSignatures.push(crypto.createHash('sha256').update(states).digest('hex'));
    report.portraits.push({ person: i+1, ...pixels, windows: result.analysis.persons[i].windows.length });
    await page.locator('#personPanel').screenshot({ path: path.join(output, 'cloud-person' + (i+1) + '-panel.png') });
    await image.screenshot({ path: path.join(output, 'cloud-person' + (i+1) + '-head.png') });
    await page.locator('.event[data-time="960"]').scrollIntoViewIfNeeded();
    await page.locator('.event[data-time="960"] img').evaluate(im=>im.decode());
    await page.locator('#personPanel').screenshot({ path:path.join(output,'cloud-person'+(i+1)+'-16min.png') });
    for (const thumbnail of await page.locator('.event img').all()) {
      await thumbnail.scrollIntoViewIfNeeded();
      await thumbnail.evaluate(im => new Promise((resolve, reject) => {
        if (im.complete) { im.naturalWidth ? resolve() : reject(new Error('image_failed')); return; }
        im.addEventListener('load', resolve, {once:true}); im.addEventListener('error', () => reject(new Error('image_failed')), {once:true});
      }));
    }
    check(await page.locator('img[src=""]').count() === 0, 'person_' + (i+1) + '_no_empty_images');
    check(await page.locator('.frame-placeholder').filter({ hasText: '截图暂未加载' }).count() === 0, 'person_' + (i+1) + '_no_failed_images');
  }
  check(new Set(stateSignatures).size > 1, 'person_timeline_content_differs');
  const downloaded=await context.request.get(origin+result.task.secure_result_download_url);
  check(downloaded.ok(),'updated_result_download');
  const exported=await downloaded.json();
  check(exported.simple_student_analysis.analysis_version===result.analysis.analysis_version,'download_matches_screen_version');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('#personTabs .person-tab').nth(0).click();
  await page.waitForFunction(() => document.querySelector('.hero-frame')?.complete);
  await page.locator('#personPanel').screenshot({ path: path.join(output, 'cloud-person-mobile.png') });
  check(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'mobile_no_page_overflow');
  check(report.errors.length === 0, 'no_page_script_errors');
  report.passed = true;
})().catch(error => { report.failure = { type: error.name, code: /^[a-z0-9_]+$/.test(error.message) ? error.message : 'browser_check_failed' }; process.exitCode = 1; })
.finally(async () => {
  if (context) await context.request.post(origin + '/api/v1/demo2/auth/logout').catch(() => {});
  if (browser) await browser.close();
  fs.writeFileSync(path.join(output, 'acceptance.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
});
