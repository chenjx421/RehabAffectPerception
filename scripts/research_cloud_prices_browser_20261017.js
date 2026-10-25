const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const out = path.resolve('output/cloud_research_20261017');
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, locale: 'zh-CN' });
    for (const [key, url] of [
      ['tencent_cos_live', 'https://buy.cloud.tencent.com/price/cos'],
      ['tencent_pg_live', 'https://buy.cloud.tencent.com/price/pgsql'],
    ]) {
      const page = await context.newPage();
      try {
        await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 35000 });
        await page.waitForTimeout(12000);
        if (key === 'tencent_cos_live') {
          await page.getByText('上海', { exact: true }).first().click();
          await page.waitForFunction(() => /0\.118/.test(document.body.innerText), { timeout: 30000 });
          fs.writeFileSync(path.join(out, 'tencent_cos_selection.json'), JSON.stringify({
            region: '上海', cloud: '公有云', observed: '2026-10-17', url: page.url(),
            regionElement: await page.getByText('上海', { exact: true }).first().evaluate(el => el.parentElement.outerHTML)
          }, null, 2));
        }
        const text = await page.locator('body').innerText();
        fs.writeFileSync(path.join(out, key + '.txt'), text);
        await page.screenshot({ path: path.join(out, key + '.png'), fullPage: true });
        console.log(JSON.stringify({ id: key, public_only: true, url: page.url(), chars: text.length }));
      } catch (e) {
        console.log(JSON.stringify({ id: key, error_type: e.name }));
      } finally { await page.close(); }
    }
  } finally { await browser.close(); }
})().catch(e => { console.error(e.name); process.exitCode = 1; });
