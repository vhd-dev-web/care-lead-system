# Waterfall Phase 5: Tavily Research

Phase 5 adds Tavily as a narrow research helper for ambiguous cases.

It is not the default enrichment source. It does not search every lead, enrich contact data at scale, scrape LinkedIn, or create outreach-ready records. It produces a short research note and sources for manual review when the company or decision maker is unclear.

## When Tavily Runs

The runner processes rows where:

- `provider_recommended = tavily`, or
- `next_enrichment_step` starts with `tavily_`.

Typical upstream state:

```text
free enrichment / Serper / Firecrawl produced usable evidence
-> company operator or decision maker remains ambiguous
-> Tavily creates a compact research summary
-> manual review decides the final source of truth
```

## What It Calls

The adapter uses Tavily's Search API:

```text
POST https://api.tavily.com/search
Authorization: Bearer TAVILY_API_KEY
```

The payload keeps cost predictable:

```json
{
  "search_depth": "basic",
  "include_answer": "basic",
  "include_raw_content": false,
  "include_usage": true,
  "auto_parameters": false,
  "country": "germany"
}
```

The official docs note that `basic`, `fast`, and `ultra-fast` search depths cost 1 API credit, while `advanced` costs 2 credits. Auto-parameters can also increase cost, so this runner keeps them off.

## Extracted Fields

The Tavily response is stored as review evidence:

- `tavily_used`
- `tavily_queries`
- `tavily_result_urls`
- `tavily_answer`
- `tavily_summary`
- `tavily_confidence_score`
- `tavily_credits`
- `research_note`

If the answer/snippets clearly name a legal entity or decision maker and the local field is empty, the runner may prefill:

- `legal_name`
- `legal_form`
- `managing_director_name`
- `managing_director_source = tavily_research`

That does not make the lead outreach-ready. Ambiguous rows move to `manual_review` after Tavily instead of looping through the provider again.

## Enable Locally

Copy the example policy:

```powershell
Copy-Item config/enrichment_policy.example.json config/enrichment_policy.json
```

Enable only Tavily:

```json
{
  "tavily_daily_limit": 5,
  "providers": {
    "tavily": {
      "enabled": true
    }
  }
}
```

Add the key to `.env`:

```text
TAVILY_API_KEY=tvly-your-key
```

Run:

```powershell
$env:PYTHONPATH = "src"
python -m lead_enrichment tavily-research --queue data/output/enrichment_queue.csv --limit 3
```

or:

```powershell
.\scripts\tavily_research.ps1 -Limit 3
```

## Guardrails

- Tavily is only for ambiguous entity or decision-maker research.
- `tavily_daily_limit` is treated as the credit/query budget.
- No raw-content extraction by default.
- No LinkedIn scraping.
- No personal email guessing.
- No automatic outreach approval.
