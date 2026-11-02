// المختبر وبطاقات حالات الحافة: إعادة عرض الخطط المحفوظة لمدن السرب وحالات الحافة العشر.
// أدوات العرض لا تغيّر المسار ولا نموذج الحركة.
import { t, raw } from './content.js?v=viewport-20261018';
import { liquidToggle, attachTooltip, controlIcon } from './easyui.js';
import { duration } from './chart-data.js';
import { syncSelect } from './spring-select.js';
import { deferUntilNear } from './viewport-loop.js';
import { isStaticSummary, readStaticSummary } from './static-data.js';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const ALGS = ['GA', 'PSO', 'ACO', 'DP'];
const COLORS = { GA: '#87c2ff', PSO: '#ffd2b0', ACO: '#69e5b5', DP: '#bfa5ff' };
const number = (value, digits = 2) => value === null || value === undefined || !Number.isFinite(Number(value)) ? '—' : Number(value).toFixed(digits);
const escape = (value) => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const request = async (url, options) => {
  if (!options && isStaticSummary(url)) return readStaticSummary(url);
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === 'string' ? body.detail : `${response.status}`);
  }
  return response.json();
};
const sizeLabel = (city) => t(`workspace.${city.replace('fleet_', '')}`);
const withUnit = (value, digits, unit) => { const text = number(value, digits); return text === '—' ? text : text + unit; };
const isSafe = (result) => Boolean(result?.validator?.valid && result?.feasible);
// بطاقات حالات الحافة كما يقدمها /api/special-cases: التوقع المثبت للحالة وأفضل خطة آمنة.
const CASES = new Map();

// سبب الرفض بالأرقام من تقرير المدقق، مع حدود القيود من بيانات المدينة.
function rejectionReasons(result, city) {
  const v = result.validator || {}, checks = v.checks || {}, out = [];
  const drone = city?.drone || {}, world = city?.world || {};
  if (checks.endpoints === false) out.push(t('workspace.why.endpoints'));
  if (checks.bounds === false) out.push(t('workspace.why.bounds'));
  if (checks.towers === false) out.push(t('workspace.why.towers', { d: number(v.min_margin_linf_m), need: number(world.d_safe, 0) }));
  if (checks.fire_core === false) out.push(t('workspace.why.fire_core', { h: number(v.max_hazard, 2), tau: number(city?.hazard?.tau_core, 2) }));
  if (checks.separation === false) out.push(t('workspace.why.separation', { d: number(v.min_separation_m), need: number(drone.d_sep, 0) }));
  if (checks.battery === false) {
    const need = Math.max(...(v.drones || []).map(d => d.energy_kj ?? 0));
    out.push(t('workspace.why.battery', { e: number(need, 1), max: number(drone.battery_kj * drone.battery_usable, 1) }));
  }
  return out.length ? out.join('؛ ') : t('workspace.checks.unknown');
}

// ثلاثة أحكام مختلفة: خطة آمنة، أو محاولة غير آمنة في حالة لها حل، أو حالة مستحيلة بالتصميم.
function verdictText(result, city) {
  if (isSafe(result)) return t('workspace.verified');
  const why = rejectionReasons(result, city), entry = CASES.get(result.scenario);
  if (entry?.expect === 'infeasible') return t('workspace.verdictImpossible', { why });
  return t(entry ? 'workspace.verdictUnsafe' : 'workspace.verdictRejected', { why });
}

function loading(id, state, message) {
  const el = $(`.stage-loading[data-for="${id}"]`);
  el.classList.toggle('done', state === 'ready');
  el.firstElementChild.style.display = state === 'error' ? 'none' : '';
  el.lastElementChild.textContent = message || t('common.loadingScene');
}

