import * as THREE from '/scene/vendor/three/three.module.js';
import { loadDrone,DRONE_MODEL_URL } from '/scene/js/swarm.js';
import { ViewportLoop } from './viewport-loop.js';
import { AmbientPlacement } from './ambient-placement.js';

const canvas = document.getElementById('ambientDroneCanvas');
if (canvas) {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'low-power' });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.25));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setClearColor(0x000000, 0);
  renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.05;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 100);
  camera.position.set(0, 0.55, 6.4);

  const hemi = new THREE.HemisphereLight(0xc5d2dc, 0x05080b, 1.9);
  const key = new THREE.DirectionalLight(0xf1f5f8, 1.7);
  key.position.set(4.2, 5.1, 5.8);
  const fill = new THREE.DirectionalLight(0x8ea0af, 0.7);
  fill.position.set(-5.2, 2.4, 4.5);
  const rim = new THREE.DirectionalLight(0x6d7e8e, 0.8);
  rim.position.set(-3.8, 2.0, -4.5);
  scene.add(hemi, key, fill, rim);

  const root = new THREE.Group();
  scene.add(root);
  let paused=false, sizeDirty=true, drawFrame=null, loop=null;
  const placement = new AmbientPlacement(canvas, resized => {
    sizeDirty ||= resized;
    if (paused && !document.hidden && placement.needed) drawFrame?.(0);
    else loop?.invalidate();
  });

  // بيئة استوديو تصوير مدمجة تجعل المعدن والزجاج يعكسان
  // مصادر ضوء فعلية بدل أن يظهرا شبه أسودين على الخلفية الشفافة.
  const studio=new THREE.Scene();studio.background=new THREE.Color(0x24313b);
  const addPanel=(x,y,z,sx,sy,color)=>{
    const panel=new THREE.Mesh(new THREE.PlaneGeometry(sx,sy),new THREE.MeshBasicMaterial({color,side:THREE.DoubleSide}));
    panel.position.set(x,y,z);panel.lookAt(0,0,0);studio.add(panel);
  };
  addPanel(-3,3,2,3,4,0xc2d6e5);addPanel(4,1,1,2,4,0x798e9e);addPanel(0,4,-2,5,2,0xe5ecf2);
  const pmrem=new THREE.PMREMGenerator(renderer),environment=pmrem.fromScene(studio,.06);
  scene.environment=environment.texture;pmrem.dispose();
  studio.traverse(node=>{node.geometry?.dispose();node.material?.dispose();});

  loadDrone().then(template => {
    // القالب نفسه وهندسة الشبكة الثابتة نفسها المستخدمة في المحاكي.
    // لا جسم بديل، ولا أقراص مراوح مضافة، ولا تلوين جديد، ولا أذرع معدلة.
    const model = template.clone(true);
    const box = new THREE.Box3().setFromObject(model);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    model.position.sub(center);
    const scale = 3.35 / Math.max(size.x, size.y, size.z);
    const pivot=new THREE.Group();pivot.scale.setScalar(scale);pivot.rotation.set(.17,-.88,.025);
    pivot.add(model);
    model.traverse((o) => {
      if (o.isMesh) {
        o.castShadow = false;
        o.receiveShadow = false;
      }
    });
    root.add(pivot);
    // ملاءمة الجسم الثابت الأصلي بإحكام؛ دون تأثير منظور مع المؤشر ودون حركة للجسم.
    root.updateMatrixWorld(true);
    const samples = [];
    model.traverse(mesh => {
      if (!mesh.isMesh || !mesh.geometry || !mesh.visible) return;
      const positions = mesh.geometry.attributes.position;
      for (let i = 0; i < positions.count; i++) samples.push(new THREE.Vector3().fromBufferAttribute(positions, i).applyMatrix4(mesh.matrixWorld));
    });
    const point = new THREE.Vector3();
    const viewDirection = new THREE.Vector3(0, .085, 1).normalize();
    const viewUp = new THREE.Vector3(0, 1, -.085).normalize();

    const props = [];
    model.traverse((o) => { if (/^Prop_/i.test(o.name)) props.push(o); });
    let frames=0;
    const state={root,model,props,renderer,camera,placement,setPaused(value){paused=Boolean(value);loop.setEnabled(!paused);},get paused(){return paused;},
      info(){return {modelSource:DRONE_MODEL_URL,rotors:props.length,angles:props.map(prop=>prop.rotation.y),position:root.position.toArray(),frames,reduced,
        layout:placement.info(),scheduler:loop.info()};}};
    window.__ambientDrone=state;canvas.dataset.modelReady='true';

    function resize() {
      const w = Math.max(1, Math.round(placement.baseWidth));
      const h = Math.max(1, Math.round(placement.baseWidth / 1.9));
      renderer.setSize(w, h, false);
      camera.aspect = w / h;
      const tanV = Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2), tanH = tanV * camera.aspect;
      let distance = 1;
      for (const sample of samples) {
        point.copy(sample);
        distance = Math.max(distance, point.dot(viewDirection) + Math.max((Math.abs(point.x) + .1) / (tanH * .9), (Math.abs(point.dot(viewUp)) + .1) / (tanV * .9)));
      }
      camera.position.copy(viewDirection).multiplyScalar(distance * 1.04);
      camera.lookAt(0, 0, 0);
      camera.updateProjectionMatrix();
      sizeDirty=false;
    }

    function render(dt) {
      if (document.hidden || !placement.needed) return;
      if (sizeDirty) resize();
      if(!paused&&!reduced) for (const p of props) p.rotation.y=(p.rotation.y+(p.userData.spin||1)*70*dt)%(Math.PI*2);
      renderer.render(scene, camera);frames++;
    }
    drawFrame=render;
    loop=new ViewportLoop(canvas,{frame:render,ready:()=>placement.needed,continuous:()=>!reduced,maxFPS:24});
    state.loop=loop;placement.queue();
  }).catch(error=>console.warn('[ambient-drone] Model unavailable.',error));
}
