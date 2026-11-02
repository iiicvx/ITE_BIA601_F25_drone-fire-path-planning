// الحرائق والدخان والقلب المحظور والإطفاء.
// الحجم والقلب المرسوم من معاملات نموذج الحريق (c وR وI وHf وk وtau_core).
// حالة الحريق تُحسب من زمن المهمة: يشتعل حتى تصيبه الكبسولة أو ينهيه فريق الأرض، ثم يخمد خلال ثوانٍ.
import * as THREE from '../vendor/three/three.module.js';
import { RoundedBoxGeometry } from '../vendor/three/examples/jsm/geometries/RoundedBoxGeometry.js';
import { V, rng, canvasTexture, coreRadius, smooth, clamp } from './util.js';
import { fireWingBounds } from './architecture.js';

const PARTICLE_VS = `
  uniform float uTime, uScale, uIntensity, uLife, uRise, uWidth, uSize, uSpread, uK, uOut;
  uniform vec3 uOrigin, uNormal, uRight;
  attribute vec4 aSeed;
  varying float vLife; varying float vSeed;
  void main(){
    float life = fract(uTime / (uLife * (0.7 + 0.6 * aSeed.w)) + aSeed.x);
    float age = life * uLife;
    vec3 up = vec3(0.0, 1.0, 0.0);
    float rise = uRise * (0.6 + 0.8 * aSeed.y) * age;
    float spread = uWidth * (aSeed.z - 0.5) * (0.35 + 0.65 * uIntensity) + uSpread * (aSeed.y - 0.5) * (1.0 + uK * rise);
    float sway = sin(uTime * 1.7 + aSeed.x * 40.0) * (0.6 + 0.08 * rise);
    vec3 p = uOrigin + uRight * (spread + sway) + up * rise + uNormal * (uOut * age + 0.6);
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    float size = uSize * (0.55 + aSeed.w) * mix(1.0, 0.45, life) * (0.25 + 0.75 * uIntensity);
     gl_PointSize = clamp(size * uScale / -mv.z,1.,4.);
    vLife = life; vSeed = aSeed.y;
  }`;


// حجم مشارك محدود، يُكامل بالأشعة عبر اضطراب ثلاثي الأبعاد صاعد.
// يحل محل كومة النقاط المستديرة المضافة. وهو بصري فقط:
// لا هذه الكثافة ولا حركتها تعودان إلى مقيّم الخطر.
const FLAME_VS = `
  uniform vec3 uCentre,uNormal,uRight;
  varying vec3 vOrigin,vRay;
  void main(){
    vec3 eye=cameraPosition-uCentre;
    vOrigin=vec3(dot(eye,uRight),eye.y,dot(eye,uNormal));
    vRay=position-vOrigin;
    gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);
  }`;
