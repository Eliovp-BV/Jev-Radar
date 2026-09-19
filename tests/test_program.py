"""Bounded research-program contracts; no live inference or provider traffic."""
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from radar.jev import DecisionError
from radar.program import active_program, build_program, program_fingerprint
from radar.schemas import Criterion, Plan
from radar.storage import Store, dumps, now, uid


def setup_program(tmp_path, **overrides):
    plan = Plan(goal="I'm looking for viral video's and why they went viral", **overrides).model_dump()
    plan['research_mode'] = overrides.get('research_mode', 'adaptive')
    store = Store(tmp_path / 'program-fixture.sqlite')
    mid = uid()
    store.execute('INSERT INTO missions VALUES(?,?,?,?,?,?,?,?,?)',
                  (mid, plan['goal'], 'running', dumps(plan), 1, now(), now(), None, 'fixture'))
    return store, mid, plan


def jev_fixture(**choices):
    selections = {
        'research_unit': 'videos', 'research_method': 'explain_patterns',
        'primary_dimension': 'observed_traction', 'secondary_dimension': 'distribution',
        'discovery_route': 'measured_outcomes',
    } | choices
    decision = {'id': uid(), 'model': 'fixture-model', 'latency_ms': 12.25,
                'answers': {key: {'type': 'choice', 'choice': value} for key, value in selections.items()}}
    class Fixture:
        ask = AsyncMock(return_value=decision)
    return Fixture()


async def test_program_asks_goal_specific_typed_questions_and_persists_provenance(tmp_path):
    store, mid, plan = setup_program(tmp_path, region='France', time_window='past month')
    jev = jev_fixture()
    result = await build_program(jev, store, mid, plan)
    args, kwargs = jev.ask.call_args
    assert args[0] == mid and args[3] == 'Design research approach'
    assert args[1]['goal'] == plan['goal']
    assert args[1]['region'] == 'France' and args[1]['time_window'] == 'past month'
    assert all(question.type == 'choice' for question in args[2].values())
    assert kwargs['cache'] is False
    assert result['unit'] == 'videos' and result['method'] == 'explain_patterns'
    assert {'artifact', 'observed_traction', 'content_features', 'comparison', 'mechanism', 'causal_limits', 'distribution'} == {item['id'] for item in result['criteria']}
    assert all(plan['goal'] in item['question'] for item in result['criteria'])
    assert result['search_queries'][0] == 'viral videos France past month'
    assert 'listicle' not in result['search_queries'][0]
    assert any('actual research objects' in condition for condition in result['stop_conditions'])
    assert any('uninspected footage' in limitation for limitation in result['limitations'])
    assert result['provenance']['latency_ms'] == 12.25
    assert 'templates' in result['provenance']['queries']
    saved = store.records(mid, 'research_program')
    assert saved == [result] and active_program(store, mid) == result
    event = store.events(mid)[-1]
    assert event['type'] == 'research.programmed' and event['mode'] == 'fixture'
    assert event['payload']['record_changes'][0]['record']['decision_id'] == result['decision_id']


async def test_jev_selection_not_keyword_router_drives_program(tmp_path):
    store, mid, plan = setup_program(tmp_path)
    jev = jev_fixture(research_unit='companies', research_method='compare_options',
                      primary_dimension='pricing', secondary_dimension='geography', discovery_route='comparative_cases')
    result = await build_program(jev, store, mid, plan)
    assert 'viral' in plan['goal'] and result['unit'] == 'companies'
    assert {'offering', 'capabilities', 'audience', 'comparison', 'limitations', 'pricing', 'geography'} == {item['id'] for item in result['criteria']}
    assert result['search_queries'][0].endswith('official product')
    assert 'comparison counterexamples' in result['search_queries'][-1]
    assert all('footage' not in item for item in result['limitations'])


async def test_retry_reuses_successful_program_without_another_paid_request(tmp_path):
    store, mid, plan = setup_program(tmp_path)
    jev = jev_fixture()
    first = await build_program(jev, store, mid, plan)
    store.mutate(mid, 'mission.retry', {}, status='running')
    second = await build_program(jev, store, mid, plan)
    assert first == second and jev.ask.await_count == 1
    assert len(store.records(mid, 'research_program')) == 1


