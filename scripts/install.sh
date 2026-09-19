#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

usage() {
  cat <<'USAGE'
Usage: ./scripts/install.sh [--with-browser]

Install pinned dependencies, build the app and create .env if it is missing.
Requires Python 3.11+, Node.js ^20.19.0 or >=22.12.0, and npm.

  --with-browser  Also download project-local Chromium for optional rendering
                  and browser tests. No operating-system packages are installed.
  -h, --help      Show this help.

Set RADAR_PYTHON to select a Python executable. Existing .env values are kept.
USAGE
}

with_browser=0
for argument in "$@"; do
  case "$argument" in
    --with-browser) with_browser=1 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$argument" >&2; usage >&2; exit 2 ;;
  esac
done

fail() { printf 'Setup stopped: %s\n' "$1" >&2; exit 1; }

if [[ -z "${RADAR_PYTHON:-}" ]]; then
  for candidate in python3.12 python3 python3.14 python3.13 python3.11; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
      RADAR_PYTHON="$candidate"
      break
    fi
  done
fi
[[ -n "${RADAR_PYTHON:-}" ]] || fail 'Install Python 3.11+ and rerun this command.'
command -v "$RADAR_PYTHON" >/dev/null 2>&1 || fail 'RADAR_PYTHON does not identify an available executable.'
"$RADAR_PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 11))' ||
  fail 'Python 3.11+ is required. Set RADAR_PYTHON to a supported executable.'
command -v node >/dev/null 2>&1 || fail 'Install Node.js 22.12+ (or 20.19+) and npm, then rerun this command.'
node -e 'const [major, minor] = process.versions.node.split(".").map(Number); if (!((major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22)) process.exit(1)' ||
  fail 'Node.js must satisfy ^20.19.0 or >=22.12.0. Node.js 21 is not supported.'
command -v npm >/dev/null 2>&1 || fail 'npm is missing. Install it with your Node.js distribution.'

if [[ -e .venv && ! -x .venv/bin/python ]]; then
  fail '.venv exists but has no working Python. Move it aside and rerun setup.'
fi
if [[ -x .venv/bin/python ]]; then
  .venv/bin/python -c 'import sys; sys.exit(sys.version_info < (3, 11))' ||
    fail 'The existing .venv uses an unsupported Python. Move it aside and rerun setup.'
else
  if command -v uv >/dev/null 2>&1; then
    uv venv --python "$RADAR_PYTHON" .venv
  else
    "$RADAR_PYTHON" -m venv .venv ||
      fail 'Could not create .venv. Your Python installation needs the venv and pip modules.'
  fi
fi

if command -v uv >/dev/null 2>&1; then
  uv pip sync requirements.lock --python .venv/bin/python
else
  .venv/bin/python -m pip install -r requirements.lock
fi
npm --prefix frontend ci --ignore-scripts
npm --prefix frontend run build

if [[ ! -e .env ]]; then
  (umask 077; set -o noclobber; cat .env.example > .env)
fi
chmod 600 .env

if [[ "$with_browser" -eq 1 ]]; then
  PLAYWRIGHT_BROWSERS_PATH="$PWD/.cache/ms-playwright" .venv/bin/playwright install chromium ||
    fail 'The core app is installed, but Chromium download failed. Rerun with --with-browser when ready.'
fi

cat <<'NEXT'

Jev Radar is installed.
1. Edit the project-local .env: add TYPESAFE_API_KEY and BRAVE_SEARCH_API_KEY.
2. Start the app: ./scripts/run.sh
3. Open the address printed by the launcher.

Existing .env values were preserved. Keys stay on the server.
Optional browser rendering: rerun ./scripts/install.sh --with-browser.
Setup, provider choices and troubleshooting: docs/SETUP.md
NEXT
