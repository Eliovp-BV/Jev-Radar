"""Bounded discovery fixtures: no external requests or paid inference."""
from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from radar.api import create_app
from radar.config import Settings
from radar.outcomes import plan_readiness,mission_outcome
from radar.research import Runner
from radar.reports import telemetry
from radar.schemas import Plan
from radar.search import queries_for, source_query, SearchError
from radar.storage import Store, uid, now, dumps


def fixture(tmp_path, **changes):
    plan=Plan(goal='Find French alternatives to a public workspace product',research_mode='fixed',providers=['brave'],
              criteria=[{'id':'offer','label':'Offering','question':'What concrete product does this company offer?'}],**changes).model_dump()
    store=Store(tmp_path/'fixture.sqlite'); mid=uid()
    store.execute('INSERT INTO missions VALUES(?,?,?,?,?,?,?,?,?)',(mid,plan['goal'],'running',dumps(plan),1,now(),now(),None,'fixture'))
    store.set_setting('action_library',[])
    runner=Runner(Settings(data_dir=tmp_path,key='fixture-only',brave_key='fixture-only'),store)
    return store,runner,mid,plan


def test_query_templates_use_goal_subject_and_reserve_adaptive_budget():
    plan=Plan(goal='Find French alternatives to FixtureDesk. Compare capabilities, prices and content.',providers=['brave'],limits={'max_queries':4}).model_dump()
    queries=queries_for(plan)
    assert queries[0]=='French alternatives to FixtureDesk'
    assert len(queries)==3 and all('Compare capabilities' not in q for q in queries)
    assert source_query('One AI workspace for team documents and automation',plan)=='AI workspace team documents automation French alternatives'
    plan['goal']='Find alternatives to Fixture.test. Compare capabilities.'
    assert 'Fixture.test' in queries_for(plan)[0]


def test_web_setup_does_not_ask_for_competitor_urls():
    plan=Plan(goal='Find French alternatives to FixtureDesk',providers=['brave']).model_dump()
    result=plan_readiness(plan,{'jev':True,'brave':False})
    assert [block['code'] for block in result['blockers']]==['brave_unavailable']
    assert result['blockers'][0]['action']=='settings'


def test_settings_reload_changes_capabilities_without_connection_request(tmp_path):
    settings=Settings(data_dir=tmp_path,key='')
    app=create_app(settings)
    app.state.runner.jev.client=lambda: (_ for _ in ()).throw(AssertionError('No provider request permitted'))
    with TestClient(app) as client:
        client.headers['x-radar-csrf']=client.get('/api/session').json()['csrf']
        with patch('radar.api.Settings.load',return_value=Settings(data_dir=tmp_path,key='fixture-new-jev',brave_key='fixture-new-search')):
            response=client.post('/api/settings/reload')
        assert response.status_code==200 and response.json()['jev'] and response.json()['brave']
        assert 'fixture-new' not in response.text
        assert response.json()['connection']['success'] is False
        assert not app.state.store.rows('SELECT * FROM reservations')


def test_diverse_candidate_batch_includes_new_domains_after_many_old_links(tmp_path):
    store,runner,mid,plan=fixture(tmp_path)
    old=[{'id':str(i),'kind':'fetch','value':f'https://old.example/page/{i}'} for i in range(20)]
    new={'id':'new','kind':'fetch','value':'https://new.example/'}
    query={'id':'query','kind':'search','value':'public company alternatives'}
    batch=runner.candidate_batch(old+[new,query],[{'url':'https://old.example/'}])
    assert len(batch)==16 and batch[:2]==[new,query]
    store.close()


