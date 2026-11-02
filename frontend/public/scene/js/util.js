// دوال مساعدة مشتركة للمشهد ثلاثي الأبعاد.
// إحداثيات العالم في المشروع: x شرقًا وy شمالًا وz للأعلى (بالمتر). وفي three.js: x شرقًا وy للأعلى وz جنوبًا.
import * as THREE from '../vendor/three/three.module.js';

export const V = (x, y, z) => new THREE.Vector3(x, z, -y);          // المشروع -> three
export const toWorld = (v) => [v.x, -v.z, v.y];                       // three -> المشروع

// أرقام عشوائية حتمية (المدينة نفسها تحصل دائمًا على الأشجار والسيارات والنوافذ المضاءة نفسها).
export function rng(seed) {
  let s = (seed >>> 0) || 1;
  return () => { s ^= s << 13; s >>>= 0; s ^= s >> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; };
}

export const lerp = (a, b, t) => a + (b - a) * t;
export const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
export const smooth = (t) => t * t * (3 - 2 * t);

// ------------------------------------------------------------------ حقل الخطر الحراري
// H(p) = min(1, sum_f h_f(p))؛ فوق الحريق عمود متسع، وتحته تلاشٍ سريع.
export function hazardAt(p, fires, k, t) {
  let H = 0;
  for (const f of fires) {
    const inten = f.intensity === undefined ? 1 : f.intensity;        // 1 مشتعل .. 0 مطفأ (بصريًا)
    if (inten <= 0) continue;
    const dx = p[0] - f.c[0], dy = p[1] - f.c[1], dz = p[2] - f.c[2];
    const dh2 = dx * dx + dy * dy;
    let h;
    if (dz >= 0) { const s = f.R + k * dz; h = f.I * Math.exp(-dh2 / (s * s) - dz / f.Hf); }
    else h = f.I * Math.exp(-(dh2 + 4 * dz * dz) / (f.R * f.R));
    H += h * inten;
  }
  return Math.min(1, H);
}

// نصف قطر القلب المحظور (H >= tau) لحريق واحد عند ارتفاع dz فوق مركز الحريق أو تحته (0 = لا شيء).
export function coreRadius(f, dz, tau) {
  const L = Math.log(f.I / tau);
  if (L <= 0) return 0;
  if (dz >= 0) { const a = L - dz / f.Hf; return a <= 0 ? 0 : (f.R + f.k * dz) * Math.sqrt(a); }
  const a = f.R * f.R * L - 4 * dz * dz;
  return a <= 0 ? 0 : Math.sqrt(a);
}

// ------------------------------------------------------------------ الأبراج
// المسافة الإقليدية من p إلى أقرب صندوق AABB أصلي لبرج (0 في الداخل).
export function nearestTower(p, buildings) {
  let best = Infinity;
  for (const b of buildings) {
    const dx = Math.max(b.x0 - p[0], 0, p[0] - b.x1);
    const dy = Math.max(b.y0 - p[1], 0, p[1] - b.y1);
    const dz = Math.max(0 - p[2], 0, p[2] - b.h);
    const d = Math.sqrt(dx * dx + dy * dy + dz * dz);
    if (d < best) best = d;
  }
  return best;
}

// ------------------------------------------------------------------ الطيران على خط متعدد المقاطع بسرعة ثابتة
export class Flight {
  constructor(path, speed) {
    this.P = path.map(p => [p[0], p[1], p[2]]);
    this.speed = speed;
    this.cum = [0];
    for (let i = 1; i < this.P.length; i++) {
      const a = this.P[i - 1], b = this.P[i];
      this.cum.push(this.cum[i - 1] + Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]));
    }
    this.length = this.cum[this.cum.length - 1];
    this.duration = this.length / speed;                       // زمن الوصول (ث)
  }
  // الموضع (بإحداثيات المشروع) ومتجه الاتجاه والأمتار المصعودة عند الزمن t
  at(t) {
    const s = clamp(t * this.speed, 0, this.length);
    let i = 1;
    while (i < this.cum.length - 1 && this.cum[i] < s) i++;
    const a = this.P[i - 1], b = this.P[i];
    const L = this.cum[i] - this.cum[i - 1];
    const u = L > 1e-9 ? (s - this.cum[i - 1]) / L : 1;
    const pos = [lerp(a[0], b[0], u), lerp(a[1], b[1], u), lerp(a[2], b[2], u)];
    const dir = L > 1e-9 ? [(b[0] - a[0]) / L, (b[1] - a[1]) / L, (b[2] - a[2]) / L] : [1, 0, 0];
    let climb = 0;
    for (let j = 1; j < i; j++) climb += Math.max(0, this.P[j][2] - this.P[j - 1][2]);
    climb += Math.max(0, pos[2] - a[2]);
    return { pos, dir, s, climb, arrived: s >= this.length - 1e-6 };
  }
  // الجزء المقطوع من المسار حتى الزمن t، كمصفوفة مسطحة لرسم خط
  flownPoints(t) {
    const s = clamp(t * this.speed, 0, this.length);
    const out = [];
    for (let i = 0; i < this.P.length && this.cum[i] <= s; i++) out.push(...this.P[i]);
    const r = this.at(t).pos;
    out.push(...r);
    return out;
  }
}

// ------------------------------------------------------------------ دوال مساعدة للوحة الرسم
export function canvasTexture(w, h, draw, opts = {}) {
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  draw(c.getContext('2d'), w, h);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = opts.linear ? THREE.NoColorSpace : THREE.SRGBColorSpace;
  tex.wrapS = tex.wrapT = opts.repeat ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping;
  tex.anisotropy = opts.aniso || 8;
  return tex;
}

export function noise(ctx, w, h, amount, rand) {
  const img = ctx.getImageData(0, 0, w, h), d = img.data;
  for (let i = 0; i < d.length; i += 4) {
    const n = (rand() - 0.5) * amount;
    d[i] += n; d[i + 1] += n; d[i + 2] += n;
  }
  ctx.putImageData(img, 0, 0);
}

export function radialSprite(size, inner, outer, sharp = 1) {
  return canvasTexture(size, size, (ctx) => {
    const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
    g.addColorStop(0, inner);
    g.addColorStop(Math.min(0.99, 0.35 * sharp), inner);
    g.addColorStop(1, outer);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size, size);
  });
}

export function textSprite(text, color = '#ffffff', bg = 'rgba(11,13,18,0.75)') {
  const c = document.createElement('canvas');
  c.width = 128; c.height = 64;
  const ctx = c.getContext('2d');
  ctx.fillStyle = bg;
  ctx.beginPath(); ctx.roundRect(8, 8, 112, 48, 12); ctx.fill();
  ctx.font = 'bold 30px sans-serif';
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillStyle = color;
  ctx.fillText(text, 64, 33);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, sizeAttenuation: false, depthTest: false, transparent: true }));
  sp.scale.set(0.09, 0.045, 1);
  sp.renderOrder = 20;
  return sp;
}

export function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
