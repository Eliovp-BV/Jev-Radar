"""Artifact inference contracts using explicitly labeled fixtures, never paid calls."""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from radar.artifact_research import FEATURES, analyze_artifact, compare_artifacts, eligible_artifacts
from radar.jev import DecisionError
from radar.schemas import Criterion, Plan
from radar.storage import Store, dumps, fingerprint, now, uid
from radar.video import source_from_result


class FixtureJev:
    """Return valid choices from the supplied candidate set and record the request."""
    def __init__(self, store, *, role='primary_artifact', features=None, evidence=True,
                 span_answers=None, verification='supported', comparison='observed'):
        self.store = store
        self.calls = []
        self.role = role
        self.features = features or {'title_hook': 'promise'}
        self.evidence = evidence
        self.span_answers = span_answers or {}
        self.verification = verification
        self.comparison = comparison

    async def ask(self, mid, state, questions, purpose, source_id=None, cache=True):
        content = {'state': state, 'questions': {key: question.model_dump(mode='json', exclude_none=True) for key, question in questions.items()},
                   'model': 'explicit-test-fixture', 'rubric_version': self.store.mission(mid)['plan_version']}
        assert len(dumps(content).encode()) <= 50000, 'Fixture request would exceed the real Jev payload limit'
        self.calls.append({'state': deepcopy(state), 'questions': questions, 'purpose': purpose})
        answers = {}
        for key, question in questions.items():
            if question.type == 'score':
                answers[key] = {'type': 'score', 'score': 2, 'confidence': 1,
                                'probabilities': {str(i): float(i == 2) for i in range(len(question.criteria))}}
                continue
            if key == 'source_role':
                choice = self.role
            elif key.startswith('span_'):
                choice = self.span_answers.get(key[5:], 'unknown')
            elif key in FEATURES:
                choice = self.features.get(key, 'unknown')
            elif key.endswith('_evidence'):
                choice = state['untrusted_passages'][0]['id'] if self.evidence else 'unknown'
            elif purpose == 'Verify selected evidence against each question':
                choice = self.verification
            elif key == 'next_test':
                choice = 'matched'
            else:
                choice = self.comparison
            assert choice in question.criteria, (key, choice)
            answers[key] = {'type': 'choice', 'choice': choice, 'confidence': 1,
                            'probabilities': {candidate: float(candidate == choice) for candidate in question.criteria}}
        decision = {'id': uid(), 'purpose': purpose, 'status': 'complete', 'model': 'explicit-test-fixture',
                    'mode': 'fixture', 'source_id': source_id, 'answers': answers, 'state': deepcopy(state),
                    'questions': {key: question.model_dump(mode='json') for key, question in questions.items()},
                    'created_at': now(), 'cache': False, 'latency_ms': 0}
        self.store.mutate(mid, 'fixture.decision', {'decision_id': decision['id']}, [('decision', decision)], mode='fixture')
        return decision


def setup_artifacts(tmp_path, unit='videos', **jev_options):
    store = Store(tmp_path / 'artifact-fixtures.sqlite')
    criteria = [Criterion(id=key, label=label, question=question).model_dump() for key, label, question in [
        ('artifact', 'Original artifact', 'Which original artifact was inspected?'),
        ('content_features', 'Content', 'What can be observed in the original content?'),
        ('mechanism', 'Explanation', 'What measured evidence establishes a causal explanation?'),
    ]]
    plan = Plan(goal='Fixture research: compare original artifacts and test possible explanations', criteria=criteria).model_dump()
    mid = uid()
    store.execute('INSERT INTO missions VALUES(?,?,?,?,?,?,?,?,?)',
                  (mid, plan['goal'], 'running', dumps(plan), 1, now(), now(), None, 'fixture'))
    program = {'id': uid(), 'unit': unit, 'method': 'explain_patterns', 'objective': plan['goal'],
               'plan_version': 1, 'evidence_requirements': ['Inspect the actual original artifacts'],
               'stop_conditions': ['Leave unavailable evidence unknown']}
    store.mutate(mid, 'fixture.program', {}, [('research_program', program)], mode='fixture')
    runner = SimpleNamespace(store=store, jev=FixtureJev(store, **jev_options))
    return runner, mid, plan, program


