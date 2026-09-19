# Setup and configuration

Jev Radar runs locally on a normal CPU machine. Jev inference runs through TypeSafe; web discovery uses Brave Search. An optional text model helps propose research questions and write evidence-linked answers. No local model weights or GPU framework is required.

## Install

Use Linux, macOS, or a Linux environment under WSL. Install these prerequisites first:

- Python **3.11 or newer**, including `venv` and `pip` when not using `uv`.
- Node.js **22.12 or newer**, or **20.19 or newer within Node 20**, and npm. Node 21 is unsupported.
- Git if cloning the repository. Internet access is required to install dependencies and use hosted research services.

From the project directory:

```bash
./scripts/install.sh
```

The installer checks your runtime versions, creates `.venv`, installs the pinned Python and npm dependencies, builds the interface, and creates a private `.env` from `.env.example` **only if it is missing**. An existing `.env` is preserved and its permissions are restricted to its owner. No operating-system packages are installed.

If you have several Python installations, select one explicitly:

```bash
RADAR_PYTHON=python3.12 ./scripts/install.sh
```

Chromium is optional. Basic search, page fetching, research decisions and results work without it. To enable JavaScript page rendering or run the browser tests:

```bash
./scripts/install.sh --with-browser
```

This downloads Chromium into `.cache/ms-playwright/`. It keeps Chromium's sandbox enabled and does not reuse your personal browser profile. Your operating system must provide [Playwright's supported platform dependencies](https://playwright.dev/python/docs/intro#system-requirements). If a rendering request reports missing libraries or sandbox support, resolve that platform issue before enabling browser rendering in **Settings → Research defaults**. The installer does not modify the operating system for you.

## Add server-side keys

Open the project's `.env` in a local text editor. It is ignored by Git. Do not put credentials in the frontend, README, screenshots, issue reports or terminal command arguments.

| Variable | Needed for |
| --- | --- |
| `TYPESAFE_API_KEY` | Jev's research choices and evidence assessment. |
| `BRAVE_SEARCH_API_KEY` | Automatic web and video discovery from a prompt. Brave video search requires the corresponding account entitlement. |
| `OPENAI_API_KEY` | Optional OpenAI text model. |
| `GEMINI_API_KEY` | Optional Google Gemini text model, using a Google AI Studio key. `GOOGLE_API_KEY` is also accepted; `GEMINI_API_KEY` takes precedence. |
| `ANTHROPIC_API_KEY` | Optional Anthropic text model. |
| `OPENROUTER_API_KEY` | Optional OpenRouter text model. |
| `TEXT_MODEL_API_KEY`, `TEXT_MODEL_BASE_URL` | Optional OpenAI-compatible service. Configure an HTTPS API base URL on the server. |

You need only the key for the text provider you choose. A TypeSafe key alone supports investigation of supplied public URLs; prompt-only general web discovery also needs Brave Search. Jev is the decision engine, not a search index.

To find provider setup documentation, use the links under **Guide → API keys & setup** in the app or the [primary references](REFERENCES.md).

## Start and open

```bash
./scripts/run.sh
```

Open **http://127.0.0.1:8787** on the same machine, or **http://YOUR_SERVER_LAN_IP:8787** on another machine in your trusted network. The default listen address is `0.0.0.0`. Use the server's actual address in the browser. If the preferred port is occupied, the launcher selects another port and prints its address.

**There is no login.** Anyone who can reach the port can read saved research and initiate paid requests. Keep this on a trusted network. For access only from the server itself, set `RADAR_HOST=127.0.0.1` in `.env` and restart. Do not expose it directly to the internet. Run one backend process per data directory; see the [security boundaries](SECURITY.md).

The app opens on **Live → What are you looking for?** Enter a concrete research goal and start. **Research options** exposes source choices and per-run limits; ordinary prompt-based research does not require manually adding websites. A first run can still be partial when sources are inaccessible, evidence is missing or a limit is reached. The results state the stop reason and distinguish supported findings from unknowns.

After changing credentials in `.env`, use **Settings → API connections → Reload keys**. Reloading keys does not make a model request. An explicit connection test does make a small paid request. Changing the listen address, port or data directory requires a restart.

## Choose a text model

1. Add the matching key to `.env` and reload keys.
2. Open **Settings → API connections → Research text model**.
3. Select the provider and enter the model ID your account can use. For Gemini, use a bare model ID, without a URL or `models/` prefix.
4. Check the model's price estimates and request/token limits, then save.

Provider and model availability depend on your account. Known models have included price estimates; unknown models need both input and output rates before a request can run. Check these against your provider's current pricing. Radar does not silently retry a failed request or send it to another provider. Google Gemini uses Google's native structured-output API; Google Search grounding is not enabled by this connection.

The text model proposes goal-specific questions and searches, then drafts an answer from collected findings. Jev selects proposals, assesses evidence and checks the draft's claims. Without a text provider, Jev's bounded research templates and evidence assessments remain available, but there is no generated narrative answer.

Settings save the selected model separately for each provider. `TEXT_MODEL_PROVIDER` and `TEXT_MODEL_MODEL` in `.env` set an initial choice only; saved Settings selections take precedence. Provider and spend-limit changes are unavailable while research is running.

## Set limits

**Settings → Spend limits** starts at **$5 for Jev and $20 for the text model per investigation**. These are estimated ceilings, not expected charges or provider billing caps. Search charges are separate. Use your provider's account controls for a billing limit.

Radar reserves estimated cost before each model request and updates it from returned usage. Failed or interrupted requests retain their reservation because they may have been billed. Research also stops at the first applicable page, query, request, token, depth or time limit—even if its dollar allowance remains.

Jev limit changes become defaults for new investigations; saved plans retain their original limits. The text-model allowance also applies when resuming saved work and includes its previous usage. **Settings → Research defaults** controls starting limits, source providers and optional browser rendering. Existing investigations keep their saved plans.

## Other configuration

The backend reads named values from project-local `.env` and falls back to the process environment. A nonempty `.env` value takes precedence. The browser receives connection status, never the key values.

| Variable | Default / purpose |
| --- | --- |
| `RADAR_HOST` | `0.0.0.0`; use `127.0.0.1` for local-only access. |
| `RADAR_PORT` | `8787`, with fallback to an available port in the next 19 ports. |
| `RADAR_DATA_DIR` | `data/`; stores SQLite research, settings and artifacts. |
| `JEV_MODEL` | Explicit hosted Jev model ID; see `.env.example`. |
| `RADAR_CONTACT_URL` | Optional public contact URL in the crawler's user agent. |
| `RADAR_HTTP_CONCURRENCY`, `RADAR_JEV_CONCURRENCY` | Separate request limits from 1–4; both default to 4. |
| `RADAR_BROWSER_CONTEXTS` | Browser context limit from 1–2; defaults to 1. |
| `TEXT_MODEL_INPUT_USD_PER_MILLION`, `TEXT_MODEL_OUTPUT_USD_PER_MILLION` | Optional initial price estimates for the configured text model. |
| `JEV_INPUT_USD_PER_MILLION`, `JEV_OUTPUT_USD_PER_MILLION`, `JEV_PRICING_SOURCE` | Optional account-specific Jev price estimates and their source. |

Keep `.env`, `data/`, `.runtime/`, local imports and exports private. They are ignored by Git, not encrypted. Back up `.env` and the configured data directory securely. Settings provides retention controls; an exported report is a separate file and remains until you remove it. Review research exports before sharing them.

## Update and develop

Stop the server before replacing source files. Preserve your private `.env` and data directory, update the code, and rerun `./scripts/install.sh` followed by `./scripts/run.sh`. If you use browser rendering, include `--with-browser` to install the browser revision expected by the updated Playwright package.

For development:

```bash
# Full checks, including browser tests; requires --with-browser installation:
./scripts/test.sh

# Core tests without downloading Chromium:
.venv/bin/pytest -q --ignore=tests/test_browser.py

# UI development, with the backend running in another terminal:
npm --prefix frontend run dev
```

The Vite development server listens on loopback port 5173 and proxies API requests to port 8787. If the backend selects another port, adjust the proxy or use the built application. Unit tests block unmocked Jev and text-model requests. Explicit paid checks are separate; read [Contributing](../CONTRIBUTING.md) before using them.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Installer rejects Python or Node | Verify the versions above. Use `RADAR_PYTHON` to select an existing supported Python. A stale `.venv` may need to be moved aside and recreated. |
| `venv` or `pip` is missing | Install those components for your selected Python, or install `uv`, then rerun setup. |
| No automatic discoveries | Check Brave's key, account entitlement/quota and the enabled source providers. Jev alone does not search the web. |
| Missing or rejected model key | Check the exact variable name in server-side `.env`, then reload keys. Do not paste the key into an issue. |
| Unknown model pricing | Save both per-million input and output estimates for that exact provider/model in Settings. |
| Run stops early | Inspect its stop reason and usage. Money, requests, tokens and elapsed time are separate limits. Unsupported or unavailable evidence remains unknown. |
| Browser rendering fails | Run the installer with `--with-browser`, then resolve any missing Playwright platform libraries or sandbox restrictions. There is no unsandboxed fallback. |
| Site is blocked or incomplete | Read the coverage notes. Robots rules, access controls and rate limits are respected; choose another permitted source. |
| Another machine cannot connect | Use the server's actual LAN address and printed port; check `RADAR_HOST` and your network's firewall policy. |
| Local API rejects a change | Open the app on its actual listening IP and port. State-changing calls require its same-origin session and CSRF token. Arbitrary proxy aliases are not automatically accepted. |
| Interface is stale | Rerun `npm --prefix frontend run build` and restart the server. |
| A run was interrupted | Review saved activity before retrying. Restarting does not automatically repeat uncertain paid requests. |

For architecture, provenance, imports and known limits, continue with [Architecture](ARCHITECTURE.md), [Data provenance](DATA_PROVENANCE.md), and [Known limitations](../NEXT_STEPS.md).
