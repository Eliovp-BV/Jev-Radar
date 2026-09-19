"""Native Gemini protocol checks with mocked HTTP only; no hosted model calls."""
from datetime import date
import json

import httpx
import pytest
from fastapi.testclient import TestClient

import radar.config as config_module
import radar.text_model as text_module
from radar.api import create_app
from radar.config import Settings
from radar.schemas import Plan, TextModelSettings
from radar.storage import Store, dumps, now, uid
from radar.text_model import TextBudgetError, TextModel, TextModelError


MODEL = 'gemini-3.8-flash'
SCHEMA = {'type': 'object', 'properties': {'status': {'const': 'connected'}}, 'required': ['status']}


@pytest.fixture(autouse=True)
def stable_default_price_date(monkeypatch):
    monkeypatch.setattr(text_module, '_pricing_date', lambda: date(2026, 9, 19))


def setup(tmp_path):
    settings = Settings(data_dir=tmp_path, text_provider='gemini', text_model=MODEL,
                        gemini_key='PRIVATE-GEMINI-KEY')
    store = Store(tmp_path / 'gemini.sqlite')
    plan = Plan(goal='Isolated Gemini protocol fixture').model_dump()
    mid = uid()
    store.execute('INSERT INTO missions VALUES(?,?,?,?,?,?,?,?,?)',
                  (mid, plan['goal'], 'running', dumps(plan), 1, now(), now(), None, 'fixture'))
    return settings, store, mid, TextModel(settings, store)


def response(**changes):
    return {'modelVersion': MODEL, 'candidates': [{'finishReason': 'STOP', 'content': {
        'role': 'model', 'parts': [{'text': '{"status":"connected"}'}]}}],
        'usageMetadata': {'promptTokenCount': 90, 'candidatesTokenCount': 12,
                          'thoughtsTokenCount': 25, 'totalTokenCount': 127}, **changes}


