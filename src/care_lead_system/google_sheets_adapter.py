from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .lead_to_clay_adapter import (
    CLAY_QUEUE_COLUMNS,
    build_clay_queue_plan,
    build_clay_result_patch,
)
from .master_store import MasterStore
from .master_updater import MasterUpdater
from .normalizer import utc_now
from .run_registry import RunRegistry


CLAY_QUEUE_TAB = "Clay Queue"
CLAY_RESULTS_TAB = "Clay Results"
SYNC_LOG_TAB = "Sync Log"

CLAY_RESULTS_COLUMNS = [
    "lead_id",
    "domain",
    "clay_export_batch_id",
    "legal_name",
    "imprint_url",
    "email_general",
    "phone_main",
    "decision_maker_1_name",
    "decision_maker_1_role",
    "linkedin_company_url",
    "linkedin_person_url",
    "clay_status",
    "clay_notes",
]

SYNC_LOG_COLUMNS = [
    "synced_at",
    "direction",
    "run_id",
    "batch_id",
    "records_read",
    "records_written",
    "records_updated",
    "records_skipped",
    "status",
    "notes",
]

GOOGLE_SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetsClient(Protocol):
    def ensure_sheets(self, spreadsheet_id: str, sheet_names: list[str]) -> None:
        ...

    def read_values(self, spreadsheet_id: str, range_name: str) -> list[list[str]]:
        ...

    def write_values(self, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> None:
        ...

    def append_values(self, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> None:
        ...

    def clear_values(self, spreadsheet_id: str, range_name: str) -> None:
        ...


@dataclass(frozen=True)
class GoogleSheetSyncResult:
    run_id: str
    spreadsheet_id: str
    batch_id: str
    records_read: int
    records_written: int
    records_updated: int
    records_skipped: int


class GoogleSheetsClient:
    def __init__(self, service: object) -> None:
        self.service = service

    @classmethod
    def from_service_account_file(cls, credentials_path: str | Path | None = None) -> "GoogleSheetsClient":
        path = (
            str(credentials_path)
            if credentials_path
            else os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
        )
        if not path:
            raise ValueError(
                "Google credentials missing. Set GOOGLE_APPLICATION_CREDENTIALS or pass --credentials."
            )
        try:
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise ImportError(
                "Google Sheets dependencies are missing. Install the project with the 'google' extra."
            ) from exc
        credentials = Credentials.from_service_account_file(path, scopes=GOOGLE_SHEETS_SCOPES)
        service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        return cls(service)

    def ensure_sheets(self, spreadsheet_id: str, sheet_names: list[str]) -> None:
        spreadsheet = self.service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        existing = {sheet["properties"]["title"] for sheet in spreadsheet.get("sheets", [])}
        requests = [
            {"addSheet": {"properties": {"title": sheet_name}}}
            for sheet_name in sheet_names
            if sheet_name not in existing
        ]
        if requests:
            self.service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": requests},
            ).execute()

    def read_values(self, spreadsheet_id: str, range_name: str) -> list[list[str]]:
        response = self.service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name,
        ).execute()
        return [[str(value) for value in row] for row in response.get("values", [])]

    def write_values(self, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> None:
        self.service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="RAW",
            body={"values": values},
        ).execute()

    def append_values(self, spreadsheet_id: str, range_name: str, values: list[list[str]]) -> None:
        self.service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption="RAW",
            insertDataOption="INSERT_ROWS",
            body={"values": values},
        ).execute()

    def clear_values(self, spreadsheet_id: str, range_name: str) -> None:
        self.service.spreadsheets().values().clear(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            body={},
        ).execute()


def resolve_spreadsheet_id(spreadsheet_id: str | None = None) -> str:
    resolved = spreadsheet_id or os.environ.get("VHD_GOOGLE_SPREADSHEET_ID")
    if not resolved:
        raise ValueError("Spreadsheet id missing. Pass --spreadsheet-id or set VHD_GOOGLE_SPREADSHEET_ID.")
    return resolved


def default_client(credentials_path: str | Path | None = None) -> GoogleSheetsClient:
    return GoogleSheetsClient.from_service_account_file(credentials_path)


def a1_range(sheet_name: str, range_name: str) -> str:
    escaped = sheet_name.replace("'", "''")
    return f"'{escaped}'!{range_name}"


def rows_to_values(columns: list[str], rows: list[dict[str, str]]) -> list[list[str]]:
    return [columns] + [[row.get(column, "") for column in columns] for row in rows]


