from __future__ import annotations

import sqlite3
from pathlib import Path


def write_sqlite(path: Path | str, rows: list[dict[str, str]], table: str = "enriched_leads") -> None:
    sqlite_path = Path(path)
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    columns = list(rows[0].keys())
    quoted_columns = ", ".join(f'"{column}" TEXT' for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    with sqlite3.connect(sqlite_path) as conn:
        conn.execute(f'DROP TABLE IF EXISTS "{table}"')
        conn.execute(f'CREATE TABLE "{table}" ({quoted_columns})')
        conn.executemany(
            f'INSERT INTO "{table}" VALUES ({placeholders})',
            [[row.get(column, "") for column in columns] for row in rows],
        )
