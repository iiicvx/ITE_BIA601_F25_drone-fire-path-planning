// ملاءمة صحيحة للمنظور في إحداثيات الكاميرا نفسها، بما فيها العمق.
import * as THREE from './scene/vendor/three/three.module.js';

const UP = new THREE.Vector3(0, 1, 0);
export function turnFleetDirection(current, target, amount) {
  const a = Math.atan2(current.z, current.x), b = Math.atan2(target.z, target.x);
  const azimuth = a + Math.atan2(Math.sin(b - a), Math.cos(b - a)) * amount;
  const elevation = THREE.MathUtils.lerp(Math.asin(THREE.MathUtils.clamp(current.y, -1, 1)), Math.asin(THREE.MathUtils.clamp(target.y, -1, 1)), amount);
  // استيفاء متجهات الاتجاه قد يمر بسمت الرأس عند تغيير
  // الجانب. أما استيفاء الزاويتين فيحافظ على ارتفاع مائل.
  return current.set(Math.cos(azimuth) * Math.cos(elevation), Math.sin(elevation), Math.sin(azimuth) * Math.cos(elevation));
}

export function cameraBasis(back) {
  const right = new THREE.Vector3().crossVectors(UP, back).normalize();
  return { back, right, up: new THREE.Vector3().crossVectors(back, right).normalize() };
}

export function fitDistance(points, focus, back, tanX, tanY, minHeight = 0) {
  const basis = cameraBasis(back), delta = new THREE.Vector3();
  let distance = Math.max(4, (minHeight - focus.y) / back.y);
  for (const point of points) {
    delta.copy(point).sub(focus);
    distance = Math.max(distance, delta.dot(back) + Math.max(Math.abs(delta.dot(basis.right)) / tanX, Math.abs(delta.dot(basis.up)) / tanY));
  }
  return distance;
}

export function fleetBounds(positions, radius) {
  const points = [];
  for (const p of positions) for (const x of [-radius, radius]) for (const y of [-radius, radius + 15]) for (const z of [-radius, radius]) {
    points.push(new THREE.Vector3(p.x + x, p.y + y, p.z + z));
  }
  return points;
}

export function chooseFleetDirection(positions, points, focus, frame, tanV, boxes, minHeight, previous) {
  const tanX = tanV * (frame.right - frame.left) / frame.height;
  const tanY = tanV * (frame.bottom - frame.top) / frame.height;
  const ray = new THREE.Ray(), hit = new THREE.Vector3(), delta = new THREE.Vector3();
  let best = null;
  const candidates = previous ? [previous.clone()] : [];
  // مسح جانبي بزاوية 15 درجة يشمل المناظر المماسية التي تحتاجها الواجهات المتقابلة؛
  // وقد تفوّت بضع عينات قطرية واسعة الممر الوحيد غير المحجوب للرؤية.
  for (const elevation of [38, 46, 54]) for (let azimuth = 0; azimuth < 360; azimuth += 15) {
    const e = THREE.MathUtils.degToRad(elevation), a = THREE.MathUtils.degToRad(azimuth);
    candidates.push(new THREE.Vector3(Math.cos(a) * Math.cos(e), Math.sin(e), Math.sin(a) * Math.cos(e)));
  }
  for (const back of candidates) {
    const basis = cameraBasis(back), distance = fitDistance(points, focus, back, tanX, tanY, minHeight) * 1.04;
    const eye = focus.clone().addScaledVector(back, distance), projected = [];
    let occluded = 0;
    for (const p of positions) {
      delta.copy(p).sub(eye); const length = delta.length();
      ray.set(eye, delta.normalize());
      if (boxes.some(box => ray.intersectBox(box, hit) && eye.distanceTo(hit) < length - 2)) occluded++;
      delta.copy(p).sub(focus); const depth = distance - delta.dot(back);
      projected.push(new THREE.Vector2(delta.dot(basis.right) / depth, delta.dot(basis.up) / depth).multiplyScalar(frame.height / (2 * tanV)));
    }
    let separation = 100;
    for (let i = 0; i < projected.length; i++) for (let j = 0; j < i; j++) separation = Math.min(separation, projected[i].distanceTo(projected[j]));
    const turn = previous ? 1 - previous.dot(back) : 0;
    const score = occluded * 10000 + Math.max(0, 34 - separation) * 12 + distance * .003 + turn * 18;
    if (!best || score < best.score) best = { back, score, occluded, separation };
  }
  return best;
}
