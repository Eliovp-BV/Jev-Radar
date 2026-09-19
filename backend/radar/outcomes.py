"""Small, deterministic explanations of research scope and saved run outcomes.

These are views over saved records, not new research or generated conclusions.
Old missions need no migration, inference call, or rewritten evidence.
"""
import re
from urllib.parse import urlsplit
from .evidence import current_findings


def available_findings(plan, records):
    """Current claims also need an available source and a nonrejected subject."""
    excluded={name.casefold() for name in plan.get('excluded_entities',[])}
    def blocked_host(host):
        return any(host==domain or host.endswith('.'+domain) for domain in plan.get('excluded_domains',[]))
    entities={e['id']:e for e in records.get('entity',[])}
    invalid_entities={e['id'] for e in entities.values() if e.get('stale') or e.get('excluded') or e.get('review')=='rejected' or e.get('name','').casefold() in excluded or any(domain.casefold() in excluded for domain in e.get('domains',[]))}
    source_ids={s['id'] for s in records.get('source',[]) if not s.get('stale') and not s.get('excluded') and s.get('review')!='rejected' and not blocked_host(urlsplit(s['url']).hostname or '')}
    return [f for f in current_findings(records.get('finding',[])) if not f.get('excluded') and f.get('entity_id') not in invalid_entities and source_ids.intersection(f.get('source_ids',[]))]


def discovery_requested(plan):
    """A copy hint only; this never schedules work or establishes goal completion."""
    return alternatives_requested(plan) or bool(re.search(r'\b(find|discover|identify|trouver)\b', plan.get('goal', ''), re.I))


def alternatives_requested(plan):
    """Keep company/alternative copy separate from generic source discovery."""
    goal = plan.get('goal', '')
    explicit = re.search(r'\b(alternatives?|competitors?|alternatieven|concurrenten|concurrents?)\b', goal, re.I)
    supplier_search = (re.search(r'\b(find|discover|identify|trouver|chercher|vind|zoek)\b', goal, re.I)
                       and re.search(r'\b(suppliers?|vendors?|fournisseurs?|leveranciers?)\b', goal, re.I))
    return bool(explicit or supplier_search)


def plan_readiness(plan, capabilities):
    providers = plan.get('providers', ['seed'])
    seeds = list(dict.fromkeys(plan.get('seeds', []) + ([plan['reference']] if plan.get('reference') else [])))
    hosts = {urlsplit(url).hostname for url in seeds}
    has_queries = plan.get('limits', {}).get('max_queries', 4) > 0
    general = 'brave' in providers and bool(capabilities.get('brave')) and has_queries
    encyclopedia = 'wikipedia' in providers and has_queries
    mode = 'general_web' if general else 'wikipedia' if encyclopedia else 'seed' if seeds else 'none'
    discovery = discovery_requested(plan)
    alternatives = alternatives_requested(plan)
    warnings = []
    blockers = []
    if not capabilities.get('jev'):
        blockers.append({'code': 'jev_unavailable', 'message': 'Connect TypeSafe in Settings before starting research.', 'action': 'jev_settings'})
    if 'brave' in providers and not capabilities.get('brave'):
        blockers.append({'code': 'brave_unavailable', 'message': 'Brave web search is selected but its API key is not configured. Choose supplied websites or configure Brave in the project .env.', 'action': 'settings'})
    if not seeds and not general and not encyclopedia and not ('brave' in providers and not capabilities.get('brave')):
        blockers.append({'code':'discovery_unavailable','message':'Enable general web search to discover companies directly from this question.','action':'discover' if capabilities.get('brave') else 'settings'} if alternatives else {'code': 'no_sources', 'message': 'Add at least one public website to investigate, or enable an available search provider.', 'action': 'add_sources'})
    if not general:
        message = ('Wider web search is not configured. Radar can analyze websites you provide; Wikipedia only searches encyclopedia articles.'
                   if not capabilities.get('brave') else 'Wider web search is not enabled in this plan. Enable Brave in research options to search for other websites.')
        warnings.append({'code': 'general_web_unavailable', 'title': 'Wider web discovery is off', 'message': message, 'action': 'settings' if not capabilities.get('brave') else 'edit_plan'})
    if encyclopedia and not general:
        warnings.append({'code': 'encyclopedia_only', 'title': 'Wikipedia is an encyclopedia search', 'message': 'Wikipedia can supply background sources. It is not a company directory or a general web search.', 'action': 'add_sources'})
    if mode == 'seed' and discovery:
        title = 'Automatic company discovery needs web search' if alternatives else 'Discovery is limited to your websites'
        message = ('Enable general web search to find companies from your question. This plan currently inspects only supplied websites and their same-site links.'
                   if alternatives else 'This run can inspect only your supplied websites and their same-site links. Add more source websites or enable wider web search to look beyond them.')
        warnings.append({'code': 'seed_only_discovery', 'title': title, 'message': message, 'action': ('discover' if capabilities.get('brave') else 'settings') if alternatives else 'add_sources'})
    if not has_queries and any(p in providers for p in ('brave', 'wikipedia')):
        warnings.append({'code': 'queries_disabled', 'title': 'Search budget is zero', 'message': 'No search requests will run until the query limit is greater than zero.', 'action': 'edit_plan'})
    if general:
        summary = 'Search the web for sources, then inspect relevant pages. Findings remain limited to the pages actually visited.'
    elif encyclopedia:
        summary = 'Search Wikipedia and inspect any supplied websites. Wider web discovery is off.'
    elif seeds:
        summary = f'Inspect {len(seeds)} supplied page{"s" if len(seeds) != 1 else ""} across {len(hosts)} website{"s" if len(hosts) != 1 else ""}, plus allowed same-site links.'
    else:
        summary = 'Add a website to give this investigation a starting point.'
    return {'can_start': not blockers, 'mode': mode, 'summary': summary, 'discovery_requested': discovery, 'alternatives_requested': alternatives,
            'warnings': warnings, 'blockers': blockers, 'seed_pages': len(seeds), 'seed_websites': len(hosts)}


