// تكييف بلغة JavaScript المجردة لمكون EasyUI LiquidToggle، بترخيص MIT (c) 2026 Suraj Maurya.
// المصدر: https://easyui.site/source/liquid-toggle.json
// أُبقيت هندسة الكتلة التربيعية ذات النقاط الاثنتي عشرة وثوابت النابض الأصلية.
// استُبدل دمج React/Framer Motion بنابض requestAnimationFrame قابل للمقاطعة.
import { t } from './content.js?v=viewport-20261018';

let tooltipId=0;
const tooltips=new WeakMap();
export function attachTooltip(button, text) {
  if(tooltips.has(button))return;
  const tip=document.createElement('span');tip.className='control-tooltip';tip.id=`control-tip-${++tooltipId}`;
  tip.role='tooltip';tip.hidden=true;tip.textContent=text;document.body.append(tip);
  button.setAttribute('aria-describedby',tip.id);
  const hide=()=>{tip.hidden=true;};
  const show=()=>{
    tip.hidden=false;
    const box=button.getBoundingClientRect(),width=tip.offsetWidth,height=tip.offsetHeight;
    tip.style.left=`${Math.max(12,Math.min(innerWidth-width-12,box.left+(box.width-width)/2))}px`;
    tip.style.top=`${box.top>height+12?box.top-height-8:box.bottom+8}px`;
  };
  button.addEventListener('pointerenter',show);button.addEventListener('pointerleave',hide);
  button.addEventListener('focus',show);button.addEventListener('blur',hide);button.addEventListener('click',hide);
  addEventListener('scroll',hide,{passive:true});tooltips.set(button,tip);
}

export const controlIcon = path => `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${path}"/></svg>`;

function buildBlobPath(width, height, t, stretch) {
  const padding = 4, radius = (height - padding * 2) / 2;
  const left = padding + radius, right = width - padding - radius;
  const cx = left + (right - left) * t, cy = height / 2, points = [];
  for (let i = 0; i < 12; i++) {
    const a = Math.PI * 2 * i / 12 - Math.PI / 2;
    const wobble = 1 + stretch * .18 * Math.sin(a * 3 + t * Math.PI * 2);
    points.push([cx + Math.cos(a) * radius * (1 + stretch * .35) * wobble,
      cy + Math.sin(a) * radius * (1 - stretch * .12) * wobble]);
  }
  const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  let d = `M ${mid(points[11], points[0]).join(' ')}`;
  for (let i = 0; i < 12; i++) d += ` Q ${points[i].join(' ')} ${mid(points[i], points[(i + 1) % 12]).join(' ')}`;
  return d + ' Z';
}

export function liquidToggle(key, label, value, onChange) {
  const button = document.createElement('button');
  button.type = 'button'; button.className = 'liquid-option'; button.role = 'switch';
  button.setAttribute('aria-label', label); button.dataset.option = key;
  button.innerHTML = `<span>${label}</span><svg viewBox="0 0 56 32" aria-hidden="true"><rect x=".5" y=".5" width="55" height="31" rx="16"/><path/></svg>`;
  const path = button.querySelector('path');
  let current = value ? 1 : 0, velocity = 0, target = current, frame = null;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  function paint() { path.setAttribute('d', buildBlobPath(56, 32, current, Math.min(1, Math.abs(velocity) * .06))); }
  function animate() {
    // خطوات فرعية صغيرة ثابتة تُبقي النابض القاسي مستقرًا حتى مع معدل إطارات منخفض.
    for (let i = 0; i < 4; i++) {
      const dt = 1 / 240;
      velocity += ((target - current) * 280 - velocity * 24) / .55 * dt;
      current += velocity * dt;
    }
    paint();
    if (Math.abs(target - current) > .001 || Math.abs(velocity) > .01) frame = requestAnimationFrame(animate);
    else { current = target; velocity = 0; frame = null; paint(); }
  }
  function set(next, notify = true) {
    value = next; target = next ? 1 : 0;
    button.setAttribute('aria-checked', String(value));
    button.title = `${label}: ${t(value ? 'workspace.on' : 'workspace.off')}`;
    if (reduced) { current = target; paint(); }
    else if (frame === null) frame = requestAnimationFrame(animate);
    if (notify) onChange(value);
  }
  button.onclick = () => set(!value);
  button.onkeydown = (event) => {
    if (['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp'].includes(event.key)) {
      event.preventDefault(); set(['ArrowRight', 'ArrowDown'].includes(event.key));
    }
  };
  set(value, false); paint();
  return { element: button, set };
}
