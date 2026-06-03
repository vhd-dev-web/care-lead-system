from __future__ import annotations

import csv

from vhd_lead_system.pipeline_runner import PipelineOptions, run_pipeline
from vhd_lead_system.scraper.lead_qualifier import main as verify_main
from vhd_lead_system.scraper.woocommerce_lead_finder import main as scrape_main


def write_semicolon_csv(path, rows):
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=";", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_bundled_scraper_and_verifier_cli_entrypoints_smoke(tmp_path):
    assert (
        scrape_main(
            [
                "--dry-run",
                "--show-queries",
                "--budget-calls",
                "1",
                "--query-limit",
                "1",
                "--output-dir",
                str(tmp_path / "scrape"),
            ]
        )
        == 0
    )
    empty_input = tmp_path / "empty.csv"
    write_semicolon_csv(empty_input, [{"domain": ""}])
    assert (
        verify_main(
            [
                "--input",
                str(empty_input),
                "--output-dir",
                str(tmp_path / "verify"),
                "--limit",
                "0",
                "--no-sleep",
            ]
        )
        == 0
    )


def test_run_pipeline_can_execute_master_flow_from_existing_upstream_outputs(tmp_path):
    verification = tmp_path / "verification_all.csv"
    enrichment = tmp_path / "enrichment_queue.csv"
    write_semicolon_csv(
        verification,
        [
            {
                "domain": "pipeline-shop.de",
                "source_url": "https://pipeline-shop.de/",
                "company_name": "Pipeline Shop GmbH",
                "lead_type": "shop",
                "is_shop": "yes",
                "is_woocommerce": "yes",
                "vhd_fit_score": "90",
                "best_status": "200",
                "possible_shop_levers": "woocommerce_growth_system|checkout_payment_shipping_review",
                "checked_at": "2026-05-27T10:00:00Z",
            }
        ],
    )
    write_semicolon_csv(
        enrichment,
        [
            {
                "domain": "pipeline-shop.de",
                "website_url": "https://pipeline-shop.de/",
                "company_name": "Pipeline Shop GmbH",
                "lead_quality": "A++",
                "vhd_fit_score": "90",
                "general_email": "kontakt@pipeline-shop.de",
                "phone_main": "+49 30 123456",
                "managing_director_name": "Paula Pipeline",
                "managing_director_source": "website_imprint",
                "confidence_score": "0.90",
                "imprint_url": "https://pipeline-shop.de/impressum",
                "next_enrichment_step": "clay_email_queue_planned",
                "clay_eligible": "true",
                "clay_reason": "A++ lead is eligible for Clay email enrichment queue.",
                "last_queued_at": "2026-05-27T11:00:00Z",
            }
        ],
    )

    result = run_pipeline(
        PipelineOptions(
            root_dir=tmp_path,
            existing_verification=verification,
            existing_enrichment=enrichment,
            skip_scrape=True,
            # Belt-and-suspenders: conftest scrubs the env, this makes
            # the test correct even if conftest is removed.
            sync_google=False,
        )
    )

    assert (tmp_path / "data" / "master" / "leads_master.csv").exists()
    assert (tmp_path / "data" / "master" / "Leads_Master.xlsx").exists()
    assert result.outputs["clay_queue"].endswith(".csv")
    assert any(step["name"] == "verification_import" for step in result.steps)
    assert any(step["name"] == "enrichment_import" for step in result.steps)
    assert any(step["name"] == "clay_queue" for step in result.steps)
