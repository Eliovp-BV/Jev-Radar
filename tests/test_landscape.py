"""Projection contracts: saved evidence, host identity, and honest ranking."""
from copy import deepcopy

import pytest

from radar.landscape import landscape


def fixture():
    mission = {'id': 'mission', 'plan': {
        'goal': 'Find competitors for Tool A and compare public capabilities and pricing.',
        'reference': 'https://tool-a.example/product',
        'criteria': [{'id': 'capabilities', 'label': 'Capabilities', 'question': 'What capabilities are described?'},
                     {'id': 'pricing', 'label': 'Public pricing', 'question': 'What public pricing is published?'}]}}
    records = {'entity': [], 'source': [], 'span': [], 'finding': [], 'decision': [], 'search': [], 'metric': []}
    add_entity(records, 'a', 'tool-a.example', 'direct', role='reference_product', relevance=.85)
    add_entity(records, 'b', 'tool-b.example', 'direct', relevance=.9)
    add_entity(records, 'c', 'tool-c.example', 'alternative', relevance=.7)
    add_finding(records, 'a', 'capabilities', 'The reference supports local operation.')
    add_finding(records, 'b', 'capabilities', 'The candidate describes managed deployment.')
    add_finding(records, 'b', 'pricing', 'The candidate advertises €20 per month.')
    add_finding(records, 'c', 'capabilities', 'The candidate describes configurable workflows.', status='partly_supported')
    records['search'] = [
        {'id': 'search-1', 'query': 'tool alternatives', 'provider': 'brave', 'timestamp': '2026-09-19T10:00:00Z',
         'scope': 'Brave results', 'language': 'en', 'region_requested': 'BE', 'results': [
             {'id': 'result-b', 'url': 'https://www.tool-b.example/product', 'position': 2},
             {'id': 'result-b-2', 'url': 'https://tool-b.example/pricing', 'position': 4},
             {'id': 'result-c', 'url': 'https://tool-c.example/product', 'position': 5}]},
        {'id': 'search-2', 'query': 'tool alternatives', 'provider': 'brave', 'timestamp': '2026-09-19T11:00:00Z',
         'scope': 'Brave results', 'language': 'en', 'region_requested': 'BE', 'results': [
             {'id': 'result-c-2', 'url': 'https://tool-c.example/', 'position': 1}]}]
    return mission, records


def add_entity(records, key, host, classification, role='candidate', relevance=.8, entity_type='software_product'):
    records['decision'].append({'id': 'decision-' + key, 'answers': {}})
    records['source'].append({'id': 'source-' + key, 'url': 'https://' + host + '/', 'relevance': relevance,
                              'decision_id': 'decision-' + key, 'retrieved_at': '2026-09-19T09:00:00Z'})
    records['entity'].append({'id': key, 'name': host, 'domains': [host], 'classification': classification,
                              'classification_decision': 'decision-' + key, 'role': role, 'entity_type': entity_type,
                              'source_ids': ['source-' + key], 'fields': {}})


def add_finding(records, entity, criterion, text, status='supported'):
    key = entity + '-' + criterion
    records['span'].append({'id': 'span-' + key, 'source_id': 'source-' + entity, 'text': text})
    records['finding'].append({'id': 'finding-' + key, 'entity_id': entity, 'criterion_id': criterion,
                              'source_ids': ['source-' + entity], 'span_ids': ['span-' + key],
                              'decision_id': 'decision-' + entity, 'statement': text, 'status': status,
                              'retrieved_at': '2026-09-19T09:00:00Z', 'evidence_kind': 'company assertion'})


