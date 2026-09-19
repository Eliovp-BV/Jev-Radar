# Third-party notices

The application is an original implementation using the dependencies pinned in `requirements.lock` and `frontend/package-lock.json`. The two browser projects below were reviewed for observation/action loops, finite indexed choices, stale-target verification, typed responses and visible traces. No implementation code was copied from either repository, and neither reference application's installers or package lifecycle scripts were executed.

| Reference | Reviewed revision | Files inspected | License |
| --- | --- | --- | --- |
| [browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast) | `1231850a0bf1a0c0341fe408ef1668dbbfdfac46` | `pyproject.toml`, `questions.py`, `agent.py`, `browser.py`, license and project structure | MIT, Copyright 2026 Browser Use; retained in `licenses/jev-ultrafast-MIT.txt` |
| [jkudish/jev-browser](https://github.com/jkudish/jev-browser) | `257edfc19dfe5194c153ba94f351425630a46aeb` | `package.json`, `src/questions.ts`, `src/provider.ts`, `src/lib.ts`, license and project structure | MIT, Copyright 2026 Joey Kudish; retained in `licenses/jev-browser-MIT.txt` |

The reference projects' generative string helpers, credential/provider autodetection and broader browser actions are not part of Radar. Their README speed figures are not used as product claims.

Major dependencies: FastAPI (MIT), Uvicorn (BSD-3-Clause), official TypeSafe SDK (see installed distribution metadata), aiohttp (Apache-2.0 AND MIT metadata), HTTPX (BSD-3-Clause), Beautiful Soup (MIT), lxml (BSD), python-dotenv (BSD-3-Clause), defusedxml (PSF), Playwright (Apache-2.0), React/React DOM (MIT), Vite (MIT), TypeScript (Apache-2.0), React Flow (MIT) and Lucide React (ISC). See the exact installed metadata in `DEPENDENCY_LICENSES.json`; package license files remain in the isolated dependency trees. Chromium/FFmpeg downloads carry their own notices in the browser distribution.

No external fonts, generated concept artwork, telemetry service or paid image assets are used. The Jev Radar by Eliovp display name does not assert domain/trademark clearance.
