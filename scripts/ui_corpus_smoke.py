"""Collection UI regression using temporary, explicitly marked fixtures. No external calls."""
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
import uvicorn
from playwright.async_api import async_playwright, expect
from radar.api import create_app
from radar.config import ROOT, Settings
from radar.schemas import Plan
from radar.storage import dumps, now


async def main():
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / '.cache/ms-playwright')
    runtime = ROOT / '.runtime'
    screenshots = runtime / 'screenshots'
    screenshots.mkdir(parents=True, exist_ok=True)
    data = Path(tempfile.mkdtemp(prefix='corpus-ui-fixture-', dir=runtime))
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    app = create_app(Settings(data_dir=data, host='127.0.0.1', port=port))
    store = app.state.store
    errors, forbidden_calls = [], []
    mid = 'synthetic-corpus-mission'
    criteria = [dict(id=key, label=label, question=question) for key, label, question in [
        ('capabilities', 'Documented capabilities', 'Which capabilities are documented in the original product material?'),
        ('pricing', 'Public price', 'What price and billing period are explicitly stated?'),
        ('limits', 'Published limits', 'Which restrictions are documented for this product?'),
    ]]
    plan = Plan(goal='Synthetic UI fixture: compare documented product capabilities, prices and limits.',
                research_mode='fixed', criteria=criteria).model_dump()
    stamp = now()
    store.execute('INSERT INTO missions VALUES(?,?,?,?,?,?,?,?,?)',
                  (mid, plan['goal'], 'partial', dumps(plan), 1, stamp, stamp, None, 'fixture'))
    store.execute('INSERT INTO plans VALUES(?,?,?,?,?)', ('fixture-plan', mid, 1, dumps(plan), stamp))
    store.event(mid, 'mission.created', {'fixture_notice': 'Synthetic UI fixture; no external calls'}, mode='fixture')

    def add_record(name, statuses):
        source_id, entity_id = f'fixture-source-{name}', f'fixture-entity-{name}'
        lines = [f'Synthetic {name.title()} supports team notes and offline reading.',
                 f'Synthetic {name.title()} lists a price of EUR 12 per workspace per month.',
                 f'Synthetic {name.title()} documents a maximum of 20 team members.']
        text = '\n'.join(lines)
        decision_ids = [f'fixture-assess-{name}', f'fixture-verify-{name}']
        source = {'id': source_id, 'url': f'https://{name}.example/fixture-documentation',
                  'title': f'Synthetic {name.title()} product documentation', 'text': text,
                  'entity_id': entity_id, 'decision_id': decision_ids[0], 'role': 'candidate',
                  'entity_type': 'company', 'retrieved_at': now(), 'review': 'unreviewed',
                  'content_hash': f'fixture-hash-{name}', 'mode': 'fixture',
                  'chunks': [{'id': 'c0', 'start': 0, 'end': len(text), 'text': text}],
                  'coverage': {'analyzed_chunks': 1, 'total_chunks': 1, 'method': 'Synthetic fixture',
                               'blocked_sections': '', 'truncated': False}}
        records = [('source', source), ('entity', {'id': entity_id, 'name': f'Synthetic {name.title()}',
                   'domains': [f'{name}.example'], 'source_ids': [source_id], 'review': 'unreviewed',
                   'classification': 'candidate', 'role': 'candidate', 'fields': {}})]
        for index, decision_id in enumerate(decision_ids):
            records.append(('decision', {'id': decision_id, 'purpose': 'Assess public source' if index == 0 else 'Verify selected evidence against each question',
                'source_id': source_id, 'status': 'complete', 'model': 'explicit-ui-fixture', 'mode': 'fixture',
                'created_at': now(), 'cache': False, 'latency_ms': 20 + index * 10,
                'estimated_usd': .0001, 'rubric_version': 1, 'usage': {'input_tokens': 10, 'output_tokens': 4},
                'questions': {item['id']: {'type': 'choice', 'instructions': item['question'],
                    'criteria': {'supported': 'Supported by fixture passage', 'partly_supported': 'Partial fixture passage', 'unknown': 'Not established'}} for item in criteria},
                'answers': {item['id']: {'type': 'choice', 'choice': status, 'confidence': 1} for item, status in zip(criteria, statuses)}}))
        for item, line, status in zip(criteria, lines, statuses):
            if status == 'unknown':
                continue
            span_id = f'fixture-span-{name}-{item["id"]}'
            start = text.index(line)
            records.append(('span', {'id': span_id, 'source_id': source_id, 'start': start,
                                    'end': start + len(line), 'text': line}))
            records.append(('finding', {'id': f'fixture-finding-{name}-{item["id"]}', 'entity_id': entity_id,
                'source_ids': [source_id], 'span_ids': [span_id], 'decision_id': decision_ids[1],
                'subject': f'Synthetic {name.title()}', 'criterion_id': item['id'], 'question': item['question'],
                'status': status, 'review': 'unreviewed', 'rubric_version': 1, 'statement': line,
                'scope': 'Synthetic fixture only', 'evidence_kind': 'publisher_claim', 'limitations': []}))
        store.mutate(mid, 'fixture.collection_updated', {'fixture_notice': 'Synthetic UI fixture; no external calls'},
                     records, status='partial', mode='fixture')

    add_record('alpha', ['supported', 'supported', 'supported'])
    add_record('bravo', ['supported', 'partly_supported', 'unknown'])

    def forbidden(*args, **kwargs):
        forbidden_calls.append('unexpected external access')
        raise AssertionError('Collection UI fixture must not call external providers')

    async def forbidden_async(*args, **kwargs):
        forbidden()

    app.state.runner.jev.client = forbidden
    app.state.runner.search.query = forbidden_async
    app.state.runner.fetcher.get = forbidden_async
    app.state.text_model.client = forbidden
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
            await page.goto(base)
            await page.get_by_role('button', name='Saved research', exact=True).click()
            await page.locator(f'[data-mission-id="{mid}"]').click()
            board = page.get_by_role('region', name='Jev collection analysis', exact=True)
            await expect(board).to_be_visible()
            await expect(board).to_contain_text('Test fixture')
            await expect(board.locator('tbody tr')).to_have_count(2)
            payload = await (await page.request.get(base + '/api/missions/' + mid)).json()
            assert payload['corpus']['metrics']['items'] == 2
            assert payload['corpus']['metrics']['typed_judgments'] == 12
            assert payload['corpus']['metrics']['median_item_ms'] == 50
            await expect(board.locator('.corpus-stats')).to_contain_text('50 ms')
            await board.get_by_label('Needs review', exact=False).check()
            await expect(board.locator('tbody tr')).to_have_count(1)
            await expect(board.locator('tbody tr')).to_contain_text('Synthetic Bravo')
            await board.get_by_label('Needs review', exact=False).uncheck()
            await board.get_by_label('Search compared records', exact=True).fill('alpha')
            await expect(board.locator('tbody tr')).to_have_count(1)
            await board.get_by_role('button', name='Documented capabilities: Supported. Inspect source for Synthetic Alpha product documentation', exact=True).click()
            await expect(page.get_by_role('dialog')).to_contain_text('Synthetic Alpha supports team notes and offline reading.')
            await page.keyboard.press('Escape')
            await board.get_by_label('Search compared records', exact=True).fill('')
            await board.locator('.corpus-decision-link').first.click()
            await expect(page.get_by_role('dialog')).to_contain_text('Assess public source')
            await page.keyboard.press('Escape')
            await board.locator('.corpus-distributions > summary').first.click()
            await expect(board.locator('.corpus-coverage').last).to_contain_text('1/2 supported')
            await expect(board.locator('.corpus-coverage').last).to_contain_text('1 unknown')
            # A new source event updates the real API projection and the mounted view.
            add_record('charlie', ['unknown', 'unknown', 'unknown'])
            await expect(board.locator('tbody tr')).to_have_count(3, timeout=10000)
            await expect(board.locator('.corpus-coverage').last).to_contain_text('1/3 supported')
            await expect(board.locator('.corpus-coverage').last).to_contain_text('2 unknown')
            await board.get_by_label('Sort compared records', exact=True).select_option('name')
            await expect(board.locator('tbody tr').first).to_contain_text('Synthetic Alpha')
            await board.screenshot(path=str(screenshots / 'corpus-desktop-fixture.png'))
            await page.set_viewport_size({'width': 430, 'height': 932})
            assert not await page.evaluate('document.documentElement.scrollWidth > innerWidth')
            assert await board.locator('.corpus-table-scroll').evaluate('(element) => element.scrollWidth > element.clientWidth')
            await board.screenshot(path=str(screenshots / 'corpus-mobile-fixture.png'))
            await board.locator('.corpus-table-scroll').evaluate('(element) => element.scrollLeft = element.scrollWidth')
            await expect(board.locator('.corpus-decision-link').first).to_be_in_viewport()
            # Marked event fixtures exercise the real live state projection without a runner.
            await page.set_viewport_size({'width': 1500, 'height': 1050})
            await page.get_by_role('button', name='Live', exact=True).click()
            stage = page.get_by_role('region', name='Jev live research', exact=True)
            store.mutate(mid, 'mission.resume', {'fixture_notice': 'Synthetic UI fixture; no external calls'}, status='running', mode='fixture')
            group = {'id': 'fixture-grouped-choice', 'status': 'inflight', 'cache': False,
                     'purpose': 'Select independent records for parallel assessment', 'created_at': now(),
                     'model': 'explicit-ui-fixture', 'mode': 'fixture', 'answers': {},
                     'questions': {f'opaque-action-{name}': {'type': 'choice',
                         'instructions': 'Inspect this observed fixture lead if it can answer the shared research questions.',
                         'criteria': {'inspect': 'Inspect using the common questions', 'defer': 'Leave out of this collection batch'}}
                         for name in ('alpha', 'bravo', 'charlie')},
                     'state': {'observed_leads': {f'opaque-action-{name}': {'kind': 'fetch',
                         'url': f'https://{name}.example/fixture-documentation',
                         'description': f'Synthetic {name.title()} product documentation'} for name in ('alpha', 'bravo', 'charlie')}}}
            store.mutate(mid, 'jev.started', {'decision_id': group['id']}, [('decision', group)], mode='fixture')
            await expect(stage).to_have_attribute('data-phase', 'choosing')
            group_choices = stage.get_by_label('Independent record choices', exact=True)
            await expect(group_choices.locator('button')).to_have_count(3)
            await expect(group_choices).to_contain_text('https://alpha.example/fixture-documentation')
            await expect(stage.locator('.jev-choice-preview')).not_to_contain_text('opaque-action')
            await expect(group_choices.locator('.pending')).to_have_count(3)
            group.update(status='complete', latency_ms=22, usage={'input_tokens': 20, 'output_tokens': 6},
                         estimated_usd=.0002, answers={f'opaque-action-{name}': {'type': 'choice', 'choice': choice}
                         for name, choice in [('alpha', 'inspect'), ('bravo', 'inspect'), ('charlie', 'defer')]})
            store.mutate(mid, 'jev.completed', {'decision_id': group['id']}, [('decision', group)], mode='fixture')
            await expect(group_choices.locator('.inspect')).to_have_count(2)
            await expect(group_choices.locator('.defer')).to_have_count(1)
            await group_choices.get_by_role('button', name='Inspect selection for https://charlie.example/fixture-documentation', exact=True).click()
            await expect(page.get_by_role('dialog')).to_contain_text('Select independent records for parallel assessment')
            await page.keyboard.press('Escape')
            await stage.screenshot(path=str(screenshots / 'collection-choices-desktop-fixture.png'))
            pending_requests = []
            for name, purpose in [('alpha', 'Analyze individual artifact and select evidence'),
                                  ('bravo', 'Verify selected evidence against each question')]:
                request = {'id': f'fixture-pending-{name}', 'status': 'inflight', 'cache': False,
                           'purpose': purpose, 'source_id': f'fixture-source-{name}', 'created_at': now(),
                           'model': 'explicit-ui-fixture', 'mode': 'fixture', 'answers': {},
                           'questions': {'capabilities': {'type': 'choice', 'instructions': 'Check the synthetic fixture evidence.',
                               'criteria': {'supported': 'Supported in fixture text', 'unknown': 'Unknown'}}}}
                pending_requests.append(request)
                store.mutate(mid, 'jev.started', {'decision_id': request['id']}, [('decision', request)], mode='fixture')
            pending_seq = store.events(mid)[-1]['seq']
            concurrent = stage.get_by_label('Concurrent Jev requests', exact=True)
            await expect(concurrent).to_be_visible()
            await expect(concurrent).to_contain_text('2 Jev requests in flight')
            await expect(concurrent.locator('button')).to_have_count(2)
            await expect(stage.locator('.jev-core-label')).to_contain_text('2 REQUESTS IN FLIGHT')
            await concurrent.locator('button').first.click()
            await expect(page.get_by_role('dialog')).to_contain_text('Analyze individual artifact and select evidence')
            await page.keyboard.press('Escape')
            await stage.screenshot(path=str(screenshots / 'concurrent-jev-desktop-fixture.png'))
            await page.set_viewport_size({'width': 430, 'height': 932})
            assert not await page.evaluate('document.documentElement.scrollWidth > innerWidth')
            await expect(concurrent.locator('button')).to_have_count(2)
            await stage.screenshot(path=str(screenshots / 'concurrent-jev-mobile-fixture.png'))
            finished = pending_requests[0]
            finished.update(status='complete', latency_ms=25, usage={'input_tokens': 10, 'output_tokens': 2},
                            estimated_usd=.0001, answers={'capabilities': {'type': 'choice', 'choice': 'supported'}})
            store.mutate(mid, 'jev.completed', {'decision_id': finished['id']}, [('decision', finished)], mode='fixture')
            await expect(concurrent).to_have_count(0)
            await expect(stage.locator('.jev-core-label')).to_contain_text('AWAITING RESPONSE')
            await stage.get_by_role('button', name='Inspect current Jev decision', exact=True).click()
            await expect(page.get_by_role('dialog')).to_contain_text('Verify selected evidence against each question')
            await page.keyboard.press('Escape')
            store.mutate(mid, 'mission.paused', {'fixture_notice': 'Synthetic pause with an uncertain pending record'}, status='paused', mode='fixture')
            await expect(stage).to_have_attribute('data-phase', 'idle')
            await expect(stage.get_by_label('Concurrent Jev requests', exact=True)).to_have_count(0)
            await page.get_by_role('button', name='Replay machine', exact=True).click()
            await page.get_by_role('slider', name='Replay position', exact=True).fill(str(pending_seq))
            await expect(stage).to_have_attribute('data-phase', 'idle')
            await expect(stage.get_by_label('Concurrent Jev requests', exact=True)).to_have_count(0)
            await expect(stage.locator('.jev-core-label')).to_contain_text('RECORDED')
            assert not errors and not forbidden_calls
            report = {'mode': 'temporary synthetic fixtures; no external calls', 'api_backed_projection': True,
                      'live_record_updates': True, 'question_labels_from_plan': True,
                      'needs_review_and_search_filters': True, 'source_and_decision_links': True,
                      'unknowns_in_denominator': True, 'mobile_table_scroll': True,
                      'mobile_page_overflow': False, 'grouped_inspect_and_defer_choices': True,
                      'concurrent_request_count_and_links': True, 'completion_removes_pending_request': True,
                      'pause_and_replay_have_no_active_requests': True, 'javascript_errors': errors}
            (runtime / 'ui-corpus-smoke.json').write_text(json.dumps(report, indent=2) + '\n')
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
