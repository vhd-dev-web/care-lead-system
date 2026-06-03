from __future__ import annotations

import re

from ..normalizer import clean_text


STREET_RE = re.compile(
    r"\b((?:[A-Z][A-Za-z0-9.'\-]+\s+){0,2}"
    r"[A-Z][A-Za-z0-9.'\-]*(?:strasse|str\.|straße|weg|allee|platz|ring|gasse)\s+\d+[a-zA-Z]?)",
    flags=re.IGNORECASE,
)
ZIP_CITY_RE = re.compile(
    r"\b(\d{5}\s+[A-Z\u00c4\u00d6\u00dc][A-Za-z\u00c4\u00d6\u00dc\u00e4\u00f6\u00fc\u00df .'\-]{2,60})"
)


def extract_address(text: str) -> str:
    cleaned = clean_text(text)
    street_match = STREET_RE.search(cleaned)
    zip_match = ZIP_CITY_RE.search(cleaned)
    parts = []
    if street_match:
        parts.append(clean_street(clean_text(street_match.group(1))))
    if zip_match:
        parts.append(clean_city(clean_text(zip_match.group(1))))
    return ", ".join(parts)


def clean_street(value: str) -> str:
    text = value
    for marker in ("GmbH", "UG", "AG", "KG", "OHG", "GbR"):
        if marker in text:
            text = text.split(marker, 1)[-1]
    return text.strip(" ,.;:-")


def clean_city(value: str) -> str:
    text = value
    for marker in (
        "Gesch\u00e4ftsf\u00fchrer",
        "Geschaeftsfuehrer",
        "Inhaber",
        "Telefon",
        "E-Mail",
        "Email",
    ):
        if marker in text:
            text = text.split(marker, 1)[0]
    return text.strip(" ,.;:-")
