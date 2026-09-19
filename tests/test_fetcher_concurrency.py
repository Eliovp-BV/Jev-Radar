"""Queued acquisition must observe a sibling request's access denial."""
import asyncio
from unittest.mock import AsyncMock
from urllib.robotparser import RobotFileParser

import pytest

from radar.acquisition import Fetcher
from radar.security import PolicyError


@pytest.mark.parametrize('status',[401,403,429])
async def test_sibling_denial_during_crawl_delay_stops_waiting_request(monkeypatch,status):
    fetcher=Fetcher();origin='https://example.org'
    robots=RobotFileParser();robots.parse(['User-agent: *','Allow: /'])
    fetcher.robots[origin]=robots
    first_entered=asyncio.Event();finish_first=asyncio.Event()
    delay_entered=asyncio.Event();finish_delay=asyncio.Event();requests=[]
    async def single(url):
        requests.append(url)
        first_entered.set()
        await finish_first.wait()
        return {'url':url,'status':status,'headers':{},'body':b''}
    async def delayed_sleep(delay):
        assert delay>0
        delay_entered.set()
        await finish_delay.wait()
    fetcher.single=single
    monkeypatch.setattr('radar.acquisition.asyncio.sleep',delayed_sleep)
    first=asyncio.create_task(fetcher.get(origin+'/first'))
    await first_entered.wait()
    second=asyncio.create_task(fetcher.get(origin+'/second'))
    await delay_entered.wait()
    finish_first.set()
    with pytest.raises(PolicyError,match='Access blocked'):
        await first
    finish_delay.set()
    with pytest.raises(PolicyError,match='Origin stopped'):
        await second
    assert requests==[origin+'/first'] and origin in fetcher.denied


async def test_denial_while_waiting_for_origin_lock_prevents_robots_fetch():
    fetcher=Fetcher();origin='https://example.org'
    lock=asyncio.Lock();fetcher.locks[origin]=lock
    await lock.acquire()
    fetcher.raw=AsyncMock(return_value={'status':404,'body':b''})
    waiting=asyncio.create_task(fetcher.permitted(origin+'/queued'))
    await asyncio.sleep(0)
    fetcher.denied.add(origin);lock.release()
    with pytest.raises(PolicyError,match='Origin stopped'):
        await waiting
    fetcher.raw.assert_not_awaited()


async def test_denial_while_waiting_for_global_slot_prevents_network(monkeypatch):
    fetcher=Fetcher(concurrency=1);origin='https://example.org'
    await fetcher.sem.acquire()
    def forbidden_session(*args,**kwargs):
        raise AssertionError('A denied origin must not create a network session')
    monkeypatch.setattr('radar.acquisition.aiohttp.ClientSession',forbidden_session)
    waiting=asyncio.create_task(fetcher.single(origin+'/queued'))
    await asyncio.sleep(0)
    fetcher.denied.add(origin);fetcher.sem.release()
    with pytest.raises(PolicyError,match='Origin stopped'):
        await waiting
