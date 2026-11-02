// مدينة ملف سيناريو واحد، مبنية من بياناته.
// كل برج يُرسم داخل صندوقه نفسه الذي استخدمته الخوارزميات: [x0, x1] x [y0, y1] x [0, h].
// الطرق والأشجار والسيارات وأعمدة الإنارة توضع خارج الأبراج وهوامش أمانها (5 م).
import * as THREE from '../vendor/three/three.module.js';
import { mergeGeometries } from '../vendor/three/examples/jsm/utils/BufferGeometryUtils.js';
import { RoundedBoxGeometry } from '../vendor/three/examples/jsm/geometries/RoundedBoxGeometry.js';
import { V, rng, canvasTexture, noise, radialSprite, clamp } from './util.js';
import { buildArchitecturalCity } from './architecture.js';
import { getVisualAssets } from './visual-assets.js';

const FLOOR = 3.5;              // متر لكل طابق
const BAY = 3.0;                // متر لكل فتحة نافذة
const TILE_W = 24, TILE_H = 56; // بلاطة خامة واجهة واحدة = 8 فتحات × 16 طابقًا
const LOBBY = 5.0;              // ارتفاع الطابق الأرضي
const PARAPET = 1.2;
const ROAD = 11, WALK = 2.6;    // عرض الإسفلت وعرض الرصيف
const CORRIDOR = ROAD + 2 * WALK;

// ======================================================================= خامات الواجهات
const STYLES = [
  { name: 'glass', base: '#1a222d', mullion: '#a1acb6', spandrel: '#283240', glass: '#1d2b3a', lit: 0.38,
    rough: [0.06, 0.48], metal: 0.68, tint: [[0.82, 0.92, 1.08], [0.88, 0.96, 1.03], [0.96, 0.99, 1.02]] },
  { name: 'concrete', base: '#827c73', mullion: '#5a5550', spandrel: '#867f77', glass: '#182028', lit: 0.44,
    rough: [0.15, 0.96], metal: 0.03, tint: [[1.0, 0.97, 0.92], [0.93, 0.93, 0.93], [1.04, 1.0, 0.95]] },
  { name: 'banded', base: '#363941', mullion: '#a3a8b0', spandrel: '#484c54', glass: '#15202b', lit: 0.34,
    rough: [0.08, 0.62], metal: 0.32, tint: [[1.0, 1.0, 1.0], [0.89, 0.92, 0.97], [1.04, 1.02, 0.99]] },
];

function facadeTextures(style, seed) {
  const W = 512, H = 1194;                 // 8 فتحات × 16 طابقًا، نحو 21 بكسل لكل متر
  const cols = 8, rows = 16, cw = W / cols, rh = H / rows;
  const rand = rng(seed);
  const litPattern = [];
  for (let r = 0; r < rows; r++) {
    const floor = rand();                                  // بعض الطوابق مزدحمة وأغلبها هادئ
    const busy = floor < 0.12 ? 0.75 : floor < 0.45 ? 0.32 : 0.07;
    let run = rand() < busy;
    for (let c = 0; c < cols; c++) {
      if (rand() < 0.55) run = rand() < busy;              // النوافذ المضاءة تأتي في مجموعات صغيرة
      litPattern.push(run ? rand() * style.lit : 1);
    }
  }
  const warm = ['#ffd49a', '#ffe2b5', '#ffcb84', '#ffdcae', '#ffe9cc', '#dde8ff'];
  const albedo = canvasTexture(W, H, (ctx) => {
    ctx.fillStyle = style.base; ctx.fillRect(0, 0, W, H);
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
      const x = c * cw, y = r * rh;
      if (style.name === 'glass') {
        ctx.fillStyle = style.spandrel; ctx.fillRect(x, y + rh * 0.8, cw, rh * 0.2);
        const g = ctx.createLinearGradient(x, y, x + cw, y + rh * 0.8);
        g.addColorStop(0, '#3a4f68'); g.addColorStop(0.42, '#28384b'); g.addColorStop(1, style.glass);
        ctx.fillStyle = g; ctx.fillRect(x + 2, y + 2, cw - 4, rh * 0.8 - 3);
        ctx.fillStyle = 'rgba(205,225,255,0.12)'; ctx.fillRect(x + 4, y + 4, cw * 0.18, rh * 0.74);
        ctx.fillStyle = 'rgba(255,255,255,0.07)'; ctx.fillRect(x + 2, y + 3, cw - 8, 3);
        ctx.fillStyle = style.mullion; ctx.fillRect(x, y, 2, rh); ctx.fillRect(x, y + rh * 0.8, cw, 2);
      } else if (style.name === 'concrete') {
        ctx.fillStyle = '#514c46'; ctx.fillRect(x + cw * 0.17, y + rh * 0.2, cw * 0.66, rh * 0.58);
        const cg = ctx.createLinearGradient(x, y, x, y + rh * 0.75); cg.addColorStop(0, '#233241'); cg.addColorStop(1, style.glass);
        ctx.fillStyle = cg; ctx.fillRect(x + cw * 0.2, y + rh * 0.23, cw * 0.6, rh * 0.52);
        ctx.fillStyle = 'rgba(255,255,255,0.08)'; ctx.fillRect(x + cw * 0.24, y + rh * 0.25, cw * 0.12, rh * 0.46);
        ctx.fillStyle = 'rgba(255,255,255,0.08)'; ctx.fillRect(x + cw * 0.15, y + rh * 0.79, cw * 0.7, 3);
      } else {
        ctx.fillStyle = (r % 2) ? '#4b4f56' : '#3a3e45'; ctx.fillRect(x, y, cw, rh);
        const bg = ctx.createLinearGradient(x, y + rh * 0.3, x + cw, y + rh * 0.8); bg.addColorStop(0, '#233241'); bg.addColorStop(1, style.glass);
        ctx.fillStyle = bg; ctx.fillRect(x, y + rh * 0.3, cw, rh * 0.5);
        ctx.fillStyle = 'rgba(255,255,255,0.05)'; ctx.fillRect(x + 2, y + rh * 0.32, cw * 0.15, rh * 0.42);
        ctx.fillStyle = style.mullion; ctx.fillRect(x, y + rh * 0.3, 1.5, rh * 0.5);
      }
    }
    noise(ctx, W, H, 14, rand);
  }, { repeat: true });
  const emissive = canvasTexture(W, H, (ctx) => {
    ctx.fillStyle = '#000'; ctx.fillRect(0, 0, W, H);
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
      const p = litPattern[r * cols + c];
      if (p > style.lit) continue;
      const x = c * cw, y = r * rh;
      let wx, wy, ww, wh;
      if (style.name === 'glass') { wx = x + 2; wy = y + 2; ww = cw - 4; wh = rh * 0.8 - 3; }
      else if (style.name === 'concrete') { wx = x + cw * 0.2; wy = y + rh * 0.23; ww = cw * 0.6; wh = rh * 0.52; }
      else { wx = x; wy = y + rh * 0.3; ww = cw; wh = rh * 0.5; }
      const col = warm[Math.floor(rand() * warm.length)];
      const k = 0.35 + 0.65 * rand();
      const g = ctx.createLinearGradient(wx, wy, wx, wy + wh);
      g.addColorStop(0, col); g.addColorStop(1, '#000');
      ctx.globalAlpha = k; ctx.fillStyle = g; ctx.fillRect(wx, wy, ww, wh);
      if (rand() < 0.35) {                               // الستائر
        ctx.globalAlpha = 0.5; ctx.fillStyle = '#000';
        for (let b = 0; b < wh; b += 4) ctx.fillRect(wx, wy + b, ww, 1.5);
      }
      ctx.globalAlpha = 1;
    }
  }, { repeat: true });
  const rough = canvasTexture(W, H, (ctx) => {
    const v = Math.round(style.rough[1] * 255);
    ctx.fillStyle = `rgb(${v},${v},${v})`; ctx.fillRect(0, 0, W, H);
    const gv = Math.round(style.rough[0] * 255);
    ctx.fillStyle = `rgb(${gv},${gv},${gv})`;
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
      const x = c * cw, y = r * rh;
      if (style.name === 'concrete') ctx.fillRect(x + cw * 0.2, y + rh * 0.23, cw * 0.6, rh * 0.52);
      else if (style.name === 'glass') ctx.fillRect(x + 2, y + 2, cw - 4, rh * 0.8 - 3);
      else ctx.fillRect(x, y + rh * 0.3, cw, rh * 0.5);
    }
  }, { repeat: true, linear: true });
  return { albedo, emissive, rough };
}

