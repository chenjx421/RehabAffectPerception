// Screenshots and interaction acceptance against a disposable local database.
const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const sharp = require('sharp');
const ROOT = path.resolve(__dirname, '..');
const OUT = path.join(ROOT, 'output/playwright/dual_evaluation_20260916');
const connection = JSON.parse(fs.readFileSync(path.join(ROOT, 'outputs/dual_evaluation_qa/connection.json'), 'utf8'));
const manifest = { synthetic: true, api_mocked: false, viewport: { width: 1440, height: 1020 }, pages: [], checks: [], errors: [] };
fs.mkdirSync(OUT, { recursive: true });

async function main() {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const context = await browser.newContext({ viewport: manifest.viewport, deviceScaleFactor: 2, locale: 'zh-CN' });
    await context.addCookies([{ name: 'rehab_demo2_session', value: connection.token, url: connection.url }]);
    const page = await context.newPage();
    page.on('pageerror', e => manifest.errors.push(e.message));
    async function shot(name, selector = null) {
      await page.evaluate(() => document.fonts.ready);
      const destination = path.join(OUT, name + '.png');
      const buffer = selector
        ? await page.locator(selector).screenshot({ path: destination, animations: 'disabled' })
        : await page.screenshot({ path: destination, animations: 'disabled' });
      const metadata = await sharp(buffer).metadata();
      const stats = await sharp(buffer).stats();
      assert(stats.channels.some(c => c.stdev > 8), 'blank image');
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
      assert.equal(overflow, false, name + ' horizontal overflow');
      manifest.pages.push({ name, filename: path.basename(destination), width: metadata.width, height: metadata.height, overflow, synthetic: true });
      console.log('captured ' + name);
    }
    await page.goto(connection.url + '/demo2/login');
    await shot('01_login');
    await page.goto(connection.url + '/demo2/evaluation');
    await page.waitForFunction(() => document.querySelectorAll('#fTemplate option').length > 1);
    await page.locator('#newBtn').click();
    await page.locator('#fLessonId').fill('synthetic-visual-20260916');
    await page.locator('#fLessonDate').fill('2026-09-15');
    await page.locator('#fCourseName').fill('合成演示 · 生活数学课堂');
    await page.locator('#fSubject').selectOption('math');
    await page.locator('#fTemplate').selectOption('basic_100');
    await page.locator('#fGoalContext').fill('合成演示数据，不代表真实课堂。围绕物品分类设置分层目标，允许指认、手势及实物操作回应；按课前约定的提示条件核对目标达成。');
    await page.locator('#fSchoolRater').fill('演示复核员');
    await page.evaluate(() => window.scrollTo(0, 0));
    await shot('02_course_setup');
    const scores = [8, 8, 8, 8, 8, 9, 6, 6, 8, 9];
    const changes = {
      6: ['合成片段 06:20-07:10：提供实物与图卡两种回应方式。', '复核发现可及性支持比原记录更充分。', '保留实物与图卡支持，记录学生使用哪种方式。'],
      7: ['合成片段 10:00-12:00：部分学生重复回应，另有学生缺少独立机会。', '活跃发言不能代表全体学生都有参与机会。', '下一课为每名学生安排可观察的回应机会。'],
      8: ['合成片段 18:10-19:00：部分正确答案出现在完整示范之后。', '示范后完成与约定条件下独立完成需分别记录。', '安排相似材料的独立尝试，并记录提示程度。'],
      10: ['合成片段 22:00-23:00：重复指令后改为一步指令并延长等待。', '观察到教师根据回应困难调整教学。', '保留调整前后片段，下一课复查是否稳定。']
    };
    for (let n = 1; n <= 10; n++) {
      await page.locator(`[name=school_i${n}]`).fill('8');
      await page.locator(`[name=enhanced_i${n}]`).fill(String(scores[n-1]));
      await page.locator(`[name=evidence_i${n}]`).fill(changes[n]?.[0] || '合成教案与观察记录：目标、材料和支持条件已对应。本条仅演示录入流程。');
      if (changes[n]) {
        await page.locator(`[name=reason_i${n}]`).fill(changes[n][1]);
        await page.locator(`[name=suggestion_i${n}]`).fill(changes[n][2]);
      }
    }
    await page.locator('#fReviewed').check();
    await page.locator('#previewBtn').click();
    await page.locator('#resultCard').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#sScore10').textContent(), '8.00');
    assert.equal(await page.locator('#eScore10').textContent(), '7.57');
    assert.equal(await page.locator('#exportJsonBtn').isDisabled(), true);
    manifest.checks.push('preview computed by live API, unsaved export disabled');
    await page.locator('#editRecordBtn').click();
    await page.locator('#saveBtn').click();
    await page.waitForFunction(() => !document.querySelector('#exportJsonBtn').disabled);
    await page.evaluate(() => window.scrollTo(0, 0));
    await shot('03_school_workspace');
    await shot('04_school_result', '#resultCard');
    await page.locator('#tabEnhanced').click();
    await page.evaluate(() => window.scrollTo(0, 0));
    await shot('05_enhanced_workspace');
    await shot('06_enhanced_summary', '#panelEnhanced .score-grid');
    await shot('07_weights_and_chart', '#eChartWrap');
    await shot('08_enhanced_reasons', '.evidence-reasons');
    await page.locator('#tabCompare').click();
    await page.evaluate(() => window.scrollTo(0, 0));
    await shot('09_comparison_workspace');
    await shot('10_comparison_result', '#panelCompare');
    await page.locator('#tabRefs').click();
    await page.evaluate(() => window.scrollTo(0, 0));
    await shot('11_references_workspace');
    await shot('12_references', '#panelRefs');
    await page.locator('#tabRefs').focus();
    await page.keyboard.press('Home');
    assert.equal(await page.locator('#tabSchool').getAttribute('aria-selected'), 'true');
    manifest.checks.push('tab keyboard navigation');
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#exportJsonBtn').click();
    const download = await downloadPromise;
    const saved = JSON.parse(fs.readFileSync(await download.path(), 'utf8'));
    assert.equal(saved.result.enhanced.score_10, 7.57);
    assert.equal(saved.result.comparison.total_delta, -0.43);
    manifest.checks.push('downloaded JSON matches server: 8.00 / 7.57, delta -0.43');
    await page.reload();
    await page.locator('#resultCard').waitFor({ state: 'visible' });
    assert.equal(await page.locator('#sScore10').textContent(), '8.00');
    manifest.checks.push('saved record restored after reload');
    await page.locator('#editRecordBtn').click();
    await page.locator('[name=school_i1]').fill('7');
    assert.equal(await page.locator('#resultCard').isVisible(), false);
    await page.locator('[name=school_i1]').fill('8');
    await page.locator('#saveBtn').click();
    await page.waitForFunction(() => document.querySelector('#resultMeta').textContent.includes('版本 2'));
    manifest.checks.push('editing invalidates stale result and saves version 2');
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      await page.evaluate(() => window.scrollTo(0, 0));
      await shot('mobile_' + width);
      await page.locator('#editRecordBtn').click();
      await page.locator('[name=school_i1]').scrollIntoViewIfNeeded();
      await shot('mobile_form_' + width);
    }
    assert.deepEqual(manifest.errors, []);
  } finally {
    await browser.close();
    fs.writeFileSync(path.join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 2));
  }
}
main().catch(e => { console.error(e); process.exitCode = 1; });
