from __future__ import annotations

from pathlib import Path
from typing import Any


def load_simple_yaml(path: Path | str) -> dict[str, Any]:
    yaml_path = Path(path)
    if not yaml_path.exists():
        return {}
    try:
        import yaml  # type: ignore

        with yaml_path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
            return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return _fallback_parse(yaml_path.read_text(encoding="utf-8"))


def _fallback_parse(text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_list_key = ""
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_list_key:
            result.setdefault(current_list_key, []).append(stripped[2:].strip())
            continue
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not value:
                result[key] = []
                current_list_key = key
            else:
                result[key] = _coerce_value(value)
                current_list_key = ""
    return result


def _coerce_value(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return int(value)
    except ValueError:
        return value