def test_cards_separate_reference_and_candidates_and_keep_exact_evidence():
    mission, records = fixture()
    before = deepcopy((mission, records))
    result = landscape(mission, records)
    assert result['mode'] == 'competitors'
    assert [card['id'] for card in result['references']] == ['a']
    assert [card['id'] for card in result['candidates']] == ['b', 'c']
    assert result['references'][0]['reference_basis'] == 'plan_reference'
    candidate = result['candidates'][0]
    assert candidate['capabilities']['values'][0] == {
        'finding_id': 'finding-b-capabilities', 'value': 'The candidate describes managed deployment.',
        'status': 'supported', 'source_ids': ['source-b'], 'span_ids': ['span-b-capabilities'],
        'decision_id': 'decision-b', 'evidence_kind': 'company assertion', 'retrieved_at': '2026-09-19T09:00:00Z',
        'scope': 'Only the cited passages were inspected; factual accuracy is not independently established.'}
    assert candidate['evidence_count'] == 2
    assert candidate['relevance']['score'] == .9
    assert candidate['relevance']['observations'] == [{'source_id': 'source-b', 'decision_id': 'decision-b', 'score': .9, 'url': 'https://tool-b.example/'}]
    assert (mission, records) == before


def test_visibility_is_exact_saved_observations_not_popularity():
    mission, records = fixture()
    records['metric'] = [{'id': 'huge-views', 'source_id': 'source-b', 'value': 900000000, 'metric': 'views'}]
    result = landscape(mission, records)
    b, c = result['candidates']
    assert b['search_visibility']['observation_count'] == 1
    assert len(b['search_visibility']['observations']) == 2
    assert c['search_visibility']['observation_count'] == 2
    assert c['search_visibility']['query_count'] == 1
    assert c['search_visibility']['best_position'] == 1
    assert b['search_visibility']['observations'][0] == {
        'search_id': 'search-1', 'result_id': 'result-b', 'query': 'tool alternatives',
        'timestamp': '2026-09-19T10:00:00Z', 'provider': 'brave', 'position': 2,
        'url': 'https://www.tool-b.example/product', 'scope': 'Brave results', 'language': 'en', 'region_requested': 'BE'}
    assert result['popularity']['status'] == 'unknown'
    assert 'popularity' not in b['sort_values']
    assert b['sort_values']['search_visibility'] == 1
    assert {sort['id'] for sort in result['sorts']} == {'relevance', 'name', 'search_visibility', 'evidence'}


def test_host_identity_does_not_merge_subdomains_suffixes_or_similar_hosts():
    mission, records = fixture()
    records['search'][0]['results'] = [
        {'id': 'subdomain', 'url': 'https://shop.tool-b.example/', 'position': 1},
        {'id': 'suffix', 'url': 'https://tool-b.example.unrelated.example/', 'position': 2},
        {'id': 'similar', 'url': 'https://another-tool-b.example/', 'position': 3},
        {'id': 'exact', 'url': 'https://www.TOOL-B.EXAMPLE/product', 'position': 4}]
    b = landscape(mission, records)['candidates'][0]
    assert [observation['result_id'] for observation in b['search_visibility']['observations']] == ['exact']


@pytest.mark.parametrize('record_type,flag', [('finding', 'stale'), ('finding', 'review'), ('source', 'stale'), ('source', 'review'), ('source', 'excluded'), ('entity', 'review')])
def test_rejected_and_stale_records_cannot_supply_current_claims(record_type, flag):
    mission, records = fixture()
    target_id = {'finding': 'finding-b-pricing', 'source': 'source-b', 'entity': 'b'}[record_type]
    target = next(record for record in records[record_type] if record['id'] == target_id)
    target[flag] = 'rejected' if flag == 'review' else True
    result = landscape(mission, records)
    if record_type in ('source', 'entity'):
        assert 'b' not in [card['id'] for card in result['candidates']]
    else:
        b = next(card for card in result['candidates'] if card['id'] == 'b')
        assert b['pricing']['status'] == 'unknown'
        assert b['pricing']['values'] == []
        assert 'finding-b-pricing' not in b['finding_ids']
        assert 'pricing' not in [improvement['criterion_id'] for improvement in result['improvements']]


