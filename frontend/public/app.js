// التنقل في الصفحة، والعارضات، ورسوم النتائج المحفوظة، ومساحة إعادة العرض.
// تُحمّل نصوص الواجهة الرئيسية من frontend/public/content/ar.json عبر content.js.
import { Viewer } from '/scene.js?v=viewport-20261018';
import { SegmentLens, initGlassButtons } from '/glass.js?v=viewport-20261018';
import { startOfficialLiquidGlass } from '/official-liquid-glass.js?v=viewport-20261018';
import { t, raw, ready, missingKeys } from '/content.js?v=viewport-20261018';
import { initWorkspace, initStoryCamera, initCaseStudies, initInsights } from '/experience.js?v=viewport-20261018';
import { installSpringSelects } from '/spring-select.js';
import { attachTooltip, controlIcon } from '/easyui.js';
import { convergenceSeries, stepPath, relativeGap, barPercent, duration } from '/chart-data.js';
import { renderHazardDiagram } from '/hazard-diagram.js';
import { deferUntilNear } from '/viewport-loop.js';
import { isStaticSummary, readStaticSummary } from '/static-data.js';
// نموذج GLB الزخرفي اختياري: فشل WebGL يجب ألا يمنع بدء الواجهة أو التنقل.
import('/ambient-drone.js?v=viewport-20261018').catch((error) => {
  console.warn('[ambient-drone] Decorative model unavailable; interface unaffected.', error);
});

await ready;
renderHazardDiagram();

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const COLORS = { GA: '#4DA3FF', PSO: '#FF8A47', ACO: '#2BD99A', DP: '#A47CFF' };
const COLORS_T = { GA: '#87c2ff', PSO: '#ffb583', ACO: '#69e5b5', DP: '#bfa5ff' };  // ألوان مقروءة على واجهة الجرافيت
const ALGS = ['GA', 'PSO', 'ACO', 'DP'];
const AR = Object.fromEntries(ALGS.map((a) => [a, t(`algorithmsMeta.${a}.name`)]));
const api = async (p, o) => {
  if (!o && isStaticSummary(p)) return readStaticSummary(p);
  const r = await fetch(p, o);
  if (!r.ok) throw new Error(`${p}: ${r.status}`);
  return r.json();
};
const fmt = (x, d = 3) => (x === null || x === undefined || !isFinite(x) ? '—' : Number(x).toFixed(d));

/* ── حقائق الواجهة الرئيسية (أخطاء كل ميزة تبقى محلية فيها) ── */
try {
  const runs = await api('/api/table/runs');
  const cities = await api('/api/cities');
  $('#factRuns').textContent = Number(runs.length).toLocaleString('en');
  $('#factCities').textContent = String(3 + (cities.random?.length || 0));
} catch (e) { /* تحتفظ الحقائق بنصوصها المؤقتة، وكل ميزة تبلّغ عن أخطائها */ }

