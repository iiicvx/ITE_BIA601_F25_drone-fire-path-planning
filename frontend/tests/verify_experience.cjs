// فحص تكامل اختياري في المتصفح؛ ثبّت أدوات الواجهة وChromium أولًا.
// من جذر المشروع: node frontend/tests/verify_experience.cjs (ويغير APP_URL العنوان المحلي).
// لقطات الشاشة دليل على ناتج WebGL الفعلي، لا على مشاهد اختبار محاكاة.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1, reducedMotion: 'reduce' });
  page.setDefaultTimeout(60000);
  const errors = [], warnings = [], liveRequests = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') warnings.push(message.text()); });
  page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/api/live')) liveRequests.push(request.url()); });
  const base = process.env.APP_URL || 'http://127.0.0.1:8000';
  async function choose(selector,value){
    const option=await page.locator(selector).evaluate((select,value)=>({id:select.id,label:[...select.options].find(option=>option.value===value)?.textContent}),value);
    assert.ok(option.label,`missing ${selector} option ${value}`);
    await page.locator(`#${option.id}-trigger`).click();
    await page.locator(`#${option.id}-list`).getByRole('option',{name:option.label,exact:true}).click();
  }
  async function capture(name) {
    await page.locator('#labStage').evaluate(el => window.scrollTo({ top: el.getBoundingClientRect().top + scrollY - 90, behavior: 'instant' }));
    await page.screenshot({ path: path.join(__dirname, '../results', name) });
  }
  try {
    await page.goto(base + '/#lab', { waitUntil: 'networkidle', timeout: 90000 });
    await page.waitForFunction(() => document.querySelector('.stage-loading[data-for="labCanvas"]').classList.contains('done'), null, { timeout: 60000 });
    await page.locator('body[data-app-ready]').waitFor();
    const tenCases = ['empty_city', 'behind_tall_tower', 'narrow_street', 'fire_on_line', 'target_near_fire',
      'crossing_drones', 'maze', 'enclosed_target', 'small_battery', 'tiny_battery'].map(name => `special_${name}`);
    assert.equal(await page.locator('#specialCases .case-card').count(), 10);
    assert.deepEqual(await page.locator('#labCity optgroup option').evaluateAll(options => options.map(option => option.value)), tenCases);
    assert.equal(await page.locator('#specialTable tbody tr').count(), 10);
    assert.equal(await page.locator('#labSource, #labSeed, #labBudget, #labProgress').count(), 0);
    console.log('Ready: real scenes, fleet winners and ten cases');
    if(!process.argv.includes('--from-city')){
    assert.equal(await page.locator('#winnerOverview .winner-card').count(), 3);
    assert.deepEqual(await page.locator('#winnerOverview .winner-code').allTextContents(), ['GA', 'ACO', 'ACO']);
    assert.equal(await page.locator('#insightCards .insight-card').count(), 4);
    assert.equal(await page.locator('#labCameraTools select option').count(), 3);
    await page.locator('#labCameraTools [data-camera="follow"]').click();
    await choose('#labCameraTools select','1');
    assert.deepEqual(await page.evaluate(() => { const v = window.__viewers.find(v => v.c.id === 'labCanvas'); return [v.S.camera, v.S.selected]; }), ['follow', 1]);
    await page.locator('#labCameraTools [data-camera="cockpit"]').click();
    await page.locator('#missionScrub').fill('450');
    await page.locator('#labCameraTools [data-restart]').click();
    assert.equal(await page.evaluate(()=>window.__viewers.find(v=>v.c.id==='labCanvas').S.camera),'cockpit');
    assert.ok(await page.evaluate(()=>window.__viewers.find(v=>v.c.id==='labCanvas').S.t<5));
    await page.locator('#missionScrub').fill('450');
    for (const key of ['lights', 'rotors', 'spotlight', 'dimensions']) {
      await page.locator(`[data-option="${key}"]`).click();
      assert.equal(await page.locator(`[data-option="${key}"]`).getAttribute('aria-checked'), ['lights', 'rotors'].includes(key) ? 'false' : 'true');
    }
    await capture('qa-lab-desktop.png');
    console.log('Verified: follow, cockpit, drone selection, operating switches');
    await page.locator('#labCameraTools [data-camera="orbit"]').click();
    for (const key of ['paths', 'danger', 'margins', 'realScale']) {
      const control = page.locator(`[data-option="${key}"]`);
      const previous = await control.getAttribute('aria-checked');
      await control.click();
      assert.equal(await control.getAttribute('aria-checked'), previous === 'true' ? 'false' : 'true');
      await page.waitForFunction(({key, expected}) => {
        const v = window.__viewers.find(v => v.c.id === 'labCanvas'), drone = v.world.swarms[0].drones[0];
        if (key === 'paths') return drone.plan.visible === expected;
        if (key === 'danger') return v.world.fires.cores.visible === expected;
        if (key === 'margins') return v.world.city.margins.visible === expected;
        return v.S.realScale === expected && (!expected || drone.root.scale.x === 1);
      }, {key, expected: previous !== 'true'});
      assert.ok(await control.getAttribute('aria-describedby'));
      await control.click();
    }
    }
    await choose('#labCity','large');
    await page.waitForFunction(() => window.__viewers.find(v => v.c.id === 'labCanvas')?.world?.data.problem.n_drones === 6);
    assert.equal(await page.locator('#labCameraTools select option').count(), 7);
    await page.locator('#labCameraTools [data-camera="follow"]').click();
    await choose('#labCameraTools select','5');
    await page.locator('#missionScrub').fill('300');
    await capture('qa-city-large.png');
    console.log('Verified: six-drone large city');
    await choose('#labCity','special_crossing_drones');
    await choose('#labAlg','DP');
    await page.waitForFunction(() => document.querySelector('#labTele .status-unsafe'));
    // الخطة المرفوضة تبدأ مخفية خلف بوابة التشخيص، ثم تظهر عند طلب المعاينة دون مؤثرات نجاح.
    await page.waitForFunction(() => !document.querySelector('#labGate').hidden && window.__viewers.find(v => v.c.id === 'labCanvas').world.swarms[0].group.visible === false);
    await page.locator('#labPreview').click();
    assert.ok(await page.evaluate(() => window.__viewers.find(v => v.c.id === 'labCanvas').world.swarms[0].group.visible));
    // مؤثرات النجاح تتطلب حكمًا صريحًا: الرفض أو غياب الحكم يمنع الإطلاق، والخطة الآمنة تبقى كما هي.
    const verdicts = await page.evaluate(async () => {
      const v = window.__viewers.find(v => v.c.id === 'labCanvas');
      const saved = await (await fetch('/api/special/special_target_near_fire/PSO/scene')).json();
      const variants = { rejected: r => { r.valid = false; r.feasible = false; }, missingValid: r => { delete r.valid; },
        missingFeasible: r => { delete r.feasible; }, nullVerdict: r => { r.valid = null; }, safe: () => {} };
      const out = {};
      for (const [name, change] of Object.entries(variants)) {
        const payload = structuredClone(saved); change(payload.runs[0]);
        await v.showPayload(payload);
        const swarm = v.world.swarms[0], drone = swarm.drones[0];
        out[name] = { thrown: drone.throwInfo !== null, burning: v.world.fires.items.every(item => item.tEnd === Infinity), status: swarm.status(drone, v.T, v.world.fires) };
      }
      return out;
    });
    const refused = { thrown: false, burning: true, status: 'خطة مرفوضة: لا إطلاق' };
    assert.deepEqual(verdicts, { rejected: refused, missingValid: refused, missingFeasible: refused, nullVerdict: refused,
      safe: { thrown: true, burning: false, status: 'أُخمد الحريق' } });
    console.log('Verified: independent rejection of crossing-drone DP without a success replay');
    await page.waitForFunction(() => !document.querySelector('#labRun').disabled);
    await page.locator('.case-card').filter({ has: page.locator('[data-case="special_target_near_fire"]') }).locator('summary').click();
    await page.locator('[data-case="special_target_near_fire"]').click();
    await page.waitForFunction(() => !document.querySelector('#labRun').disabled && window.__viewers.find(v => v.c.id === 'labCanvas').world.data.name === 'special_target_near_fire');
    assert.equal(await page.locator('#labCity').inputValue(), 'special_target_near_fire');
    assert.equal(await page.locator('#labTele .status-safe').count(), 1);
    assert.equal(await page.locator('#labAlg').inputValue(), 'PSO');
    assert.ok((await page.locator('#labStatus').textContent()).includes('PSO'));
    assert.equal(await page.locator('#labCity-trigger .spring-value').textContent(), 'هدف قريب من الحريق');
    await choose('#labCity','small');
    await page.waitForFunction(() => !document.querySelector('#labRun').disabled);
    // فتح الحالة اختار أفضل خوارزمية آمنة لها (PSO)؛ نعود إلى DP لمقارنة حقائق الخطة المعروفة.
    await choose('#labAlg','DP');
    await page.waitForFunction(() => !document.querySelector('#labRun').disabled);
    await page.locator('#labRun').click();
    await page.waitForFunction(() => !document.querySelector('#labRun').disabled && window.__viewers.find(v => v.c.id === 'labCanvas').world.data.name === 'fleet_small');
    assert.equal(await page.locator('#labTele .status-safe').count(), 1);
    assert.deepEqual(await page.locator('#labFacts dd').allTextContents(), ['2', '1', '0']);
    // الخطط الآمنة المحفوظة تحتفظ بالإطلاق والإطفاء.
    assert.ok(await page.evaluate(() => window.__viewers.find(v => v.c.id === 'labCanvas').world.swarms[0].drones.every(d => d.mission.fire < 0 || d.throwInfo !== null)));
    assert.ok(!(await page.locator('#labStatus').textContent()).includes('·'));
    console.log('Verified: saved replay, case navigation, display switches and plan facts');
    await page.locator('.flight-details details').filter({ has: page.locator('#droneTable') }).locator('summary').click();
    const download = page.waitForEvent('download');
    await page.locator('#missionCsv').click();
    assert.ok((await download).suggestedFilename().endsWith('.csv'));
    await page.locator('#labSpeed-trigger').focus();
    await page.keyboard.press('ArrowDown');await page.keyboard.press('Home');await page.keyboard.press('Enter');
    assert.equal(await page.locator('#labSpeed').inputValue(),'1');
    assert.equal(await page.evaluate(()=>window.__viewers.find(v=>v.c.id==='labCanvas').S.speed),1);
    await page.locator('#story').scrollIntoViewIfNeeded();
    await page.locator('#storyCameraTools [data-camera="cockpit"]').click();
    await page.mouse.move(700, 380);
    const previousScroll = await page.evaluate(() => scrollY);
    await page.mouse.wheel(0, 300);
    await page.waitForTimeout(200);
    assert.ok(await page.evaluate(previous => scrollY > previous, previousScroll), 'wheel over the story canvas must scroll the page');
    const scrollTime = await page.evaluate(() => {
      const v = window.__viewers.find(v => v.c.id === 'storyCanvas');
      return v.S.t;
    });
    await page.evaluate(() => window.scrollBy(0, 650));
    await page.waitForFunction(previous => window.__viewers.find(v => v.c.id === 'storyCanvas').S.t !== previous, scrollTime);
    await page.screenshot({ path: path.join(__dirname, '../results', 'qa-story.png'), timeout: 180000 });
    await page.locator('#storyCameraTools [data-restart]').click();
    assert.ok(await page.evaluate(()=>window.__viewers.find(v=>v.c.id==='storyCanvas').S.t<5));
    await page.locator('#insights').evaluate(el => window.scrollTo({ top: el.getBoundingClientRect().top + scrollY - 90, behavior: 'instant' }));
    await page.screenshot({ path: path.join(__dirname, '../results', 'qa-insights.png'), timeout: 180000 });
    await page.setViewportSize({ width: 390, height: 844 });
    const closed=await page.locator('.topbar-inner').boundingBox();
    await page.locator('#menuBtn').click();
    const opened=await page.locator('.topbar-inner').boundingBox();
    assert.ok(Math.abs(opened.height-closed.height)<1,'opening the mobile menu must not enlarge the glass capsule');
    assert.equal(await page.locator('#topnav').evaluate(node=>getComputedStyle(node).position),'absolute');
    await page.screenshot({path:path.join(__dirname,'../results','qa-mobile-menu.png')});
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#menuBtn').getAttribute('aria-expanded'),'false');
    await page.locator('#lab').scrollIntoViewIfNeeded();
    await page.waitForTimeout(300);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'mobile page must not overflow horizontally');
    await capture('qa-lab-mobile.png');
    const missing = await page.evaluate(async () => (await import('/content.js?v=viewport-20261018')).missingKeys());
    assert.deepEqual(missing, []);
    assert.deepEqual(errors, []);
    assert.deepEqual(liveRequests, []);
    console.log(JSON.stringify({ ok: true, runtimeErrors: errors, consoleErrors: warnings, missingCopy: missing, liveRequests, screenshots: 5 }, null, 2));
  } catch (error) {
    console.error(JSON.stringify({ runtimeErrors: errors, consoleErrors: warnings }, null, 2));
    throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
