"""Conservative Schema.org InteractionCounter parsing; publisher assertions only."""
from urllib.parse import urlsplit
from datetime import datetime
from .security import validate_url
from .storage import uid,fingerprint

ACTIONS={'ViewAction':'views','WatchAction':'views','ReadAction':'reads','LikeAction':'likes','ShareAction':'shares','CommentAction':'comments','ListenAction':'listens','DownloadAction':'downloads'}

def claimed_date(value):
    if not isinstance(value,str):return None
    try:return datetime.fromisoformat(value.replace('Z','+00:00')).isoformat()
    except ValueError:return None

def public_metrics(source):
    result=[];seen=set()
    def visit(obj,path,depth):
        if depth>8:return
        if isinstance(obj,list):
            for i,item in enumerate(obj[:50]):visit(item,f'{path}[{i}]',depth+1)
        elif isinstance(obj,dict):
            scope=obj.get('url') or obj.get('mainEntityOfPage')
            if isinstance(scope,dict):scope=scope.get('@id') or scope.get('url')
            try: matches=isinstance(scope,str) and validate_url(scope)==validate_url(source['url'])
            except ValueError:matches=False
            # Do not attach an unrelated embedded video's counts to the containing page.
            if matches and 'interactionStatistic' in obj:
                counters=obj['interactionStatistic'];counters=counters if isinstance(counters,list) else [counters]
                for i,c in enumerate(counters[:20]):
                    if not isinstance(c,dict):continue
                    action=c.get('interactionType');action=action.get('@type') if isinstance(action,dict) else action
                    if not isinstance(action,str):continue
                    metric=ACTIONS.get(action.rsplit('/',1)[-1]);value=c.get('userInteractionCount')
                    if isinstance(value,str) and value.isdigit():value=int(value)
                    if not metric or isinstance(value,bool) or not isinstance(value,int) or not 0<=value<=10**15:continue
                    start=claimed_date(c.get('startTime'));end=claimed_date(c.get('endTime'))
                    item={'source_id':source['id'],'url':source['url'],'provider':urlsplit(source['url']).hostname,'metric':metric,'value':value,'unit':metric,
                          'kind':'asserted','provenance':f'Publisher JSON-LD at {path}.interactionStatistic[{i}].userInteractionCount',
                          'measured_at':source['retrieved_at'],'measurement_time_basis':'Observed publisher counter at retrieval; underlying counting period may be unknown',
                          'window_start':start,'window_end':end,'scope':'Explicitly matched page URL','country':None,'device':None,'query':None,
                          'language':source['language'],'format':None,'topic':None,'private':False,'allow_analysis':True}
                    key=fingerprint(item)
                    if key not in seen:result.append({**item,'id':uid(),'fingerprint':key});seen.add(key)
            for key,value in list(obj.items())[:100]:
                if key!='interactionStatistic':visit(value,path+'.'+key,depth+1)
    visit(source.get('structured_data',[]),'structured_data',0)
    return result
