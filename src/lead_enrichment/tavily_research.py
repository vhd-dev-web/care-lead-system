from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .clay import assess_clay_eligibility
from .data_quality import merge_quality_value, overwrite_with_quality_value, sanitize_queue_fields
from .exporters.csv_exporter import read_csv_rows, write_csv_rows
from .extractors.company_identity import company_identity_from_text
from .extractors.decision_makers import extract_decision_maker
from .normalizer import bool_string, clean_text, normalize_domain, truthy
from .policy import EnrichmentPolicy
from .providers.tavily_client import TavilyClient, TavilyResult, TavilySearchResponse
from .queue import QUEUE_FIELDS
from .website_enrichment import needs_review
from .waterfall import decide_next_step


class ResearchClient(Protocol):
    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        search_depth: str = "basic",
        country: str = "germany",
    ) -> TavilySearchResponse:
        ...


@dataclass(frozen=True)
class TavilyResearchOptions:
    queue_path: Path
    output_dir: Path = Path("data/output")
    policy_path: Path | None = None
    limit: int | None = None
    credit_limit: int | None = None
    max_results: int = 5
    require_provider_enabled: bool = True


@dataclass(frozen=True)
class TavilyResearchResult:
    enriched_path: str
    review_path: str
    clay_queue_path: str
    run_path: str
    processed_count: int
    query_count: int
    credit_count: int
    clay_row_count: int


@dataclass(frozen=True)
class TavilyPlan:
    query: str
    purpose: str


def run_tavily_research(
    options: TavilyResearchOptions,
    client: ResearchClient | None = None,
) -> TavilyResearchResult:
    policy = EnrichmentPolicy.from_file(options.policy_path)
    if options.require_provider_enabled and not policy.provider_enabled("tavily"):
        raise RuntimeError(
            "Tavily provider is disabled. Copy config/enrichment_policy.example.json to "
            "config/enrichment_policy.json and set providers.tavily.enabled=true."
        )
    active_client = client or TavilyClient()
    rows = read_csv_rows(options.queue_path)
    processed = 0
    queries_used = 0
    credits_used = 0
    row_budget = options.limit if options.limit is not None else len(rows)
    credit_budget = max(0, policy.tavily_daily_limit)
    if options.credit_limit is not None:
        credit_budget = min(credit_budget, max(0, options.credit_limit))
    updated_rows: list[dict[str, str]] = []
    timestamp = now_utc()

    for row in rows:
        normalized = ensure_queue_row(row)
        if should_process(normalized) and processed < row_budget and credits_used < credit_budget:
            updated, query_count, credit_count = enrich_with_tavily(
                normalized,
                active_client,
                max_results=options.max_results,
            )
            if query_count:
                processed += 1
                queries_used += query_count
                credits_used += max(1, credit_count)
            normalized = updated
        updated_rows.append(redecide_row(normalized, policy))

    clay_rows = [
        row for row in updated_rows if row["next_enrichment_step"].startswith("clay_email_queue")
    ]
    review_rows = [row for row in updated_rows if needs_review(row) or row["next_enrichment_step"] == "manual_review"]

    output_dir = options.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = output_dir / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    enriched_path = output_dir / "enriched_master.csv"
    review_path = output_dir / "enrichment_review.csv"
    clay_path = output_dir / "clay_queue.csv"
    queue_path = output_dir / "enrichment_queue.csv"
    run_path = run_dir / f"tavily_research_{timestamp_for_filename(timestamp)}.csv"

    write_csv_rows(enriched_path, updated_rows, QUEUE_FIELDS)
    write_csv_rows(review_path, review_rows, QUEUE_FIELDS)
    write_csv_rows(clay_path, clay_rows, QUEUE_FIELDS)
    write_csv_rows(queue_path, updated_rows, QUEUE_FIELDS)
    write_csv_rows(run_path, updated_rows, QUEUE_FIELDS)

    return TavilyResearchResult(
        enriched_path=str(enriched_path),
        review_path=str(review_path),
        clay_queue_path=str(clay_path),
        run_path=str(run_path),
        processed_count=processed,
        query_count=queries_used,
        credit_count=credits_used,
        clay_row_count=len(clay_rows),
    )


def should_process(row: dict[str, str]) -> bool:
    return row.get("provider_recommended") == "tavily" or row.get("next_enrichment_step", "").startswith(
        "tavily_"
    )


