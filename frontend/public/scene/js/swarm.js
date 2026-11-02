// الأسراب: مسيّرة لكل مهمة في كل تشغيل معروض، تطير على الخطوط المخططة نفسها بدقة.
// الموضع = المسار عند الطول القوسي speed * t (سرعة ثابتة، ثم تحوم عند الهدف: نموذج الحركة
// نفسه في دالة اللياقة والمدقق). أما الوضعية (الاتجاه والميل والدوران الجانبي)
// والمراوح فتجميلية فقط.
import * as THREE from '../vendor/three/three.module.js';
import { GLTFLoader } from '../vendor/three/examples/jsm/loaders/GLTFLoader.js';
import { Line2 } from '../vendor/three/examples/jsm/lines/Line2.js';
import { LineGeometry } from '../vendor/three/examples/jsm/lines/LineGeometry.js';
import { LineMaterial } from '../vendor/three/examples/jsm/lines/LineMaterial.js';
import { V, Flight, clamp, lerp, smooth, radialSprite, textSprite, hazardAt, nearestTower } from './util.js';
import { t as copy } from '../../content.js?v=viewport-20261018';

const TAKEOFF = 4;           // ثوانٍ للصعود الرأسي من المنصة إلى نقطة الإقلاع S (قبل الزمن 0 للمهمة)
const G = 9.81;
let TEMPLATE = null;
let modelLoading=null;
export const DRONE_MODEL_URL='/scene/assets/rescue_hexacopter.glb';
export const PATH_STYLE={plan:0x9874d3,core:0xc69aff,glow:0x9650ef};
// مؤثرات نجاح المهمة (قذف الكبسولة وإطفاء الحريق) تتطلب حكم سلامة صريحًا من المدقق ودالة اللياقة؛
// وغياب أي من الحكمين يُعامل كخطة غير آمنة.
export const missionSuccessAllowed = run => run?.valid === true && run?.feasible === true;

export async function loadDrone(url=DRONE_MODEL_URL) {
  if (TEMPLATE) return TEMPLATE;
  if(!modelLoading)modelLoading=new GLTFLoader().loadAsync(url).then(gltf=>{
    TEMPLATE=gltf.scene;
    TEMPLATE.traverse(o=>{if(o.isMesh){o.castShadow=true;o.layers.enable(0);}});
    return TEMPLATE;
  }).catch(error=>{modelLoading=null;throw error;});
  return modelLoading;
}

function wrap(a) { return Math.atan2(Math.sin(a), Math.cos(a)); }

function dense(path, step) {
  const out = [];
  for (let i = 1; i < path.length; i++) {
    const a = path[i - 1], b = path[i];
    const L = Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
    const n = Math.max(1, Math.ceil(L / step));
    for (let j = 0; j < n; j++) out.push([lerp(a[0], b[0], j / n), lerp(a[1], b[1], j / n), lerp(a[2], b[2], j / n)]);
  }
  out.push(path[path.length - 1]);
  return out;
}

function lineObj(points, color, width, opacity, dashed = false) {
  const g = new LineGeometry();
  const flat = [];
  for (const p of points) flat.push(...V(p[0], p[1], p[2]).toArray());
  g.setPositions(flat);
  const m = new LineMaterial({ color, linewidth: width, transparent: opacity < 1, opacity, dashed,
    dashSize: 6, gapSize: 4, worldUnits: false, depthWrite: false, toneMapped: false });
  const l = new Line2(g, m);
  if (dashed) l.computeLineDistances();
  l.renderOrder = 4;
  l.layers.set(1);
  return l;
}

export class Swarm {
  // run = ناتج run_summary() في backend/server.py؛ وcity = بيانات السيناريو
  constructor(scene, city, run, idx, fires, compare = false) {
    this.scene = scene;
    this.compare = compare;
    this.city = city;
    this.run = run;
    this.idx = idx;
    this.color = new THREE.Color(run.color);
    this.safe = missionSuccessAllowed(run);
    this.group = new THREE.Group();
    this.group.name = `swarm_${run.algorithm}`;
    scene.add(this.group);
    const speed = city.drone.speed;
    this.drones = run.paths.map((path, k) => this.makeDrone(path, k, speed, fires));
    this.T = Math.max(...this.drones.map(d => d.done));
    this.lines = [];
    this.precomputeSeparation();
  }

