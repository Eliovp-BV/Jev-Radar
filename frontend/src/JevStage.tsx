import {useEffect,useMemo,useRef,useState} from 'react';
import {ArrowRight,ArrowUpRight,BookOpen,Check,ChevronRight,FileText,GitBranch,Globe,Layers,Pause,Play,Search,Sparkles} from 'lucide-react';
import {ms,type Item,type Mission} from './api';
import {deriveStageState,type StageState} from './jev-stage-state';
import './jev-stage.css';

type Point={x:number;y:number};
type Props={mission:Mission;replay:boolean;playing:boolean;onDecision:(id:string)=>void;onSource:(id:string)=>void;onFinding:(id:string)=>void};
const gold='235,204,139',teal='112,207,193';
const clamp=(n:number,min:number,max:number)=>Math.min(max,Math.max(min,n));
function positions(w:number,h:number){
 const small=w<560;
 return {core:{x:w*.5,y:h*(small?.445:w>1200?.55:.51)},search:{x:w*(small?.19:.19),y:h*(small?.715:.565)},read:{x:w*(small?.81:.81),y:h*(small?.715:.565)},evidence:{x:w*.5,y:h*(small?.81:.825)},radius:small?57:clamp(w*.065,77,115)};
}
function line(ctx:CanvasRenderingContext2D,points:Point[],color:string,width=1){
 ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(p.x,p.y):ctx.moveTo(p.x,p.y));ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke();
}
function glow(ctx:CanvasRenderingContext2D,p:Point,r:number,color:string,alpha:number){
 const g=ctx.createRadialGradient(p.x,p.y,0,p.x,p.y,r);g.addColorStop(0,`rgba(${color},${alpha})`);g.addColorStop(1,`rgba(${color},0)`);ctx.fillStyle=g;ctx.fillRect(p.x-r,p.y-r,r*2,r*2);
}
function bezier(a:Point,b:Point,t:number){const k=1-t,c={x:(a.x+b.x)/2,y:Math.min(a.y,b.y)-35};return{x:k*k*a.x+2*k*t*c.x+t*t*b.x,y:k*k*a.y+2*k*t*c.y+t*t*b.y};}
function paint(ctx:CanvasRenderingContext2D,w:number,h:number,state:StageState,angle:number,pulse:number){
 ctx.clearRect(0,0,w,h);
 const p=positions(w,h),r=p.radius,core=p.core,small=w<560;
 // A perspective floor is decorative geometry, never a visualization of invented records.
 const horizon=h*.37,vanish={x:w/2,y:horizon};
 for(let i=-10;i<=10;i++)line(ctx,[vanish,{x:w/2+i*w*.145,y:h}],`rgba(151,174,170,${i%2===0?.045:.024})`);
 for(let i=1;i<=12;i++){const y=horizon+(h-horizon)*(i/12)**2;line(ctx,[{x:0,y},{x:w,y}],`rgba(151,174,170,${.016+i*.003})`);}
 glow(ctx,{x:core.x,y:core.y+50},r*2.7,gold,.07);
 glow(ctx,p.read,120,teal,.065);
 // Elliptical tracks and layered platforms give the stage depth without animation at rest.
 ctx.save();ctx.translate(core.x,core.y+40);ctx.beginPath();ctx.ellipse(0,0,w*(small?.37:.335),h*.205,-.12,0,Math.PI*2);ctx.strokeStyle='rgba(154,173,163,.12)';ctx.setLineDash([2,7]);ctx.stroke();ctx.setLineDash([]);ctx.restore();
 const activity=state.transport==='search_api'?'search':['page_fetch','browser_render','metadata'].includes(state.transport)?'read':state.phase==='verifying'||state.phase==='prioritizing'||state.phase==='comparing'?'evidence':state.phase==='assessing'?'read':null;
 for(const key of ['search','read','evidence'] as const){
  const node=p[key],lit=key===activity,color=key==='evidence'?gold:teal;
  const start={x:core.x+(node.x-core.x)*.22,y:core.y+(node.y-core.y)*.22};
  const path=Array.from({length:41},(_,i)=>bezier(start,node,i/40));
  line(ctx,path,lit?`rgba(${color},.37)`:'rgba(127,151,149,.13)',lit?1.35:1);
  if(lit&&pulse>0){const point=bezier(node,start,1-pulse);glow(ctx,point,18,color,pulse*.42);ctx.beginPath();ctx.arc(point.x,point.y,2.5,0,Math.PI*2);ctx.fillStyle=`rgba(${color},${pulse})`;ctx.fill();}
  const width=small?27:35,depth=small?13:17,y=node.y;
  const top=[{x:node.x,y:y-depth},{x:node.x+width,y},{x:node.x,y:y+depth},{x:node.x-width,y},{x:node.x,y:y-depth}];
  ctx.beginPath();ctx.moveTo(node.x-width,y);ctx.lineTo(node.x,y+depth);ctx.lineTo(node.x+width,y);ctx.lineTo(node.x+width,y+8);ctx.lineTo(node.x,y+depth+8);ctx.lineTo(node.x-width,y+8);ctx.closePath();ctx.fillStyle='#0a1115';ctx.fill();line(ctx,[{x:node.x-width,y:y+8},{x:node.x,y:y+depth+8},{x:node.x+width,y:y+8}],`rgba(${color},.18)`);
  ctx.beginPath();top.forEach((v,i)=>i?ctx.lineTo(v.x,v.y):ctx.moveTo(v.x,v.y));ctx.fillStyle=lit?'#172525':'#111a1f';ctx.fill();line(ctx,top,`rgba(${color},${lit?.65:.29})`);
  glow(ctx,{x:node.x,y:y-5},32,color,lit?.19:.075);
  ctx.beginPath();ctx.arc(node.x,y-6,lit?4:3,0,Math.PI*2);ctx.fillStyle=`rgba(${color},${lit?.95:.6})`;ctx.fill();
  line(ctx,[{x:node.x,y:y-8},{x:node.x,y:y-28}],`rgba(${color},${lit?.45:.17})`);
 }
 // Core plinth: four inset ellipses form a small illuminated mechanical housing.
 for(let i=3;i>=0;i--){ctx.beginPath();ctx.ellipse(core.x,core.y+r*.72+i*7,r*1.08-i*2,r*.31,0,0,Math.PI*2);ctx.fillStyle=i===0?'#151c1b':'#080e12';ctx.fill();ctx.strokeStyle=`rgba(${gold},${i===0?.3:.12})`;ctx.lineWidth=1;ctx.stroke();}
 glow(ctx,{x:core.x,y:core.y+r*.84},r*1.2,gold,.1);
 const active=state.transport!=='none';
 glow(ctx,core,r*1.75,gold,active?.14:.075);
 const body=ctx.createRadialGradient(core.x-r*.34,core.y-r*.38,0,core.x,core.y,r);
 body.addColorStop(0,'#4a4932');body.addColorStop(.28,'#262d26');body.addColorStop(.72,'#121d20');body.addColorStop(1,'#081216');
 ctx.beginPath();ctx.arc(core.x,core.y,r,0,Math.PI*2);ctx.fillStyle=body;ctx.fill();ctx.strokeStyle=`rgba(${gold},.35)`;ctx.stroke();
 const project=(x:number,y:number,z:number)=>{
  const x1=x*Math.cos(angle)+z*Math.sin(angle),z1=z*Math.cos(angle)-x*Math.sin(angle);
  const y1=y*Math.cos(.3)-z1*Math.sin(.3),z2=y*Math.sin(.3)+z1*Math.cos(.3),f=420/(420-z2);
  return{x:core.x+x1*f,y:core.y+y1*f,z:z2};
 };
 // Surface lines are drawn in rear/front passes for a translucent globe.
 const curves:Array<Array<ReturnType<typeof project>>>=[];
 for(let lat=-3;lat<=3;lat++){const a=lat*Math.PI/9;curves.push(Array.from({length:65},(_,i)=>{const t=i*Math.PI/32;return project(r*Math.cos(a)*Math.cos(t),r*Math.sin(a),r*Math.cos(a)*Math.sin(t));}));}
 for(let lon=0;lon<10;lon++){const a=lon*Math.PI/10;curves.push(Array.from({length:65},(_,i)=>{const t=i*Math.PI/32;return project(r*Math.cos(t)*Math.cos(a),r*Math.sin(t),r*Math.cos(t)*Math.sin(a));}));}
 for(const front of [false,true])for(const curve of curves){for(let i=1;i<curve.length;i++)if((curve[i].z>=0)===front)line(ctx,[curve[i-1],curve[i]],`rgba(${gold},${front?.23:.045})`,front?.8:.6);}
 for(let ring=0;ring<2;ring++){
  ctx.save();ctx.translate(core.x,core.y);ctx.rotate((ring?-.6:.5)+angle*.12);ctx.beginPath();ctx.ellipse(0,0,r*(ring?1.33:1.22),r*(ring?.49:.36),0,0,Math.PI*2);ctx.strokeStyle=`rgba(${ring?teal:gold},${ring?.2:.52})`;ctx.lineWidth=ring?1:1.5;ctx.stroke();ctx.restore();
 }
 glow(ctx,{x:core.x-r*.55,y:core.y-r*.65},r*.7,gold,.22);
 // Each branch is one actual supplied choice, capped for legibility.
 const criteria=state.currentDecision?.questions?.next?.criteria||state.currentDecision?.questions?.refine_query?.criteria||(state.collectionSelection&&state.currentDecision?.questions?.[state.collectionSelection.items[0]?.actionId]?.criteria);
 const options=criteria&&typeof criteria==='object'?Object.keys(criteria).length:(state.chosen?state.chosen.alternatives.length+1:0);
 for(let i=0;i<Math.min(options,4);i++){
  const a=-Math.PI*.98+i*.15,point={x:core.x+Math.cos(a)*r*1.6,y:core.y+Math.sin(a)*r*1.6};
  line(ctx,[{x:core.x+Math.cos(a)*r*1.14,y:core.y+Math.sin(a)*r*1.14},point],`rgba(${gold},.2)`);
  ctx.beginPath();ctx.arc(point.x,point.y,2,0,Math.PI*2);ctx.fillStyle=`rgba(${gold},.6)`;ctx.fill();
 }
}