def enrich_with_tavily(
    row: dict[str, str],
    client: ResearchClient,
    *,
    max_results: int,
) -> tuple[dict[str, str], int, int]:
    plan = plan_tavily_query(row)
    if not plan.query:
        updated = dict(row)
        updated["tavily_summary"] = "Skipped: no useful research query could be planned."
        return updated, 0, 0

    enriched = dict(row)
    enriched["tavily_used"] = bool_string(True)
    enriched["tavily_queries"] = plan.query
    try:
        response = client.search(plan.query, max_results=max_results, search_depth="basic", country="germany")
    except Exception as exc:  # noqa: BLE001 - provider failures should route to review.
        enriched["tavily_error"] = clean_text(str(exc))[:500]
        enriched["tavily_summary"] = "Tavily request failed; route to manual review."
        return enriched, 1, 1

    combined_text = response_as_text(response)
    identity = company_identity_from_text(combined_text)
    decision = extract_decision_maker(combined_text)
    merge_if_present(enriched, "legal_name", identity.get("legal_name", ""))
    merge_if_present(enriched, "legal_form", identity.get("legal_form", ""))
    if identity.get("legal_name") and not enriched.get("company_name"):
        enriched["company_name"] = identity["legal_name"]
    if decision.get("name"):
        previous_name = enriched.get("managing_director_name", "")
        overwrite_with_quality_value(enriched, "managing_director_name", str(decision["name"]))
        if enriched.get("managing_director_name") and enriched.get("managing_director_name") != previous_name:
            enriched["managing_director_source"] = "tavily_research"
    enriched["tavily_answer"] = clean_text(response.answer)
    enriched["tavily_result_urls"] = "|".join(unique_urls(response.results))
    enriched["tavily_summary"] = build_summary(response)
    enriched["tavily_confidence_score"] = f"{tavily_confidence(row, response):.2f}"
    enriched["tavily_credits"] = str(max(1, response.credits))
    enriched["tavily_error"] = ""
    enriched["research_note"] = research_note(plan, response)
    return enriched, 1, max(1, response.credits)


def plan_tavily_query(row: dict[str, str]) -> TavilyPlan:
    domain = normalize_domain(row.get("domain") or row.get("website_url"))
    company = clean_text(row.get("company_name") or row.get("legal_name"))
    if truthy(row.get("entity_ambiguous")):
        query = f'"{company or domain}" Betreiber Firma Impressum Geschäftsführer {domain}'.strip()
        return TavilyPlan(query=query, purpose="entity")
    if truthy(row.get("decision_maker_ambiguous")):
        query = f'"{company or domain}" Geschäftsführer Inhaber Vertreten durch {domain}'.strip()
        return TavilyPlan(query=query, purpose="decision_maker")
    step = row.get("next_enrichment_step", "")
    if "ambiguous_entity" in step:
        query = f'"{company or domain}" Betreiber Firma Impressum Geschäftsführer {domain}'.strip()
        return TavilyPlan(query=query, purpose="entity")
    return TavilyPlan(query="", purpose="")


def response_as_text(response: TavilySearchResponse) -> str:
    parts = [response.answer]
    for result in response.results:
        parts.append(result.title)
        parts.append(result.content)
        parts.append(result.raw_content)
    return clean_text(" ".join(parts))


def unique_urls(results: list[TavilyResult]) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for result in results:
        if result.url and result.url not in seen:
            seen.add(result.url)
            urls.append(result.url)
    return urls


def build_summary(response: TavilySearchResponse) -> str:
    parts = []
    answer = clean_text(response.answer)
    if answer:
        parts.append(answer[:450])
    for result in response.results[:3]:
        text = clean_text(f"{result.title}: {result.content}")
        if text:
            parts.append(text[:220])
    return " | ".join(parts)


def tavily_confidence(row: dict[str, str], response: TavilySearchResponse) -> float:
    if not response.results and not response.answer:
        return 0.30
    domain = normalize_domain(row.get("domain") or row.get("website_url"))
    same_domain = any(normalize_domain(result.url) == domain for result in response.results)
    text = response_as_text(response).lower()
    has_role = any(token in text for token in ("geschäftsführer", "geschaeftsfuehrer", "inhaber"))
    if same_domain and has_role:
        return 0.75
    if has_role:
        return 0.70
    if same_domain:
        return 0.65
    return 0.55


def research_note(plan: TavilyPlan, response: TavilySearchResponse) -> str:
    urls = unique_urls(response.results)
    lead = f"Tavily {plan.purpose} research"
    if response.answer:
        lead += f": {clean_text(response.answer)[:300]}"
    if urls:
        lead += f" Sources: {' | '.join(urls[:3])}"
    return lead


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


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def timestamp_for_filename(timestamp: str) -> str:
    return timestamp.replace("-", "").replace(":", "").replace("T", "_").replace("Z", "")
