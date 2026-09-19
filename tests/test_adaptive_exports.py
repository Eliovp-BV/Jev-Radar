"""Adaptive exports retain decisions and provenance without raw input snapshots."""
import json

from radar.actions import construct
from radar.activity import jev_activity
from radar.program import program_fingerprint
from radar.reports import export_data,report
from radar.schemas import Plan
from radar.storage import Store,uid,now,dumps


def fixture(tmp_path):
    store=Store(tmp_path/'adaptive-export.sqlite');mid=uid()
    plan=Plan(goal='Compare the public descriptions of individual science demonstrations',research_mode='adaptive',
              criteria=[{'id':'old','label':'Old preset','question':'What was the old draft question?'}]).model_dump()
    store.execute('INSERT INTO missions VALUES(?,?,?,?,?,?,?,?,?)',(mid,plan['goal'],'partial',dumps(plan),1,now(),now(),None,'fixture'))
    criterion={'id':'observed','label':'Observed content','question':'Which descriptions support this comparison?','rubric':'Only saved evidence.'}
    program={'id':'program','status':'complete','created_at':now(),'program_version':1,'plan_version':1,'decision_id':'planning',
             'fingerprint':program_fingerprint(plan,1),'objective':plan['goal'],'unit':'videos','method':'explain_patterns',
             'selections':{'research_unit':'videos','raw_state':'PRIVATE_RAW_MARKER'},'criteria':[criterion],
             'search_queries':['science demonstrations'],'evidence_requirements':['Keep media-access gaps explicit.'],
             'stop_conditions':['Stop at configured limits.'],'limitations':['Typed program options are bounded.'],
             'provenance':{'selection':'Jev typed answers','model':'jev-fixture','latency_ms':5,'raw_state':'PRIVATE_RAW_MARKER'},
             'state':{'transcript':'PRIVATE_RAW_MARKER'}}
    sources=[]
    for index in range(2):
        sources.append({'id':f'source{index}','url':f'https://www.youtube.com/watch?v=fixture{index}abc','title':f'Demonstration {index}',
                        'source_kind':'video','unit_id':f'video-{index}','retrieved_at':now(),'source_date':None,'content_hash':str(index),
                        'coverage':{'method':'search-provider metadata'},'text':'FULL_TRANSCRIPT_MARKER'*100,'chunks':[],
                        'video_metadata':{'views':100 if index==0 else None,'transcript':'FULL_TRANSCRIPT_MARKER'*100,'description':'FULL_DESCRIPTION_MARKER'*100,
                                          'published_at':None,'published_at_basis':'Provider page date, not verified upload date','provider':'brave',
                                          'provenance':'Search-provider indexed metadata; no watched footage','observed_at':now(),'acquisition':'search_provider_metadata',
                                          'transcript_available':False,'frames_available':False,'raw_state':'PRIVATE_RAW_MARKER'},
                        'provider_observation':{'search_id':'search','result_id':f'result{index}','latency_ms':12,'raw_state':'PRIVATE_RAW_MARKER'}})
    assessment={'id':'artifact','source_id':'source0','unit_id':'video-0','program_id':'program','plan_version':1,'decision_id':'assess','verification_decision_id':'verify',
                'unit':'videos','role':'primary_artifact','relevance':1,'evidence_basis':'indexed video metadata only',
                'features':{'title_hook':{'choice':'challenge','label':'A named experiment','span_ids':['span'],'basis':'indexed title','decision_id':'verify','raw_state':'PRIVATE_RAW_MARKER'}},
                'limitations':['No video frames inspected.'],'state':'PRIVATE_RAW_MARKER'}
    analysis={'id':'comparison','program_id':'program','decision_id':'compare','plan_version':1,'unit':'videos','artifact_count':2,
              'patterns':[{'id':'title_hook_challenge','label':'Experiment titles <script>','source_ids':['source0'],'comparison_source_ids':['source1'],
                           'span_ids':['span'],'status':'possible','model_status':'possible','observation':'One named experiment among two items.',
                           'rationale':'A bounded hypothesis to test.','limitations':['No causal identification.'],'state':'PRIVATE_RAW_MARKER'}],
              'comparisons':[{'id':'pair','source_ids':['source0','source1'],'observation':'Compare indexed titles.','basis':'Observed text','state':'PRIVATE_RAW_MARKER'}],
              'next_test':{'id':'content','label':'Obtain permitted primary content before interpreting unseen details.','state':'PRIVATE_RAW_MARKER'},
              'limitations':['Missing transcripts; no causal conclusion.'],'state':'PRIVATE_RAW_MARKER'}
    search={'id':'search','provider':'brave','search_kind':'video','query':'science demonstrations','timestamp':now(),
            'results':[{'id':'result0','url':sources[0]['url'],'title':'Demonstration','snippet':'Observed description. '+('x'*300)+'FULL_DESCRIPTION_MARKER',
                        'video':{'views':100,'duration':'01:00','transcript':'FULL_TRANSCRIPT_MARKER'}}]}
    records=[('research_program',program),('artifact_analysis',assessment),('research_analysis',analysis),('search',search),
             ('span',{'id':'span','source_id':'source0','start':0,'end':1300,'text':'Q'*1300}),
             ('entity',{'id':'entity','name':'Fixture artifact','fields':{},'source_ids':['source0']}),
             ('metric',{'id':'private-metric','private':True,'kind':'user-supplied','metric':'views','unit':'views','value':9,'provenance':'PRIVATE_IMPORT_MARKER'})]
    records += [('source',source) for source in sources]
    store.mutate(mid,'fixture.records',{},records,mode='fixture')
    store.mutate(mid,'mission.finished',{'gaps':['Transcript access'],'stop_reason':{'code':'configured_limits','message':'Configured page allowance reached.','raw_state':'PRIVATE_RAW_MARKER'}},mode='fixture')
    return store,mid,program,assessment,analysis


