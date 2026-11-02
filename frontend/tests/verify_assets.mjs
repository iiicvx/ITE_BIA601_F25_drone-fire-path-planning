// انحدار هندسي: شبكات الإنتاج الفعلية، مع أشعة دعم مستقلة.
import fs from 'node:fs';
import assert from 'node:assert/strict';
import * as THREE from '../public/scene/vendor/three/three.module.js';
import { buildArchitecturalCity } from '../public/scene/js/architecture.js';
import { Fires } from '../public/scene/js/fire.js';
import { treeGeometries,carGeometries } from '../public/scene/js/city.js';
import { V } from '../public/scene/js/util.js';

class Paint{
  fillRect(){}clearRect(){}beginPath(){}closePath(){}arc(){}ellipse(){}fill(){}stroke(){}moveTo(){}lineTo(){}fillText(){}
  roundRect(){}setLineDash(){}save(){}restore(){}translate(){}rotate(){}scale(){}
  createLinearGradient(){return {addColorStop(){}}}createRadialGradient(){return {addColorStop(){}}}
}
globalThis.document={createElement(){return {width:0,height:0,getContext(){return new Paint()}}}};
const report={buildings:0,groundedFireWings:0,backedFireDecals:0,roofPads:0,failures:[]};
for(const name of ['small','medium','large','fleet/small','fleet/medium','fleet/large']){
  const city=JSON.parse(fs.readFileSync(new URL(`../../simulation/scenarios/${name}.json`,import.meta.url),'utf8'));
  const scene=new THREE.Scene(),group=new THREE.Group();scene.add(group);
  const {towers}=buildArchitecturalCity(group,city,(city.seed_used||city.seed)*7919+city.buildings.length,[]);
  const fires=new Fires(scene,city);scene.updateMatrixWorld(true);
  for(const item of fires.items){
    const tower=towers.find(t=>t.id===item.f.building);
    const wing=tower.built.getObjectByName(`fire_facade_${tower.id}_${item.f.id}`);
    assert.ok(wing?.isMesh,`${name}: no solid backing for fire ${item.f.id}`);
    const bounds=new THREE.Box3().setFromObject(wing);
    assert.ok(Math.abs(bounds.min.y)<1e-5,`${name}: fire facade does not reach the ground`);
    assert.ok(bounds.max.y>=item.f.c[2],`${name}: facade ends below its fire`);
    const n=V(item.f.normal[0],item.f.normal[1],0).normalize(),origin=V(...item.f.c).addScaledVector(n,.6);
    const hits=new THREE.Raycaster(origin,n.clone().negate(),0,1).intersectObject(wing);
    assert.ok(hits.length&&Math.abs(hits[0].distance-.6)<1e-4,`${name}: fire does not meet a real facade`);
    report.groundedFireWings++;
    for(const [mesh,offset] of [[item.soot,.12],[item.glow,.15]]){
      const points=mesh.geometry.attributes.position;
      for(let i=0;i<points.count;i++){
        const point=new THREE.Vector3().fromBufferAttribute(points,i).applyMatrix4(mesh.matrixWorld).addScaledVector(n,-offset-.01);
        assert.ok(bounds.containsPoint(point),`${name}: ${mesh.name} floats beyond its supporting facade`);
      }
      report.backedFireDecals++;
    }
  }
  for(const tower of towers){
    report.buildings++;
    const pad=tower.built.getObjectByName('rooftop_helipad');if(!pad)continue;
    const roofs=tower.built.children.filter(mesh=>mesh!==pad&&mesh.isMesh);
    const points=pad.geometry.attributes.position;
    for(let i=0;i<points.count;i++){
      const p=new THREE.Vector3().fromBufferAttribute(points,i).applyMatrix4(pad.matrixWorld).add(new THREE.Vector3(0,.1,0));
      const hit=new THREE.Raycaster(p,new THREE.Vector3(0,-1,0),0,.3).intersectObjects(roofs)[0];
      assert.ok(hit,`${name}: rooftop pad has an unsupported corner`);
    }
    report.roofPads++;
  }
}
const tree=treeGeometries();tree.trunk.computeBoundingBox();
assert.ok(Math.abs(tree.trunk.boundingBox.min.y)<1e-6,'tree trunk is not grounded');
assert.ok(Number.isFinite(tree.maxHeight)&&tree.maxHeight<8,'canopy exceeds the scale envelope');
const car=carGeometries(),vehicle=new THREE.Group();
for(const geometry of Object.values(car))vehicle.add(new THREE.Mesh(geometry,new THREE.MeshBasicMaterial()));
const bounds=new THREE.Box3().setFromObject(vehicle);
assert.ok(Math.abs(bounds.min.y)<1e-6,'car wheels do not touch ground');
assert.ok(bounds.max.y<2.1,'car height is outside the intended street scale');
report.treeBase=tree.trunk.boundingBox.min.y;report.carGroundClearance=bounds.min.y;
report.passed=true;
fs.writeFileSync(new URL('../results/assets-audit.json',import.meta.url),JSON.stringify(report,null,2));
console.log(JSON.stringify(report,null,2));
