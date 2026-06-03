# Data Model

## Core Objects

- `LeadInput`: one imported CSV row.
- `EnrichedLead`: normalized output row with scoring, evidence, and compliance fields.
- `SourceEvidence`: source name, URL, confidence, and checked timestamp.
- `DecisionMaker`: person, role, source, confidence.
- `ContactPoint`: generic email, phone, contact form, and source.
- `ComplianceAssessment`: status, notes, do-not-contact reason.

## Output Columns

The canonical output columns live in `src/lead_enrichment/models.py` as `OUT_FIELDS`.

Important fields:

- `overall_priority`: A, B, C, Review, or Reject.
- `recommended_outreach_channel`: conservative channel recommendation.
- `mutmassliche_einwilligung_reason`: documented telephone-first relevance note.
- `gdpr_legal_basis_note`: processing note for legitimate-interest review.
- `compliance_status`: outreach_ready, manual_review, or do_not_contact.
- `do_not_contact`: boolean-like string for filtering.

## Evidence Pattern

Use this pattern for high-value fields:

```text
company_name
company_name_source
company_name_confidence
```

Do not overwrite a high-confidence source with weaker evidence.
