"""Frontend evidence projection rejects stale derived claims without provider calls."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def project(tmp_path_factory):
    node, compiler = shutil.which('node'), ROOT / 'frontend/node_modules/.bin/tsc'
    if not node or not compiler.exists():
        pytest.skip('Install existing frontend dependencies to check the evidence projection')
    output = tmp_path_factory.mktemp('research-validity-js')
    result = subprocess.run([str(compiler), '--outDir', str(output), '--target', 'ES2022', '--module', 'ESNext',
                             '--moduleResolution', 'bundler', '--skipLibCheck', '--strict',
                             str(ROOT / 'frontend/src/research-validity.ts')], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    module = output / 'research-validity.mjs'
    (output / 'research-validity.js').rename(module)
    script = 'import(process.argv[1]).then(({deriveResearchEvidence})=>{let input="";process.stdin.on("data",v=>input+=v);process.stdin.on("end",()=>{const m=JSON.parse(input),before=JSON.stringify(m),result=deriveResearchEvidence(m);if(before!==JSON.stringify(m))throw Error("Input mutated");process.stdout.write(JSON.stringify(result))});});'

    def run(mission):
        result = subprocess.run([node, '-e', script, module.as_uri()], input=json.dumps(mission),
                                capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    return run


def fixture():
    source = {'id': 'source', 'url': 'https://example.org/video', 'entity_id': 'entity', 'review': 'unreviewed'}
    span = {'id': 'span', 'source_id': source['id'], 'text': 'Synthetic evidence'}
    finding = {'id': 'finding', 'source_ids': [source['id']], 'span_ids': [span['id']], 'review': 'unreviewed', 'rubric_version': 1}
    program = {'id': 'program', 'unit': 'videos', 'plan_version': 1}
    feature = {'id': 'feature', 'source_id': source['id'], 'program_id': program['id'], 'plan_version': 1,
               'features': {'hook': {'choice': 'descriptive', 'label': 'Descriptive', 'span_ids': [span['id']]}}}
    analysis = {'id': 'analysis', 'program_id': program['id'], 'plan_version': 1,
                'patterns': [{'id': 'pattern', 'status': 'possible', 'source_ids': [source['id']], 'span_ids': [span['id']]}],
                'comparisons': []}
    records = {'source': [source], 'span': [span], 'finding': [finding], 'entity': [{'id': 'entity', 'name': 'Example'}],
               'research_program': [program], 'artifact_analysis': [feature], 'research_analysis': [analysis]}
    return {'plan': {'excluded_domains': [], 'excluded_entities': []}, 'plan_version': 1, 'records': records,
            'events': [{'seq': 1, 'type': 'assessment.recorded', 'payload': {'record_changes': [
                {'kind': 'source', 'record': deepcopy(source)}, {'kind': 'finding', 'record': deepcopy(finding)}]}},
                {'seq': 2, 'type': 'research.compared', 'payload': {'record_changes': [{'kind': 'research_analysis', 'record': deepcopy(analysis)}]}}]}


def test_current_comparison_and_features_remain_visible(project):
    state = project(fixture())
    assert state['analysis']['id'] == 'analysis' and not state['invalidated']
    assert len(state['features']) == len(state['findings']) == 1


@pytest.mark.parametrize('kind', ['source', 'finding', 'entity'])
def test_rejected_evidence_hides_prior_comparison_even_without_stale_flag(project, kind):
    m = fixture()
    m['records'][kind][0]['review'] = 'rejected'
    state = project(m)
    assert state['invalidated'] and 'analysis' not in state
    assert not state['features']


def test_domain_exclusion_and_new_plan_hide_prior_results(project):
    m = fixture()
    m['plan']['excluded_domains'] = ['example.org']
    state = project(m)
    assert state['invalidated'] and not state['sources']
    m = fixture()
    m['plan_version'] = 2
    state = project(m)
    assert state['invalidated'] and not state['features'] and 'program' not in state
    assert not state['findings']


def test_stale_latest_analysis_never_falls_back_to_older_claims(project):
    m = fixture()
    m['records']['research_analysis'].append({**m['records']['research_analysis'][0], 'id': 'new', 'stale': True,
                                            'stale_reason': 'Reviewed evidence changed.'})
    state = project(m)
    assert state['invalidated'] and 'analysis' not in state
    assert state['invalidationReason'] == 'Reviewed evidence changed.'


def test_approval_preserves_comparison_but_reject_then_restore_requires_reassessment(project):
    m = fixture()
    finding = m['records']['finding'][0]
    finding['review'] = 'approved'
    m['events'].append({'seq': 3, 'type': 'review.saved', 'payload': {'state': 'approved',
                        'record_changes': [{'kind': 'finding', 'record': deepcopy(finding)}]}})
    assert project(m)['analysis']['id'] == 'analysis'
    m['events'].append({'seq': 4, 'type': 'review.saved', 'payload': {'state': 'rejected',
                        'record_changes': [{'kind': 'finding', 'record': {**finding, 'review': 'rejected'}}]}})
    m['events'].append({'seq': 5, 'type': 'review.saved', 'payload': {'state': 'approved',
                        'record_changes': [{'kind': 'finding', 'record': deepcopy(finding)}]}})
    assert project(m)['invalidated']
    refreshed = {**m['records']['research_analysis'][0], 'id': 'fresh-analysis'}
    m['records']['research_analysis'].append(refreshed)
    m['events'].append({'seq': 6, 'type': 'research.compared', 'payload': {'record_changes': [{'kind': 'research_analysis', 'record': refreshed}]}})
    assert project(m)['analysis']['id'] == 'fresh-analysis'


def test_unknown_span_and_changed_program_cannot_support_a_pattern(project):
    m = fixture()
    m['records']['span'] = []
    assert project(m)['invalidated']
    m = fixture()
    m['records']['research_program'][0]['id'] = 'new-program'
    state = project(m)
    assert state['invalidated'] and not state['features']
