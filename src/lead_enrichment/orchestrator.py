from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .exporters.csv_exporter import read_csv_rows
from .final_gate import FinalGateOptions, FinalGateResult, run_final_gate
from .firecrawl_fallback import FirecrawlFallbackOptions, ScrapeClient, run_firecrawl_fallback
from .policy import EnrichmentPolicy
from .queue import QueueBuildOptions, QueueBuildResult, build_enrichment_queue
from .serper_fallback import SearchClient, SerperFallbackOptions, run_serper_fallback
from .tavily_research import ResearchClient, TavilyResearchOptions, run_tavily_research
from .website_enrichment import FetchFn, WebsiteEnrichmentOptions, run_free_website_enrichment


@dataclass(frozen=True)
class WaterfallRunOptions:
    verified_path: Path
    review_path: Path | None = None
    output_dir: Path = Path("data/output")
    policy_path: Path | None = Path("config/enrichment_policy.json")
    limit: int | None = None
    run_website: bool = True
    run_providers: bool = True
    provider_rounds: int = 1
    clay_results_path: Path | None = None
    serper_results_per_query: int = 5
    tavily_max_results: int = 5


@dataclass(frozen=True)
class StepSummary:
    name: str
    status: str
    detail: str = ""
    counts: dict[str, int] | None = None
    paths: dict[str, str] | None = None


@dataclass(frozen=True)
class WaterfallRunResult:
    queue_path: str
    final_result: FinalGateResult
    summary_path: str
    steps: list[StepSummary]


def run_waterfall(
    options: WaterfallRunOptions,
    *,
    fetcher: FetchFn | None = None,
    serper_client: SearchClient | None = None,
    firecrawl_client: ScrapeClient | None = None,
    tavily_client: ResearchClient | None = None,
) -> WaterfallRunResult:
    policy = EnrichmentPolicy.from_file(options.policy_path)
    steps: list[StepSummary] = []
    options.output_dir.mkdir(parents=True, exist_ok=True)

    queue_result = build_enrichment_queue(
        QueueBuildOptions(
            verified_path=options.verified_path,
            review_path=options.review_path,
            output_dir=options.output_dir,
            policy_path=options.policy_path,
            limit=options.limit,
        )
    )
    queue_path = Path(queue_result.queue_path)
    steps.append(summary_from_queue(queue_result))

    if options.run_website:
        website_result = run_free_website_enrichment(
            WebsiteEnrichmentOptions(
                queue_path=queue_path,
                output_dir=options.output_dir,
                policy_path=options.policy_path,
                limit=None,
            ),
            fetcher=fetcher,
        )
        queue_path = options.output_dir / "enrichment_queue.csv"
        steps.append(
            StepSummary(
                name="free_website_enrichment",
                status="completed",
                detail="Public website/imprint enrichment finished.",
                counts={
                    "processed": website_result.processed_count,
                    "clay_rows": website_result.clay_row_count,
                },
                paths={
                    "enriched": website_result.enriched_path,
                    "review": website_result.review_path,
                    "clay_queue": website_result.clay_queue_path,
                    "run": website_result.run_path,
                },
            )
        )
    else:
        steps.append(
            StepSummary(
                name="free_website_enrichment",
                status="skipped",
                detail="Skipped by run option.",
            )
        )

    if options.run_providers:
        provider_steps = run_provider_rounds(
            queue_path,
            options,
            policy,
            serper_client=serper_client,
            firecrawl_client=firecrawl_client,
            tavily_client=tavily_client,
        )
        steps.extend(provider_steps)
    else:
        steps.append(
            StepSummary(
                name="provider_waterfall",
                status="skipped",
                detail="Skipped by run option.",
            )
        )

    final_result = run_final_gate(
        FinalGateOptions(
            queue_path=queue_path,
            output_dir=options.output_dir,
            clay_results_path=options.clay_results_path,
        )
    )
    steps.append(
        StepSummary(
            name="final_gate",
            status="completed",
            detail="Compliance and export gate finished.",
            counts={
                "rows": final_result.row_count,
                "review": final_result.review_count,
                "outreach_ready": final_result.outreach_ready_count,
                "do_not_contact": final_result.do_not_contact_count,
                "instantly_ready": final_result.instantly_ready_count,
            },
            paths={
                "enriched": final_result.enriched_path,
                "compliance_review": final_result.compliance_review_path,
                "review": final_result.review_path,
                "outreach_ready": final_result.outreach_ready_path,
                "do_not_contact": final_result.do_not_contact_path,
                "instantly_ready": final_result.instantly_ready_path,
                "run": final_result.run_path,
            },
        )
    )

    summary_path = write_run_summary(options, queue_path, final_result, steps)
    return WaterfallRunResult(
        queue_path=str(queue_path),
        final_result=final_result,
        summary_path=str(summary_path),
        steps=steps,
    )


