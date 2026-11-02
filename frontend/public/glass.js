// الزجاج السائل في الواجهة، ولا يُرشَّح نص الواجهة أبدًا.
// SegmentLens يطبق مرشح SVG على العنصر `.seg-lens` نفسه، والأزرار فوقه لا تتأثر.
// StaticLens يطبق المرشح على طبقة `.gbtn-bg` خلف نص الزر، فيبقى النص حادًا.
// خريطة الإزاحة تُولَّد عند تغير شكل العدسة فقط، والحركة بالتحويلات دون إعادة رسم.
const SVGNS = 'http://www.w3.org/2000/svg';
const REDUCED_T = matchMedia('(prefers-reduced-transparency: reduce)').matches;
const FORCED_C = matchMedia('(forced-colors: active)').matches;
const REDUCED_M = matchMedia('(prefers-reduced-motion: reduce)').matches;

function sdRoundRect(x, y, w, h, r) {
  const qx = Math.abs(x - w / 2) - (w / 2 - r), qy = Math.abs(y - h / 2) - (h / 2 - r);
  const ax = Math.max(qx, 0), ay = Math.max(qy, 0);
  return Math.hypot(ax, ay) + Math.min(Math.max(qx, qy), 0) - r;
}

/** صورة PNG لخريطة الإزاحة محلية للعدسة: R/G = متجه الانحناء (128 محايد). */
export function buildLensMap(w, h, r, o = {}) {
  w = Math.max(8, Math.round(w)); h = Math.max(8, Math.round(h));
  const { strength = 1.0, depth = 12, curvature = 0.65, splay = 1.0 } = o;
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const ctx = c.getContext('2d');
  const img = ctx.createImageData(w, h), d = img.data;
  const cx = w / 2, cy = h / 2, maxR = Math.hypot(cx, cy) || 1;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = (y * w + x) * 4;
    const sd = sdRoundRect(x + 0.5, y + 0.5, w, h, Math.min(r, Math.min(w, h) / 2));
    if (sd > 1) { d[i] = 128; d[i + 1] = 128; d[i + 2] = 0; d[i + 3] = 0; continue; }
    const dd = Math.max(0, -sd);
    const ex = (x + 0.5 - cx) / maxR, ey = (y + 0.5 - cy) / maxR;
    const band = Math.max(0, 1 - dd / depth);
    const rad = Math.min(1, Math.hypot(x + 0.5 - cx, y + 0.5 - cy) / maxR);
    const dome = Math.sin(Math.PI * Math.min(1, rad * 1.15)) * curvature;
    const m = band * band * 1.4 * splay + dome * 0.5;
    const feather = Math.min(1, Math.max(0, 1 - sd));
    d[i] = 128 + 100 * m * ex * strength * feather;
    d[i + 1] = 128 + 100 * m * ey * strength * feather;
    d[i + 2] = 0;
    d[i + 3] = 255 * feather;
  }
  ctx.putImageData(img, 0, 0);
  return c.toDataURL('image/png');
}

let uid = 0;

/**
 * خريطة إزاحة للحواف فقط: الانكسار محصور ضمن `depth` بكسل
 * من الحافة (باتجاه العمود الخارجي)، والداخل محايد تمامًا.
 * تُستخدم للكبسولات التي تحتوي نصًا، فيبقى النص مطابقًا بكسلًا ببكسل.
 */
