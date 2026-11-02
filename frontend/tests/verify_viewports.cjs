// فحوص إسقاط WebGL فعلية للمنظر العام للسرب والزخرفة المتجاوبة
// وأعمدة التحقق من اليمين إلى اليسار. تُشغَّل على خادم FastAPI المحلي.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce', deviceScaleFactor: 1 });
  page.setDefaultTimeout(90000);
  const errors = [], report = { fleetScenes: [], viewports: [], storyFrames: [], errors };
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  const scrollTo = selector => page.locator(selector).evaluate(el => window.scrollTo({ top: scrollY + el.getBoundingClientRect().top - 90, behavior: 'instant' }));
  async function choose(selector, value) {
    const { id, label } = await page.locator(selector).evaluate((el, value) => ({ id: el.id, label: [...el.options].find(o => o.value === value)?.textContent }), value);
    assert.ok(label, `missing ${selector} option ${value}`);
    await page.locator(`#${id}-trigger`).click();
    await page.locator(`#${id}-list`).getByRole('option', { name: label, exact: true }).click();
  }
  async function fleetFrame(id, time) {
    const result = await page.evaluate(async ({ id, time }) => {
      const THREE = await import('/scene/vendor/three/three.module.js');
      const v = window.__viewers.find(v => v.c.id === id);
      // تأكيدات مخروط الرؤية تحتاج هندسة الإنتاج ووضعيته الحقيقيتين، لا تكرار
      // تنقيط التوهج. ويُفحص ناتج GPU الأصلي منفصلًا أدناه.
      const render = v.composer.render;
      try {
        v.composer.render = () => {};
        v.setTime(time); v.visible = true; v.resize(); v.frame(); v.visible = false;
      } finally { v.composer.render = render; }
      v.scene.updateMatrixWorld(true); v.camera.updateMatrixWorld(true);
      const frame = v.fleetFrame, points = [], failures = [];
      const obstructionNodes = [...v.c.parentElement.querySelectorAll('.viewer-tools, .scene-hud>span')];
      if (v.c.closest('.story')) obstructionNodes.push(...v.c.closest('.story').querySelectorAll('.step-card, .stage-dock'));
      const canvasRect = v.c.getBoundingClientRect(), obstructions = obstructionNodes.map(el => el.getBoundingClientRect());
      for (const sw of v.world.swarms) for (const d of sw.drones) {
        const center = d.holder.getWorldPosition(new THREE.Vector3()).project(v.camera);
        const pixel = { x: (center.x + 1) * frame.width / 2, y: (1 - center.y) * frame.height / 2 };
        points.push({ drone: d.k + 1, ...pixel });
        if (pixel.x < frame.left || pixel.x > frame.right || pixel.y < frame.top || pixel.y > frame.bottom) failures.push(`D${d.k + 1}: outside clear frame`);
        if (obstructions.some(box => pixel.x + canvasRect.left > box.left - 12 && pixel.x + canvasRect.left < box.right + 12 && pixel.y + canvasRect.top > box.top - 12 && pixel.y + canvasRect.top < box.bottom + 12)) failures.push(`D${d.k + 1}: covered by stage controls or a story card`);
        const box = new THREE.Box3().setFromObject(d.root);
        for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) {
          const p = new THREE.Vector3(x, y, z).project(v.camera);
          if (Math.abs(p.x) > .995 || Math.abs(p.y) > .995 || Math.abs(p.z) > 1) failures.push(`D${d.k + 1}: clipped model`);
        }
        if (!d.root.visible || !d.label.visible || !d.ring.visible) failures.push(`D${d.k + 1}: hidden overview marker`);
      }
      return { id, time, count: points.length, frame, points, failures, up: v.camera.up.toArray(), direction: v.fleetDirection.toArray(),
        occluded: v._fleetVantage.occluded, cameraHeight: v.camera.position.y, maxBuildingHeight: v.world.maxBuildingHeight };
    }, { id, time });
    assert.deepEqual(result.failures, [], JSON.stringify(result));
    assert.deepEqual(result.up, [0, 1, 0], 'oblique view must retain an upright horizon');
    assert.ok(result.direction[1] > .6 && result.direction[1] < .82, 'view must remain genuinely oblique');
    assert.equal(result.occluded, 0, 'selected fleet vantage must not hide a drone behind a tower');
    assert.ok(result.cameraHeight > result.maxBuildingHeight, 'camera must clear every roof');
    return result;
  }
  async function captureFleet(id, name) {
    await page.evaluate(id => {
      const v = window.__viewers.find(v => v.c.id === id);
      v.renderer.setPixelRatio(1); v.composer.setPixelRatio(1); v.resize(); v.visible = true; v.frame(); v.visible = false;
    }, id);
    await page.screenshot({ path: path.join(__dirname, '../results', name), timeout: 90000 });
    await page.evaluate(id => { const v = window.__viewers.find(v => v.c.id === id); v.renderer.setPixelRatio(.4); v.composer.setPixelRatio(.4); v.resize(); }, id);
  }
  async function checkDecoration() {
    const result = await page.evaluate(async () => {
      const THREE = await import('/scene/vendor/three/three.module.js');
      const state = window.__ambientDrone, canvas = document.querySelector('#ambientDroneCanvas');
      const rect = canvas.getBoundingClientRect(), viewport = window.visualViewport, layout = state.placement.info();
      const projected = [];
      if (state.info().frames > 0) {
        state.root.updateMatrixWorld(true); state.camera.updateMatrixWorld(true);
        state.root.traverse(mesh => {
          if (!mesh.isMesh || !mesh.visible) return;
          const a = mesh.geometry.attributes.position;
          for (let i = 0; i < a.count; i++) {
            const p = new THREE.Vector3().fromBufferAttribute(a, i).applyMatrix4(mesh.matrixWorld).project(state.camera);
            if (Math.abs(p.x) >= 1 || Math.abs(p.y) >= 1 || Math.abs(p.z) >= 1) projected.push([p.x, p.y, p.z]);
          }
        });
      }
      return { rect: rect.toJSON(), viewport: { left: viewport.offsetLeft, top: viewport.offsetTop, width: viewport.width, height: viewport.height, scale: viewport.scale }, projected, layout };
    });
    const { rect, viewport, projected } = result;
    assert.ok(rect.left >= viewport.left - 1 && rect.top >= viewport.top - 1 && rect.right <= viewport.left + viewport.width + 1 && rect.bottom <= viewport.top + viewport.height + 1, `decoration outside visual viewport: ${JSON.stringify(result)}`);
    assert.ok(rect.width >= 290 && rect.height >= 140, 'fixed decoration must remain legible');
    assert.ok(rect.left - viewport.left < viewport.width * .1 && result.layout.fixed, 'decoration must stay on the left');
    assert.deepEqual(projected, [], 'ambient model must not be cropped by its own camera');
    return { rect, viewport, layout: result.layout };
  }
  async function checkColumns() {
    const failures = await page.evaluate(() => {
      const failures = [], table = document.querySelector('#specialTable');
      const headers = [...table.tHead.rows[0].cells].map(c => c.getBoundingClientRect());
      for (const row of table.tBodies[0].rows) for (const [i, cell] of [...row.cells].entries()) {
        const box = cell.getBoundingClientRect();
        if (Math.abs(box.left - headers[i].left) > 1 || Math.abs(box.right - headers[i].right) > 1) failures.push(`column ${i} is misaligned`);
        const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
        while (walker.nextNode()) {
          const range = document.createRange(); range.selectNodeContents(walker.currentNode);
          for (const text of range.getClientRects()) if (text.left < box.left - 1 || text.right > box.right + 1) failures.push(`${cell.textContent}: escaped cell`);
        }
      }
      for (const column of document.querySelectorAll('#checksBox>div')) {
        const box = column.getBoundingClientRect(), range = document.createRange(); range.selectNodeContents(column.querySelector('dd'));
        const value = range.getBoundingClientRect();
        if (Math.abs((value.left + value.right - box.left - box.right) / 2) > 1) failures.push('validation total not centered under its heading');
      }
      if (document.documentElement.scrollWidth > innerWidth + 1) failures.push('horizontal page overflow');
      return failures;
    });
    assert.deepEqual(failures, []);
  }
  try {
    await page.goto(process.env.APP_URL || 'http://127.0.0.1:8000', { waitUntil: 'load' });
    await page.locator('body[data-app-ready]').waitFor();
    await page.locator('#ambientDroneCanvas[data-model-ready]').waitFor();
    // إحداثيات الإسقاط وDOM تبقى ببكسلات CSS. وحالات الهندسة الشاملة
    // تعلّق التنقيط؛ واللقطات التمثيلية تستخدم WebGL بالدقة الأصلية.
    await page.evaluate(() => { window.__viewers.forEach(v => {
      v.S.playing = false; v.loop.setEnabled(false); v.visible = false;
      v.renderer.setPixelRatio(.4); v.composer.setPixelRatio(.4); v.resize();
    }); window.__ambientDrone.setPaused(true); });
    const cdp = await page.context().newCDPSession(page);
    await cdp.send('DOM.enable'); await cdp.send('CSS.enable');
    const { root } = await cdp.send('DOM.getDocument');
    report.fonts = [];
    for (const selector of ['#validation h2', '#validation .prose p']) {
      const { nodeId } = await cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector });
      const { fonts } = await cdp.send('CSS.getPlatformFontsForNode', { nodeId });
      assert.ok(fonts.some(f => f.isCustomFont && f.familyName === 'Akhbar MT' && f.glyphCount > 10), `${selector} is not actually using Akhbar MT: ${JSON.stringify(fonts)}`);
      report.fonts.push({ selector, fonts });
    }
    await scrollTo('#labStage');
    await page.waitForFunction(() => window.__viewers[2].world && !document.querySelector('#labRun').disabled);
    await page.locator('#labCameraTools [data-camera=follow]').click();
    await choose('#labCameraTools select', 'all');
    for (const city of (process.argv.includes('--large-only') ? ['large'] : ['small', 'medium', 'large'])) {
      await scrollTo('#lab');
      if (await page.locator('#labCity').inputValue() !== city) await choose('#labCity', city);
      await page.waitForFunction(city => !document.querySelector('#labRun').disabled && window.__viewers.find(v => v.c.id === 'labCanvas').world.data.name === `fleet_${city}`, city);
      for (const alg of ['GA', 'PSO', 'ACO', 'DP']) {
        console.log(`Loading bounds check: ${city} / ${alg}`);
        if (await page.locator('#labAlg').inputValue() !== alg) await choose('#labAlg', alg);
        await page.waitForFunction(alg => !document.querySelector('#labRun').disabled && window.__viewers.find(v => v.c.id === 'labCanvas').runs[0].algorithm === alg, alg);
        await scrollTo('#labStage');
        await page.evaluate(() => window.__viewers.forEach(v => { v.S.playing = false; v.loop.setEnabled(false); v.visible = false; }));
        const meta = await page.evaluate(() => {
          const v = window.__viewers.find(v => v.c.id === 'labCanvas');
          return { T: v.T, count: v.world.data.problem.n_drones, outside: !!v.world.city.group.getObjectByName('distant_district_outside_flight_bounds'), towers: v.world.city.towers.length, buildings: v.world.data.buildings.length };
        });
        assert.equal(meta.outside, false); assert.equal(meta.towers, meta.buildings);
        assert.equal(await page.locator('#labCameraTools select').inputValue(), 'all');
        for (const t of [-4, meta.T * .5, meta.T]) {
          if (process.argv.includes('--trace')) console.log(`  mission time ${t.toFixed(1)}`);
          const frame = await fleetFrame('labCanvas', t); assert.equal(frame.count, meta.count);
        }
        report.fleetScenes.push({ city, alg, drones: meta.count });
        console.log(`Projected bounds: ${city} / ${alg}`);
      }
      console.log(`Fleet overview: ${city}, all four algorithms`);
    }
    const sizes = [[320, 568], [390, 844], [768, 1024], [844, 390], [1366, 768], [1920, 1080], [2560, 1080], [960, 640], [720, 480]];
    const T = await page.evaluate(() => window.__viewers.find(v => v.c.id === 'labCanvas').T);
    for (const [width, height] of sizes) {
      await page.setViewportSize({ width, height }); await scrollTo('#labStage');
      await page.waitForTimeout(150);
      for (const time of [-4, T * .25, T * .6, T]) await fleetFrame('labCanvas', time);
      if ([390, 1366].includes(width)) {
        await captureFleet('labCanvas', `viewport-fleet-${width}.png`);
      }
      await scrollTo('#validation');
      await page.evaluate(() => { window.__layoutStamp = performance.now(); window.__ambientDrone.placement.queue(); });
      await page.waitForFunction(() => window.__ambientDrone.placement.measuredAt >= window.__layoutStamp);
      const decoration = await checkDecoration(); await checkColumns();
      report.viewports.push({ width, height, decoration }); console.log(`Viewport: ${width} x ${height}`);
      if ([390, 1366].includes(width)) await page.screenshot({ path: path.join(__dirname, '../results', `viewport-validation-${width}.png`) });
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await cdp.send('Emulation.setPageScaleFactor', { pageScaleFactor: 1.5 });
    await page.evaluate(() => { window.__layoutStamp = performance.now(); window.__ambientDrone.placement.queue(); });
    await page.waitForFunction(() => window.__ambientDrone.placement.measuredAt >= window.__layoutStamp);
    report.pinchZoom = await checkDecoration();
    await cdp.send('Emulation.setPageScaleFactor', { pageScaleFactor: 1 });
    await scrollTo('#labStage');
    await choose('#labCameraTools select', '5');
    assert.deepEqual(await page.evaluate(() => { const v = window.__viewers.find(v => v.c.id === 'labCanvas'); return [v.S.camera, v.S.selected, v.camera.view.enabled]; }), ['follow', 5, false]);
    await choose('#labCameraTools select', 'all');
    await page.locator('#labCameraTools [data-restart]').click();
    assert.equal(await page.locator('#labCameraTools select').inputValue(), 'all');
    await page.locator('#labCameraTools [data-reset]').click();
    assert.equal(await page.locator('#labCameraTools select').inputValue(), '5');
    assert.equal(await page.locator('#labCameraTools .spring-value').textContent(), 'المُسيَّرة 6');
    for (const [width, height] of [[1440, 1000], [390, 844], [844, 390]]) {
      await page.setViewportSize({ width, height });
      await page.locator('.step[data-state=swarm]').evaluate(el => el.scrollIntoView({ block: 'center', behavior: 'instant' }));
      await page.waitForTimeout(200);
      await choose('#storyCameraTools select', 'all');
      report.storyFrames.push(await fleetFrame('storyCanvas', 25));
      console.log(`Story overview: ${width} x ${height}`);
      await captureFleet('storyCanvas', `viewport-story-${width}.png`);
    }
    assert.ok(await page.evaluate(() => window.__viewers.every(v => !v.world || !v.world.city.group.getObjectByName('distant_district_outside_flight_bounds'))));
    assert.deepEqual(errors, []);
    report.passed = true;
    await fs.writeFile(path.join(__dirname, '../results', 'viewport-audit.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ passed: true, fleetScenes: report.fleetScenes.length, viewports: report.viewports.length, storyFrames: report.storyFrames.length, realAkhbarMT: true, pinchZoom: true, errors }, null, 2));
  } catch (error) { console.error('Viewport verification failed:', error); throw error; }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