def values_to_rows(values: list[list[str]]) -> list[dict[str, str]]:
    if not values:
        return []
    headers = [str(value).strip() for value in values[0]]
    rows: list[dict[str, str]] = []
    for values_row in values[1:]:
        row = {
            header: str(values_row[index]).strip() if index < len(values_row) else ""
            for index, header in enumerate(headers)
            if header
        }
        if any(row.values()):
            rows.append(row)
    return rows


def ensure_phase2_sheet(client: SheetsClient, spreadsheet_id: str) -> None:
    client.ensure_sheets(spreadsheet_id, [CLAY_QUEUE_TAB, CLAY_RESULTS_TAB, SYNC_LOG_TAB])
    ensure_header(client, spreadsheet_id, CLAY_QUEUE_TAB, CLAY_QUEUE_COLUMNS)
    ensure_header(client, spreadsheet_id, CLAY_RESULTS_TAB, CLAY_RESULTS_COLUMNS)
    ensure_header(client, spreadsheet_id, SYNC_LOG_TAB, SYNC_LOG_COLUMNS)


def ensure_header(client: SheetsClient, spreadsheet_id: str, sheet_name: str, columns: list[str]) -> None:
    existing = client.read_values(spreadsheet_id, a1_range(sheet_name, "1:1"))
    if existing and existing[0][: len(columns)] == columns:
        return
    client.write_values(spreadsheet_id, a1_range(sheet_name, "A1"), [columns])


def append_sync_log(
    client: SheetsClient,
    spreadsheet_id: str,
    *,
    direction: str,
    run_id: str,
    batch_id: str = "",
    records_read: int = 0,
    records_written: int = 0,
    records_updated: int = 0,
    records_skipped: int = 0,
    status: str = "done",
    notes: str = "",
) -> None:
    row = {
        "synced_at": utc_now(),
        "direction": direction,
        "run_id": run_id,
        "batch_id": batch_id,
        "records_read": str(records_read),
        "records_written": str(records_written),
        "records_updated": str(records_updated),
        "records_skipped": str(records_skipped),
        "status": status,
        "notes": notes,
    }
    client.append_values(spreadsheet_id, a1_range(SYNC_LOG_TAB, "A1"), [[row[column] for column in SYNC_LOG_COLUMNS]])


def setup_google_sheet(
    *,
    spreadsheet_id: str | None = None,
    credentials_path: str | Path | None = None,
    client: SheetsClient | None = None,
) -> dict[str, object]:
    resolved_id = resolve_spreadsheet_id(spreadsheet_id)
    sheets_client = client or default_client(credentials_path)
    ensure_phase2_sheet(sheets_client, resolved_id)
    append_sync_log(
        sheets_client,
        resolved_id,
        direction="setup",
        run_id="setup",
        status="done",
        notes="Ensured Phase 2 tabs and headers.",
    )
    return {"spreadsheet_id": resolved_id, "tabs": [CLAY_QUEUE_TAB, CLAY_RESULTS_TAB, SYNC_LOG_TAB]}


def sync_clay_queue_to_sheet(
    *,
    root_dir: str | Path = ".",
    spreadsheet_id: str | None = None,
    credentials_path: str | Path | None = None,
    client: SheetsClient | None = None,
    batch_id: str | None = None,
    include_already_exported: bool = False,
) -> dict[str, object]:
    resolved_id = resolve_spreadsheet_id(spreadsheet_id)
    sheets_client = client or default_client(credentials_path)
    store = MasterStore(root_dir)
    rows = store.load_rows()
    batch = batch_id or f"gclay_{utc_now().replace('-', '').replace(':', '').replace('Z', '')}"
    registry = RunRegistry(root_dir)
    run = registry.start_run("google_clay_queue_sync", input_paths=[str(store.master_csv_path)])
    try:
        ensure_phase2_sheet(sheets_client, resolved_id)
        plan = build_clay_queue_plan(rows, batch=batch, include_already_exported=include_already_exported)
        for patch in plan.patches:
            patch["clay_last_synced_at"] = utc_now()
        sheets_client.clear_values(resolved_id, a1_range(CLAY_QUEUE_TAB, "A:ZZ"))
        sheets_client.write_values(resolved_id, a1_range(CLAY_QUEUE_TAB, "A1"), rows_to_values(CLAY_QUEUE_COLUMNS, plan.queue_rows))
        updater = MasterUpdater(root_dir)
        result = updater.update_leads(plan.patches, run_id=run.run_id, step="google_clay_queue_sync")
        registry.finish_run(
            run.run_id,
            "done",
            output_paths=[f"google_sheet:{resolved_id}#{CLAY_QUEUE_TAB}", str(store.master_csv_path)],
            records_read=len(rows),
            records_written=len(plan.queue_rows),
            records_updated=result.records_updated,
            records_skipped=result.records_skipped,
            detail={"spreadsheet_id": resolved_id, "batch_id": batch, "queue_rows": len(plan.queue_rows)},
        )
        append_sync_log(
            sheets_client,
            resolved_id,
            direction="master_to_clay_queue",
            run_id=run.run_id,
            batch_id=batch,
            records_read=len(rows),
            records_written=len(plan.queue_rows),
            records_updated=result.records_updated,
            records_skipped=result.records_skipped,
        )
        return GoogleSheetSyncResult(
            run_id=run.run_id,
            spreadsheet_id=resolved_id,
            batch_id=batch,
            records_read=len(rows),
            records_written=len(plan.queue_rows),
            records_updated=result.records_updated,
            records_skipped=result.records_skipped,
        ).__dict__
    except Exception as exc:
        registry.finish_run(run.run_id, "failed", error=str(exc))
        try:
            append_sync_log(
                sheets_client,
                resolved_id,
                direction="master_to_clay_queue",
                run_id=run.run_id,
                batch_id=batch,
                status="failed",
                notes=str(exc),
            )
        except Exception:
            pass
        raise