def install(monkeypatch, handler):
    monkeypatch.setattr(TextModel, 'client', lambda self: httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def generate(model, mid, **changes):
    return await model.generate(mid, purpose='Gemini fixture', instructions='Return a valid test object.',
                                state={'public': 'isolated public fixture'}, schema=SCHEMA, **changes)


async def test_native_protocol_private_auth_and_thinking_accounting(tmp_path, monkeypatch):
    settings, store, mid, model = setup(tmp_path)
    requests = []
    def handler(request):
        requests.append(request)
        assert str(request.url) == 'https://generativelanguage.googleapis.com/v1beta/models/' + MODEL + ':generateContent'
        assert request.headers['x-goog-api-key'] == settings.gemini_key
        assert 'authorization' not in request.headers and not request.url.query
        body = json.loads(request.content)
        assert set(body) == {'systemInstruction', 'contents', 'generationConfig'}
        assert body['contents'][0]['role'] == 'user'
        assert 'isolated public fixture' in body['contents'][0]['parts'][0]['text']
        assert 'untrusted' in body['systemInstruction']['parts'][0]['text']
        generation = body['generationConfig']
        assert generation['maxOutputTokens'] == 128
        assert generation['responseMimeType'] == 'application/json'
        assert generation['responseJsonSchema']['additionalProperties'] is False
        assert generation['responseJsonSchema']['properties']['status'] == {'enum': ['connected'], 'type': 'string'}
        assert generation['thinkingConfig'] == {'thinkingLevel': 'LOW', 'includeThoughts': False}
        assert 'candidateCount' not in generation
        assert store.records(mid, 'text_call')[0]['status'] == 'inflight'
        result = response()
        result['candidates'][0]['content']['parts'].insert(0, {'text': 'PRIVATE THOUGHT', 'thought': True})
        result['candidates'][0]['content']['parts'][-1]['thoughtSignature'] = 'PRIVATE SIGNATURE'
        return httpx.Response(200, json=result)
    install(monkeypatch, handler)
    call = await generate(model, mid, max_output_tokens=128)
    assert len(requests) == 1 and call['output'] == {'status': 'connected'}
    assert call['usage'] == {'input_tokens': 90, 'output_tokens': 37, 'thought_tokens': 25}
    assert call['actual_tokens'] == 127
    assert call['actual_usd'] == pytest.approx((90 * .75 + 37 * 3.75) / 1e6)
    persisted = dumps({'records': store.records(mid), 'events': store.events(mid)})
    for private in (settings.gemini_key, 'PRIVATE THOUGHT', 'PRIVATE SIGNATURE', 'isolated public fixture', 'Return a valid test object.'):
        assert private not in persisted
    store.close()


@pytest.mark.parametrize('finish', ['MAX_TOKENS', 'SAFETY', 'RECITATION', 'MALFORMED_FUNCTION_CALL', 'OTHER', None])
async def test_refused_or_truncated_output_is_not_accepted(tmp_path, monkeypatch, finish):
    _, store, mid, model = setup(tmp_path)
    envelope = response()
    envelope['candidates'][0]['finishReason'] = finish
    install(monkeypatch, lambda request: httpx.Response(200, json=envelope))
    with pytest.raises(TextModelError, match='incomplete or refused'):
        await generate(model, mid)
    call = store.records(mid, 'text_call')[0]
    assert call['status'] == 'error' and call['actual_usd'] is None and call['reserved_usd'] > 0
    store.close()


@pytest.mark.parametrize('changes', [
    {'candidates': []},
    {'candidates': [response()['candidates'][0]] * 2},
    {'promptFeedback': {'blockReason': 'SAFETY', 'blockReasonMessage': 'PRIVATE DETAIL'}},
    {'modelVersion': ''},
    {'usageMetadata': {'promptTokenCount': -1}},
    {'usageMetadata': {'candidatesTokenCount': True}},
    {'usageMetadata': {'thoughtsTokenCount': '25'}},
    {'usageMetadata': {'toolUsePromptTokenCount': 1}},
    {'usageMetadata': {'promptTokenCount': 90, 'candidatesTokenCount': 12, 'thoughtsTokenCount': 25, 'totalTokenCount': 102}},
    {'usageMetadata': []},
])
async def test_invalid_native_envelopes_fail_closed(tmp_path, monkeypatch, changes):
    _, store, mid, model = setup(tmp_path)
    install(monkeypatch, lambda request: httpx.Response(200, json=response(**changes)))
    with pytest.raises(TextModelError):
        await generate(model, mid)
    assert 'PRIVATE DETAIL' not in dumps(store.records(mid))
    store.close()


@pytest.mark.parametrize('part', [
    {'functionCall': {'name': 'web_search', 'args': {}}},
    {'text': '{}', 'functionCall': {'name': 'web_search'}},
    {'inlineData': {'mimeType': 'image/png', 'data': 'PRIVATE IMAGE'}},
    {'text': '{}', 'thought': 'true'},
    {'text': '{}', 'thought': True},
])
async def test_tools_multimodal_and_thought_only_responses_are_rejected(tmp_path, monkeypatch, part):
    _, store, mid, model = setup(tmp_path)
    envelope = response()
    envelope['candidates'][0]['content']['parts'] = [part]
    install(monkeypatch, lambda request: httpx.Response(200, json=envelope))
    with pytest.raises(TextModelError):
        await generate(model, mid)
    assert 'PRIVATE IMAGE' not in dumps(store.records(mid))
    store.close()


@pytest.mark.parametrize('usage', [{}, {'promptTokenCount': 90}, {'candidatesTokenCount': 12, 'thoughtsTokenCount': 25}])
async def test_missing_usage_retains_monetary_reservation(tmp_path, monkeypatch, usage):
    _, store, mid, model = setup(tmp_path)
    install(monkeypatch, lambda request: httpx.Response(200, json=response(usageMetadata=usage)))
    call = await generate(model, mid)
    assert call['actual_tokens'] is None and call['actual_usd'] is None and call['reserved_usd'] > 0
    store.close()


@pytest.mark.parametrize('status', [301, 401, 429, 503])
async def test_http_errors_do_not_leak_or_retry(tmp_path, monkeypatch, status):
    _, store, mid, model = setup(tmp_path)
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, text='PRIVATE PROVIDER BODY', headers={'Location': 'https://example.org/'})
    install(monkeypatch, handler)
    with pytest.raises(TextModelError, match='HTTP ' + str(status)):
        await generate(model, mid)
    assert len(requests) == 1 and 'PRIVATE PROVIDER BODY' not in dumps(store.records(mid))
    store.close()


