"""Video identities and exact-text metadata evidence, without media inference.

Brave fields: https://api-dashboard.search.brave.com/api-reference/videos/video_search/get
Publisher fields: https://schema.org/VideoObject
Neither adapter watches video, estimates views, or infers a cause of popularity.
"""
from copy import deepcopy
import hashlib
import json
import re
import time
from datetime import datetime
from urllib.parse import parse_qs, urlsplit
from bs4 import BeautifulSoup

from .security import validate_url
from .storage import now, uid


def canonical_video_url(url):
    """Collapse known share/player URLs to one artifact identity, not one host."""
    url=validate_url(url)
    parts=urlsplit(url); host=(parts.hostname or '').removeprefix('www.').removeprefix('m.')
    path=parts.path.rstrip('/'); video_id=None
    if host=='youtu.be': video_id=path.lstrip('/').split('/')[0]
    elif host in ('youtube.com','youtube-nocookie.com'):
        if path=='/watch': video_id=parse_qs(parts.query).get('v',[None])[0]
        elif re.match(r'^/(shorts|embed|live)/',path): video_id=path.split('/')[2]
    if video_id and re.fullmatch(r'[A-Za-z0-9_-]{6,64}',video_id): return 'https://www.youtube.com/watch?v='+video_id
    if host in ('vimeo.com','player.vimeo.com'):
        match=re.search(r'/(?:video/)?(\d+)$',path)
        if match:return 'https://vimeo.com/'+match[1]
    if host in ('tiktok.com','instagram.com','dailymotion.com','facebook.com','x.com','twitter.com'):
        # Query arguments on known individual posts are tracking/player options.
        if is_video_url(url): return 'https://'+host+path+(('?v='+parse_qs(parts.query)['v'][0]) if host=='facebook.com' and path=='/watch' and 'v' in parse_qs(parts.query) else '')
    return url


def is_video_url(url):
    """Conservative platform URL recognition excludes search/channel/blog pages."""
    try: parts=urlsplit(validate_url(url))
    except (ValueError,TypeError): return False
    host=(parts.hostname or '').removeprefix('www.').removeprefix('m.')
    path=parts.path.rstrip('/')
    if host=='youtu.be':return bool(re.fullmatch(r'/[A-Za-z0-9_-]{6,64}',path))
    if host in ('youtube.com','youtube-nocookie.com'):
        return (path=='/watch' and bool(re.fullmatch(r'[A-Za-z0-9_-]{6,64}',parse_qs(parts.query).get('v',[''])[0]))) or bool(re.fullmatch(r'/(shorts|embed|live)/[A-Za-z0-9_-]{6,64}',path))
    if host in ('vimeo.com','player.vimeo.com'): return bool(re.fullmatch(r'/(?:video/)?\d+',path))
    if host=='tiktok.com': return bool(re.fullmatch(r'/@[^/]+/video/\d+',path))
    if host=='instagram.com': return bool(re.fullmatch(r'/(?:reel|reels|tv)/[A-Za-z0-9_-]+',path))
    if host=='dailymotion.com': return bool(re.fullmatch(r'/video/[A-Za-z0-9]+',path))
    if host=='facebook.com':return bool(re.search(r'/(?:videos|reel)/\d+$',path) or path=='/watch' and parse_qs(parts.query).get('v',[''])[0].isdigit())
    if host in ('x.com','twitter.com'): return bool(re.fullmatch(r'/[^/]+/status/\d+',path))
    return False


def _string(value,maximum=12000):
    return value[:maximum] if isinstance(value,str) else None


def _count(value,allow_string=False):
    if allow_string and isinstance(value,str):
        if not re.fullmatch(r'[0-9]{1,16}',value):return None
        value=int(value)
    return value if isinstance(value,int) and not isinstance(value,bool) and 0<=value<=10**15 else None


def _safe_url(value):
    if not isinstance(value,str):return None
    try:return validate_url(value)
    except ValueError:return None


def _append(source,value,field,provenance):
    """Append observed field text; offsets always address the stored source text."""
    if value is None or value=='':return
    value=str(value)
    if source['text']:source['text']+='\n'
    offset=len(source['text']); source['text']+=value
    for start in range(0,len(value),650):
        text=value[start:start+650]
        source['chunks'].append({'start':offset+start,'end':offset+start+len(text),'text':text,
                                 'tag':'video_metadata','anchor':None,'field':field,'provenance':provenance})


