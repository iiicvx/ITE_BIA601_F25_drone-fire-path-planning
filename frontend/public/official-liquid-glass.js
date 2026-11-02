/**
 * دمج رسمي (لا إعادة إنشاء) لـ PallavAg/liquid-glass-web-react@0.1.1.
 * https://github.com/PallavAg/liquid-glass-web-react
 *
 * يستخدم الموقع محرك LiquidGlassEngine من حزمة NPM الرسمية عبر jsDelivr، دون React ودون خطوة بناء.
 * يكسر المحرك طبقة DOM المرسومة داخل `filtered` فقط، لا البكسلات الحية خلفها.
 * وإذا تعذر الوصول إلى CDN يظهر بديل غير كاسر.
 */
const OFFICIAL_CDN = 'https://cdn.jsdelivr.net/npm/liquid-glass-web-react@0.1.1/+esm';

const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const reducedTransparency = matchMedia('(prefers-reduced-transparency: reduce)');
const forcedColors = matchMedia('(forced-colors: active)');
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');

function createLayers(host, kind) {
  // لا يُرشَّح نص الواجهة أو الترويسة أو الأزرار أبدًا.
  host.classList.add('official-liquid-host');
  const filtered = document.createElement('div');
  filtered.className = `official-liquid-source official-liquid-${kind}`;
  filtered.setAttribute('aria-hidden', 'true');
  const defsHost = document.createElement('div');
  defsHost.className = 'official-liquid-defs';
  defsHost.setAttribute('aria-hidden', 'true');
  const chrome = document.createElement('div');
  chrome.className = 'official-liquid-chrome';
  chrome.setAttribute('aria-hidden', 'true');
  host.prepend(filtered);
  host.insertBefore(chrome, filtered.nextSibling);
  host.append(defsHost);
  return { container: host, filtered, defsHost, shadow: chrome };
}

function mountCapsule(LiquidGlassEngine, host, kind) {
  host.classList.add(`official-liquid-${kind}-host`);
  const dom = createLayers(host, kind);
  const getSize = () => {
    const r = host.getBoundingClientRect();
    return { width: Math.max(12, r.width), height: Math.max(12, r.height) };
  };
  const engine = new LiquidGlassEngine(dom, {
    ...getSize(), radius: 'auto', strength: 0.21,
    chromaticAberration: 0.15, curvature: 0.83,
    depth: 14, glow: 0.2, edgeHighlight: 0.34,
    specular: 0.85, specularAngle: 43, quality: 512,
  });
  engine.setPosition(0.5, 0.5);
  const observer = new ResizeObserver(() => {
    engine.setOptions(getSize());
    engine.setPosition(0.5, 0.5);
  });
  observer.observe(host);
  host.dataset.glassEngine = 'liquid-glass-web-react@0.1.1';
  return { engine, destroy() { observer.disconnect(); engine.destroy(); } };
}

