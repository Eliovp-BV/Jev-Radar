"""Budget checks use temporary SQLite stores and mocked transports only."""
import json
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient

from radar.api import create_app
from radar.config import Settings
from radar.jev import Jev, BudgetError, DecisionError
from radar.schemas import Limits, ResearchDefaults, TextModelSettings
from radar.storage import dumps, uid
from radar.text_model import TextModel, TextBudgetError, TextModelError
from test_text_model import setup, generate, install, envelope


def test_money_defaults_and_known_model_prices(tmp_path):
    assert Limits().usd == ResearchDefaults().limits.usd == 5
    assert TextModelSettings().usd == 20
    settings, store, _, model = setup(tmp_path)
    model.save({'provider': 'openai', 'model': 'gpt-4.1-mini'})
    config = model.config()
    assert config['usd'] == 20 and config['pricing_configured']
    assert (config['input_usd_per_million'], config['output_usd_per_million']) == (.4, 1.6)
    model.save({'provider': 'openai', 'model': 'gpt-4.1-mini-2025-04-14'})
    assert model.config()['pricing_configured']
    store.close()


async def test_unknown_model_and_invalid_prices_stop_before_request(tmp_path):
    settings, store, mid, model = setup(tmp_path)
    model.save({'provider': 'openai', 'model': 'unknown-model'})
    with pytest.raises(TextBudgetError, match='price estimates'):
        await generate(model, mid)
    assert not store.records(mid)
    for rate in (float('nan'), float('inf'), -1):
        settings.text_model = 'unknown-model'
        settings.text_input_rate = rate
        assert not model.config()['pricing_configured']
        with pytest.raises(TextBudgetError, match='price estimates'):
            await generate(model, mid)
    assert not store.records(mid)
    store.close()


def test_prices_stay_with_model_and_require_complete_pair(tmp_path):
    _, store, _, model = setup(tmp_path)
    model.save({'provider': 'openai', 'model': 'custom-one', 'input_usd_per_million': 3, 'output_usd_per_million': 4})
    assert model.config()['input_usd_per_million'] == 3
    model.save({'provider': 'openai', 'model': 'custom-two'})
    assert not model.config()['pricing_configured']
    assert model.pricing('openai', 'custom-one', store.setting('text_model'))['input_usd_per_million'] == 3
    with pytest.raises(TextModelError, match='both input and output'):
        model.save({'provider': 'openai', 'model': 'custom-two', 'input_usd_per_million': 3})
    store.close()


async def test_dollar_reservation_blocks_network_before_first_request(tmp_path):
    _, store, mid, model = setup(tmp_path)
    model.save({'provider': 'openai', 'model': 'fixture-model', 'usd': .001})
    with pytest.raises(TextBudgetError, match='spend limit'):
        await generate(model, mid)
    assert not store.records(mid)
    store.close()


async def test_usage_cost_and_failed_reservation_both_count(tmp_path, monkeypatch):
    _, store, mid, model = setup(tmp_path)
    seen = []
    def failed(request):
        seen.append(request)
        return httpx.Response(503)
    install(monkeypatch, failed)
    with pytest.raises(TextModelError):
        await generate(model, mid)
    reservation = store.records(mid, 'text_call')[0]
    assert reservation['actual_usd'] is None and reservation['reserved_usd'] > 0
    model.save({'provider': 'openai', 'model': 'fixture-model', 'usd': reservation['reserved_usd'] * 1.5})
    with pytest.raises(TextBudgetError, match='spend limit'):
        await generate(model, mid)
    assert len(seen) == 1
    model.save({'provider': 'openai', 'model': 'fixture-model', 'usd': 20})
    install(monkeypatch, lambda request: httpx.Response(200, json=envelope()))
    call = await generate(model, mid)
    assert call['actual_usd'] == pytest.approx((90 + 12*2) / 1e6)
    assert call['input_usd_per_million'] == 1 and call['output_usd_per_million'] == 2
    store.close()


async def test_missing_usage_retains_dollar_reservation(tmp_path, monkeypatch):
    _, store, mid, model = setup(tmp_path)
    install(monkeypatch, lambda request: httpx.Response(200, json=envelope(usage={})))
    call = await generate(model, mid)
    assert call['actual_usd'] is None and call['reserved_usd'] > 0
    model.save({'provider': 'openai', 'model': 'fixture-model', 'usd': call['reserved_usd'] * 1.5})
    with pytest.raises(TextBudgetError, match='spend limit'):
        await generate(model, mid)
    assert len(store.records(mid, 'text_call')) == 1
    store.close()


async def test_legacy_cost_snapshot_cannot_be_repriced_after_reconciliation(tmp_path, monkeypatch):
    _, store, mid, model = setup(tmp_path)
    old = {'id': uid(), 'provider': 'openai', 'requested_model': 'fixture-model',
           'status': 'error', 'reserved_input_tokens': 1000, 'max_output_tokens': 100,
           'reserved_tokens': 1100, 'actual_tokens': None}
    store.mutate(mid, 'fixture.legacy_call', {}, [('text_call', old)])
    install(monkeypatch, lambda request: httpx.Response(200, json=envelope()))
    await generate(model, mid)
    reconciled = next(call for call in store.records(mid, 'text_call') if call['id'] == old['id'])
    assert reconciled['reserved_usd'] == pytest.approx(.0012)
    assert reconciled['legacy_cost_estimate']
    model.save({'provider': 'openai', 'model': 'fixture-model', 'usd': .001,
                'input_usd_per_million': 0, 'output_usd_per_million': 0})
    with pytest.raises(TextBudgetError, match='spend limit'):
        await generate(model, mid)
    assert next(call for call in store.records(mid, 'text_call') if call['id'] == old['id'])['reserved_usd'] == reconciled['reserved_usd']
    store.close()


