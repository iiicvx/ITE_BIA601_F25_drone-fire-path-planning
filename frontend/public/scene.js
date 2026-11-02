// عارض المشهد ثلاثي الأبعاد، ويستخدم وحدات city وfire وswarm.
// ما يظهر في كل لحظة يُحسب من زمن المهمة، فيمكن تقديم الرحلة وإرجاعها.
import * as THREE from '/scene/vendor/three/three.module.js';
import { OrbitControls } from '/scene/vendor/three/examples/jsm/controls/OrbitControls.js';
import { EffectComposer } from '/scene/vendor/three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from '/scene/vendor/three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from '/scene/vendor/three/examples/jsm/postprocessing/UnrealBloomPass.js';
import { OutputPass } from '/scene/vendor/three/examples/jsm/postprocessing/OutputPass.js';
import { City, buildSky } from '/scene/js/city.js?v=viewport-20261018';
import { Fires } from '/scene/js/fire.js';
import { Swarm, loadDrone,PATH_STYLE } from '/scene/js/swarm.js';
import { V, textSprite, clamp } from '/scene/js/util.js';
import { loadVisualAssets } from '/scene/js/visual-assets.js';
import { fleetBounds, fitDistance, chooseFleetDirection, turnFleetDirection } from '/fleet-camera.js';
import { ViewportLoop } from '/viewport-loop.js';

const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
const COARSE = matchMedia('(pointer: coarse)').matches;
const LOW_POWER = COARSE || navigator.connection?.saveData || (navigator.deviceMemory || 8) <= 4;
// الظلال تحسين لسطح المكتب فقط: خريطة PCFSoft واحدة محدودة بدقة 1024px من
// ضوء القمر الاتجاهي. الأبراج مفعّل لها castShadow مسبقًا، والأرض تستقبل الظل.
const SHADOWS = !REDUCED && !LOW_POWER;
let droneReady = null, droneRadius = 2.5;
function ensureDrone() {
  if (!droneReady) droneReady = loadDrone().then(model => {
    droneRadius = new THREE.Box3().setFromObject(model).getBoundingSphere(new THREE.Sphere()).radius;
    return model;
  });
  return droneReady;
}
window.__viewers = window.__viewers || [];

function disposeGroup(g) {
  const textures = new Set(), materials = new Set(), geometries = new Set();
  g.traverse((o) => {
    if (o.geometry) geometries.add(o.geometry);
    const ms = Array.isArray(o.material) ? o.material : o.material ? [o.material] : [];
    for (const m of ms) {
      materials.add(m);
      const owned=[...Object.values(m),...Object.values(m.userData||{}),...Object.values(m.uniforms||{}).map(uniform=>uniform.value)];
      for (const value of owned) if (value?.isTexture&&!value.userData?.sharedVisualAsset) textures.add(value);
    }
  });
  for (const t of textures) t.dispose();
  for (const m of materials) m.dispose();
  for (const g of geometries) g.dispose();
}

function buildDimensions(scene, city) {
  const group = new THREE.Group(), W = city.world.W, Z = city.world.z_max;
  group.name = 'world_dimensions';
  const points = [V(0, 0, 1), V(W, 0, 1), V(0, 0, 1), V(0, W, 1), V(0, 0, 1), V(0, 0, Z)];
  group.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(points),
    new THREE.LineBasicMaterial({ color: 0xc4d4df, transparent: true, opacity: .65 })));
  for (const [text, position] of [[`X: ${W} m`, V(W / 2, 0, 5)], [`Y: ${W} m`, V(0, W / 2, 5)], [`Z: ${Z} m`, V(0, 0, Z + 5)]]) {
    const label = textSprite(text, '#d4e1eb'); label.position.copy(position); label.scale.set(.06, .03, 1); group.add(label);
  }
  group.visible = false; scene.add(group); return group;
}

/**
 * حلقات الإقلاع (S) ومجسمات نقطة الإطلاق (G) الثمانية الأوجه بلون كل تشغيل.
 * توضع بدقة على نهايتي المهمة؛ ولا تُمس خطوط المسارات.
 */