function cameraTools(container, viewer, { story = false, onRestart } = {}) {
  const modes = story ? ['follow', 'cockpit', 'orbit'] : ['orbit', 'follow', 'cockpit', 'fleet'];
  container.classList.add('glass-b', 'viewer-tools');
  container.innerHTML = `<div class="camera-modes" role="group" data-ui-actions aria-label="${t('camera.label')}">
    ${modes.map(mode => `<button type="button" data-camera="${mode}" aria-pressed="false">${t(`camera.${mode}`)}</button>`).join('')}</div>
    <label class="drone-picker"><span>${t('camera.drone')}</span><select aria-label="${t('camera.drone')}"></select></label>
    <div class="zoom-tools" role="group" data-ui-actions aria-label="${t('camera.zoom')}"><button type="button" data-zoom="in" aria-label="${t('camera.zoomIn')}" title="${t('camera.zoomIn')}">${controlIcon('M5 12h14M12 5v14')}</button><button type="button" data-zoom="out" aria-label="${t('camera.zoomOut')}" title="${t('camera.zoomOut')}">${controlIcon('M5 12h14')}</button><button type="button" data-reset aria-label="${t('camera.reset')}" title="${t('camera.reset')}">${controlIcon('M4 5v6h6M4 11a8 8 0 1 1 2 7')}</button></div>
    <button type="button" data-restart title="${t('camera.restartHint')}">${t('camera.restart')}</button>`;
  const select = $('select', container);
  function refresh() {
    select.innerHTML = `<option value="all">${t('camera.all')}</option>` +
      (viewer.world?.swarms[0]?.drones || []).map(d => `<option value="${d.k}">${t('camera.droneN', { n: d.k + 1 })}</option>`).join('');
    sync();
  }
  function sync() {
    select.value = viewer.S.camera === 'fleet' ? 'all' : String(viewer.S.selected);
    syncSelect(select);
    $$('[data-camera]', container).forEach(b => b.setAttribute('aria-pressed', String(b.dataset.camera === viewer.S.camera)));
    viewer.c.parentElement.classList.toggle('is-cockpit', viewer.S.camera === 'cockpit');
    viewer.c.parentElement.classList.toggle('is-fleet', viewer.S.camera === 'fleet');
    viewer.invalidateLayout();
  }
  $$('[data-camera]', container).forEach(b => b.onclick = () => { viewer.setCamera(b.dataset.camera); sync(); });
  select.onchange = () => { viewer.selectDrone(select.value); sync(); };
  $('[data-zoom="in"]', container).onclick = () => viewer.zoom(1 / 1.22);
  $('[data-zoom="out"]', container).onclick = () => viewer.zoom(1.22);
  $('[data-reset]', container).onclick = () => { viewer.resetCamera(); sync(); };
  $('[data-restart]', container).onclick = () => { viewer.restart(); onRestart?.(); };
  $$('.zoom-tools button',container).forEach(button=>attachTooltip(button,button.getAttribute('aria-label')));
  return { refresh, sync };
}

export function initStoryCamera(viewer) {
  // القصة تتحكم في تمرير الصفحة، حتى عندما يكون المؤشر فوق لوحتها.
  // أزرار +/- الصريحة ما زالت تقرّب، أما العجلة وإيماءات اللمس الرأسية فتقرأ القصة.
  viewer.scrollDriven = true; viewer.controls.enableZoom = false;
  viewer.c.style.touchAction = 'pan-y';
  const tools = cameraTools($('#storyCameraTools'), viewer, { story: true });
  viewer.setCamera('follow'); viewer.S.playing = false; tools.refresh();
  function seek() {
    if (!viewer.visible || document.hidden) return;
    const rect = $('.story-steps').getBoundingClientRect();
    const progress = Math.max(0, Math.min(1, (innerHeight * .5 - rect.top) / Math.max(1, rect.height - innerHeight * .5)));
    viewer.setTime(-4 + progress * (viewer.T + 4));
  }
  // تحديث هذه القيمة رخيص؛ فننفذه داخل حدث التمرير نفسه حتى لا يترك
  // إطار WebGL مزدحم ساعة المهمة القابلة للعكس متأخرة إطارًا.
  addEventListener('scroll', seek, { passive: true });
  addEventListener('resize', seek, { passive: true });
  viewer.onVisible = seek;
  seek();
}

