const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const BASE_URL = process.env.DEMO2_URL || 'http://127.0.0.1:8791/seewo_student_demo2';
const OUTPUT_DIR = path.resolve(
  process.env.DEMO2_QA_OUTPUT || 'output/playwright/demo2_v8_round1'
);
const EDGE_PATH = process.env.EDGE_PATH ||
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';

fs.mkdirSync(OUTPUT_DIR, { recursive: true });

async function capture(page, name, options = {}) {
  await page.screenshot({
    path: path.join(OUTPUT_DIR, `${name}.png`),
    animations: 'disabled',
    ...options,
  });
}

async function enterWorkspace(page, options = {}) {
  const device = options.device || (page.viewportSize().width <= 600 ? 'mobile' : 'desktop');
  const captureEntry = options.captureEntry !== false;
  await page.goto(BASE_URL, { waitUntil: 'networkidle' });
  await page.evaluate(() => {
    localStorage.clear();
    sessionStorage.clear();
  });
  await page.reload({ waitUntil: 'networkidle' });
  if (captureEntry) {
    await capture(page, `00_entry_viewport_${device}`);
    await capture(page, `01_entry_full_${device}`, { fullPage: true });
  }

  await page.locator('#entrySecurityConfirmed').check();
  await page.locator('#entryCompanyArchive').check();
  while (await page.locator('#entryNextButton').isVisible()) {
    await page.locator('#entryNextButton').click();
  }
  await page.locator('#entryConfirmed').check();
  if (captureEntry) {
    await capture(page, `01_confirm_viewport_${device}`);
    await capture(page, `02_entry_confirm_full_${device}`, { fullPage: true });
  }
  await page.locator('#enterDemoButton').click();
  await page.locator('#entryGate').waitFor({ state: 'hidden' });
  await page.locator('main').waitFor({ state: 'visible' });
  await page.waitForTimeout(300);
}

async function openTab(page, tabName) {
  const button = page.locator(`[data-tab="${tabName}"]`);
  await button.scrollIntoViewIfNeeded();
  await button.click();
  await page.waitForTimeout(250);
}

async function collectMetrics(page, label, errors) {
  return page.evaluate(({ currentLabel, capturedErrors }) => {
    const root = document.documentElement;
    const activeTab = document.querySelector('[data-tab].active');
    const isVisible = (item) => {
      const rect = item.getBoundingClientRect();
      const style = getComputedStyle(item);
      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden';
    };
    const visibleButtons = [...document.querySelectorAll('button')]
      .filter(isVisible);
    const visibleFields = [...document.querySelectorAll('input,select,textarea')]
      .filter(isVisible);
    const unnamedControls = [...document.querySelectorAll('button,input,select,textarea,a')]
      .filter(isVisible)
      .filter((item) => !(item.getAttribute('aria-label') || item.getAttribute('title') || item.textContent.trim() || item.labels?.length));
    const brokenImages = [...document.images]
      .filter((item) => item.offsetParent !== null && (!item.complete || item.naturalWidth === 0));
    return {
      label: currentLabel,
      viewport: { width: innerWidth, height: innerHeight },
      document: { width: root.scrollWidth, height: root.scrollHeight },
      horizontalOverflow: root.scrollWidth - root.clientWidth,
      activeTab: activeTab?.dataset.tab || null,
      scrollY,
      visibleButtons: visibleButtons.length,
      buttonsUnder36px: visibleButtons.filter((item) => item.getBoundingClientRect().height < 36).length,
      buttonsUnder40px: visibleButtons.filter((item) => item.getBoundingClientRect().height < 40).length,
      smallButtons: visibleButtons
        .filter((item) => item.getBoundingClientRect().height < 40)
        .slice(0, 10)
        .map((item) => ({
          id: item.id || null,
          className: item.className || null,
          text: item.textContent.trim().slice(0, 40),
          height: Math.round(item.getBoundingClientRect().height),
        })),
      fieldsUnder40px: visibleFields.filter((item) => item.getBoundingClientRect().height < 40).length,
      unnamedControls: unnamedControls.length,
      brokenImages: brokenImages.length,
      visibleIcons: [...document.querySelectorAll('svg')].filter((item) => item.offsetParent !== null).length,
      consoleErrors: capturedErrors,
    };
  }, { currentLabel: label, capturedErrors: errors });
}

