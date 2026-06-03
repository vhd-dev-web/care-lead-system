from __future__ import annotations

from .extractors.company_identity import company_identity_from_text, is_plausible_legal_name
from .extractors.contacts import is_plausible_phone, normalize_phone
from .extractors.decision_makers import clean_person_name, is_plausible_person_name
from .extractors.legal_form import detect_legal_form
from .normalizer import clean_text


def sanitize_queue_fields(row: dict[str, str]) -> dict[str, str]:
    cleaned = dict(row)
    cleaned["phone_main"] = sanitize_phone(cleaned.get("phone_main"))
    cleaned["legal_name"] = sanitize_legal_name(cleaned.get("legal_name"), cleaned.get("legal_form"))
    if cleaned["legal_name"]:
        cleaned["legal_form"] = clean_text(cleaned.get("legal_form")) or detect_legal_form(cleaned["legal_name"])
    else:
        cleaned["legal_form"] = ""
    cleaned["managing_director_name"] = sanitize_person_name(cleaned.get("managing_director_name"))
    if not cleaned["managing_director_name"]:
        cleaned["managing_director_source"] = ""
    return cleaned


def sanitize_phone(value: object) -> str:
    phone = normalize_phone(clean_text(value))
    return phone if phone and is_plausible_phone(phone) else ""


def sanitize_legal_name(value: object, legal_form: object = "") -> str:
    text = clean_text(value)
    form = clean_text(legal_form) or detect_legal_form(text)
    if not text or not form:
        return ""
    if is_plausible_legal_name(text, form):
        return text
    identity = company_identity_from_text(text)
    candidate = identity.get("legal_name", "")
    candidate_form = identity.get("legal_form", "") or form
    if candidate and is_plausible_legal_name(candidate, candidate_form):
        return candidate
    return ""


def sanitize_person_name(value: object) -> str:
    name = clean_person_name(clean_text(value))
    return name if is_plausible_person_name(name) else ""


def merge_quality_value(row: dict[str, str], key: str, value: str, *, source_key: str = "") -> None:
    sanitized = sanitize_value_for_key(key, value)
    current = sanitize_value_for_key(key, row.get(key, ""))
    if current:
        row[key] = current
        return
    if sanitized:
        row[key] = sanitized
        return
    if key in row:
        row[key] = ""
        if source_key:
            row[source_key] = ""


def overwrite_with_quality_value(row: dict[str, str], key: str, value: str, *, source_key: str = "") -> None:
    sanitized = sanitize_value_for_key(key, value)
    if sanitized:
        row[key] = sanitized
    elif key in row and not sanitize_value_for_key(key, row.get(key, "")):
        row[key] = ""
        if source_key:
            row[source_key] = ""


def sanitize_value_for_key(key: str, value: object) -> str:
    if key == "phone_main":
        return sanitize_phone(value)
    if key == "legal_name":
        return sanitize_legal_name(value)
    if key == "managing_director_name":
        return sanitize_person_name(value)
    return clean_text(value)