def source_from_result(result,observation,action):
    """Turn one indexed video record into auditable evidence, not fetched media."""
    started=time.perf_counter(); url=validate_url(result['url'])
    if not is_video_url(url):raise ValueError('An individual video URL is required; a web article is not a video source')
    video=result.get('video') if isinstance(result.get('video'),dict) else {}
    observed_at=observation.get('timestamp') or now()
    provenance='Brave Video Search indexed metadata; original video not fetched or watched'
    thumbnail=result.get('thumbnail') if isinstance(result.get('thumbnail'),dict) else {}
    metadata={'title':_string(result.get('title'),1000),'description':_string(result.get('snippet')),
              'creator':_string(video.get('creator'),1000),'publisher':_string(video.get('publisher'),1000),
              'duration':_string(video.get('duration'),100),'views':_count(video.get('views')),
              'published_at':_string(result.get('page_age'),100),'published_at_basis':'Search-provider page age; may be publication or modification date, not verified upload date',
              'thumbnail_url':_safe_url(thumbnail.get('original')) or _safe_url(thumbnail.get('src')),
              'transcript':None,'transcript_available':False,'frames_available':False,
              'acquisition':'search_provider_metadata','provenance':provenance,'observed_at':observed_at,'provider':observation.get('provider','brave'),
              'provider_fetched_at':_string(result.get('page_fetched'),100),
              'field_provenance':{'title':'results[].title','description':'results[].description','creator':'results[].video.creator',
                                  'publisher':'results[].video.publisher','duration':'results[].video.duration','views':'results[].video.views','published_at':'results[].page_age'}}
    originals={'title':result.get('title'),'description':result.get('snippet'),'creator':video.get('creator'),
               'publisher':video.get('publisher'),'duration':video.get('duration'),'published_at':result.get('page_age')}
    clipped=[field for field,value in originals.items() if isinstance(value,str) and len(value)>len(metadata[field] or '')]
    source={'id':uid(),'url':url,'requested_url':url,'unit_id':canonical_video_url(url),'source_kind':'video',
            'title':metadata['title'] or url,'text':'','chunks':[],'links':[],
            'metadata':{'acquisition':'search_provider_metadata'},'video_metadata':metadata,'structured_data':[],
            'provider_observation':{'search_id':observation.get('id'),'result_id':result.get('id'),'position':result.get('position'),
                                    'query':observation.get('query'),'endpoint':observation.get('endpoint'),'latency_ms':observation.get('latency_ms')},
            'native_video_metadata':deepcopy(video),'canonical_claim':None,'language':observation.get('language',''),
            'source_date':metadata['published_at'],'source_date_provenance':'Brave results[].page_age; page date, not verified upload date' if metadata['published_at'] else None,
            'retrieved_at':observed_at,'status_code':None,'fetch_ms':0,'extraction_ms':0,
            'action_id':action['id'],'discovered_via':observation.get('id') or action.get('parent') or action['id'],
            'cache':False,'depth':action.get('depth',0),'mode':'live','excluded':False,
            'indexability_declaration':'Observed in Brave video index; current original-page indexability unknown',
            'coverage':{'method':provenance,'main_container':'video_search_result','analyzed_chunks':0,'truncated':bool(clipped),'truncated_fields':clipped,'uninspected_links':0,
                         'blocked_sections':'Original page, video frames, audio, transcript and comments not acquired; metadata cannot establish why a video spread'}}
    for field in ('title','description','creator','publisher','duration','views','published_at'):
        _append(source,metadata[field],field,provenance+'; '+metadata['field_provenance'][field])
    source['coverage'].update(total_chunks=len(source['chunks']),text_characters=len(source['text']))
    source['content_hash']=hashlib.sha256((source['unit_id']+'\n'+source['text']).encode()).hexdigest()
    source['extraction_ms']=round((time.perf_counter()-started)*1000,2)
    return source


