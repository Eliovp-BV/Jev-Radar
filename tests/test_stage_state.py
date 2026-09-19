"""Pure visual-state checks with synthetic records, local TypeScript and Node only."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def derive(tmp_path_factory):
    node = shutil.which('node')
    compiler = ROOT / 'frontend/node_modules/.bin/tsc'
    if not node or not compiler.exists():
        pytest.skip('Install the existing frontend dependencies to check visual-state TypeScript')
    output = tmp_path_factory.mktemp('stage-state-js')
    built = subprocess.run([str(compiler), '--outDir', str(output), '--target', 'ES2022', '--module', 'ESNext',
                            '--moduleResolution', 'bundler', '--skipLibCheck', '--strict',
                            str(ROOT / 'frontend/src/jev-stage-state.ts')], capture_output=True, text=True)
    assert built.returncode == 0, built.stdout + built.stderr
    module = output / 'jev-stage-state.mjs'
    (output / 'jev-stage-state.js').rename(module)
    program = 'import(process.argv[1]).then(({deriveStageState})=>{let input="";process.stdin.on("data",c=>input+=c);process.stdin.on("end",()=>{const x=JSON.parse(input);const before=JSON.stringify(x);const result=deriveStageState(x.mission,x.replay);if(before!==JSON.stringify(x))throw Error("Input mutated");process.stdout.write(JSON.stringify(result))});});'

    def run(mission, replay=False):
        completed = subprocess.run([node, '-e', program, module.as_uri()],
                                   input=json.dumps({'mission': mission, 'replay': replay}),
                                   text=True, capture_output=True, check=True)
        return json.loads(completed.stdout)
    return run


def mission(status='running'):
    return {'id': 'fixture', 'goal': 'Inspect public research evidence', 'status': status, 'plan': {},
            'events': [{'seq': 1, 'type': 'mission.start', 'payload': {}}], 'records': {}}


def add(m, seq, event_type, kind, record, **payload):
    m['records'].setdefault(kind, []).append(record)
    m['events'].append({'seq': seq, 'type': event_type,
                        'payload': {**payload, 'record_changes': [{'kind': kind, 'record': record}]}})


def pending(m, seq=2, id='decision-a', question='next', purpose='Choose next research action'):
    add(m, seq, 'jev.started', 'decision', {'id': id, 'status': 'inflight', 'questions': {question: {}},
                                         'purpose': purpose}, decision_id=id)


def test_terminal_and_replay_states_never_animate_stale_work(derive):
    for status in ('complete', 'partial', 'blocked', 'paused', 'cancelled', 'interrupted'):
        m = mission(status)
        pending(m)
        state = derive(m)
        assert state['phase'] == 'idle' and not state['active'] and state['transport'] == 'none'
        assert 'currentDecision' not in state
    m = mission()
    pending(m)
    replay = derive(m, True)
    assert replay['statusLabel'] == 'Recorded replay' and not replay['active']
    assert replay['phase'] == 'idle' and 'currentDecision' not in replay


def test_retry_does_not_claim_a_historical_inflight_request(derive):
    m = mission()
    pending(m)
    add(m, 3, 'action.started', 'action', {'id': 'search-a', 'kind': 'search', 'status': 'running'}, action_id='search-a')
    add(m, 4, 'search.started', 'search_attempt', {'id': 'attempt-a', 'action_id': 'search-a', 'status': 'running',
                                               'provider': 'fixture-provider'}, attempt_id='attempt-a')
    m['events'].append({'seq': 5, 'type': 'mission.retry', 'payload': {}})
    state = derive(m)
    assert state['phase'] == 'processing' and state['transport'] == 'none'
    assert 'currentDecision' not in state and 'currentSearch' not in state
    pending(m, seq=6, id='decision-b', question='relevance', purpose='Assess public source')
    state = derive(m)
    assert state['phase'] == 'assessing' and state['currentDecision']['id'] == 'decision-b'


def test_actual_search_provider_requires_a_matching_started_action(derive):
    m = mission()
    add(m, 2, 'action.started', 'action', {'id': 'action-a', 'kind': 'search', 'status': 'running'}, action_id='action-a')
    add(m, 3, 'search.started', 'search_attempt', {'id': 'attempt-a', 'action_id': 'action-a', 'status': 'running',
                                               'provider': 'brave', 'query': 'document search evidence'}, attempt_id='attempt-a')
    state = derive(m)
    assert state['phase'] == 'searching' and state['transport'] == 'search_api'
    assert state['requestLabel'] == 'brave · document search evidence'
    assert state['counts']['searches'] == 0
    m['records']['search_attempt'][0]['action_id'] = 'another-action'
    assert derive(m)['phase'] == 'processing'


def test_page_reading_stops_when_a_source_arrives_and_browser_is_explicit(derive):
    m = mission()
    action = {'id': 'action-a', 'kind': 'fetch', 'status': 'running', 'value': 'https://example.org/'}
    add(m, 2, 'action.started', 'action', action, action_id=action['id'])
    assert derive(m)['phase'] == 'reading' and derive(m)['transport'] == 'page_fetch'
    source = {'id': 'source-a', 'action_id': action['id'], 'url': action['value']}
    add(m, 3, 'source.extracted', 'source', source, source_id=source['id'])
    state = derive(m)
    assert state['phase'] == 'processing' and state['transport'] == 'none' and state['sourceMode'] == 'http'
    pending(m, seq=4, question='offer', purpose='Verify selected evidence against each question')
    assert derive(m)['phase'] == 'verifying'
    rendered = mission()
    add(rendered, 2, 'action.started', 'action', {**action, 'kind': 'render'}, action_id=action['id'])
    assert derive(rendered)['phase'] == 'rendering'
    add(rendered, 3, 'source.extracted', 'source', {**source, 'browser_ms': 250, 'artifact_id': 'screenshot-fixture'})
    assert derive(rendered)['sourceMode'] == 'rendered'
    rendered['records']['source'][0]['cache'] = True
    assert derive(rendered)['sourceMode'] == 'cache'


def test_completed_call_and_saved_choice_are_not_counted_per_question(derive):
    m = mission('complete')
    decision = {'id': 'decision-a', 'status': 'complete', 'latency_ms': 125, 'questions': {
        'next': {'criteria': {'action-a': 'Read example.org', 'stop': 'Decline this batch'}},
        'relevance': {'criteria': ['Unrelated', 'Useful']}},
        'answers': {'next': {'choice': 'action-a'}, 'relevance': {'score': 1}}}
    add(m, 2, 'jev.completed', 'decision', decision, decision_id=decision['id'])
    add(m, 3, 'decision.cached', 'decision', {**decision, 'id': 'cached-a', 'cache': True, 'latency_ms': None}, decision_id='cached-a')
    state = derive(m)
    assert state['counts']['decisions'] == 1 and state['counts']['cachedDecisions'] == 1
    assert state['chosen']['id'] == 'action-a' and state['chosen']['label'] == 'Read example.org'
    assert state['chosen']['alternatives'] == [{'id': 'stop', 'label': 'Decline this batch'}]
    assert state['latestCompletedDecision']['id'] == 'cached-a'


def test_only_passed_records_contribute_and_reviews_do_not_fake_new_arrivals(derive):
    m = mission('complete')
    a = {'id': 'source-a', 'url': 'https://example.org/'}
    b = {'id': 'source-b', 'url': 'https://example.net/'}
    add(m, 2, 'source.extracted', 'source', a, source_id=a['id'])
    add(m, 3, 'source.extracted', 'source', b, source_id=b['id'])
    # A review updates the stored order, but it is not newly retrieved content.
    m['records']['source'] = [b, {**a, 'review': 'pinned'}]
    m['events'].append({'seq': 4, 'type': 'review.saved', 'payload': {'record_changes': [{'kind': 'source', 'record': a}]}})
    add(m, 5, 'assessment.recorded', 'finding', {'id': 'finding-a', 'status': 'unknown'})
    # Derived latest-state fields must never introduce future replay data.
    m['jev_activity'] = {'summary': {'completions': 99}}
    m['telemetry'] = {'pages': 99}
    state = derive(m, True)
    assert state['latestSource']['id'] == 'source-b' and state['latestEventSeq'] == 5
    assert state['counts']['pages'] == 2 and state['counts']['findings'] == 1
    assert state['counts']['supportedFindings'] == 0 and state['counts']['decisions'] == 0


def test_priority_call_after_research_stopped_remains_real_work(derive):
    m = mission()
    m['events'].append({'seq': 2, 'type': 'research.stopped', 'payload': {'code': 'criteria_covered'}})
    pending(m, seq=3, question='priority', purpose='Prioritize prepared experiments')
    state = derive(m)
    assert state['phase'] == 'prioritizing' and state['active'] and state['transport'] == 'jev_api'


def test_discovery_phrase_is_part_of_the_actual_source_assessment(derive):
    m = mission()
    pending(m, question='discovery_phrase', purpose='Assess source and select evidence passages')
    m['records']['decision'][0]['questions']['relevance'] = {}
    assert derive(m)['phase'] == 'assessing'


@pytest.mark.parametrize(('purpose', 'phase'), [
    ('Design research approach', 'planning'),
    ('Compare observed artifacts', 'comparing'),
])
def test_adaptive_decisions_have_distinct_live_phases(derive, purpose, phase):
    m = mission()
    pending(m, question='research_unit' if phase == 'planning' else 'title_hook', purpose=purpose)
    state = derive(m)
    assert state['phase'] == phase and state['transport'] == 'jev_api'
    assert state['requestLabel'] == purpose
    assert derive(m, True)['phase'] == 'idle', 'Replay must not imply an active provider request'


def test_video_metadata_processing_does_not_imply_page_fetch(derive):
    m = mission()
    action = {'id': 'video-action', 'kind': 'video', 'status': 'running', 'value': 'https://example.org/video'}
    add(m, 2, 'action.started', 'action', action, action_id=action['id'])
    state = derive(m)
    assert state['phase'] == 'reading_metadata' and state['transport'] == 'metadata'
    assert state['statusLabel'] == 'Inspecting video metadata'
    add(m, 3, 'source.extracted', 'source', {'id': 'video-source', 'action_id': action['id'], 'url': action['value'],
        'source_kind': 'video', 'video_metadata': {'acquisition': 'search_provider_metadata'}})
    state = derive(m)
    assert state['sourceMode'] == 'metadata' and state['transport'] == 'none'


def test_refinement_is_a_real_selection_and_reassessment_is_local(derive):
    m = mission()
    pending(m, question='refine_query', purpose='Refine discovery for unanswered questions')
    state = derive(m)
    assert state['phase'] == 'choosing' and state['transport'] == 'jev_api'
    m = mission()
    add(m, 2, 'action.started', 'action', {'id': 'reassess', 'kind': 'reassess', 'status': 'running',
        'value': 'https://example.org/video', 'source_id': 'old-source'}, action_id='reassess')
    state = derive(m)
    assert state['phase'] == 'assessing' and state['transport'] == 'none'
    assert state['statusLabel'] == 'Reassessing saved evidence'
    pending(m, seq=3, question='relevance', purpose='Analyze individual artifact and select evidence')
    assert derive(m)['transport'] == 'jev_api', 'Only the actual follow-up Jev request has network activity'


def test_grouped_record_selection_uses_real_leads_and_explicit_deferrals(derive):
    m = mission()
    pending(m, question='opaque-action-a', purpose='Select independent records for parallel assessment')
    decision = m['records']['decision'][0]
    decision['questions']['opaque-action-b'] = {}
    decision['state'] = {'observed_leads': {
        'opaque-action-a': {'url': 'https://alpha.example/original', 'description': 'Original documentation'},
        'opaque-action-b': {'url': 'https://bravo.example/original', 'description': 'Another observed lead'}}}
    state = derive(m)
    assert state['phase'] == 'choosing'
    assert [item['url'] for item in state['collectionSelection']['items']] == ['https://alpha.example/original', 'https://bravo.example/original']
    assert all('choice' not in item for item in state['collectionSelection']['items'])
    decision.update(status='complete', answers={'opaque-action-a': {'choice': 'inspect'}, 'opaque-action-b': {'choice': 'defer'}})
    m['events'].append({'seq': 3, 'type': 'jev.completed', 'payload': {'decision_id': decision['id']}})
    m['records']['source'] = [{'id': 'source-a', 'action_id': 'opaque-action-a'}, {'id': 'older-b', 'action_id': 'opaque-action-b'}]
    completed = derive(m)
    assert completed['currentDecisions'] == []
    selected, deferred = completed['collectionSelection']['items']
    assert selected['choice'] == 'inspect' and selected['sourceId'] == 'source-a'
    assert deferred['choice'] == 'defer' and 'sourceId' not in deferred


def test_concurrent_requests_only_include_pending_current_segment_work(derive):
    m = mission()
    pending(m, seq=2, id='old-request', purpose='Assess public source')
    m['events'].append({'seq': 3, 'type': 'mission.resume', 'payload': {}})
    pending(m, seq=4, id='request-a', purpose='Assess public source')
    pending(m, seq=5, id='request-b', purpose='Verify selected evidence against each question')
    pending(m, seq=6, id='request-c', purpose='Assess public source')
    m['events'].append({'seq': 7, 'type': 'jev.error', 'payload': {'decision_id': 'request-c'}})
    state = derive(m)
    assert [item['id'] for item in state['currentDecisions']] == ['request-a', 'request-b']
    assert state['currentDecision']['id'] == 'request-b'
    assert derive(m, True)['currentDecisions'] == []
    m['status'] = 'paused'
    assert derive(m)['currentDecisions'] == []
    m['status'] = 'running'
    m['events'].append({'seq': 8, 'type': 'jev.completed', 'payload': {'decision_id': 'request-a'}})
    assert [item['id'] for item in derive(m)['currentDecisions']] == ['request-b']
