from __future__ import annotations


def register_review_note(company_name: str) -> str:
    if not company_name:
        return "Manual register check needed after company identity is confirmed."
    return f"Manual Unternehmensregister/Handelsregister check recommended for {company_name}."
