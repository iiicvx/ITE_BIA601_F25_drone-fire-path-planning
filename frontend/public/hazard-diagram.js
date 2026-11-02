// مقطع تحليلي لحريق منفرد، لا مثلث متسع مرسوم يدويًا.
import { hazardAt } from './scene/js/util.js';
import { t } from './content.js?v=viewport-20261018';
import { EXAMPLE_FIRE,sectionCurve,diagramMetrics } from './hazard-math.js';
export function renderHazardDiagram(){
  const svg=document.getElementById('hazardSection'),facts=document.getElementById('hazardFacts');
  if(!svg)return;
  const f=EXAMPLE_FIRE,scale=3.5,X=x=>200+x*scale,Y=z=>380-(z+20)*scale;
  const image=document.createElement('canvas');image.width=150;image.height=300;
  const ctx=image.getContext('2d'),pixels=ctx.createImageData(image.width,image.height);
  for(let y=0;y<image.height;y++)for(let x=0;x<image.width;x++){
    const H=hazardAt([50*x/(image.width-1),0,80-100*y/(image.height-1)],[f],f.k);
    const a=Math.min(1,H*1.6),i=(y*image.width+x)*4;
    const color=H>=.5?[182,67,56]:[207,130,71];
    pixels.data[i]=color[0];pixels.data[i+1]=color[1];pixels.data[i+2]=color[2];pixels.data[i+3]=Math.round(a*200);
  }
  ctx.putImageData(pixels,0,0);
  const curve=sectionCurve(f),boundary=`M${X(0)},${Y(curve[0][1])}`+curve.map(([r,z])=>`L${X(r).toFixed(3)},${Y(z).toFixed(3)}`).join('')+`L${X(0)},${Y(curve.at(-1)[1])}Z`;
  const metric=diagramMetrics(),sigma=f.R+f.k*30;
  let ticks='';
  for(const z of [-20,0,20,40,60,80])ticks+=`<line x1="190" x2="380" y1="${Y(z)}" y2="${Y(z)}" stroke="#4c5963" stroke-opacity=".35"/><text x="182" y="${Y(z)+4}" text-anchor="end">${z}</text>`;
  for(const x of [0,15,30,45])ticks+=`<text x="${X(x)}" y="402" text-anchor="middle">${x}</text>`;
  svg.setAttribute('viewBox','0 0 640 450');
  svg.setAttribute('direction','ltr');
  svg.innerHTML=`<defs><pattern id="hazardWall" width="20" height="24" patternUnits="userSpaceOnUse"><rect width="20" height="24" fill="#243341"/><rect x="4" y="4" width="11" height="14" fill="#101c27"/></pattern></defs>
    <rect x="45" y="30" width="155" height="350" fill="url(#hazardWall)"/>
    <image href="${image.toDataURL()}" x="200" y="30" width="175" height="350" preserveAspectRatio="none"/>
    ${ticks}<path id="hazardCoreContour" d="${boundary}" fill="#e66e58" fill-opacity=".22" stroke="#ffc0a5" stroke-width="1.8"/>
    <line x1="200" x2="200" y1="30" y2="380" stroke="#aec4d6" stroke-width="2"/>
    <circle cx="200" cy="${Y(0)}" r="5" fill="#ff9b50"/>
    <line x1="200" x2="${X(sigma)}" y1="${Y(30)}" y2="${Y(30)}" stroke="#d7e7f2" stroke-dasharray="4 3"/>
    <path d="M${X(13)},${Y(14)}H392L402 280" fill="none" stroke="#f7b99c"/>
    <text x="408" y="294">${t('hazard.figCore')}</text>
    <text x="408" y="334" direction="ltr">H ≥ 0.5</text>
    <text x="408" y="${Y(30)-7}">${t('hazard.figSigma')}</text>
    <text x="408" y="238" direction="ltr">σ(30) = ${sigma.toFixed(1)} m</text>
    <text x="408" y="78">${t('hazard.figExposure')}</text>
    <text x="408" y="118" direction="ltr">0 ≤ H &lt; 0.5</text>
    <rect x="55" y="318" width="135" height="42" rx="5" fill="#142330"/>
    <text x="122" y="347" text-anchor="middle">${t('hazard.figFacade')}</text>
    <text x="289" y="435" text-anchor="middle">${t('hazard.figDistance')}</text>
    <text x="26" y="205" transform="rotate(-90 26 205)" text-anchor="middle">${t('hazard.figHeight')}</text>`;
  svg.dataset.radius=metric.radius;svg.dataset.coreTop=metric.top;
  facts.innerHTML=`<div><dt>${t('hazard.radiusLabel')}</dt><dd>${metric.radius.toFixed(2)} م</dd></div><div><dt>${t('hazard.topLabel')}</dt><dd>${metric.top.toFixed(2)} م</dd></div>`;
}
