"""Search interfaces: seed crawl, permitted MediaWiki API, optional Brave API."""
import asyncio,time,re
from urllib.parse import quote
import httpx
from bs4 import BeautifulSoup
from .storage import now,uid
from .security import validate_url
from .video import is_video_url

class SearchError(ValueError): pass

class Search:
    def __init__(self,settings): self.settings=settings; self.lock=asyncio.Lock(); self.last=0
    async def videos(self,query,region,language):
        """Read individual video records from Brave; never substitute web articles.

        Response fields follow the official Video Search API. A result is an
        observation from the search index, not a page fetch or a watched video.
        """
        start=time.perf_counter()
        if not self.settings.brave_key: raise SearchError('Brave Search key not configured for video discovery')
        endpoint='https://api.search.brave.com/res/v1/videos/search'
        params={'q':query,'count':8,'search_lang':language.split('-')[0],'country':'ALL'}
        if re.fullmatch('[A-Za-z]{2}',region): params['country']=region.upper()
        async with self.lock:
            wait=1-(time.monotonic()-self.last)
            if wait>0: await asyncio.sleep(wait)
            self.last=time.monotonic()
            async with httpx.AsyncClient(timeout=20,follow_redirects=False,trust_env=False,headers={'User-Agent':self.settings.user_agent}) as client:
                try:
                    response=await client.get(endpoint,params=params,headers={'X-Subscription-Token':self.settings.brave_key})
                except httpx.HTTPError:
                    raise SearchError('Brave video search connection failed; no retries') from None
                if response.status_code!=200:
                    raise SearchError(f'Brave video search HTTP {response.status_code}; provider stopped, no retries')
                try: data=response.json()
                except ValueError: raise SearchError('Brave video search returned invalid JSON; no retries') from None
        if not isinstance(data,dict) or not isinstance(data.get('results'),list):
            raise SearchError('Brave video search returned no valid result list; no retries')
        results=[]; skipped=0
        for position,item in enumerate(data['results'][:8],1):
            if not isinstance(item,dict) or not isinstance(item.get('url'),str):
                skipped+=1; continue
            try: url=validate_url(item['url'])
            except ValueError: skipped+=1; continue
            if not is_video_url(url): skipped+=1; continue
            results.append({'id':uid(),'position':position,'url':url,'title':BeautifulSoup(str(item.get('title') or ''),'lxml').get_text(),
                            'snippet':BeautifulSoup(str(item.get('description') or ''),'lxml').get_text(),
                            'source_kind':'video','video':item.get('video') if isinstance(item.get('video'),dict) else {},
                            'page_age':item.get('page_age'),'age':item.get('age'),'page_fetched':item.get('page_fetched'),
                            'fetched_content_timestamp':item.get('fetched_content_timestamp'),
                            'thumbnail':item.get('thumbnail') if isinstance(item.get('thumbnail'),dict) else {},
                            'meta_url':item.get('meta_url') if isinstance(item.get('meta_url'),dict) else {}})
        return {'id':uid(),'query':query,'provider':'brave','search_kind':'video','region_requested':region,'language':language,
                'timestamp':now(),'results':results,'latency_ms':round((time.perf_counter()-start)*1000,2),'endpoint':endpoint,
                'scope':'Brave video index metadata for recognized individual video URLs; index position is not popularity. Original videos, frames and audio were not fetched.',
                'skipped_results':skipped,'skipped_reason':'Malformed, unsafe or unrecognized individual-video URL; articles and listings are not video evidence',
                'estimated_usd':None,'pricing_provenance':'Account plan unverified'}
    async def query(self,query,provider,region,language):
        start=time.perf_counter()
        async with self.lock:
            wait=1-(time.monotonic()-self.last)
            if wait>0: await asyncio.sleep(wait)
            self.last=time.monotonic()
            async with httpx.AsyncClient(timeout=20,follow_redirects=False,trust_env=False,headers={'User-Agent':self.settings.user_agent}) as client:
                if provider=='brave':
                    if not self.settings.brave_key: raise SearchError('Brave Search key not configured')
                    params={'q':query,'count':8,'search_lang':language.split('-')[0]}
                    if re.fullmatch('[A-Za-z]{2}',region): params['country']=region.upper()
                    r=await client.get('https://api.search.brave.com/res/v1/web/search',params=params,headers={'X-Subscription-Token':self.settings.brave_key})
                    if r.status_code!=200: raise SearchError(f'Brave HTTP {r.status_code}; provider stopped, no retries')
                    items=r.json().get('web',{}).get('results',[])
                    results=[{'url':x['url'],'title':x.get('title',''),'snippet':BeautifulSoup(x.get('description',''),'lxml').get_text()} for x in items]
                    scope='Brave index position, not Google rank; country applied only for a two-letter code'
                elif provider=='wikipedia':
                    lang=language.split('-')[0]
                    if lang not in ('en','nl','fr','de','es','it','pt'): raise SearchError('Wikipedia language not supported in this adapter')
                    endpoint=f'https://{lang}.wikipedia.org/w/api.php'
                    r=await client.get(endpoint,params={'action':'query','list':'search','srsearch':query,'srlimit':8,'format':'json','maxlag':5})
                    if r.status_code!=200: raise SearchError(f'Wikipedia HTTP {r.status_code}; provider stopped, no retries')
                    data=r.json()
                    if 'error' in data: raise SearchError('Wikipedia API unavailable or maxlag; provider stopped')
                    results=[{'url':f'https://{lang}.wikipedia.org/wiki/'+quote(x['title'].replace(' ','_')),'title':x['title'],'snippet':BeautifulSoup(x.get('snippet',''),'lxml').get_text()} for x in data.get('query',{}).get('search',[])]
                    scope='Wikipedia corpus only; no geographic filter; not general-web discovery or Google rank'
                else: raise SearchError('Unsupported search provider')
        for i,item in enumerate(results):
            item.update(id=uid(),position=i+1,url=validate_url(item['url']))
        return {'id':uid(),'query':query,'provider':provider,'region_requested':region,'language':language,'timestamp':now(),
                'results':results,'scope':scope,'latency_ms':round((time.perf_counter()-start)*1000,2),
                'estimated_usd':None if provider=='brave' else 0,'pricing_provenance':'Account plan unverified' if provider=='brave' else 'Public MediaWiki API; usage limits apply'}