function mountMovingSelection(LiquidGlassEngine, host, activeSelector = 'button.on', firstSelector = 'button') {
  const dom = createLayers(host, 'selection');
  const initial = host.querySelector(activeSelector) || host.querySelector(firstSelector);
  const measured = initial?.getBoundingClientRect();
  // روابط التنقل في الجوال قد تكون display:none؛ فلا تُهيأ أبدًا خريطة SVG بعرض 0px.
  const size = measured?.width > 1 && measured?.height > 1 ? measured : { width: 56, height: 44 };
  const engine = new LiquidGlassEngine(dom, {
    width: size.width, height: size.height,
    radius: 'auto', strength: 0.27,
    chromaticAberration: 0.2, curvature: 0.86,
    depth: 9, glow: 0.2, edgeHighlight: 0.38,
    specular: 0.9, specularAngle: 38, quality: 384,
  });
  let current = { x: 0.5, y: 0.5 };
  let active = null;
  let animation = 0;
  let updateScheduled = 0;
  let lastFrameTime = 0;
  function clipToCurrent() {
    const c = dom.filtered.getBoundingClientRect();
    const o = engine.getOptions();
    const left = Math.max(0, current.x * c.width - o.width / 2);
    const top = Math.max(0, current.y * c.height - o.height / 2);
    const right = Math.max(0, c.width - left - o.width);
    const bottom = Math.max(0, c.height - top - o.height);
    dom.filtered.style.clipPath = `inset(${top}px ${right}px ${bottom}px ${left}px round 999px)`;
  }

  function positionFor(button) {
    const c = dom.filtered.getBoundingClientRect();
    const b = button.getBoundingClientRect();
    return {
      x: clamp((b.left + b.width / 2 - c.left) / Math.max(1, c.width), 0, 1),
      y: clamp((b.top + b.height / 2 - c.top) / Math.max(1, c.height), 0, 1),
      width: b.width, height: b.height,
    };
  }
  const stop = () => { if (animation) cancelAnimationFrame(animation); animation = 0; };
  function moveTo(button, instant = false) {
    if (!button) return;
    // روابط الجوال تقع خارج الكبسولة، وهندسة قائمتها المنسدلة يجب ألا
    // تغير حجم كبسولة الترويسة البصرية أو موضعها أبدًا.
    if (host.classList.contains('topbar-inner') && matchMedia('(max-width:1020px)').matches) {
      active = button; stop(); host.classList.add('official-selection-hidden'); return;
    }
    host.classList.remove('official-selection-hidden');
    active = button;
    const target = positionFor(button);
    if (Math.abs(target.width - engine.getOptions().width) > 0.5 ||
        Math.abs(target.height - engine.getOptions().height) > 0.5) {
      engine.setOptions({ width: target.width, height: target.height });
    }
    stop();
    if (instant || reducedMotion.matches || !lastFrameTime) {
      current = { x: target.x, y: target.y };
      engine.setPosition(current.x, current.y);
      clipToCurrent();
      lastFrameTime = performance.now();
      return;
    }
    const from = { ...current };
    const start = performance.now();
    const duration = 340;
    const tick = (now) => {
      const p = clamp((now - start) / duration, 0, 1);
      const ease = 1 - Math.pow(1 - p, 4);
      current.x = from.x + (target.x - from.x) * ease;
      current.y = from.y + (target.y - from.y) * ease;
      engine.setPosition(current.x, current.y); // المسار السريع الرسمي: دون إعادة توليد الخريطة
      clipToCurrent();
      if (p < 1) animation = requestAnimationFrame(tick);
      else animation = 0;
    };
    animation = requestAnimationFrame(tick);
  }
  const observer = new ResizeObserver(() => {
    if (!active || updateScheduled) return;
    updateScheduled = requestAnimationFrame(() => {
      updateScheduled = 0;
      moveTo(active, true);
    });
  });
  observer.observe(host);
  host.dataset.selectionEngine = 'liquid-glass-web-react@0.1.1';
  if (initial && measured?.width > 1 && measured?.height > 1) moveTo(initial, true);
  return {
    moveTo,
    hide() {
      active = null;
      stop();
      host.classList.add('official-selection-hidden');
    },
    destroy() {
      stop();
      if (updateScheduled) cancelAnimationFrame(updateScheduled);
      observer.disconnect();
      engine.destroy();
    },
  };
}

/**
 * بصريات البطاقات تستخدم محرك LiquidGlassEngine نفسه المستخدم في شريطي التنقل.
 * تُحمَّل عند الحاجة لأن خرائط إزاحة البطاقات أكبر، ويبقى النص والعناصر التفاعلية حادة.
 * لا تغيير على مكوني التنقل ولا على إعدادات عدستيهما.
 */
function mountGlassCard(LiquidGlassEngine, card, kind) {
  card.classList.add('official-glass-card');
  const dom = createLayers(card, `card-${kind}`);
  const size = () => {
    const r = card.getBoundingClientRect();
    return { width: Math.max(12, r.width), height: Math.max(12, r.height) };
  };
  let alive = true;
  let scheduled = 0;
  const engine = new LiquidGlassEngine(dom, {
    ...size(),
    radius: 22,
    // مطابقة عائلة زجاج التنقل، مع انكسار أهدأ فوق النص المقروء.
    strength: kind === 'story' ? 0.15 : 0.17,
    chromaticAberration: 0.12,
    curvature: 0.83,
    depth: 13,
    glow: 0.19,
    edgeHighlight: 0.35,
    specular: 0.85,
    specularAngle: 43,
    quality: 256,
  });
  engine.setPosition(0.5, 0.5);
  const resize = new ResizeObserver(() => {
    if (scheduled || !alive) return;
    scheduled = requestAnimationFrame(() => {
      scheduled = 0;
      if (!alive) return;
      engine.setOptions(size());
      engine.setPosition(0.5, 0.5);
    });
  });
  resize.observe(card);
  card.dataset.glassEngine = 'liquid-glass-web-react@0.1.1';
  return {
    destroy() {
      alive = false;
      resize.disconnect();
      if (scheduled) cancelAnimationFrame(scheduled);
      engine.destroy();
    },
  };
}

