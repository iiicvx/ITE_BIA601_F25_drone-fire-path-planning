// انحدارات دورة الحياة والحركة في متصفح حقيقي. قياسات عدادات SwiftShader
// تتحقق من الجدولة، لا من معدل إطارات العتاد.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, hasTouch: true, reducedMotion: 'no-preference' });
  page.setDefaultTimeout(90000);
  const errors = [], report = { errors, renderer: 'SwiftShader; scheduling counters, not a hardware benchmark' };
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  async function go(selector) {
    const stamp = await page.locator(selector).evaluate(el => {
      window.scrollTo({ top: scrollY + el.getBoundingClientRect().top - 90, behavior: 'instant' });
      window.__ambientDrone.placement.queue(); return performance.now();
    });
    await page.waitForFunction(stamp => window.__ambientDrone.placement.measuredAt >= stamp, stamp);
    if (selector === '#lab' || selector === '#labStage') await page.waitForFunction(() => window.__viewers[2].world && !document.querySelector('#labRun').disabled);
  }
  async function choose(selector, value) {
    const { id, label } = await page.locator(selector).evaluate((el, value) => ({ id: el.id, label: [...el.options].find(o => o.value === value).textContent }), value);
    await page.locator(`#${id}-trigger`).click(); await page.locator(`#${id}-list`).getByRole('option', { name: label, exact: true }).click();
  }
  const counters = () => page.evaluate(() => window.__viewers.map(v => ({ id: v.c.id, callbacks: v.loop.callbacks, updates: v._updates, renders: v._rendered, resizes: v._resizeCount, t: v.S.t, visualTime: v.time })));
  async function settleAmbient() {
    await page.waitForFunction(() => { const s = window.__ambientDrone.info(); return s.layout.fixed && !s.layout.covered && s.frames > 0; });
  }
  try {
    await page.goto(process.env.APP_URL || 'http://127.0.0.1:8000', { waitUntil: 'load' });
    await page.locator('body[data-app-ready]').waitFor(); await page.locator('#ambientDroneCanvas[data-model-ready]').waitFor();
    await page.evaluate(() => window.__viewers.forEach(v => { v.renderer.setPixelRatio(.5); v.composer.setPixelRatio(.5); v.resize(); }));
    await go('#compare'); await settleAmbient();
    const left = await page.evaluate(() => window.__ambientDrone.info());
    assert.ok(left.layout.left < 100 && left.layout.width >= 600, 'background drone should remain large and fixed on the left');
    await page.screenshot({ path: path.join(__dirname, '../results', 'rendering-ambient-fixed.png') });
    const rotorBefore = left.angles;
    await page.waitForTimeout(500);
    const rotorAfter = await page.evaluate(() => window.__ambientDrone.info().angles);
    assert.ok(rotorAfter.some((a, i) => Math.abs(a - rotorBefore[i]) > .05), 'visible original rotors must animate');
    const movement = await page.evaluate(async () => {
      const samples = [];
      for (let i = 0; i < 12; i++) {
        window.scrollBy({ top: 24, behavior: 'instant' });
        await new Promise(resolve => requestAnimationFrame(() => setTimeout(resolve, 0)));
        const s = window.__ambientDrone, r = document.querySelector('#ambientDroneCanvas').getBoundingClientRect();
        samples.push({ x: r.left, y: r.top, body: s.root.position.toArray(), rotation: s.root.rotation.toArray() });
      }
      return samples;
    });
    for (const sample of movement) assert.deepEqual(sample, movement[0], 'scrolling must not move or tilt the fixed background drone');
    await go('#validation'); await settleAmbient();
    const otherSection = await page.evaluate(() => window.__ambientDrone.info());
    assert.deepEqual(otherSection.layout, left.layout, 'background placement must not change sides between sections');
    report.ambient = { layout: left.layout, rotorsAnimated: true, fixedAcrossScroll: true, bodyStationary: true };
    console.log('Verified fixed left placement, stationary body and original rotor animation');

    await go('#lab'); await choose('#labCity', 'large');
    await page.waitForFunction(() => !document.querySelector('#labRun').disabled && window.__viewers[2].world.data.problem.n_drones === 6);
    await go('#labStage'); await choose('#labCameraTools select', '5'); await choose('#labCameraTools select', 'all');
    await page.evaluate(() => {
      const v = window.__viewers[2]; v.setTime(10); v.S.speed = 3; v.play(true);
      window.__retained = { world: v.world, environment: v.world.environmentTarget, model: v.world.swarms[0].drones[5].root, loadId: v._loadId };
      window.__resumeDeltas = []; const original = v.frame.bind(v);
      v.frame = (dt, now) => { window.__resumeDeltas.push(dt); return original(dt, now); };
    });
    await page.waitForFunction(() => window.__viewers[2].S.t > 10);
    await go('#validation'); await page.waitForFunction(() => window.__viewers.every(v => !v.loop.active));
    const before = await counters(); await page.waitForTimeout(1200); const after = await counters();
    assert.deepEqual(after, before, 'offscreen callbacks, visual/physics updates, renders, resizes and time must all stop');
    report.offscreen = { sampleMs: 1200, before, after, callbackDelta: after.map((s, i) => s.callbacks - before[i].callbacks) };
    await page.setViewportSize({ width: 1200, height: 820 });
    await page.waitForTimeout(200);
    assert.deepEqual((await counters()).map(s => s.resizes), before.map(s => s.resizes), 'offscreen GPU resizing must be deferred');
    await page.evaluate(() => { window.__resumeDeltas = []; });
    await go('#labStage');
    await page.waitForFunction(() => window.__resumeDeltas.length > 0);
    const resumed = await page.evaluate(() => {
      const v = window.__viewers[2], r = window.__retained;
      return { sameWorld: v.world === r.world, sameEnvironment: v.world.environmentTarget === r.environment, sameModel: v.world.swarms[0].drones[5].root === r.model,
        sameLoad: v._loadId === r.loadId, firstDelta: window.__resumeDeltas[0], playing: v.S.playing, selected: v.S.selected, camera: v.S.camera, speed: v.S.speed };
    });
    assert.deepEqual(resumed, { sameWorld: true, sameEnvironment: true, sameModel: true, sameLoad: true, firstDelta: 0, playing: true, selected: 5, camera: 'fleet', speed: 3 });
    report.resume = resumed;
    console.log('Verified zero offscreen work, deferred resize and retained scene/playback state');

    // إيقاف المستخدم المؤقت ولقطة البحث يُحفظان باستقلال عن الظهور.
    await page.evaluate(() => { const v = window.__viewers[2]; v.play(false); v.showSnapshot(0); });
    await go('#validation'); const paused = await counters(); await page.waitForTimeout(400); assert.deepEqual(await counters(), paused);
    await go('#labStage');
    assert.deepEqual(await page.evaluate(() => { const v = window.__viewers[2]; return [v.S.playing, v.snapshot, v.S.selected, v.S.camera]; }), [false, 0, 5, 'fleet']);
    await page.evaluate(() => window.__viewers[2].showSnapshot(null));

    await page.evaluate(() => window.dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true })));
    const cacheBefore = await counters(); await page.waitForTimeout(400); assert.deepEqual(await counters(), cacheBefore);
    await page.evaluate(() => { window.__resumeDeltas = []; window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })); });
    await page.waitForFunction(() => window.__resumeDeltas.length > 0);
    assert.equal(await page.evaluate(() => window.__resumeDeltas[0]), 0);
    report.backForwardCache = { stateRetained: true, firstResumeDelta: 0 };

    // اختبار مسار visibilitychange الفعلي دون الاعتماد على تقديرات تركيز التبويب
    // في المتصفح دون واجهة. وتبقى الصفحة قابلة للتشغيل لقراءة العدادات المعلقة.
    await page.evaluate(() => { Object.defineProperty(document, 'hidden', { configurable: true, value: true }); document.dispatchEvent(new Event('visibilitychange')); });
    const tabBefore = await counters(), ambientBefore = await page.evaluate(() => window.__ambientDrone.info().frames);
    await page.waitForTimeout(800); assert.deepEqual(await counters(), tabBefore);
    assert.equal(await page.evaluate(() => window.__ambientDrone.info().frames), ambientBefore);
    await page.evaluate(() => { window.__resumeDeltas = []; delete document.hidden; document.dispatchEvent(new Event('visibilitychange')); });
    await page.waitForFunction(() => window.__resumeDeltas.length > 0);
    assert.equal(await page.evaluate(() => window.__resumeDeltas[0]), 0);
    report.documentVisibility = { allCountersFrozen: true, firstResumeDelta: 0, eventPath: 'visibilitychange' };
    console.log('Verified document visibility, paused snapshots and zero-delta resume');

    await go('#lab'); await choose('#labCity', 'small');
    await page.waitForFunction(() => !document.querySelector('#labRun').disabled);
    await choose('#labAlg', 'DP');
    await page.waitForFunction(() => !document.querySelector('#labRun').disabled && window.__viewers[2].runs[0].algorithm === 'DP');
    await page.locator('#labRun').click();
    await page.waitForFunction(() => !document.querySelector('#labRun').disabled);
    assert.equal(await page.locator('#labTele .status-safe').count(), 1);
    report.savedReplay = { reloadedSuccessfully: true, independentlySafe: true };
    assert.deepEqual(errors, []); report.passed = true;
    await fs.writeFile(path.join(__dirname, '../results', 'rendering-audit.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ passed: true, offscreenCallbackDelta: report.offscreen.callbackDelta, retainedResources: true, documentVisibility: true,
      fixedAmbient: true, rotorsAnimated: true, savedReplay: report.savedReplay, errors }, null, 2));
  } catch (error) { console.error('Rendering verification failed:', error); throw error; }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
