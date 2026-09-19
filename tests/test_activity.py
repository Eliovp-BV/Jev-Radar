"""Recorded Jev work, portable configuration, and new-plan defaults only."""
from copy import deepcopy
from unittest.mock import patch
import json

from fastapi.testclient import TestClient
from radar.activity import jev_activity
from radar.acquisition import AGENT
from radar.api import create_app
from radar.config import Settings


def choice(labels, selected):
    return {'type':'choice','criteria':labels,'instructions':'Fixture evidence question.'}, {'type':'choice','choice':selected,'confidence':.8,'probabilities':{key:1 if key==selected else 0 for key in labels}}


def activity_fixture():
    select_q,select_a=choice({'action-a':'Inspect the product page','action-b':'Inspect another page','stop':'No useful action'},'action-a')
    relation_q,relation_a=choice({'direct':'Direct substitute','adjacent':'Related but different work','unknown':'Unknown'},'adjacent')
    passage_q,passage_a=choice({'s0':'Existing passage','unknown':'No passage'},'s0')
    support_q,support_a=choice({'supported':'Passage directly answers','unknown':'Insufficient evidence'},'supported')
    priority_q,priority_a=choice({'experiment-a':'Check a scoped evidence gap','none':'No useful experiment'},'experiment-a')
    def decision(id,questions,answers,latency,source_id=None,purpose='Fixture assessment'):
        return {'id':id,'status':'complete','questions':questions,'answers':answers,'latency_ms':latency,'queue_ms':2,'source_id':source_id,
                'purpose':purpose,'model':'jev-fixture','created_at':id,'usage':{'input_tokens':10,'output_tokens':5}}
    selection=decision('d1',{'next':select_q},{'next':select_a},100,purpose='Choose next research action')
    assessment=decision('d2',{'relevance':{'type':'score','criteria':['Unrelated','Context','Useful'],'instructions':'Assess relevance.'},'entity_kind':relation_q,'span_offer':passage_q},
                        {'relevance':{'type':'score','score':1.75,'confidence':.6,'probabilities':{'0':0,'1':.25,'2':.75}},'entity_kind':relation_a,'span_offer':passage_a},200,'source-a')
    verification=decision('d3',{'offer':support_q},{'offer':support_a},300,'source-a','Verify selected evidence against each question')
    priority=decision('d4',{'priority':priority_q},{'priority':priority_a},400,purpose='Prioritize prepared experiments')
    cached={**deepcopy(assessment),'id':'d5','cache':True,'latency_ms':1,'created_at':'d5'}
    failed={**deepcopy(selection),'id':'d6','status':'error','answers':{},'latency_ms':500,'created_at':'d6'}
    records={'decision':[selection,assessment,verification,priority,cached,failed],
             'action':[{'id':'action-a','kind':'fetch','status':'complete','value':'https://vendor.example/','decision_id':'d1'}],
             'source':[{'id':'source-a','url':'https://vendor.example/','action_id':'action-a','entity_id':'entity-a','classification':'adjacent','decision_id':'d2'}],
             'finding':[{'id':'finding-a','entity_id':'entity-a','criterion_id':'offer','status':'supported','source_ids':['source-a'],'decision_id':'d3'}],
             'opportunity_priority':[{'id':'priority-a','selected':'experiment-a','decision_id':'d4','suggestions':[{'id':'experiment-a','evidence_ids':['finding-a'],'context_source_ids':['source-a']}]}]}
    events=[{'id':'event-1','type':'action.reference_prerequisite','payload':{'action_id':'reference-action','reason':'Read the specified reference first; no Jev selection.'}},
            {'id':'event-2','type':'assessment.recorded','payload':{'source_id':'source-a','decision_id':'d2'}}]
    mission={'plan':{'criteria':[{'id':'offer','label':'Offering'}]}}
    return mission,records,events


def test_batched_questions_do_not_multiply_live_call_timings_or_attempts():
    mission,records,events=activity_fixture()
    before=deepcopy((mission,records,events))
    activity=jev_activity(mission,records,events,{'attempts':5})
    summary=activity['summary']
    assert summary['attempts']==5 and summary['completions']==4 and summary['errors']==1
    assert summary['cached_calls']==1 and summary['measured_calls']==4
    assert summary['median_ms']==250 and summary['latest_ms']==400
    assert summary['answered_questions']==6
    items=[item for group in activity['groups'] for item in group['items']]
    assert all(item['latency_ms'] is None and item['queue_ms'] is None for item in items if item['cached'])
    assert len(items)>summary['attempts']
    assert (mission,records,events)==before


