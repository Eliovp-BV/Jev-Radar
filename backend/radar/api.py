import asyncio,json,secrets,re,os,ipaddress
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime,timezone,timedelta
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import JSONResponse,FileResponse,StreamingResponse,Response
from fastapi.staticfiles import StaticFiles
from typesafe_sdk import Choice,Noul
from .config import Settings,ROOT
from .storage import Store,now,uid,dumps
from .schemas import Plan,Lens,Command,Steer,Review,ImportRequest,Profile,ResearchDefaults,MissionOut,MissionDetailOut,TextModelSettings,SpendLimits
from .text_model import TextModel,TextModelError,TextBudgetError
from .lenses import BUILTINS,suggested_lens
from .actions import DEFAULT_ACTIONS,ActionTemplate
from .research import Runner
from .search import queries_for
from .security import validate_url,PolicyError
from .imports import parse_import,ImportError,cohorts
from .reports import telemetry,opportunities,report
from .outcomes import mission_outcome,plan_readiness
from .landscape import landscape
from .activity import jev_activity
from .artifact_research import invalidate_research
from .synthesis import current_brief
from .corpus import corpus_summary


def browser_installed(cache_dir=None):
    """Detect downloaded browser executables without starting Playwright.

    Cache revision names change with Playwright releases. A directory alone is
    insufficient: interrupted downloads can leave an empty revision folder.
    This checks installation files; sandbox/runtime dependencies are checked on
    browser launch.
    """
    cache_dir = Path(cache_dir) if cache_dir is not None else ROOT / '.cache/ms-playwright'
    layouts = (
        'chromium-*/chrome-linux*/chrome',
        'chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium',
        'chromium-*/chrome-win*/chrome.exe',
        'chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell',
        'chromium_headless_shell-*/chrome-headless-shell-*/chrome-headless-shell.exe',
        'chromium_headless_shell-*/chrome-*/headless_shell',
        'chromium_headless_shell-*/chrome-*/headless_shell.exe',
    )
    return any(path.is_file() and (path.suffix == '.exe' or os.access(path, os.X_OK))
               for layout in layouts for path in cache_dir.glob(layout))


