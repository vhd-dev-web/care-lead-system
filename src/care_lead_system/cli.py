from __future__ import annotations

import argparse
import sys
from pathlib import Path
from pprint import pprint

from .enrichment_planner import plan_enrichment
from .enrichment_results_adapter import import_enrichment_results
from .env_utils import load_env_file
from .export_master_xlsx import export_master_xlsx
from .google_sheets_adapter import (
    import_clay_results_from_sheet,
    setup_google_sheet,
    sync_clay_queue_to_sheet,
)
from .import_scrapes import import_scrape_files
from .lead_to_clay_adapter import export_clay_queue, import_clay_results
from .pipeline_runner import PipelineOptions, run_pipeline
from .scraper.lead_qualifier import main as verify_main
from .scraper.woocommerce_lead_finder import main as scrape_main
from .setup_wizard import main as setup_main
from .verification_adapter import import_verification_results

from lead_enrichment.cli import main as enrich_main


def _resolve_root(raw_args: list[str]) -> Path:
    """Best-effort lookup of --root before argparse runs, so .env loads early."""
    for index, token in enumerate(raw_args):
        if token == "--root" and index + 1 < len(raw_args):
            return Path(raw_args[index + 1])
        if token.startswith("--root="):
            return Path(token.split("=", 1)[1])
    return Path(".")


