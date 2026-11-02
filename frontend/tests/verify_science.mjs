import assert from 'node:assert/strict';
import * as THREE from '../public/scene/vendor/three/three.module.js';
import { convergenceSeries,stepPath,barPercent,relativeGap,duration } from '../public/chart-data.js';
import { EXAMPLE_FIRE,sectionCurve,diagramMetrics } from '../public/hazard-math.js';
import { hazardAt } from '../public/scene/js/util.js';
import { surroundingGroundGeometry } from '../public/scene/js/city.js';

const series=convergenceSeries([[[1,8],[3,4],[10,2]],[[1,10],[5,6],[10,4]]],10);
assert.deepEqual(series,[[1,9],[3,7],[5,5],[10,3]]);
assert.equal(stepPath(series,x=>x,y=>y),'M1.00,9.00H3.00V7.00H5.00V5.00H10.00V3.00');
assert.deepEqual(convergenceSeries([[[1,1.6]]],100),[[1,1.6],[100,1.6]]);
assert.throws(()=>convergenceSeries([[[1,2],[5,3]]],10));
assert.equal(barPercent(.04,400),.01);assert.equal(relativeGap(1.5,2),-25);assert.equal(relativeGap(1,0),null);
assert.equal(duration(.0417),'0.042');assert.equal(duration(null),'—');
const metrics=diagramMetrics();
assert.ok(Math.abs(metrics.radius-15*Math.sqrt(Math.log(2)))<1e-12);
assert.ok(Math.abs(metrics.top-80*Math.log(2))<1e-12);
let boundaryError=0;
for(const [radius,z] of sectionCurve(EXAMPLE_FIRE)){
  const H=hazardAt([radius,0,z],[EXAMPLE_FIRE],EXAMPLE_FIRE.k);
  boundaryError=Math.max(boundaryError,Math.abs(H-.5));
  assert.ok(Math.abs(H-.5)<1e-12);
}
let groundSamples=0;
for(const W of [300,600,1000]){
  const outer=new THREE.Mesh(surroundingGroundGeometry(W),new THREE.MeshBasicMaterial({side:THREE.DoubleSide}));
  const inner=new THREE.Mesh(new THREE.PlaneGeometry(W,W).rotateX(-Math.PI/2).translate(W/2,0,-W/2),new THREE.MeshBasicMaterial({side:THREE.DoubleSide}));
  outer.updateMatrixWorld();inner.updateMatrixWorld();
  for(const x of [-20,.71,W/3,W-.71,W+20])for(const y of [-20,1.37,W/2,W-1.37,W+20]){
    const ray=new THREE.Raycaster(new THREE.Vector3(x,50,-y),new THREE.Vector3(0,-1,0));
    const hits=ray.intersectObjects([inner,outer]);
    assert.equal(new Set(hits.map(hit=>hit.object)).size,1,`overlapping or missing terrain at ${W}:${x},${y}`);groundSamples++;
  }
}
console.log(JSON.stringify({passed:true,boundaryError,coreRadius:metrics.radius,coreHeight:metrics.top,groundSamples,exactStepChart:true,section:sectionCurve(EXAMPLE_FIRE)}));
