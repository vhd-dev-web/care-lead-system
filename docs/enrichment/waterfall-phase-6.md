# Waterfall Phase 6: Final Gate

Phase 6 closes the enrichment waterfall.

It does not call Clay, Instantly, LinkedIn, or any external provider. It merges optional manual Clay results, applies a compliance gate, and writes final review/export files.

## Inputs

Default input:

```text
data/output/enrichment_queue.csv
```

Optional Clay result import:

```text
lead_id
domain
personal_email
email_verification_status
email_source
```

Example:

```text
data/samples/clay_results_sample.csv
```

Clay results are matched by `lead_id` first, then by normalized `domain`. Personal emails are only imported when they look syntactically valid. They are never guessed or generated.

## Outputs

```text
data/output/enriched_master.csv
data/output/compliance_review.csv
data/output/enrichment_review.csv
data/output/outreach_ready.csv
data/output/do_not_contact.csv
data/output/instantly_ready.csv
data/output/runs/final_gate_YYYYMMDD_HHMMSS.csv
```

## Status Logic

`do_not_contact` when:

- do-not-contact is already set,
- B2B/shop context is unclear,
- lead quality is below enrichment threshold.

`manual_review` when:

- provider enrichment is still pending,
- confidence is below `0.70`,
- no concrete relevance note exists,
- a personal email exists without explicit approval and verified status,
- no conservative channel is ready.

`outreach_ready` when:

- B2B/shop context is clear,
- concrete WooCommerce/shop relevance exists,
- confidence is high enough,
- no provider step is pending,
- a conservative human-first channel exists.

## Instantly Protection

`instantly_ready.csv` stays empty unless all conditions are true:

- `outreach_approved = true`
- `do_not_contact = false`
- `outreach_channel = email`
- `personal_email` is present
- `email_verification_status` is `verified`, `valid`, or `deliverable`

This means Clay can enrich a personal email, but the lead still does not become Instantly-ready until a human explicitly approves it.

## Run

```powershell
$env:PYTHONPATH = "src"
python -m lead_enrichment finalize --queue data/output/enrichment_queue.csv
```

With a manual Clay result file:

```powershell
python -m lead_enrichment finalize `
  --queue data/output/enrichment_queue.csv `
  --clay-results data/samples/clay_results_sample.csv
```

or:

```powershell
.\scripts\finalize_enrichment.ps1 -ClayResults data/samples/clay_results_sample.csv
```

## Guardrails

- No automatic outreach.
- No automatic Instantly push.
- No personal email guessing.
- Personal email always requires explicit approval before export.
- Compliance notes are generated for review, not legal advice.