def queries_for(plan):
    goal=plan['goal'].strip()
    stem=re.split(r'[.!?](?=\s|$)|\b(?:Show|Compare|Include|Distinguish)\b',goal,flags=re.I)[0].strip()
    if not stem:stem=re.split(r'[.!?](?=\s|$)',goal)[0]
    stem=re.sub(r'^(?:find|discover|identify|research|investigate|compare)\s+','',stem,flags=re.I)[:160]
    phrases=[stem]
    # Language and region are independent; no geographic assumption from language.
    lens=plan.get('lens_id','open')
    templates={'landscape':{'en':['alternatives','pricing capabilities','evidence limitations'],'nl':['alternatieven','prijzen mogelijkheden','bewijs beperkingen'],'fr':['alternatives','prix fonctionnalités','preuves limites'],'de':['Alternativen','Preise Funktionen','Belege Einschränkungen']},
               'content':{'en':['useful content examples','reader questions methods','evidence limitations'],'nl':['bruikbare inhoud voorbeelden','vragen methoden','bewijs beperkingen'],'fr':['contenu utile exemples','questions méthodes','preuves limites'],'de':['nützliche Inhalte Beispiele','Fragen Methoden','Belege Einschränkungen']},
               'campaign':{'en':['campaign examples','distribution engagement evidence','measurement limitations'],'nl':['campagne voorbeelden','distributie bereik bewijs','meetbeperkingen'],'fr':['exemples campagnes','distribution engagement preuves','limites mesure'],'de':['Kampagnen Beispiele','Verbreitung Belege','Messgrenzen']},
               'open':{'en':['implementation documentation','supporting evidence methods','known limitations'],'nl':['implementatie documentatie','bewijs methoden','bekende beperkingen'],'fr':['implémentation documentation','preuves méthodes','limites connues'],'de':['Implementierung Dokumentation','Belege Methoden','bekannte Grenzen']}}
    localized=templates.get(lens,templates['open'])
    for suffix in localized.get(plan['language'].split('-')[0],localized['en']):
        phrases.append(' '.join(x for x in (stem,suffix,plan.get('region','')) if x))
    maximum=plan['limits']['max_queries']
    # Leave one slot for a source-derived query, without increasing the budget.
    initial=maximum-1 if maximum>2 else maximum
    return list(dict.fromkeys(phrases))[:initial]


def source_query(phrase,plan):
    """Jev selects existing text; code turns those words into a bounded query."""
    words=re.findall(r"[\w-]+",phrase)
    stop={'a','an','the','our','your','we','you','and','or','for','with','one','to','of','in','is','are','on','by','that','this','it','from'}
    terms=[word for word in words if word.lower() not in stop][:10]
    if not terms:return ''
    location=plan.get('region','')
    if not location:
        # Reuse explicit geographic words from the user's goal; no geolocation
        # or inference from the selected interface language.
        location=' '.join(re.findall(r'\b(?:Belgian|Belgium|Belgische|België|Belgique|French|France|Dutch|Netherlands|German|Germany|European|Europe)\b',plan['goal'],re.I))
    return ' '.join(x for x in (' '.join(terms),location,'alternatives') if x)[:240]
