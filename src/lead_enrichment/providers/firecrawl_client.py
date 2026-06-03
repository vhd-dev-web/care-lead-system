from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_FIRECRAWL_ENDPOINT = "https://api.firecrawl.dev/v2/scrape"


@dataclass(frozen=True)
class FirecrawlScrapeResponse:
    url: str
    markdown: str
    source_url: str
    title: str = ""
    status_code: int = 0
    warning: str = ""
    raw: dict | None = None


class FirecrawlClient:
    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str = DEFAULT_FIRECRAWL_ENDPOINT,
        timeout: int = 60,
        request_timeout_ms: int = 60000,
        proxy: str = "basic",
    ) -> None:
        self.api_key = api_key or os.environ.get("FIRECRAWL_API_KEY") or read_dotenv_key(
            Path(".env"), "FIRECRAWL_API_KEY"
        )
        self.endpoint = endpoint
        self.timeout = timeout
        self.request_timeout_ms = request_timeout_ms
        self.proxy = proxy
        if not self.api_key:
            raise ValueError("FIRECRAWL_API_KEY is missing. Add it to .env or the environment.")

    def scrape(self, url: str) -> FirecrawlScrapeResponse:
        payload = json.dumps(
            {
                "url": url,
                "formats": ["markdown"],
                "onlyMainContent": True,
                "removeBase64Images": True,
                "blockAds": True,
                "proxy": self.proxy,
                "storeInCache": False,
                "timeout": self.request_timeout_ms,
            }
        ).encode("utf-8")
        request = Request(
            self.endpoint,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            raise RuntimeError(f"Firecrawl request failed with HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Firecrawl request failed: {exc.reason}") from exc

        data = json.loads(body)
        if not isinstance(data, dict) or not data.get("success", False):
            raise RuntimeError(f"Firecrawl request failed: {body[:500]}")
        scrape_data = data.get("data", {})
        if not isinstance(scrape_data, dict):
            scrape_data = {}
        metadata = scrape_data.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        return FirecrawlScrapeResponse(
            url=url,
            markdown=str(scrape_data.get("markdown") or ""),
            source_url=str(metadata.get("sourceURL") or metadata.get("url") or url),
            title=str(metadata.get("title") or ""),
            status_code=int(metadata.get("statusCode") or 0),
            warning=str(scrape_data.get("warning") or ""),
            raw=data,
        )


def read_dotenv_key(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return ""
