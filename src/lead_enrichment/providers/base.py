from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SearchResult:
    title: str
    link: str
    snippet: str = ""
    position: int = 0


@dataclass(frozen=True)
class ProviderUsage:
    provider: str
    query_count: int = 0
    result_count: int = 0
    error: str = ""