/* ── التقدم والتنقل ── */
const bar = $('#progressBar');
const secs = $$('main section[id]');
let officialTopSelection = null;
let currentTopLink = null;
function activateTopLink(link, instant = false) {
  if (link === currentTopLink && !instant) return;
  currentTopLink = link;
  $$('#topnav a').forEach((a) => {
    a.classList.toggle('active', a === link);
    if (a === link) a.setAttribute('aria-current', 'location');
    else a.removeAttribute('aria-current');
  });
  if (link) officialTopSelection?.moveTo(link, instant);
  else officialTopSelection?.hide();
}
function updateScrollNavigation() {
  const h = document.documentElement;
  bar.style.transform = `scaleX(${h.scrollTop / (h.scrollHeight - h.clientHeight || 1)})`;
  let cur = secs[0]?.id;
  for (const s of secs) if (s.getBoundingClientRect().top < innerHeight * 0.4) cur = s.id;
  activateTopLink($$('#topnav a').find((a) => a.hash === '#' + cur) || null);
  $('#topbar').classList.toggle('scrolled', h.scrollTop > 10);
}
addEventListener('scroll', updateScrollNavigation, { passive: true });
function closeMenu(focus = false) {
  $('#topnav').classList.remove('open');
  $('#menuBtn').setAttribute('aria-expanded', 'false');
  $('#menuBtn').setAttribute('aria-label', t('navigation.menuAria'));
  if (focus) $('#menuBtn').focus();
}
$('#menuBtn').onclick = () => {
  const open = $('#topnav').classList.toggle('open');
  $('#menuBtn').setAttribute('aria-expanded', String(open));
  $('#menuBtn').setAttribute('aria-label', t(open ? 'navigation.closeMenu' : 'navigation.menuAria'));
};
addEventListener('keydown', event => { if (event.key === 'Escape' && $('#topnav').classList.contains('open')) closeMenu(true); });
document.addEventListener('pointerdown', event => { if (!event.target.closest('.topbar-inner')) closeMenu(); });
matchMedia('(min-width:1021px)').addEventListener('change', () => closeMenu());
$$('#topnav a').forEach((a) => a.onclick = () => {
  closeMenu();
  activateTopLink(a);
});
// استعادة الاختيار الصحيح عند التحميل المباشر برابط الفقرة وعند التنقل في المتصفح.
addEventListener('hashchange', () => {
  const link = $$('#topnav a').find((a) => a.hash === location.hash) || null;
  activateTopLink(link);
});
// إبقاء العدسة في موضعها إذا أعيد تخطيط نافذة العرض (ومنه تحميل الخطوط).
addEventListener('resize', () => {
  if (currentTopLink) officialTopSelection?.moveTo(currentTopLink, true);
}, { passive: true });


/* ── إظهار تدريجي (خفيف، وليس في كل مكان) ── */
const io = new IntersectionObserver((es) => es.forEach((e) => e.isIntersecting && e.target.classList.add('in')), { threshold: 0.12 });
$$('.reveal').forEach((el) => io.observe(el));

/* ── الشريط الجانبي ── */
$('#railPrev').onclick = () => $('#algRail').scrollBy({ left: 360, behavior: 'smooth' });
$('#railNext').onclick = () => $('#algRail').scrollBy({ left: -360, behavior: 'smooth' });
$('#railPrev').innerHTML=controlIcon('m9 5 7 7-7 7');
$('#railNext').innerHTML=controlIcon('m15 5-7 7 7 7');
for(const button of [$('#railPrev'),$('#railNext')])attachTooltip(button,button.getAttribute('aria-label'));

/* ══ عدسات اختيار كاسرة (إزاحة SVG محدودة، في طبقة التفاعل فقط) ══ */
const STAGES = ['city', 'towers', 'fires', 'hazard', 'swarm', 'mission'];
const STAGE_META = raw('story.stages') || [];
$('#stageAlt').innerHTML = STAGES.map((s, i) => `<button data-goto="${s}">${STAGE_META[i]?.tag || s}</button>`).join('');
// عدسة المرحلة توفرها المكتبة الرسمية؛ تؤجل حتى تحميل وحدة NPM.
let officialSelection = null;
let currentStageButton = null;
const stageLens = { moveTo(button) { currentStageButton = button; officialSelection?.moveTo(button); } };
const tabsLens = new SegmentLens($('#cityTabs'), { strength: 4, chromatic: 0.1, radius: 999 });
function lensTo(lens, btn) { if (btn) lens.moveTo(btn); }
let glassEnhancementsStarted = false;
function initializeGlassEnhancements() {
  if (glassEnhancementsStarted) return;
  glassEnhancementsStarted = true;
  // استعادة اختيار الترويسة الصحيح حتى لو لم يحدث تمرير أولي.
  updateScrollNavigation();
  lensTo(stageLens, document.querySelector('.stage-alt button.on') || document.querySelector('.stage-alt button'));
  lensTo(tabsLens, document.querySelector('#cityTabs button[aria-selected="true"]'));
  document.querySelectorAll('.btn').forEach((b) => {
    if (!b.querySelector('.btn-sheen')) b.insertAdjacentHTML('afterbegin', '<span class="btn-sheen" aria-hidden="true"></span>');
  });
  initGlassButtons();
  // دمج محرك LiquidGlassEngine الأصلي المثبت من PallavAg للشريطين.
  // هذا التحسين غير المتزامن لا يعطل المحاكاة ولا التنقل أبدًا.
  startOfficialLiquidGlass().then((lenses) => {
    officialSelection = lenses?.stage || null;
    officialTopSelection = lenses?.header || null;
    const selected = currentStageButton || document.querySelector('.stage-alt button.on') || document.querySelector('.stage-alt button');
    officialSelection?.moveTo(selected, true);
    // الترويسة كبسولة مستقلة؛ والرابط النشط كبسولة بصرية متحركة مطابقة،
    // تتشارك محرك S1–S6 الأصلي ونمط مادته.
    const activeLink = $$('#topnav a').find((a) => a.classList.contains('active')) || null;
    if (activeLink) officialTopSelection?.moveTo(activeLink, true);
    else officialTopSelection?.hide();
    currentTopLink = activeLink;
    // إعادة محاذاة الكبسولة المختارة عند اكتمال تحميل الخط أو
    // عند استعادة المتصفح للصفحة. تُحدَّث الهندسة فقط.
    document.fonts?.ready.then(() => {
      requestAnimationFrame(() => {
        updateScrollNavigation();
        if (currentTopLink) officialTopSelection?.moveTo(currentTopLink, true);
      });
    });
  }).catch((error) => {
    console.warn('[liquid-glass] Official package unavailable; accessible CSS fallback in use.', error);
    document.documentElement.dataset.officialLiquidGlass = 'fallback';
  });
}
// يُنتظر فهرس الترجمة عند دخول الوحدة. وقد ينتهي بعد
// window.load (خاصة مع ذاكرة مؤقتة جاهزة أو استجابة JSON بطيئة)، فمستمع
// التحميل العادي لن يعمل وسيغيب زجاج الترويسة.
if (document.readyState === 'complete') initializeGlassEnhancements();
else addEventListener('load', initializeGlassEnhancements, { once: true });
addEventListener('pageshow', (event) => {
  if (event.persisted) {
    requestAnimationFrame(() => {
      updateScrollNavigation();
      if (currentTopLink) officialTopSelection?.moveTo(currentTopLink, true);
    });
  }
});