const FLAME_FS = `
  uniform float uTime,uIntensity,uSeed;uniform vec3 uHalf;
  varying vec3 vOrigin,vRay;
  float hash(vec3 p){p=fract(p*.1031);p+=dot(p,p.yzx+33.33);return fract((p.x+p.y)*p.z);}
  float noise(vec3 p){
    vec3 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);
    return mix(mix(mix(hash(i),hash(i+vec3(1,0,0)),f.x),mix(hash(i+vec3(0,1,0)),hash(i+vec3(1,1,0)),f.x),f.y),
      mix(mix(hash(i+vec3(0,0,1)),hash(i+vec3(1,0,1)),f.x),mix(hash(i+vec3(0,1,1)),hash(i+vec3(1)),f.x),f.y),f.z);
  }
  void main(){
    vec3 rd=normalize(vRay);vec3 safe=mix(vec3(-1.),vec3(1.),step(vec3(0.),rd))*max(abs(rd),vec3(.00001));
    vec3 a=(-uHalf-vOrigin)/safe,b=(uHalf-vOrigin)/safe;
    vec3 lo=min(a,b),hi=max(a,b);
    float enter=max(0.,max(lo.x,max(lo.y,lo.z))),exit=min(hi.x,min(hi.y,hi.z));
    if(exit<=enter)discard;
    float stepSize=(exit-enter)/16.;vec4 sum=vec4(0.);
    for(int j=0;j<16;j++){
      vec3 p=vOrigin+rd*(enter+(float(j)+.5)*stepSize);
      float height=p.y+uHalf.y,h=height/(2.*uHalf.y);
      vec3 flow=vec3(p.x*.55+uSeed,height*.63-uTime*2.8,p.z*.7);
      float broad=noise(flow),detail=noise(flow*2.13+vec3(1.4,-uTime*.7,3.2));
      float fine=noise(flow*4.31+vec3(broad*1.5,-uTime*1.1,detail));
      float turbulence=broad*.55+detail*.3+fine*.15;
      float phase=noise(vec3(p.x*.23,uSeed,7.));
      float localHeight=height-phase*3.5;
      float tip=9.+phase*13.+sin(uTime*1.7+phase*6.3)*2.;
      float taper=1.-smoothstep(tip*.45,tip,localHeight);
      float warp=p.x+sin(h*4.-uTime*2.+phase*8.)*h*.7;
      float tongueDistance=abs(fract((warp+1.6)/3.2)-.5)*3.2;
      float tongueWidth=max(.32,1.45*(1.-localHeight/(tip*1.4)));
      float tongues=1.-smoothstep(tongueWidth*.2,tongueWidth,tongueDistance);
      float sides=1.-smoothstep(uHalf.x*.58,uHalf.x-.1,abs(p.x+(broad-.5)*h*2.));
      float outward=(p.z+uHalf.z-1.9-height*.09)/(1.5+height*.04);
      float depth=exp(-outward*outward);
      float source=mix(.5+.5*tongues,1.,smoothstep(2.,7.,localHeight));
      float density=max(0.,turbulence*1.15+taper*.43+tongues*.12-.83)*source;
      density*=taper*sides*depth*smoothstep(0.,1.8,localHeight)*(1.-smoothstep(.85,1.,h))*uIntensity;
      float alpha=1.-exp(-density*stepSize*2.1);
      float heat=clamp(density*1.5+(1.-h)*.17,0.,1.);
      vec3 fire=mix(vec3(.9,.018,.001),vec3(2.1,.23,.006),smoothstep(.04,.48,heat));
      fire=mix(fire,vec3(3.,1.15,.15),smoothstep(.53,.95,heat));
      sum.rgb+=(1.-sum.a)*fire*alpha;sum.a+=(1.-sum.a)*alpha;
      if(sum.a>.97)break;
    }
    if(sum.a<.006)discard;
    gl_FragColor=vec4(sum.rgb/max(sum.a,.001),sum.a);
  }`;

const EMBER_FS=`varying float vLife,vSeed;uniform float uIntensity;
  void main(){vec2 q=gl_PointCoord-.5;float r=length(q*vec2(1.7,.8))*2.;if(r>1.)discard;
    float a=(1.-r)*smoothstep(0.,.04,vLife)*(1.-smoothstep(.35,1.,vLife))*uIntensity;
    gl_FragColor=vec4(mix(vec3(2.,.22,.01),vec3(3.,1.4,.25),vSeed),a);}`;

