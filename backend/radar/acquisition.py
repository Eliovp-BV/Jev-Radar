import asyncio, time, hashlib, json, re, zlib
from itertools import chain
from urllib.parse import urlsplit,urljoin
from urllib.robotparser import RobotFileParser
from datetime import datetime
import aiohttp
from bs4 import BeautifulSoup
from defusedxml.ElementTree import fromstring
from .security import validate_url, PublicResolver, PolicyError
from .storage import now

AGENT='JevRadarBot/0.1 (bounded single-user public research)'
MAX_BYTES=2_000_000

async def bounded_body(response,limit):
    encoding=response.headers.get('Content-Encoding','identity').lower()
    if encoding not in ('identity','','gzip','deflate'): raise PolicyError('Unsupported compression; refusing unbounded decompression')
    decoder=zlib.decompressobj(16+zlib.MAX_WBITS if encoding=='gzip' else zlib.MAX_WBITS) if encoding in ('gzip','deflate') else None
    body=bytearray();wire=0
    try:
        async for chunk in response.content.iter_chunked(65536):
            wire+=len(chunk)
            if wire>limit: raise PolicyError('Compressed response exceeds byte limit')
            decoded=decoder.decompress(chunk,limit-len(body)+1) if decoder else chunk
            body.extend(decoded)
            if len(body)>limit or (decoder and decoder.unconsumed_tail): raise PolicyError('Decompressed response exceeds byte limit')
        if decoder:
            body.extend(decoder.flush(limit-len(body)+1))
            if len(body)>limit or not decoder.eof: raise PolicyError('Invalid or oversized compressed response')
    except zlib.error: raise PolicyError('Invalid compressed response') from None
    return bytes(body)


