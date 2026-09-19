import {useState} from 'react';
import {ArrowRight,BookOpen,Check,ChevronDown,Clock,GitBranch,Layers,ScanSearch,Sparkles} from 'lucide-react';
import {ms,rows,type Item,type Mission} from './api';
import {deriveStageState} from './jev-stage-state';

const stages=[
 {id:'planning',label:'Design the approach',icon:GitBranch,description:'Choose the research unit, questions and evidence needed for this goal.'},
 {id:'selection',label:'Choose the next step',icon:GitBranch,description:'Select a source or search that addresses an evidence gap.'},
 {id:'screen',label:'Assess the source',icon:ScanSearch,description:'Judge relevance and distinguish competitors from background sources.'},
 {id:'check',label:'Check the evidence',icon:BookOpen,description:'Select exact passages, then check whether they answer the question.'},
 {id:'comparison',label:'Compare the artifacts',icon:Layers,description:'Assess similarities, differences and possible explanations across inspected artifacts.'},
 {id:'priorities',label:'Suggest what to try',icon:Sparkles,description:'Prioritize a prepared experiment using the collected evidence.'},
];
const stageOf=(stage:string)=>['classification','relevance'].includes(stage)?'screen':['evidence','verification'].includes(stage)?'check':stage;

/** Read-only rendering of saved request/answer records. Replay filters out future decisions. */
export default function JevActivity({mission,replay,onDecision,onFinding,onSource,onReplay}:{mission:Mission;replay:boolean;onDecision:(id:string)=>void;onFinding:(id:string)=>void;onSource:(id:string)=>void;onReplay:()=>void}){
 const [stage,setStage]=useState('recent'),[visible,setVisible]=useState(1);
 const decisions=rows(mission,'decision'),decisionMap=new Map(decisions.map(d=>[d.id,d]));
 const groups:Item[]=mission.jev_activity?.groups||[];
 const items:Item[]=groups.flatMap(g=>(g.items||[]).map((item:Item)=>({...item,stage:item.stage||g.id})))
  .filter(item=>decisionMap.has(item.decision_id)&&(!replay||decisionMap.get(item.decision_id)?.status==='complete'))
  .map(item=>!replay?item:{...item,
   result:'Recorded answer at this point in the run. Follow the linked evidence available at this replay position.',
   finding_ids:(item.finding_ids||[]).filter((id:string)=>rows(mission,'finding').some(f=>f.id===id)),
   source_ids:(item.source_ids||[]).filter((id:string)=>rows(mission,'source').some(s=>s.id===id))});
 const order=new Map(decisions.map((d,i)=>[d.id,i]));
 items.sort((a,b)=>(order.get(b.decision_id)||0)-(order.get(a.decision_id)||0));
 const displayed=(stage==='recent'?items:items.filter(i=>stageOf(i.stage)===stage));
 // One answer per request in the overview keeps a batched assessment from dominating it.
 const seen=new Set<string>();
 const recent=stage==='recent'?displayed.filter(i=>{if(seen.has(i.decision_id))return false;seen.add(i.decision_id);return true}):displayed;
 const finished=decisions.filter(d=>d.status==='complete');
 const measured=finished.filter(d=>!d.cache&&Number.isFinite(d.latency_ms));
 const timings=measured.map(d=>d.latency_ms as number).sort((a,b)=>a-b);
 const median=timings.length?(timings[Math.floor((timings.length-1)/2)]+timings[Math.floor(timings.length/2)])/2:null;
 const visualState=deriveStageState(mission,replay);
 const inflight=replay?[...decisions].reverse().find(d=>d.status==='inflight'):visualState.currentDecision;
 const active=!replay&&['running','pausing'].includes(mission.status);
 const action=visualState.currentAction;
 const eventIds=new Set(mission.events.map(e=>e.id));
 const deterministic:Item[]=(mission.jev_activity?.deterministic||[]).filter((x:Item)=>!replay||eventIds.has(x.event_id));
 const answered=finished.reduce((n,d)=>n+Object.keys(d.answers||{}).length,0);
 const currentLabel=visualState.currentTextCall?`Text model · ${visualState.currentTextCall.purpose}`:inflight?(replay?'Recorded pending request · '+inflight.purpose:inflight.purpose):action?`${action.kind==='search'?'Searching the web':action.kind==='video'?'Inspecting indexed metadata':action.kind==='reassess'?'Reassessing saved evidence':'Reading a source'} · ${action.value}`:active?'Preparing the next research step':replay?'Showing decisions at this replay position':'This run’s decisions are saved below';
 return <section className={'jev-workbench '+(active?'jev-active':'')} aria-label="Jev in action">
  <div className="jev-heading"><div className="jev-mark"><GitBranch size={22}/></div><div><div className="eyebrow">THE DECISION LAYER</div><h2>Jev in action</h2></div><span className={'jev-state '+(active?'active':'')}>{mission.mode==='fixture'?'Test fixture':replay?'Recorded replay':active?'Live':'Saved decisions'}</span></div>
  <p className="jev-intro">Follow how your question becomes a choice, a checked passage, and a next step.</p>
  <div className="jev-numbers"><span><strong>{answered}</strong> typed answers <small>{finished.filter(d=>!d.cache).length} live requests{finished.some(d=>d.cache)?` + ${finished.filter(d=>d.cache).length} cached`:''}</small></span><span><strong>{ms(median)}</strong> median response <small>{measured.length?`measured round-trip · ${measured.length} calls`:'waiting for a measured response'}</small></span><span><strong>{items.filter(i=>i.stage==='verification'&&i.status==='complete').length}</strong> passage checks <small>against the research questions</small></span></div>
  <div className="jev-stages" aria-label="Decision stages">{stages.map(({id,label,icon:Icon,description},index)=>{
   const groupItems=items.filter(i=>stageOf(i.stage)===id),count=groupItems.filter(i=>i.status==='complete'&&i.selected).length;
   const pending=!!inflight&&(id==='planning'?/Design research approach|Approve goal-specific research questions/.test(inflight.purpose):id==='comparison'?inflight.purpose==='Compare observed artifacts':id==='selection'?/next research|Refine discovery|Choose evidence-driven follow-up|Select independent records/.test(inflight.purpose):id==='screen'?/Assess|Analyze individual artifact/.test(inflight.purpose):id==='check'?/Verify|Check (?:research|proposed) answer against cited evidence/.test(inflight.purpose):inflight.purpose.includes('Prioritize'));
   return <button key={id} className={(stage===id?'selected ':'')+(pending?'pending':'')} aria-pressed={stage===id} onClick={()=>{setStage(stage===id?'recent':id);setVisible(1)}} title={description}><span className="stage-index">0{index+1}</span><Icon size={19}/><strong>{label}</strong><small>{pending?(replay?'Pending at this point':'Jev is responding…'):count?`${count} recorded answers`:'No answers yet'}</small></button>
  })}</div>
  <div className="jev-now" role="status"><span className={active?'live-dot':'saved-dot'}/><span>{currentLabel}</span>{inflight&&!replay&&<span className="jev-awaiting">Waiting for API</span>}</div>
  <div className="jev-log-heading"><strong>{stage==='recent'?'Recent decisions':stages.find(s=>s.id===stage)?.label}</strong><div>{stage!=='recent'&&<button className="text-link" onClick={()=>{setStage('recent');setVisible(1)}}>All stages</button>}{!!mission.events.length&&!replay&&<button className="text-link" onClick={onReplay}><Clock size={13}/> Replay run</button>}</div></div>
  {recent.slice(0,visible).map(item=>{
   const d=decisionMap.get(item.decision_id)!;
   const q=d.questions?.[item.question_id];
   const selected=item.selected;
   const source=rows(mission,'source').find(s=>(item.source_ids||[]).includes(s.id));
   const alternatives=(item.alternatives||[]).filter((a:Item)=>a.id!==selected?.id).slice(0,4);
   return <article className="jev-decision" key={item.id||`${item.decision_id}-${item.question_id}`}>
    <div className="jev-decision-meta"><span>{item.stage==='verification'?'Passage check':item.stage==='evidence'?'Evidence selection':stages.find(s=>s.id===stageOf(item.stage))?.label||item.stage}</span><span>{d.cache?'Cached answer':d.status==='complete'?ms(d.latency_ms):d.status}</span></div>
    <h3>{item.title}</h3>
    {selected&&<div className="jev-choice"><Check size={15}/><span>{item.type==='noul'&&selected.value!=null?`${(selected.value*100).toFixed(1)}% estimated probability of “yes”`:selected.value!=null&&selected.maximum!=null?`${selected.value} / ${selected.maximum} on the supplied rubric`:selected.label??String(selected.value??selected.id)}</span></div>}
    {item.result&&<p className="jev-effect"><ArrowRight size={15}/><span>{typeof item.result==='string'?item.result:item.result.summary||item.result.label||JSON.stringify(item.result)}</span></p>}
    <div className="jev-links">{(item.finding_ids||[]).slice(0,2).map((id:string)=><button key={id} className="text-link" onClick={()=>onFinding(id)}><BookOpen size={13}/> Open linked finding</button>)}{source&&<button className="text-link" onClick={()=>onSource(source.id)}>Read source</button>}<button className="text-link" onClick={()=>onDecision(d.id)}>Full request &amp; answers</button></div>
    {(q||alternatives.length>0)&&<details className="jev-why"><summary>Question &amp; considered options <ChevronDown size={13}/></summary>{q?.instructions&&<p>{q.instructions}</p>}{alternatives.length>0&&<><p className="small muted">Other supplied choices{alternatives.some((a:Item)=>a.probability!=null)?' · response probabilities, not factual accuracy':''}</p>{alternatives.map((a:Item)=><div className="jev-alternative" key={a.id}><span>{a.label||a.id}</span>{a.probability!=null&&<b>{(a.probability*100).toFixed(1)}%</b>}</div>)}</>}</details>}
   </article>
  })}
  {!recent.length&&<div className="jev-empty"><Layers size={21}/><p>{inflight?(replay?'This request was pending at this replay position. Advance the replay to inspect its recorded response.':'A real request is in flight. Its selected answer will appear when the provider responds.'):active?'Public content is being acquired. Jev’s responses will appear as they arrive.':mission.status==='draft'?'Start the investigation to see actual choices and supporting evidence here.':'No saved answers for this stage.'}</p></div>}
  {recent.length>1&&<div className="jev-log-controls">{visible<recent.length&&<button className="text-link jev-more" onClick={()=>setVisible(n=>n+10)}>Show more decisions ({recent.length-visible})<ChevronDown size={14}/></button>}{visible>1&&<button className="text-link jev-more" onClick={()=>setVisible(1)}>Show fewer</button>}</div>}
  {!!deterministic.length&&<details className="jev-rules"><summary>{deterministic.length} steps followed workflow rules</summary><p>Reference prerequisites, a single available action, and periodic exploration do not need a Jev choice.</p>{deterministic.slice(-6).map((step:Item)=><p key={step.event_id}><strong>{step.label}</strong> · {step.reason}</p>)}</details>}
  <p className="jev-footnote">{finished.filter(d=>d.cache).length>0&&<>{finished.filter(d=>d.cache).length} cached requests reused without new inference. </>}Timings include the network and provider. Batched answers share a request. Source checks assess the supplied text; they do not establish that a publisher’s claims are true.</p>
 </section>;
}
