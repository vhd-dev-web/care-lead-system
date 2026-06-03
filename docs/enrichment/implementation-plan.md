# Implementation Plan

## Goal

Build a controlled enrichment pipeline for already scored or verified B2B shop leads. The output is a reviewable sales pipeline, not an outreach automation system.

## Phases

1. Repo baseline: project metadata, config, sample CSV, CLI.
2. Phase 1 queue: build `enrichment_queue.csv`, derive A++/A+/A/B/C quality, decide the next waterfall step, and write `clay_queue.csv` without external API calls.
3. CSV-only enrichment: normalize, dedupe, derive scores, create outreach angles.
4. Company enrichment: discover imprint/contact pages and extract firm identity.
5. Contact extraction: collect generic email, main phone, and contact form URLs.
6. Decision-maker extraction: use only clear sources for managing director or owner data.
7. Serper fallback: use targeted Google-SERP searches only for missing imprint or decision-maker evidence.
8. Firecrawl fallback: scrape only known same-domain imprint/contact URLs when local extraction confidence is low.
9. Tavily research: summarize ambiguous company or decision-maker evidence for manual review.
10. Clay result boundary: import optional Clay results only for queued A++ rows; never guess personal emails.
11. Final compliance gate: classify each lead as outreach-ready, manual review, or do-not-contact.
12. Protected export: write enriched, review, do-not-contact, outreach-ready, and Instantly-ready CSVs.
13. Tests and documentation.

## MVP Acceptance

- `python -m lead_enrichment enrich --mode csv-only --input data/samples/verified_sample.csv` works.
- `python -m lead_enrichment prepare-queue --verified data/samples/verified_sample.csv` works.
- No network request is made in `csv-only` mode.
- No network request is made by `prepare-queue`.
- Every lead receives source/confidence fields where data is enriched.
- No personal email is guessed or generated.
- No lead is outreach-ready without a compliance note.

## Later Acceptance

- `website` mode has its own limit and visits only public company pages.
- `free-website-enrich` reads `enrichment_queue.csv`, enriches only queued A/A+/A++ leads, and rewrites `enriched_master.csv`, `enrichment_review.csv`, and `clay_queue.csv`.
- Website extraction never sends forms or starts outreach.
- `serper-fallback` runs only targeted search-gap queries and respects the daily query budget.
- `firecrawl-fallback` runs only on known URLs, respects the daily page budget, and routes repeated low-confidence rows to manual review.
- `tavily-research` runs only on ambiguous rows, respects the daily credit budget, and keeps results in manual review.
- `finalize` merges optional Clay results, applies compliance rules, and writes `instantly_ready.csv` only after explicit approval.
- Register and LinkedIn fields are manual-review friendly and do not automate mass scraping.
