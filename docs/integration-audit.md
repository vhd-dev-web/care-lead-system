# Integration Audit: Upstream Lead Repos

Audit date: 2026-05-28

This pass checked the four intended upstream repositories against the
master-first `care-lead-system` architecture. The rule remains unchanged:
`data/master/leads_master.csv` is the only persisted truth; upstream CSVs,
Google Sheets, Clay queues, reviews, and archives are handoffs.

Update: the root package now vendors the executable scraper/verifier modules
and the `lead_enrichment` waterfall, so a solo `care-lead-system` install can
run the standard pipeline without installing the old split repos separately.

## Repositories Checked

| Repo | Audited ref | State | Integration status |
| --- | --- | --- | --- |
| `vhd-dev-web/care-lead-scraper` | `346995d` | Active Python/PowerShell scraper and verifier | Importable now through scrape import and verification import |
| `vhd-dev-web/vhd-lead-scoring-operator` | `29d1cea` | Operator contract/runbook repo, no executable scorer | Contract mapped where possible; waits for stable scorer script |
| `vhd-dev-web/vhd-lead-enrichment` | `cc32713` | Active Python enrichment waterfall | Importable now through enrichment result import |
| `vhd-dev-web/lead-to-clay` | `cc32713` | Active Python Clay/enrichment waterfall, currently code-identical to `vhd-lead-enrichment` | Queue/final outputs are importable through enrichment result import; local Clay CSV/Google handoff remains canonical |

## care-lead-scraper

Relevant entrypoints:

- `woocommerce_lead_finder.py`
- `lead_qualifier.py`
- `run_pipeline.ps1`
- `run_daily.ps1`
- `run_qualifier.ps1`

Relevant outputs:

- `output/leads_master.csv`
- `output/qualified_master.csv`
- `output/domain_verification/verified_master.csv`
- `output/domain_verification/review_master.csv`
- `output/domain_verification/rejected_master.csv`
- `output/domain_verification/runs/*/verification_all.csv`

Important fields:

- Search master: `domain`, `url`, `company_name`, `email`, `phone`,
  `country_hint`, `lead_score`, `signals`, `found_at`, `last_seen_at`.
- Verification: `domain`, `source_url`, `company_name`, `scoring_mode`,
  `lead_type`, `is_shop`, `is_woocommerce`, `is_dach`, `vhd_fit_score`,
  `next_action`, `exclusion_reason`, `email`, `phone`, `best_status`,
  `robots_status`, `skipped_by_robots`, `policy_skip_reason`,
  `verified_signals`, `possible_shop_levers`, `input_lead_score`,
  `input_signals`, `checked_at`.

Implemented in this repo:

- `import-scrapes` already handles search-style CSV files and dedupes by
  normalized `domain_key`.
- `import-verification` now also upserts unknown scraper verification rows,
  maps semicolon CSVs, derives `verification_status`, `domain_alive`,
  `verification_score`, `business_potential_score`, `lead_grade`, review
  status, and evidence URL.
- Grade derivation follows the current master rules: WooCommerce + high score
  and a concrete lever becomes `A++`; WooCommerce with lower high score becomes
  `A+`; verified shops become `A`/`B`; rejects and service-provider classes
  become `Reject`.

## vhd-lead-scoring-operator

Relevant files:

- `schemas/lead-ledger.schema.csv`
- `schemas/run-result.schema.csv`
- `references/scorer-integration-contract.md`
- `references/runbook.md`
- `references/config.md`
- `references/scoring-kriterien.md`

Current state:

- This repo defines operator behavior, limits, state and the desired scorer
  contract.
- It does not yet include a stable scorer executable.

Implemented in this repo:

- `import-verification` can already consume the documented `run-result` shape
  where fields include `domain`, `status`, `http_status`, `score`, `category`,
  `error_reason`, `next_action`, and `notes`.
- Unknown/contract categories are normalized conservatively, for example
  `unknown` -> `Review`, `excluded` -> `Reject`.

Remaining integration:

- Once a stable scorer script exists, add an orchestration adapter that prepares
  batch inputs, calls the script with conservative limits, and imports the
  structured run-result CSV back through `MasterUpdater`.

## vhd-lead-enrichment

Relevant entrypoints:

- `python -m lead_enrichment enrich`
- `python -m lead_enrichment prepare-queue`
- `python -m lead_enrichment free-website-enrich`
- `python -m lead_enrichment serper-fallback`
- `python -m lead_enrichment firecrawl-fallback`
- `python -m lead_enrichment tavily-research`
- `python -m lead_enrichment finalize`
- `python -m lead_enrichment run-waterfall`

Relevant outputs:

- `data/output/enrichment_queue.csv`
- `data/output/clay_queue.csv`
- `data/output/enriched_master.csv`
- `data/output/enrichment_review.csv`
- `data/output/compliance_review.csv`
- `data/output/outreach_ready.csv`
- `data/output/do_not_contact.csv`
- `data/output/instantly_ready.csv`

Important fields:

- `OUT_FIELDS`: `lead_id`, `domain`, `website_url`, `company_name`,
  `legal_name`, `imprint_url`, `decision_maker_1_name`, `phone_main`,
  `email_general`, `woocommerce_detected`, `shop_relevance_score`,
  `technical_pain_score`, `conversion_pain_score`,
  `business_potential_score`, `overall_priority`,
  `recommended_outreach_channel`, `outreach_angle`, `compliance_status`,
  `do_not_contact`, `last_enriched_at`, `next_action`.
- `QUEUE_FIELDS`: `lead_id`, `domain`, `source_url`, `website_url`,
  `company_name`, `legal_name`, `lead_quality`, `vhd_fit_score`,
  `possible_shop_levers`, `pain_summary`, `why_relevant`,
  `next_enrichment_step`, `provider_recommended`, `imprint_url`,
  `managing_director_name`, `general_email`, `phone_main`, provider fields,
  `clay_eligible`, `clay_reason`, compliance fields, `last_queued_at`.

Implemented in this repo:

- New `import-enrichment-results` command imports both enrichment result styles:
  `OUT_FIELDS` and `QUEUE_FIELDS`.
- The adapter maps `overall_priority`/`lead_quality` to `lead_grade`,
  `general_email`/`email_general` to `email_general`, `managing_director_name`
  to `decision_maker_1_name`, provider recommendations to
  `firecrawl_*`/`serper_*`/`tavily_*` statuses, and Clay eligibility to
  `clay_needed`/`clay_status`.
- Source, confidence and checked timestamps are preserved for high-value
  enrichment fields whenever the upstream CSV provides them; otherwise the
  adapter marks source as `vhd-lead-enrichment` and uses the queue/enrichment
  timestamp.

## lead-to-clay

Current state:

- The repository now contains the controlled `lead_enrichment` waterfall at
  commit `cc32713`.
- Its current package/module name and field contracts match
  `vhd-lead-enrichment`: `python -m lead_enrichment ...`,
  `QUEUE_FIELDS`, `OUT_FIELDS`, `data/output/enrichment_queue.csv`,
  `data/output/clay_queue.csv`, and final-gate outputs.
- The included Clay result sample is semicolon CSV with
  `lead_id`, `domain`, `personal_email`, `email_verification_status`, and
  `email_source`.

Implemented in this repo:

- `import-enrichment-results` already supports the queue/final output fields
  because the current repo uses the same `lead_enrichment` schemas.
- Local `lead_to_clay_adapter.py` remains the active master-to-Clay handoff for
  our Phase 1/2 master schema.
- Phase 2 Google Sheets adapter writes `Clay Queue`, imports business-safe
  `Clay Results`, and appends `Sync Log`.
- Personal email fields from the upstream sample are intentionally not promoted
  to first-class master columns in this phase because the master schema and
  current compliance boundary are business-contact-first. If personal email
  review becomes required, it should be added as an explicit later schema and
  compliance-gate decision instead of silently flowing into outreach exports.

Remaining integration:

- Decide whether `lead-to-clay` should stay a separate repo or be treated as a
  renamed/mirrored `vhd-lead-enrichment` component.
- If Clay should return personal emails into the central master, add explicit
  master columns, source/confidence/timestamp fields, manual review status, and
  tests before importing those values.

## Current Test Coverage

The integration pass added tests for:

- Realistic scraper verification CSV import using semicolon CSV and
  `vhd_fit_score`.
- Idempotent verification import without duplicate leads.
- Enrichment queue/result import using `lead_quality`, `general_email`,
  `managing_director_name`, provider recommendation and Clay eligibility.
- Existing master import, enrichment planning, Clay CSV handoff, Google Sheets
  adapter, and Clay result import behavior.

Validation command:

```powershell
python -m pytest -q
```

Current result: `9 passed`.

## First Real Test Run Recommendation

Use the lowest-risk sequence:

1. Run the scraper in a small budget mode and produce verification CSVs.
2. Import `output/domain_verification/verified_master.csv` with
   `import-verification`.
3. Generate `Leads_Master.xlsx`.
4. Run `plan-enrichment`.
5. Optionally run `vhd-lead-enrichment` in `csv-only` or queue mode.
6. Import `data/output/enrichment_queue.csv` or `enriched_master.csv` with
   `import-enrichment-results`.
7. Sync the Clay queue to the Google Sheet.
8. Import `Clay Results` back into the master.