def test_directory_editorial_unknown_and_background_are_not_competitors():
    mission, records = fixture()
    add_entity(records, 'directory', 'directory.example', 'direct', entity_type='directory')
    add_entity(records, 'editor', 'news.example', 'alternative', entity_type='editorial')
    add_entity(records, 'background', 'background.example', 'adjacent', role='background')
    add_entity(records, 'unknown', 'unknown.example', 'unknown', role='unknown')
    add_entity(records, 'adjacent', 'supplier.example', 'adjacent', entity_type='service_firm')
    result = landscape(mission, records)
    assert {card['id'] for card in result['candidates']} == {'b', 'c', 'adjacent'}
    assert {card['id'] for card in result['entities']} == {'directory', 'editor', 'background', 'unknown'}


def test_legacy_references_remain_visible_but_do_not_imply_own_product():
    mission, records = fixture()
    mission['plan']['reference'] = ''
    reference = records['entity'][0]
    reference.pop('role')
    reference.pop('entity_type')
    reference['classification'] = 'reference'
    result = landscape(mission, records)
    assert result['references'][0]['reference_basis'] == 'classification'
    assert result['improvements'] == []


def test_improvement_experiments_reference_exact_comparisons_and_unknowns():
    mission, records = fixture()
    result = landscape(mission, records)
    capability, pricing = result['improvements']
    assert capability['reference_ids'] == ['a']
    assert capability['candidate_ids'] == ['b', 'c']
    assert set(capability['finding_ids']) == {'finding-a-capabilities', 'finding-b-capabilities', 'finding-c-capabilities'}
    assert capability['kind'] == 'proposed experiment'
    assert pricing['finding_ids'] == ['finding-b-pricing']
    assert pricing['source_ids'] == ['source-b', 'source-a']
    assert pricing['decision_ids'] == ['decision-b']
    assert 'evidence gap, not proof' in pricing['observation']
    assert 'No current answer for reference: tool-a.example.' in pricing['unknowns']
    assert 'commercial impact have not been established' in pricing['unknowns'][-1]
    assert not any('superior' in opportunity['observation'] for opportunity in result['improvements'])


def test_generic_goal_has_entities_and_custom_questions_without_company_assumptions():
    mission, records = fixture()
    mission['plan'] = {'goal': 'Explain the implementation choices in a programming language.', 'criteria': [
        {'id': 'implementation', 'label': 'Implementation', 'question': 'What implementation choices are described?'}]}
    for entity in records['entity']:
        entity['classification'] = 'unknown'
        entity['role'] = 'unknown'
    add_finding(records, 'b', 'implementation', 'The project documents a bytecode interpreter.')
    result = landscape(mission, records)
    assert result['mode'] == 'entities'
    assert result['candidates'] == []
    b = next(card for card in result['entities'] if card['id'] == 'b')
    assert len(b['fields']) == 1
    assert b['fields'][0]['values'][0]['finding_id'] == 'finding-b-implementation'
    assert b['pricing'] is None and b['capabilities'] is None
    assert result['improvements'] == []


def test_no_evidence_does_not_create_unseen_entities_from_reference_or_search():
    mission, records = fixture()
    records['entity'] = []
    result = landscape(mission, records)
    assert result['candidates'] == result['references'] == result['entities'] == []
    assert result['improvements'] == []


def test_invalid_relevance_or_search_positions_do_not_become_rankings():
    mission, records = fixture()
    records['source'][1]['relevance'] = float('nan')
    records['source'][2]['decision_id'] = 'missing-decision'
    records['search'][0]['results'][0]['position'] = True
    records['search'][0]['results'][1]['position'] = -2
    result = landscape(mission, records)
    b = next(card for card in result['candidates'] if card['id'] == 'b')
    c = next(card for card in result['candidates'] if card['id'] == 'c')
    assert b['relevance']['score'] is None and c['relevance']['score'] is None
    assert b['search_visibility']['observations'] == []
    assert b['search_visibility']['best_position'] is None


