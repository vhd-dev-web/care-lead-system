from __future__ import annotations

import csv
from copy import deepcopy

from vhd_lead_system.google_sheets_adapter import (
    CLAY_QUEUE_COLUMNS,
    CLAY_QUEUE_TAB,
    CLAY_RESULTS_COLUMNS,
    CLAY_RESULTS_TAB,
    SYNC_LOG_TAB,
    import_clay_results_from_sheet,
    sync_clay_queue_to_sheet,
)
from vhd_lead_system.import_scrapes import import_scrape_files
from vhd_lead_system.lead_to_clay_adapter import export_clay_queue
from vhd_lead_system.master_store import MasterStore


class FakeSheetsClient:
    def __init__(self) -> None:
        self.sheets: dict[str, list[list[str]]] = {}

    def ensure_sheets(self, spreadsheet_id: str, sheet_names: list[str]) -> None:
        for sheet_name in sheet_names:
            self.sheets.setdefault(sheet_name, [])

    def read_values(self, spreadsheet_id: str, range_name: str) -> list[list[str]]:
        return deepcopy(self.sheets.get(self._sheet_name(range_name), []))

    def write_values(self, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> None:
        sheet_name = self._sheet_name(range_name)
        if range_name.endswith("A1") or "!A1" in range_name:
            self.sheets[sheet_name] = deepcopy(values)
            return
        self.sheets[sheet_name] = deepcopy(values)

    def append_values(self, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> None:
        self.sheets.setdefault(self._sheet_name(range_name), []).extend(deepcopy(values))

    def clear_values(self, spreadsheet_id: str, range_name: str) -> None:
        self.sheets[self._sheet_name(range_name)] = []

    def _sheet_name(self, range_name: str) -> str:
        sheet_ref = range_name.split("!", 1)[0]
        if sheet_ref.startswith("'") and sheet_ref.endswith("'"):
            return sheet_ref[1:-1].replace("''", "'")
        return sheet_ref


def write_csv(path, rows):
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_google_clay_queue_sync_writes_sheet_tabs_and_marks_master(tmp_path):
    scrape = tmp_path / "scrape.csv"
    write_csv(
        scrape,
        [
            {"domain": "alpha-shop.de", "company_name": "Alpha GmbH", "lead_grade": "A++"},
            {"domain": "beta-shop.de", "company_name": "Beta GmbH", "lead_grade": "B"},
        ],
    )
    import_scrape_files([scrape], root_dir=tmp_path, write_xlsx=False)
    client = FakeSheetsClient()

    result = sync_clay_queue_to_sheet(
        root_dir=tmp_path,
        spreadsheet_id="sheet_123",
        client=client,
        batch_id="gbatch_001",
    )

    queue_values = client.sheets[CLAY_QUEUE_TAB]
    assert result["records_written"] == 1
    assert queue_values[0] == CLAY_QUEUE_COLUMNS
    assert queue_values[1][CLAY_QUEUE_COLUMNS.index("domain")] == "alpha-shop.de"
    assert client.sheets[SYNC_LOG_TAB][1][1] == "master_to_clay_queue"

    master_by_domain = {row["domain_key"]: row for row in MasterStore(tmp_path).load_rows()}
    assert master_by_domain["alpha-shop.de"]["clay_status"] == "queued"
    assert master_by_domain["alpha-shop.de"]["clay_export_batch_id"] == "gbatch_001"
    assert master_by_domain["alpha-shop.de"]["clay_last_synced_at"]
    assert master_by_domain["beta-shop.de"]["clay_status"] == "not_needed"

    second = sync_clay_queue_to_sheet(
        root_dir=tmp_path,
        spreadsheet_id="sheet_123",
        client=client,
        batch_id="gbatch_002",
    )
    assert second["records_written"] == 0
    assert client.sheets[CLAY_QUEUE_TAB] == [CLAY_QUEUE_COLUMNS]


def test_sync_after_local_export_still_writes_queued_rows(tmp_path):
    """Regression: the pipeline runs export_clay_queue first, which sets
    clay_status=queued on the master rows. Without include_already_exported
    the sheet sync would skip every row and write an empty queue tab.
    """
    scrape = tmp_path / "scrape.csv"
    write_csv(
        scrape,
        [
            {"domain": "alpha-shop.de", "company_name": "Alpha GmbH", "lead_grade": "A++"},
            {"domain": "beta-shop.de", "company_name": "Beta GmbH", "lead_grade": "A+"},
        ],
    )
    import_scrape_files([scrape], root_dir=tmp_path, write_xlsx=False)

    # Step 1: local export marks both rows clay_status=queued.
    local = export_clay_queue(root_dir=tmp_path, batch_id="local_batch_001")
    assert local["records_written"] == 2

    # Step 2: sheet sync must still write the same rows when explicitly
    # told to include already-exported rows (the pipeline path).
    client = FakeSheetsClient()
    result = sync_clay_queue_to_sheet(
        root_dir=tmp_path,
        spreadsheet_id="sheet_123",
        client=client,
        batch_id="local_batch_001",
        include_already_exported=True,
    )
    assert result["records_written"] == 2

    queue_values = client.sheets[CLAY_QUEUE_TAB]
    domains_in_sheet = {
        row[CLAY_QUEUE_COLUMNS.index("domain")] for row in queue_values[1:]
    }
    assert domains_in_sheet == {"alpha-shop.de", "beta-shop.de"}

    # Default sync (without the flag) keeps the skip-behaviour so manual
    # callers can re-run without surprises.
    second_client = FakeSheetsClient()
    skipped = sync_clay_queue_to_sheet(
        root_dir=tmp_path,
        spreadsheet_id="sheet_123",
        client=second_client,
        batch_id="standalone_batch_001",
    )
    assert skipped["records_written"] == 0


def test_google_clay_results_import_updates_master_and_logs_sync(tmp_path):
    scrape = tmp_path / "scrape.csv"
    write_csv(scrape, [{"domain": "alpha-shop.de", "company_name": "Alpha GmbH", "lead_grade": "A++"}])
    import_scrape_files([scrape], root_dir=tmp_path, write_xlsx=False)
    client = FakeSheetsClient()
    sync_clay_queue_to_sheet(root_dir=tmp_path, spreadsheet_id="sheet_123", client=client, batch_id="gbatch_001")
    lead_id = client.sheets[CLAY_QUEUE_TAB][1][CLAY_QUEUE_COLUMNS.index("lead_id")]
    client.write_values(
        "sheet_123",
        "'Clay Results'!A1",
        [
            CLAY_RESULTS_COLUMNS,
            [
                lead_id,
                "alpha-shop.de",
                "gbatch_001",
                "Alpha Legal GmbH",
                "https://alpha-shop.de/impressum",
                "kontakt@alpha-shop.de",
                "+49 30 123",
                "Dana Clay",
                "E-Commerce Leitung",
                "https://www.linkedin.com/company/alpha-shop",
                "",
                "done",
                "Imported from Clay sheet.",
            ],
        ],
    )

    result = import_clay_results_from_sheet(root_dir=tmp_path, spreadsheet_id="sheet_123", client=client)
    row = MasterStore(tmp_path).load_rows()[0]
    log_directions = [log_row[1] for log_row in client.sheets[SYNC_LOG_TAB][1:]]

    assert result["records_updated"] == 1
    assert row["clay_status"] == "done"
    assert row["legal_name"] == "Alpha Legal GmbH"
    assert row["email_general"] == "kontakt@alpha-shop.de"
    assert row["decision_maker_1_name"] == "Dana Clay"
    assert row["decision_maker_1_source"] == "clay"
    assert row["clay_notes"] == "Imported from Clay sheet."
    assert "clay_results_to_master" in log_directions