  makeDrone(path, k, speed, fires) {
    const mission = this.city.missions[k];
    const flight = new Flight(path, speed);
    const root = TEMPLATE.clone(true);
    const props = [], navs = [];
    let capsule = null, strobe = null;
    root.traverse(o => {
      if (o.name.startsWith('Prop_')) props.push(o);
      if (o.name === 'Payload_FireCapsule') capsule = o;
      if (o.name === 'Strobe_Top') strobe = o;
      if (o.name.startsWith('Light_')) navs.push(o);
    });
    root.rotation.order = 'YXZ';
    const holder = new THREE.Group();
    holder.add(root);
    this.group.add(holder);
    // رقع توهج لأضواء الملاحة (تُرى ليلًا حتى لو صغرت المسيّرة جدًا)
    const addGlow = (node, col, size) => {
      if (!node) return null;
      const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: radialSprite(64, 'rgba(255,255,255,1)', 'rgba(255,255,255,0)'),
        color: col, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false }));
      s.scale.set(size, size, 1);
      node.add(s);
      s.layers.set(1);
      return s;
    };
    for (const nd of navs) {
      // تُنسخ مواد المصابيح لكل مسيّرة فقط؛ وتبقى هندسة GLB المشتركة ثابتة.
      if (nd.material) nd.material = nd.material.clone();
      addGlow(nd, nd.name.includes('Port') ? 0xff2222 : nd.name.includes('Starboard') ? 0x22ff66 : 0xffffff, 0.5);
    }
    if (strobe?.material) strobe.material = strobe.material.clone();
    const strobeGlow = addGlow(strobe, 0xffffff, 1.4);
    // حلقة منارة بلون الخوارزمية + تسمية
    const ring = new THREE.Mesh(new THREE.RingGeometry(1.25, 1.45, 40).rotateX(-Math.PI / 2),
      new THREE.MeshBasicMaterial({ color: this.color, transparent: true, opacity: 0.9, side: THREE.DoubleSide,
        depthWrite: false, toneMapped: false }));
    ring.layers.set(1);
    holder.add(ring);
    const label = textSprite(this.compare ? this.run.algorithm : `${this.run.algorithm} D${k + 1}`, this.run.color);
    label.scale.set(.05, .025, 1);
    label.userData.show = !this.compare || k === 0;          // المقارنة: تسمية واحدة لكل سرب
    label.position.set(0, 2.2, 0);
    holder.add(label);
    // خط إسقاط إلى الأرض (إشارة للعمق)
    const dropGeo = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(), new THREE.Vector3(0, -1, 0)]);
    const drop = new THREE.Line(dropGeo, new THREE.LineBasicMaterial({ color: PATH_STYLE.plan, transparent: true, opacity: 0.2, depthWrite: false }));
    drop.layers.set(1);
    this.group.add(drop);
    // المسارات: الخطة كاملة (متقطعة وباهتة) والجزء المقطوع (ساطع ويطول مع الزمن)
    const pts = dense(path, 1.5);
    const plan = lineObj(path, PATH_STYLE.plan, 1.2, 0.46, true);
    const flown = lineObj(pts, PATH_STYLE.core, 2.2, 0.96);
    const flownGlow=new Line2(flown.geometry,new LineMaterial({color:PATH_STYLE.glow,linewidth:6.5,transparent:true,opacity:.16,worldUnits:false,depthWrite:false,toneMapped:false}));
    flownGlow.layers.set(1);flownGlow.renderOrder=3;flownGlow.name='purple_trail_halo';
    flown.name='purple_trail_core';plan.name='purple_planned_path';
    flown.userData.step = 1.5;
    this.group.add(plan,flownGlow,flown);
    // تُقذف الكبسولة من G إلى نقطة أمام مركز الحريق بـ 0.6 م، إذا كانت الخطة آمنة.
    let throwInfo = null;
    const fire = mission.fire >= 0 ? this.city.fires.find(f => f.id === mission.fire) : null;
    if (fire && capsule && this.safe) {
      const from = V(...mission.G);
      const n = V(fire.normal[0], fire.normal[1], 0).normalize();
      const to = V(...fire.c).addScaledVector(n, 0.6);
      const Tc = Math.max(0.9, from.distanceTo(to) / 12);
      const v0 = to.clone().sub(from).sub(new THREE.Vector3(0, -0.5 * G * Tc * Tc, 0)).divideScalar(Tc);
      const flying = capsule.clone(true);
      flying.visible = false;
      this.group.add(flying);
      throwInfo = { from, v0, Tc, tRelease: flight.duration + 1.5, flying, fireId: fire.id };
      throwInfo.tImpact = throwInfo.tRelease + Tc;
      fires.setExtinguishTime(fire.id, Math.min(fires.items.find(x => x.f.id === fire.id)?.tEnd ?? Infinity, throwInfo.tImpact));
    }
    const done = throwInfo ? throwInfo.tImpact + 9 : flight.duration + 4;
    // الأطوال التراكمية للتقسيم الفعلي، لا لخطوة اسمية قدرها 1.5 م.
    // نهاية كل مقطع دقيقة حتى لو لم يقبل طول المقطع القسمة على الخطوة.
    const cumulative = [0];
    for (let i = 1; i < pts.length; i++) cumulative.push(cumulative[i - 1] + Math.hypot(...pts[i].map((v, j) => v - pts[i - 1][j])));
    return { k, mission, flight, root, holder, props, navs, strobe, capsule, strobeGlow, ring, label, drop, plan, flown,flownGlow, cumulative, nPts: pts.length,
      throwInfo, done, lastYaw: null, pitch: 0, bank: 0, yaw: null, state: {} };
  }

  precomputeSeparation() {
    const D = this.drones;
    this.sep = [];
    if (D.length < 2) return;
    const dt = 0.1, T = Math.max(...D.map(d => d.flight.duration));
    for (let t = 0; t <= T + dt; t += dt) {
      let best = Infinity, pair = null;
      const P = D.map(d => d.flight.at(t).pos);
      for (let i = 0; i < P.length; i++) for (let j = i + 1; j < P.length; j++) {
        const dd = Math.hypot(P[i][0] - P[j][0], P[i][1] - P[j][1], P[i][2] - P[j][2]);
        if (dd < best) { best = dd; pair = [i, j]; }
      }
      this.sep.push({ t, d: best, pair });
    }
    this.minSep = this.sep.reduce((a, b) => (b.d < a.d ? b : a), this.sep[0]);
  }

  separationAt(t) {
    if (!this.sep.length) return null;
    return this.sep[clamp(Math.round(Math.max(0, t) / 0.1), 0, this.sep.length - 1)];
  }

  // موضع المسيّرة d عند زمن المهمة t (صعود الإقلاع قبل 0)
  pose(d, t) {
    const S = d.mission.S;
    if (t < 0) {
      const u = smooth(clamp((t + TAKEOFF) / TAKEOFF, 0, 1));
      return { pos: [S[0], S[1], S[2] * u], dir: [0, 0, 1], s: 0, climb: 0, moving: u > 0 && u < 1, phase: 'takeoff' };
    }
    const a = d.flight.at(t);
    return { ...a, moving: !a.arrived, phase: a.arrived ? 'arrived' : 'flying' };
  }

  status(d, t, fires) {
    if (t < 0) return copy('statuses.takeoff');
    const ti = d.throwInfo;
    if (t < d.flight.duration) return copy('statuses.enroute');
    if (!this.safe) return copy('statuses.rejected');
    if (!ti) return copy('statuses.arrived');
    if (t < ti.tRelease) return copy('statuses.preparing');
    if (t < ti.tImpact + 1) return copy('statuses.released');
    const it = fires.items.find(x => x.f.id === ti.fireId);
    return it && t >= it.tEnd + 3 ? copy('statuses.out') : copy('statuses.dying');
  }

  telemetry(d, t, fires) {
    const p = this.pose(d, t);
    const dr = this.city.drone;
    const E = dr.e_c * p.s + dr.e_up * p.climb;
    return {
      t: Math.max(0, t), s: p.s, L: d.flight.length, pos: p.pos,
      battery: 100 - 100 * E / (dr.battery_kj * 1000),
      tower: nearestTower(p.pos, this.city.buildings),
      alt: p.pos[2], speed: p.phase === 'flying' ? dr.speed : (p.phase === 'takeoff' && p.moving ? 2.5 : 0),
      hazard: hazardAt(p.pos, fires.modelFires(), this.city.hazard.k),
      status: this.status(d, t, fires),
    };
  }

  update(t, dt, time, camera, opts) {
    const camPos = camera.position;
    for (const d of this.drones) {
      const p = this.pose(d, t);
      const pos = V(...p.pos);
      d.holder.position.copy(pos);
      // الحجم البصري: حقيقي عن قرب، ومكبّر عند الرؤية من بعيد (مشار إليه في شاشة البيانات)
      const dist = camPos.distanceTo(pos);
      const overview = opts.camera === 'fleet';
      const sc = opts.realScale ? 1 : overview ? clamp(dist / 70, 1, 10) : clamp(dist / 38, 1, 18);
      d.root.scale.setScalar(sc);
      d.ring.scale.setScalar(sc);
      d.label.position.y = 1.2 * sc + 1 + this.idx * 1.1 * sc;     // التشغيلات مكدسة، والتسميات لا تتداخل
      const hidden = opts.cockpit && d.k === opts.selected;
      d.root.visible = !hidden;
      d.label.visible = opts.labels && d.label.userData.show && !hidden && (!opts.camera || opts.camera === 'orbit' || overview || d.k === opts.selected);
      d.ring.visible = opts.labels && !hidden && (!opts.camera || opts.camera === 'orbit' || overview);
      for (const nav of d.navs) nav.visible = opts.lights !== false;
      if (d.strobe) d.strobe.visible = opts.lights !== false;
      // الوضعية
      const v = p.dir;
      const hs = Math.hypot(v[0], v[1]);
      if (p.phase === 'flying' && hs > 0.05) {
        const heading = Math.atan2(v[0], -v[1]);                     // محور النموذج +Z للأمام -> three (x, -y)
        d.yaw = d.yaw === null ? heading : d.yaw + wrap(heading - d.yaw) * Math.min(1, dt * 4);
        const rate = d.lastYaw === null ? 0 : wrap(d.yaw - d.lastYaw) / Math.max(dt, 1e-3);
        d.lastYaw = d.yaw;
        d.pitch = lerp(d.pitch, 0.17, Math.min(1, dt * 3));
        d.bank = lerp(d.bank, clamp(-rate * 0.35, -0.35, 0.35), Math.min(1, dt * 3));
      } else {
        d.pitch = lerp(d.pitch, 0, Math.min(1, dt * 3));
        d.bank = lerp(d.bank, 0, Math.min(1, dt * 3));
        if (d.yaw === null) d.yaw = 0;
      }
      d.root.rotation.set(d.pitch, d.yaw, d.bank);
      if (opts.rotors !== false) for (const pr of d.props) pr.rotation.y += (pr.userData.spin || 1) * 70 * Math.min(dt, 0.05) * (t > -TAKEOFF ? 1 : 0.1);
      if (d.strobeGlow) d.strobeGlow.material.opacity = (time % 1.2) < 0.08 ? 1 : 0;
      // خط الإسقاط
      const dp = d.drop.geometry.attributes.position;
      dp.setXYZ(0, pos.x, pos.y, pos.z); dp.setXYZ(1, pos.x, 0.2, pos.z); dp.needsUpdate = true;
      d.drop.visible = opts.labels && !hidden;
      // الجزء المقطوع من المسار
      let low = 0, high = d.cumulative.length - 1;
      while (low < high) { const mid = Math.ceil((low + high) / 2); if (d.cumulative[mid] <= Math.max(0, p.s) + 1e-8) low = mid; else high = mid - 1; }
      const n = low;
      d.flown.geometry.instanceCount = clamp(n, 0, d.nPts - 1);
       d.flown.visible = opts.paths && t > 0 && opts.snapshot === null;
       d.flownGlow.visible=d.flown.visible;
      d.plan.visible = opts.paths && opts.snapshot === null;
      // الكبسولة
      const ti = d.throwInfo;
      if (d.capsule) d.capsule.visible = !ti || t < ti.tRelease;
      if (ti) {
        const u = t - ti.tRelease;
        ti.flying.visible = u >= 0 && u <= ti.Tc;
        if (ti.flying.visible) {
          ti.flying.position.copy(ti.from).addScaledVector(ti.v0, u).add(new THREE.Vector3(0, -0.5 * G * u * u, 0));
          ti.flying.scale.setScalar(sc);
          ti.flying.rotation.x += dt * 6;
        }
      }
      d.holder.visible = true;
    }
  }

  setResolution(w, h) {
    for (const d of this.drones) { d.plan.material.resolution.set(w, h); d.flown.material.resolution.set(w, h);d.flownGlow.material.resolution.set(w,h); }
    for (const l of this.lines) l.material.resolution.set(w, h);
  }

  // تطور المسار: عرض أفضل خطة محفوظة عند نسبة معينة من الميزانية (null = معطل)
  showSnapshot(k, w, h) {
    for (const l of this.lines) { this.group.remove(l); l.geometry.dispose(); l.material.dispose(); }
    this.lines = [];
    if (k === null || k === undefined || !this.run.snapshots?.length) return;
    const snap = this.run.snapshots[clamp(k, 0, this.run.snapshots.length - 1)];
    for (const p of snap.paths) {
      const halo=lineObj(p,PATH_STYLE.glow,6.5,.16);halo.material.resolution.set(w,h);halo.renderOrder=3;this.group.add(halo);this.lines.push(halo);
      const l = lineObj(p, PATH_STYLE.core, 2.2, 0.96);
      l.material.resolution.set(w, h);
      this.group.add(l);
      this.lines.push(l);
    }
  }

  setVisible(v) { this.group.visible = v; }

  dispose() {
    // شبكات المسيّرات تتشارك قالب GLB، فلا تُحرَّر إلا الخطوط والتسميات والمصابيح المملوكة.
    for (const d of this.drones) {
      for (const o of [d.plan, d.flown, d.drop, d.ring]) { o.geometry.dispose(); o.material.dispose(); }
      d.flownGlow.material.dispose();
      d.label.material.map?.dispose(); d.label.material.dispose();
      for (const nav of [...d.navs, d.strobe].filter(Boolean)) {
        nav.material?.dispose();
        for (const glow of nav.children) if (glow.isSprite) { glow.material.map?.dispose(); glow.material.dispose(); }
      }
    }
    for (const line of this.lines) { line.geometry.dispose(); line.material.dispose(); }
    this.scene.remove(this.group);
  }
}
