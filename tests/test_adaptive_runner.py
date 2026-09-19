"""Complete adaptive Runner exercises with explicit fixtures and no network.

The fixture Jev returns supplied typed candidates and uses the real reservation
gate. These tests verify orchestration, evidence scope and bounded execution;
they do not claim to measure live model accuracy or performance.
"""
from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest

from radar.api import create_app
from radar.config import Settings
from radar.jev import Jev, DecisionError, validate_answer
from radar.program import active_program, build_program
from radar.security import PolicyError
from radar.storage import fingerprint, now, uid


class RunnerFixtureJev(Jev):
    def __init__(self, settings, store, unit='videos'):
        super().__init__(settings, store)
        self.unit = unit
        self.calls = []
        self.declines_after_search = 0
        self.refinement_choice = 'q0'
        self.refinement_choices = []
        self.context_title_marker = None

    async def ask(self, mid, state, questions, purpose, source_id=None, cache=True):
        # No transport/client is constructed. Real call-count limits still apply.
        reservation = self.reserve(mid, 1, 0)
        qdata = {key: question.model_dump(mode='json') for key, question in questions.items()}
        decision = {'id': uid(), 'purpose': purpose, 'source_id': source_id, 'mode': 'fixture',
                    'state': deepcopy(state), 'questions': qdata, 'requested_model': self.settings.model,
                    'fingerprint': fingerprint({'state': state, 'questions': qdata}),
                    'rubric_version': self.store.mission(mid)['plan_version'], 'created_at': now(),
                    'cache': False, 'queue_ms': 0, 'status': 'inflight'}
        self.store.mutate(mid, 'jev.started', {'decision_id': decision['id'], 'purpose': purpose}, [('decision', decision)], mode='fixture')
        answers = {}
        protocol = {'research_unit': self.unit, 'research_method': 'explain_patterns',
                    'primary_dimension': 'observed_traction', 'secondary_dimension': 'distribution',
                    'discovery_route': 'primary_records'}
        decline_collection = (purpose == 'Select independent records for parallel assessment'
                              and self.declines_after_search and self.store.records(mid, 'search'))
        if decline_collection:
            self.declines_after_search -= 1
        for key, question in questions.items():
            if question.type == 'score':
                level = len(question.criteria)-1
                answers[key] = {'type': 'score', 'score': level, 'confidence': 1,
                                'probabilities': {str(index): float(index == level) for index in range(len(question.criteria))}}
                continue
            assert question.type == 'choice'
            choices = question.criteria
            if key in protocol:
                selected = protocol[key]
            elif purpose == 'Select independent records for parallel assessment':
                selected = 'defer' if decline_collection else 'inspect'
            elif key == 'next':
                candidates = [(key, label) for key, label in choices.items() if key != 'stop']
                # Prefer actually queued artifact observations, then original
                # page inspection. Candidate IDs come from this real Runner.
                candidates.sort(key=lambda item: 0 if item[1].startswith('video:') else 1 if item[1].startswith('fetch:') else 2)
                selected = candidates[0][0] if candidates else 'stop'
                if self.declines_after_search and self.store.records(mid, 'search'):
                    self.declines_after_search -= 1
                    selected = 'stop'
            elif key == 'refine_query':
                selected = self.refinement_choices.pop(0) if self.refinement_choices else self.refinement_choice
            elif key == 'source_role':
                selected = 'primary_artifact'  # adversarial for the blog test: code must still gate it
                if self.context_title_marker and self.context_title_marker in state.get('title', ''):
                    selected = 'secondary_commentary'
            elif key.startswith('span_'):
                selected = state['untrusted_passages'][0]['id'] if key in ('span_artifact', 'span_implementation') else 'unknown'
            elif key in ('title_hook', 'content_format', 'audience_value'):
                selected = {'title_hook': 'promise', 'content_format': 'demonstration', 'audience_value': 'practical'}[key]
            elif key.endswith('_evidence'):
                selected = state['untrusted_passages'][0]['id']
            elif purpose == 'Verify selected evidence against each question':
                selected = 'supported'
            elif key == 'next_test':
                selected = 'matched'
            elif key == 'priority':
                selected = 'none'
            elif purpose == 'Compare observed artifacts':
                selected = 'observed'
            else:
                raise AssertionError(f'Unexpected fixture question {purpose}: {key}')
            assert selected in choices, (key, selected)
            answers[key] = {'type': 'choice', 'choice': selected, 'confidence': 1,
                            'probabilities': {option: float(option == selected) for option in choices}}
        result = {'answers': answers, 'model': self.settings.model, 'usage': {'input_tokens': 1, 'output_tokens': 0}}
        validate_answer(questions, result)
        decision.update(result, status='complete', latency_ms=0, estimated_usd=0,
                        pricing_source='Explicit isolated fixture; no provider request or charge')
        self.store.execute('UPDATE reservations SET status=?,actual_usd=?,actual_tokens=? WHERE id=?', ('complete', 0, 1, reservation))
        self.store.mutate(mid, 'jev.completed', {'decision_id': decision['id'], 'purpose': purpose, 'latency_ms': 0,
                          'questions': len(questions), 'model': self.settings.model, 'usage': result['usage']}, [('decision', decision)], mode='fixture')
        self.calls.append(deepcopy(decision))
        return decision