function buildEndpoints(scene, city, runs) {
  const group = new THREE.Group();
  group.name = 'endpoints';
  const ringGeo = new THREE.RingGeometry(3.4, 4.2, 40).rotateX(-Math.PI / 2);
  const gemGeo = new THREE.OctahedronGeometry(2.2);
  runs.forEach((r) => {
     const col = new THREE.Color(PATH_STYLE.core);
    city.missions.forEach((m) => {
      const ring = new THREE.Mesh(ringGeo, new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.55, depthWrite: false, toneMapped: false }));
      ring.position.copy(V(m.S[0], m.S[1], 0.25));
      const gem = new THREE.Mesh(gemGeo, new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.9, toneMapped: false }));
      gem.position.copy(V(m.G[0], m.G[1], m.G[2]));
      group.add(ring, gem);
    });
  });
  // مدن حالات الحافة صغيرة وقد تخلو من الحرائق، فتُسمّى نقطتا الإقلاع والهدف ليظهر الهدف بوضوح.
  if (city.name?.startsWith('special_')) for (const m of city.missions) {
    for (const [text, p] of [['S', m.S], ['G', m.G]]) {
      const label = textSprite(text, '#e9dcff');
      label.scale.set(0.045, 0.0225, 1);
      label.position.copy(V(p[0], p[1], p[2] + 9));
      group.add(label);
    }
  }
  scene.add(group);
  return { group };
}

