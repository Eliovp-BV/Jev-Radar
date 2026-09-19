"""Collection statistics must remain tied to exact current public evidence."""
from copy import deepcopy
import pytest

from radar.corpus import project_corpus


def fixture_records():
    criteria=[{'id':'identity','label':'Original record','question':'Which original record was inspected?'},
              {'id':'result','label':'Measured result','question':'Which measured result is documented?'}]
    mission={'plan_version':1,'plan':{'criteria':criteria,'excluded_domains':[],'excluded_entities':[]}}
    program={'id':'program','unit':'articles','criteria':criteria}
    records={kind:[] for kind in ('source','entity','span','finding','decision','artifact_analysis')}
    for index in range(2):
        sid=f's{index}';did=f'd{index}';fid=f'f{index}';spid=f'p{index}'
        text=f'An original observed record {index}.'
        records['source'].append({'id':sid,'url':f'https://publisher{index}.example/original','title':f'Record {index}',
                                  'text':text,'program_id':'program','decision_id':did,'retrieved_at':'2026-09-19T12:00:00+00:00'})
        records['span'].append({'id':spid,'source_id':sid,'text':text,'start':0,'end':len(text)})
        records['finding'].append({'id':fid,'source_ids':[sid],'span_ids':[spid],'criterion_id':'identity',
                                   'status':'supported','decision_id':did,'program_id':'program'})
        records['decision'].append({'id':did,'source_id':sid,'status':'complete','rubric_version':1,
                                    'answers':{'identity':{'choice':'supported','confidence':.8}},
                                    'created_at':f'2026-09-19T12:00:0{index}+00:00','latency_ms':2000,
                                    'queue_ms':100,'estimated_usd':.001})
        records['artifact_analysis'].append({'id':f'a{index}','source_id':sid,'program_id':'program',
                                            'plan_version':1,'role':'primary_artifact','relevance':2,
                                            'decision_id':did,'features':{}})
    return mission,records,program


def test_collection_evidence_denominators_and_real_overlapping_timing():
    mission,records,program=fixture_records()
    result=project_corpus(mission,records,program)
    assert result['metrics']['items']==2
    assert result['metrics']['typed_judgments']==2
    assert result['metrics']['analysis_wall_ms']==3000
    assert result['metrics']['active_inference_ms']==3000
    assert result['metrics']['median_item_ms']==2000
    assert result['metrics']['items_per_second']==.67
    assert result['metrics']['estimated_usd']==.002
    assert result['rollups'][0]['supported']==2
    assert result['rollups'][1]['unknown']==2
    assert result['rollups'][1]['denominator']==2
    assert result['rows'][0]['cells'][0]['citations'][0]['quote']==records['source'][0]['text']


@pytest.mark.parametrize('kind',['source','artifact_analysis','decision'])
@pytest.mark.parametrize('change',[{'private':True},{'stale':True},{'excluded':True},{'review':'rejected'}])
def test_unavailable_rows_are_not_counted(kind,change):
    mission,records,program=fixture_records()
    records[kind][0].update(change)
    result=project_corpus(mission,records,program)
    assert result['metrics']['items']==1
    assert result['rows'][0]['source_id']=='s1'
    assert result['rollups'][0]['denominator']==1


@pytest.mark.parametrize('kind',['finding','span'])
@pytest.mark.parametrize('change',[{'private':True},{'stale':True},{'excluded':True},{'review':'rejected'}])
def test_removed_evidence_becomes_unknown_without_disclosing_excerpt(kind,change):
    mission,records,program=fixture_records()
    records[kind][0].update(change)
    result=project_corpus(mission,records,program)
    assert result['metrics']['items']==2
    cell=result['rows'][0]['cells'][0]
    assert cell['status']=='unknown' and cell['citations']==[] and cell['finding_ids']==[]
    assert result['rollups'][0]['unknown']==1


def test_exact_offsets_all_sources_and_current_program_are_required():
    mission,records,program=fixture_records()
    records['span'][0]['text']='fabricated excerpt'
    records['finding'][1]['source_ids'].append('private-missing-source')
    result=project_corpus(mission,records,program)
    assert result['rollups'][0]['unknown']==2
    records['source'][0]['program_id']='old-program'
    assert project_corpus(mission,records,program)['metrics']['items']==1


