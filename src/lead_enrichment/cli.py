from __future__ import annotations

import argparse
from pathlib import Path

from .firecrawl_fallback import FirecrawlFallbackOptions, run_firecrawl_fallback
from .final_gate import FinalGateOptions, run_final_gate
from .orchestrator import WaterfallRunOptions, run_waterfall
from .pipeline import EnrichmentOptions, run_enrichment
from .queue import QueueBuildOptions, build_enrichment_queue
from .serper_fallback import SerperFallbackOptions, run_serper_fallback
from .tavily_research import TavilyResearchOptions, run_tavily_research
from .website_enrichment import WebsiteEnrichmentOptions, run_free_website_enrichment


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lead_enrichment",
        description="Free-first lead enrichment with compliance gates.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    enrich = subparsers.add_parser("enrich", help="Run lead enrichment.")
    enrich.add_argument("--input", required=True, help="Input CSV path.")
    enrich.add_argument("--output-dir", default="data/output", help="Output directory.")
    enrich.add_argument(
        "--mode",
        choices=["csv-only", "website"],
        default="csv-only",
        help="Enrichment mode. csv-only makes no network requests.",
    )
    enrich.add_argument("--limit", type=int, default=None, help="Maximum rows to process.")
    enrich.add_argument(
        "--website-pages-per-domain",
        type=int,
        default=3,
        help="Maximum public pages per domain in website mode.",
    )
    queue = subparsers.add_parser(
        "prepare-queue",
        help="Build enrichment_queue.csv and clay_queue.csv without provider calls.",
    )
    queue.add_argument("--verified", required=True, help="Verified master CSV from scraper.")
    queue.add_argument("--review", default=None, help="Optional review master CSV from scraper.")
    queue.add_argument("--output-dir", default="data/output", help="Output directory.")
    queue.add_argument(
        "--policy",
        default="config/enrichment_policy.json",
        help="Optional local enrichment policy JSON. Missing file falls back to safe defaults.",
    )
    queue.add_argument("--limit", type=int, default=None, help="Maximum rows to process.")
    website = subparsers.add_parser(
        "free-website-enrich",
        help="Run free website/imprint enrichment for queued leads.",
    )
    website.add_argument(
        "--queue",
        default="data/output/enrichment_queue.csv",
        help="Input enrichment queue CSV.",
    )
    website.add_argument("--output-dir", default="data/output", help="Output directory.")
    website.add_argument(
        "--policy",
        default="config/enrichment_policy.json",
        help="Optional local enrichment policy JSON. Missing file falls back to safe defaults.",
    )
    website.add_argument("--limit", type=int, default=None, help="Maximum queued leads to enrich.")
    serper = subparsers.add_parser(
        "serper-fallback",
        help="Run Serper fallback for planned Serper waterfall rows.",
    )
    serper.add_argument(
        "--queue",
        default="data/output/enrichment_queue.csv",
        help="Input enrichment queue CSV.",
    )
    serper.add_argument("--output-dir", default="data/output", help="Output directory.")
    serper.add_argument(
        "--policy",
        default="config/enrichment_policy.json",
        help="Local enrichment policy JSON. Serper must be enabled there.",
    )
    serper.add_argument("--limit", type=int, default=None, help="Maximum Serper-eligible rows to process.")
    serper.add_argument(
        "--results-per-query",
        type=int,
        default=5,
        help="Number of Serper organic results to request per query.",
    )
    firecrawl = subparsers.add_parser(
        "firecrawl-fallback",
        help="Run Firecrawl scrape fallback for known imprint/contact URLs.",
    )
    firecrawl.add_argument(
        "--queue",
        default="data/output/enrichment_queue.csv",
        help="Input enrichment queue CSV.",
    )
    firecrawl.add_argument("--output-dir", default="data/output", help="Output directory.")
    firecrawl.add_argument(
        "--policy",
        default="config/enrichment_policy.json",
        help="Local enrichment policy JSON. Firecrawl must be enabled there.",
    )
    firecrawl.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum Firecrawl-eligible rows to process.",
    )
    tavily = subparsers.add_parser(
        "tavily-research",
        help="Run Tavily research for ambiguous company or decision-maker rows.",
    )
    tavily.add_argument(
        "--queue",
        default="data/output/enrichment_queue.csv",
        help="Input enrichment queue CSV.",
    )
    tavily.add_argument("--output-dir", default="data/output", help="Output directory.")
    tavily.add_argument(
        "--policy",
        default="config/enrichment_policy.json",
        help="Local enrichment policy JSON. Tavily must be enabled there.",
    )
    tavily.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum Tavily-eligible rows to process.",
    )
    tavily.add_argument(
        "--max-results",
        type=int,
        default=5,
        help="Maximum Tavily results per research query.",
    )
    final = subparsers.add_parser(
        "finalize",
        help="Run final compliance gate and write review/outreach/Instantly exports.",
    )
    final.add_argument(
        "--queue",
        default="data/output/enrichment_queue.csv",
        help="Input enrichment queue CSV.",
    )
    final.add_argument("--output-dir", default="data/output", help="Output directory.")
    final.add_argument(
        "--clay-results",
        default=None,
        help="Optional manual Clay result CSV to merge before final gating.",
    )
    waterfall = subparsers.add_parser(
        "run-waterfall",
        help="Run the full controlled enrichment waterfall from scraper CSV to final exports.",
    )
    waterfall.add_argument("--verified", required=True, help="Verified master CSV from scraper.")
    waterfall.add_argument("--review", default=None, help="Optional review master CSV from scraper.")
    waterfall.add_argument("--output-dir", default="data/output", help="Output directory.")
    waterfall.add_argument(
        "--policy",
        default="config/enrichment_policy.json",
        help="Optional local enrichment policy JSON. Missing file falls back to safe defaults.",
    )
    waterfall.add_argument("--limit", type=int, default=None, help="Maximum input rows to process.")
    waterfall.add_argument(
        "--skip-website",
        action="store_true",
        help="Skip free website/imprint enrichment and only use CSV/queue data.",
    )
    waterfall.add_argument(
        "--skip-providers",
        action="store_true",
        help="Skip Serper, Firecrawl, and Tavily even when enabled in policy.",
    )
    waterfall.add_argument(
        "--provider-rounds",
        type=int,
        default=1,
        help=(
            "Maximum provider waterfall rounds. Defaults to 1 until global provider "
            "budgeting and parser quality are proven on larger batches."
        ),
    )
    waterfall.add_argument(
        "--clay-results",
        default=None,
        help="Optional manual Clay result CSV to merge during final gating.",
    )
    waterfall.add_argument(
        "--serper-results-per-query",
        type=int,
        default=5,
        help="Number of Serper organic results per query.",
    )
    waterfall.add_argument(
        "--tavily-max-results",
        type=int,
        default=5,
        help="Maximum Tavily results per research query.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "enrich":
        result = run_enrichment(
            EnrichmentOptions(
                input_path=Path(args.input),
                output_dir=Path(args.output_dir),
                mode=args.mode,
                limit=args.limit,
                website_pages_per_domain=args.website_pages_per_domain,
            )
        )
        print(f"enriched={result.enriched_path}")
        print(f"review={result.review_path}")
        print(f"outreach_ready={result.outreach_ready_path}")
        print(f"run={result.run_path}")
    elif args.command == "prepare-queue":
        result = build_enrichment_queue(
            QueueBuildOptions(
                verified_path=Path(args.verified),
                review_path=Path(args.review) if args.review else None,
                output_dir=Path(args.output_dir),
                policy_path=Path(args.policy) if args.policy else None,
                limit=args.limit,
            )
        )
        print(f"queue={result.queue_path}")
        print(f"clay_queue={result.clay_queue_path}")
        print(f"rows={result.row_count}")
        print(f"clay_rows={result.clay_row_count}")
    elif args.command == "free-website-enrich":
        result = run_free_website_enrichment(
            WebsiteEnrichmentOptions(
                queue_path=Path(args.queue),
                output_dir=Path(args.output_dir),
                policy_path=Path(args.policy) if args.policy else None,
                limit=args.limit,
            )
        )
        print(f"enriched={result.enriched_path}")
        print(f"review={result.review_path}")
        print(f"clay_queue={result.clay_queue_path}")
        print(f"run={result.run_path}")
        print(f"processed={result.processed_count}")
        print(f"clay_rows={result.clay_row_count}")
    elif args.command == "serper-fallback":
        result = run_serper_fallback(
            SerperFallbackOptions(
                queue_path=Path(args.queue),
                output_dir=Path(args.output_dir),
                policy_path=Path(args.policy) if args.policy else None,
                limit=args.limit,
                results_per_query=args.results_per_query,
            )
        )
        print(f"enriched={result.enriched_path}")
        print(f"review={result.review_path}")
        print(f"clay_queue={result.clay_queue_path}")
        print(f"run={result.run_path}")
        print(f"processed={result.processed_count}")
        print(f"queries={result.query_count}")
        print(f"clay_rows={result.clay_row_count}")
    elif args.command == "firecrawl-fallback":
        result = run_firecrawl_fallback(
            FirecrawlFallbackOptions(
                queue_path=Path(args.queue),
                output_dir=Path(args.output_dir),
                policy_path=Path(args.policy) if args.policy else None,
                limit=args.limit,
            )
        )
        print(f"enriched={result.enriched_path}")
        print(f"review={result.review_path}")
        print(f"clay_queue={result.clay_queue_path}")
        print(f"run={result.run_path}")
        print(f"processed={result.processed_count}")
        print(f"pages={result.page_count}")
        print(f"clay_rows={result.clay_row_count}")
    elif args.command == "tavily-research":
        result = run_tavily_research(
            TavilyResearchOptions(
                queue_path=Path(args.queue),
                output_dir=Path(args.output_dir),
                policy_path=Path(args.policy) if args.policy else None,
                limit=args.limit,
                max_results=args.max_results,
            )
        )
        print(f"enriched={result.enriched_path}")
        print(f"review={result.review_path}")
        print(f"clay_queue={result.clay_queue_path}")
        print(f"run={result.run_path}")
        print(f"processed={result.processed_count}")
        print(f"queries={result.query_count}")
        print(f"credits={result.credit_count}")
        print(f"clay_rows={result.clay_row_count}")
    elif args.command == "finalize":
        result = run_final_gate(
            FinalGateOptions(
                queue_path=Path(args.queue),
                output_dir=Path(args.output_dir),
                clay_results_path=Path(args.clay_results) if args.clay_results else None,
            )
        )
        print(f"enriched={result.enriched_path}")
        print(f"compliance_review={result.compliance_review_path}")
        print(f"review={result.review_path}")
        print(f"outreach_ready={result.outreach_ready_path}")
        print(f"do_not_contact={result.do_not_contact_path}")
        print(f"instantly_ready={result.instantly_ready_path}")
        print(f"run={result.run_path}")
        print(f"rows={result.row_count}")
        print(f"review_rows={result.review_count}")
        print(f"outreach_ready_rows={result.outreach_ready_count}")
        print(f"do_not_contact_rows={result.do_not_contact_count}")
        print(f"instantly_ready_rows={result.instantly_ready_count}")
    elif args.command == "run-waterfall":
        result = run_waterfall(
            WaterfallRunOptions(
                verified_path=Path(args.verified),
                review_path=Path(args.review) if args.review else None,
                output_dir=Path(args.output_dir),
                policy_path=Path(args.policy) if args.policy else None,
                limit=args.limit,
                run_website=not args.skip_website,
                run_providers=not args.skip_providers,
                provider_rounds=args.provider_rounds,
                clay_results_path=Path(args.clay_results) if args.clay_results else None,
                serper_results_per_query=args.serper_results_per_query,
                tavily_max_results=args.tavily_max_results,
            )
        )
        print(f"queue={result.queue_path}")
        print(f"summary={result.summary_path}")
        print(f"enriched={result.final_result.enriched_path}")
        print(f"compliance_review={result.final_result.compliance_review_path}")
        print(f"review={result.final_result.review_path}")
        print(f"outreach_ready={result.final_result.outreach_ready_path}")
        print(f"do_not_contact={result.final_result.do_not_contact_path}")
        print(f"instantly_ready={result.final_result.instantly_ready_path}")
        print(f"rows={result.final_result.row_count}")
        print(f"review_rows={result.final_result.review_count}")
        print(f"outreach_ready_rows={result.final_result.outreach_ready_count}")
        print(f"do_not_contact_rows={result.final_result.do_not_contact_count}")
        print(f"instantly_ready_rows={result.final_result.instantly_ready_count}")