@pytest.mark.parametrize('model', ['models/gemini-3.8-flash', '../gemini', 'gemini:generateContent', 'https://example.org', '/gemini', '..', 'gemini?key=bad', 'gemini\\evil'])
def test_only_bare_model_ids_are_valid(model):
    with pytest.raises(ValueError):
        TextModelSettings(provider='gemini', model=model)


@pytest.mark.parametrize('location', ['environment', 'saved'])
async def test_invalid_server_model_does_not_fall_back_to_paid_default(tmp_path, location):
    settings, store, mid, model = setup(tmp_path)
    if location == 'environment':
        settings.text_model = 'models/' + MODEL
    else:
        store.set_setting('text_model', {'provider': 'gemini', 'models': {'gemini': 'models/' + MODEL}})
    assert model.config()['model'] == '' and not model.enabled
    with pytest.raises(TextModelError, match='no inference was attempted'):
        await generate(model, mid)
    assert store.records(mid) == []
    store.close()


def test_keys_load_server_side_with_primary_precedence_and_alias(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, 'ROOT', tmp_path)
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
    env = tmp_path / '.env'
    env.write_text('GEMINI_API_KEY=PRIVATE-PRIMARY\nGOOGLE_API_KEY=PRIVATE-ALIAS\n')
    assert Settings.load().gemini_key == 'PRIVATE-PRIMARY'
    env.write_text('GOOGLE_API_KEY=PRIVATE-ALIAS\n')
    assert Settings.load().gemini_key == 'PRIVATE-ALIAS'
    env.write_text('GEMINI_API_KEY=your_gemini_key\nGOOGLE_API_KEY=your_google_key\n')
    assert Settings.load().gemini_key == ''