def test_classification_from_rejected_page_cannot_survive_through_background_source():
    mission, records = fixture()
    b = records['entity'][1]
    b['classification_observations'] = [
        {'source_id': 'source-b', 'decision_id': 'decision-b', 'classification': 'direct', 'role': 'candidate', 'entity_type': 'software_product'},
        {'source_id': 'source-b-docs', 'decision_id': 'decision-docs', 'classification': 'reference', 'role': 'background', 'entity_type': 'editorial'}]
    records['source'][1]['review'] = 'rejected'
    records['source'].append({'id': 'source-b-docs', 'url': 'https://tool-b.example/docs', 'decision_id': 'decision-docs'})
    records['decision'].append({'id': 'decision-docs', 'source_id': 'source-b-docs'})
    b['source_ids'].append('source-b-docs')
    result = landscape(mission, records)
    assert 'b' not in [candidate['id'] for candidate in result['candidates']]
    retained = next(entity for entity in result['entities'] if entity['id'] == 'b')
    assert retained['classification'] == 'unknown'
    assert retained['source_ids'] == ['source-b-docs']
    assert len(retained['classification_observations']) == 1
    assert retained['evidence_count'] == 0


def test_legacy_classification_with_removed_decision_source_is_unknown():
    mission, records = fixture()
    records['decision'][1]['source_id'] = 'removed-source'
    result = landscape(mission, records)
    assert 'b' not in [candidate['id'] for candidate in result['candidates']]
    assert next(entity for entity in result['entities'] if entity['id'] == 'b')['classification'] == 'unknown'


def test_only_actual_current_matching_jev_priority_is_exposed():
    mission, records = fixture()
    mission['plan_version'] = 3
    original = landscape(mission, records)['improvements']
    selected = original[1]['id']
    records['decision'].append({'id': 'priority-decision', 'status': 'complete',
                                'answers': {'priority': {'choice': selected}}, 'latency_ms': 750})
    records['opportunity_priority'] = [{'id': 'priority', 'rubric_version': 3, 'selected': selected,
                                        'decision_id': 'priority-decision', 'suggestions': original}]
    result = landscape(mission, records)
    assert result['improvements'][0]['id'] == selected
    assert result['improvements'][0]['jev_priority'] is True
    assert result['improvements'][0]['decision_id'] == 'priority-decision'
    assert result['improvements'][1]['jev_priority'] is False
    # New evidence invalidates this projection's priority even if the saved plan
    # version and stable comparison ID have not changed.
    add_finding(records, 'a', 'pricing', 'Reference pricing is now published.')
    changed = landscape(mission, records)
    assert not any(item['jev_priority'] for item in changed['improvements'])


@pytest.mark.parametrize('change', ['old_version', 'failed_decision', 'missing_decision', 'mismatched_answer'])
def test_priority_snapshot_requires_a_current_successful_decision(change):
    mission, records = fixture()
    mission['plan_version'] = 2
    suggestions = landscape(mission, records)['improvements']
    selected = suggestions[0]['id']
    decision = {'id': 'priority-decision', 'status': 'complete', 'answers': {'priority': {'choice': selected}}}
    priority = {'id': 'priority', 'rubric_version': 2, 'selected': selected, 'decision_id': decision['id'], 'suggestions': suggestions}
    if change == 'old_version':
        priority['rubric_version'] = 1
    elif change == 'failed_decision':
        decision['status'] = 'error'
    elif change == 'missing_decision':
        priority['decision_id'] = 'unknown'
    else:
        decision['answers']['priority']['choice'] = 'none'
    records['decision'].append(decision)
    records['opportunity_priority'] = [priority]
    assert not any(item['jev_priority'] for item in landscape(mission, records)['improvements'])