def video_observation(query='fixture videos'):
    return {'id': uid(), 'query': query, 'provider': 'brave', 'search_kind': 'video', 'region_requested': '',
            'language': 'en', 'timestamp': now(), 'latency_ms': 0,
            'endpoint': 'https://api.search.brave.com/res/v1/videos/search',
            'scope': 'Explicit synthetic video-index fixture, not a live provider observation',
            'estimated_usd': 0, 'pricing_provenance': 'Fixture with no charge',
            'results': [{'id': uid(), 'position': index+1, 'url': 'https://www.youtube.com/watch?v=fixture00'+str(index),
                         'title': 'Fixture: build a useful example '+str(index),
                         'snippet': 'Explicit fixture description of an instructional demonstration.',
                         'video': {'creator': 'Fixture creator '+str(index), 'views': None},
                         'source_kind': 'video', 'page_age': None, 'thumbnail': {}, 'meta_url': {}}
                        for index in range(2)]}


def setup_runner(tmp_path, *, unit='videos'):
    settings = Settings(data_dir=tmp_path, key='explicit-fixture-key', brave_key='explicit-fixture-brave', model='explicit-fixture-model')
    app = create_app(settings)
    runner = app.state.runner
    runner.jev = RunnerFixtureJev(settings, app.state.store, unit)
    runner.search.videos = AsyncMock(side_effect=lambda query, region, language: video_observation(query))
    runner.search.query = AsyncMock(side_effect=AssertionError('Generic search is forbidden in this video fixture'))
    runner.fetcher.get = AsyncMock(side_effect=PolicyError('Explicit fixture access block; no original page acquired'))
    runner.fetcher.sitemap = AsyncMock(return_value=[])
    runner.browser.render = AsyncMock(side_effect=AssertionError('This fixture cannot render or access the network'))
    return app, runner


async def create_fixture_mission(client, app, **changes):
    token = (await client.get('/api/session')).json()['csrf']
    client.headers['x-radar-csrf'] = token
    plan = {'goal': "I'm looking for viral videos and why they went viral", 'research_mode': 'adaptive',
            'lens_id': 'landscape', 'providers': ['seed', 'brave'], 'discovery_target': 2,
            'limits': {'max_pages': 2, 'max_queries': 1, 'max_calls': 30, 'max_depth': 0, 'per_domain': 4,
                       'wall_seconds': 30, 'usd': 1, 'max_tokens': 10000}} | changes
    response = await client.post('/api/missions', json=plan)
    assert response.status_code == 200, response.text
    mission = response.json()
    store = app.state.store
    store.execute("UPDATE missions SET status='running',mode='fixture' WHERE id=?", (mission['id'],))
    store.execute("UPDATE events SET mode='fixture' WHERE mission_id=?", (mission['id'],))
    store.mutate(mission['id'], 'mission.start', {'fixture': True}, mode='fixture')
    return mission['id']


async def test_complete_runner_uses_jev_program_then_individual_video_evidence_and_comparison(tmp_path):
    app, runner = setup_runner(tmp_path)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            mid = await create_fixture_mission(client, app)
            await runner.bounded_run(mid)
            response = await client.get('/api/missions/'+mid)
            assert response.status_code == 200, response.text
            detail = response.json()
        assert detail['status'] == 'partial'  # unavailable causal/content evidence remains missing
        program = active_program(runner.store, mid)
        assert program and program['unit'] == 'videos'
        assert runner.store.mission(mid)['plan']['lens_id'] == 'landscape'
        assert detail['plan']['criteria'] == program['criteria']
        assert 'offering' not in {item['id'] for item in detail['plan']['criteria']}
        runner.search.videos.assert_awaited_once()
        runner.search.query.assert_not_awaited()
        assert runner.fetcher.get.await_count == 2
        sources = detail['records']['source']
        assert len(sources) == 2 and all(source['source_kind'] == 'video' for source in sources)
        assert len({source['entity_id'] for source in sources}) == 2
        assert all(source['video_metadata']['views'] is None for source in sources)
        assert all(source['video_metadata']['transcript_available'] is False for source in sources)
        assert detail['outcome']['counts']['primary_artifacts'] == 2
        assert detail['outcome']['counts']['supported_findings'] == 2
        assert {item['criterion_id'] for item in detail['outcome']['gaps']} <= {item['id'] for item in program['criteria']}
        assert 'watched footage' in detail['outcome']['summary']
        comparison = detail['records']['research_analysis'][-1]
        assert comparison['artifact_count'] == 2 and comparison['decision_id']
        assert comparison['patterns'] and all(len(item['source_ids']) == 2 for item in comparison['patterns'])
        purposes = [decision['purpose'] for decision in detail['records']['decision']]
        assert purposes[0] == 'Design research approach'
        assert purposes.count('Analyze individual artifact and select evidence') == 2
        assert purposes.count('Verify selected evidence against each question') == 2
        assert 'Compare observed artifacts' in purposes
        assert all(event['mode'] == 'fixture' for event in detail['events'])
        assert detail['telemetry']['attempts'] == len(runner.jev.calls) < 30
        assert detail['telemetry']['search_attempts'] == 1
        assert detail['telemetry']['estimated_usd'] == 0
        assert not detail['records'].get('metric')
    finally:
        app.state.store.close()


