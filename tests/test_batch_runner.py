"""Independent collection scheduling with explicit fake inference and acquisition."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from radar.config import Settings
from radar.jev import BudgetError, DecisionError
from radar.research import Runner
from radar.schemas import Plan
from radar.storage import Store, dumps, now, uid
from typesafe_sdk import Noul


def setup_runner(tmp_path, *, tokens=250000, calls=60, pages=12, per_domain=6, unit='articles'):
    store=Store(tmp_path/'batch.sqlite')
    plan=Plan(goal='Fixture only: compare original observed publications',
              criteria=[{'id':'identity','label':'Identity','question':'Which original publication is observed?'}],
              limits={'max_tokens':tokens,'max_calls':calls,'max_pages':pages,'per_domain':per_domain}).model_dump()
    mid=uid()
    store.execute('INSERT INTO missions VALUES(?,?,?,?,?,?,?,?,?)',(mid,plan['goal'],'running',dumps(plan),1,now(),now(),None,'fixture'))
    runner=Runner(Settings(data_dir=tmp_path,key='fixture-only'),store)
    runner.text=SimpleNamespace(enabled=False)
    program={'id':'program','unit':unit,'criteria':plan['criteria']}
    effective={**plan,'_program':program}
    runner.effective_plan=lambda _:effective
    return runner,mid,effective


def add_candidates(runner,mid,urls=None,kind='fetch'):
    for url in urls or ['https://one.example/original','https://two.example/original','https://three.example/original']:
        runner.add_action(mid,kind,url)
    return runner.store.records(mid,'action')


def install_choice(runner, choices=None, after=None):
    requests=[]
    async def ask(mid,state,questions,purpose,**kwargs):
        requests.append({'state':state,'questions':questions,'purpose':purpose})
        decision={'id':uid(),'answers':{key:{'choice':(choices or {}).get(key,'inspect')} for key in questions}}
        if after:after(mid)
        return decision
    runner.jev.ask=ask
    return requests


async def test_default_budget_groups_records_in_one_request_and_overlaps_acquisition(tmp_path):
    runner,mid,p=setup_runner(tmp_path)
    candidates=add_candidates(runner,mid)
    requests=install_choice(runner)
    entered=0;peak=0;active=0;both=asyncio.Event()
    async def page(mid,action,p):
        nonlocal entered,active,peak
        entered+=1;active+=1;peak=max(peak,active)
        if entered==3:both.set()
        await asyncio.wait_for(both.wait(),1)
        active-=1
    runner.do_page=page
    count=await runner.assess_collection(mid,p,candidates,[],[],set())
    assert count==3 and peak==3 and len(requests)==1
    assert len(requests[0]['questions'])==3
    assert all(set(q.criteria)=={'inspect','defer'} for q in requests[0]['questions'].values())
    actions=runner.store.records(mid,'action')
    assert sum(a['status']=='complete' for a in actions)==3
    assert sum(a['status']=='queued' for a in actions)==0
    assert all(a.get('decision_id') for a in actions if a['status']=='complete')
    assert any(e['type']=='collection.finished' and e['payload']['wall_ms']>=0 for e in runner.store.events(mid))


async def test_three_is_a_hard_concurrency_bound_when_budget_allows(tmp_path):
    runner,mid,p=setup_runner(tmp_path,tokens=1000000)
    candidates=add_candidates(runner,mid,[f'https://source{i}.example/item' for i in range(8)])
    requests=install_choice(runner)
    runner.do_page=AsyncMock()
    assert await runner.assess_collection(mid,p,candidates,[],[],set())==3
    assert len(requests[0]['questions'])==3
    assert runner.do_page.await_count==3


async def test_declined_items_are_not_fetched_or_turned_into_synthetic_decisions(tmp_path):
    runner,mid,p=setup_runner(tmp_path)
    candidates=add_candidates(runner,mid)
    requests=install_choice(runner,{a['id']:'defer' for a in candidates})
    runner.do_page=AsyncMock();deferred=set()
    assert await runner.assess_collection(mid,p,candidates,[],[],deferred)==0
    assert deferred=={a['id'] for a in candidates}
    assert len(requests)==1 and runner.do_page.await_count==0
    assert all(a['status']=='queued' for a in runner.store.records(mid,'action'))


@pytest.mark.parametrize('change',[{'max_calls':5},{'max_tokens':10000},{'usd':.001}])
async def test_insufficient_collection_allowance_uses_serial_fallback_without_paid_selection(tmp_path,change):
    runner,mid,p=setup_runner(tmp_path)
    p['limits'].update(change)
    candidates=add_candidates(runner,mid)
    requests=install_choice(runner)
    assert await runner.assess_collection(mid,p,candidates,[],[],set()) is None
    assert requests==[]


def test_page_domain_identity_and_shared_entity_admission(tmp_path):
    runner,mid,p=setup_runner(tmp_path,pages=2,per_domain=1)
    candidates=add_candidates(runner,mid,['https://one.example/a','https://one.example/b','https://two.example/c','https://three.example/d'])
    chosen=runner.collection_candidates(mid,p,candidates,[],[])
    assert [a['value'] for a in chosen]==['https://one.example/a','https://two.example/c']
    assert len(runner.collection_candidates(mid,p,candidates,[{'id':'existing','url':'https://four.example/z'}],[]))==1
    p['limits'].update(max_pages=12,per_domain=6)
    p['_program']['unit']='companies'
    assert len([a for a in runner.collection_candidates(mid,p,candidates,[],[]) if 'one.example' in a['value']])==1


async def test_pause_after_selection_preserves_decision_without_adopting_old_choices(tmp_path):
    runner,mid,p=setup_runner(tmp_path)
    candidates=add_candidates(runner,mid)
    install_choice(runner,after=lambda mid:runner.store.mutate(mid,'fixture.pause',{},status='pausing'))
    runner.do_page=AsyncMock()
    assert await runner.assess_collection(mid,p,candidates,[],[],set())==0
    assert runner.do_page.await_count==0
    assert not any(a.get('decision_id') for a in runner.store.records(mid,'action'))
    assert any(e['type']=='collection.selection_deferred' for e in runner.store.events(mid))
    assert all(a['status']=='queued' for a in runner.store.records(mid,'action'))


async def test_plan_revision_during_selection_does_not_reuse_old_approval(tmp_path):
    runner,mid,p=setup_runner(tmp_path)
    candidates=add_candidates(runner,mid)
    install_choice(runner,after=lambda mid:runner.store.execute('UPDATE missions SET plan_version=2 WHERE id=?',(mid,)))
    runner.do_page=AsyncMock()
    assert await runner.assess_collection(mid,p,candidates,[],[],set())==0
    assert runner.do_page.await_count==0
    assert not any(a.get('decision_id') for a in runner.store.records(mid,'action'))


async def test_batch_cancel_marks_each_inflight_action_uncertain(tmp_path):
    runner,mid,p=setup_runner(tmp_path)
    candidates=add_candidates(runner,mid)
    install_choice(runner)
    entered=0;both=asyncio.Event();never=asyncio.Event()
    async def page(mid,action,p):
        nonlocal entered
        entered+=1
        if entered==2:both.set()
        await never.wait()
    runner.do_page=page
    task=asyncio.create_task(runner.assess_collection(mid,p,candidates,[],[],set()))
    await asyncio.wait_for(both.wait(),1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    assert [a['status'] for a in runner.store.records(mid,'action')].count('uncertain')==3
    assert not any(a['status']=='running' for a in runner.store.records(mid,'action'))
    assert mid not in runner.jev.headroom


@pytest.mark.parametrize('error',[BudgetError('fixture budget'),DecisionError('fixture provider')])
async def test_failure_retains_completed_independent_work_and_propagates(tmp_path,error):
    runner,mid,p=setup_runner(tmp_path)
    candidates=add_candidates(runner,mid)
    install_choice(runner)
    async def page(mid,action,p):
        if action['id']==candidates[0]['id']:raise error
    runner.do_page=page
    with pytest.raises(type(error)):
        await runner.assess_collection(mid,p,candidates,[],[],set())
    actions={a['id']:a for a in runner.store.records(mid,'action')}
    assert actions[candidates[1]['id']]['status']=='complete'
    assert actions[candidates[0]['id']]['status']==('queued' if isinstance(error,BudgetError) else 'uncertain')


async def test_redirects_to_shared_company_host_serialize_actual_entity_merges(tmp_path):
    runner,mid,p=setup_runner(tmp_path,unit='companies')
    active=0;peak=0;completed=[]
    async def analysis(mid,source,chunks,p):
        nonlocal active,peak
        active+=1;peak=max(peak,active)
        previous=list(completed)
        await asyncio.sleep(.005)
        completed[:]=previous+[source['id']]
        active-=1
    runner._analyze=analysis
    await asyncio.gather(runner.analyze(mid,{'id':'a','url':'https://actual.example/a'},[],p),
                         runner.analyze(mid,{'id':'b','url':'https://actual.example/b'},[],p))
    assert peak==1 and completed==['a','b']


def test_atomic_paid_reservations_remain_authoritative_under_parallel_selection(tmp_path):
    runner,mid,p=setup_runner(tmp_path,calls=1)
    runner.jev.reserve(mid,100,.001)
    with pytest.raises(BudgetError):runner.jev.reserve(mid,100,.001)
    assert runner.store.one('SELECT COUNT(*) n FROM reservations WHERE mission_id=?',(mid,))['n']==1


async def test_default_allowance_still_batches_after_thirty_thousand_recorded_tokens(tmp_path):
    runner,mid,p=setup_runner(tmp_path)
    runner.jev.reserve(mid,30000,.001)
    candidates=add_candidates(runner,mid)
    requests=install_choice(runner)
    async def page(mid,action,p):
        assert runner.jev.headroom[mid]['tokens']==16000
        runner.jev.reserve(mid,12000,.001)
    runner.do_page=page
    assert await runner.assess_collection(mid,p,candidates,[],[],set())==3
    assert len(requests)==1 and not runner.jev.headroom
    row=runner.store.one('SELECT COUNT(*) n,SUM(reserved_tokens) tokens FROM reservations WHERE mission_id=?',(mid,))
    assert row=={'n':4,'tokens':66000}


async def test_actual_payload_cannot_consume_protected_headroom_before_provider_call(tmp_path,monkeypatch):
    runner,mid,p=setup_runner(tmp_path,tokens=30000)
    client=Mock(side_effect=AssertionError('Provider must never be constructed'))
    monkeypatch.setattr(runner.jev,'client',client)
    with runner.jev.protect_budget(mid,calls=2,tokens=16000,usd=.001):
        with pytest.raises(BudgetError,match='protected'):
            await runner.jev.ask(mid,{'actual_public_passage':'x'*15000},
                                 {'observed':Noul(instructions='Does the supplied public passage establish this observation?')},
                                 'Fixture actual payload budget check',cache=False)
    client.assert_not_called()
    assert not runner.jev.headroom
    assert runner.store.one('SELECT COUNT(*) n FROM reservations WHERE mission_id=?',(mid,))['n']==0


@pytest.mark.parametrize('protected,reservation',[
    ({'calls':60,'tokens':0,'usd':0},(1,0)),
    ({'calls':0,'tokens':240000,'usd':0},(11000,0)),
    ({'calls':0,'tokens':0,'usd':4.9},(1,.2)),
])
def test_each_protected_limit_is_atomic_and_release_retains_existing_usage(tmp_path,protected,reservation):
    runner,mid,p=setup_runner(tmp_path)
    with runner.jev.protect_budget(mid,**protected):
        with pytest.raises(BudgetError,match='protected'):runner.jev.reserve(mid,*reservation)
    first=runner.jev.reserve(mid,*reservation)
    assert first and not runner.jev.headroom
    with runner.jev.protect_budget(mid,calls=0,tokens=0,usd=0):pass
    assert runner.store.one('SELECT COUNT(*) n FROM reservations WHERE mission_id=?',(mid,))['n']==1


def test_protected_allowance_is_local_to_its_investigation(tmp_path):
    runner,mid,p=setup_runner(tmp_path)
    other=uid();plan=runner.store.mission(mid)['plan']
    runner.store.execute('INSERT INTO missions VALUES(?,?,?,?,?,?,?,?,?)',(other,plan['goal'],'running',dumps(plan),1,now(),now(),None,'fixture'))
    with runner.jev.protect_budget(mid,calls=60,tokens=250000,usd=5):
        assert runner.jev.reserve(other,100,.001)
        with pytest.raises(BudgetError):runner.jev.reserve(mid,100,.001)
    assert not runner.jev.headroom


@pytest.mark.parametrize('state_change',['revision','pause'])
async def test_stale_defer_all_does_not_contaminate_fresh_loop_or_trigger_abstention(tmp_path,state_change):
    runner,mid,p=setup_runner(tmp_path)
    candidates=add_candidates(runner,mid)
    def change(mid):
        if state_change=='revision':runner.store.execute('UPDATE missions SET plan_version=2 WHERE id=?',(mid,))
        else:runner.store.mutate(mid,'fixture.pause',{},status='pausing')
    install_choice(runner,{a['id']:'defer' for a in candidates},after=change)
    deferred={'previous-unrelated-action'}
    assert await runner.assess_collection(mid,p,candidates,[],[],deferred)==0
    assert deferred=={'previous-unrelated-action'}
    assert not any(e['type'] in ('action.abstained','collection.selected') for e in runner.store.events(mid))
