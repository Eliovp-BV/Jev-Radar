import asyncio, logging, time, math, json, sqlite3
from pathlib import Path
import httpx2
from contextlib import contextmanager
from typesafe_sdk import AsyncTypeSafeClient,Choice,Score,Noul,RetryPolicy
from .storage import now,uid,dumps,fingerprint
from .config import ROOT

logging.getLogger('typesafe_sdk').disabled=True
logging.getLogger('httpx2').setLevel(logging.WARNING)

class BudgetError(ValueError): pass
class DecisionError(ValueError): pass

def validate_answer(questions,result):
    if set(result['answers'])!=set(questions): raise DecisionError('Response question IDs differ from request')
    if not result.get('model'): raise DecisionError('Resolved model missing')
    for k,q in questions.items():
        a=result['answers'][k]
        if a.get('type')!=q.type: raise DecisionError('Answer type mismatch')
        if q.type=='choice':
            if a.get('choice') not in q.criteria or set(a.get('probabilities',{}))!=set(q.criteria): raise DecisionError('Unknown candidate ID')
        if q.type in ('choice','score'):
            probs=list(a.get('probabilities',{}).values())
            if not probs or any(not math.isfinite(v) or v<0 or v>1 for v in probs) or abs(sum(probs)-1)>.03: raise DecisionError('Invalid probability distribution')
            if not math.isfinite(a.get('confidence',float('nan'))) or not 0<=a['confidence']<=1: raise DecisionError('Invalid confidence')
        if q.type=='score' and set(a['probabilities'])!={str(i) for i in range(len(q.criteria))}: raise DecisionError('Invalid Score levels')
        if q.type=='score' and (not math.isfinite(a['score']) or not 0<=a['score']<=len(q.criteria)-1): raise DecisionError('Invalid score')
        if q.type=='noul' and (not math.isfinite(a['noul']) or not 0<=a['noul']<=1): raise DecisionError('Invalid Noul')
    for v in result.get('usage',{}).values():
        if v is not None and (not isinstance(v,int) or v<0): raise DecisionError('Invalid usage')

