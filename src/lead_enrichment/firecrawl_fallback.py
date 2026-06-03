from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .clay import assess_clay_eligibility
from .data_quality import merge_quality_value, sanitize_queue_fields
from .exporters.csv_exporter import read_csv_rows, write_csv_rows
from .extractors.address import extract_address
from .extractors.company_identity import company_identity_from_text
from .extractors.contacts import choose_general_email, choose_main_phone
from .extractors.decision_makers import extract_decision_maker
from .normalizer import bool_string, clean_text, normalize_domain, truthy
from .policy import EnrichmentPolicy
from .providers.firecrawl_client import FirecrawlClient, FirecrawlScrapeResponse
from .queue import QUEUE_FIELDS
from .website_enrichment import needs_review
from .waterfall import decide_next_step


class ScrapeClient(Protocol):
    def scrape(self, url: str) -> FirecrawlScrapeResponse:
        ...


@dataclass(frozen=True)
class FirecrawlFallbackOptions:
    queue_path: Path
    output_dir: Path = Path("data/output")
    policy_path: Path | None = None
    limit: int | None = None
    page_limit: int | None = None
    require_provider_enabled: bool = True


@dataclass(frozen=True)
class FirecrawlFallbackResult:
    enriched_path: str
    review_path: str
    clay_queue_path: str
    run_path: str
    processed_count: int
    page_count: int
    clay_row_count: int


@dataclass(frozen=True)
class FirecrawlExtractedData:
    legal_name: str = ""
    legal_form: str = ""
    address: str = ""
    managing_director_name: str = ""
    managing_director_source: str = ""
    general_email: str = ""
    phone_main: str = ""
    confidence_score: float = 0.0
    parse_status: str = "failed"


def run_firecrawl_fallback(
    options: FirecrawlFallbackOptions,
    client: ScrapeClient | None = None,
) -> FirecrawlFallbackResult:
    policy = EnrichmentPolicy.from_file(options.policy_path)
    if options.require_provider_enabled and not policy.provider_enabled("firecrawl"):
        raise RuntimeError(
            "Firecrawl provider is disabled. Copy config/enrichment_policy.example.json to "
            "config/enrichment_policy.json and set providers.firecrawl.enabled=true."
        )
    active_client = client or FirecrawlClient()
    rows = read_csv_rows(options.queue_path)
    processed = 0
    pages_used = 0
    row_budget = options.limit if options.limit is not None else len(rows)
    page_budget = max(0, policy.firecrawl_daily_limit)
    if options.page_limit is not None:
        page_budget = min(page_budget, max(0, options.page_limit))
    updated_rows: list[dict[str, str]] = []
    timestamp = now_utc()

    for row in rows:
        normalized = ensure_queue_row(row)
        if should_process(normalized) and processed < row_budget and pages_used < page_budget:
            updated, used = enrich_with_firecrawl(normalized, active_client)
            processed += 1 if used else 0
            pages_used += used
            normalized = updated
        updated_rows.append(redecide_row(normalized, policy))

    clay_rows = [
        row for row in updated_rows if row["next_enrichment_step"].startswith("clay_email_queue")
    ]
    review_rows = [row for row in updated_rows if needs_review(row)]

    output_dir = options.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = output_dir / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    enriched_path = output_dir / "enriched_master.csv"
    review_path = output_dir / "enrichment_review.csv"
    clay_path = output_dir / "clay_queue.csv"
    queue_path = output_dir / "enrichment_queue.csv"
    run_path = run_dir / f"firecrawl_fallback_{timestamp_for_filename(timestamp)}.csv"

    write_csv_rows(enriched_path, updated_rows, QUEUE_FIELDS)
    write_csv_rows(review_path, review_rows, QUEUE_FIELDS)
    write_csv_rows(clay_path, clay_rows, QUEUE_FIELDS)
    write_csv_rows(queue_path, updated_rows, QUEUE_FIELDS)
    write_csv_rows(run_path, updated_rows, QUEUE_FIELDS)

    return FirecrawlFallbackResult(
        enriched_path=str(enriched_path),
        review_path=str(review_path),
        clay_queue_path=str(clay_path),
        run_path=str(run_path),
        processed_count=processed,
        page_count=pages_used,
        clay_row_count=len(clay_rows),
    )


def should_process(row: dict[str, str]) -> bool:
    return row.get("provider_recommended") == "firecrawl" or row.get(
        "next_enrichment_step", ""
    ).startswith("firecrawl_")


