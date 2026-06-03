from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .clay import assess_clay_eligibility
from .data_quality import merge_quality_value, sanitize_queue_fields
from .exporters.csv_exporter import read_csv_rows, write_csv_rows
from .extractors.address import extract_address
from .extractors.company_identity import company_identity_from_text
from .extractors.contacts import choose_general_email, choose_main_phone
from .extractors.decision_makers import extract_decision_maker
from .normalizer import bool_string, clean_text, normalize_domain
from .policy import EnrichmentPolicy
from .queue import QUEUE_FIELDS
from .sources.contact_page import discover_contact_url
from .sources.imprint import absolute_url, discover_imprint_url, extract_links
from .sources.website import FetchResult, fetch_url, html_to_text, same_domain_url
from .waterfall import decide_next_step


FetchFn = Callable[[str], FetchResult]


@dataclass(frozen=True)
class WebsiteEnrichmentOptions:
    queue_path: Path
    output_dir: Path = Path("data/output")
    policy_path: Path | None = None
    limit: int | None = None
    user_agent: str = "VHDLeadEnrichment/0.1 (+https://www.vhd-coaching-x2.de/)"


@dataclass(frozen=True)
class WebsiteEnrichmentResult:
    enriched_path: str
    review_path: str
    clay_queue_path: str
    run_path: str
    processed_count: int
    clay_row_count: int


@dataclass(frozen=True)
class PublicWebsiteData:
    legal_name: str = ""
    legal_form: str = ""
    address: str = ""
    managing_director_name: str = ""
    managing_director_role: str = ""
    managing_director_source: str = ""
    general_email: str = ""
    phone_main: str = ""
    imprint_url: str = ""
    contact_url: str = ""
    confidence_score: float = 0.0
    parse_status: str = "failed"
    source_urls: tuple[str, ...] = ()
    pages_checked: int = 0


def run_free_website_enrichment(
    options: WebsiteEnrichmentOptions,
    fetcher: FetchFn | None = None,
) -> WebsiteEnrichmentResult:
    policy = EnrichmentPolicy.from_file(options.policy_path)
    rows = read_csv_rows(options.queue_path)
    active_fetcher = fetcher or (
        lambda url: fetch_url(url, user_agent=options.user_agent)
    )
    limit = effective_limit(options.limit, policy.website_enrichment_daily_limit)
    processed = 0
    updated_rows: list[dict[str, str]] = []
    timestamp = now_utc()

    for row in rows:
        normalized = ensure_queue_row(row)
        if should_process(normalized) and processed < limit:
            normalized = enrich_queue_row(normalized, policy, active_fetcher)
            processed += 1
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
    run_path = run_dir / f"free_website_enrichment_{timestamp_for_filename(timestamp)}.csv"

    write_csv_rows(enriched_path, updated_rows, QUEUE_FIELDS)
    write_csv_rows(review_path, review_rows, QUEUE_FIELDS)
    write_csv_rows(clay_path, clay_rows, QUEUE_FIELDS)
    write_csv_rows(queue_path, updated_rows, QUEUE_FIELDS)
    write_csv_rows(run_path, updated_rows, QUEUE_FIELDS)

    return WebsiteEnrichmentResult(
        enriched_path=str(enriched_path),
        review_path=str(review_path),
        clay_queue_path=str(clay_path),
        run_path=str(run_path),
        processed_count=processed,
        clay_row_count=len(clay_rows),
    )


def should_process(row: dict[str, str]) -> bool:
    return (
        row.get("next_enrichment_step") == "free_website_enrichment"
        and row.get("do_not_contact") != "true"
        and row.get("domain") != ""
    )


def enrich_queue_row(
    row: dict[str, str],
    policy: EnrichmentPolicy,
    fetcher: FetchFn,
) -> dict[str, str]:
    domain = normalize_domain(row.get("domain") or row.get("website_url"))
    data = extract_public_website_data(domain, row, policy, fetcher)
    enriched = dict(row)
    merge_if_present(enriched, "legal_name", data.legal_name)
    merge_if_present(enriched, "legal_form", data.legal_form)
    if data.legal_name and not enriched.get("company_name"):
        enriched["company_name"] = data.legal_name
    merge_if_present(enriched, "address", data.address)
    merge_if_present(enriched, "general_email", data.general_email)
    merge_if_present(enriched, "phone_main", data.phone_main)
    merge_if_present(enriched, "imprint_url", data.imprint_url)
    merge_if_present(enriched, "contact_url", data.contact_url)
    merge_if_present(enriched, "managing_director_name", data.managing_director_name)
    merge_if_present(enriched, "managing_director_source", data.managing_director_source)
    enriched["confidence_score"] = f"{data.confidence_score:.2f}"
    enriched["imprint_parse_status"] = data.parse_status
    enriched["free_enrichment_status"] = (
        "complete" if data.confidence_score >= 0.70 else data.parse_status
    )
    enriched["free_enrichment_source_urls"] = "|".join(data.source_urls)
    enriched["website_pages_checked"] = str(data.pages_checked)
    return enriched


