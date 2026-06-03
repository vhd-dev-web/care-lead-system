from __future__ import annotations

import json
from pathlib import Path


def write_json(path: Path | str, rows: list[dict[str, str]]) -> None:
    json_path = Path(path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(rows, ensure_ascii=True, indent=2), encoding="utf-8")
