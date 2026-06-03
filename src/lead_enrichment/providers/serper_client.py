from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .base import SearchResult


DEFAULT_SERPER_ENDPOINT = "https://google.serper.dev/search"


@dataclass(frozen=True)
class SerperSearchResponse:
    query: str
    results: list[SearchResult]
    raw: dict


class SerperClient:
    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str = DEFAULT_SERPER_ENDPOINT,
        timeout: int = 15,
    ) -> None:
        self.api_key = api_key or os.environ.get("SERPER_API_KEY") or read_dotenv_key(
            Path(".env"), "SERPER_API_KEY"
        )
        self.endpoint = endpoint
        self.timeout = timeout
        if not self.api_key:
            raise ValueError("SERPER_API_KEY is missing. Add it to .env or the environment.")

    def search(self, query: str, *, num: int = 5, gl: str = "de", hl: str = "de") -> SerperSearchResponse:
        payload = json.dumps({"q": query, "num": num, "gl": gl, "hl": hl}).encode("utf-8")
        request = Request(
            self.endpoint,
            data=payload,
            headers={
                "X-API-KEY": self.api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else str(exc)
            raise RuntimeError(f"Serper request failed with HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Serper request failed: {exc.reason}") from exc

        data = json.loads(body)
        organic = data.get("organic", []) if isinstance(data, dict) else []
        results = [
            SearchResult(
                title=str(item.get("title", "")),
                link=str(item.get("link", "")),
                snippet=str(item.get("snippet", "")),
                position=int(item.get("position") or idx + 1),
            )
            for idx, item in enumerate(organic)
            if isinstance(item, dict) and item.get("link")
        ]
        return SerperSearchResponse(query=query, results=results, raw=data)


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
