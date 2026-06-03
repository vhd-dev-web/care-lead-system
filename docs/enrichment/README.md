# VHD Lead Enrichment

Controlled lead enrichment for verified WooCommerce/B2B leads.

The project starts after scraping and scoring. It turns verified leads into a small, reviewable sales pipeline with source evidence, confidence scores, and compliance gates. It is not an automated outreach sender.

## Pipeline

```text
raw_leads
-> normalized_companies
-> company_enriched
-> decision_maker_enriched
-> compliance_reviewed
-> outreach_ready | manual_review | do_not_contact
```

## MVP

Version 0.1 supports:

- CSV import from scored or verified leads.
- Domain normalization and deduplication.
- CSV-only enrichment without network requests.
- Shop, pain, potential, and priority scoring.
- Conservative outreach angle generation.
- GDPR/UWG review notes.
- CSV exports for enriched, review, and outreach-ready leads.
- Prepared modules for website/imprint enrichment.

The MVP does not:

- guess personal email addresses,
- scrape LinkedIn,
- submit contact forms,
- send outreach,
- blindly trust third-party directories.

## Quick Start

```powershell
cd .\vhd-lead-enrichment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
python -m lead_enrichment enrich --mode csv-only --input data\samples\verified_sample.csv
pytest
```

Phase 1 queue preparation:

```powershell
python -m lead_enrichment prepare-queue --verified data\samples\verified_sample.csv
```

Phase 2 free website enrichment:

```powershell
python -m lead_enrichment free-website-enrich --queue data\output\enrichment_queue.csv --limit 5
```

Phase 3 Serper fallback:

```powershell
python -m lead_enrichment serper-fallback --queue data\output\enrichment_queue.csv --limit 5
```

Phase 4 Firecrawl fallback:

```powershell
python -m lead_enrichment firecrawl-fallback --queue data\output\enrichment_queue.csv --limit 5
```

Phase 5 Tavily research:

```powershell
python -m lead_enrichment tavily-research --queue data\output\enrichment_queue.csv --limit 3
```

Phase 6 final compliance gate:

```powershell
python -m lead_enrichment finalize --queue data\output\enrichment_queue.csv
```

Full orchestrated waterfall:

```powershell
python -m lead_enrichment run-waterfall --verified data\samples\verified_sample.csv
```

Without installation:

```powershell
$env:PYTHONPATH = "src"
python -m lead_enrichment enrich --mode csv-only --input data\samples\verified_sample.csv
```

Outputs:

```text
data/output/enrichment_queue.csv
data/output/clay_queue.csv
data/output/enriched_master.csv
data/output/enrichment_review.csv
data/output/outreach_ready.csv
data/output/compliance_review.csv
data/output/do_not_contact.csv
data/output/instantly_ready.csv
data/output/runs/enrichment_YYYYMMDD_HHMMSS.csv
```

## Phase 1 Waterfall

`prepare-queue` is the cost-control layer before provider enrichment. It makes no external API calls and writes:

- `enrichment_queue.csv`: all queued leads with `lead_quality`, `next_enrichment_step`, and provider recommendation.
- `clay_queue.csv`: only A++ leads that have reached the Clay email-enrichment condition.

Lead quality:

```text
A++ = WooCommerce + score >= 85 + clear shop lever
A+  = WooCommerce + score >= 70
A   = shop + score >= 60
B   = review or weaker shop
C   = not enrichment-worthy
```

Provider calls are disabled by default through `config/enrichment_policy.example.json`. Copy it to `config/enrichment_policy.json` for local settings; that local file is gitignored.

## Phase 2 Free Website Enrichment

`free-website-enrich` processes only queue rows whose `next_enrichment_step` is `free_website_enrichment`.

It visits only known public company pages such as:

```text
/
/impressum
/imprint
/kontakt
/contact
/datenschutz
/ueber-uns
/team
```

It extracts company/legal name, legal form, address, managing director or owner, generic email, main phone, imprint URL, contact URL, source URLs, and a confidence score. After extraction it recalculates the next waterfall step. Provider fallbacks remain only planned until later phases.

## Phase 3 Serper Fallback