def video_source(store, mid, video_id='fixture001', *, views=None, url=None, title='Fixture: build an example'):
    result = {'id': uid(), 'position': 1, 'url': url or 'https://www.youtube.com/watch?v='+video_id,
              'title': title, 'snippet': 'Explicit fixture description of an instructional example.',
              'video': {'creator': 'Fixture creator', 'views': views}}
    observation = {'id': uid(), 'timestamp': '2026-01-01T10:00:00+00:00', 'provider': 'brave',
                   'query': 'isolated fixture', 'language': 'en', 'latency_ms': 0}
    source = source_from_result(result, observation, {'id': uid(), 'depth': 0})
    source['mode'] = 'fixture'
    for index, chunk in enumerate(source['chunks']):
        chunk['id'] = 'c'+str(index)
    store.mutate(mid, 'source.extracted', {'source_id': source['id']}, [('source', source)], mode='fixture')
    return source


def blog_source(store, mid):
    text = 'Fixture article discussing viral videos; no individual video was acquired.'
    source = {'id': uid(), 'url': 'https://example.org/fixture-blog', 'title': 'Fixture secondary blog',
              'text': text, 'chunks': [{'id': 'c0', 'text': text, 'start': 0, 'end': len(text)}],
              'retrieved_at': now(), 'source_date': None, 'coverage': {}, 'content_hash': fingerprint(text),
              'mode': 'fixture'}
    store.mutate(mid, 'source.extracted', {'source_id': source['id']}, [('source', source)], mode='fixture')
    return source


async def assess(runner, mid, source, plan, program):
    await analyze_artifact(runner, mid, source, source['chunks'], plan, program)


async def test_individual_videos_on_same_host_have_distinct_entities_and_aliases_deduplicate(tmp_path):
    runner, mid, plan, program = setup_artifacts(tmp_path)
    first = video_source(runner.store, mid, 'fixture001')
    second = video_source(runner.store, mid, 'fixture002')
    alias = video_source(runner.store, mid, url='https://youtu.be/fixture001')
    for source in (first, second, alias):
        await assess(runner, mid, source, plan, program)
    entities = runner.store.records(mid, 'entity')
    assert len(entities) == 2
    assert sorted(len(item['source_ids']) for item in entities) == [1, 2]
    assert len(eligible_artifacts(runner.store, mid, program)) == 2


@pytest.mark.parametrize('role', ['primary_artifact', 'secondary_commentary', 'original_measurement'])
async def test_secondary_page_never_counts_as_an_inspected_video(tmp_path, role):
    runner, mid, plan, program = setup_artifacts(tmp_path, role=role)
    source = blog_source(runner.store, mid)
    await assess(runner, mid, source, plan, program)
    assert not eligible_artifacts(runner.store, mid, program)
    analysis = await compare_artifacts(runner, mid, plan, program)
    assert analysis['artifact_count'] == 0 and analysis['decision_id'] is None
    assert not any(call['purpose'] == 'Compare observed artifacts' for call in runner.jev.calls)


async def test_missing_transcript_and_unsupported_features_stay_unknown(tmp_path):
    runner, mid, plan, program = setup_artifacts(tmp_path, evidence=False)
    source = video_source(runner.store, mid, views=None)
    await assess(runner, mid, source, plan, program)
    assessment = runner.store.records(mid, 'artifact_analysis')[0]
    assert source['video_metadata']['transcript'] is None
    assert source['video_metadata']['transcript_available'] is False
    assert source['video_metadata']['views'] is None
    assert source['video_metadata']['frames_available'] is False
    assert assessment['evidence_basis'] == 'indexed video metadata only'
    assert all(feature['choice'] == 'unknown' and not feature['span_ids'] for feature in assessment['features'].values())
    assert not runner.store.records(mid, 'finding')
    assert not runner.store.records(mid, 'metric')
    assert 'No video frames or audio were inspected' in runner.jev.calls[0]['state']['instructions_scope']