def test_decisions_link_observed_work_and_keep_application_rules_separate():
    mission,records,events=activity_fixture()
    activity=jev_activity(mission,records,events,{'attempts':5})
    items={item['id']:item for group in activity['groups'] for item in group['items']}
    selected=items['d1:next']
    assert selected['selected']['label']=='Inspect the product page'
    assert selected['source_ids']==['source-a'] and selected['finding_ids']==['finding-a']
    assert selected['action_ids']==['action-a'] and 'snapshot' in selected['result']
    assert 'retained' in items['d2:relevance']['result']
    assert items['d2:relevance']['selected']['value']==1.75 and items['d2:relevance']['selected']['maximum']==2
    assert 'adjacent' in items['d2:entity_kind']['result']
    assert items['d3:offer']['finding_ids']==['finding-a'] and '1 supported' in items['d3:offer']['result']
    assert items['d4:priority']['finding_ids']==['finding-a'] and items['d4:priority']['source_ids']==['source-a']
    assert activity['deterministic'][0]['action_ids']==['reference-action']
    assert all('reference-action' not in item['action_ids'] for item in items.values())


def test_screened_page_and_actual_search_response_are_visible():
    mission,records,events=activity_fixture()
    events[-1]['type']='source.screened_out'
    records['action'][0]['kind']='search';records['action'][0]['value']='fixture query'
    records['search']=[{'id':'search-a','query':'fixture query','results':[{'url':'https://one.example/'},{'url':'https://two.example/'}]}]
    records['search_attempt']=[{'id':'attempt-a','action_id':'action-a','search_id':'search-a'}]
    activity=jev_activity(mission,records,events,{'attempts':5})
    items={item['id']:item for group in activity['groups'] for item in group['items']}
    assert '2 results' in items['d1:next']['result'] and items['d1:next']['search_ids']==['search-a']
    assert 'screened out' in items['d2:relevance']['result']


def test_empty_activity_has_no_synthetic_decisions_or_timings():
    activity=jev_activity({'plan':{}},{},[],{'attempts':0})
    assert activity['summary']['median_ms'] is None and activity['summary']['measured_calls']==0
    assert all(not group['items'] for group in activity['groups']) and not activity['deterministic']


def test_collection_questions_link_individual_leads_and_preserve_deferral():
    inspect_q, inspect_a = choice({'inspect': 'Inspect independent record', 'defer': 'Leave out of this batch'}, 'inspect')
    defer_q, defer_a = choice({'inspect': 'Inspect independent record', 'defer': 'Leave out of this batch'}, 'defer')
    decision = {'id': 'collection-decision', 'status': 'complete', 'purpose': 'Select independent records for parallel assessment',
                'questions': {'opaque-action-a': inspect_q, 'opaque-action-b': defer_q},
                'answers': {'opaque-action-a': inspect_a, 'opaque-action-b': defer_a},
                'state': {'observed_leads': {'opaque-action-a': {'url': 'https://alpha.example/original'},
                                            'opaque-action-b': {'url': 'https://bravo.example/original'}}}}
    records = {'decision': [decision], 'action': [
        {'id': 'opaque-action-a', 'kind': 'fetch', 'status': 'complete', 'value': 'https://alpha.example/original'},
        {'id': 'opaque-action-b', 'kind': 'fetch', 'status': 'queued', 'value': 'https://bravo.example/original'}],
        'source': [{'id': 'source-a', 'action_id': 'opaque-action-a'},
                   {'id': 'older-source-b', 'action_id': 'opaque-action-b'}]}
    events = [{'id': 'collection-event', 'type': 'collection.started',
               'payload': {'decision_id': decision['id'], 'action_ids': ['opaque-action-a']}}]
    activity = jev_activity({'plan': {}}, records, events, {})
    selection = next(group for group in activity['groups'] if group['id'] == 'selection')
    inspected, deferred = selection['items']
    assert inspected['lead_url'] == 'https://alpha.example/original'
    assert inspected['lead_url'] in inspected['title'] and 'opaque-action' not in inspected['title']
    assert inspected['action_ids'] == ['opaque-action-a'] and inspected['source_ids'] == ['source-a']
    assert 'parallel collection' in inspected['result'] and 'complete' in inspected['result']
    assert deferred['action_ids'] == ['opaque-action-b'] and deferred['source_ids'] == []
    assert 'deferred' in deferred['result'] and 'schedules no inspection' in deferred['result']
    assert activity['summary']['action_choices'] == 1 and activity['summary']['abstentions'] == 1
    pending_admission = jev_activity({'plan': {}}, records, [], {})
    assert 'no collection start is linked yet' in next(group for group in pending_admission['groups'] if group['id'] == 'selection')['items'][0]['result']