def test_visibility_sort_does_not_reward_repeating_queries_or_providers():
    mission, records = fixture()
    repeated = deepcopy(records['search'][0])
    repeated['id'] = 'repeated-search'
    repeated['provider'] = 'another-provider'
    records['search'].append(repeated)
    b = landscape(mission, records)['candidates'][0]
    assert b['search_visibility']['observation_count'] == 2
    assert b['search_visibility']['provider_query_count'] == 2
    assert b['search_visibility']['query_count'] == 1
    assert b['sort_values']['search_visibility'] == 1


def test_relevance_preserves_actual_jev_rubric_score_above_one():
    mission, records = fixture()
    records['source'][2]['relevance'] = 1.93
    records['decision'][2]['questions'] = {'relevance': {'type': 'score', 'criteria': ['Unrelated', 'Context', 'Direct evidence']}}
    result = landscape(mission, records)
    assert result['candidates'][0]['id'] == 'c'
    assert result['candidates'][0]['relevance']['score'] == 1.93
    assert result['candidates'][0]['relevance']['observations'][0]['score'] == 1.93
    assert result['candidates'][0]['sort_values']['relevance'] == 1.93
    records['source'][2]['relevance'] = 2.5
    assert next(card for card in landscape(mission, records)['candidates'] if card['id'] == 'c')['relevance']['score'] is None


def test_legacy_relevance_records_use_the_saved_source_rubric_range():
    mission, records = fixture()
    records['source'][1]['relevance'] = 2
    b = landscape(mission, records)['candidates'][0]
    assert b['id'] == 'b' and b['relevance']['score'] == 2


@pytest.mark.parametrize('exclusion', ['domain', 'entity'])
def test_plan_excluded_domains_and_entities_are_absent_from_cards_and_experiments(exclusion):
    mission, records = fixture()
    if exclusion == 'domain':
        mission['plan']['excluded_domains'] = ['tool-b.example']
    else:
        mission['plan']['excluded_entities'] = ['TOOL-B.EXAMPLE']
    result = landscape(mission, records)
    assert [card['id'] for card in result['candidates']] == ['c']
    assert all('b' not in opportunity['candidate_ids'] for opportunity in result['improvements'])
    assert all('source-b' not in opportunity['source_ids'] for opportunity in result['improvements'])
    assert all('pricing' != opportunity['criterion_id'] for opportunity in result['improvements'])


def test_improvement_comparison_excerpts_are_current_linked_and_bounded():
    mission, records = fixture()
    for i in range(4):
        key = f'extra-{i}'
        add_entity(records, key, f'{key}.example', 'alternative')
        add_finding(records, key, 'capabilities', 'Advertised workflow capability. ' * 20)
    records['finding'][3]['stale'] = True  # Candidate c cannot supply an excerpt.
    records['finding'][2]['review'] = 'rejected'  # Rejected candidate pricing is absent.
    result = landscape(mission, records)
    capability = next(item for item in result['improvements'] if item['criterion_id'] == 'capabilities')
    excerpts = capability['comparison_evidence']
    assert excerpts[0] == {'side': 'reference', 'entity_id': 'a', 'name': 'tool-a.example',
                           'finding_id': 'finding-a-capabilities', 'value': 'The reference supports local operation.', 'status': 'supported'}
    assert sum(entry['side'] == 'candidate' for entry in excerpts) == 3
    assert all(len(entry['value']) <= 240 for entry in excerpts)
    assert any(len(entry['value']) == 240 for entry in excerpts)
    assert all(entry['entity_id'] != 'c' for entry in excerpts)
    assert all(entry['finding_id'] in capability['finding_ids'] for entry in excerpts)
    assert all(item['criterion_id'] != 'pricing' for item in result['improvements'])


def test_improvement_reference_comparison_is_limited_to_two_current_excerpts():
    mission, records = fixture()
    for i in range(3):
        key = f'reference-{i}'
        add_entity(records, key, f'{key}.example', 'reference', role='reference_product')
        add_finding(records, key, 'capabilities', 'Another identified reference describes its workflow.')
    capability = landscape(mission, records)['improvements'][0]
    assert sum(entry['side'] == 'reference' for entry in capability['comparison_evidence']) == 2
