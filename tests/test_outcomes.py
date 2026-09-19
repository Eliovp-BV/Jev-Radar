"""Outcome copy is derived from evidence, never a substitute for research."""
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from radar.actions import construct
from radar.api import create_app
from radar.config import Settings
from radar.lenses import BUILTINS
from radar.outcomes import mission_outcome, plan_readiness
from radar.reports import opportunities
from radar.research import Runner
from radar.schemas import Plan
from radar.storage import Store, dumps, now, uid


CAPS = {'jev': True, 'brave': False}


def saved_reference_shape():
    """Matches the failed UX scenario without importing or mutating live data."""
    plan = Plan(goal='Find French alternatives to FixtureDesk. Compare public capabilities, positioning, pricing evidence and content.',
                research_mode='fixed', seeds=['https://reference.example/products/fixture-desk'], criteria=BUILTINS[0]['criteria']).model_dump()
    mission = {'id': 'fixture-mission', 'status': 'partial', 'plan': plan, 'plan_version': 1}
    source = {'id': 'reference-source', 'url': plan['seeds'][0], 'title': 'FixtureDesk', 'decision_id': 'source-decision'}
    entity = {'id': 'reference-entity', 'classification': 'reference', 'name': 'reference.example', 'source_ids': [source['id']], 'fields': {}}
    findings = []
    for criterion in plan['criteria']:
        if criterion['id'] == 'pricing':
            entity['fields']['pricing'] = {'status': 'unknown', 'source_id': source['id']}
            continue
        finding = {'id': 'finding-' + criterion['id'], 'entity_id': entity['id'], 'criterion_id': criterion['id'],
                   'subject': 'reference.example', 'question': criterion['question'], 'statement': 'Fixture source assertion.',
                   'status': 'supported', 'evidence_kind': 'company assertion', 'source_ids': [source['id']], 'rubric_version': 1}
        findings.append(finding)
        entity['fields'][criterion['id']] = {'status': 'supported', 'finding_id': finding['id'], 'source_id': source['id']}
    records = {'source': [source], 'finding': findings, 'entity': [entity], 'action': [
        {'id': 'first', 'status': 'complete', 'kind': 'fetch', 'value': plan['seeds'][0]},
        {'id': 'remaining', 'status': 'queued', 'kind': 'fetch', 'value': 'https://reference.example/contact'}]}
    events = [{'type': 'mission.start', 'payload': {}}, {'type': 'action.abstained', 'payload': {'decision_id': 'stop-decision'}},
              {'type': 'mission.finished', 'payload': {'gaps': ['Public pricing']}}, {'type': 'run.segment', 'payload': {'wall_ms': 2500}}]
    return mission, records, events


def test_saved_reference_only_run_has_findings_but_no_alternatives():
    mission, records, events = saved_reference_shape()
    before = deepcopy((mission, records, events))
    outcome = mission_outcome(mission, records, events, CAPS)
    assert outcome['headline'] == 'Reference evidence found; no alternatives identified yet'
    assert outcome['counts']['supported_findings'] == 5
    assert outcome['counts']['pages'] == 1
    assert outcome['counts']['alternative_candidates'] == 0
    assert outcome['stop']['code'] == 'jev_abstained'
    assert outcome['stop']['decision_id'] == 'stop-decision'
    assert outcome['gaps'][0] == {'criterion_id': 'pricing', 'label': 'Public pricing', 'message': 'No current supported answer in the inspected sources.'}
    assert outcome['gaps'][1]['criterion_id'] == 'candidate_discovery'
    assert outcome['next_steps'][0]['kind'] == 'settings'
    assert all(f['source_ids'] == ['reference-source'] for f in outcome['findings'])
    assert (mission, records, events) == before


def test_seed_only_discovery_warning_without_blocking_useful_seed_analysis():
    mission, _, _ = saved_reference_shape()
    readiness = plan_readiness(mission['plan'], CAPS)
    assert readiness['can_start']
    assert readiness['mode'] == 'seed'
    assert readiness['alternatives_requested']
    assert {w['code'] for w in readiness['warnings']} == {'seed_only_discovery', 'general_web_unavailable'}


