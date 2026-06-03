from __future__ import annotations

import re

from ..normalizer import clean_text


PATTERNS = [
    (
        "Operator",
        r"(?:run by|operated by|managed by|CEO(?:\s+(?:is|named))?|owner(?:\s+is)?)\s*:?\s*"
        r"([A-Z\u00c4\u00d6\u00dc][A-Za-z\u00c4\u00d6\u00dc\u00e4\u00f6\u00fc\u00df\-\s.]{3,80})",
    ),
    (
        "Geschaeftsfuehrer",
        r"(?:Geschaeftsfuehrer(?:/in)?|Gesch\u00e4ftsf\u00fchrer(?:/in)?|Vertreten durch)\s*(?:ist|:)?\s*"
        r"([A-Z\u00c4\u00d6\u00dc][A-Za-z\u00c4\u00d6\u00dc\u00e4\u00f6\u00fc\u00df\-\s.]{3,80})",
    ),
    (
        "Inhaber",
        r"(?:Inhaber|Inhaberin)\s*:?\s*"
        r"([A-Z\u00c4\u00d6\u00dc][A-Za-z\u00c4\u00d6\u00dc\u00e4\u00f6\u00fc\u00df\-\s.]{3,80})",
    ),
]


def extract_decision_maker(text: str) -> dict[str, str | float]:
    source_text = clean_text(text)
    for role, pattern in PATTERNS:
        match = re.search(pattern, source_text, flags=re.IGNORECASE)
        if match:
            name = clean_person_name(match.group(1))
            if is_plausible_person_name(name):
                return {
                    "name": name,
                    "role": role,
                    "source": "website_text",
                    "confidence": 0.95,
                }
    return {"name": "", "role": "", "source": "", "confidence": 0.0}


def clean_person_name(value: str) -> str:
    text = clean_text(value)
    text = re.split(
        r"(?:Telefon|E-Mail|Email|Register|USt|Ust-ID|Umsatzsteuer(?:-Identifikationsnummer)?|"
        r"Umsatzsteueridentifikationsnummer|Adresse|Sitz|Impressum|Kontakt|"
        r"The company|company's|registered|address|Sources?|managed by|website|offers|"
        r"EU-STREITSCHLICHTUNG|Werderstr|Stra\u00dfe|Strasse|Street|HRB)\b",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    text = re.split(
        r"(?:\.(?=\s+(?:The|This|Der|Die|Das|USt|Ust|Adresse|Register|Telefon|Email|E-Mail))|\||, und|, and)\s+",
        text,
        maxsplit=1,
    )[0]
    text = re.split(r"\s+and\s+(?:offers|has|runs|operates|is)\b", text, maxsplit=1, flags=re.IGNORECASE)[0]
    text = re.sub(r"\s+(?:and|und)\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(
        r"^(?:ist|is|Gesch\u00e4ftsf\u00fchrer|Geschaeftsfuehrer|Inhaber|Inhaberin|"
        r"Vertreten durch|managed by)\s*:?\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = text.strip(" ,.;")
    words = text.split()
    if len(words) > 5:
        text = " ".join(words[:5])
    return text


def is_plausible_person_name(value: str) -> bool:
    text = clean_text(value)
    if not text:
        return False
    lowered = text.lower()
    if lowered in {"einer", "eine", "einem", "wir", "kontakt", "impressum"}:
        return False
    if any(token in lowered for token in ("umsatzsteuer", "identifikationsnummer", "register", "adresse")):
        return False
    words = text.split()
    if len(words) < 2:
        return False
    if any(char.isdigit() for char in text):
        return False
    return True