export function initWorkspace(viewer) {
  const tools = cameraTools($('#labCameraTools'), viewer, { onRestart: () => {
    $('#labEvolution').value = $('#labEvolution').max;
    $('#evolutionLabel').textContent = t('workspace.finalPlan');
  } });
  let current = null, currentCity = null, loadVersion = 0, csvURL = null, busy = false, autoPick = false;
  const switches = new Map();
  const keys = ['lights', 'rotors', 'spotlight', 'dimensions', 'paths', 'danger', 'margins', 'realScale'];
  const optionHelp = raw('optionHelp');
  for (const key of keys) {
    const control = liquidToggle(key, t(`options.${key}`), viewer.S[key], value => { viewer.S[key] = value; });
    const help = optionHelp[key];
    if (help) attachTooltip(control.element, help);
    switches.set(key, control); $('#labSceneOptions').append(control.element);
  }
  function setBusy(value) {
    busy = value;
    for (const el of $$('#labWorkspace .lab-config select, #labRun')) el.disabled = value;
    $('#labWorkspace').setAttribute('aria-busy', String(value));
  }
  function metric(label, value, cls = '') { return `<div><dt>${label}</dt><dd class="${cls}">${value}</dd></div>`; }
  function telemetry(result, city) {
    const rep = result.report, v = result.validator, safe = isSafe(result);
    // كلفة الخطة المرفوضة تتضمن العقوبة، فتُذكر مع ملاحظة حتى لا تُقرأ كلفة طيران.
    const cost = safe ? number(result.best_f, 4) : `${number(result.best_f, 2)}<small class="metric-note" dir="rtl">${t('workspace.penalized')}</small>`;
    $('#labTele').innerHTML = metric(t('laboratory.teleF'), cost, 'ltr') +
      metric(t('workspace.validator'), t(safe ? 'common.safe' : 'common.unsafe'), safe ? 'status-safe' : 'status-unsafe') +
      metric(t('laboratory.teleTime'), withUnit(rep.mission_time_s, 1, t('units.second')), 'ltr') +
      metric(t('laboratory.teleClear'), withUnit(rep.min_clearance_m, 2, t('units.metre')), 'ltr') +
      metric(t('mission.teleSep'), withUnit(rep.min_separation_m, 2, t('units.metre')), 'ltr') +
      metric(t('workspace.computation'), result.time_s===null?'—':`${duration(result.time_s)}${t('units.second')}`, 'ltr');
    $('#labProblems').textContent = verdictText(result, city);
    $('#labProblems').classList.toggle('status-unsafe', !safe);
    const headers = raw('workspace.droneHeaders');
    $('#droneTable').innerHTML = `<thead><tr>${headers.map(h => `<th>${h}</th>`).join('')}</tr></thead><tbody>` + rep.drones.map(d =>
      `<tr><td class="ltr">D${d.k + 1}</td><td class="ltr">${number(d.length_m, 1)}</td><td class="ltr">${number(d.time_s, 1)}</td><td class="ltr">${number(d.energy_kj)}</td><td class="ltr">${number(d.battery_used_pct)}</td><td class="ltr">${number(v.drones?.find(row=>row.k===d.k)?.max_hazard??d.max_hazard, 3)}</td><td class="ltr">${number(d.clearance_m)}</td></tr>`).join('') + '</tbody>';
    if (csvURL) URL.revokeObjectURL(csvURL);
    const lines = ['drone,point,x_m,y_m,z_m'];
    result.paths.forEach((path, k) => path.forEach((p, i) => lines.push([k + 1, i, ...p].join(','))));
    csvURL = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' }));
    $('#missionCsv').href = csvURL;
    $('#missionCsv').download = `${result.algorithm}_${result.scenario}_s${result.seed}.csv`;
    const count = result.snapshots?.length || 0;
    $('#labEvolution').max = count; $('#labEvolution').value = count; $('#labEvolution').disabled = !count;
    $('#evolutionLabel').textContent = t(count ? 'workspace.finalPlan' : 'workspace.noEvolution');
  }
  // الخطة المرفوضة لا تُعرض تلقائيًا كرحلة: تظهر المدينة والهدف وسبب الرفض،
  // ويبقى المسار المحفوظ متاحًا للفحص بزر المعاينة.
  function setGate(on) {
    $('#labStage').classList.toggle('is-gated', on);
    $('#labGate').hidden = !on;
    for (const swarm of viewer.world?.swarms || []) swarm.setVisible(!on);
    $('#missionPlay').disabled = on; $('#missionScrub').disabled = on;
    if (!on || !current) return;
    if (viewer.S.camera !== 'orbit') { viewer.setCamera('orbit'); tools.sync(); }
    viewer.S.playing = false;
    const entry = CASES.get(current.scenario), best = entry?.default_alg;
    $('#labGateTitle').textContent = entry && !best ? t('workspace.gateImpossible') : t('workspace.gateUnsafe', { alg: current.algorithm });
    $('#labGateWhy').textContent = verdictText(current, currentCity);
    const other = $('#labGateBest');
    other.hidden = !best || best === current.algorithm;
    if (best) {
      other.textContent = t('workspace.gateBest', { alg: best });
      other.onclick = () => { $('#labAlg').value = best; syncSelect($('#labAlg')); autoPick = true; loadSaved(); };
    }
  }
  async function display(result, payload, version, auto) {
    if (version !== loadVersion) return;
    await viewer.showPayload(payload);
    if (version !== loadVersion) return;
    current = result; currentCity = payload.city; viewer.setState('mission', true); viewer.orbit = false;
    const safe = isSafe(result);
    viewer.S.playing = safe && !matchMedia('(prefers-reduced-motion: reduce)').matches;
    tools.refresh();
    for (const key of keys) switches.get(key).set(viewer.S[key], false);
    telemetry(result, payload.city);
    setGate(!safe);
    const city = result.scenario.startsWith('special_') ? t(`caseCopy.${result.scenario.slice(8)}.title`) : sizeLabel(result.scenario);
    const hud = t('mission.hudSeed', { alg: result.algorithm, city, seed: result.seed });
    $('#labLabel').textContent = safe ? hud : `${t('workspace.diagnostic')} · ${hud}`;
    $('#labLabel').classList.toggle('status-unsafe', !safe);
    const entry = CASES.get(result.scenario);
    $('#labStatus').textContent = entry && !entry.default_alg ? t('workspace.noSafeCase', { alg: result.algorithm })
      : auto && safe ? t('workspace.autoBest', { alg: result.algorithm }) : t('workspace.loaded', { alg: result.algorithm });
    $('#labFacts').innerHTML = metric(t('workspace.droneCount'), result.paths.length) +
      metric(t('workspace.evaluations'), result.fe_used == null ? '—' : result.fe_used.toLocaleString('en')) +
      metric(t('laboratory.seedLabel'), result.seed);
    loading('labCanvas', 'ready');
  }
  // عند فتح حالة حافة تُختار افتراضيًا خوارزمية أفضل خطة آمنة، ويُذكر اسمها في سطر الحالة.
  function pickDefault() {
    const best = CASES.get($('#labCity').value)?.default_alg;
    autoPick = Boolean(best);
    if (best) { $('#labAlg').value = best; syncSelect($('#labAlg')); }
  }
  async function loadSaved() {
    if (busy) return;
    const version = ++loadVersion, city = $('#labCity').value, alg = $('#labAlg').value, auto = autoPick;
    const endpoint = city.startsWith('special_') ? `/api/special/${city}/${alg}` : `/api/fleet/${city}/${alg}`;
    setBusy(true); loading('labCanvas', 'loading'); $('#labStatus').textContent = t('workspace.loading');
    try {
      const [result, payload] = await Promise.all([request(endpoint), request(endpoint + '/scene')]);
      await display(result, payload, version, auto);
    } catch (error) {
      $('#labStatus').textContent = t('common.runLoadError');
      loading('labCanvas', 'error', t('common.runLoadError'));
      console.error('[workspace]', error);
    } finally { setBusy(false); }
  }
  $('#labRun').onclick = () => loadSaved();
  $('#labCity').onchange = () => { pickDefault(); loadSaved(); };
  $('#labAlg').onchange = () => { autoPick = false; loadSaved(); };
  $('#labPreview').onclick = () => { setGate(false); viewer.restart(); };
  $('#labSpeed').onchange = e => { viewer.S.speed = Number(e.target.value); };
  $('#missionPlay').onclick = () => { viewer.showSnapshot(null); $('#labEvolution').value = $('#labEvolution').max; $('#evolutionLabel').textContent = t('workspace.finalPlan'); viewer.play(); };
  $('#missionScrub').oninput = e => {
    viewer.showSnapshot(null); $('#labEvolution').value = $('#labEvolution').max;
    viewer.setTime(-4 + (Number(e.target.value) + 40) / 1040 * (viewer.T + 4));
  };
  $('#labEvolution').oninput = e => {
    const i = Number(e.target.value), snapshots = current?.snapshots || [];
    viewer.showSnapshot(i >= snapshots.length ? null : i);
    const snap = snapshots[i];
    $('#evolutionLabel').textContent = snap ? t('workspace.snapshot', { fe: snap.fe, f: number(snap.best_f, 4) }) : t('workspace.finalPlan');
  };
  const stage = $('#labStage');
  $('#labFullscreen').onclick = async () => {
    if (document.fullscreenElement) await document.exitFullscreen();
    else if (stage.requestFullscreen) await stage.requestFullscreen().catch(() => stage.classList.toggle('expanded'));
    else stage.classList.toggle('expanded');
    viewer.resize();
  };
  stage.onkeydown = event => {
    if (['SELECT', 'INPUT', 'BUTTON'].includes(event.target.tagName)) return;
    if (event.key === ' ') { event.preventDefault(); if (!$('#labGate').hidden) return; viewer.play(); }
    if (['+', '='].includes(event.key)) { event.preventDefault(); viewer.zoom(1 / 1.2); }
    if (event.key === '-') { event.preventDefault(); viewer.zoom(1.2); }
    if (event.key.toLowerCase() === 'r') { viewer.resetCamera(); tools.sync(); }
    if (event.key === 'Escape') stage.classList.remove('expanded');
  };
  viewer.onTick = (time, playing) => {
    $('#labClock').textContent = t('mission.clock', { t: Math.max(0, time).toFixed(1) });
    $('#missionClock').textContent = `${Math.max(0,time+4).toFixed(1)} / ${(viewer.T+4).toFixed(1)}${t('units.second')}`;
    $('#missionScrub').value = Math.round((time + 4) / (viewer.T + 4) * 1040 - 40);
    $('#missionPlay .hero-cta-label').textContent = t(playing ? 'mission.pause' : time >= viewer.T - .05 ? 'mission.replay' : 'mission.play');
    const sw = viewer.world?.swarms[0], drone = sw?.drones[viewer.S.selected];
    if (!drone) return;
    const data = sw.telemetry(drone, time, viewer.world.fires);
    $('#flightReadout').innerHTML = `<span class="readout-title">D${drone.k + 1}<span>${escape(data.status)}</span></span><dl>` +
      metric(t('workspace.altitude'), `${number(data.alt, 1)}${t('units.metre')}`, 'ltr') +
      metric(t('workspace.velocity'), `${number(data.speed, 1)} ${t('workspace.speedUnit')}`, 'ltr') +
      // لا تُعرض نسبة سالبة: محاولة تتجاوز الطاقة المتاحة تظهر 0% مع تنبيه.
      (data.battery < 0 ? metric(t('workspace.battery'), `0% ${t('workspace.batteryOut')}`, 'status-unsafe')
        : metric(t('workspace.battery'), `${number(data.battery, 1)}%`, 'ltr')) + '</dl>';
  };
  deferUntilNear($('#labWorkspace'), () => { if (!current && !busy) loadSaved(); });
  return { setCases(cases) { for (const entry of cases) CASES.set(entry.name, entry); },
    async openCase(name) {
    if (busy) return;
    $('#labCity').value = name; syncSelect($('#labCity')); pickDefault();
    $('#lab').scrollIntoView({ behavior: 'smooth', block: 'start' });
    await loadSaved();
  } };
}