def test_generic_find_goal_does_not_claim_to_find_company_alternatives():
    mission, records, events = saved_reference_shape()
    mission['plan']['goal'] = 'Find public reference material describing Python as a programming language.'
    outcome = mission_outcome(mission, records, events, CAPS)
    assert outcome['readiness']['discovery_requested']
    assert not outcome['readiness']['alternatives_requested']
    assert outcome['headline'] == '5 supported findings to review'
    assert 'alternative' not in outcome['summary']
    assert all('companies' not in step['detail'] for step in outcome['next_steps'])
    warning = next(w for w in outcome['readiness']['warnings'] if w['code'] == 'seed_only_discovery')
    assert 'companies' not in warning['message']
    assert warning['title'] == 'Discovery is limited to your websites'


def test_generic_comparison_has_no_alternative_company_copy():
    mission, records, events = saved_reference_shape()
    mission['plan']['goal'] = 'Compare Python and Rust public documentation.'
    outcome = mission_outcome(mission, records, events, CAPS)
    assert not outcome['readiness']['alternatives_requested']
    assert not outcome['readiness']['discovery_requested']
    assert 'alternative' not in outcome['summary']
    assert not any(step['label'] == 'Enable wider web discovery' for step in outcome['next_steps'])


def test_supplier_search_is_distinct_from_inspecting_one_vendors_claims():
    find = Plan(goal='Find vendors for managed public hosting.').model_dump()
    inspect = Plan(goal='Inspect this vendor documentation for public pricing.').model_dump()
    assert plan_readiness(find, CAPS)['alternatives_requested']
    assert not plan_readiness(inspect, CAPS)['alternatives_requested']


def test_wikipedia_does_not_promise_company_or_web_discovery():
    plan = Plan(goal='Find useful public research', providers=['wikipedia']).model_dump()
    readiness = plan_readiness(plan, CAPS)
    assert readiness['can_start'] and readiness['mode'] == 'wikipedia'
    assert any(w['code'] == 'encyclopedia_only' for w in readiness['warnings'])
    assert any(w['code'] == 'general_web_unavailable' for w in readiness['warnings'])


def test_general_web_requires_available_selected_provider_and_nonzero_budget():
    plan = Plan(goal='Find French alternatives', providers=['brave']).model_dump()
    assert not plan_readiness(plan, CAPS)['can_start']
    ready = plan_readiness(plan, {**CAPS, 'brave': True})
    assert ready['can_start'] and ready['mode'] == 'general_web'
    plan['limits']['max_queries'] = 0
    unavailable = plan_readiness(plan, {**CAPS, 'brave': True})
    assert not unavailable['can_start']
    assert any(b['code'] == 'discovery_unavailable' for b in unavailable['blockers'])


def test_no_results_explains_failed_action_and_offers_sources():
    mission, _, _ = saved_reference_shape()
    result = mission_outcome(mission, {'action': [{'status': 'failed', 'error': 'Robots disallowed'}]}, [], CAPS)
    assert result['headline'] == 'No evidence collected yet'
    assert result['stop']['code'] == 'actions_failed'
    assert result['counts']['supported_findings'] == 0
    assert result['next_steps'][0]['kind'] == 'settings'


@pytest.mark.parametrize('status,code', [('draft', 'not_started'), ('running', 'running'), ('pausing', 'running'),
                                      ('paused', 'paused'), ('cancelled', 'cancelled'), ('interrupted', 'interrupted')])
def test_lifecycle_does_not_reuse_previous_stop_reason(status, code):
    mission, records, events = saved_reference_shape()
    mission['status'] = status
    if status == 'interrupted':
        events += [{'type': 'mission.retry', 'payload': {}}]
    result = mission_outcome(mission, records, events, CAPS)
    assert result['stop']['code'] == code


def test_new_retry_error_takes_precedence_over_prior_abstention():
    mission, records, events = saved_reference_shape()
    mission['status'] = 'blocked'
    events += [{'type': 'mission.retry', 'payload': {}}, {'type': 'mission.blocked', 'payload': {'reason': 'Call budget reached'}}]
    result = mission_outcome(mission, records, events, CAPS)
    assert result['stop']['code'] == 'blocked'
    assert 'Call budget reached' in result['stop']['message']
    assert any(step['kind']=='inspect_activity' for step in result['next_steps'])


def test_only_current_linked_nonrejected_findings_count_and_steering_preserves_them():
    mission, records, events = saved_reference_shape()
    mission['plan_version'] = 2  # Steering adds a source but does not invalidate past findings.
    records['finding'][0]['stale'] = True
    records['finding'][1]['review'] = 'rejected'
    records['finding'][2]['source_ids'] = ['missing-source']
    result = mission_outcome(mission, records, events, CAPS)
    assert result['counts']['supported_findings'] == 2
    assert result['counts']['historical_findings'] == 1