/* ── قوائم اختيار تُملأ من الفهرس (القيم تبقى معرفات برمجية) ── */
function fillSelect(sel, values, labels) {
  sel.innerHTML = values.map((v, i) => `<option value="${v}">${labels[i]}</option>`).join('');
}
fillSelect($('#labAlg'), ALGS, ALGS.map((a) => t(`algorithmsMeta.${a}.code`)));
$('#labLabel').textContent = t('laboratory.waiting');
for (const id of ['heroT', 'missionClock', 'labClock', 'storyT']) {
  const el = document.getElementById(id);
  if (el) el.textContent = t('mission.clock', { t: '0.0' });
}
function stage(id, state, msg) {
  const el = document.querySelector(`.stage-loading[data-for="${id}"]`);
  if (!el) return;
  if (state === 'ready') el.classList.add('done');
  else { el.classList.remove('done'); if (msg) el.lastChild.textContent = msg; }
  // المشهد الفاشل يجب ألا يبدو كأنه يحمّل إلى الأبد؛ دون تغيير للمراحل السليمة.
  if (el.firstElementChild) el.firstElementChild.style.display = state === 'error' ? 'none' : '';
}
const hero = new Viewer($('#heroCanvas'));
const story = new Viewer($('#storyCanvas'));
const lab = new Viewer($('#labCanvas'));
lab.S.speed = 6;
const workspace = initWorkspace(lab);
installSpringSelects();
let caseStudiesReady = false;
initCaseStudies(workspace).then(() => { caseStudiesReady = true; });
initInsights();

deferUntilNear($('#heroCanvas'), () => hero.load('large', 'ACO').then(({ T }) => {
  hero.setState('city'); hero.S.playing = true;
  hero.onTick = (time) => { $('#heroT').textContent = t('mission.clock', { t: Math.max(0, time).toFixed(1) }); };
  stage('heroCanvas', 'ready');
}).catch((error) => { console.error('[scene] hero', error); stage('heroCanvas', 'error', t('common.sceneError')); }));
deferUntilNear($('#storyCanvas'), () => story.load('large', 'ACO')
  .then(() => { story.setState($('.step.active')?.dataset.state || 'city', true); initStoryCamera(story); stage('storyCanvas', 'ready'); })
  .catch((error) => { console.error('[scene] story', error); stage('storyCanvas', 'error', t('common.sceneError')); }));