`serper-fallback` processes only rows where Serper is the recommended provider. It is for targeted search gaps, not broad enrichment.

Typical queries:

```text
site:domain.de impressum
"domain.de" impressum
site:domain.de "Geschaeftsfuehrer"
"Firmenname GmbH" Geschaeftsfuehrer
```

Serper is disabled by default. To execute real queries, create `config/enrichment_policy.json` from the example and set:

```json
{
  "providers": {
    "serper": {
      "enabled": true
    }
  }
}
```

Then add `SERPER_API_KEY` to `.env`. Tests use fake responses and never call Serper.

## Phase 4 Firecrawl Fallback

`firecrawl-fallback` processes only rows where Firecrawl is the recommended provider. It does not search the web and does not crawl whole domains. It scrapes one known same-domain `imprint_url` or `contact_url` and parses the returned Markdown with the local extractors.

Firecrawl is disabled by default. To execute real requests, create `config/enrichment_policy.json` from the example and set:

```json
{
  "providers": {
    "firecrawl": {
      "enabled": true
    }
  }
}
```

Then add `FIRECRAWL_API_KEY` to `.env`. The adapter targets Firecrawl's v2 `/scrape` endpoint and keeps the request narrow: `formats=["markdown"]`, `storeInCache=false`, `proxy=basic`. Tests use fake Markdown responses and never call Firecrawl.

## Phase 5 Tavily Research

`tavily-research` processes only rows where Tavily is the recommended provider. It is for ambiguous company or decision-maker cases, not for standard enrichment. The runner creates a research summary, source URLs, and a confidence score for manual review.

Tavily is disabled by default. To execute real requests, create `config/enrichment_policy.json` from the example and set:

```json
{
  "providers": {
    "tavily": {
      "enabled": true
    }
  }
}
```

Then add `TAVILY_API_KEY` to `.env`. The adapter targets Tavily's `/search` endpoint with `search_depth=basic`, `include_answer=basic`, `include_usage=true`, and `auto_parameters=false` so the credit use stays predictable. Tests use fake responses and never call Tavily.

## Phase 6 Final Gate

`finalize` applies the final compliance and outreach gate. It makes no provider calls and sends nothing. Optional manual Clay results can be merged before gating:

```powershell
python -m lead_enrichment finalize `
  --queue data\output\enrichment_queue.csv `
  --clay-results data\samples\clay_results_sample.csv
```

It writes:

```text
data/output/compliance_review.csv
data/output/enrichment_review.csv
data/output/outreach_ready.csv
data/output/do_not_contact.csv
data/output/instantly_ready.csv
```

`instantly_ready.csv` is protected by explicit approval. A row only appears there when `outreach_approved=true`, `outreach_channel=email`, `do_not_contact=false`, a syntactically valid `personal_email` exists, and `email_verification_status` is `verified`, `valid`, or `deliverable`.

## Orchestrated Waterfall

`run-waterfall` connects the phases:

```text
prepare-queue
-> free-website-enrich
-> enabled provider fallbacks
-> finalize
```

Providers are only called when rows are queued for that provider, the provider is enabled in `config/enrichment_policy.json`, and the daily budget is greater than zero. API keys alone do not activate a provider.

No-request control run:

```powershell
python -m lead_enrichment run-waterfall `
  --verified data\samples\verified_sample.csv `
  --skip-website `
  --skip-providers
```

The orchestrator writes a run summary to:

```text
data/output/runs/waterfall_summary_YYYYMMDD_HHMMSS.json
```

## Operating Rule

Keep budgets separate:

- Search budget finds new domains.
- Scoring budget verifies shop fit.
- Enrichment budget reads only the minimum data needed for firm identity, generic contact paths, and review.

When scoring is exhausted, run only `csv-only` enrichment.

## Legal Guardrails

This project encodes operational guardrails, not legal advice. In Germany, the relevant review points include section 7 UWG for advertising channels, Art. 6(1)(f) GDPR for legitimate interest balancing, and GDPR recital 47 for direct-marketing context. Each outreach-ready lead must include a concrete business relevance note and a recommended conservative contact channel.
