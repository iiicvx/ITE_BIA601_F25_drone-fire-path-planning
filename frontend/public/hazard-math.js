// مقطع تحليلي للحقل نفسه لحريق منفرد الذي يستخدمه المُحسِّن.
import { coreRadius } from './scene/js/util.js';
export const EXAMPLE_FIRE=Object.freeze({c:[0,0,0],R:15,I:1,Hf:80,k:.25});
export function sectionCurve(f,threshold=.5){
  if(!(f.I>threshold))return [];
  const log=Math.log(f.I/threshold),bottom=-f.R*Math.sqrt(log)/2,top=f.Hf*log;
  const heights=[0,...Array.from({length:81},(_,i)=>bottom+(top-bottom)*i/80)];
  return [...new Set(heights)].sort((a,b)=>a-b).map(z=>[coreRadius(f,z,threshold),z]);
}
export function diagramMetrics(f=EXAMPLE_FIRE,threshold=.5){
  const log=Math.max(0,Math.log(f.I/threshold));
  return {radius:f.R*Math.sqrt(log),top:f.Hf*log,bottom:-f.R*Math.sqrt(log)/2};
}
