import json,csv,io,html,statistics,re,math
from urllib.parse import quote
from .storage import now
from .security import csv_safe
from .imports import cohorts

def _fields(record,keys):
    return {key:record[key] for key in keys if key in record}

def _video_metadata(record):
    keys=('creator','publisher','duration','views','published_at','published_at_basis','transcript_available','frames_available',
          'acquisition','provenance','observed_at','provider','provider_fetched_at')
    result=_fields(record,keys)
    result['field_provenance']=_fields(record.get('field_provenance',{}),('creator','publisher','duration','views','published_at'))
    return result

def _research_records(store,mid):
    """Export selected derived fields, never serialized model states/snapshots."""
    programs=[];artifacts=[];analyses=[]
    for record in store.records(mid,'research_program'):
        if record.get('private'):continue
        safe=_fields(record,('id','status','created_at','program_version','plan_version','decision_id','approval_decision_id','text_call_id','objective','unit','method','selections','search_queries','query_routes','evidence_requirements','stop_conditions','limitations'))
        safe['selections']=_fields(record.get('selections',{}),('research_unit','research_method','primary_dimension','secondary_dimension','discovery_route'))
        safe['criteria']=[_fields(item,('id','label','question','rubric')) for item in record.get('criteria',[])]
        safe['provenance']=_fields(record.get('provenance',{}),('selection','criteria','queries','model','latency_ms','text_model','text_provider','text_call_id'))
        programs.append(safe)
    for record in store.records(mid,'artifact_analysis'):
        if record.get('private'):continue
        safe=_fields(record,('id','source_id','unit_id','program_id','plan_version','decision_id','verification_decision_id','unit','role','relevance','evidence_basis','limitations','stale'))
        safe['features']={key:_fields(item,('choice','label','dimension','span_ids','basis','decision_id','verification_status')) for key,item in record.get('features',{}).items()}
        artifacts.append(safe)
    for record in store.records(mid,'research_analysis'):
        if record.get('private'):continue
        safe=_fields(record,('id','decision_id','program_id','plan_version','unit','artifact_count','total_artifact_count','limitations','stale'))
        if record.get('stale'):
            safe.update(patterns=[],comparisons=[],limitations=['Historical comparison: the evidence or research plan changed. Reassessment is required before its patterns or next test can be presented as current.']+list(record.get('limitations',[])))
            analyses.append(safe)
            continue
        safe['patterns']=[_fields(item,('id','label','source_ids','span_ids','comparison_source_ids','observation','status','model_status','rationale','limitations')) for item in record.get('patterns',[])]
        safe['comparisons']=[_fields(item,('id','source_ids','observation','basis')) for item in record.get('comparisons',[])]
        if record.get('next_test'):safe['next_test']=_fields(record['next_test'],('id','label'))
        analyses.append(safe)
    from .synthesis import current_brief
    brief=current_brief(store,mid)
    answer=None
    if brief:
        answer=_fields(brief,('id','status','created_at','plan_version','program_id','text_call_id','verification_decision_id','unknowns','unsupported_claim_count','limitations','omitted'))
        answer['provenance']=_fields(brief.get('provenance',{}),('provider','model','latency_ms'))
        answer['claims']=[]
        quote_budget={}
        for claim in brief.get('claims',[]):
            safe=_fields(claim,('id','text','kind','status','decision_id'))
            safe['citations']=[]
            for citation in claim.get('citations',[]):
                cited=_fields(citation,('finding_id','span_id','source_id','url','start','end','excerpt_truncated','field','provenance'))
                sid=citation['source_id']; remaining=max(0,1000-quote_budget.get(sid,0))
                excerpt=str(citation.get('quote',''))[:min(240,remaining)]
                quote_budget[sid]=quote_budget.get(sid,0)+len(excerpt)
                cited.update(quote=excerpt,end=citation['start']+len(excerpt),excerpt_truncated=len(excerpt)!=len(citation.get('quote','')) or bool(citation.get('excerpt_truncated')))
                safe['citations'].append(cited)
            answer['claims'].append(safe)
        answer['recommendations']=[_fields(item,('id','text','claim_ids','status','performed')) for item in brief.get('recommendations',[])]
    followups=[_fields(item,('id','program_id','plan_version','checkpoint','status','gap','selected','decision_id','text_call_id')) for item in store.records(mid,'research_followup') if not item.get('private')]
    return {'research_program':programs,'artifact_analysis':artifacts,'research_analysis':analyses,'research_answer':answer,'research_followups':followups}