def test_portable_contact_and_placeholder_credentials():
    assert 'https://' not in Settings().user_agent and 'https://' not in AGENT
    assert 'https://example.org/operator' in Settings(contact_url='https://example.org/operator').user_agent
    with patch('radar.config.dotenv_values',return_value={'TYPESAFE_API_KEY':'your_typesafe_key','BRAVE_SEARCH_API_KEY':'your_brave_search_key'}),patch.dict('radar.config.os.environ',{},clear=True):
        settings=Settings.load()
    assert not settings.key and not settings.brave_key and not settings.contact_url


def test_workspace_does_not_import_runtime_connection_and_defaults_persist(tmp_path):
    runtime=tmp_path/'.runtime';runtime.mkdir()
    (runtime/'connection-test.json').write_text(json.dumps({'success':True,'resolved_model':'unrelated-fixture-model'}))
    data=tmp_path/'data'
    with patch('radar.api.ROOT',tmp_path):app=create_app(Settings(data_dir=data,key='fixture-key'))
    with TestClient(app) as client:
        client.headers['x-radar-csrf']=client.get('/api/session').json()['csrf']
        settings=client.get('/api/settings').json()
        assert settings['connection'] is None and settings['research_defaults']['lens_id']=='auto'
        defaults=settings['research_defaults'];defaults.update(language='fr',region='France',lens_id='content')
        defaults['limits']['max_pages']=18
        mission=client.post('/api/missions',json={'goal':'Inspect a public reference page','seeds':['https://example.org/']}).json()
        updated=client.put('/api/settings/research-defaults',json=defaults)
        assert updated.status_code==200 and updated.json()['research_defaults']==defaults
        assert client.get('/api/missions/'+mission['id']).json()['plan']==mission['plan']
        bad={**defaults,'key':'must-not-be-accepted'}
        assert client.put('/api/settings/research-defaults',json=bad).status_code==422
        assert client.put('/api/settings/research-defaults',json={**defaults,'limits':{**defaults['limits'],'max_pages':81}}).status_code==422
    with TestClient(create_app(Settings(data_dir=data,key='fixture-key'))) as client:
        client.get('/api/session')
        assert client.get('/api/settings').json()['research_defaults']==defaults


def test_automatic_goal_fit_and_explicit_questions_need_no_jev(tmp_path):
    app=create_app(Settings(data_dir=tmp_path,key='fixture-key'))
    with TestClient(app) as client:
        client.headers['x-radar-csrf']=client.get('/api/session').json()['csrf']
        request={'goal':'Find useful video topics about bicycle repair with source evidence','lens_id':'auto','providers':['brave']}
        preview=client.post('/api/plan',json=request).json()
        assert preview['plan']['lens_id']=='content' and preview['planning']['lens']['method']=='deterministic_rules'
        assert all('pricing capabilities' not in query and 'alternatives' not in query for query in preview['plan']['queries'])
        technical=client.post('/api/plan',json={**request,'goal':'Investigate technical implementation and benchmarks for a programming library'}).json()
        assert technical['plan']['lens_id']=='open'
        criterion={'id':'custom','label':'Specific evidence','question':'What specific evidence supports this custom question?'}
        custom=client.post('/api/plan',json={**request,'criteria':[criterion]}).json()
        assert custom['plan']['criteria'][0]['question']==criterion['question']
        assert custom['planning']['lens']['method']=='explicit'
        assert not app.state.store.rows('SELECT * FROM reservations')
