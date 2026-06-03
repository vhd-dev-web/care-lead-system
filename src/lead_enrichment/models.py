from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


OUT_FIELDS = [
    "lead_id",
    "domain",
    "website_url",
    "company_name",
    "company_name_source",
    "company_name_confidence",
    "legal_name",
    "legal_form",
    "street",
    "zip",
    "city",
    "country",
    "imprint_url",
    "register_source",
    "register_number",
    "managing_director",
    "owner_name",
    "decision_maker_1_name",
    "decision_maker_1_role",
    "decision_maker_1_source",
    "decision_maker_1_confidence",
    "linkedin_company_url",
    "linkedin_person_url",
    "phone_main",
    "phone_main_source",
    "email_general",
    "email_general_source",
    "email_personal",
    "email_personal_source",
    "contact_form_url",
    "technology_stack",
    "woocommerce_detected",
    "wordpress_detected",
    "shop_relevance_score",
    "technical_pain_score",
    "conversion_pain_score",
    "business_potential_score",
    "overall_priority",
    "recommended_outreach_channel",
    "outreach_angle",
    "mutmassliche_einwilligung_reason",
    "gdpr_legal_basis_note",
    "compliance_status",
    "do_not_contact",
    "do_not_contact_reason",
    "last_enriched_at",
    "next_action",
    "notes",
]


@dataclass(frozen=True)
class SourceEvidence:
    source: str = ""
    url: str = ""
    confidence: float = 0.0
    checked_at: str = ""


@dataclass
class EnrichedLead:
    lead_id: str = ""
    domain: str = ""
    website_url: str = ""
    company_name: str = ""
    company_name_source: str = ""
    company_name_confidence: str = ""
    legal_name: str = ""
    legal_form: str = ""
    street: str = ""
    zip: str = ""
    city: str = ""
    country: str = ""
    imprint_url: str = ""
    register_source: str = ""
    register_number: str = ""
    managing_director: str = ""
    owner_name: str = ""
    decision_maker_1_name: str = ""
    decision_maker_1_role: str = ""
    decision_maker_1_source: str = ""
    decision_maker_1_confidence: str = ""
    linkedin_company_url: str = ""
    linkedin_person_url: str = ""
    phone_main: str = ""
    phone_main_source: str = ""
    email_general: str = ""
    email_general_source: str = ""
    email_personal: str = ""
    email_personal_source: str = ""
    contact_form_url: str = ""
    technology_stack: str = ""
    woocommerce_detected: str = ""
    wordpress_detected: str = ""
    shop_relevance_score: str = ""
    technical_pain_score: str = ""
    conversion_pain_score: str = ""
    business_potential_score: str = ""
    overall_priority: str = ""
    recommended_outreach_channel: str = ""
    outreach_angle: str = ""
    mutmassliche_einwilligung_reason: str = ""
    gdpr_legal_basis_note: str = ""
    compliance_status: str = ""
    do_not_contact: str = "false"
    do_not_contact_reason: str = ""
    last_enriched_at: str = ""
    next_action: str = ""
    notes: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, str]:
        row: dict[str, str] = {}
        for field_name in OUT_FIELDS:
            value = getattr(self, field_name, "")
            row[field_name] = "" if value is None else str(value)
        return row


@dataclass(frozen=True)
class EnrichmentResult:
    rows: list[EnrichedLead]
    enriched_path: str
    review_path: str
    outreach_ready_path: str
    run_path: str