def extract_public_website_data(
    domain: str,
    row: dict[str, str],
    policy: EnrichmentPolicy,
    fetcher: FetchFn,
) -> PublicWebsiteData:
    if not domain:
        return PublicWebsiteData()
    candidates = candidate_urls(domain, row, policy.website_paths)
    fetched: list[FetchResult] = []
    seen: set[str] = set()
    for url in candidates:
        if url in seen:
            continue
        seen.add(url)
        if len(fetched) >= policy.website_pages_per_domain:
            break
        result = fetcher(url)
        fetched.append(result)
        if is_home_url(url, domain) and result.html:
            for discovered in discover_home_links(domain, result.html):
                if discovered not in seen:
                    candidates.append(discovered)

    successful = [result for result in fetched if result.html and 200 <= result.status < 400]
    combined_text = " ".join(html_to_text(result.html) for result in successful)
    identity = company_identity_from_text(combined_text)
    decision = extract_decision_maker(combined_text)
    email = choose_general_email(combined_text)
    phone = choose_main_phone(combined_text)
    address = extract_address(combined_text)
    imprint_url = first_matching_url(successful, ("impressum", "imprint", "anbieterkennzeichnung"))
    contact_url = first_matching_url(successful, ("kontakt", "contact"))
    confidence = calculate_confidence(
        has_imprint=bool(imprint_url),
        has_legal=bool(identity.get("legal_name") or identity.get("legal_form")),
        has_decision=bool(decision.get("name")),
        has_contact=bool(email or phone),
        has_address=bool(address),
        pages_successful=bool(successful),
    )
    if not successful:
        parse_status = "failed"
    elif confidence >= 0.70:
        parse_status = "complete"
    else:
        parse_status = "low_confidence"
    return PublicWebsiteData(
        legal_name=identity.get("legal_name", ""),
        legal_form=identity.get("legal_form", ""),
        address=address,
        managing_director_name=str(decision.get("name") or ""),
        managing_director_role=str(decision.get("role") or ""),
        managing_director_source=str(decision.get("source") or ""),
        general_email=email,
        phone_main=phone,
        imprint_url=imprint_url,
        contact_url=contact_url,
        confidence_score=confidence,
        parse_status=parse_status,
        source_urls=tuple(result.url for result in successful),
        pages_checked=len(fetched),
    )


def candidate_urls(domain: str, row: dict[str, str], paths: list[str]) -> list[str]:
    candidates: list[str] = []
    candidates.append(same_domain_url(domain, "/"))
    for key in ("imprint_url", "contact_url", "website_url", "source_url"):
        url = clean_text(row.get(key))
        if url and normalize_domain(url) == domain:
            candidates.append(url)
    for path in paths:
        candidates.append(same_domain_url(domain, path))
    return candidates


def discover_home_links(domain: str, html: str) -> list[str]:
    discovered = [discover_imprint_url(domain, html), discover_contact_url(domain, html)]
    for href, label in extract_links(html):
        lowered = f"{href} {label}".lower()
        if any(token in lowered for token in ("datenschutz", "ueber", "über", "team")):
            discovered.append(absolute_url(domain, href))
    return discovered


def calculate_confidence(
    *,
    has_imprint: bool,
    has_legal: bool,
    has_decision: bool,
    has_contact: bool,
    has_address: bool,
    pages_successful: bool,
) -> float:
    if not pages_successful:
        return 0.0
    score = 0.20
    if has_imprint:
        score += 0.25
    if has_legal:
        score += 0.20
    if has_decision:
        score += 0.20
    if has_contact:
        score += 0.15
    if has_address:
        score += 0.10
    return min(0.95 if has_imprint else 0.75, score)


def first_matching_url(results: list[FetchResult], tokens: tuple[str, ...]) -> str:
    for result in results:
        lowered = result.url.lower()
        if any(token in lowered for token in tokens):
            return result.url
    return ""


def is_home_url(url: str, domain: str) -> bool:
    return url.rstrip("/") == same_domain_url(domain, "/").rstrip("/")


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
    return updated


def ensure_queue_row(row: dict[str, str]) -> dict[str, str]:
    return sanitize_queue_fields({field: clean_text(row.get(field)) for field in QUEUE_FIELDS})


def needs_review(row: dict[str, str]) -> bool:
    return (
        row.get("enrichment_status") == "provider_disabled"
        or row.get("free_enrichment_status") in {"low_confidence", "failed"}
    )


def effective_limit(requested: int | None, policy_limit: int) -> int:
    if requested is None:
        return max(0, policy_limit)
    return max(0, min(requested, policy_limit))


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def timestamp_for_filename(timestamp: str) -> str:
    return timestamp.replace("-", "").replace(":", "").replace("T", "_").replace("Z", "")