async def test_exact_selected_spans_are_verified_and_replay_links_are_complete(tmp_path):
    runner, mid, plan, program = setup_artifacts(tmp_path, span_answers={'artifact': 'c0', 'content_features': 'c1'}, verification='partly_supported')
    source = video_source(runner.store, mid, views=73)
    await assess(runner, mid, source, plan, program)
    saved_sources = {item['id']: item for item in runner.store.records(mid, 'source')}
    saved_spans = {item['id']: item for item in runner.store.records(mid, 'span')}
    assert len(saved_spans) == 3  # title is shared; creator supplements the identity record
    for span in saved_spans.values():
        assert saved_sources[span['source_id']]['text'][span['start']:span['end']] == span['text']
    findings = runner.store.records(mid, 'finding')
    assert {item['criterion_id'] for item in findings} == {'artifact', 'content_features'}
    assert all(item['status'] == 'partly_supported' for item in findings)
    assert all(item['scope'] == 'Search-provider video metadata; footage and audio not inspected' for item in findings if item['evidence_kind'] != 'verified text feature')
    assert all(item['span_ids'][0] in saved_spans for item in findings)
    verification = next(call for call in runner.jev.calls if call['purpose'].startswith('Verify selected'))
    assert verification['state']['propositions']['artifact']['span']['text'] == source['chunks'][0]['text']
    classification = runner.jev.calls[0]
    assert 'title_hook' in classification['questions']
    assert not any(key.endswith('_evidence') for key in classification['questions'])
    # Evidence selection depends on the classification Jev actually returned;
    # independent answers in the first request cannot see one another.
    assert verification['state']['feature_proposals']['title_hook']['choice'] == 'promise'
    assert verification['state']['feature_proposals']['title_hook']['description'] == FEATURES['title_hook'][1]['promise']
    assert FEATURES['title_hook'][1]['promise'] in verification['questions']['title_hook_evidence'].instructions
    assert verification['state']['untrusted_passages'] == source['chunks']
    assert 'title_hook_evidence' in verification['questions']
    assert 'content_format_evidence' not in verification['questions']  # unknown classifications cannot become verified features
    assessment = runner.store.records(mid, 'artifact_analysis')[0]
    verification_record = next(decision for decision in runner.store.records(mid, 'decision') if decision['purpose'].startswith('Verify selected'))
    assert assessment['verification_decision_id'] == verification_record['id']
    assert assessment['features']['title_hook']['decision_id'] == verification_record['id']
    event = runner.store.events(mid)[-1]
    assert event['type'] == 'assessment.recorded' and event['mode'] == 'fixture'
    replay_records = {change['record']['id']: change['kind'] for change in event['payload']['record_changes']}
    assert all(replay_records[span_id] == 'span' for item in findings for span_id in item['span_ids'])
    assert not runner.store.records(mid, 'metric')  # no proxy conversion of indexed views into owned analytics


async def test_invalid_passage_offsets_cannot_be_saved_as_evidence(tmp_path):
    runner, mid, plan, program = setup_artifacts(tmp_path, span_answers={'artifact': 'c0'})
    source = video_source(runner.store, mid)
    source['chunks'][0]['start'] += 1
    with pytest.raises(DecisionError, match='offset integrity'):
        await assess(runner, mid, source, plan, program)
    assert not runner.store.records(mid, 'finding')
    assert not runner.store.records(mid, 'span')
    assert not runner.store.records(mid, 'artifact_analysis')


async def test_comparison_requires_two_distinct_eligible_objects_and_reuses_a_saved_result(tmp_path):
    runner, mid, plan, program = setup_artifacts(tmp_path)
    first = video_source(runner.store, mid, 'fixture001')
    await assess(runner, mid, first, plan, program)
    unavailable = await compare_artifacts(runner, mid, plan, program)
    assert unavailable['artifact_count'] == 1 and unavailable['decision_id'] is None
    assert not unavailable['patterns']
    assert await compare_artifacts(runner, mid, plan, program) == unavailable
    second = video_source(runner.store, mid, 'fixture002')
    await assess(runner, mid, second, plan, program)
    result = await compare_artifacts(runner, mid, plan, program)
    assert result['artifact_count'] == 2 and result['decision_id']
    assert result['patterns'][0]['status'] == 'observed'
    assert len(result['patterns'][0]['source_ids']) == 2
    assert 'causal' in result['patterns'][0]['limitations'][0]
    calls = len(runner.jev.calls)
    assert await compare_artifacts(runner, mid, plan, program) == result
    assert len(runner.jev.calls) == calls
    compare_call = next(call for call in runner.jev.calls if call['purpose'] == 'Compare observed artifacts')
    assert all(item['observed_views'] is None for item in compare_call['state']['artifacts'])
    assert len({item['source_id'] for item in compare_call['state']['artifacts']}) == 2