def test_alternative_candidates_need_classification_and_linked_evidence():
    mission, records, events = saved_reference_shape()
    records['entity'][0]['classification'] = 'alternative'
    result = mission_outcome(mission, records, events, CAPS)
    assert result['counts']['alternative_candidates'] == 1
    assert 'geographic fit still need review' in result['scope']
    records['finding'] = []
    assert mission_outcome(mission, records, events, CAPS)['counts']['alternative_candidates'] == 0


def test_preview_and_detail_add_outcomes_without_inference(tmp_path):
    app = create_app(Settings(data_dir=tmp_path, key='fixture-only-key'))
    with TestClient(app) as client:
        client.headers['x-radar-csrf'] = client.get('/api/session').json()['csrf']
        plan = {'goal': 'Find useful research sources', 'providers': ['wikipedia']}
        preview = client.post('/api/plan', json=plan).json()
        assert preview['readiness']['mode'] == 'wikipedia'
        assert any(a['kind'] == 'search' for a in preview['initial_actions'])  # Single provider works too.
        mission = client.post('/api/missions', json=preview['plan']).json()
        result = client.get('/api/missions/' + mission['id']).json()
        assert result['outcome']['stop']['code'] == 'not_started'
        assert result['telemetry']['attempts'] == 0
        plan['limits'] = {'max_queries': 0}
        mission = client.post('/api/missions', json=plan).json()
        response = client.post('/api/missions/' + mission['id'] + '/command', json={'action': 'start', 'idempotency_key': 'no-query-fixture'})
        assert response.status_code == 422


def store_fixture(tmp_path):
    store = Store(tmp_path / 'fixture.sqlite')
    mission, records, _ = saved_reference_shape()
    mid = uid()
    store.execute('INSERT INTO missions VALUES(?,?,?,?,?,?,?,?,?)', (mid, mission['plan']['goal'], 'running', dumps(mission['plan']), 1, now(), now(), None, 'fixture'))
    store.mutate(mid, 'fixture.seeded', {}, [(kind, r) for kind, items in records.items() for r in items])
    return store, mid


async def test_unchanged_retry_reuses_saved_priority_without_request(tmp_path):
    store, mid = store_fixture(tmp_path)
    runner = Runner(Settings(data_dir=tmp_path, key='fixture-only-key'), store)
    suggestions = construct(store, mid, current=True)
    store.mutate(mid, 'fixture.priority', {}, [
        ('decision', {'id': 'decision-fixture', 'model': runner.settings.model}),
        ('opportunity_priority', {'id': 'priority-fixture', 'selected': suggestions[0]['id'], 'decision_id': 'decision-fixture', 'rubric_version': 1, 'suggestions': suggestions})])
    runner.jev.ask = AsyncMock(side_effect=AssertionError('Unchanged priority must not call Jev'))
    await runner.finish(mid)
    runner.jev.ask.assert_not_called()
    assert store.events(mid)[-2]['type'] == 'opportunity.priority_reused'
    store.close()


async def test_new_stop_reason_is_saved_on_finish(tmp_path):
    store = Store(tmp_path / 'fixture.sqlite')
    plan = Plan(goal='Review public research',research_mode='fixed').model_dump()
    mid = uid()
    store.execute('INSERT INTO missions VALUES(?,?,?,?,?,?,?,?,?)', (mid, plan['goal'], 'running', dumps(plan), 1, now(), now(), None, 'fixture'))
    runner = Runner(Settings(data_dir=tmp_path, key='fixture-only-key'), store)
    runner.jev.ask = AsyncMock(side_effect=AssertionError('Empty queue must not call Jev'))
    await runner.run(mid)
    finished = next(e for e in store.events(mid) if e['type'] == 'mission.finished')
    assert finished['payload']['stop_reason']['code'] == 'no_more_actions'
    assert store.mission(mid)['status'] == 'partial'
    store.close()


def test_missing_jev_uses_workspace_settings_and_steps_are_unique():
    mission, records, events = saved_reference_shape()
    mission['status'] = 'draft'
    result = mission_outcome(mission, records, events, {**CAPS, 'jev': False})
    assert result['readiness']['blockers'][0]['action'] == 'jev_settings'
    assert result['next_steps'][0]['kind'] == 'jev_settings'
    mission['plan']['seeds'] = []
    mission['plan']['goal'] = 'Inspect public reference documentation'
    result = mission_outcome(mission, {}, [], CAPS)
    kinds = [step['kind'] for step in result['next_steps']]
    assert kinds == ['add_sources']
    assert result['next_steps'][0]['label'] == 'Add websites'  # Preserve first recommendation.


