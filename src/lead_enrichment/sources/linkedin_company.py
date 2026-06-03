from __future__ import annotations


def linkedin_manual_search_hint(company_name: str, domain: str) -> str:
    terms = " ".join(part for part in (company_name, domain) if part)
    return f"Manual LinkedIn company/person research only: {terms}".strip()
