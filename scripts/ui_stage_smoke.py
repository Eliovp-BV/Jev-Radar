"""Direct-start live-stage UI regression using isolated, explicit fixtures.

No public website, search or model provider is called. A controlled synthetic
runner writes ordinary backend records/events so SSE, projections and replay
use their real implementations. Fixture decisions carry no measured latency.
"""
import asyncio
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sys
import tempfile
import threading

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import uvicorn
from playwright.async_api import async_playwright, expect
from radar.api import create_app
from radar.config import ROOT, Settings
from radar.storage import now


class FixtureProgress:
    """Advance a synthetic run deliberately between browser assertions."""

    def __init__(self, store):
        self.store = store
        self.mid = None
        self.query = 'fixture collaboration software comparison'
        self.text = 'Synthetic UI fixture: Example Studio provides document search for small teams.'
        self.search_action = {'id': 'fixture-search-action', 'kind': 'search', 'value': self.query,
                              'status': 'running', 'depth': 0}
        self.fetch_action = {'id': 'fixture-fetch-action', 'kind': 'fetch', 'value': 'https://example.com/',
                             'status': 'queued', 'depth': 0}
        self.search_attempt = {'id': 'fixture-search-attempt', 'action_id': self.search_action['id'],
                               'provider': 'fixture-search', 'query': self.query, 'status': 'running'}
        self.decision = None
        self.source = None

    def emit(self, kind, payload, records=(), status=None):
        self.store.mutate(self.mid, kind, {'fixture_notice': 'Synthetic UI fixture; no provider call', **payload},
                          records, status=status, mode='fixture')

    def launch(self, mid):
        assert self.mid is None, 'Fixture must start only once'
        self.mid = mid
        self.store.execute("UPDATE missions SET mode='fixture' WHERE id=?", (mid,))
        self.emit('action.started', {'action_id': self.search_action['id'], 'kind': 'search', 'value': self.query},
                  [('action', self.search_action)])
        self.emit('search.started', {'attempt_id': self.search_attempt['id'], 'action_id': self.search_action['id']},
                  [('search_attempt', self.search_attempt)])

    def choose_source(self):
        self.search_action = {**self.search_action, 'status': 'complete'}
        self.search_attempt = {**self.search_attempt, 'status': 'complete', 'search_id': 'fixture-search-response'}
        search = {'id': 'fixture-search-response', 'provider': 'fixture-search', 'query': self.query,
                  'timestamp': now(), 'language': 'en', 'region_requested': '',
                  'scope': 'Synthetic result set; no actual search engine response',
                  'results': [{'id': 'fixture-result', 'url': self.fetch_action['value'],
                               'title': 'Example Studio · synthetic fixture', 'snippet': self.text, 'position': 1}]}
        self.emit('search.finished', {'search_id': search['id'], 'action_id': self.search_action['id']},
                  [('action', self.search_action), ('action', self.fetch_action), ('search_attempt', self.search_attempt), ('search', search)])
        self.decision = {'id': 'fixture-next-decision', 'created_at': now(), 'purpose': 'Select next research action',
                         'status': 'inflight', 'cache': False, 'requested_model': 'synthetic-fixture',
                         'latency_ms': None, 'queue_ms': None,
                         'questions': {'next': {'type': 'choice', 'instructions': 'Which prepared source addresses the fixture question?',
                                               'criteria': {self.fetch_action['id']: 'Read Example Studio · synthetic fixture',
                                                            'stop': 'No useful prepared action'}}}, 'answers': {}}
        self.emit('jev.started', {'decision_id': self.decision['id']}, [('decision', self.decision)])

    def read_source(self):
        # Cache-marking prevents synthetic values from being counted as measured
        # live calls. This is only a browser fixture, never an SDK response.
        self.decision = {**self.decision, 'status': 'complete', 'cache': True, 'model': 'synthetic-fixture',
                         'answers': {'next': {'type': 'choice', 'choice': self.fetch_action['id'],
                                              'confidence': None, 'probabilities': {}}}}
        self.fetch_action = {**self.fetch_action, 'status': 'running'}
        self.emit('jev.completed', {'decision_id': self.decision['id']}, [('decision', self.decision)])
        self.emit('action.started', {'action_id': self.fetch_action['id'], 'kind': 'fetch', 'value': self.fetch_action['value']},
                  [('action', self.fetch_action)])

    def inspect_source(self):
        self.fetch_action = {**self.fetch_action, 'status': 'complete'}
        self.source = {'id': 'fixture-source', 'url': self.fetch_action['value'], 'requested_url': self.fetch_action['value'],
                       'title': 'Example Studio · synthetic fixture', 'text': self.text, 'content_hash': 'synthetic-fixture-hash',
                       'retrieved_at': now(), 'source_date': None, 'source_date_provenance': 'unknown',
                       'status_code': 200, 'cache': False, 'depth': 0, 'action_id': self.fetch_action['id'],
                       'discovered_via': 'fixture-search-response', 'role': 'candidate', 'entity_type': 'software',
                       'classification': 'alternative', 'entity_id': 'fixture-entity',
                       'coverage': {'analyzed_chunks': 1, 'total_chunks': 1, 'method': 'HTTP text · synthetic fixture',
                                    'blocked_sections': '', 'truncated': False},
                       'chunks': [{'start': 0, 'end': len(self.text), 'text': self.text, 'kind': 'paragraph'}]}
        self.emit('source.recorded', {'source_id': self.source['id']}, [('source', self.source), ('action', self.fetch_action)])
        self.decision = {'id': 'fixture-assessment', 'created_at': now(), 'purpose': 'Assess source against the research goal',
                         'status': 'inflight', 'cache': False, 'requested_model': 'synthetic-fixture',
                         'source_id': self.source['id'], 'latency_ms': None, 'queue_ms': None,
                         'questions': {'relevance': {'type': 'score', 'instructions': 'Does the fixture page address document search?',
                                                    'criteria': ['Unrelated', 'Context only', 'Directly relevant']}}, 'answers': {}}
        self.emit('jev.started', {'decision_id': self.decision['id'], 'source_id': self.source['id']}, [('decision', self.decision)])

    def check_passage(self):
        self.decision = {**self.decision, 'status': 'complete', 'cache': True, 'model': 'synthetic-fixture',
                         'answers': {'relevance': {'type': 'score', 'score': 2, 'confidence': None, 'probabilities': {}}}}
        self.emit('assessment.recorded', {'decision_id': self.decision['id'], 'source_id': self.source['id']}, [('decision', self.decision)])
        passage = {'id': 'fixture-passage-choice', 'created_at': now(), 'purpose': 'Select supporting passages',
                   'status': 'complete', 'cache': True, 'model': 'synthetic-fixture', 'source_id': self.source['id'],
                   'latency_ms': None, 'queue_ms': None,
                   'questions': {'span_capabilities': {'type': 'choice', 'instructions': 'Which existing passage states a capability?',
                                                      'criteria': {'p0': self.text, 'unknown': 'No supplied passage'}}},
                   'answers': {'span_capabilities': {'type': 'choice', 'choice': 'p0', 'probabilities': {}, 'confidence': None}}}
        self.emit('jev.completed', {'decision_id': passage['id']}, [('decision', passage)])
        self.decision = {'id': 'fixture-verification', 'created_at': now(), 'purpose': 'Verify selected evidence',
                         'status': 'inflight', 'cache': False, 'requested_model': 'synthetic-fixture',
                         'source_id': self.source['id'], 'latency_ms': None, 'queue_ms': None,
                         'questions': {'capabilities': {'type': 'choice', 'instructions': 'Does the excerpt explicitly describe document search?',
                                                       'criteria': {'supported': 'Explicit in the provided fixture passage',
                                                                    'unknown': 'Not established by this passage'}}}, 'answers': {}}
        self.emit('jev.started', {'decision_id': self.decision['id']}, [('decision', self.decision)])

    def save_finding(self):
        self.decision = {**self.decision, 'status': 'complete', 'cache': True, 'model': 'synthetic-fixture',
                         'answers': {'capabilities': {'type': 'choice', 'choice': 'supported', 'probabilities': {}, 'confidence': None}}}
        span = {'id': 'fixture-span', 'source_id': self.source['id'], 'start': 0, 'end': len(self.text),
                'text': self.text, 'anchor': 'fixture', 'provenance': 'Synthetic UI regression fixture'}
        finding = {'id': 'fixture-finding', 'subject': self.source['title'], 'entity_id': 'fixture-entity',
                   'criterion_id': 'capabilities', 'question': 'What capability is explicitly stated?',
                   'statement': self.text, 'status': 'supported', 'source_ids': [self.source['id']],
                   'span_ids': [span['id']], 'decision_id': self.decision['id'], 'review': 'unreviewed',
                   'evidence_kind': 'synthetic UI fixture', 'scope': 'Fixture only; no real company claim.',
                   'rubric_version': 1, 'retrieved_at': self.source['retrieved_at'], 'limitations': ['Synthetic data, not research evidence']}
        entity = {'id': 'fixture-entity', 'name': self.source['title'], 'domains': ['example.com'],
                  'source_ids': [self.source['id']], 'classification': 'alternative', 'entity_type': 'software',
                  'role': 'candidate', 'review': 'unreviewed',
                  'fields': {'capabilities': {'finding_id': finding['id'], 'source_id': self.source['id'], 'status': 'supported', 'value': self.text}}}
        self.emit('jev.completed', {'decision_id': self.decision['id']}, [('decision', self.decision)])
        self.emit('finding.recorded', {'source_id': self.source['id'], 'decision_id': self.decision['id']},
                  [('span', span), ('finding', finding), ('entity', entity)])


