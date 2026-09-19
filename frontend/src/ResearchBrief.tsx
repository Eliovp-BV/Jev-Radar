import {ArrowUpRight,BookOpen,CheckCircle2,GitBranch,Lightbulb} from 'lucide-react';
import {ms,rows,type Item,type Mission} from './api';
import {deriveResearchEvidence} from './research-validity';

const list=(value:unknown):Item[]=>Array.isArray(value)?value:[];

export default function ResearchBrief({mission,filter,onFinding,onDecision}:{mission:Mission;filter:string;onFinding:(id:string)=>void;onDecision:(id:string)=>void}){
 // The server exposes only a current, verified projection. Never resurrect a saved
 // draft or older brief when it is absent (including review or scope changes).
 const answer=mission.outcome?.research_answer;
 const evidence=deriveResearchEvidence(mission),program=evidence.program;
 if(!answer||answer.stale||answer.plan_version!==mission.plan_version||answer.program_id!==(program?.id||null))return null;
 const sourceIds=new Set(evidence.sources.map(item=>item.id)),findingIds=new Set(evidence.findings.map(item=>item.id)),spanIds=new Set(evidence.spans.map(item=>item.id));
 const completedDecisions=new Set(rows(mission,'decision').filter(item=>item.status==='complete').map(item=>item.id));
 const validClaims=list(answer.claims).filter(claim=>['supported','qualified'].includes(claim.status)&&completedDecisions.has(claim.decision_id||answer.verification_decision_id)&&list(claim.citations).length>0&&list(claim.citations).every(citation=>sourceIds.has(citation.source_id)&&findingIds.has(citation.finding_id)&&spanIds.has(citation.span_id)));
 const claimIds=new Set(validClaims.map(claim=>claim.id));
 const claims=validClaims.filter(claim=>!filter||String(claim.text).toLowerCase().includes(filter.toLowerCase()));
 const recommendations=list(answer.recommendations).filter(item=>item.status==='proposed'&&item.performed===false&&Array.isArray(item.claim_ids)&&item.claim_ids.length>0&&item.claim_ids.every((id:string)=>claimIds.has(id)));
 const unknowns=Array.isArray(answer.unknowns)?answer.unknowns.filter((item:unknown)=>typeof item==='string'):[];
 return <section className="research-brief" aria-label="Evidence-linked research answer">
  <div className="brief-heading"><div><span className="eyebrow">YOUR RESEARCH ANSWER</span><h2>{validClaims.length?'What the evidence tells us':'The evidence does not yet support an answer'}</h2><p>Written from collected findings, with each displayed claim checked by Jev against its cited passages. This checks source support; it does not independently prove the source is correct.</p></div>{answer.verification_decision_id&&completedDecisions.has(answer.verification_decision_id)&&<button className="secondary" onClick={()=>onDecision(answer.verification_decision_id)}><GitBranch size={15}/> Inspect answer check</button>}</div>
  {answer.status==='partial'&&<p className="brief-partial">Partial answer · some questions remain unresolved.</p>}
  <div className="brief-claims">{claims.map(claim=><article className={'brief-claim '+(claim.status==='qualified'?'qualified':'')} key={claim.id}><div className="brief-claim-type">{claim.status==='supported'?<CheckCircle2 size={14}/>:<Lightbulb size={14}/>}<span>{claim.kind==='hypothesis'?'Possible explanation':claim.status==='qualified'?'Qualified conclusion':'Supported by cited evidence'}</span></div><p>{claim.text}</p><details className="brief-citations"><summary><BookOpen size={13}/> {claim.citations.length} supporting {claim.citations.length===1?'passage':'passages'}</summary>{claim.citations.map((citation:Item,index:number)=><blockquote key={citation.span_id+'-'+index}>{citation.field&&<span className="small muted">{citation.field.replaceAll('_',' ')}</span>}<p>{citation.quote}</p><footer><button className="text-link" onClick={()=>onFinding(citation.finding_id)}>Inspect source &amp; finding <ArrowUpRight size={12}/></button><span>Text offsets {citation.start}–{citation.end}</span></footer></blockquote>)}</details></article>)}</div>
  {!!filter&&!claims.length&&validClaims.length>0&&<p className="small muted">No answer claims match this filter.</p>}
  {recommendations.length>0&&<div className="brief-recommendations"><h3>What you could do next</h3><p>Proposed actions based on the checked findings. These actions have not been performed and their outcomes are not established.</p><ol>{recommendations.map(item=><li key={item.id}>{item.text}</li>)}</ol></div>}
  {unknowns.length>0&&<div className="brief-unknowns"><h3>What remains unknown</h3><ul>{unknowns.map((unknown:string,index:number)=><li key={index}>{unknown}</li>)}</ul></div>}
  <div className="brief-provenance"><span>Draft: {answer.provenance?.provider||'configured text provider'}{answer.provenance?.model?` · ${answer.provenance.model}`:''}{typeof answer.provenance?.latency_ms==='number'?` · ${ms(answer.provenance.latency_ms)} measured round-trip`:''}</span><span>Claim checks: Jev{answer.unsupported_claim_count>0?` · ${answer.unsupported_claim_count} unsupported ${answer.unsupported_claim_count===1?'claim':'claims'} withheld`:''}</span></div>
 </section>;
}
