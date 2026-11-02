// معمار للعرض فقط داخل صناديق AABB الثابتة للمدينة (بالمتر).
// الكتلة اتحاد لا كومة صناديق مغلقة متداخلة: لكل رقعة خارجية
// مالك واحد. وبالأخص لا يقع سطح على وجه علوي لصندوق ثانٍ أبدًا.
import * as THREE from '../vendor/three/three.module.js';
import { V, canvasTexture, radialSprite, clamp } from './util.js';
import { getVisualAssets } from './visual-assets.js';

const ARCHETYPES=['courtyard-office','limestone-residential','setback-office','terrace-hotel',
  'twin-towers','brick-apartments','slender-office','civic-stone','stepped-residential',
  'ribbon-office','corner-hotel','limestone-landmark'];
const PALETTES=['#c1c5c5','#dfd6c2','#b8c7cd','#cfc1ad','#a9babd','#bea58e',
  '#becbd0','#d5d2c7','#d2c8b5','#a6b9c1','#c7bcae','#dbd2bb'];
const FLOOR=3.5;
const rect=(b,sx,sy,ox=0,oy=0)=>{
  const w=b.x1-b.x0,d=b.y1-b.y0,cx=(b.x0+b.x1)/2+w*ox,cy=(b.y0+b.y1)/2+d*oy;
  return [cx-w*sx/2,cy-d*sy/2,cx+w*sx/2,cy+d*sy/2];
};

export function fireWingBounds(b,f) {
  const pw=b.x1-b.x0,pd=b.y1-b.y0,cx=(b.x0+b.x1)/2,cy=(b.y0+b.y1)/2;
  const alongY=Math.abs(f.normal[0])>.5;
  const width=Math.min(clamp(f.R*2.1,14,34),(alongY?pd:pw)-.4);
  const centre=clamp(alongY?f.c[1]:f.c[0],(alongY?b.y0:b.x0)+width/2+.1,(alongY?b.y1:b.x1)-width/2-.1);
  const rect=alongY?[f.normal[0]>0?cx-pw*.18:b.x0,centre-width/2,f.normal[0]>0?b.x1:cx+pw*.18,centre+width/2]:
    [centre-width/2,f.normal[1]>0?cy-pd*.18:b.y0,centre+width/2,f.normal[1]>0?b.y1:cy+pd*.18];
  return {rect,width,centre,alongY,height:Math.min(b.h,Math.ceil((f.c[2]+f.R*2.05)/FLOOR)*FLOOR)};
}

