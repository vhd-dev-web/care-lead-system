from __future__ import annotations

import csv
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .normalizer import utc_now


REGISTRY_COLUMNS = [
    "run_id",
    "run_type",
    "status",
    "started_at",
    "finished_at",
    "input_paths",
    "output_paths",
    "records_read",
    "records_written",
    "records_created",
    "records_updated",
    "records_skipped",
    "notes",
    "error",
]


@dataclass
class RunRecord:
    run_id: str
    run_type: str
    status: str = "running"
    started_at: str = field(default_factory=utc_now)
    finished_at: str = ""
    input_paths: list[str] = field(default_factory=list)
    output_paths: list[str] = field(default_factory=list)
    records_read: int = 0
    records_written: int = 0
    records_created: int = 0
    records_updated: int = 0
    records_skipped: int = 0
    notes: str = ""
    error: str = ""

    def to_row(self) -> dict[str, str]:
        return {
            "run_id": self.run_id,
            "run_type": self.run_type,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "input_paths": "|".join(self.input_paths),
            "output_paths": "|".join(self.output_paths),
            "records_read": str(self.records_read),
            "records_written": str(self.records_written),
            "records_created": str(self.records_created),
            "records_updated": str(self.records_updated),
            "records_skipped": str(self.records_skipped),
            "notes": self.notes,
            "error": self.error,
        }


class RunRegistry:
    def __init__(self, root_dir: str | Path = ".") -> None:
        self.root_dir = Path(root_dir)
        self.runs_dir = self.root_dir / "output" / "runs"
        self.registry_path = self.runs_dir / "run_registry.csv"

    def ensure_dirs(self) -> None:
        self.runs_dir.mkdir(parents=True, exist_ok=True)

    def _load_rows(self) -> list[dict[str, str]]:
        if not self.registry_path.exists():
            return []
        with self.registry_path.open("r", newline="", encoding="utf-8-sig") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    def _write_rows(self, rows: list[dict[str, str]]) -> None:
        self.ensure_dirs()
        with self.registry_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=REGISTRY_COLUMNS, lineterminator="\n")
            writer.writeheader()
            for row in rows:
                writer.writerow({column: row.get(column, "") for column in REGISTRY_COLUMNS})

    def start_run(self, run_type: str, input_paths: list[str] | None = None, notes: str = "") -> RunRecord:
        stamp = utc_now().replace("-", "").replace(":", "").replace("Z", "")
        run_id = f"{run_type}_{stamp}_{uuid.uuid4().hex[:8]}"
        record = RunRecord(run_id=run_id, run_type=run_type, input_paths=input_paths or [], notes=notes)
        rows = self._load_rows()
        rows.append(record.to_row())
        self._write_rows(rows)
        self._write_detail(record, {})
        return record

    def finish_run(
        self,
        run_id: str,
        status: str,
        *,
        output_paths: list[str] | None = None,
        records_read: int = 0,
        records_written: int = 0,
        records_created: int = 0,
        records_updated: int = 0,
        records_skipped: int = 0,
        notes: str = "",
        error: str = "",
        detail: dict[str, object] | None = None,
    ) -> RunRecord:
        rows = self._load_rows()
        selected: dict[str, str] | None = None
        for row in rows:
            if row.get("run_id") == run_id:
                selected = row
                break
        if selected is None:
            selected = RunRecord(run_id=run_id, run_type="unknown").to_row()
            rows.append(selected)

        selected.update(
            {
                "status": status,
                "finished_at": utc_now(),
                "output_paths": "|".join(output_paths or []),
                "records_read": str(records_read),
                "records_written": str(records_written),
                "records_created": str(records_created),
                "records_updated": str(records_updated),
                "records_skipped": str(records_skipped),
                "notes": notes,
                "error": error,
            }
        )
        self._write_rows(rows)
        record = RunRecord(
            run_id=selected["run_id"],
            run_type=selected.get("run_type", "unknown"),
            status=selected.get("status", ""),
            started_at=selected.get("started_at", ""),
            finished_at=selected.get("finished_at", ""),
            input_paths=selected.get("input_paths", "").split("|") if selected.get("input_paths") else [],
            output_paths=output_paths or [],
            records_read=records_read,
            records_written=records_written,
            records_created=records_created,
            records_updated=records_updated,
            records_skipped=records_skipped,
            notes=notes,
            error=error,
        )
        self._write_detail(record, detail or {})
        return record

    def _write_detail(self, record: RunRecord, detail: dict[str, object]) -> None:
        self.ensure_dirs()
        detail_path = self.runs_dir / f"{record.run_id}.json"
        payload = {"run": record.to_row(), "detail": detail}
        detail_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