def _search_observation(record):
    if record.get('search_kind')!='video':return record
    safe=_fields(record,('id','query','provider','search_kind','region_requested','language','timestamp','latency_ms','endpoint','scope','skipped_results','skipped_reason','estimated_usd','pricing_provenance'))
    safe['results']=[]
    for item in record.get('results',[]):
        result=_fields(item,('id','position','url','title','source_kind','page_age','age','page_fetched','fetched_content_timestamp'))
        result['snippet']=str(item.get('snippet') or '')[:240]
        result['video']=_fields(item.get('video',{}),('duration','views','creator','publisher','requires_subscription'))
        safe['results'].append(result)
    return safe

def telemetry(store,mid):
    decisions=store.records(mid,'decision'); live=[d for d in decisions if not d.get('cache')]; complete=[d for d in live if d.get('status')=='complete']
    lat=[d['latency_ms'] for d in complete if type(d.get('latency_ms')) in (int,float) and math.isfinite(d['latency_ms']) and d['latency_ms']>=0]
    reservations=store.rows('SELECT * FROM reservations WHERE mission_id=?',(mid,))
    sources=store.records(mid,'source'); searches=store.records(mid,'search')
    search_attempts=store.records(mid,'search_attempt'); linked_searches={attempt.get('search_id') for attempt in search_attempts}
    text_calls=store.records(mid,'text_call'); text_complete=[call for call in text_calls if call.get('status')=='complete']
    text_priced=[call for call in text_calls if call.get('actual_usd') is not None]
    text_unknown=[call for call in text_calls if call.get('actual_usd') is None and call.get('reserved_usd') is None]
    return {'attempts':len(reservations),'completions':len(complete),'errors':sum(d.get('status')=='error' for d in live),
            'questions':sum(len(d.get('answers',{})) for d in complete),'cache_hits':sum(bool(d.get('cache')) for d in decisions)+sum(bool(s.get('cache')) for s in sources),
            'current_ms':lat[-1] if lat else None,'median_ms':statistics.median(lat) if lat else None,'n':len(lat),
            'p95_ms':sorted(lat)[int((len(lat)-1)*.95)] if len(lat)>=20 else None,
            'input_tokens':sum(d['usage']['input_tokens'] for d in complete) if complete else None,
            'output_tokens':sum(d['usage']['output_tokens'] for d in complete) if complete else None,
            'estimated_usd':sum(d.get('estimated_usd') or 0 for d in complete) if complete else None,
            'reserved_usd':sum(r['reserved_usd'] for r in reservations if r['status'] in ('inflight','uncertain')),
            'pages':len({s['url'] for s in sources}),'independent_documents':len({s['content_hash'] for s in sources}),'analyzed':len({s['url'] for s in sources if s.get('decision_id')}),'searches':len(searches),
            'search_attempts':len(search_attempts)+sum(search['id'] not in linked_searches for search in searches),'search_errors':sum(attempt.get('status')=='failed' for attempt in search_attempts),
            'findings':len(store.records(mid,'finding')),'wall_ms':sum(e['payload'].get('wall_ms',0) for e in store.events(mid) if e['type']=='run.segment'),
            'fetch_ms':sum(s.get('fetch_ms',0) for s in sources if not s.get('cache')),'extraction_ms':sum(s.get('extraction_ms',0) for s in sources if not s.get('cache')),
            'browser_ms':sum(s.get('browser_ms',0) for s in sources),'search_ms':sum(s.get('latency_ms',0) for s in searches),
            'search_cost':'Unknown account pricing and request billing' if any(s['provider']=='brave' for s in searches+search_attempts) else 'No paid search requests',
            'text_attempts':len(text_calls),'text_completions':len(text_complete),'text_errors':sum(call.get('status')=='error' for call in text_calls),
            'text_ms':sum(call.get('latency_ms') or 0 for call in text_calls),
            'text_input_tokens':sum(call['usage']['input_tokens'] for call in text_complete) if text_complete and all('input_tokens' in call.get('usage',{}) for call in text_complete) else None,
            'text_output_tokens':sum(call['usage']['output_tokens'] for call in text_complete) if text_complete and all('output_tokens' in call.get('usage',{}) for call in text_complete) else None,
            'text_estimated_usd':sum(call['actual_usd'] for call in text_priced) if text_priced else None,
            'text_reserved_usd':sum(call.get('reserved_usd') or 0 for call in text_calls if call.get('actual_usd') is None),
            'text_unpriced_attempts':len(text_unknown),
            'text_cost':('Some historical text calls have unknown cost' if text_unknown else 'Estimated separately using each request’s saved model rates; provider charges can differ') if text_calls else 'No text model requests',
            'pricing_provenance':'Public Jev list estimate; not a provider billing cap'}