/* خطوات القصة ↔ المشهد */
const label = {
  city: t('story.hud.city'), towers: t('story.hud.towers'), fires: t('story.hud.fires'),
  hazard: t('story.hud.hazard'), swarm: t('story.hud.swarm'), mission: t('story.hud.mission'),
};
const stepIO = new IntersectionObserver((es) => {
  for (const e of es) {
    if (!e.isIntersecting) continue;
    const st = e.target.dataset.state;
    $$('.step').forEach((s) => s.classList.toggle('active', s === e.target));
    const segBtn = document.querySelector(`.stage-alt button[data-goto="${st}"]`);
    $$('.stage-alt button').forEach((b) => b.classList.toggle('on', b === segBtn));
    lensTo(stageLens, segBtn);
    story.setState(st);
    $('#storyLabel').textContent = label[st];
    story.S.playing = false;
  }
}, { rootMargin: '-38% 0px -38% 0px' });
$$('.step').forEach((s) => stepIO.observe(s));
$$('.stage-alt button').forEach((b) => b.onclick = () => {
  lensTo(stageLens, b);
  const el = $(`.step[data-state="${b.dataset.goto}"]`);
  el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
});
story.onTick = (time) => { $('#storyT').textContent = t('mission.clock', { t: Math.max(0, time).toFixed(1) }); };

