// فحوص تصميم على الواجهة المعروضة بأداة lintapple الأصلية، بما فيها حالات الواجهة المفتوحة.
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require('playwright');
const measureGlassContrast=require('./glass-contrast.cjs');

(async () => {
  const { checkPage } = await import('lintapple');
  const root = path.resolve(__dirname, '..');
  const policy = JSON.parse(await fs.readFile(path.join(root, 'ui-policy.json'), 'utf8'));
  const retry=process.argv.includes('--retry-failed');
  const previous=retry?JSON.parse(await fs.readFile(path.join(root,'results','ui-lint.json'),'utf8')):null;
  const key=(width,state)=>`${width}:${state}`;
  const failedKeys=new Set(previous?.runs.filter(run=>run.findings.length).map(run=>key(run.viewport.width,run.state))||[]);
  if(retry&&process.argv.includes('--include-city-lists'))for(const viewport of policy.viewports)failedKeys.add(key(viewport.width,'city-list-open'));
  const browser = await chromium.launch({ headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const report = { tool: 'lintapple', version: '0.1.20', url: process.env.APP_URL || 'http://127.0.0.1:8000', runs: [], findings: [], runtimeErrors: [] };
  if(retry)report.runs=previous.runs.filter(run=>!failedKeys.has(key(run.viewport.width,run.state))).map(run=>({...run,retained:true}));
  report.retainedChecks=report.runs.length;
  try {
    for (const viewport of policy.viewports) {
      const context = await browser.newContext({ viewport, colorScheme: 'dark', reducedMotion: 'reduce', locale: 'ar', deviceScaleFactor: 1 });
      const page = await context.newPage();
      page.on('pageerror', error => report.runtimeErrors.push(error.message));
      await page.goto(report.url, { waitUntil: 'load', timeout: 90000 });
      await page.locator('body[data-app-ready]').waitFor({ timeout: 90000 });
      async function audit(state) {
        if(retry&&!failedKeys.has(key(viewport.width,state)))return;
        const result = await checkPage(page, policy);
        const popupSamples=await page.evaluate(()=>[...document.querySelectorAll('.spring-menu:not([hidden]) .spring-option>span,.spring-menu:not([hidden]) .spring-group')].map(node=>({rule:'text-contrast',selector:`#${node.id}`})));
        if(policy.exceptions.some(exception=>exception.rules.includes('text-contrast'))||process.argv.includes('--pixels')){
          result.pixelContrast=await measureGlassContrast(page,[...result.findings,...result.suppressed,...popupSamples],state==='initial'||state==='details-open');
          console.log(`Pixel contrast: ${result.pixelContrast.samples} text ranges; ${result.pixelContrast.failures.length} failures; ${result.pixelContrast.unmeasured?.length||0} unmeasured`);
          for(const finding of result.pixelContrast.failures)console.log(JSON.stringify(finding));
          for(const finding of result.pixelContrast.failures)result.findings.push({rule:'text-contrast',status:'failed',...finding,message:'Rendered background pixels do not meet WCAG AA.'});
          if((state==='initial'||state==='details-open')&&result.pixelContrast.unmeasured.length)result.findings.push({rule:'text-contrast',status:'unresolved',message:'Some optical text was not measured.',selectors:result.pixelContrast.unmeasured});
        }
        report.runs.push({ viewport, state, checkedAt:new Date().toISOString(),...result });
        report.findings.push(...result.findings.map(finding => ({ ...finding, viewport, state })));
        await page.screenshot({ path: path.join(root, 'results', `ui-${viewport.width}-${state}.png`) });
        console.log(`${viewport.width}px ${state}: ${result.findings.length} findings`);
      }
      await audit('initial');
      if (!process.argv.includes('--initial')) {
        if (viewport.width <= 1020&&(!retry||failedKeys.has(key(viewport.width,'navigation-open')))) {
          await page.locator('#menuBtn').click();
          await audit('navigation-open');
          await page.keyboard.press('Escape');
        }
        await page.locator('#lab').evaluate(el => window.scrollTo({ top: scrollY + el.getBoundingClientRect().top - 90, behavior: 'instant' }));
        await page.waitForFunction(()=>window.__viewers.find(v=>v.c.id==='labCanvas')?.world&&!document.querySelector('#labRun').disabled,{},{timeout:90000});
        await page.locator('#labCity-trigger').click();
        await audit('city-list-open');
        await page.keyboard.press('Escape');
        await page.locator('#labStage').evaluate(el => window.scrollTo({ top: scrollY + el.getBoundingClientRect().top - 90, behavior: 'instant' }));
        await audit('flight-controls');
        await page.evaluate(()=>document.querySelectorAll('.case-card,.flight-details details,.sensitivity').forEach(node=>node.open=true));
        await audit('details-open');
      }
      await context.close();
    }
  } finally { await browser.close(); }
  const counts = {};
  for (const finding of report.findings) counts[finding.rule] = (counts[finding.rule] || 0) + 1;
  report.passed = !report.findings.length && !report.runtimeErrors.length;
  await fs.writeFile(path.join(root, 'results', 'ui-lint.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ passed: report.passed, checks: report.runs.length, rechecked:report.runs.length-report.retainedChecks,retained:report.retainedChecks,findings: report.findings.length, rules: counts, runtimeErrors: report.runtimeErrors }, null, 2));
  process.exitCode = report.passed ? 0 : 1;
})().catch(error => { console.error(error); process.exitCode = 2; });
