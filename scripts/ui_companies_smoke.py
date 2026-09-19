"""Company/results and one-time search setup QA in an isolated fixture app.

All companies, source passages, and search observations are explicitly test
fixtures. No public provider is called, no .env is read, and no live record is
changed. The real backend projection and built frontend run together.
"""
import asyncio
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import uvicorn
from playwright.async_api import async_playwright, expect
from radar.api import create_app
from radar.config import ROOT, Settings
from radar.lenses import BUILTINS
from radar.schemas import Plan
from radar.storage import dumps, now, uid


def seed_companies(store):
    """Create intentionally synthetic records, never labeled as live research."""
    mid = uid()
    criteria = BUILTINS[0]['criteria']
    plan = Plan(goal='Fixture only: find competitors for Example Reference and compare capabilities and pricing',
                reference='https://example.com/', seeds=['https://example.com/'],
                providers=['seed'], criteria=criteria).model_dump()
    stamp = now()
    store.execute('INSERT INTO missions VALUES(?,?,?,?,?,?,?,?,?)',
                  (mid, plan['goal'], 'partial', dumps(plan), 1, stamp, stamp, None, 'fixture'))
    records = []
    entities = [
        ('reference', 'Example Reference · fixture', 'example.com', 'reference', 'reference_product', 'software', .75,
         {'offering': 'Fixture statement: a reference collaboration product.', 'capabilities': 'Fixture statement: team chat.'}),
        ('alpha', 'Alpha Company · fixture', 'example.net', 'direct', 'candidate', 'software', .8,
         {'offering': 'Fixture statement: Alpha collaboration software.', 'capabilities': 'Fixture statement: team chat and document search.', 'pricing': 'Fixture statement: EUR 25 per seat per month.'}),
        ('beta', 'Beta Company · fixture', 'example.org', 'alternative', 'candidate', 'software', .9,
         {'offering': 'Fixture statement: Beta knowledge software.', 'capabilities': 'Fixture statement: document question answering.'}),
        ('gamma', 'Gamma Service · fixture', 'service.example.net', 'adjacent', 'candidate', 'service', .6,
         {'offering': 'Fixture statement: Gamma implementation services.', 'capabilities': 'Fixture statement: integration consulting.'}),
    ]
    for eid, name, host, relationship, role, kind, relevance, values in entities:
        sid, did = 'source-' + eid, 'decision-' + eid
        text = '\n'.join(values.values())
        source = {'id': sid, 'url': f'https://{host}/', 'requested_url': f'https://{host}/',
                  'title': name, 'text': text, 'content_hash': 'fixture-hash-' + eid,
                  'retrieved_at': stamp, 'source_date': None, 'source_date_provenance': 'unknown',
                  'decision_id': did, 'relevance': relevance, 'entity_id': eid, 'purpose': 'offer',
                  'coverage': {'analyzed_chunks': len(values), 'total_chunks': len(values),
                               'method': 'Explicit synthetic UI fixture', 'blocked_sections': '', 'truncated': False},
                  'depth': 0, 'cache': False, 'status_code': 200, 'chunks': []}
        fields = {}
        for cid, passage in values.items():
            fid, span_id = f'finding-{eid}-{cid}', f'span-{eid}-{cid}'
            start = text.index(passage)
            span = {'id': span_id, 'source_id': sid, 'start': start, 'end': start + len(passage),
                    'text': passage, 'anchor': 'fixture', 'provenance': 'Synthetic UI test fixture'}
            source['chunks'].append(span)
            question = next(c['question'] for c in criteria if c['id'] == cid)
            finding = {'id': fid, 'subject': name, 'entity_id': eid, 'criterion_id': cid,
                       'question': question, 'statement': passage, 'status': 'supported',
                       'source_ids': [sid], 'span_ids': [span_id], 'decision_id': did,
                       'evidence_kind': 'synthetic test assertion', 'scope': 'Fixture only, not a factual company claim.',
                       'review': 'unreviewed', 'rubric_version': 1, 'retrieved_at': stamp,
                       'limitations': ['Synthetic data for UI regression only']}
            fields[cid] = {'finding_id': fid, 'value': passage, 'status': 'supported', 'source_id': sid}
            records.extend([('span', span), ('finding', finding)])
        entity = {'id': eid, 'name': name, 'domains': [host], 'source_ids': [sid], 'fields': fields,
                  'classification': relationship, 'classification_decision': did, 'entity_type': kind,
                  'role': role, 'review': 'unreviewed', 'ownership': 'Synthetic UI fixture entity'}
        # Mark the saved decision as a fixture cache record: no live request or
        # invented live inference duration is implied by the UI telemetry.
        decision = {'id': did, 'purpose': 'Fixture assessment only', 'status': 'complete',
                    'cache': True, 'latency_ms': None, 'queue_ms': 0, 'source_id': sid,
                    'requested_model': 'fixture', 'model': 'fixture', 'questions': {}, 'answers': {}}
        records.extend([('source', source), ('entity', entity), ('decision', decision)])
    for index, hosts in enumerate([['example.org', 'example.net'], ['example.net']]):
        search = {'id': f'fixture-search-{index}', 'query': f'fixture category query {index}',
                  'provider': 'fixture-search', 'timestamp': stamp, 'language': 'en', 'region_requested': '',
                  'scope': 'Synthetic search observation; not a real engine response', 'latency_ms': 0,
                  'results': [{'id': f'fixture-result-{index}-{position}', 'url': 'https://' + host + '/',
                               'title': host + ' fixture', 'snippet': 'Synthetic test result', 'position': position}
                              for position, host in enumerate(hosts, 1)]}
        records.append(('search', search))
    store.mutate(mid, 'fixture.created', {'notice': 'Synthetic UI fixtures, no live research'}, records, mode='fixture')
    store.event(mid, 'mission.finished', {'stop_reason': {'code': 'fixture', 'message': 'Synthetic UI test data only; no research was performed.'}}, mode='fixture')
    return mid