def opportunities(store,mid):
    from .actions import construct
    return construct(store,mid)

def _corpus_export(store,mid):
    """Use the current public projection and quote each corpus span only once.

    Matrix citations retain provenance and reference evidence_excerpts by
    excerpt_id. This bounded pool is independent of historical report excerpts.
    """
    from .corpus import corpus_summary
    corpus=corpus_summary(store,mid)
    excerpts={};used={}
    for row in corpus['rows']:
        for cell in row['cells']:
            citations=[]
            for citation in cell.get('citations',[]):
                safe=_fields(citation,('span_id','source_id','url','start','end'))
                key=(citation['source_id'],citation['span_id'],citation['start'])
                if key not in excerpts:
                    remaining=max(0,1000-used.get(citation['source_id'],0))
                    text=citation.get('quote','')[:min(240,remaining)]
                    if text:
                        excerpts[key]={'id':citation['span_id'],**safe,'quote':text,
                                       'end':citation['start']+len(text),
                                       'excerpt_truncated':len(text)<len(citation.get('quote',''))}
                        used[citation['source_id']]=used.get(citation['source_id'],0)+len(text)
                    else:excerpts[key]=None
                excerpt=excerpts[key]
                safe.update(excerpt_id=excerpt['id'] if excerpt else None,
                            excerpt_truncated=excerpt['excerpt_truncated'] if excerpt else True,
                            excerpt_omitted=excerpt is None)
                if excerpt:safe['end']=excerpt['end']
                citations.append(safe)
            cell['citations']=citations
    corpus['evidence_excerpts']=[excerpt for excerpt in excerpts.values() if excerpt]
    corpus['export_notes']=['Cell citations reference this corpus evidence_excerpts pool by excerpt_id. Repeated spans are stored once.',
                            'Quotes retain exact source offsets and are limited to 240 characters per excerpt and 1000 characters per source. Omitted quotes retain their span and source identifiers.']
    return corpus

def _corpus_timing_quality(row):
    if row.get('missing_timing_calls'):return 'missing provider timing'
    if row.get('jev_calls') and row.get('assessment_ms') is not None:return 'measured provider timing'
    if row.get('cached_calls'):return 'cached only; no fresh provider timing'
    return 'no linked provider timing'

def _matrix_csv(corpus):
    out=io.StringIO();writer=csv.writer(out)
    columns=['source_id','title','source_url','role','criterion_id','criterion','status','exact_quotes',
             'citation_source_urls','excerpt_ids','span_ids','finding_ids','decision_ids','source_decision_ids',
             'confidence','assessment_ms','jev_calls','cached_calls','missing_timing_calls','timing_quality','timing_scope','excerpt_truncated']
    writer.writerow(columns)
    criteria={item['id']:item for item in corpus['columns']}
    excerpts={item['id']:item for item in corpus['evidence_excerpts']}
    for row in corpus['rows']:
        for cell in row['cells']:
            citations=cell.get('citations',[])
            ids=list(dict.fromkeys(citation.get('excerpt_id') for citation in citations if citation.get('excerpt_id') in excerpts))
            values={'source_id':row['source_id'],'title':row['title'],'source_url':row['url'],'role':row['role'],
                    'criterion_id':cell['criterion_id'],'criterion':criteria.get(cell['criterion_id'],{}).get('label',''),
                    'status':cell['status'],'exact_quotes':'\n\n'.join(excerpts[key]['quote'] for key in ids),
                    'citation_source_urls':' | '.join(dict.fromkeys(citation['url'] for citation in citations)),
                    'excerpt_ids':' | '.join(ids),'span_ids':' | '.join(dict.fromkeys(citation['span_id'] for citation in citations)),
                    'finding_ids':' | '.join(cell.get('finding_ids',[])),
                    'decision_ids':' | '.join(cell.get('decision_ids',[])),
                    'source_decision_ids':' | '.join(row.get('decision_ids',[])),
                    'confidence':cell.get('confidence'),'assessment_ms':row.get('assessment_ms'),
                    'jev_calls':row.get('jev_calls'),'cached_calls':row.get('cached_calls'),
                    'missing_timing_calls':row.get('missing_timing_calls'),
                    'timing_quality':_corpus_timing_quality(row),
                    'timing_scope':'Per source item; repeated across criteria. Deduplicate source_decision_ids before summing.',
                    'excerpt_truncated':any(citation.get('excerpt_truncated') for citation in citations)}
            writer.writerow([csv_safe(values.get(key)) for key in columns])
    return out.getvalue(),'text/csv'