function roofTexture(seed) {
  const rand = rng(seed);
  return canvasTexture(256, 256, (ctx) => {
    const g = ctx.createLinearGradient(0,0,256,256); g.addColorStop(0,'#595b5d'); g.addColorStop(1,'#404245'); ctx.fillStyle = g; ctx.fillRect(0, 0, 256, 256);
    noise(ctx, 256, 256, 34, rand);
    ctx.fillStyle='rgba(255,255,255,0.04)'; for(let i=0;i<14;i++) ctx.fillRect(rand()*220,rand()*220,18+rand()*26,2+rand()*3);
    ctx.strokeStyle = 'rgba(0,0,0,0.25)'; ctx.lineWidth = 2;
    for (let i = 0; i <= 256; i += 64) { ctx.beginPath(); ctx.moveTo(i, 0); ctx.lineTo(i, 256); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(0, i); ctx.lineTo(256, i); ctx.stroke(); }
  }, { repeat: true });
}

// ======================================================================= دوال هندسية مساعدة
function quad(pos, nrm, uv, col, a, b, c, d, n, uva, uvb, uvc, uvd, tint) {
  // مثلثان a-b-c وa-c-d
  for (const [p, t] of [[a, uva], [b, uvb], [c, uvc], [a, uva], [c, uvc], [d, uvd]]) {
    pos.push(p.x, p.y, p.z); nrm.push(n.x, n.y, n.z); uv.push(t[0], t[1]); col.push(...tint);
  }
}

function geometryFrom(pos, nrm, uv, col) {
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute('normal', new THREE.Float32BufferAttribute(nrm, 3));
  g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
  g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
  return g;
}

// الجدران الأربعة لصندوق بين الارتفاعين z0 وz1، مع إحداثيات خامة الواجهة بالمتر لكل بلاطة.
function walls(arr, x0, y0, x1, y1, z0, z1, tint, uo, vo, inset = 0) {
  const [pos, nrm, uv, col] = arr;
  x0 += inset; y0 += inset; x1 -= inset; y1 -= inset;
  const faces = [
    // الجنوب (y = y0، للخارج -y)، على طول +x
    { a: [x0, y0], b: [x1, y0], n: [0, -1] },
    { a: [x1, y0], b: [x1, y1], n: [1, 0] },
    { a: [x1, y1], b: [x0, y1], n: [0, 1] },
    { a: [x0, y1], b: [x0, y0], n: [-1, 0] },
  ];
  faces.forEach((f, i) => {
    const L = Math.hypot(f.b[0] - f.a[0], f.b[1] - f.a[1]);
    const u0 = uo + i * 0.37, u1 = u0 + L / TILE_W;
    const v0 = vo + (z0 - LOBBY) / TILE_H, v1 = vo + (z1 - LOBBY) / TILE_H;
    const A = V(f.a[0], f.a[1], z0), B = V(f.b[0], f.b[1], z0), C = V(f.b[0], f.b[1], z1), D = V(f.a[0], f.a[1], z1);
    const n = V(f.n[0], f.n[1], 0);
    quad(pos, nrm, uv, col, A, B, C, D, n, [u0, v0], [u1, v0], [u1, v1], [u0, v1], tint);
  });
}

function topFace(arr, x0, y0, x1, y1, z, tint, scale = 1 / 8) {
  const [pos, nrm, uv, col] = arr;
  const A = V(x0, y0, z), B = V(x1, y0, z), C = V(x1, y1, z), D = V(x0, y1, z);
  quad(pos, nrm, uv, col, A, B, C, D, new THREE.Vector3(0, 1, 0),
    [x0 * scale, y0 * scale], [x1 * scale, y0 * scale], [x1 * scale, y1 * scale], [x0 * scale, y1 * scale], tint);
}

function boxGeom(x0, y0, z0, x1, y1, z1, tint) {
  const arr = [[], [], [], []];
  walls(arr, x0, y0, x1, y1, z0, z1, tint, 0, 0);
  topFace(arr, x0, y0, x1, y1, z1, tint, 0.25);
  return arr;
}

// ======================================================================= شبكة الطرق
// طرق مستقيمة في الفجوات بين الأبراج: خطوط مرشحة x = ثابت / y = ثابت لا يلامس ممرها
// أي برج (مع الهامش)؛ والامتدادات الحرة الأطول من 40 م تصبح مقاطع طرق.
function freeIntervals(c, blocks, W, axis) {
  const half = CORRIDOR / 2;
  const blocked = [];
  for (const b of blocks) {
    const [lo, hi, a0, a1] = axis === 'x' ? [b.x0, b.x1, b.y0, b.y1] : [b.y0, b.y1, b.x0, b.x1];
    if (c + half > lo && c - half < hi) blocked.push([a0, a1]);
  }
  blocked.sort((p, q) => p[0] - q[0]);
  const free = [];
  let s = 0;
  for (const [a0, a1] of blocked) { if (a0 > s) free.push([s, a0]); s = Math.max(s, a1); }
  if (s < W) free.push([s, W]);
  return free.filter(([a, b]) => b - a >= 40);
}

export function roadNetwork(city) {
  const W = city.world.W;
  const m = 6;                                   // ساحة حول كل برج
  const blocks = city.buildings.map(b => ({ x0: b.x0 - m, y0: b.y0 - m, x1: b.x1 + m, y1: b.y1 + m }));
  const nRoads = W <= 300 ? 3 : W <= 600 ? 5 : 8;
  const minGap = W <= 300 ? 60 : 75;
  const roads = [];
  for (const axis of ['x', 'y']) {
    const cands = [];
    for (let c = CORRIDOR / 2 + 4; c <= W - CORRIDOR / 2 - 4; c += 2) {
      const iv = freeIntervals(c, blocks, W, axis);
      const len = iv.reduce((s, [a, b]) => s + (b - a), 0);
      cands.push({ c, iv, len });
    }
    cands.sort((p, q) => q.len - p.len);
    const chosen = [];
    for (const cd of cands) {
      if (chosen.length >= nRoads) break;
      if (cd.len < W * 0.3) break;
      if (chosen.some(o => Math.abs(o.c - cd.c) < minGap)) continue;
      chosen.push(cd);
    }
    for (const cd of chosen) for (const [a, b] of cd.iv) roads.push({ axis, c: cd.c, a, b });
  }
  // التقاطعات
  const xs = [];
  for (const r of roads.filter(r => r.axis === 'x')) for (const q of roads.filter(q => q.axis === 'y')) {
    if (q.c > r.a && q.c < r.b && r.c > q.a && r.c < q.b) xs.push({ x: r.c, y: q.c });
  }
  return { roads, intersections: xs, blocks };
}