// اتحاد مصمت بإحداثيات مضغوطة. تُدمج خلايا الحدود المتجاورة قبل
// بناء الشبكة، فلا تنتج المنصة والبرج والجناح والحاجز أوجهًا متطابقة متراكبة.
// مُصدَّر للسماح باختبارات مستقلة للحجب وملكية الحدود.
export function exteriorSurfaces(volumes){
  // الفروق الحسابية دون الميكرومتر يجب ألا تُنشئ خلايا رقيقة فارغة
  // بين حافتين مشتركتين مقصودتين (مثل 371.8 مقابل 371.79999999999995).
  const sorted=values=>[...new Set(values.map(v=>Math.round(v*1e6)/1e6))].sort((a,b)=>a-b);
  const xs=sorted(volumes.flatMap(v=>[v.rect[0],v.rect[2]]));
  const ys=sorted(volumes.flatMap(v=>[v.rect[1],v.rect[3]]));
  const zs=sorted(volumes.flatMap(v=>[v.z0,v.z1]));
  const nx=xs.length-1,ny=ys.length-1,nz=zs.length-1;
  const grid=new Int16Array(nx*ny*nz).fill(-1),index=(x,y,z)=>(x*ny+y)*nz+z;
  for(let i=0;i<nx;i++)for(let j=0;j<ny;j++)for(let k=0;k<nz;k++){
    const x=(xs[i]+xs[i+1])/2,y=(ys[j]+ys[j+1])/2,z=(zs[k]+zs[k+1])/2;
    for(let v=0;v<volumes.length;v++){
      const a=volumes[v];if(x>a.rect[0]&&x<a.rect[2]&&y>a.rect[1]&&y<a.rect[3]&&z>a.z0&&z<a.z1)grid[index(i,j,k)]=v;
    }
  }
  const occupied=(x,y,z)=>x>=0&&x<nx&&y>=0&&y<ny&&z>=0&&z<nz&&grid[index(x,y,z)]>=0;
  const planes=new Map();
  const add=(axis,sign,p,u,v,owner)=>{
    const key=`${axis}:${sign}:${p}:${owner}`;
    if(!planes.has(key))planes.set(key,{axis,sign,p,owner,cells:new Set()});
    planes.get(key).cells.add(`${u}:${v}`);
  };
  for(let x=0;x<nx;x++)for(let y=0;y<ny;y++)for(let z=0;z<nz;z++){
    const owner=grid[index(x,y,z)];if(owner<0)continue;
    if(!occupied(x-1,y,z))add('x',-1,x,y,z,owner);
    if(!occupied(x+1,y,z))add('x',1,x+1,y,z,owner);
    if(!occupied(x,y-1,z))add('y',-1,y,x,z,owner);
    if(!occupied(x,y+1,z))add('y',1,y+1,x,z,owner);
    if(!occupied(x,y,z+1))add('z',1,z+1,x,y,owner);
    // لا أوجه سفلية منطبقة على سطح الأرض الوحيد.
  }
  const faces=[];
  for(const plane of planes.values()){
    const {axis,sign,p,owner,cells}=plane;
    const coords=axis==='x'?[ys,zs,xs]:axis==='y'?[xs,zs,ys]:[xs,ys,zs];
    while(cells.size){
      const [u,v]=cells.values().next().value.split(':').map(Number);
      let u1=u+1,v1=v+1;while(cells.has(`${u1}:${v}`))u1++;
      while(v1<coords[1].length-1&&Array.from({length:u1-u},(_,i)=>cells.has(`${u+i}:${v1}`)).every(Boolean))v1++;
      for(let a=u;a<u1;a++)for(let b=v;b<v1;b++)cells.delete(`${a}:${b}`);
      faces.push({axis,sign,plane:coords[2][p],u0:coords[0][u],u1:coords[0][u1],v0:coords[1][v],v1:coords[1][v1],owner:volumes[owner].owner||'body'});
    }
  }
  return faces;
}

function buffers(){return {p:[],uv:[]};}
function quad(buf,a,b,c,d,uv=[[0,0],[1,0],[1,1],[0,1]]){
  for(const i of [0,1,2,0,2,3]){buf.p.push(...[a,b,c,d][i]);buf.uv.push(...uv[i]);}
}
function geometry(buf){
  const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(buf.p,3));
  g.setAttribute('uv',new THREE.Float32BufferAttribute(buf.uv,2));g.computeVertexNormals();return g;
}
function wallFrame(face){
  const {axis,sign,plane,u0,u1}=face;
  const n=axis==='x'?[sign,0]:[0,sign];
  const forward=axis==='x'?sign>0:sign<0;
  const a=axis==='x'?[plane,forward?u0:u1]:[forward?u0:u1,plane];
  const dir=axis==='x'?[0,forward?1:-1]:[forward?1:-1,0];
  return {length:u1-u0,n,point:(u,z,depth=0)=>V(a[0]+dir[0]*u+n[0]*depth,a[1]+dir[1]*u+n[1]*depth,z).toArray()};
}
function patch(buf,frame,u0,u1,z0,z1,depth=0,tile=[6,6],offset=0){
  if(u1-u0<1e-6||z1-z0<1e-6)return;
  const p=frame.point;
  quad(buf,p(u0,z0,depth),p(u1,z0,depth),p(u1,z1,depth),p(u0,z1,depth),
    [[u0/tile[0]+offset,z0/tile[1]],[u1/tile[0]+offset,z0/tile[1]],[u1/tile[0]+offset,z1/tile[1]],[u0/tile[0]+offset,z1/tile[1]]]);
}

