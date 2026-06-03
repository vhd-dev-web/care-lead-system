# Compliance Playbook

This is an operational playbook, not legal advice.

## Guardrails

- Treat personal data as optional, not the goal.
- Prefer generic company contact points.
- Prefer telephone-first review when a concrete B2B relevance exists.
- Treat email outreach as high-risk unless a separate legal basis exists.
- Keep personal emails empty unless clearly public and manually reviewed.

## Required Outreach-Ready Conditions

All must be true:

- B2B/shop context is clear.
- WooCommerce/shop relevance is documented.
- A concrete shop lever exists.
- A source and confidence exist for enriched data.
- A conservative channel is recommended.
- There is no do-not-contact signal.
- The compliance note is specific.

## Instantly-Ready Conditions

All must be true:

- `outreach_approved = true`.
- `outreach_channel = email`.
- `do_not_contact = false`.
- `personal_email` is present and syntactically valid.
- `email_verification_status` is `verified`, `valid`, or `deliverable`.
- A relevance note and GDPR/UWG review note exist.

Clay results alone do not approve outreach. They only add evidence for manual review.

## Statuses

`outreach_ready`: ready for human review and possible manual first contact.

`manual_review`: promising but missing evidence, channel clarity, or source confidence.

`do_not_contact`: not relevant, risky, competitor/agency/platform, or explicitly unsuitable.
