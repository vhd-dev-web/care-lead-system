from __future__ import annotations

import re

from .legal_form import detect_legal_form
from ..normalizer import clean_text


LOW_VALUE_COMPANY_NAMES = {
    "impressum",
    "kontakt",
    "datenschutz",
    "home",
    "shop",
    "startseite",
}

LOW_VALUE_LEGAL_NAME_TOKENS = {
    "cleverreach",
    "google",
    "facebook",
    "meta platforms",
    "paypal",
    "klarna",
    "shopify",
    "woocommerce",
    "trustpilot",
    "zammad",
    "box-taped",
}

PRODUCT_LEGAL_NAME_RE = re.compile(
    r"\b\d+(?:[,.]\d+)?\s*(?:kg|g|gramm|ml|l|liter|stk|stück|pcs)\b",
    flags=re.IGNORECASE,
)

LEGAL_CONTEXT_MARKERS = (
    "diensteanbieter",
    "anbieter",
    "betreiber",
    "firma",
    "impressum",
    "angaben gemaess",
    "angaben gemass",
    "angaben gemäß",
)


def clean_company_name(value: object) -> str:
    text = clean_text(value)
    if not text:
        return ""
    text = re.sub(r"\s*\|\s*.*$", "", text).strip()
    text = re.sub(r"\s+-\s+.*$", "", text).strip()
    if text.lower() in LOW_VALUE_COMPANY_NAMES:
        return ""
    return text


def company_name_from_row(row: dict[str, str]) -> tuple[str, str, float]:
    for key, confidence in (("company_name", 0.70), ("title", 0.45)):
        name = clean_company_name(row.get(key))
        if name:
            return name, f"input_csv:{key}", confidence
    domain = row.get("domain", "")
    if domain:
        stem = domain.split(".")[0].replace("-", " ").title()
        return stem, "derived_from_domain", 0.35
    return "", "", 0.0


def company_identity_from_text(text: str) -> dict[str, str]:
    cleaned = clean_text(text)
    legal_form = detect_legal_form(cleaned)
    legal_name = ""
    if legal_form:
        legal_name = choose_legal_name(cleaned, legal_form)
    if not legal_name:
        for fallback_form in ("GmbH", "UG", "AG", "e.K.", "KG", "OHG", "GbR"):
            if re.search(rf"\b{re.escape(fallback_form)}\b", cleaned, flags=re.IGNORECASE):
                candidate = choose_legal_name(cleaned, fallback_form)
                if candidate:
                    legal_form = fallback_form
                    legal_name = candidate
                    break
    return {"legal_name": legal_name, "legal_form": legal_form}


def choose_legal_name(text: str, legal_form: str) -> str:
    candidates: list[tuple[int, str]] = []
    pattern = (
        rf"([A-Z\u00c4\u00d6\u00dcA-Za-z0-9]"
        rf"[A-Z\u00c4\u00d6\u00dca-z\u00e4\u00f6\u00fc\u00df0-9&.,\-\s]{{2,80}}"
        rf"{re.escape(legal_form)})"
    )
    for match in re.finditer(pattern, text):
        candidate = clean_legal_name(match.group(1))
        if not is_plausible_legal_name(candidate, legal_form):
            continue
        context = text[max(0, match.start() - 80) : match.end() + 40].lower()
        score = 10
        if any(marker in context for marker in LEGAL_CONTEXT_MARKERS):
            score += 20
        if candidate.lower().endswith(legal_form.lower()):
            score += 5
        candidates.append((score, candidate))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: (-item[0], len(item[1])))
    return candidates[0][1]


def is_plausible_legal_name(value: str, legal_form: str) -> bool:
    text = clean_text(value)
    lower = text.lower()
    if not text or legal_form.lower() not in lower:
        return False
    if any(token in lower for token in LOW_VALUE_LEGAL_NAME_TOKENS):
        return False
    if PRODUCT_LEGAL_NAME_RE.search(lower):
        return False
    if lower.startswith(("diensteanbieter ", "anbieter ")):
        return False
    if re.search(r"\b(eine|einer|einem|einen|umgr\u00fcndung|seminar|bestellungen)\b", lower):
        return False
    words = text.split()
    if len(words) > 8 or len(words) < 2:
        return False
    return True


def clean_legal_name(value: str) -> str:
    text = clean_text(value)
    for marker in (
        "Angaben gemaess",
        "Angaben gemass",
        "Angaben gem\u00e4\u00df",
        "Impressum",
        "Kontakt",
        "Anbieter",
        "Diensteanbieter",
        "Betreiber",
    ):
        while marker in text:
            text = text.split(marker, 1)[-1]
    words = text.split()
    if len(words) > 8:
        text = " ".join(words[-8:])
    return text.strip(" ,.;:-")