function surfaceTexture(key,linear=false){
  const image=getVisualAssets()[key];if(!image)return null;
  const t=new THREE.Texture(image);t.needsUpdate=true;t.wrapS=t.wrapT=THREE.RepeatWrapping;
  t.colorSpace=linear?THREE.NoColorSpace:THREE.SRGBColorSpace;t.anisotropy=8;return t;
}
function materialLibrary(){
  // خرائط مشتركة داخل المدينة بدل أربع خامات مستقلة لكل برج.
  const office={map:surfaceTexture('office'),normalMap:surfaceTexture('officeNormal',true),
    roughnessMap:surfaceTexture('officeRough',true),metalnessMap:surfaceTexture('officeMetal',true)};
  const rooms={map:surfaceTexture('rooms'),normalMap:surfaceTexture('roomsNormal',true),
    roughnessMap:surfaceTexture('roomsRough',true),metalnessMap:surfaceTexture('roomsMetal',true),emissiveMap:surfaceTexture('roomsEmission')};
  const stone=canvasTexture(512,512,ctx=>{
    ctx.fillStyle='#d3d5d1';ctx.fillRect(0,0,512,512);
    if(getVisualAssets().concrete){ctx.globalAlpha=.12;ctx.drawImage(getVisualAssets().concrete,0,0,512,512);ctx.globalAlpha=1;}
  },{repeat:true,aniso:8});
  const flatAtlas=(emission=false)=>canvasTexture(512,512,ctx=>{
    ctx.fillStyle=emission?'#000':'#d4d4d4';ctx.fillRect(0,0,512,512);
    if(!emission&&getVisualAssets().concrete)ctx.drawImage(stone.image,0,0,512,512);
    const source=getVisualAssets()[emission?'roomsEmission':'rooms'];
    for(let r=0;r<8;r++)for(let c=0;c<8;c++){
      const x=c*64+9.6,y=r*64+64*(1-2.9/FLOOR),w=44.8,h=64*(2.9-.62)/FLOOR;
      if(source)ctx.drawImage(source,((c*7+r*3)%28)*32,((r*3+c)%32)*32,32,27,x,y,w,h);
      else{ctx.fillStyle=emission?'#000':'#203445';ctx.fillRect(x,y,w,h);}
    }
  },{repeat:true,aniso:8});
  const flatMap=flatAtlas(),flatEmission=flatAtlas(true);
  return PALETTES.map((tint,i)=>({
    office:new THREE.MeshPhysicalMaterial({...office,color:i%3===0?0xc1d4dc:i%3===1?0xc8d1ca:0xe0e5e7,
      roughness:.62,metalness:.68,normalScale:new THREE.Vector2(.42,.42),clearcoat:.8,clearcoatRoughness:.16,envMapIntensity:1.3}),
    rooms:new THREE.MeshPhysicalMaterial({...rooms,color:0xb8c6ca,metalness:.5,roughness:.7,
      emissive:0xffe4bf,emissiveIntensity:.65,clearcoat:.65,clearcoatRoughness:.23,envMapIntensity:.95}),
    stone:new THREE.MeshStandardMaterial({map:stone,color:tint,roughness:.87,metalness:.035}),
    flatStone:new THREE.MeshStandardMaterial({map:flatMap,emissiveMap:flatEmission,color:tint,emissive:0xffe4bf,emissiveIntensity:.65,roughness:.7,metalness:.12,envMapIntensity:.8}),
    roof:new THREE.MeshStandardMaterial({map:stone,color:0x8b9291,roughness:.9}),
    trim:new THREE.MeshStandardMaterial({color:i%3===0?0x526771:i%3===1?0xc4c3b9:0x929b9d,roughness:.49,metalness:.62}),
  }));
}

