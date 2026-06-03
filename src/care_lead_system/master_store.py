from __future__ import annotations

import csv
import os
from pathlib import Path

from .master_schema import MASTER_COLUMNS, ensure_master_columns, ordered_fieldnames


class MasterStore:
    def __init__(self, root_dir: str | Path = ".") -> None:
        self.root_dir = Path(root_dir)
        self.master_dir = self.root_dir / "data" / "master"
        self.master_csv_path = self.master_dir / "leads_master.csv"
        self.master_xlsx_path = self.master_dir / "Leads_Master.xlsx"

    def ensure_dirs(self) -> None:
        self.master_dir.mkdir(parents=True, exist_ok=True)

    def ensure_master_file(self) -> None:
        self.ensure_dirs()
        if self.master_csv_path.exists():
            return
        with self.master_csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=MASTER_COLUMNS, lineterminator="\n")
            writer.writeheader()

    def load_rows(self) -> list[dict[str, str]]:
        if not self.master_csv_path.exists():
            return []
        with self.master_csv_path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            return [ensure_master_columns(dict(row)) for row in reader]

    def write_rows(self, rows: list[dict[str, str]]) -> None:
        self.ensure_dirs()
        normalized = [ensure_master_columns(row) for row in rows]
        fieldnames = ordered_fieldnames(normalized)
        tmp_path = self.master_csv_path.with_suffix(".csv.tmp")
        with tmp_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=fieldnames,
                lineterminator="\n",
                extrasaction="ignore",
            )
            writer.writeheader()
            writer.writerows(normalized)
        os.replace(tmp_path, self.master_csv_path)

    def index_by(self, key: str = "domain_key") -> dict[str, dict[str, str]]:
        return {row.get(key, ""): row for row in self.load_rows() if row.get(key, "")}