async def test_revision_invalidates_protocol_and_preserves_old_record(tmp_path):
    store, mid, plan = setup_program(tmp_path)
    jev = jev_fixture()
    first = await build_program(jev, store, mid, plan)
    plan['region'] = 'Portugal'
    store.execute('UPDATE missions SET plan=?,plan_version=2 WHERE id=?', (dumps(plan), mid))
    assert active_program(store, mid) is None
    second = await build_program(jev, store, mid, plan)
    assert jev.ask.await_count == 2
    assert first['fingerprint'] != second['fingerprint'] and second['plan_version'] == 2
    assert 'Portugal' in second['search_queries'][0]
    assert len(store.records(mid, 'research_program')) == 2
    assert active_program(store, mid) == second


async def test_explicit_custom_criteria_are_preserved_exactly(tmp_path):
    custom = Criterion(id='my_check', label='My check', question='Does the accessible evidence match my own exact question?', rubric='Use only an original signed record.').model_dump()
    store, mid, plan = setup_program(tmp_path, criteria=[custom])
    plan['research_mode'] = 'fixed'
    store.execute('UPDATE missions SET plan=? WHERE id=?', (dumps(plan), mid))
    jev = jev_fixture()
    result = await build_program(jev, store, mid, plan)
    assert result['criteria'] == [custom]
    assert jev.ask.call_args.args[1]['user_criteria'] == [custom]
    assert result['provenance']['criteria'] == 'preserved user criteria'


async def test_failed_inference_cannot_create_a_program(tmp_path):
    store, mid, plan = setup_program(tmp_path)
    jev = jev_fixture()
    jev.ask.side_effect = DecisionError('fixture failure')
    with pytest.raises(DecisionError, match='fixture failure'):
        await build_program(jev, store, mid, plan)
    assert active_program(store, mid) is None
    assert not store.records(mid, 'research_program')
    assert not store.events(mid)


async def test_invalid_typed_selection_cannot_drive_a_program(tmp_path):
    store, mid, plan = setup_program(tmp_path)
    jev = jev_fixture(discovery_route='execute_user_code')
    with pytest.raises(DecisionError, match='invalid typed selection'):
        await build_program(jev, store, mid, plan)
    assert not store.records(mid, 'research_program')


async def test_goal_bound_questions_are_bounded_without_losing_full_goal(tmp_path):
    store, mid, plan = setup_program(tmp_path)
    plan['goal'] = ('Research subtle differences in original video records and their evidence. ' * 35)[:2000]
    plan['queries'] = ['An exact user-supplied query']
    store.execute('UPDATE missions SET plan=? WHERE id=?', (dumps(plan), mid))
    jev = jev_fixture(primary_dimension='pricing', secondary_dimension='distribution')
    result = await build_program(jev, store, mid, plan)
    assert len(result['criteria']) == 8
    for item in result['criteria']:
        assert Criterion.model_validate(item).question.endswith('…')
    assert result['objective'] == jev.ask.call_args.args[1]['goal'] == plan['goal']
    assert result['search_queries'][-1] == plan['queries'][0]
    assert all(len(query) <= 500 for query in result['search_queries'])


@pytest.mark.parametrize('field,value', [
    ('goal', 'A different goal entirely'), ('region', 'France'), ('time_window', 'past week'),
    ('research_mode', 'fixed'), ('criteria', [{'id': 'changed'}]),
    ('providers', ['wikipedia']), ('known_entities', ['Example']), ('reference', 'https://example.com/'),
])
def test_fingerprint_binds_research_inputs(tmp_path, field, value):
    _, _, plan = setup_program(tmp_path)
    modified = deepcopy(plan)
    modified[field] = value
    assert program_fingerprint(plan, 1) != program_fingerprint(modified, 1)
    assert program_fingerprint(plan, 1) != program_fingerprint(plan, 2)