function massing(b,id,fireIds){
  const type=id%ARCHETYPES.length,volumes=[];
  const roofHeight=b.h-2.4,podium=Math.min(14,Math.max(6.5,Math.floor(b.h*.14/FLOOR)*FLOOR));
  const push=(r,z0,z1,owner='body')=>volumes.push({rect:r,z0,z1,owner});
  const podiumRect=rect(b,.956,.956);push(podiumRect,0,podium);
  let top=rect(b,.76,.76),shaft=rect(b,.82,.82);
  switch(type){
    case 0: // مكتب مع جناح سفلي على شكل L نحو الشارع
      shaft=rect(b,.57,.84,-.15,0);top=shaft;push(rect(b,.9,.31,0,-.29),podium,Math.min(roofHeight,b.h*.43));break;
    case 1: top=rect(b,.71,.73,.065,0);push(rect(b,.87,.85),podium,roofHeight*.65);break;
    case 2: top=rect(b,.58,.65,.09,.07);push(rect(b,.84,.84),podium,roofHeight*.55);push(rect(b,.72,.74,.04,.035),roofHeight*.55,roofHeight*.81);break;
    case 3: shaft=rect(b,.77,.87);top=rect(b,.59,.7,0,.05);push(shaft,podium,roofHeight*.78);break;
    case 4: shaft=rect(b,.38,.82,-.245,0);top=shaft;push(rect(b,.36,.78,.25,.01),podium,roofHeight*.81);break;
    case 5: top=rect(b,.79,.7);push(rect(b,.88,.84),podium,roofHeight*.72);break;
    case 6: top=rect(b,.62,.74,.08,.02);break;
    case 7: top=rect(b,.79,.78);push(rect(b,.9,.9),podium,Math.min(roofHeight-3,roofHeight*.68));break;
    case 8: top=rect(b,.56,.62,.1,.09);push(rect(b,.88,.88),podium,roofHeight*.49);push(rect(b,.72,.76,.05,.04),roofHeight*.49,roofHeight*.74);break;
    case 9: top=rect(b,.88,.55,0,-.12);push(rect(b,.4,.85,-.24,0),podium,roofHeight*.53);break;
    case 10: top=rect(b,.64,.7,-.09,.08);push(rect(b,.87,.82),podium,roofHeight*.63);break;
    default: top=rect(b,.66,.66);push(rect(b,.84,.84),podium,roofHeight*.78);break;
  }
  // التداخل هنا مدخل منطقي لا هندسة للعرض. لا يُخرج إلا الغلاف
  // الخارجي للاتحاد، ومنه المصاطب الأفقية المتدرجة الحقيقية.
  push(top,podium,roofHeight);
  const [x0,y0,x1,y1]=top,edge=.22;
  for(const r of [[x0,y0,x1,y0+edge],[x0,y1-edge,x1,y1],[x0,y0+edge,x0+edge,y1-edge],[x1-edge,y0+edge,x1,y1-edge]])push(r,roofHeight,roofHeight+.65,'roof');
  // غرفة خدمات حقيقية تقع على السطح وتنتهي عند الارتفاع الأصلي h.
  const ew=Math.min(4.2,(x1-x0)*.22),ed=Math.min(3.6,(y1-y0)*.2);
  push([x0+1.1,y0+1.1,x0+1.1+ew,y0+1.1+ed],roofHeight,b.h,'equipment');
  for(const f of fireIds){const s=fireWingBounds(b,f);push(s.rect,0,s.height,`fire_${f.id}`);}
  return {volumes,top:[[x0,y0],[x1,y0],[x1,y1],[x0,y1]],roofHeight,podium};
}

function recessedWall(face,wall,glass,trim,seed,balcony=false){
  const frame=wallFrame(face),p=frame.point,L=frame.length;
  const bay=3.2,side=.48,windowW=bay-side*2,depth=-.32;
  const z0=face.v0,z1=face.v1;
  // لكل فتحة إطارها وعتبتها الخاصان. لا جدار معتم خلف
  // مستوى نافذة منطبق، ولا شبكة سلكية عامة فوق الواجهة.
  let floor=z0;
  while(floor<z1-1e-5){
    const end=Math.min(z1,(Math.floor((floor+1e-5)/FLOOR)+1)*FLOOR);
    const low=Math.max(floor,Math.floor((floor+1e-5)/FLOOR)*FLOOR+(balcony?.22:.62)),high=Math.min(end,Math.floor((floor+1e-5)/FLOOR)*FLOOR+2.9);
    if(high-low<1.2||L<2.8){patch(wall,frame,0,L,floor,end);floor=end;continue;}
    patch(wall,frame,0,L,floor,low);patch(wall,frame,0,L,high,end);
    const count=Math.max(1,Math.floor(L/bay)),spacing=L/count;
    for(let c=0;c<count;c++){
      const centre=(c+.5)*spacing,a=centre-windowW/2,b=centre+windowW/2;
      patch(wall,frame,c*spacing,a,low,high);patch(wall,frame,b,(c+1)*spacing,low,high);
      quad(wall,p(a,low),p(a,low,depth),p(a,high,depth),p(a,high));
      quad(wall,p(b,high),p(b,high,depth),p(b,low,depth),p(b,low));
      quad(wall,p(a,low),p(b,low),p(b,low,depth),p(a,low,depth));
      quad(wall,p(a,high,depth),p(b,high,depth),p(b,high),p(a,high));
      // مقتطعات من أطلس الغرف المحلي: إحداثيات لون ونواظم وخشونة وإضاءة
      // متطابقة، لا بكسلات مضيئة لا علاقة لها فوق شبكة زجاجية.
      const col=((c*7+seed)%28)*2,row=(Math.floor(floor/FLOOR)*3+seed)%32;
      const uv=[[col/64,row/32],[(col+2)/64,row/32],[(col+2)/64,(row+.86)/32],[col/64,(row+.86)/32]];
      quad(glass,p(a,low,depth),p(b,low,depth),p(b,high,depth),p(a,high,depth),uv);
      patch(trim,frame,a,b,low,low+.08,depth+.035,[3,3]);
      if(balcony&&high-low>2.3){
        // أرضية شرفة وحاجز مدعومان، داخل صندوق AABB للمدينة بالكامل.
        // كل الألواح مجمعة مع شبكات الحجر والمعدن الموجودة.
        const left=a-.18,right=b+.18,top=floor+.18,bottom=floor+.04,out=.64;
        quad(wall,p(left,top,out),p(right,top,out),p(right,top,0),p(left,top,0));
        quad(wall,p(left,bottom,0),p(right,bottom,0),p(right,bottom,out),p(left,bottom,out));
        quad(wall,p(left,bottom,out),p(right,bottom,out),p(right,top,out),p(left,top,out));
        quad(wall,p(left,bottom,0),p(left,bottom,out),p(left,top,out),p(left,top,0));
        quad(wall,p(right,bottom,out),p(right,bottom,0),p(right,top,0),p(right,top,out));
        patch(trim,frame,left,right,floor+.92,floor+.98,out);
        for(let bar=0;bar<=5;bar++){
          const u=left+(right-left)*bar/5;
          patch(trim,frame,u,u+.035,top,floor+.92,out);
        }
      }
    }
    floor=end;
  }
}