async def main():
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / '.cache/ms-playwright')
    runtime = ROOT / '.runtime'
    screenshots = runtime / 'screenshots'
    screenshots.mkdir(parents=True, exist_ok=True)
    data = Path(tempfile.mkdtemp(prefix='stage-ui-fixture-', dir=runtime))
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    app = create_app(Settings(data_dir=data, host='127.0.0.1', port=port,
                              key='synthetic-fixture-not-a-key', brave_key='synthetic-fixture-not-a-search-key'))
    store = app.state.store
    store.set_setting('profile', {'name': 'Radar · synthetic stage fixture', 'accent': '#f1d54a', 'retention_days': 30})
    progress = FixtureProgress(store)
    app.state.runner.launch = progress.launch
    provider_calls, errors = [], []

    def forbidden(*args, **kwargs):
        provider_calls.append('forbidden provider')
        raise AssertionError('Synthetic stage regression must never call a provider')

    async def forbidden_async(*args, **kwargs):
        forbidden()

    app.state.runner.jev.client = forbidden
    app.state.runner.search.query = forbidden_async
    app.state.runner.fetcher.get = forbidden_async
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error',
                                         access_log=False, timeout_graceful_shutdown=2))
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
            page = await browser.new_page(viewport={'width': 1440, 'height': 1000}, reduced_motion='no-preference')
            page.on('pageerror', lambda error: errors.append(str(error)))
            mutations = []
            page.on('request', lambda request: mutations.append(request.url)
                    if request.method not in ('GET', 'HEAD', 'OPTIONS') else None)
            await page.goto(base)
            await expect(page.get_by_role('heading', name='What are you looking for?', exact=True)).to_be_visible()
            await expect(page.get_by_role('button', name='Review research plan', exact=True)).to_be_hidden()
            await page.get_by_role('textbox', name='Research goal', exact=True).fill('Fixture only: compare collaboration tools and their document search capabilities.')
            await page.get_by_role('textbox', name='Research goal', exact=True).focus()
            await page.keyboard.press('Shift+Enter')
            assert not mutations, 'Shift+Enter unexpectedly submitted research'
            assert (await page.get_by_role('textbox', name='Research goal', exact=True).input_value()).endswith('\n')
            await page.get_by_role('button', name='Start research', exact=True).click()
            stage = page.get_by_role('region', name='Jev live research', exact=True)
            await expect(stage).to_be_visible()
            await expect(page.get_by_role('button', name='Live', exact=True)).to_have_class(re.compile('active'))
            await expect(page.locator('.mission-kicker')).to_contain_text('Fixture')
            await expect(page.locator('.plan-sidebar')).to_be_hidden()
            await expect(page.locator('.inspector')).to_be_hidden()
            await expect(page.get_by_role('button', name='Comparison', exact=True)).to_be_hidden()
            await expect(page.get_by_role('button', name='Import', exact=True)).to_be_hidden()
            assert progress.mid
            assert len(store.rows('SELECT id FROM missions')) == 1
            assert len(store.rows('SELECT * FROM commands')) == 1
            assert len(mutations) == 3, mutations  # plan, create, start; no extra paid/setup request
            assert (await stage.bounding_box())['y'] < 350
            assert (await stage.locator('.jev-stage-canvas').bounding_box())['y'] < 550
            await expect(stage).to_have_attribute('data-motion', 'active')
            await expect(stage).to_have_attribute('data-phase', 'searching')
            await expect(stage.locator('.jev-stage-current')).to_contain_text(progress.query)
            await page.screenshot(path=str(screenshots / 'stage-search-desktop-fixture.png'), full_page=True)

            await stage.get_by_role('button', name='Pause visualization motion', exact=True).click()
            await expect(stage).to_have_attribute('data-motion', 'frozen')
            progress.choose_source()
            await expect(stage).to_have_attribute('data-phase', 'choosing')
            await expect(stage.locator('.jev-stage-status')).to_contain_text(re.compile('choos|select', re.I))
            await expect(stage).to_have_attribute('data-motion', 'frozen')
            await stage.get_by_role('button', name='Resume visualization motion', exact=True).click()
            await expect(stage).to_have_attribute('data-motion', 'active')
            await page.screenshot(path=str(screenshots / 'stage-choosing-desktop-fixture.png'), full_page=True)
            progress.read_source()
            await expect(stage).to_have_attribute('data-phase', 'reading')
            await expect(stage.locator('.jev-stage-current')).to_contain_text('example.com')
            progress.inspect_source()
            await expect(stage).to_have_attribute('data-phase', 'assessing')
            await expect(stage.locator('.jev-source-preview')).to_contain_text(progress.text)
            await expect(stage.locator('.jev-source-preview')).to_contain_text('example.com')
            await expect(stage.locator('.jev-source-preview')).to_contain_text(re.compile('HTTP text', re.I))
            await page.screenshot(path=str(screenshots / 'stage-source-desktop-fixture.png'), full_page=True)

            progress.check_passage()
            await expect(stage).to_have_attribute('data-phase', 'verifying')
            await expect(stage.locator('.jev-stage-status')).to_contain_text(re.compile('check|verif', re.I))
            progress.save_finding()
            for _ in range(30):
                detail = await (await page.request.get(base + '/api/missions/' + progress.mid)).json()
                if detail['records'].get('finding'):
                    break
                await asyncio.sleep(.1)
            assert len(detail['records']['finding']) == 1
            assert detail['telemetry']['attempts'] == 0
            assert detail['jev_activity']['summary']['measured_calls'] == 0
            await page.set_viewport_size({'width': 430, 'height': 932})
            await page.evaluate('window.scrollTo(0, 0)')
            await page.wait_for_timeout(250)
            assert not await page.evaluate('document.documentElement.scrollWidth > innerWidth')
            assert (await stage.locator('.jev-stage-canvas').bounding_box())['y'] < 600
            await page.screenshot(path=str(screenshots / 'stage-mobile-fixture.png'), full_page=True)

            reduced = await browser.new_page(viewport={'width': 430, 'height': 932}, reduced_motion='reduce')
            reduced.on('pageerror', lambda error: errors.append(str(error)))
            await reduced.add_init_script(f'localStorage.setItem("radar:last", {json.dumps(progress.mid)})')
            await reduced.goto(base)
            await expect(reduced.get_by_role('heading', name='What are you looking for?', exact=True)).to_be_visible()
            await reduced.get_by_role('button', name='Saved research', exact=True).click()
            await reduced.locator(f'[data-mission-id="{progress.mid}"]').click()
            await reduced.get_by_role('button', name='Live', exact=True).click()
            reduced_stage = reduced.get_by_role('region', name='Jev live research', exact=True)
            await expect(reduced_stage).to_have_attribute('data-motion', 'frozen')
            await expect(reduced_stage.get_by_role('button', name=re.compile('visualization motion'))).to_be_disabled()
            await expect(reduced_stage).to_contain_text(re.compile('reduced.motion', re.I))
            await reduced.screenshot(path=str(screenshots / 'stage-reduced-motion-fixture.png'), full_page=True)
            overflow = await reduced.evaluate('document.documentElement.scrollWidth > innerWidth')
            if overflow:
                offending = await reduced.evaluate('Array.from(document.querySelectorAll("body *")).map(e=>({tag:e.tagName, cls:e.className, x:e.getBoundingClientRect().x, right:e.getBoundingClientRect().right, width:e.getBoundingClientRect().width})).filter(x=>x.right>innerWidth+1 || x.x< -1).slice(0,20)')
                raise AssertionError(json.dumps({'reduced_motion_overflow': offending}))

            await page.get_by_role('button', name='Results', exact=True).click()
            finding_group = page.locator('details.evidence-findings')
            if not await finding_group.evaluate('(element) => element.open'):
                await finding_group.locator('summary').click()
            await expect(page.locator('.finding-card')).to_have_count(1)
            await page.locator('.finding-card').get_by_role('button', name='Inspect supporting passage', exact=True).click()
            await expect(page.locator('blockquote').first).to_have_text(re.compile(re.escape(progress.text)))
            await page.keyboard.press('Escape')
            progress.emit('mission.finished', {'stop_reason': {'code': 'fixture', 'message': 'Synthetic stage fixture ended; no live research was performed.'}}, status='partial')
            await page.get_by_role('button', name='Live', exact=True).click()
            await expect(stage).to_have_attribute('data-motion', 'frozen')
            await page.get_by_role('button', name='Replay machine', exact=True).click()
            await page.get_by_role('button', name='Pause replay', exact=True).click()
            await page.wait_for_timeout(350)
            replay_requests = []
            record_replay = lambda request: replay_requests.append(request.url)
            page.on('request', record_replay)
            await page.get_by_role('slider', name='Replay position', exact=True).first.fill('0')
            await expect(stage.locator('.jev-stage-status')).to_contain_text('Recorded replay')
            await expect(stage).to_have_attribute('data-motion', 'frozen')
            assert progress.text not in await stage.inner_text(), 'Replay leaked future source text'
            await page.wait_for_timeout(400)
            page.remove_listener('request', record_replay)
            assert not replay_requests, replay_requests
            await page.screenshot(path=str(screenshots / 'stage-replay-mobile-fixture.png'), full_page=True)
            assert not provider_calls and not errors, {'providers': provider_calls, 'errors': errors}
            assert not store.rows('SELECT * FROM reservations')
            assert store.mission(progress.mid)['mode'] == 'fixture'
            assert len(store.rows('SELECT id FROM missions')) == 1
            result = {'mode': 'isolated synthetic event sequence, never a provider benchmark',
                      'direct_prompt_to_live': True, 'new_session_always_opens_prompt': True, 'saved_research_explicitly_reopened': True, 'stage_visible_above_fold': True,
                      'search_choice_source_and_evidence_events_observed': True,
                      'motion_pause_keeps_data_current': True, 'reduced_motion_respected': True,
                      'source_preview_uses_stored_text': True, 'exact_citation_opened': True,
                      'replay_is_frozen_and_hides_future_evidence': True, 'replay_provider_requests': 0,
                      'provider_calls': 0, 'measured_model_calls': 0, 'live_database_mutations': 0,
                      'narrow_horizontal_overflow': False, 'javascript_errors': errors}
            (runtime / 'ui-stage-smoke.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result, indent=2))
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