def run_provider_rounds(
    queue_path: Path,
    options: WaterfallRunOptions,
    policy: EnrichmentPolicy,
    *,
    serper_client: SearchClient | None,
    firecrawl_client: ScrapeClient | None,
    tavily_client: ResearchClient | None,
) -> list[StepSummary]:
    steps: list[StepSummary] = []
    usage = {"serper": 0, "firecrawl": 0, "tavily": 0}
    for round_number in range(1, max(1, options.provider_rounds) + 1):
        round_steps: list[StepSummary] = []
        for provider in ("serper", "firecrawl", "tavily"):
            step = maybe_run_provider(
                provider,
                queue_path,
                options,
                policy,
                usage=usage,
                round_number=round_number,
                serper_client=serper_client,
                firecrawl_client=firecrawl_client,
                tavily_client=tavily_client,
            )
            if step:
                round_steps.append(step)
        if not round_steps:
            steps.append(
                StepSummary(
                    name=f"provider_round_{round_number}",
                    status="skipped",
                    detail="No enabled provider rows were ready.",
                )
            )
            break
        steps.extend(round_steps)
        if not any(step.status == "completed" and step.counts for step in round_steps):
            break
    return steps


def maybe_run_provider(
    provider: str,
    queue_path: Path,
    options: WaterfallRunOptions,
    policy: EnrichmentPolicy,
    *,
    usage: dict[str, int],
    round_number: int,
    serper_client: SearchClient | None,
    firecrawl_client: ScrapeClient | None,
    tavily_client: ResearchClient | None,
) -> StepSummary | None:
    if not provider_rows_exist(queue_path, provider):
        return None
    if not policy.provider_enabled(provider):
        return StepSummary(
            name=f"{provider}_round_{round_number}",
            status="skipped",
            detail=f"Provider '{provider}' has queued rows but is disabled by policy.",
        )
    remaining_budget = remaining_provider_budget(policy, provider, usage)
    if remaining_budget <= 0:
        return StepSummary(
            name=f"{provider}_round_{round_number}",
            status="skipped",
            detail=f"Provider '{provider}' has no remaining daily budget available.",
        )

    if provider == "serper":
        result = run_serper_fallback(
            SerperFallbackOptions(
                queue_path=queue_path,
                output_dir=options.output_dir,
                policy_path=options.policy_path,
                limit=None,
                query_limit=remaining_budget,
                results_per_query=options.serper_results_per_query,
            ),
            client=serper_client,
        )
        usage["serper"] += result.query_count
        return StepSummary(
            name=f"serper_round_{round_number}",
            status="completed",
            detail="Serper targeted search fallback finished.",
            counts={"processed": result.processed_count, "queries": result.query_count},
            paths={"run": result.run_path, "enriched": result.enriched_path},
        )
    if provider == "firecrawl":
        result = run_firecrawl_fallback(
            FirecrawlFallbackOptions(
                queue_path=queue_path,
                output_dir=options.output_dir,
                policy_path=options.policy_path,
                limit=None,
                page_limit=remaining_budget,
            ),
            client=firecrawl_client,
        )
        usage["firecrawl"] += result.page_count
        return StepSummary(
            name=f"firecrawl_round_{round_number}",
            status="completed",
            detail="Firecrawl known-URL extraction fallback finished.",
            counts={"processed": result.processed_count, "pages": result.page_count},
            paths={"run": result.run_path, "enriched": result.enriched_path},
        )
    if provider == "tavily":
        result = run_tavily_research(
            TavilyResearchOptions(
                queue_path=queue_path,
                output_dir=options.output_dir,
                policy_path=options.policy_path,
                limit=None,
                credit_limit=remaining_budget,
                max_results=options.tavily_max_results,
            ),
            client=tavily_client,
        )
        usage["tavily"] += result.credit_count
        return StepSummary(
            name=f"tavily_round_{round_number}",
            status="completed",
            detail="Tavily ambiguity research finished.",
            counts={
                "processed": result.processed_count,
                "queries": result.query_count,
                "credits": result.credit_count,
            },
            paths={"run": result.run_path, "enriched": result.enriched_path},
        )
    return None


