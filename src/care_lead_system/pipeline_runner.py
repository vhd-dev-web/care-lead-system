from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

from lead_enrichment.orchestrator import WaterfallRunOptions, run_waterfall

from .env_utils import load_env_file
from .enrichment_results_adapter import import_enrichment_results
from .export_master_xlsx import export_master_xlsx
from .google_sheets_adapter import sync_clay_queue_to_sheet
from .import_scrapes import import_scrape_files
from .lead_to_clay_adapter import export_clay_queue
from .normalizer import utc_now
from .scraper.lead_qualifier import main as verify_main
from .scraper.woocommerce_lead_finder import main as scrape_main
from .verification_adapter import import_verification_results


@dataclass(frozen=True)
class PipelineOptions:
    root_dir: Path = Path(".")
    provider: str = "brave"
    niche: str = "pflegebox"
    budget_calls: int = 5
    query_limit: int | None = 5
    pages_per_query: int = 1
    search_delay: float = 1.0
    # The scrape-stage pre-qualifier uses WooCommerce-shop heuristics
    # (cart/checkout terms in the Brave snippet). Pflegebox snippets
    # rarely contain that vocabulary, so a high threshold here drops
    # real care providers. Default is 0 for the care fork — the
    # verifier does the authoritative classification anyway.
    qualified_min_score: int = 0
    scrape_enrich: bool = False
    verify_mode: str = "deep"
    verify_limit: int = 0
    verify_workers: int = 2
    verify_timeout: int = 5
    verified_min_score: int = 60
    no_sleep: bool = False
    enrichment_limit: int | None = None
    skip_website_enrichment: bool = False
    run_provider_enrichment: bool = False
    provider_rounds: int = 1
    sync_google: bool | None = None
    spreadsheet_id: str | None = None
    credentials_path: str | None = None
    clay_batch_id: str | None = None
    existing_scrape: Path | None = None
    existing_verification: Path | None = None
    existing_enrichment: Path | None = None
    skip_scrape: bool = False
    skip_verify: bool = False
    skip_enrichment: bool = False


@dataclass
class PipelineResult:
    steps: list[dict[str, object]] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)

    def add_step(self, name: str, status: str, **detail: object) -> None:
        payload: dict[str, object] = {"name": name, "status": status}
        payload.update(detail)
        self.steps.append(payload)

    def to_dict(self) -> dict[str, object]:
        return {"steps": self.steps, "outputs": self.outputs}


