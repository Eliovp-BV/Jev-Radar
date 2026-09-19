"""Unused approved query recovery; explicit offline model decisions only."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from radar.config import Settings
from radar.program import build_program
from radar.research import Runner
from radar.research_proposals import FollowupOutcome
from radar.storage import uid
from test_program import setup_program, jev_fixture


async def prepared_runner(tmp_path, monkeypatch, reject_all=False):
    store, mid, plan = setup_program(tmp_path, providers=['brave'], limits={'max_queries': 6})
    runner = Runner(Settings(data_dir=tmp_path, key='fixture', brave_key='fixture'), store)
    runner.jev = jev_fixture()
    design = runner.jev.ask.return_value
    approval = {'id': uid(), 'answers': {f'query_{i}': {'choice': 'accept' if i < 3 and not reject_all else 'reject'} for i in range(4)}}
    runner.jev.ask.side_effect = [design, approval]
    runner.text = SimpleNamespace(enabled=True, config=lambda: {'provider': 'openai', 'model': 'fixture'},
        generate=AsyncMock(return_value={'id': uid(), 'output': {'questions': [], 'queries': [
            {'query': 'fixture candidate '+str(i), 'purpose': 'Locate individual fixture subjects for inspection.',
             'search_kind': 'web_leads' if i == 2 else 'video'} for i in range(4)]}}))
    program = await build_program(runner.jev, store, mid, plan, runner.text)
    runner.initialize(mid)
    runner.jev.ask = AsyncMock(return_value={'id': uid(), 'answers': {'remaining_query': {'choice': 'approved_2'}}})
    followup = AsyncMock(return_value=FollowupOutcome.EXHAUSTED)
    monkeypatch.setattr('radar.research.propose_followup', followup)
    return runner, mid, program, followup


async def test_exhausted_rounds_offer_unused_approved_query_to_jev(tmp_path, monkeypatch):
    runner, mid, program, followup = await prepared_runner(tmp_path, monkeypatch)
    assert len(runner.store.records(mid, 'action')) == 2
    plan = runner.effective_plan(mid)
    assert await runner.refine_discovery(mid, plan)
    state, questions = runner.jev.ask.call_args.args[1:3]
    assert set(questions['remaining_query'].criteria) == {'approved_2', 'stop'}
    assert state['approval_decision_id'] == program['approval_decision_id']
    action = runner.store.records(mid, 'action')[-1]
    assert action['value'] == 'fixture candidate 2' and action['search_kind'] == 'web_leads'
    assert action['decision_id'] == runner.jev.ask.return_value['id']
    assert action['approval_decision_id'] == program['approval_decision_id']
    assert action['program_id'] == program['id'] and action['discovery_refinement']
    assert runner.text.generate.await_count == 1  # Initial planning only.
    assert not await runner.refine_discovery(mid, plan)
    assert runner.jev.ask.await_count == 1
    assert followup.await_count == 2
    runner.store.close()


@pytest.mark.parametrize('outcome', [FollowupOutcome.DECLINED, FollowupOutcome.DEFERRED, FollowupOutcome.UNAVAILABLE])
async def test_never_overrides_decline_defer_or_unavailable(tmp_path, monkeypatch, outcome):
    runner, mid, _, followup = await prepared_runner(tmp_path, monkeypatch)
    followup.return_value = outcome
    assert not await runner.refine_discovery(mid, runner.effective_plan(mid))
    runner.jev.ask.assert_not_awaited()
    assert len(runner.store.records(mid, 'action')) == 2
    runner.store.close()


async def test_explicit_stop_is_retained_without_repeating_same_paid_choice(tmp_path, monkeypatch):
    runner, mid, _, _ = await prepared_runner(tmp_path, monkeypatch)
    runner.jev.ask.return_value['answers']['remaining_query']['choice'] = 'stop'
    assert not await runner.refine_discovery(mid, runner.effective_plan(mid))
    assert not await runner.refine_discovery(mid, runner.effective_plan(mid), reason='challenge_before_conclusion')
    assert runner.jev.ask.await_count == 1
    assert len(runner.store.records(mid, 'action')) == 2
    assert any(event['type'] == 'research.remaining_discovery_declined' for event in runner.store.events(mid))
    runner.store.close()


@pytest.mark.parametrize('change', ['paused', 'scope_changed', 'budget_spent', 'provider_blocked', 'already_queued'])
async def test_inflight_selection_cannot_adopt_after_scope_pause_or_limits_change(tmp_path, monkeypatch, change):
    runner, mid, _, _ = await prepared_runner(tmp_path, monkeypatch)
    decision = runner.jev.ask.return_value
    async def changing(*args, **kwargs):
        if change == 'paused':
            runner.store.mutate(mid, 'fixture.paused', {}, status='paused')
        elif change == 'scope_changed':
            runner.store.execute('UPDATE missions SET plan_version=plan_version+1 WHERE id=?', (mid,))
        elif change == 'budget_spent':
            for i in range(6):
                runner.store.mutate(mid, 'fixture.search', {}, [('search_attempt', {'id': uid(), 'query': 'fixture spent '+str(i), 'status': 'failed'})])
        elif change == 'provider_blocked':
            runner.store.mutate(mid, 'fixture.provider_blocked', {}, [('provider_error', {'id': uid(), 'provider': 'brave'})])
        elif change == 'already_queued':
            runner.add_action(mid, 'search', 'fixture candidate 2')
        return decision
    runner.jev.ask.side_effect = changing
    assert not await runner.refine_discovery(mid, runner.effective_plan(mid))
    assert not any(action.get('decision_id') == decision['id'] for action in runner.store.records(mid, 'action'))
    runner.store.close()


@pytest.mark.parametrize('blocked_by', ['budget', 'provider', 'paused', 'no_approval'])
async def test_unusable_recovery_does_not_spend_a_jev_call(tmp_path, monkeypatch, blocked_by):
    runner, mid, program, _ = await prepared_runner(tmp_path, monkeypatch)
    if blocked_by == 'budget':
        for i in range(6):
            runner.store.mutate(mid, 'fixture.search', {}, [('search_attempt', {'id': uid(), 'query': 'fixture spent '+str(i)})])
    elif blocked_by == 'provider':
        runner.settings.brave_key = ''
    elif blocked_by == 'paused':
        runner.store.mutate(mid, 'fixture.paused', {}, status='paused')
    else:
        program.pop('approval_decision_id')
        runner.store.mutate(mid, 'fixture.no_approval', {}, [('research_program', program)])
    assert not await runner.refine_discovery(mid, runner.effective_plan(mid))
    runner.jev.ask.assert_not_awaited()
    runner.store.close()


async def test_old_attempt_without_action_is_not_requeued(tmp_path, monkeypatch):
    runner, mid, _, _ = await prepared_runner(tmp_path, monkeypatch)
    runner.store.mutate(mid, 'fixture.old_attempt', {}, [('search_attempt', {
        'id': uid(), 'query': '  FIXTURE   CANDIDATE 2 ', 'status': 'failed'})])
    assert not await runner.refine_discovery(mid, runner.effective_plan(mid))
    runner.jev.ask.assert_not_awaited()
    runner.store.close()


async def test_all_rejected_queries_never_recover_template_fallback_as_approved(tmp_path, monkeypatch):
    runner, mid, program, _ = await prepared_runner(tmp_path, monkeypatch, reject_all=True)
    assert program['approval_decision_id']
    assert program['search_queries'] and program['approved_search_queries'] == []
    assert not await runner.refine_discovery(mid, runner.effective_plan(mid))
    runner.jev.ask.assert_not_awaited()
    runner.store.close()


async def test_legacy_program_without_explicit_approved_query_list_is_not_recovered(tmp_path, monkeypatch):
    runner, mid, program, _ = await prepared_runner(tmp_path, monkeypatch)
    program.pop('approved_search_queries')
    runner.store.mutate(mid, 'fixture.legacy_program', {}, [('research_program', program)])
    assert not await runner.refine_discovery(mid, runner.effective_plan(mid))
    runner.jev.ask.assert_not_awaited()
    runner.store.close()
