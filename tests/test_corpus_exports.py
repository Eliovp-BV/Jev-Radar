"""Current-corpus exports preserve provenance, quote bounds and explicit unknowns."""
import csv
import io
import json

import pytest

from radar.reports import report
from radar.schemas import Plan
from radar.storage import Store, dumps, now, uid


def fixture(tmp_path):
    store=Store(tmp_path/'corpus-exports.sqlite');mid=uid()
    criteria=[{'id':'capability','label':'Capability <script> | detail','question':'What actual capability is documented?'},
              {'id':'pricing','label':'Pricing','question':'What public price is documented?'}]
    plan=Plan(goal='Compare an isolated public collection',criteria=criteria,research_mode='fixed').model_dump()
    store.execute('INSERT INTO missions VALUES(?,?,?,?,?,?,?,?,?)',(mid,plan['goal'],'partial',dumps(plan),1,now(),now(),None,'fixture'))
    quote='=HYPERLINK("https://example.org") <script>alert(1)</script> & quoted | value. '+('Q'*1500)
    sources=[];decisions=[]
    for index in range(2):
        sid=f'source{index}';did=f'decision{index}'
        sources.append({'id':sid,'url':f'https://example.org/item{index}?a=1&b=2','title':'=Source <script> | value' if index==0 else 'Item two',
                        'retrieved_at':now(),'source_date':None,'content_hash':sid,'coverage':{},'role':'primary','decision_id':did,
                        'text':quote if index==0 else 'No price evidence was present.','review':'unreviewed'})
        decisions.append({'id':did,'source_id':sid,'status':'complete','created_at':f'2026-09-19T18:00:0{index}+00:00',
                          'latency_ms':25,'estimated_usd':.001,'rubric_version':1,
                          'answers':{'capability':{'confidence':.8},'pricing':{'confidence':.7}},
                          'usage':{'input_tokens':10,'output_tokens':4}})
    span={'id':'span0','source_id':'source0','start':0,'end':len(quote),'text':quote}
    findings=[]
    for criterion,status in [('capability','supported'),('pricing','partly_supported')]:
        findings.append({'id':'finding-'+criterion,'criterion_id':criterion,'decision_id':'decision0','source_ids':['source0'],'span_ids':['span0'],
                         'subject':'Fixture item','question':criterion,'statement':'A bounded fixture observation.','status':status,
                         'evidence_kind':'public statement','retrieved_at':now(),'review':'unreviewed','limitations':[],'scope':'Inspected page text'})
    store.mutate(mid,'fixture.records',{},[('source',source) for source in sources]+[('decision',decision) for decision in decisions]+[('span',span)]+[('finding',finding) for finding in findings],mode='fixture')
    return store,mid,sources,decisions,span,findings


def test_json_pool_deduplicates_exact_bounded_quotes_and_citation_offsets(tmp_path):
    store,mid,sources,_,span,_=fixture(tmp_path)
    body,mime=report(store,mid,'json');data=json.loads(body);corpus=data['corpus']
    assert mime=='application/json' and corpus['metrics']['items']==2
    assert len(corpus['evidence_excerpts'])==1
    excerpt=corpus['evidence_excerpts'][0]
    assert excerpt['quote']==sources[0]['text'][:240] and excerpt['end']==excerpt['start']+240
    assert excerpt['span_id']==span['id'] and excerpt['source_id']=='source0' and excerpt['excerpt_truncated']
    assert excerpt['quote']==sources[0]['text'][excerpt['start']:excerpt['end']]
    row=next(row for row in corpus['rows'] if row['id']=='source0')
    for cell in row['cells']:
        citation=cell['citations'][0]
        assert 'quote' not in citation and citation['excerpt_id']==excerpt['id']
        assert citation['end']==excerpt['end'] and citation['url']==sources[0]['url']
        assert cell['finding_ids'] and cell['decision_ids']==['decision0']
    assert len(json.dumps(corpus))<15000 and 'Q'*241 not in json.dumps(corpus)
    assert 'evidence_excerpts pool' in ' '.join(corpus['export_notes'])
    store.close()


def test_matrix_csv_has_every_item_criterion_and_safe_exact_evidence(tmp_path):
    store,mid,sources,_,_,_=fixture(tmp_path)
    body,mime=report(store,mid,'matrix');rows=list(csv.DictReader(io.StringIO(body)))
    assert mime=='text/csv' and len(rows)==4
    selected=next(row for row in rows if row['source_id']=='source0' and row['criterion_id']=='capability')
    assert selected['title'].startswith("'=Source") and selected['exact_quotes']=="'"+sources[0]['text'][:240]
    assert selected['source_url']==sources[0]['url'] and selected['citation_source_urls']==sources[0]['url']
    assert selected['finding_ids']=='finding-capability' and selected['decision_ids']=='decision0'
    assert selected['source_decision_ids']=='decision0' and selected['span_ids']=='span0'
    assert selected['confidence']=='0.8' and selected['assessment_ms']=='25'
    assert selected['timing_quality']=='measured provider timing' and selected['excerpt_truncated']=='True'
    assert 'repeated across criteria' in selected['timing_scope']
    unknown=next(row for row in rows if row['source_id']=='source1')
    assert unknown['status']=='unknown' and unknown['exact_quotes']==unknown['finding_ids']==''
    assert 'Q'*241 not in body
    store.close()