const SMOKE_VS = `
  uniform float uTime, uScale, uLife, uRise, uR, uK, uSize, uDensity, uWind;
  uniform vec3 uOrigin, uNormal, uRight, uWindDir;
  attribute vec4 aSeed;
  varying float vLife; varying float vShade;
  void main(){
    float life = fract(uTime / uLife + aSeed.x);
    float age = life * uLife;
    float dz = uRise * age * (0.7 + 0.6 * aSeed.y);
    float sigma = uR * 0.45 + uK * dz;                      // العمود يتسع كما في نموذج الخطر
    vec2 g = vec2(aSeed.z - 0.5, aSeed.w - 0.5) * 2.0;
    vec3 fwd = cross(uRight, vec3(0.0, 1.0, 0.0));
    vec3 p = uOrigin + vec3(0.0, dz + 6.0, 0.0) + uRight * g.x * sigma + fwd * g.y * sigma * 0.8
           + uNormal * (3.0 + 0.2 * dz) + uWindDir * uWind * age;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
     gl_PointSize = uSize * (0.65 + 1.45 * life) * (0.7 + 0.6 * aSeed.y) * uScale / -mv.z;
    vLife = life; vShade = aSeed.w;
  }`;

const SMOKE_FS = `
  uniform float uDensity, uSteam,uTime; uniform vec3 uLit;
  varying float vLife; varying float vShade;
  float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
  float noise(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1)),f.x),f.y);}
  void main(){
    vec2 q = gl_PointCoord - 0.5; float r = length(q) * 2.0;
    if (r > 1.0) discard;
     vec2 p=q*5.+vec2(vShade*24.,uTime*.18);
     float billow=.6*noise(p)+.28*noise(p*2.1)+.12*noise(p*4.3);
     float edge=1.-smoothstep(.54,1.,r);
     float a=smoothstep(.28,.76,billow+edge*.3)*edge*.27*uDensity;
    a *= smoothstep(0.0, 0.12, vLife) * (1.0 - smoothstep(0.55, 1.0, vLife));
     float rim=clamp(.55+q.x*.45+billow*.35,0.,1.);
     vec3 dark=mix(vec3(.018,.024,.032),vec3(.085,.105,.13),rim);
     vec3 steam = vec3(.46,.49,.52);
     vec3 c = mix(dark, steam, uSteam) + uLit * pow(1.0 - vLife, 3.0) * .22 * (1.0 - uSteam);
    gl_FragColor = vec4(c, a);
  }`;

const BURST_VS = `
  uniform float uAge, uScale; uniform vec3 uOrigin, uNormal; attribute vec4 aSeed; varying float vA;
  void main(){
    vec3 dir = normalize(vec3(aSeed.x - 0.5, aSeed.y - 0.35, aSeed.z - 0.5) + uNormal * 0.9);
    float d = 14.0 * (1.0 - exp(-uAge * 1.8)) * (0.4 + 0.8 * aSeed.w);
    vec3 p = uOrigin + dir * d + vec3(0.0, -0.6 * uAge * uAge, 0.0);
    vec4 mv = modelViewMatrix * vec4(p, 1.0); gl_Position = projectionMatrix * mv;
    gl_PointSize = (3.0 + 7.0 * uAge) * (0.5 + aSeed.w) * uScale / -mv.z;
    vA = clamp(1.0 - uAge / 5.0, 0.0, 1.0);
  }`;
const BURST_FS = `varying float vA; void main(){ vec2 q = gl_PointCoord - 0.5; float r = length(q) * 2.0; if (r > 1.0) discard;
  float a = (1.0 - r) * vA * 0.75; gl_FragColor = vec4(vec3(0.93, 0.94, 0.95), a); }`;

const WATER_VS = `
  uniform float uTime, uScale, uOn; uniform vec3 uFrom, uTo; attribute vec4 aSeed; varying float vA;
  void main(){
    float life = fract(uTime * 0.9 + aSeed.x);
    vec3 d = uTo - uFrom; float L = length(d);
    vec3 p = uFrom + d * life + vec3(0.0, 4.0 * sin(3.14159 * life) * (L / 30.0), 0.0)
           + (aSeed.yzw - 0.5) * (0.3 + 2.2 * life);
    vec4 mv = modelViewMatrix * vec4(p, 1.0); gl_Position = projectionMatrix * mv;
    gl_PointSize = (0.6 + 2.2 * life) * uScale / -mv.z;
    vA = uOn * (1.0 - life * 0.6);
  }`;