def test_safe_json_keeps_program_assessments_and_provenance_without_snapshots(tmp_path):
    store,mid,program,assessment,analysis=fixture(tmp_path)
    body,_=report(store,mid,'json');data=json.loads(body)
    for marker in ('FULL_TRANSCRIPT_MARKER','FULL_DESCRIPTION_MARKER','PRIVATE_RAW_MARKER','PRIVATE_IMPORT_MARKER'):
        assert marker not in body
    assert data['research_program'][0]['decision_id']=='planning'
    assert data['artifact_analysis'][0]['features']['title_hook']['span_ids']==['span']
    assert data['artifact_analysis'][0]['verification_decision_id']==data['artifact_analysis'][0]['features']['title_hook']['decision_id']=='verify'
    assert data['research_analysis'][0]['patterns'][0]['status']=='possible'
    assert data['sources'][0]['video_metadata']['views']==100 and data['sources'][1]['video_metadata']['views'] is None
    assert not data['sources'][0]['video_metadata']['transcript_available']
    assert data['sources'][0]['provider_observation']['latency_ms']==12
    assert len(data['evidence_excerpts'][0]['text'])==240 and data['evidence_excerpts'][0]['export_excerpt_truncated']
    assert data['metrics'][0]['value'] is None and data['cohorts']==[]
    store.close()


def test_readable_reports_show_actual_program_patterns_citations_limits_and_unperformed_test(tmp_path):
    store,mid,*_=fixture(tmp_path)
    for fmt in ('md','html'):
        body,_=report(store,mid,fmt)
        assert 'Jev research approach' in body and 'Observed content' in body
        assert 'Cross-item assessment' in body and 'possible' in body and 'bounded hypothesis' in body
        assert 'https://www.youtube.com/watch?v=fixture0abc' in body and 'https://www.youtube.com/watch?v=fixture1abc' in body
        assert 'Next test' in body and 'not performed' in body and 'Obtain permitted primary content' in body
        assert 'Configured page allowance reached.' in body and 'Transcript access' in body
        assert ('max\\_pages=' if fmt=='md' else 'max_pages=') in body
        assert 'Provider page date' in body and 'no watched footage' in body
        assert '<script>' not in body and 'FULL_TRANSCRIPT_MARKER' not in body and 'PRIVATE_IMPORT_MARKER' not in body
    store.close()


def test_adaptive_suggestions_follow_program_questions_not_old_preview_lens(tmp_path):
    store,mid,*_=fixture(tmp_path)
    suggestions=construct(store,mid,current=True)
    assert suggestions and all('observed content' in item['title'].lower() for item in suggestions)
    assert all('old preset' not in item['title'].lower() for item in suggestions)
    store.close()


def test_private_adaptive_records_are_omitted(tmp_path):
    store,mid,program,assessment,analysis=fixture(tmp_path)
    store.mutate(mid,'fixture.private',{},[(kind,{**record,'private':True}) for kind,record in [('research_program',program),('artifact_analysis',assessment),('research_analysis',analysis)]],mode='fixture')
    data=export_data(store,mid)
    assert data['research_program']==data['artifact_analysis']==data['research_analysis']==[]
    store.close()


