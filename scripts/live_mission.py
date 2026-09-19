"""Opt-in real research against a running local Radar; creates a saved mission.

Uses explicit public URLs, real hosted Jev requests and the retained development
ledger. Results are private runtime artifacts, never public fixtures.
"""
import argparse
import asyncio
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def common_arguments(parser):
    parser.add_argument('--allow-paid', action='store_true',
                        help='Explicitly allow paid TypeSafe requests and a new saved live mission.')
    parser.add_argument('--port', type=int, default=8787, help='Running local Radar port (default: 8787).')
    parser.add_argument('--goal', required=True, help='Research question; use only content you may send to TypeSafe.')


def validate_arguments(parser, args):
    if not args.allow_paid:
        parser.error('Live research is opt-in; pass --allow-paid to authorize paid requests and mission creation.')
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535.')


async def run_mission(plan, port, artifact_prefix='live-mission'):
    """Execute one finite seed-only plan; never retry an uncertain paid action."""
    plan.update(providers=['seed'], development_test=True, freshness='recent')
    plan['limits'] = {'max_pages': 2, 'max_calls': 12, 'max_queries': 0, 'max_depth': 0,
                      'wall_seconds': 180, 'usd': .10, 'max_tokens': 100000}
    async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}', timeout=30, trust_env=False) as client:
        response = await client.get('/api/session')
        response.raise_for_status()
        client.headers['x-radar-csrf'] = response.json()['csrf']
        response = await client.post('/api/missions', json=plan)
        response.raise_for_status()
        mid = response.json()['id']
        print('Created explicit live mission:', mid, flush=True)
        response = await client.post(f'/api/missions/{mid}/command', json={
            'action': 'start', 'idempotency_key': 'live-check-' + mid})
        response.raise_for_status()
        for _ in range(200):
            response = await client.get(f'/api/missions/{mid}')
            response.raise_for_status()
            detail = response.json()
            if detail['status'] not in ('running', 'pausing'):
                break
            await asyncio.sleep(1)
        else:
            response = await client.post(f'/api/missions/{mid}/command', json={
                'action': 'cancel', 'idempotency_key': 'live-check-timeout-' + mid})
            response.raise_for_status()
            raise RuntimeError('Wait limit reached; cancellation requested. Inspect saved state before any retry.')
    output_dir = ROOT / '.runtime'
    output_dir.mkdir(mode=0o700, exist_ok=True)
    output = output_dir / f'{artifact_prefix}-{mid}.json'
    output.write_text(json.dumps(detail, indent=2) + '\n')
    summary = {'mission_id': mid, 'status': detail['status'],
               'sources': len(detail['records'].get('source', [])),
               'findings': len(detail['records'].get('finding', [])),
               'completed_model_requests': detail['telemetry']['completions'],
               'searches': detail['telemetry']['searches'],
               'private_result': str(output.relative_to(ROOT))}
    print(json.dumps(summary, indent=2))
    return detail


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    common_arguments(parser)
    parser.add_argument('--url', action='append', required=True,
                        help='Public source URL; repeat for a second source. No search is performed.')
    parser.add_argument('--lens', choices=['open', 'landscape', 'content', 'campaign'], default='open')
    args = parser.parse_args()
    validate_arguments(parser, args)
    urls = list(dict.fromkeys(args.url))
    if len(urls) > 2:
        parser.error('This bounded smoke check accepts at most two distinct --url values.')
    asyncio.run(run_mission({'goal': args.goal, 'seeds': urls, 'lens_id': args.lens}, args.port))


if __name__ == '__main__':
    main()
