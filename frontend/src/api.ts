let csrf='';
export async function init(){const r=await fetch('/api/session');const x=await r.json();csrf=x.csrf;}
export async function api<T=any>(path:string,body?:unknown,method?:string):Promise<T>{
 const r=await fetch('/api'+path,{method:method||(body===undefined?'GET':'POST'),headers:{'Content-Type':'application/json','X-Radar-CSRF':csrf},body:body===undefined?undefined:JSON.stringify(body)});
 if(!r.ok){const e=await r.json().catch(()=>({detail:r.statusText}));throw Error(typeof e.detail==='string'?e.detail:JSON.stringify(e.detail));}return r.json();
}
export type Item=Record<string,any>;
export interface Mission extends Item {id:string;goal:string;status:string;plan:Item;records:Record<string,Item[]>;events:Item[];telemetry:Item;opportunities:Item[];cohorts:Item[];}
export const rows=(m:Mission|undefined,kind:string):Item[]=>m?.records?.[kind]||[];
export function replayAt(m:Mission,seq:number):Mission{
 const records:Record<string,Item[]>={};const maps:Record<string,Map<string,Item>>={};
 const events=m.events.filter(e=>e.seq<=seq);
 for(const e of events)for(const change of e.payload.record_changes||[]){(maps[change.kind]??=new Map()).set(change.record.id,change.record);}
 for(const [kind,map] of Object.entries(maps))records[kind]=[...map.values()];
 return {...m,records,events};
}
export const ms=(n:any)=>n==null?'—':n>=1000?(n/1000).toFixed(2)+' s':Math.round(n)+' ms';
export const short=(s:string,n=65)=>s?.length>n?s.slice(0,n)+'…':s;