def main(argv: list[str] | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    load_env_file(_resolve_root(raw_args) / ".env")
    if raw_args and raw_args[0] in {"scrape", "verify", "enrich", "setup"}:
        forwarded = raw_args[1:]
        if forwarded[:1] == ["--"]:
            forwarded = forwarded[1:]
        if raw_args[0] == "scrape":
            return scrape_main(forwarded)
        if raw_args[0] == "verify":
            return verify_main(forwarded)
        if raw_args[0] == "setup":
            return setup_main(forwarded)
        enrich_main(forwarded)
        return 0

    parser = argparse.ArgumentParser(description="VHD lead system CLI.")
    parser.add_argument("--root", default=".", help="Repository/workspace root.")
    parser.add_argument("--spreadsheet-id", help="Google Sheets spreadsheet id for Phase 2 commands.")
    parser.add_argument("--credentials", help="Google service-account credentials JSON path.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    scrape_parser = subparsers.add_parser("scrape", help="Run bundled Brave/Google scraper.")
    scrape_parser.add_argument("scraper_args", nargs=argparse.REMAINDER)

    verify_direct = subparsers.add_parser("verify", help="Run bundled domain verifier/scorer.")
    verify_direct.add_argument("verifier_args", nargs=argparse.REMAINDER)

    enrich_direct = subparsers.add_parser("enrich", help="Run bundled enrichment/Clay waterfall CLI.")
    enrich_direct.add_argument("enrichment_args", nargs=argparse.REMAINDER)

    setup_direct = subparsers.add_parser("setup", help="Configure local .env, policies, and Obsidian run script.")
    setup_direct.add_argument("setup_args", nargs=argparse.REMAINDER)

    pipeline = subparsers.add_parser("run-pipeline", help="Run scrape -> verify -> enrich -> Clay handoff.")
    pipeline.add_argument("--provider", choices=["auto", "brave", "google"], default="brave")
    pipeline.add_argument(
        "--niche",
        choices=["pflegebox", "woocommerce"],
        default="pflegebox",
        help="ICP niche. pflegebox is the default for this care fork.",
    )
    pipeline.add_argument("--budget-calls", type=int, default=5)
    pipeline.add_argument("--query-limit", type=int, default=5)
    pipeline.add_argument("--pages-per-query", type=int, default=1)
    pipeline.add_argument("--search-delay", type=float, default=1.0)
    pipeline.add_argument("--scrape-enrich", action="store_true")
    pipeline.add_argument("--verify-mode", choices=["light", "deep"], default="deep")
    pipeline.add_argument("--verify-limit", type=int, default=0)
    pipeline.add_argument("--verify-workers", type=int, default=2)
    pipeline.add_argument("--verify-timeout", type=int, default=5)
    pipeline.add_argument("--verified-min-score", type=int, default=60)
    pipeline.add_argument("--no-sleep", action="store_true")
    pipeline.add_argument("--enrichment-limit", type=int, default=None)
    pipeline.add_argument("--skip-website-enrichment", action="store_true")
    pipeline.add_argument("--run-provider-enrichment", action="store_true")
    pipeline.add_argument("--provider-rounds", type=int, default=1)
    pipeline.add_argument(
        "--sync-google",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Force-enable/disable Google Sheets sync (auto-enabled when VHD_GOOGLE_SPREADSHEET_ID is set).",
    )
    pipeline.add_argument("--clay-batch-id")
    pipeline.add_argument("--existing-scrape")
    pipeline.add_argument("--existing-verification")
    pipeline.add_argument("--existing-enrichment")
    pipeline.add_argument("--skip-scrape", action="store_true")
    pipeline.add_argument("--skip-verify", action="store_true")
    pipeline.add_argument("--skip-enrichment", action="store_true")

    import_parser = subparsers.add_parser("import-scrapes")
    import_parser.add_argument("paths", nargs="+")
    import_parser.add_argument("--no-xlsx", action="store_true")

    verify_parser = subparsers.add_parser("import-verification")
    verify_parser.add_argument("path")

    enrichment_import = subparsers.add_parser("import-enrichment-results")
    enrichment_import.add_argument("path")

    subparsers.add_parser("plan-enrichment")
    subparsers.add_parser("export-master-xlsx")

    clay_export = subparsers.add_parser("export-clay-queue")
    clay_export.add_argument("--output")
    clay_export.add_argument("--batch-id")
    clay_export.add_argument("--include-already-exported", action="store_true")

    clay_import = subparsers.add_parser("import-clay-results")
    clay_import.add_argument("path")

    subparsers.add_parser("setup-google-sheet")

    google_queue = subparsers.add_parser("sync-google-clay-queue")
    google_queue.add_argument("--batch-id")
    google_queue.add_argument("--include-already-exported", action="store_true")

    subparsers.add_parser("import-google-clay-results")

    args, unknown = parser.parse_known_args(argv)
    if args.command in {"scrape", "verify", "enrich", "setup"}:
        attr = {
            "scrape": "scraper_args",
            "verify": "verifier_args",
            "enrich": "enrichment_args",
            "setup": "setup_args",
        }[args.command]
        forwarded = list(getattr(args, attr) or []) + unknown
        if forwarded[:1] == ["--"]:
            forwarded = forwarded[1:]
        if args.command == "setup" and "--root" not in forwarded:
            forwarded = ["--root", args.root, *forwarded]
        setattr(args, attr, forwarded)
    elif unknown:
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")
    if args.command == "scrape":
        return scrape_main(args.scraper_args)
    if args.command == "verify":
        return verify_main(args.verifier_args)
    if args.command == "enrich":
        enrich_main(args.enrichment_args)
    elif args.command == "setup":
        return setup_main(args.setup_args)
    elif args.command == "run-pipeline":
        result = run_pipeline(
            PipelineOptions(
                root_dir=Path(args.root),
                provider=args.provider,
                niche=args.niche,
                budget_calls=args.budget_calls,
                query_limit=args.query_limit,
                pages_per_query=args.pages_per_query,
                search_delay=args.search_delay,
                scrape_enrich=args.scrape_enrich,
                verify_mode=args.verify_mode,
                verify_limit=args.verify_limit,
                verify_workers=args.verify_workers,
                verify_timeout=args.verify_timeout,
                verified_min_score=args.verified_min_score,
                no_sleep=args.no_sleep,
                enrichment_limit=args.enrichment_limit,
                skip_website_enrichment=args.skip_website_enrichment,
                run_provider_enrichment=args.run_provider_enrichment,
                provider_rounds=args.provider_rounds,
                sync_google=args.sync_google,
                spreadsheet_id=args.spreadsheet_id,
                credentials_path=args.credentials,
                clay_batch_id=args.clay_batch_id,
                existing_scrape=Path(args.existing_scrape) if args.existing_scrape else None,
                existing_verification=Path(args.existing_verification) if args.existing_verification else None,
                existing_enrichment=Path(args.existing_enrichment) if args.existing_enrichment else None,
                skip_scrape=args.skip_scrape,
                skip_verify=args.skip_verify,
                skip_enrichment=args.skip_enrichment,
            )
        )
        pprint(result.to_dict())
    elif args.command == "import-scrapes":
        print(import_scrape_files(args.paths, root_dir=args.root, write_xlsx=not args.no_xlsx))
    elif args.command == "import-verification":
        print(import_verification_results(args.path, root_dir=args.root))
    elif args.command == "import-enrichment-results":
        print(import_enrichment_results(args.path, root_dir=args.root))
    elif args.command == "plan-enrichment":
        print(plan_enrichment(root_dir=args.root))
    elif args.command == "export-master-xlsx":
        print(export_master_xlsx(root_dir=args.root))
    elif args.command == "export-clay-queue":
        print(
            export_clay_queue(
                root_dir=args.root,
                output_path=args.output,
                batch_id=args.batch_id,
                include_already_exported=args.include_already_exported,
            )
        )
    elif args.command == "import-clay-results":
        print(import_clay_results(args.path, root_dir=args.root))
    elif args.command == "setup-google-sheet":
        print(setup_google_sheet(spreadsheet_id=args.spreadsheet_id, credentials_path=args.credentials))
    elif args.command == "sync-google-clay-queue":
        print(
            sync_clay_queue_to_sheet(
                root_dir=args.root,
                spreadsheet_id=args.spreadsheet_id,
                credentials_path=args.credentials,
                batch_id=args.batch_id,
                include_already_exported=args.include_already_exported,
            )
        )
    elif args.command == "import-google-clay-results":
        print(
            import_clay_results_from_sheet(
                root_dir=args.root,
                spreadsheet_id=args.spreadsheet_id,
                credentials_path=args.credentials,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
