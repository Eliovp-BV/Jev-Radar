"""Fresh-install UI regression with isolated configuration and no provider calls.

Run: .venv/bin/python scripts/ui_simplified_smoke.py
Exercises no-key setup, settings persistence, goal-based plan selection, guide
search and mobile layout using a temporary empty database and the built UI.
Never loads the project .env or alters a running workspace. No research starts.
"""
import asyncio
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import uvicorn
from playwright.async_api import async_playwright, expect
from radar.api import create_app
from radar.config import ROOT, Settings


async def main():
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(ROOT / '.cache/ms-playwright')
    runtime = ROOT / '.runtime'
    runtime.mkdir(exist_ok=True)
    screenshots = runtime / 'screenshots'
    screenshots.mkdir(exist_ok=True)
    data = Path(tempfile.mkdtemp(prefix='fresh-ui-fixture-', dir=runtime))
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    settings = Settings(data_dir=data, host='127.0.0.1', port=port, key='', brave_key='')
    app = create_app(settings)
    calls, errors = [], []

    def forbidden(*args, **kwargs):
        calls.append('provider-or-research')
        raise AssertionError('This isolated smoke must not call a provider or start research')

    async def forbidden_async(*args, **kwargs):
        forbidden()

    app.state.runner.launch = forbidden
    app.state.runner.jev.client = forbidden
    app.state.runner.search.query = forbidden_async
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=port, log_level='error', access_log=False, timeout_graceful_shutdown=2))
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
            page = await browser.new_page(viewport={'width': 1920, 'height': 1100})
            page.on('pageerror', lambda error: errors.append(str(error)))
            await page.goto(base)
            await expect(page.get_by_role('textbox', name='Research goal', exact=True)).to_be_visible()
            await expect(page.get_by_role('textbox', name='Seed URLs', exact=True)).to_be_hidden()
            await expect(page.get_by_role('heading', name='What are you looking for?', exact=True)).to_be_visible()
            await expect(page.locator('.focus-rail .rail-control.primary > span')).to_be_visible()
            await expect(page.locator('.focus-rail .rail-control.primary > span')).to_have_text('Live')
            shell_width = (await page.locator('.shell').bounding_box())['width']
            assert (await page.locator('.prompt-home').bounding_box())['width'] >= shell_width * .9
            assert (await page.locator('.prompt-composer').bounding_box())['width'] >= shell_width * .85
            await expect(page.get_by_role('button', name='Review research plan', exact=True)).to_be_hidden()
            await expect(page.locator('.source-mode')).to_contain_text('Connect your API keys')
            await expect(page.locator('.prompt-examples button')).to_have_count(3)
            await page.locator('.prompt-examples button').first.click()
            await expect(page.get_by_role('textbox', name='Research goal', exact=True)).not_to_have_value('')
            await expect(page.get_by_role('textbox', name='Research goal', exact=True)).to_be_focused()
            assert not calls
            assert await (await page.request.get(base + '/api/missions')).json() == []
            assert await (await page.request.get(base + '/api/missions')).json() == []
            await page.screenshot(path=str(screenshots / 'fresh-home-desktop.png'), full_page=True)

            await page.get_by_role('textbox', name='Research goal', exact=True).fill('Find competitors for a collaborative document editor and compare public pricing.')
            await page.get_by_role('button', name='Start research', exact=True).click()
            await expect(page.get_by_role('button', name='Start investigation', exact=True)).to_be_disabled()
            await expect(page.locator('.plan-readiness')).to_contain_text('TypeSafe')
            await expect(page.locator('.plan-readiness')).to_contain_text('Brave')
            await expect(page.locator('.plan-approach')).to_contain_text('Competitor landscape')

            # Missing TypeSafe setup opens automatically from direct submission.
            dialog = page.get_by_role('dialog')
            await expect(dialog).to_be_visible()
            await expect(page.get_by_role('tab', name='API connections', exact=True)).to_be_visible()
            await page.screenshot(path=str(screenshots / 'fresh-settings-wide-diagnostic.png'), full_page=True)
            dialog_box = await dialog.bounding_box()
            assert dialog_box['width'] >= 1920 * .9, dialog_box
            await expect(dialog.locator('pre')).to_contain_text('TYPESAFE_API_KEY=your_typesafe_key')
            await expect(dialog.locator('pre')).to_contain_text('BRAVE_SEARCH_API_KEY=your_brave_search_key')
            assert await dialog.locator('input[type=password]').count() == 0
            await expect(page.get_by_role('button', name='Test Jev connection', exact=True)).to_be_disabled()
            await page.screenshot(path=str(screenshots / 'fresh-key-setup-desktop.png'), full_page=True)
            configured = Settings(data_dir=data, host='127.0.0.1', port=port,
                                  key='isolated-fixture-not-a-real-key', brave_key='isolated-fixture-not-a-search-key')
            with patch('radar.api.Settings.load', return_value=configured):
                await page.get_by_role('button', name='Reload keys', exact=True).click()
                await expect(page.get_by_role('button', name='Test Jev connection', exact=True)).to_be_enabled()
            assert await dialog.locator('.setup-status.configured').count() == 2
            assert 'isolated-fixture-not' not in await dialog.inner_text()
            assert 'invaliddate' not in ''.join((await dialog.inner_text()).lower().split())
            await expect(dialog.locator('.connection-last')).to_contain_text('test the Jev connection')
            assert not calls

            await page.get_by_role('tab', name='Research defaults', exact=True).click()
            await page.get_by_role('combobox', name='Research approach', exact=True).select_option('auto')
            await page.get_by_role('spinbutton', name='Maximum pages', exact=True).fill('17')
            await page.get_by_role('spinbutton', name='Maximum search queries', exact=True).fill('3')
            await page.get_by_role('textbox', name='Region (optional)', exact=True).fill('Canada')
            await page.get_by_role('button', name='Save research defaults', exact=True).click()
            await expect(page.locator('.alert').filter(has_text='Settings saved')).to_be_visible()
            await page.screenshot(path=str(screenshots / 'fresh-defaults-desktop.png'), full_page=True)
            await page.get_by_role('tab', name='Workspace', exact=True).click()
            await page.get_by_role('textbox', name='Workspace name', exact=True).fill('Research studio · UI fixture')
            await page.get_by_role('button', name='Save workspace settings', exact=True).click()
            await page.keyboard.press('Escape')
            await page.reload()
            await page.get_by_role('button', name='Settings', exact=True).wait_for()
            await page.get_by_role('button', name='Settings', exact=True).click()
            await page.get_by_role('tab', name='Research defaults', exact=True).click()
            await expect(page.get_by_role('spinbutton', name='Maximum pages', exact=True)).to_have_value('17')
            await expect(page.get_by_role('spinbutton', name='Maximum search queries', exact=True)).to_have_value('3')
            await expect(page.get_by_role('textbox', name='Region (optional)', exact=True)).to_have_value('Canada')
            await page.get_by_role('tab', name='Workspace', exact=True).click()
            await expect(page.get_by_role('textbox', name='Workspace name', exact=True)).to_have_value('Research studio · UI fixture')
            await page.keyboard.press('Escape')
            await page.get_by_role('button', name='Saved research', exact=True).click()
            await expect(page.locator('.library')).to_be_visible()
            assert (await page.locator('.library').bounding_box())['width'] >= shell_width * .9
            await page.screenshot(path=str(screenshots / 'fresh-library-wide.png'), full_page=True)

            for goal, expected in [
                ('Research useful public articles about remote collaboration and identify content gaps.', 'Content & search'),
                ('Compare public campaign distribution and engagement evidence for collaboration products.', 'Campaign & traction'),
                ('Investigate documented limitations of file format interoperability.', 'Open investigation'),
            ]:
                await page.get_by_role('button', name='New investigation', exact=True).first.click()
                await page.get_by_role('textbox', name='Research goal', exact=True).fill(goal)
                await page.get_by_role('button', name='Research options', exact=True).click()
                await page.get_by_role('button', name='Review research plan', exact=True).click()
                await expect(page.locator('.plan-approach')).to_contain_text(expected)
                await expect(page.locator('.plan-recap')).to_contain_text('17')
                await expect(page.get_by_role('button', name='Start investigation', exact=True)).to_be_enabled()
            await page.screenshot(path=str(screenshots / 'fresh-generic-plan.png'), full_page=True)

            async def review_goal(goal):
                await page.get_by_role('textbox', name='Research goal', exact=True).fill(goal)
                if not await page.get_by_role('button', name='Review research plan', exact=True).is_visible():
                    await page.get_by_role('button', name='Research options', exact=True).click()
                async with page.expect_response(lambda response: response.url.endswith('/api/plan') and response.request.method == 'POST') as response:
                    await page.get_by_role('button', name='Review research plan', exact=True).click()
                reviewed = await response.value
                assert reviewed.ok, await reviewed.text()
                return await reviewed.json()

            # Refining an untouched auto-selected plan should choose questions
            # for the new goal, without silently preserving the prior category.
            await page.get_by_role('button', name='New investigation', exact=True).first.click()
            original = await review_goal('Find competitors for a shared document editor and compare public pricing.')
            assert original['plan']['lens_id'] == 'landscape'
            assert original['plan']['research_mode'] == 'adaptive'
            await page.get_by_role('textbox', name='Geography', exact=True).fill('France')
            await expect(page.locator('.plan-preview')).to_have_count(0)
            revised = await review_goal('Research useful public articles about remote work and identify content gaps.')
            assert revised['plan']['lens_id'] == 'content'
            assert revised['plan']['criteria'] != original['plan']['criteria']
            await expect(page.locator('.plan-approach')).to_contain_text('Content & search')

            # Once the user edits a question, refining the goal must preserve
            # their full edited criterion set, including IDs, labels and rubrics.
            await page.get_by_role('button', name='New investigation', exact=True).first.click()
            original = await review_goal('Find competitors for a shared document editor and compare public pricing.')
            expected_criteria = deepcopy(original['plan']['criteria'])
            expected_criteria[0]['question'] = 'Which documented administrative controls support a small distributed team?'
            await page.locator('.plan-customize > summary').click()
            await page.locator('.question-edit textarea').first.fill(expected_criteria[0]['question'])
            revised = await review_goal('Research useful public articles about remote work, emphasizing documented administration for small teams.')
            assert revised['plan']['research_mode'] == 'fixed'
            assert revised['plan']['criteria'] == expected_criteria, 'Refining the goal discarded the user-edited questions'
            await page.locator('.plan-customize > summary').click()
            await expect(page.locator('.question-edit textarea').first).to_have_value(expected_criteria[0]['question'])

            # Provider changes invalidate the scope. Direct start must recheck
            # readiness before creating anything, even after an earlier review.
            if not await page.get_by_role('checkbox', name='Brave web search', exact=True).is_visible():
                await page.get_by_role('button', name='Research options', exact=True).click()
            await page.get_by_role('checkbox', name='Brave web search', exact=True).uncheck()
            await expect(page.locator('.plan-preview')).to_have_count(0)
            await expect(page.get_by_role('button', name='Start investigation', exact=True)).to_be_hidden()
            await page.get_by_role('button', name='Start research', exact=True).click()
            await expect(page.get_by_role('button', name='Start investigation', exact=True)).to_be_disabled()
            assert await (await page.request.get(base + '/api/missions')).json() == []

            await page.get_by_role('button', name='User guide', exact=True).click()
            await expect(page.get_by_role('heading', name='Good questions. Clear evidence.', exact=True)).to_be_visible()
            assert (await page.locator('.radar-guide').bounding_box())['width'] >= shell_width * .9
            await page.screenshot(path=str(screenshots / 'guide-desktop.png'), full_page=True)
            guide_search = page.get_by_role('searchbox', name='Find an answer', exact=True)
            await guide_search.fill('TYPESAFE_API_KEY')
            await expect(page.get_by_role('article', name='API keys & setup', exact=True)).to_be_visible()
            await expect(page.get_by_label('Server environment variable example')).to_contain_text('BRAVE_SEARCH_API_KEY=your_brave_search_key')
            await expect(page.locator('.guide-content')).to_contain_text('Reload keys')
            await page.screenshot(path=str(screenshots / 'guide-key-setup-desktop.png'), full_page=True)
            await guide_search.fill('CAPTCHA')
            await expect(page.get_by_role('article', name='Troubleshooting', exact=True)).to_be_visible()
            await expect(page.locator('.guide-faq details').filter(has_text='website blocks access')).to_have_attribute('open', '')
            await guide_search.fill('no-matching-fixture-query')
            await expect(page.get_by_role('heading', name='No matching guide sections', exact=True)).to_be_visible()
            await page.get_by_role('button', name='Show all sections', exact=True).click()
            guide_nav = page.get_by_role('navigation', name='Guide sections', exact=True)
            await guide_nav.get_by_role('button', name='What Jev does', exact=True).focus()
            await page.keyboard.press('Enter')
            await expect(page.get_by_role('article', name='What Jev does', exact=True)).to_be_focused()
            await expect(page.locator('.guide-content')).to_contain_text('Request timing includes network travel and provider processing')
            await expect(page.locator('.guide-content')).to_contain_text('Refine unanswered questions')
            await page.screenshot(path=str(screenshots / 'guide-jev-desktop.png'), full_page=True)
            await guide_nav.get_by_role('button', name='Videos & virality', exact=True).click()
            await expect(page.get_by_role('article', name='Videos & virality', exact=True)).to_be_visible()
            await expect(page.locator('.guide-content')).to_contain_text('Video frames and audio are not analyzed')
            await page.screenshot(path=str(screenshots / 'guide-video-evidence-desktop.png'), full_page=True)
            await guide_nav.get_by_role('button', name='Jev ecosystem', exact=True).click()
            await expect(page.locator('.guide-content')).to_contain_text('not installed Radar integrations')
            await expect(page.locator('.guide-content a[href="https://github.com/browser-use/jev-ultrafast"]')).to_be_visible()
            await page.screenshot(path=str(screenshots / 'guide-ecosystem-desktop.png'), full_page=True)
            await page.set_viewport_size({'width': 430, 'height': 932})
            await guide_nav.get_by_role('button', name='Getting started', exact=True).click()
            await page.wait_for_timeout(200)
            await page.evaluate('window.scrollTo(0, 0)')
            assert not await page.evaluate('document.documentElement.scrollWidth > innerWidth')
            await page.screenshot(path=str(screenshots / 'guide-mobile.png'), full_page=True)
            await page.get_by_role('button', name='Settings', exact=True).click()
            await expect(page.get_by_role('dialog')).to_be_visible()
            assert not await page.evaluate('document.documentElement.scrollWidth > innerWidth')
            await page.screenshot(path=str(screenshots / 'fresh-settings-mobile.png'), full_page=True)
            await page.keyboard.press('Escape')
            await page.get_by_role('button', name='New investigation', exact=True).first.click()
            await expect(page.get_by_role('textbox', name='Research goal', exact=True)).to_be_visible()
            assert not await page.evaluate('document.documentElement.scrollWidth > innerWidth')
            submit_box = await page.get_by_role('button', name='Start research', exact=True).bounding_box()
            assert submit_box and submit_box['y'] + submit_box['height'] < 932
            await page.screenshot(path=str(screenshots / 'fresh-home-mobile.png'), full_page=True)
            assert not calls, calls
            assert not errors, errors
            assert not app.state.store.rows('SELECT * FROM reservations')
            assert not app.state.store.rows('SELECT * FROM missions')
            result = {'mode': 'isolated empty workspace; synthetic configuration only', 'provider_calls': 0,
                      'research_created': 0, 'initial_missing_keys_block_start': True,
                      'reload_keys_reads_only_patched_fixture': True, 'keys_not_exposed': True, 'untested_keys_have_no_invalid_date': True,
                      'settings_and_defaults_persist': True, 'generic_goal_lenses': True,
                      'unedited_goal_reselects_auto_lens_after_option_change': True, 'edited_questions_survive_goal_refinement': True,
                      'example_chips_only_fill_and_focus': True,
                      'provider_changes_rechecked_before_direct_start': True,
                      'guide_full_text_search': True, 'adaptive_video_and_ecosystem_guide': True, 'live_navigation_label_visible': True, 'guide_keyboard_navigation': True,
                      'home_guide_settings_library_use_available_width': True,
                      'narrow_horizontal_overflow': False, 'javascript_errors': errors}
            (runtime / 'ui-simplified-smoke.json').write_text(json.dumps(result, indent=2))
            print(json.dumps(result, indent=2))
            await browser.close()
            # The general read-only smoke must also work without private saved
            # research. Exercise it against this same isolated empty workspace.
            process = await asyncio.create_subprocess_exec(sys.executable, str(ROOT / 'scripts/ui_smoke.py'), base,
                                                          stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            try:
                output, _ = await asyncio.wait_for(process.communicate(), timeout=45)
            except TimeoutError:
                process.kill()
                await process.wait()
                raise
            assert process.returncode == 0, output.decode()
            assert not calls
    finally:
        server.should_exit = True
        await asyncio.to_thread(thread.join, 5)
        if thread.is_alive():
            server.force_exit = True
            await asyncio.to_thread(thread.join, 3)
        app.state.store.close()
        sock.close()
        shutil.rmtree(data, ignore_errors=True)


if __name__ == '__main__':
    asyncio.run(main())