def _corpus_summary_text(corpus):
    metrics=corpus['metrics']
    def measured(key):
        value=metrics.get(key)
        return f'{value:g} ms' if value is not None else 'unknown'
    return [f"{metrics['items']} inspected items; {metrics['typed_judgments']} typed judgments; {metrics['jev_calls']} live Jev assessment calls; {metrics['cached_calls']} cached calls.",
            f"Observed assessment window: {measured('analysis_wall_ms')}. Active provider time: {measured('active_inference_ms')}. Median linked provider time per item: {measured('median_item_ms')}.",
            corpus['scope']]

def _corpus_rollup_text(rollup):
    return f"{rollup['label']}: {rollup['supported']}/{rollup['denominator']} supported; {rollup['partly_supported']} partly supported; {rollup['contradicted']} contradicted; {rollup['not_applicable']} not applicable; {rollup['unknown']} unknown."

def export_data(store,mid):
    m=store.mission(mid)
    finished=next((event for event in reversed(store.events(mid)) if event['type']=='mission.finished'),None)
    run_outcome={}
    if finished:
        payload=finished.get('payload',{})
        run_outcome=_fields(payload,('gaps','failed_actions','coverage'))
        if payload.get('stop_reason'):run_outcome['stop_reason']=_fields(payload['stop_reason'],('code','message','decision_id'))
    sources=[]
    for source in store.records(mid,'source'):
        safe={key:source.get(key) for key in ('id','url','title','retrieved_at','source_date','source_date_provenance','content_hash','coverage','duplicate_of','canonical_claim','indexability_declaration','source_kind','unit_id','evidence_basis','review','excluded','stale')}
        if source.get('video_metadata'):safe['video_metadata']=_video_metadata(source['video_metadata'])
        if source.get('provider_observation'):safe['provider_observation']=_fields(source['provider_observation'],('search_id','result_id','position','query','endpoint','latency_ms'))
        sources.append(safe)
    spans=[]; chars={}
    for span in store.records(mid,'span'):
        remaining=1000-chars.get(span['source_id'],0)
        if remaining<=0: continue
        quote=span['text'][:min(240,remaining)]; chars[span['source_id']]=chars.get(span['source_id'],0)+len(quote)
        spans.append({**span,'text':quote,'export_excerpt_truncated':len(quote)<len(span['text'])})
    metrics=store.records(mid,'metric')
    public_metrics=[m for m in metrics if not m.get('private')]
    safe_metrics=[m if not m.get('private') else {'id':m['id'],'private':True,'kind':'user-supplied','metric':m['metric'],'value':None,'unit':m['unit'],'provenance':'Private import fields omitted from default export'} for m in metrics]
    search_imports=[m if not m.get('private') else {'id':m['id'],'private':True,'kind':'user-supplied','provenance':'Private search observation omitted from default export'} for m in store.records(mid,'search_import')]
    return {'schema_version':1,'generated_at':now(),'mission':m,'findings':store.records(mid,'finding'),'sources':sources,'evidence_excerpts':spans,'run_outcome':run_outcome,
            'entities':store.records(mid,'entity'),'search_observations':[_search_observation(record) for record in store.records(mid,'search')]+search_imports,
            **_research_records(store,mid),'corpus':_corpus_export(store,mid),
            'metrics':safe_metrics,'cohorts':cohorts(public_metrics),'opportunities':opportunities(store,mid),'telemetry':telemetry(store,mid),
            'methodology':['Jev selects the research protocol, actions and supporting passages. When configured, a text model proposes questions, follow-up queries and answer wording; Jev evaluates their relevance or passage support. Templates remain available without a text provider.',
              'Extracted claims are scoped to inspected sources. Company assertions are not independently established facts.',
              'Seed crawl is not exhaustive discovery. Provider result positions are not Google rankings.',
              'Video index metadata is not watched footage. Missing transcripts, frames, counters and time windows remain unknown. Cross-item patterns are observations or hypotheses, not causal proof.',
              'Snapshots, full decision inputs and private import fields are omitted from default exports. Imported observations are user-supplied, not authenticated API observations.']}