const WATER_FS = `varying float vA; void main(){ vec2 q = gl_PointCoord - 0.5; float r = length(q) * 2.0; if (r > 1.0) discard;
  gl_FragColor = vec4(0.75, 0.85, 1.0, (1.0 - r) * 0.55 * vA); }`;

function seeds(n, seed) {
  const r = rng(seed), a = new Float32Array(n * 4);
  for (let i = 0; i < a.length; i++) a[i] = r();
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(n * 3), 3));
  g.setAttribute('aSeed', new THREE.Float32BufferAttribute(a, 4));
  g.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 1e6);
  return g;
}

function sootTexture(seed) {
  const rand = rng(seed);
  return canvasTexture(256, 512, (ctx) => {
    ctx.clearRect(0, 0, 256, 512);
    for (let i = 0; i < 70; i++) {
      const x = 128 + (rand() - 0.5) * 120 * (1 + i / 70), y = 420 - i * 5.5 - rand() * 30;
      const r = 30 + rand() * 50;
      const g = ctx.createRadialGradient(x, y, 0, x, y, r);
      g.addColorStop(0, 'rgba(8,6,5,0.32)'); g.addColorStop(1, 'rgba(8,6,5,0)');
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.fill();
    }
  });
}

function emberWindows(seed) {
  const rand = rng(seed);
  return canvasTexture(256, 256, (ctx) => {
    ctx.fillStyle = '#000'; ctx.fillRect(0, 0, 256, 256);
    for (let r = 0; r < 8; r++) for (let c = 0; c < 8; c++) {
      const dx = (c - 3.5) / 4, dy = (r - 4.5) / 4.5;
      const k = Math.max(0, 1 - Math.hypot(dx, dy)) * (0.4 + 0.6 * rand());
      if (k < 0.1) continue;
      const g = ctx.createLinearGradient(0, r * 32, 0, r * 32 + 22);
      g.addColorStop(0, `rgba(255,${120 + 80 * rand()},40,${k})`); g.addColorStop(1, `rgba(255,60,10,${k * 0.6})`);
      ctx.fillStyle = g; ctx.fillRect(c * 32 + 4, r * 32 + 4, 24, 20);
    }
  });
}

export class Fires {
  constructor(scene, city, opts = {}) {
    this.scene = scene;
    this.group = new THREE.Group();
    this.group.name = 'fires';
    scene.add(this.group);
    this.k = city.hazard.k;
    this.tau = city.hazard.tau_core;
    this.items = [];
    this.scaleUniforms = [];
    city.fires.forEach((f, i) => this.items.push(this.makeFire(f, i, city)));
    this.cores = new THREE.Group();
    this.cores.name = 'danger_zones';
    this.group.add(this.cores);
    this.items.forEach(it => this.cores.add(it.core));
  }

