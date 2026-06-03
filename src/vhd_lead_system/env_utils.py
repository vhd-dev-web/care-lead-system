from __future__ import annotations

import os
from pathlib import Path


def parse_env_file(path: str | Path) -> dict[str, str]:
    env_path = Path(path)
    if not env_path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def load_env_file(path: str | Path) -> dict[str, str]:
    values = parse_env_file(path)
    for key, value in values.items():
        if key and value and not os.environ.get(key):
            os.environ[key] = value
    return values