export default function JevStage({mission,replay,playing,onDecision,onSource,onFinding}:Props){
 const state=useMemo(()=>deriveStageState(mission,replay),[mission,replay]);
 const canvas=useRef<HTMLCanvasElement>(null),scene=useRef<HTMLDivElement>(null),orientation=useRef(.44),eventRef=useRef({mission:mission.id,seq:state.latestEventSeq,at:0});
 const [size,setSize]=useState({width:850,height:510}),[paused,setPaused]=useState(false),[reduced,setReduced]=useState(()=>window.matchMedia('(prefers-reduced-motion: reduce)').matches),[visible,setVisible]=useState(!document.hidden),[arriving,setArriving]=useState(false);
 useEffect(()=>{const media=window.matchMedia('(prefers-reduced-motion: reduce)'),change=()=>setReduced(media.matches),visibility=()=>setVisible(!document.hidden);media.addEventListener('change',change);document.addEventListener('visibilitychange',visibility);return()=>{media.removeEventListener('change',change);document.removeEventListener('visibilitychange',visibility);};},[]);
 useEffect(()=>{if(!scene.current)return;const observer=new ResizeObserver(([entry])=>setSize({width:entry.contentRect.width,height:entry.contentRect.height}));observer.observe(scene.current);return()=>observer.disconnect();},[]);
 const arrivalSeen=useRef({mission:mission.id,seq:state.latestEventSeq});
 useEffect(()=>{
  const previous=arrivalSeen.current;arrivalSeen.current={mission:mission.id,seq:state.latestEventSeq};
  if(previous.mission!==mission.id||state.latestEventSeq<=previous.seq){setArriving(false);return;}
  const received=mission.events.some(e=>e.seq>previous.seq&&['jev.completed','text.completed','source.extracted','assessment.recorded','search.completed'].includes(e.type));
  if(!received||!((!replay&&state.active)||(replay&&playing))){setArriving(false);return;}
  setArriving(true);const timer=window.setTimeout(()=>setArriving(false),1100);return()=>window.clearTimeout(timer);
 },[mission.id,state.latestEventSeq,replay,playing,state.active]);
 const moving=visible&&!paused&&!reduced&&((!replay&&state.transport!=='none'&&state.active)||arriving);
 useEffect(()=>{
  const el=canvas.current;if(!el)return;const ctx=el.getContext('2d');if(!ctx)return;
  const dpr=Math.min(window.devicePixelRatio||1,1.6),w=size.width,h=size.height;el.width=Math.round(w*dpr);el.height=Math.round(h*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);
  if(eventRef.current.mission!==mission.id)eventRef.current={mission:mission.id,seq:state.latestEventSeq,at:0};
  else if(eventRef.current.seq!==state.latestEventSeq){eventRef.current={mission:mission.id,seq:state.latestEventSeq,at:performance.now()};}
  let frame=0,last=0;
  const draw=(now:number)=>{
   if(!last||now-last>=1000/30){const elapsed=last?Math.min(now-last,100):0;last=now;if(moving)orientation.current+=elapsed*.000065;
    const pulse=moving&&eventRef.current.at?clamp(1-(now-eventRef.current.at)/1100,0,1):0;paint(ctx,w,h,state,orientation.current,pulse);if(pulse>0)glow(ctx,positions(w,h).core,positions(w,h).radius*1.55,gold,pulse*.1);
   }
   if(moving)frame=requestAnimationFrame(draw);
  };
  draw(performance.now());return()=>cancelAnimationFrame(frame);
 },[state,size,moving,mission.id]);
 const p=positions(size.width,size.height),source=state.latestSource;
 const sourceText=source?String(source.text||source.chunks?.map((c:Item)=>c.text).join('\n\n')||'No extracted text was saved for this source.'):'The next collected page will appear here, with its actual address and extracted text.';
 const previewText=sourceText.slice(0,680);
 const measured=(mission.records.decision||[]).filter((d:Item)=>d.status==='complete'&&!d.cache&&typeof d.latency_ms==='number'&&Number.isFinite(d.latency_ms));
 const measuredIds=new Set(measured.map((d:Item)=>d.id));
 const measuredEvent=[...mission.events].reverse().find(e=>e.type==='jev.completed'&&measuredIds.has(e.payload?.decision_id));
 const lastMeasured=measuredEvent?measured.find((d:Item)=>d.id===measuredEvent.payload.decision_id):measured.at(-1);
 const decision=state.currentDecision||state.latestCompletedDecision;
 const textCall=state.currentTextCall||state.latestTextCall;
 const textPending=!!state.currentTextCall;
 const textFailed=!!textCall&&['error','failed','uncertain','blocked'].includes(textCall.status);
 const textMeasured=(mission.records.text_call||[]).filter((call:Item)=>call.status==='complete'&&typeof call.latency_ms==='number'&&Number.isFinite(call.latency_ms)).at(-1);
 const questions=decision?.questions||{},questionKey=Object.keys(questions).find(k=>k==='next')||Object.keys(questions).find(k=>questions[k]?.type==='choice')||Object.keys(questions)[0];
 const question=questions[questionKey],answer=decision?.status==='complete'?decision.answers?.[questionKey]:undefined;
 const options=question?.criteria&&typeof question.criteria==='object'&&!Array.isArray(question.criteria)?Object.entries(question.criteria):[];
 const selectedId=typeof answer?.choice==='string'?answer.choice:undefined;
 const selectedOption=options.find(([id])=>id===selectedId);
 const selectedLabel=selectedOption?String(selectedOption[1]):selectedId;
 const alternatives=options.filter(([id])=>id!==selectedId).slice(0,3);
 const finding=state.latestFinding;
 const fixture=!!(mission.mode==='fixture'||mission.fixture||mission.provenance==='fixture'||mission.plan?.fixture||mission.goal?.startsWith('[fixture]')||(mission.records.decision||[]).some((d:Item)=>d.provenance==='fixture'||String(d.model||'').includes('fixture')));
 const mode=fixture?'Fixture · recorded test data':replay?(playing?'Recorded replay · playing':'Recorded replay · paused'):state.active?'Live workflow':'Saved research';
 const readMode=state.transport==='metadata'?'Indexed metadata':state.transport==='browser_render'?'Browser requested':state.transport==='page_fetch'?'HTTP / cache':state.sourceMode==='rendered'?'Browser extraction':state.sourceMode==='cache'?'Cached text':source?.source_kind==='video'?'Video metadata':state.sourceMode==='http'?'HTTP text':'Public sources';
 const sourceMode=source?.source_kind==='video'?'VIDEO METADATA':state.sourceMode==='rendered'?'Browser extraction':state.sourceMode==='cache'?'Cached text':'HTTP text';
 return <section className="jev-stage" aria-label="Jev live research" data-motion={moving?'active':'frozen'} data-phase={state.phase}>
  <div className="jev-stage-scene" ref={scene}>
   <canvas className="jev-stage-canvas" ref={canvas} aria-hidden="true"/>
   <header className="jev-stage-top"><span className="jev-stage-brand"><GitBranch size={15}/> JEV <span>RESEARCH ENGINE</span></span><div className="jev-stage-controls"><span className={'jev-stage-mode '+(state.active&&!replay?'is-live':'')}><i/>{mode}</span><button type="button" className="jev-motion" aria-label={paused?'Resume visualization motion':'Pause visualization motion'} aria-pressed={paused||reduced} disabled={reduced} title={reduced?'Motion is disabled by your reduced-motion preference':paused?'Resume visual motion; research continues either way':'Pause visual motion; research keeps running'} onClick={()=>setPaused(v=>!v)}>{paused||reduced?<Play size={14}/>:<Pause size={14}/>}</button></div></header>
   <div className="jev-stage-now" role="status" aria-live="polite"><span className="jev-stage-kicker">{state.transport==='text_api'?'TEXT MODEL · GENERATIVE PROPOSALS':state.transport==='jev_api'?'STRUCTURED INTELLIGENCE':state.transport==='search_api'?'PUBLIC WEB DISCOVERY':state.transport==='metadata'?'INDEXED VIDEO EVIDENCE':['page_fetch','browser_render'].includes(state.transport)?'SOURCE ACQUISITION':replay?'YOUR RESEARCH, REPLAYED':'FROM QUESTION TO EVIDENCE'}</span><h2 className="jev-stage-status">{state.statusLabel}</h2><p className="jev-stage-current" title={state.requestLabel}>{state.requestLabel}</p></div>
   <button type="button" className="jev-core-label" style={{left:p.core.x,top:p.core.y}} onClick={()=>decision&&onDecision(decision.id)} disabled={!decision} aria-label={decision?'Inspect current Jev decision':'Jev research core'}><span style={{fontSize:clamp(p.radius*.59,37,66)}}>jev<span className="jev-core-dot">.</span></span><small>{state.transport==='text_api'?'AWAITING PROPOSALS':state.transport==='jev_api'?(state.currentDecisions.length>1?`${state.currentDecisions.length} REQUESTS IN FLIGHT`:'AWAITING RESPONSE'):replay?'RECORDED':state.counts.decisions+state.counts.cachedDecisions?`${state.counts.decisions+state.counts.cachedDecisions} SAVED DECISIONS`:'DECISION CORE'}</small></button>
   <div className={'jev-orbit-label '+(state.phase==='searching'?'is-current':'')} style={{left:p.search.x,top:p.search.y+24}}><Search size={13}/><strong>SEARCH</strong><small>{state.counts.searches} responses</small></div>
   <button type="button" className={'jev-orbit-label '+(['reading','rendering','reading_metadata'].includes(state.phase)?'is-current':'')} style={{left:p.read.x,top:p.read.y+24}} disabled={!source} onClick={()=>source&&onSource(source.id)} aria-label="Inspect latest source"><Globe size={13}/><strong>READ</strong><small>{state.counts.pages} sources · {readMode}</small></button>
   <button type="button" className={'jev-orbit-label '+(['assessing','verifying'].includes(state.phase)?'is-current':'')} style={{left:p.evidence.x,top:p.evidence.y+24}} disabled={!finding} onClick={()=>finding&&onFinding(finding.id)} aria-label="Inspect latest finding"><Layers size={13}/><strong>EVIDENCE</strong><small>{state.counts.findings} saved assessments</small></button>
   <div className="jev-stage-timing">{lastMeasured?<><span className="jev-timing-dot"/><strong>{ms(lastMeasured.latency_ms)}</strong><span>last Jev round-trip</span></>:<span>{state.counts.cachedDecisions?'Cached decisions · no new timing':'Waiting for first measured response'}</span>}</div>
   {(paused||reduced)&&<span className="jev-motion-note">{reduced?'Reduced motion':'Motion paused'} · data still updates</span>}
  </div>
  {state.currentDecisions.length>1&&<div className="jev-parallel-lane" aria-label="Concurrent Jev requests"><div className="jev-parallel-heading"><GitBranch size={16}/><strong>{state.currentDecisions.length} Jev requests in flight</strong><span>Actual pending provider requests</span></div><div className="jev-parallel-requests">{state.currentDecisions.map(request=>{const requestSource=(mission.records.source||[]).find((item:Item)=>item.id===request.source_id);return <button key={request.id} onClick={()=>onDecision(request.id)} aria-label={`Inspect pending Jev request: ${request.purpose}${requestSource?` · ${requestSource.title||requestSource.url}`:''}`}><span className="jev-pending-dot"/><span><strong>{request.purpose}</strong><small>{requestSource?.title||requestSource?.url||'Research decision'} · awaiting response</small></span><ArrowUpRight size={12}/></button>;})}</div></div>}
  {textCall&&<div className={'jev-text-lane '+(textPending?'is-pending ':'')+(textFailed?'is-failed':'')} aria-label="Text model activity"><span className="jev-text-icon"><Sparkles size={20}/></span><div><span className="jev-text-kicker">TEXT MODEL <span>→</span> JEV</span><strong>{textPending?state.statusLabel:textFailed?'Text model request did not complete':textCall.status==='complete'?'Proposal received · Jev checks before use':'Saved text model request'}</strong><p>{textCall.provider} · {textCall.model} · {textCall.purpose}</p></div><span className="jev-text-timing">{textPending?'Waiting for provider':textFailed?'No successful response':textMeasured?<><strong>{ms(textMeasured.latency_ms)}</strong> text model round-trip</>:'No measured text response'}</span></div>}
  <div className="jev-stage-details">
   <article className="jev-source-preview"><div className="jev-window-bar"><span className="jev-window-dots" aria-hidden="true"><i/><i/><i/></span><span><Globe size={11}/>{source?String(source.url):'Awaiting a public source'}</span>{source&&<button aria-label="Open source evidence" onClick={()=>onSource(source.id)}><ArrowUpRight size={14}/></button>}</div><div className="jev-window-body"><div className="jev-detail-eyebrow"><FileText size={12}/>{source?sourceMode:'SOURCE WINDOW'}<span>{source?.source_kind==='video'?'Collected metadata':'Extracted text'}</span></div><h3>{source?source.title||'Untitled source':'A window into the source'}</h3><p>{previewText}{sourceText.length>680?'…':''}</p>{source&&<button className="jev-stage-link" onClick={()=>onSource(source.id)}>Read collected evidence <ArrowRight size={13}/></button>}</div></article>
   <article className="jev-choice-preview"><div className="jev-detail-eyebrow"><GitBranch size={13}/>{decision?.status==='inflight'?'JEV IS CONSIDERING':'INSIDE THE DECISION'}{decision?.cache&&<span>Cached</span>}</div><h3>{state.collectionSelection?'Which records should be inspected together?':decision?(questionKey==='next'?'What should happen next?':questionKey?.replaceAll('_',' ')):'The next step is a decision.'}</h3>{decision?<><p className="jev-choice-purpose">{decision.purpose}</p>{state.collectionSelection?<div className="jev-collection-choices" aria-label="Independent record choices">{state.collectionSelection.items.map(item=><button key={item.actionId} onClick={()=>item.sourceId?onSource(item.sourceId):onDecision(state.collectionSelection!.decisionId)} aria-label={`Inspect selection for ${item.url||'observed record'}`}><span className={'jev-collection-status '+(item.choice||'pending')}>{item.choice==='inspect'?<Check size={12}/>:null}{item.choice==='inspect'?'Selected':item.choice==='defer'?'Deferred':'Awaiting choice'}</span><span className="jev-collection-url">{item.url||'Observed record'}<ArrowUpRight size={11}/></span>{item.description&&<small>{item.description}</small>}</button>)}<p>Each selected record is assessed against the shared research questions. Deferred records are left out of this batch.</p></div>:<>{selectedLabel?<div className="jev-selected-option"><Check size={14}/><span>{selectedLabel}</span></div>:decision.status==='inflight'?<div className="jev-pending-option"><span/>Waiting for Jev’s response</div>:<p className="jev-answer-summary">{answer?JSON.stringify(answer):'No response was saved for this question.'}</p>}{alternatives.length>0&&<div className="jev-choice-alternatives"><span>{selectedLabel?'Other supplied choices':'Supplied choices'}</span>{alternatives.map(([id,label])=><div key={id}><span/>{String(label)}</div>)}{options.length>(selectedId?4:3)&&<small>+ {options.length-(selectedId?4:3)} more in the full request</small>}</div>}</>}<button className="jev-stage-link" onClick={()=>onDecision(decision.id)}>Inspect actual request <ChevronRight size={14}/></button></>:<p>Jev will select from the available actions, assess collected pages and check their evidence against your question.</p>}</article>
  </div>
  {finding&&<button className="jev-latest-finding" onClick={()=>onFinding(finding.id)}><span className="jev-finding-icon"><BookOpen size={17}/></span><span><small>LATEST SAVED ASSESSMENT · {String(finding.status||'unknown').replaceAll('_',' ')}{finding.stale?' · previous plan':''}{finding.review==='rejected'?' · rejected':''}</small><strong>{finding.statement||finding.question||'Inspect the saved assessment and its evidence'}</strong></span><ArrowUpRight size={17}/></button>}
  <p className="jev-stage-footnote">{replay?'Recorded events at this replay position. ':''}Motion reflects recorded work. Timings include the network and provider. Source assessments do not establish that a publisher’s claims are true.</p>
 </section>;
}