/* ══ النتائج ══ */
let curCity = 'large';
async function drawConv(city) {
  const svg = $('#convChart');
  svg.setAttribute('direction','ltr');
  try {
    const summary = await api(`/api/fleet/${city}`);
    // توافق مع خادم يعمل مسبقًا أثناء تحميل إصدار جديد.
    const data=summary.improvements||Object.fromEntries(Object.entries(summary.histories).map(([alg,histories])=>[alg,histories.map(history=>history.map(point=>[point[1],point[2]]))]));
    if (curCity !== city) return;
    const algs = Object.keys(data).filter((a) => data[a]?.length);
    const med = {}, budget = Math.max(1, ...summary.rows.map(r => r.budget));
    for (const a of algs) {
      const m=convergenceSeries(data[a],budget);
      if (m.length) med[a] = m;
    }
    const all = Object.values(med).flatMap(points => points.map(p => p[1]));
    if (!all.length) { svg.innerHTML = `<text x="20" y="40" fill="#AEBCC7">${t('results.convEmpty')}</text>`; return; }
    const logarithmic = Math.max(...all) / Math.min(...all) > 8;
    $('#convScale').textContent=t(logarithmic?'results.logScale':'results.linearScale');
    const transform = value => logarithmic ? Math.log10(value) : value;
    const ymin = transform(Math.min(...all)), ymax = transform(Math.max(...all));
    const W = 560, H = 300, pad = { l: 68, r: 10, t: 12, b: 26 };
    let s = `<line x1="${pad.l}" y1="${H - pad.b}" x2="${W - pad.r}" y2="${H - pad.b}" stroke="#52606B"/>`;
    for (const g of [0, 0.5, 1]) {
      const v = ymin + (ymax - ymin) * g, y = H - pad.b - g * (H - pad.t - pad.b);
      const tick=logarithmic?10**v:v;
      s += `<text x="${pad.l-8}" y="${y + 4}" text-anchor="end" fill="#AEBCC7" font-size="12">${tick>=10000?tick.toExponential(1):tick.toFixed(2)}</text><line x1="${pad.l}" y1="${y}" x2="${W - pad.r}" y2="${y}" stroke="#34414B"/>`;
    }
    const X = fe => pad.l + fe / budget * (W - pad.l - pad.r);
    const Y = value => H - pad.b - (transform(value) - ymin) / (ymax - ymin || 1) * (H - pad.t - pad.b);
    for (const fe of [0, budget / 2, budget]) s += `<text x="${X(fe)}" y="${H - 5}" text-anchor="${fe === budget ? 'end' : fe === 0 ? 'start' : 'middle'}" fill="#AEBCC7" font-size="12">${fe.toLocaleString('en')} ${t('results.effortUnit')}</text>`;
    for (const a of ['GA', 'PSO', 'ACO', 'DP']) {
      if (!med[a]) continue;
      const path = stepPath(med[a],X,Y);
      s += `<path d="${path}" fill="none" stroke="${COLORS[a]}" stroke-width="2"/>`;
    }
    svg.innerHTML = s;
    $('#convLegend').innerHTML = ['GA', 'PSO', 'ACO', 'DP'].filter((a) => med[a]).map((a) => `<span><i style="background:${COLORS[a]}"></i>${t(`algorithmsMeta.${a}.code`)}</span>`).join('');
  } catch { svg.innerHTML = `<text x="20" y="40" fill="#FF8488">${t('results.convError')}</text>`; }
}
async function drawTables(city) {
  try {
    const summary = await api(`/api/fleet/${city}`), rows = summary.rows;
    if (curCity !== city) return;
    $('#fleetWinner').innerHTML = `<span>${t('fleet.winner')}</span><strong class="ltr" style="color:${COLORS_T[summary.winner] || 'inherit'}">${summary.winner || '—'}</strong><span>${t('fleet.banner', { drones: summary.drones, safe: rows.filter(r => r.valid).length, total: rows.length })}</span>`;
    const mh = raw('results.mainHeaders') || [];
    $('#mainTable').innerHTML = '<tr>' + mh.map((h) => `<th>${h}</th>`).join('') + '</tr>' +
      rows.map((r, i) => `<tr><td style="color:${COLORS_T[r.algorithm]}">${r.algorithm}${i === 0 && r.valid ? ' ♛' : ''}</td><td>${fmt(r.F)}</td><td class="${r.valid ? 'status-safe' : 'status-unsafe'}">${t(r.valid ? 'common.safe' : 'common.unsafe')}</td><td>${r.safe}/${r.runs}</td><td>${r.fe_used.toLocaleString('en')}</td><td>${duration(r.time_s)}${t('units.second')}</td></tr>`).join('');
    const w = (await api('/api/table/wilcoxon')).filter((r) => r.size === city);
    if (curCity !== city) return;
    const wh = raw('results.wilcHeaders') || [];
    $('#wilcTable').innerHTML = '<tr>' + wh.map((h) => `<th>${h}</th>`).join('') + '</tr>' +
      w.map((r) => `<tr><td>${r.first}–${r.second}</td><td>${r.n_nonzero}</td><td>${Number(r.p_holm).toExponential(1)}</td><td>${fmt(r.A12, 2)}</td><td>${r.verdict === 'no significant difference' ? t('results.noDifference') : t('results.better', { alg: r.verdict.split(' ')[0] })}</td></tr>`).join('');
  } catch { $('#fleetWinner').textContent = t('comparison.loadError'); }
}
$$('#cityTabs button').forEach((b) => b.onclick = () => {
  $$('#cityTabs button').forEach((x) => x.setAttribute('aria-selected', x === b));
  lensTo(tabsLens, b);
  curCity = b.dataset.city; drawConv(curCity); drawTables(curCity);
});
drawConv(curCity); drawTables(curCity);

/* ══ المقارنة ══ */
async function drawCompare() {
  const city = $('#cmpCity').value;
  try {
    const summary = await api(`/api/fleet/${city}`), rows = summary.rows;
    if ($('#cmpCity').value !== city) return;
    const dp = rows.find(r => r.algorithm === 'DP')?.F, maxF = Math.max(1, ...rows.map(r => r.F));
    $('#cmpRows').innerHTML = rows.map((r) => {
      const a = r.algorithm, gap = relativeGap(r.F,dp);
      return `<div class="cmp-row"><b style="color:${COLORS_T[a]}" class="ltr">${a}</b>
        <span class="bar"><i style="width:${barPercent(r.F,maxF)}%;background:${COLORS[a]}"></i></span>
        <span class="ltr mono">${t('comparison.valueTpl', { value: fmt(r.F), gap: gap===null?'—':`${gap >= 0 ? '+' : ''}${gap.toFixed(1)}%` })}</span></div>
      <div class="note" style="margin:-4px 0 8px">${t('comparison.rowNote', { name: AR[a], seed: r.seed, status: r.valid ? t('common.safe') : t('common.unsafe'), time: duration(r.time_s) })}</div>`;
    }).join('');
    const tc = rows;
    const mx = Math.max(...tc.map((r) => r.time_s), 1);
    $('#costBars').innerHTML = tc.map((r) => `<div class="cb"><b class="ltr" style="color:${COLORS_T[r.algorithm]}">${r.algorithm}</b>
      <span class="track"><i style="width:${barPercent(r.time_s,mx)}%;background:${COLORS[r.algorithm]}"></i></span>
      <span class="ltr mono">${duration(r.time_s)}${t('units.second')}</span></div>`).join('');
  } catch { $('#cmpRows').innerHTML = `<p class="note">${t('comparison.loadError')}</p>`; }
}
$('#cmpCity').onchange = drawCompare; drawCompare();

