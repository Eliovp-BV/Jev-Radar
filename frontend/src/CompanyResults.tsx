import {useMemo,useState} from 'react';
import {ArrowUpRight,BookOpen,CheckCircle2,Globe,Lightbulb,Link2,Search} from 'lucide-react';
import {short,type Item} from './api';

const relationships:Record<string,string>={direct:'Potential competitor',alternative:'Alternative',adjacent:'Related supplier',reference:'Reference',unknown:'Not yet classified',unrelated:'Background source'};

export default function CompanyResults({data,active,filter,onClearFilter,onFinding,onSource,onDecision}:{data:Item;active:boolean;filter:string;onClearFilter:()=>void;onFinding:(id:string)=>void;onSource:(id:string)=>void;onDecision:(id:string)=>void}){
 const [sort,setSort]=useState('relevance'),[relationship,setRelationship]=useState('all'),[pricing,setPricing]=useState(false);
 const competitors=data.mode==='competitors';
 const focal=(c:Item)=>['plan_reference','role'].includes(c.reference_basis)&&c.role!=='background'&&!['directory','editorial'].includes(c.entity_type);
 const all=useMemo(()=>competitors?data.candidates||[]:[...(data.candidates||[]),...(data.entities||[])],[data,competitors]);
 const cards=useMemo(()=>all.filter((c:Item)=>(relationship==='all'||c.classification===relationship)&&(!pricing||c.pricing?.values?.length)&&(!filter||JSON.stringify(c).toLowerCase().includes(filter.toLowerCase()))).sort((a:Item,b:Item)=>{
  if(sort==='name')return a.name.localeCompare(b.name);
  if(sort==='search_visibility')return (b.search_visibility?.query_count||0)-(a.search_visibility?.query_count||0)||(a.search_visibility?.best_position??Infinity)-(b.search_visibility?.best_position??Infinity)||a.name.localeCompare(b.name);
  if(sort==='evidence')return b.evidence_count-a.evidence_count||a.name.localeCompare(b.name);
  return (b.relevance?.score??-Infinity)-(a.relevance?.score??-Infinity)||b.evidence_count-a.evidence_count||a.name.localeCompare(b.name);
 }),[all,relationship,pricing,filter,sort]);
 const field=(c:Item,id:string)=>c.fields?.find((f:Item)=>f.criterion_id===id);
 function excerpt(f:Item|undefined,fallback='Not found in inspected pages'){
  const value=f?.values?.[0];
  return value?<><button className="company-excerpt" onClick={()=>onFinding(value.finding_id)}>{short(value.value,210)} <Link2 size={12}/></button>{value.status==='partly_supported'&&<small className="partial-evidence">Partial evidence</small>}</>:<span className="unknown">{fallback}</span>;
 }
 function company(c:Item,reference=false){
  const visibility=c.search_visibility||{};
  return <article className={'company-card '+(reference?'reference-card':'')} key={c.id}>
   <div className="company-top"><div className="company-mark"><Globe size={20}/></div><div><h3>{c.name}</h3><a href={c.url} target="_blank" rel="noreferrer">{c.domains?.[0]||c.url}<ArrowUpRight size={12}/></a></div><span className="badge">{reference?focal(c)?'Your reference':c.role==='background'?'Background source':'Reference source':relationships[c.classification]||c.classification}</span></div>
   <div className="company-offer">{excerpt(field(c,'offering')||field(c,'implementation'), 'The inspected pages do not yet establish the offering.')}</div>
   <div className="company-facts"><div><strong>Capabilities</strong>{excerpt(c.capabilities||field(c,'capabilities'))}</div><div><strong>Pricing evidence</strong>{excerpt(c.pricing)}</div></div>
   <details className="company-more"><summary>More details &amp; sources</summary>
    {(c.fields||[]).filter((f:Item)=>!['offering','implementation','capabilities','pricing'].includes(f.criterion_id)).map((f:Item)=><div className="company-dimension" key={f.criterion_id}><strong>{f.label}</strong>{excerpt(f)}</div>)}
    <div className="visibility-detail"><strong><Search size={13}/> Search visibility</strong><p>{visibility.query_count?`Appeared in ${visibility.query_count} collected ${visibility.query_count===1?'query':'queries'}.`:'Not observed in the collected search results.'} This is not a traffic or market-share measurement.</p>
     {(visibility.observations||[]).slice(0,12).map((o:Item,i:number)=><a key={o.result_id||i} href={o.url} target="_blank" rel="noreferrer">{o.provider} · position {o.position} · “{o.query}”<small>{o.timestamp?new Date(o.timestamp).toLocaleDateString():'Date unknown'}</small></a>)}
    </div>
    {!!c.relevance?.observations?.length&&<button className="text-link" onClick={()=>onDecision([...c.relevance.observations].sort((a:Item,b:Item)=>b.score-a.score)[0].decision_id)}>Inspect Jev relevance assessment</button>}
   </details>
   <div className="company-footer"><span><CheckCircle2 size={13}/>{c.evidence_count} linked findings</span><button className="text-link" onClick={()=>onSource(c.source_ids[0])} disabled={!c.source_ids?.length}><BookOpen size={13}/>{c.source_count} {c.source_count===1?'source':'sources'}</button></div>
  </article>;
 }
 return <section className="company-results" aria-label="Discovered companies">
  <div className="section-heading"><div><h2>{competitors?'Competitors & alternatives':'Research subjects'}</h2><p className="small muted">{all.length} {competitors?'candidates inspected':'subjects inspected'} · Classification is based on the cited pages.</p></div></div>
  {!!all.length&&<div className="company-filters"><label>Sort by<select aria-label="Sort companies" value={sort} onChange={e=>setSort(e.target.value)}><option value="relevance">Relevance</option><option value="search_visibility">Search visibility</option><option value="evidence">Evidence collected</option><option value="name">Name A–Z</option></select></label><label>Relationship<select aria-label="Filter company relationship" value={relationship} onChange={e=>setRelationship(e.target.value)}><option value="all">All relationships</option>{[...new Set(all.map((c:Item)=>c.classification))].map((r:any)=><option key={r} value={r}>{relationships[r]||r}</option>)}</select></label><label className="check"><input type="checkbox" checked={pricing} onChange={e=>setPricing(e.target.checked)}/>Has pricing evidence</label></div>}
  {!!all.length&&<p className="ranking-note">Popularity is not established. Search visibility orders the appearances in this investigation’s searches; relevance comes from Jev’s page assessments.</p>}
  <div className="company-grid">{cards.map((c:Item)=>company(c))}</div>
  {!cards.length&&<div className="company-empty"><Search size={23}/><h3>{all.length?'No matches for these filters':active?'Finding and checking candidates…':competitors?'No competitors inspected yet':'No research subjects inspected yet'}</h3><p>{all.length?'Change the filters to see other collected candidates.':active?'Companies will appear as their websites are reviewed.':'The investigation has not established a comparison. Any reference evidence is shown below.'}</p>{!!all.length&&<button className="text-link" onClick={()=>{setRelationship('all');setPricing(false);onClearFilter()}}>Reset company filters</button>}</div>}
  {!!data.references?.length&&<details className="reference-group" open={!all.length}><summary>{data.references.every(focal)?'Reference products':'Reference & background sources'} · {data.references.length}</summary><div className="company-grid">{data.references.map((c:Item)=>company(c,true))}</div></details>}
  <section className="improvement-results" aria-label="Improvement opportunities"><div className="section-heading"><div><h2><Lightbulb size={20}/> What could you improve?</h2><p className="small muted">Experiments grounded in the comparison. Each links back to the evidence.</p></div></div>
   {data.improvements?.length?<div className="improvement-grid">{data.improvements.slice(0,6).map((o:Item)=><article className="improvement-card" key={o.id}><span className="eyebrow">{o.jev_priority?'JEV PRIORITY · PROPOSED EXPERIMENT':'PROPOSED EXPERIMENT'}</span><h3>{o.title}</h3><p>{o.observation}</p><div className="improvement-comparison">{(o.comparison_evidence||[]).filter((e:Item,i:number,a:Item[])=>i===a.findIndex(x=>x.side===e.side)).map((e:Item)=><div key={e.side+e.finding_id}><strong>{e.side==='reference'?'Your reference':'Candidate'} · {e.name}</strong><button className="company-excerpt" onClick={()=>onFinding(e.finding_id)}>{short(e.value,180)} <Link2 size={12}/></button>{e.status==='partly_supported'&&<small className="partial-evidence">Partial evidence</small>}</div>)}</div><h4>Try this</h4><p>{o.experiment}</p><h4>Measure</h4><p>{o.success_measure}</p>{o.jev_priority&&o.decision_id&&<button className="text-link" onClick={()=>onDecision(o.decision_id)}>Why Jev prioritized this</button>}<div className="improvement-evidence">{(o.finding_ids||[]).slice(0,4).map((id:string,i:number)=><button className="text-link" onClick={()=>onFinding(id)} key={id}><Link2 size={12}/>Evidence {i+1}</button>)}</div><details><summary>Limits of this suggestion</summary><p>{Array.isArray(o.unknowns)?o.unknowns.join(' '):o.unknowns}</p>{(o.source_ids||[]).slice(0,3).map((id:string,i:number)=><button className="text-link" onClick={()=>onSource(id)} key={id}>Source {i+1}</button>)}</details></article>)}</div>:<p className="company-empty-copy">{active?'Comparison-based opportunities will appear as evidence accumulates.':'A useful improvement comparison needs evidence about your reference product and other candidates. No improvement claims have been invented.'}</p>}
  </section>
 </section>;
}
