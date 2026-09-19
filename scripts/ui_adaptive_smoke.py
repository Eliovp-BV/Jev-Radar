"""Adaptive research UI regression: explicit synthetic records, zero provider calls."""
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
from radar.storage import now


async def main():
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / '.cache/ms-playwright')
    runtime = ROOT / '.runtime'
    screenshots = runtime / 'screenshots'
    screenshots.mkdir(parents=True, exist_ok=True)
    data = Path(tempfile.mkdtemp(prefix='adaptive-ui-fixture-', dir=runtime))
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    app = create_app(Settings(data_dir=data, host='127.0.0.1', port=port,
                              key='synthetic-fixture', brave_key='synthetic-fixture'))
    store = app.state.store
    identifiers, errors, calls = {}, [], []
    goal = 'Synthetic fixture only: investigate viral videos and compare the evidence for why they spread.'
    planning = {'id': 'fixture-plan-decision', 'purpose': 'Design research approach', 'status': 'inflight',
                'cache': False, 'requested_model': 'synthetic-fixture', 'questions': {
                    'research_unit': {'type': 'choice', 'instructions': goal, 'criteria': {
                        'videos': 'Individual videos', 'articles': 'Individual articles'}}}, 'answers': {}}

    def emit(kind, records, status=None):
        store.mutate(identifiers['mid'], kind, {'fixture_notice': 'Synthetic UI fixture, no model call',
                    **({'decision_id': records[0][1]['id']} if records and records[0][0] == 'decision' else {})},
                     records, status=status, mode='fixture')

    def launch(mid):
        identifiers['mid'] = mid
        store.execute("UPDATE missions SET mode='fixture' WHERE id=?", (mid,))
        emit('jev.started', [('decision', planning)])

    def forbidden(*args, **kwargs):
        calls.append('forbidden provider')
        raise AssertionError('UI fixture must not call providers')

    async def forbidden_async(*args, **kwargs):
        forbidden()

    app.state.runner.launch = launch
    app.state.runner.jev.client = forbidden
    app.state.runner.search.query = forbidden_async
    app.state.runner.fetcher.get = forbidden_async
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
            page = await browser.new_page(viewport={'width': 1500, 'height': 1000})
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(base)
            await page.get_by_role('textbox', name='Research goal', exact=True).fill(goal)
            await page.get_by_role('button', name='Start research', exact=True).click()
            stage = page.get_by_role('region', name='Jev live research', exact=True)
            await expect(stage).to_have_attribute('data-phase', 'planning')
            assert store.mission(identifiers['mid'])['plan']['research_mode'] == 'adaptive'
            await expect(page.locator('.research-approach')).to_contain_text('Jev is designing your research approach')
            await page.screenshot(path=str(screenshots / 'adaptive-planning-fixture.png'), full_page=True)
            planning.update(status='complete', cache=True, answers={'research_unit': {'type': 'choice', 'choice': 'videos'}})
            emit('jev.completed', [('decision', planning)])
            program = {'id': 'fixture-program', 'plan_version': 1, 'decision_id': planning['id'], 'unit': 'videos',
                       'objective': goal, 'criteria': [{'id': 'engagement', 'label': 'Observed engagement',
                       'question': 'What engagement evidence is recorded for each individual video?'}],
                       'search_queries': ['fixture videos public view counts'],
                       'evidence_requirements': ['Individual video metadata and observed counts'],
                       'stop_conditions': ['Stop at the configured research limits'],
                       'limitations': ['Synthetic fixture only; views cannot establish causation.']}
            emit('research.programmed', [('research_program', program)])
            await page.locator('.research-approach > summary').click()
            await expect(page.locator('.research-approach')).to_contain_text('Observed engagement')
            await page.get_by_role('button', name='Inspect Jev’s planning decision', exact=True).click()
            await expect(page.get_by_role('dialog')).to_contain_text('Design research approach')
            await expect(page.get_by_role('dialog')).to_contain_text('Individual videos')
            await page.keyboard.press('Escape')
            await page.locator('.live-decision-log > summary').click()
            await page.get_by_role('button', name='Design the approach', exact=False).click()
            await expect(page.locator('.jev-decision')).to_contain_text('Individual videos')
            await page.locator('.live-decision-log > summary').click()
            stamp = now()
            source_records = []
            for index, views in enumerate([None, 24680]):
                sid = f'fixture-video-{index}'
                passage = f'Synthetic video metadata {index}. ' + (f'Observed views: {views}.' if views else 'View count unavailable.')
                source = {'id': sid, 'source_kind': 'video', 'unit_id': f'https://example.org/videos/{index}',
                          'url': f'https://example.org/videos/{index}', 'title': f'Video {index} · synthetic fixture',
                          'text': passage, 'content_hash': 'synthetic-'+sid, 'retrieved_at': stamp, 'source_date': None, 'cache': False,
                          'video_metadata': {'views': views, 'published_at': '2026-01-05' if views else None,
                                             'description': 'Synthetic publisher description: https://example.org/channel/' + 'longpublicidentifier' * 8,
                                             'published_at_basis': 'Synthetic provider page_age; publication date not verified',
                                             'transcript_available': False, 'frames_available': False,
                                             'creator': 'Synthetic fixture creator', 'observed_at': stamp,
                                             'provenance': 'Synthetic provider metadata; video not watched'},
                          'coverage': {'analyzed_chunks': 1, 'total_chunks': 1, 'method': 'Synthetic indexed metadata only',
                                       'blocked_sections': '', 'truncated': False},
                          'chunks': [{'start': 0, 'end': len(passage), 'text': passage}]}
                span = {'id': 'span-' + sid, 'source_id': sid, 'start': 0, 'end': len(passage), 'text': passage}
                source_records.extend([('source', source), ('span', span)])
            duplicate = {**source_records[-2][1], 'id': 'fixture-video-duplicate',
                         'video_metadata': {**source_records[-2][1]['video_metadata'], 'views': None},
                         'content_hash': 'duplicate-fixture-hash', 'retrieved_at': '2000-01-01T00:00:00+00:00'}
            source_records.append(('source', duplicate))
            for index in range(2):
                source_records.append(('artifact_analysis', {'id': 'fixture-artifact-' + str(index), 'source_id': f'fixture-video-{index}',
                    'plan_version': 1, 'program_id': program['id'], 'role': 'primary_artifact', 'relevance': 1, 'features': {}}))
            artifact_decision = {'id': 'fixture-artifact-decision', 'purpose': 'Analyze individual artifact and select evidence',
                'status': 'complete', 'cache': True, 'questions': {}, 'answers': {}, 'model': 'synthetic-fixture'}
            verification_decision = {'id': 'fixture-evidence-check', 'purpose': 'Verify selected evidence against each question',
                'status': 'complete', 'cache': True, 'model': 'synthetic-fixture', 'questions': {
                    'feature_title': {'type': 'choice', 'instructions': 'Check only the supplied synthetic passage.',
                                      'criteria': {'supported': 'Supported by supplied fixture passage', 'unknown': 'Unknown'}}},
                'answers': {'feature_title': {'type': 'choice', 'choice': 'supported'}}}
            for kind, record in source_records:
                if kind == 'artifact_analysis' and record['source_id'] == 'fixture-video-1':
                    record.update(decision_id=artifact_decision['id'], verification_decision_id=verification_decision['id'])
            source_records += [('decision', artifact_decision), ('decision', verification_decision),
                ('artifact_analysis', {'id': 'fixture-old-reassessment', 'source_id': duplicate['id'],
                    'plan_version': 1, 'program_id': program['id'], 'role': 'secondary_commentary', 'relevance': 1, 'features': {}})]
            context_source = {**source_records[0][1], 'id': 'fixture-video-context', 'unit_id': 'https://example.org/videos/context',
                              'url': 'https://example.org/videos/context', 'title': 'How to discuss viral videos · synthetic context',
                              'content_hash': 'fixture-context-hash'}
            source_records += [('source', context_source), ('artifact_analysis', {'id': 'fixture-context-assessment',
                'source_id': context_source['id'], 'plan_version': 1, 'program_id': program['id'],
                'role': 'secondary_commentary', 'relevance': 1, 'features': {}})]
            emit('source.extracted', source_records)
            comparison = {'id': 'fixture-compare-decision', 'purpose': 'Compare observed artifacts', 'status': 'inflight',
                          'cache': False, 'questions': {'pattern': {'type': 'choice', 'instructions': 'Compare the supplied fixture observations.',
                          'criteria': {'possible': 'Possible explanation', 'unsupported': 'Not established'}}}, 'answers': {}}
            emit('jev.started', [('decision', comparison)])
            snapshot = await page.request.get(base + '/api/missions/' + identifiers['mid'])
            assert snapshot.ok, await snapshot.text()
            assert len((await snapshot.json())['records']['source']) == 4
            await expect(stage).to_have_attribute('data-phase', 'comparing', timeout=10000)
            comparison.update(status='complete', cache=True, answers={'pattern': {'type': 'choice', 'choice': 'unsupported'}})
            emit('jev.completed', [('decision', comparison)])
            analysis = {'id': 'fixture-analysis', 'plan_version': 1, 'program_id': program['id'], 'unit': 'videos', 'decision_id': comparison['id'],
                        'artifact_count': 2, 'patterns': [
                            {'id': 'fixture-observation', 'label': 'A view count was observed', 'status': 'observed',
                             'rationale': 'One synthetic record supplies a count; the other does not.',
                             'source_ids': ['fixture-video-1'], 'span_ids': ['span-fixture-video-1'], 'limitations': []},
                            {'id': 'fixture-cause', 'label': 'Cause of spread remains unestablished', 'status': 'unsupported',
                             'rationale': 'These fixture observations contain no causal evidence.',
                             'source_ids': ['fixture-video-0', 'fixture-video-1'], 'span_ids': [],
                             'limitations': ['No transcripts, frames or distribution history.']}],
                        'comparisons': [], 'limitations': ['Synthetic UI test only; no real research was performed.']}
            analysis['patterns'] += [{'id': 'fixture-additional-' + str(i), 'label': 'Additional fixture hypothesis ' + str(i),
                                     'status': 'possible', 'rationale': 'Synthetic hypothesis only, not an established explanation.',
                                     'source_ids': ['fixture-video-1'], 'span_ids': [], 'limitations': []} for i in range(2)]
            emit('research.analyzed', [('research_analysis', analysis)], status='partial')
            await page.locator('.live-decision-log > summary').click()
            await page.get_by_role('button', name='Compare the artifacts', exact=False).click()
            await expect(page.locator('.jev-decision')).to_contain_text('Not established')
            await page.get_by_role('button', name='Results', exact=True).click()
            results = page.get_by_role('region', name='Direct research findings', exact=True)
            await expect(results).to_contain_text('What Jev found across the evidence')
            await expect(results.locator('.artifact-card:visible')).to_have_count(2)
            await results.locator('.artifact-context > summary').click()
            await expect(results.locator('.artifact-card:visible')).to_have_count(3)
            await expect(results.locator('.artifact-context')).to_contain_text('Supporting commentary')
            await results.locator('.artifact-context > summary').click()
            await expect(results.locator('.artifact-card:visible')).to_have_count(2)
            await expect(results.locator('.research-pattern')).to_have_count(3)
            await results.get_by_role('button', name='Show all 4 patterns', exact=True).click()
            await expect(results.locator('.research-pattern')).to_have_count(4)
            await results.get_by_role('button', name='Show fewer patterns', exact=True).click()
            await expect(results.locator('.research-pattern')).to_have_count(3)
            await expect(results.locator('.pattern-unsupported')).to_contain_text('Insufficient evidence')
            await expect(results.locator('.artifact-card').first.locator('.video-observations')).to_contain_text('Unavailable')
            await results.get_by_role('combobox', name='Sort videos', exact=True).select_option('views')
            await expect(results.locator('.artifact-card').first).to_contain_text('24,680')
            await expect(results.locator('.artifact-card').first).to_contain_text('video not watched')
            await expect(results.locator('.artifact-card').first).to_contain_text('Reported date')
            await expect(results.locator('.artifact-card').first).to_contain_text('publication date not verified')
            await expect(results.locator('.artifact-card').first).to_contain_text('2 collected snapshots')
            await results.locator('.artifact-card').first.get_by_role('button', name='Inspect evidence check', exact=True).click()
            await expect(page.get_by_role('dialog')).to_contain_text('Verify selected evidence against each question')
            await expect(page.get_by_role('dialog')).to_contain_text('Check only the supplied synthetic passage.')
            await page.keyboard.press('Escape')
            await results.get_by_role('button', name='Inspect exact evidence', exact=True).click()
            await expect(page.get_by_role('dialog')).to_contain_text('Observed views: 24680.')
            await expect(page.get_by_role('dialog')).to_contain_text('Synthetic indexed metadata only')
            await page.keyboard.press('Escape')
            await page.screenshot(path=str(screenshots / 'adaptive-results-desktop-fixture.png'), full_page=True)
            await page.set_viewport_size({'width': 430, 'height': 932})
            await expect(results.locator('.artifact-description').first).to_contain_text('longpublicidentifier')
            assert not await page.evaluate('document.documentElement.scrollWidth > innerWidth')
            await page.screenshot(path=str(screenshots / 'adaptive-results-mobile-fixture.png'), full_page=True)
            await page.evaluate('(id)=>localStorage.setItem("radar:last",id)', identifiers['mid'])
            await page.reload()
            await expect(page.get_by_role('heading', name='What are you looking for?', exact=True)).to_be_visible()
            await page.get_by_role('button', name='Saved research', exact=True).click()
            await page.locator(f'[data-mission-id="{identifiers["mid"]}"]').click()
            await expect(results).to_contain_text('What Jev found across the evidence')
            session = await (await page.request.get(base + '/api/session')).json()
            headers = {'X-Radar-CSRF': session['csrf']}
            review_url = base + '/api/missions/' + identifiers['mid'] + '/review/fixture-video-1'
            response = await page.request.post(review_url, headers=headers, data={'state': 'rejected', 'note': 'Synthetic evidence review fixture'})
            assert response.ok, await response.text()
            await expect(results.locator('.research-stale-notice')).to_contain_text('Comparison needs reassessment')
            await expect(results.locator('.research-pattern')).to_have_count(0)
            await expect(results.get_by_role('button', name='Inspect comparison', exact=True)).to_have_count(0)
            response = await page.request.post(review_url, headers=headers, data={'state': 'approved', 'note': 'Synthetic restored review fixture'})
            assert response.ok, await response.text()
            await expect(results.locator('.research-stale-notice')).to_be_visible()
            await expect(results.locator('.research-pattern')).to_have_count(0)
            response = await page.request.post(base + '/api/missions/' + identifiers['mid'] + '/steer', headers=headers, data={'query': 'synthetic changed scope only'})
            assert response.ok, await response.text()
            await expect(results.locator('.research-stale-notice')).to_be_visible()
            await expect(results.locator('.research-pattern')).to_have_count(0)
            await expect(results.locator('.artifact-empty')).to_contain_text('No direct examples yet')
            await page.screenshot(path=str(screenshots / 'adaptive-stale-evidence-fixture.png'), full_page=True)
            assert not calls and not errors, {'calls': calls, 'errors': errors}
            assert not store.rows('SELECT * FROM reservations')
            report = {'mode': 'synthetic fixture; no provider calls', 'prompt_always_default': True,
                      'planning_and_comparison_live_phases': True, 'goal_specific_program_visible': True, 'planning_comparison_activity_groups': True,
                      'direct_video_metadata_and_unknowns': True, 'primary_examples_separate_from_commentary': True, 'verification_call_link_inspected': True,
                      'newer_snapshot_beats_later_reassessment_of_old_snapshot': True, 'hypotheses_separate_from_observations': True,
                      'source_citation_inspected': True, 'sort_uses_observed_counts_only': True, 'reported_date_basis_visible': True,
                      'duplicate_video_snapshots_grouped': True, 'patterns_initially_limited': True,
                      'review_and_steering_hide_stale_comparisons': True, 'approval_does_not_restore_invalidated_patterns': True,
                      'mobile_overflow': False, 'javascript_errors': errors}
            (runtime / 'ui-adaptive-smoke.json').write_text(json.dumps(report, indent=2) + '\n')
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
