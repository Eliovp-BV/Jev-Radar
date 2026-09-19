"""Offline end-to-end orchestration, not a benchmark of real model quality.

The Runner, text adapter, extraction, evidence validation, persistence, API and
exports are real. Every hosted response and web document is explicitly synthetic;
transport and Jev are replaced before the fixture investigation starts.
"""
from copy import deepcopy
import json
from unittest.mock import AsyncMock

import httpx

from radar.jev import validate_answer
from radar.program import active_program
from radar.storage import fingerprint, now, uid
from radar.text_model import TextModel
from test_adaptive_runner import RunnerFixtureJev, create_fixture_mission, setup_runner


INITIAL_QUERY = 'Fixture Alpha embedded database writer documentation'
REJECTED_QUERY = 'Fixture irrelevant celebrity merchandise'
FOLLOWUP_QUERY = 'Fixture Beta concurrent writer optimistic retry documentation'
ALPHA = 'https://alpha.example.org/fixture/database'
BETA = 'https://beta.example.org/fixture/database'
UNSUPPORTED = 'Both implementations guarantee a 1000 percent production performance increase.'


class WorkflowFixtureJev(RunnerFixtureJev):
    """Explicit fixture choices, recorded with the real reservation mechanism."""

    async def ask(self, mid, state, questions, purpose, source_id=None, cache=True):
        special = ('Approve goal-specific research questions', 'Choose evidence-driven follow-up',
                   'Check proposed answer against cited evidence')
        if purpose not in special:
            return await super().ask(mid, state, questions, purpose, source_id, cache)
        reservation = self.reserve(mid, 1, 0)
        answers = {}
        for key, question in questions.items():
            assert question.type == 'choice'
            if purpose == special[0]:
                selected = 'accept' if key in ('question_0', 'query_0') else 'reject'
            elif purpose == special[1]:
                selected = 'followup_0'
                # This choice is based on newly extracted source passages, not
                # merely the original prompt or an uninspected search snippet.
                assert state['observed_evidence']
                assert any('serializes writes' in citation['quote'] for item in state['observed_evidence'] for citation in item['citations'])
                assert any(item['id'] == 'research_1' for item in state['missing_questions'])
            else:
                selected = 'unsupported' if key == 'invented_performance' else 'supported'
            assert selected in question.criteria
            answers[key] = {'type': 'choice', 'choice': selected, 'confidence': 1,
                            'probabilities': {option: float(option == selected) for option in question.criteria}}
        result = {'answers': answers, 'model': self.settings.model, 'usage': {'input_tokens': 1, 'output_tokens': 0}}
        validate_answer(questions, result)
        qdata = {key: question.model_dump(mode='json') for key, question in questions.items()}
        decision = {'id': uid(), 'purpose': purpose, 'source_id': source_id, 'mode': 'fixture',
                    'state': deepcopy(state), 'questions': qdata, 'requested_model': self.settings.model,
                    'fingerprint': fingerprint({'state': state, 'questions': qdata}),
                    'rubric_version': self.store.mission(mid)['plan_version'], 'created_at': now(),
                    'cache': False, 'queue_ms': 0, 'status': 'complete', 'latency_ms': 0,
                    'estimated_usd': 0, 'pricing_source': 'Explicit synthetic fixture; no provider call or charge', **result}
        self.store.execute('UPDATE reservations SET status=?,actual_usd=?,actual_tokens=? WHERE id=?',
                           ('complete', 0, 1, reservation))
        self.store.mutate(mid, 'jev.completed', {'decision_id': decision['id'], 'purpose': purpose,
                          'latency_ms': 0, 'model': self.settings.model, 'questions': len(questions),
                          'usage': result['usage']}, [('decision', decision)], mode='fixture')
        self.calls.append(deepcopy(decision))
        return decision


