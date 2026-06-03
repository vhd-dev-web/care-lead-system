from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_TAVILY_ENDPOINT = "https://api.tavily.com/search"


@dataclass(frozen=True)
class TavilyResult:
    title: str
    url: str
    content: str = ""
    score: float = 0.0
    raw_content: str = ""


@dataclass(frozen=True)
class TavilySearchResponse:
    query: str
    answer: str
    results: list[TavilyResult]
    credits: int = 1
    raw: dict | None = None


class TavilyClient:
    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str = DEFAULT_TAVILY_ENDPOINT,
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key or os.environ.get("TAVILY_API_KEY") or read_dotenv_key(
            Path(".env"), "TAVILY_API_KEY"
        )
        self.endpoint = endpoint
        self.timeout = timeout
        if not self.api_key:
            raise ValueError("TAVILY_API_KEY is missing. Add it to .env or the environment.")

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        search_depth: str = "basic",
        country: str = "germany",
    ) -> TavilySearchResponse:
        payload = json.dumps(
            {
                "query": query,
                "topic": "general",
                "search_depth": search_depth,
                "max_results": max_results,
                "include_answer": "basic",
                "include_raw_content": False,
                "include_images": False,
                "include_favicon": False,
                "include_usage": True,
                "auto_parameters": False,
                "country": country,
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
            raise RuntimeError(f"Tavily request failed with HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Tavily request failed: {exc.reason}") from exc

        data = json.loads(body)
        if not isinstance(data, dict):
            raise RuntimeError(f"Tavily request returned invalid JSON: {body[:500]}")
        return parse_tavily_response(query, data)


def parse_tavily_response(query: str, data: dict) -> TavilySearchResponse:
    raw_results = data.get("results", [])
    if not isinstance(raw_results, list):
        raw_results = []
    usage = data.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}
    results = [
        TavilyResult(
            title=str(item.get("title", "")),
            url=str(item.get("url", "")),
            content=str(item.get("content", "")),
            score=float(item.get("score") or 0.0),
            raw_content=str(item.get("raw_content") or ""),
        )
        for item in raw_results
        if isinstance(item, dict) and item.get("url")
    ]
    return TavilySearchResponse(
        query=str(data.get("query") or query),
        answer=str(data.get("answer") or ""),
        results=results,
        credits=int(usage.get("credits") or 1),
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
