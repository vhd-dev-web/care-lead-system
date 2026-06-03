# Waterfall Phase 4: Firecrawl Fallback

Phase 4 adds Firecrawl as a narrow extraction helper for known URLs.

It is not used for discovery, SERP search, full-domain crawling, LinkedIn research, or outreach. It only runs when the pipeline already has a same-domain `imprint_url` or `contact_url` and local parsing produced low confidence.

## When Firecrawl Runs

The runner processes rows where:

- `provider_recommended = firecrawl`, or
- `next_enrichment_step` starts with `firecrawl_`.

Typical upstream state:

```text
free website enrichment found an imprint/contact URL
-> local HTML extraction confidence < 0.70
-> Firecrawl is planned as scrape helper
```

If Firecrawl is disabled in policy, rows stay planned for review.

## What It Calls

The adapter uses Firecrawl's v2 scrape endpoint:

```text
POST https://api.firecrawl.dev/v2/scrape
Authorization: Bearer FIRECRAWL_API_KEY
formats: ["markdown"]
```

The payload requests only Markdown from one known URL and sets `storeInCache=false` and `proxy=basic` to keep the request narrow and predictable.

## Extracted Fields

The returned Markdown is parsed with the same local extractors as Phase 2:

- `legal_name`
- `legal_form`
- `address`
- `managing_director_name`
- `general_email`
- `phone_main`
- `confidence_score`
- `firecrawl_source_url`
- `firecrawl_markdown_chars`
- `firecrawl_summary`

The runner then recalculates the waterfall decision. If the result is still low-confidence after Firecrawl, the lead moves to `manual_review` instead of looping through Firecrawl again.

## Enable Locally

Copy the example policy:

```powershell
Copy-Item config/enrichment_policy.example.json config/enrichment_policy.json
```

Enable only Firecrawl:

```json
{
  "firecrawl_daily_limit": 10,
  "providers": {
    "firecrawl": {
      "enabled": true
    }
  }
}
```

Add the key to `.env`:

```text
FIRECRAWL_API_KEY=fc-your-key
```

Run:

```powershell
$env:PYTHONPATH = "src"
python -m lead_enrichment firecrawl-fallback --queue data/output/enrichment_queue.csv --limit 5
```

or:

```powershell
.\scripts\firecrawl_fallback.ps1 -Limit 5
```

## Guardrails

- No Firecrawl search endpoint.
- No crawl or batch scrape.
- No arbitrary provider chain for every lead.
- No guessed personal email generation.
- No automatic outreach export.
- `firecrawl_daily_limit` is treated as the page/request budget.