async function collectThemeAudit(page) {
  return page.evaluate(() => {
    const style = getComputedStyle(document.documentElement);
    const tokens = Object.fromEntries([
      '--canvas','--paper','--ink','--muted','--navy-deep','--teal','--coral','--line',
    ].map((name) => [name, style.getPropertyValue(name).trim()]));
    const hexToRgb = (hex) => {
      const value = hex.replace('#','');
      return [0,2,4].map((index) => parseInt(value.slice(index,index + 2),16) / 255);
    };
    const luminance = (hex) => hexToRgb(hex)
      .map((value) => value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
      .reduce((sum,value,index) => sum + value * [0.2126,0.7152,0.0722][index],0);
    const contrast = (foreground,background) => {
      const [high,low] = [luminance(foreground),luminance(background)].sort((a,b) => b - a);
      return Number(((high + 0.05) / (low + 0.05)).toFixed(2));
    };
    const contrastPairs = {
      inkOnCanvas: contrast(tokens['--ink'],tokens['--canvas']),
      mutedOnCanvas: contrast(tokens['--muted'],tokens['--canvas']),
      whiteOnDeepMineral: contrast('#ffffff',tokens['--navy-deep']),
      tealOnCanvas: contrast(tokens['--teal'],tokens['--canvas']),
      reviewTextOnReviewSurface: contrast('#955346','#fbf3f0'),
    };
    const colorCounts = new Map();
    [...document.querySelectorAll('body *')]
      .filter((element) => element.offsetParent !== null)
      .forEach((element) => {
        const computed = getComputedStyle(element);
        [computed.color,computed.backgroundColor,computed.borderTopColor].forEach((value) => {
          if (!value || value === 'rgba(0, 0, 0, 0)' || value === 'transparent') return;
          colorCounts.set(value,(colorCounts.get(value) || 0) + 1);
        });
      });
    const renderedPalette = [...colorCounts.entries()]
      .sort((left,right) => right[1] - left[1])
      .slice(0,20)
      .map(([color,count]) => ({ color,count }));
    return { tokens,contrastPairs,renderedPalette };
  });
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: EDGE_PATH,
  });
  const report = { url: BASE_URL, createdAt: new Date().toISOString(), pages: [], tabAudits: [], interactions: [] };

  try {
    const desktop = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    const desktopErrors = [];
    desktop.on('console', (message) => {
      if (message.type() === 'error') desktopErrors.push(message.text());
    });
    desktop.on('pageerror', (error) => desktopErrors.push(error.message));

    await enterWorkspace(desktop);
    report.theme = await collectThemeAudit(desktop);
    report.performance = await desktop.evaluate(() => {
      const navigation = performance.getEntriesByType('navigation')[0];
      return {
        transferSize: navigation?.transferSize || 0,
        encodedBodySize: navigation?.encodedBodySize || 0,
        decodedBodySize: navigation?.decodedBodySize || 0,
        domContentLoadedMs: Math.round(navigation?.domContentLoadedEventEnd || 0),
        loadEventMs: Math.round(navigation?.loadEventEnd || 0),
        domNodes: document.querySelectorAll('*').length,
        resourceCount: performance.getEntriesByType('resource').length,
      };
    });
    report.interactions.push({
      name: 'theme_contrast',
      passed: Object.values(report.theme.contrastPairs).every((ratio) => ratio >= 4.5),
      ratios: report.theme.contrastPairs,
    });
    await capture(desktop, '03_workspace_desktop');
    await capture(desktop, '04_workspace_full_desktop', { fullPage: true });

    await desktop.locator('#portraitMode').click();
    await desktop.waitForTimeout(200);
    await capture(desktop, '04a_portrait_mode_desktop');
    const portraitSource = await desktop.locator('#classImage').getAttribute('src');
    await desktop.locator('#groupMode').click();
    const groupSource = await desktop.locator('#classImage').getAttribute('src');
    const studentCount = await desktop.locator('[data-overview-student]').count();
    for (let index = 0; index < studentCount; index += 1) {
      await desktop.locator('[data-overview-student]').nth(index).click();
    }
    report.interactions.push({
      name: 'portrait_group_switch',
      passed: Boolean(portraitSource && groupSource && portraitSource !== groupSource),
    });
    report.interactions.push({
      name: 'three_student_switch',
      passed: studentCount === 3 && await desktop.locator('[data-overview-student].active').count() === 1,
    });

    const tabs = [
      ['profile', '05_profile_desktop'],
      ['tracking', '06_tracking_desktop'],
      ['profileImport', '06a_profile_import_desktop'],
      ['state', '07_state_timeline_desktop'],
      ['interaction', '05_interaction_desktop'],
      ['evidence', '06_teacher_review_desktop'],
      ['teacher', '07_support_effect_desktop'],
      ['mastery', '08_mastery_desktop'],
      ['specialSupport', '09_support_tools_desktop'],
      ['action', '10_action_plan_desktop'],
      ['growth', '08_growth_desktop'],
      ['courseReport', '09_course_report_desktop'],
      ['feedback', '11_deep_report_start_desktop'],
      ['summary', '12_data_source_desktop'],
      ['videoUpload', '12a_four_channel_upload_desktop'],
      ['storage', '12b_storage_governance_desktop'],
      ['json', '13_json_desktop'],
    ];
    for (const [tab, fileName] of tabs) {
      await openTab(desktop, tab);
      await desktop.locator('.analysis-studio').scrollIntoViewIfNeeded();
      await capture(desktop, fileName);
      report.tabAudits.push(await collectMetrics(desktop, `desktop:${tab}`, desktopErrors));
      if (tab === 'evidence') {
        await capture(desktop, '06_teacher_review_full_desktop', { fullPage: true });
      }
      if (tab === 'courseReport') {
        await desktop.emulateMedia({ media: 'print' });
        await capture(desktop, '09a_course_report_print_preview', { fullPage: true });
        await desktop.pdf({
          path: path.join(OUTPUT_DIR, 'course_report_print.pdf'),
          format: 'A4',
          printBackground: true,
          margin: { top: '16mm', right: '17mm', bottom: '16mm', left: '17mm' },
        });
        const printState = await desktop.evaluate(() => ({
          headerHidden: getComputedStyle(document.querySelector('header')).display === 'none',
          reportVisible: document.querySelector('.course-report')?.offsetParent !== null,
        }));
        report.interactions.push({
          name: 'course_report_print_layout',
          passed: printState.headerHidden && printState.reportVisible,
        });
        await desktop.emulateMedia({ media: 'screen' });
      }
    }

    await openTab(desktop, 'evidence');
    const reviewClips = desktop.locator('details.review-clip');
    const reviewClipCount = await reviewClips.count();
    const initiallyOpenReviewClips = await reviewClips.evaluateAll((items) => items.filter((item) => item.open).length);
    const firstReviewClip = reviewClips.first();
    if (!(await firstReviewClip.evaluate((item) => item.open))) {
      await firstReviewClip.locator('summary').click();
    }
    await firstReviewClip.locator('[data-review="需修正"]').click();
    const updatedReviewState = await desktop.locator('details.review-clip').first().locator('.clip-review-state').textContent();
    report.interactions.push({
      name: 'teacher_review_disclosure_and_verdict',
      passed: reviewClipCount > 1 && initiallyOpenReviewClips === 1 && updatedReviewState?.trim() === '需修正',
      reviewClipCount,
      initiallyOpenReviewClips,
    });

    await openTab(desktop, 'state');
    const allStateRows = await desktop.locator('#tabBody tbody tr').count();
    await desktop.locator('[data-state-filter="review"]').click();
    const filteredStateRows = await desktop.locator('#tabBody tbody tr').count();
    report.interactions.push({
      name: 'review_only_state_filter',
      passed: allStateRows > filteredStateRows && filteredStateRows > 0,
      allStateRows,
      filteredStateRows,
    });

    await openTab(desktop, 'specialSupport');
    await desktop.locator('#startWaitTimer').click();
    const timerStarted = await desktop.locator('#startWaitTimer').isDisabled();
    await desktop.waitForFunction(() => document.querySelector('#waitTimerValue')?.textContent.includes('等待完成'), null, { timeout: 8000 });
    const timerCompleted = !(await desktop.locator('#startWaitTimer').isDisabled())
      && (await desktop.locator('#startWaitTimer').textContent())?.includes('再次等待6秒');
    report.interactions.push({
      name: 'low_stimulation_wait_timer',
      passed: timerStarted && Boolean(timerCompleted),
    });

    await openTab(desktop, 'profile');
    await desktop.locator('[data-tab="profile"]').focus();
    await desktop.keyboard.press('ArrowRight');
    report.interactions.push({
      name: 'keyboard_tab_navigation',
      passed: await desktop.locator('[data-tab="tracking"]').getAttribute('aria-selected') === 'true',
    });
    await openTab(desktop, 'feedback');
    const reportStartedAt = Date.now();
    await desktop.locator('#generateReport').click();
    await desktop.locator('#copyReport').waitFor({ state: 'visible', timeout: 30000 });
    report.performance.longReportGenerationMs = Date.now() - reportStartedAt;
    await desktop.locator('.analysis-studio').scrollIntoViewIfNeeded();
    await capture(desktop, '14_deep_report_generated_desktop');
    report.interactions.push({
      name: 'local_long_report_generation',
      passed: await desktop.locator('#copyReport').isVisible(),
    });
    report.pages.push(await collectMetrics(desktop, 'desktop', desktopErrors));
    await desktop.close();

    for (const preset of [
      { name: 'school_laptop_1366', width: 1366, height: 768 },
      { name: 'tablet_1024', width: 1024, height: 900 },
      { name: 'tablet_768', width: 768, height: 900 },
    ]) {
      const tablet = await browser.newPage({ viewport: { width: preset.width, height: preset.height } });
      const tabletErrors = [];
      tablet.on('console', (message) => {
        if (message.type() === 'error') tabletErrors.push(message.text());
      });
      tablet.on('pageerror', (error) => tabletErrors.push(error.message));
      await enterWorkspace(tablet, { device: preset.name, captureEntry: false });
      await capture(tablet, `15_workspace_${preset.name}`);
      await openTab(tablet, 'interaction');
      await tablet.locator('.analysis-studio').scrollIntoViewIfNeeded();
      await capture(tablet, `16_interaction_${preset.name}`);
      report.pages.push(await collectMetrics(tablet, preset.name, tabletErrors));
      await tablet.close();
    }

    const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
    const mobileErrors = [];
    mobile.on('console', (message) => {
      if (message.type() === 'error') mobileErrors.push(message.text());
    });
    mobile.on('pageerror', (error) => mobileErrors.push(error.message));
    await enterWorkspace(mobile);
    await capture(mobile, '10_workspace_mobile', { fullPage: true });
    await openTab(mobile, 'interaction');
    await mobile.locator('.analysis-studio').scrollIntoViewIfNeeded();
    await capture(mobile, '11_interaction_mobile');
    await openTab(mobile, 'evidence');
    await mobile.locator('.analysis-studio').scrollIntoViewIfNeeded();
    await capture(mobile, '12_teacher_review_mobile');
    await openTab(mobile, 'profile');
    await mobile.locator('.analysis-studio').scrollIntoViewIfNeeded();
    await capture(mobile, '13_profile_mobile');
    await openTab(mobile, 'courseReport');
    await mobile.locator('.analysis-studio').scrollIntoViewIfNeeded();
    await capture(mobile, '14_course_report_mobile');
    const mobileTabs = [
      'profile','tracking','profileImport','state','interaction','evidence','teacher','mastery',
      'specialSupport','action','growth','courseReport','feedback','summary','videoUpload','storage','json',
    ];
    for (const tab of mobileTabs) {
      await openTab(mobile, tab);
      report.tabAudits.push(await collectMetrics(mobile, `mobile:${tab}`, mobileErrors));
      if (tab === 'specialSupport') await capture(mobile, '15_support_tools_mobile');
      if (tab === 'action') await capture(mobile, '16_action_plan_mobile');
      if (tab === 'growth') await capture(mobile, '17_growth_mobile');
      if (tab === 'profileImport') await capture(mobile, '17a_profile_import_mobile');
      if (tab === 'videoUpload') await capture(mobile, '17b_four_channel_upload_mobile');
      if (tab === 'storage') await capture(mobile, '17c_storage_governance_mobile');
    }
    report.pages.push(await collectMetrics(mobile, 'mobile', mobileErrors));
    await mobile.close();

    const mobileNarrow = await browser.newPage({ viewport: { width: 360, height: 800 } });
    const mobileNarrowErrors = [];
    mobileNarrow.on('console', (message) => {
      if (message.type() === 'error') mobileNarrowErrors.push(message.text());
    });
    mobileNarrow.on('pageerror', (error) => mobileNarrowErrors.push(error.message));
    await enterWorkspace(mobileNarrow, { device: 'mobile_360' });
    await capture(mobileNarrow, '18_workspace_mobile_360', { fullPage: true });
    for (const tab of ['state', 'evidence', 'specialSupport', 'courseReport', 'profileImport', 'videoUpload', 'storage']) {
      await openTab(mobileNarrow, tab);
      report.tabAudits.push(await collectMetrics(mobileNarrow, `mobile_360:${tab}`, mobileNarrowErrors));
    }
    report.pages.push(await collectMetrics(mobileNarrow, 'mobile_360', mobileNarrowErrors));
    await mobileNarrow.close();

    fs.writeFileSync(
      path.join(OUTPUT_DIR, 'qa-report.json'),
      JSON.stringify(report, null, 2),
      'utf8'
    );
    process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
  } finally {
    await browser.close();
  }
})().catch((error) => {
  process.stderr.write(`${error.stack || error.message}\n`);
  process.exitCode = 1;
});
