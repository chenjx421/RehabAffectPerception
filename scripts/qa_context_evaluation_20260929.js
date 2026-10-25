const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const connection = JSON.parse(fs.readFileSync(path.join(root, 'outputs/dual_evaluation_qa/connection.json'), 'utf8'));
const out = path.join(root, 'output/playwright/context_evaluation_20260929');
fs.mkdirSync(out, {recursive: true});

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  const errors = [];
  try {
    const ctx = await browser.newContext({viewport: {width: 1440, height: 1000}});
    await ctx.addCookies([{name:'rehab_demo2_session', value:connection.token, url:connection.url}]);
    const page = await ctx.newPage();
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(connection.url + '/demo2/evaluation');
    await page.waitForFunction(() => document.querySelectorAll('#fTemplate option').length > 1);
    await page.locator('#newBtn').click();
    assert.equal(await page.locator('#fWeightPolicy').inputValue(), 'school_context');
    await page.locator('#fLessonId').fill('synthetic-context-20260929');
    await page.locator('#fLessonDate').fill('2026-09-29');
    await page.locator('#fCourseName').fill('合成验收 · 情境复核课堂');
    await page.locator('#fSubject').selectOption('language');
    await page.locator('#fTemplate').selectOption('basic_100');
    await page.locator('#fGoalContext').fill('合成案例：允许指认、手势和沟通板回应。');
    await page.locator('#fSchoolRater').fill('合成复核员');
    for (let n = 1; n <= 10; n++) {
      await page.locator(`[name=school_i${n}]`).fill(String(6 + (n-1)%5));
      await page.locator(`[name=evidence_i${n}]`).fill('合成记录 02:10-02:40：教案与课堂观察。');
    }
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({path: path.join(out, '00_setup.png')});
    await page.locator('#previewBtn').click();
    await page.locator('#resultCard').waitFor({state: 'visible'});
    assert.equal(await page.locator('#sScore10').textContent(), '8.00');
    assert.equal(await page.locator('#eScore10').textContent(), '8.00');
    await page.locator('#tabEnhanced').click();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({path: path.join(out, '01_ordinary.png')});
    await page.locator('#editRecordBtn').click();
    await page.locator('[name=enhanced_i1]').fill('8');
    await page.locator('[name=reason_i1]').fill('合成片段：教师将口头回答改为指认，学生完成约定任务；原记录遗漏了有效回应。');
    await page.locator('[name=suggestion_i1]').fill('下一课保留指认渠道，核对独立回应。');
    await page.locator('#saveBtn').click();
    await page.waitForFunction(() => !document.querySelector('#exportJsonBtn').disabled);
    assert.equal(await page.locator('#eScore10').textContent(), '8.00');
    assert.match(await page.locator('#contextChanges').textContent(), /1项建议待复核/);
    await page.reload();
    await page.locator('#resultCard').waitFor({state: 'visible'});
    await page.locator('#tabEnhanced').click();
    await page.locator('#contextChanges').screenshot({path: path.join(out, '02_pending.png')});
    await page.locator('#editRecordBtn').click();
    assert.equal(await page.locator('[name=enhanced_i1]').inputValue(), '8');
    await page.locator('#fReviewed').check();
    await page.locator('#saveBtn').click();
    await page.waitForFunction(() => document.querySelector('#eScore10').textContent === '8.20');
    await page.locator('#tabEnhanced').click();
    await page.locator('#contextChanges').screenshot({path: path.join(out, '03_reviewed.png')});
    await page.locator('#tabCompare').click();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({path: path.join(out, '03b_comparison.png')});
    await page.locator('#editRecordBtn').click();
    await page.locator('[name=reason_i1]').fill('修改后的合成证据，需要重新复核。');
    assert.equal(await page.locator('#fReviewed').isChecked(), false);
    for (const width of [390, 320]) {
      await page.setViewportSize({width, height: 900});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
      await page.screenshot({path: path.join(out, `04_mobile_${width}.png`)});
    }
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(out, 'acceptance.json'), JSON.stringify({passed:true, synthetic:true, api_mocked:false, checks:['ordinary equality with unequal scores','pending does not change score','save reload preserves proposals','confirmed changes applied','editing resets confirmation','320/390 no overflow'], errors}, null, 2));
    console.log('Context evaluation browser acceptance passed.');
  } finally { await browser.close(); }
})().catch(e => {console.error(e); process.exitCode = 1;});
