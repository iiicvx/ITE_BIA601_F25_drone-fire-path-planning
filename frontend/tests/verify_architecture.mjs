// تحقق هندسي دون واجهة من مولد المعمار نفسه المستخدم في الإنتاج.
// تُحاكى اللوحة فقط على مستوى واجهة الرسم الثنائية؛ وكل الهندسة ثلاثية الأبعاد Three.js حقيقية.
import fs from 'node:fs';
import assert from 'node:assert/strict';
import * as THREE from '../public/scene/vendor/three/three.module.js';
import { buildArchitecturalCity,exteriorSurfaces } from '../public/scene/js/architecture.js';
class Paint {
  fillRect(){}clearRect(){}strokeRect(){}beginPath(){}closePath(){}arc(){}fill(){}stroke(){}moveTo(){}lineTo(){}
  fillText(){}rect(){}roundRect(){}setLineDash(){}save(){}restore(){}translate(){}rotate(){}scale(){}
  createLinearGradient(){return {addColorStop(){}}}
  createRadialGradient(){return {addColorStop(){}}}
}
globalThis.document={createElement(type){if(type!=='canvas')throw Error('Unexpected '+type);return {width:0,height:0,getContext(){return new Paint()}}}};
let total=0, maxOvershoot=0,checkedPatches=0;
function verifyShell(volumes){
  const inside=([x,y,z])=>volumes.some(v=>x>v.rect[0]&&x<v.rect[2]&&y>v.rect[1]&&y<v.rect[3]&&z>v.z0&&z<v.z1);
  const faces=exteriorSurfaces(volumes);
  for(const f of faces){
    const u=(f.u0+f.u1)/2,v=(f.v0+f.v1)/2;
    const point=f.axis==='x'?[f.plane,u,v]:f.axis==='y'?[u,f.plane,v]:[u,v,f.plane];
    const axis={x:0,y:1,z:2}[f.axis],outer=[...point],inner=[...point];outer[axis]+=f.sign*1e-5;inner[axis]-=f.sign*1e-5;
    assert.equal(inside(outer),false,`interior/covered surface was emitted: ${JSON.stringify({f,outer,volumes})}`);assert.equal(inside(inner),true,'surface has no supporting solid');checkedPatches++;
  }
  for(let i=0;i<faces.length;i++)for(let j=i+1;j<faces.length;j++){
    const a=faces[i],b=faces[j];if(a.axis!==b.axis||a.plane!==b.plane)continue;
    const overlapU=Math.min(a.u1,b.u1)-Math.max(a.u0,b.u0),overlapV=Math.min(a.v1,b.v1)-Math.max(a.v0,b.v0);
    assert.ok(overlapU<1e-7||overlapV<1e-7,'duplicate coplanar exterior patches (depth fighting)');
  }
  return faces;
}
const fixture=verifyShell([{rect:[0,0,10,10],z0:0,z1:10},{rect:[8,0,18,10],z0:0,z1:10}]);
assert.equal(fixture.filter(f=>f.axis==='z').reduce((sum,f)=>sum+(f.u1-f.u0)*(f.v1-f.v0),0),180,'overlapping roof counted twice');
for(const cityName of ['small','medium','large','fleet/small','fleet/medium','fleet/large']) {
 const city=JSON.parse(fs.readFileSync(new URL(`../../simulation/scenarios/${cityName}.json`,import.meta.url),'utf8'));
 const group=new THREE.Group(),anim=[];
 const {towers}=buildArchitecturalCity(group,city,city.seed*7919+city.buildings.length,anim);
 const geom=new THREE.Box3();
 const sig=new Set(),classes=new Set();
 let wrong=0,exceptions=[];
 for(let i=0;i<towers.length;i++){
  const b=city.buildings[i],tower=towers[i];
  verifyShell(tower.built.userData.visualVolumes);
  geom.setFromObject(tower.built);
  const ext=[b.x0-geom.min.x,geom.max.x-b.x1,(-b.y1)-geom.min.z,geom.max.z-(-b.y0),-geom.min.y,geom.max.y-b.h];
  const max = Math.max(...ext,0); maxOvershoot=Math.max(maxOvershoot,max);
  if (max>1e-4){wrong++;exceptions.push({i,ext});}
  if(Math.abs(geom.max.y-b.h)>0.25){wrong++;exceptions.push({i,height:geom.max.y,h:b.h});}
  if(!tower.signature)throw Error('No signature');
  sig.add(tower.signature);classes.add(tower.style);
 }
 assert.equal(sig.size,towers.length,'duplicate building identity');assert.ok(classes.size>=Math.min(8,towers.length),'insufficient architectural variety');
 console.log(JSON.stringify({cityName,n:towers.length,styles:classes.size,unique:sig.size,violations:wrong,sampleErrors:exceptions.slice(0,7)}));
 total+=towers.length;
 if(wrong)process.exitCode=1;
}
console.log(JSON.stringify({total,maxOvershoot,checkedPatches,nonOverlappingShell:true}));