// ======================================================================= خامة الأرض
function groundTextures(city, net, seed) {
  const W = city.world.W;
  const ppm = W <= 300 ? 4 : W <= 600 ? 3 : 2;         // بكسل لكل متر
  const N = Math.min(2048, Math.round(W * ppm));
  const s = N / W;
  const rand = rng(seed);
  const assets=getVisualAssets();
  const X = (x) => x * s, Y = (y) => (W - y) * s;      // محور y في اللوحة يزيد نحو الجنوب
  const lights = [];
  const albedo = canvasTexture(N, N, (ctx) => {
    const photoPattern=(image,metres)=>{
      if(!image)return null;
      const tile=document.createElement('canvas');tile.width=tile.height=Math.max(8,Math.round(metres*s));
      tile.getContext('2d').drawImage(image,0,0,tile.width,tile.height);return ctx.createPattern(tile,'repeat');
    };
    const asphalt=photoPattern(assets.asphalt,7),paving=photoPattern(assets.concrete,3);
    // العشب عالي التفاصيل يُؤخذ منفصلًا في مظلل الأرض، أما
    // أطلس المدينة فيوفر اللون العام وسطحًا واحدًا للطرق والساحات.
    ctx.fillStyle = '#718a4e'; ctx.fillRect(0, 0, N, N);
    // الساحات حول الأبراج
    for (const b of city.buildings) {
      const m = 5;
      ctx.fillStyle = paving||'#5d5b57';
      ctx.fillRect(X(b.x0 - m), Y(b.y1 + m), (b.x1 - b.x0 + 2 * m) * s, (b.y1 - b.y0 + 2 * m) * s);
      ctx.strokeStyle = 'rgba(0,0,0,0.18)'; ctx.lineWidth = 1;
      for (let x = b.x0 - m; x < b.x1 + m; x += 2) { ctx.beginPath(); ctx.moveTo(X(x), Y(b.y1 + m)); ctx.lineTo(X(x), Y(b.y0 - m)); ctx.stroke(); }
    }
    // الأرصفة ثم الإسفلت
    for (const pass of ['walk', 'road']) {
      for (const r of net.roads) {
        const w = pass === 'walk' ? CORRIDOR : ROAD;
        ctx.fillStyle = pass === 'walk' ? (paving||'#6a6862') : (asphalt||'#2a2b2e');
        if (r.axis === 'x') ctx.fillRect(X(r.c - w / 2), Y(r.b), w * s, (r.b - r.a) * s);
        else ctx.fillRect(X(r.a), Y(r.c + w / 2), (r.b - r.a) * s, w * s);
      }
    }
    // علامات المسارات
    ctx.setLineDash([3 * s, 4 * s]);
    ctx.strokeStyle = 'rgba(235,235,225,0.75)'; ctx.lineWidth = Math.max(1, 0.18 * s);
    for (const r of net.roads) {
      ctx.beginPath();
      if (r.axis === 'x') { ctx.moveTo(X(r.c), Y(r.a)); ctx.lineTo(X(r.c), Y(r.b)); }
      else { ctx.moveTo(X(r.a), Y(r.c)); ctx.lineTo(X(r.b), Y(r.c)); }
      ctx.stroke();
    }
    ctx.setLineDash([]);
    ctx.strokeStyle = 'rgba(235,235,225,0.5)';
    for (const r of net.roads) for (const side of [-1, 1]) {
      const o = r.c + side * (ROAD / 2 - 0.5);
      ctx.beginPath();
      if (r.axis === 'x') { ctx.moveTo(X(o), Y(r.a)); ctx.lineTo(X(o), Y(r.b)); }
      else { ctx.moveTo(X(r.a), Y(o)); ctx.lineTo(X(r.b), Y(o)); }
      ctx.stroke();
    }
    // التقاطعات: إسفلت عادي + ممرات مشاة
    for (const p of net.intersections) {
      ctx.fillStyle = asphalt||'#2a2b2e';
      ctx.fillRect(X(p.x - ROAD / 2), Y(p.y + ROAD / 2), ROAD * s, ROAD * s);
      ctx.fillStyle = 'rgba(230,230,220,0.75)';
      for (let k = -ROAD / 2 + 1; k < ROAD / 2 - 0.5; k += 1.4) {
        for (const d of [-1, 1]) {
          ctx.fillRect(X(p.x + k), Y(p.y + d * (ROAD / 2 + 2.6)), 0.7 * s, 2.2 * s);       // معابر شمال/جنوب
          ctx.fillRect(X(p.x + d * (ROAD / 2 + 0.4) + (d < 0 ? -2.2 : 0)), Y(p.y + k), 2.2 * s, 0.7 * s);
        }
      }
    }
    // منصات الهبوط في منطقة الإقلاع
    for (const S of city.staging.points) {
      ctx.fillStyle = '#3d3f43'; ctx.beginPath(); ctx.arc(X(S[0]), Y(S[1]), 6 * s, 0, 7); ctx.fill();
      ctx.strokeStyle = '#e8e8e0'; ctx.lineWidth = 0.35 * s; ctx.beginPath(); ctx.arc(X(S[0]), Y(S[1]), 5.2 * s, 0, 7); ctx.stroke();
      ctx.fillStyle = '#e8e8e0'; ctx.font = `bold ${6 * s}px sans-serif`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      ctx.fillText('H', X(S[0]), Y(S[1]));
    }
    noise(ctx, N, N, 5, rand);
  });
  const emissive = canvasTexture(N, N, (ctx) => {
    ctx.fillStyle = '#000'; ctx.fillRect(0, 0, N, N);
    const glow = (x, y, r, col, a) => {
      const g = ctx.createRadialGradient(X(x), Y(y), 0, X(x), Y(y), r * s);
      g.addColorStop(0, col.replace('A', a)); g.addColorStop(1, col.replace('A', 0));
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(X(x), Y(y), r * s, 0, 7); ctx.fill();
    };
    // أعمدة إنارة كل ~32 م، على جانبين متبادلين
    for (const r of net.roads) {
      let side = 1;
      for (let t = r.a + 12; t < r.b - 8; t += 32) {
        const o = r.c + side * (ROAD / 2 + 0.6);
        const [x, y] = r.axis === 'x' ? [o, t] : [t, o];
        if (net.intersections.some(p => Math.hypot(p.x - x, p.y - y) < 10)) { side = -side; continue; }
        lights.push({ x, y, side, axis: r.axis });
        glow(x - (r.axis === 'x' ? side * 2.5 : 0), y - (r.axis === 'y' ? side * 2.5 : 0), 12, 'rgba(255,170,90,A)', 0.42);
        side = -side;
      }
    }
    for (const S of city.staging.points) {
      for (let a = 0; a < 8; a++) {
        const x = S[0] + 5.6 * Math.cos(a * Math.PI / 4), y = S[1] + 5.6 * Math.sin(a * Math.PI / 4);
        glow(x, y, 0.8, 'rgba(120,255,170,A)', 0.9);
      }
      glow(S[0], S[1], 16, 'rgba(220,235,255,A)', 0.25);
    }
    // ضوء الردهة المنسكب على الساحات
    for (const b of city.buildings) {
      ctx.fillStyle = 'rgba(255,200,140,0.10)';
      ctx.fillRect(X(b.x0 - 4), Y(b.y1 + 4), (b.x1 - b.x0 + 8) * s, (b.y1 - b.y0 + 8) * s);
    }
  });
  const lawnMask=canvasTexture(N,N,ctx=>{
    ctx.fillStyle='#fff';ctx.fillRect(0,0,N,N);ctx.fillStyle='#000';
    for(const b of city.buildings)ctx.fillRect(X(b.x0-5),Y(b.y1+5),(b.x1-b.x0+10)*s,(b.y1-b.y0+10)*s);
    for(const r of net.roads){
      if(r.axis==='x')ctx.fillRect(X(r.c-CORRIDOR/2),Y(r.b),CORRIDOR*s,(r.b-r.a)*s);
      else ctx.fillRect(X(r.a),Y(r.c+CORRIDOR/2),(r.b-r.a)*s,CORRIDOR*s);
    }
    for(const S of city.staging.points){ctx.beginPath();ctx.arc(X(S[0]),Y(S[1]),6*s,0,Math.PI*2);ctx.fill();}
  },{linear:true,aniso:8});
  return { albedo, emissive, lights, lawnMask };
}

