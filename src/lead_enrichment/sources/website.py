from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import re


DEFAULT_USER_AGENT = "VHDLeadEnrichment/0.1 (+https://www.vhd-coaching-x2.de/)"


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int
    html: str
    error: str = ""


def fetch_url(url: str, user_agent: str = DEFAULT_USER_AGENT, timeout: int = 8) -> FetchResult:
    request = Request(url, headers={"User-Agent": user_agent})
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(512_000)
            charset = response.headers.get_content_charset() or "utf-8"
            html = raw.decode(charset, errors="replace")
            return FetchResult(url=url, status=response.status, html=html)
    except HTTPError as exc:
        return FetchResult(url=url, status=exc.code, html="", error=str(exc))
    except URLError as exc:
        return FetchResult(url=url, status=0, html="", error=str(exc.reason))


def html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html or "")
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</p>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def same_domain_url(domain: str, path: str) -> str:
    cleaned_path = path if path.startswith("/") else f"/{path}"
    return f"https://{domain}{cleaned_path}"