def report(store,mid,fmt):
    data=export_data(store,mid); m=data['mission']; sources={s['id']:s for s in data['sources']}
    program=next((record for record in reversed(data['research_program']) if record.get('plan_version')==m['plan_version'] and record.get('status')=='complete'),None)
    analysis=next((record for record in reversed(data['research_analysis']) if program and record.get('program_id')==program['id'] and record.get('plan_version')==m['plan_version']),None)
    if fmt=='json': return json.dumps(data,indent=2,ensure_ascii=False),'application/json'
    if fmt=='matrix':return _matrix_csv(data['corpus'])
    if fmt=='metrics':
        out=io.StringIO();writer=csv.writer(out)
        columns=['id','metric','value','unit','provider','kind','url','measured_at','window_start','window_end','country','device','query','provenance','private']
        writer.writerow(columns)
        for m in data['metrics']:writer.writerow([csv_safe(m.get(k)) for k in columns])
        return out.getvalue(),'text/csv'
    if fmt=='csv':
        out=io.StringIO(); writer=csv.writer(out); writer.writerow(['claim_id','subject','question','statement','status','evidence_kind','source_urls','retrieved_at','review','limitations'])
        for f in data['findings']:
            writer.writerow([csv_safe(v) for v in [f['id'],f['subject'],f['question'],f['statement'],f['status'],f['evidence_kind'],' | '.join(sources[s]['url'] for s in f['source_ids'] if s in sources),f['retrieved_at'],f['review'],'; '.join(f['limitations'])]])
        return out.getvalue(),'text/csv'
    def md(value): return re.sub(r'([\\`*_{}\[\]!])',r'\\\1',html.escape(str(value)))
    lines=[f"# {md(m['goal'])}",'',f"Structured brief · {m['status']} · {data['generated_at']}",'',
           f"{len(data['sources'])} source snapshots; {len(data['findings'])} evidence-linked assessments. Interpretations require review.",'']
    corpus=data['corpus'];preview=corpus['rows'][:40]
    lines+=['## Research collection & evidence matrix','']+[md(text) for text in _corpus_summary_text(corpus)]+['']
    lines+=['- '+md(_corpus_rollup_text(rollup)) for rollup in corpus['rollups']]+['']
    if preview:
        def table_cell(value):return md(str(value)).replace('|','\\|').replace('\n',' ').replace('\r',' ')
        lines+=['| Source | '+' | '.join(table_cell(column['label']) for column in corpus['columns'])+' | Linked Jev time |',
                '| --- | '+' | '.join('---' for _ in corpus['columns'])+' | --- |']
        for row in preview:
            statuses={cell['criterion_id']:cell['status'] for cell in row['cells']}
            timing=(f"{row['assessment_ms']:g} ms" if row.get('assessment_ms') is not None else 'unknown')+'; '+_corpus_timing_quality(row)
            lines+=['| ['+table_cell(row['title'][:240])+']('+quote(row['url'],safe=':/?&=%#')+') | '+
                    ' | '.join(table_cell(statuses.get(column['id'],'unknown')) for column in corpus['columns'])+' | '+table_cell(timing)+' |']
    if len(corpus['rows'])>len(preview):lines+=['',f"Showing {len(preview)} of {len(corpus['rows'])} items. JSON and matrix CSV contain the complete current collection."]
    lines+=['']+['- '+md(item) for item in corpus['limitations']]+['']
    answer=data.get('research_answer')
    if answer:
        lines+=['## Evidence-linked answer','']
        for claim in answer['claims']:
            lines += ['- '+md(claim['text'])+' ('+md(claim['kind']+'; '+claim['status'])+')']
            for citation in claim['citations']:
                lines += ['  Evidence ['+md(citation['finding_id'][:8])+']('+quote(citation['url'],safe=':/?&=%#')+')']
        lines += ['','Proposed actions (not performed):']+['- '+md(item['text']) for item in answer['recommendations']]
        lines += ['','Remaining questions:']+['- '+md(item) for item in answer['unknowns']]+['']
    if program:
        lines+=['## Jev research approach',md(f"Subject: {program.get('unit')} · Method: {program.get('method')} · Recorded decision: {program.get('decision_id')}"),'']
        lines+=['- '+md(item.get('label','')+': '+item.get('question','')) for item in program.get('criteria',[])]
        lines+=['','Evidence requirements:']+['- '+md(item) for item in program.get('evidence_requirements',[])]+['']
    if analysis:
        lines+=['## Comparison needs reassessment' if analysis.get('stale') else '## Cross-item assessment',md(f"{analysis.get('artifact_count',0)} inspected artifacts were available to this {'historical ' if analysis.get('stale') else ''}comparison."),'']
        for pattern in analysis.get('patterns',[]):
            lines += [f"### {md(pattern.get('label','Comparison'))} · {md(pattern.get('status','unknown'))}",md(pattern.get('rationale') or pattern.get('observation',''))]
            for sid in dict.fromkeys(pattern.get('source_ids',[])+pattern.get('comparison_source_ids',[])):
                if sid in sources:lines.append(f"Evidence [{md(sources[sid]['title'])}]({quote(sources[sid]['url'],safe=':/?&=%#')})")
            lines+=['- '+md(item) for item in pattern.get('limitations',[])]+['']
        lines+=['- '+md(item) for item in analysis.get('limitations',[])]+['']
        if analysis.get('next_test'):lines += ['**Next test — not performed:** '+md(analysis['next_test'].get('label','')),'']
    for f in data['findings']:
        lines.extend([f"## {md(f['subject'])} · {md(f['question'])}",f"{f['status']} · {f['evidence_kind']} · review: {f['review']}",'',md(f['statement']),f"Scope: {md(f['scope'])}",''])
        for sid in f['source_ids']:
            if sid in sources: lines.append(f"Source [{sid[:8]}]({quote(sources[sid]['url'],safe=':/?&=%#')}) · retrieved {sources[sid]['retrieved_at']}")
    lines+=['','## Observed metrics']
    for metric in data['metrics'][:200]:
        if metric.get('private'):lines.append('- Private import fields omitted.');continue
        lines.append('- '+md(f"{metric['metric']}: {metric['value']} {metric['unit']} · {metric['kind']} · {metric['provider']} · {metric['provenance']} · period {metric.get('window_start') or 'unknown'} to {metric.get('window_end') or 'unknown'} · {metric['url']}"))
    lines+=['','## Coverage & limitations']+['- '+x for x in data['methodology']]
    lines+=['- Configured run limits: '+md('; '.join(f'{key}={value}' for key,value in m['plan'].get('limits',{}).items()))]
    if data['run_outcome'].get('stop_reason'):lines+=['- Recorded stop reason: '+md(data['run_outcome']['stop_reason'].get('message',''))]
    lines+=['- Unresolved: '+md(gap) for gap in data['run_outcome'].get('gaps',[])]
    if program:lines+=['- '+md(item) for item in program.get('limitations',[])]+['- Stop condition: '+md(item) for item in program.get('stop_conditions',[])]
    lines+=['','## Source appendix']+[f"- [{md(s['title'])}]({quote(s['url'],safe=':/?&=%#')}) · retrieved {s['retrieved_at']} · source date {s['source_date'] or 'unknown'}" for s in data['sources']]
    for source in data['sources']:
        if source.get('video_metadata'):
            video=source['video_metadata']
            lines+=['- '+md(f"Video {source['id'][:8]}: {video.get('provenance','metadata')} · views {video.get('views') if video.get('views') is not None else 'unknown'} · observed {video.get('observed_at') or 'unknown'} · date basis: {video.get('published_at_basis') or 'unknown'} · transcript {'available' if video.get('transcript_available') else 'not acquired'} · frames {'available' if video.get('frames_available') else 'not inspected'}")]
    lines+=['','## Next steps']+['- '+x['experiment'] for x in data['opportunities']]
    if fmt=='html':
        esc=html.escape
        cards=[]
        cards.append('<section><h2>Research collection &amp; evidence matrix</h2>'+''.join('<p>'+esc(text)+'</p>' for text in _corpus_summary_text(corpus))+
                     '<ul>'+''.join('<li>'+esc(_corpus_rollup_text(rollup))+'</li>' for rollup in corpus['rollups'])+'</ul>')
        if preview:
            cards.append('<div style="overflow-x:auto"><table><thead><tr><th>Source</th>'+''.join('<th>'+esc(column['label'])+'</th>' for column in corpus['columns'])+'<th>Linked Jev time</th></tr></thead><tbody>')
            for row in preview:
                statuses={cell['criterion_id']:cell['status'] for cell in row['cells']}
                timing=(f"{row['assessment_ms']:g} ms" if row.get('assessment_ms') is not None else 'unknown')+'; '+_corpus_timing_quality(row)
                cards.append('<tr><td><a href="'+esc(row['url'],quote=True)+'">'+esc(row['title'][:240])+'</a></td>'+''.join('<td>'+esc(statuses.get(column['id'],'unknown'))+'</td>' for column in corpus['columns'])+'<td>'+esc(timing)+'</td></tr>')
            cards.append('</tbody></table></div>')
        if len(corpus['rows'])>len(preview):cards.append(f"<p>Showing {len(preview)} of {len(corpus['rows'])} items. JSON and matrix CSV contain the complete current collection.</p>")
        cards.append('<ul>'+''.join('<li>'+esc(item)+'</li>' for item in corpus['limitations'])+'</ul></section>')
        if answer:
            cards.append('<section><h2>Evidence-linked answer</h2>')
            for claim in answer['claims']:
                links=' · '.join('<a href="'+esc(citation['url'],quote=True)+'">Evidence '+esc(citation['finding_id'][:8])+'</a>' for citation in claim['citations'])
                cards.append('<article><p>'+esc(claim['text'])+'</p><p>'+esc(claim['kind']+' · '+claim['status'])+'</p><p>'+links+'</p></article>')
            cards.append('<h3>Proposed actions (not performed)</h3><ul>'+''.join('<li>'+esc(item['text'])+'</li>' for item in answer['recommendations'])+'</ul><h3>Remaining questions</h3><ul>'+''.join('<li>'+esc(item)+'</li>' for item in answer['unknowns'])+'</ul></section>')
        if program:
            cards.append('<section><h2>Jev research approach</h2><p>'+esc(f"Subject: {program.get('unit')} · Method: {program.get('method')} · Recorded decision: {program.get('decision_id')}")+'</p><ul>'+''.join('<li>'+esc(item.get('label','')+': '+item.get('question',''))+'</li>' for item in program.get('criteria',[]))+'</ul><h3>Evidence requirements</h3><ul>'+''.join('<li>'+esc(item)+'</li>' for item in program.get('evidence_requirements',[]))+'</ul></section>')
        if analysis:
            cards.append('<section><h2>'+('Comparison needs reassessment' if analysis.get('stale') else 'Cross-item assessment')+'</h2><p>'+esc(f"{analysis.get('artifact_count',0)} inspected artifacts were available to this {'historical ' if analysis.get('stale') else ''}comparison.")+'</p>')
            for pattern in analysis.get('patterns',[]):
                links=' · '.join('<a href="'+esc(sources[sid]['url'],quote=True)+'">'+esc(sources[sid]['title'] or sid)+'</a>' for sid in dict.fromkeys(pattern.get('source_ids',[])+pattern.get('comparison_source_ids',[])) if sid in sources)
                cards.append('<article><h3>'+esc(pattern.get('label','Comparison')+' · '+pattern.get('status','unknown'))+'</h3><p>'+esc(pattern.get('rationale') or pattern.get('observation',''))+'</p><p>'+links+'</p><ul>'+''.join('<li>'+esc(item)+'</li>' for item in pattern.get('limitations',[]))+'</ul></article>')
            cards.append('<ul>'+''.join('<li>'+esc(item)+'</li>' for item in analysis.get('limitations',[]))+'</ul>')
            if analysis.get('next_test'):cards.append('<p><strong>Next test — not performed:</strong> '+esc(analysis['next_test'].get('label',''))+'</p>')
            cards.append('</section>')
        for f in data['findings']:
            links=' · '.join('<a href="'+esc(sources[s]['url'],quote=True)+'">Original source '+s[:8]+'</a>' for s in f['source_ids'] if s in sources)
            cards.append('<article><h2>'+esc(f['subject']+' · '+f['question'])+'</h2><p class="meta">'+esc(f['status']+' · '+f['evidence_kind']+' · '+f['review'])+'</p><blockquote>'+esc(f['statement'])+'</blockquote><p>'+links+'</p><p>'+esc(f['scope'])+'</p></article>')
        metric_rows=[]
        for metric in data['metrics'][:200]:
            if metric.get('private'):metric_rows.append('<li>Private import fields omitted.</li>');continue
            metric_rows.append('<li>'+esc(f"{metric['metric']}: {metric['value']} {metric['unit']} · {metric['kind']} · {metric['provider']} · {metric['provenance']} · measured {metric.get('measured_at') or 'unknown'} · period {metric.get('window_start') or 'unknown'} to {metric.get('window_end') or 'unknown'}")+' · <a href="'+esc(metric['url'],quote=True)+'">Original page</a></li>')
        cards.append('<h2>Observed metrics</h2><ul>'+''.join(metric_rows)+'</ul>')
        cards.append('<h2>Source appendix</h2><ul>'+''.join('<li><a href="'+esc(s['url'],quote=True)+'">'+esc(s['title'] or s['url'])+'</a> · retrieved '+esc(s['retrieved_at'])+' · source date '+esc(s['source_date'] or 'unknown')+'</li>' for s in data['sources'])+'</ul>')
        for source in data['sources']:
            if source.get('video_metadata'):
                video=source['video_metadata']
                cards.append('<p>'+esc(f"Video {source['id'][:8]}: {video.get('provenance','metadata')} · views {video.get('views') if video.get('views') is not None else 'unknown'} · observed {video.get('observed_at') or 'unknown'} · date basis: {video.get('published_at_basis') or 'unknown'} · transcript {'available' if video.get('transcript_available') else 'not acquired'} · frames {'available' if video.get('frames_available') else 'not inspected'}")+'</p>')
        cards.append('<h2>Proposed experiments</h2><ul>'+''.join('<li>'+esc(o['experiment'])+' <strong>Success measure:</strong> '+esc(o['success_measure'])+'</li>' for o in data['opportunities'])+'</ul>')
        limits=''.join('<li>'+esc(x)+'</li>' for x in data['methodology'])
        limits+='<li>Configured run limits: '+esc('; '.join(f'{key}={value}' for key,value in m['plan'].get('limits',{}).items()))+'</li>'
        if data['run_outcome'].get('stop_reason'):limits+='<li>Recorded stop reason: '+esc(data['run_outcome']['stop_reason'].get('message',''))+'</li>'
        limits+=''.join('<li>Unresolved: '+esc(gap)+'</li>' for gap in data['run_outcome'].get('gaps',[]))
        if program:limits+=''.join('<li>'+esc(item)+'</li>' for item in program.get('limitations',[])+program.get('stop_conditions',[]))
        body='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Structured brief</title><style>body{font:16px/1.7 system-ui;max-width:900px;margin:40px auto;padding:20px;color:#222}article{border-top:1px solid #bbb;padding:24px 0;break-inside:avoid}h1{line-height:1.3}h2{font-size:20px}blockquote{border-left:3px solid #aa8d00;padding-left:20px;margin:20px 0}.meta{color:#555;font-size:14px}a{color:#275874}a:after{content:" (" attr(href) ")";font-size:12px;overflow-wrap:anywhere}@media print{body{margin:0}}</style><h1>'+esc(m['goal'])+'</h1><p>Jev Radar by Eliovp · Structured brief · '+esc(m['status'])+'</p><p>'+str(len(data['findings']))+' evidence-linked assessments across '+str(len(data['sources']))+' source snapshots. Coverage is limited to collected sources.</p>'+''.join(cards)+'<h2>Methodology and limitations</h2><ul>'+limits+'</ul></html>'
        return body,'text/html'
    return '\n'.join(lines),'text/markdown'