@pytest.mark.parametrize('flag', [{'private':True},{'excluded':True},{'stale':True},{'review':'rejected'}])
def test_excluded_sources_never_enter_corpus_or_matrix(tmp_path,flag):
    store,mid,sources,_,_,_=fixture(tmp_path)
    store.mutate(mid,'fixture.exclude',{},[('source',{**sources[0],**flag})],mode='fixture')
    body,_=report(store,mid,'json');corpus=json.loads(body)['corpus']
    assert [row['id'] for row in corpus['rows']]==['source1'] and corpus['evidence_excerpts']==[]
    assert corpus['metrics']['items']==1 and all(rollup['denominator']==1 for rollup in corpus['rollups'])
    matrix,_=report(store,mid,'matrix')
    assert 'source0' not in matrix and 'finding-capability' not in matrix and 'span0' not in matrix
    store.close()


@pytest.mark.parametrize('kind,flag', [('finding',{'stale':True}),('finding',{'private':True}),('span',{'private':True}),('decision',{'rubric_version':0})])
def test_stale_or_private_evidence_cannot_populate_matrix_cells(tmp_path,kind,flag):
    store,mid,_,decisions,span,findings=fixture(tmp_path)
    records=findings if kind=='finding' else [span] if kind=='span' else [decisions[0]]
    store.mutate(mid,'fixture.invalidate',{},[(kind,{**record,**flag}) for record in records],mode='fixture')
    body,_=report(store,mid,'matrix');rows=list(csv.DictReader(io.StringIO(body)))
    assert all(row['status']=='unknown' and row['exact_quotes']==row['finding_ids']=='' for row in rows)
    store.close()


def test_pool_budget_is_shared_across_distinct_spans_and_cells(tmp_path):
    store,mid,sources,_,_,findings=fixture(tmp_path)
    text=''.join(chr(65+index)*600 for index in range(6))
    spans=[{'id':f'part{index}','source_id':'source0','start':index*600,'end':(index+1)*600,'text':text[index*600:(index+1)*600]} for index in range(6)]
    store.mutate(mid,'fixture.many_excerpts',{},[('source',{**sources[0],'text':text})]+[('span',span) for span in spans]+
                 [('finding',{**finding,'span_ids':[span['id'] for span in spans]}) for finding in findings],mode='fixture')
    body,_=report(store,mid,'json');corpus=json.loads(body)['corpus']
    assert sum(len(excerpt['quote']) for excerpt in corpus['evidence_excerpts'])==1000
    assert len(corpus['evidence_excerpts'])==5
    assert all(len(excerpt['quote'])<=240 for excerpt in corpus['evidence_excerpts'])
    assert any(citation['excerpt_omitted'] for row in corpus['rows'] for cell in row['cells'] for citation in cell['citations'])
    assert all(excerpt['quote']==text[excerpt['start']:excerpt['end']] for excerpt in corpus['evidence_excerpts'])
    store.close()


def test_readable_matrix_has_sourced_rows_denominators_and_escaped_content(tmp_path):
    store,mid,sources,_,_,_=fixture(tmp_path)
    for fmt in ('md','html'):
        body,_=report(store,mid,fmt)
        assert 'Research collection' in body and 'evidence matrix' in body and '2 inspected items' in body
        assert '1/2 supported' in body and '1 unknown' in body and '0/2 supported' in body
        assert 'Observed assessment window:' in body and 'Active provider time:' in body
        assert 'Neither is a comparative speed benchmark' in body
        assert '<script>' not in body and '&lt;script&gt;' in body
        assert 'Q'*241 not in body and '=HYPERLINK' not in body
        assert ('https://example.org/item0?a=1&amp;b=2' if fmt=='html' else sources[0]['url']) in body
        assert ('<table>' if fmt=='html' else '\\| detail') in body
    store.close()


def test_cached_rows_do_not_export_fabricated_live_timings(tmp_path):
    store,mid,_,decisions,_,_=fixture(tmp_path)
    store.mutate(mid,'fixture.cached',{},[('decision',{**decision,'cache':True}) for decision in decisions],mode='fixture')
    body,_=report(store,mid,'matrix');rows=list(csv.DictReader(io.StringIO(body)))
    assert all(row['assessment_ms']=='' and row['jev_calls']=='0' and row['cached_calls']=='1' for row in rows)
    assert all(row['timing_quality']=='cached only; no fresh provider timing' for row in rows)
    store.close()


def test_missing_timing_is_exported_as_unknown_without_crashing_telemetry(tmp_path):
    store,mid,_,decisions,_,_=fixture(tmp_path)
    missing={key:value for key,value in decisions[0].items() if key!='latency_ms'}
    store.mutate(mid,'fixture.missing_timing',{},[('decision',missing)],mode='fixture')
    body,_=report(store,mid,'matrix');rows=list(csv.DictReader(io.StringIO(body)))
    unknown=next(row for row in rows if row['source_id']=='source0')
    assert unknown['assessment_ms']=='' and unknown['missing_timing_calls']=='1'
    assert unknown['timing_quality']=='missing provider timing'
    body,_=report(store,mid,'json');data=json.loads(body)
    assert data['telemetry']['n']==1 and data['telemetry']['median_ms']==25
    assert data['corpus']['metrics']['analysis_wall_ms'] is None
    store.close()