def provider_rows_exist(queue_path: Path, provider: str) -> bool:
    if not queue_path.exists():
        return False
    for row in read_csv_rows(queue_path):
        if row.get("provider_recommended") == provider:
            return True
        if row.get("next_enrichment_step", "").startswith(f"{provider}_"):
            return True
    return False


def provider_budget_available(policy: EnrichmentPolicy, provider: str) -> bool:
    return provider_budget(policy, provider) > 0


def provider_budget(policy: EnrichmentPolicy, provider: str) -> int:
    if provider == "serper":
        return policy.serper_daily_limit
    if provider == "firecrawl":
        return policy.firecrawl_daily_limit
    if provider == "tavily":
        return policy.tavily_daily_limit
    return 0


def remaining_provider_budget(policy: EnrichmentPolicy, provider: str, usage: dict[str, int]) -> int:
    return max(0, provider_budget(policy, provider) - usage.get(provider, 0))


def summary_from_queue(result: QueueBuildResult) -> StepSummary:
    return StepSummary(
        name="prepare_queue",
        status="completed",
        detail="Enrichment queue prepared from verified/review CSV input.",
        counts={"rows": result.row_count, "clay_rows": result.clay_row_count},
        paths={"queue": result.queue_path, "clay_queue": result.clay_queue_path},
    )


def write_run_summary(
    options: WaterfallRunOptions,
    queue_path: Path,
    final_result: FinalGateResult,
    steps: list[StepSummary],
) -> Path:
    run_dir = options.output_dir / "runs"
    run_dir.mkdir(parents=True, exist_ok=True)
    timestamp = now_utc()
    summary_path = run_dir / f"waterfall_summary_{timestamp_for_filename(timestamp)}.json"
    payload: dict[str, Any] = {
        "created_at": timestamp,
        "verified_path": str(options.verified_path),
        "review_path": str(options.review_path or ""),
        "queue_path": str(queue_path),
        "policy_path": str(options.policy_path or ""),
        "run_website": options.run_website,
        "run_providers": options.run_providers,
        "provider_rounds": options.provider_rounds,
        "clay_results_path": str(options.clay_results_path or ""),
        "final_counts": {
            "rows": final_result.row_count,
            "review": final_result.review_count,
            "outreach_ready": final_result.outreach_ready_count,
            "do_not_contact": final_result.do_not_contact_count,
            "instantly_ready": final_result.instantly_ready_count,
        },
        "steps": [asdict(step) for step in steps],
    }
    summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return summary_path


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def timestamp_for_filename(timestamp: str) -> str:
    return timestamp.replace("-", "").replace(":", "").replace("T", "_").replace("Z", "")
