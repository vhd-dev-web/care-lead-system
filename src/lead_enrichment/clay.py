from __future__ import annotations

from dataclasses import dataclass

from .quality import quality_rank
from .normalizer import truthy


@dataclass(frozen=True)
class ClayEligibility:
    eligible: bool
    reason: str


def assess_clay_eligibility(row: dict[str, str]) -> ClayEligibility:
    quality = row.get("lead_quality", "")
    if quality_rank(quality) < quality_rank("A++"):
        return ClayEligibility(False, "Lead is not A++.")
    if not truthy(row.get("is_woocommerce")):
        return ClayEligibility(False, "Lead is not confirmed WooCommerce.")
    if not row.get("company_name"):
        return ClayEligibility(False, "Company name is missing.")
    if not row.get("managing_director_name"):
        return ClayEligibility(False, "Managing director or owner is missing.")
    if row.get("personal_email"):
        return ClayEligibility(False, "Personal email already present.")
    if not row.get("why_relevant") and not row.get("pain_summary"):
        return ClayEligibility(False, "Relevance note is missing.")
    if truthy(row.get("do_not_contact")):
        return ClayEligibility(False, "Lead is marked do-not-contact.")
    return ClayEligibility(True, "A++ lead is eligible for Clay email enrichment queue.")
