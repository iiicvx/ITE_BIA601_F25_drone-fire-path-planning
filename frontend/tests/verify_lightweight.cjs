// انحدار شعاع LineMaterial بدقة 1x1 وبدء التشغيل الخفيف الفعلي.
const { chromium } = require('playwright');
const { PNG } = require('pngjs');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');

(async () => {
  const browser = await chromium.launch({ args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 900, height: 700 }, reducedMotion: 'reduce' });
  page.setDefaultTimeout(90000);
  const errors = [], requests = new Map(), report = { errors, beamReloads: [] };
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { const p = new URL(request.url()).pathname; requests.set(p, (requests.get(p) || 0) + 1); });
  try {
    await page.goto(process.env.APP_URL || 'http://127.0.0.1:8000', { waitUntil: 'load' });
    await page.locator('body[data-app-ready]').waitFor();
    await page.locator('#ambientDroneCanvas[data-model-ready]').waitFor();
    report.startup = await page.evaluate(() => ({ loaded: window.__viewers.filter(v => v.world).map(v => v.c.id), caps: window.__viewers.map(v => v.loop.maxFPS) }));
    assert.deepEqual(report.startup.loaded, ['heroCanvas'], 'unvisited large cities must not be constructed at startup');
    assert.deepEqual(report.startup.caps, [20, 30, 30]);
    assert.equal(requests.get('/api/fleet/large'), 1, 'simultaneous saved-summary requests should be coalesced');
    report.city = await page.evaluate(() => {
      const v = window.__viewers[0]; let triangles = 0;
      v.scene.updateMatrixWorld(true); v.world.city.group.traverse(o => { if (o.isLOD) o.update(v.camera); });
      v.world.city.group.traverseVisible(o => { if (o.geometry) triangles += Math.round((o.geometry.index?.count || o.geometry.attributes.position?.count || 0) / 3 * (o.isInstancedMesh ? o.count : 1)); });
      return { triangles, trees: v.world.city.treeCount, grass: v.world.city.grassCount, before: 1812785, pixelBudget: v.pixelBudget };
    });
    report.city.reduction = 1 - report.city.triangles / report.city.before;
    assert.ok(report.city.reduction > .55); assert.equal(report.city.trees, 4089); assert.ok(report.city.grass > 0);
    await page.evaluate(() => { for (const v of window.__viewers) v.loop.setEnabled(false); window.__ambientDrone.setPaused(true); });
    await page.locator('#labStage').evaluate(el => window.scrollTo({ top: scrollY + el.getBoundingClientRect().top - 90, behavior: 'instant' }));
    await page.waitForFunction(() => window.__viewers[2].world && !document.querySelector('#labRun').disabled);
    await page.evaluate(() => { const v = window.__viewers[2]; v.visible = true; v.frame(); v.visible = false; });
    const resized = await page.evaluate(() => window.__viewers[2]._resizeCount);
    for (const algorithm of ['GA', 'PSO', 'ACO', 'DP', 'GA', 'PSO']) {
      if (await page.locator('#labAlg').inputValue() === algorithm) await page.locator('#labRun').click();
      else await page.locator('#labAlg').selectOption(algorithm, { force: true });
      await page.waitForFunction(a => !document.querySelector('#labRun').disabled && window.__viewers[2].runs[0].algorithm === a, algorithm);
      const result = await page.evaluate(() => {
        const v = window.__viewers[2]; v.setTime(6); v.visible = true; v.frame(); v.visible = false;
        const box = v.c.getBoundingClientRect(), bad = [];
        for (const sw of v.world.swarms) for (const d of sw.drones) for (const line of [d.plan, d.flown, d.flownGlow]) {
          if (Math.abs(line.material.resolution.x - box.width) > 1 || Math.abs(line.material.resolution.y - box.height) > 1 || line.material.worldUnits) bad.push({ name: line.name, resolution: line.material.resolution.toArray(), expected: [box.width, box.height] });
        }
        return { bad, size: [box.width, box.height], resizes: v._resizeCount, pixelCount: v.renderer.domElement.width * v.renderer.domElement.height, pixelBudget: v.pixelBudget };
      });
      assert.deepEqual(result.bad, [], 'every new trail/halo must have real canvas resolution');
      assert.equal(result.resizes, resized, 'fixing new line uniforms must not reallocate unchanged GPU targets');
      assert.ok(result.pixelCount <= result.pixelBudget + 2000);
      report.beamReloads.push({ algorithm, ...result });
    }
    const image = PNG.sync.read(await page.locator('#labCanvas').screenshot({ path: path.join(__dirname, '../results', 'beam-after.png'), timeout: 90000 }));
    let purple = 0;
    for (let i = 0; i < image.data.length; i += 4) {
      const r = image.data[i], g = image.data[i + 1], b = image.data[i + 2];
      if (b > r + 5 && r > g + 12 && b > g + 25 && b > 140) purple++;
    }
    report.purplePixelFraction = purple / (image.width * image.height);
    assert.ok(report.purplePixelFraction < .15, 'purple lines must not cover the scene after replay');
    const following = await page.evaluate(() => {
      const v = window.__viewers[2]; v.setCamera('follow');
      const old = v.ray.intersectObjects; let triangleCasts = 0;
      v.ray.intersectObjects = () => { triangleCasts++; return []; };
      const started = performance.now();
      for (let t = 0; t < 30; t += .25) { v.S.t = t; v.followCamera(1 / 30); }
      v.ray.intersectObjects = old;
      return { triangleCasts, milliseconds: performance.now() - started, finite: v.camera.position.toArray().every(Number.isFinite) };
    });
    assert.equal(following.triangleCasts, 0); assert.ok(following.finite); report.following = following;
    await page.locator('#labCameraTools [data-camera="orbit"]').click();
    await page.evaluate(() => { const v = window.__viewers[2]; v.setTime(6); v.loop.setEnabled(true); v.play(true); });
    await page.waitForFunction(() => window.__viewers[2].S.t > 8);
    assert.ok(await page.evaluate(() => window.__viewers[2].world.swarms[0].drones.every(d => d.flown.material.resolution.y > 100)));
    assert.deepEqual(errors, []); report.passed = true;
    await fs.writeFile(path.join(__dirname, '../results', 'lightweight-audit.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ passed: true, startupWorlds: report.startup.loaded.length, triangleReductionPercent: +(report.city.reduction * 100).toFixed(1),
      sameSizeReloads: report.beamReloads.length, purplePixelFraction: +report.purplePixelFraction.toFixed(4), perTriangleCameraCasts: following.triangleCasts, errors }, null, 2));
  } catch (error) { console.error('Lightweight verification failed:', error); throw error; }
  finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
