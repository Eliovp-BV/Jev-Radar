"""Read-only, question-level views of actual Jev calls and their recorded work."""
import math
import statistics


STAGES = {
    'planning': ('Designing the investigation', 'Jev selects the research subject, method, evidence priorities and discovery route for this goal.'),
    'selection': ('Choosing what to inspect', 'Jev chooses among prepared actions or existing search phrases.'),
    'relevance': ('Screening relevance', 'Jev assesses whether a retrieved page helps answer this goal.'),
    'classification': ('Understanding sources', 'Jev classifies the source, offer and relationship using supplied evidence.'),
    'evidence': ('Selecting evidence', 'Jev selects existing passages; the application checks their stored offsets.'),
    'verification': ('Checking support', 'Jev checks whether each selected passage answers its question.'),
    'comparison': ('Comparing inspected artifacts', 'Jev assesses proposed patterns against collected evidence and chooses a useful next test; association is not causation.'),
    'priorities': ('Prioritizing next steps', 'Jev chooses among prepared, evidence-linked experiments.')}


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _stage(question_id, purpose):
    if purpose == 'Design research approach': return 'planning'
    if purpose == 'Compare observed artifacts': return 'comparison'
    if purpose == 'Select independent records for parallel assessment': return 'selection'
    if purpose == 'Refine discovery for unanswered questions' or question_id in ('next', 'discovery_phrase', 'refine_query'): return 'selection'
    if question_id == 'relevance': return 'relevance'
    if question_id == 'priority': return 'priorities'
    if question_id.startswith('span_'): return 'evidence'
    if 'verify selected evidence' in purpose.lower(): return 'verification'
    return 'classification'