  makeFire(f, i, city) {
    const c = V(...f.c);
    const n = V(f.normal[0], f.normal[1], 0).normalize();
    const right = new THREE.Vector3().crossVectors(new THREE.Vector3(0, 1, 0), n).normalize();
    const R = f.R, I = f.I;
    const building=city.buildings.find(b=>b.id===f.building);
    const support=building?fireWingBounds(building,f):null;
    const flameWidth=Math.min(R*1.65,support?support.width-1:R*1.65),flameHeight=Math.min(26,7+R*1.25),flameDepth=7;
    const centre=c.clone().addScaledVector(n,flameDepth/2+.18).add(new THREE.Vector3(0,flameHeight/2-3.5,0));
    const common = { uTime: { value: 0 }, uScale: { value: 800 }, uOrigin: { value: c.clone() }, uNormal: { value: n },
      uRight: { value: right }, uIntensity: { value: 1 } };
    const flameMat = new THREE.ShaderMaterial({
      uniforms: { ...common,uCentre:{value:centre},uHalf:{value:new THREE.Vector3(flameWidth/2,flameHeight/2,flameDepth/2)},uSeed:{value:i*13.17} },
      vertexShader: FLAME_VS, fragmentShader: FLAME_FS, transparent: true, depthWrite: false,
      side:THREE.BackSide });
    const flames = new THREE.Mesh(new THREE.BoxGeometry(flameWidth,flameHeight,flameDepth), flameMat);
    flames.position.copy(centre);flames.lookAt(centre.clone().add(n));flames.name=`volumetric_flames_${f.id}`;
    flames.renderOrder=1;
    const emberMat = new THREE.ShaderMaterial({
      uniforms: { ...common, uLife: { value: 3.8 }, uRise: { value: 10.0 }, uWidth: { value: flameWidth*.9 }, uSize: { value: .2 },
        uSpread: { value: 4 }, uK: { value: 0.10 }, uOut: { value: 1.1 } },
      vertexShader: PARTICLE_VS, fragmentShader: EMBER_FS, transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending });
    const embers = new THREE.Points(seeds(110, 2000 + i), emberMat);
    const smokeMat = new THREE.ShaderMaterial({
      uniforms: { uTime: { value: 0 }, uScale: { value: 800 }, uOrigin: { value: c.clone() }, uNormal: { value: n },
        uRight: { value: right }, uLife: { value: 14 }, uRise: { value: 5.5 }, uR: { value: R }, uK: { value: this.k },
        uSize: { value: 23 }, uDensity: { value: 1 }, uSteam: { value: 0 }, uWind: { value: 1.65 },
        uWindDir: { value: new THREE.Vector3(0.8, 0, 0.35).normalize() }, uLit: { value: new THREE.Color(0.55, 0.22, 0.06) } },
      vertexShader: SMOKE_VS, fragmentShader: SMOKE_FS, transparent: true, depthWrite: false });
    const smoke = new THREE.Points(seeds(150, 3000 + i), smokeMat);
    smoke.renderOrder = 2;
    // الواجهة: سخام ونوافذ متوهجة من الداخل
    const decalPosition=(width,height,offset,rise=0)=>{
      const at=c.clone().addScaledVector(n,offset);
      if(support){
        const [x0,y0,x1,y1]=support.rect;
        if(support.alongY)at.z=-clamp(f.c[1],y0+width/2+.02,y1-width/2-.02);
        else at.x=clamp(f.c[0],x0+width/2+.02,x1-width/2-.02);
        at.y=clamp(f.c[2]+rise,height/2+.02,support.height-height/2-.02);
      }
      return at;
    };
    const sootW=Math.min(R*2,support?support.width-.1:R*2),sootH=Math.min(R*3,support?support.height-.1:R*3);
    const soot = new THREE.Mesh(new THREE.PlaneGeometry(sootW,sootH), new THREE.MeshBasicMaterial({
      map: sootTexture(4000 + i), transparent: true, depthWrite: false, polygonOffset: true, polygonOffsetFactor: -2 }));
    soot.position.copy(decalPosition(sootW,sootH,.12,R*.45));
    soot.name=`attached_soot_${f.id}`;
    soot.lookAt(soot.position.clone().add(n));
    const glowMat = new THREE.MeshBasicMaterial({ map: emberWindows(5000 + i), transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending, toneMapped: false, polygonOffset: true, polygonOffsetFactor: -3 });
    const glowW=Math.min(R*1.7,support?support.width-.1:R*1.7),glowH=Math.min(R*2.1,support?support.height-.1:R*2.1);
    const glow = new THREE.Mesh(new THREE.PlaneGeometry(glowW,glowH), glowMat);
    glow.position.copy(decalPosition(glowW,glowH,.15));glow.name=`attached_fire_glow_${f.id}`;
    glow.lookAt(glow.position.clone().add(n));
    // الضوء الملقى على المحيط
    const light = new THREE.PointLight(0xff6a1c, 0, Math.max(100, R * 8), 2);
    light.position.copy(c).addScaledVector(n, 5);
    light.userData.base = 3000 * I * (R / 15) * (R / 15);
    // القلب المحظور (H >= tau لهذا الحريق وحده): مجسم دوراني بمنحنى نصف القطر الدقيق
    const prof = [];
    const fk = { ...f, k: this.k };
    const below = -Math.sqrt(Math.max(0, R * R * Math.log(I / this.tau))) / 2;
    const top = f.Hf * Math.log(I / this.tau);
    const N = 48;
    prof.push(new THREE.Vector2(0, below));
    for (let j = 0; j <= N; j++) {
      const dz = below + (top - below) * j / N;
      prof.push(new THREE.Vector2(Math.max(0.01, coreRadius(fk, dz, this.tau)), dz));
    }
    prof.push(new THREE.Vector2(0, top));
    const coreMat = new THREE.ShaderMaterial({
      uniforms: { uOpacity: { value: 1 }, uTime: { value: 0 } },
      vertexShader: `varying vec3 vN; varying vec3 vV; void main(){ vec4 w = modelMatrix * vec4(position,1.);
        vN = normalize(mat3(modelMatrix) * normal); vV = normalize(cameraPosition - w.xyz); gl_Position = projectionMatrix * viewMatrix * w; }`,
      fragmentShader: `uniform float uOpacity, uTime; varying vec3 vN; varying vec3 vV;
        void main(){ float f = 1.0 - abs(dot(vN, vV)); float a = (0.025 + 0.22 * pow(f, 3.0)) * uOpacity * (0.9 + 0.1 * sin(uTime * 3.0));
        gl_FragColor = vec4(vec3(1.0, 0.16, 0.12) * 0.55, a); }`,
      transparent: true, depthWrite: false, side: THREE.FrontSide });
    const core = new THREE.Mesh(new THREE.LatheGeometry(prof, 48), coreMat);
    core.position.copy(c);
    core.renderOrder = 3;
    core.name = `core_${i}`;
    // انفجار الكبسولة (مسحوق)
    const burstMat = new THREE.ShaderMaterial({ uniforms: { uAge: { value: 0 }, uScale: { value: 800 },
      uOrigin: { value: c.clone().addScaledVector(n, 1) }, uNormal: { value: n } },
      vertexShader: BURST_VS, fragmentShader: BURST_FS, transparent: true, depthWrite: false });
    const burst = new THREE.Points(seeds(500, 6000 + i), burstMat);
    burst.visible = false;
    this.group.add(flames, embers, smoke, soot, glow, light, burst);
    const item = { f, i, c, n, flames, embers, smoke, soot, glow, light, core, burst, tEnd: Infinity, crew: null,
      mats: [flameMat, emberMat, smokeMat] };
    if (f.handled_by === 'ground') this.addGroundCrew(item, city);
    return item;
  }

