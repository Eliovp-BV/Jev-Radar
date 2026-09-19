"""Optional text-model UI regression. Synthetic temporary data; zero external calls."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import socket
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import httpx
import uvicorn
from playwright.async_api import async_playwright, expect
from radar.api import create_app
from radar.config import ROOT, Settings
from radar.storage import now
from radar.synthesis import _snapshot, current_brief


async def main():
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / '.cache/ms-playwright')
    runtime = ROOT / '.runtime'
    screenshots = runtime / 'screenshots'
    screenshots.mkdir(parents=True, exist_ok=True)
    data = Path(tempfile.mkdtemp(prefix='text-ui-fixture-', dir=runtime))
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    app = create_app(Settings(data_dir=data, host='127.0.0.1', port=port,
        key='synthetic-fixture', brave_key='synthetic-fixture', openai_key='synthetic-fixture',
        gemini_key='synthetic-fixture', anthropic_key='synthetic-fixture', openrouter_key='synthetic-fixture',
        text_model_key='synthetic-fixture', text_model_base_url='https://fixture.example/v1'))
    store = app.state.store
    identifiers, errors, forbidden_calls, mock_tests = {}, [], [], []
    goal = 'Synthetic fixture only: compare collaboration products and suggest useful improvements.'
    text_call = {'id': 'fixture-text', 'provider': 'fixture', 'model': 'synthetic-text-fixture',
        'purpose': 'Propose goal-specific research questions', 'status': 'inflight', 'provenance': 'fixture'}

    def emit(kind, records=(), status=None, **payload):
        store.mutate(identifiers['mid'], kind, {'fixture_notice': 'Synthetic UI fixture; no external request', **payload},
                     records, status=status, mode='fixture')

    def launch(mid):
        identifiers['mid'] = mid
        store.execute("UPDATE missions SET mode='fixture' WHERE id=?", (mid,))
        emit('text.started', [('text_call', text_call)], call_id=text_call['id'])

    def forbidden(*args, **kwargs):
        forbidden_calls.append('unexpected external provider access')
        raise AssertionError('UI fixture must not call external providers')

    async def forbidden_async(*args, **kwargs):
        forbidden()

    def mock_provider(request):
        # The real adapter and endpoint are exercised against a local mock transport.
        # Request headers/body are never printed or retained in the report.
        mock_tests.append('local mock transport only')
        if request.url.host == 'generativelanguage.googleapis.com':
            assert request.headers.get('x-goog-api-key') == 'synthetic-fixture'
            assert 'key=' not in str(request.url)
            return httpx.Response(200, json={'modelVersion': 'gemini-3.8-flash',
                'candidates': [{'finishReason': 'STOP', 'content': {'role': 'model',
                    'parts': [{'text': '{"status":"connected"}'}]}}],
                'usageMetadata': {'promptTokenCount': 12, 'candidatesTokenCount': 5,
                                  'thoughtsTokenCount': 9, 'totalTokenCount': 26}})
        return httpx.Response(200, json={'model': 'synthetic-text-fixture',
            'choices': [{'finish_reason': 'stop', 'message': {'content': '{"status":"connected"}'}}],
            'usage': {'prompt_tokens': 12, 'completion_tokens': 5}})

    app.state.runner.launch = launch
    app.state.runner.jev.client = forbidden
    app.state.runner.search.query = forbidden_async
    app.state.runner.fetcher.get = forbidden_async
    app.state.text_model.client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(mock_provider))
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error', access_log=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        for _ in range(50):
            if server.started:
                break
            await asyncio.sleep(.1)
        assert server.started
        base = f'http://127.0.0.1:{port}'
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True, chromium_sandbox=True)
            page = await browser.new_page(viewport={'width': 1500, 'height': 1050})
            page.on('pageerror', lambda error: errors.append(str(error)))
            async def reload_fixture_keys(route):
                # Exercise the browser reload flow without reading the operator's .env.
                response = await page.request.get(base + '/api/settings')
                await route.fulfill(status=200, json=await response.json())
            await page.route('**/api/settings/reload', reload_fixture_keys)
            await page.goto(base)
            await expect(page.get_by_role('heading', name='What are you looking for?', exact=True)).to_be_visible()
            await page.get_by_role('button', name='Workspace settings', exact=True).click()
            await page.get_by_role('tab', name='Spend limits', exact=True).click()
            spending = page.get_by_role('region', name='Spend limits', exact=True)
            await expect(spending.get_by_label('Jev allowance (USD)', exact=True)).to_have_value('5')
            await expect(spending.get_by_label('LLM allowance (USD)', exact=True)).to_have_value('20')
            await spending.get_by_label('Jev allowance (USD)', exact=True).fill('7')
            await spending.get_by_label('LLM allowance (USD)', exact=True).fill('25')
            await spending.get_by_role('button', name='Save spend limits', exact=True).click()
            await expect(page.locator('.alert')).to_contain_text('Spend limits saved')
            assert store.setting('research_defaults')['limits']['usd'] == 7
            assert store.setting('text_model')['usd'] == 25
            await spending.get_by_label('Jev allowance (USD)', exact=True).fill('5')
            await spending.get_by_label('LLM allowance (USD)', exact=True).fill('20')
            await spending.get_by_role('button', name='Save spend limits', exact=True).click()
            await page.screenshot(path=str(screenshots / 'spend-limits-settings-fixture.png'))
            await page.set_viewport_size({'width': 430, 'height': 932})
            assert not await page.evaluate('document.documentElement.scrollWidth > innerWidth')
            await page.set_viewport_size({'width': 1500, 'height': 1050})
            await page.get_by_role('tab', name='API connections', exact=True).click()
            panel = page.get_by_role('region', name='Text model connection', exact=True)
            provider = panel.get_by_role('combobox', name='Text model provider', exact=True)
            model = panel.get_by_role('textbox', name='Text model name', exact=True)
            await expect(provider.locator('option')).to_have_count(6)
            await provider.select_option('openai')
            await model.fill('synthetic-openai-fixture')
            await panel.locator('summary', has_text='Model prices, limits').click()
            await panel.get_by_label('Text input price per million tokens', exact=True).fill('1')
            await panel.get_by_label('Text output price per million tokens', exact=True).fill('2')
            await expect(panel).to_contain_text('OPENAI_API_KEY=your_provider_key')
            await expect(panel.get_by_role('button', name='Test text model', exact=True)).to_be_disabled()
            await panel.get_by_role('button', name='Save text model', exact=True).click()
            await expect(panel.get_by_role('button', name='Test text model', exact=True)).to_be_enabled()
            await provider.select_option('anthropic')
            await model.fill('synthetic-anthropic-fixture')
            await panel.get_by_label('Text input price per million tokens', exact=True).fill('1')
            await panel.get_by_label('Text output price per million tokens', exact=True).fill('2')
            await expect(panel).to_contain_text('ANTHROPIC_API_KEY=your_provider_key')
            await panel.get_by_role('button', name='Save text model', exact=True).click()
            await expect(panel.get_by_role('button', name='Test text model', exact=True)).to_be_enabled()
            await provider.select_option('gemini')
            await expect(model).to_have_value('gemini-3.8-flash')
            await expect(panel).to_contain_text('GEMINI_API_KEY=your_provider_key')
            await expect(panel).to_contain_text('GOOGLE_API_KEY')
            await expect(panel.get_by_role('link', name='Google AI Studio')).to_have_attribute('href', 'https://aistudio.google.com/apikey')
            await expect(panel.get_by_label('Text input price per million tokens', exact=True)).to_have_value('')
            await panel.get_by_role('button', name='Save text model', exact=True).click()
            await expect(panel.get_by_role('button', name='Test text model', exact=True)).to_be_enabled()
            assert 'gemini:gemini-3.8-flash' not in store.setting('text_model')['prices']
            assert not mock_tests and not forbidden_calls
            await panel.get_by_role('button', name='Test text model', exact=True).click()
            await expect(panel.locator('.connection-last')).to_contain_text('succeeded')
            assert len(mock_tests) == 1
            await panel.screenshot(path=str(screenshots / 'gemini-settings-fixture.png'))
            await page.set_viewport_size({'width': 430, 'height': 932})
            assert not await page.evaluate('document.documentElement.scrollWidth > innerWidth')
            await page.set_viewport_size({'width': 1500, 'height': 1050})
            await provider.select_option('openrouter')
            await expect(panel).to_contain_text('OPENROUTER_API_KEY=your_provider_key')
            await provider.select_option('compatible')
            await expect(panel).to_contain_text('TEXT_MODEL_BASE_URL=https://your-provider.example/v1')
            await model.fill('synthetic-compatible-fixture')
            await page.get_by_role('button', name='Reload keys', exact=True).click()
            await expect(page.locator('.alert')).to_contain_text('Both keys are configured')
            await expect(provider).to_have_value('compatible')
            await expect(model).to_have_value('synthetic-compatible-fixture')
            await provider.select_option('openai')
            await expect(model).to_have_value('synthetic-openai-fixture')
            await panel.get_by_role('button', name='Save text model', exact=True).click()
            await expect(panel.get_by_role('button', name='Test text model', exact=True)).to_be_enabled()
            assert len(mock_tests) == 1 and not forbidden_calls
            await panel.get_by_role('button', name='Test text model', exact=True).click()
            await expect(panel.locator('.connection-last')).to_contain_text('succeeded')
            assert len(mock_tests) == 2
            assert not await panel.locator('input[type=password]').count()
            await panel.screenshot(path=str(screenshots / 'text-provider-settings-fixture.png'))
            await page.set_viewport_size({'width': 430, 'height': 932})
            assert not await page.evaluate('document.documentElement.scrollWidth > innerWidth')
            await page.get_by_role('button', name='Close dialog', exact=True).click()
            await page.set_viewport_size({'width': 1500, 'height': 1050})
            await page.get_by_role('textbox', name='Research goal', exact=True).fill(goal)
            await page.get_by_role('button', name='Start research', exact=True).click()
            stage = page.get_by_role('region', name='Jev live research', exact=True)
            await expect(stage).to_have_attribute('data-phase', 'proposing')
            await expect(stage).to_contain_text('Fixture · recorded test data')
            await expect(stage.get_by_label('Text model activity')).to_contain_text('Waiting for provider')
            await expect(stage.locator('.jev-stage-timing')).to_contain_text('Waiting for first measured response')
            await page.screenshot(path=str(screenshots / 'text-proposal-live-fixture.png'), full_page=True)
            text_call.update(status='complete', latency_ms=17)
            emit('text.completed', [('text_call', text_call)], call_id=text_call['id'], latency_ms=17)
            plan = store.mission(identifiers['mid'])['plan']
            criterion = next((item for item in plan['criteria'] if item['id'] == 'capabilities'), plan['criteria'][0])
            quote = 'Synthetic Product documents offline storage and team access controls.'
            source = {'id': 'fixture-source', 'url': 'https://product.example/docs', 'title': 'Synthetic Product documentation',
                'text': quote, 'entity_id': 'fixture-entity', 'retrieved_at': now(), 'review': 'unreviewed',
                'content_hash': 'fixture-hash', 'chunks': [{'start': 0, 'end': len(quote), 'text': quote}],
                'coverage': {'analyzed_chunks': 1, 'total_chunks': 1, 'method': 'Synthetic public passage fixture',
                    'blocked_sections': '', 'truncated': False}}
            span = {'id': 'fixture-span', 'source_id': source['id'], 'start': 0, 'end': len(quote), 'text': quote}
            finding = {'id': 'fixture-finding', 'entity_id': source['entity_id'], 'source_ids': [source['id']], 'span_ids': [span['id']],
                'subject': source['title'], 'criterion_id': criterion['id'], 'question': criterion['question'],
                'status': 'supported', 'review': 'unreviewed', 'rubric_version': 1, 'statement': quote,
                'scope': 'Synthetic publisher documentation only', 'evidence_kind': 'publisher_claim', 'limitations': []}
            entity = {'id': source['entity_id'], 'name': 'Synthetic Product', 'domains': ['product.example'],
                'source_ids': [source['id']], 'review': 'unreviewed', 'classification': 'candidate', 'fields': {}}
            emit('assessment.recorded', [('source', source), ('span', span), ('finding', finding), ('entity', entity)])
            decision = {'id': 'fixture-verification', 'purpose': 'Check proposed answer against cited evidence',
                'status': 'inflight', 'cache': False, 'model': 'synthetic-jev-fixture', 'questions': {
                    'claim': {'type': 'choice', 'instructions': 'Check the supplied synthetic claim against its synthetic passage.',
                        'criteria': {'supported': 'Supported by the provided passage', 'unsupported': 'Not established'}}}, 'answers': {}}
            emit('jev.started', [('decision', decision)], decision_id=decision['id'])
            await expect(stage).to_have_attribute('data-phase', 'verifying')
            await expect(stage.get_by_label('Text model activity')).to_contain_text('17 ms')
            await expect(stage.locator('.jev-stage-timing')).to_contain_text('Waiting for first measured response')
            decision.update(status='complete', cache=True, answers={'claim': {'choice': 'supported'}})
            emit('jev.completed', [('decision', decision)], decision_id=decision['id'])
            citation = {'finding_id': finding['id'], 'span_id': span['id'], 'source_id': source['id'],
                'url': source['url'], 'quote': quote, 'start': 0, 'end': len(quote)}
            claim = {'id': 'fixture-claim', 'text': 'Synthetic Product documents offline storage.', 'kind': 'observation',
                'status': 'supported', 'citations': [citation], 'decision_id': decision['id']}
            brief = {'id': 'fixture-brief', 'status': 'partial', 'plan_version': 1, 'program_id': None,
                'evidence_fingerprint': _snapshot(store, identifiers['mid'], plan)['fingerprint'],
                'claims': [claim, {**claim, 'id': 'fixture-hypothesis', 'text': 'Offline support may fit traveling teams; demand is unmeasured.',
                    'kind': 'hypothesis', 'status': 'qualified'}, {**claim, 'id': 'fixture-unsupported',
                    'text': 'UNSUPPORTED TEXT MUST STAY HIDDEN', 'status': 'unsupported'}],
                'recommendations': [{'id': 'fixture-recommendation', 'text': 'Interview team members about their offline workflow.',
                    'claim_ids': ['fixture-hypothesis'], 'status': 'proposed', 'performed': False}],
                'unknowns': ['Independent performance and user demand were not measured.'],
                'text_call_id': text_call['id'], 'verification_decision_id': decision['id'],
                'provenance': {'provider': 'fixture', 'model': 'synthetic-text-fixture', 'latency_ms': 17},
                'unsupported_claim_count': 1, 'created_at': now()}
            emit('research.brief_completed', [('research_brief', brief)], status='partial')
            assert current_brief(store, identifiers['mid'])
            await page.get_by_role('button', name='Results', exact=True).click()
            answer = page.get_by_role('region', name='Evidence-linked research answer', exact=True)
            await expect(answer).to_be_visible(timeout=10000)
            await expect(answer).to_contain_text('Synthetic Product documents offline storage.')
            await expect(answer).to_contain_text('Possible explanation')
            await expect(answer).to_contain_text('These actions have not been performed')
            await expect(answer).to_contain_text('1 unsupported claim withheld')
            await expect(answer).not_to_contain_text('UNSUPPORTED TEXT MUST STAY HIDDEN')
            await answer.locator('.brief-citations > summary').first.click()
            await answer.get_by_role('button', name='Inspect source & finding', exact=True).first.click()
            await expect(page.get_by_role('dialog')).to_contain_text(quote)
            await page.keyboard.press('Escape')
            await answer.get_by_role('button', name='Inspect answer check', exact=True).click()
            await expect(page.get_by_role('dialog')).to_contain_text('Check proposed answer against cited evidence')
            await page.keyboard.press('Escape')
            await page.screenshot(path=str(screenshots / 'text-research-answer-fixture.png'), full_page=True)
            await page.set_viewport_size({'width': 430, 'height': 932})
            assert not await page.evaluate('document.documentElement.scrollWidth > innerWidth')
            await page.screenshot(path=str(screenshots / 'text-research-answer-mobile-fixture.png'), full_page=True)
            session = await (await page.request.get(base + '/api/session')).json()
            response = await page.request.post(base + '/api/missions/' + identifiers['mid'] + '/review/' + finding['id'],
                headers={'X-Radar-CSRF': session['csrf']}, data={'state': 'rejected', 'note': 'Synthetic UI rejection fixture'})
            assert response.ok, await response.text()
            await expect(answer).to_have_count(0)
            assert current_brief(store, identifiers['mid']) is None
            assert len(mock_tests) == 2 and not forbidden_calls and not errors
            report = {'mode': 'synthetic UI fixtures and two local mock transport responses; no external calls',
                'spend_defaults_jev5_text20': True, 'separate_spend_limits_persist': True,
                'provider_options': 6, 'gemini_native_connection_test': True, 'automatic_prices_remain_automatic': True, 'provider_models_persist': True, 'reload_preserves_unsaved_provider_choice': True, 'configuration_makes_no_inference': True,
                'explicit_connection_test_only': True, 'no_browser_key_entry': True,
                'text_requests_visible_separately_from_jev': True, 'text_latency_not_counted_as_jev': True,
                'checked_answer_and_citation_inspected': True, 'unsupported_claim_hidden': True,
                'hypotheses_and_unperformed_recommendations_labeled': True,
                'rejected_evidence_hides_answer': True, 'mobile_overflow': False, 'javascript_errors': errors}
            (runtime / 'ui-text-model-smoke.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(report, indent=2))
            await browser.close()
    finally:
        server.should_exit = True
        await asyncio.to_thread(thread.join, 5)
        if thread.is_alive():
            server.force_exit = True
            await asyncio.to_thread(thread.join, 3)
        store.close()
        sock.close()
        shutil.rmtree(data, ignore_errors=True)


if __name__ == '__main__':
    asyncio.run(main())
