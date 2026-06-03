from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .clay import assess_clay_eligibility
from .data_quality import overwrite_with_quality_value, sanitize_queue_fields
from .exporters.csv_exporter import read_csv_rows, write_csv_rows
from .extractors.decision_makers import extract_decision_maker
from .normalizer import bool_string, clean_text, normalize_domain
from .policy import EnrichmentPolicy
from .providers.base import SearchResult
from .providers.serper_client import SerperClient, SerperSearchResponse
from .quality import quality_rank
from .queue import QUEUE_FIELDS
from .website_enrichment import needs_review
from .waterfall import decide_next_step


class SearchClient(Protocol):
    def search(self, query: str, *, num: int = 5, gl: str = "de", hl: str = "de") -> SerperSearchResponse:
        ...


@dataclass(frozen=True)
class SerperFallbackOptions:
    queue_path: Path
    output_dir: Path = Path("data/output")
    policy_path: Path | None = None
    limit: int | None = None
    query_limit: int | None = None
    results_per_query: int = 5
    require_provider_enabled: bool = True


@dataclass(frozen=True)
class SerperFallbackResult:
    enriched_path: str
    review_path: str
    clay_queue_path: str
    run_path: str
    processed_count: int
    query_count: int
    clay_row_count: int


@dataclass(frozen=True)
class SerperPlan:
    queries: tuple[str, ...]
    purpose: str


def run_serper_fallback(
    options: SerperFallbackOptions,
    client: SearchClient | None = None,
) -> SerperFallbackResult:
    policy = EnrichmentPolicy.from_file(options.policy_path)
    if options.require_provider_enabled and not policy.provider_enabled("serper"):
        raise RuntimeError(
            "Serper provider is disabled. Copy config/enrichment_policy.example.json to "
            "config/enrichment_policy.json and set providers.serper.enabled=true."
        )
    active_client = client or SerperClient()
    rows = read_csv_rows(options.queue_path)
    processed = 0
    queries_used = 0
    row_budget = options.limit if options.limit is not None else len(rows)
    query_budget = max(0, policy.serper_daily_limit)
    if options.query_limit is not None:
        query_budget = min(query_budget, max(0, options.query_limit))
    updated_rows: list[dict[str, str]] = []
    timestamp = now_utc()

    for row in rows:
        normalized = ensure_queue_row(row)
        if should_process(normalized) and processed < row_budget and queries_used < query_budget:
            remaining = query_budget - queries_used
            updated, used = enrich_with_serper(
                normalized,
                policy,
                active_client,
                max_queries=remaining,
                results_per_query=options.results_per_query,
            )
            processed += 1 if used else 0
            queries_used += used
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
    run_path = run_dir / f"serper_fallback_{timestamp_for_filename(timestamp)}.csv"

    write_csv_rows(enriched_path, updated_rows, QUEUE_FIELDS)
    write_csv_rows(review_path, review_rows, QUEUE_FIELDS)
    write_csv_rows(clay_path, clay_rows, QUEUE_FIELDS)
    write_csv_rows(queue_path, updated_rows, QUEUE_FIELDS)
    write_csv_rows(run_path, updated_rows, QUEUE_FIELDS)

    return SerperFallbackResult(
        enriched_path=str(enriched_path),
        review_path=str(review_path),
        clay_queue_path=str(clay_path),
        run_path=str(run_path),
        processed_count=processed,
        query_count=queries_used,
        clay_row_count=len(clay_rows),
    )


def should_process(row: dict[str, str]) -> bool:
    return row.get("provider_recommended") == "serper" or row.get("next_enrichment_step", "").startswith(
        "serper_"
    )


def enrich_with_serper(
    row: dict[str, str],
    policy: EnrichmentPolicy,
    client: SearchClient,
    *,
    max_queries: int,
    results_per_query: int,
) -> tuple[dict[str, str], int]:
    plan = plan_serper_queries(row, policy)
    if not plan.queries or max_queries <= 0:
        return row, 0
    query_limit = min(max_queries, len(plan.queries), max_queries_for_lead(row, policy))
    used_queries: list[str] = []
    all_results: list[SearchResult] = []
    enriched = dict(row)

    for query in plan.queries[:query_limit]:
        response = client.search(query, num=results_per_query, gl="de", hl="de")
        used_queries.append(query)
        all_results.extend(response.results)
        apply_serper_results(enriched, plan.purpose, response.results)
        if serper_goal_satisfied(enriched, plan.purpose):
            break

    enriched["serper_used"] = bool_string(bool(used_queries))
    enriched["serper_queries"] = " | ".join(used_queries)
    enriched["serper_result_urls"] = "|".join(unique_links(all_results))
    enriched["serper_summary"] = build_summary(all_results)
    enriched["serper_confidence_score"] = f"{serper_confidence(enriched, plan.purpose):.2f}"
    return enriched, len(used_queries)