async def test_blog_findings_do_not_satisfy_video_program_or_api_coverage(tmp_path):
    app, runner = setup_runner(tmp_path)
    blog = 'https://example.org/fixture-article'
    runner.fetcher.get = AsyncMock(return_value={
        'url': blog, 'status': 200, 'headers': {'Content-Type': 'text/html'}, 'retrieved_at': now(), 'fetch_ms': 0,
        'body': b'<html><head><title>Explicit fixture article about viral videos</title></head><body><main><h1>Fixture observations</h1><p>This is an explicitly synthetic article describing other people\'s videos. It is not an individual video, and no footage, audio, transcript or original video record was acquired. The repeated content exists only to exercise ordinary extraction and its provenance. A commentary page cannot satisfy research coverage for original video artifacts.</p></main></body></html>',
    })
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            mid = await create_fixture_mission(client, app, seeds=[blog], providers=['seed'],
                                               limits={'max_pages': 1, 'max_queries': 0, 'max_calls': 10, 'max_depth': 0, 'wall_seconds': 30})
            await runner.bounded_run(mid)
            detail = (await client.get('/api/missions/'+mid)).json()
        assert detail['status'] == 'partial'
        assert not detail['records'].get('finding')
        assert not any(decision['purpose'] == 'Verify selected evidence against each question' for decision in runner.jev.calls)
        assert detail['records']['source'][0]['research_role'] == 'secondary_commentary'
        assert detail['outcome']['counts']['primary_artifacts'] == 0
        assert detail['outcome']['counts']['supported_findings'] == 0
        assert not detail['outcome']['findings']
        assert 'artifact_coverage' in {item['criterion_id'] for item in detail['outcome']['gaps']}
        assert detail['records']['research_analysis'][-1]['artifact_count'] == 0
        assert detail['records']['research_analysis'][-1]['decision_id'] is None
        runner.search.videos.assert_not_awaited()
        runner.search.query.assert_not_awaited()
    finally:
        app.state.store.close()


async def test_adaptive_runner_stops_at_real_reservation_call_limit(tmp_path):
    app, runner = setup_runner(tmp_path)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            mid = await create_fixture_mission(client, app, limits={'max_pages': 2, 'max_queries': 1, 'max_calls': 1, 'max_depth': 0, 'wall_seconds': 30})
            await runner.bounded_run(mid)
            detail = (await client.get('/api/missions/'+mid)).json()
        assert detail['status'] == 'partial'
        assert active_program(runner.store, mid) is not None
        assert len(runner.jev.calls) == detail['telemetry']['attempts'] == 1
        assert not detail['records'].get('artifact_analysis')
        assert detail['records']['research_analysis'][-1]['decision_id'] is None
        assert not detail['records']['research_analysis'][-1]['patterns']
        assert detail['outcome']['stop']['code'] == 'inference_limit'
        assert not any(event['type'] == 'mission.blocked' for event in detail['events'])
        runner.search.videos.assert_awaited_once()
        runner.search.query.assert_not_awaited()
    finally:
        app.state.store.close()


@pytest.mark.parametrize('max_calls,primary_count', [(3, 0), (4, 1)])
async def test_inference_limit_preserves_collected_source_and_retry_issues_no_extra_request(tmp_path, max_calls, primary_count):
    app, runner = setup_runner(tmp_path)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            mid = await create_fixture_mission(client, app, limits={'max_pages': 2, 'max_queries': 1, 'max_calls': max_calls, 'max_depth': 0, 'wall_seconds': 30})
            await runner.bounded_run(mid)
            stopped = (await client.get('/api/missions/'+mid)).json()
            assert stopped['status'] == 'partial'
            assert stopped['outcome']['stop']['code'] == 'inference_limit'
            assert len(stopped['records']['source']) == 1
            assert stopped['outcome']['counts']['primary_artifacts'] == primary_count
            assert stopped['outcome']['counts']['supported_findings'] == primary_count
            assert not any(action['status'] == 'uncertain' for action in stopped['records']['action'])
            assert not any(event['type'] in ('mission.blocked', 'action.uncertain') for event in stopped['events'])
            assert all(row['status'] == 'complete' for row in runner.store.rows('SELECT status FROM reservations WHERE mission_id=?', (mid,)))
            if max_calls == 3:
                limited = next(event for event in stopped['events'] if event['type'] == 'action.budget_limited')
                assert limited['payload']['blocked_request_attempted'] is False
                action = next(action for action in stopped['records']['action'] if action['id'] == limited['payload']['action_id'])
                assert action['status'] == 'queued'
            response = await client.post('/api/missions/'+mid+'/command', json={'action': 'retry', 'idempotency_key': 'fixture-no-allowance-retry'})
            assert response.status_code == 200
            await runner.tasks[mid]
            retried = (await client.get('/api/missions/'+mid)).json()
        assert retried['status'] == 'partial'
        assert retried['outcome']['stop']['code'] == 'inference_limit'
        assert len(runner.jev.calls) == retried['telemetry']['attempts'] == max_calls
        assert retried['records']['source'] == stopped['records']['source']
        assert retried['records'].get('finding', []) == stopped['records'].get('finding', [])
        assert retried['records']['research_analysis'][-1]['decision_id'] is None
        runner.search.videos.assert_awaited_once()
    finally:
        app.state.store.close()