def jev_activity(mission, records, events, metrics):
    decisions = sorted(records.get('decision', []), key=lambda d: d.get('created_at', ''))
    sources = {source['id']: source for source in records.get('source', [])}
    actions = {action['id']: action for action in records.get('action', [])}
    findings = records.get('finding', [])
    finding_ids = {finding['id'] for finding in findings}
    criteria = {criterion['id']: criterion for criterion in mission.get('plan', {}).get('criteria', [])}
    programs=[program for program in records.get('research_program',[]) if program.get('plan_version')==mission.get('plan_version') and program.get('status')=='complete']
    if programs:criteria={criterion['id']:criterion for criterion in programs[-1].get('criteria',[])}
    groups = {key: {'id': key, 'label': label, 'description': description, 'items': []} for key, (label, description) in STAGES.items()}
    observed = {'action_choices': 0, 'abstentions': 0, 'assessed_sources': set(), 'passage_selections': 0, 'verification_answers': 0}
    for decision in decisions:
        purpose = decision.get('purpose', '')
        answered = decision.get('answers', {})
        cached = bool(decision.get('cache'))
        for question_id, question in decision.get('questions', {}).items():
            stage = _stage(question_id, purpose)
            answer = answered.get(question_id, {})
            raw_options = question.get('criteria', {})
            options = {str(i): label for i, label in enumerate(raw_options)} if isinstance(raw_options, list) else raw_options if isinstance(raw_options, dict) else {}
            probabilities = answer.get('probabilities', {})
            choice = answer.get('choice')
            selected = None
            if choice is not None:
                selected = {'id': choice, 'label': str(options.get(choice, choice)), 'probability': _number(probabilities.get(choice))}
            elif answer:
                value = _number(answer.get('score') if question.get('type') == 'score' else answer.get('noul'))
                selected = {'id': None, 'label': str(value) if value is not None else 'Unavailable', 'value': value,
                            'maximum': len(options) - 1 if question.get('type') == 'score' and options else 1 if question.get('type') == 'noul' else None}
            alternatives = [{'id': key, 'label': str(label), 'probability': _number(probabilities.get(key))} for key, label in options.items() if key != choice]
            alternatives.sort(key=lambda option: -(option['probability'] if option['probability'] is not None else -1))
            source_ids = [decision['source_id']] if decision.get('source_id') in sources else []
            action_ids = []
            search_ids = []
            collection = purpose == 'Select independent records for parallel assessment'
            lead = decision.get('state', {}).get('observed_leads', {}).get(question_id, {}) if collection else {}
            collection_action = actions.get(question_id) if collection else None
            lead_url = lead.get('url') or (collection_action or {}).get('value') or ''
            experiment = None
            comparison=next((record for record in records.get('research_analysis',[]) if record.get('decision_id')==decision['id']),None) if stage=='comparison' else None
            if comparison:
                pattern=next((item for item in comparison.get('patterns',[]) if item.get('id')==question_id),None)
                if pattern:source_ids+=[sid for sid in pattern.get('source_ids',[])+pattern.get('comparison_source_ids',[]) if sid in sources]
            if collection:
                if collection_action: action_ids = [question_id]
                if choice == 'inspect':
                    source_ids += [source['id'] for source in sources.values() if source.get('action_id') == question_id]
                    if collection_action and collection_action.get('kind') == 'reassess' and collection_action.get('source_id') in sources:
                        source_ids.append(collection_action['source_id'])
            elif question_id == 'next' and choice in actions:
                action_ids = [choice]
                source_ids += [source['id'] for source in sources.values() if source.get('action_id') == choice]
                if actions[choice].get('kind')=='reassess' and actions[choice].get('source_id') in sources:source_ids.append(actions[choice]['source_id'])
                if actions[choice].get('kind') == 'search':
                    search_ids = [attempt['search_id'] for attempt in records.get('search_attempt', []) if attempt.get('action_id') == choice and attempt.get('search_id')]
                    if not search_ids:search_ids = [search['id'] for search in records.get('search', []) if search.get('query') == actions[choice].get('value')]
                    source_ids += [source['id'] for source in sources.values() if source.get('discovered_via') in search_ids]
            elif question_id == 'discovery_phrase':
                if choice and choice != 'unknown':action_ids = [action['id'] for action in actions.values() if action.get('parent') in source_ids and action.get('kind') == 'search']
            elif question_id == 'refine_query' and choice not in (None,'stop'):
                action_ids=[action['id'] for action in actions.values() if action.get('kind')=='search' and action.get('parent')==decision['id']]
                search_ids=[attempt['search_id'] for attempt in records.get('search_attempt',[]) if attempt.get('action_id') in action_ids and attempt.get('search_id')]
                source_ids += [source['id'] for source in sources.values() if source.get('discovered_via') in search_ids]
            elif question_id == 'priority' and choice not in (None, 'none'):
                priority=next((p for p in records.get('opportunity_priority', []) if p.get('decision_id') == decision['id'] and p.get('selected') == choice),None)
                experiments=priority.get('suggestions', []) if priority else decision.get('state', {}).get('prepared_experiments', [])
                experiment=next((item for item in experiments if item.get('id') == choice),None)
                if experiment:source_ids += [sid for sid in experiment.get('context_source_ids',experiment.get('source_ids',[])) if sid in sources]
            source_ids = list(dict.fromkeys(source_ids))
            criterion_id = question_id.removeprefix('span_')
            related = [finding for finding in findings if (finding.get('decision_id') == decision['id'] or set(finding.get('source_ids', [])) & set(source_ids))
                       and (stage not in ('evidence', 'verification') or finding.get('criterion_id') == criterion_id)]
            if experiment:
                related=[finding for finding in findings if finding['id'] in set(experiment.get('evidence_ids',experiment.get('finding_ids',[]))) & finding_ids]
            label = criteria.get(criterion_id, {}).get('label', question_id.replace('_', ' ').capitalize())
            title = {'next': 'Next research action', 'discovery_phrase': 'Search phrase from this page', 'refine_query':'Refine discovery for missing evidence', 'relevance': 'Relevance to your question',
                     'entity_kind': 'Relationship to the reference', 'entity_role': 'Reference, candidate or background', 'entity_type': 'Type of offer',
                     'purpose': 'Purpose of this page', 'excluded_entity': 'Excluded subject check', 'original_data_claim': 'Original-data claim',
                     'research_unit':'What to investigate','research_method':'How to investigate','primary_dimension':'Primary evidence priority',
                     'secondary_dimension':'Evidence to challenge the answer','discovery_route':'How to discover original evidence','next_test':'Next test for this comparison',
                     'priority': 'Suggested next experiment'}.get(question_id, ('Passage for ' if stage == 'evidence' else 'Support for ' if stage == 'verification' else '') + label)
            if collection: title = 'Inspect independently: ' + (str(lead_url)[:240] or 'observed record')
            result = 'Awaiting an answer.' if not answer else 'Recorded model assessment; inspect the linked source and question.'
            if decision.get('status') == 'error': result = 'The request did not return a usable answer. Remote billing may still be uncertain.'
            if collection and answer:
                if choice == 'defer':
                    result = 'Jev deferred this record in this collection batch. This choice schedules no inspection.'
                    if not cached: observed['abstentions'] += 1
                elif choice == 'inspect':
                    selected_event = next((event for event in reversed(events) if event['type'] == 'collection.started'
                        and event.get('payload', {}).get('decision_id') == decision['id']), None)
                    admitted = bool(selected_event and question_id in selected_event['payload'].get('action_ids', []))
                    result = ('Selected for this parallel collection; linked action is ' + collection_action.get('status', 'unknown') + '.') if admitted and collection_action else 'Jev selected this record for inspection; no collection start is linked yet.'
                    if admitted and source_ids: result += f' {len(source_ids)} source snapshot(s) recorded.'
                    if not cached: observed['action_choices'] += 1
            if answer and stage == 'planning':
                linked=next((program for program in records.get('research_program',[]) if program.get('decision_id')==decision['id']),None)
                result='Selected a research-protocol option; no source finding is implied by planning.'
                if linked:result=f"Configured the {linked.get('unit','selected')} investigation with {len(linked.get('criteria',[]))} questions. The saved program expands these choices into bounded research steps."
            if answer and stage == 'comparison':
                result='Assessed collected artifact evidence; a recurring observation does not establish a causal mechanism.'
                if question_id=='next_test':result='Selected a prepared follow-up test. The test has not been executed.'
                elif comparison:
                    pattern=next((item for item in comparison.get('patterns',[]) if item.get('id')==question_id),None)
                    if pattern:result=f"Saved comparison status: {pattern.get('status','unknown')}. "+result
                if comparison and comparison.get('stale'):result='Historical comparison; changed evidence or plan requires reassessment. '+result
            if answer and question_id=='refine_query':
                if choice=='stop':
                    result='Jev declined the prepared discovery refinements; no new query was scheduled.'
                    if not cached:observed['abstentions']+=1
                else:
                    states=', '.join(dict.fromkeys(actions[action_id].get('status','unknown') for action_id in action_ids))
                    result=('Selected an evidence-gap query; linked search action status: '+states+'.') if action_ids else 'Selected a prepared refinement; no resulting search action is linked yet.'
                    if not cached:observed['action_choices']+=1
            if answer and question_id == 'next':
                if choice == 'stop':
                    result = 'Jev declined the presented action batch; the event trail records whether further work remained.'
                    if not cached: observed['abstentions'] += 1
                elif choice in actions:
                    action = actions[choice]
                    result = f"Selected {action['kind']} action is {action.get('status', 'unknown')}."
                    if action.get('kind')=='video':
                        result=f"Indexed video metadata inspection is {action.get('status','unknown')}. This action does not fetch or watch the original video."
                    elif action.get('kind')=='reassess':
                        result=f"Saved-evidence reassessment is {action.get('status','unknown')}. Existing observations are checked against the current questions; no new page or media fetch occurs."
                    elif action.get('status') == 'complete' and action.get('kind') == 'search':
                        searches=[search for search in records.get('search',[]) if search['id'] in search_ids]
                        count=sum(len(search.get('results',[])) for search in searches)
                        result=f'Completed search; {count} results were recorded in {len(searches)} provider response(s).'
                    elif action.get('status') == 'complete' and source_ids:
                        result=f'Completed {action["kind"]}; {len(source_ids)} source snapshot(s) recorded.'
                    if action.get('error'): result += ' ' + str(action['error'])[:200]
                    if not cached: observed['action_choices'] += 1
            if answer and question_id == 'relevance' and decision.get('source_id'):
                observed['assessed_sources'].add(decision['source_id'])
                screened=any(e['type']=='source.screened_out' and e.get('payload',{}).get('decision_id')==decision['id'] for e in events)
                retained=any(e['type']=='assessment.recorded' and e.get('payload',{}).get('decision_id')==decision['id'] for e in events)
                result=('This page was screened out; no findings were inferred from it.' if screened else 'This page was retained and its assessment was recorded.' if retained else 'Relevance answer recorded; a final source assessment is not yet linked.')+' The score uses the displayed rubric, not factual-accuracy probability.'
            if answer and stage == 'evidence':
                if choice in ('unknown', 'not_applicable'):
                    result = 'No applicable supporting passage was selected from the inspected excerpts.'
                else:
                    result = 'Selected an existing passage for a separate support check.'
                    if not cached: observed['passage_selections'] += 1
            if answer and stage == 'verification':
                statuses={status:sum(f.get('status')==status for f in related) for status in sorted({f.get('status','unknown') for f in related})}
                recorded=', '.join(f'{count} {status.replace("_"," ")}' for status,count in statuses.items())
                result=(f'Recorded findings: {recorded}.' if related else 'Support answer recorded; no matching finding has been saved yet.')+' This is a passage-support check, not independent factual verification.'
                if not cached: observed['verification_answers'] += 1
            if answer and stage == 'priorities':
                result = f'Selected a prepared experiment linked to {len(related)} finding(s) and {len(source_ids)} source(s). It has not been executed; no commercial result is predicted.' if choice != 'none' else 'None of the prepared experiments was selected.'
            if answer and stage == 'classification' and decision.get('source_id') in sources:
                source=sources[decision['source_id']]
                field={'entity_kind':'classification','entity_role':'role','entity_type':'entity_type','purpose':'purpose'}.get(question_id)
                if field and source.get(field)==choice:
                    result=f'Recorded this source’s {field.replace("_"," ")}: {str(choice).replace("_"," ")}. '+('It contributes to the saved entity profile.' if source.get('entity_id') else 'No entity profile is linked yet.')
            groups[stage]['items'].append({'id': decision['id'] + ':' + question_id, 'decision_id': decision['id'], 'question_id': question_id,
                'stage': stage, 'title': title, 'question': question.get('instructions', ''), 'type': question.get('type'),
                'status': decision.get('status', 'unknown'), 'cached': cached, 'selected': selected, 'alternatives': alternatives[:6],
                'alternatives_total': len(alternatives), 'rubric': [{'id': key, 'label': str(value)} for key, value in options.items()] if question.get('type') == 'score' else [],
                'confidence': _number(answer.get('confidence')), 'latency_ms': None if cached else _number(decision.get('latency_ms')),
                'queue_ms': None if cached else _number(decision.get('queue_ms')), 'model': decision.get('model') or decision.get('requested_model'),
                'source_ids': source_ids, 'finding_ids': [finding['id'] for finding in related], 'action_ids': action_ids,'search_ids':search_ids,
                **({'lead_url': lead_url} if collection else {}),
                'result': result, 'created_at': decision.get('created_at'), 'purpose': purpose})
    deterministic = []
    policies = {'action.reference_prerequisite': 'Read the reference first', 'action.single_legal': 'Only one eligible action', 'action.exploration': 'Reserved exploration step', 'coverage.satisfied': 'Coverage rule satisfied'}
    for event in events:
        if event['type'] not in policies: continue
        payload = event.get('payload', {})
        deterministic.append({'event_id': event['id'], 'type': event['type'], 'label': policies[event['type']],
                              'reason': payload.get('reason', 'The configured coverage rule was evaluated against collected evidence.'),
                              'action_ids': [payload['action_id']] if payload.get('action_id') else [],
                              'source_ids': [payload['source_id']] if payload.get('source_id') else [], 'timestamp': event.get('timestamp')})
    measured = [d for d in decisions if not d.get('cache') and d.get('status') == 'complete' and _number(d.get('latency_ms')) is not None]
    latencies = [d['latency_ms'] for d in measured]
    summary = {'attempts': metrics.get('attempts', 0), 'completions': sum(not d.get('cache') and d.get('status') == 'complete' for d in decisions),
               'errors': sum(not d.get('cache') and d.get('status') == 'error' for d in decisions), 'cached_calls': sum(bool(d.get('cache')) for d in decisions),
               'answered_questions': sum(len(d.get('answers', {})) for d in decisions if not d.get('cache') and d.get('status') == 'complete'),
               'measured_calls': len(latencies), 'median_ms': statistics.median(latencies) if latencies else None, 'latest_ms': latencies[-1] if latencies else None,
               **observed, 'assessed_sources': len(observed['assessed_sources']), 'deterministic_steps': len(deterministic)}
    return {'summary': summary, 'groups': list(groups.values()), 'deterministic': deterministic,
            'scope': 'Recorded questions, answers and resulting work. One call can contain several question types; timings are counted once per live call and include client/network round-trip. Cache reuse is separate. No claim of saved time, guaranteed accuracy or hidden model reasoning is made.'}
