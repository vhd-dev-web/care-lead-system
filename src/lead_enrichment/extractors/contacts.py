from __future__ import annotations

import re


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", flags=re.IGNORECASE)
PHONE_RE = re.compile(r"(?:\+49|0049|0)[\d\s()./-]{5,}\d")
PHONE_CONTEXT_RE = re.compile(
    r"(?:Telefon|Tel\.?|Fon|Phone|Mobil|Mobile|Rufnummer)\s*:?\s*"
    r"((?:\+49|0049|0)[\d\s()./-]{5,}\d)",
    flags=re.IGNORECASE,
)
DATE_LIKE_RE = re.compile(r"^\d{1,2}[./-]\d{2,4}$")
GENERIC_PREFIXES = {
    "info",
    "kontakt",
    "contact",
    "office",
    "service",
    "support",
    "shop",
    "kundenservice",
    "mail",
    "hello",
    "hallo",
    "team",
    "vertrieb",
    "sales",
}


def extract_emails(text: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for match in EMAIL_RE.findall(text or ""):
        email = match.lower()
        if email not in seen:
            seen.add(email)
            result.append(email)
    return result


def is_generic_email(email: str) -> bool:
    prefix = email.split("@", 1)[0].lower()
    return prefix in GENERIC_PREFIXES or prefix.startswith(("info.", "kontakt.", "office."))


def choose_general_email(text: str) -> str:
    emails = extract_emails(text)
    for email in emails:
        if is_generic_email(email):
            return email
    return ""


def extract_phone_numbers(text: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for match in PHONE_RE.findall(text or ""):
        phone = normalize_phone(match)
        if not is_plausible_phone(phone):
            continue
        if phone not in seen:
            seen.add(phone)
            result.append(phone)
    return result


def extract_contextual_phone_numbers(text: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for match in PHONE_CONTEXT_RE.findall(text or ""):
        phone = normalize_phone(match)
        if is_plausible_phone(phone) and phone not in seen:
            seen.add(phone)
            result.append(phone)
    return result


def is_plausible_phone(phone: str) -> bool:
    compact = phone.strip()
    digits = re.sub(r"\D", "", compact)
    if len(digits) < 8:
        return False
    if digits.startswith("000"):
        return False
    if DATE_LIKE_RE.match(compact):
        return False
    groups = [group for group in re.split(r"\D+", compact) if group]
    if len(groups) == 2 and len(groups[1]) == 4 and groups[1].startswith(("19", "20")):
        return False
    if len(groups) == 2 and all(len(group) == 4 for group in groups):
        return False
    if "." in compact and len(groups) >= 4 and sum(1 for group in groups if len(group) <= 2) >= 2:
        return False
    return True


def normalize_phone(value: str) -> str:
    phone = re.sub(r"\s+", " ", value).strip(" .-/")
    phone = re.sub(r"^0\)", "0", phone)
    phone = re.sub(r"(?<!\()0\)", "0", phone)
    phone = re.sub(r"\(\s*0\s*\)", "(0)", phone)
    return phone


def choose_main_phone(text: str) -> str:
    phones = extract_contextual_phone_numbers(text)
    if not phones:
        phones = extract_phone_numbers(text)
    return phones[0] if phones else ""
