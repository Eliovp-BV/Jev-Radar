import type {Item, Mission} from './api';

export type StagePhase = 'idle'|'proposing'|'drafting'|'planning'|'comparing'|'choosing'|'assessing'|'verifying'|'prioritizing'|'searching'|'reading_metadata'|'reading'|'rendering'|'processing';
export interface StageState {
 phase: StagePhase;
 active: boolean;
 statusLabel: string;
 requestLabel: string;
 currentDecision?: Item;
 currentDecisions: Item[];
 collectionSelection?: {decisionId:string;items:{actionId:string;url:string;description:string;choice?:string;sourceId?:string}[]};
 currentAction?: Item;
 currentSearch?: Item;
 currentTextCall?: Item;
 latestTextCall?: Item;
 latestCompletedDecision?: Item;
 latestSource?: Item;
 latestFinding?: Item;
 counts: {searches:number;pages:number;findings:number;supportedFindings:number;decisions:number;cachedDecisions:number};
 chosen?: {decision:Item;id:string;label:string;alternatives:{id:string;label:string}[]};
 latestEventSeq: number;
 transport: 'none'|'search_api'|'jev_api'|'text_api'|'page_fetch'|'browser_render'|'metadata';
 sourceMode: 'metadata'|'http'|'rendered'|'cache'|null;
}