def plan_serper_queries(row: dict[str, str], policy: EnrichmentPolicy) -> SerperPlan:
    del policy
    step = row.get("next_enrichment_step", "")
    domain = normalize_domain(row.get("domain") or row.get("website_url"))
    company = clean_text(row.get("company_name") or row.get("legal_name"))
    if "find_imprint" in step:
        queries = [f"site:{domain} impressum", f'"{domain}" impressum']
        if company:
            queries.append(f'"{company}" Impressum')
        return SerperPlan(tuple(queries), "imprint")
    if "find_decision_maker" in step:
        queries = [f'site:{domain} "Gesch\u00e4ftsf\u00fchrer"']
        if company:
            queries.extend(
                [
                    f'"{company}" Gesch\u00e4ftsf\u00fchrer',
                    f'"{company}" Inhaber',
                ]
            )
        queries.append(f'site:{domain} "Vertreten durch"')
        return SerperPlan(tuple(queries), "decision_maker")
    return SerperPlan((), "")


def max_queries_for_lead(row: dict[str, str], policy: EnrichmentPolicy) -> int:
    quality = row.get("lead_quality", "")
    if quality == "A++":
        return policy.max_serper_queries_a_plus_plus_lead
    if quality_rank(quality) <= quality_rank("B"):
        return policy.max_serper_queries_b_lead
    return 3


def apply_serper_results(row: dict[str, str], purpose: str, results: list[SearchResult]) -> None:
    if purpose == "imprint" and not row.get("imprint_url"):
        imprint = choose_imprint_url(row, results)
        if imprint:
            row["imprint_url"] = imprint
            row["imprint_parse_status"] = "serper_url_found"
    if purpose == "decision_maker":
        decision = extract_decision_maker(results_as_text(results))
        if decision.get("name"):
            previous_name = row.get("managing_director_name", "")
            overwrite_with_quality_value(row, "managing_director_name", str(decision["name"]))
            if row.get("managing_director_name") and row.get("managing_director_name") != previous_name:
                row["managing_director_source"] = "serper_snippet"


def choose_imprint_url(row: dict[str, str], results: list[SearchResult]) -> str:
    domain = normalize_domain(row.get("domain") or row.get("website_url"))
    for result in results:
        haystack = f"{result.link} {result.title} {result.snippet}".lower()
        if domain and normalize_domain(result.link) != domain:
            continue
        if any(token in haystack for token in ("impressum", "imprint", "anbieterkennzeichnung")):
            return result.link
    return ""


def serper_goal_satisfied(row: dict[str, str], purpose: str) -> bool:
    if purpose == "imprint":
        return bool(row.get("imprint_url"))
    if purpose == "decision_maker":
        return bool(row.get("managing_director_name"))
    return False


def serper_confidence(row: dict[str, str], purpose: str) -> float:
    if purpose == "imprint" and row.get("imprint_url"):
        return 0.75
    if purpose == "decision_maker" and row.get("managing_director_name"):
        return 0.70
    return 0.30


def results_as_text(results: list[SearchResult]) -> str:
    return " ".join(f"{result.title} {result.snippet}" for result in results)


def unique_links(results: list[SearchResult]) -> list[str]:
    seen: set[str] = set()
    links: list[str] = []
    for result in results:
        if result.link and result.link not in seen:
            seen.add(result.link)
            links.append(result.link)
    return links


def build_summary(results: list[SearchResult]) -> str:
    parts = []
    for result in results[:3]:
        text = clean_text(f"{result.title}: {result.snippet}")
        if text:
            parts.append(text[:220])
    return " | ".join(parts)


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


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def timestamp_for_filename(timestamp: str) -> str:
    return timestamp.replace("-", "").replace(":", "").replace("T", "_").replace("Z", "")
