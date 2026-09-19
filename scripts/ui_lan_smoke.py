"""Browser regression for UUIDs and recovery over HTTP LAN and localhost.

Usage: .venv/bin/python scripts/ui_lan_smoke.py <this-machine-LAN-IP>
Isolated fixture database and simulated runner; no provider calls or live records.
"""
import argparse,asyncio,ipaddress,json,os,re,shutil,socket,sys,tempfile,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import uvicorn
from playwright.async_api import async_playwright
from radar.api import create_app
from radar.config import ROOT,Settings

async def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('lan_ip',type=ipaddress.IPv4Address,help='This computer’s LAN IPv4 address; the test creates its own temporary fixture server.')
 lan=str(parser.parse_args().lan_ip)
 if ipaddress.ip_address(lan).is_loopback:raise ValueError('Provide a LAN IP to exercise insecure HTTP')
 os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(ROOT/'.cache/ms-playwright')
 runtime=ROOT/'.runtime';runtime.mkdir(exist_ok=True)
 data=Path(tempfile.mkdtemp(prefix='lan-ui-fixture-',dir=runtime))
 sock=socket.socket();sock.bind(('0.0.0.0',0));port=sock.getsockname()[1]
 app=create_app(Settings(data_dir=data,port=port,key='fixture-only-never-sent'))
 store=app.state.store
 store.set_setting('profile',{'name':'Radar · HTTP compatibility fixture','accent':'#f1d54a','retention_days':30})
 launched=[]
 def simulated_launch(mid):
  launched.append(mid)
  store.execute("UPDATE missions SET mode='fixture' WHERE id=?",(mid,))
  store.event(mid,'fixture.runner_started',{},mode='fixture')
 def forbid_provider():raise AssertionError('This regression test must not call a provider')
 app.state.runner.launch=simulated_launch
 app.state.runner.jev.client=forbid_provider
 server=uvicorn.Server(uvicorn.Config(app,host='0.0.0.0',port=port,log_level='error',access_log=False))
 thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
 try:
  for _ in range(50):
   if server.started:break
   await asyncio.sleep(.1)
  assert server.started
  results=[]
  async with async_playwright() as p:
   browser=await p.chromium.launch(headless=True,chromium_sandbox=True)
   for host,secure in [('127.0.0.1',True),(lan,False)]:
    page=await browser.new_page(viewport={'width':1500,'height':1100});errors=[];commands=[];steers=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:commands.append(r.post_data_json) if r.method=='POST' and r.url.endswith('/command') else None)
    page.on('request',lambda r:steers.append(r.post_data_json) if r.method=='POST' and r.url.endswith('/steer') else None)
    await page.goto(f'http://{host}:{port}/')
    crypto=await page.evaluate('({secure:isSecureContext,randomUUID:typeof crypto.randomUUID,getRandomValues:typeof crypto.getRandomValues})')
    assert crypto['secure']==secure
    assert crypto['randomUUID']==('function' if secure else 'undefined')
    assert crypto['getRandomValues']=='function'
    await page.get_by_role('textbox',name='Research goal',exact=True).fill('Fixture only: start and cancel over HTTP with no research execution')
    await page.get_by_role('button',name='Research options').click()
    await page.get_by_role('checkbox',name='Brave web search').uncheck()
    await page.get_by_role('textbox',name='Seed URLs',exact=True).fill('https://example.com/')
    await page.get_by_role('button',name='Review research plan').click()
    await page.locator('.plan-customize>summary').click()
    await page.get_by_role('button',name='Save as a custom lens').click()
    await page.get_by_label('Lens name',exact=True).fill('HTTP compatibility fixture')
    await page.get_by_role('button',name='Save new lens',exact=True).click()
    await page.get_by_role('dialog').wait_for(state='hidden')
    if secure:
     await page.get_by_role('button',name='Start research',exact=True).click()
    else:
     await page.get_by_role('textbox',name='Research goal',exact=True).focus()
     await page.keyboard.press('Enter')
    await page.get_by_role('region',name='Jev live research',exact=True).wait_for()
    await page.get_by_role('button',name='Cancel mission',exact=True).wait_for()
    mid=launched[-1]
    assert store.mission(mid)['status']=='running'
    assert re.fullmatch(r'custom-[0-9a-f]{8}',store.mission(mid)['plan']['lens_id'])
    await page.get_by_role('button',name='Cancel mission',exact=True).click()
    await page.locator('.mission-kicker .badge').filter(has_text='cancelled').wait_for()
    assert store.mission(mid)['status']=='cancelled'
    assert [c['action'] for c in commands]==['start','cancel']

    # The simulated runner does no research. Seed an explicit fixture note and
    # partial state to exercise the same recovery controls as a real short run.
    note={'id':'recovery-note-'+mid,'text':'Isolated fixture evidence-preservation marker; not research evidence.'}
    store.mutate(mid,'fixture.partial',{'reason':'Browser test state only'},[('note',note)],status='partial',mode='fixture')
    await page.reload()
    await page.get_by_role('heading',name='What are you looking for?',exact=True).wait_for()
    await page.get_by_role('button',name='Saved research',exact=True).click()
    await page.locator(f'[data-mission-id="{mid}"]').click()
    await page.locator('.mission-kicker .badge').filter(has_text='partial').wait_for()
    await page.get_by_role('button',name='Add websites',exact=True).click()
    await page.get_by_role('textbox',name='Websites to add',exact=True).fill('https://example.com/')
    await page.get_by_role('button',name='Add websites & continue',exact=True).click()
    await page.get_by_role('dialog').get_by_role('alert').filter(has_text='already in this investigation').wait_for()
    assert [c['action'] for c in commands]==['start','cancel'] and not steers
    assert store.mission(mid)['status']=='partial'
    await page.get_by_role('textbox',name='Websites to add',exact=True).fill('https://example.net/')
    await page.get_by_role('button',name='Add websites & continue',exact=True).click()
    await page.get_by_role('dialog').wait_for(state='hidden')
    await page.get_by_role('button',name='Cancel mission',exact=True).wait_for()
    assert launched[-1]==mid
    assert store.mission(mid)['status']=='running'
    assert store.mission(mid)['plan']['seeds']==['https://example.com/','https://example.net/']
    assert steers==[{'url':'https://example.net/'}]
    assert [c['action'] for c in commands]==['start','cancel','retry']
    assert store.records(mid,'note')==[note]
    await page.get_by_role('button',name='Cancel mission',exact=True).click()
    await page.locator('.mission-kicker .badge').filter(has_text='cancelled').wait_for()

    # Editing a finished plan must create a fresh child. Reusing completed
    # actions in the old mission would silently skip the changed questions.
    store.mutate(mid,'fixture.partial',{'reason':'Browser test state only'},status='partial',mode='fixture')
    old_mission=store.mission(mid);old_records=store.records(mid)
    await page.reload()
    await page.get_by_role('heading',name='What are you looking for?',exact=True).wait_for()
    await page.get_by_role('button',name='Saved research',exact=True).click()
    await page.locator(f'[data-mission-id="{mid}"]').click()
    await page.locator('.mission-kicker .badge').filter(has_text='partial').wait_for()
    await page.get_by_role('button',name='Research details',exact=True).click()
    await page.get_by_role('button',name='Edit plan',exact=True).click()
    revised_goal='Fixture only: revise the research question without rewriting previous evidence'
    await page.get_by_role('textbox',name='Research goal',exact=True).fill(revised_goal)
    await page.get_by_role('button',name='Review research plan',exact=True).click()
    await page.get_by_role('button',name='Save & continue',exact=True).click()
    await page.get_by_role('button',name='Cancel mission',exact=True).wait_for()
    child=launched[-1]
    assert child!=mid
    child_mission=store.mission(child)
    assert child_mission['status']=='running' and child_mission['parent_id']==mid
    assert child_mission['goal']==revised_goal and child_mission['plan']['freshness']=='recent'
    assert store.mission(mid)==old_mission and store.records(mid)==old_records
    assert not store.records(child)
    await page.get_by_role('button',name='Cancel mission',exact=True).click()
    await page.locator('.mission-kicker .badge').filter(has_text='cancelled').wait_for()
    assert store.mission(child)['status']=='cancelled'
    assert [c['action'] for c in commands]==['start','cancel','retry','cancel','start','cancel']
    ids=[c['idempotency_key'] for c in commands]
    assert len(set(ids))==len(ids) and all(re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}',i) for i in ids)
    assert not store.rows('SELECT * FROM reservations')
    assert not errors and await page.get_by_role('alert').count()==0
    results.append({'origin':f'http://{host}:{port}','crypto':crypto,'prompt_default_after_reload':True,'custom_lens_saved':True,'start_and_cancel':True,
                    'duplicate_source_rejected_without_command':True,'new_source_retries_same_investigation':True,
                    'revised_plan_starts_fresh_child':True,'prior_goal_and_records_preserved':True,
                    'distinct_uuid_v4_command_ids':True,'command_count':len(commands),'paid_attempts':0,'javascript_errors':errors})
    await page.close()
   await browser.close()
  out={'mode':'isolated fixture, simulated runner, no inference','checks':results}
  (runtime/'lan-uuid-smoke.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2))
 finally:
  server.should_exit=True;thread.join(timeout=10);sock.close();shutil.rmtree(data)

if __name__=='__main__':asyncio.run(main())