/** Saved records and event boundaries only; no clocks, inferred progress or model calls. */
export function deriveStageState(mission:Mission,replay:boolean):StageState {
 const records=mission.records||{},events=mission.events||[];
 const decisions:Item[]=records.decision||[],actions:Item[]=records.action||[],sources:Item[]=records.source||[],findings:Item[]=records.finding||[];
 const created=new Map<string,number>(),completed=new Map<string,number>();
 let segment=0,latestEventSeq=0;
 for(const event of events){
  const seq=Number(event.seq)||0;
  latestEventSeq=Math.max(latestEventSeq,seq);
  if(['mission.start','mission.resume','mission.retry'].includes(event.type))segment=Math.max(segment,seq);
  for(const change of event.payload?.record_changes||[])if(!created.has(change.record.id))created.set(change.record.id,seq);
  if(['jev.completed','decision.cached'].includes(event.type)&&event.payload?.decision_id)completed.set(event.payload.decision_id,seq);
 }
 const latest=(items:Item[],ranks=created):Item|undefined=>items.reduce<Item|undefined>((last,item)=>{
  if(!last)return item;
  const left=ranks.get(last.id),right=ranks.get(item.id);
  if(left!==undefined||right!==undefined)return (right??-1)>=(left??-1)?item:last;
  const previous=last.created_at||last.retrieved_at||'',next=item.created_at||item.retrieved_at||'';
  return next>=previous?item:last;
 },undefined);
 const started=(type:string,key:string)=>new Set(events.filter(e=>e.type===type&&(Number(e.seq)||0)>segment).map(e=>e.payload?.[key]).filter(Boolean));
 const live=!replay&&['running','pausing'].includes(mission.status);
 const decisionStarts=started('jev.started','decision_id'),actionStarts=started('action.started','action_id'),searchStarts=started('search.started','attempt_id');
 const textCalls:Item[]=records.text_call||[];
 const textStarts=started('text.started','call_id');
 const currentTextCall=live?latest(textCalls.filter(call=>['inflight','running'].includes(call.status)&&textStarts.has(call.id))):undefined;
 const latestTextCall=latest(textCalls);
 // Recovery retains uncertain old records. Only this run segment can be active.
 const closedDecisions=started('jev.completed','decision_id');
 for(const id of started('jev.error','decision_id'))closedDecisions.add(id);
 const currentDecisions=live?decisions.filter(d=>d.status==='inflight'&&!d.cache&&decisionStarts.has(d.id)&&!closedDecisions.has(d.id)):[];
 const currentDecision=latest(currentDecisions);
 const currentAction=live?latest(actions.filter(a=>a.status==='running'&&actionStarts.has(a.id))):undefined;
 const currentSearch=live&&currentAction?.kind==='search'?latest((records.search_attempt||[]).filter((s:Item)=>s.status==='running'&&s.action_id===currentAction.id&&searchStarts.has(s.id))):undefined;
 const latestSource=latest(sources),latestFinding=latest(findings);
 const latestCompletedDecision=latest(decisions.filter(d=>d.status==='complete'),completed);
 const displayedDecision=currentDecision||latestCompletedDecision;
 const collectionSelection=displayedDecision?.purpose==='Select independent records for parallel assessment'?{
  decisionId:displayedDecision.id,
  items:Object.keys(displayedDecision.questions||{}).map(actionId=>{
   const lead=displayedDecision.state?.observed_leads?.[actionId]||{},action=actions.find(item=>item.id===actionId);
   const choice=displayedDecision.status==='complete'?displayedDecision.answers?.[actionId]?.choice:undefined;
   return {actionId,url:String(lead.url||action?.value||''),description:String(lead.description||action?.description||''),choice,
    sourceId:choice==='inspect'?sources.find(source=>source.action_id===actionId)?.id:undefined};
  }),
 }:undefined;
 const selection=latest(decisions.filter(d=>d.status==='complete'&&(typeof d.answers?.next?.choice==='string'||typeof d.answers?.refine_query?.choice==='string')),completed);
 const selectionQuestion=selection?.answers?.refine_query?'refine_query':'next';
 const id=selection?.answers?.[selectionQuestion]?.choice;
 const options=selection?.questions?.[selectionQuestion]?.criteria;
 const chosen=selection&&id&&options&&typeof options==='object'&&!Array.isArray(options)?{
  decision:selection,id,label:String(options[id]??id),
  alternatives:Object.entries(options).filter(([key])=>key!==id).map(([key,label])=>({id:key,label:String(label)})),
 }:undefined;
 const sourceMode=latestSource?(latestSource.cache?'cache':latestSource.source_kind==='video'&&latestSource.video_metadata?.acquisition==='search_provider_metadata'?'metadata':latestSource.artifact_id||latestSource.browser_ms!=null||latestSource.browser_trace?'rendered':'http'):null;
 const result:StageState={phase:'idle',active:false,statusLabel:replay?'Recorded replay':({draft:'Ready to start',complete:'Research complete',partial:'Research stopped',paused:'Research paused',cancelled:'Research cancelled',blocked:'Research blocked',interrupted:'Research interrupted'}[mission.status]||'Saved research'),
  requestLabel:replay?'Saved work at this replay position.':mission.status==='draft'?'Start to discover sources and follow actual decisions.':'Collected sources and decisions remain available below.',
  currentDecision,currentDecisions,collectionSelection,currentAction,currentSearch,currentTextCall,latestTextCall,latestCompletedDecision,latestSource,latestFinding,chosen,latestEventSeq,transport:'none',sourceMode,
  counts:{searches:(records.search||[]).length,pages:new Set(sources.map(s=>s.url)).size,findings:findings.length,
   supportedFindings:findings.filter(f=>!f.stale&&f.review!=='rejected'&&['supported','partly_supported'].includes(f.status)).length,
   decisions:decisions.filter(d=>d.status==='complete'&&!d.cache).length,cachedDecisions:decisions.filter(d=>d.status==='complete'&&d.cache).length}};
 if(!live)return result;
 result.active=true;
 if(currentDecision){
  const questions=currentDecision.questions||{},purpose=String(currentDecision.purpose||'');
  result.phase=/design research approach|approve goal-specific research questions/i.test(purpose)?'planning':/compare observed artifacts/i.test(purpose)?'comparing':questions.priority?'prioritizing':(questions.next||questions.refine_query||/refine discovery for unanswered questions|choose evidence-driven follow-up|select independent records for parallel assessment/i.test(purpose))?'choosing':/verify selected evidence|check (?:research|proposed) answer against cited evidence/i.test(purpose)?'verifying':'assessing';
  result.statusLabel={planning:'Designing your research approach',comparing:'Comparing the collected evidence',choosing:'Choosing the next step',assessing:'Assessing a source',verifying:'Checking the evidence',prioritizing:'Prioritizing suggestions'}[result.phase];
  result.requestLabel=purpose||'A recorded Jev request is awaiting its response.';
  result.transport='jev_api';
 }else if(currentTextCall){
  result.phase=/answer|brief|synthesi|draft/i.test(String(currentTextCall.purpose))?'drafting':'proposing';
  result.statusLabel=result.phase==='drafting'?'Drafting an evidence-linked answer':'Proposing research options';
  result.requestLabel=`${currentTextCall.provider||'Text model'} · ${currentTextCall.purpose||'Waiting for a text model response'}`;
  result.transport='text_api';
 }else if(currentSearch){
  result.phase='searching';result.statusLabel='Searching public sources';result.requestLabel=String(currentSearch.provider)+' · '+String(currentSearch.query||currentAction?.value||'');result.transport='search_api';
 }else if(currentAction?.kind==='reassess'){
  result.phase='assessing';result.statusLabel='Reassessing saved evidence';result.requestLabel=String(currentAction.value);result.transport='none';
 }else if(currentAction?.kind==='video'&&!sources.some(s=>s.action_id===currentAction.id)){
  result.phase='reading_metadata';result.statusLabel='Inspecting video metadata';result.requestLabel=String(currentAction.value);result.transport='metadata';
 }else if(currentAction&&['fetch','render'].includes(currentAction.kind)&&!sources.some(s=>s.action_id===currentAction.id)){
  result.phase=currentAction.kind==='render'?'rendering':'reading';result.statusLabel=result.phase==='rendering'?'Rendering a public page':'Reading a public page';
  result.requestLabel=String(currentAction.value);result.transport=result.phase==='rendering'?'browser_render':'page_fetch';
 }else{
  result.phase='processing';result.statusLabel=mission.status==='pausing'?'Finishing the current step':'Preparing the next step';
  result.requestLabel=currentAction?'Processing the recorded action and its collected results.':'The workflow is preparing bounded research actions.';
 }
 return result;
}
