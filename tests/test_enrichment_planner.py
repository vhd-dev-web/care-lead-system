from __future__ import annotations

import csv

from care_lead_system.enrichment_planner import plan_enrichment
from care_lead_system.import_scrapes import import_scrape_files
from care_lead_system.master_store import MasterStore


def write_csv(path, rows):
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_enrichment_planner_sets_needed_module_statuses(tmp_path):
    scrape = tmp_path / "scrape.csv"
    write_csv(scrape, [{"domain": "missing-fields.de", "company_name": "Missing GmbH", "lead_grade": "A++"}])
    import_scrape_files([scrape], root_dir=tmp_path, write_xlsx=False)

    result = plan_enrichment(root_dir=tmp_path)
    row = MasterStore(tmp_path).load_rows()[0]

    assert result["records_updated"] == 1
    assert row["enrichment_stage"] == "planned"
    assert row["firecrawl_status"] == "needed"
    assert row["serper_status"] == "needed"
    assert row["tavily_status"] == "needed"