def test_settings_expose_presence_only_and_reload_is_idle_only(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers['x-radar-csrf'] = client.get('/api/session').json()['csrf']
        initial = client.get('/api/settings').json()['text_model']
        assert initial['provider'] == 'disabled'
        provider = next(item for item in initial['providers'] if item['id'] == 'gemini')
        assert provider['label'] == 'Google Gemini' and provider['key_env'] == 'GEMINI_API_KEY'
        assert provider['default_model'] == MODEL and not provider['configured']
        result = client.put('/api/settings/text-model', json={'provider': 'gemini', 'model': MODEL})
        assert result.status_code == 200 and not result.json()['text_model']['enabled']
        assert client.put('/api/settings/text-model', json={'provider': 'gemini', 'model': 'models/' + MODEL}).status_code == 422
        monkeypatch.setattr(Settings, 'load', lambda: Settings(data_dir=tmp_path, gemini_key='PRIVATE-NEW'))
        mission = client.post('/api/missions', json={'goal': 'Isolated Gemini reload fixture'}).json()
        app.state.store.execute("UPDATE missions SET status='running' WHERE id=?", (mission['id'],))
        assert client.post('/api/settings/reload').status_code == 409
        assert settings.gemini_key == ''
        app.state.store.execute("UPDATE missions SET status='paused' WHERE id=?", (mission['id'],))
        result = client.post('/api/settings/reload')
        assert result.status_code == 200 and result.json()['text_model']['enabled']
        assert settings.gemini_key == 'PRIVATE-NEW' and 'PRIVATE-NEW' not in result.text
        assert 'PRIVATE-NEW' not in dumps(app.state.store.setting('text_model'))


async def test_date_aware_price_snapshots_and_unknown_models(tmp_path, monkeypatch):
    _, store, mid, model = setup(tmp_path)
    monkeypatch.setattr(text_module, '_pricing_date', lambda: date(2026, 12, 31))
    assert model.config()['input_usd_per_million'] == .75
    install(monkeypatch, lambda request: httpx.Response(200, json=response()))
    old_call = await generate(model, mid)
    monkeypatch.setattr(text_module, '_pricing_date', lambda: date(2027, 1, 1))
    assert model.config()['input_usd_per_million'] == 1.5
    assert model.config()['output_usd_per_million'] == 7.5
    assert store.records(mid, 'text_call')[0]['actual_usd'] == old_call['actual_usd']
    assert store.records(mid, 'text_call')[0]['output_usd_per_million'] == 3.75
    model.save({'provider': 'gemini', 'model': 'gemini-future-unpriced'})
    with pytest.raises(TextBudgetError, match='price estimates'):
        await generate(model, mid)
    assert len(store.records(mid, 'text_call')) == 1
    model.save({'provider': 'gemini', 'model': 'gemini-future-unpriced', 'input_usd_per_million': 4, 'output_usd_per_million': 8})
    assert model.config()['pricing_configured']
    assert model.config()['input_usd_per_million'] == 4
    store.close()


def test_public_pricing_mode_distinguishes_automatic_rates_and_overrides(tmp_path):
    settings, store, _, model = setup(tmp_path)
    assert model.config()['pricing_mode'] == 'catalog'
    assert next(item for item in model.config()['providers'] if item['id'] == 'gemini')['pricing_mode'] == 'catalog'
    settings.text_input_rate = 1
    settings.text_output_rate = 2
    assert model.config()['pricing_mode'] == 'environment'
    model.save({'provider': 'gemini', 'model': MODEL, 'input_usd_per_million': 3, 'output_usd_per_million': 4})
    assert model.config()['pricing_mode'] == 'operator'
    model.save({'provider': 'gemini', 'model': MODEL})
    assert model.config()['pricing_mode'] == 'environment'
    settings.text_input_rate = settings.text_output_rate = None
    assert model.config()['pricing_mode'] == 'catalog'
    model.save({'provider': 'gemini', 'model': 'gemini-future-unpriced'})
    assert model.config()['pricing_mode'] == 'unconfigured'
    settings.text_model = 'gemini-future-unpriced'
    settings.text_input_rate = float('nan')
    settings.text_output_rate = 2
    assert model.config()['pricing_mode'] == 'unconfigured'
    store.close()


async def test_budget_counts_thinking_before_allowing_another_call(tmp_path, monkeypatch):
    _, store, mid, model = setup(tmp_path)
    envelope = response(usageMetadata={'promptTokenCount': 90, 'candidatesTokenCount': 12,
                                      'thoughtsTokenCount': 3000, 'totalTokenCount': 3102})
    install(monkeypatch, lambda request: httpx.Response(200, json=envelope))
    first = await generate(model, mid)
    next_reservation = first['reserved_usd']
    model.save({'provider': 'gemini', 'model': MODEL, 'usd': next_reservation + first['actual_usd'] / 2})
    with pytest.raises(TextBudgetError, match='spend limit'):
        await generate(model, mid)
    assert len(store.records(mid, 'text_call')) == 1
    store.close()


@pytest.mark.parametrize('configured_limit,requested_limit', [(3500, 1024), (128, 128)])
def test_gemini_connection_test_keeps_keys_and_content_private(tmp_path, monkeypatch, configured_limit, requested_limit):
    settings = Settings(data_dir=tmp_path, gemini_key='PRIVATE-GEMINI', text_provider='gemini', text_model=MODEL)
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=response())
    install(monkeypatch, handler)
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers['x-radar-csrf'] = client.get('/api/session').json()['csrf']
        assert client.put('/api/settings/text-model', json={'provider': 'gemini', 'model': MODEL, 'max_output_tokens': configured_limit}).status_code == 200
        result = client.post('/api/text-connection-test')
        assert result.status_code == 200 and result.json()['success']
        assert result.json()['provider'] == 'gemini' and result.json()['usage']['output_tokens'] == 37
        assert seen[0]['generationConfig']['maxOutputTokens'] == requested_limit
        assert 'PRIVATE-GEMINI' not in result.text and 'output' not in result.json()
        assert client.get('/api/missions').json() == []
        persisted = json.loads(app.state.store.rows("SELECT payload FROM records WHERE kind='text_call'")[0]['payload'])
        assert persisted['max_output_tokens'] == requested_limit
        assert persisted['reserved_usd'] == pytest.approx((persisted['reserved_input_tokens'] * .75 + requested_limit * 3.75) / 1e6)