// للأرض المحيطة فتحة فعلية بحجم المدينة. فقد سبب مستويان شبه منطبقين
// ومتداخلين تنازعًا في العمق عند المسافات البعيدة والزوايا المماسية.
export function surroundingGroundGeometry(W){
  const lo=-4*W,hi=5*W,shape=new THREE.Shape();
  shape.moveTo(lo,lo);shape.lineTo(hi,lo);shape.lineTo(hi,hi);shape.lineTo(lo,hi);shape.closePath();
  const hole=new THREE.Path();hole.moveTo(0,0);hole.lineTo(0,W);hole.lineTo(W,W);hole.lineTo(W,0);hole.closePath();shape.holes.push(hole);
  const geometry=new THREE.ShapeGeometry(shape),uv=geometry.attributes.uv,position=geometry.attributes.position;
  for(let i=0;i<position.count;i++)uv.setXY(i,position.getX(i)/48,position.getY(i)/48);
  geometry.rotateX(-Math.PI/2);return geometry;
}

// ======================================================================= الأشجار والسيارات وأعمدة الإنارة
export function treeGeometries() {
  const r=rng(7),branches=[new THREE.CylinderGeometry(.12,.24,3.8,5).translate(0,1.9,0).toNonIndexed()];
  const up=new THREE.Vector3(0,1,0);
  for(let i=0;i<3;i++){
    const angle=i*2.3999,end=new THREE.Vector3(Math.cos(angle)*(1.1+r()*.6),4.1+r()*1.1,Math.sin(angle)*(1.1+r()*.6));
    const start=new THREE.Vector3(0,2.1+r()*.8,0),delta=end.clone().sub(start);
    const branch=new THREE.CylinderGeometry(.028,.075,delta.length(),3).toNonIndexed();
    branch.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(up,delta.clone().normalize()));
    branch.translate(...start.add(end).multiplyScalar(.5).toArray());branches.push(branch);
  }
  const trunk=mergeGeometries(branches),cards=[];
  // تحل عناقيد أوراق متقاطعة مختبرة بالشفافية محل كرات مضلعة معتمة،
  // ويبقى الحي كاملًا مجمعًا في شبكة تاج واحدة متعددة النسخ.
  for(let i=0;i<24;i++){
    const a=i*2.39996,vertical=1-2*(i+.5)/24,ring=Math.sqrt(1-vertical*vertical);
    const radius=.48+.52*Math.cbrt(r());
    const at=new THREE.Vector3(Math.cos(a)*ring*2.05*radius,4.7+vertical*1.55,Math.sin(a)*ring*2.05*radius);
    const card=new THREE.PlaneGeometry(1.25+r()*.65,1.3+r()*.65).toNonIndexed();
    card.rotateY(a);card.rotateX((r()-.5)*1.4);card.translate(...at.toArray());cards.push(card);
  }
  const crown=mergeGeometries(cards),p=crown.attributes.position,colors=[],normals=[];
  for(let i=0;i<p.count;i++){
    const light=.63+.37*clamp((p.getY(i)-2.5)/4.2,0,1);colors.push(light*.96,light,light*.88);
    const n=new THREE.Vector3(p.getX(i),p.getY(i)-4.7,p.getZ(i)).normalize();normals.push(n.x,n.y,n.z);
  }
  crown.setAttribute('color',new THREE.Float32BufferAttribute(colors,3));
  crown.setAttribute('normal',new THREE.Float32BufferAttribute(normals,3));
  crown.computeBoundingBox();
  return {trunk,crown,maxHeight:crown.boundingBox.max.y};
}

function leafTexture() {
  const r=rng(411);
  return canvasTexture(128,128,ctx=>{
    ctx.clearRect(0,0,128,128);
    ctx.strokeStyle='#8a9d66';ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(64,120);ctx.lineTo(62,18);ctx.stroke();
    for(let i=0;i<48;i++){
      const y=14+r()*100,x=64+(r()-.5)*70*Math.sin(y/128*Math.PI);
      ctx.save();ctx.translate(x,y);ctx.rotate((r()-.5)*2.6);
      ctx.fillStyle=['#a8c17f','#d1dfa1','#849e60','#bbc98c'][i%4];
      ctx.beginPath();ctx.ellipse(0,0,3+r()*3,6+r()*5,.25,0,Math.PI*2);ctx.fill();ctx.restore();
    }
  },{aniso:4});
}

export function carGeometries() {
  const extrude=(points,depth,bevel)=>{
    const shape=new THREE.Shape();points.forEach(([x,y],i)=>i?shape.lineTo(x,y):shape.moveTo(x,y));shape.closePath();
    return new THREE.ExtrudeGeometry(shape,{depth,bevelEnabled:true,bevelSegments:1,steps:1,bevelSize:bevel,bevelThickness:bevel}).translate(0,0,-depth/2);
  };
  const shell=extrude([[-2.05,.47],[-2.05,.88],[-1.38,1.03],[.85,1.08],[1.9,.91],[2.08,.67],[2.05,.47]],1.68,.08);
  const roof=new RoundedBoxGeometry(1.85,.11,1.40,1,.055).translate(-.34,1.82,0);
  const body=mergeGeometries([shell,roof.index?roof.toNonIndexed():roof]);
  const glass=extrude([[-1.4,1.02],[-.98,1.77],[.49,1.77],[1.08,1.06]],1.48,.04);
  const pillars=[];
  for(const side of [-1,1])pillars.push(new THREE.BoxGeometry(.09,.71,.06).translate(-.25,1.40,side*.79).toNonIndexed());
  const cabin=glass;
  const wheels = [],hubs=[];
  for (const [x, z] of [[1.35, 0.85], [1.35, -0.85], [-1.35, 0.85], [-1.35, -0.85]]) {
    wheels.push(new THREE.CylinderGeometry(0.36, 0.36, 0.28, 8).rotateX(Math.PI / 2).translate(x, 0.36, z).toNonIndexed());
    hubs.push(new THREE.CylinderGeometry(.21,.21,.035,8).rotateX(Math.PI/2).translate(x,.36,z>0?z+.15:z-.15).toNonIndexed());
  }
  for(const x of [-2.12,2.15])hubs.push(new THREE.BoxGeometry(.045,.11,1.30).translate(x,.53,0).toNonIndexed());
  return { body:mergeGeometries([body,...pillars]), cabin, wheels:mergeGeometries(wheels),hubs:mergeGeometries(hubs) };
}

// ======================================================================= كائن المدينة
export class City {
  constructor(scene, city, opts = {}) {
    this.scene = scene;
    this.data = city;
    this.W = city.world.W;
    this.group = new THREE.Group();
    this.group.name = 'city';
    scene.add(this.group);
    this.seed = (city.seed_used || city.seed || 1) * 7919 + city.buildings.length;
    this.net = roadNetwork(city);
    this.anim = [];
    this.buildGround();
    this.buildTowers();
    this.buildStreetDetails();
    this.buildTrees();
    this.buildGrass();
    this.buildStreetLights();
    this.buildCars();
    this.buildStaging();
    this.buildMargins();
  }