def import_clay_results_from_sheet(
    *,
    root_dir: str | Path = ".",
    spreadsheet_id: str | None = None,
    credentials_path: str | Path | None = None,
    client: SheetsClient | None = None,
) -> dict[str, object]:
    resolved_id = resolve_spreadsheet_id(spreadsheet_id)
    sheets_client = client or default_client(credentials_path)
    store = MasterStore(root_dir)
    registry = RunRegistry(root_dir)
    run = registry.start_run("google_clay_results_import", input_paths=[f"google_sheet:{resolved_id}#{CLAY_RESULTS_TAB}"])
    try:
        ensure_phase2_sheet(sheets_client, resolved_id)
        values = sheets_client.read_values(resolved_id, a1_range(CLAY_RESULTS_TAB, "A:ZZ"))
        rows = values_to_rows(values)
        patches = [build_clay_result_patch(row) for row in rows if row.get("lead_id")]
        updater = MasterUpdater(root_dir)
        result = updater.update_leads(patches, run_id=run.run_id, step="google_clay_results_import")
        registry.finish_run(
            run.run_id,
            "done",
            output_paths=[str(store.master_csv_path)],
            records_read=len(rows),
            records_written=result.records_updated,
            records_updated=result.records_updated,
            records_skipped=result.records_skipped + (len(rows) - len(patches)),
            detail={"spreadsheet_id": resolved_id, "result_rows": len(rows), "patches": len(patches)},
        )
        append_sync_log(
            sheets_client,
            resolved_id,
            direction="clay_results_to_master",
            run_id=run.run_id,
            records_read=len(rows),
            records_written=result.records_updated,
            records_updated=result.records_updated,
            records_skipped=result.records_skipped + (len(rows) - len(patches)),
        )
        return {
            "run_id": run.run_id,
            "spreadsheet_id": resolved_id,
            "records_read": len(rows),
            "records_updated": result.records_updated,
            "records_skipped": result.records_skipped + (len(rows) - len(patches)),
        }
    except Exception as exc:
        registry.finish_run(run.run_id, "failed", error=str(exc))
        try:
            append_sync_log(
                sheets_client,
                resolved_id,
                direction="clay_results_to_master",
                run_id=run.run_id,
                status="failed",
                notes=str(exc),
            )
        except Exception:
            pass
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync VHD master data with a Google Drive Sheets handoff.")
    parser.add_argument("--spreadsheet-id")
    parser.add_argument("--credentials")
    parser.add_argument("--root", default=".")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("setup")

    queue_parser = subparsers.add_parser("sync-clay-queue")
    queue_parser.add_argument("--batch-id")
    queue_parser.add_argument("--include-already-exported", action="store_true")

    subparsers.add_parser("import-clay-results")

    args = parser.parse_args(argv)
    if args.command == "setup":
        print(setup_google_sheet(spreadsheet_id=args.spreadsheet_id, credentials_path=args.credentials))
    elif args.command == "sync-clay-queue":
        print(
            sync_clay_queue_to_sheet(
                root_dir=args.root,
                spreadsheet_id=args.spreadsheet_id,
                credentials_path=args.credentials,
                batch_id=args.batch_id,
                include_already_exported=args.include_already_exported,
            )
        )
    else:
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