export function buildEdgeMap(w, h, r, o = {}) {
  w = Math.max(8, Math.round(w)); h = Math.max(8, Math.round(h));
  const { strength = 1.0, depth = 14 } = o;
  const rr = Math.min(r, w / 2, h / 2);
  const sdAt = (x, y) => sdRoundRect(x, y, w, h, rr);
  const c = document.createElement('canvas');
  c.width = w; c.height = h;
  const ctx = c.getContext('2d');
  const img = ctx.createImageData(w, h), d = img.data;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = (y * w + x) * 4;
    const sd = sdAt(x + 0.5, y + 0.5);
    if (sd > 1) { d[i] = 128; d[i + 1] = 128; d[i + 2] = 0; d[i + 3] = 0; continue; }
    const dd = Math.max(0, -sd);
    const band = Math.max(0, 1 - dd / depth);
    // العمود الخارجي من تدرج دالة المسافة SDF (فروق مركزية)
    const gx = sdAt(x + 1.5, y + 0.5) - sdAt(x - 0.5, y + 0.5);
    const gy = sdAt(x + 0.5, y + 1.5) - sdAt(x + 0.5, y - 0.5);
    const len = Math.hypot(gx, gy) || 1;
    const m = band * band * strength;   // للخارج، مثل العدسات القبابية
    d[i] = 128 + 100 * m * (gx / len);
    d[i + 1] = 128 + 100 * m * (gy / len);
    d[i + 2] = 0;
    d[i + 3] = 255;
  }
  ctx.putImageData(img, 0, 0);
  return c.toDataURL('image/png');
}

/** مرشح SVG واحد: صورة النمط + إزاحة لونية بثلاث قنوات + دمج القنوات. */
function buildFilter(id, o, pw, ph) {
  const f = document.createElementNS(SVGNS, 'filter');
  f.setAttribute('id', id);
  f.setAttribute('filterUnits', 'userSpaceOnUse');   // آمن على iOS (دون انزياح objectBoundingBox)
  const s = o.strength, ca = o.chromatic;
  const img = document.createElementNS(SVGNS, 'feImage');
  img.setAttribute('preserveAspectRatio', 'none');
  img.setAttribute('result', 'lensmap');
  img.setAttribute('href', buildLensMap(pw, ph, o.radius, o));
  const mk = (scale, res) => {
    const e = document.createElementNS(SVGNS, 'feDisplacementMap');
    e.setAttribute('in', 'SourceGraphic'); e.setAttribute('in2', 'lensmap');
    e.setAttribute('scale', scale.toFixed(2));
    e.setAttribute('xChannelSelector', 'R'); e.setAttribute('yChannelSelector', 'G');
    e.setAttribute('result', res);
    return e;
  };
  const chan = (src, keep, res) => {
    const keepM = { r: '1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0',
      g: '0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0',
      b: '0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0' }[keep];
    const e = document.createElementNS(SVGNS, 'feColorMatrix');
    e.setAttribute('in', src); e.setAttribute('type', 'matrix');
    e.setAttribute('values', keepM); e.setAttribute('result', res);
    return e;
  };
  const add = (a, b, res) => {
    const e = document.createElementNS(SVGNS, 'feComposite');
    e.setAttribute('in', a); e.setAttribute('in2', b);
    e.setAttribute('operator', 'arithmetic');
    e.setAttribute('k1', '0'); e.setAttribute('k2', '1'); e.setAttribute('k3', '1'); e.setAttribute('k4', '0');
    e.setAttribute('result', res);
    return e;
  };
  f.append(img, mk(s * (1 - ca), 'dR'), mk(s, 'dG'), mk(s * (1 + ca), 'dB'),
    chan('dR', 'r', 'cR'), chan('dG', 'g', 'cG'), chan('dB', 'b', 'cB'),
    add('cR', 'cG', 'cRG'), add('cRG', 'cB', 'cRGB'));
  return { filter: f, mapImg: img };
}

function mountFilter(id, filter) {
  const svg = document.createElementNS(SVGNS, 'svg');
  svg.setAttribute('width', '0'); svg.setAttribute('height', '0');
  svg.style.position = 'absolute';
  svg.append(filter);
  document.body.append(svg);
  return svg;
}

function setRegion(filter, img, w, h) {
  for (const [k, v] of [['x', 0], ['y', 0], ['width', w], ['height', h]]) {
    filter.setAttribute(k, v);
    img.setAttribute(k, v);
  }
}

/** إزاحة حقيقية لأي خلفية في Chromium/Edge. وتبقى طبقة الزجاج المصنفر
 * في Safari/Firefox، لأن مُركِّبهما لا يشغّل url() الخاص بـ SVG
 * داخل backdrop-filter. لا تُحدَّث خرائط SVG إلا عند تغير حجم الكبسولة.
 * النصوص والأزرار عناصر شقيقة فوق السطح البصري ولا تُرشَّح أبدًا. */
