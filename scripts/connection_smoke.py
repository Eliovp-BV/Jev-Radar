"""Opt-in single paid TypeSafe connection check using clearly synthetic text.

Keeps actual usage/timing in ignored .runtime, uses the cumulative development
ledger and never inserts a finding into the application research database.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from radar.config import Settings, ROOT
from radar.storage import Store, now, uid, dumps
from radar.jev import Jev
from radar.schemas import Plan
from typesafe_sdk import Choice, Score, Noul


async def check():
    settings = Settings.load()
    settings.dev_testing = True
    if not settings.key:
        raise SystemExit('TYPESAFE_API_KEY is not configured server-side; no request made.')
    output_dir = ROOT / '.runtime'
    output_dir.mkdir(mode=0o700, exist_ok=True)
    store = Store(output_dir / 'connection.sqlite')
    mid = uid()
    plan = Plan(goal='Synthetic typed-decision connection check', development_test=True,
                limits={'max_calls': 1, 'max_pages': 1, 'max_queries': 0}).model_dump()
    store.execute('INSERT INTO missions VALUES(?,?,?,?,?,?,?,?,?)',
                  (mid, plan['goal'], 'draft', dumps(plan), 1, now(), now(), None, 'system'))
    jev = Jev(settings, store)
    result = {'tested_at': now(), 'provider': 'TypeSafe direct',
              'requested_model': settings.model, 'source_mode': 'synthetic connection fixture'}
    try:
        decision = await jev.ask(mid,
            {'fixture_text': 'ExampleTool is a programming language used to build small applications.'},
            {'category': Choice(instructions='What is ExampleTool described as?', criteria={
                'language': 'A programming language', 'hardware': 'A hardware product', 'unknown': 'Not specified'}),
             'relevance': Score(instructions='How explicitly does this excerpt describe a programming language?',
                                criteria=['Not described', 'Indirectly suggested', 'Explicitly described']),
             'mentions_language': Noul(instructions='Does the fixture explicitly describe ExampleTool as a programming language?')},
            'Synthetic-text connection test', cache=False)
        result.update(success=True, resolved_model=decision['model'], answers=decision['answers'],
                      usage=decision['usage'], latency_ms=decision['latency_ms'],
                      estimated_usd=decision['estimated_usd'])
    except Exception as exc:
        result.update(success=False, error=type(exc).__name__, http_status=getattr(exc, 'status_code', None))
    finally:
        store.close()
    (output_dir / 'connection-test.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return result['success']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-paid', action='store_true', help='Allow one real paid TypeSafe request.')
    args = parser.parse_args()
    if not args.allow_paid:
        parser.error('Live connection testing is opt-in; pass --allow-paid to authorize the request.')
    raise SystemExit(0 if asyncio.run(check()) else 1)


if __name__ == '__main__':
    main()
