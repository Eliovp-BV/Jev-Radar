from copy import deepcopy

import pytest

from radar.research_proposals import FollowupProposal, ResearchProposal
from radar.structured_output import strict_schema
from radar.synthesis import AnswerProposal


@pytest.mark.parametrize('model', [ResearchProposal, FollowupProposal, AnswerProposal])
def test_research_schemas_make_every_nested_field_required_without_mutation(model):
    original = model.model_json_schema()
    saved = deepcopy(original)
    schema = strict_schema(original)
    assert original == saved
    def inspect(value):
        if isinstance(value, dict):
            assert 'default' not in value
            if value.get('type') == 'object':
                assert value['additionalProperties'] is False
                assert set(value['required']) == set(value['properties'])
            for child in value.values(): inspect(child)
        elif isinstance(value, list):
            for child in value: inspect(child)
    inspect(schema)
    if model is not AnswerProposal:
        query = schema['$defs']['DiscoveryQuery']
        assert 'search_kind' in query['required']
        assert query['properties']['search_kind']['enum'] == ['web', 'video', 'web_leads']


def test_constant_connection_response_has_explicit_type_and_no_extra_fields():
    schema = strict_schema({'type': 'object', 'properties': {'status': {'const': 'connected'}}})
    assert schema['properties']['status'] == {'type': 'string', 'enum': ['connected']}
    assert schema['required'] == ['status'] and schema['additionalProperties'] is False
