"""Grounded-answer contracts; all model outputs are explicit test fixtures."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from radar.jev import BudgetError, DecisionError
from radar.outcomes import available_findings
from radar.program import program_fingerprint
from radar.schemas import Plan
from radar.storage import Store, dumps, now, uid
from radar.synthesis import AnswerProposal, current_brief, synthesize


def fixture(tmp_path, count=2):
    plan = Plan(goal='Compare public product capabilities and identify a useful next improvement', research_mode='fixed',
                criteria=[{'id': 'capabilities', 'label': 'Capabilities', 'question': 'What capabilities are directly documented?'}]).model_dump()
    store = Store(tmp_path / 'synthesis.sqlite')
    mid = uid()
    store.execute('INSERT INTO missions VALUES(?,?,?,?,?,?,?,?,?)',
                  (mid, plan['goal'], 'running', dumps(plan), 1, now(), now(), None, 'fixture'))
    records = []
    for index in range(count):
        quote = f'Product {index} documents offline storage with encryption.'
        source = {'id': f's{index}', 'url': f'https://product{index}.example/docs', 'title': f'Product {index}',
                  'text': 'Introduction. ' + quote + ' A private-looking unrelated tail should never be submitted.',
                  'entity_id': f'e{index}', 'retrieved_at': now(), 'review': 'unreviewed', 'content_hash': str(index)}
        span = {'id': f'p{index}', 'source_id': source['id'], 'text': quote, 'start': 14, 'end': 14 + len(quote)}
        finding = {'id': f'f{index}', 'entity_id': f'e{index}', 'source_ids': [source['id']], 'span_ids': [span['id']],
                   'subject': source['title'], 'criterion_id': 'capabilities', 'question': plan['criteria'][0]['question'],
                   'status': 'supported', 'review': 'unreviewed', 'scope': 'Publisher documentation, not an independent test',
                   'statement': 'MODEL STATEMENT IS NOT EVIDENCE'}
        entity = {'id': f'e{index}', 'name': f'Product {index}', 'domains': [f'product{index}.example'],
                  'source_ids': [source['id']], 'review': 'unreviewed', 'fields': {}}
        records += [('source', source), ('span', span), ('finding', finding), ('entity', entity)]
    store.mutate(mid, 'fixture.saved', {}, records)
    proposal = {'claims': [
        {'id': 'offline', 'text': 'Product 0 documents encrypted offline storage.', 'kind': 'observation', 'finding_ids': ['f0']},
        {'id': 'comparison', 'text': 'Both inspected products document encrypted offline storage.', 'kind': 'comparison', 'finding_ids': ['f0', 'f1']},
        {'id': 'hypothesis', 'text': 'Offline use may be worth investigating as a user need.', 'kind': 'hypothesis', 'finding_ids': ['f0']}],
        'recommendations': [{'id': 'interview', 'text': 'Interview users about their offline workflows before choosing an improvement.', 'claim_ids': ['hypothesis']}],
        'unknowns': ['Independent performance and user demand were not measured.']}
    text = SimpleNamespace(enabled=True, generate=AsyncMock(return_value={'id': 'text-call', 'output': proposal,
                           'model': 'fixture-text', 'provider': 'fixture', 'latency_ms': 12.5}))
    text.config = lambda: {'provider': 'fixture', 'model': 'fixture-text'}
    async def ask(mid, state, questions, purpose, **kwargs):
        return {'id': 'verification', 'model': 'fixture-jev', 'answers': {key: {'choice': 'supported'} for key in questions}}
    runner = SimpleNamespace(store=store, text=text, jev=SimpleNamespace(ask=AsyncMock(side_effect=ask)), settings=SimpleNamespace(model='fixture-jev'))
    runner.eligible_findings = lambda mid, plan: available_findings(plan, {key: store.records(mid, key) for key in ('source', 'finding', 'entity')})
    return runner, mid, plan, proposal


def change(store, mid, kind, id, **values):
    record = next(item for item in store.records(mid, kind) if item['id'] == id)
    record.update(values)
    store.mutate(mid, 'fixture.changed', {}, [(kind, record)])
    return record


async def test_generated_answer_is_verified_and_bound_to_exact_public_passages(tmp_path):
    runner, mid, plan, _ = fixture(tmp_path)
    result = await synthesize(runner, mid, plan)
    assert result['status'] == 'partial'
    assert result['text_call_id'] == 'text-call' and result['verification_decision_id'] == 'verification'
    assert result['provenance'] == {'provider': 'fixture', 'model': 'fixture-text', 'latency_ms': 12.5}
    assert [claim['status'] for claim in result['claims']] == ['supported', 'supported', 'qualified']
    citation = result['claims'][0]['citations'][0]
    source = runner.store.records(mid, 'source')[0]
    assert source['text'][citation['start']:citation['end']] == citation['quote']
    assert citation['finding_id'] == 'f0' and citation['span_id'] == 'p0'
    assert result['recommendations'][0]['performed'] is False
    args = runner.jev.ask.call_args
    assert args.args[3] == 'Check proposed answer against cited evidence'
    assert args.kwargs['cache'] is False and len(args.args[2]) == 3
    for key, question in args.args[2].items():
        assert 'claim ID ' + key + ' in state.claims' in question.instructions
    sent = dumps(runner.text.generate.call_args.kwargs['state'])
    assert 'unrelated tail' not in sent and 'MODEL STATEMENT' not in sent
    assert current_brief(runner.store, mid) == result
    assert runner.store.events(mid)[-1]['mode'] == 'fixture'


async def test_unchanged_retry_reuses_brief_without_either_model_call(tmp_path):
    runner, mid, plan, _ = fixture(tmp_path)
    result = await synthesize(runner, mid, plan)
    assert await synthesize(runner, mid, plan) == result
    assert runner.text.generate.await_count == runner.jev.ask.await_count == 1


async def test_verification_failure_retry_reuses_validated_draft_without_writer_billing(tmp_path):
    runner, mid, plan, _ = fixture(tmp_path)
    original = runner.jev.ask.side_effect
    runner.jev.ask.side_effect = BudgetError('Fixture verification cap')
    with pytest.raises(BudgetError):
        await synthesize(runner, mid, plan)
    drafts = runner.store.records(mid, 'answer_proposal')
    assert len(drafts) == 1 and drafts[0]['private'] is True
    assert drafts[0]['status'] == 'validated' and current_brief(runner.store, mid) is None
    runner.jev.ask.side_effect = original
    result = await synthesize(runner, mid, plan)
    assert result['claims'] and result['text_call_id'] == 'text-call'
    assert runner.text.generate.await_count == 1 and runner.jev.ask.await_count == 2


async def test_pause_during_writer_defers_jev_and_resume_reuses_saved_draft(tmp_path):
    runner, mid, plan, _ = fixture(tmp_path)
    response = runner.text.generate.return_value
    async def pause(*args, **kwargs):
        runner.store.mutate(mid, 'fixture.pause', {}, status='pausing')
        return response
    runner.text.generate.side_effect = pause
    result = await synthesize(runner, mid, plan)
    assert result['status'] == 'unavailable' and not result['claims']
    runner.jev.ask.assert_not_called()
    assert len(runner.store.records(mid, 'answer_proposal')) == 1
    assert current_brief(runner.store, mid) is None
    runner.text.generate.side_effect = None
    runner.store.mutate(mid, 'fixture.resume', {}, status='running')
    result = await synthesize(runner, mid, plan)
    assert result['claims'] and current_brief(runner.store, mid) == result
    assert runner.text.generate.await_count == runner.jev.ask.await_count == 1


@pytest.mark.parametrize('change_kind', ['model', 'provider', 'evidence'])
async def test_draft_reuse_requires_same_model_provider_and_evidence(tmp_path, change_kind):
    runner, mid, plan, _ = fixture(tmp_path)
    original = runner.jev.ask.side_effect
    runner.jev.ask.side_effect = BudgetError('Fixture verification cap')
    with pytest.raises(BudgetError):
        await synthesize(runner, mid, plan)
    if change_kind == 'evidence':
        change(runner.store, mid, 'source', 's0', review='approved')
    else:
        config = {'provider': 'fixture', 'model': 'fixture-text'}
        config[change_kind] = 'another-fixture'
        runner.text.config = lambda: config
    runner.jev.ask.side_effect = original
    await synthesize(runner, mid, plan)
    assert runner.text.generate.await_count == 2


async def test_missing_criteria_are_retained_when_writer_returns_no_unknowns(tmp_path):
    runner, mid, plan, proposal = fixture(tmp_path)
    plan['criteria'].append({'id': 'pricing', 'label': 'Pricing evidence', 'question': 'What prices are documented?', 'rubric': 'Use exact evidence.'})
    runner.store.execute('UPDATE missions SET plan=? WHERE id=?', (dumps(plan), mid))
    proposal['claims'] = proposal['claims'][:1]
    proposal['recommendations'] = []
    proposal['unknowns'] = []
    result = await synthesize(runner, mid, plan)
    assert result['status'] == 'partial'
    assert result['unknowns'] == ['No fully supported current public passage answers: Pricing evidence.']


async def test_no_text_key_does_not_generate_or_invent_answer(tmp_path):
    runner, mid, plan, _ = fixture(tmp_path)
    runner.text.enabled = False
    assert await synthesize(runner, mid, plan) is None
    assert not runner.store.records(mid, 'research_brief')
    runner.text.generate.assert_not_called()
    runner.jev.ask.assert_not_called()


@pytest.mark.parametrize('kind,updates', [
    ('source', {'private': True}), ('finding', {'private': True}), ('entity', {'private': True}),
    ('span', {'private': True}), ('source', {'review': 'rejected'}), ('finding', {'stale': True}),
    ('entity', {'excluded': True}), ('span', {'text': 'A fabricated quote'}),
    ('span', {'start': 0}), ('span', {'source_id': 's1'}),
])
async def test_private_rejected_stale_or_invalid_evidence_is_never_sent(tmp_path, kind, updates):
    runner, mid, plan, _ = fixture(tmp_path)
    ids = {'source': 's0', 'finding': 'f0', 'entity': 'e0', 'span': 'p0'}
    change(runner.store, mid, kind, ids[kind], **updates)
    result = await synthesize(runner, mid, plan)
    sent = runner.text.generate.call_args.kwargs['state']['evidence']
    assert [item['finding_id'] for item in sent] == ['f1']
    assert not result['claims']
    runner.jev.ask.assert_not_called()


async def test_no_valid_passages_stops_without_model_calls(tmp_path):
    runner, mid, plan, _ = fixture(tmp_path)
    for source in runner.store.records(mid, 'source'):
        change(runner.store, mid, 'source', source['id'], text='Changed body makes the saved span invalid.')
    result = await synthesize(runner, mid, plan)
    assert result['status'] == 'unavailable'
    assert current_brief(runner.store, mid) is None
    runner.text.generate.assert_not_called()
    runner.jev.ask.assert_not_called()


async def test_fabricated_references_and_single_subject_comparison_are_rejected(tmp_path):
    runner, mid, plan, proposal = fixture(tmp_path)
    proposal['claims'][0]['finding_ids'] = ['invented']
    proposal['claims'][1]['finding_ids'] = ['f0']
    result = await synthesize(runner, mid, plan)
    assert [item['id'] for item in result['claims']] == ['hypothesis']
    assert result['unsupported_claim_count'] == 2
    assert set(runner.jev.ask.call_args.args[2]) == {'hypothesis'}


async def test_jev_rejection_removes_claim_and_dependent_recommendation(tmp_path):
    runner, mid, plan, _ = fixture(tmp_path)
    async def ask(mid, state, questions, purpose, **kwargs):
        return {'id': 'verification', 'answers': {key: {'choice': 'unsupported' if key == 'hypothesis' else 'supported'} for key in questions}}
    runner.jev.ask.side_effect = ask
    result = await synthesize(runner, mid, plan)
    assert [item['id'] for item in result['claims']] == ['offline', 'comparison']
    assert result['recommendations'] == [] and result['unsupported_claim_count'] == 1


async def test_partly_supported_finding_cannot_be_promoted_to_supported_claim(tmp_path):
    runner, mid, plan, _ = fixture(tmp_path)
    change(runner.store, mid, 'finding', 'f0', status='partly_supported')
    result = await synthesize(runner, mid, plan)
    assert all(item['status'] == 'qualified' for item in result['claims'])


@pytest.mark.parametrize('mutation', ['source', 'finding', 'entity', 'span', 'goal', 'review_restore'])
async def test_saved_answer_disappears_when_current_evidence_or_scope_changes(tmp_path, mutation):
    runner, mid, plan, _ = fixture(tmp_path)
    await synthesize(runner, mid, plan)
    if mutation == 'goal':
        plan['goal'] = 'A new research goal with different scope'
        runner.store.execute('UPDATE missions SET plan=?,plan_version=2 WHERE id=?', (dumps(plan), mid))
    elif mutation == 'review_restore':
        runner.store.mutate(mid, 'review.saved', {'record_id': 's0', 'state': 'rejected'})
        runner.store.mutate(mid, 'review.saved', {'record_id': 's0', 'state': 'unreviewed'})
    else:
        ids = {'source': 's0', 'finding': 'f0', 'entity': 'e0', 'span': 'p0'}
        change(runner.store, mid, mutation, ids[mutation], review='rejected')
    assert current_brief(runner.store, mid) is None


async def test_rejected_multi_source_finding_does_not_survive_on_one_source(tmp_path):
    runner, mid, plan, _ = fixture(tmp_path)
    change(runner.store, mid, 'finding', 'f0', source_ids=['s0', 's1'])
    change(runner.store, mid, 'source', 's1', private=True)
    result = await synthesize(runner, mid, plan)
    assert result['status'] == 'unavailable'
    runner.text.generate.assert_not_called()


async def test_noncompany_commentary_cannot_ground_the_requested_subject(tmp_path):
    runner, mid, plan, _ = fixture(tmp_path)
    plan['research_mode'] = 'adaptive'
    runner.store.execute('UPDATE missions SET plan=? WHERE id=?', (dumps(plan), mid))
    program = {'id': 'program', 'status': 'complete', 'plan_version': 1, 'fingerprint': program_fingerprint(plan, 1),
               'unit': 'videos', 'criteria': plan['criteria'], 'search_queries': [], 'created_at': now()}
    records = [('research_program', program)]
    for index in range(2):
        source = change(runner.store, mid, 'source', f's{index}', source_kind='video', unit_id=f'video-{index}')
        records.append(('artifact_analysis', {'id': f'assessment{index}', 'source_id': source['id'], 'program_id': program['id'],
                        'plan_version': 1, 'role': 'secondary_commentary' if index == 0 else 'primary_artifact', 'relevance': 1}))
    runner.store.mutate(mid, 'fixture.program', {}, records)
    effective = {**plan, '_program': program}
    result = await synthesize(runner, mid, effective)
    assert [item['finding_id'] for item in runner.text.generate.call_args.kwargs['state']['evidence']] == ['f1']
    assert result['status'] == 'unavailable'
    runner.jev.ask.assert_not_called()


async def test_review_during_generation_prevents_publishing_answer(tmp_path):
    runner, mid, plan, proposal = fixture(tmp_path)
    async def generate(*args, **kwargs):
        change(runner.store, mid, 'source', 's0', review='rejected')
        return {'id': 'text-call', 'output': proposal, 'provider': 'fixture'}
    runner.text.generate.side_effect = generate
    result = await synthesize(runner, mid, plan)
    assert result['status'] == 'unavailable' and not result['claims']
    assert current_brief(runner.store, mid) is None
    runner.jev.ask.assert_not_called()


@pytest.mark.parametrize('stage,error', [('text', ValueError('Provider raw body secret')), ('jev', BudgetError('Budget exhausted'))])
async def test_failures_preserve_evidence_and_do_not_invent_narrative(tmp_path, stage, error):
    runner, mid, plan, _ = fixture(tmp_path)
    (runner.text.generate if stage == 'text' else runner.jev.ask).side_effect = error
    with pytest.raises(type(error)):
        await synthesize(runner, mid, plan)
    result = runner.store.records(mid, 'research_brief')[-1]
    assert result['status'] == 'unavailable' and result['claims'] == []
    assert len(runner.store.records(mid, 'source')) == 2
    assert 'Provider raw body secret' not in dumps(runner.store.events(mid))
    assert current_brief(runner.store, mid) is None


async def test_invalid_output_schema_cannot_reach_jev(tmp_path):
    runner, mid, plan, proposal = fixture(tmp_path)
    proposal['invented_field'] = 'not allowed'
    with pytest.raises(DecisionError, match='schema'):
        await synthesize(runner, mid, plan)
    runner.jev.ask.assert_not_called()
    assert current_brief(runner.store, mid) is None


async def test_model_cannot_verify_unsupplied_claim_ids(tmp_path):
    runner, mid, plan, _ = fixture(tmp_path)
    runner.jev.ask.side_effect = None
    runner.jev.ask.return_value = {'id': 'verify', 'answers': {'invented': {'choice': 'supported'}}}
    with pytest.raises(DecisionError, match='claim IDs'):
        await synthesize(runner, mid, plan)
    assert current_brief(runner.store, mid) is None


async def test_evidence_and_verification_payloads_are_bounded_with_omission_counts(tmp_path):
    runner, mid, plan, proposal = fixture(tmp_path, count=24)
    for index in range(24):
        quote = ('Publicly observed text. ' * 100) + 'FULL_END_NOT_SUBMITTED'
        change(runner.store, mid, 'source', f's{index}', text=quote)
        change(runner.store, mid, 'span', f'p{index}', text=quote, start=0, end=len(quote))
    await synthesize(runner, mid, plan)
    state = runner.text.generate.call_args.kwargs['state']
    assert len(dumps(state['evidence']).encode()) <= 15000
    assert state['evidence_scope']['eligible_findings'] == 24
    assert state['evidence_scope']['findings_omitted'] > 0
    assert 'FULL_END_NOT_SUBMITTED' not in dumps(state)
    verification = runner.jev.ask.call_args
    assert len(dumps({'state': verification.args[1], 'questions': {key: value.model_dump() for key, value in verification.args[2].items()}}).encode()) < 49000


def test_schema_preserves_strictness_and_bounds():
    schema = AnswerProposal.model_json_schema()
    assert schema['additionalProperties'] is False
    assert schema['properties']['claims']['maxItems'] == 6
    assert schema['$defs']['ProposedClaim']['properties']['finding_ids']['maxItems'] == 4


def test_snapshot_retains_named_metadata_context_and_invalidates_changed_labels(tmp_path):
    from radar.synthesis import _snapshot
    runner,mid,plan,_=fixture(tmp_path)
    values=[('views','1000000'),('title','A documented demonstration'),('creator','Example creator'),('publisher','Example platform'),('published_at','2024-01-01')]
    source=runner.store.records(mid,'source')[0]
    source['text']='\n'.join(value for _,value in values)
    spans=[];offset=0
    for i,(field,value) in enumerate(values):
        spans.append({'id':f'metadata{i}','source_id':source['id'],'text':value,'start':offset,'end':offset+len(value),'field':field,'provenance':'Publisher field from observed HTML'})
        offset+=len(value)+1
    finding=next(f for f in runner.store.records(mid,'finding') if f['id']=='f0')
    finding['span_ids']=[s['id'] for s in spans]
    runner.store.mutate(mid,'fixture.metadata',{},[('source',source),('finding',finding)]+[('span',s) for s in spans])
    snap=_snapshot(runner.store,mid,plan)
    item=next(i for i in snap['items'] if i['finding_id']=='f0')
    assert [c['field'] for c in item['citations']]==[field for field,_ in values]
    assert all(source['text'][c['start']:c['end']]==c['quote'] for c in item['citations'])
    assert not item['additional_spans_omitted']
    change(runner.store,mid,'span','metadata0',field='duration')
    assert _snapshot(runner.store,mid,plan)['fingerprint']!=snap['fingerprint']