async def test_decision_failure_still_blocks_with_uncertain_action(tmp_path):
    app, runner = setup_runner(tmp_path)
    original = runner.jev.ask
    async def fixture_failure(mid, state, questions, purpose, source_id=None, cache=True):
        if purpose == 'Analyze individual artifact and select evidence':
            raise DecisionError('Explicit fixture provider-response failure')
        return await original(mid, state, questions, purpose, source_id, cache)
    runner.jev.ask = fixture_failure
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            mid = await create_fixture_mission(client, app)
            await runner.bounded_run(mid)
            detail = (await client.get('/api/missions/'+mid)).json()
        assert detail['status'] == 'blocked'
        assert any(action['status'] == 'uncertain' for action in detail['records']['action'])
        assert any(event['type'] == 'mission.blocked' for event in detail['events'])
        assert not any(event['type'] == 'action.budget_limited' for event in detail['events'])
    finally:
        app.state.store.close()


async def test_page_budget_counts_individual_videos_and_prevents_second_assessment(tmp_path):
    app, runner = setup_runner(tmp_path)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            mid = await create_fixture_mission(client, app, limits={'max_pages': 1, 'max_queries': 1, 'max_calls': 20, 'max_depth': 0, 'wall_seconds': 30})
            await runner.bounded_run(mid)
            detail = (await client.get('/api/missions/'+mid)).json()
        assert detail['status'] == 'partial'
        assert len(detail['records']['source']) == len(detail['records']['artifact_analysis']) == 1
        assert detail['outcome']['counts']['primary_artifacts'] == 1
        assert detail['records']['research_analysis'][-1]['artifact_count'] == 1
        assert detail['records']['research_analysis'][-1]['decision_id'] is None
        assert any(action['kind'] == 'video' and action['status'] == 'queued' for action in detail['records']['action'])
        assert detail['outcome']['stop']['code'] == 'configured_limits'
        assert len(runner.jev.calls) < 20
    finally:
        app.state.store.close()


async def test_same_goal_retry_reuses_program_assessments_and_comparison_without_extra_inference(tmp_path):
    app, runner = setup_runner(tmp_path)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            mid = await create_fixture_mission(client, app)
            await runner.bounded_run(mid)
            original = (await client.get('/api/missions/'+mid)).json()
            call_count = len(runner.jev.calls)
            response = await client.post('/api/missions/'+mid+'/command', json={'action': 'retry', 'idempotency_key': 'explicit-fixture-retry'})
            assert response.status_code == 200, response.text
            await runner.tasks[mid]
            retried = (await client.get('/api/missions/'+mid)).json()
        assert len(runner.jev.calls) == call_count
        assert retried['records']['research_program'] == original['records']['research_program']
        assert retried['records']['artifact_analysis'] == original['records']['artifact_analysis']
        assert retried['records']['research_analysis'] == original['records']['research_analysis']
        assert retried['telemetry']['attempts'] == original['telemetry']['attempts']
        assert retried['outcome']['counts']['primary_artifacts'] == 2
        runner.search.videos.assert_awaited_once()
    finally:
        app.state.store.close()


async def test_actual_jev_unit_controls_general_research_instead_of_the_provisional_lens(tmp_path):
    app, runner = setup_runner(tmp_path, unit='technical_artifacts')
    urls = ['https://github.com/fixture-org/fixture-project-a', 'https://github.com/fixture-org/fixture-project-b']
    runner.search.query = AsyncMock(return_value={
        'id': uid(), 'query': 'explicit fixture technical research', 'provider': 'brave', 'region_requested': '',
        'language': 'en', 'timestamp': now(), 'latency_ms': 0, 'scope': 'Explicit synthetic web-search fixture',
        'results': [{'id': uid(), 'position': index+1, 'url': url, 'title': 'Explicit fixture repository '+str(index),
                     'snippet': 'Fixture original documentation'} for index, url in enumerate(urls)],
    })
    async def fixture_page(url):
        title = 'Explicit fixture repository '+url.rsplit('/', 1)[-1]
        return {'url': url, 'status': 200, 'headers': {'Content-Type': 'text/html'}, 'retrieved_at': now(), 'fetch_ms': 0,
                'body': ('<html><head><title>'+title+'</title></head><body><main><h1>'+title+'</h1><p>This explicitly synthetic technical artifact supplies original documentation for an example implementation. It records design choices, implementation boundaries and reproducibility limitations without claiming that an experiment was run. The fixture exercises evidence extraction and typed comparison without making a real network request or reporting real benchmarks.</p></main></body></html>').encode()}
    runner.fetcher.get = AsyncMock(side_effect=fixture_page)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            mid = await create_fixture_mission(client, app, goal='Compare original open-source document database implementations', lens_id='campaign')
            await runner.bounded_run(mid)
            detail = (await client.get('/api/missions/'+mid)).json()
        assert detail['status'] == 'partial'
        assert detail['records']['research_program'][0]['unit'] == 'technical_artifacts'
        assert runner.store.mission(mid)['plan']['lens_id'] == 'campaign'
        assert 'implementation' in {criterion['id'] for criterion in detail['plan']['criteria']}
        assert 'campaign' not in {criterion['id'] for criterion in detail['plan']['criteria']}
        runner.search.query.assert_awaited_once()
        runner.search.videos.assert_not_awaited()
        assert {source['url'] for source in detail['records']['source']} == set(urls)
        assert detail['outcome']['counts']['primary_artifacts'] == 2
        assert detail['records']['research_analysis'][-1]['decision_id']
        assert detail['records']['research_analysis'][-1]['patterns'][0]['id'] == 'implementation'
        assert len({entity['id'] for entity in detail['records']['entity']}) == 2
    finally:
        app.state.store.close()


