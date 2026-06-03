from __future__ import annotations

import csv

from care_lead_system.enrichment_results_adapter import import_enrichment_results
from care_lead_system.master_store import MasterStore
from care_lead_system.verification_adapter import import_verification_results


def write_semicolon_csv(path, rows):
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, delimiter=";", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_verification_import_cooldown_skip_preserves_prior_grade(tmp_path):
    """Regression: a second verifier run on a domain in cooldown writes
    a placeholder row (lead_type=skipped, vhd_fit_score=0, exclusion_reason=
    domain_cooldown). Without the guard the verifier_adapter would derive
    lead_grade=Reject from the placeholder and erase the A++ from the
    first run, which is the exact destructive behaviour we hit live.
    """
    first = tmp_path / "verification_1.csv"
    write_semicolon_csv(
        first,
        [
            {
                "domain": "shop-alpha.de",
                "lead_type": "shop",
                "is_shop": "yes",
                "is_woocommerce": "yes",
                "detected_platform": "woocommerce",
                "vhd_fit_score": "100",
                "best_status": "200",
                "possible_shop_levers": "woocommerce_growth_system",
                "checked_at": "2026-06-01T08:00:00Z",
            }
        ],
    )
    import_verification_results(first, root_dir=tmp_path)

    master = {row["domain_key"]: row for row in MasterStore(tmp_path).load_rows()}
    assert master["shop-alpha.de"]["lead_grade"] == "A++"
    assert master["shop-alpha.de"]["detected_platform"] == "woocommerce"

    # Second run: the verifier hit a cooldown and wrote the skip placeholder.
    second = tmp_path / "verification_2.csv"
    write_semicolon_csv(
        second,
        [
            {
                "domain": "shop-alpha.de",
                "lead_type": "skipped",
                "is_shop": "no",
                "is_woocommerce": "no",
                "detected_platform": "",
                "vhd_fit_score": "0",
                "exclusion_reason": "domain_cooldown",
                "policy_skip_reason": "domain_cooldown",
                "checked_at": "2026-06-03T08:00:00Z",
            }
        ],
    )
    import_verification_results(second, root_dir=tmp_path)

    master = {row["domain_key"]: row for row in MasterStore(tmp_path).load_rows()}
    # The placeholder must NOT degrade the previous classification.
    assert master["shop-alpha.de"]["lead_grade"] == "A++"
    assert master["shop-alpha.de"]["is_woocommerce"] == "yes"
    assert master["shop-alpha.de"]["detected_platform"] == "woocommerce"
    # The cooldown notice may surface as a verification_error for audit.
    assert master["shop-alpha.de"].get("verification_error") == "domain_cooldown"


def test_import_scraper_verified_master_creates_master_rows_and_derives_grade(tmp_path):
    verified = tmp_path / "verified_master.csv"
    write_semicolon_csv(
        verified,
        [
            {
                "domain": "muster-shop.de",
                "source_url": "https://www.muster-shop.de/",
                "company_name": "Muster Shop GmbH",
                "lead_type": "shop",
                "is_shop": "yes",
                "is_woocommerce": "yes",
                "is_dach": "yes",
                "vhd_fit_score": "88",
                "next_action": "qualified",
                "email": "info@muster-shop.de",
                "phone": "+49 30 123456",
                "best_status": "200",
                "possible_shop_levers": "woocommerce_growth_system|checkout_payment_shipping_review",
                "checked_at": "2026-05-27T10:00:00Z",
            }
        ],
    )

    first = import_verification_results(verified, root_dir=tmp_path)
    second = import_verification_results(verified, root_dir=tmp_path)
    rows = MasterStore(tmp_path).load_rows()
    row = rows[0]

    assert first["records_created"] == 1
    assert second["records_created"] == 0
    assert len(rows) == 1
    assert row["domain_key"] == "muster-shop.de"
    assert row["verification_status"] == "done"
    assert row["verification_score"] == "88"
    assert row["domain_alive"] == "true"
    assert row["is_woocommerce"] == "yes"
    assert row["lead_grade"] == "A++"
    assert row["business_potential_score"] == "88"
    assert row["verification_evidence_url"] == "https://www.muster-shop.de/"


def test_import_enrichment_queue_output_maps_results_to_master_truth(tmp_path):
    enrichment = tmp_path / "enrichment_queue.csv"
    write_semicolon_csv(
        enrichment,
        [
            {
                "lead_id": "",
                "domain": "muster-shop.de",
                "website_url": "https://muster-shop.de/",
                "company_name": "Muster Shop GmbH",
                "legal_name": "Muster Shop GmbH",
                "lead_quality": "A+",
                "vhd_fit_score": "78",
                "general_email": "kontakt@muster-shop.de",
                "phone_main": "+49 30 123456",
                "managing_director_name": "Max Mustermann",
                "managing_director_source": "website_imprint",
                "confidence_score": "0.86",
                "imprint_url": "https://muster-shop.de/impressum",
                "next_enrichment_step": "compliance_review",
                "provider_recommended": "serper",
                "waterfall_reason": "Decision maker source should be checked.",
                "clay_eligible": "true",
                "clay_reason": "A+ lead is missing a verified business email.",
                "last_queued_at": "2026-05-27T11:00:00Z",
            }
        ],
    )

    result = import_enrichment_results(enrichment, root_dir=tmp_path)
    row = MasterStore(tmp_path).load_rows()[0]

    assert result["records_created"] == 1
    assert row["lead_grade"] == "A+"
    assert row["legal_name"] == "Muster Shop GmbH"
    assert row["legal_name_confidence"] == "0.86"
    assert row["email_general"] == "kontakt@muster-shop.de"
    assert row["email_general_source"] == "vhd-lead-enrichment"
    assert row["decision_maker_1_name"] == "Max Mustermann"
    assert row["decision_maker_1_role"] == "Geschaeftsfuehrer"
    assert row["decision_maker_1_source"] == "website_imprint"
    assert row["serper_status"] == "needed"
    assert row["clay_needed"] == "true"
    assert row["clay_status"] == "needed"