const BACKDROP_SVG_SUPPORTED = /Chrome\/|Chromium\/|Edg\//.test(navigator.userAgent) && !/Firefox\/|OPR\//.test(navigator.userAgent);
function mountBackdropFilter(id, width, height, options) {
  // خط التشتت ثلاثي القنوات نفسه المستخدم في عدسة DOM الحية المرجعية،
  // لكنه مطبق على خلفية فعلية لا على نصوص الواجهة.
  const shape = {
    strength: options.strength || 12,
    chromatic: options.chromatic ?? 0.085,
    radius: options.radius || 999,
    depth: options.depth || 14,
  };
  const { filter, mapImg } = buildFilter(id, shape, width, height);
  filter.setAttribute('color-interpolation-filters', 'sRGB');
  mountFilter(id, filter);
  setRegion(filter, mapImg, width, height);
  mapImg.setAttribute('href', buildEdgeMap(width, height,
    Math.min(height / 2, shape.radius), { strength: 1, depth: shape.depth }));
  return { filter, img: mapImg };
}

export class BackdropLens {
  constructor(host, options = {}) {
    if (!host) return;
    this.host = host;
    this.options = options;
    const surface = document.createElement('span');
    surface.className = 'liquid-backdrop';
    surface.setAttribute('aria-hidden', 'true');
    host.prepend(surface);
    this.surface = surface;
    if (FORCED_C || REDUCED_T || !BACKDROP_SVG_SUPPORTED) return;
    try {
      const id = `lgBackdrop${++uid}`;
      this.fx = mountBackdropFilter(id, 64, 40, options);
      surface.style.setProperty('--optical-backdrop', `url("#${id}")`);
      surface.classList.add('liquid-backdrop--refractive');
      let last = '';
      const measure = () => {
        const r = surface.getBoundingClientRect();
        if (!r.width || !r.height) return;
        const w = Math.round(r.width), h = Math.round(r.height), key = `${w}x${h}`;
        if (key === last) return;
        last = key;
        setRegion(this.fx.filter, this.fx.img, w, h);
        this.fx.img.setAttribute('href', buildEdgeMap(w, h, Math.min(h / 2, options.radius || 999), { strength: 1, depth: options.depth || 14 }));
      };
      measure();
      new ResizeObserver(() => requestAnimationFrame(measure)).observe(host);
    } catch (error) {
      surface.classList.remove('liquid-backdrop--refractive');
      surface.style.removeProperty('--optical-backdrop');
      console.warn('Liquid-glass backdrop refraction unavailable', error);
    }
  }
}

/** عدسة كاسرة منزلقة فوق عنصر تحكم مقسم؛ العدسة وحدها تُرشَّح. */
export class SegmentLens {
  constructor(control, opts = {}) {
    this.el = control;
    this.o = { strength: 4, chromatic: 0.1, depth: 12, curvature: 0.65, splay: 1, radius: 999, ...opts };
    this.id = `lg${++uid}`;
    this.active = null;
    this._key = '';
    if (REDUCED_T || FORCED_C) { control.classList.add('lens-off'); return; }
    try {
      const lens = document.createElement('div');
      lens.className = 'seg-lens';
      lens.setAttribute('aria-hidden', 'true');
      this.el.prepend(lens);
      this.lens = lens;
      const { filter, mapImg } = buildFilter(this.id, this.o, 32, 32);
      mountFilter(this.id, filter);
      this.filter = filter; this.mapImg = mapImg;
      if (BACKDROP_SVG_SUPPORTED) {
        lens.style.setProperty('--segment-backdrop', `url("#${this.id}")`);
        lens.classList.add('seg-lens--refractive');
      }
    } catch { control.classList.add('lens-off'); return; }
    new ResizeObserver(() => this.active && this.moveTo(this.active, true)).observe(control);
  }

