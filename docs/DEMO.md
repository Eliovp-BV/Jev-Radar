# Public demo: a private AI second brain

The README media shows one real, bounded investigation recorded on September 19, 2026, in a fresh, isolated workspace. No previous investigations, private imports or personal browser profile were loaded. Only the reviewed screenshots and recordings are shipped; the installation starts with an empty database.

## The question

> Find open-source AI tools that turn my documents into a private, searchable second brain. Compare local-model support, document search, self-hosting and license evidence using official sources.

This goal was entered through the normal Live prompt. No seed websites, search results, decisions or findings were preloaded. Brave Search discovered public content; TypeSafe hosted `jev-1.13.0`; OpenAI `gpt-4.1` (resolved `gpt-4.1-2025-04-14`) proposed questions and follow-up searches and drafted the cited answer. Keys stayed on the server.

Jev selected a technical-artifact comparison, accepted questions about privacy/self-hosting, document formats and license evidence, chose observed leads for inspection, assessed the retrieved material and checked the proposed answer. The live recording includes real concurrent requests. Page collection used HTTP text extraction; the demo did not use rendered-browser extraction or install any of the products being researched.

## Recorded measurements

| Measurement | This run |
| --- | ---: |
| Research wall time recorded by Radar | 47.16 seconds |
| Completed Jev requests | 34 |
| Typed answers across those requests | 186 |
| Median Jev request round trip | 932.64 ms |
| 95th-percentile Jev request round trip | 1,150.66 ms |
| Jev cache hits / request errors | 0 / 0 |
| Search responses | 3 |
| Independent retrieved documents | 11 |
| Records classified as original artifacts in the comparison matrix | 7 |
| Saved evidence assessments | 28 |
| Completed text-model requests | 4 |
| Estimated Jev cost | $0.007883 |
| Estimated text-model cost | $0.060496 |
| Estimated combined model cost | **$0.068379** |

These are measurements from one run, not a representative benchmark, latency guarantee or measured speedup against another system. Typed answers are individual structured questions, not separate network calls. Request timing includes the hosted round trip. Estimated costs use recorded usage and configured rates, exclude Brave Search fees, and may differ from invoices.

The matrix's narrower assessment subset contains 14 Jev requests and 98 typed answers. Its first-to-last assessment window is 20.09 seconds; overlapping active inference occupies 9.32 seconds. Those figures exclude other research decisions and are not the whole investigation's duration. Multiple original records can describe the same product.

## What it found—and what remains unresolved

The answer links to inspected passages from public repositories and product documentation, including [OpenDocuments](https://github.com/joungminsung/OpenDocuments), [llm-search](https://github.com/snexus/llm-search), [GPT4All](https://www.nomic.ai/gpt4all), [PrivateGPT](https://github.com/zylon-ai/private-gpt) and [Khoj](https://khoj.dev/). These are sources from the investigation, not endorsements or independently tested product recommendations.

The run finished **partial**. Its recorded stop reason was that the remaining observed original-record leads were declined and no further discovery refinement was selected. The generated answer retained qualified conclusions and missing evidence. In particular, it did not establish a complete license comparison or prove that every candidate met every requested property.

Discovery also encountered secondary and unrelated pages; not every retrieved page became a comparison record. Source classification can be wrong. No software was installed, privacy guarantee independently audited, license legally assessed, popularity measured or exhaustive market search performed. Keep these limits in mind when reading the screenshots.

## Reproduce the workflow

1. Follow [Setup](SETUP.md), add TypeSafe and Brave keys, and configure a text model.
2. In Research defaults, use a target of 4, at most 12 pages, 60 Jev requests, 5 searches, depth 1 and 300 seconds.
3. Keep the $5 Jev / $20 text-model ceilings. The text-model limits were 6 requests, 3,500 output tokens per request and 120,000 total reserved/used tokens.
4. Enter the question above on Live. Open Results and follow the source passages and recorded decisions.

For this recording, the isolated workspace also had a 650,000-token Jev allowance and a 6-page per-domain limit configured in its backend before the prompt was entered. These two advanced values are not currently editable in the interface; developers can set them through the research-defaults API. The standard token allowance is 250,000, so a default installation can stop earlier. No research decisions or evidence were configured this way.

A fresh run makes paid provider requests. Results can change with search ranking, source content, provider behavior and model versions. The recording is a saved observation, not an expected-output fixture.

## Media provenance

- `radar-home.png`: the real starting screen before entering the goal; its displayed limits are the demo's settings.
- `radar-live.png`: an actual screenshot with two Jev requests in flight.
- `radar-results.png`: the real result screen, including its partial status and qualified conclusions.
- `radar-demo.mp4`: a continuous 30-second excerpt (capture seconds 1.5–31.5) at normal speed, re-encoded to 1280×800 / 24 fps for size and compatibility.
- `radar-demo.gif`: capture seconds 8–20 at normal speed, downscaled to 800×500 / 10 fps for the README.

There are no fabricated UI overlays, substituted metrics or generated screenshots. Media metadata is stripped and the public exporter requires exact file hashes in `media-review.json`. Credentials, databases, raw recordings, provider payloads and previous research remain excluded from the public source package.