async def test_one_matching_feature_cannot_become_an_observed_recurring_pattern(tmp_path):
    runner, mid, plan, program = setup_artifacts(tmp_path)
    first = video_source(runner.store, mid, 'fixture001')
    await assess(runner, mid, first, plan, program)
    runner.jev.features = {'title_hook': 'question'}
    second = video_source(runner.store, mid, 'fixture002', title='Fixture: what is an example?')
    await assess(runner, mid, second, plan, program)
    result = await compare_artifacts(runner, mid, plan, program)
    assert len(result['patterns']) == 2
    assert all(item['status'] == 'possible' for item in result['patterns'])
    assert all(item['model_status'] == 'observed' for item in result['patterns'])
    assert all('application retains' in item['rationale'] for item in result['patterns'])
    assert all(len(item['source_ids']) == len(item['comparison_source_ids']) == 1 for item in result['patterns'])
    assert all('1 of 2' in item['observation'] for item in result['patterns'])


async def test_excluded_or_wrong_version_artifacts_cannot_complete_a_comparison(tmp_path):
    runner, mid, plan, program = setup_artifacts(tmp_path)
    first = video_source(runner.store, mid, 'fixture001')
    second = video_source(runner.store, mid, 'fixture002')
    await assess(runner, mid, first, plan, program)
    await assess(runner, mid, second, plan, program)
    second['excluded'] = True
    runner.store.mutate(mid, 'fixture.exclude', {}, [('source', second)], mode='fixture')
    assert len(eligible_artifacts(runner.store, mid, program)) == 1
    result = await compare_artifacts(runner, mid, plan, program)
    assert result['artifact_count'] == 1 and result['decision_id'] is None
    runner.store.execute('UPDATE missions SET plan_version=2 WHERE id=?', (mid,))
    assert eligible_artifacts(runner.store, mid, program) == []


async def test_general_comparison_recomputes_after_supporting_findings_are_rejected(tmp_path):
    runner, mid, plan, program = setup_artifacts(tmp_path, unit='articles', span_answers={'artifact': 'c0'})
    for index in range(2):
        source = blog_source(runner.store, mid)
        source['url'] += str(index)
        await assess(runner, mid, source, plan, program)
    first = await compare_artifacts(runner, mid, plan, program)
    assert first['decision_id'] and first['patterns']
    for finding in runner.store.records(mid, 'finding'):
        finding['review'] = 'rejected'
        runner.store.mutate(mid, 'fixture.reject', {}, [('finding', finding)], mode='fixture')
    second = await compare_artifacts(runner, mid, plan, program)
    assert second['id'] != first['id']
    assert not second['patterns'] and second['decision_id'] is None


@pytest.mark.parametrize('unit', ['technical_artifacts', 'articles', 'videos'])
async def test_comparison_limitations_match_the_research_subject(tmp_path, unit):
    runner, mid, plan, program = setup_artifacts(tmp_path, unit=unit, span_answers={'artifact': 'c0'})
    for index in range(2):
        if unit == 'videos':
            source = video_source(runner.store, mid, 'fixture'+str(index).zfill(3))
        else:
            source = blog_source(runner.store, mid)
            source['url'] += str(index)
        await assess(runner, mid, source, plan, program)

    comparison = await compare_artifacts(runner, mid, plan, program)
    assert comparison['decision_id'] and comparison['patterns']
    assert comparison['artifact_count'] == 2
    for pattern in comparison['patterns']:
        limitations = ' '.join(pattern['limitations']).lower()
        assert 'bounded observational sample' in limitations and 'causal mechanism' in limitations
        if unit == 'videos':
            assert 'virality' in limitations and 'audience' in limitations
        else:
            assert 'comparability' in limitations and 'available evidence' in limitations
            assert all(word not in limitations for word in ('virality', 'video', 'audience', 'publication age'))
        assert len(pattern['source_ids']) == 2 and pattern['span_ids']
    saved = runner.store.records(mid, 'research_analysis')[-1]
    assert saved['patterns'] == comparison['patterns']


