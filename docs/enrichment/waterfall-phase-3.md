# Waterfall Phase 3

Phase 3 adds Serper as a targeted Google-SERP fallback. It is not a broad scraper and it does not enrich every lead.

## Command

```powershell
python -m lead_enrichment serper-fallback --queue data/output/enrichment_queue.csv --limit 5
```

## Preconditions

Create a local gitignored policy file:

```powershell
Copy-Item config/enrichment_policy.example.json config/enrichment_policy.json
```

Then enable Serper:

```json
{
  "providers": {
    "serper": {
      "enabled": true
    }
  }
}
```

Set the key locally:

```text
SERPER_API_KEY=...
```

## When Serper Runs

Only rows with `provider_recommended = serper` or `next_enrichment_step` beginning with `serper_` are processed.

## Query Purposes

Imprint finding:

```text
site:domain.de impressum
"domain.de" impressum
"Firmenname GmbH" Impressum
```

Decision-maker finding:

```text
site:domain.de "Geschaeftsfuehrer"
"Firmenname GmbH" Geschaeftsfuehrer
"Firmenname GmbH" Inhaber
site:domain.de "Vertreten durch"
```

## Output Fields

```text
serper_used
serper_queries
serper_result_urls
serper_summary
serper_confidence_score
imprint_url
managing_director_name
managing_director_source
```

After Serper updates a row, the waterfall is recalculated. If Serper only finds an imprint URL but parsing is still weak, the next step should normally become Firecrawl planned for that known URL.

## Safety

Tests use fake clients and never spend credits. The production command refuses to run unless `providers.serper.enabled = true` in the local policy.
