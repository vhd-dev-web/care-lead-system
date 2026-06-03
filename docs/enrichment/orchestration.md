# Orchestration

The orchestrator connects all waterfall phases into one controlled run.

```text
prepare-queue
-> free-website-enrich
-> enabled provider fallbacks
-> finalize
```

Clay is not called by the orchestrator. Clay remains a manual result import into the final gate.

## Command

```powershell
$env:PYTHONPATH = "src"
python -m lead_enrichment run-waterfall `
  --verified data/samples/verified_sample.csv
```

With optional review input:

```powershell
python -m lead_enrichment run-waterfall `
  --verified output/domain_verification/verified_master.csv `
  --review output/domain_verification/review_master.csv
```

CSV-only control run:

```powershell
python -m lead_enrichment run-waterfall `
  --verified data/samples/verified_sample.csv `
  --skip-website `
  --skip-providers
```

With manual Clay result import:

```powershell
python -m lead_enrichment run-waterfall `
  --verified output/domain_verification/verified_master.csv `
  --clay-results data/samples/clay_results_sample.csv
```

## Provider Behavior

The orchestrator only calls a provider when all are true:

- rows for that provider are queued,
- `--skip-providers` is not set,
- the provider is enabled in `config/enrichment_policy.json`,
- the provider's daily budget is greater than zero.

Provider order per round:

```text
Serper -> Firecrawl -> Tavily
```

The runner uses multiple provider rounds because one provider can create the next provider step. Example:

```text
Serper finds imprint URL
-> Firecrawl can parse known URL
-> Serper may later search missing decision maker
```

Default maximum:

```text
provider_rounds = 1
```

Increase `provider_rounds` only for intentional recovery runs. The orchestrator now
tracks provider usage across rounds and stops Serper, Firecrawl, and Tavily once
their configured daily budget is exhausted.

## Outputs

All normal phase outputs are still written. The orchestrator additionally writes:

```text
data/output/runs/waterfall_summary_YYYYMMDD_HHMMSS.json
```

The summary contains:

- input paths,
- active run options,
- step status,
- per-step counts,
- final export counts.

## Field Quality Gate

Every enrichment phase normalizes queue rows before writing output. The shared
data-quality gate removes known false positives instead of preserving them as
"existing" values:

- phone-like dates and numeric fragments, e.g. `05.2026` or `0152-0153`,
- vendor/tool names misread as legal entities, e.g. support widget vendors,
- single-word or address-contaminated decision-maker names.

Provider fallbacks may only set a decision-maker source when the candidate name
passes the quality gate.

## Guardrails

- No provider is called just because an API key exists.
- Missing `config/enrichment_policy.json` means providers are disabled.
- `--skip-website` allows a no-new-website-request run.
- `--skip-providers` allows a free-only run.
- Final gate always runs.
- `instantly_ready.csv` remains protected by explicit approval fields.