class Fetcher:
    def __init__(self,concurrency=4,user_agent=AGENT):
        self.user_agent=user_agent
        self.robots={}; self.locks={}; self.last={}; self.denied=set(); self.sem=asyncio.Semaphore(concurrency)
    async def raw(self,url,limit=MAX_BYTES,redirects=5):
        url=validate_url(url)
        async with self.sem:
            connector=aiohttp.TCPConnector(resolver=PublicResolver(),use_dns_cache=False,limit=4)
            async with aiohttp.ClientSession(connector=connector,trust_env=False,auto_decompress=False,
                    timeout=aiohttp.ClientTimeout(total=25),headers={'User-Agent':self.user_agent,'Accept-Encoding':'identity'}) as client:
                for _ in range(redirects+1):
                    async with client.get(url,allow_redirects=False) as r:
                        if r.status in (301,302,303,307,308):
                            url=validate_url(urljoin(url,r.headers.get('Location',''))); continue
                        data=await bounded_body(r,limit)
                        return {'url':url,'status':r.status,'headers':dict(r.headers),'body':data}
                raise PolicyError('Redirect limit reached')
    async def permitted(self,url):
        url=validate_url(url); p=urlsplit(url); origin=f'{p.scheme}://{p.netloc}'
        if origin in self.denied: raise PolicyError('Origin stopped after robots, rate or access denial')
        lock=self.locks.setdefault(origin,asyncio.Lock())
        async with lock:
            if origin in self.denied: raise PolicyError('Origin stopped after robots, rate or access denial')
            if origin not in self.robots:
                r=await self.raw(origin+'/robots.txt',limit=256000)
                if r['status']==404: text='User-agent: *\nAllow: /'
                elif r['status']!=200:
                    self.denied.add(origin)
                    raise PolicyError(f'Robots unavailable (HTTP {r["status"]}); stopped this origin')
                else: text=r['body'].decode('utf-8','replace')
                parser=RobotFileParser(); parser.parse(text.splitlines()); self.robots[origin]=parser
            robot=self.robots[origin]
            if not robot.can_fetch(self.user_agent,url): raise PolicyError('robots.txt disallows this path')
            delay=max(robot.crawl_delay(self.user_agent) or 1,1)
            if delay>60: raise PolicyError('Robots crawl delay exceeds bounded task wait; origin not crawled')
            wait=delay-(time.monotonic()-self.last.get(origin,0))
            if wait>0: await asyncio.sleep(wait)
            # Another in-flight page may have denied the origin while this
            # caller waited on robots, the origin lock or the crawl delay.
            if origin in self.denied: raise PolicyError('Origin stopped after robots, rate or access denial')
            self.last[origin]=time.monotonic()
        return url
    async def get(self,url):
        # Validate each redirect destination's robots policy before requesting it.
        start=time.perf_counter(); url=validate_url(url)
        for _ in range(6):
            await self.permitted(url)
            # raw with redirects=0 is intentionally replaced with a single-hop request.
            r=await self.single(url)
            if r['status'] in (301,302,303,307,308):
                url=validate_url(urljoin(url,r['headers'].get('Location',''))); continue
            if r['status'] in (401,403,429):
                p=urlsplit(url); self.denied.add(f'{p.scheme}://{p.netloc}')
                raise PolicyError(f'Access blocked (HTTP {r["status"]}); origin stopped, no retries; Retry-After respected by stopping')
            if r['status']>=400: raise PolicyError(f'Page returned HTTP {r["status"]}')
            r['fetch_ms']=round((time.perf_counter()-start)*1000,2); r['retrieved_at']=now(); return r
        raise PolicyError('Redirect limit reached')
    async def single(self,url):
        url=validate_url(url)
        async with self.sem:
            parsed=urlsplit(url)
            if f'{parsed.scheme}://{parsed.netloc}' in self.denied:
                raise PolicyError('Origin stopped after robots, rate or access denial')
            connector=aiohttp.TCPConnector(resolver=PublicResolver(),use_dns_cache=False)
            async with aiohttp.ClientSession(connector=connector,trust_env=False,auto_decompress=False,
                    timeout=aiohttp.ClientTimeout(total=25),headers={'User-Agent':self.user_agent,'Accept-Encoding':'identity'}) as client:
                async with client.get(url,allow_redirects=False) as r:
                    body=await bounded_body(r,MAX_BYTES)
                    return {'url':url,'status':r.status,'headers':dict(r.headers),'body':body}
    async def sitemap(self,url):
        p=urlsplit(validate_url(url)); r=await self.get(f'{p.scheme}://{p.netloc}/sitemap.xml')
        root=fromstring(r['body'])
        if root.tag.endswith('sitemapindex'): return [] # no recursive sitemap expansion
        urls=[]
        for element in root.iter():
            if element.tag.endswith('}loc') and element.text:
                try: urls.append(validate_url(element.text.strip()))
                except PolicyError: continue
                if len(urls)>=50: break
        return urls