def test_excluded_entities_domains_and_background_are_not_population_members():
    mission,records,program=fixture_records()
    records['entity']=[{'id':'entity','name':'Excluded subject','role':'candidate'}]
    records['source'][0]['entity_id']='entity'
    mission['plan']['excluded_entities']=['Excluded subject']
    mission['plan']['excluded_domains']=['publisher1.example']
    assert project_corpus(mission,records,program)['rows']==[]
    mission,records,program=fixture_records()
    program['unit']='companies'
    records['entity']=[{'id':'background','role':'background'}]
    records['source'][0]['entity_id']='background'
    assert len(project_corpus(mission,records,program)['rows'])==1


def test_unknown_timing_cost_and_cache_are_not_zero_latency_or_free_provider_calls():
    mission,records,program=fixture_records()
    records['decision'][0].pop('latency_ms')
    records['decision'][0].pop('estimated_usd')
    records['decision'][1]['cache']=True
    result=project_corpus(mission,records,program)
    assert result['metrics']['jev_calls']==1 and result['metrics']['cached_calls']==1
    assert result['metrics']['analysis_wall_ms'] is None
    assert result['metrics']['items_per_second'] is None
    assert result['metrics']['estimated_usd'] is None
    assert result['metrics']['cost_unknown_calls']==1
    assert result['rows'][0]['missing_timing_calls']==1
    assert result['rows'][1]['assessment_ms'] is None


def test_feature_labels_require_current_verified_exact_spans_and_keep_unknown_denominator():
    mission,records,program=fixture_records()
    feature={'choice':'question','label':'Question','dimension':'Observed approach','span_ids':['p0'],
             'verification_status':'supported','decision_id':'d0'}
    records['artifact_analysis'][0]['features']={'approach':feature}
    result=project_corpus(mission,records,program)
    assert result['features'][0]=={'id':'approach','label':'Observed approach','denominator':2,'unknown':1,
                                  'values':[{'value':'question','label':'Question','count':1,'source_ids':['s0']}]}
    records['span'][0]['private']=True
    assert project_corpus(mission,records,program)['features'][0]['unknown']==2


def test_private_program_and_contradiction_are_not_promoted_as_supported():
    mission,records,program=fixture_records()
    extra=deepcopy(records['finding'][0]);extra.update(id='counter',status='contradicted')
    records['finding'].append(extra)
    assert project_corpus(mission,records,program)['rows'][0]['cells'][0]['status']=='contradicted'
    program.update(private=True,criteria=[{'id':'private','label':'Private label','question':'Private question'}])
    result=project_corpus(mission,records,program)
    assert not result['rows'] and 'Private' not in str(result)


@pytest.mark.parametrize('record_kind,key',[('source','decision_id'),('artifact_analysis','decision_id'),('artifact_analysis','verification_decision_id')])
def test_assessments_cannot_reuse_a_different_sources_decision(record_kind,key):
    mission,records,program=fixture_records()
    records[record_kind][0][key]='d1'
    result=project_corpus(mission,records,program)
    assert [row['source_id'] for row in result['rows']]==['s1']
    assert result['metrics']['jev_calls']==1 and result['rollups'][0]['denominator']==1


def test_company_rows_require_their_own_source_decision():
    mission,records,program=fixture_records()
    program['unit']='companies'
    records['source'][0]['decision_id']='d1'
    assert [row['source_id'] for row in project_corpus(mission,records,program)['rows']]==['s1']


@pytest.mark.parametrize('binding',['different_source','unbound'])
def test_findings_need_source_bound_verification_before_populating_a_cell(binding):
    mission,records,program=fixture_records()
    if binding=='different_source':records['finding'][0]['decision_id']='d1'
    else:
        records['decision'].append({**records['decision'][0],'id':'unbound','source_id':None})
        records['finding'][0]['decision_id']='unbound'
    result=project_corpus(mission,records,program)
    assert result['metrics']['items']==2
    cell=result['rows'][0]['cells'][0]
    assert cell['status']=='unknown' and cell['citations']==[] and cell['confidence'] is None
    assert cell['finding_ids']==cell['decision_ids']==[]
    assert result['rollups'][0]['supported']==1 and result['rollups'][0]['unknown']==1


def test_feature_verification_cannot_borrow_another_sources_decision():
    mission,records,program=fixture_records()
    records['artifact_analysis'][0]['features']={'approach':{'choice':'question','label':'Question',
        'dimension':'Observed approach','span_ids':['p0'],'verification_status':'supported','decision_id':'d1'}}
    result=project_corpus(mission,records,program)
    assert result['metrics']['items']==2
    assert result['features'][0]['values']==[] and result['features'][0]['unknown']==2
