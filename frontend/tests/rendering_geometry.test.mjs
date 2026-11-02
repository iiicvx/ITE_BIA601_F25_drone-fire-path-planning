import test from 'node:test';
import assert from 'node:assert/strict';
import * as THREE from '../public/scene/vendor/three/three.module.js';
import { fitDistance, fleetBounds, chooseFleetDirection, turnFleetDirection } from '../public/fleet-camera.js';
import { fixedAmbientFrame } from '../public/ambient-placement.js';
import { treeGeometries, carGeometries } from '../public/scene/js/city.js';

test('fixed background stays large, left-anchored and inside portrait/landscape viewports', () => {
  for (const [width, height] of [[320, 568], [390, 844], [768, 1024], [844, 390], [1366, 768], [1920, 1080], [2560, 1080]]) {
    const frame = fixedAmbientFrame({ width, height });
    assert.ok(frame.left >= 10 && frame.right <= width - 9 && frame.top >= 0 && frame.bottom <= height - 15);
    assert.ok(frame.width >= Math.min(290, width * .9));
    assert.ok(frame.left < width * .1);
    assert.deepEqual(fixedAmbientFrame({ width, height }), frame, 'scroll/content state cannot change the fixed placement');
  }
});

test('decorative vegetation and traffic fit a lightweight geometry budget', () => {
  const tris = g => (g.index?.count || g.attributes.position.count) / 3;
  const tree = treeGeometries(), car = carGeometries();
  assert.ok(tris(tree.trunk) + tris(tree.crown) <= 110, 'tree used to require 336 triangles per instance');
  assert.ok(tris(car.body) < 300 && tris(car.cabin) < 180 && tris(car.wheels) <= 128);
  for (const g of [tree.trunk, tree.crown, ...Object.values(car)]) g.dispose();
});

test('oblique perspective fit contains all drone corners in asymmetrical safe frames', () => {
  const positions = [[10, 10, -20], [165, 80, -320], [600, 260, -250], [250, 140, -830], [900, 40, -900], [730, 300, -70]].map(p => new THREE.Vector3(...p));
  const points = fleetBounds(positions, 35), focus = new THREE.Box3().setFromPoints(positions).getCenter(new THREE.Vector3());
  for (const [w, h, left, top, right, bottom] of [[1440, 900, 36, 90, 1404, 700], [390, 844, 36, 300, 354, 490], [844, 390, 350, 90, 500, 350]]) {
    for (const elevation of [38, 46, 54]) for (const azimuth of [.3, 1.2, 2.6, 4.5]) {
      const e = elevation * Math.PI / 180, back = new THREE.Vector3(Math.cos(azimuth) * Math.cos(e), Math.sin(e), Math.sin(azimuth) * Math.cos(e));
      const camera = new THREE.PerspectiveCamera(45, w / h, .6, 100000), tan = Math.tan(Math.PI / 8);
      const d = fitDistance(points, focus, back, tan * (right - left) / h, tan * (bottom - top) / h, 360) * 1.01;
      camera.position.copy(focus).addScaledVector(back, d); camera.lookAt(focus);
      camera.setViewOffset(w, h, (w - left - right) / 2, (h - top - bottom) / 2, w, h); camera.updateMatrixWorld(true);
      for (const point of points) {
        const p = point.clone().project(camera), x = (p.x + 1) * w / 2, y = (1 - p.y) * h / 2;
        assert.ok(x >= left && x <= right && y >= top && y <= bottom && Math.abs(p.z) < 1);
      }
      assert.ok(camera.position.y >= 360);
    }
  }
});

test('fleet vantage remains oblique and separates a linear take-off formation', () => {
  const positions = Array.from({ length: 6 }, (_, i) => new THREE.Vector3(30 * i, 10, 0));
  const frame = { left: 36, right: 1364, top: 100, bottom: 700, height: 900 };
  const result = chooseFleetDirection(positions, fleetBounds(positions, 20), new THREE.Vector3(75, 10, 0), frame, Math.tan(Math.PI / 8), [], 360, null);
  assert.ok(result.back.y >= Math.sin(38 * Math.PI / 180) - 1e-6 && result.back.y <= Math.sin(54 * Math.PI / 180) + 1e-6);
  assert.ok(result.separation > 20 && result.occluded === 0);
});

test('opposite-side camera transitions never pass through a top-down view', () => {
  const start = 38 * Math.PI / 180, end = 54 * Math.PI / 180;
  const current = new THREE.Vector3(Math.cos(start), Math.sin(start), 0);
  const target = new THREE.Vector3(-Math.cos(end), Math.sin(end), .001).normalize();
  for (let i = 0; i < 100; i++) {
    turnFleetDirection(current, target, .08);
    assert.ok(current.y >= Math.sin(start) - 1e-6 && current.y <= Math.sin(end) + 1e-6);
    assert.ok(Math.abs(current.length() - 1) < 1e-12);
  }
  assert.ok(current.distanceTo(target) < .01);
});