  // ------------------------------------------------------------------ الأرض
  buildGround() {
    const W = this.W;
    const tex = groundTextures(this.data, this.net, this.seed);
    this.lightsPos = tex.lights;
    const assets=getVisualAssets();
    const mat = new THREE.MeshStandardMaterial({ map: tex.albedo, emissiveMap: tex.emissive, emissive: 0xffffff,
      emissiveIntensity: .32, roughness:.96, metalness:0 });
    if(assets.grass){
      const grass=new THREE.Texture(assets.grass);grass.needsUpdate=true;grass.colorSpace=THREE.SRGBColorSpace;
      grass.wrapS=grass.wrapT=THREE.RepeatWrapping;grass.anisotropy=8;
      const detail=new THREE.Texture(assets.leafyGrass||assets.grass);detail.needsUpdate=true;detail.colorSpace=THREE.SRGBColorSpace;
      detail.wrapS=detail.wrapT=THREE.RepeatWrapping;detail.anisotropy=8;
      const normal=assets.grassNormal?new THREE.Texture(assets.grassNormal):null;
      if(normal){normal.needsUpdate=true;normal.wrapS=normal.wrapT=THREE.RepeatWrapping;normal.repeat.set(W/8,W/8);normal.anisotropy=8;mat.normalMap=normal;mat.normalScale=new THREE.Vector2(.3,.3);}
      // إبقاء الخامات المملوكة ظاهرة لأداة تحرير الموارد في العارض.
      mat.userData.lawnMap=grass;mat.userData.lawnDetail=detail;mat.userData.lawnMask=tex.lawnMask;
      mat.onBeforeCompile=shader=>{
        shader.uniforms.uLawnMap={value:grass};shader.uniforms.uLawnDetail={value:detail};shader.uniforms.uLawnMask={value:tex.lawnMask};
        shader.fragmentShader='uniform sampler2D uLawnMap,uLawnDetail,uLawnMask;\n'+shader.fragmentShader;
        shader.fragmentShader=shader.fragmentShader.replace('#include <map_fragment>',`#include <map_fragment>
          float lawn=texture2D(uLawnMask,vMapUv).r;
          vec3 turf=mix(texture2D(uLawnMap,vMapUv*${(W/8).toFixed(4)}).rgb,texture2D(uLawnDetail,vMapUv*${(W/4).toFixed(4)}).rgb,.18)*vec3(.78,1.12,.61);
          diffuseColor.rgb=mix(diffuseColor.rgb,turf,lawn);`);
        shader.fragmentShader=shader.fragmentShader.replace('#include <normal_fragment_maps>',`#include <normal_fragment_maps>
          normal=normalize(mix(nonPerturbedNormal,normal,lawn));`);
      };
      mat.customProgramCacheKey=()=>`photographic-turf-${W}`;
    }
    const g = new THREE.PlaneGeometry(W, W).rotateX(-Math.PI / 2).translate(W / 2, 0, -W / 2);
    const ground = new THREE.Mesh(g, mat);
    ground.receiveShadow = true;
    ground.name = 'ground';
    this.group.add(ground);
    // الأرض حول المدينة، تتلاشى في الضباب
    const outer = canvasTexture(512, 512, (ctx) => {
      ctx.fillStyle = '#607b49'; ctx.fillRect(0,0,512,512);
      if(assets.grass)ctx.drawImage(assets.grass,0,0,512,512);
    }, { repeat: true,aniso:8 });
    outer.repeat.set(6,6);
    const big = new THREE.Mesh(surroundingGroundGeometry(W),
      new THREE.MeshStandardMaterial({ map: outer,color:0x94b777, roughness: 1 }));
    big.name = 'land';
    this.group.add(big);
  }

  // مولد المعمار: كل مبنى كتلة مصممة مستقلة.
  // يبقى صندوق AABB الرياضي للمدينة عائق الطيران دون تغيير.
  buildTowers() {
    const built = buildArchitecturalCity(this.group, this.data, this.seed, this.anim);
    this.towers = built.towers;
    this.redLights = built.redLights;
    this.redMat = built.redMat;
  }

  buildStreetDetails() {
    // أرصفة وأعمدة مجمعة تثبّت المدينة بصريًا عند ارتفاع عين المسيّرة.
    // كل هندسة الشوارع تبقى تحت أرضية الطيران وخارج هوامش الأبراج.
    const kerbs=[], posts=[];
    for(const r of this.net.roads) for(const side of [-1,1]) {
      const length=r.b-r.a, across=r.c+side*(ROAD/2+.12);
      const size=r.axis==='x'?[.24,.18,length]:[length,.18,.24];
      const centre=r.axis==='x'?V(across,(r.a+r.b)/2,.09):V((r.a+r.b)/2,across,.09);
      kerbs.push(new THREE.BoxGeometry(...size).translate(centre.x,centre.y,centre.z));
      for(let t=r.a+4;t<r.b-3;t+=18){
        const [x,y]=r.axis==='x'?[r.c+side*(ROAD/2+WALK*.7),t]:[t,r.c+side*(ROAD/2+WALK*.7)];
        if(!this.net.intersections.some(p=>Math.hypot(p.x-x,p.y-y)<12)) posts.push(V(x,y,.45));
      }
    }
    if(kerbs.length){
      const curb=new THREE.Mesh(mergeGeometries(kerbs.map(g=>g.toNonIndexed())),new THREE.MeshStandardMaterial({color:0x93918b,roughness:.92}));
      curb.receiveShadow=true;curb.name='raised_kerbs';this.group.add(curb);
      for(const g of kerbs)g.dispose();
    }
    const bollards=new THREE.InstancedMesh(new THREE.CylinderGeometry(.12,.16,.9,8),
      new THREE.MeshStandardMaterial({color:0x3d454a,roughness:.55,metalness:.65}),posts.length);
    const matrix=new THREE.Matrix4();posts.forEach((p,i)=>bollards.setMatrixAt(i,matrix.makeTranslation(p.x,p.y,p.z)));
    bollards.name='street_bollards';this.group.add(bollards);
    // تماس المباني مع الأرض يأتي من خريطة الظل الحقيقية. لا ملصقات سوداء واسعة
    // تغطي العشب أو تتنازع مع الأرض عند زاوية كاميرا مماسية.
  }

  // ------------------------------------------------------------------ الأشجار
  free(x, y, r) {
    const W = this.W;
    if (x < r || y < r || x > W - r || y > W - r) return false;
    for (const b of this.data.buildings) if (x > b.x0 - 6 - r && x < b.x1 + 6 + r && y > b.y0 - 6 - r && y < b.y1 + 6 + r) return false;
    for (const rd of this.net.roads) {
      const [u, v] = rd.axis === 'x' ? [x, y] : [y, x];
      if (Math.abs(u - rd.c) < ROAD / 2 + 0.8 + r && v > rd.a - 2 && v < rd.b + 2) return false;
    }
    for (const S of this.data.staging.points) if (Math.hypot(x - S[0], y - S[1]) < 16) return false;
    return true;
  }

