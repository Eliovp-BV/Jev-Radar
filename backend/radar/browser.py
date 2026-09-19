"""Read-only rendering; all HTTP(S) traffic is fulfilled through the pinned public fetcher."""
import asyncio,os,time,hashlib
from urllib.parse import urlsplit
from pathlib import Path
from playwright.async_api import async_playwright
from .config import ROOT
from .security import validate_url,PolicyError
from .storage import uid,now

class Browser:
    def __init__(self,fetcher,data_dir,concurrency=1): self.fetcher=fetcher; self.data_dir=data_dir; self.sem=asyncio.Semaphore(concurrency)
    async def render(self,url):
        url=validate_url(url); await self.fetcher.permitted(url)
        async with self.sem:
            env={k:os.environ[k] for k in ('PATH','LANG','DISPLAY','XDG_RUNTIME_DIR','TMPDIR') if k in os.environ}
            env['PLAYWRIGHT_BROWSERS_PATH']=str(ROOT/'.cache/ms-playwright')
            # Resolve the driver's cache inside this project. Chromium gets only env above.
            os.environ['PLAYWRIGHT_BROWSERS_PATH']=env['PLAYWRIGHT_BROWSERS_PATH']
            start=time.perf_counter(); trace=[]; count=0
            initial=await self.fetcher.get(url)
            resolved_url=validate_url(initial.get('url',url))
            prefetched={resolved_url:initial}
            if resolved_url!=url:trace.append({'operation':'redirect','requested_url':url,'actual_url':resolved_url,'verified':True,'at':now()})
            async with async_playwright() as p:
                browser=await p.chromium.launch(headless=True,chromium_sandbox=True,env=env,args=['--force-webrtc-ip-handling-policy=disable_non_proxied_udp','--disable-background-networking'])
                try:
                    context=await browser.new_context(service_workers='block',accept_downloads=False,viewport={'width':1280,'height':900})
                    async def route_request(route):
                        nonlocal count
                        request=route.request; count+=1
                        if count>50 or request.method not in ('GET','HEAD'):
                            await route.abort(); return
                        try:
                            target=validate_url(request.url)
                            if request.is_navigation_request() and request.frame==page.main_frame and target!=resolved_url:
                                raise PolicyError('Page-initiated navigation requires a new validated research action')
                            host=urlsplit(target).hostname or ''
                            if any(part in host for part in ('google-analytics','googletagmanager','doubleclick','facebook.net','hotjar','segment.io')):
                                raise PolicyError('Tracking endpoint blocked')
                            response=prefetched.pop(target,None)
                            if response is None:response=await self.fetcher.get(target)
                            resolved=validate_url(response.get('url',target))
                            if resolved!=target:
                                trace.append({'operation':'redirect','requested_url':target,'actual_url':resolved,'verified':True,'at':now()})
                                # Never fulfill with a Location redirect: Chromium can follow it
                                # without a second route callback. All redirect I/O stays in Fetcher.
                            headers={k:v for k,v in response['headers'].items() if k.lower() in ('content-type','cache-control','content-language')}
                            await route.fulfill(status=response['status'],headers=headers,body=response['body'])
                        except Exception as e:
                            trace.append({'operation':'network.blocked','host':urlsplit(request.url).hostname,'method':request.method,'reason':type(e).__name__,'at':now()})
                            await route.abort()
                    await context.route('**/*',route_request)
                    await context.route_web_socket('**/*',lambda ws:ws.close())
                    page=await context.new_page()
                    page.on('popup',lambda popup:asyncio.create_task(popup.close()))
                    page.on('download',lambda d:asyncio.create_task(d.cancel()))
                    navigation=await page.goto(resolved_url,wait_until='domcontentloaded',timeout=45000)
                    await page.wait_for_timeout(750)
                    actual=validate_url(page.url)
                    html=await page.content()
                    if len(html.encode())>2_000_000: raise PolicyError('Rendered DOM exceeds size limit')
                    # Trusted extraction JavaScript only; page strings cannot become executable code.
                    targets=await page.locator('a[href]').evaluate_all('(els) => els.slice(0,80).map((e,i)=>({id:"t"+i,url:e.href,label:e.innerText.slice(0,160)}))')
                    safe=[]
                    for target in targets:
                        try: target['url']=validate_url(target['url']); safe.append(target)
                        except ValueError: pass
                    artifact=uid(); path=self.data_dir/'artifacts'/f'{artifact}.png'; path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                    await page.screenshot(path=str(path),full_page=False)
                    trace.extend([{'operation':'navigate','requested_url':url,'actual_url':actual,'verified':True,'at':now()},
                           {'operation':'inspect','target_count':len(safe),'dom_fingerprint':hashlib.sha256(html.encode()).hexdigest(),'dom_hash_note':'Targets are scoped to this observation; navigation always re-observes.','at':now()}])
                    return {'url':actual,'body':html.encode(),'status':navigation.status if navigation else None,'headers':{'Content-Type':'text/html'},'retrieved_at':now(),
                            'fetch_ms':0,'browser_ms':round((time.perf_counter()-start)*1000,2),'artifact_id':artifact,'targets':safe,'trace':trace}
                finally: await browser.close()
