const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');

(async()=>{
  const browser=await chromium.launch({args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1});
  page.setDefaultTimeout(90000);
  const capture=async file=>{
    await page.evaluate(()=>{
      window.__captureVisibility=window.__viewers.map(v=>v.loop.enabled);for(const v of window.__viewers)v.loop.setEnabled(false);
      window.__captureAmbientPaused=window.__ambientDrone.paused;window.__ambientDrone.setPaused(true);
    });
    try{await page.screenshot({path:path.join(__dirname,'../results',file),timeout:90000});}
    finally{await page.evaluate(()=>{window.__viewers.forEach((v,i)=>v.loop.setEnabled(window.__captureVisibility[i]));window.__ambientDrone.setPaused(window.__captureAmbientPaused);});}
  };
  const errors=[],consoleErrors=[];page.on('pageerror',error=>errors.push(error.message));
  page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text());});
  try{
    await page.goto((process.env.APP_URL||'http://127.0.0.1:8000')+'/',{waitUntil:'networkidle',timeout:90000});
    await page.locator('body[data-app-ready]').waitFor({timeout:90000});
     await page.locator('#ambientDroneCanvas[data-model-ready]').waitFor();
     await page.locator('#compare').evaluate(el=>window.scrollTo({top:el.getBoundingClientRect().top+scrollY-90,behavior:'instant'}));
     await page.waitForFunction(()=>window.__ambientDrone.info().frames>0&&window.__ambientDrone.info().layout.opacity>.8);
    const first=await page.evaluate(()=>window.__ambientDrone.info());
    await page.mouse.move(1150,300);await page.waitForTimeout(350);
    const second=await page.evaluate(()=>window.__ambientDrone.info());
     assert.equal(first.rotors,6);assert.ok(second.angles.some((a,i)=>Math.abs(a-first.angles[i])>.01));
     assert.deepEqual(first.position,second.position,'background body must remain fixed');
     await page.locator('#intro').evaluate(el=>el.scrollIntoView({block:'start',behavior:'instant'}));
    await capture('visual-hero.png');
    const metrics=await page.evaluate(()=>{
      const v=window.__viewers.find(v=>v.c.id==='heroCanvas');
      const land=v.world.city.group.getObjectByName('land'),ground=v.world.city.group.getObjectByName('ground');
      const moon=v.scene.getObjectByName('moon_lroc_surface');
      return {groundGeometry:land.geometry.type,moonGeometry:moon.geometry.type,moonImageWidth:moon.material.uniforms.uMap.value.image.width,
        facadeImageWidth:(()=>{let width=0;for(const tower of v.world.city.towers)tower.built.traverse(o=>{if(o.material?.isMeshPhysicalMaterial)width=Math.max(width,o.material.map?.image?.width||0);});return width;})(),
        lawnImageWidth:ground.material.userData.lawnMap.image.width,grassTufts:v.world.city.grassCount,
        environmentType:v.scene.environment.type,volumetricFire:v.world.fires.items.every(item=>item.flames.isMesh&&item.flames.geometry.type==='BoxGeometry'),
        sameDroneGeometry:(()=>{let same=true;window.__ambientDrone.model.traverse(mesh=>{if(mesh.isMesh&&mesh.geometry!==v.world.swarms[0].drones[0].root.getObjectByName(mesh.name)?.geometry)same=false;});return same;})(),
        purpleTrails:window.__viewers.every(view=>!view.world||view.world.swarms.every(sw=>sw.drones.every(d=>d.plan.material.color.getHexString()==='9874d3'&&d.flown.material.color.getHexString()==='c69aff'&&d.flownGlow.geometry===d.flown.geometry))),
        purpleSnapshots:(()=>{const sw=v.world.swarms[0];sw.showSnapshot(0,1440,1000);const good=sw.lines.length>0&&sw.lines.every(l=>['9650ef','c69aff'].includes(l.material.color.getHexString()));sw.showSnapshot(null,1440,1000);return good;})(),
        noBlackContactDecals:window.__viewers.every(view=>!view.world||!view.world.city.group.getObjectByName('building_contact_shadow')),
        radius:Number(document.querySelector('#hazardSection').dataset.radius),coreTop:Number(document.querySelector('#hazardSection').dataset.coreTop),renderer:v.info()};
    });
    assert.equal(metrics.groundGeometry,'ShapeGeometry');assert.equal(metrics.moonGeometry,'SphereGeometry');
    assert.equal(metrics.moonImageWidth,2048);assert.equal(metrics.facadeImageWidth,1024);
    assert.equal(metrics.lawnImageWidth,1024);assert.ok(metrics.grassTufts>0);
    assert.ok(metrics.volumetricFire&&metrics.sameDroneGeometry&&metrics.purpleTrails&&metrics.purpleSnapshots&&metrics.noBlackContactDecals);
    assert.ok(Math.abs(metrics.radius-12.488319167365466)<1e-10);
    await page.locator('#hazard').evaluate(el=>window.scrollTo({top:el.getBoundingClientRect().top+scrollY-90,behavior:'instant'}));
    await page.waitForFunction(()=>document.querySelector('#hazard .hazard-fig').classList.contains('in'));
    await capture('visual-hazard.png');
    for(const [id,value] of [['labAlg','ACO'],['labCity','large']]){
      const label=await page.locator(`#${id}`).evaluate((node,value)=>[...node.options].find(option=>option.value===value).textContent,value);
      await page.locator(`#${id}-trigger`).click();await page.locator(`#${id}-list`).getByRole('option',{name:label,exact:true}).click();
      await page.waitForFunction(()=>!document.querySelector('#labRun').disabled);
    }
    await page.evaluate(()=>{
      const v=window.__viewers.find(v=>v.c.id==='labCanvas');v.setState('mission',true);v.orbit=false;v.setTime(20);
      const fire=v.world.data.fires[0],c={x:fire.c[0],y:fire.c[2],z:-fire.c[1]},n={x:fire.normal[0],z:-fire.normal[1]};
      v.camera.position.set(c.x+n.x*75-n.z*30,c.y+18,c.z+n.z*75+n.x*30);v.controls.target.set(c.x,c.y+4,c.z);v.controls.update();
    });
    await page.locator('#labStage').evaluate(el=>window.scrollTo({top:el.getBoundingClientRect().top+scrollY-90,behavior:'instant'}));
    await page.waitForTimeout(700);await capture('visual-facade-fire.png');
    await page.evaluate(()=>{const v=window.__viewers.find(v=>v.c.id==='labCanvas');v.setState('mission',true);v.orbit=false;v.setTime(Math.min(35,v.T*.55));});
    await page.waitForTimeout(600);await capture('visual-city-purple.png');
    await page.evaluate(()=>{
      const v=window.__viewers.find(v=>v.c.id==='labCanvas'),r=v.world.city.net.roads.find(r=>r.b-r.a>120);
      if(!r)throw Error('No street available for eye-level visual verification');
      const t=r.a+18;v.S.paths=false;v.S.labels=false;
      if(r.axis==='x'){v.camera.position.set(r.c,4.8,-t);v.controls.target.set(r.c+3,14,-Math.min(t+70,r.b));}
      else{v.camera.position.set(t,4.8,-r.c);v.controls.target.set(Math.min(t+70,r.b),14,-r.c+3);}
      v.controls.update();
    });
    await page.waitForTimeout(600);await capture('visual-street-grass.png');
    const totals=await page.evaluate(()=>{
      const v=window.__viewers.find(v=>v.c.id==='labCanvas');
      return {musayyarat:v.world.swarms[0].drones.length,shaderFailures:v.renderer.info.programs.filter(p=>p.diagnostics?.runnable===false).length};
    });
    assert.equal(totals.shaderFailures,0);assert.deepEqual(errors,[]);assert.deepEqual(consoleErrors,[]);
    const report={passed:true,testRenderer:'SwiftShader (headless software, not a hardware benchmark)',rotors:first.rotors,rotorsAnimated:true,bodyAnimated:JSON.stringify(first.position)!==JSON.stringify(second.position),...metrics,...totals,errors,consoleErrors};
    await fs.writeFile(path.join(__dirname,'../results','visual-audit.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1});
