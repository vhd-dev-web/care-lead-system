from __future__ import annotations

import re


LEGAL_FORM_PATTERNS = [
    r"\bGmbH\s*&\s*Co\.\s*KG\b",
    r"\bGmbH\b",
    r"\bUG\s*\(haftungsbeschraenkt\)\b",
    r"\bUG\s*\(haftungsbeschr\u00e4nkt\)\b",
    r"\bAG\b",
    r"\be\.K\.\b",
    r"\be\.Kfm\.\b",
    r"\bKG\b",
    r"\bOHG\b",
    r"\bGbR\b",
    r"\bEinzelunternehmen\b",
]


def detect_legal_form(text: str) -> str:
    for pattern in LEGAL_FORM_PATTERNS:
        match = re.search(pattern, text or "", flags=re.IGNORECASE)
        if match:
            return match.group(0)
    return ""
