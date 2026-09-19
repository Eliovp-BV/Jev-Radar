# Contributing

Install using the [setup guide](docs/SETUP.md), then read [Architecture](docs/ARCHITECTURE.md) and [Development](docs/DEVELOPMENT.md). Radar is distributed under the [MIT License](LICENSE).

## Make a change

1. Keep the change focused and document user-visible behavior or limitations.
2. Preserve source provenance, explicit unknowns and the distinction between fixtures, cache, replay and live requests. Do not introduce scripted research outcomes or invented telemetry.
3. Run `./scripts/test.sh`. For interface changes, run the relevant isolated browser check listed in [Development](docs/DEVELOPMENT.md) and inspect its screenshots.
4. Describe the behavior tested and any material gap. Provider mocks do not establish live account access or research accuracy.

Use clearly labeled synthetic examples for bugs and tests. Keep credentials in the ignored server `.env`. Local research records, imports, databases, provider responses and ordinary screenshots/exports must stay out of patches. New public demonstration media needs explicit review of every visible label and source; never copy an operator workspace wholesale.

Paid checks require `--allow-paid` and retain their cumulative development ledger. They are not part of normal tests. Browser changes must preserve sandboxing, public-address validation, access restrictions and bounded actions. Model output must not gain arbitrary execution, external messaging or publishing permissions.

## Prepare a source distribution

Use the exporter when sharing a clean source snapshot, especially from a checkout that has ever contained private work:

```bash
# Review and stage intended public files before exporting.
python3 scripts/export_public.py --check
python3 scripts/export_public.py --output .runtime/public-export/jev-radar-source.tar.gz
```

The exporter reads current tracked working-tree files, including uncommitted edits. It does not read historical blobs or copy Git identity/history. New public files must be staged before inclusion. The path and content policy rejects private directories, environment files other than `.env.example`, symlinks, submodules, missing required files and common accidental private content. Reviewed demo assets have their own restricted policy; ordinary screenshots remain excluded.

The archive contains `Jev-Radar/` and a SHA-256 `SOURCE_MANIFEST.json`. File order, timestamps and archive ownership are normalized. The manifest is an ignored distribution inventory, not source history. `--force` explicitly replaces an existing archive.

Inspect the extracted source, dependency notices and approved media, then run the documented installation/checks from that clean copy. Automated scanning cannot prove that all private or third-party material was removed. If creating a new repository, initialize it inside the reviewed extracted source; never copy the original `.git` directory. The exporter does not publish or rewrite history.

Use the issue templates for bug reports and feature requests. Follow [Security](docs/SECURITY.md) for sensitive reports and omit credentials or private research from disclosures.