async def test_jev_abstention_examines_unseen_candidate_batch_without_forced_choice(tmp_path):
    store,runner,mid,plan=fixture(tmp_path)
    for i in range(21):runner.add_action(mid,'fetch',f'https://candidate{i}.example/')
    runner.jev.ask=AsyncMock(return_value={'id':'fixture-stop','answers':{'next':{'choice':'stop'}}})
    runner.do_page=AsyncMock(side_effect=AssertionError('Jev did not select a fetch'))
    await runner.run(mid)
    events=[e['payload'] for e in store.events(mid) if e['type']=='action.abstained']
    assert len(events)==2 and len(events[0]['candidate_ids'])==16 and len(events[1]['candidate_ids'])==5
    assert not set(events[0]['candidate_ids'])&set(events[1]['candidate_ids'])
    assert runner.jev.ask.await_count==2 and runner.do_page.await_count==0
    assert store.mission(mid)['status']=='partial'
    store.close()


async def test_later_success_does_not_reuse_early_batch_stop_reason(tmp_path):
    store,runner,mid,plan=fixture(tmp_path)
    for i in range(17):runner.add_action(mid,'fetch',f'https://candidate{i}.example/')
    runner.jev.ask=AsyncMock(return_value={'id':'fixture-stop','answers':{'next':{'choice':'stop'}}})
    runner.do_page=AsyncMock()
    await runner.run(mid)
    finished=next(e for e in store.events(mid) if e['type']=='mission.finished')
    assert runner.do_page.await_count==1
    assert finished['payload']['stop_reason']['code']=='no_useful_actions'
    store.close()


async def test_failed_search_counts_against_attempt_limit(tmp_path):
    store,runner,mid,plan=fixture(tmp_path,limits={'max_queries':1})
    runner.search.query=AsyncMock(side_effect=SearchError('Fixture provider denial'))
    action={'id':'search-action','kind':'search','value':'public fixture query'}
    with pytest.raises(SearchError):await runner.do_search(mid,action,plan)
    assert runner.search_usage(mid)==1
    assert store.records(mid,'search_attempt')[0]['status']=='failed'
    assert not runner.allowable(action,plan,[],[None]*runner.search_usage(mid))
    assert not store.records(mid,'search')
    assert telemetry(store,mid)['search_attempts']==1
    assert telemetry(store,mid)['search_cost']=='Unknown account pricing and request billing'
    store.close()


def test_directory_outbound_links_are_bounded_observed_and_discovery_only(tmp_path):
    store,runner,mid,plan=fixture(tmp_path)
    source={'url':'https://directory.example/','entity_type':'directory','links':[{'url':f'https://vendor{i}.example/','label':f'Fixture vendor {i}'} for i in range(12)]}
    selected=runner.outbound_candidates(source,plan)
    assert len(selected)==6 and all(link in source['links'] for link in selected)
    plan['providers']=['seed']
    assert not runner.outbound_candidates(source,plan)
    plan['providers']=['brave'];source['entity_type']='software_product'
    assert not runner.outbound_candidates(source,plan)
    store.close()


@pytest.mark.parametrize('kind', ['source','entity'])
async def test_rejected_record_cannot_satisfy_completion(tmp_path,kind):
    store,runner,mid,plan=fixture(tmp_path,discovery_target=1)
    records=[('source',{'id':'source','url':'https://vendor.example/'}),
             ('entity',{'id':'entity','name':'vendor.example','domains':['vendor.example'],'classification':'direct','role':'candidate','fields':{},'source_ids':['source']}),
             ('finding',{'id':'finding','entity_id':'entity','criterion_id':'offer','status':'supported','source_ids':['source']})]
    for record_kind,record in records:
        if record_kind==kind:record['review']='rejected'
    store.mutate(mid,'fixture.rejection',{},records,mode='fixture')
    await runner.finish(mid)
    assert store.mission(mid)['status']=='partial'
    assert 'Offering' in store.events(mid)[-1]['payload']['gaps']
    assert runner.discovery_coverage(mid,plan)['candidate_domains']==0
    store.close()


