"""Read-only smoke for any running Radar workspace, including an empty one.

Usage: .venv/bin/python scripts/ui_smoke.py [BASE_URL] [--mission-id ID]
No owner-specific research is required. Browser mutations are blocked except
nonpersisting plan previews. Use ui_lan_smoke.py for isolated control tests.
"""
import argparse
import asyncio
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright, expect

ROOT = Path(__file__).resolve().parents[1]
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / '.cache/ms-playwright')


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base_url', nargs='?', default='http://127.0.0.1:8787')
    parser.add_argument('--mission-id', help='Optionally inspect a specific existing investigation')
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    screenshots = ROOT / '.runtime/screenshots'
    screenshots.mkdir(parents=True, exist_ok=True)
    errors, blocked = [], []
    result = {'mode': 'read-only; no provider or mutation requests', 'mission_inspected': False,
              'sampled_field_citations': 0, 'replay_checked': False}
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, chromium_sandbox=True)
        page = await browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.on('pageerror', lambda error: errors.append(str(error)))

        async def read_only(route):
            request = route.request
            path = urlparse(request.url).path
            if request.method not in ('GET', 'HEAD', 'OPTIONS') and not (request.method == 'POST' and path == '/api/plan'):
                blocked.append({'method': request.method, 'path': path})
                await route.abort('blockedbyclient')
            else:
                await route.continue_()

        await page.route('**/api/**', read_only)
        await page.goto(base)
        await page.get_by_role('button', name='New investigation', exact=True).first.wait_for()
        initial = await (await page.request.get(base + '/api/missions')).json()
        await page.get_by_role('button', name='New investigation', exact=True).first.click()
        await expect(page.get_by_role('textbox', name='Seed URLs', exact=True)).to_be_hidden()
        await expect(page.get_by_role('button', name='Review research plan', exact=True)).to_be_hidden()
        await expect(page.get_by_role('heading', name='What are you looking for?', exact=True)).to_be_visible()
        await page.screenshot(path=str(screenshots / 'home-desktop.png'), full_page=True)
        await page.get_by_role('button', name='User guide', exact=True).click()
        await expect(page.get_by_role('heading', name='Good questions. Clear evidence.', exact=True)).to_be_visible()
        await page.get_by_role('searchbox', name='Find an answer', exact=True).fill('TYPESAFE_API_KEY')
        await expect(page.get_by_role('article', name='API keys & setup', exact=True)).to_be_visible()
        await expect(page.get_by_label('Server environment variable example')).to_contain_text('BRAVE_SEARCH_API_KEY=your_brave_search_key')
        await page.get_by_role('button', name='Clear guide search', exact=True).click()

        selected = next((mission for mission in initial if mission['id'] == args.mission_id), None) if args.mission_id else (initial[0] if initial else None)
        if args.mission_id and selected is None:
            raise AssertionError('Requested mission ID is not present in this workspace')
        if selected:
            await page.evaluate('(id) => localStorage.setItem("radar:last", id)', selected['id'])
            await page.reload()
            await expect(page.get_by_role('heading', name='What are you looking for?', exact=True)).to_be_visible()
            await page.get_by_role('button', name='Saved research', exact=True).click()
            await page.locator(f'[data-mission-id="{selected["id"]}"]').click()
            await expect(page.locator('.outcome-card')).to_be_visible()
            mission = await (await page.request.get(base + '/api/missions/' + selected['id'])).json()
            await expect(page.get_by_role('button', name='Results', exact=True)).to_have_class(re.compile('active'))
            result['mission_inspected'] = True
            await page.screenshot(path=str(screenshots / 'mission-results.png'), full_page=True)
            await page.get_by_role('button', name='Research details', exact=True).click()
            await page.get_by_role('button', name='Comparison', exact=True).click()
            citations = page.locator('.field-citation')
            for index in range(min(await citations.count(), 4)):
                await citations.nth(index).click()
                await expect(page.get_by_role('dialog')).to_be_visible()
                await expect(page.locator('blockquote').first).to_be_visible()
                if index == 0:
                    await page.screenshot(path=str(screenshots / 'evidence.png'), full_page=True)
                await page.keyboard.press('Escape')
                result['sampled_field_citations'] += 1
            await page.get_by_role('button', name='Map', exact=True).click()
            await expect(page.locator('.react-flow__node').first).to_be_visible()
            await page.screenshot(path=str(screenshots / 'mission-map.png'), full_page=True)
            if mission.get('events'):
                await page.get_by_role('button', name='Replay', exact=True).click()
                await page.wait_for_timeout(600)
                requests = []
                record = lambda request: requests.append(request.url)
                page.on('request', record)
                await page.get_by_role('slider', name='Replay position').fill('0')
                await page.wait_for_timeout(500)
                page.remove_listener('request', record)
                assert not requests, 'Replay caused unexpected network requests'
                await page.get_by_role('button', name='Return to latest state', exact=True).click()
                result['replay_checked'] = True
            await page.set_viewport_size({'width': 430, 'height': 932})
            await page.wait_for_timeout(300)
            assert not await page.evaluate('document.documentElement.scrollWidth > innerWidth')
            await page.screenshot(path=str(screenshots / 'mission-mobile.png'), full_page=True)
        await page.get_by_role('button', name='New investigation', exact=True).first.click()
        await page.set_viewport_size({'width': 430, 'height': 932})
        await page.wait_for_timeout(250)
        assert not await page.evaluate('document.documentElement.scrollWidth > innerWidth')
        await page.screenshot(path=str(screenshots / 'home-mobile.png'), full_page=True)
        await page.get_by_role('button', name='Settings', exact=True).click()
        await expect(page.get_by_role('dialog')).to_be_visible()
        await expect(page.get_by_role('tab', name='API connections', exact=True)).to_be_visible()
        await page.keyboard.press('Tab')
        await page.keyboard.press('Escape')
        await expect(page.get_by_role('dialog')).to_be_hidden()
        final = await (await page.request.get(base + '/api/missions')).json()
        assert {mission['id'] for mission in initial} == {mission['id'] for mission in final}
        assert not errors, errors
        assert not blocked, blocked
        result.update(javascript_errors=errors, blocked_mutations=blocked, narrow_horizontal_overflow=False,
                      saved_missions_unchanged=True, saved_mission_count=len(initial), guide_search=True)
        (ROOT / '.runtime/ui-smoke.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result, indent=2))
        await browser.close()


if __name__ == '__main__':
    asyncio.run(main())