def run_pipeline(options: PipelineOptions) -> PipelineResult:
    root = options.root_dir.resolve()
    load_env_file(root / ".env")
    result = PipelineResult()
    raw_dir = root / "output" / "raw_scrapes"
    run_id = utc_now().replace("-", "").replace(":", "").replace("Z", "")
    verification_dir = root / "output" / "runs" / f"verification_{run_id}"
    enrichment_dir = root / "output" / "enrichment"
    state_db = root / "output" / "state" / "pipeline_state.sqlite"
    policy_path = root / "crawler_policy.json"
    enrichment_policy = root / "config" / "enrichment_policy.json"

    raw_dir.mkdir(parents=True, exist_ok=True)
    verification_dir.mkdir(parents=True, exist_ok=True)
    enrichment_dir.mkdir(parents=True, exist_ok=True)

    scrape_master_path = options.existing_scrape
    if options.existing_scrape:
        import_result = import_scrape_files([options.existing_scrape], root_dir=root, write_xlsx=False)
        result.add_step("scrape_import", "done", **import_result)
    elif options.skip_scrape:
        result.add_step("scrape", "skipped", reason="Skipped by option.")
    else:
        scrape_args = [
            "--provider",
            options.provider,
            "--niche",
            options.niche,
            "--budget-calls",
            str(options.budget_calls),
            "--pages-per-query",
            str(options.pages_per_query),
            "--output-dir",
            str(raw_dir),
            "--policy",
            str(policy_path),
            "--state-db",
            str(state_db),
            "--qualified-min-score",
            str(options.qualified_min_score),
        ]
        if options.query_limit is not None:
            scrape_args.extend(["--query-limit", str(options.query_limit)])
        if options.search_delay >= 0:
            scrape_args.extend(["--delay", str(options.search_delay)])
        if options.scrape_enrich:
            scrape_args.append("--enrich")
        scrape_exit = scrape_main(scrape_args)
        if scrape_exit != 0:
            raise RuntimeError(f"Scraper exited with code {scrape_exit}.")
        scrape_master_path = raw_dir / "leads_master.csv"
        import_result = import_scrape_files([scrape_master_path], root_dir=root, write_xlsx=False)
        result.add_step("scrape", "done", output=str(scrape_master_path), import_result=import_result)

    verified_path = options.existing_verification
    review_path: Path | None = None
    if options.existing_verification:
        verify_import = import_verification_results(options.existing_verification, root_dir=root)
        result.add_step("verification_import", "done", **verify_import)
    elif options.skip_verify:
        result.add_step("verification", "skipped", reason="Skipped by option.")
    else:
        verify_input = raw_dir / "qualified_master.csv"
        if not verify_input.exists() and scrape_master_path:
            verify_input = scrape_master_path
        if not verify_input.exists():
            raise FileNotFoundError(
                "No verification input found. Run scraping first or pass --existing-verification."
            )
        verify_args = [
            "--input",
            str(verify_input),
            "--output-dir",
            str(verification_dir),
            "--policy",
            str(policy_path),
            "--state-db",
            str(state_db),
            "--mode",
            options.verify_mode,
            "--workers",
            str(options.verify_workers),
            "--timeout",
            str(options.verify_timeout),
            "--verified-min-score",
            str(options.verified_min_score),
        ]
        if options.verify_limit:
            verify_args.extend(["--limit", str(options.verify_limit)])
        if options.no_sleep:
            verify_args.append("--no-sleep")
        verify_exit = verify_main(verify_args)
        if verify_exit != 0:
            raise RuntimeError(f"Verifier exited with code {verify_exit}.")
        verified_path = verification_dir / "verified_leads.csv"
        review_path = verification_dir / "review_leads.csv"
        verify_import = import_verification_results(verification_dir / "verification_all.csv", root_dir=root)
        result.add_step(
            "verification",
            "done",
            verified=str(verified_path),
            review=str(review_path),
            import_result=verify_import,
        )

    enrichment_import_path = options.existing_enrichment
    if options.existing_enrichment:
        enrich_import = import_enrichment_results(options.existing_enrichment, root_dir=root)
        result.add_step("enrichment_import", "done", **enrich_import)
    elif options.skip_enrichment:
        result.add_step("enrichment", "skipped", reason="Skipped by option.")
    else:
        if not verified_path:
            raise FileNotFoundError(
                "No enrichment input found. Run verification first or pass --existing-enrichment."
            )
        waterfall = run_waterfall(
            WaterfallRunOptions(
                verified_path=verified_path,
                review_path=review_path if review_path and review_path.exists() else None,
                output_dir=enrichment_dir,
                policy_path=enrichment_policy,
                limit=options.enrichment_limit,
                run_website=not options.skip_website_enrichment,
                run_providers=options.run_provider_enrichment,
                provider_rounds=options.provider_rounds,
            )
        )
        enrichment_import_path = Path(waterfall.final_result.enriched_path)
        enrich_import = import_enrichment_results(enrichment_import_path, root_dir=root)
        result.add_step(
            "enrichment",
            "done",
            queue=waterfall.queue_path,
            enriched=waterfall.final_result.enriched_path,
            summary=waterfall.summary_path,
            import_result=enrich_import,
        )

    xlsx_path = export_master_xlsx(root_dir=root)
    result.outputs["master_xlsx"] = str(xlsx_path)

    clay_result = export_clay_queue(root_dir=root, batch_id=options.clay_batch_id)
    result.outputs["clay_queue"] = str(clay_result["queue_path"])
    result.add_step("clay_queue", "done", **clay_result)

    # Auto-enable only if the user did not pass an explicit choice AND
    # we are not running under pytest. The pytest guard is a safety net
    # so a future test that forgets sync_google=False can never reach
    # the real Sheets API even if conftest is bypassed.
    running_under_pytest = "PYTEST_CURRENT_TEST" in os.environ or "pytest" in sys.modules
    if options.sync_google is None:
        if running_under_pytest:
            should_sync = False
            sync_reason_auto = "skipped: running under pytest"
        else:
            should_sync = bool(options.spreadsheet_id or os.environ.get("VHD_GOOGLE_SPREADSHEET_ID"))
            sync_reason_auto = "auto-enabled via VHD_GOOGLE_SPREADSHEET_ID"
    else:
        should_sync = options.sync_google
        sync_reason_auto = ""
    if should_sync:
        # The local export_clay_queue step above already marked these
        # rows as clay_status=queued in the master. Without
        # include_already_exported=True the sheet sync would drop every
        # row it was supposed to write. Reusing clay_result's batch_id
        # keeps the local CSV and the sheet on the same batch.
        google_result = sync_clay_queue_to_sheet(
            root_dir=root,
            spreadsheet_id=options.spreadsheet_id,
            credentials_path=options.credentials_path,
            batch_id=options.clay_batch_id or clay_result["batch_id"],
            include_already_exported=True,
        )
        result.add_step("google_sheet_sync", "done", trigger=sync_reason_auto or "explicit", **google_result)
    else:
        result.add_step(
            "google_sheet_sync",
            "skipped",
            reason="Set VHD_GOOGLE_SPREADSHEET_ID in .env or pass --sync-google to write Clay Queue.",
        )

    return result