async def test_anthropic_cached_tokens_have_conservative_cost(tmp_path, monkeypatch):
    _, store, mid, model = setup(tmp_path, provider='anthropic')
    install(monkeypatch, lambda request: httpx.Response(200, json={
        'model': 'fixture-resolved', 'stop_reason': 'end_turn',
        'content': [{'type': 'text', 'text': '{"status":"connected"}'}],
        'usage': {'input_tokens': 100, 'output_tokens': 10,
                  'cache_creation_input_tokens': 30, 'cache_read_input_tokens': 20}}))
    call = await generate(model, mid)
    assert call['actual_tokens'] == 160
    assert call['actual_usd'] == pytest.approx((100 + 30*2 + 20 + 10*2) / 1e6)
    store.close()


def test_settings_spend_limits_preserve_configuration_and_old_plan(tmp_path):
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as client:
        client.headers['x-radar-csrf'] = client.get('/api/session').json()['csrf']
        assert client.get('/api/settings').json()['spend_limits'] == {'jev_usd': 5, 'text_usd': 20}
        client.put('/api/settings/text-model', json={'provider': 'openai', 'model': 'custom',
                   'input_usd_per_million': 1, 'output_usd_per_million': 2})
        mission = client.post('/api/missions', json={'goal': 'Offline budget test mission', 'limits': {'usd': 2}}).json()
        saved = client.put('/api/settings/spend-limits', json={'jev_usd': 7, 'text_usd': 25})
        assert saved.status_code == 200 and saved.json()['spend_limits'] == {'jev_usd': 7, 'text_usd': 25}
        assert saved.json()['text_model']['model'] == 'custom'
        assert saved.json()['text_model']['input_usd_per_million'] == 1
        assert app.state.store.mission(mission['id'])['plan']['limits']['usd'] == 2
        app.state.store.execute("UPDATE missions SET status='running' WHERE id=?", (mission['id'],))
        assert client.put('/api/settings/spend-limits', json={'jev_usd': 8, 'text_usd': 26}).status_code == 409
        app.state.store.execute("UPDATE missions SET status='paused' WHERE id=?", (mission['id'],))
        for invalid in ({'jev_usd': -1}, {'text_usd': 1001}, {'jev_usd': 'NaN'}):
            assert client.put('/api/settings/spend-limits', json=invalid).status_code == 422
        assert client.get('/api/settings').json()['spend_limits'] == {'jev_usd': 7, 'text_usd': 25}


@pytest.mark.parametrize('rate', [-1, float('nan'), float('inf')])
async def test_jev_invalid_prices_never_reach_network(tmp_path, rate):
    settings, store, mid, _ = setup(tmp_path)
    settings.key = 'fixture-key'
    settings.input_rate = rate
    jev = Jev(settings, store)
    with pytest.raises(DecisionError, match='price estimates'):
        await jev.ask(mid, {}, {}, 'Fixture invalid prices')
    with pytest.raises(BudgetError, match='cost reservation'):
        jev.reserve(mid, 100, rate)
    assert store.rows('SELECT * FROM reservations') == []
    store.close()


def test_development_ledger_retains_198_attempts_and_separates_new_costs(tmp_path, monkeypatch):
    import radar.jev as module
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    runtime = tmp_path/'.runtime'
    runtime.mkdir()
    path = runtime/'live-testing-ledger.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE attempts(id TEXT PRIMARY KEY,at TEXT,tokens INTEGER,usd REAL)')
        db.executemany('INSERT INTO attempts VALUES(?,?,?,?)', [(str(index), 'fixture', 100, .001) for index in range(198)])
    (runtime/'development-limits.json').write_text(dumps({'max_calls': 300, 'jev_usd': 5, 'text_usd': 20}))
    settings, store, _, _ = setup(tmp_path)
    jev = Jev(settings, store)
    jev.reserve_dev(100, .1, provider='text')
    jev.reserve_dev(100, .2)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 200
        assert db.execute("SELECT COUNT(*) FROM attempts WHERE at='fixture' AND provider='jev'").fetchone()[0] == 198
        assert db.execute("SELECT SUM(usd) FROM attempts WHERE provider='text'").fetchone()[0] == .1
    with pytest.raises(BudgetError):
        jev.reserve_dev(100, 20, provider='text')
    (runtime/'development-limits.json').write_text('{bad}')
    with pytest.raises(BudgetError, match='Invalid development'):
        jev.reserve_dev(100, .001)
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0] == 200
    store.close()


def test_original_development_caps_stay_shared_without_override(tmp_path, monkeypatch):
    import radar.jev as module
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    settings, store, _, _ = setup(tmp_path)
    jev = Jev(settings, store)
    jev.reserve_dev(100, 1.9)
    with pytest.raises(BudgetError):
        jev.reserve_dev(100, .2, provider='text')
    store.close()
