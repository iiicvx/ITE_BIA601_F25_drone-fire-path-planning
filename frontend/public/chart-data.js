// تحويلات دقيقة لا تعتمد على DOM للرسوم العددية. لا يدخل هذه الحسابات استيفاء للمنحنيات
// ولا طول أدنى مصطنع للأعمدة ولا مدخلات مقرّبة.
export function median(values){
  const sorted=[...values].sort((a,b)=>a-b),n=sorted.length;
  return n?n%2?sorted[(n-1)/2]:(sorted[n/2-1]+sorted[n/2])/2:null;
}
export function convergenceSeries(histories,budget){
  if(!Number.isInteger(budget)||budget<1)throw new Error('Invalid evaluation budget');
  const valid=histories.filter(history=>history.length);
  if(!valid.length)return [];
  for(const history of valid)for(let i=0;i<history.length;i++){
    const [fe,F]=history[i];
    if(!Number.isInteger(fe)||fe<1||fe>budget||!Number.isFinite(F)||F<=0||i&&(fe<=history[i-1][0]||F>history[i-1][1]+1e-12))throw new Error('Invalid best-so-far history');
  }
  const first=Math.max(...valid.map(history=>history[0][0]));
  const times=[...new Set([first,budget,...valid.flatMap(history=>history.map(point=>point[0]).filter(fe=>fe>=first))])].sort((a,b)=>a-b);
  const pointers=valid.map(()=>0);
  return times.map(fe=>[fe,median(valid.map((history,i)=>{
    while(pointers[i]+1<history.length&&history[pointers[i]+1][0]<=fe)pointers[i]++;
    return history[pointers[i]][1];
  }))]);
}
export function stepPath(points,X,Y){
  return points.map(([fe,F],i)=>i?`H${X(fe).toFixed(2)}V${Y(F).toFixed(2)}`:`M${X(fe).toFixed(2)},${Y(F).toFixed(2)}`).join('');
}
export function relativeGap(value,baseline){return Number.isFinite(value)&&Number.isFinite(baseline)&&baseline>0?100*(value-baseline)/baseline:null;}
export function barPercent(value,maximum){return Number.isFinite(value)&&value>=0&&Number.isFinite(maximum)&&maximum>0?100*value/maximum:0;}
export function duration(value){return value===null||value===undefined||!Number.isFinite(value)?'—':value.toFixed(value<1?3:value<10?2:1);}