def _stop_reason(mission, records, events):
    status = mission['status']
    if status == 'draft':
        return {'code': 'not_started', 'message': 'This investigation has not started.'}
    if status in ('running', 'pausing'):
        return {'code': 'running', 'message': 'Research is in progress.' if status == 'running' else 'Pausing after the current bounded action finishes.'}
    if status == 'paused':
        return {'code': 'paused', 'message': 'Research is paused. Collected evidence is saved.'}
    if status == 'cancelled':
        return {'code': 'cancelled', 'message': 'Research was cancelled. Any evidence already collected is saved.'}
    # Prior attempts must not explain a later retry's outcome.
    start = max((i for i, event in enumerate(events) if event['type'] in ('mission.start', 'mission.resume', 'mission.retry')), default=0)
    recent = events[start:]
    for event in reversed(recent):
        kind, payload = event['type'], event.get('payload', {})
        if kind == 'mission.finished' and payload.get('stop_reason'):
            return payload['stop_reason']
        if kind == 'action.abstained':
            return {'code': 'jev_abstained', 'message': 'Jev stopped because none of the remaining prepared actions looked useful for this goal. This does not mean the research question is fully answered.', 'decision_id': payload.get('decision_id')}
        if kind in ('mission.blocked', 'mission.error'):
            return {'code': 'blocked', 'message': 'Research could not continue: ' + payload.get('reason', 'The current action failed.')}
        if kind == 'mission.deadline':
            return {'code': 'time_limit', 'message': 'The configured research time limit was reached. Collected evidence is saved.'}
        if kind == 'recovery':
            return {'code': 'interrupted', 'message': 'The server stopped during research. Saved evidence remains available; review the interrupted action before retrying.'}
        if kind == 'coverage.satisfied':
            return {'code': 'criteria_covered', 'message': 'The selected questions have supporting passages in the inspected sources. Wider discovery and independent verification are not established.'}
        if kind == 'research.stopped':
            return {k: v for k, v in payload.items() if k != 'record_changes'}
    if status == 'interrupted':
        return {'code': 'interrupted', 'message': 'Research was interrupted. Evidence already collected is saved.'}
    failed = [a for a in records.get('action', []) if a.get('status') in ('failed', 'uncertain')]
    if failed:
        return {'code': 'actions_failed', 'message': f'{len(failed)} research action{"s" if len(failed) != 1 else ""} could not be completed. Check source and provider errors before adding another source.'}
    return {'code': 'no_more_actions', 'message': 'No further eligible research actions remained in this plan. This is not proof that other sources or answers do not exist.'}