  buildTrees() {
    const rand = rng(this.seed + 21);
    const spots = [];
    // على طول الأرصفة
    for (const r of this.net.roads) for (const side of [-1, 1]) {
      for (let t = r.a + 6 + rand() * 6; t < r.b - 4; t += 9 + rand() * 6) {
        const o = r.c + side * (ROAD / 2 + WALK * 0.55);
        const [x, y] = r.axis === 'x' ? [o, t] : [t, o];
        if (rand() < 0.15) continue;
        if (this.net.intersections.some(p => Math.abs(p.x - x) < 10 && Math.abs(p.y - y) < 10)) continue;
        let ok = true;
        for (const b of this.data.buildings) if (x > b.x0 - 7 && x < b.x1 + 7 && y > b.y0 - 7 && y < b.y1 + 7) ok = false;
        if (ok) spots.push([x, y, 0.8 + rand() * 0.4]);
      }
    }
    // الحدائق: أرض مفتوحة بعيدة عن الطرق والأبراج
    const tries = Math.round(this.W * this.W / 180);
    for (let i = 0; i < tries; i++) {
      const x = rand() * this.W, y = rand() * this.W;
      if (!this.free(x, y, 2)) continue;
      if (spots.some(s => Math.abs(s[0] - x) < 5 && Math.abs(s[1] - y) < 5)) continue;
      spots.push([x, y, 0.7 + rand() * 0.75]);
    }
    const { trunk, crown, maxHeight } = treeGeometries();
    const n = spots.length;
    const trunks = new THREE.InstancedMesh(trunk, new THREE.MeshStandardMaterial({ color: 0x3a2c22, roughness: 1 }), n);
    const foliage=new THREE.MeshStandardMaterial({map:leafTexture(),alphaTest:.42,side:THREE.DoubleSide,color:0xffffff,roughness:.92,vertexColors:true});
    const crowns = new THREE.InstancedMesh(crown,foliage,n);
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), sc = new THREE.Vector3(), c = new THREE.Color();
    spots.forEach(([x, y, s], i) => {
      q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), rand() * 6.28);
      sc.set(s, Math.min(s*(.9+rand()*.25),(this.data.world.z_min-.8)/maxHeight), s);
      m.compose(V(x, y, 0), q, sc);
      trunks.setMatrixAt(i, m); crowns.setMatrixAt(i, m);
      c.setHSL(.28+rand()*.045,.32+rand()*.12,.28+rand()*.08);
      crowns.setColorAt(i, c);
    });
    trunks.castShadow = crowns.castShadow = true;
    trunks.name = 'tree_trunks'; crowns.name = 'tree_crowns';
    this.group.add(trunks, crowns);
    this.treeCount = n;
  }

  buildGrass(){
    // خصلات عشب منخفضة فعلية في القطع المفتوحة، مجمعة في رسم واحد. وهي
    // أقل من 0.6 م، أي أسفل أرضية الطيران الثابتة بأمان. والقاعدة عشب
    // فوتوغرافي متصل، فتبقى القطع البعيدة خضراء مع تلاشي الأوراق.
    const rand=rng(this.seed+432),positions=[];
    const spacing=this.W<=300?5.5:this.W<=600?7.5:10;
    for(let x=2;x<this.W-2;x+=spacing)for(let y=2;y<this.W-2;y+=spacing){
      const xx=x+(rand()-.5)*spacing,yy=y+(rand()-.5)*spacing;
      if(this.free(xx,yy,1.3))positions.push([xx,yy,.65+rand()*.6]);
    }
    const p=[],col=[];
    for(let blade=0;blade<9;blade++){
      const a=rand()*Math.PI*2,r=rand()*.65,cx=Math.cos(a)*r,cz=Math.sin(a)*r;
      const h=.22+rand()*.32,w=.035+rand()*.035,dx=Math.cos(a)*w,dz=Math.sin(a)*w;
      p.push(cx-dx,0,cz-dz,cx+dx,0,cz+dz,cx+.12*Math.sin(a),h,cz+.12*Math.cos(a));
      col.push(.22,.34,.10,.22,.34,.10,.56,.68,.28);
    }
    const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(p,3));
    geo.setAttribute('color',new THREE.Float32BufferAttribute(col,3));geo.computeVertexNormals();
    const mat=new THREE.MeshStandardMaterial({vertexColors:true,roughness:1,side:THREE.DoubleSide});
    const wind={value:0};
    mat.onBeforeCompile=shader=>{
      shader.uniforms.uGrassTime=wind;
      shader.vertexShader='uniform float uGrassTime;\n'+shader.vertexShader;
      shader.vertexShader=shader.vertexShader.replace('#include <begin_vertex>',`#include <begin_vertex>
        transformed.x+=sin(uGrassTime*1.5+instanceMatrix[3].x*.4+instanceMatrix[3].z*.3)*position.y*position.y*.18;`);
    };
    mat.customProgramCacheKey=()=> 'low-grass-wind';
    const mesh=new THREE.InstancedMesh(geo,mat,positions.length),m=new THREE.Matrix4(),q=new THREE.Quaternion(),scale=new THREE.Vector3();
    positions.forEach(([x,y,s],i)=>{q.setFromAxisAngle(new THREE.Vector3(0,1,0),rand()*6.283);scale.setScalar(s);m.compose(V(x,y,0),q,scale);mesh.setMatrixAt(i,m);});
    mesh.name='park_grass_tufts';mesh.receiveShadow=true;this.group.add(mesh);
    this.anim.push(t=>{wind.value=t;});this.grassCount=positions.length;
  }

  // ------------------------------------------------------------------ أعمدة الإنارة
  buildStreetLights() {
    const L = this.lightsPos;
    if (!L.length) return;
    const pole = new THREE.CylinderGeometry(0.09, 0.13, 8, 6).translate(0, 4, 0);
    const arm = new THREE.BoxGeometry(2.4, 0.12, 0.18).translate(-1.1, 7.9, 0);
    const head = new THREE.BoxGeometry(0.9, 0.18, 0.4).translate(-2.2, 7.82, 0);
    const geo = mergeGeometries([pole.toNonIndexed(), arm.toNonIndexed(), head.toNonIndexed()]);
    const mesh = new THREE.InstancedMesh(geo, new THREE.MeshStandardMaterial({ color: 0x55585e, roughness: 0.6, metalness: 0.4 }), L.length);
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), one = new THREE.Vector3(1, 1, 1);
    const lamps = [];
    L.forEach((l, i) => {
      // الذراع يشير فوق الطريق
      let ang;
      if (l.axis === 'x') ang = l.side > 0 ? 0 : Math.PI; else ang = l.side > 0 ? Math.PI / 2 : -Math.PI / 2;
      q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), ang);
      m.compose(V(l.x, l.y, 0), q, one);
      mesh.setMatrixAt(i, m);
      const dx = l.axis === 'x' ? -l.side * 2.2 : 0, dy = l.axis === 'y' ? -l.side * 2.2 : 0;
      lamps.push(V(l.x + dx, l.y + dy, 7.7));
    });
    mesh.name = 'street_poles';
    this.group.add(mesh);
    const pts = new THREE.Points(new THREE.BufferGeometry().setFromPoints(lamps), new THREE.PointsMaterial({
      size: 5, sizeAttenuation: true, color: 0xffb066, map: radialSprite(64, 'rgba(255,255,255,1)', 'rgba(255,255,255,0)'),
      transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false }));
    pts.name = 'street_lamps';
    this.group.add(pts);
  }

  // ------------------------------------------------------------------ السيارات
  buildCars() {
    const rand = rng(this.seed + 31);
    const lanes = [];
    for (const r of this.net.roads) {
      const len = r.b - r.a;
      const n = Math.max(1, Math.round(len / 55));
      for (let i = 0; i < n; i++) {
        const dir = rand() < 0.5 ? 1 : -1;
        lanes.push({ r, dir, s: rand() * len, len, speed: 7 + rand() * 7, lane: dir * 1.9 });
      }
    }
    this.cars = lanes;
    const n = lanes.length;
    const { body, cabin, wheels,hubs } = carGeometries();
    const paint = [0xd8d8d8, 0x9aa0a6, 0x1c1d20, 0x24324a, 0x7a1e1e, 0x4b4f55, 0xe9e5dc, 0x2f3b2e];
    this.carBody = new THREE.InstancedMesh(body, new THREE.MeshPhysicalMaterial({ color: 0xffffff, roughness:.32,metalness:.42,clearcoat:.85,clearcoatRoughness:.14 }), n);
    this.carCabin = new THREE.InstancedMesh(cabin, new THREE.MeshPhysicalMaterial({color:0x172b3c,roughness:.13,metalness:.6,clearcoat:1}), n);
    this.carWheels = new THREE.InstancedMesh(wheels, new THREE.MeshStandardMaterial({ color: 0x111111, roughness: 0.9 }), n);
    this.carHubs=new THREE.InstancedMesh(hubs,new THREE.MeshStandardMaterial({color:0x9ba7ae,metalness:.8,roughness:.26}),n);
    const c = new THREE.Color();
    for (let i = 0; i < n; i++) this.carBody.setColorAt(i, c.setHex(paint[Math.floor(rand() * paint.length)]));
    this.carBody.name = 'cars';
    for(const mesh of [this.carBody,this.carCabin,this.carWheels,this.carHubs])mesh.castShadow=mesh.receiveShadow=true;
    this.group.add(this.carBody, this.carCabin, this.carWheels,this.carHubs);
    const mk = (color, size) => {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(n * 2 * 3), 3));
      const p = new THREE.Points(g, new THREE.PointsMaterial({ size, color, sizeAttenuation: true,
        map: radialSprite(64, 'rgba(255,255,255,1)', 'rgba(255,255,255,0)'), transparent: true, depthWrite: false,
        blending: THREE.AdditiveBlending, toneMapped: false }));
      p.frustumCulled = false;
      this.group.add(p);
      return p;
    };
    this.headLights = mk(0xfff4dc, 2.6);
    this.tailLights = mk(0xff2010, 1.6);
    this.anim.push((t, dt) => this.updateCars(dt));
    this.updateCars(0);
  }

  updateCars(dt) {
    const m = new THREE.Matrix4(), q = new THREE.Quaternion(), one = new THREE.Vector3(1, 1, 1);
    const hp = this.headLights.geometry.attributes.position, tp = this.tailLights.geometry.attributes.position;
    const up = new THREE.Vector3(0, 1, 0);
    this.cars.forEach((car, i) => {
      car.s += car.dir * car.speed * dt;
      if (car.s > car.len) car.s -= car.len;
      if (car.s < 0) car.s += car.len;
      const r = car.r;
      const t = r.a + car.s;
      const [x, y] = r.axis === 'x' ? [r.c + car.lane, t] : [t, r.c - car.lane];
      // الاتجاه بإحداثيات المشروع
      const hx = r.axis === 'x' ? 0 : car.dir, hy = r.axis === 'x' ? car.dir : 0;
      const yaw = Math.atan2(hy, hx);                 // three: دوران حول +Y؛ وy في المشروع -> -z
      q.setFromAxisAngle(up, yaw);
      const p = V(x, y, 0);
      m.compose(p, q, one);
      this.carBody.setMatrixAt(i, m); this.carCabin.setMatrixAt(i, m); this.carWheels.setMatrixAt(i, m);
      this.carHubs.setMatrixAt(i,m);
      const fx = Math.cos(yaw), fz = -Math.sin(yaw), sx = Math.sin(yaw) * 0.7, sz = Math.cos(yaw) * 0.7;
      hp.setXYZ(2 * i, p.x + fx * 2.25 + sx, 0.75, p.z + fz * 2.25 + sz);
      hp.setXYZ(2 * i + 1, p.x + fx * 2.25 - sx, 0.75, p.z + fz * 2.25 - sz);
      tp.setXYZ(2 * i, p.x - fx * 2.25 + sx, 0.85, p.z - fz * 2.25 + sz);
      tp.setXYZ(2 * i + 1, p.x - fx * 2.25 - sx, 0.85, p.z - fz * 2.25 - sz);
    });
    this.carBody.instanceMatrix.needsUpdate = this.carCabin.instanceMatrix.needsUpdate = this.carWheels.instanceMatrix.needsUpdate = this.carHubs.instanceMatrix.needsUpdate = true;
    hp.needsUpdate = tp.needsUpdate = true;
  }

  // ------------------------------------------------------------------ منطقة الإقلاع: شاحنات الإطفاء والأضواء
  buildStaging() {
    const city = this.data;
    const pts = city.staging.points;
    const edge = city.staging.edge;
    this.beacons = [];
    const out = { W: [-1, 0], E: [1, 0], S: [0, -1], N: [0, 1] }[edge] || [-1, 0];
    const along = [out[1], -out[0]];
    const c = pts.reduce((a, p) => [a[0] + p[0] / pts.length, a[1] + p[1] / pts.length], [0, 0]);
    const spread = Math.max(30, Math.abs((pts[pts.length - 1][0] - pts[0][0]) * along[0] + (pts[pts.length - 1][1] - pts[0][1]) * along[1]));
    const nTrucks = pts.length >= 3 ? 3 : 2;
    for (let k = 0; k < nTrucks; k++) {
      const u = (k - (nTrucks - 1) / 2) * (spread / Math.max(1, nTrucks - 1) + 8);
      const x = c[0] + along[0] * u + out[0] * 22, y = c[1] + along[1] * u + out[1] * 22;
      const yaw = Math.atan2(along[1], along[0]);
      this.addTruck(x, y, yaw, false);
    }
  }

  addTruck(x, y, yaw, ladderTo = null) {
    const g = new THREE.Group();
    const red = new THREE.MeshStandardMaterial({ color: 0xb3120f, roughness: 0.4, metalness: 0.3 });
    const dark = new THREE.MeshStandardMaterial({ color: 0x15171a, roughness: 0.3, metalness: 0.6 });
    const steel = new THREE.MeshStandardMaterial({ color: 0xb8bcc2, roughness: 0.35, metalness: 0.8 });
    const body = new THREE.Mesh(new RoundedBoxGeometry(7.5, 2.6, 2.5, 2, 0.15), red); body.position.set(-0.8, 1.9, 0);
    const cab = new THREE.Mesh(new RoundedBoxGeometry(2.4, 2.4, 2.5, 2, 0.2), red); cab.position.set(3.9, 1.8, 0);
    const glass = new THREE.Mesh(new THREE.BoxGeometry(0.1, 1.0, 2.2), dark); glass.position.set(5.12, 2.3, 0);
    const stripe = new THREE.Mesh(new THREE.BoxGeometry(10.1, 0.18, 2.52), new THREE.MeshStandardMaterial({ color: 0xf0f0e8, emissive: 0x332f22 }));
    stripe.position.set(0.4, 1.3, 0);
    const ladder = new THREE.Mesh(new THREE.BoxGeometry(7.5, 0.35, 1.0), steel); ladder.position.set(-0.6, 3.4, 0);
    const wheels = new THREE.Mesh(mergeGeometries([[-3, 1.15], [-3, -1.15], [-1.4, 1.15], [-1.4, -1.15], [3.8, 1.15], [3.8, -1.15]]
      .map(([wx, wz]) => new THREE.CylinderGeometry(0.55, 0.55, 0.4, 12).rotateX(Math.PI / 2).translate(wx, 0.55, wz).toNonIndexed())), dark);
    g.add(body, cab, glass, stripe, ladder, wheels);
    // شريط الأضواء
    const bar = [];
    for (const [z, col] of [[0.7, 0xff2020], [-0.7, 0x2a5bff]]) {
      const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: radialSprite(64, 'rgba(255,255,255,1)', 'rgba(255,255,255,0)'),
        color: col, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }));
      s.scale.set(3.2, 3.2, 1); s.position.set(3.9, 3.15, z);
      g.add(s); bar.push(s);
    }
    g.position.copy(V(x, y, 0));
    g.rotation.y = yaw;
    this.group.add(g);
    const phase = rng(this.seed + Math.round(x * 13 + y * 37))() * 2;
    this.anim.push((t) => {
      const on = ((t + phase) * 2.6) % 2 < 1;
      bar[0].material.opacity = on ? 1 : 0.05;
      bar[1].material.opacity = on ? 0.05 : 1;
    });
    return g;
  }

  // ------------------------------------------------------------------ هوامش الأمان (قابلة للإظهار والإخفاء)
  buildMargins() {
    const d = this.data.world.d_safe;
    const lines = [];
    for (const b of this.data.buildings) {
      const x0 = b.x0 - d, x1 = b.x1 + d, y0 = b.y0 - d, y1 = b.y1 + d, z = b.h + d;
      const c = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
      for (let i = 0; i < 4; i++) {
        const [a, bb] = [c[i], c[(i + 1) % 4]];
        for (const zz of [0.2, z]) lines.push(V(a[0], a[1], zz), V(bb[0], bb[1], zz));
        lines.push(V(a[0], a[1], 0.2), V(a[0], a[1], z));
      }
    }
    const g = new THREE.BufferGeometry().setFromPoints(lines);
    this.margins = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: 0x8fd0ff, transparent: true, opacity: 0.28, depthWrite: false }));
    this.margins.visible = false;
    this.margins.name = 'safety_margins';
    this.group.add(this.margins);
  }

  update(t, dt) { for (const f of this.anim) f(t, dt); }
}

