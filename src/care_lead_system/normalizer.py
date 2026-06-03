from __future__ import annotations

import hashlib
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Iterable


TRUE_VALUES = {"1", "true", "yes", "ja", "y", "x"}
FALSE_VALUES = {"0", "false", "no", "nein", "n", "false"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_text(value: object) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"\s+", " ", text).strip()


def truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = clean_text(value).lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    return bool(text)


def bool_string(value: bool) -> str:
    return "true" if value else "false"


def parse_score(value: object, default: int = 0) -> int:
    text = clean_text(value).replace(",", ".")
    if not text:
        return default
    try:
        return int(float(text))
    except ValueError:
        return default


def parse_confidence(value: object, default: float = 0.0) -> float:
    text = clean_text(value).replace(",", ".").rstrip("%")
    if not text:
        return default
    try:
        number = float(text)
    except ValueError:
        return default
    if number > 1:
        return max(0.0, min(1.0, number / 100.0))
    return max(0.0, min(1.0, number))


def normalize_domain(value: object) -> str:
    raw = clean_text(value).lower()
    if not raw:
        return ""
    if "@" in raw and "://" not in raw:
        raw = raw.rsplit("@", 1)[-1]
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urllib.parse.urlsplit(raw)
    host = parsed.netloc or parsed.path.split("/")[0]
    host = host.split("@")[-1].split(":")[0].strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def normalize_url(value: object, fallback_domain: object = "") -> str:
    raw = clean_text(value)
    if raw:
        if "://" not in raw:
            raw = "https://" + raw
        parsed = urllib.parse.urlsplit(raw)
        domain = normalize_domain(raw)
        if domain:
            path = parsed.path or "/"
            return urllib.parse.urlunsplit(("https", domain, path, "", ""))
    domain = normalize_domain(fallback_domain)
    return f"https://{domain}/" if domain else ""


def stable_lead_id(domain_key: object) -> str:
    normalized = normalize_domain(domain_key)
    if not normalized:
        return ""
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
    return f"lead_{digest[:12]}"


def split_tokens(value: object) -> list[str]:
    text = clean_text(value)
    if not text:
        return []
    parts = re.split(r"[|,;]+", text)
    return [clean_text(part) for part in parts if clean_text(part)]


def join_tokens(values: Iterable[object]) -> str:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        token = clean_text(value)
        if not token:
            continue
        key = token.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(token)
    return "|".join(result)


def merge_token_values(*values: object) -> str:
    tokens: list[str] = []
    for value in values:
        tokens.extend(split_tokens(value))
    return join_tokens(tokens)