@pytest.mark.parametrize('code', ['time_limit', 'configured_limits'])
def test_exhausted_limits_suggest_editing_plan_before_adding_sources(code):
    mission, records, _ = saved_reference_shape()
    events = [{'type': 'mission.finished', 'payload': {'stop_reason': {'code': code, 'message': 'Fixture limit reached'}}}]
    result = mission_outcome(mission, records, events, CAPS)
    assert result['next_steps'][0]['kind'] == 'edit_plan'
    assert result['next_steps'][0]['label'] == 'Review research limits'


@pytest.mark.parametrize('invalid', [None, 'stale', 'rejected'])
async def test_finish_retains_steered_evidence_but_not_superseded_or_rejected(tmp_path, invalid):
    store, mid = store_fixture(tmp_path)
    plan = store.mission(mid)['plan']
    plan['criteria'] = plan['criteria'][:2]
    plan['goal'] = 'Inspect public website evidence'
    store.execute('UPDATE missions SET plan=?,plan_version=2 WHERE id=?', (dumps(plan), mid))
    store.set_setting('action_library', [])  # No priority request in this fixture.
    if invalid:
        finding = store.records(mid, 'finding')[0]
        if invalid == 'stale': finding['stale'] = True
        else: finding['review'] = 'rejected'
        store.mutate(mid, 'fixture.review', {}, [('finding', finding)], mode='fixture')
    before = store.records(mid, 'finding')
    runner = Runner(Settings(data_dir=tmp_path, key='fixture-only-key'), store)
    runner.jev.ask = AsyncMock(side_effect=AssertionError('No inference expected'))
    await runner.finish(mid)
    finished = store.events(mid)[-1]
    assert finished['type'] == 'mission.finished'
    assert finished['payload']['gaps'] == ([] if invalid is None else ['Offering'])
    assert store.mission(mid)['status'] == ('complete' if invalid is None else 'partial')
    assert store.records(mid, 'finding') == before
    store.close()


async def test_run_coverage_uses_retained_evidence_after_steering(tmp_path):
    store, mid = store_fixture(tmp_path)
    plan = store.mission(mid)['plan']
    plan['criteria'] = plan['criteria'][:2]
    plan['goal'] = 'Inspect public website evidence'
    store.execute('UPDATE missions SET plan=?,plan_version=2 WHERE id=?', (dumps(plan), mid))
    store.set_setting('action_library', [])
    for action in store.records(mid, 'action'):
        action['status'] = 'complete'
        store.mutate(mid, 'fixture.completed', {}, [('action', action)], mode='fixture')
    runner = Runner(Settings(data_dir=tmp_path, key='fixture-only-key'), store)
    runner.add_action(mid, 'fetch', 'https://example.net/')
    runner.jev.ask = AsyncMock(side_effect=AssertionError('One prepared action needs no inference'))
    async def simulated_page(mid, action, plan):
        store.mutate(mid, 'fixture.source', {}, [('source', {'id': 'second-source', 'url': action['value']})], mode='fixture')
        runner.add_action(mid, 'fetch', 'https://example.org/')
    runner.do_page = AsyncMock(side_effect=simulated_page)
    before = store.records(mid, 'finding')
    await runner.run(mid)
    assert runner.do_page.await_count == 1
    assert any(e['type'] == 'coverage.satisfied' for e in store.events(mid))
    assert store.mission(mid)['status'] == 'complete'
    assert store.records(mid, 'finding') == before
    store.close()


def test_current_suggestions_and_report_preserve_steered_evidence(tmp_path):
    store, mid = store_fixture(tmp_path)
    before = construct(store, mid, current=True)
    original = store.records(mid, 'finding')
    store.execute('UPDATE missions SET plan_version=2 WHERE id=?', (mid,))
    assert construct(store, mid, current=True) == before
    assert opportunities(store, mid) == before
    finding = store.records(mid, 'finding')[0]
    finding['review'] = 'rejected'
    store.mutate(mid, 'fixture.rejected', {}, [('finding', finding)], mode='fixture')
    revised = construct(store, mid, current=True)
    assert all(finding['id'] not in suggestion['evidence_ids'] for suggestion in revised)
    assert any(s['template_id'] == 'resolve_gap' and 'offering' in s['title'] for s in revised)
    assert {f['id']: f for f in store.records(mid, 'finding') if f['id'] != finding['id']} == {f['id']: f for f in original if f['id'] != finding['id']}
    store.close()
