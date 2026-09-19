# Limitations

Radar is a single-user research workspace. It collects public evidence, applies goal-specific questions with Jev and keeps the resulting choices inspectable. An investigation can finish partial when access, evidence or its configured limits prevent a complete answer.

## Discovery and coverage

- Automatic web/video discovery requires a Brave Search key and the relevant account entitlement. Jev makes research decisions; it does not supply a web index. Wikipedia searches its encyclopedia corpus only.
- Finite searches and inspected pages cannot establish that every competitor, artifact or relevant source has been found. Search visibility is specific to the provider and collection time; it is not market share, traffic, popularity or Google rank.
- Generated questions and queries can be unhelpful, and providers can fail or return no relevant cases. Schema validation checks the format of an answer, not its quality. The application records explicit declines, missing evidence and stop reasons.

## What Radar can inspect

Acquisition supports bounded public HTML/text, permitted rendered pages, flat sitemaps, indexed video metadata and supported publisher metadata. Access restrictions and robots rules can prevent acquisition. PDFs, paywalls, nested sitemap indexes and signed-in browsing are unsupported.

Video records can contain a title, description, creator, date and public counter when actually supplied by the source. A transcript is available only if supported accessible page content includes it. Radar does not download videos, inspect frames/audio, fetch hidden caption endpoints or transcribe speech. Metadata alone cannot establish what happened in a video or why it spread.

Browser actions are bounded read-only navigation, inspection and screenshots. The application does not expose general click/type automation, use personal browser profiles or execute model-written programs. Prose time windows guide research but are not strict search-provider date filters.

## Interpreting results

Source claims remain attributed to their sources. A supported finding means the cited excerpt addresses the question; it does not independently verify a vendor claim. Missing values remain unknown. Imports are user-supplied observations, not authenticated analytics connections.

Cross-item patterns describe the collected sample. Similar titles, large counters or search positions do not demonstrate causation, growth or business impact. Proposed improvements are experiments to review, with uncertainty and suggested measures; Radar does not carry them out.

An optional text model proposes research questions/searches and drafts cited conclusions. Jev selects proposals and checks claim support. Models can still misclassify a source or assess a passage incorrectly. Review the underlying evidence before making consequential decisions.

## Costs and performance

Displayed costs are estimates from configured model rates and recorded usage. Failed or interrupted requests can retain a conservative reservation. Search fees are separate. Local limits are safeguards, not provider billing caps.

Jev timings measure completed requests from this client. Search, acquisition, text generation, queueing and the whole investigation have separate timings. Cache and replay do not become new live samples. Radar does not claim a speedup against an unmeasured baseline or reproduce third-party demonstrations' cost/volume figures.

## Deployment and scope

The default server listens on the trusted LAN and has no login. Anyone who can reach it can read research and initiate requests. Public multi-user hosting requires a separate authentication and isolation design. Chromium's sandbox and validated acquisition do not replace operating-system egress isolation. See [security boundaries](SECURITY.md).

Scheduled monitoring, multiple accounts, automatic publishing/outreach and model training are outside the current scope. Improvements are welcome through the [contribution process](../CONTRIBUTING.md).