async def test_reference_only_coverage_is_partial_even_with_all_questions_answered(tmp_path):
    store,runner,mid,plan=fixture(tmp_path)
    records=[('entity',{'id':'reference','name':'ref.example','domains':['ref.example'],'classification':'reference','role':'reference_product','fields':{},'source_ids':['source1','source2']}),
             ('source',{'id':'source1','url':'https://ref.example/','entity_id':'reference'}),('source',{'id':'source2','url':'https://ref.example/pricing','entity_id':'reference'}),
             ('finding',{'id':'finding','entity_id':'reference','criterion_id':'offer','status':'supported','source_ids':['source1']})]
    store.mutate(mid,'fixture.reference',{},records,mode='fixture')
    runner.jev.ask=AsyncMock(side_effect=AssertionError('No prepared experiment request expected'))
    await runner.finish(mid)
    assert store.mission(mid)['status']=='partial'
    assert store.events(mid)[-1]['payload']['discovery']['candidate_domains']==0
    store.close()


def test_discovery_coverage_excludes_rejected_or_excluded_source_evidence(tmp_path):
    store,runner,mid,plan=fixture(tmp_path)
    records=[]
    for i in range(3):
        records += [('entity',{'id':f'e{i}','name':f'c{i}.example','domains':[f'c{i}.example'],'classification':'direct','role':'candidate','source_ids':[f's{i}']}),
                    ('source',{'id':f's{i}','url':f'https://c{i}.example/'}),
                    ('finding',{'id':f'f{i}','entity_id':f'e{i}','criterion_id':'offer','status':'supported','source_ids':[f's{i}']})]
    store.mutate(mid,'fixture.candidates',{},records,mode='fixture')
    assert runner.discovery_coverage(mid,plan)['satisfied']
    plan['excluded_domains']=['c0.example']
    store.mutate(mid,'fixture.rejected',{},[('source',{'id':'s1','url':'https://c1.example/','review':'rejected'})],mode='fixture')
    result=runner.discovery_coverage(mid,plan)
    assert not result['satisfied'] and result['candidate_domains']==1
    store.close()


async def test_documentation_does_not_overwrite_company_relationship(tmp_path):
    store,runner,mid,plan=fixture(tmp_path)
    roles=iter([('candidate','direct','software_product'),('background','reference','editorial')])
    async def assessed(mid,state,questions,purpose,source_id):
        role,relationship,kind=next(roles)
        choices={'entity_role':role,'entity_kind':relationship,'entity_type':kind,'purpose':'offer','excluded_entity':'allowed','discovery_phrase':'unknown'}
        answers={key:{'choice':choices.get(key,'unknown')} for key in questions}
        answers['relevance']={'score':2};answers['original_data_claim']={'noul':0}
        return {'id':uid(),'answers':answers,'model':'jev-1.13.0'}
    runner.jev.ask=AsyncMock(side_effect=assessed)
    text='Fixture software product for team document workflows.'
    chunk={'id':'s0','text':text,'start':0,'end':len(text),'anchor':None,'provenance':'source_text'}
    for suffix in ('','docs'):
        source={'id':uid(),'url':'https://company.example/'+suffix,'title':'Fixture company','text':text,'source_date':None,'source_date_provenance':None,'retrieved_at':now(),'coverage':{}}
        await runner.analyze(mid,source,[chunk],plan)
    entity=store.records(mid,'entity')[0]
    assert entity['classification']=='direct' and entity['role']=='candidate' and entity['entity_type']=='software_product'
    assert [o['role'] for o in entity['classification_observations']]==['candidate','background']
    assert len({o['source_id'] for o in entity['classification_observations']})==2
    store.close()


