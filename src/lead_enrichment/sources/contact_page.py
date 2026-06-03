from __future__ import annotations

from .imprint import absolute_url, extract_links


CONTACT_PATHS = ["/kontakt", "/contact", "/service", "/kundenservice"]


def discover_contact_url(domain: str, html: str = "") -> str:
    for href, label in extract_links(html):
        lowered = label.lower()
        if "kontakt" in lowered or "contact" in lowered or "kundenservice" in lowered:
            return absolute_url(domain, href)
    return f"https://{domain}/kontakt"