def create_app(settings=None):
    settings=settings or Settings.load()
    settings.data_dir.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(settings.data_dir,0o700)
    store=Store(settings.data_dir/'radar.sqlite'); runner=Runner(settings,store); csrf=secrets.token_urlsafe(32)
    text_model=getattr(runner,'text',None) or TextModel(settings,store)
    @asynccontextmanager
    async def lifespan(app):
        store.recover()
        yield
        for mid in list(runner.tasks): await runner.stop(mid)
        store.close()
    app=FastAPI(title='Jev Radar by Eliovp',version='0.1.0',lifespan=lifespan,docs_url=None,redoc_url=None)
    app.state.store=store; app.state.runner=runner; app.state.text_model=text_model
    origins={f'http://127.0.0.1:{settings.port}',f'http://localhost:{settings.port}','http://127.0.0.1:5173','http://localhost:5173'}
    hosts={f'127.0.0.1:{settings.port}',f'localhost:{settings.port}','testserver','127.0.0.1:5173','localhost:5173'}
    @app.middleware('http')
    async def local_security(request,call_next):
        request_hosts=hosts;request_origins=origins
        # Uvicorn supplies the actual local socket address, independent of Host
        # and forwarded headers. This permits LAN IP access without trusting arbitrary domains.
        server=request.scope.get('server')
        if settings.host not in ('127.0.0.1','localhost') and server:
            try:address=ipaddress.IPv4Address(server[0])
            except ValueError:address=None
            if address and not address.is_unspecified and server[1]==settings.port:
                authority=f'{address}:{settings.port}'
                request_hosts=hosts|{authority}
                request_origins=origins|{f'http://{authority}'}
        if request.headers.get('host','') not in request_hosts: return JSONResponse({'detail':'Host rejected'},400)
        origin=request.headers.get('origin')
        if origin and origin not in request_origins: return JSONResponse({'detail':'Origin rejected'},403)
        if request.headers.get('sec-fetch-site')=='cross-site': return JSONResponse({'detail':'Cross-site request rejected'},403)
        if request.url.path.startswith('/api/') and request.url.path!='/api/session':
            if request.cookies.get('radar_session')!=csrf: return JSONResponse({'detail':'Open Radar in your browser to initialize a session'},401)
            if request.method not in ('GET','HEAD','OPTIONS') and request.headers.get('x-radar-csrf')!=csrf: return JSONResponse({'detail':'CSRF token required'},403)
        length=request.headers.get('content-length','0')
        try:
            if int(length)>1_100_000: return JSONResponse({'detail':'Request exceeds body limit'},413)
        except ValueError: return JSONResponse({'detail':'Invalid content length'},400)
        if request.method in ('POST','PUT','PATCH'):
            body=bytearray()
            async for chunk in request.stream():
                if len(body)+len(chunk)>1_100_000: return JSONResponse({'detail':'Request exceeds body limit'},413)
                body.extend(chunk)
            request._body=bytes(body)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Cache-Control']='no-store'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'; form-action 'self'"
        return response
    @app.exception_handler(KeyError)
    async def missing(request,error): return JSONResponse({'detail':'Record not found'},404)
    @app.exception_handler(PolicyError)
    async def policy(request,error): return JSONResponse({'detail':str(error)},422)
    @app.get('/api/session')
    async def session():
        r=JSONResponse({'csrf':csrf}); r.set_cookie('radar_session',csrf,httponly=True,samesite='strict',max_age=86400); return r
    def lenses(): return store.setting('lenses',BUILTINS)
    def capabilities():
        connection=store.setting('connection')
        research_defaults=store.setting('research_defaults',ResearchDefaults().model_dump())
        text_config=text_model.config()
        return {'jev':bool(settings.key),'requested_model':settings.model,'brave':bool(settings.brave_key),
                'wikipedia':'Best-effort public encyclopedia search; not general web search','seed':True,
                'browser_installed':browser_installed(),
                'text_model':text_config,'text_provider':text_config['provider'],
                'spend_limits':{'jev_usd':research_defaults['limits']['usd'],'text_usd':text_config['usd']},
                'pricing':{'input_usd_per_million':settings.input_rate,'output_usd_per_million':settings.output_rate,'source':settings.pricing_source},
                'what_is_sent':'Approved goal, bounded public text passages, public URLs, typed questions and candidate descriptions go to TypeSafe. When enabled, the selected text provider also receives bounded research goals and public evidence for proposals and cited synthesis. Screenshots, environment variables and private analytics do not.',
                'connection':connection, 'profile':store.setting('profile',Profile().model_dump()),
                'research_defaults':research_defaults,'operator_contact_configured':bool(settings.contact_url)}
    @app.get('/api/settings')
    async def get_settings(): return capabilities()
    @app.post('/api/settings/reload')
    async def reload_settings():
        fresh=Settings.load()
        text_fields=('openai_key','gemini_key','anthropic_key','openrouter_key','text_model_key','text_model_base_url',
                     'text_provider','text_model','text_input_rate','text_output_rate')
        if any(getattr(settings,key)!=getattr(fresh,key) for key in text_fields) and store.one("SELECT id FROM missions WHERE status IN ('running','pausing') LIMIT 1"):
            raise HTTPException(409,'Pause active investigations before changing text provider credentials or settings.')
        if settings.key!=fresh.key: store.set_setting('connection',{'success':False,'message':'Credentials changed; test the Jev connection to verify them.'})
        settings.key=fresh.key; settings.brave_key=fresh.brave_key
        for key in text_fields:setattr(settings,key,getattr(fresh,key))
        return capabilities()
    @app.put('/api/settings/text-model')
    async def put_text_model(value:TextModelSettings):
        if store.one("SELECT id FROM missions WHERE status IN ('running','pausing') LIMIT 1"):
            raise HTTPException(409,'Pause active investigations before changing the text provider or its allowances.')
        try:text_model.save(value)
        except TextModelError as error:raise HTTPException(422,str(error)) from None
        return capabilities()
    @app.put('/api/settings/spend-limits')
    async def put_spend_limits(value:SpendLimits):
        if store.one("SELECT id FROM missions WHERE status IN ('running','pausing') LIMIT 1"):
            raise HTTPException(409,'Pause active investigations before changing spend limits.')
        defaults=ResearchDefaults.model_validate(store.setting('research_defaults',ResearchDefaults().model_dump())).model_dump()
        defaults['limits']['usd']=value.jev_usd
        # Preserve remembered models, prices and provider credentials configuration.
        text_saved=store.setting('text_model',{})
        text_saved['usd']=value.text_usd
        with store.lock:
            store.execute('BEGIN IMMEDIATE')
            try:
                store.set_setting('research_defaults',defaults)
                store.set_setting('text_model',text_saved)
                store.execute('COMMIT')
            except BaseException:
                store.execute('ROLLBACK')
                raise
        return capabilities()
    @app.post('/api/text-connection-test')
    async def text_connection_test():
        if not text_model.enabled:
            raise HTTPException(409,'Select a text provider and model in Settings, add its API key to the server .env, then reload keys.')
        p=Plan(goal='Text model JSON connection test',limits={'max_calls':1,'max_pages':1}).model_dump()
        mid=make_mission(p,'system');store.mutate(mid,'text.test_started',{},status='running')
        try:
            call=await text_model.generate(mid,purpose='Text connection test',instructions='Return exactly {"status":"connected"}.',
                state={'test':'JSON connection'},schema={'type':'object','properties':{'status':{'const':'connected'}},'required':['status'],'additionalProperties':False},
                max_output_tokens=1024 if text_model.config()['provider']=='gemini' else 128)
            if call['output']!={'status':'connected'}:raise TextModelError('The text provider did not return the requested test object')
            result={'success':True,'tested_at':now(),'provider':call['provider'],'model':call['model'],'latency_ms':call['latency_ms'],'usage':call['usage']}
        except (TextModelError,TextBudgetError) as error:
            result={'success':False,'tested_at':now(),'error':str(error)}
        store.mutate(mid,'text.test_completed',{'success':result['success']},status='complete' if result['success'] else 'partial')
        store.set_setting('text_connection',result)
        return result
    @app.put('/api/settings')
    async def put_settings(profile:Profile): store.set_setting('profile',profile.model_dump()); return capabilities()
    @app.put('/api/settings/research-defaults')
    async def put_research_defaults(defaults:ResearchDefaults):
        if defaults.lens_id!='auto' and not any(lens['id']==defaults.lens_id for lens in lenses()):raise HTTPException(422,'Unknown research lens')
        value=defaults.model_dump(); value['providers']=list(dict.fromkeys(value['providers']))
        store.set_setting('research_defaults',value)
        return capabilities()
    @app.post('/api/connection-test')
    async def connection_test():
        fresh=Settings.load(); settings.key=fresh.key; settings.brave_key=fresh.brave_key
        if not settings.key: raise HTTPException(409,'Add TYPESAFE_API_KEY to the project-local .env, then test again.')
        p=Plan(goal='Public-text connection test',limits={'max_calls':1,'max_pages':1}).model_dump(); mid=make_mission(p,'system')
        try:
            async with runner.jev.client() as c: models=(await c.models.list()).model_dump(mode='json')
            d=await runner.jev.ask(mid,{'public_text':'Python is a programming language.','source':'https://www.python.org/'},
                 {'category':Choice(instructions='What is the described category?',criteria={'language':'Programming language','hardware':'Hardware device','unknown':'Unknown'})},'Connection test',cache=False)
            result={'success':True,'tested_at':now(),'model':d['model'],'latency_ms':d['latency_ms'],'usage':d['usage'],'available_models':models}
        except Exception as e: result={'success':False,'tested_at':now(),'error':type(e).__name__}
        store.set_setting('connection',result); return result
    @app.get('/api/action-library')
    async def action_library(): return store.setting('action_library',DEFAULT_ACTIONS)
    @app.put('/api/action-library')
    async def save_action_library(items:list[ActionTemplate]):
        if not 1<=len(items)<=12 or len({i.id for i in items})!=len(items): raise HTTPException(422,'Provide 1–12 templates with unique IDs')
        store.set_setting('action_library',[item.model_dump() for item in items]); return items
    @app.get('/api/lenses')
    async def get_lenses(): return lenses()
    @app.post('/api/lenses')
    async def save_lens(lens:Lens):
        items=lenses(); previous=next((l for l in items if l['id']==lens.id),None)
        if previous: lens.version=previous['version']+1
        store.set_setting('lens_history:'+lens.id+':'+str(lens.version),lens.model_dump())
        store.set_setting('lenses',[x for x in items if x['id']!=lens.id]+[lens.model_dump()]); return lens
    def prepare(plan):
        p=plan.model_dump(); p['seeds']=[validate_url(u) for u in p['seeds']]
        if p['reference']: p['reference']=validate_url(p['reference']); p['seeds']=list(dict.fromkeys([p['reference']]+p['seeds']))
        if p['lens_id']=='auto':p['lens_id']='open' if p['criteria'] else suggested_lens(p['goal'])[0]
        if not p['criteria']:
            chosen=next((l for l in lenses() if l['id']==p['lens_id']),None)
            if not chosen: raise HTTPException(422,'Unknown research lens')
            p['criteria']=chosen['criteria']; p['lens_version']=chosen['version']
        if not p['queries']: p['queries']=queries_for(p)
        return p
    @app.post('/api/plan')
    async def preview_plan(plan:Plan):
        p=prepare(plan)
        caps=capabilities(); readiness=plan_readiness(p,caps)
        selected=next((lens for lens in lenses() if lens['id']==p['lens_id']),None)
        auto=plan.lens_id=='auto' and not plan.criteria
        planning={'lens':{'requested':plan.lens_id,'selected':p['lens_id'],'name':selected['name'] if selected else 'Custom questions',
                          'method':'deterministic_rules' if auto else 'explicit','reason':suggested_lens(p['goal'])[1] if auto else 'Your selected lens or supplied questions are preserved. No model call is used to prepare this plan.'}}
        if p['research_mode']=='adaptive':
            planning['research']={'method':'jev_on_start','message':'After Start, Jev selects what to investigate, the method and evidence requirements from your goal. These preview questions are provisional; no inference is performed during preview.'}
        searchable=any(provider=='wikipedia' or (provider=='brave' and caps['brave']) for provider in p['providers'])
        return {'plan':p,'capabilities':caps,'readiness':readiness,'planning':planning,'initial_actions':[{'kind':'fetch','value':u} for u in p['seeds']]+[{'kind':'search','value':q} for q in p['queries'][:p['limits']['max_queries']] if searchable],
                'coverage':'Seed-only mode: selected public URLs and allowed same-domain links; not exhaustive discovery.' if p['providers']==['seed'] else 'Search providers may fail or cover limited corpora. Result positions are provider-specific.'}
    def make_mission(p,mode='live',parent=None):
        mid=uid(); t=now()
        store.execute('INSERT INTO missions VALUES(?,?,?,?,?,?,?,?,?)',(mid,p['goal'],'draft',dumps(p),1,t,t,parent,mode))
        store.execute('INSERT INTO plans VALUES(?,?,?,?,?)',(uid(),mid,1,dumps(p),t)); store.event(mid,'mission.created',{'goal':p['goal']},mode=mode)
        return mid
    @app.post('/api/missions',response_model=MissionOut)
    async def new_mission(plan:Plan): return store.mission(make_mission(prepare(plan)))
    @app.get('/api/missions')
    async def list_missions(q:str=''):
        if len(q)>200: raise HTTPException(422,'Search too long')
        if q.strip():
            expression=' OR '.join('"'+word.replace('"','""')+'"' for word in q.split())
            rows=store.rows("SELECT m.id,m.goal,m.status,m.created_at,m.updated_at,m.parent_id,m.mode FROM missions m JOIN mission_search f ON f.mission_id=m.id WHERE mission_search MATCH ? AND m.mode!='system' ORDER BY m.created_at DESC LIMIT 100",(expression,))
        else:
            rows=store.rows("SELECT id,goal,status,created_at,updated_at,parent_id,mode FROM missions WHERE mode!='system' ORDER BY created_at DESC LIMIT 100")
        for m in rows: m['telemetry']=telemetry(store,m['id'])
        return rows
    @app.get('/api/missions/{mid}',response_model=MissionDetailOut)
    async def detail(mid:str):
        m=store.mission(mid); groups={}
        for r in store.rows('SELECT kind,payload FROM records WHERE mission_id=? ORDER BY created_at,id',(mid,)):
            groups.setdefault(r['kind'],[]).append(json.loads(r['payload']))
        events=store.events(mid)
        measured=telemetry(store,mid)
        effective=runner.effective_plan(mid)
        m={**m,'plan':{key:value for key,value in effective.items() if not key.startswith('_')}}
        outcome=mission_outcome(m,groups,events,capabilities())
        outcome['research_answer']=current_brief(store,mid,effective)
        return {**m,'records':groups,'telemetry':measured,'events':events,'opportunities':opportunities(store,mid),'cohorts':cohorts(groups.get('metric',[])),
                'corpus':corpus_summary(store,mid),'outcome':outcome,'landscape':landscape(m,groups),'jev_activity':jev_activity(m,groups,events,measured)}
    @app.put('/api/missions/{mid}/plan')
    async def revise(mid:str,plan:Plan):
        m=store.mission(mid)
        if m['status'] in ('running','pausing'): raise HTTPException(409,'Pause before revising the plan')
        p=prepare(plan); version=m['plan_version']+1
        store.execute('UPDATE missions SET plan=?,goal=?,plan_version=?,updated_at=? WHERE id=?',(dumps(p),p['goal'],version,now(),mid))
        store.execute('INSERT INTO plans VALUES(?,?,?,?,?)',(uid(),mid,version,dumps(p),now()))
        historical=[]
        for f in store.records(mid,'finding'):
            f['stale']=True; historical.append(('finding',f))
        for e in store.records(mid,'entity'):
            for field in e['fields'].values(): field['stale']=True
            historical.append(('entity',e))
        store.mutate(mid,'plan.revised',{'version':version,'previous_assessments':'Retained as historical; rerun to assess under new questions'},historical)
        return store.mission(mid)
    @app.post('/api/missions/{mid}/command')
    async def command(mid:str,cmd:Command):
        m=store.mission(mid)
        existing=store.one('SELECT * FROM commands WHERE key=?',(cmd.idempotency_key,))
        if existing:
            if existing['mission_id']!=mid or existing['action']!=cmd.action: raise HTTPException(409,'Idempotency key reused for a different command')
            return store.mission(mid)
        action=cmd.action
        if action in ('start','resume','retry'):
            if not settings.key: raise HTTPException(409,'TypeSafe key required. Open Settings and test the connection.')
            allowed={'start':('draft',),'resume':('paused',),'retry':('blocked','interrupted','partial')}
            if m['status'] not in allowed[action]: raise HTTPException(409,'Command is not valid for current mission state')
            if not m['plan']['seeds'] and not any(x in m['plan']['providers'] for x in ('brave','wikipedia')): raise HTTPException(422,'Add a public seed URL or an available search provider')
            if 'brave' in m['plan']['providers'] and not settings.brave_key: raise HTTPException(409,'Brave was allowed but its key is not configured')
            missing_sources=next((b for b in plan_readiness(m['plan'],capabilities())['blockers'] if b['code'] in ('no_sources','discovery_unavailable')),None)
            if missing_sources: raise HTTPException(422,missing_sources['message'])
            if action=='retry':
                for a in store.records(mid,'action'):
                    if a['status'] in ('running','uncertain'):
                        # Completed source assessments survive; explicit retries create a fresh action only where needed.
                        a['status']='queued'; store.mutate(mid,'action.retry_authorized',{'action_id':a['id']},[('action',a)])
            store.mutate(mid,'mission.'+action,{},status='running'); runner.launch(mid)
        elif action=='pause':
            if m['status']!='running': raise HTTPException(409,'Mission is not running')
            store.mutate(mid,'mission.pause_requested',{'policy':'Stop after bounded in-flight work settles'},status='pausing')
        elif action=='cancel':
            store.mutate(mid,'mission.cancelled',{'remote_requests':'Already accepted requests may still be billed'},status='cancelled'); await runner.stop(mid)
        store.execute('INSERT INTO commands VALUES(?,?,?)',(cmd.idempotency_key,mid,action))
        return store.mission(mid)
    @app.post('/api/missions/{mid}/steer')
    async def steer(mid:str,body:Steer):
        m=store.mission(mid); p=m['plan']
        if body.url: runner.add_action(mid,'fetch',body.url); p['seeds']=list(dict.fromkeys(p['seeds']+[validate_url(body.url)]))
        if body.query: runner.add_action(mid,'search',body.query); p['queries']=list(dict.fromkeys(p['queries']+[body.query]))[:20]
        if body.exclude: p['excluded_domains']=list(dict.fromkeys(p['excluded_domains']+[body.exclude.lower().strip()]))
        version=m['plan_version']+1
        store.execute('UPDATE missions SET plan=?,plan_version=?,updated_at=? WHERE id=?',(dumps(p),version,now(),mid))
        store.execute('INSERT INTO plans VALUES(?,?,?,?,?)',(uid(),mid,version,dumps(p),now()))
        store.mutate(mid,'plan.steered',{'version':version,'added_url':body.url,'added_query':body.query,'excluded':body.exclude})
        invalidate_research(store,mid,'The research plan changed; saved assessments need reassessment.',all_artifacts=True)
        return store.mission(mid)
    @app.post('/api/missions/{mid}/rerun')
    async def rerun(mid:str):
        m=store.mission(mid); p={**m['plan'],'freshness':'recent'}; return store.mission(make_mission(p,parent=mid))
    @app.get('/api/missions/{mid}/diff')
    async def diff(mid:str):
        m=store.mission(mid)
        if not m['parent_id']: return {'parent_id':None,'changes':[]}
        old={s['url']:s for s in store.records(m['parent_id'],'source')}; new={s['url']:s for s in store.records(mid,'source')}
        return {'parent_id':m['parent_id'],'changes':[{'url':u,'change':'new' if u not in old else 'not revisited' if u not in new else 'unchanged' if old[u]['content_hash']==new[u]['content_hash'] else 'content changed'} for u in sorted(set(old)|set(new))]}
    @app.post('/api/missions/{mid}/sources/{sid}/render')
    async def queue_render(mid:str,sid:str):
        m=store.mission(mid); source=next((s for s in store.records(mid,'source') if s['id']==sid),None)
        if not source: raise KeyError(sid)
        p=m['plan'];p['browser']=True
        store.execute('UPDATE missions SET plan=? WHERE id=?',(dumps(p),mid))
        runner.add_action(mid,'render',source['url'],source['id'],source['depth'])
        if m['status'] not in ('running','pausing'):
            store.mutate(mid,'browser.queued',{'source_id':sid,'operation':'navigate + inspect + screenshot','requires_resume':True},status='paused')
        return {'queued':True,'message':'Read-only browser check queued. Resume the mission to capture it.'}
    @app.get('/api/approved-evidence')
    async def approved_evidence(q:str=''):
        terms=set(re.findall(r'\w{4,}',q.lower()))
        records=[]
        for row in store.rows("SELECT mission_id,payload FROM records WHERE kind='finding' ORDER BY created_at DESC LIMIT 1000"):
            f=json.loads(row['payload'])
            if f.get('review')!='approved': continue
            if terms and not terms & set(re.findall(r'\w{4,}',(f['subject']+' '+f['question']+' '+f['statement']).lower())): continue
            records.append({**f,'mission_id':row['mission_id'],'reuse_policy':'Review source date and rubric before reusing; no automatic training or inference substitution'})
        return records[:30]
    @app.post('/api/missions/{mid}/review/{rid}')
    async def review(mid:str,rid:str,body:Review):
        r=store.one('SELECT kind,payload FROM records WHERE id=? AND mission_id=?',(rid,mid))
        if not r: raise KeyError(rid)
        if r['kind'] not in ('finding','entity','source'): raise HTTPException(422,'This record cannot be reviewed')
        data=json.loads(r['payload']); previous=data.get('review'); data.update(review=body.state,note=body.note,reviewed_at=now())
        store.mutate(mid,'review.saved',{'record_id':rid,'state':body.state},[(r['kind'],data)])
        if previous!=body.state and (previous=='rejected' or body.state=='rejected'):
            source_ids=([rid] if r['kind']=='source' else data.get('source_ids',[])) if body.state=='rejected' else []
            invalidate_research(store,mid,'Evidence review changed; reassess before reusing this comparison.',source_ids=source_ids)
        return data
    @app.post('/api/missions/{mid}/imports')
    async def imports(mid:str,body:ImportRequest):
        store.mission(mid)
        try: records=parse_import(body)
        except ImportError as e: raise HTTPException(422,str(e))
        if len(store.records(mid)) + len(records)>12000: raise HTTPException(422,'Mission record limit reached; create a separate investigation')
        existing={r.get('fingerprint') for r in store.records(mid)}
        records=[(k,r) for k,r in records if r['fingerprint'] not in existing]
        store.mutate(mid,'import.completed',{'kind':body.kind,'rows':len(records),'provenance':body.provenance,'private':body.private,'allow_analysis':body.allow_analysis},records,mode='live')
        if not body.private or body.allow_analysis:
            for kind,r in records:
                if kind=='import_url': runner.add_action(mid,'fetch',r['url'])
        return {'imported':len(records),'warnings':['User-supplied, not authenticated API evidence.','Missing dimensions, suppressed rows and aggregate/detail overlap may affect comparisons. No cross-platform audience totals.','Private analytics remain local; URL analysis requires explicit permission.']}
    @app.get('/api/missions/{mid}/events')
    async def events(mid:str,request:Request,after:int=0):
        store.mission(mid)
        try: cursor=max(after,int(request.headers.get('last-event-id','0')))
        except ValueError: raise HTTPException(422,'Invalid event cursor')
        async def stream():
            nonlocal cursor
            while not await request.is_disconnected():
                for event in store.events(mid,cursor):
                    cursor=event['seq']; yield f'id: {cursor}\nevent: radar\ndata: {dumps(event)}\n\n'
                yield ': heartbeat\n\n'; await asyncio.sleep(.65)
        return StreamingResponse(stream(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no'})
    @app.get('/api/missions/{mid}/export/{fmt}')
    async def export(mid:str,fmt:str):
        if fmt not in ('json','csv','md','html','metrics','matrix'): raise HTTPException(404)
        body,mime=report(store,mid,fmt)
        suffix=fmt+'.csv' if fmt in ('metrics','matrix') else fmt
        return Response(body,media_type=mime,headers={'Content-Disposition':f'attachment; filename="radar-{mid[:8]}.{suffix}"'})
    @app.get('/api/missions/{mid}/artifacts/{aid}')
    async def artifact(mid:str,aid:str):
        if not re.fullmatch('[a-f0-9]{32}',aid) or not any(s.get('artifact_id')==aid for s in store.records(mid,'source')): raise HTTPException(404)
        return FileResponse(settings.data_dir/'artifacts'/f'{aid}.png',media_type='image/png')
    def delete_mission(mid):
        for s in store.records(mid,'source'):
            aid=s.get('artifact_id')
            if aid and re.fullmatch('[a-f0-9]{32}',aid): (settings.data_dir/'artifacts'/f'{aid}.png').unlink(missing_ok=True)
        store.execute('DELETE FROM missions WHERE id=?',(mid,))
        # Cached snippets may originate in this mission; purge all shared caches conservatively.
        store.execute('DELETE FROM cache')
    @app.delete('/api/missions/{mid}')
    async def delete(mid:str):
        store.mission(mid); await runner.stop(mid); delete_mission(mid); return {'deleted':mid}
    @app.post('/api/retention')
    async def retention():
        days=store.setting('profile',Profile().model_dump())['retention_days']; threshold=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
        old=store.rows("SELECT id FROM missions WHERE updated_at<? AND status NOT IN ('running','pausing')",(threshold,))
        for m in old: delete_mission(m['id'])
        return {'deleted':len(old),'retention_days':days}
    dist=ROOT/'frontend/dist'
    if dist.exists():
        app.mount('/assets',StaticFiles(directory=dist/'assets'),name='assets')
        @app.get('/')
        async def index(): return FileResponse(dist/'index.html')
    else:
        @app.get('/')
        async def index(): return JSONResponse({'message':'Build frontend: npm --prefix frontend run build'})
    return app
