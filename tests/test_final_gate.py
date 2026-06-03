from lead_enrichment.exporters.csv_exporter import read_csv_rows, write_csv_rows
from lead_enrichment.final_gate import FinalGateOptions, apply_clay_results, run_final_gate
from lead_enrichment.queue import QUEUE_FIELDS


def test_final_gate_marks_phone_first_lead_outreach_ready(tmp_path):
    queue_path = tmp_path / "queue.csv"
    write_csv_rows(
        queue_path,
        [
            queue_row(
                {
                    "lead_quality": "A+",
                    "free_enrichment_status": "complete",
                    "confidence_score": "0.95",
                    "next_enrichment_step": "compliance_review",
                    "phone_main": "+49 30 1234567",
                }
            )
        ],
        QUEUE_FIELDS,
    )

    result = run_final_gate(FinalGateOptions(queue_path=queue_path, output_dir=tmp_path / "out"))
    rows = read_csv_rows(result.enriched_path)
    outreach_rows = read_csv_rows(result.outreach_ready_path)
    instantly_rows = read_csv_rows(result.instantly_ready_path)

    assert result.outreach_ready_count == 1
    assert rows[0]["compliance_status"] == "outreach_ready"
    assert rows[0]["outreach_channel"] == "call"
    assert rows[0]["next_action"] == "manual_call_review"
    assert "Art. 6(1)(f)" in rows[0]["gdpr_legal_basis_note"]
    assert outreach_rows[0]["lead_id"] == "lead_1"
    assert instantly_rows == []


def test_clay_result_import_needs_manual_approval_before_instantly(tmp_path):
    queue_path = tmp_path / "queue.csv"
    clay_path = tmp_path / "clay_results.csv"
    write_csv_rows(
        queue_path,
        [
            queue_row(
                {
                    "lead_quality": "A++",
                    "free_enrichment_status": "complete",
                    "confidence_score": "0.95",
                    "next_enrichment_step": "clay_email_queue_planned",
                    "managing_director_name": "Max Mustermann",
                }
            )
        ],
        QUEUE_FIELDS,
    )
    write_csv_rows(
        clay_path,
        [
            {
                "lead_id": "lead_1",
                "domain": "muster-shop.de",
                "personal_email": "max.mustermann@muster-shop.de",
                "email_verification_status": "verified",
                "email_source": "clay_manual_import",
            }
        ],
        ["lead_id", "domain", "personal_email", "email_verification_status", "email_source"],
    )

    result = run_final_gate(
        FinalGateOptions(queue_path=queue_path, output_dir=tmp_path / "out", clay_results_path=clay_path)
    )
    rows = read_csv_rows(result.enriched_path)
    instantly_rows = read_csv_rows(result.instantly_ready_path)

    assert rows[0]["personal_email"] == "max.mustermann@muster-shop.de"
    assert rows[0]["clay_used"] == "true"
    assert rows[0]["compliance_status"] == "manual_review"
    assert result.instantly_ready_count == 0
    assert instantly_rows == []


def test_explicitly_approved_verified_email_exports_to_instantly(tmp_path):
    queue_path = tmp_path / "queue.csv"
    write_csv_rows(
        queue_path,
        [
            queue_row(
                {
                    "lead_quality": "A++",
                    "free_enrichment_status": "complete",
                    "confidence_score": "0.95",
                    "next_enrichment_step": "compliance_review",
                    "managing_director_name": "Max Mustermann",
                    "personal_email": "max.mustermann@muster-shop.de",
                    "email_verification_status": "verified",
                    "email_source": "manual_verified",
                    "outreach_approved": "true",
                    "outreach_channel": "email",
                }
            )
        ],
        QUEUE_FIELDS,
    )

    result = run_final_gate(FinalGateOptions(queue_path=queue_path, output_dir=tmp_path / "out"))
    rows = read_csv_rows(result.enriched_path)
    instantly_rows = read_csv_rows(result.instantly_ready_path)

    assert rows[0]["compliance_status"] == "outreach_ready"
    assert rows[0]["unsubscribe_required"] == "true"
    assert result.instantly_ready_count == 1
    assert instantly_rows[0]["personal_email"] == "max.mustermann@muster-shop.de"


def test_pending_provider_stays_manual_review(tmp_path):
    queue_path = tmp_path / "queue.csv"
    write_csv_rows(
        queue_path,
        [
            queue_row(
                {
                    "lead_quality": "A+",
                    "free_enrichment_status": "complete",
                    "confidence_score": "0.95",
                    "next_enrichment_step": "firecrawl_extract_known_url_planned",
                    "provider_recommended": "firecrawl",
                }
            )
        ],
        QUEUE_FIELDS,
    )

    result = run_final_gate(FinalGateOptions(queue_path=queue_path, output_dir=tmp_path / "out"))
    rows = read_csv_rows(result.enriched_path)

    assert rows[0]["compliance_status"] == "manual_review"
    assert "pending" in rows[0]["compliance_reason"]


def test_low_quality_lead_is_do_not_contact(tmp_path):
    queue_path = tmp_path / "queue.csv"
    write_csv_rows(
        queue_path,
        [
            queue_row(
                {
                    "lead_quality": "C",
                    "is_shop": "false",
                    "is_woocommerce": "false",
                    "why_relevant": "",
                    "pain_summary": "",
                    "next_enrichment_step": "store_only",
                }
            )
        ],
        QUEUE_FIELDS,
    )

    result = run_final_gate(FinalGateOptions(queue_path=queue_path, output_dir=tmp_path / "out"))
    rows = read_csv_rows(result.enriched_path)
    dnc_rows = read_csv_rows(result.do_not_contact_path)

    assert rows[0]["compliance_status"] == "do_not_contact"
    assert rows[0]["do_not_contact"] == "true"
    assert result.do_not_contact_count == 1
    assert dnc_rows[0]["lead_id"] == "lead_1"


def test_apply_clay_results_matches_by_domain_when_lead_id_missing():
    rows = [queue_row({"lead_id": "lead_1", "domain": "muster-shop.de"})]
    clay_results = [
        {
            "domain": "https://www.muster-shop.de/",
            "email": "max.mustermann@muster-shop.de",
            "status": "valid",
        }
    ]

    updated = apply_clay_results(rows, clay_results)

    assert updated[0]["personal_email"] == "max.mustermann@muster-shop.de"
    assert updated[0]["email_verification_status"] == "valid"
    assert updated[0]["email_source"] == "clay_manual_import"


def queue_row(overrides: dict[str, str]) -> dict[str, str]:
    row = {field: "" for field in QUEUE_FIELDS}
    row.update(
        {
            "lead_id": "lead_1",
            "domain": "muster-shop.de",
            "website_url": "https://muster-shop.de/",
            "company_name": "Muster Shop GmbH",
            "lead_quality": "A+",
            "is_shop": "true",
            "is_woocommerce": "true",
            "why_relevant": "WooCommerce shop with checkout lever.",
            "pain_summary": "Checkout and tracking optimization opportunity.",
            "free_enrichment_status": "complete",
            "confidence_score": "0.95",
            "imprint_url": "https://muster-shop.de/impressum",
            "managing_director_name": "Max Mustermann",
            "do_not_contact": "false",
        }
    )
    row.update(overrides)
    return row