async def test_jev_refines_declined_discovery_and_inspects_new_original_video_records(tmp_path):
    app, runner = setup_runner(tmp_path)
    runner.jev.declines_after_search = 1
    async def fixture_videos(query, region, language):
        result = video_observation(query)
        refined = '-compilation' in query
        for index, item in enumerate(result['results']):
            item['url'] = 'https://www.youtube.com/watch?v=' + ('original' if refined else 'collection') + str(index)
            item['title'] = ('Fixture original tutorial ' if refined else 'Fixture unrelated compilation ') + str(index)
        return result
    runner.search.videos = AsyncMock(side_effect=fixture_videos)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            mid = await create_fixture_mission(client, app, limits={'max_pages': 2, 'max_queries': 2, 'max_calls': 30, 'max_depth': 0, 'wall_seconds': 30})
            await runner.bounded_run(mid)
            detail = (await client.get('/api/missions/'+mid)).json()
        assert detail['status'] == 'partial'
        assert runner.search.videos.await_count == 2
        runner.search.query.assert_not_awaited()
        refinement = next(decision for decision in runner.jev.calls if decision['purpose'] == 'Refine discovery for unanswered questions')
        assert refinement['answers']['refine_query']['choice'] == 'q0'
        assert all('compilation' in result['title'] for result in refinement['state']['observed_results'])
        assert all(result['snippet'] and len(result['snippet']) <= 200 for result in refinement['state']['observed_results'])
        refined_action = next(action for action in detail['records']['action'] if action.get('decision_id') == refinement['id'])
        assert refined_action['kind'] == 'search' and refined_action['status'] == 'complete'
        assert refined_action['value'] == refinement['questions']['refine_query']['criteria']['q0']
        assert all('original' in source['url'] for source in detail['records']['source'])
        assert detail['outcome']['counts']['primary_artifacts'] == 2
        assert detail['records']['research_analysis'][-1]['decision_id']
        assert detail['telemetry']['search_attempts'] == 2
        assert len([event for event in detail['events'] if event['type'] == 'research.refined']) == 1
    finally:
        app.state.store.close()


async def test_refinement_abstention_never_executes_an_unselected_search(tmp_path):
    app, runner = setup_runner(tmp_path)
    runner.jev.declines_after_search = 1
    runner.jev.refinement_choice = 'stop'
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            mid = await create_fixture_mission(client, app, limits={'max_pages': 2, 'max_queries': 2, 'max_calls': 20, 'max_depth': 0, 'wall_seconds': 30})
            await runner.bounded_run(mid)
            detail = (await client.get('/api/missions/'+mid)).json()
        runner.search.videos.assert_awaited_once()
        assert len([decision for decision in runner.jev.calls if decision['purpose'] == 'Refine discovery for unanswered questions']) == 1
        assert not any(event['type'] == 'research.refined' for event in detail['events'])
        assert not detail['records'].get('source')
        assert detail['outcome']['stop']['code'] == 'jev_abstained'
    finally:
        app.state.store.close()


@pytest.mark.parametrize('providers,blocked', [(['seed'], False), (['wikipedia'], False), (['brave'], True)])
async def test_refinement_does_not_spend_inference_without_a_usable_provider(tmp_path, providers, blocked):
    app, runner = setup_runner(tmp_path)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            mid = await create_fixture_mission(client, app)
        await build_program(runner.jev, runner.store, mid, runner.store.mission(mid)['plan'])
        plan = runner.effective_plan(mid)
        plan['providers'] = providers
        if blocked:
            runner.store.mutate(mid, 'fixture.provider_blocked', {}, [('provider_error', {'id': uid(), 'provider': 'brave', 'error': 'Explicit fixture access block'})], mode='fixture')
        calls = len(runner.jev.calls)
        assert await runner.refine_discovery(mid, plan) is False
        assert len(runner.jev.calls) == calls
        runner.search.videos.assert_not_awaited()
        runner.search.query.assert_not_awaited()
    finally:
        app.state.store.close()


async def test_exhausted_query_allowance_prevents_a_refinement_inference_call(tmp_path):
    app, runner = setup_runner(tmp_path)
    runner.jev.declines_after_search = 1
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            mid = await create_fixture_mission(client, app)
            await runner.bounded_run(mid)
        runner.search.videos.assert_awaited_once()
        assert not any(decision['purpose'] == 'Refine discovery for unanswered questions' for decision in runner.jev.calls)
    finally:
        app.state.store.close()