def _video_objects(value,path='structured_data',depth=0):
    if depth>8:return
    if isinstance(value,list):
        for index,item in enumerate(value[:50]):yield from _video_objects(item,f'{path}[{index}]',depth+1)
    elif isinstance(value,dict):
        types=value.get('@type',[]); types=types if isinstance(types,list) else [types]
        if any(isinstance(t,str) and t.rsplit('/',1)[-1]=='VideoObject' for t in types):yield value,path
        for key,item in list(value.items())[:100]:
            if isinstance(item,(dict,list)):yield from _video_objects(item,path+'.'+key,depth+1)


def enrich_video_source(source):
    """Attach matching publisher VideoObject text to a fetched page.

    An embedded video with a different identity cannot turn a blog into that
    video's primary source. Existing text/chunks and all acquisition fields stay.
    """
    result=deepcopy(source); target=canonical_video_url(source['url']); matches=[]
    objects=list(_video_objects(source.get('structured_data',[])))[:50]
    for obj,path in objects:
        identities=[]
        for field in ('url','mainEntityOfPage','embedUrl','@id'):
            value=obj.get(field)
            if isinstance(value,dict):value=value.get('@id') or value.get('url')
            safe=_safe_url(value)
            if safe:identities.append(canonical_video_url(safe))
        if target in identities or not identities and len(objects)==1 and is_video_url(source['url']):matches.append((obj,path))
    if len(matches)!=1:return result
    obj,path=matches[0]
    def named(value):return _string(value.get('name'),1000) if isinstance(value,dict) else _string(value,1000)
    fields={'title':('name',_string(obj.get('name'),1000)),'description':('description',_string(obj.get('description'))),
            'creator':('author',named(obj.get('author') or obj.get('creator'))),'publisher':('publisher',named(obj.get('publisher'))),
            'duration':('duration',_string(obj.get('duration'),100)),'published_at':('uploadDate',_string(obj.get('uploadDate'),100)),
            'transcript':('transcript',_string(obj.get('transcript'),60000))}
    if not obj.get('author') and obj.get('creator'):fields['creator']=('creator',fields['creator'][1])
    counters=obj.get('interactionStatistic',[]); counters=counters if isinstance(counters,list) else [counters]
    views=[]
    for index,counter in enumerate(counters[:20]):
        if not isinstance(counter,dict):continue
        kind=counter.get('interactionType');kind=kind.get('@type') if isinstance(kind,dict) else kind
        value=_count(counter.get('userInteractionCount'),allow_string=True)
        if isinstance(kind,str) and kind.rsplit('/',1)[-1] in ('ViewAction','WatchAction') and value is not None:
            views.append((f'interactionStatistic[{index}].userInteractionCount',value))
    # Multiple observation periods cannot be collapsed into one current count.
    fields['views']=views[0] if len(views)==1 else ('interactionStatistic',None)
    provenance='Publisher JSON-LD metadata from fetched page; video/audio not watched'
    thumbnail=obj.get('thumbnailUrl');thumbnail=thumbnail[0] if isinstance(thumbnail,list) and thumbnail else thumbnail
    metadata={field:value for field,(_,value) in fields.items()}
    metadata.update(published_at_basis='Publisher-asserted VideoObject.uploadDate',thumbnail_url=_safe_url(thumbnail),
                    transcript_available=bool(metadata['transcript'] and metadata['transcript'].strip()),frames_available=False,acquisition='publisher_structured_metadata',
                    provenance=provenance,observed_at=source['retrieved_at'],provider=urlsplit(source['url']).hostname,provider_fetched_at=None,
                    field_provenance={field:path+'.'+key for field,(key,_) in fields.items()})
    result.update(source_kind='video',unit_id=target,video_metadata=metadata)
    result.setdefault('text','');result.setdefault('chunks',[])
    for field,(key,value) in fields.items():_append(result,value,field,provenance+'; '+path+'.'+key)
    if metadata['title']:result['title']=metadata['title']
    if metadata['published_at']:
        result.update(source_date=metadata['published_at'],source_date_provenance=path+'.uploadDate (publisher assertion)')
    result['content_hash']=hashlib.sha256(result['text'].encode()).hexdigest()
    clipped=[field for field,(key,value) in fields.items() if isinstance(obj.get(key),str) and len(obj[key])>len(value or '')]
    result.setdefault('coverage',{}).update(method=source.get('coverage',{}).get('method','HTTP source text')+'; matching VideoObject metadata',
                                         total_chunks=len(result['chunks']),text_characters=len(result['text']),
                                         truncated=bool(source.get('coverage',{}).get('truncated') or clipped),video_truncated_fields=clipped,
                                         video_frames=False,video_audio=False,video_transcript=metadata['transcript_available'],
                                         video_limitations='Only fetched page text and publisher metadata inspected; no frame/audio analysis or demonstrated causal attribution')
    return result