/* ══ التحقق ══ */
(async () => {
  try {
    const c = await api('/api/table/checks');
    $('#checksBox').innerHTML = `<div><dt>${t('validation.checkRuns')}</dt><dd class="ltr">${c.runs}</dd></div>
      <div><dt>${t('validation.checkUnsafe')}</dt><dd class="ltr">${c.unsafe_by_validator}</dd></div>
      <div><dt>${t('validation.checkAgree')}</dt><dd class="ltr">${c.validator_disagrees_with_F}</dd></div>`;
    const cases = await api('/api/special-cases');
    const sh = raw('validation.specialHeaders') || [];
    $('#specialTable').innerHTML = '<colgroup><col><col><col><col><col></colgroup><thead><tr>' +
      sh.map((h) => `<th scope="col">${h}</th>`).join('') + '</tr></thead><tbody>' + cases.map((cs) =>
      `<tr><th scope="row">${t(`caseCopy.${cs.case}.title`)}</th>` + ['GA', 'PSO', 'ACO', 'DP'].map((a) => {
        const r = cs.algorithms[a], accepted = cs.expect === 'feasible' ? r.safe === r.runs : r.correct === r.runs;
        const verdict=cs.expect==='feasible'?t('cases.safeCount',{count:r.safe,total:r.runs}):t('cases.rejectedCount',{count:r.correct,total:r.runs});
        return `<td class="${accepted ? 'status-safe' : 'status-unsafe'}"><span class="case-score ltr">${r.best_safe_F == null ? '—' : fmt(r.best_safe_F)}</span><span class="case-outcome">${verdict}</span></td>`;
      }).join('') + '</tr>').join('') + '</tbody>';
  } catch { /* صامت */ }
})();

/* ══ الحساسية ══ */
(async () => {
  try {
    const rows = await api('/api/table/sensitivity');
    const by = {};
    for (const r of rows) (by[`${r.algorithm}:${r.parameter}`] ||= { a: r.algorithm, p: r.parameter, v: 0 }).v = Math.max(by[`${r.algorithm}:${r.parameter}`].v, Number(r.spread_pct) || 0);
    const top = Object.values(by).sort((x, y) => y.v - x.v).slice(0, 12);
    const mx = Math.max(...top.map((t) => t.v), 1);
    const labels = raw('parameters');
    $('#sensBars').innerHTML = top.map((item) => `<div class="sens-row"><span><bdi>${item.a}</bdi>: ${labels[item.p] || item.p}</span><span class="track"><i style="width:${(item.v / mx * 100).toFixed(1)}%;background:${COLORS[item.a]}"></i></span><span class="ltr mono">${item.v.toFixed(1)}%</span></div>`).join('');
  } catch { /* صامت */ }
})();

// الواجهة والمشهد الظاهر أولًا جاهزان. أما المدن خارج الشاشة فتُبنى
// عند أول اقتراب منها بدل حجز العوالم الثلاثة الكبيرة عند البدء.
const readiness = setInterval(() => {
  if (document.hidden) return;
  const visibleReady = [hero, story, lab].every(viewer => {
    const r = viewer.c.getBoundingClientRect();
    return r.bottom <= 0 || r.top >= innerHeight || Boolean(viewer.world && viewer._rendered > 0);
  });
  if (visibleReady && caseStudiesReady && $$('#winnerOverview .winner-card').length === 3) {
    clearInterval(readiness); document.body.dataset.appReady = 'true';
    $$('[id$="Clock"], #heroT, #storyT, .workspace-metrics .ltr, .stat-strip dt').forEach(el => el.setAttribute('data-ui-number', ''));
  }
}, 100);
