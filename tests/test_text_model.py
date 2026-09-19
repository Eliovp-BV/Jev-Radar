"""Text provider protocol and allowance checks; every network response is a mock."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from radar.api import create_app
from radar.config import Settings
from radar.schemas import Plan
from radar.storage import Store, dumps, now, uid
from radar.text_model import TextModel, TextModelError, TextBudgetError, MAX_RESPONSE_BYTES


SCHEMA = {'type': 'object', 'properties': {'status': {'type': 'string'}}, 'required': ['status']}


def setup(tmp_path, provider='openai', **options):
    options = {'text_input_rate': 1, 'text_output_rate': 2, **options}
    settings = Settings(data_dir=tmp_path, text_provider=provider, text_model='fixture-model',
                        openai_key='fixture-openai-secret', anthropic_key='fixture-anthropic-secret',
                        openrouter_key='fixture-openrouter-secret', text_model_key='fixture-compatible-secret',
                        text_model_base_url='https://gateway.example/v1', **options)
    store = Store(tmp_path/'text.sqlite')
    plan = Plan(goal='Isolated text provider fixture').model_dump()
    mid = uid()
    store.execute('INSERT INTO missions VALUES(?,?,?,?,?,?,?,?,?)',
                  (mid, plan['goal'], 'running', dumps(plan), 1, now(), now(), None, 'fixture'))
    return settings, store, mid, TextModel(settings, store)


def install(monkeypatch, handler):
    monkeypatch.setattr(TextModel, 'client', lambda self: httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def envelope(content='{"status":"connected"}', **changes):
    return {'model': 'fixture-resolved', 'choices': [{'finish_reason': 'stop', 'message': {'content': content}}],
            'usage': {'prompt_tokens': 90, 'completion_tokens': 12}, **changes}


async def generate(model, mid, **changes):
    return await model.generate(mid, purpose='Fixture synthesis', instructions='Return the supplied object.',
                                state={'public': 'fixture text'}, schema=SCHEMA, **changes)


@pytest.mark.parametrize('provider,host,header,limit', [
    ('openai', 'api.openai.com', 'authorization', 'max_completion_tokens'),
    ('anthropic', 'api.anthropic.com', 'x-api-key', 'max_tokens'),
    ('openrouter', 'openrouter.ai', 'authorization', 'max_tokens'),
    ('compatible', 'gateway.example', 'authorization', 'max_tokens'),
])
async def test_provider_protocols_and_private_metadata(tmp_path, monkeypatch, provider, host, header, limit):
    settings, store, mid, model = setup(tmp_path, provider)
    captured = []
    def handler(request):
        captured.append(request)
        body = json.loads(request.content)
        assert request.url.host == host and request.url.scheme == 'https'
        assert body[limit] == 128 and body['model'] == 'fixture-model'
        assert request.headers[header].endswith('fixture-' + provider + '-secret')
        assert store.records(mid, 'text_call')[0]['status'] == 'inflight'
        if provider == 'anthropic':
            assert request.headers['anthropic-version'] == '2023-06-01'
            return httpx.Response(200, json={'model': 'fixture-resolved', 'stop_reason': 'end_turn',
                                  'content': [{'type': 'text', 'text': '{"status":"connected"}'}],
                                  'usage': {'input_tokens': 90, 'output_tokens': 12}})
        if provider in ('openai', 'openrouter'):
            fmt=body['response_format']
            assert fmt['type']=='json_schema' and fmt['json_schema']['strict'] is True
            assert fmt['json_schema']['schema']=={**SCHEMA,'additionalProperties':False}
            if provider=='openrouter':assert body['provider']['require_parameters'] is True
        else:
            assert body['response_format'] == {'type': 'json_object'}
        return httpx.Response(200, json=envelope())
    install(monkeypatch, handler)
    result = await generate(model, mid, max_output_tokens=128)
    assert result['output'] == {'status': 'connected'} and result['status'] == 'complete'
    assert result['latency_ms'] >= 0 and result['model'] == 'fixture-resolved'
    assert result['actual_tokens'] == 102 and len(captured) == 1
    persisted = dumps({'records': store.records(mid), 'events': store.events(mid)})
    assert all(secret not in persisted for secret in [settings.openai_key, settings.anthropic_key, settings.openrouter_key, settings.text_model_key])
    assert 'fixture text' not in persisted and 'Return the supplied object.' not in persisted and '"output"' not in persisted
    assert store.rows('SELECT * FROM reservations') == []
    store.close()


@pytest.mark.parametrize('content', ['[]', '{bad}', '{"a":NaN}', '{"a":1e999}', '{"a":1,"a":2}', '```json\n{}\n```'])
async def test_rejects_nonobject_invalid_and_duplicate_json(tmp_path, monkeypatch, content):
    _, store, mid, model = setup(tmp_path)
    install(monkeypatch, lambda request: httpx.Response(200, json=envelope(content)))
    with pytest.raises(TextModelError):
        await generate(model, mid)
    record = store.records(mid, 'text_call')[0]
    assert record['status'] == 'error' and record['actual_tokens'] is None
    assert 'output' not in record
    store.close()


@pytest.mark.parametrize('change', [
    {'choices': [{'finish_reason': 'length', 'message': {'content': '{}'}}]},
    {'choices': [{'finish_reason': 'stop', 'message': {'content': '{}', 'refusal': 'provider private body'}}]},
    {'choices': [{'finish_reason': 'stop', 'message': {'content': '{}', 'tool_calls': [{'id': 'forbidden'}]}}]},
    {'model': ''}, {'usage': {'prompt_tokens': -1}}, {'usage': {'completion_tokens': True}},
])
async def test_incomplete_refused_or_invalid_provider_metadata(tmp_path, monkeypatch, change):
    _, store, mid, model = setup(tmp_path)
    install(monkeypatch, lambda request: httpx.Response(200, json=envelope(**change)))
    with pytest.raises(TextModelError):
        await generate(model, mid)
    assert 'provider private body' not in dumps(store.records(mid))
    store.close()


async def test_missing_usage_keeps_full_reserved_allowance(tmp_path, monkeypatch):
    _, store, mid, model = setup(tmp_path)
    install(monkeypatch, lambda request: httpx.Response(200, json=envelope(usage={})))
    result = await generate(model, mid)
    assert result['actual_tokens'] is None and result['reserved_tokens'] > 3500
    store.close()


@pytest.mark.parametrize('status', [301, 401, 429, 503])
async def test_http_errors_are_safe_counted_and_never_retried(tmp_path, monkeypatch, status):
    _, store, mid, model = setup(tmp_path)
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text='SECRET provider response body', headers={'Location': 'https://other.example/'})
    install(monkeypatch, handler)
    model.save({'provider': 'openai', 'model': 'fixture-model', 'max_calls': 1})
    with pytest.raises(TextModelError, match='HTTP ' + str(status)):
        await generate(model, mid)
    with pytest.raises(TextBudgetError):
        await generate(model, mid)
    assert len(calls) == 1 and 'SECRET' not in dumps(store.records(mid))
    store.close()


async def test_response_size_and_request_size_limits(tmp_path, monkeypatch):
    _, store, mid, model = setup(tmp_path)
    with pytest.raises(TextModelError, match='input size'):
        await model.generate(mid, purpose='Fixture', instructions='x'*50000, state={}, schema=SCHEMA)
    assert store.records(mid) == []
    install(monkeypatch, lambda request: httpx.Response(200, content=b'x'*(MAX_RESPONSE_BYTES+1)))
    with pytest.raises(TextModelError, match='size limit'):
        await generate(model, mid)
    assert len(store.records(mid, 'text_call')) == 1
    store.close()


async def test_token_budget_prevents_network_even_with_calls_remaining(tmp_path, monkeypatch):
    _, store, mid, model = setup(tmp_path)
    model.save({'provider': 'openai', 'model': 'fixture-model', 'max_tokens': 4096})
    with pytest.raises(TextBudgetError):
        await generate(model, mid)
    assert store.records(mid) == []
    store.close()


async def test_concurrent_attempt_reservations_cannot_overrun_cap(tmp_path, monkeypatch):
    _, store, mid, model = setup(tmp_path)
    model.save({'provider': 'openai', 'model': 'fixture-model', 'max_calls': 1})
    calls = []
    async def handler(request):
        calls.append(request)
        await asyncio.sleep(.01)
        return httpx.Response(200, json=envelope())
    install(monkeypatch, handler)
    # Separate adapters share SQLite, so their per-instance semaphores cannot
    # provide this guarantee; reservation + count must be one locked operation.
    other = TextModel(model.settings, store)
    results = await asyncio.gather(generate(model, mid), generate(other, mid), return_exceptions=True)
    assert len(calls) == 1 and sum(isinstance(item, TextBudgetError) for item in results) == 1
    store.close()


async def test_dev_calls_require_known_prices_and_use_existing_ledger_hook(tmp_path, monkeypatch):
    settings, store, mid, model = setup(tmp_path, dev_testing=True, text_input_rate=None, text_output_rate=None)
    from radar.jev import Jev
    reservations = []
    monkeypatch.setattr(Jev, 'reserve_dev', lambda self, tokens, usd, provider: reservations.append((tokens, usd, provider)))
    with pytest.raises(TextBudgetError, match='price estimates'):
        await generate(model, mid)
    assert reservations == [] and store.records(mid) == []
    settings.text_input_rate = 1
    settings.text_output_rate = 2
    install(monkeypatch, lambda request: httpx.Response(200, json=envelope()))
    await generate(model, mid)
    assert len(reservations) == 1 and reservations[0][0] > 0 and reservations[0][1] > 0
    assert reservations[0][2] == 'text'
    store.close()


@pytest.mark.parametrize('base_url', ['http://gateway.example/v1', 'https://user:secret@gateway.example/v1',
                                    'https://gateway.example/v1?key=secret', 'https://gateway.example/v1#secret'])
async def test_compatible_endpoint_requires_server_https_config(tmp_path, base_url):
    settings, store, mid, model = setup(tmp_path, 'compatible')
    settings.text_model_base_url = base_url
    assert not model.enabled and not model.config()['configured']
    with pytest.raises(TextModelError, match='no inference'):
        await generate(model, mid)
    assert store.records(mid) == []
    store.close()


def test_settings_remember_models_and_never_return_credentials(tmp_path):
    settings = Settings(data_dir=tmp_path, openai_key='PRIVATE-OPENAI', anthropic_key='PRIVATE-ANTHROPIC')
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers['x-radar-csrf'] = client.get('/api/session').json()['csrf']
        initial = client.get('/api/settings').json()['text_model']
        assert not initial['enabled'] and initial['provider'] == 'disabled'
        for provider, model in [('openai', 'fixture-openai'), ('anthropic', 'fixture-anthropic')]:
            result = client.put('/api/settings/text-model', json={'provider': provider, 'model': model})
            assert result.status_code == 200 and result.json()['text_model']['enabled']
            assert 'PRIVATE-' not in result.text
        config = result.json()['text_model']
        assert next(item for item in config['providers'] if item['id'] == 'openai')['model'] == 'fixture-openai'
        saved = app.state.store.setting('text_model')
        assert 'PRIVATE-' not in dumps(saved)
        assert client.put('/api/settings/text-model', json={'provider': 'compatible', 'model': 'x', 'base_url': 'https://arbitrary.example/'}).status_code == 422
        for extra in [{'max_calls': 13}, {'max_output_tokens': 6001}, {'max_tokens': 600001}, {'model': 'bad\nname'}]:
            assert client.put('/api/settings/text-model', json={'provider': 'openai', 'model': 'fixture', **extra}).status_code == 422
        missing = client.put('/api/settings/text-model', json={'provider': 'openrouter', 'model': 'fixture'})
        assert missing.status_code == 200 and not missing.json()['text_model']['enabled']
        assert client.post('/api/text-connection-test').status_code == 409


def test_active_investigation_prevents_provider_and_key_changes(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, openai_key='PRIVATE-OLD')
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers['x-radar-csrf'] = client.get('/api/session').json()['csrf']
        mission = client.post('/api/missions', json={'goal': 'Isolated settings fixture'}).json()
        app.state.store.execute("UPDATE missions SET status='running' WHERE id=?", (mission['id'],))
        assert client.put('/api/settings/text-model', json={'provider': 'openai', 'model': 'fixture'}).status_code == 409
        monkeypatch.setattr(Settings, 'load', lambda: Settings(data_dir=tmp_path, openai_key='PRIVATE-NEW'))
        response = client.post('/api/settings/reload')
        assert response.status_code == 409 and settings.openai_key == 'PRIVATE-OLD'
        assert 'PRIVATE-' not in response.text
        app.state.store.execute("UPDATE missions SET status='paused' WHERE id=?", (mission['id'],))
        assert client.post('/api/settings/reload').status_code == 200
        assert settings.openai_key == 'PRIVATE-NEW'


def test_connection_test_uses_small_paid_adapter_and_returns_only_metadata(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path, openai_key='PRIVATE-OPENAI', text_provider='openai', text_model='fixture', text_input_rate=1, text_output_rate=2)
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=envelope())
    install(monkeypatch, handler)
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers['x-radar-csrf'] = client.get('/api/session').json()['csrf']
        response = client.post('/api/text-connection-test')
        assert response.status_code == 200 and response.json()['success']
        assert seen[0]['max_completion_tokens'] == 128
        assert 'PRIVATE-' not in response.text and 'output' not in response.json()
        assert client.get('/api/missions').json() == []
        calls = app.state.store.rows("SELECT payload FROM records WHERE kind='text_call'")
        assert len(calls) == 1 and json.loads(calls[0]['payload'])['status'] == 'complete'