async def test_latest_assessment_cannot_fall_back_to_an_obsolete_primary_role(tmp_path):
    runner, mid, plan, program = setup_artifacts(tmp_path)
    source = video_source(runner.store, mid)
    await assess(runner, mid, source, plan, program)
    assert len(eligible_artifacts(runner.store, mid, program)) == 1
    runner.jev.role = 'secondary_commentary'
    await assess(runner, mid, source, plan, program)
    assert not eligible_artifacts(runner.store, mid, program)


async def test_publisher_metadata_without_transcript_is_not_mislabeled_as_search_index_content(tmp_path):
    runner, mid, plan, program = setup_artifacts(tmp_path)
    source = video_source(runner.store, mid)
    source['video_metadata']['acquisition'] = 'publisher_structured_metadata'
    source['video_metadata']['provenance'] = 'Explicit fixture publisher metadata from fetched page'
    await assess(runner, mid, source, plan, program)
    assessment = runner.store.records(mid, 'artifact_analysis')[0]
    assert assessment['evidence_basis'] != 'indexed video metadata only'
    assert 'publisher' in assessment['evidence_basis'] or 'retrieved' in assessment['evidence_basis']
    assert source['video_metadata']['transcript_available'] is False


async def test_bounded_comparison_only_claims_recurrence_in_artifacts_jev_received(tmp_path):
    runner, mid, plan, program = setup_artifacts(tmp_path)
    for index in range(13):
        source = video_source(runner.store, mid, 'fixture'+str(index).zfill(3))
        await assess(runner, mid, source, plan, program)
    result = await compare_artifacts(runner, mid, plan, program)
    call = next(call for call in runner.jev.calls if call['purpose'] == 'Compare observed artifacts')
    seen_source_ids = {source['source_id'] for source in call['state']['artifacts']}
    seen_span_ids = {span['id'] for span in call['state']['evidence']}
    assert len(seen_source_ids) == result['artifact_count'] == 12
    assert result['total_artifact_count'] == 13
    assert all(set(pattern['source_ids']) <= seen_source_ids for pattern in result['patterns'])
    assert all(set(pattern['span_ids']) <= seen_span_ids for pattern in result['patterns'])
    assert all('12 of 12' in pattern['observation'] for pattern in result['patterns'])
    assert runner.store.one('SELECT COUNT(*) AS count FROM reservations')['count'] == 0


async def test_two_objects_without_comparable_features_do_not_trigger_a_claimed_comparison(tmp_path):
    runner, mid, plan, program = setup_artifacts(tmp_path, evidence=False)
    for video_id in ('fixture001', 'fixture002'):
        source = video_source(runner.store, mid, video_id)
        await assess(runner, mid, source, plan, program)
    calls = len(runner.jev.calls)
    result = await compare_artifacts(runner, mid, plan, program)
    assert result['artifact_count'] == 2
    assert result['decision_id'] is None and not result['patterns']
    assert len(runner.jev.calls) == calls
    assert 'Unknown evidence was not converted' in result['limitations'][0]