  // شاحنة إطفاء بسلم مرفوع نحو حريق منخفض؛ ترش الماء وتطفئ الحريق.
  addGroundCrew(item, city) {
    const { c, n } = item;
    const base = c.clone().addScaledVector(n, 16); base.y = 0;
    const g = new THREE.Group();
    const red = new THREE.MeshStandardMaterial({ color: 0xb3120f, roughness: 0.4, metalness: 0.3 });
    const steel = new THREE.MeshStandardMaterial({ color: 0xc3c7cc, roughness: 0.35, metalness: 0.8 });
    const body = new THREE.Mesh(new RoundedBoxGeometry(9.5, 2.8, 2.6, 2, 0.18), red); body.position.y = 1.9;
    g.add(body);
    g.position.copy(base);
    g.lookAt(base.clone().add(new THREE.Vector3(n.z, 0, -n.x)));
    this.group.add(g);
    const tip = c.clone().addScaledVector(n, 7).add(new THREE.Vector3(0, -2, 0));
    const from = base.clone().add(new THREE.Vector3(0, 3.6, 0));
    const len = from.distanceTo(tip);
    const ladder = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.5, len), steel);
    ladder.position.copy(from).lerp(tip, 0.5);
    ladder.lookAt(tip);
    this.group.add(ladder);
    const waterMat = new THREE.ShaderMaterial({ uniforms: { uTime: { value: 0 }, uScale: { value: 800 }, uOn: { value: 1 },
      uFrom: { value: tip.clone() }, uTo: { value: c.clone().addScaledVector(n, 0.5) } },
      vertexShader: WATER_VS, fragmentShader: WATER_FS, transparent: true, depthWrite: false });
    const water = new THREE.Points(seeds(400, 7000 + item.i), waterMat);
    this.group.add(water);
    item.crew = { water, waterMat };
    item.tEnd = 28;                       // يحتاج فريق الأرض نحو نصف دقيقة
  }

  // زمن إصابة الكبسولة للحريق ذي هذا المعرف (Infinity = يبقى مشتعلًا)
  setExtinguishTime(id, t) {
    const it = this.items.find(x => x.f.id === id);
    if (it && !it.crew) it.tEnd = t;
  }

  intensityAt(it, t) { return t < it.tEnd ? 1 : 1 - smooth(clamp((t - it.tEnd) / 6, 0, 1)); }

  // حرائق نموذج التخطيط لقراءات الخطر (مشتعلة دائمًا كما افترضت الخوارزميات)
  modelFires() { return this.items.map(it => ({ c: it.f.c, R: it.f.R, I: it.f.I, Hf: it.f.Hf })); }

  update(time, t, scale) {
    for (const it of this.items) {
      const k = this.intensityAt(it, t);
      for (const m of it.mats) { m.uniforms.uTime.value = time; m.uniforms.uScale.value = scale; }
      it.mats[0].uniforms.uIntensity.value = k;
      it.mats[1].uniforms.uIntensity.value = k;
      const sm = it.mats[2].uniforms;
      const after = t - it.tEnd;
      sm.uSteam.value = after > 0 ? clamp(after / 4, 0, 1) : 0;
      sm.uDensity.value = after > 0 ? 0.76 * Math.max(0, 1 - after / 30) : 1;
      it.flames.visible = it.embers.visible = k > 0.01;
      it.smoke.visible = sm.uDensity.value > 0.01;
      const flick=.92+.045*Math.sin(time*7.2+it.i)+.035*Math.sin(time*11.1+2*it.i);
      it.light.intensity = it.light.userData.base * k * flick;
      it.glow.material.opacity = k * (.12 + .12 * flick);
      // تمثل هذه الطبقة الحقل الثابت المستخدم أثناء التخطيط؛ ويجب
      // ألا يمحو مشهد الإطفاء التوضيحي قيده.
      it.core.material.uniforms.uOpacity.value = 1;
      it.core.material.uniforms.uTime.value = time;
      it.core.visible = true;
      it.burst.visible = !it.crew && after > 0 && after < 5;
      if (it.burst.visible) { it.burst.material.uniforms.uAge.value = after; it.burst.material.uniforms.uScale.value = scale; }
      if (it.crew) {
        const wu = it.crew.waterMat.uniforms;
        wu.uTime.value = time; wu.uScale.value = scale;
        wu.uOn.value = t > 3 && t < it.tEnd + 4 ? 1 : 0;
        it.crew.water.visible = wu.uOn.value > 0;
      }
    }
  }

  count(t) {
    const drone = this.items.filter(it => !it.crew);
    return { total: this.items.length, out: this.items.filter(it => t >= it.tEnd + 3).length,
      drone: drone.length, droneOut: drone.filter(it => t >= it.tEnd + 3).length };
  }
}