export class Viewer {
  constructor(canvas) {
    this.c = canvas;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'default' });
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.04;
    this.renderer.info.autoReset=false;
    this.maxPR = Math.min(devicePixelRatio || 1, LOW_POWER ? 1 : 1.25);
    this.pixelBudget = LOW_POWER ? 900000 : 1300000;
    this._scaleLimit = this.maxPR; this._budgetPR = this.maxPR;
    this.renderer.setPixelRatio(this.maxPR);
    if (SHADOWS) {
      this.renderer.shadowMap.enabled = true;
      this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      this.renderer.shadowMap.autoUpdate = false;
    }
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x05070c);
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.3, 30000);
    this.camera.layers.enable(1);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.zoomSpeed = 0.55;
    this.controls.maxPolarAngle = Math.PI * 0.495;
    const target=new THREE.WebGLRenderTarget(64,64,{type:THREE.HalfFloatType});
    if(this.renderer.capabilities.isWebGL2)target.samples=Math.min(LOW_POWER?0:2,this.renderer.capabilities.maxSamples);
    this.composer = new EffectComposer(this.renderer,target);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.24, 0.26, 1.15);
    this.composer.addPass(this.bloom);
    this.composer.addPass(new OutputPass());
    this.scene.add(new THREE.HemisphereLight(0xb9cddd, 0x727958, 1.5));
    this.moon = new THREE.DirectionalLight(0xd4e2f3, 1.8);
    this.moon.castShadow = SHADOWS;
    if (SHADOWS) {
      this.moon.shadow.mapSize.set(1024, 1024);
      this.moon.shadow.bias = -0.00012;
      this.moon.shadow.normalBias=.12;
      this.moon.shadow.camera.near = 10;
    }
    this.scene.add(this.moon, new THREE.AmbientLight(0x78899d, 0.18));
    this.S = { t: -4, playing: !REDUCED, speed: 5, danger: false, margins: false, labels: true, paths: true,
      lights: true, rotors: true, spotlight: false, dimensions: false, realScale: false, camera: 'orbit', selected: 0 };
    this.world = null; this.T = 60;
    this.camGoal = null; this.lookGoal = null;
    this.time = 0; this._updates = 0; this._rendered = 0; this._resizeCount = 0; this._resizePending = true;
    this._ema = 16; this._slow = 0;   // حساب نسبة البكسل التكيفية
    this._frames = 0; this._fpsT = performance.now(); this.fps = 0;
    this.followDistance = 16; this.fleetZoom = 1; this.singleCamera = 'follow';
    this.fleetFocus = new THREE.Vector3(); this.fleetDirection = null; this._fleetViewportCache = null;
    this.cameraSnap = true; this.snapshot = null; this._loadId = 0;
    this.ray = new THREE.Raycaster();
    this.cameraHit = new THREE.Vector3(); this._shadowT = -Infinity; this._shadowUpdates = 0;
    this.spot = new THREE.SpotLight(0xdcecff, 0, 180, Math.PI / 7, .6, 1.5);
    this.scene.add(this.spot, this.spot.target);
    this.controls.addEventListener('start', () => { this.orbit = false; this.camGoal = null; });
    canvas.addEventListener('wheel', (e) => {
      if (this.scrollDriven || this.S.camera === 'orbit' || !this.world) return;
      e.preventDefault();
      const delta = Math.sign(e.deltaY) * Math.min(Math.abs(e.deltaY), 100);
      const factor = Math.pow(1.002, delta);
      this.zoom(factor);
    }, { passive: false });
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement || canvas);
    // الإبطال فورًا عند تغير حجم نافذة العرض أيضًا: قد يصل إشعار ResizeObserver
    // بعد دورة الحركة التالية، فيبقى إطار كاميرا واحد قديمًا.
    addEventListener('resize', () => this.resize(), { passive: true });
    window.visualViewport?.addEventListener('resize', () => this.resize(), { passive: true });
    addEventListener('scroll', () => { if (this.visible && this.S.camera === 'fleet') this.invalidateLayout(); }, { passive: true });
    this.loop = new ViewportLoop(canvas, { frame: (dt, now) => this.frame(dt, now), ready: () => Boolean(this.world), maxFPS: canvas.id === 'heroCanvas' ? 20 : 30,
      onResume: () => {
        this._fpsT = performance.now(); this._frames = 0; this._ema = 1000 / this.loop.maxFPS; this._slow = 0; this._lastTick = 0;
        this.invalidateLayout(); this.onVisible?.();
      } });
    window.__viewers.push(this);
  }

  // الإبقاء على سطح الفحص والإيقاف المؤقت الموجود الذي يستخدمه فحص المتصفح.
  get visible() { return this.loop?.visible || false; }
  set visible(value) { this.loop?.setVisible(value); }

  /** إحصاءات الإطارات المقيسة للفحص (متوسط متحرك لمعدل الإطارات + عدادات العارض). */
  info() {
    const i = this.renderer.info;
    return { fps: this.fps>0?+this.fps.toFixed(1):null, calls: i.render.calls, tris: i.render.triangles,
      pr: this.renderer.getPixelRatio(), shadows: SHADOWS, scheduler: this.loop.info(),
      updates: this._updates, rendered: this._rendered, resizes: this._resizeCount, pixelBudget: this.pixelBudget, shadowUpdates: this._shadowUpdates };
  }

  resize() {
    this._fleetViewportCache = null;
    this._resizePending = true; this.loop?.invalidate();
  }

  applyResize() {
    const r = this.c.getBoundingClientRect();
    const w = Math.max(2, r.width || this.c.clientWidth), h = Math.max(2, r.height || this.c.clientHeight || 400);
    // الحفاظ على مقياس مخفض صراحة أو تكيفي، مع استعادة تخفيضات ميزانية البكسل
    // عندما تعود نافذة عرض كبيرة أو بملء الشاشة صغيرة مرة أخرى.
    if (Math.abs(this.renderer.getPixelRatio() - this._budgetPR) > .01) this._scaleLimit = Math.min(this.maxPR, this.renderer.getPixelRatio());
    const pr = Math.min(this._scaleLimit, Math.sqrt(this.pixelBudget / (w * h)));
    const key = `${w}:${h}:${pr}`;
    this._resizePending = false;
    // الخطة الجديدة تنشئ مواد LineMaterial جديدة حتى لو لم يتغير حجم اللوحة.
    // ودقتها الافتراضية 1x1 تحول الآثار بعرض بكسل إلى شعاع ضخم
    // بحجم الشاشة؛ فتجب مزامنتها دائمًا قبل الخروج المبكر الخاص بتغيير حجم GPU.
    if (this.world) for (const sw of this.world.swarms) sw.setResolution(w, h);
    if (key === this._sizeKey) return;
    this._sizeKey = key; this._resizeCount++;
    this._budgetPR = pr;
    if (this.renderer.getPixelRatio() !== pr) this.renderer.setPixelRatio(pr);
    this.renderer.setSize(w, h, false);
    if (this.composer.getPixelRatio?.() !== pr) this.composer.setPixelRatio(pr);
    this.composer.setSize(w, h);
    this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
    this.cameraSnap = true;
  }

  async load(cityName, alg, seed, fleet = true) {
    const id = ++this._loadId;
    if (fleet && ['small', 'medium', 'large'].includes(cityName)) {
      const response = await fetch(`/api/fleet/${cityName}/${alg}/scene` + (Number.isInteger(seed) ? `?seed=${seed}` : ''));
      if (!response.ok) throw new Error(`Scene: ${response.status}`);
      const payload = await response.json();
      if (id !== this._loadId) return null;
      return this.showPayload(payload);
    }
    const url = `/api/scene/${alg}/${cityName}` + (seed !== undefined && seed !== null && seed !== '' ? `?seed=${seed}` : '');
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Scene: ${response.status}`);
    const payload = await response.json();
    if (id !== this._loadId) return null;
    return this.showPayload(payload);
  }

  /** عرض بيانات مشهد مجلوبة مسبقًا {city, runs, options}. تُستخدم لنتائج التشغيل المباشر. */
  async showPayload(payload) {
    try { await document.fonts.ready; } catch { /* التسميات تعود إلى خط النظام البديل */ }
    await Promise.all([ensureDrone(),loadVisualAssets()]);
    const city = payload.city, runs = payload.runs;
    if (this.world) {
      for (const sw of this.world.swarms) { this.scene.remove(sw.group); sw.dispose?.(); }
      this.scene.remove(this.world.fires.group); disposeGroup(this.world.fires.group);
      for (const l of this.world.fireLights) this.scene.remove(l);
      if (this.world.markers) { this.scene.remove(this.world.markers.group); disposeGroup(this.world.markers.group); }
      this.scene.remove(this.world.dimensions); disposeGroup(this.world.dimensions);
      if (this.world.cityName !== city.name) {
        this.scene.remove(this.world.city.group); disposeGroup(this.world.city.group);
        for (const o of this.world.skyObjs) { this.scene.remove(o); disposeGroup(o); }
        this.world.environmentTarget?.dispose();this.scene.environment=null;
        this.world = null;
      }
    }
    const W = city.world.W;
    let cityObj = this.world?.city, skyObjs = this.world?.skyObjs,environmentTarget=this.world?.environmentTarget;
    if (!cityObj) {
      const before = new Set(this.scene.children);
      const skyInfo=buildSky(this.scene, this.renderer, W);
      environmentTarget=skyInfo.environmentTarget;
      skyObjs = this.scene.children.filter((c) => !before.has(c));
      cityObj = new City(this.scene, city);
       this.scene.fog = new THREE.FogExp2(skyInfo.fogColor, 0.30 / W);
      this.moon.position.copy(new THREE.Vector3(W/2,0,-W/2).addScaledVector(skyInfo.moonDir,W*2));
      this.moon.target.position.set(W / 2, 0, -W / 2);
      this.scene.add(this.moon.target);
      if (SHADOWS) {
        // مخروط ظل محكم فوق المدينة كلها: دقة عمق دون خريطة ضخمة
        const sc = this.moon.shadow.camera, e = W * 0.75;
        sc.left = -e; sc.right = e; sc.top = e; sc.bottom = -e;
        sc.far = W * 4;
        sc.updateProjectionMatrix();
      }
      this.controls.minDistance = 4;
      this.controls.maxDistance = W * 3;
      this.camera.far=W*10;this.camera.near=this.S.camera==='cockpit'?.2:.6;this.camera.updateProjectionMatrix();
    }
    const fires = new Fires(this.scene, city);
    const swarms = runs.map((r, i) => new Swarm(this.scene, city, r, i, fires, runs.length > 1));
    // تملك الحرائق أصلًا ضوءًا متذبذبًا متضائلًا فيزيائيًا لكل واجهة.
    // تجنب مجموعة أضواء مكررة: هذا يبقي التعريض وكلفة المظلل مستقرين.
    const fireLights = [];
    const markers = buildEndpoints(this.scene, city, runs);
    const dimensions = buildDimensions(this.scene, city);
    const T = Math.max(20, ...swarms.map((s) => s.T));
    this.world = { city: cityObj, cityName: city.name, fires, swarms, W, skyObjs,environmentTarget, data: city, fireLights, markers, dimensions,
      maxBuildingHeight: Math.max(0, ...city.buildings.map(b => b.h)),
      buildingBoxes: city.buildings.map(b => new THREE.Box3(new THREE.Vector3(b.x0, 0, -b.y1), new THREE.Vector3(b.x1, b.h, -b.y0))) };
    this.fleetDirection = null; this._fleetVantageAt = -Infinity;
    this._shadowT = -Infinity;
    this.runs = runs; this.T = T; this.S.t = -4;
    this.S.selected = clamp(this.S.selected, 0, swarms[0]?.drones.length - 1 || 0);
    this.snapshot = null; this.cameraSnap = true;
    this.setState('city', true);
    this.resize();
    this._fpsT=performance.now();this._frames=0;this.loop.invalidate();
    return { runs, T, city };
  }

  setState(name, snap = false) {
    if (!this.world) return;
    const W = this.world.W;
    const maxH = Math.max(40, ...this.world.data.buildings.map((b) => b.h));
    const ctr = (y = 30, z = 30) => ({ pos: V(W / 2 + W * 0.55, W / 2 - W * 0.8, W * 0.5), look: V(W / 2, W / 2, z) });
    const P = {
      city: { ...ctr(), danger: true, margins: false, labels: false, orbit: !REDUCED },
      caseView: this.caseFrame(),
      towers: { pos: V(W * 0.15, W * 0.1, Math.max(120, maxH * 0.9)), look: V(W / 2, W / 2, maxH * 0.35), danger: false, margins: true, labels: false, orbit: false },
      fires: (() => { const f = this.world.data.fires[0]; const c = f ? f.c : [W / 2, W / 2, 80]; return { pos: V(c[0] + 120, c[1] - 150, c[2] + 60), look: V(c[0], c[1], c[2]), danger: true, margins: false, labels: false, orbit: false }; })(),
      hazard: (() => { const f = this.world.data.fires[0]; const c = f ? f.c : [W / 2, W / 2, 80]; return { pos: V(c[0] + 200, c[1] - 240, c[2] + 160), look: V(c[0], c[1], c[2] + 40), danger: true, margins: false, labels: false, orbit: false }; })(),
      swarm: { ...ctr(), danger: true, margins: false, labels: true, orbit: false },
      mission: { pos: V(W / 2 + W * 0.3, W / 2 - W * 0.45, W * 0.32), look: V(W / 2, W / 2, 40), danger: true, margins: false, labels: true, orbit: false },
    }[name === 'mission' && this.world.data.name?.startsWith('special_') ? 'caseView' : name] || {};
    Object.assign(this.S, { danger: name === 'hazard', margins: P.margins ?? false, labels: P.labels ?? true });
    this.orbit = P.orbit && !REDUCED;
    if (P.pos && this.S.camera === 'orbit') {
      if (snap) { this.camera.position.copy(P.pos); this.controls.target.copy(P.look); this.controls.update(); this.camGoal = null; }
      else { this.camGoal = P.pos.clone(); this.lookGoal = P.look.clone(); }
    }
    this.state = name;
  }

  // تأطير مدن حالات الحافة (300 م وأبراج قد تتجاوز السقف): زاوية أعلى تحيط بنقاط الإقلاع
  // والأهداف والمسارات والمباني. يغيّر موضع الكاميرا فقط، لا المدينة ولا المسار.
  caseFrame() {
    const data = this.world.data, pts = [];
    for (const m of data.missions) pts.push(m.S, m.G);
    for (const run of this.runs || []) for (const path of run.paths) pts.push(...path);
    for (const b of data.buildings) pts.push([b.x0, b.y0, 0], [b.x1, b.y1, b.h]);
    const lo = [0, 1, 2].map(i => Math.min(...pts.map(p => p[i]))), hi = [0, 1, 2].map(i => Math.max(...pts.map(p => p[i])));
    const c = lo.map((v, i) => (v + hi[i]) / 2);
    const r = Math.max(60, Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) / 2);
    const dist = r / Math.sin(THREE.MathUtils.degToRad(45 / 2)) * 1.02;
    // إذا تجاوزت الأبراج سقف الطيران (المتاهة والفناء المغلق) تقترب الزاوية من الرأسية ليظهر المسار بينها.
    const tall = data.buildings.some(b => b.h >= data.world.z_max);
    const el = THREE.MathUtils.degToRad(tall ? 84 : 56), az = Math.atan2(-0.45, 0.3);
    // نقطة النظر أقرب قليلًا إلى الكاميرا، فترتفع المدينة في الإطار فوق أدوات الكاميرا السفلية.
    const shift = 0.18 * r;
    return { pos: V(c[0] + dist * Math.cos(el) * Math.cos(az), c[1] + dist * Math.cos(el) * Math.sin(az), c[2] + dist * Math.sin(el)),
      look: V(c[0] + shift * Math.cos(az), c[1] + shift * Math.sin(az), c[2] * 0.5), danger: true, margins: false, labels: true, orbit: false };
  }

  setTime(t) { if (Math.abs(t - this.S.t) > .75) this.cameraSnap = true; this.S.t = t; this.S.playing = false; this.onTick?.(t,false); }
  play(p) { if (p === undefined) p = !this.S.playing; if (p && this.S.t >= this.T - 0.05) this.S.t = -4; this.S.playing = p; return p; }

  restart() {
    this.showSnapshot(null); this.S.t = -4; this.S.playing = true; this.cameraSnap = true;
    for (const sw of this.world?.swarms || []) for (const drone of sw.drones) {
      drone.lastYaw = drone.yaw = null; drone.pitch = drone.bank = 0;
    }
    this.onTick?.(this.S.t, true);
  }

  setCamera(mode) {
    if (!['orbit', 'follow', 'cockpit', 'top', 'fleet'].includes(mode)) return;
    if (mode === 'fleet' && this.S.camera !== 'fleet') this.singleCamera = this.S.camera;
    this.S.camera = mode; this.orbit = false; this.camGoal = null; this.cameraSnap = true;
    this.controls.enabled = mode === 'orbit';
    this.invalidateLayout();
    this.camera.clearViewOffset();
    this.camera.up.set(0, 1, 0);
    this.camera.fov = mode === 'cockpit' ? 72 : 45; this.camera.updateProjectionMatrix();
    this.camera.near=mode==='cockpit'?.2:.6;this.camera.updateProjectionMatrix();
    if (mode === 'orbit') this.resetCamera();
  }

  selectDrone(index) {
    if (index === 'all') this.setCamera('fleet');
    else {
      this.S.selected = clamp(Number(index) || 0, 0, (this.world?.swarms[0]?.drones.length || 1) - 1);
      if (this.S.camera === 'fleet') this.setCamera(this.singleCamera);
    }
    this.cameraSnap = true; this.onTick?.(this.S.t,this.S.playing);
  }

  resetCamera() {
    this.S.camera = 'orbit'; this.controls.enabled = true; this.orbit = false;
    this.camera.clearViewOffset(); this.camera.up.set(0, 1, 0);
    this.camera.fov = 45; this.camera.updateProjectionMatrix();
    this.setState(this.state || 'mission', true); this.orbit = false;
  }

  zoom(factor) {
    this.orbit = false; this.camGoal = null;
    if (this.S.camera === 'cockpit') {
      this.camera.fov = clamp(this.camera.fov * factor, 35, 95); this.camera.updateProjectionMatrix();
    } else if (this.S.camera === 'fleet') {
      // أقرب منظر عام يتسع دائمًا للسرب كاملًا؛ والتقريب لا يقتطعه.
      this.fleetZoom = clamp(this.fleetZoom * factor, 1, 3);
    } else if (this.S.camera === 'follow' || this.S.camera === 'top') {
      this.followDistance = clamp(this.followDistance * factor, 5, 70);
    } else {
      const offset = this.camera.position.clone().sub(this.controls.target);
      offset.setLength(clamp(offset.length() * factor, this.controls.minDistance, this.controls.maxDistance));
      this.camera.position.copy(this.controls.target).add(offset); this.controls.update();
    }
  }

  showSnapshot(index) {
    this.snapshot = index;
    if (index !== null) this.S.playing = false;
    const { width, height } = this.c.getBoundingClientRect();
    for (const sw of this.world?.swarms || []) sw.showSnapshot(index, width, height);
  }

  invalidateLayout() { this._fleetViewportCache = null; this.loop?.invalidate(); }

  fleetViewport() {
    if (this._fleetViewportCache) return this._fleetViewportCache;
    const rect = this.c.getBoundingClientRect(), w = rect.width, h = rect.height;
    const left = 36, right = Math.max(left + 1, w - 36), top = 36, bottom = Math.max(top + 1, h - 36);
    const overlays = [...this.c.parentElement.querySelectorAll('.viewer-tools, .scene-hud>span'), document.querySelector('.topbar')];
    const story = this.c.closest('.story');
    // تضمين كل بطاقة ظاهرة: قد يتقدم التفعيل قبل خروج البطاقة.
    if (story) overlays.push(...story.querySelectorAll('.step-card, .stage-dock'));
    const boxes = overlays.filter(Boolean).map(el => el.getBoundingClientRect())
      .filter(box => box.width && box.height && box.right > rect.left && box.left < rect.right && box.bottom > rect.top && box.top < rect.bottom)
      .map(box => ({ left: clamp(box.left - rect.left - 28, left, right), right: clamp(box.right - rect.left + 28, left, right),
        top: clamp(box.top - rect.top - 28, top, bottom), bottom: clamp(box.bottom - rect.top + 28, top, bottom) }));
    const edges = [...new Set([left, right, ...boxes.flatMap(box => [box.left, box.right])])].sort((a, b) => a - b);
    let best = { left, right, top, bottom }, area = 0;
    // أكبر مستطيل فارغ: يعمل بجانب البطاقات وبين عناصر التحكم المكدسة
    // في التخطيطات الطولية والعرضية والمكبرة.
    for (let i = 0; i < edges.length - 1; i++) for (let j = i + 1; j < edges.length; j++) {
      const x0 = edges[i], x1 = edges[j];
      const blocked = boxes.filter(box => box.left < x1 && box.right > x0).sort((a, b) => a.top - b.top);
      let cursor = top;
      for (const box of [...blocked, { top: bottom, bottom }]) {
        const candidate = (x1 - x0) * (box.top - cursor);
        if (candidate > area) { area = candidate; best = { left: x0, right: x1, top: cursor, bottom: box.top }; }
        cursor = Math.max(cursor, box.bottom);
      }
    }
    return this._fleetViewportCache = { ...best, width: w, height: h };
  }

  fleetCamera(dt) {
    const positions = this.world.swarms.flatMap(sw => sw.drones.map(d => V(...sw.pose(d, this.S.t).pos)));
    if (!positions.length) return;
    const bounds = new THREE.Box3().setFromPoints(positions), center = bounds.getCenter(new THREE.Vector3());
    const frame = this.fleetViewport(); this.fleetFrame = frame;
    this.camera.setViewOffset(frame.width, frame.height,
      (frame.width - frame.left - frame.right) / 2, (frame.height - frame.top - frame.bottom) / 2,
      frame.width, frame.height);
    const tanV = Math.tan(THREE.MathUtils.degToRad(this.camera.fov) / 2);
    const tanX = tanV * (frame.right - frame.left) / frame.height;
    const tanY = tanV * (frame.bottom - frame.top) / frame.height;
    const k = this.cameraSnap ? 1 : 1 - Math.exp(-dt * 5);
    const radius = (this.S.realScale ? 1 : 10) * droneRadius + 3;
    const points = fleetBounds(positions, radius), minHeight = this.world.maxBuildingHeight + 35;
    this.fleetFocus.lerp(center, k);
    if (this.cameraSnap || !this.fleetDirection || this.time - this._fleetVantageAt > 1.2) {
      this._fleetVantage = chooseFleetDirection(positions, points, this.fleetFocus, frame, tanV, this.world.buildingBoxes, minHeight, this.fleetDirection);
      this._fleetVantageAt = this.time;
    }
    if (!this.fleetDirection || this.cameraSnap) this.fleetDirection = this._fleetVantage.back.clone();
    else turnFleetDirection(this.fleetDirection, this._fleetVantage.back, 1 - Math.exp(-dt * 2.5));
    const required = fitDistance(points, this.fleetFocus, this.fleetDirection, tanX, tanY, minHeight) * 1.04 * this.fleetZoom;
    this._fleetDistance = this.cameraSnap ? required : Math.max(required, THREE.MathUtils.lerp(this._fleetDistance || required, required, k));
    this.camera.position.copy(this.fleetFocus).addScaledVector(this.fleetDirection, this._fleetDistance);
    this.controls.target.copy(this.fleetFocus);
    this.camera.up.set(0, 1, 0); this.camera.lookAt(this.controls.target);
    if (this._fleetDistance + this.world.W * 2 > this.camera.far) {
      this.camera.far = this._fleetDistance + this.world.W * 4; this.camera.updateProjectionMatrix();
    }
    this.cameraSnap = false;
  }

  followCamera(dt) {
    const sw = this.world.swarms[0], d = sw?.drones[this.S.selected];
    if (!d) return;
    const p = sw.pose(d, this.S.t), pos = V(...p.pos);
    // استخدام مماس المسار الدقيق؛ فميل المسيّرة الزخرفي لا يُميل الأفق أبدًا.
    const ahead = d.flight.at(Math.max(0, this.S.t) + .65);
    let dir = V(...ahead.pos).sub(pos);
    if (dir.lengthSq() < .01) {
      const fire = this.world.data.fires.find(f => f.id === d.mission.fire);
      dir = fire ? V(...fire.c).sub(pos) : V(...d.flight.at(Math.max(0, d.flight.duration - .1)).dir);
    }
    dir.y = clamp(dir.y, -dir.length() * .35, dir.length() * .35);
    if (dir.lengthSq() < .001) dir.set(0, 0, -1);
    dir.normalize();
    const cockpit = this.S.camera === 'cockpit';
    const goal = pos.clone().addScaledVector(dir, cockpit ? .65 : -this.followDistance);
    goal.y += cockpit ? .25 : this.S.camera === 'top' ? this.followDistance * 5 : this.followDistance * .36;
    goal.y = Math.max(1.5, goal.y);
    if (!cockpit) {
      const delta = goal.clone().sub(pos), distance = delta.length();
      this.ray.set(pos, delta.normalize()); this.ray.far = distance;
      // أغلفة السيناريو تحتوي كل تفصيل معماري. وخلوص الكاميرا
      // لا يحتاج إلا هذه الصناديق القليلة، لا آلاف مثلثات النوافذ والأغصان.
      let nearest = distance;
      for (const box of this.world.buildingBoxes) {
        if (this.ray.ray.intersectBox(box, this.cameraHit)) nearest = Math.min(nearest, pos.distanceTo(this.cameraHit));
      }
      if (nearest < distance) goal.copy(pos).addScaledVector(delta, Math.max(1, nearest - .8));
    }
    const look = pos.clone().addScaledVector(dir, cockpit ? 45 : 10);
    const k = this.cameraSnap ? 1 : 1 - Math.exp(-dt * 7);
    this.camera.position.lerp(goal, k); this.controls.target.lerp(look, k);
    this.camera.lookAt(this.controls.target); this.cameraSnap = false;
  }

  frame(dt = 0, now = performance.now()) {
    if (!this.visible || !this.world || document.hidden) return;
    if (this._resizePending) this.applyResize();
    this.time += dt;
    // التكيف فقط مع تجاوز ميزانية الإطار، لا مع سقف 20/30 إطارًا في الثانية المقصود.
    this._frames++;
    if (now - this._fpsT >= 1000) { this.fps = (this._frames * 1000) / (now - this._fpsT); this._frames = 0; this._fpsT = now; }
    this._ema = this._ema * 0.95 + Math.min(100, dt * 1000) * 0.05;
    if (this._ema > 1500 / this.loop.maxFPS && this.renderer.getPixelRatio() > .7) {
      if (++this._slow > 6) { this._scaleLimit = Math.max(.7, this._scaleLimit * .85); this.resize(); this._slow = 0; }
    } else this._slow = 0;
    if (this.S.playing && this.snapshot === null) {
      this.S.t += dt * this.S.speed;
      if (this.S.t >= this.T) { this.S.t = this.T; this.S.playing = false; }
    }
    if (this.S.camera === 'fleet') this.fleetCamera(dt);
    else if (this.S.camera !== 'orbit') this.followCamera(dt);
    else if (this.camGoal) {
      const k = Math.min(1, dt * 2.2);
      this.camera.position.lerp(this.camGoal, k);
      this.controls.target.lerp(this.lookGoal, k);
      if (this.camera.position.distanceTo(this.camGoal) < 1.5) this.camGoal = null;
    } else if (this.orbit && !REDUCED) {
      const W = this.world.W, a = this.time * 0.035;
      this.camera.position.set(W / 2 + Math.cos(a) * W * 0.95, W * 0.42, -W / 2 + Math.sin(a) * W * 0.95);
      this.camera.lookAt(W / 2, 30, -W / 2);
    } else this.controls.update();
    const scale = this.c.clientHeight / (2 * Math.tan(THREE.MathUtils.degToRad(this.camera.fov) / 2));
    this.world.city.update(this.time, dt);
    this._updates++;
    this.world.city.margins.visible = this.S.margins;
    this.world.dimensions.visible = this.S.dimensions;
    this.world.markers.group.visible = this.S.camera === 'orbit';
    this.world.fires.update(this.time, this.S.t, scale);
    this.world.fires.cores.visible = this.S.danger;
    for (const sw of this.world.swarms)
      sw.update(this.S.t, dt, this.time, this.camera, { ...this.S, snapshot: this.snapshot,
        labels: this.S.labels || this.S.camera === 'fleet',
        realScale: this.S.realScale || ['follow', 'cockpit', 'top'].includes(this.S.camera), cockpit: this.S.camera === 'cockpit' });
    const selected = this.world.swarms[0]?.drones[this.S.selected];
    this.spot.visible = this.S.spotlight;
    if (selected && this.S.spotlight) {
      const pose = this.world.swarms[0].pose(selected, this.S.t), at = V(...pose.pos);
      this.spot.position.copy(at).add(new THREE.Vector3(0, -.3, 0));
      this.spot.target.position.copy(at).add(V(pose.dir[0] * 35, pose.dir[1] * 35, -18));
      this.spot.intensity = 450;
    }
    if (!this._lastTick || now - this._lastTick > 100) {
      this._lastTick = now; this.onTick?.(this.S.t, this.S.playing);
    }
    if (SHADOWS && this.time - this._shadowT >= .125) {
      this.renderer.shadowMap.needsUpdate = true; this._shadowT = this.time; this._shadowUpdates++;
    }
    this.renderer.info.reset();this.composer.render();this._rendered++;
  }
}