def mission_outcome(mission, records, events, capabilities, program=None):
    plan = mission['plan']
    program=program or next((r for r in reversed(records.get('research_program',[])) if r.get('status')=='complete' and r.get('plan_version')==mission.get('plan_version')),None)
    if program:plan={**plan,'criteria':program['criteria']}
    readiness = plan_readiness(plan, capabilities)
    sources = records.get('source', [])
    source_ids = {source['id'] for source in sources}
    entities = [entity for entity in records.get('entity', []) if entity.get('review') != 'rejected' and not entity.get('stale') and not entity.get('excluded')]
    findings = available_findings(plan, records)
    primary=[]
    if program and program['unit']!='companies':
        from .artifact_research import project_artifacts
        primary=project_artifacts(mission,records,program)
        primary_ids={s['id'] for s,_ in primary}
        findings=[f for f in findings if set(f.get('source_ids',[])) & primary_ids]
    supported = [finding for finding in findings if finding.get('status') == 'supported' and set(finding.get('source_ids', [])) & source_ids]
    partly = [finding for finding in findings if finding.get('status') == 'partly_supported' and set(finding.get('source_ids', [])) & source_ids]
    # Use the same surviving source/classification projection as company cards.
    # Runtime import avoids a module cycle; landscape only uses the pure helpers
    # above, never mission_outcome itself.
    from .landscape import landscape
    projected=landscape(mission,records)
    candidates=[card for card in projected['candidates'] if card['classification'] in ('direct','alternative') and card['evidence_count']]
    references=projected['references']
    pages = len({source['url'] for source in sources})
    counts = {'pages': pages, 'entities': len(entities), 'supported_findings': len(supported),
              'partly_supported_findings': len(partly), 'alternative_candidates': len(candidates), 'reference_entities': len(references),
              'failed_actions': sum(action.get('status') in ('failed', 'uncertain') for action in records.get('action', [])),
              'searches': len(records.get('search', [])), 'historical_findings': sum(bool(f.get('stale')) for f in records.get('finding', []))}
    if program:counts['primary_artifacts']=len(primary)
    stop = _stop_reason(mission, records, events)
    status = mission['status']
    discovery = readiness['discovery_requested']
    alternatives = readiness['alternatives_requested'] and (not program or program['unit']=='companies')
    if status == 'draft':
        headline = 'Ready to review your research plan'
    elif status in ('running', 'pausing'):
        headline = 'Collecting evidence'
    elif supported and alternatives and not candidates and references:
        headline = 'Reference evidence found; no alternatives identified yet'
    elif supported:
        headline = f'{len(supported)} supported finding{"s" if len(supported) != 1 else ""} to review'
    elif partly:
        headline = 'Some evidence found; the answers still need qualification'
    elif pages:
        headline = 'Pages inspected; no supported answers yet'
    else:
        headline = 'No evidence collected yet'
    summary = f'{pages} page{"s" if pages != 1 else ""} inspected; {len(supported)} supported finding{"s" if len(supported) != 1 else ""}.'
    if program and program['unit']=='videos':
        summary=f'{len(primary)} distinct relevant video records assessed; {len(supported)} scoped supported findings. Available metadata and text are not watched footage or proof of causation.'
        if pages and not supported:headline='Video records collected; the explanation still needs evidence'
    if alternatives:
        summary += f' {len(candidates)} candidate alternative{"s" if len(candidates) != 1 else ""} identified from inspected sources.'
    if references and alternatives:
        summary += ' Reference sources are shown separately from candidate alternatives.'
    if status == 'draft':
        summary = readiness['summary']
    covered = {f['criterion_id'] for f in supported}
    gaps = [{'criterion_id': criterion['id'], 'label': criterion['label'],
             'message': 'No current supported answer in the inspected sources.'}
            for criterion in plan.get('criteria', []) if criterion['id'] not in covered]
    if program and program['unit']!='companies':
        target=max(2,min(5,plan.get('discovery_target',3)))
        if len(primary)<target:gaps.append({'criterion_id':'artifact_coverage','label':'Comparable original artifacts','message':f'{len(primary)} of {target} distinct relevant artifacts assessed. Commentary about artifacts cannot fill this coverage gap.'})
    if alternatives and len(candidates)<plan.get('discovery_target',3):
        gaps.append({'criterion_id':'candidate_discovery','label':'Alternative discovery','message':f"{len(candidates)} of {plan.get('discovery_target',3)} target candidate domains have supporting evidence. This target is not proof of exhaustive discovery."})
    next_steps = []
    if stop['code'] in ('time_limit', 'configured_limits'):
        next_steps.append({'kind': 'edit_plan', 'label': 'Review research limits', 'detail': 'The previous run reached a configured limit. Review the plan and start a fresh run if further research is needed.'})
    if alternatives and readiness['mode']!='general_web' and status not in ('running','pausing') and not (status=='draft' and readiness['blockers']):
        kind='discover' if capabilities.get('brave') else 'settings'
        next_steps.append({'kind':kind,'label':'Find companies automatically' if kind=='discover' else 'Connect web search','detail':'Run a web search from your research question, then inspect candidate companies and compare their cited evidence.'})
    if status == 'paused':
        next_steps.append({'kind': 'resume', 'label': 'Continue research', 'detail': 'Resume the saved queue of research actions.'})
    elif status == 'draft' and readiness['blockers']:
        blocker = readiness['blockers'][0]
        next_steps.append({'kind': blocker['action'], 'label': 'Add websites' if blocker['action'] == 'add_sources' else 'Check research setup', 'detail': blocker['message']})
    elif status in ('blocked', 'interrupted'):
        next_steps.append({'kind': 'inspect_activity', 'label': 'Review what stopped research', 'detail': stop['message']})
    if status not in ('running', 'pausing') and ((alternatives and not candidates) or not supported or gaps):
        if readiness['mode'] != 'general_web' and not alternatives:
            detail = ('Paste public websites for the other companies or sources you want compared, then continue research.'
                      if alternatives else 'Paste public websites with relevant evidence for the unanswered questions, then continue research.')
            next_steps.append({'kind': 'add_sources', 'label': 'Add websites to investigate', 'detail': detail})
        elif status != 'draft' and readiness['mode']=='general_web':
            next_steps.append({'kind': 'edit_plan', 'label': 'Refine sources or search queries', 'detail': 'Review failed sources, add a focused query or website, and continue with the revised plan.'})
    if supported or partly:
        next_steps.append({'kind': 'review_results', 'label': 'Read the findings', 'detail': 'Open each finding to inspect its original source and exact supporting passage.'})
    if discovery and readiness['mode'] != 'general_web':
        next_steps.append({'kind': 'settings' if not capabilities.get('brave') else 'discover' if alternatives else 'edit_plan', 'label': 'Enable wider web discovery', 'detail': readiness['warnings'][0]['message']})
    if not next_steps and status not in ('running', 'pausing'):
        next_steps.append({'kind': 'review_results', 'label': 'Review the collected sources', 'detail': 'Inspect source pages and evidence before drawing conclusions.'})
    unique_steps = {}
    for step in next_steps:
        unique_steps.setdefault(step['kind'], step)
    next_steps = list(unique_steps.values())
    # UI receives a bounded preview; full, unchanged records remain available.
    cards = [{key: finding.get(key) for key in ('id', 'subject', 'question', 'statement', 'status', 'source_ids', 'evidence_kind', 'entity_id', 'criterion_id')}
             for finding in (supported + partly)[:8]]
    return {'headline': headline, 'summary': summary, 'counts': counts, 'stop': stop, 'gaps': gaps,
            'findings': cards, 'next_steps': next_steps, 'readiness': readiness,
            'scope': 'Support means the cited passage addresses the question. Company claims, entity classifications and geographic fit still need review.'}
