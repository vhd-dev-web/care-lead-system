from __future__ import annotations

from .normalizer import clean_text


SCHEMA_VERSION = "phase1.0"

STATUS_VALUES = {
    "not_needed",
    "needed",
    "queued",
    "running",
    "done",
    "partial",
    "manual_review",
    "failed",
    "blocked",
    "skipped_budget",
    "stale",
}

MODULE_NAMES = ("firecrawl", "serper", "tavily")
MODULE_SUFFIXES = (
    "needed",
    "status",
    "reason",
    "attempts",
    "last_run_id",
    "checked_at",
    "error",
)

BASE_COLUMNS = [
    "lead_id",
    "domain_key",
    "domain",
    "url",
    "website_url",
    "shop_name",
    "company_name",
    "country",
    "language",
    "source_lists",
    "first_seen_at",
    "last_seen_at",
    "created_at",
    "updated_at",
    "scrape_source_primary",
    "scrape_sources_all",
    "scrape_run_ids",
    "duplicate_group_id",
    "duplicate_status",
    "canonical_lead_id",
    "verification_status",
    "verification_score",
    "domain_alive",
    "is_shop",
    "is_woocommerce",
    "woocommerce_confidence",
    "detected_platform",
    "detected_platform_signals",
    "niche",
    "care_lead_type",
    "ik_number",
    "care_product_signals",
    "care_gkv_signals",
    "care_process_signals",
    "care_insurer_signals",
    "care_ratgeber_signals",
    "scale_indicators",
    "verification_evidence_url",
    "verification_checked_at",
    "verification_error",
    "shop_relevance_score",
    "technical_pain_score",
    "conversion_pain_score",
    "business_potential_score",
    "lead_grade",
    "lead_grade_reason",
    "priority",
    "enrichment_stage",
    "next_action",
    "next_action_reason",
    "pipeline_status",
    "last_completed_step",
    "last_completed_at",
    "last_run_id",
    "manual_review_required",
    "review_status",
    "review_reason",
    "do_not_contact",
    "do_not_contact_reason",
]

ENRICHMENT_RESULT_COLUMNS = [
    "legal_name",
    "legal_name_source",
    "legal_name_confidence",
    "legal_name_checked_at",
    "imprint_url",
    "imprint_url_source",
    "imprint_url_confidence",
    "imprint_url_checked_at",
    "email_general",
    "email_general_source",
    "email_general_confidence",
    "email_general_checked_at",
    "phone_main",
    "phone_main_source",
    "phone_main_confidence",
    "phone_main_checked_at",
    "decision_maker_1_name",
    "decision_maker_1_role",
    "decision_maker_1_source",
    "decision_maker_1_confidence",
    "decision_maker_1_checked_at",
    "linkedin_company_url",
    "linkedin_company_url_source",
    "linkedin_company_url_confidence",
    "linkedin_company_url_checked_at",
    "linkedin_person_url",
    "linkedin_person_url_source",
    "linkedin_person_url_confidence",
    "linkedin_person_url_checked_at",
    "recommended_outreach_channel",
    "outreach_angle",
]

CLAY_STATUS_COLUMNS = [
    "clay_needed",
    "clay_reason",
    "clay_status",
    "clay_export_batch_id",
    "clay_exported_at",
    "clay_last_synced_at",
    "clay_result_imported_at",
    "clay_notes",
]

MODULE_COLUMNS = [f"{module}_{suffix}" for module in MODULE_NAMES for suffix in MODULE_SUFFIXES]

MASTER_COLUMNS = BASE_COLUMNS + MODULE_COLUMNS + ENRICHMENT_RESULT_COLUMNS + CLAY_STATUS_COLUMNS

EVIDENCE_VALUE_FIELDS = {
    "legal_name",
    "imprint_url",
    "email_general",
    "phone_main",
    "decision_maker_1_name",
    "linkedin_company_url",
    "linkedin_person_url",
}

DEFAULTS = {
    "duplicate_status": "canonical",
    "manual_review_required": "false",
    "do_not_contact": "false",
    "pipeline_status": "imported",
    "enrichment_stage": "not_started",
    "review_status": "not_needed",
    "clay_needed": "false",
    "clay_status": "not_needed",
}

for module in MODULE_NAMES:
    DEFAULTS[f"{module}_needed"] = "false"
    DEFAULTS[f"{module}_status"] = "not_needed"
    DEFAULTS[f"{module}_attempts"] = "0"


def blank_master_row() -> dict[str, str]:
    row = {column: "" for column in MASTER_COLUMNS}
    row.update(DEFAULTS)
    return row


def ensure_master_columns(row: dict[str, object]) -> dict[str, str]:
    normalized = {column: clean_text(row.get(column, "")) for column in MASTER_COLUMNS}
    for key, value in row.items():
        if key not in normalized:
            normalized[key] = clean_text(value)
    for key, value in DEFAULTS.items():
        if not normalized.get(key):
            normalized[key] = value
    return normalized


def ordered_fieldnames(rows: list[dict[str, str]]) -> list[str]:
    extras: list[str] = []
    seen = set(MASTER_COLUMNS)
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                extras.append(key)
    return MASTER_COLUMNS + extras