def test_rejected_classification_source_cannot_survive_via_other_findings(tmp_path):
    store,runner,mid,plan=fixture(tmp_path,discovery_target=1)
    records=[('source',{'id':'offer-source','url':'https://vendor.example/'}),
             ('source',{'id':'docs-source','url':'https://vendor.example/docs'}),
             ('decision',{'id':'offer-decision','status':'complete'}),('decision',{'id':'docs-decision','status':'complete'}),
             ('entity',{'id':'vendor','name':'vendor.example','domains':['vendor.example'],'source_ids':['offer-source','docs-source'],
                        'classification':'direct','role':'candidate','entity_type':'software_product','fields':{},'classification_observations':[
                            {'source_id':'offer-source','decision_id':'offer-decision','classification':'direct','role':'candidate','entity_type':'software_product'},
                            {'source_id':'docs-source','decision_id':'docs-decision','classification':'reference','role':'background','entity_type':'editorial'}]}),
             ('finding',{'id':'docs-finding','entity_id':'vendor','criterion_id':'offer','status':'supported','source_ids':['docs-source']})]
    store.mutate(mid,'fixture.classification',{},records,mode='fixture')
    assert runner.discovery_coverage(mid,plan)['candidate_domains']==1
    store.mutate(mid,'fixture.review',{},[('source',{'id':'offer-source','url':'https://vendor.example/','review':'rejected'})],mode='fixture')
    groups={kind:store.records(mid,kind) for kind in ('entity','finding','source','decision')}
    result=mission_outcome(store.mission(mid),groups,store.events(mid),{'jev':True,'brave':True})
    assert result['counts']['supported_findings']==1
    assert result['counts']['alternative_candidates']==0
    assert runner.discovery_coverage(mid,plan)['candidate_domains']==0
    store.close()


async def test_explicit_reference_is_inspected_as_logged_dependency(tmp_path):
    reference='https://reference.example/'
    store,runner,mid,plan=fixture(tmp_path,reference=reference,seeds=['https://candidate-a.example/','https://candidate-b.example/'])
    inspected=[]
    async def simulated_page(mid,action,plan):
        inspected.append(action['value'])
        store.mutate(mid,'fixture.inspected',{},[('source',{'id':'reference-source','url':reference,'title':'Fixture reference','requested_url':reference,'decision_id':'fixture-assessment'})],mode='fixture')
    runner.do_page=AsyncMock(side_effect=simulated_page)
    runner.jev.ask=AsyncMock(return_value={'id':'fixture-stop','answers':{'next':{'choice':'stop'}}})
    await runner.run(mid)
    assert inspected==[reference]
    dependency=next(e for e in store.events(mid) if e['type']=='action.reference_prerequisite')
    assert 'not selected by Jev' in dependency['payload']['reason']
    assert runner.jev.ask.await_count==1  # The remaining candidate batch still follows Jev.
    store.close()


async def test_candidate_assessment_receives_bounded_cited_reference_context(tmp_path):
    reference='https://reference.example/'
    store,runner,mid,plan=fixture(tmp_path,reference=reference)
    records=[('source',{'id':'reference-source','url':reference}),
             ('entity',{'id':'reference-entity','name':'reference.example','domains':['reference.example'],'source_ids':['reference-source'],'role':'reference_product','classification':'reference','fields':{}})]
    for i in range(8):
        records += [('finding',{'id':f'reference-finding-{i}','entity_id':'reference-entity','criterion_id':'offer','status':'supported','source_ids':['reference-source'],'span_ids':[f'reference-span-{i}']}),
                    ('span',{'id':f'reference-span-{i}','source_id':'reference-source','text':'An automation workspace for team documents. '+('Long fixture context. '*40)})]
    store.mutate(mid,'fixture.reference',{},records,mode='fixture')
    async def assess(mid,state,questions,purpose,source_id):
        assert len(state['reference_evidence'])==6
        assert all(item['url']==reference and len(item['text'])<=400 and item['text_kind']=='source passage' for item in state['reference_evidence'])
        assert 'same core job' in questions['entity_kind'].instructions
        assert 'training' in questions['entity_type'].instructions
        answers={key:{'choice':'unknown'} for key in questions}
        answers['relevance']={'score':2};answers['original_data_claim']={'noul':0};answers['excluded_entity']={'choice':'allowed'}
        return {'id':'fixture-assessment','answers':answers,'model':'jev-1.13.0'}
    runner.jev.ask=AsyncMock(side_effect=assess)
    text='Fixture provider offers a customer training service.'
    source={'id':'candidate-source','url':'https://candidate.example/','title':'Fixture candidate','text':text,'source_date':None,'source_date_provenance':None,'retrieved_at':now(),'coverage':{}}
    await runner.analyze(mid,source,[{'id':'s0','text':text,'start':0,'end':len(text),'anchor':None,'provenance':'source_text'}],plan)
    assert runner.jev.ask.await_count==1
    store.close()
