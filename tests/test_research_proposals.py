"""Explicit generation/decision fixtures; these test orchestration, not quality."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from copy import deepcopy

import pytest

from radar.config import Settings
from radar.program import active_program, build_program, program_fingerprint
from radar.research import Runner
from radar.research_proposals import propose_followup, personalize_program, _followup_state, FollowupOutcome, DiscoveryQuery
from radar.storage import uid, dumps, now
from radar.text_model import TextModelError
from radar.jev import BudgetError
from test_program import setup_program, jev_fixture


def text_fixture(output):
    return SimpleNamespace(enabled=True, config=lambda: {'provider': 'openai', 'model': 'fixture-text'},
        generate=AsyncMock(return_value={'id': uid(), 'output': output, 'provider': 'openai', 'model': 'fixture-text', 'latency_ms': 0}))


def proposal():
    return {'questions': [{'label': 'Measured growth', 'question': 'What view observations exist at two known dates for each original video?'},
                          {'label': 'Irrelevant', 'question': 'What unrelated celebrity gossip was reported?'}],
            'queries': [{'query': 'original creator video dated audience observations', 'purpose': 'Find repeated primary observations', 'search_kind': 'video'},
                        {'query': 'how to claim a video is viral', 'purpose': 'A deliberately rejected how-to lead', 'search_kind': 'web_leads'}]}


def planner():
    base = jev_fixture()
    design = base.ask.return_value
    approval = {'id': uid(), 'answers': {key: {'choice': value} for key, value in
                 {'question_0': 'accept', 'question_1': 'reject', 'query_0': 'accept', 'query_1': 'reject'}.items()}}
    base.ask.side_effect = [design, approval]
    return base


async def test_text_proposals_only_enter_protocol_when_jev_accepts(tmp_path):
    store, mid, plan = setup_program(tmp_path)
    jev, text = planner(), text_fixture(proposal())
    result = await build_program(jev, store, mid, plan, text)
    assert result['search_queries'] == ['original creator video dated audience observations']
    assert result['query_routes'][result['search_queries'][0]] == 'video'
    assert {'artifact', 'observed_traction', 'content_features', 'research_1'} <= {q['id'] for q in result['criteria']}
    assert not any(q['label'] == 'Irrelevant' for q in result['criteria'])
    assert result['approval_decision_id']
    assert result['text_call_id'] and result['compiler']['model'] == 'fixture-text'
    assert jev.ask.call_args_list[-1].args[3] == 'Approve goal-specific research questions'
    assert active_program(store, mid) == result
    assert await build_program(jev, store, mid, plan, text) == result
    assert text.generate.await_count == 1 and jev.ask.await_count == 2


async def test_configuring_text_model_does_not_reuse_template_program(tmp_path):
    store, mid, plan = setup_program(tmp_path)
    first = await build_program(jev_fixture(), store, mid, plan)
    result = await build_program(planner(), store, mid, plan, text_fixture(proposal()))
    assert first['id'] != result['id'] and first['fingerprint'] != result['fingerprint']
    assert active_program(store, mid) == result


async def test_invalid_generation_preserves_explicit_template_fallback(tmp_path):
    store, mid, plan = setup_program(tmp_path)
    text = text_fixture({'questions': [], 'queries': [], 'execute': 'arbitrary command'})
    result = await build_program(jev_fixture(), store, mid, plan, text)
    assert result['text_planning_unavailable']
    assert not result.get('approval_decision_id')
    assert any(event['type'] == 'research.proposal_unavailable' for event in store.events(mid))


async def followup_runner(tmp_path, selection='followup_0'):
    store, mid, plan = setup_program(tmp_path, providers=['seed', 'brave'])
    runner = Runner(Settings(data_dir=tmp_path, key='fixture', brave_key='fixture'), store)
    runner.jev = jev_fixture()
    await build_program(runner.jev, store, mid, plan)
    runner.jev.ask = AsyncMock(return_value={'id': uid(), 'answers': {'followup': {'choice': selection}}})
    runner.text = text_fixture({'queries': [{'query': 'matched less viewed original videos same creator',
        'purpose': 'Find a counterexample to the proposed format explanation', 'search_kind': 'video'}],
        'gap': 'The current cases do not include a matched lower-reception comparison.'})
    return runner, mid


async def test_followup_queues_only_selected_query_and_does_not_rebill_same_state(tmp_path):
    runner, mid = await followup_runner(tmp_path)
    plan = runner.effective_plan(mid)
    assert await propose_followup(runner, mid, plan, 'challenge_before_conclusion')
    action = runner.store.records(mid, 'action')[-1]
    assert action['kind'] == 'search' and action['discovery_refinement'] and action['decision_id']
    assert action['search_kind'] == 'video' and action['followup_id']
    assert runner.jev.ask.call_args.args[3] == 'Choose evidence-driven follow-up'
    # Updated state includes the queued query, so a second call can propose a
    # different round; its duplicate query is rejected before another Jev call.
    assert not await propose_followup(runner, mid, plan, 'challenge_before_conclusion')
    assert not await propose_followup(runner, mid, plan, 'challenge_before_conclusion')
    assert runner.text.generate.await_count == 2
    assert runner.jev.ask.await_count == 1


async def test_jev_declined_followup_never_queues_and_same_checkpoint_is_cached(tmp_path):
    runner, mid = await followup_runner(tmp_path, 'stop')
    plan = runner.effective_plan(mid)
    assert not await propose_followup(runner, mid, plan)
    assert not runner.store.records(mid, 'action')
    assert not await propose_followup(runner, mid, plan)
    assert runner.text.generate.await_count == 1


async def test_text_failure_retains_record_and_no_generated_search(tmp_path):
    runner, mid = await followup_runner(tmp_path)
    runner.text.generate.side_effect = TextModelError('Explicit fixture provider failure')
    assert not await propose_followup(runner, mid, runner.effective_plan(mid))
    assert not runner.store.records(mid, 'action')
    assert runner.store.records(mid, 'research_followup')[-1]['status'] == 'unavailable'


async def test_verification_retry_reuses_generated_followup_without_writer_rebilling(tmp_path):
    runner, mid = await followup_runner(tmp_path)
    plan = runner.effective_plan(mid)
    result = runner.jev.ask.return_value
    runner.jev.ask.side_effect = BudgetError('Fixture allowance exhausted')
    assert not await propose_followup(runner, mid, plan)
    runner.jev.ask.side_effect = None
    runner.jev.ask.return_value = result
    assert await propose_followup(runner, mid, plan, 'queue_exhausted')
    assert len(runner.store.records(mid, 'research_followup')) == 1
    assert runner.text.generate.await_count == 1


async def test_search_allowance_prevents_followup_inference(tmp_path):
    runner, mid = await followup_runner(tmp_path)
    plan = runner.effective_plan(mid)
    plan['limits']['max_queries'] = 0
    assert not await runner.refine_discovery(mid, plan)
    runner.text.generate.assert_not_awaited()


async def test_generated_video_web_queries_become_leads_and_initial_search_reserves_room(tmp_path):
    store, mid, plan = setup_program(tmp_path, providers=['brave'])
    output = proposal()
    output['queries'][0]['search_kind'] = 'web'
    result = await build_program(planner(), store, mid, plan, text_fixture(output))
    runner = Runner(Settings(data_dir=tmp_path, key='fixture', brave_key='fixture'), store)
    runner.text = text_fixture(output)
    runner.initialize(mid)
    actions = store.records(mid, 'action')
    assert len(actions) == 1 and actions[0]['search_kind'] == 'web_leads'
    assert result['query_routes'][actions[0]['value']] == 'web_leads'


async def test_runner_executes_generated_followup_before_finishing(tmp_path, monkeypatch):
    # Real runner queue + routing + selection, synthetic acquisition and models.
    runner, mid = await followup_runner(tmp_path)
    runner.initialize = lambda _: None
    executed = []
    async def search(mid, action, plan):
        executed.append(action['value'])
        runner.store.mutate(mid, 'search.started', {}, [('search_attempt', {'id': uid(), 'status': 'complete'})])
    runner.do_search = search
    runner.finish = AsyncMock()
    # The already compiled program has no text compiler identity. Avoid a second
    # planning decision in this isolated run-loop test; proposal behavior is above.
    import radar.research as module
    monkeypatch.setattr(module, 'build_program', AsyncMock())
    await runner.run(mid)
    assert executed == ['matched less viewed original videos same creator']
    assert runner.store.records(mid, 'action')[-1]['status'] == 'complete'
    runner.finish.assert_awaited_once()


def add_evidence(runner, mid):
    program = runner.effective_plan(mid)['_program']
    text = 'PUBLIC_EVIDENCE: a documented original video record.'
    source = {'id': 'source', 'entity_id': 'entity', 'url': 'https://www.youtube.com/watch?v=fixture1234',
              'title': 'Public original record', 'text': text, 'source_kind': 'video', 'unit_id': 'original',
              'retrieved_at': now(), 'research_role': 'primary_artifact'}
    entity = {'id': 'entity', 'name': 'Public creator', 'domains': ['youtube.com'], 'source_ids': ['source']}
    span = {'id': 'span', 'source_id': 'source', 'start': 0, 'end': len(text), 'text': text}
    finding = {'id': 'finding', 'entity_id': 'entity', 'source_ids': ['source'], 'span_ids': ['span'],
               'status': 'supported', 'criterion_id': program['criteria'][0]['id'], 'program_id': program['id'],
               'question': program['criteria'][0]['question'], 'subject': source['title']}
    assessment = {'id': 'assessment', 'source_id': 'source', 'program_id': program['id'], 'plan_version': 1,
                  'role': 'primary_artifact', 'relevance': 1}
    runner.store.mutate(mid, 'fixture.evidence', {}, [('source', source), ('entity', entity), ('span', span),
                       ('finding', finding), ('artifact_analysis', assessment)])


def change_record(runner, mid, kind, record_id, **updates):
    value = next(item for item in runner.store.records(mid, kind) if item['id'] == record_id)
    value.update(updates)
    runner.store.mutate(mid, 'fixture.changed', {}, [(kind, value)])


@pytest.mark.parametrize('kind,record_id,updates', [
    ('source', 'source', {'private': True}), ('source', 'source', {'stale': True}),
    ('source', 'source', {'excluded': True}), ('source', 'source', {'review': 'rejected'}),
    ('entity', 'entity', {'private': True}), ('entity', 'entity', {'review': 'rejected'}),
    ('span', 'span', {'private': True}), ('span', 'span', {'stale': True}),
    ('span', 'span', {'text': 'fabricated quotation'}), ('span', 'span', {'start': True}),
    ('finding', 'finding', {'stale': True}), ('finding', 'finding', {'private': True}),
    ('artifact_analysis', 'assessment', {'role': 'secondary_commentary'}),
])
async def test_followup_uses_only_current_exact_public_primary_evidence(tmp_path, kind, record_id, updates):
    runner, mid = await followup_runner(tmp_path)
    add_evidence(runner, mid)
    change_record(runner, mid, kind, record_id, **updates)
    state = _followup_state(runner, mid, runner.effective_plan(mid), 'fixture')
    assert state['observed_evidence'] == []
    if kind == 'artifact_analysis':
        assert state['source_roles'][0]['role'] == 'secondary_commentary'
        assert state['source_roles'][0]['basis'] == 'inspected context; no primary finding'
    else:
        assert state['source_roles'] == []
    assert state['missing_questions'][0]['id'] == 'artifact'
    assert 'PUBLIC_EVIDENCE' not in dumps(state)


async def test_private_entities_and_excluded_domains_cannot_reenter_through_search_results(tmp_path):
    runner, mid = await followup_runner(tmp_path)
    add_evidence(runner, mid)
    change_record(runner, mid, 'entity', 'entity', private=True)
    runner.store.mutate(mid, 'fixture.search', {}, [('search', {'id': 'search', 'results': [
        {'url': 'https://www.youtube.com/watch?v=fixture1234', 'title': 'PRIVATE_SUBJECT', 'snippet': 'PRIVATE_SUBJECT'},
        {'url': 'https://excluded.example/page', 'title': 'EXCLUDED_SUBJECT', 'snippet': 'EXCLUDED_SUBJECT'}]})])
    plan = runner.effective_plan(mid)
    plan['excluded_domains'] = ['excluded.example']
    state = _followup_state(runner, mid, plan, 'fixture')
    assert state['recent_results'] == []
    assert 'PRIVATE_SUBJECT' not in dumps(state) and 'EXCLUDED_SUBJECT' not in dumps(state)


@pytest.mark.parametrize('boundary', ['writer', 'jev'])
async def test_pause_stops_follow_on_inference_and_resume_reuses_paid_work(tmp_path, boundary):
    runner, mid = await followup_runner(tmp_path)
    response = runner.text.generate.return_value if boundary == 'writer' else runner.jev.ask.return_value
    async def pause(*args, **kwargs):
        runner.store.mutate(mid, 'fixture.pause', {}, status='pausing')
        return response
    selected_mock = runner.text.generate if boundary == 'writer' else runner.jev.ask
    selected_mock.side_effect = pause
    plan = runner.effective_plan(mid)
    assert not await propose_followup(runner, mid, plan)
    assert not runner.store.records(mid, 'action')
    assert runner.jev.ask.await_count == (0 if boundary == 'writer' else 1)
    assert runner.store.records(mid, 'research_followup')[-1]['status'] == 'deferred'
    selected_mock.side_effect = None
    runner.store.mutate(mid, 'fixture.resume', {}, status='running')
    assert await propose_followup(runner, mid, plan)
    assert runner.text.generate.await_count == 1 and runner.jev.ask.await_count == 1


@pytest.mark.parametrize('boundary,change', [('writer', 'review'), ('jev', 'review'), ('writer', 'scope'), ('jev', 'scope')])
async def test_inflight_scope_or_review_change_prevents_followup_adoption(tmp_path, boundary, change):
    runner, mid = await followup_runner(tmp_path)
    add_evidence(runner, mid)
    response = runner.text.generate.return_value if boundary == 'writer' else runner.jev.ask.return_value
    async def changed(*args, **kwargs):
        if change == 'review':
            change_record(runner, mid, 'source', 'source', review='rejected')
        else:
            runner.store.execute('UPDATE missions SET plan_version=2 WHERE id=?', (mid,))
        return response
    (runner.text.generate if boundary == 'writer' else runner.jev.ask).side_effect = changed
    assert not await propose_followup(runner, mid, runner.effective_plan(mid))
    assert not runner.store.records(mid, 'action')
    assert runner.jev.ask.await_count == (0 if boundary == 'writer' else 1)


@pytest.mark.parametrize('status', ['paused', 'pausing', 'cancelled', 'partial'])
async def test_followup_does_not_start_for_inactive_run(tmp_path, status):
    runner, mid = await followup_runner(tmp_path)
    runner.store.mutate(mid, 'fixture.status', {}, status=status)
    assert not await propose_followup(runner, mid, runner.effective_plan(mid))
    runner.text.generate.assert_not_called()
    runner.jev.ask.assert_not_called()


async def test_custom_questions_preserve_selected_dimensions_and_causal_comparison_rules(tmp_path):
    store, mid, plan = setup_program(tmp_path)
    jev = jev_fixture(primary_dimension='pricing', secondary_dimension='geography')
    design = jev.ask.return_value
    async def choose(mid, state, questions, purpose, **kwargs):
        if purpose == 'Design research approach':
            return design
        return {'id': uid(), 'answers': {key: {'choice': 'accept'} for key in questions}}
    jev.ask.side_effect = choose
    output = proposal()
    output['questions'] = [{'label': f'Specific question {i}', 'question': f'What documented measurement answers specific user question {i}?'} for i in range(4)]
    result = await build_program(jev, store, mid, plan, text_fixture(output))
    protected = {'artifact', 'observed_traction', 'content_features', 'comparison', 'causal_limits', 'pricing', 'geography'}
    assert protected <= {item['id'] for item in result['criteria']}
    assert len(result['criteria']) == 8
    assert result['accepted_question_count'] == 4 and result['adopted_question_count'] == 1
    assert result['approved_questions_omitted'] == 3
    assert '3 approved questions omitted' in result['provenance']['criteria']


@pytest.mark.parametrize('boundary', ['writer', 'jev'])
async def test_personalization_does_not_adopt_after_pause(tmp_path, boundary):
    store, mid, plan = setup_program(tmp_path)
    base = await build_program(jev_fixture(), store, mid, plan)
    program = deepcopy(base)
    program['compiler'] = {'provider': 'openai', 'model': 'fixture-text', 'version': 1}
    program['fingerprint'] = program_fingerprint(plan, 1, program['compiler'])
    text = text_fixture(proposal())
    jev = SimpleNamespace(ask=AsyncMock(return_value={'id': uid(), 'answers': {
        'question_0': {'choice': 'accept'}, 'question_1': {'choice': 'reject'},
        'query_0': {'choice': 'accept'}, 'query_1': {'choice': 'reject'}}}))
    response = text.generate.return_value if boundary == 'writer' else jev.ask.return_value
    async def pause(*args, **kwargs):
        store.mutate(mid, 'fixture.pause', {}, status='pausing')
        return response
    (text.generate if boundary == 'writer' else jev.ask).side_effect = pause
    assert not await personalize_program(jev, text, store, mid, plan, program)
    assert program['status'] == 'pending'
    assert program['criteria'] == base['criteria'] and program['search_queries'] == base['search_queries']
    assert jev.ask.await_count == (0 if boundary == 'writer' else 1)


async def test_proposal_cache_is_bound_to_actual_protocol_selections(tmp_path):
    store, mid, plan = setup_program(tmp_path)
    base = await build_program(jev_fixture(), store, mid, plan)
    compiler = {'provider': 'openai', 'model': 'fixture-text', 'version': 1}
    base.update(compiler=compiler, fingerprint=program_fingerprint(plan, 1, compiler))
    first, second = deepcopy(base), deepcopy(base)
    second['unit'] = 'companies'
    second['method'] = 'compare_options'
    text = text_fixture(proposal())
    async def choose(mid, state, questions, purpose, **kwargs):
        return {'id': uid(), 'answers': {key: {'choice': 'accept'} for key in questions}}
    jev = SimpleNamespace(ask=AsyncMock(side_effect=choose))
    await personalize_program(jev, text, store, mid, plan, first)
    await personalize_program(jev, text, store, mid, plan, second)
    assert text.generate.await_count == 2
    assert first['proposal_id'] != second['proposal_id']


def add_context(runner, mid, suffix='one', **updates):
    program = runner.effective_plan(mid)['_program']
    source = {'id': 'context_' + suffix, 'url': 'https://context.example/' + suffix,
              'title': 'Observed commentary ' + suffix, 'text': 'CONTEXT_BODY_MUST_NOT_BECOME_EVIDENCE',
              'program_id': program['id'], 'research_role': 'secondary_commentary', **updates}
    assessment = {'id': 'context_assessment_' + suffix, 'source_id': source['id'],
                  'program_id': program['id'], 'plan_version': program['plan_version'],
                  'role': 'secondary_commentary', 'relevance': .5}
    runner.store.mutate(mid, 'fixture.context', {}, [('source', source), ('artifact_analysis', assessment)])
    return source, assessment


async def test_negative_discovery_reaches_followup_without_creating_evidence(tmp_path):
    runner, mid = await followup_runner(tmp_path, 'stop')
    add_context(runner, mid)
    assert await propose_followup(runner, mid, runner.effective_plan(mid)) is FollowupOutcome.DECLINED
    first = runner.text.generate.call_args.kwargs['state']
    assert first['source_roles'][0]['role'] == 'secondary_commentary'
    assert first['observed_evidence'] == []
    assert 'CONTEXT_BODY_MUST_NOT_BECOME_EVIDENCE' not in dumps(first)
    add_context(runner, mid, 'two')
    assert await propose_followup(runner, mid, runner.effective_plan(mid)) is FollowupOutcome.DECLINED
    assert runner.text.generate.await_count == 2
    assert len(runner.text.generate.call_args.kwargs['state']['source_roles']) == 2
    assert not runner.store.records(mid, 'finding')


@pytest.mark.parametrize('target,updates', [
    ('source', {'private': True}), ('source', {'review': 'rejected'}),
    ('source', {'stale': True}), ('source', {'excluded': True}),
    ('assessment', {'private': True}), ('assessment', {'stale': True}),
    ('assessment', {'review': 'rejected'}), ('assessment', {'program_id': 'old-program'}),
    ('assessment', {'plan_version': 0}),
])
async def test_negative_context_obeys_source_and_assessment_privacy(tmp_path, target, updates):
    runner, mid = await followup_runner(tmp_path)
    source, assessment = add_context(runner, mid)
    kind, item = ('source', source) if target == 'source' else ('artifact_analysis', assessment)
    change_record(runner, mid, kind, item['id'], **updates)
    state = _followup_state(runner, mid, runner.effective_plan(mid), 'fixture')
    assert state['source_roles'] == []
    assert 'Observed commentary' not in dumps(state)


@pytest.mark.parametrize('exclusion', ['domain', 'entity_name', 'private_entity'])
async def test_negative_context_obeys_entity_and_domain_exclusions(tmp_path, exclusion):
    runner, mid = await followup_runner(tmp_path)
    source, _ = add_context(runner, mid)
    entity = {'id': 'context_entity', 'name': 'Excluded subject', 'domains': ['context.example'],
              'source_ids': [source['id']]}
    if exclusion == 'private_entity':
        entity['private'] = True
    runner.store.mutate(mid, 'fixture.entity', {}, [('entity', entity)])
    plan = runner.effective_plan(mid)
    if exclusion == 'domain':
        plan['excluded_domains'] = ['context.example']
    elif exclusion == 'entity_name':
        plan['excluded_entities'] = ['Excluded subject']
    assert _followup_state(runner, mid, plan, 'fixture')['source_roles'] == []


@pytest.mark.parametrize('boundary', ['writer', 'jev'])
async def test_negative_context_review_during_inference_defers_adoption(tmp_path, boundary):
    runner, mid = await followup_runner(tmp_path)
    source, _ = add_context(runner, mid)
    model = runner.text.generate if boundary == 'writer' else runner.jev.ask
    response = model.return_value
    async def reject(*args, **kwargs):
        change_record(runner, mid, 'source', source['id'], review='rejected')
        return response
    model.side_effect = reject
    assert await propose_followup(runner, mid, runner.effective_plan(mid)) is FollowupOutcome.DEFERRED
    assert not runner.store.records(mid, 'action')
    assert runner.jev.ask.await_count == (0 if boundary == 'writer' else 1)


async def test_schema_failure_is_diagnosable_without_retaining_invalid_values(tmp_path):
    runner, mid = await followup_runner(tmp_path)
    runner.text.generate.return_value['output'] = {
        'queries': [{'query': 'actual original candidate', 'purpose': 'Find its original publication',
                     'search_kind': 'PRIVATE_INVALID_VALUE'}],
        'gap': 'A primary record has not yet been inspected.', 'PRIVATE_EXTRA_FIELD': 'PRIVATE_CONTENT'}
    assert await propose_followup(runner, mid, runner.effective_plan(mid)) is FollowupOutcome.GENERATION_UNAVAILABLE
    failure = runner.store.records(mid, 'research_followup')[-1]
    assert failure['text_call_id']
    assert {'path': ['queries', 0, 'search_kind'], 'type': 'literal_error'} in failure['validation_issues']
    assert {'path': ['<unknown_field>'], 'type': 'extra_forbidden'} in failure['validation_issues']
    saved = dumps(runner.store.events(mid))
    assert not any(value in saved for value in ('PRIVATE_INVALID_VALUE', 'PRIVATE_EXTRA_FIELD', 'PRIVATE_CONTENT'))
    assert await propose_followup(runner, mid, runner.effective_plan(mid)) is FollowupOutcome.GENERATION_UNAVAILABLE
    assert runner.text.generate.await_count == 1
    runner.jev.ask.assert_not_awaited()


@pytest.mark.parametrize('failure', ['schema', 'provider'])
async def test_generation_failure_uses_real_jev_refinement_choice(tmp_path, failure):
    runner, mid = await followup_runner(tmp_path)
    if failure == 'schema':
        runner.text.generate.return_value['output'] = {'queries': [], 'gap': 42}
    else:
        runner.text.generate.side_effect = TextModelError('Explicit fixture unavailable provider')
    runner.jev.ask.return_value = {'id': 'fixture-refinement-decision', 'answers': {'refine_query': {'choice': 'q0'}}}
    assert await runner.refine_discovery(mid, runner.effective_plan(mid))
    action = runner.store.records(mid, 'action')[-1]
    assert action['decision_id'] == 'fixture-refinement-decision'
    assert action['search_kind'] == 'video'
    assert runner.jev.ask.call_args.args[3] == 'Refine discovery for unanswered questions'
    assert any(event['type'] == 'research.refinement_fallback' for event in runner.store.events(mid))


async def test_jev_decline_does_not_trigger_template_fallback(tmp_path):
    runner, mid = await followup_runner(tmp_path, 'stop')
    assert not await runner.refine_discovery(mid, runner.effective_plan(mid))
    assert not await runner.refine_discovery(mid, runner.effective_plan(mid))
    assert runner.jev.ask.await_count == 1
    assert not runner.store.records(mid, 'action')
    assert not any(event['type'] == 'research.refinement_fallback' for event in runner.store.events(mid))


async def test_fallback_respects_pause_during_jev_choice(tmp_path):
    runner, mid = await followup_runner(tmp_path)
    runner.text.generate.side_effect = TextModelError('Explicit fixture unavailable provider')
    async def pause(*args, **kwargs):
        runner.store.mutate(mid, 'fixture.pause', {}, status='paused')
        return {'id': 'fixture-paused-decision', 'answers': {'refine_query': {'choice': 'q0'}}}
    runner.jev.ask.side_effect = pause
    assert not await runner.refine_discovery(mid, runner.effective_plan(mid))
    assert not runner.store.records(mid, 'action')


async def test_video_page_only_queues_individual_video_links(tmp_path):
    runner, mid = await followup_runner(tmp_path)
    url = 'https://www.youtube.com/watch?v=fixture1234'
    other = 'https://www.youtube.com/watch?v=fixture5678'
    runner.fetcher.get = AsyncMock(return_value={
        'url': url, 'status': 200, 'headers': {'Content-Type': 'text/html'}, 'retrieved_at': now(), 'fetch_ms': 0,
        'body': ('<html><head><title>Explicit source fixture</title></head><body><main><p>'
                 + 'Explicit fixture prose for bounded extraction and no claims about a real video. ' * 6
                 + '</p><a href="' + other + '">Observed video reference</a>'
                 + '<a href="' + url + '">Current video</a><a href="/about/">About</a>'
                 + '<a href="/t/contact_us/">Contact</a><a href="/playlist?list=fixture">Playlist</a>'
                 + '</main></body></html>').encode()})
    runner.fetcher.sitemap = AsyncMock(return_value=[])
    runner.analyze = AsyncMock()
    plan = runner.effective_plan(mid)
    plan['limits']['max_depth'] = 2
    await runner.do_page(mid, {'id': 'fixture-fetch', 'kind': 'fetch', 'value': url, 'parent': None, 'depth': 0}, plan)
    actions = runner.store.records(mid, 'action')
    assert len(actions) == 1 and actions[0]['value'] == other and actions[0]['artifact_lead']
    runner.fetcher.sitemap.assert_not_awaited()


def test_search_route_is_required_by_the_proposal_contract():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        DiscoveryQuery(query='a specific original subject', purpose='Find its primary record')


async def test_research_phase_waits_for_public_primary_subjects_before_comparison(tmp_path):
    runner, mid = await followup_runner(tmp_path)
    plan = runner.effective_plan(mid)
    add_context(runner, mid)
    initial = _followup_state(runner, mid, plan, 'fixture')
    assert initial['research_phase'] == 'discover_subjects' and initial['primary_subject_count'] == 0
    add_evidence(runner, mid)
    first = _followup_state(runner, mid, plan, 'fixture')
    assert first['research_phase'] == 'inspect_more_subjects' and first['primary_subject_count'] == 1
    source = deepcopy(next(s for s in runner.store.records(mid, 'source') if s['id'] == 'source'))
    source.update(id='second_source', unit_id='second_original', url='https://www.youtube.com/watch?v=fixture5678')
    assessment = deepcopy(next(a for a in runner.store.records(mid, 'artifact_analysis') if a['id'] == 'assessment'))
    assessment.update(id='second_assessment', source_id='second_source')
    runner.store.mutate(mid, 'fixture.second_subject', {}, [('source', source), ('artifact_analysis', assessment)])
    second = _followup_state(runner, mid, plan, 'fixture')
    assert second['research_phase'] == 'compare_and_challenge' and second['primary_subject_count'] == 2
    change_record(runner, mid, 'source', 'second_source', private=True)
    assert _followup_state(runner, mid, plan, 'fixture')['primary_subject_count'] == 1
    change_record(runner, mid, 'source', 'source', review='rejected')
    assert _followup_state(runner, mid, plan, 'fixture')['research_phase'] == 'discover_subjects'


async def test_zero_subject_followup_models_share_acquisition_priority(tmp_path):
    runner, mid = await followup_runner(tmp_path)
    add_context(runner, mid)
    assert await propose_followup(runner, mid, runner.effective_plan(mid))
    request = runner.text.generate.call_args.kwargs
    assert request['state']['primary_subject_count'] == 0
    assert request['state']['research_phase'] == 'discover_subjects'
    assert 'First locate inspectable subjects' in request['instructions']
    assert 'before acquiring cases' in request['instructions']
    assert 'UNVERIFIED SEARCH LEADS' in request['instructions']
    choice = runner.jev.ask.call_args.args[2]['followup']
    assert 'First locate inspectable subjects' in choice.instructions
    assert 'already prove the conclusion' in choice.instructions


async def test_initial_discovery_separates_query_terms_from_evidence_requirements(tmp_path):
    store, mid, plan = setup_program(tmp_path, providers=['brave'])
    text = text_fixture(proposal())
    await build_program(planner(), store, mid, plan, text)
    request = text.generate.call_args.kwargs
    assert request['state']['research_phase'] == 'discover_subjects'
    assert request['state']['primary_subject_count'] == 0
    assert {'video', 'web_leads'} == set(request['state']['available_search_tools'])
    assert all(plan['goal'] not in question['question'] for question in request['state']['core_questions'])
    assert 'first two initial queries' in request['instructions']
    assert 'core_questions are for later inspection' in request['instructions']
    assert 'reserve video for a particular title' in request['instructions']
