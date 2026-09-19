"""Evidence-consumer contract; fixture roles are not live-model accuracy claims."""
from unittest.mock import AsyncMock

from radar.artifact_research import compare_artifacts,eligible_artifacts
from radar.config import Settings
from radar.research import Runner
from radar.schemas import Plan
from radar.storage import Store,dumps,now,uid
from radar.video import source_from_result


async def test_how_to_video_with_large_native_counter_is_context_not_requested_population(tmp_path):
    store=Store(tmp_path/'video-consumer-fixture.sqlite');mid=uid()
    plan=Plan(goal='Fixture: investigate original widely shared science clips and possible explanations',discovery_target=2,
              criteria=[{'id':'content','label':'Content','question':'What original content was inspected?'}]).model_dump()
    store.execute('INSERT INTO missions VALUES(?,?,?,?,?,?,?,?,?)',(mid,plan['goal'],'running',dumps(plan),1,now(),now(),None,'fixture'))
    program={'id':'fixture-program','unit':'videos','plan_version':1,'criteria':plan['criteria']}
    source=source_from_result({'id':'fixture-result','url':'https://www.youtube.com/watch?v=fixtureGuide',
                              'title':'Fixture tutorial: how to promote science videos','snippet':'Advice about making other videos popular.',
                              'video':{'creator':'Fixture author','views':100_000_000}},
                             {'id':'fixture-search','provider':'brave','timestamp':now(),'query':'fixture query'},
                             {'id':'fixture-action','depth':0})
    source['mode']='fixture'
    # A deliberately supplied role tests the consumer boundary. This test does
    # not claim that a live Jev request would classify every tutorial correctly.
    assessment={'id':'fixture-assessment','source_id':source['id'],'program_id':program['id'],'plan_version':1,
                'role':'secondary_commentary','relevance':1,'unit':'videos','features':{},'evidence_basis':'indexed video metadata only'}
    finding={'id':'fixture-finding','source_ids':[source['id']],'criterion_id':plan['criteria'][0]['id'],
             'status':'supported','review':'unreviewed','span_ids':[]}
    store.mutate(mid,'fixture.commentary',{},[('source',source),('artifact_analysis',assessment),('finding',finding)],mode='fixture')
    runner=Runner(Settings(data_dir=tmp_path,key=''),store)
    runner.jev.ask=AsyncMock(side_effect=AssertionError('This consumer fixture must not make a model request'))
    effective={**plan,'_program':program}
    assert source['source_kind']=='video' and source['video_metadata']['views']==100_000_000
    assert eligible_artifacts(store,mid,program)==[] and runner.eligible_findings(mid,effective)==[]
    coverage=runner.discovery_coverage(mid,effective)
    assert coverage['candidate_domains']==0 and not coverage['satisfied']
    comparison=await compare_artifacts(runner,mid,effective,program)
    assert comparison['artifact_count']==0 and comparison['patterns']==[] and comparison['decision_id'] is None
    runner.jev.ask.assert_not_called()
    store.close()
