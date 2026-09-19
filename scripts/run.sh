#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python ]]; then
  printf 'Jev Radar is not installed. Run ./scripts/install.sh first.\n' >&2
  exit 1
fi
if [[ ! -f frontend/dist/index.html ]]; then
  printf 'The web interface is not built. Run ./scripts/install.sh first.\n' >&2
  exit 1
fi
export PYTHONPATH="$PWD/backend"
exec .venv/bin/python -m radar.run