def extract(raw):
    start=time.perf_counter()
    soup=BeautifulSoup(raw['body'],'lxml')
    meta={}
    for m in soup.find_all('meta'):
        key=m.get('property') or m.get('name')
        if key and m.get('content'): meta[key.lower()]=m['content'][:1000]
    title=soup.title.get_text(' ',strip=True)[:300] if soup.title else urlsplit(raw['url']).hostname
    lang=(soup.html.get('lang','') if soup.html else '')[:30]
    canonical=soup.find('link',rel='canonical')
    canonical=canonical.get('href') if canonical else None
    structured=[]
    for tag in soup.find_all('script',type='application/ld+json')[:8]:
        try: structured.append(json.loads(tag.get_text()[:30000]))
        except (ValueError,TypeError,RecursionError): pass
    links=[]; seen=set()
    link_root=soup.find('main') or soup.find('article') or soup.body or soup
    # Embedded player URLs are observed leads, never inspected media evidence.
    from .video import is_video_url,canonical_video_url
    for frame in link_root.find_all('iframe',src=True)[:24]:
        try:
            observed=validate_url(urljoin(raw['url'],frame['src']))
            if not is_video_url(observed):continue
            url=canonical_video_url(observed)
        except ValueError:continue
        if url in seen:continue
        seen.add(url);links.append({'url':url,'observed_url':observed,'label':str(frame.get('title') or 'Embedded video reference')[:160],'provenance':'Observed iframe.src; original media not inspected'})
        if len(links)>=8:break
    for anchor in link_root.find_all('a',href=True):
        try:
            observed=validate_url(urljoin(raw['url'],anchor['href']))
            if not is_video_url(observed):continue
            url=canonical_video_url(observed)
        except ValueError:continue
        if url in seen:continue
        seen.add(url);links.append({'url':url,'observed_url':observed,'label':anchor.get_text(' ',strip=True)[:160] or 'Referenced original video','provenance':'Observed article video link; original media not inspected'})
        if len(links)>=24:break
    # Navigation menus must not crowd actual references out of the bounded list.
    for a in chain(link_root.find_all('a',href=True),soup.find_all('a',href=True)):
        try: url=validate_url(urljoin(raw['url'],a['href']))
        except ValueError: continue
        if url in seen: continue
        seen.add(url); links.append({'url':url,'label':a.get_text(' ',strip=True)[:160]})
        if len(links)>=200: break
    for tag in soup(['script','style','noscript','svg','iframe','form','nav','footer']): tag.decompose()
    main=soup.find('main') or soup.find('article') or soup.body or soup
    chunks=[]; offset=0; full=[]; truncated=False
    for tag in main.find_all(['h1','h2','h3','h4','p','li','tr','pre','blockquote']):
        if tag.find_parent(['p','li','tr','pre','blockquote']) is not None: continue
        text=re.sub(r'\s+',' ',tag.get_text(' ',strip=True))
        if not text: continue
        if sum(len(x) for x in full)+len(text)>120000:
            truncated=True; break
        if text in full[-3:]: continue
        full.append(text)
        # Split long structural blocks, preserving exact normalized source offsets.
        for part in re.findall(r'.{1,650}(?:\s|$)|.{1,650}',text):
            part=part.rstrip()
            at=text.find(part)
            chunks.append({'start':offset+at,'end':offset+at+len(part),'text':part,'tag':tag.name,'anchor':tag.get('id'),'provenance':'source_text'})
        offset+=len(text)+1
    text='\n'.join(full)
    if not text: text=main.get_text(' ',strip=True)[:120000]; chunks=[{'start':0,'end':min(len(text),650),'text':text[:650],'tag':'body','anchor':None,'provenance':'source_text'}] if text else []
    date=None; date_source=None
    for key in ('article:published_time','datepublished','date'):
        if key in meta:
            try: datetime.fromisoformat(meta[key].replace('Z','+00:00')); date=meta[key]; date_source='meta:'+key; break
            except ValueError: pass
    return {'url':raw['url'],'title':title,'text':text,'chunks':chunks,'links':links,'metadata':meta,'structured_data':structured,
            'canonical_claim':canonical,'language':lang,'source_date':date,'source_date_provenance':date_source,
            'retrieved_at':raw['retrieved_at'],'content_hash':hashlib.sha256(text.encode()).hexdigest(),'status_code':raw['status'],
            'coverage':{'method':'HTTP source text; hidden text may be present','main_container':main.name,'total_chunks':len(chunks),'analyzed_chunks':0,
                        'text_characters':len(text),'truncated':truncated or len(text)>=120000,'uninspected_links':len(links),'blocked_sections':'Login, forms, scripts and embedded content excluded'},
            'fetch_ms':raw.get('fetch_ms',0),'extraction_ms':round((time.perf_counter()-start)*1000,2),
            'indexability_declaration':meta.get('robots','No robots meta observed; actual indexation unknown')}

def select_chunks(source,goal,criteria,limit=24):
    terms=set(re.findall(r'\w{3,}',(goal+' '+' '.join(c['question'] for c in criteria)).lower()))
    scored=sorted(enumerate(source['chunks']),key=lambda x:(-len(terms & set(re.findall(r'\w{3,}',x[1]['text'].lower()))),x[0]))
    chosen={i for i,_ in scored[:max(1,limit-4)]}|set(range(min(4,len(source['chunks']))))
    return [dict(c,id=f's{i}') for i,c in enumerate(source['chunks']) if i in chosen][:limit]