async def main():
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / '.cache/ms-playwright')
    runtime = ROOT / '.runtime'
    runtime.mkdir(exist_ok=True)
    screenshots = runtime / 'screenshots'
    screenshots.mkdir(exist_ok=True)
    data = Path(tempfile.mkdtemp(prefix='companies-ui-fixture-', dir=runtime))
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    settings = Settings(data_dir=data, host='127.0.0.1', port=port, key='fixture-only-never-sent')
    app = create_app(settings)
    store = app.state.store
    store.set_setting('profile', {'name': 'Radar · synthetic company UI fixture', 'accent': '#f1d54a', 'retention_days': 30})
    store.set_setting('connection', {'success': False, 'tested_at': now(), 'model': 'fixture', 'error': 'No provider called in this test'})
    mid = seed_companies(store)

    def forbid_provider(*args, **kwargs):
        raise AssertionError('Isolated UI test must not start research or call a provider')

    async def forbid_async_provider(*args, **kwargs):
        forbid_provider()

    app.state.runner.launch = forbid_provider
    app.state.runner.jev.client = forbid_provider
    app.state.runner.search.query = forbid_async_provider
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error', access_log=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    errors, reload_requests = [], []
    try:
        for _ in range(50):
            if server.started:
                break
            await asyncio.sleep(.1)
        assert server.started
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True, chromium_sandbox=True)
            page = await browser.new_page(viewport={'width': 1440, 'height': 1050})
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: reload_requests.append(request.url)
                    if request.method == 'POST' and request.url.endswith('/settings/reload') else None)
            await page.goto(f'http://127.0.0.1:{port}/')
            await expect(page.get_by_role('textbox', name='Seed URLs', exact=True)).to_be_hidden()
            await page.get_by_role('textbox', name='Research goal', exact=True).fill('Find competitors for a knowledge management product in France')
            await page.get_by_role('button', name='Start research', exact=True).click()
            await expect(page.get_by_role('button', name='Start investigation', exact=True)).to_be_disabled()
            await expect(page.locator('.plan-readiness')).to_contain_text('Brave')
            await page.get_by_role('button', name='Set up automatic discovery', exact=True).click()
            await expect(page.get_by_role('dialog')).to_be_visible()
            assert await page.get_by_role('dialog').locator('input[type=password]').count() == 0
            await page.screenshot(path=str(screenshots / 'automatic-search-setup-fixture.png'), full_page=True)
            # Reload is deliberately not a paid connection test. Patch the local
            # configuration loader so the real project .env is never touched.
            configured = Settings(data_dir=data, host='127.0.0.1', port=port,
                                  key='fixture-only-never-sent', brave_key='fixture-search-never-sent')
            with patch('radar.api.Settings.load', return_value=configured):
                await page.get_by_role('button', name='Reload connection', exact=True).click()
                await expect(page.get_by_role('heading', name='Automatic discovery is ready', exact=True)).to_be_visible()
            await page.keyboard.press('Escape')
            await page.get_by_role('button', name='Research options', exact=True).click()
            await page.get_by_role('button', name='Review research plan', exact=True).click()
            await expect(page.get_by_role('button', name='Start investigation', exact=True)).to_be_enabled()
            assert len(reload_requests) == 1

            await page.get_by_role('button', name='Saved research').click()
            await page.locator('.saved-card').filter(has_text='Fixture only: find competitors').click()
            await expect(page.locator('.mission-kicker')).to_contain_text('Fixture')
            cards = page.locator('.company-card:not(.reference-card)')
            await expect(cards).to_have_count(3)
            await expect(page.locator('.reference-group')).to_contain_text('Example Reference')
            assert 'Example Reference' not in await cards.first.inner_text()
            await expect(cards.first).to_contain_text('Beta Company')
            await page.get_by_role('combobox', name='Sort companies', exact=True).select_option('search_visibility')
            await expect(cards.first).to_contain_text('Alpha Company')
            await cards.first.locator('.company-more > summary').click()
            await expect(cards.first.locator('.visibility-detail')).to_contain_text('2 collected queries')
            await expect(cards.first.locator('.visibility-detail')).to_contain_text('not a traffic or market-share measurement')
            await expect(cards.first.locator('.visibility-detail a')).to_have_count(2)
            assert 'popularity' in (await page.locator('.company-results').inner_text()).lower()
            await page.get_by_role('combobox', name='Filter company relationship', exact=True).select_option('direct')
            await expect(cards).to_have_count(1)
            await expect(cards).to_contain_text('Alpha Company')
            await page.get_by_role('combobox', name='Filter company relationship', exact=True).select_option('all')
            await page.get_by_role('checkbox', name='Has pricing evidence', exact=True).check()
            await expect(cards).to_have_count(1)
            await expect(cards).to_contain_text('Alpha Company')
            await page.get_by_role('checkbox', name='Has pricing evidence', exact=True).uncheck()
            await page.get_by_role('textbox', name='Filter collected evidence', exact=True).fill('Gamma')
            await expect(cards).to_have_count(1)
            await expect(cards).to_contain_text('Gamma Service')
            await page.get_by_role('textbox', name='Filter collected evidence', exact=True).fill('no-such-fixture-company')
            await expect(cards).to_have_count(0)
            await page.get_by_role('button', name='Reset company filters', exact=True).click()
            await expect(page.get_by_role('textbox', name='Filter collected evidence', exact=True)).to_have_value('')
            await expect(cards).to_have_count(3)
            await expect(page.locator('.improvement-card').first).to_contain_text('PROPOSED EXPERIMENT')
            await page.locator('.improvement-card').first.get_by_role('button', name='Evidence 1', exact=True).click()
            await expect(page.locator('blockquote').first).to_contain_text('Fixture statement:')
            await page.keyboard.press('Escape')
            await cards.first.locator('.company-excerpt').first.click()
            await expect(page.locator('blockquote').first).to_contain_text('Fixture statement:')
            await page.keyboard.press('Escape')
            await page.evaluate('window.scrollTo(0, 0)')
            await page.screenshot(path=str(screenshots / 'companies-desktop-fixture.png'), full_page=True)

            await page.locator('details.evidence-findings > summary').click()
            await page.locator('.finding-card').first.get_by_role('button', name='Inspect supporting passage').click()
            await expect(page.locator('blockquote').first).to_contain_text('Fixture statement:')
            await page.keyboard.press('Escape')
            await page.set_viewport_size({'width': 430, 'height': 932})
            await page.wait_for_timeout(250)
            assert not await page.evaluate('document.documentElement.scrollWidth > innerWidth')
            await page.evaluate('window.scrollTo(0, 0)')
            await page.screenshot(path=str(screenshots / 'companies-mobile-fixture.png'), full_page=True)
            await page.locator('.company-results > .company-grid').screenshot(path=str(screenshots / 'companies-mobile-cards-fixture.png'))
            assert not errors, errors
            assert not store.rows('SELECT * FROM reservations')
            assert len(store.rows('SELECT id FROM missions')) == 1
            assert store.mission(mid)['mode'] == 'fixture'
            result = {'mode': 'isolated synthetic fixture; no live evidence or provider calls',
                      'automatic_search_default': True, 'urls_optional_and_hidden': True,
                      'unconfigured_search_blocks_start': True, 'reload_config_without_provider_call': True,
                      'configured_prompt_only_plan_enabled': True, 'candidate_cards': 3,
                      'reference_separate_from_candidates': True, 'sorts_and_filters': True,
                      'reset_filters_clears_text_query': True,
                      'observed_search_visibility_not_popularity': True, 'citation_opened': True,
                      'narrow_horizontal_overflow': False, 'paid_attempts': 0, 'javascript_errors': errors,
                      'live_database_unchanged': True}
            (runtime / 'ui-companies-smoke.json').write_text(json.dumps(result, indent=2))
            print(json.dumps(result, indent=2))
            await browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        shutil.rmtree(data)


if __name__ == '__main__':
    asyncio.run(main())
