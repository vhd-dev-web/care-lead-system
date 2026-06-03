from __future__ import annotations


def gdpr_note(has_personal_data: bool, purpose: str = "B2B lead review") -> str:
    if has_personal_data:
        return (
            "Art. 6(1)(f) GDPR legitimate-interest review required; process only business-relevant "
            f"data needed for {purpose}; keep source evidence and allow manual review before outreach."
        )
    return (
        "Company-level enrichment only; if personal data is added later, perform Art. 6(1)(f) "
        "GDPR legitimate-interest balancing and keep data minimised."
    )
