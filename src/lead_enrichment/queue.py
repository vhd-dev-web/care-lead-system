from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .clay import assess_clay_eligibility
from .data_quality import sanitize_legal_name, sanitize_person_name, sanitize_phone
from .dedupe import dedupe_rows
from .exporters.csv_exporter import read_csv_rows, write_csv_rows
from .extractors.company_identity import company_name_from_row
from .extractors.legal_form import detect_legal_form
from .normalizer import bool_string, clean_text, normalize_domain, normalize_url, stable_lead_id, truthy
from .policy import EnrichmentPolicy
from .quality import lead_quality, score_from_row
from .scoring import build_outreach_angle
from .waterfall import decide_next_step


QUEUE_FIELDS = [
    "lead_id",
    "domain",
    "source_url",
    "website_url",
    "company_name",
    "legal_name",
    "legal_form",
    "lead_quality",
    "vhd_fit_score",
    "is_shop",
    "is_woocommerce",
    "is_dach",
    "possible_shop_levers",
    "pain_summary",
    "why_relevant",
    "recommended_outreach_channel",
    "free_enrichment_status",
    "confidence_score",
    "imprint_parse_status",
    "free_enrichment_source_urls",
    "website_pages_checked",
    "enrichment_status",
    "next_enrichment_step",
    "waterfall_reason",
    "provider_recommended",
    "requires_external_provider",
    "entity_ambiguous",
    "decision_maker_ambiguous",
    "imprint_url",
    "contact_url",
    "managing_director_name",
    "managing_director_source",
    "general_email",
    "phone_main",
    "address",
    "firecrawl_used",
    "firecrawl_source_url",
    "firecrawl_markdown_chars",
    "firecrawl_confidence_score",
    "firecrawl_summary",
    "firecrawl_error",
    "serper_used",
    "serper_queries",
    "serper_result_urls",
    "serper_summary",
    "serper_confidence_score",
    "tavily_used",
    "tavily_queries",
    "tavily_result_urls",
    "tavily_answer",
    "tavily_summary",
    "tavily_confidence_score",
    "tavily_credits",
    "tavily_error",
    "research_note",
    "clay_eligible",
    "clay_reason",
    "clay_used",
    "personal_email",
    "email_verification_status",
    "email_source",
    "mutmassliche_einwilligung_reason",
    "gdpr_legal_basis_note",
    "compliance_status",
    "compliance_reason",
    "unsubscribe_required",
    "outreach_approved",
    "outreach_channel",
    "do_not_contact",
    "do_not_contact_reason",
    "next_action",
    "instantly_pushed",
    "source_bucket",
    "last_queued_at",
    "notes",
]


@dataclass(frozen=True)
class QueueBuildOptions:
    verified_path: Path
    review_path: Path | None = None
    output_dir: Path = Path("data/output")
    policy_path: Path | None = None
    limit: int | None = None


@dataclass(frozen=True)
class QueueBuildResult:
    queue_path: str
    clay_queue_path: str
    row_count: int
    clay_row_count: int


def build_enrichment_queue(options: QueueBuildOptions) -> QueueBuildResult:
    policy = EnrichmentPolicy.from_file(options.policy_path)
    rows = load_input_rows(options.verified_path, options.review_path)
    rows = dedupe_rows(rows)
    if options.limit is not None:
        rows = rows[: options.limit]

    timestamp = now_utc()
    queue_rows = [build_queue_row(row, policy, timestamp) for row in rows]
    clay_rows = [
        row for row in queue_rows if row["next_enrichment_step"].startswith("clay_email_queue")
    ]

    output_dir = options.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    queue_path = output_dir / "enrichment_queue.csv"
    clay_path = output_dir / "clay_queue.csv"
    run_dir = output_dir / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    run_path = run_dir / f"enrichment_queue_{timestamp_for_filename(timestamp)}.csv"

    write_csv_rows(queue_path, queue_rows, QUEUE_FIELDS)
    write_csv_rows(clay_path, clay_rows, QUEUE_FIELDS)
    write_csv_rows(run_path, queue_rows, QUEUE_FIELDS)

    return QueueBuildResult(
        queue_path=str(queue_path),
        clay_queue_path=str(clay_path),
        row_count=len(queue_rows),
        clay_row_count=len(clay_rows),
    )


def load_input_rows(verified_path: Path, review_path: Path | None) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for row in read_csv_rows(verified_path):
        normalized = dict(row)
        normalized["source_bucket"] = "verified"
        rows.append(normalized)
    if review_path and review_path.exists():
        for row in read_csv_rows(review_path):
            normalized = dict(row)
            normalized["source_bucket"] = "review"
            rows.append(normalized)
    return rows