async def test_steering_reassesses_saved_sources_for_new_program_without_more_acquisition(tmp_path):
    app, runner = setup_runner(tmp_path)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            mid = await create_fixture_mission(client, app)
            await runner.bounded_run(mid)
            old = (await client.get('/api/missions/'+mid)).json()
            response = await client.post('/api/missions/'+mid+'/steer', json={'query': 'Fixture: compare original creators and counterexamples'})
            assert response.status_code == 200
            response = await client.post('/api/missions/'+mid+'/command', json={'action': 'retry', 'idempotency_key': 'fixture-steered-retry'})
            assert response.status_code == 200, response.text
            await runner.tasks[mid]
            revised = (await client.get('/api/missions/'+mid)).json()
        assert revised['status'] == 'partial'
        program = active_program(runner.store, mid)
        assert program['plan_version'] == 2 and program['id'] != old['records']['research_program'][0]['id']
        reassessments = [action for action in revised['records']['action'] if action['kind'] == 'reassess']
        assert len(reassessments) == 2 and all(action['status'] == 'complete' for action in reassessments)
        assert all(action['program_id'] == program['id'] for action in reassessments)
        assert {source['id'] for source in revised['records']['source']} == {source['id'] for source in old['records']['source']}
        assert revised['outcome']['counts']['primary_artifacts'] == 2
        assert revised['outcome']['counts']['supported_findings'] == 2
        assert revised['outcome']['counts']['historical_findings'] == len(old['records']['finding'])
        assert revised['records']['research_analysis'][-1]['program_id'] == program['id']
        assert revised['records']['research_analysis'][-1]['decision_id']
        runner.search.videos.assert_awaited_once()
        assert runner.fetcher.get.await_count == 2
    finally:
        app.state.store.close()


async def test_collection_keeps_the_final_inference_call_for_comparing_two_artifacts(tmp_path):
    app, runner = setup_runner(tmp_path)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            mid = await create_fixture_mission(client, app, limits={'max_pages': 2, 'max_queries': 1, 'max_calls': 8, 'max_depth': 0, 'wall_seconds': 30})
            await runner.bounded_run(mid)
            detail = (await client.get('/api/missions/'+mid)).json()
        assert detail['status'] == 'partial'
        assert detail['outcome']['stop']['code'] == 'comparison_reserved'
        assert detail['outcome']['counts']['primary_artifacts'] == 2
        assert detail['records']['research_analysis'][-1]['decision_id']
        assert detail['telemetry']['attempts'] == 8
        # Grouped selection saves a call, allowing the existing post-comparison
        # experiment prioritizer to use the final allowance. Comparison still
        # must happen before that optional phase and within the hard cap.
        purposes = [decision['purpose'] for decision in runner.jev.calls]
        assert 'Compare observed artifacts' in purposes
        assert purposes.index('Compare observed artifacts') < purposes.index('Prioritize prepared experiments')
        runner.fetcher.get.assert_not_awaited()
    finally:
        app.state.store.close()


async def test_video_route_prefers_capable_provider_even_if_wikipedia_was_selected_first(tmp_path):
    app, runner = setup_runner(tmp_path)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            mid = await create_fixture_mission(client, app, providers=['wikipedia', 'brave'])
            await runner.bounded_run(mid)
            detail = (await client.get('/api/missions/'+mid)).json()
        runner.search.videos.assert_awaited_once()
        runner.search.query.assert_not_awaited()
        assert detail['outcome']['counts']['primary_artifacts'] == 2
    finally:
        app.state.store.close()


async def test_rejected_then_reapproved_source_requires_new_assessment_and_comparison(tmp_path):
    app, runner = setup_runner(tmp_path)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            mid = await create_fixture_mission(client, app)
            await runner.bounded_run(mid)
            before = (await client.get('/api/missions/'+mid)).json()
            source_id = before['records']['source'][0]['id']
            original_comparison = before['records']['research_analysis'][-1]['id']
            for review_round in range(2):
                response = await client.post(f'/api/missions/{mid}/review/{source_id}', json={'state': 'rejected'})
                assert response.status_code == 200
                rejected = (await client.get('/api/missions/'+mid)).json()
                assert rejected['outcome']['counts']['primary_artifacts'] == 1
                assert all(analysis.get('stale') for analysis in rejected['records']['research_analysis'])
                assert all(analysis.get('stale') for analysis in rejected['records']['artifact_analysis'] if analysis['source_id'] == source_id)
                response = await client.post(f'/api/missions/{mid}/review/{source_id}', json={'state': 'approved'})
                assert response.status_code == 200
                approved = (await client.get('/api/missions/'+mid)).json()
                assert approved['outcome']['counts']['primary_artifacts'] == 1
                response = await client.post('/api/missions/'+mid+'/command', json={'action': 'retry', 'idempotency_key': 'fixture-review-retry-'+str(review_round)})
                assert response.status_code == 200, response.text
                await runner.tasks[mid]
                reassessed = (await client.get('/api/missions/'+mid)).json()
                assert reassessed['outcome']['counts']['primary_artifacts'] == 2
                assert reassessed['outcome']['counts']['supported_findings'] == 2
                assert reassessed['records']['research_analysis'][-1]['id'] != original_comparison
                assert reassessed['records']['research_analysis'][-1]['decision_id']
                assert not reassessed['records']['research_analysis'][-1].get('stale')
                tasks = [action for action in reassessed['records']['action'] if action['kind'] == 'reassess' and action['source_id'] == source_id]
                assert len(tasks) == review_round+1 and all(action['status'] == 'complete' for action in tasks)
        runner.search.videos.assert_awaited_once()
        assert runner.fetcher.get.await_count == 2
        assert len([decision for decision in runner.jev.calls if decision['purpose'] == 'Design research approach']) == 1
    finally:
        app.state.store.close()