export async function initCaseStudies(workspace) {
  try {
    const cases = await request('/api/special-cases');
    workspace.setCases(cases);
    const group = document.createElement('optgroup'); group.label = t('cases.title');
    for (const entry of cases) {
      const option = document.createElement('option'); option.value = entry.name; option.textContent = t(`caseCopy.${entry.case}.title`); group.append(option);
    }
    $('#labCity').append(group);
    $('#specialCases').innerHTML = cases.map((entry, i) => {
      const expected = entry.expect === 'feasible', best = entry.default_alg;
      const bestLine = best ? `${t('cases.bestSafe', { alg: best })} · <span class="ltr">F ${number(entry.algorithms[best].best_safe_F, 4)}</span>`
        : t(expected ? 'cases.noSafe' : 'cases.noSafeExpected');
      return `<details class="case-card"><summary><span class="case-number ltr">${String(i + 1).padStart(2, '0')}</span><span>${t(`caseCopy.${entry.case}.title`)}</span><span class="case-expect">${t(expected ? 'cases.feasible' : 'cases.impossible')}</span></summary>
        <div class="case-body"><p>${t(`caseCopy.${entry.case}.body`)}</p><div class="case-verdicts">${ALGS.map(a => {
          const r = entry.algorithms[a], accepted = expected ? r.safe === r.runs : r.correct === r.runs;
          return `<span class="${accepted ? 'status-safe' : 'status-unsafe'}"><b style="color:${COLORS[a]}">${a}</b> ${t(expected ? 'cases.safeCount' : 'cases.rejectedCount', { count: expected ? r.safe : r.correct, total: r.runs })}</span>`;
        }).join('')}</div><p class="case-best${best || !expected ? '' : ' status-unsafe'}">${bestLine}</p><button type="button" class="btn ghost compact" data-case="${entry.name}">${t('cases.try')}</button></div></details>`;
    }).join('');
    $$('[data-case]').forEach(button => button.onclick = () => workspace.openCase(button.dataset.case));
  } catch { $('#specialCases').textContent = t('cases.error'); }
}

