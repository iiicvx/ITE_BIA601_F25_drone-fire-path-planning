// أصول فوتوغرافية محلية منسوبة لأصحابها. لا حاجة لأي طلب خارجي وقت التشغيل.
// نموذج التخطيط العددي مستقل عن كل خامة في هذه الوحدة.
import { RGBELoader } from '../vendor/three/examples/jsm/loaders/RGBELoader.js';
const sources={
  asphalt:'asphalt_02_diff_1k.jpg',asphaltHeight:'asphalt_02_disp_1k.jpg',
  concrete:'concrete_wall_003_diff_1k.jpg',moon:'lroc_color_2k.jpg',moonHeight:'ldem_3_8bit.jpg',
  grass:'grass_ground_diff_1k.jpg',grassNormal:'grass_ground_nor_gl_1k.jpg',leafyGrass:'leafy_grass_diff_1k.jpg',
  office:'Facade001_1K-JPG_Color.jpg',officeNormal:'Facade001_1K-JPG_NormalGL.jpg',
  officeRough:'Facade001_1K-JPG_Roughness.jpg',officeMetal:'Facade001_1K-JPG_Metalness.jpg',
  rooms:'Facade010_1K-JPG_Color.jpg',roomsNormal:'Facade010_1K-JPG_NormalGL.jpg',
  roomsRough:'Facade010_1K-JPG_Roughness.jpg',roomsMetal:'Facade010_1K-JPG_Metalness.jpg',
  roomsEmission:'Facade010_1K-JPG_Emission.jpg',
};
const images={};let loading=null;
export function getVisualAssets(){return images;}
export function loadVisualAssets(){
  if(!loading)loading=Promise.all([...Object.entries(sources).map(([key,file])=>new Promise(resolve=>{
    const image=new Image();image.onload=()=>{images[key]=image;resolve();};image.onerror=()=>resolve();
    image.src=`/scene/assets/${file}`;
  })),new RGBELoader().loadAsync('/scene/assets/kiara_1_dawn_1k.hdr').then(texture=>{texture.userData.sharedVisualAsset=true;images.environment=texture;}).catch(()=>{})]);
  return loading;
}