async def test_secondary_context_can_lead_to_an_observed_original_artifact_without_counting_itself(tmp_path):
    app, runner = setup_runner(tmp_path)
    blog = 'https://example.org/fixture-context'
    video = 'https://www.youtube.com/watch?v=fixturelinked'
    async def fixture_page(url):
        if url == blog:
            body = '<html><head><title>Explicit fixture commentary</title></head><body><main><p>This fixture article is commentary about other videos and cannot count as an inspected video itself. Its concrete link is an observed lead to an original artifact.</p><a href="'+video+'">Original fixture video example</a></main></body></html>'
        else:
            assert url == video
            body = '<html><head><title>Explicit fixture original video</title><script type="application/ld+json">{"@type":"VideoObject","url":"'+video+'","name":"Explicit fixture original video","description":"Fixture publisher description of an original demonstration."}</script></head><body><main><p>Explicit fixture original video with matching publisher metadata. No footage or audio was analyzed.</p></main></body></html>'
        return {'url': url, 'status': 200, 'headers': {'Content-Type': 'text/html'}, 'retrieved_at': now(), 'fetch_ms': 0, 'body': body.encode()}
    runner.fetcher.get = AsyncMock(side_effect=fixture_page)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            mid = await create_fixture_mission(client, app, seeds=[blog], providers=['seed'],
                                               limits={'max_pages': 2, 'max_queries': 0, 'max_calls': 15, 'max_depth': 1, 'wall_seconds': 30})
            await runner.bounded_run(mid)
            detail = (await client.get('/api/missions/'+mid)).json()
        assert detail['status'] == 'partial'
        sources = {source['url']: source for source in detail['records']['source']}
        assert set(sources) == {blog, video}
        assert sources[blog]['research_role'] == 'secondary_commentary'
        assert sources[video]['source_kind'] == 'video'
        assert detail['outcome']['counts']['primary_artifacts'] == 1
        followed = next(action for action in detail['records']['action'] if action['value'] == video)
        assert followed['parent'] == sources[blog]['id'] and followed['depth'] == 1
        assert followed['artifact_lead'] is True
        assert followed['status'] == 'complete'
        assert runner.fetcher.get.await_count == 2
        runner.search.videos.assert_not_awaited()
    finally:
        app.state.store.close()


def test_adaptive_outbound_candidates_are_bounded_observed_links_for_general_goals(tmp_path):
    app, runner = setup_runner(tmp_path)
    try:
        source = {'url': 'https://example.org/context', 'links': [
            {'url': f'https://source{index}.example.org/original', 'label': 'Original database evidence '+str(index)} for index in range(10)]}
        source['links'].insert(0, {'url': 'http://127.0.0.1/private', 'label': 'Original database evidence'})
        plan = {'goal': 'Compare original database implementations', 'providers': ['seed'], '_program': {'unit': 'technical_artifacts'}}
        links = runner.outbound_candidates(source, plan)
        assert len(links) == 6
        assert all(link in source['links'] and not link['url'].startswith('http://127.') for link in links)
    finally:
        app.state.store.close()


async def test_context_feedback_selects_web_leads_then_follows_an_actual_original_video(tmp_path):
    app, runner = setup_runner(tmp_path)
    runner.jev.context_title_marker = 'Context fixture'
    runner.jev.refinement_choice = 'q3'
    lead = 'https://example.org/fixture-original-video-references'
    original = 'https://www.youtube.com/watch?v=originalfixture'
    observed = video_observation()
    for item in observed['results']:
        item['title'] = 'Context fixture: advice about publishing viral videos'
    runner.search.videos = AsyncMock(return_value=observed)
    runner.search.query = AsyncMock(return_value={
        'id': uid(), 'provider': 'brave', 'query': 'Fixture web leads', 'timestamp': now(), 'latency_ms': 0,
        'scope': 'Explicit fixture web search, used only for original-artifact leads',
        'results': [{'id': uid(), 'position': 1, 'url': lead, 'title': 'Fixture original-video references', 'snippet': 'Links to original examples.'}],
    })
    async def fixture_page(url):
        if url == lead:
            body = '<html><head><title>Fixture reference list</title></head><body><main><p>Explicit fixture list that is context only.</p><a href="'+original+'">Original fixture video</a></main></body></html>'
        elif url == original:
            body = '<html><head><title>Fixture original demonstration</title><script type="application/ld+json">{"@type":"VideoObject","url":"'+original+'","name":"Fixture original demonstration","description":"Explicit fixture original artifact metadata."}</script></head><body><main><p>Fixture original video page with matching publisher metadata. No footage was watched.</p></main></body></html>'
        else:
            raise PolicyError('Explicit fixture original page access block')
        return {'url': url, 'status': 200, 'headers': {'Content-Type': 'text/html'}, 'retrieved_at': now(), 'fetch_ms': 0, 'body': body.encode()}
    runner.fetcher.get = AsyncMock(side_effect=fixture_page)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            mid = await create_fixture_mission(client, app, limits={'max_pages': 4, 'max_queries': 2, 'max_calls': 30, 'max_depth': 1, 'wall_seconds': 30})
            await runner.bounded_run(mid)
            detail = (await client.get('/api/missions/'+mid)).json()
        assert detail['status'] == 'partial'
        runner.search.videos.assert_awaited_once()
        runner.search.query.assert_awaited_once()
        assert runner.search.query.call_args.args[1] == 'brave'
        decision = next(item for item in runner.jev.calls if item['purpose'] == 'Refine discovery for unanswered questions')
        assert decision['state']['primary_artifacts'] == 0
        assert len(decision['state']['observed_roles']) == 2
        assert all(item['role'] == 'secondary_commentary' for item in decision['state']['observed_roles'])
        chosen = decision['state']['prepared_refinements']['q3']
        assert chosen['search_kind'] == 'web_leads'
        assert runner.search.query.call_args.args[0] == chosen['query']
        assert 'list itself never counts' in decision['questions']['refine_query']['criteria']['q3']
        assert len([event for event in detail['events'] if event['type'] == 'research.refinement_triggered']) == 1
        sources = {source['url']: source for source in detail['records']['source']}
        assert sources[lead]['research_role'] == 'secondary_commentary'
        assert sources[original]['research_role'] == 'primary_artifact'
        assert detail['outcome']['counts']['primary_artifacts'] == 1
        assert any(action['value'] == original and action['parent'] == sources[lead]['id'] and action['status'] == 'complete' for action in detail['records']['action'])
    finally:
        app.state.store.close()


