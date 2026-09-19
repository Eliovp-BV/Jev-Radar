"""Evidence-bound collection view. No inference, invented scores or speedup claims."""
from collections import Counter
from datetime import datetime
from statistics import median
import math
from urllib.parse import urlsplit

from .artifact_research import project_artifacts
from .program import active_program


STATUSES = ('supported', 'partly_supported', 'contradicted', 'not_applicable', 'unknown')


def _public(record):
    return not any(record.get(key) for key in ('private', 'stale', 'excluded')) and record.get('review') != 'rejected'


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _timings(decisions):
    paid = [d for d in decisions if not d.get('cache')]
    missing = sum(not _number(d.get('latency_ms')) for d in paid)
    return {'decision_ids': [d['id'] for d in decisions], 'jev_calls': len(paid),
            'cached_calls': len(decisions) - len(paid),
            'question_count': sum(len(d.get('answers', {})) for d in decisions),
            'missing_timing_calls': missing,
            'assessment_ms': round(sum(d['latency_ms'] for d in paid), 2) if paid and not missing else None,
            'estimated_usd': sum(d['estimated_usd'] for d in paid) if all(_number(d.get('estimated_usd')) for d in paid) else None}


def _analysis_window(decisions):
    """Union of observed provider intervals; concurrent requests count once."""
    intervals = []
    for decision in decisions:
        if decision.get('cache'):
            continue
        if not _number(decision.get('latency_ms')):
            return None, None
        try:
            stamp = datetime.fromisoformat(decision['created_at'].replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                return None, None
            # Jev records created_at after entering its semaphore; queue_ms is
            # already excluded from this provider interval.
            start = stamp.timestamp() * 1000
        except (KeyError, TypeError, ValueError, OverflowError):
            return None, None
        intervals.append((start, start + decision['latency_ms']))
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    if not intervals:return None, None
    return (round(max(end for _,end in intervals)-min(start for start,_ in intervals),2),
            round(sum(end-start for start,end in merged),2))


def project_corpus(mission, records, program=None):
    """Project current original records; every populated cell retains exact evidence."""
    plan = mission['plan']
    if program and not _public(program):
        records={};program=None
    columns = [{key: item.get(key, '') for key in ('id', 'label', 'question')}
               for item in (program or {}).get('criteria', plan.get('criteria', []))]
    excluded_names = {name.casefold() for name in plan.get('excluded_entities', [])}
    entities={e['id']:e for e in records.get('entity', [])}
    invalid_entities = {e['id'] for e in entities.values() if not _public(e)
                        or e.get('name', '').casefold() in excluded_names
                        or any(domain.casefold() in excluded_names for domain in e.get('domains', []))}
    sources = {}
    for source in records.get('source', []):
        host = urlsplit(source.get('url', '')).hostname or ''
        if (not _public(source) or source.get('entity_id') in invalid_entities
                or any(host == domain or host.endswith('.' + domain) for domain in plan.get('excluded_domains', []))
                or program and source.get('program_id') != program['id']):
            continue
        sources[source['id']] = source
    decisions = {d['id']: d for d in records.get('decision', [])
                 if _public(d) and d.get('status') == 'complete'
                 and (d.get('rubric_version') is None or d['rubric_version'] == mission['plan_version'])}
    def bound_decision(decision_id,source_id):
        return decision_id in decisions and decisions[decision_id].get('source_id') == source_id
    assessments = {}
    if program and program.get('unit') != 'companies':
        safe_records = {**records, 'source': list(sources.values()),
                        'artifact_analysis': [a for a in records.get('artifact_analysis', []) if _public(a)]}
        pairs = project_artifacts(mission, safe_records, program)
        # A classification without its saved typed decision is not a verified row.
        assessments = {s['id']: a for s, a in pairs
                       if bound_decision(a.get('decision_id'),s['id'])
                       and bound_decision(s.get('decision_id'),s['id'])
                       and (not a.get('verification_decision_id') or bound_decision(a['verification_decision_id'],s['id']))}
        sources = {sid: source for sid, source in sources.items() if sid in assessments}
    else:
        sources = {sid: s for sid, s in sources.items() if bound_decision(s.get('decision_id'),sid)
                   and not s.get('duplicate_of') and s.get('role') not in ('background',)
                   and s.get('entity_type') not in ('directory', 'editorial')
                   and entities.get(s.get('entity_id'),{}).get('role')!='background'}
    spans = {}
    for span in records.get('span', []):
        source = sources.get(span.get('source_id'))
        start, end, quote = span.get('start'), span.get('end'), span.get('text')
        if (source and _public(span) and type(start) is int and type(end) is int and 0 <= start < end
                and isinstance(quote, str) and quote and isinstance(source.get('text'), str)
                and source['text'][start:end] == quote and len(quote) == end - start):
            spans[span['id']] = span
    findings = []
    criterion_ids = {column['id'] for column in columns}
    for finding in records.get('finding', []):
        source_ids = set(finding.get('source_ids', []))
        evidence_ids = set(finding.get('span_ids', []))
        if (not _public(finding) or finding.get('entity_id') in invalid_entities
                or finding.get('criterion_id') not in criterion_ids
                or finding.get('status') not in STATUSES
                or finding.get('decision_id') not in decisions
                or decisions[finding['decision_id']].get('source_id') not in source_ids
                or program and finding.get('program_id') not in (None, program['id'])
                or not source_ids or not source_ids <= sources.keys()
                or not evidence_ids or not evidence_ids <= spans.keys()
                or any(spans[sid]['source_id'] not in source_ids for sid in evidence_ids)
                or {spans[sid]['source_id'] for sid in evidence_ids} != source_ids):
            continue
        findings.append(finding)
    rows = []
    used_decisions = {}
    for source_id, source in sources.items():
        assessment = assessments.get(source_id, {})
        relevant = [f for f in findings if source_id in f['source_ids']]
        ids = {source.get('decision_id'), assessment.get('decision_id'), assessment.get('verification_decision_id')}
        ids.update(f['decision_id'] for f in relevant)
        linked = [d for did, d in decisions.items() if did in ids and d.get('source_id') == source_id]
        used_decisions.update({d['id']: d for d in linked})
        cells = []
        for column in columns:
            selected = [f for f in relevant if f['criterion_id'] == column['id']]
            statuses = {f['status'] for f in selected}
            # Contradictory results cannot be flattened into a reassuring coverage score.
            status = ('contradicted' if 'contradicted' in statuses else 'supported' if 'supported' in statuses
                      else 'partly_supported' if 'partly_supported' in statuses
                      else 'not_applicable' if statuses == {'not_applicable'} else 'unknown')
            citation_ids = list(dict.fromkeys(sid for finding in selected for sid in finding['span_ids']))
            citations = []
            for sid in citation_ids:
                span = spans[sid]
                citations.append({'span_id': sid, 'source_id': span['source_id'], 'url': sources[span['source_id']]['url'],
                                  'quote': span['text'][:800], 'start': span['start'],
                                  'end': span['start'] + min(800, len(span['text']))})
            confidence = [decisions[f['decision_id']].get('answers', {}).get(column['id'], {}).get('confidence') for f in selected]
            confidence = [value for value in confidence if _number(value) and value <= 1]
            cells.append({'criterion_id': column['id'], 'status': status,
                          'finding_ids': [f['id'] for f in selected],
                          'decision_ids': list(dict.fromkeys(f['decision_id'] for f in selected)),
                          'citations': citations, 'confidence': min(confidence) if confidence else None})
        rows.append({'id': source_id, 'source_id': source_id, 'title': source.get('title', source['url']),
                     'url': source['url'], 'role': assessment.get('role', source.get('role', 'unknown')),
                     'evidence_basis': source.get('evidence_basis', 'Inspected public page text'),
                     'cells': cells, **_timings(linked)})
    rollups = []
    for column in columns:
        counts = Counter(cell['status'] for row in rows for cell in row['cells'] if cell['criterion_id'] == column['id'])
        rollups.append({'criterion_id': column['id'], 'label': column['label'], 'denominator': len(rows),
                        **{status: counts[status] for status in STATUSES}})
    features = []
    dimensions = {key for assessment in assessments.values() for key in assessment.get('features', {})}
    for key in sorted(dimensions):
        values, label, unknown = {}, key, 0
        for row in rows:
            feature = assessments.get(row['id'], {}).get('features', {}).get(key, {})
            label = feature.get('dimension', label)
            evidence_ids = set(feature.get('span_ids', []))
            if (feature.get('choice') in (None, 'unknown') or not _public(feature)
                    or feature.get('verification_status') not in ('supported', 'partly_supported')
                    or not bound_decision(feature.get('decision_id'),row['id']) or not evidence_ids or not evidence_ids <= spans.keys()
                    or any(spans[sid]['source_id'] != row['id'] for sid in evidence_ids)):
                unknown += 1
                continue
            choice = feature['choice']
            value = values.setdefault(choice, {'value': choice, 'label': feature.get('label', choice), 'count': 0, 'source_ids': []})
            value['count'] += 1
            value['source_ids'].append(row['id'])
        features.append({'id': key, 'label': label, 'denominator': len(rows), 'unknown': unknown,
                         'values': sorted(values.values(), key=lambda value: (-value['count'], value['value']))})
    measured = list(used_decisions.values())
    timing = _timings(measured)
    paid = [d for d in measured if not d.get('cache')]
    wall,active = _analysis_window(measured)
    paid_items = sum(row['jev_calls'] > 0 for row in rows)
    paid_questions = sum(len(d.get('answers', {})) for d in paid)
    latencies = [row['assessment_ms'] for row in rows if row['assessment_ms'] is not None]
    metrics = {'items': len(rows), 'typed_judgments': timing['question_count'], 'jev_calls': timing['jev_calls'],
               'cached_calls': timing['cached_calls'], 'median_item_ms': median(latencies) if latencies else None,
               'analysis_wall_ms': wall, 'active_inference_ms':active,
               'items_per_second': round(paid_items * 1000 / wall, 2) if wall else None,
               'judgments_per_second': round(paid_questions * 1000 / wall, 2) if wall else None,
               'estimated_usd': timing['estimated_usd'],
               'cost_known_calls': sum(_number(d.get('estimated_usd')) for d in paid),
               'cost_unknown_calls': sum(not _number(d.get('estimated_usd')) for d in paid)}
    return {'program_id': (program or {}).get('id'), 'unit': (program or {}).get('unit', 'sources'),
            'scope': 'Current inspected original records; this collection is not an exhaustive market or population census.',
            'columns': columns, 'rows': rows, 'rollups': rollups, 'features': features, 'metrics': metrics,
            'limitations': ['Question rollups measure evidence coverage, not quality, popularity or causal impact.',
                            'Typed classifications describe the supplied evidence. Unknowns remain in each denominator.',
                            'The measured analysis window runs from the first linked request to the last completion, including any intervening acquisition or idle time. Active inference time counts overlapping request intervals once. Neither is a comparative speed benchmark.',
                            'Costs cover linked Jev assessment requests only. Search, other decisions and text-model generation are separate.']}


def corpus_summary(store, mid):
    mission=store.mission(mid)
    program=active_program(store,mid)
    if mission['plan'].get('research_mode')=='adaptive' and not program:
        return project_corpus(mission,{},None)
    return project_corpus(mission, {kind: store.records(mid, kind)
                          for kind in ('source', 'entity', 'finding', 'span', 'decision', 'artifact_analysis')},
                          program)