function makeTower(group,b,id,seed,materials,fireIds){
  const styleIndex=(id*5+(seed>>>0))%ARCHETYPES.length;
  const designId=styleIndex+Math.floor(id/ARCHETYPES.length)*ARCHETYPES.length;
  const plan=massing(b,designId,fireIds),faces=exteriorSurfaces(plan.volumes);
  const G=new THREE.Group(),style=ARCHETYPES[styleIndex],stoneStyle=[1,3,5,7,8,10,11].includes(styleIndex);
  G.name=`tower_${id}_${style}`;
  G.userData={buildingId:b.id,archetype:style,collisionBox:{x0:b.x0,y0:b.y0,x1:b.x1,y1:b.y1,h:b.h},exteriorPatchCount:faces.length,visualVolumes:plan.volumes};
  const owned=new Map(),glass=buffers(),trim=buffers(),flatWalls=buffers();
  const ownerBuffers=owner=>{if(!owned.has(owner))owned.set(owner,{wall:buffers(),roof:buffers()});return owned.get(owner);};
  for(const face of faces){
    const out=ownerBuffers(face.owner);
    if(face.axis==='z'){
      const {u0:x0,u1:x1,v0:y0,v1:y1,plane:z}=face;
      quad(out.roof,V(x0,y0,z).toArray(),V(x1,y0,z).toArray(),V(x1,y1,z).toArray(),V(x0,y1,z).toArray(),[[x0/6,y0/6],[x1/6,y0/6],[x1/6,y1/6],[x0/6,y1/6]]);
    }else if(stoneStyle&&face.owner==='body'){
      const clearance=face.axis==='x'?(face.sign>0?b.x1-face.plane:face.plane-b.x0):(face.sign>0?b.y1-face.plane:face.plane-b.y0);
      recessedWall(face,out.wall,glass,trim,id+styleIndex,[3,5,8,10].includes(styleIndex)&&face.v0>=plan.podium-.001&&clearance>.7);
      const frame=wallFrame(face);patch(flatWalls,frame,0,frame.length,face.v0,face.v1,0,[25.6,28]);
    }
    else {
      const frame=wallFrame(face),isStone=face.owner==='roof'||face.owner==='equipment';
      patch(out.wall,frame,0,frame.length,face.v0,face.v1,0,isStone?[6,6]:[24,35],(id%7)/16);
    }
  }
  const close=new THREE.Group();close.name='near_architectural_relief';
  for(const [owner,out]of owned){
    const wallGeometry=geometry(out.wall),roofGeometry=geometry(out.roof);
    const stoneOwner=owner==='roof'||owner==='equipment';
    const mesh=new THREE.Mesh(wallGeometry,stoneOwner?materials.trim:stoneStyle&&owner==='body'?materials.stone:materials.office);
    mesh.name=owner.startsWith('fire_')?`fire_facade_${b.id}_${owner.slice(5)}`:owner==='body'?`facade_${id}`:`${owner}_${id}`;
    mesh.castShadow=mesh.receiveShadow=true;
    mesh.userData={grounded:owner.startsWith('fire_'),surfaceOwner:owner,baseAltitude:0};
    (stoneStyle&&owner==='body'?close:G).add(mesh);
    if(out.roof.p.length){const roof=new THREE.Mesh(roofGeometry,materials.roof);roof.name=`roof_${owner}_${id}`;roof.castShadow=roof.receiveShadow=true;G.add(roof);}else roofGeometry.dispose();
  }
  if(glass.p.length){const panes=new THREE.Mesh(geometry(glass),materials.rooms);panes.name=`recessed_glazing_${id}`;panes.receiveShadow=true;close.add(panes);}
  if(trim.p.length){const sills=new THREE.Mesh(geometry(trim),materials.trim);sills.name=`window_sills_${id}`;close.add(sills);}
  if(flatWalls.p.length){
    const far=new THREE.Group(),mesh=new THREE.Mesh(geometry(flatWalls),materials.flatStone);mesh.castShadow=mesh.receiveShadow=true;mesh.name=`distant_facade_${id}`;far.add(mesh);
    const lod=new THREE.LOD();lod.name='facade_relief_lod';
    lod.position.copy(V((b.x0+b.x1)/2,(b.y0+b.y1)/2,b.h*.5));close.position.copy(lod.position).negate();far.position.copy(close.position);
    lod.addLevel(close,0);lod.addLevel(far,300,.12);G.add(lod);
  }else G.add(close);
  group.add(G);
  return {built:G,style,facade:stoneStyle?'recessed-stone':'reflective-curtain',top:plan.top,roofAltitude:plan.roofHeight,
    roofPatches:faces.filter(f=>f.axis==='z'&&Math.abs(f.plane-plan.roofHeight)<1e-6),
    signature:`${style}-${seed}-${id}-${b.h.toFixed(3)}`};
}