def enrich_with_firecrawl(
    row: dict[str, str],
    client: ScrapeClient,
) -> tuple[dict[str, str], int]:
    target_url = known_extraction_url(row)
    if not target_url:
        updated = dict(row)
        updated["firecrawl_summary"] = "Skipped: no known same-domain imprint or contact URL."
        return updated, 0

    enriched = dict(row)
    enriched["firecrawl_used"] = bool_string(True)
    enriched["firecrawl_source_url"] = target_url
    try:
        response = client.scrape(target_url)
    except Exception as exc:  # noqa: BLE001 - provider failures should not abort the queue.
        enriched["firecrawl_error"] = clean_text(str(exc))[:500]
        enriched["firecrawl_summary"] = "Firecrawl request failed; route to manual review."
        enriched["imprint_parse_status"] = "failed"
        enriched["free_enrichment_status"] = "failed"
        return enriched, 1

    markdown = clean_text(response.markdown)
    source_url = clean_text(response.source_url or target_url)
    data = extract_from_markdown(markdown, bool(row.get("imprint_url")))
    merge_if_present(enriched, "legal_name", data.legal_name)
    merge_if_present(enriched, "legal_form", data.legal_form)
    if data.legal_name and not enriched.get("company_name"):
        enriched["company_name"] = data.legal_name
    merge_if_present(enriched, "address", data.address)
    merge_if_present(enriched, "general_email", data.general_email)
    merge_if_present(enriched, "phone_main", data.phone_main)
    merge_if_present(enriched, "managing_director_name", data.managing_director_name)
    merge_if_present(enriched, "managing_director_source", data.managing_director_source)
    enriched["firecrawl_source_url"] = source_url
    enriched["firecrawl_markdown_chars"] = str(len(response.markdown or ""))
    enriched["firecrawl_confidence_score"] = f"{data.confidence_score:.2f}"
    enriched["firecrawl_summary"] = build_summary(response, markdown)
    enriched["firecrawl_error"] = ""
    enriched["confidence_score"] = f"{max(existing_confidence(row), data.confidence_score):.2f}"
    enriched["imprint_parse_status"] = data.parse_status
    enriched["free_enrichment_status"] = (
        "complete" if data.confidence_score >= 0.70 else data.parse_status
    )
    append_source_url(enriched, source_url)
    return enriched, 1


def extract_from_markdown(markdown: str, has_known_imprint_url: bool) -> FirecrawlExtractedData:
    if not markdown:
        return FirecrawlExtractedData()
    identity = company_identity_from_text(markdown)
    decision = extract_decision_maker(markdown)
    email = choose_general_email(markdown)
    phone = choose_main_phone(markdown)
    address = extract_address(markdown)
    confidence = calculate_confidence(
        has_known_imprint_url=has_known_imprint_url,
        has_legal=bool(identity.get("legal_name") or identity.get("legal_form")),
        has_decision=bool(decision.get("name")),
        has_contact=bool(email or phone),
        has_address=bool(address),
        has_markdown=bool(markdown),
    )
    return FirecrawlExtractedData(
        legal_name=identity.get("legal_name", ""),
        legal_form=identity.get("legal_form", ""),
        address=address,
        managing_director_name=str(decision.get("name") or ""),
        managing_director_source="firecrawl_markdown" if decision.get("name") else "",
        general_email=email,
        phone_main=phone,
        confidence_score=confidence,
        parse_status="complete" if confidence >= 0.70 else "low_confidence",
    )


def calculate_confidence(
    *,
    has_known_imprint_url: bool,
    has_legal: bool,
    has_decision: bool,
    has_contact: bool,
    has_address: bool,
    has_markdown: bool,
) -> float:
    if not has_markdown:
        return 0.0
    score = 0.20
    if has_known_imprint_url:
        score += 0.20
    if has_legal:
        score += 0.20
    if has_decision:
        score += 0.25
    if has_contact:
        score += 0.15
    if has_address:
        score += 0.10
    return min(0.97 if has_known_imprint_url else 0.80, score)


def known_extraction_url(row: dict[str, str]) -> str:
    domain = normalize_domain(row.get("domain") or row.get("website_url"))
    for key in ("imprint_url", "contact_url"):
        url = clean_text(row.get(key))
        if url and (not domain or normalize_domain(url) == domain):
            return url
    return ""


def build_summary(response: FirecrawlScrapeResponse, markdown: str) -> str:
    parts = []
    if response.title:
        parts.append(clean_text(response.title))
    if markdown:
        parts.append(markdown[:280])
    if response.warning:
        parts.append(f"Warning: {clean_text(response.warning)[:160]}")
    return " | ".join(part for part in parts if part)


def append_source_url(row: dict[str, str], url: str) -> None:
    if not url:
        return
    existing = [part for part in row.get("free_enrichment_source_urls", "").split("|") if part]
    if url not in existing:
        existing.append(url)
    row["free_enrichment_source_urls"] = "|".join(existing)


def existing_confidence(row: dict[str, str]) -> float:
    try:
        value = float(clean_text(row.get("confidence_score")).replace(",", "."))
    except ValueError:
        return 0.0
    if value > 1:
        value /= 100
    return max(0.0, min(1.0, value))


def merge_if_present(row: dict[str, str], key: str, value: str) -> None:
    merge_quality_value(row, key, value)


def redecide_row(row: dict[str, str], policy: EnrichmentPolicy) -> dict[str, str]:
    updated = ensure_queue_row(row)
    clay = assess_clay_eligibility(updated)
    updated["clay_eligible"] = bool_string(clay.eligible)
    updated["clay_reason"] = clay.reason
    decision = decide_next_step(updated, policy)
    updated["enrichment_status"] = decision.status
    updated["next_enrichment_step"] = decision.next_step
    updated["waterfall_reason"] = decision.reason
    updated["provider_recommended"] = decision.provider
    updated["requires_external_provider"] = bool_string(decision.requires_external_provider)
    if truthy(updated.get("firecrawl_used")) and updated.get("next_enrichment_step").startswith(
        "firecrawl_"
    ):
        updated["enrichment_status"] = "queued_manual_review"
        updated["next_enrichment_step"] = "manual_review"
        updated["waterfall_reason"] = "Firecrawl already ran; low-confidence result needs manual review."
        updated["provider_recommended"] = ""
        updated["requires_external_provider"] = bool_string(False)
    return updated


def ensure_queue_row(row: dict[str, str]) -> dict[str, str]:
    return sanitize_queue_fields({field: clean_text(row.get(field)) for field in QUEUE_FIELDS})


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def timestamp_for_filename(timestamp: str) -> str:
    return timestamp.replace("-", "").replace(":", "").replace("T", "_").replace("Z", "")
