# Development

Install from the [setup guide](SETUP.md). For the complete test suite and UI checks, include the optional browser download:

```bash
./scripts/install.sh --with-browser
```

Radar uses Python/FastAPI, SQLite and React/Vite. It runs on a CPU; hosted inference requires separate provider credentials. [Architecture](ARCHITECTURE.md) describes the research loop and module boundaries.

## Build and test

```bash
./scripts/test.sh
```

This runs pytest and the TypeScript/production frontend build. Tests use temporary databases and synthetic fixtures. An automatic guard rejects unmocked Jev and text-provider clients. Browser tests use the project-local Chromium installed with `--with-browser`; they do not need provider keys. For backend checks without Chromium, run `.venv/bin/pytest -q --ignore=tests/test_browser.py`.

For a focused backend change:

```bash
.venv/bin/pytest -q tests/test_core.py
```

Avoid running a frontend build concurrently with API tests: Vite replaces `frontend/dist`, while the API mounts its generated assets.

## Interface checks

Run the relevant isolated browser check after rebuilding the frontend. These checks create temporary applications, simulate provider responses, and save screenshots under ignored `.runtime/`.

| Area | Command |
| --- | --- |
| First use, navigation and responsive layout | `.venv/bin/python scripts/ui_simplified_smoke.py` |
| Live machine, events, replay and reduced motion | `.venv/bin/python scripts/ui_stage_smoke.py` |
| Adaptive questions, evidence and answer validity | `.venv/bin/python scripts/ui_adaptive_smoke.py` |
| Company comparison | `.venv/bin/python scripts/ui_companies_smoke.py` |
| Import workflow | `.venv/bin/python scripts/ui_import_smoke.py` |
| Text-provider settings and checked answers | `.venv/bin/python scripts/ui_text_model_smoke.py` |
| Collection matrix, filters and evidence | `.venv/bin/python scripts/ui_corpus_smoke.py` |

For a read-only check of a running workspace, use `scripts/ui_smoke.py --help`. It can inspect an empty workspace or an explicitly selected investigation. `scripts/ui_lan_smoke.py --help` describes the isolated LAN check. Screenshots from a running workspace can contain private research and must remain local unless specifically reviewed for publication.

## Optional network checks

`scripts/browser_smoke.py` contacts public websites without model inference. Hosted checks are separate from normal tests and require `--allow-paid`:

```bash
.venv/bin/python scripts/connection_smoke.py --allow-paid
.venv/bin/python scripts/evaluate_jev.py --allow-paid
```

The connection check makes one model request. The evaluation may make 15 requests against developer-labeled synthetic examples. Neither inserts fixture evidence into the application's research database. A passing check verifies that tested configuration; it is not a representative accuracy or performance benchmark.

To exercise real supplied-source research, start Radar and provide your own public goal and URLs:

```bash
.venv/bin/python scripts/live_mission.py --allow-paid \
  --goal 'Compare the implementation goals described in these public documents.' \
  --url https://www.python.org/ --url https://www.rust-lang.org/
```

`scripts/live_comparison_smoke.py --help` describes the reference/candidate variant. Both create saved investigations and use real Jev requests. They are supplied-source checks, so they do not validate automatic discovery. Brave web/video availability and every text provider must be verified with the intended account; mocked protocol tests cannot establish service access or billing.

Live checks retain an independent cumulative ledger in ignored `.runtime/live-testing-ledger.sqlite`. Its initial allowance is 200 attempts and an estimated $2 across model providers. Changing application spend settings does not raise this development allowance. An explicit operator-authorized `.runtime/development-limits.json` can set `max_calls`, `jev_usd` and `text_usd`; existing usage remains counted. Never reset the ledger to regain allowance.

## Evidence and contributions

Keep fixture, cache, replay and live events distinguishable. Preserve exact source links, excerpt offsets, unknowns, review state and measured timing. A supported excerpt establishes support for that bounded claim, not independent truth or causation. See [data provenance](DATA_PROVENANCE.md), [limitations](LIMITATIONS.md) and [security](SECURITY.md).

See [Contributing](../CONTRIBUTING.md) for patch expectations and the public source export procedure. Test logs, paid-call records and operator research stay outside the repository.
