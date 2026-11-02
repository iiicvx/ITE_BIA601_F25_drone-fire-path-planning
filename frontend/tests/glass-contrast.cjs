// حل فحوص التباين الخاصة بأداة axe للخلفيات المتدرجة وخلفيات SVG باستقلال عبر البكسلات.
// يُخفى النص دون إزالة تخطيطه أو سطحه، ثم تُؤخذ عينات من الخلفية الحقيقية
// تحت كل مقطع نصي. ويجب أن تستوفي المراجعة الناجحة معيار WCAG AA.
const { PNG } = require('pngjs');
const linear = value => { const n=value/255;return n<=.04045?n/12.92:((n+.055)/1.055)**2.4; };
const luminance = (r,g,b) => .2126*linear(r)+.7152*linear(g)+.0722*linear(b);
const linearByte=Array.from({length:256},(_,i)=>linear(i));

module.exports = async function measureGlassContrast(page, findings, allSections=false) {
  const selectors=[...new Set(findings.filter(f=>f.rule==='text-contrast').map(f=>f.selector))];
  if(!selectors.length)return {samples:0,checks:[],failures:[]};
  const savedScroll=await page.evaluate(()=>({x:scrollX,y:scrollY}));
  const samples=await page.evaluate(selectors=>{
    window.__viewers?.forEach(v=>{
      v.__auditFrame=v.frame;v.frame=()=>{};
      v.__auditEnabled=v.loop?.enabled;v.loop?.setEnabled(false);
    });
    if(window.__ambientDrone){window.__ambientDrone.__auditPaused=window.__ambientDrone.paused;window.__ambientDrone.setPaused(true);}
    const samples=[];
    for(const selector of selectors){
      const node=document.querySelector(selector);if(!node)continue;
      const style=getComputedStyle(node),color=node instanceof SVGElement?style.fill:style.color;
      const rgba=color.match(/[\d.]+/g)?.map(Number);if(!rgba||rgba.length<3)continue;
      let opacity=1;for(let p=node;p;p=p.parentElement)opacity*=Number(getComputedStyle(p).opacity);
      const alpha=(rgba[3]??1)*opacity;
      const probe=String(samples.length);node.dataset.contrastProbe=probe;
      samples.push({selector,probe,rgba:[...rgba.slice(0,3),alpha],required:parseFloat(style.fontSize)>=24||(parseFloat(style.fontWeight)>=700&&parseFloat(style.fontSize)>=18.666)?3:4.5});
      node.classList.add('pixel-contrast-sample');
    }
    return samples;
  },selectors);
  const mask=await page.addStyleTag({content:'.pixel-contrast-sample,.pixel-contrast-sample *{color:transparent!important;-webkit-text-fill-color:transparent!important;text-shadow:none!important}.pixel-contrast-sample:is(text,tspan){fill:transparent!important}'});
  const results=samples.map(sample=>({...sample,ratio:Infinity,pixels:0}));
  async function capture() {
    const rects=await page.evaluate(probes=>{
      const header=document.querySelector('.topbar-inner')?.getBoundingClientRect();
      return probes.map(probe=>{
        const node=document.querySelector(`[data-contrast-probe="${probe}"]`);if(!node||!node.checkVisibility({visibilityProperty:true}))return [];
        const boxes=[];
        for(const text of node.childNodes){
          if(text.nodeType!==Node.TEXT_NODE||!text.textContent.trim())continue;
          const range=document.createRange();range.selectNodeContents(text);
          for(const rect of range.getClientRects()){
            let left=Math.max(0,rect.left),right=Math.min(innerWidth,rect.right),top=Math.max(0,rect.top),bottom=Math.min(innerHeight,rect.bottom);
            if(header&&!node.closest('.topbar')&&top<header.bottom)top=header.bottom;
            for(let parent=node.parentElement;parent;parent=parent.parentElement){
              const style=getComputedStyle(parent),bounds=parent.getBoundingClientRect();
              if(/hidden|clip|auto|scroll/.test(style.overflowX)){left=Math.max(left,bounds.left);right=Math.min(right,bounds.right);}
              if(/hidden|clip|auto|scroll/.test(style.overflowY)&&parent!==document.body&&parent!==document.documentElement){top=Math.max(top,bounds.top);bottom=Math.min(bottom,bounds.bottom);}
            }
            if(right>left&&bottom>top)boxes.push({left,right,top,bottom});
          }
        }
        return boxes;
      });
    },samples.map(sample=>sample.probe));
    const image=PNG.sync.read(await page.screenshot({timeout:90000}));
    for(let i=0;i<results.length;i++){
      const result=results[i],[fr,fg,fb,alpha]=result.rgba;
      const opaqueFore=alpha===1?luminance(fr,fg,fb):null;
      for(const rect of rects[i])for(let y=Math.max(0,Math.ceil(rect.top));y<Math.min(image.height,Math.floor(rect.bottom));y++){
        for(let x=Math.max(0,Math.ceil(rect.left));x<Math.min(image.width,Math.floor(rect.right));x++){
          const index=(y*image.width+x)*4,br=image.data[index],bg=image.data[index+1],bb=image.data[index+2];
          const back=.2126*linearByte[br]+.7152*linearByte[bg]+.0722*linearByte[bb],fore=opaqueFore??luminance(fr*alpha+br*(1-alpha),fg*alpha+bg*(1-alpha),fb*alpha+bb*(1-alpha));
          result.ratio=Math.min(result.ratio,(Math.max(back,fore)+.05)/(Math.min(back,fore)+.05));result.pixels++;
        }
      }
    }
  }
  try {
    if(allSections){
      const height=await page.evaluate(()=>document.documentElement.scrollHeight),step=page.viewportSize().height*.8;
      for(let top=0;top<height;top+=step){
        await page.evaluate(top=>window.scrollTo({top,behavior:'instant'}),top);
        await capture();
      }
      // زيارة بطاقات الخوارزميات الممررة أفقيًا كذلك، بدل معاملة
      // محتوى العرض الدوار خارج الشاشة كأنه قيس.
      for(const result of results.filter(result=>!result.pixels)){
        await page.locator(`[data-contrast-probe="${result.probe}"]`).evaluate(node=>node.scrollIntoView({block:'center',inline:'nearest',behavior:'instant'}));
        await capture();
      }
    } else await capture();
  } finally {
    await mask.evaluate(node=>node.remove());
    await page.evaluate(scroll=>{
      document.querySelectorAll('.pixel-contrast-sample').forEach(node=>{node.classList.remove('pixel-contrast-sample');delete node.dataset.contrastProbe;});
      window.__viewers?.forEach(v=>{
        if(v.__auditFrame){v.frame=v.__auditFrame;delete v.__auditFrame;}
        if(v.__auditEnabled!==undefined){v.loop.setEnabled(v.__auditEnabled);delete v.__auditEnabled;}
      });
      if(window.__ambientDrone){window.__ambientDrone.setPaused(window.__ambientDrone.__auditPaused);delete window.__ambientDrone.__auditPaused;}
      window.scrollTo({...scroll,left:scroll.x,top:scroll.y,behavior:'instant'});
    },savedScroll);
  }
  const checks=results.filter(result=>result.pixels).map(({selector,ratio,required,pixels})=>({selector,ratio:+ratio.toFixed(3),required,pixels}));
  return {samples:checks.length,checks,failures:checks.filter(check=>check.ratio+.01<check.required),unmeasured:results.filter(result=>!result.pixels).map(result=>result.selector)};
};
