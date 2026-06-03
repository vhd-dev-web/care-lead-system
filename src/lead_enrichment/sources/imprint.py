from __future__ import annotations

import re
import urllib.parse


IMPRINT_PATHS = ["/impressum", "/imprint", "/anbieterkennzeichnung"]


def discover_imprint_url(domain: str, html: str = "") -> str:
    for href, label in extract_links(html):
        if "impressum" in label.lower() or "imprint" in label.lower():
            return absolute_url(domain, href)
    return f"https://{domain}/impressum"


def extract_links(html: str) -> list[tuple[str, str]]:
    pattern = re.compile(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', flags=re.IGNORECASE | re.DOTALL)
    links: list[tuple[str, str]] = []
    for href, label_html in pattern.findall(html or ""):
        label = re.sub(r"<[^>]+>", " ", label_html)
        label = re.sub(r"\s+", " ", label).strip()
        links.append((href.strip(), label))
    return links


def absolute_url(domain: str, href: str) -> str:
    base = f"https://{domain}/"
    return urllib.parse.urljoin(base, href)