async def test_long_multibyte_evidence_is_bounded_without_rewriting_passages(tmp_path):
    runner, mid, plan, program = setup_artifacts(tmp_path, span_answers={'artifact': 'c0'})
    plan['goal'] = '明确的测试研究目标：比较原始证据。' * 70
    plan['criteria'] = [Criterion(id='artifact' if index == 0 else 'criterion_'+str(index), label='Fixture '+str(index),
                                 question='比较原始证据中的具体观察。' * 25, rubric='仅使用观察到的来源，缺失信息保持未知。' * 25).model_dump() for index in range(8)]
    source = video_source(runner.store, mid)
    source['chunks'] = []
    source['text'] = ''
    for index in range(24):
        text = '明确的测试来源。' * 80
        start = len(source['text'])
        source['text'] += text+'\n'
        source['chunks'].append({'id': 'c'+str(index), 'start': start, 'end': start+len(text), 'text': text})
    original = source['text']
    await assess(runner, mid, source, plan, program)
    first = runner.jev.calls[0]
    selected = first['state']['untrusted_passages']
    assert 0 < len(selected) < 24
    assert source['text'] == original
    assert source['coverage']['analyzed_chunks'] == len(selected)
    assert source['coverage']['decision_chunks_omitted'] == 24-len(selected)
    assert set(first['questions']['span_artifact'].criteria) == {chunk['id'] for chunk in selected} | {'unknown', 'not_applicable'}
    for span in runner.store.records(mid, 'span'):
        assert original[span['start']:span['end']] == span['text']


async def test_large_comparison_shrinks_its_sample_and_preserves_every_cited_passage(tmp_path):
    runner, mid, plan, program = setup_artifacts(tmp_path)
    # Large saved search queries must not be duplicated into a comparison request.
    program['search_queries'] = ['未发送到比较模型的长查询。' * 150] * 20
    for index in range(12):
        source = video_source(runner.store, mid, 'fixture'+str(index).zfill(3), title='例'*998+str(index))
        source['video_metadata']['creator'] = '创作者'*250
        await assess(runner, mid, source, plan, program)
    result = await compare_artifacts(runner, mid, plan, program)
    call = next(call for call in runner.jev.calls if call['purpose'] == 'Compare observed artifacts')
    assert 2 <= result['artifact_count'] < result['total_artifact_count'] == 12
    assert 'search_queries' not in call['state']['program']
    assert len(call['state']['artifacts']) == result['artifact_count']
    assert call['state']['sample']['eligible_artifacts'] == 12
    evidence = {span['id']: span for span in call['state']['evidence']}
    assert all(set(pattern['span_ids']) <= set(evidence) for pattern in result['patterns'])
    assert all(f"of {result['artifact_count']}" in pattern['observation'] for pattern in result['patterns'])
    assert any('bounded request payload' in limitation for limitation in result['limitations'])


async def test_reassessing_an_older_snapshot_cannot_replace_a_newer_observation(tmp_path):
    runner, mid, plan, program = setup_artifacts(tmp_path)
    old = video_source(runner.store, mid)
    old['retrieved_at'] = '2026-01-01T10:00:00+00:00'
    await assess(runner, mid, old, plan, program)
    new = video_source(runner.store, mid)
    new['retrieved_at'] = '2026-01-01T11:00:00+00:00'
    await assess(runner, mid, new, plan, program)
    runner.jev.role = 'secondary_commentary'
    await assess(runner, mid, old, plan, program)
    eligible = eligible_artifacts(runner.store, mid, program)
    assert len(eligible) == 1 and eligible[0][0]['id'] == new['id']
    assert eligible[0][1]['role'] == 'primary_artifact'


async def test_video_advice_is_context_when_jev_identifies_it_as_secondary(tmp_path):
    runner, mid, plan, program = setup_artifacts(tmp_path, role='secondary_commentary')
    source = video_source(runner.store, mid, title='Explicit fixture: how to make a viral video')
    await assess(runner, mid, source, plan, program)
    choices = runner.jev.calls[0]['questions']['source_role']
    assert 'actual population requested by the user' in choices.criteria['primary_artifact']
    assert 'regardless of media format' in choices.instructions
    assert source['research_role'] == 'secondary_commentary'
    assert not eligible_artifacts(runner.store, mid, program)