  /** تحريك العدسة إلى زر؛ وفوريًا عند طلب تقليل الحركة. */
  moveTo(btn, instant = REDUCED_M) {
    if (!this.filter || !btn) return;
    this.active = btn;
    const host = this.el.getBoundingClientRect();
    const r = btn.getBoundingClientRect();
    const x = Math.round(r.left - host.left), y = Math.round(r.top - host.top);
    const w = Math.round(r.width), h = Math.round(r.height);
    if (w < 8 || h < 8) return;
    const key = `${w}x${h}`;
    if (key !== this._key) {   // تغير الشكل -> نمط جديد؛ والتحريك المجرد يتجاوز هذا
      this._key = key;
      setRegion(this.filter, this.mapImg, w, h);
      this.mapImg.setAttribute('href', buildLensMap(w, h, this.o.radius, this.o));
      this.lens.style.width = `${w}px`;
      this.lens.style.height = `${h}px`;
    }
    if (instant) {
      this.lens.style.transition = 'none';
      this.lens.style.transform = `translate(${x}px,${y}px)`;
      requestAnimationFrame(() => { this.lens.style.transition = ''; });
    } else {
      this.lens.style.transform = `translate(${x}px,${y}px)`;
    }
  }
}

/**
 * زر زجاج كاسر ثابت: طبقة الخلفية `.gbtn-bg` وحدها
 * تُرشَّح، ونص `.gbtn-fg` فوقها لا يُمس أبدًا. والخريطة
 * لا يعاد توليدها إلا عند تغير الحجم (مع تأخير)، والضغطات لا تمسها.
 */
export class StaticLens {
  constructor(target, opts = {}) {
    this.el = target;
    this.o = { strength: 3, chromatic: 0.12, depth: 8, curvature: 0.7, splay: 1, radius: 999, edge: false, ...opts };
    this.id = `lg${++uid}`;
    this._queued = false;
    this._key = '';
    if (REDUCED_T || FORCED_C) return;
    try {
      const { filter, mapImg } = buildFilter(this.id, this.o, 32, 32);
      mountFilter(this.id, filter);
      this.filter = filter; this.mapImg = mapImg;
      target.style.filter = `url(#${this.id})`;
      this.measure();
      const host = target.closest('.topbar-inner, button, a') || target;
      new ResizeObserver(() => {
        if (this._queued) return;
        this._queued = true;
        requestAnimationFrame(() => { this._queued = false; this.measure(); });
      }).observe(host);
    } catch { target.style.filter = ''; }
  }

  measure() {
    if (!this.filter) return;
    const host = this.el.closest('.topbar-inner, button, a') || this.el;
    const r = host.getBoundingClientRect();
    const w = Math.max(8, Math.round(r.width)), h = Math.max(8, Math.round(r.height));
    const key = `${w}x${h}`;
    if (key === this._key) return;
    this._key = key;
    setRegion(this.filter, this.mapImg, w, h);
    const rad = Math.min(this.o.radius, h / 2);
    this.mapImg.setAttribute('href', this.o.edge
      ? buildEdgeMap(w, h, rad, this.o)
      : buildLensMap(w, h, rad, this.o));
  }
}

/** تقسيم الأزرار الرئيسية المعتادة إلى طبقة خلفية مرشحة وطبقة نص حادة.
 * تُستثنى أزرار الواجهة الرئيسية لأنها تستخدم LiquidGlassEngine الرسمي مباشرة،
 * ووضع .gbtn-bg القديمة فوقها يحجب السطح البصري الأصلي. */
export function initGlassButtons(selector = '.btn.primary') {
  if (REDUCED_T || FORCED_C) return [];
  return [...document.querySelectorAll(selector)]
    .filter((el) => !el.closest('.seg-control') && !el.closest('.hero-cta') && !el.classList.contains('official-cta-btn') && !el.querySelector('.gbtn-bg'))
    .map((btn) => {
      const bg = document.createElement('span');
      bg.className = 'gbtn-bg';
      bg.setAttribute('aria-hidden', 'true');
      const fg = document.createElement('span');
      fg.className = 'gbtn-fg';
      while (btn.firstChild) fg.append(btn.firstChild);
      btn.prepend(bg);
      btn.append(fg);
      return new StaticLens(bg);
    });
}
