import {ArrowRight,BookOpen,CheckCircle2,Clock,Globe,Info} from 'lucide-react';
import {rows,ms,type Mission,type Item} from './api';

export function PlanReadiness({preview,onAction}:{preview:Item;onAction:(kind:string)=>void}){
 const readiness=preview.readiness;
 return <div className="plan-readiness">
  <div className="scope-heading"><Globe size={18}/><strong>{readiness?.summary||preview.coverage}</strong></div>
  {(readiness?.warnings||[]).map((w:Item)=><div className="readiness-message" key={w.code}><Info size={17}/><div><strong>{w.title}</strong><p>{w.message}</p>{w.action==='settings'&&<button className="text-link" onClick={()=>onAction(w.action)}>How to enable web search <ArrowRight size={13}/></button>}</div></div>)}
  {(readiness?.blockers||[]).map((b:Item)=><p key={b.code} className="readiness-blocker" role="alert">{b.message}</p>)}
 </div>;
}

export function ResearchSummary({mission,onAction,onDecision}:{mission:Mission;onAction:(kind:string)=>void;onDecision:(id:string)=>void}){
 const o=mission.outcome;
 const active=['running','pausing'].includes(mission.status);
 const videos=rows(mission,'source').filter(source=>source.source_kind==='video');
 const program=rows(mission,'research_program').at(-1);
 const videoResearch=program?program.unit==='videos':videos.length>0;
 const decisions=rows(mission,'decision'),last=decisions.at(-1);
 const completedDecision=(!active&&decisions.find(d=>d.id===o?.stop?.decision_id))||last;
 const action=rows(mission,'action').find(a=>a.status==='running');
 const n=rows(mission,'finding').filter(f=>f.status==='supported'&&!f.stale).length;
 const count=o?.counts||{pages:mission.telemetry.pages,supported_findings:n,alternative_candidates:0};
 const labels:Record<string,string>={draft:'Ready to start',running:'Research in progress',pausing:'Finishing the current step',paused:'Paused',partial:'Needs more evidence',blocked:'Needs attention',interrupted:'Interrupted',cancelled:'Stopped',complete:'Research finished'};
 const phases:Record<string,string>={'Refine discovery for unanswered questions':'Choosing a focused follow-up search','Design research approach':'Designing the research approach','Compare observed artifacts':'Comparing collected evidence','Analyze individual artifact and select evidence':'Analyzing an individual artifact','Choose next research action':'Choosing what to read next','Assess source and select evidence passages':'Reading the source','Verify selected evidence against each question':'Checking the supporting passages','Prioritize prepared experiments':'Comparing possible next steps'};
 const completedPhases:Record<string,string>={'Refine discovery for unanswered questions':'Selected a discovery refinement','Design research approach':'Designed the research approach','Compare observed artifacts':'Compared collected evidence','Analyze individual artifact and select evidence':'Analyzed an individual artifact','Choose next research action':'Selected the next research step','Assess source and select evidence passages':'Read the source','Verify selected evidence against each question':'Checked the supporting passages','Prioritize prepared experiments':'Compared possible next steps'};
 return <section className={'outcome-card '+(active?'is-running':'')} aria-label="Research summary">
  <div className="outcome-eyebrow">{active?<Clock size={17}/>:<BookOpen size={17}/>} {labels[mission.status]||mission.status}</div>
  <h2>{videoResearch?(active?'Investigating individual videos':videos.length?'Video investigation coverage':'No individual video evidence collected'):o?.headline||(active?'Following your question through the sources':'Your findings so far')}</h2>
  <p className="outcome-summary">{mission.status==='draft'?o?.readiness?.summary:videoResearch?'Open a video record to check its collected metadata, available text and evidence limits.':o?.readiness?.alternatives_requested?'Findings describe the pages actually reviewed. Candidate alternatives still need checking against your requirements.':'Open a finding to check the exact passage behind it.'}</p>
  <div className="outcome-counts"><span><strong>{count.supported_findings}</strong> supported findings</span><span><strong>{videoResearch?(count.primary_artifacts??new Set(videos.map(video=>video.unit_id||video.url)).size):count.pages}</strong> {videoResearch?(count.primary_artifacts!=null?'distinct relevant videos assessed':'individual videos collected'):count.pages===1?'website page reviewed':'website pages reviewed'}</span>{o?.readiness?.alternatives_requested&&<span><strong>{count.alternative_candidates}</strong> alternative candidates</span>}</div>
  {!active&&o?.stop?.message&&<div className="outcome-explanation"><Info size={17}/><p>{o.stop.message}</p></div>}
  {!!o?.gaps?.length&&!active&&<p className="outcome-gaps">Still unanswered: {o.gaps.map((g:any)=>typeof g==='string'?g:g.label||g.question).join(' · ')}</p>}
  {active&&<div className="live-progress"><span className="live-dot"/><span>{last?.status==='inflight'?(phases[last.purpose]||last.purpose):action?`${action.kind==='search'?'Searching':'Reading'} ${action.value}`:'Preparing the next step'}</span></div>}
  {!active&&mission.status!=='cancelled'&&<div className="outcome-actions">{(o?.next_steps||[]).filter((s:Item)=>s.kind!=='review_results').slice(0,2).map((s:Item,i:number)=><button key={s.kind} title={s.detail} className={i===0?'primary':'secondary'} onClick={()=>onAction(s.kind)}>{s.kind==='add_sources'?'Add websites':s.label}<ArrowRight size={15}/></button>)}</div>}
  {completedDecision?.status==='complete'&&<div className="decision-peek"><CheckCircle2 size={14}/><span>{!active&&completedDecision.id===o?.stop?.decision_id&&o?.stop?.code==='jev_abstained'?'Jev chose to stop':completedPhases[completedDecision.purpose]||completedDecision.purpose} · {completedDecision.cache?'cached':ms(completedDecision.latency_ms)}</span><button className="text-link" onClick={()=>onDecision(completedDecision.id)}>View Jev decision</button></div>}
 </section>;
}