function mountExplanationCards(LiquidGlassEngine) {
  const targets = [
    ...document.querySelectorAll('.story-steps .step-card'),
    ...document.querySelectorAll('#algRail .alg-card'),
    ...document.querySelectorAll('#challenge .ledger, #challenge .panel, .chapter .panel'),
    ...document.querySelectorAll('#compare .compare-side, #laboratory .sensitivity, #mission .mission-controls, #lab .mission-controls'),
  ];
  if (!targets.length) return { destroy() {} };
  const mounted = new Map();
  let observer;
  function attach(card) {
    if (mounted.has(card)) return;
    try {
      const kind = card.matches('.step-card') ? 'story' : 'algorithm';
      mounted.set(card, mountGlassCard(LiquidGlassEngine, card, kind));
    } catch (err) {
      // البطاقة الطويلة المنفردة يجب ألا تعطل أيًا من شريطي التنقل العاملين.
      console.warn('[liquid-glass] Card lens could not initialize:', err);
      card.classList.remove('official-glass-card', 'official-liquid-host');
      card.querySelectorAll(':scope > .official-liquid-source, :scope > .official-liquid-chrome, :scope > .official-liquid-defs').forEach((el) => el.remove());
    }
  }
  if ('IntersectionObserver' in window) {
    observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        attach(entry.target);
        observer.unobserve(entry.target);
      }
    }, { rootMargin: '200px 0px', threshold: 0.01 });
    for (const card of targets) observer.observe(card);
  } else {
    for (const card of targets) attach(card);
  }
  return {
    destroy() {
      observer?.disconnect();
      for (const item of mounted.values()) item.destroy();
      mounted.clear();
    },
  };
}

function mountHeroButtons(LiquidGlassEngine) {
  const targets = [
    { el: document.querySelector('.hero-cta .btn.official-cta-btn'), kind: 'cta-primary' },
    { el: document.querySelector('#missionPlay'), kind: 'cta-primary' },
    { el: document.querySelector('#labRun'), kind: 'cta-primary' },
    { el: document.querySelector('.hero-cta .btn.ghost'), kind: 'cta-secondary' },
  ].filter((x) => x.el);
  if (!targets.length) return { destroy() {} };
  const mounted = targets.map(({ el, kind }) => mountCapsule(LiquidGlassEngine, el, kind));
  return { destroy() { mounted.reverse().forEach((x) => x.destroy()); } };
}

/** تهيئة الشريطين المطلوبين بالمحرك الأصلي دون تعديل. */
export async function startOfficialLiquidGlass() {
  if (reducedTransparency.matches || forcedColors.matches) return null;
  // تُستورد حزمة NPM الرسمية بدل نقل حسابات SVG الخاصة بها.
  const { LiquidGlassEngine } = await import(OFFICIAL_CDN);
  if (typeof LiquidGlassEngine !== 'function') throw new Error('LiquidGlassEngine export unavailable');
  const header = document.querySelector('.topbar-inner');
  const stage = document.querySelector('#stageAlt');
  if (!header || !stage) throw new Error('Glass navigation hosts not found');
  const mounted = [];
  try {
    mounted.push(mountCapsule(LiquidGlassEngine, header, 'header'));
    mounted.push(mountCapsule(LiquidGlassEngine, stage, 'stage'));
    // الحفاظ على اختيار S1–S6 تمامًا كما كان يعمل.
    const selection = mountMovingSelection(LiquidGlassEngine, stage);
    mounted.push(selection);
    // إعادة استخدام المحرك الرسمي نفسه وإعدادات العدسة والهندسة والحركة نفسها
    // للرابط النشط داخل التنقل الرئيسي. لا كبسولة CSS مقلدة.
    const headerSelection = mountMovingSelection(
      LiquidGlassEngine, header, '.topnav a.active', '.topnav a'
    );
    mounted.push(headerSelection);
    if (!header.querySelector('.topnav a.active')) headerSelection.hide();
    document.documentElement.dataset.officialLiquidGlass = 'ready';
    // الترويسة وشريط S1–S6 المعتمدان يبقيان دون أي تغيير.
    // إضافة العارض البصري الرسمي نفسه إلى بطاقات الشرح والقصة فقط.
    try {
      mounted.push(mountExplanationCards(LiquidGlassEngine));
    } catch (error) {
      console.warn('[liquid-glass] Card enhancement unavailable; navigation unaffected.', error);
    }
    try {
      mounted.push(mountHeroButtons(LiquidGlassEngine));
    } catch (error) {
      console.warn('[liquid-glass] Hero CTA glass unavailable; navigation unaffected.', error);
    }
    return { stage: selection, header: headerSelection };
  } catch (e) {
    mounted.reverse().forEach((x) => x.destroy());
    throw e;
  }
}
