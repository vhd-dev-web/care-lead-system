# Waterfall Phase 1

Phase 1 builds the decision layer without spending provider credits.

## Command

```powershell
python -m lead_enrichment prepare-queue --verified data/input/verified_master.csv --review data/input/review_master.csv
```

## Outputs

```text
data/output/enrichment_queue.csv
data/output/clay_queue.csv
```

## Decisions

The queue builder:

- normalizes domains,
- deduplicates verified and review inputs,
- assigns `lead_quality` as A++, A+, A, B, or C,
- writes `pain_summary` and `why_relevant`,
- chooses `next_enrichment_step`,
- marks whether an external provider would be required,
- writes Clay candidates only when the waterfall has reached the Clay email step.

## Provider Safety

External providers are disabled by default. `prepare-queue` does not call Serper, Firecrawl, Tavily, or Clay. Provider recommendations are planning signals only until a later phase implements the adapter and policy gates.

## Clay Rule

Clay eligibility requires:

```text
lead_quality = A++
is_woocommerce = true
company_name present
managing_director_name present
personal_email missing
why_relevant or pain_summary present
do_not_contact = false
```

Even then, Phase 1 only writes `clay_queue.csv`; it does not spend Clay credits.