export function buildArchitecturalCity(group,city,seed,anim){
  const towers=[],redLights=[],library=materialLibrary(),firesByBuilding=new Map();
  for(const f of city.fires){if(!firesByBuilding.has(f.building))firesByBuilding.set(f.building,[]);firesByBuilding.get(f.building).push(f);}
  city.buildings.forEach((b,i)=>{
    const built=makeTower(group,b,i,seed,library[(i*7+(seed>>>0))%library.length],firesByBuilding.get(b.id)||[]);
    towers.push({...b,...built});
    if(b.h>120){const p=built.top[0];redLights.push(V(p[0],p[1],built.roofAltitude+.65));}
  });
  // علامة الهبوط على السطح العريض، لا فوق معدات غير مدعومة.
  for(const tower of [...towers].sort((a,b)=>b.h-a.h)){
    const patch=[...tower.roofPatches].sort((a,b)=>Math.min(b.u1-b.u0,b.v1-b.v0)-Math.min(a.u1-a.u0,a.v1-a.v0))[0];
    if(!patch)continue;
    const {u0:x0,u1:x1,v0:y0,v1:y1}=patch,side=Math.min(x1-x0,y1-y0)*.56;
    if(side<4)continue;
    const tex=canvasTexture(128,128,ctx=>{
      ctx.clearRect(0,0,128,128);ctx.strokeStyle='#d7dcd4';ctx.lineWidth=6;ctx.beginPath();ctx.arc(64,64,49,0,Math.PI*2);ctx.stroke();
      ctx.fillStyle='#d7dcd4';ctx.font='bold 68px sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText('H',64,67);
    });
    const mat=new THREE.MeshBasicMaterial({map:tex,transparent:true,depthWrite:false,polygonOffset:true,polygonOffsetFactor:-2,polygonOffsetUnits:-2,toneMapped:false,opacity:.74});
    const heli=new THREE.Mesh(new THREE.PlaneGeometry(side*1.5,side*1.5).rotateX(-Math.PI/2),mat);
    heli.position.copy(V((x0+x1)/2,(y0+y1)/2,tower.roofAltitude));heli.name='rooftop_helipad';tower.built.add(heli);break;
  }
  let redMat=null;
  if(redLights.length){
    redMat=new THREE.PointsMaterial({size:4,sizeAttenuation:false,color:0xff5042,map:radialSprite(64,'rgba(255,255,255,1)','rgba(255,255,255,0)'),transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,toneMapped:false});
    group.add(new THREE.Points(new THREE.BufferGeometry().setFromPoints(redLights),redMat));
    anim.push(t=>{redMat.opacity=(t%2)<.95?.8:.12;});
  }
  return {towers,redLights,redMat};
}
