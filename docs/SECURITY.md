# Security and privacy boundaries

This is a single-user application for a local machine or trusted LAN. It has implemented defenses and tested failure paths; it has not undergone an independent penetration test and is not described as production-hardened.

## Secrets and local API

The backend reads only named settings from project `.env`/environment. `dotenv_values` does not copy the secret into process environment. API responses expose configured/not configured, never a key or key-derived mask. The SDK fixed direct endpoint overrides any ambient gateway setting. SDK body logging is disabled. Provider failures store only exception class/status, not raw request/response bodies. Access logs are off. Browser launch receives an allowlisted environment without credentials.

The server defaults to `0.0.0.0` for LAN access. `RADAR_HOST=127.0.0.1` restores local-only binding. The app has no user login: anyone able to reach the listening port can access saved research and initiate paid requests. It is intended for a trusted network. Host and Origin allowlists include loopback and, for LAN bindings, the request’s actual local socket IP/port supplied by Uvicorn. Arbitrary Host/forwarded headers do not add allowed origins. Host and Origin checks, Fetch Metadata checks, SameSite=Strict HttpOnly session cookie and a per-process CSRF header protect state-changing commands. A malicious remote website cannot read the session bootstrap through CORS. No credentialed wildcard CORS is installed. Request bodies are accumulated under a 1.1 MB streaming cap. Pydantic bounds counts, field lengths, finite numbers and allowable action enums.

Local operating-system users with access to this account can still read its files and run code. SQLite is not encrypted. Protect the account and disk. The private data directory is mode 0700; `.env` is ignored and should be mode 0600. Do not publish a checkout containing ignored runtime data.

## Untrusted web content

Fetched text, snippets, JSON-LD, imports and metadata never grant permissions. Jev output is constrained to prepared candidate IDs and validated for known question/answer types, candidate membership, finite values and distributions. Optional text-model output must be a bounded JSON object conforming to the task schema. It may propose questions, queries and cited claims; it cannot execute tools, invent an inspected URL or approve its own factual claims. Suspicious source instructions remain data; the deterministic action registry is the security boundary. No shell or model-generated JavaScript is available.

Text-provider credentials and custom HTTPS endpoints are configured only on the server. Settings exposes configured-state booleans and model names, never credentials or the custom endpoint. Provider/model, spend-limit changes and credential reloads that affect text generation are blocked while a run is active. Text requests disable environment proxy overrides and redirects and bound response size. Provider error bodies, raw replies and secret headers are not stored. Schema diagnostics contain field paths and error types without generated values. Strict JSON schemas for OpenAI/OpenRouter complement local validation; schema conformance does not establish factual truth.

Settings defaults to estimated per-investigation limits of $5 for Jev and $20 for the LLM. Model-specific price estimates and conservative reservations gate text requests; unknown pricing blocks them. Failed or uncertain requests keep their cost reservation and consume attempt/token allowance. Limits are local safeguards, not provider billing caps, and search charges are separate. Changing a limit or resuming research preserves recorded usage. Development requests additionally use the retained cumulative ledger, initially limited to 200 attempts and $2 shared spend; only an explicitly authorized ignored `.runtime/development-limits.json` override changes that cap. The app's ordinary spend settings do not reset or raise it.

URLs must be HTTP(S), standard ports, no userinfo, control characters, backslashes, credential-like query parameters or internal hostnames. Encoded numeric forms, IPv4/IPv6 private/link-local/reserved/multicast destinations and transition addresses are rejected. A custom resolver validates all answers and supplies the actual public IPs to the connection, preserving hostname TLS validation. DNS caching is disabled; redirects are checked hop by hop. Crawler requests have no authorization header or inherited proxy setting.

Robots are checked before page acquisition. Unknown robots errors stop that origin; denied access and rate limits stop scheduling network acquisition on it. There is no challenge solving, stealth, account borrowing or proxy rotation. Retry-After is respected by stopping rather than retrying prematurely. Crawl delays over the finite local wait allowance stop acquisition. GET can still have side effects on badly designed websites; known login/cart/checkout/logout paths are excluded from discovered navigation. Do not supply URLs for account-changing operations.

Response wire and decompressed sizes are bounded. Only identity/gzip/deflate are decoded, with bounded zlib output. XML uses defusedxml with no entity resolution. Sitemap depth is zero (flat URL sets only), at most 50 entries before further local filtering. HTML is parsed as data, not embedded into the app. Source previews use escaped React text; exported HTML escapes text and restricts links to validated sources. CSV formula prefixes are escaped.

## Browser

Chromium sandbox stays enabled. Profiles/contexts are ephemeral, without personal cookies, passwords or extensions. HTTP(S) subrequests go through the public-only fetcher via Playwright route fulfillment, with GET/HEAD and a request cap. Document redirects resolve in the validated fetcher before navigation. Responses never instruct Chromium to follow a network redirect; page-initiated top-level navigation is blocked pending a new research action. Service workers and WebSockets are blocked; downloads are canceled; known tracking hosts are denied. WebRTC non-proxied UDP and background networking are disabled. Targets are scoped to the observed DOM and its fingerprint; this build exposes only read-only navigation/inspection, not arbitrary clicks or forms.

**Remaining boundary:** the application does not provision a host firewall, network namespace or dedicated unprivileged worker user. Playwright routing plus Chromium's sandbox is stronger than a hostname regex, but it is not a complete OS egress sandbox. Browser engine vulnerabilities, unusual browser networking and future protocol behavior are residual risks. Leave rendering disabled for untrusted high-risk targets; use HTTP extraction. A screenshot is displayed through a mission-scoped UUID artifact endpoint, never an arbitrary filesystem path.

## Imports, artifacts, retention

Imports require schema and provenance; private URL analysis requires explicit opt-in. Analytics are never included in Jev state. Private import fields are omitted from default exports. Public structured counters are publisher assertions with an explicit page match and metadata path, not independent audience measurements. Imported counts do not become authenticated first-party observations.

Data, screenshots, snapshots, exports, logs, caches and development ledgers are gitignored. Default exports include bounded quotations, original links and limitations; they omit full snapshots and decision request bodies. Local source text supports reproducibility within permitted use. Retention is configured and applied explicitly in Settings. Deleting a mission removes its managed screenshots and database records and clears shared caches. The independent test-spend ledger is retained.

Tests cover private/encoded/DNS-mixed destinations, redirect rejection, real-browser private subrequest denial, decompression bombs, body/import limits, malicious text as data, unknown model actions, CSRF/origin/host rejection, artifact IDs and CSV safety. See [Development](DEVELOPMENT.md) for reproducible checks and their limits. Public hosting requires a separate authentication and isolation design; the current trusted-LAN configuration is insufficient.

## Reporting and sharing

Do not include API keys, raw provider requests, private imports, local database files or unredacted screenshots in public issues. Report a reproducible bug using synthetic public examples. If the repository enables private vulnerability reporting, use that channel for a vulnerability before public disclosure; do not send a live credential as proof.

A clean source export excludes local runtime data and Git history. Ignoring a file does not remove earlier committed copies. Review the exact archive before publishing it; see [CONTRIBUTING.md](../CONTRIBUTING.md).