async def test_exhausted_deferred_queue_can_use_remaining_query_budget_for_a_new_route(tmp_path):
    app, runner = setup_runner(tmp_path)
    runner.jev.declines_after_search = 1
    runner.jev.refinement_choices = ['q0', 'q3']
    # The second index request repeats exactly the declined URLs, creating no
    # unexamined actions. The queue-empty branch must offer another refinement.
    runner.search.query = AsyncMock(return_value={'id': uid(), 'provider': 'brave', 'query': 'Fixture empty web leads',
                                                 'timestamp': now(), 'latency_ms': 0, 'scope': 'Explicit fixture', 'results': []})
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            mid = await create_fixture_mission(client, app, limits={'max_pages': 2, 'max_queries': 3, 'max_calls': 15, 'max_depth': 1, 'wall_seconds': 30})
            await runner.bounded_run(mid)
            detail = (await client.get('/api/missions/'+mid)).json()
        assert detail['status'] == 'partial'
        assert runner.search.videos.await_count == 2
        runner.search.query.assert_awaited_once()
        assert detail['telemetry']['search_attempts'] == 3
        assert len([event for event in detail['events'] if event['type'] == 'research.refined']) == 2
        assert not detail['records'].get('source')
        assert detail['outcome']['counts']['primary_artifacts'] == 0
    finally:
        app.state.store.close()


def test_canonical_video_aliases_share_page_and_domain_allowances(tmp_path):
    app, runner = setup_runner(tmp_path)
    try:
        sources = [{'url': 'https://www.youtube.com/watch?v=fixtureaaa', 'requested_url': 'https://youtu.be/fixtureaaa'},
                   {'url': 'https://www.youtube.com/watch?v=fixtureaaa&app=desktop', 'requested_url': 'https://www.youtube.com/watch?v=fixtureaaa'}]
        plan = {'excluded_domains': [], 'limits': {'max_pages': 2, 'per_domain': 2, 'max_depth': 1}}
        second = {'kind': 'fetch', 'value': 'https://www.youtube.com/watch?v=fixturebbb', 'depth': 0}
        assert runner.allowable(second, plan, sources, [])
        plan['limits']['max_pages'] = 1
        assert not runner.allowable(second, plan, sources, [])
        assert runner.allowable({**second, 'value': 'https://www.youtube.com/watch?v=fixtureaaa&feature=share'}, plan, sources, [])
        plan['limits'].update(max_pages=5, per_domain=1)
        assert not runner.allowable(second, plan, sources, [])
    finally:
        app.state.store.close()


def test_observed_artifact_leads_reach_jev_batch_ahead_of_generic_host_backlog(tmp_path):
    app, runner = setup_runner(tmp_path)
    try:
        generic = [{'id': 'generic'+str(index), 'kind': 'fetch', 'value': f'https://source{index}.example.org/context'} for index in range(35)]
        leads = [{'id': 'lead'+str(index), 'kind': 'fetch', 'value': 'https://www.youtube.com/watch?v=fixturelead'+str(index), 'artifact_lead': True} for index in range(6)]
        refinement = {'id': 'refinement', 'kind': 'search', 'value': 'Explicit fixture original-artifact query',
                      'decision_id': 'fixture-recorded-selection', 'discovery_refinement': True}
        batch = runner.candidate_batch(generic+leads+[refinement], [{'url': 'https://www.youtube.com/watch?v=fixturecontext'}])
        assert len(batch) == 16 and batch[0] == refinement
        assert batch[1:7] == leads
        assert batch[7:] == generic[:9]
        assert all('decision_id' not in lead for lead in leads)  # code offers candidates; it does not select them for Jev
    finally:
        app.state.store.close()


async def test_newly_observed_artifact_link_promotes_an_existing_queued_url_without_duplicating_it(tmp_path):
    app, runner = setup_runner(tmp_path)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            mid = await create_fixture_mission(client, app)
        url = 'https://www.youtube.com/watch?v=fixturelead'
        runner.add_action(mid, 'fetch', url, 'fixture-search-id', description='Ordinary search result')
        first = runner.store.records(mid, 'action')[0]
        runner.add_action(mid, 'fetch', url, 'fixture-context-source', depth=1, description='Observed original-artifact reference', artifact_lead=True)
        actions = runner.store.records(mid, 'action')
        assert len(actions) == 1 and actions[0]['id'] == first['id']
        assert actions[0]['artifact_lead'] is True
        assert actions[0]['parent'] == 'fixture-search-id'
        assert actions[0]['lead_source_id'] == 'fixture-context-source'
        assert 'decision_id' not in actions[0]
    finally:
        app.state.store.close()