// ======================================================================= السماء والبيئة
export function buildSky(scene, renderer, W) {
  const R = W * 6;
  const skyMat = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false, fog: false,
    uniforms: { top: { value: new THREE.Color(0x182b42) }, mid: { value: new THREE.Color(0x364d63) },
      horizon: { value: new THREE.Color(0x72817e) }, glow: { value: new THREE.Color(0x6a6253) },
      uHDR:{value:getVisualAssets().environment||null},uHasHDR:{value:Boolean(getVisualAssets().environment)} },
    vertexShader: 'varying vec3 vW;varying vec2 vUV; void main(){ vW = normalize(position);vUV=uv; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.); }',
    fragmentShader: `uniform vec3 top, mid, horizon, glow;uniform sampler2D uHDR;uniform bool uHasHDR; varying vec3 vW;varying vec2 vUV;
      void main(){ float h = vW.y;
        vec3 c = mix(horizon, mid, smoothstep(0.0, 0.18, h));
        c = mix(c, top, smoothstep(0.18, 0.75, h));
        c += glow * 0.35 * exp(-abs(h) * 22.0);
        if (h < 0.0) c = horizon + glow * 0.35;
        if(uHasHDR)c=mix(c,texture2D(uHDR,vUV).rgb*.55,smoothstep(.015,.18,h)*.8);
        gl_FragColor = vec4(c, 1.0); }`,
  });
  const sky = new THREE.Mesh(new THREE.SphereGeometry(R, 32, 16), skyMat);
  sky.position.set(W / 2, 0, -W / 2);
  sky.name = 'sky';
  scene.add(sky);
  // النجوم
  const rand = rng(99), sp = [];
  for (let i = 0; i < 650; i++) {
    const u = rand() * 2 * Math.PI, v = 0.08 + rand() * 0.92;
    const y = v, r = Math.sqrt(1 - y * y);
    sp.push(W / 2 + Math.cos(u) * r * R * 0.95, y * R * 0.95, -W / 2 + Math.sin(u) * r * R * 0.95);
  }
  const sg = new THREE.BufferGeometry(); sg.setAttribute('position', new THREE.Float32BufferAttribute(sp, 3));
  const stars = new THREE.Points(sg, new THREE.PointsMaterial({ size: 1.05, sizeAttenuation: false, color: 0xabb8c9,
    transparent: true, opacity: 0.12, fog: false, depthWrite: false }));
  scene.add(stars);
  // القمر
  const md = new THREE.Vector3(-0.5, 0.42, -0.75).normalize();
  const assets=getVisualAssets(),map=assets.moon?new THREE.Texture(assets.moon):null;
  if(map){map.colorSpace=THREE.SRGBColorSpace;map.needsUpdate=true;}
  const height=assets.moonHeight?new THREE.Texture(assets.moonHeight):null;if(height)height.needsUpdate=true;
  const moonRadius=R*.0046;
  const moon = new THREE.Mesh(new THREE.SphereGeometry(moonRadius,48,32),new THREE.ShaderMaterial({
    uniforms:{uMap:{value:map},uHeight:{value:height},uTextured:{value:Boolean(map)},uSun:{value:new THREE.Vector3(-.35,.2,1).normalize()}},
    vertexShader:'varying vec2 vUV; varying vec3 vNormal; void main(){vUV=uv;vNormal=normalize(mat3(modelMatrix)*normal);gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
    fragmentShader:`uniform sampler2D uMap,uHeight;uniform bool uTextured;uniform vec3 uSun;varying vec2 vUV;varying vec3 vNormal;
      void main(){vec3 color=uTextured?texture2D(uMap,vUV).rgb:vec3(.6);float relief=texture2D(uHeight,vUV).r;
        float light=.10+.90*max(0.,dot(normalize(vNormal),uSun));gl_FragColor=vec4(color*light*(.92+.14*relief),1.);}`,
    fog:false,depthWrite:true,toneMapped:false,
  }));
  moon.position.set(W / 2 + md.x * R * 0.9, md.y * R * 0.9, -W / 2 + md.z * R * 0.9);
  moon.name='moon_lroc_surface';moon.rotation.y=Math.PI*.1;
  scene.add(moon);
  const halo=new THREE.Sprite(new THREE.SpriteMaterial({map:radialSprite(128,'rgba(188,206,232,.12)','rgba(188,206,232,0)'),transparent:true,depthWrite:false,fog:false,toneMapped:false}));
  halo.position.copy(moon.position);halo.scale.setScalar(moonRadius*7);halo.name='moon_atmospheric_halo';scene.add(halo);
  // بيئة للانعكاسات: السماء نفسها مع شريط توهج دافئ للمدينة
  const pmrem = new THREE.PMREMGenerator(renderer);
  const env = new THREE.Scene();
  const envSky = new THREE.Mesh(new THREE.SphereGeometry(100, 32, 16), skyMat.clone());
  envSky.material.uniforms.glow.value = new THREE.Color(0xc07040);
  env.add(envSky);
  const band = new THREE.Mesh(new THREE.CylinderGeometry(90, 90, 6, 48, 1, true),
    new THREE.MeshBasicMaterial({ color: 0x6a4630, side: THREE.BackSide }));
  band.position.y = 2;
  env.add(band);
  const hdr=getVisualAssets().environment;
  const target=hdr?pmrem.fromEquirectangular(hdr):pmrem.fromScene(env,.02);
  const tex = target.texture;
  scene.environment = tex;
  pmrem.dispose();
  envSky.geometry.dispose();envSky.material.dispose();band.geometry.dispose();band.material.dispose();
  const u = skyMat.uniforms;
  const fogColor = u.horizon.value.clone().add(u.glow.value.clone().multiplyScalar(0.35));
  return { sky, stars, moonDir: md, fogColor,environmentTarget:target };
}