@pytest.mark.parametrize('selection', ['anchor', 'bundle'])
async def test_video_metadata_questions_verify_complete_exact_record_context(tmp_path, selection):
    runner, mid, plan, program = setup_artifacts(tmp_path, verification='partly_supported', features={'title_hook': 'unknown'})
    plan['criteria'].append(Criterion(id='observed_traction', label='Observed traction',
                                     question='Which attributable counter observation exists for which video and date?').model_dump())
    source = video_source(runner.store, mid, views=73)
    published = '2025-02-03'
    source['video_metadata'].update(published_at=published)
    start = len(source['text']) + 1
    source['text'] += '\n' + published
    source['chunks'].append({'id': 'c4', 'start': start, 'end': start+len(published), 'text': published,
                             'field': 'published_at', 'provenance': 'Explicit fixture provider; results[].page_age'})
    runner.jev.span_answers = {'artifact': 'c4' if selection == 'anchor' else 'video_identity_record',
                               'observed_traction': 'c3' if selection == 'anchor' else 'video_counter_record'}
    await assess(runner, mid, source, plan, program)
    verify = runner.jev.calls[-1]
    assert verify['purpose'] == 'Verify selected evidence against each question'
    assert verify['state']['source_context']['retrieved_at'] == source['retrieved_at']
    assert 'not an upload date' in verify['state']['source_context']['time_scope']
    for cid, fields in [('artifact', {'title', 'creator', 'published_at'}),
                        ('observed_traction', {'title', 'creator', 'published_at', 'views'})]:
        offered = verify['state']['propositions'][cid]['spans']
        assert {span['field'] for span in offered} == fields
        assert all(source['text'][span['start']:span['end']] == span['text'] for span in offered)
        assert all(span['provenance'] for span in offered)
        finding = next(f for f in runner.store.records(mid, 'finding') if f['criterion_id'] == cid)
        assert finding['status'] == 'partly_supported'
        assert finding['span_ids'] == [span['id'] for span in offered]
        assert finding['decision_id'] == runner.store.records(mid, 'decision')[-1]['id']
    assert 'video_counter_record' in runner.jev.calls[0]['questions']['span_observed_traction'].criteria
    assert not runner.store.records(mid, 'metric')


async def test_counter_context_is_offered_even_when_term_selection_omits_short_fields(tmp_path):
    runner, mid, plan, program = setup_artifacts(tmp_path, features={'title_hook': 'unknown'},
                                               span_answers={'artifact': 'video_identity_record'})
    source = video_source(runner.store, mid, views=73)
    await analyze_artifact(runner, mid, source, source['chunks'][:2], plan, program)
    offered = runner.jev.calls[0]['state']['untrusted_passages']
    assert {'title', 'creator', 'views'} <= {chunk.get('field') for chunk in offered}
    assert all(source['text'][chunk['start']:chunk['end']] == chunk['text'] for chunk in offered)


async def test_metadata_bundle_still_requires_actual_jev_support(tmp_path):
    runner, mid, plan, program = setup_artifacts(tmp_path, span_answers={'artifact': 'video_identity_record'},
                                               features={'title_hook': 'unknown'}, verification='unknown')
    source = video_source(runner.store, mid, views=73)
    await assess(runner, mid, source, plan, program)
    findings = runner.store.records(mid, 'finding')
    assert len(findings) == 1 and findings[0]['status'] == 'unknown'
    assert len(findings[0]['span_ids']) == 2
    assert len(runner.jev.calls) == 2


@pytest.mark.parametrize('status', ['supported', 'partly_supported', 'unknown', 'contradicted'])
async def test_feature_findings_require_literal_evidence_and_jev_support(tmp_path, status):
    runner, mid, plan, program = setup_artifacts(tmp_path, verification=status)
    source = video_source(runner.store, mid)
    await assess(runner, mid, source, plan, program)
    finding = runner.store.records(mid, 'finding')
    verify = runner.jev.calls[-1]
    assert 'title_hook_support' in verify['questions']
    if status in ('supported', 'partly_supported'):
        assert len(finding) == 1
        assert finding[0]['criterion_id'] == 'content_features'
        assert finding[0]['status'] == 'partly_supported'  # does not complete the broad content question
        assert finding[0]['feature_verification_status'] == status
        assert finding[0]['evidence_kind'] == 'verified text feature'
        assert 'footage and audio were not inspected' in finding[0]['scope']
        assert finding[0]['decision_id'] == runner.store.records(mid, 'decision')[-1]['id']
    else:
        assert not finding
        assert runner.store.records(mid, 'artifact_analysis')[-1]['features']['title_hook']['choice'] == 'unknown'