async def test_full_research_loop_generates_gathers_checks_and_invalidates_answer(tmp_path, monkeypatch):
    app, runner = setup_runner(tmp_path, unit='technical_artifacts')
    runner.jev = WorkflowFixtureJev(runner.settings, runner.store, unit='technical_artifacts')
    runner.settings.text_provider = 'openai'
    runner.settings.text_model = 'explicit-fixture-text-model'
    runner.settings.text_input_rate = 1
    runner.settings.text_output_rate = 2
    runner.settings.openai_key = 'explicit-private-fixture-text-key'
    runner.store.set_setting('action_library', [])
    text_states = []

    def text_transport(request):
        body = json.loads(request.content)
        payload = json.loads(body['messages'][-1]['content'])
        state = payload['state']
        text_states.append(deepcopy(state))
        assert request.url == 'https://api.openai.com/v1/chat/completions'
        if 'core_questions' in state:
            output = {'questions': [
                {'label': 'Writer coordination', 'question': 'What writer coordination and retry conditions does each implementation document?'},
                {'label': 'Unrelated topic', 'question': 'Which celebrity merchandise is most fashionable?'}],
                'queries': [{'query': INITIAL_QUERY, 'search_kind': 'web', 'purpose': 'Inspect original implementation documentation for the requested comparison.'},
                            {'query': REJECTED_QUERY, 'search_kind': 'web', 'purpose': 'An explicit irrelevant fixture candidate that Jev must reject.'}]}
        elif 'observed_evidence' in state:
            assert state['observed_evidence'], 'Evidence-driven generation must see inspected passages'
            urls = {citation['url'] for item in state['observed_evidence'] for citation in item['citations']}
            if BETA not in urls:
                assert urls == {ALPHA}
                output = {'queries': [{'query': FOLLOWUP_QUERY, 'search_kind': 'web',
                                      'purpose': 'Find an original contrasting implementation to test the single-writer observation.'}],
                          'gap': 'Only a serial-writer implementation has been inspected; a concurrent-writer comparison is missing.'}
            else:
                assert urls == {ALPHA, BETA}
                output = {'queries': [], 'gap': 'The two documented designs differ, but no comparable workload measurements were inspected.'}
        else:
            assert 'evidence' in state
            evidence = {citation['url']: item['finding_id'] for item in state['evidence'] for citation in item['citations']}
            assert set(evidence) == {ALPHA, BETA}
            output = {'claims': [
                {'id': 'writer_comparison', 'kind': 'comparison', 'finding_ids': [evidence[ALPHA], evidence[BETA]],
                 'text': 'According to their inspected fixture documentation, Alpha serializes writes, while Beta describes concurrent writes with optimistic retries.'},
                {'id': 'invented_performance', 'kind': 'observation', 'finding_ids': [evidence[ALPHA]], 'text': UNSUPPORTED}],
                'recommendations': [
                    {'id': 'measure_workload', 'claim_ids': ['writer_comparison'],
                     'text': 'Run the same representative concurrent-write workload against both implementations before choosing one.'},
                    {'id': 'unsupported_switch', 'claim_ids': ['invented_performance'],
                     'text': 'Switch immediately on the basis of the invented performance guarantee.'}],
                'unknowns': ['No matched workload benchmark was inspected or executed.']}
        return httpx.Response(200, json={'model': 'explicit-fixture-text-model',
            'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(output)}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 100}})

    monkeypatch.setattr(TextModel, 'client', lambda self: httpx.AsyncClient(transport=httpx.MockTransport(text_transport)))

    async def search(query, provider, region, language):
        assert provider == 'brave'
        assert query in (INITIAL_QUERY, FOLLOWUP_QUERY), 'Rejected or unapproved query executed'
        url, name = (ALPHA, 'Alpha') if query == INITIAL_QUERY else (BETA, 'Beta')
        return {'id': uid(), 'provider': 'brave', 'query': query, 'timestamp': now(), 'latency_ms': 0,
                'scope': 'Explicit synthetic offline search fixture', 'estimated_usd': 0,
                'results': [{'id': uid(), 'position': 1, 'url': url, 'title': f'Fixture {name} implementation',
                             'snippet': 'Synthetic original documentation; inspect the document before using its claims.'}]}

    async def fetch(url):
        assert url in (ALPHA, BETA)
        text = ('Fixture Alpha is an embedded database implementation. Its documentation says it serializes writes '
                'behind one writer lock. Readers use snapshots. No matched-workload benchmark or throughput claim '
                'is supplied in this synthetic test document.') if url == ALPHA else (
                'Fixture Beta is an embedded database implementation. Its documentation describes concurrent writes '
                'with optimistic retries when a conflict is detected. Applications must handle retry outcomes. '
                'No matched-workload benchmark or throughput claim is supplied in this synthetic test document.')
        name = 'Alpha' if url == ALPHA else 'Beta'
        return {'url': url, 'status': 200, 'headers': {'Content-Type': 'text/html'}, 'retrieved_at': now(),
                'fetch_ms': 0, 'body': f'<html><head><title>Fixture {name} implementation</title></head><body><main><p>{text}</p></main></body></html>'.encode()}

    runner.search.query = AsyncMock(side_effect=search)
    runner.fetcher.get = AsyncMock(side_effect=fetch)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            mid = await create_fixture_mission(client, app,
                goal='Compare embedded database implementations for an offline application with concurrent writes. Identify the documented trade-offs and missing benchmarks.',
                limits={'max_pages': 2, 'max_queries': 3, 'max_calls': 40, 'max_depth': 0, 'per_domain': 2,
                        'max_tokens': 10000, 'wall_seconds': 30})
            await runner.bounded_run(mid)
            response = await client.get('/api/missions/'+mid)
            assert response.status_code == 200, response.text
            detail = response.json()
            assert detail['status'] == 'partial', detail['events'][-5:]
            assert detail['mode'] == 'fixture' and all(event['mode'] == 'fixture' for event in detail['events'])
            program = active_program(runner.store, mid)
            assert program['unit'] == 'technical_artifacts'
            assert program['text_call_id'] and program['approval_decision_id'] and program['decision_id']
            assert program['search_queries'] == [INITIAL_QUERY]
            assert any(item['id'] == 'research_1' for item in program['criteria'])
            assert not any(item['id'] == 'research_2' for item in program['criteria'])
            assert [call.args[0] for call in runner.search.query.await_args_list] == [INITIAL_QUERY, FOLLOWUP_QUERY]
            assert [call.args[0] for call in runner.fetcher.get.await_args_list] == [ALPHA, BETA]
            runner.search.videos.assert_not_awaited()
            runner.browser.render.assert_not_awaited()

            followup = next(item for item in detail['records']['research_followup'] if item['status'] == 'selected')
            action = next(item for item in detail['records']['action'] if item.get('followup_id') == followup['id'])
            assert action['value'] == FOLLOWUP_QUERY and action['status'] == 'complete'
            assert action['decision_id'] == followup['decision_id']
            assert len(text_states) == 4  # planning, observed gap, no further proposals, final synthesis
            calls = detail['records']['text_call']
            assert len(calls) == detail['telemetry']['text_attempts'] == 4
            assert all(call['status'] == 'complete' and 'output' not in call and 'state' not in call for call in calls)
            assert len(detail['records']['source']) == detail['outcome']['counts']['primary_artifacts'] == 2

            answer = detail['outcome']['research_answer']
            assert answer and answer['status'] == 'partial'
            assert [item['id'] for item in answer['claims']] == ['writer_comparison']
            assert answer['unsupported_claim_count'] == 1
            assert [item['id'] for item in answer['recommendations']] == ['measure_workload']
            assert answer['recommendations'][0]['performed'] is False
            assert any('matched workload' in item for item in answer['unknowns'])
            verify = next(item for item in detail['records']['decision'] if item['id'] == answer['verification_decision_id'])
            assert verify['purpose'] == 'Check proposed answer against cited evidence'
            assert verify['answers']['invented_performance']['choice'] == 'unsupported'
            sources = {item['id']: item for item in detail['records']['source']}
            citations = answer['claims'][0]['citations']
            assert {item['url'] for item in citations} == {ALPHA, BETA}
            for citation in citations:
                assert sources[citation['source_id']]['text'][citation['start']:citation['end']] == citation['quote']
            assert any('serializes writes' in item['quote'] for item in citations)
            assert any('optimistic retries' in item['quote'] for item in citations)

            exported = await client.get('/api/missions/'+mid+'/export/json')
            assert exported.status_code == 200
            export = exported.json()
            assert export['research_answer']['id'] == answer['id']
            assert UNSUPPORTED not in exported.text and 'unsupported_switch' not in exported.text
            assert 'explicit-private-fixture-text-key' not in exported.text
            assert 'answer_proposal' not in exported.text and 'raw_response' not in exported.text
            markdown = await client.get('/api/missions/'+mid+'/export/md')
            assert markdown.status_code == 200 and 'optimistic retries' in markdown.text
            assert UNSUPPORTED not in markdown.text

            # Published answers bind to exact evidence. An edited source cannot
            # retain an answer whose quote offsets no longer match.
            original = next(item for item in sources.values() if item['url'] == ALPHA)
            changed = {**original, 'text': 'Changed fixture evidence. ' + original['text']}
            runner.store.mutate(mid, 'fixture.source_changed', {}, [('source', changed)], mode='fixture')
            invalid = (await client.get('/api/missions/'+mid)).json()
            assert invalid['outcome']['research_answer'] is None
            assert (await client.get('/api/missions/'+mid+'/export/json')).json()['research_answer'] is None
            runner.store.mutate(mid, 'fixture.source_restored', {}, [('source', original)], mode='fixture')
            restored = (await client.get('/api/missions/'+mid)).json()
            assert restored['outcome']['research_answer']['id'] == answer['id']

            # Review changes form a new evidence epoch; undoing a rejection does
            # not silently republish the previously checked answer.
            for state in ('rejected', 'approved'):
                review = await client.post(f'/api/missions/{mid}/review/{original["id"]}', json={'state': state})
                assert review.status_code == 200
                reviewed = (await client.get('/api/missions/'+mid)).json()
                assert reviewed['outcome']['research_answer'] is None
                assert (await client.get('/api/missions/'+mid+'/export/json')).json()['research_answer'] is None
            assert len(text_states) == 4, 'Read/review/export must not generate or recharge an answer'
    finally:
        app.state.store.close()
