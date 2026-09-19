import csv,io,json,math
from datetime import datetime
from .storage import uid,now,fingerprint
from .security import validate_url

class ImportError(ValueError): pass

def date(value):
    try: return datetime.fromisoformat(str(value).replace('Z','+00:00')).isoformat()
    except (ValueError,TypeError): raise ImportError('Dates must be ISO 8601') from None

def number(v):
    if v is None or v=='': return None
    try:
        value=float(v)
        if not math.isfinite(value) or value<0: raise ValueError()
        return value
    except (ValueError,TypeError): raise ImportError('Metrics must be finite nonnegative numbers or blank') from None

def parse_import(request):
    if len(request.content.encode())>1_000_000: raise ImportError('Import exceeds 1 MB')
    try:
        rows=json.loads(request.content) if request.format=='json' else list(csv.DictReader(io.StringIO(request.content)))
    except (ValueError,csv.Error,RecursionError): raise ImportError('Invalid CSV or JSON') from None
    if not isinstance(rows,list) or not 1<=len(rows)<=2000 or any(not isinstance(r,dict) for r in rows): raise ImportError('Expected 1–2000 row objects')
    records=[]; seen=set(); batch=uid()
    for row in rows:
        if any(len(str(v))>5000 for v in row.values()): raise ImportError('Import field exceeds 5000 characters')
        if request.kind=='urls':
            if not row.get('url'): raise ImportError('URL import requires url column')
            item={'url':validate_url(row['url'])}; kind='import_url'
        elif request.kind=='search':
            for k in ('url','query','provider','position','measured_at','language'):
                if not row.get(k): raise ImportError(f'Search import requires {k}')
            position=number(row['position'])
            if position is None or position<1 or not position.is_integer(): raise ImportError('Position must be a positive integer')
            item={'url':validate_url(row['url']),'query':str(row['query'])[:500],'provider':str(row['provider'])[:80],'position':int(position),
                  'measured_at':date(row['measured_at']),'language':row['language'],'region':row.get('region',''),'title':row.get('title','')}; kind='search_import'
        else:
            for k in ('page','provider','measured_at','window_start','window_end'):
                if not row.get(k): raise ImportError(f'Analytics import requires {k}')
            base={'url':validate_url(row['page']),'provider':row['provider'],'measured_at':date(row['measured_at']),
                  'window_start':date(row['window_start']),'window_end':date(row['window_end']),
                  'query':row.get('query'),'country':row.get('country'),'device':row.get('device'),'topic':row.get('topic'),
                  'language':row.get('language'),'format':row.get('format'),'scope':'page/query/dimensions as supplied'}
            try:
                reversed_window=datetime.fromisoformat(base['window_end'])<datetime.fromisoformat(base['window_start'])
            except TypeError:raise ImportError('Window dates must both include a timezone or both omit it') from None
            if reversed_window: raise ImportError('Window end precedes start')
            metrics={'clicks':'clicks','impressions':'impressions','conversions':'conversions','views':'views','position':'provider position','ctr':'fraction'}
            found=False
            for metric,unit in metrics.items():
                if metric not in row: continue
                value=number(row[metric])
                if metric=='ctr' and value is not None and value>1: raise ImportError('CTR is a fraction between 0 and 1, not a percentage')
                item={**base,'metric':metric,'value':value,'unit':unit}
                h=fingerprint(item)
                if h not in seen:
                    records.append(('metric',{**item,'id':uid(),'fingerprint':h,'batch_id':batch,'provenance':request.provenance,'kind':'user-supplied','private':request.private,'allow_analysis':request.allow_analysis,'imported_at':now()})); seen.add(h)
                found=True
            if not found: raise ImportError('Analytics requires clicks, impressions, ctr, position, views or conversions')
            continue
        h=fingerprint(item)
        if h in seen: continue
        seen.add(h)
        records.append((kind,{**item,'id':uid(),'fingerprint':h,'batch_id':batch,'provenance':request.provenance,'kind':'user-supplied','private':request.private,'allow_analysis':request.allow_analysis,'imported_at':now()}))
    return records

def cohorts(metrics):
    groups={}
    for m in metrics:
        aggregation='page_query' if m.get('query') else 'page'
        key=(aggregation,)+tuple(m.get(x) for x in ('provider','kind','metric','unit','window_start','window_end','country','device','language','format','topic'))
        if m.get('window_start') is None or m.get('window_end') is None: key=key+(m.get('measured_at'),)
        g=groups.setdefault(key,{'aggregation':aggregation,'kind':m['kind'],'provider':m['provider'],'metric':m['metric'],'unit':m['unit'],'window_start':m['window_start'],'window_end':m['window_end'],
             'country':m.get('country'),'device':m.get('device'),'language':m.get('language'),'format':m.get('format'),'topic':m.get('topic'),'values':[],'missing':0,'pages':set()})
        g['pages'].add(m['url'])
        if m['value'] is None: g['missing']+=1
        else: g['values'].append(m['value'])
    out=[]
    for g in groups.values():
        values=sorted(g.pop('values')); g.update(n=len(values),pages=len(g['pages']),median=values[len(values)//2] if values else None,
          interpretation='Descriptive collected cohort only; selection and missing rows may bias it. No causal inference or cross-platform total.')
        if values and len(values)%2==0: g['median']=(values[len(values)//2-1]+values[len(values)//2])/2
        out.append(g)
    return out