MAX_YOUTUBE_HTML=2_000_000
MAX_PLAYER_LITERAL=1_000_000
_PLAYER_ASSIGNMENT=re.compile(r'''(?:^|[;\n])\s*(?:(?:var|let|const)\s+ytInitialPlayerResponse|ytInitialPlayerResponse|window\.ytInitialPlayerResponse|window\["ytInitialPlayerResponse"\]|window\['ytInitialPlayerResponse'\])\s*=\s*(\{)''')


def enrich_youtube_source(raw,source,requested_url=None):
    """Read only a literal JSON object in already-permitted YouTube HTML.

    No script execution, player calls, media requests or caption requests occur.
    Discard player internals immediately; retain only public descriptive fields.
    """
    started=time.perf_counter()
    try:target=canonical_video_url(requested_url or source['url'])
    except ValueError:return source
    parsed=urlsplit(target)
    if parsed.hostname!='www.youtube.com' or parsed.path!='/watch':return source
    video_id=parse_qs(parsed.query).get('v',[''])[0]
    result=deepcopy(source)
    def finish(status):
        result.setdefault('coverage',{})['video_metadata_status']=status
        result['extraction_ms']=round(float(result.get('extraction_ms') or 0)+(time.perf_counter()-started)*1000,2)
        return result
    try:
        if canonical_video_url(raw['url'])!=target or canonical_video_url(source['url'])!=target:return finish('identity_mismatch')
    except (ValueError,KeyError):return finish('identity_mismatch')
    body=raw.get('body',b'')
    if not isinstance(body,(bytes,str)):return finish('unavailable')
    if len(body)>MAX_YOUTUBE_HTML:return finish('oversized')
    soup=BeautifulSoup(body,'lxml');matches=[];status='unavailable';decoder=json.JSONDecoder()
    for script in soup.find_all('script')[:64]:
        text=script.string or script.get_text()
        if 'ytInitialPlayerResponse' not in text:continue
        if len(text)>MAX_PLAYER_LITERAL:status='oversized';continue
        for assignment in list(_PLAYER_ASSIGNMENT.finditer(text))[:8]:
            try:
                player,end=decoder.raw_decode(text,assignment.start(1))
            except (ValueError,RecursionError):status='malformed';continue
            remainder=text[end:].lstrip()
            if not isinstance(player,dict) or remainder and not remainder.startswith(';'):
                status='nonliteral';continue
            details=player.get('videoDetails')
            if not isinstance(details,dict) or details.get('videoId')!=video_id:
                status='identity_mismatch';continue
            micro=player.get('microformat',{})
            micro=micro.get('playerMicroformatRenderer',{}) if isinstance(micro,dict) else {}
            # Copy no full player object, URLs, tracking data or credentials.
            matches.append((_fields_youtube(details),_fields_youtube(micro,('publishDate','uploadDate'))))
    if len(matches)!=1:return finish('ambiguous' if len(matches)>1 else status)
    details,micro=matches[0]
    views=_count(details.get('viewCount'),allow_string=True)
    seconds=_count(details.get('lengthSeconds'),allow_string=True)
    date=None;date_field=None
    for field in ('uploadDate','publishDate'):
        value=micro.get(field)
        if not isinstance(value,str) or len(value)>100:continue
        try:datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError:continue
        date=value;date_field=field;break
    provenance='YouTube publisher metadata from fetched page; video/audio not watched'
    previous=result.get('video_metadata',{}) if result.get('source_kind')=='video' and result.get('unit_id')==target else {}
    transcript=previous.get('transcript') if previous.get('transcript_available') and isinstance(previous.get('transcript'),str) else None
    field_paths={'title':'ytInitialPlayerResponse.videoDetails.title','description':'ytInitialPlayerResponse.videoDetails.shortDescription',
                 'creator':'ytInitialPlayerResponse.videoDetails.author','views':'ytInitialPlayerResponse.videoDetails.viewCount',
                 'duration':'ytInitialPlayerResponse.videoDetails.lengthSeconds'}
    if date_field:field_paths['published_at']='ytInitialPlayerResponse.microformat.playerMicroformatRenderer.'+date_field
    if transcript:field_paths['transcript']=previous.get('field_provenance',{}).get('transcript','Previously extracted matching publisher transcript')
    metadata={'title':_string(details.get('title'),1000),'description':_string(details.get('shortDescription')),
              'creator':_string(details.get('author'),1000),'publisher':'YouTube','duration':f'{seconds} seconds' if seconds is not None else None,
              'duration_seconds':seconds,'views':views,'published_at':date,
              'published_at_basis':'Publisher player metadata '+date_field+' (asserted)' if date_field else 'No publisher upload/publication date observed',
              'thumbnail_url':previous.get('thumbnail_url'),'transcript':transcript,'transcript_available':bool(transcript),'frames_available':False,
              'acquisition':'publisher_player_metadata','provenance':provenance,'observed_at':source['retrieved_at'],
              'provider':'youtube.com','provider_fetched_at':None,'field_provenance':field_paths}
    result.update(source_kind='video',unit_id=target,video_metadata=metadata)
    result.setdefault('text','');result.setdefault('chunks',[])
    first_new_chunk=len(result['chunks'])
    values={'title':metadata['title'],'description':metadata['description'],'creator':metadata['creator'],
            'views':details.get('viewCount') if views is not None else None,
            'duration':details.get('lengthSeconds') if seconds is not None else None,'published_at':date}
    for field,value in values.items():
        if field in field_paths:_append(result,value,field,provenance+'; '+field_paths[field])
    # Use only literal links in retained publisher text. No player/streaming
    # objects or generated URLs become navigation candidates.
    description=metadata['description'] or ''
    description_chunk=next((chunk for chunk in result['chunks'][first_new_chunk:] if chunk.get('field')=='description'),None)
    links=result.setdefault('links',[]);seen={link.get('url') for link in links};added=0
    for match in re.finditer(r'https?://[^\s<>"\']+',description):
        observed=match[0].rstrip('.,!?;:)')
        url=_safe_url(observed)
        if not url or not is_video_url(url) or url in seen or canonical_video_url(url)==target:continue
        link={'url':url,'label':'Video link in publisher description','provenance':'ytInitialPlayerResponse.videoDetails.shortDescription; observed URL in fetched publisher metadata'}
        if description_chunk:link.update(start=description_chunk['start']+match.start(),end=description_chunk['start']+match.start()+len(observed))
        links.append(link);seen.add(url);added+=1
        if added>=8:break
    if metadata['title']:result['title']=metadata['title']
    if date:result.update(source_date=date,source_date_provenance=field_paths['published_at']+' (publisher assertion)')
    clipped=[field for field,key in (('title','title'),('description','shortDescription'),('creator','author'))
             if isinstance(details.get(key),str) and len(details[key])>len(metadata[field] or '')]
    result['content_hash']=hashlib.sha256(result['text'].encode()).hexdigest()
    result.setdefault('coverage',{}).update(method=source.get('coverage',{}).get('method','HTTP source text')+'; matching YouTube publisher player metadata',
                                         total_chunks=len(result['chunks']),text_characters=len(result['text']),
                                         uninspected_links=len(links),
                                         truncated=bool(source.get('coverage',{}).get('truncated') or clipped),video_truncated_fields=clipped,
                                         video_frames=False,video_audio=False,video_transcript=metadata['transcript_available'],
                                         video_limitations='Publisher descriptive metadata only; video/audio not watched. No caption endpoint or media download was requested.')
    return finish('matched_publisher_metadata')


def _fields_youtube(record,keys=('videoId','title','author','shortDescription','viewCount','lengthSeconds')):
    return {key:record[key] for key in keys if key in record} if isinstance(record,dict) else {}