def build_queue_row(row: dict[str, str], policy: EnrichmentPolicy, timestamp: str) -> dict[str, str]:
    domain = normalize_domain(row.get("domain") or row.get("source_url") or row.get("url"))
    company_name, _, _ = company_name_from_row(row)
    quality = lead_quality(row)
    pain_summary = build_outreach_angle(row)
    legal_name = sanitize_legal_name(row.get("legal_name"), row.get("legal_form"))
    legal_form = (clean_text(row.get("legal_form")) or detect_legal_form(legal_name)) if legal_name else ""
    base = {
        "lead_id": stable_lead_id(domain),
        "domain": domain,
        "source_url": clean_text(row.get("source_url") or row.get("url")),
        "website_url": normalize_url(row.get("source_url") or row.get("url"), domain),
        "company_name": company_name,
        "legal_name": legal_name,
        "legal_form": legal_form,
        "lead_quality": quality,
        "vhd_fit_score": str(score_from_row(row)),
        "is_shop": bool_string(truthy(row.get("is_shop"))),
        "is_woocommerce": bool_string(truthy(row.get("is_woocommerce"))),
        "is_dach": bool_string(truthy(row.get("is_dach"))),
        "possible_shop_levers": clean_text(row.get("possible_shop_levers")),
        "pain_summary": pain_summary,
        "why_relevant": why_relevant(row, quality, pain_summary),
        "recommended_outreach_channel": clean_text(row.get("recommended_outreach_channel")),
        "free_enrichment_status": clean_text(row.get("free_enrichment_status")),
        "confidence_score": clean_text(row.get("confidence_score")),
        "imprint_parse_status": clean_text(row.get("imprint_parse_status")),
        "free_enrichment_source_urls": clean_text(row.get("free_enrichment_source_urls")),
        "website_pages_checked": clean_text(row.get("website_pages_checked")),
        "entity_ambiguous": bool_string(truthy(row.get("entity_ambiguous"))),
        "decision_maker_ambiguous": bool_string(truthy(row.get("decision_maker_ambiguous"))),
        "imprint_url": clean_text(row.get("imprint_url")),
        "contact_url": clean_text(row.get("contact_url")),
        "managing_director_name": sanitize_person_name(
            row.get("managing_director_name")
            or row.get("managing_director")
            or row.get("decision_maker_1_name")
        ),
        "managing_director_source": clean_text(
            row.get("managing_director_source") or row.get("decision_maker_1_source")
        ),
        "general_email": clean_text(row.get("general_email") or row.get("email_general") or row.get("email")),
        "phone_main": sanitize_phone(row.get("phone_main") or row.get("phone")),
        "address": clean_text(row.get("address")),
        "firecrawl_used": bool_string(False),
        "firecrawl_source_url": clean_text(row.get("firecrawl_source_url")),
        "firecrawl_markdown_chars": clean_text(row.get("firecrawl_markdown_chars")),
        "firecrawl_confidence_score": clean_text(row.get("firecrawl_confidence_score")),
        "firecrawl_summary": clean_text(row.get("firecrawl_summary")),
        "firecrawl_error": clean_text(row.get("firecrawl_error")),
        "serper_used": bool_string(False),
        "serper_queries": clean_text(row.get("serper_queries")),
        "serper_result_urls": clean_text(row.get("serper_result_urls")),
        "serper_summary": clean_text(row.get("serper_summary")),
        "serper_confidence_score": clean_text(row.get("serper_confidence_score")),
        "tavily_used": bool_string(False),
        "tavily_queries": clean_text(row.get("tavily_queries")),
        "tavily_result_urls": clean_text(row.get("tavily_result_urls")),
        "tavily_answer": clean_text(row.get("tavily_answer")),
        "tavily_summary": clean_text(row.get("tavily_summary")),
        "tavily_confidence_score": clean_text(row.get("tavily_confidence_score")),
        "tavily_credits": clean_text(row.get("tavily_credits")),
        "tavily_error": clean_text(row.get("tavily_error")),
        "research_note": clean_text(row.get("research_note")),
        "clay_used": bool_string(False),
        "personal_email": clean_text(row.get("personal_email") or row.get("email_personal")),
        "email_verification_status": clean_text(row.get("email_verification_status")),
        "email_source": clean_text(row.get("email_source")),
        "mutmassliche_einwilligung_reason": clean_text(row.get("mutmassliche_einwilligung_reason")),
        "gdpr_legal_basis_note": clean_text(row.get("gdpr_legal_basis_note")),
        "compliance_status": clean_text(row.get("compliance_status")),
        "compliance_reason": clean_text(row.get("compliance_reason")),
        "unsubscribe_required": bool_string(truthy(row.get("unsubscribe_required"))),
        "outreach_approved": bool_string(False),
        "outreach_channel": clean_text(row.get("outreach_channel")),
        "do_not_contact": bool_string(truthy(row.get("do_not_contact"))),
        "do_not_contact_reason": clean_text(row.get("do_not_contact_reason")),
        "next_action": clean_text(row.get("next_action")),
        "instantly_pushed": bool_string(False),
        "source_bucket": clean_text(row.get("source_bucket")),
        "last_queued_at": timestamp,
        "notes": clean_text(row.get("notes")),
    }
    clay = assess_clay_eligibility(base)
    base["clay_eligible"] = bool_string(clay.eligible)
    base["clay_reason"] = clay.reason
    decision = decide_next_step(base, policy)
    base["enrichment_status"] = decision.status
    base["next_enrichment_step"] = decision.next_step
    base["waterfall_reason"] = decision.reason
    base["provider_recommended"] = decision.provider
    base["requires_external_provider"] = bool_string(decision.requires_external_provider)
    return {field: base.get(field, "") for field in QUEUE_FIELDS}


def why_relevant(row: dict[str, str], quality: str, pain_summary: str) -> str:
    if quality in {"A++", "A+", "A"}:
        tech = "WooCommerce shop" if truthy(row.get("is_woocommerce")) else "verified shop"
        return f"{tech} with documented shop lever: {pain_summary}"
    return ""


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def timestamp_for_filename(timestamp: str) -> str:
    return timestamp.replace("-", "").replace(":", "").replace("T", "_").replace("Z", "")
