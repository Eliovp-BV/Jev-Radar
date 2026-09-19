# Primary references

These links describe the APIs and concepts used by the implementation. Provider documentation, service availability and account terms can change independently of this repository. Pinned software dependencies are recorded in the lockfiles; a software license does not grant service access or replace provider agreements.

## TypeSafe and typed decisions

- [Introduction](https://docs.typesafe.ai/introduction), [models](https://docs.typesafe.ai/models), [primitives](https://docs.typesafe.ai/primitives), [Choice](https://docs.typesafe.ai/primitives/choice), [confidence](https://docs.typesafe.ai/confidence) and [Jev 1.13 limitations](https://docs.typesafe.ai/model-jaggedness/jev-1.13).
- [Python async SDK](https://docs.typesafe.ai/sdk/python/api/clients/async), [response contracts](https://docs.typesafe.ai/sdk/python/api/types/responses) and [legal index](https://docs.typesafe.ai/legal).

Radar uses the official SDK, explicit model selection, typed `Choice`/`Score`/`Noul` questions, actual response model/usage fields and disabled SDK retries. Local candidate and payload bounds are deliberately smaller than provider maxima. Pricing inputs produce client-side estimates; verify current account rates independently.

## Public acquisition

- [Brave Search API quickstart](https://api-dashboard.search.brave.com/documentation/quickstart) and [web-search API](https://api-dashboard.search.brave.com/app/documentation/web-search). The adapter uses the official endpoint and explicit API key; this is Radar's general-web discovery provider.
- [Brave video search API](https://api-dashboard.search.brave.com/api-reference/videos/video_search/get). The video adapter reads individual indexed video records from the official `/res/v1/videos/search` endpoint. Native fields include duration, integer views, creator, publisher and provider page dates when available. They are indexed metadata, not a transcript or proof of watched footage; endpoint entitlement depends on the account.
- [MediaWiki search API](https://www.mediawiki.org/wiki/API:Search), [API etiquette](https://www.mediawiki.org/wiki/API:Etiquette) and [Wikimedia user-agent policy](https://foundation.wikimedia.org/wiki/Policy:User-Agent_policy). Wikipedia is a bounded encyclopedia corpus, not a replacement for general-web search.
- [Playwright Python installation](https://playwright.dev/python/docs/intro). Radar uses project-local Chromium with ephemeral contexts and application network restrictions.

Access challenges, robots restrictions and rate limits are blockers. Browser automation is not a guarantee of search access and does not justify challenge bypass, personal-profile reuse or hidden provider retries.

## Optional text generation

- [OpenAI chat completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create): explicit model, strict JSON-schema response mode and bounded completion tokens.
- [Google Gemini generateContent](https://ai.google.dev/api/generate-content), [structured output](https://ai.google.dev/gemini-api/docs/structured-output) and [pricing](https://ai.google.dev/gemini-api/docs/pricing): native header-authenticated requests, schema-bound output and billed thinking-token accounting.
- [Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create): bounded nonstreaming messages and explicit stop/usage metadata.
- [OpenRouter API reference](https://openrouter.ai/docs/api_reference/overview): normalized chat-completions protocol and explicit provider/model selection.

Radar validates generated objects against task-specific schemas and then uses Jev to select research proposals and check cited claims. API conformance tests use mock transports. A configured key is not evidence of current model access, billing terms or research quality; compatible endpoints may differ in supported parameters.

## Evidence and metrics

- [Schema.org InteractionCounter](https://schema.org/InteractionCounter) and [interactionStatistic](https://schema.org/interactionStatistic). Parsed counters remain publisher assertions with recorded page scope and observation time.
- [Schema.org VideoObject](https://schema.org/VideoObject). Matching fetched-page objects may provide description, duration, upload date and a publisher transcript. The parser retains source paths and exact text, rejects ambiguous or unrelated embedded objects, and performs no audiovisual inference.
- [Google helpful content](https://developers.google.com/search/docs/fundamentals/creating-helpful-content), [ranking systems](https://developers.google.com/search/docs/appearance/ranking-systems-guide), [AI features guidance](https://developers.google.com/search/docs/fundamentals/ai-optimization-guide) and [Search Analytics query](https://developers.google.com/webmaster-tools/v1/searchanalytics/query). These inform labels and limitations; Radar does not infer a proprietary ranking factor, authenticated analytics connection or causal content score.

## Architecture references

The [Jev ecosystem review](JEV_ECOSYSTEM.md) records the current Jevable follow-up, verified repository revisions/licenses, practical fit, and which ideas are implemented or remain future work.

- [FastAPI](https://fastapi.tiangolo.com/) and [React Flow](https://reactflow.dev/).
- [Jev Search (`superagents-lab/jev-search`)](https://github.com/superagents-lab/jev-search) is a primary example of typed intent selection, web search and relevance ranking with incremental result updates. Its default setup uses your own Search1API and TypeSafe keys; optional Jev providers require their own service access. It was reviewed as a workflow reference; no code was copied or installed, and Radar continues to use its configured search adapter.
- [`jev-ultrafast` agent](https://github.com/browser-use/jev-ultrafast/blob/1231850a0bf1a0c0341fe408ef1668dbbfdfac46/jev_ultrafast/agent.py), [model](https://github.com/browser-use/jev-ultrafast/blob/1231850a0bf1a0c0341fe408ef1668dbbfdfac46/jev_ultrafast/model.py) and [browser](https://github.com/browser-use/jev-ultrafast/blob/1231850a0bf1a0c0341fe408ef1668dbbfdfac46/jev_ultrafast/browser.py). The finite observed-target loop informed review; the reference implementation is not installed as Radar's runtime and provides no search index. Its profile, text-helper and retry behavior are not inherited.

Reviewed revisions and retained license notices are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). No reference-project speed claim is a Radar benchmark.