def test_planning_and_comparison_activity_are_separate_real_stages(tmp_path):
    store,mid,program,assessment,analysis=fixture(tmp_path)
    def decision(identity,purpose,key,choice,options):
        return {'id':identity,'purpose':purpose,'status':'complete','created_at':identity,'latency_ms':10,
                'questions':{key:{'type':'choice','criteria':options,'instructions':'Fixture typed question.'}},
                'answers':{key:{'choice':choice}}}
    decisions=[decision('planning','Design research approach','research_unit','videos',{'videos':'Individual videos','companies':'Companies'}),
               decision('compare','Compare observed artifacts','title_hook_challenge','possible',{'possible':'Hypothesis','observed':'Descriptive pattern'})]
    records={kind:store.records(mid,kind) for kind in ('source','research_program','research_analysis')};records['decision']=decisions
    activity=jev_activity(store.mission(mid),records,[],{'attempts':2})
    groups={group['id']:group for group in activity['groups']}
    assert len(groups['planning']['items'])==1 and len(groups['comparison']['items'])==1
    assert not groups['classification']['items']
    assert groups['planning']['items'][0]['decision_id']=='planning' and 'Configured' in groups['planning']['items'][0]['result']
    assert groups['comparison']['items'][0]['source_ids']==['source0','source1']
    assert 'possible' in groups['comparison']['items'][0]['result']
    assert activity['summary']['measured_calls']==2 and activity['summary']['median_ms']==10
    store.close()


def test_stale_comparison_exports_do_not_revive_old_patterns_or_next_test(tmp_path):
    store,mid,program,assessment,analysis=fixture(tmp_path)
    store.mutate(mid,'fixture.invalidated',{},[('research_analysis',{**analysis,'stale':True})],mode='fixture')
    data=export_data(store,mid)
    record=data['research_analysis'][0]
    assert record['stale'] and record['patterns']==record['comparisons']==[] and 'next_test' not in record
    for fmt in ('md','html'):
        body,_=report(store,mid,fmt)
        assert 'Comparison needs reassessment' in body and 'Historical comparison' in body
        assert 'Experiment titles' not in body and 'Obtain permitted primary content' not in body
    store.close()


def test_refinement_and_saved_evidence_activity_do_not_claim_network_or_media_fetch():
    def decision(identity,key,choice,options,purpose='Choose next research action'):
        return {'id':identity,'purpose':purpose,'status':'complete','created_at':identity,'latency_ms':10,
                'questions':{key:{'type':'choice','criteria':options,'instructions':'Fixture selection.'}},'answers':{key:{'choice':choice}}}
    records={'decision':[decision('refine','refine_query','q0',{'q0':'original evidence'},'Refine discovery for unanswered questions'),
                         decision('select-video','next','video',{'video':'Inspect indexed metadata'}),
                         decision('select-saved','next','saved',{'saved':'Reassess saved observations'})],
             'action':[{'id':'search','kind':'search','parent':'refine','status':'complete'},
                       {'id':'video','kind':'video','status':'complete'},
                       {'id':'saved','kind':'reassess','source_id':'source','status':'complete'}],
             'source':[{'id':'source','action_id':'video','discovered_via':'search-result'}],
             'search_attempt':[{'id':'attempt','action_id':'search','search_id':'search-result'}]}
    activity=jev_activity({'plan':{}},records,[],{'attempts':3})
    items={item['id']:item for group in activity['groups'] for item in group['items']}
    refined=items['refine:refine_query']
    assert refined['stage']=='selection' and refined['action_ids']==['search'] and refined['search_ids']==['search-result']
    assert refined['source_ids']==['source'] and 'complete' in refined['result']
    assert 'does not fetch or watch' in items['select-video:next']['result']
    assert 'no new page or media fetch' in items['select-saved:next']['result'] and items['select-saved:next']['source_ids']==['source']


def test_text_cost_telemetry_keeps_unknown_and_reserved_calls_separate(tmp_path):
    from radar.reports import telemetry
    store,mid,*_=fixture(tmp_path)
    store.mutate(mid,'fixture.costs',{},[
        ('text_call',{'id':'priced','status':'complete','actual_usd':.002,'reserved_usd':.01,'usage':{'input_tokens':10,'output_tokens':20}}),
        ('text_call',{'id':'uncertain','status':'error','actual_usd':None,'reserved_usd':.03}),
        ('text_call',{'id':'legacy','status':'error'}),
    ],mode='fixture')
    result=telemetry(store,mid)
    assert result['text_estimated_usd']==.002
    assert result['text_reserved_usd']==.03
    assert result['text_unpriced_attempts']==1
    assert 'unknown' in result['text_cost']
    store.close()
