# Data provenance and interpretation

A mission contains an approved goal, immutable plan history, a recorded research program, bounded actions, search observations, source snapshots, evidence spans, decisions, findings, metrics, entity groupings and reviews. No seeded competitor list, video list or completed fixture mission is loaded into the live database.

## Research program

Jev selects the unit of investigation, research method, evidence priorities and discovery route using typed choices. The program links to the actual model decision, supplied options, measured request time and plan version. Application code expands those choices and the user's objective into allowlisted question/query templates; this is not free-text program generation. Explicitly customized questions remain preserved. A program defines what to investigate; it is not a finding or evidence that any result has been inspected.

When a text provider is enabled, its proposed questions and queries are separately recorded and submitted to Jev for acceptance. Provider/model identity, generation time, text-call ID and Jev approval ID remain distinct. Follow-up records identify the observed gap and the query Jev selected; the linked search action records whether it actually executed. Generated search terms and proposed explanations are never source observations.

The generated research answer includes only claims with valid current finding references and a subsequent Jev support assessment. Citations retain exact inspected excerpts and offsets. Supported means passage support, not independently established truth. Hypotheses stay qualified and recommendations are marked unperformed. Missing criteria remain explicit even if the writer omits them. A change to scope, source attribution, evidence or review hides an outdated answer. Default exports include only the current checked answer, with bounded quotations; internal answer proposals are omitted.

## Source records

Source URL, original requested URL, discovery parent/action, retrieval time, response status, normalized-text hash, normalized text/structural chunks, metadata, JSON-LD, headings/table rows, canonical claim and language are retained where that acquisition method provides them. General page publication dates are accepted from explicitly named ISO date metadata. Video publisher upload dates and search-provider page dates retain their distinct field provenance. A search-provider page date may describe publication or modification; it is not a verified upload date. Fetch time or a footer year never becomes a publication date. A missing date remains null.

Coverage records the extraction method, total/inspected passages, text truncation, excluded sections and uninspected links. HTTP source text can include hidden text; it is labeled source text. A rendered snapshot is separately labeled. A screenshot is not evidence of what Jev saw: Jev receives only the bounded text/structured state shown in its inspector.

Individual videos have a canonical platform URL as their unit identity. Search-provider metadata and an inspected original page are different observations about that item. An indexed record retains its search/result IDs, position, query, endpoint, provider observation time and measured search request duration. It does not invent a page response status or report time spent fetching media that was never fetched. Title, description, creator, duration and numeric views become exact-text evidence with native field paths. The original video, frames, audio, transcript and comments remain uninspected unless a separate permitted acquisition supplies relevant material.

Accessible page JSON-LD may supply an unambiguous matching `VideoObject`, including a publisher transcript. These appended passages retain exact offsets and publisher field paths. A different embedded video, multiple conflicting video objects or unavailable transcript is not silently substituted. The application does not transcribe audio, inspect frames or infer missing counters.

Permitted YouTube HTML may also contain literal publisher player metadata. Radar accepts descriptive fields only when `videoDetails.videoId` matches the requested and fetched video identity. Title, author, description, integer views/duration and named upload/publication dates retain their `ytInitialPlayerResponse` paths and observation time. These are publisher assertions, separate from Brave's indexed observations. A player response does not imply playback, caption acquisition or audiovisual analysis. Tokens, streaming/caption URLs and raw player objects are discarded; malformed, oversized, nonliteral or mismatched data remains unavailable.

## Findings and evidence

Each finding has a stable claim ID, subject/host entity, criterion/question, statement, exact scope, source IDs, span IDs, offsets, evidence kind, support assessment, reviewer state/note, source/retrieval dates, unknown metric period, model, rubric version and limitations. Spans must match stored normalized text exactly.

`Supported` means that the selected excerpt addresses the narrowly posed criterion. It does not transform a vendor assertion into independently verified reality. Evidence kinds distinguish company assertions, direct textual observations and user-supplied records. Conflicting assessments remain separate; comparison fields expose other finding IDs instead of silently deleting counterevidence. Rejected reviews do not modify the original model answer. Revised rubrics mark prior assessments/fields historical.

No field value is fabricated to fill a comparison. Unknown is not zero, absence across the entire website, low quality or poor business performance. Host-based grouping is a browsing convenience, not proof that similar brands or different domains share ownership. Mirrored content retains discovery paths and is excluded from additional independent assessment support.

Cross-item conclusions distinguish observed similarities, attributed explanations, hypotheses and missing evidence. Several similar titles or high view counts do not demonstrate that a hook caused reach. Claims about editing, imagery, timing or audio require material that was actually inspected. Comparisons cannot supply a missing baseline, randomization, growth history or independent causal evidence.

## Metrics and traction

Search positions are the dated positions observed in the named provider. Wikipedia search is corpus-limited; Brave positions are not Google rankings. Search-result totals are not counted as verified backlinks, mentions or audience.

Brave's native integer `video.views`, when present, is a search-index observation attributed to the provider and collection time. It may be stale and has no assumed counting window. Text such as “1.2M,” missing values and booleans are not converted into estimated counters. Publisher `VideoObject` and YouTube player counters are separate acquisition classes; digit strings are accepted as exact publisher integers, with the original field text retained. Counters from multiple periods are not collapsed into one current total. None of these classes independently establishes that an item went viral.

CSV/JSON analytics preserve provider, metric, value, unit, page/query scope, measured_at, window, country/device/language/format/topic and the importer's provenance declaration. They remain user-supplied, not authenticated API data. Missing numeric values remain null. Page-only aggregates and page/query detail have different cohorts. No cross-platform totals, inferred conversions, invented growth velocity or ROI predictions are produced.

Where JSON-LD contains Schema.org InteractionCounter, the parser requires the parent object's explicit URL/mainEntityOfPage to match the inspected page, validates an integer count and a known action type, and stores its metadata path. These are **publisher-asserted** counters observed at retrieval. A missing underlying period stays unknown. Counter snapshots without a known period are separated by observation time, rather than treated as growth measurements.

Cohorts display median, sample size, missingness and page count under matched provider/kind/unit/period/dimensions. These are descriptive collected cohorts, not causal models. The app does not issue “viral” or “high-engagement” labels on small biased samples. Commercial outcomes are unknown unless supplied. Suggested experiments are labeled hypotheses and include a verification action and a success measure, not an ROI promise.

## Modes, telemetry and replay

Live, cache, fixture and replay are distinct. Test fixtures reside in tests/temporary databases; developer-labeled inference checks are isolated under `.runtime/`. Explicit live checks retain actual fetched content and provider decisions in the operator's private workspace; these records are not part of the public source distribution.

One request can answer many questions. Attempts/reservations, completions, errors, typed answers, source counts and cache hits are counted separately. Usage/cost is counted once per response. Client round-trip, queue time, fetch, extraction, search, browser and completed run-segment wall time are separate. p95 is withheld below 20 completed live samples. Public list estimates are not verified account charges. Cache/replay is excluded from live inference latency.

Persisted event record snapshots drive replay. The replay slider reconstructs prior records without provider calls. Its header retains clearly labeled whole-run telemetry. Reviews or mutations require leaving replay; replay does not become new evidence.

Default reports retain the recorded research program, artifact assessments, cross-item patterns, linked sources, missing evidence and proposed next test. They omit entire website snapshots, full transcripts, raw model request states and private import fields. Video exports include counter/date provenance and content-access availability rather than copied transcript/description bodies. Short quotes are capped per excerpt; JSON's separate evidence excerpts are also capped per source. Longer local snapshots are for inspection and are subject to operator-managed retention and permitted use.
