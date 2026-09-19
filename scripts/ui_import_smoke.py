"""No-key UI/import QA in a separate temporary fixture workspace. No paid calls."""
import asyncio,os,sys,json,tempfile,threading,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import uvicorn
from playwright.async_api import async_playwright
from radar.api import create_app
from radar.config import Settings,ROOT
from radar.storage import uid,now,dumps
from radar.schemas import Plan
from radar.lenses import BUILTINS

async def main():
 os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(ROOT/'.cache/ms-playwright')
 data=Path(tempfile.mkdtemp(prefix='isolated-ui-fixture-',dir=ROOT/'.runtime'))
 app=create_app(Settings(data_dir=data,port=8788,key=''))
 store=app.state.store;store.set_setting('profile',{'name':'Radar · isolated test fixture','accent':'#f1d54a','retention_days':30})
 plan=Plan(goal='Fixture only: validate owner analytics import and unknown metrics',criteria=BUILTINS[3]['criteria']).model_dump();mid=uid()
 store.execute('INSERT INTO missions VALUES(?,?,?,?,?,?,?,?,?)',(mid,plan['goal'],'draft',dumps(plan),1,now(),now(),None,'fixture'));store.event(mid,'fixture.created',{},mode='fixture')
 server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=8788,log_level='error',access_log=False))
 thread=threading.Thread(target=server.run,daemon=True);thread.start()
 try:
  for _ in range(50):
   if server.started:break
   await asyncio.sleep(.1)
  async with async_playwright() as p:
   browser=await p.chromium.launch(headless=True,chromium_sandbox=True)
   page=await browser.new_page(viewport={'width':1450,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
   await page.goto('http://127.0.0.1:8788/');await page.get_by_role('button',name='Saved research').click();await page.locator('.saved-card').click()
   await page.get_by_role('button',name='Check research setup',exact=True).click()
   await page.get_by_role('dialog').get_by_role('heading',name='Settings & connections',exact=True).wait_for()
   await page.keyboard.press('Escape')
   assert await page.get_by_role('button',name='Add websites',exact=True).count()==1
   await page.get_by_role('button',name='Start',exact=True).click();await page.get_by_role('alert').filter(has_text='TypeSafe key required').wait_for()
   await page.get_by_role('button',name='Dismiss error').click()
   await page.get_by_role('button',name='Research details',exact=True).click()
   await page.get_by_role('button',name='Import',exact=True).click();await page.get_by_label('Record type').select_option('analytics')
   await page.get_by_role('textbox',name='Import data').fill((ROOT/'tests/fixtures/analytics.csv').read_text())
   await page.get_by_label('Provenance declaration').fill('Owner fixture export; not authenticated API data')
   await page.get_by_role('button',name='Validate & import').click();await page.get_by_text('Observed traction trail',exact=True).wait_for()
   assert await page.get_by_text('Owner fixture export; not authenticated API data',exact=False).count()>0
   assert await page.get_by_text('Unknown',exact=True).count()>0
   assert await page.locator('.cohort').count()==5
   await page.get_by_label('Metric country',exact=True).select_option('BE')
   await page.get_by_label('Metric period from',exact=True).fill('2026-09-01')
   assert await page.locator('.cohort').count()==0
   await page.get_by_role('button',name='Clear metric filters',exact=True).click()
   assert await page.locator('.cohort').count()==5
   await page.screenshot(path=str(ROOT/'.runtime/screenshots/import-fixture.png'),full_page=True)
   await page.get_by_role('button',name='Import',exact=True).click();await page.get_by_role('textbox',name='Import data').fill('page,provider,measured_at,window_start,window_end,clicks\nhttps://example.com/,Fixture,2026-01-31,2026-01-01,2026-01-31,NaN')
   await page.get_by_role('button',name='Validate & import').click()
   await page.get_by_role('dialog').get_by_role('alert').filter(has_text='finite nonnegative').wait_for()
   await page.screenshot(path=str(ROOT/'.runtime/screenshots/import-rejection-fixture.png'),full_page=True)
   await page.keyboard.press('Escape')
   result={'mode':'isolated fixture workspace','no_key_start_blocked':True,'no_key_setup_opens_typesafe_settings':True,'recovery_actions_deduplicated':True,'analytics_imported':5,'unknown_conversion_preserved':True,'malformed_metric_rejected':True,'matched_filters_recompute_cohorts':True,'javascript_errors':errors,'live_database_unchanged':True}
   (ROOT/'.runtime/import-ui-smoke.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2));await browser.close()
 finally:
  server.should_exit=True;thread.join(timeout=10);shutil.rmtree(data)
asyncio.run(main())