export async function initInsights() {
  try {
    const sizes = ['small', 'medium', 'large'];
    const [fleets, checks, main, random] = await Promise.all([
      Promise.all(sizes.map(size => request(`/api/fleet/${size}`))), request('/api/table/checks'), request('/api/table/main'), request('/api/table/random'),
    ]);
    $('#winnerOverview').innerHTML = fleets.map((summary, i) => {
      const winner = summary.rows.find(r => r.algorithm === summary.winner);
      return `<article class="panel winner-card"><p class="kicker">${sizeLabel(sizes[i])}</p><strong class="winner-code ltr" style="color:${COLORS[summary.winner] || '#c4d2dc'}">${summary.winner || '—'}</strong>
        <p>${t('fleet.bestSafe')} <b class="ltr">F ${number(winner?.F, 4)}</b></p><div class="winner-statuses">${summary.rows.map(r => `<span class="${r.valid ? 'status-safe' : 'status-unsafe'}"><b class="ltr">${r.algorithm}</b> ${r.valid ? '✓' : '✗'}</span>`).join('')}</div><p class="note">${t('fleet.singleRun')}</p></article>`;
    }).join('');
    const gaMain = main.filter(r => r.algorithm === 'GA'), gaRandom = random.filter(r => r.algorithm === 'GA');
    const mainTotal = gaMain.reduce((s, r) => s + r.runs, 0), mainSafe = gaMain.reduce((s, r) => s + Math.round(r.success_rate * r.runs), 0);
    const rndTotal = gaRandom.reduce((s, r) => s + r.cities, 0), rndSafe = gaRandom.reduce((s, r) => s + r.safe, 0);
    const cards = raw('insights.cards');
    const values = ['10 m → 5 m', `${mainSafe + rndSafe}/${mainTotal + rndTotal}`, `${checks.runs - checks.validator_disagrees_with_F}/${checks.runs}`, 'C1–C5'];
    $('#insightCards').innerHTML = cards.map((card, i) => `<article class="panel insight-card"><span class="insight-number ltr">0${i + 1}</span><p class="insight-metric ltr">${values[i]}</p><h3>${card.title}</h3><p>${card.body}</p><small>${card.source}</small></article>`).join('');
  } catch { $('#insightCards').textContent = t('comparison.loadError'); }
}
