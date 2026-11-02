// يستخدمه backend/tests/test_site.py: يقيّم نموذج المشهد على مدخلات يكتبها الاختبار
// ويطبع النتائج بصيغة JSON، لتقارنها Python بنموذج المشروع نفسه.
//   node frontend/tests/scene_check.mjs <input.json>
import { readFileSync } from 'node:fs';
import { hazardAt, Flight, nearestTower, coreRadius } from '../public/scene/js/util.js';
import { roadNetwork } from '../public/scene/js/city.js';

const inp = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const out = {};
out.hazard = inp.points.map(p => hazardAt(p, inp.fires, inp.k));
out.flight = inp.flights.map(f => { const fl = new Flight(f.path, f.speed); return { duration: fl.duration, pos: f.times.map(t => fl.at(t).pos) }; });
out.tower = inp.points.map(p => nearestTower(p, inp.buildings));
out.core = inp.core.map(c => coreRadius({ ...c.fire, k: inp.k }, c.dz, inp.tau));
out.roads = inp.cities.map(c => roadNetwork(c).roads);
console.log(JSON.stringify(out));
