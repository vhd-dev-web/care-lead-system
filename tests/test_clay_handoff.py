from __future__ import annotations

import csv
from pathlib import Path

from care_lead_system.import_scrapes import import_scrape_files
from care_lead_system.lead_to_clay_adapter import export_clay_queue, import_clay_results
from care_lead_system.master_store import MasterStore
from care_lead_system.master_updater import MasterUpdater


def write_csv(path, rows):
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path):
    with Path(path).open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_clay_queue_uses_phase_one_grade_rules_and_marks_master_status(tmp_path):
    scrape = tmp_path / "scrape.csv"
    write_csv(
        scrape,
        [
            {"domain": "a-plus-plus.de", "company_name": "A Plus Plus GmbH", "lead_grade": "A++"},
            {"domain": "a-plus-missing.de", "company_name": "A Plus Missing GmbH", "lead_grade": "A+"},
            {"domain": "a-plus-done.de", "company_name": "A Plus Done GmbH", "lead_grade": "A+"},
            {"domain": "a-start.de", "company_name": "A Start GmbH", "lead_grade": "A"},
            {"domain": "b-lead.de", "company_name": "B GmbH", "lead_grade": "B"},
            {"domain": "review-lead.de", "company_name": "Review GmbH", "lead_grade": "Review"},
            {"domain": "reject-lead.de", "company_name": "Reject GmbH", "lead_grade": "Reject"},
        ],
    )
    import_scrape_files([scrape], root_dir=tmp_path, write_xlsx=False)

    updater = MasterUpdater(tmp_path)
    updater.update_leads(
        [
            {
                "domain_key": "a-plus-done.de",
                "decision_maker_1_name": "Dana Done",
                "decision_maker_1_role": "Geschaeftsfuehrung",
                "decision_maker_1_source": "manual",
                "decision_maker_1_confidence": "0.95",
                "email_general": "kontakt@a-plus-done.de",
                "email_general_source": "website",
                "email_general_confidence": "0.95",
            }
        ],
        run_id="test_patch",
        step="test_setup",
        match_key="domain_key",
    )

    result = export_clay_queue(root_dir=tmp_path, batch_id="batch_001")
    queue_rows = read_csv(result["queue_path"])
    queued_domains = {row["domain"] for row in queue_rows}

    assert queued_domains == {"a-plus-plus.de", "a-plus-missing.de", "a-start.de"}
    assert result["records_written"] == 3

    master_by_domain = {row["domain_key"]: row for row in MasterStore(tmp_path).load_rows()}
    assert master_by_domain["a-plus-plus.de"]["clay_status"] == "queued"
    assert master_by_domain["a-plus-plus.de"]["clay_export_batch_id"] == "batch_001"
    assert master_by_domain["b-lead.de"]["clay_status"] == "not_needed"
    assert master_by_domain["review-lead.de"]["clay_status"] == "not_needed"
    assert master_by_domain["reject-lead.de"]["clay_status"] == "not_needed"

    second = export_clay_queue(root_dir=tmp_path, batch_id="batch_002")
    assert read_csv(second["queue_path"]) == []


def test_clay_result_import_updates_master_with_source_confidence_and_status(tmp_path):
    scrape = tmp_path / "scrape.csv"
    write_csv(scrape, [{"domain": "a-plus-plus.de", "company_name": "A Plus Plus GmbH", "lead_grade": "A++"}])
    import_scrape_files([scrape], root_dir=tmp_path, write_xlsx=False)
    export = export_clay_queue(root_dir=tmp_path, batch_id="batch_001")
    lead_id = read_csv(export["queue_path"])[0]["lead_id"]

    clay_result = tmp_path / "clay_results.csv"
    write_csv(
        clay_result,
        [
            {
                "lead_id": lead_id,
                "decision_maker_name": "Dana Clay",
                "decision_maker_role": "E-Commerce Leitung",
                "business_email": "hello@a-plus-plus.de",
                "company_linkedin_url": "https://www.linkedin.com/company/a-plus-plus",
            }
        ],
    )

    result = import_clay_results(clay_result, root_dir=tmp_path)
    row = MasterStore(tmp_path).load_rows()[0]

    assert result["records_updated"] == 1
    assert row["clay_status"] == "done"
    assert row["decision_maker_1_name"] == "Dana Clay"
    assert row["decision_maker_1_source"] == "clay"
    assert row["email_general"] == "hello@a-plus-plus.de"
    assert row["email_general_confidence"] == "0.70"
    assert row["linkedin_company_url"].endswith("/a-plus-plus")
