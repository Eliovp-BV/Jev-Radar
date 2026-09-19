"""Company and entity results projected from inspected, source-linked evidence.

This module does not research, generate claims, estimate market popularity, or
change saved records. Search visibility describes only saved search responses.
"""
import math
from urllib.parse import urlsplit

from .outcomes import alternatives_requested, available_findings
from .storage import fingerprint


RELATIONSHIPS = ('direct', 'alternative', 'adjacent')
SUPPORTED = ('supported', 'partly_supported')


def _host(value):
    try:
        host = urlsplit(value if '://' in value else 'https://' + value).hostname or ''
    except (ValueError, TypeError):
        return ''
    host = host.lower().rstrip('.')
    return host[4:] if host.startswith('www.') else host


def _eligible(record):
    return not record.get('stale') and record.get('review') != 'rejected' and not record.get('excluded')


def _unique(values):
    return list(dict.fromkeys(value for value in values if value))


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def landscape(mission, records):
    """Return current entity cards, observed visibility, and scoped experiments.

    The arrays are ordered by assessed page relevance by default. ``sort_values``
    gives the client explicit scalar keys; visibility sorting counts distinct
    saved query strings containing this host, not audience size or popularity.
    """
    plan = mission.get('plan', {})
    criteria = plan.get('criteria', [])
    criterion_ids = {criterion['id'] for criterion in criteria}
    excluded_entities = {name.casefold() for name in plan.get('excluded_entities', [])}
    def blocked_source(source):
        host = urlsplit(source['url']).hostname or ''
        return any(host == domain or host.endswith('.' + domain) for domain in plan.get('excluded_domains', []))
    sources = {source['id']: source for source in records.get('source', []) if _eligible(source) and not blocked_source(source)}
    spans = {span['id']: span for span in records.get('span', []) if _eligible(span) and span.get('source_id') in sources}
    decisions = {decision['id']: decision for decision in records.get('decision', []) if _eligible(decision)}
    findings = [finding for finding in available_findings(plan, records)
                if _eligible(finding) and finding.get('status') in SUPPORTED
                and finding.get('criterion_id') in criterion_ids
                and set(finding.get('source_ids', [])) & sources.keys()]
    reference_host = _host(plan.get('reference', ''))
    cards = []
    for entity in records.get('entity', []):
        if (not _eligible(entity) or entity.get('name', '').casefold() in excluded_entities
                or any(domain.casefold() in excluded_entities for domain in entity.get('domains', []))):
            continue
        entity_sources = [sources[source_id] for source_id in _unique(entity.get('source_ids', [])) if source_id in sources]
        if not entity_sources:
            continue
        source_ids = [source['id'] for source in entity_sources]
        own_findings = [finding for finding in findings if finding.get('entity_id') == entity['id']
                        and set(finding.get('source_ids', [])) & set(source_ids)]
        # Host groups are saved by the runner; do not infer shared ownership from
        # a suffix (for example, service.example.com is not example.com).
        domains = _unique(_host(domain) for domain in entity.get('domains', []))
        domains = _unique(domains + [_host(source['url']) for source in entity_sources])
        is_explicit_reference = bool(reference_host and reference_host in domains)
        role = entity.get('role', 'unknown')
        entity_type = entity.get('entity_type', 'unknown')
        classification = entity.get('classification', 'unknown')
        classification_observations = [observation for observation in entity.get('classification_observations', [])
                                       if _eligible(observation) and observation.get('source_id') in source_ids
                                       and observation.get('decision_id') in decisions]
        if entity.get('classification_observations'):
            # A saved aggregate may still refer to a source rejected after the
            # run. Retain each assessment only when current observations support
            # it; never restore a stronger relation from conflicting evidence.
            if not any(observation.get('classification') == classification for observation in classification_observations):
                classification = 'unknown'
            if not any(observation.get('role') == role for observation in classification_observations):
                role = 'unknown'
            if not any(observation.get('entity_type') == entity_type for observation in classification_observations):
                entity_type = 'unknown'
        else:
            classification_decision = decisions.get(entity.get('classification_decision'))
            if (entity.get('classification_decision') and not classification_decision
                    or classification_decision and classification_decision.get('source_id')
                    and classification_decision['source_id'] not in source_ids):
                classification, role, entity_type = 'unknown', 'unknown', 'unknown'
        reference_basis = ('plan_reference' if is_explicit_reference else
                           'role' if role == 'reference_product' else
                           'classification' if classification == 'reference' else None)
        fields = []
        for criterion in criteria:
            values = []
            related = [finding for finding in own_findings if finding['criterion_id'] == criterion['id']]
            # Supported passages precede qualified answers; retain every linked
            # answer rather than silently resolving potentially differing claims.
            related.sort(key=lambda finding: (finding['status'] != 'supported', finding.get('retrieved_at', ''), finding['id']))
            for finding in related:
                linked_sources = [source_id for source_id in finding.get('source_ids', []) if source_id in sources]
                linked_spans = [span_id for span_id in finding.get('span_ids', [])
                                if span_id in spans and spans[span_id]['source_id'] in linked_sources]
                text = spans[linked_spans[0]]['text'] if linked_spans else finding.get('statement', '')
                values.append({'finding_id': finding['id'], 'value': text[:800], 'status': finding['status'],
                               'source_ids': linked_sources, 'span_ids': linked_spans,
                               'decision_id': finding.get('decision_id') if finding.get('decision_id') in decisions else None,
                               'evidence_kind': finding.get('evidence_kind', 'Source assertion'),
                               'retrieved_at': finding.get('retrieved_at'),
                               'scope': finding.get('scope', 'Only the cited passages were inspected; factual accuracy is not independently established.')})
            field_status = ('supported' if any(value['status'] == 'supported' for value in values)
                            else 'partly_supported' if values else 'unknown')
            fields.append({'criterion_id': criterion['id'], 'label': criterion['label'],
                           'question': criterion.get('question', ''), 'status': field_status, 'values': values})
        relevance_observations = []
        for source in entity_sources:
            score = source.get('relevance')
            decision = decisions.get(source.get('decision_id'), {})
            rubric = decision.get('questions', {}).get('relevance', {}).get('criteria', [])
            # TypeSafe Score is a weighted rubric index, not a probability.
            # Existing source assessments use 0=unrelated, 1=context, 2=useful.
            maximum = len(rubric) - 1 if isinstance(rubric, list) and rubric else 2
            if _number(score) and 0 <= score <= maximum and source.get('decision_id') in decisions:
                relevance_observations.append({'source_id': source['id'], 'decision_id': source['decision_id'],
                                               'score': score, 'url': source['url']})
        relevance = max((observation['score'] for observation in relevance_observations), default=None)
        appearances = []
        seen_appearances = set()
        for search in records.get('search', []):
            if not _eligible(search):
                continue
            for result in search.get('results', []):
                position = result.get('position')
                if (not _eligible(result) or _host(result.get('url', '')) not in domains
                        or not _number(position) or position < 1 or int(position) != position):
                    continue
                key = (search['id'], result.get('id'), result['url'], position)
                if key in seen_appearances:
                    continue
                seen_appearances.add(key)
                appearances.append({'search_id': search['id'], 'result_id': result.get('id'),
                                    'query': search.get('query', ''), 'timestamp': search.get('timestamp'),
                                    'provider': search.get('provider', 'unknown'), 'position': int(position),
                                    'url': result['url'], 'scope': search.get('scope', 'Provider-specific saved search response'),
                                    'language': search.get('language'), 'region_requested': search.get('region_requested')})
        visibility_count = len({appearance['search_id'] for appearance in appearances})
        visibility = {'observation_count': visibility_count,
                      'query_count': len({appearance['query'] for appearance in appearances}),
                      'provider_query_count': len({(appearance['provider'], appearance['query']) for appearance in appearances}),
                      'best_position': min((appearance['position'] for appearance in appearances), default=None),
                      'observations': appearances,
                      'scope': 'Appearances in saved provider responses for this investigation. Repeated searches remain separate observations. This is not market popularity, market share, traffic, or a universal search ranking.'}
        card = {'id': entity['id'], 'name': entity.get('name') or domains[0], 'url': entity_sources[0]['url'],
                'domains': domains, 'classification': classification, 'role': role, 'entity_type': entity_type,
                'reference_basis': reference_basis, 'source_ids': source_ids,
                'finding_ids': [finding['id'] for finding in own_findings],
                'decision_ids': _unique([entity.get('classification_decision') if entity.get('classification_decision') in decisions else None]
                                        + [source.get('decision_id') for source in entity_sources if source.get('decision_id') in decisions]
                                        + [finding.get('decision_id') for finding in own_findings if finding.get('decision_id') in decisions]),
                'classification_observations': classification_observations,
                'evidence_count': len(own_findings), 'source_count': len(entity_sources), 'fields': fields,
                'pricing': next((field for field in fields if field['criterion_id'] == 'pricing'), None),
                'capabilities': next((field for field in fields if field['criterion_id'] == 'capabilities'), None),
                'relevance': {'score': relevance, 'aggregation': 'Highest assessed page relevance', 'observations': relevance_observations},
                'search_visibility': visibility,
                'sort_values': {'relevance': relevance, 'search_visibility': visibility['query_count'], 'evidence': len(own_findings),
                                'name': (entity.get('name') or domains[0]).casefold()},
                'unknowns': [field['label'] for field in fields if field['status'] == 'unknown'],
                'scope': entity.get('ownership', 'Grouped by inspected host; company identity and cross-domain ownership are not independently verified.')}
        cards.append(card)
    cards.sort(key=lambda card: (-(card['relevance']['score'] if card['relevance']['score'] is not None else -1),
                                 -card['evidence_count'], card['sort_values']['name'], card['id']))
    references = [card for card in cards if card['reference_basis']]
    candidates = [card for card in cards if not card['reference_basis'] and card['classification'] in RELATIONSHIPS
                  and card['role'] != 'background' and card['entity_type'] not in ('directory', 'editorial')]
    other = [card for card in cards if card not in references and card not in candidates]
    # A reference article is useful background, but it is not the user's product.
    focal = [card for card in references if card['reference_basis'] in ('plan_reference', 'role')
             and card['entity_type'] not in ('directory', 'editorial') and card['role'] != 'background']
    improvements = []
    for criterion in criteria:
        reference_values = [(card, field) for card in focal for field in card['fields']
                            if field['criterion_id'] == criterion['id'] and field['values']]
        candidate_values = [(card, field) for card in candidates for field in card['fields']
                            if field['criterion_id'] == criterion['id'] and field['values']]
        if not focal or not candidate_values:
            continue
        all_values = [value for _, field in reference_values + candidate_values for value in field['values']]
        comparison_evidence = []
        for side, pairs in (('reference', reference_values[:2]), ('candidate', candidate_values[:3])):
            for card, field in pairs:
                value = field['values'][0]
                comparison_evidence.append({'side': side, 'entity_id': card['id'], 'name': card['name'],
                                            'finding_id': value['finding_id'], 'value': value['value'][:240],
                                            'status': value['status']})
        unknown = [card['name'] for card in focal if not any(candidate['id'] == card['id'] for candidate, _ in reference_values)]
        if reference_values:
            observation = f"Both the identified reference and {len(candidate_values)} candidate(s) have source-linked answers about {criterion['label'].lower()}. The excerpts may describe different scopes."
            experiment = (f"Compare the cited {criterion['label'].lower()} passages for the reference and candidates. "
                          'Record a specific difference only if the passages establish it, then test whether explaining or changing it helps intended users complete a relevant evaluation task.')
        else:
            observation = (f"{len(candidate_values)} candidate(s) have source-linked answers about {criterion['label'].lower()}, "
                           'but the inspected reference pages have no current supported or partly supported answer. This is an evidence gap, not proof the reference lacks a capability.')
            experiment = (f"Verify the reference's {criterion['label'].lower()} with its owner or a primary source. "
                          'If an important answer exists but is hard to find publicly, test a clearer explanation with intended users before changing the product.')
        improvements.append({'id': fingerprint({'mission': mission.get('id'), 'criterion': criterion['id'], 'kind': 'landscape_experiment'})[:32],
                             'criterion_id': criterion['id'], 'title': f"Compare {criterion['label'].lower()}" if reference_values else f"Resolve the reference's {criterion['label'].lower()} gap",
                             'kind': 'proposed experiment', 'reference_ids': [card['id'] for card in focal],
                             'candidate_ids': [card['id'] for card, _ in candidate_values],
                             'comparison_evidence': comparison_evidence,
                             'finding_ids': _unique(value['finding_id'] for value in all_values),
                             'source_ids': _unique([source_id for value in all_values for source_id in value['source_ids']]
                                                   + [source_id for card in focal for source_id in card['source_ids']]),
                             'decision_ids': _unique(value['decision_id'] for value in all_values), 'observation': observation,
                             'experiment': experiment,
                             'success_measure': 'Record whether representative users can answer the evaluation question accurately from the proposed explanation; retain their observations and remaining questions.',
                             'unknowns': ([f"No current answer for reference: {name}." for name in unknown]
                                          + ['Customer preference, product superiority, demand, and commercial impact have not been established.'])})
    priorities = [priority for priority in records.get('opportunity_priority', []) if _eligible(priority)
                  and priority.get('rubric_version') == mission.get('plan_version')]
    priority = priorities[-1] if priorities else {}
    priority_decision = decisions.get(priority.get('decision_id'), {})
    selected = (priority.get('selected') if priority_decision.get('status') == 'complete'
                and priority_decision.get('answers', {}).get('priority', {}).get('choice') == priority.get('selected') else None)
    snapshot = next((item for item in priority.get('suggestions', []) if item.get('id') == selected), {})
    for improvement in improvements:
        improvement['jev_priority'] = False
        improvement['decision_id'] = None
        # The ID alone is not enough: later pages can change a comparison while
        # preserving its criterion. Link priority only to the exact saved inputs.
        same_inputs = all(snapshot.get(key) == improvement.get(key) for key in (
            'criterion_id', 'reference_ids', 'candidate_ids', 'finding_ids', 'source_ids',
            'observation', 'experiment', 'success_measure', 'unknowns'))
        if 'comparison_evidence' in snapshot:
            same_inputs = same_inputs and snapshot['comparison_evidence'] == improvement['comparison_evidence']
        if improvement['id'] == selected and same_inputs:
            improvement['jev_priority'] = True
            improvement['decision_id'] = priority_decision['id']
    improvements.sort(key=lambda improvement: not improvement['jev_priority'])
    return {'mode': 'competitors' if alternatives_requested(plan) else 'entities', 'candidates': candidates,
            'references': references, 'entities': other, 'improvements': improvements, 'default_sort': 'relevance',
            'sorts': [{'id': 'relevance', 'label': 'Relevance to your goal'}, {'id': 'search_visibility', 'label': 'Observed search visibility'},
                      {'id': 'evidence', 'label': 'Amount of collected evidence'}, {'id': 'name', 'label': 'Name'}],
            'filters': {'classifications': _unique(card['classification'] for card in cards),
                        'pricing_statuses': _unique(card['pricing']['status'] for card in cards if card['pricing'])},
            'popularity': {'status': 'unknown', 'message': 'Overall popularity is unknown. Observed search visibility is available where saved search responses match an inspected host; unrelated platform counts are not combined.'},
            'scope': 'Only inspected entities are listed. Candidate classifications and geographic fit need review against the linked evidence. Bounded research cannot establish that every competitor has been found.'}
