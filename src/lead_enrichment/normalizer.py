from __future__ import annotations

import hashlib
import re
import urllib.parse


TRUE_VALUES = {"1", "true", "yes", "ja", "y", "x"}
FALSE_VALUES = {"0", "false", "no", "nein", "n"}


def truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    return bool(text)


def normalize_domain(value: str | None) -> str:
    if not value:
        return ""
    raw = str(value).strip().lower()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urllib.parse.urlsplit(raw)
    host = parsed.netloc or parsed.path.split("/")[0]
    host = host.split("@")[-1].split(":")[0]
    host = host.strip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def normalize_url(value: str | None, fallback_domain: str = "") -> str:
    raw = str(value or "").strip()
    if raw:
        if "://" not in raw:
            raw = "https://" + raw
        parsed = urllib.parse.urlsplit(raw)
        domain = normalize_domain(raw)
        path = parsed.path or "/"
        if domain:
            return urllib.parse.urlunsplit(("https", domain, path, "", ""))
    domain = normalize_domain(fallback_domain)
    return f"https://{domain}/" if domain else ""


def stable_lead_id(domain: str) -> str:
    normalized = normalize_domain(domain)
    if not normalized:
        return ""
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
    return f"lead_{digest[:12]}"


def parse_score(value: object, default: int = 0) -> int:
    if value is None:
        return default
    text = str(value).strip().replace(",", ".")
    if not text:
        return default
    try:
        return int(float(text))
    except ValueError:
        return default


def clamp_score(value: int | float) -> int:
    return max(0, min(100, int(round(value))))


def split_tokens(value: object) -> list[str]:
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    parts = re.split(r"[|,;]+", text)
    return [part.strip().lower() for part in parts if part.strip()]


def join_tokens(values: list[str]) -> str:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        token = value.strip().lower()
        if token and token not in seen:
            seen.add(token)
            result.append(token)
    return "|".join(result)


def clean_text(value: object) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"\s+", " ", text).strip()


def bool_string(value: bool) -> str:
    return "true" if value else "false"
