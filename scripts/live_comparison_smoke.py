"""Opt-in real reference/candidate comparison; creates a saved live mission.

Both public URLs and the goal must be supplied explicitly. This seed-only check
makes real hosted Jev requests; it is not proof of automatic market discovery.
"""
import argparse
import asyncio

from live_mission import common_arguments, run_mission, validate_arguments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    common_arguments(parser)
    parser.add_argument('--reference', required=True, help='Public reference-product URL.')
    parser.add_argument('--candidate', required=True, help='Public candidate-product URL.')
    args = parser.parse_args()
    validate_arguments(parser, args)
    if args.reference == args.candidate:
        parser.error('Supply different reference and candidate URLs.')
    detail = asyncio.run(run_mission({
        'goal': args.goal, 'reference': args.reference, 'seeds': [args.candidate],
        'lens_id': 'landscape', 'discovery_target': 1,
    }, args.port, 'live-comparison'))
    assert detail['telemetry']['completions'] > 0, 'No real Jev response completed; inspect the saved stop reason.'
    assert detail['records'].get('finding'), 'No linked finding was produced; inspect source coverage.'
    assert detail['telemetry']['searches'] == 0, 'This is explicitly a supplied-source check.'


if __name__ == '__main__':
    main()
