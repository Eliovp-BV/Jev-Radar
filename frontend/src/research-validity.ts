import type {Item,Mission} from './api';

const rows=(mission:Mission,kind:string):Item[]=>mission.records?.[kind]||[];

const array=(value:unknown):any[]=>Array.isArray(value)?value:[];
const rejected=(record:Item)=>!!record.stale||!!record.excluded||record.review==='rejected';
const host=(url:unknown)=>{try{return new URL(String(url)).hostname.toLowerCase();}catch{return '';}};

export function currentResearchProgram(mission:Mission):Item|undefined {
 return rows(mission,'research_program').filter(program=>!rejected(program)&&program.plan_version===mission.plan_version).at(-1);
}

/** Match backend snapshot ordering before checking eligibility: reassessing an
 * older snapshot cannot outrank more recently acquired observations. */
export function latestArtifactAssessment(mission:Mission,sourceIds:string[],eligible:Item[]):Item|undefined {
 const program=currentResearchProgram(mission);
 if(!program)return undefined;
 const sources=new Map(rows(mission,'source').map(source=>[source.id,source]));
 const candidates=rows(mission,'artifact_analysis').map((record,position)=>({record,position,
  observed:Date.parse(sources.get(record.source_id)?.retrieved_at||'')||0})).filter(({record})=>sourceIds.includes(record.source_id)&&record.plan_version===mission.plan_version&&record.program_id===program.id);
 const latest=candidates.sort((left,right)=>left.observed-right.observed||left.position-right.position).at(-1)?.record;
 return latest?eligible.find(record=>record.id===latest.id):undefined;
}

/** Conservative projection only. Historical observations stay saved, but changed
 * scope or reviewed evidence cannot keep an old comparison looking current. */
export function deriveResearchEvidence(mission:Mission){
 const program=currentResearchProgram(mission);
 const excludedNames=new Set(array(mission.plan?.excluded_entities).map(value=>String(value).toLowerCase()));
 const excludedDomains=array(mission.plan?.excluded_domains).map(value=>String(value).toLowerCase());
 const entities=rows(mission,'entity');
 const excludedEntities=new Set(entities.filter(entity=>rejected(entity)||excludedNames.has(String(entity.name||'').toLowerCase())||array(entity.domains).some(domain=>excludedNames.has(String(domain).toLowerCase()))).map(entity=>entity.id));
 const sources=rows(mission,'source').filter(source=>{
  const domain=host(source.url);
  return !rejected(source)&&!excludedEntities.has(source.entity_id)&&!excludedNames.has(String(source.title||'').toLowerCase())&&!excludedNames.has(domain)&&!excludedDomains.some(excluded=>domain===excluded||domain.endsWith('.'+excluded));
 });
 const sourceIds=new Set(sources.map(source=>source.id));
 const allFindings=rows(mission,'finding');
 const rejectedSpans=new Set(allFindings.filter(rejected).flatMap(finding=>array(finding.span_ids)));
 const spans=rows(mission,'span').filter(span=>!rejected(span)&&sourceIds.has(span.source_id)&&!rejectedSpans.has(span.id));
 const spanIds=new Set(spans.map(span=>span.id));
 const findings=allFindings.filter(finding=>!rejected(finding)&&(finding.rubric_version==null||finding.rubric_version===mission.plan_version)&&array(finding.source_ids).every(id=>sourceIds.has(id))&&array(finding.span_ids).every(id=>spanIds.has(id)));
 const firstEvent=new Map<string,number>(),reviewStates=new Map<string,string>();
 let lastReview=0;
 for(const event of mission.events||[]){
  const seq=Number(event.seq)||0;
  let changedRejection=event.type==='review.saved'&&event.payload?.state==='rejected';
  for(const change of event.payload?.record_changes||[]){
   if(!firstEvent.has(change.record.id))firstEvent.set(change.record.id,seq);
   if(event.type==='review.saved'&&(change.record.review==='rejected'||reviewStates.get(change.record.id)==='rejected'))changedRejection=true;
   if(typeof change.record.review==='string')reviewStates.set(change.record.id,change.record.review);
  }
  if(changedRejection||['plan.revised','plan.steered'].includes(event.type))lastReview=Math.max(lastReview,seq);
 }
 const current=(record:Item)=>!!program&&!rejected(record)&&record.plan_version===mission.plan_version&&record.program_id===program.id;
 const validRefs=(record:Item)=>[...array(record.source_ids),...array(record.comparison_source_ids)].every(id=>sourceIds.has(id))&&array(record.span_ids).every(id=>spanIds.has(id));
 const features=rows(mission,'artifact_analysis').filter(record=>current(record)&&sourceIds.has(record.source_id)&&Object.values(record.features||{}).every((feature:any)=>array(feature?.span_ids).every(id=>spanIds.has(id))));
 const analyses=rows(mission,'research_analysis');
 // Never fall back to an earlier comparison after the latest one is invalidated.
 const latest=analyses.at(-1);
 const fresh=!!latest&&current(latest)&&(!lastReview||(firstEvent.get(latest.id)??0)>lastReview)&&array(latest.patterns).every(validRefs)&&array(latest.comparisons).every(validRefs);
 const analysis=fresh?latest:undefined;
 const invalidated=!!latest&&!analysis;
 const invalidationReason=invalidated?(String(latest.stale_reason||'')||'The research scope or reviewed evidence changed. Earlier comparisons are hidden until Jev reassesses the current evidence.') : '';
 return {program,sources,spans,findings,features,analysis,invalidated,invalidationReason};
}