class Jev:
    def __init__(self,settings,store): self.settings=settings; self.store=store; self.sem=asyncio.Semaphore(settings.jev_concurrency); self.headroom={}
    @contextmanager
    def protect_budget(self,mid,*,calls,tokens,usd):
        """Temporarily retain final-work allowance during actual collection calls.

        These are admission limits, not paid reservations. Every actual request
        still reserves its own payload atomically, and recorded usage survives
        release, failure and cancellation.
        """
        if (type(calls) is not int or calls<0 or type(tokens) is not int or tokens<0
                or type(usd) not in (int,float) or not math.isfinite(usd) or usd<0):
            raise BudgetError('Invalid protected Jev allowance')
        with self.store.lock:
            if mid in self.headroom:raise BudgetError('Collection budget protection is already active')
            self.headroom[mid]={'calls':calls,'tokens':tokens,'usd':usd}
        try:yield
        finally:
            with self.store.lock:self.headroom.pop(mid,None)
    def client(self):
        if not self.settings.key: raise DecisionError('TYPESAFE_API_KEY is not configured in the project .env')
        # Explicit fixed endpoint, model and disabled SDK retry: no environment gateway override.
        return AsyncTypeSafeClient(api_key=self.settings.key,base_url='https://api.typesafe.ai',model=self.settings.model,
                                   retry=RetryPolicy(max_retries=0),timeout=25,
                                   http_client=httpx2.AsyncClient(timeout=25,trust_env=False,follow_redirects=False))
    def reserve(self,mid,tokens,usd):
        if type(tokens) is not int or tokens<0 or type(usd) not in (int,float) or not math.isfinite(usd) or usd<0:
            raise BudgetError('Invalid Jev cost reservation; check model pricing')
        s=self.store
        with s.lock:
            m=s.mission(mid); limits=m['plan']['limits']
            r=s.one('SELECT COUNT(*) n,COALESCE(SUM(COALESCE(actual_usd,reserved_usd)),0) usd,COALESCE(SUM(COALESCE(actual_tokens,reserved_tokens)),0) tokens FROM reservations WHERE mission_id=?',(mid,))
            if r['n']>=limits['max_calls'] or r['usd']+usd>limits['usd'] or r['tokens']+tokens>limits['max_tokens']: raise BudgetError('Jev attempt, token or estimated spend limit reached')
            protected=self.headroom.get(mid,{'calls':0,'tokens':0,'usd':0})
            if (r['n']+1+protected['calls']>limits['max_calls'] or r['tokens']+tokens+protected['tokens']>limits['max_tokens']
                    or r['usd']+usd+protected['usd']>limits['usd']):
                raise BudgetError('Collection allowance reached; final-answer and comparison allowance is protected')
            if self.settings.dev_testing or m['plan'].get('development_test'): self.reserve_dev(tokens,usd)
            id=uid(); s.execute('INSERT INTO reservations VALUES(?,?,?,?,?,?,?,?)',(id,mid,'inflight',usd,tokens,None,None,now()))
            return id
    def reserve_dev(self,tokens,usd,provider='jev'):
        if provider not in ('jev','text') or not math.isfinite(usd) or usd<0:
            raise BudgetError('Invalid development reservation')
        path=ROOT/'.runtime'/'live-testing-ledger.sqlite'; path.parent.mkdir(exist_ok=True)
        # Explicit operator authorization can raise these development-only caps.
        # Existing attempts and conservative reservations are never reset.
        limits={'max_calls':200,'jev_usd':2.,'text_usd':0.}
        config=path.with_name('development-limits.json')
        if config.exists():
            try:
                value=json.loads(config.read_text())
                if set(value)!={'max_calls','jev_usd','text_usd'} or type(value['max_calls']) is not int or not 1<=value['max_calls']<=10000:
                    raise ValueError()
                if any(type(value[k]) not in (int,float) or not math.isfinite(value[k]) or not 0<=value[k]<=1000 for k in ('jev_usd','text_usd')):
                    raise ValueError()
                limits=value
            except (OSError,ValueError,TypeError):
                raise BudgetError('Invalid development testing limits; no inference was attempted') from None
        with sqlite3.connect(path) as c:
            c.execute('CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY,at TEXT,tokens INTEGER,usd REAL)')
            c.execute('BEGIN IMMEDIATE')
            if 'provider' not in {row[1] for row in c.execute('PRAGMA table_info(attempts)')}:
                c.execute("ALTER TABLE attempts ADD COLUMN provider TEXT NOT NULL DEFAULT 'jev'")
            n=c.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]
            if config.exists():
                cost=c.execute('SELECT COALESCE(SUM(usd),0) FROM attempts WHERE provider=?',(provider,)).fetchone()[0]
                ceiling=limits[provider+'_usd']
            else:
                cost=c.execute('SELECT COALESCE(SUM(usd),0) FROM attempts').fetchone()[0]
                ceiling=2.  # Original shared development cap until explicitly changed.
            if n>=limits['max_calls'] or cost+usd>ceiling: raise BudgetError('Cumulative development testing cap reached')
            c.execute('INSERT INTO attempts(id,at,tokens,usd,provider) VALUES(?,?,?,?,?)',(uid(),now(),tokens,usd,provider))
    async def ask(self,mid,state,questions,purpose,source_id=None,cache=True):
        if not self.settings.key: raise DecisionError('TypeSafe key not configured; no inference was attempted')
        if any(type(rate) not in (int,float) or not math.isfinite(rate) or rate<0 for rate in (self.settings.input_rate,self.settings.output_rate)):
            raise DecisionError('Set finite nonnegative Jev input and output price estimates before inference')
        qdata={k:q.model_dump(mode='json',exclude_none=True) for k,q in questions.items()}
        for q in questions.values():
            if q.type=='choice' and not 2<=len(q.criteria)<=255: raise DecisionError('Choice requires 2–255 candidates')
        content={'state':state,'questions':qdata,'model':self.settings.model,'rubric_version':self.store.mission(mid)['plan_version']}
        size=len(dumps(content).encode())
        if size>50000: raise DecisionError('Bounded Jev payload exceeds 50 kB')
        # Conservative upper estimate: UTF-8 byte count + protocol overhead (not a tokenizer claim).
        reserved_tokens=size+2048
        estimated=reserved_tokens*self.settings.input_rate/1e6+4096*self.settings.output_rate/1e6
        key=fingerprint(content)
        cached=self.store.one("SELECT payload FROM cache WHERE key=? AND kind='decision'",(key,)) if cache and self.settings.model.startswith('jev-1.') else None
        id=uid(); queued=time.perf_counter()
        if cached:
            d=json.loads(cached['payload']); d.update(id=id,source_id=source_id,cache=True,cache_origin=d.get('id'),latency_ms=None,queue_ms=0,created_at=now())
            self.store.mutate(mid,'decision.cached',{'decision_id':id,'purpose':purpose},[('decision',d)],mode='cache'); return d
        async with self.sem:
            rid=self.reserve(mid,reserved_tokens,estimated)
            d={'id':id,'purpose':purpose,'source_id':source_id,'questions':qdata,'state':state,'requested_model':self.settings.model,
               'fingerprint':key,'rubric_version':content['rubric_version'],'cache':False,'created_at':now(),'queue_ms':round((time.perf_counter()-queued)*1000,2),'status':'inflight'}
            self.store.mutate(mid,'jev.started',{'decision_id':id,'purpose':purpose},[('decision',d)])
            start=time.perf_counter()
            try:
                async with self.client() as client:
                    response=await client.system_one(state=state,questions=questions,model=self.settings.model)
                result=response.model_dump(mode='json'); validate_answer(questions,result)
                elapsed=round((time.perf_counter()-start)*1000,2)
                usage=result.get('usage',{}); ti=usage.get('input_tokens'); to=usage.get('output_tokens')
                cost=(ti*self.settings.input_rate+to*self.settings.output_rate)/1e6 if ti is not None and to is not None else None
                self.store.execute('UPDATE reservations SET status=?,actual_usd=?,actual_tokens=? WHERE id=?',('complete',cost,(ti or 0)+(to or 0) if ti is not None and to is not None else None,rid))
                d.update(result,latency_ms=elapsed,status='complete',estimated_usd=cost,pricing_source=self.settings.pricing_source)
                previous=[x.get('model') for x in self.store.records(mid,'decision') if x.get('status')=='complete']
                if (previous and previous[-1]!=d['model']) or (self.settings.model.startswith('jev-1.') and d['model']!=self.settings.model):
                    self.store.mutate(mid,'model.boundary',{'previous':previous[-1] if previous else self.settings.model,'resolved':d['model'],'requires_review':True},status='pausing')
                self.store.mutate(mid,'jev.completed',{'decision_id':id,'purpose':purpose,'latency_ms':elapsed,'questions':len(questions),'model':d['model'],'usage':usage},[('decision',d)])
                if cache and d['model']==self.settings.model: self.store.execute('INSERT OR REPLACE INTO cache VALUES(?,?,?,?)',(key,'decision',now(),dumps(d)))
                return d
            except BaseException as e:
                status=getattr(e,'status_code',None)
                # Provider exception bodies may contain submitted content. Persist only a class and status.
                safe=f'{type(e).__name__}'+(f' (HTTP {status})' if status else '')
                d.update(status='error',error=safe,latency_ms=round((time.perf_counter()-start)*1000,2))
                self.store.execute("UPDATE reservations SET status='uncertain' WHERE id=?",(rid,))
                self.store.mutate(mid,'jev.error',{'decision_id':id,'error':safe,'remote_billing':'unknown; no automatic retry'},[('decision',d)])
                if isinstance(e,asyncio.CancelledError): raise
                raise DecisionError(safe) from None
