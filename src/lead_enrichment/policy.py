from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_PROVIDER_FLAGS = {
    "serper": {"enabled": False},
    "firecrawl": {"enabled": False},
    "tavily": {"enabled": False},
    "clay": {"enabled": False},
}


@dataclass(frozen=True)
class EnrichmentPolicy:
    website_enrichment_daily_limit: int = 20
    firecrawl_daily_limit: int = 10
    serper_daily_limit: int = 20
    tavily_daily_limit: int = 5
    clay_daily_limit: int = 2
    clay_monthly_limit: int = 10
    max_serper_queries_b_lead: int = 2
    max_serper_queries_a_plus_plus_lead: int = 4
    website_pages_per_domain: int = 7
    website_paths: list[str] = field(
        default_factory=lambda: [
            "/",
            "/impressum",
            "/imprint",
            "/kontakt",
            "/contact",
            "/datenschutz",
            "/ueber-uns",
            "/team",
        ]
    )
    providers: dict[str, dict[str, Any]] = field(default_factory=lambda: dict(DEFAULT_PROVIDER_FLAGS))

    @classmethod
    def from_file(cls, path: Path | str | None) -> "EnrichmentPolicy":
        if not path:
            return cls()
        policy_path = Path(path)
        if not policy_path.exists():
            return cls()
        loaded = json.loads(policy_path.read_text(encoding="utf-8"))
        providers = dict(DEFAULT_PROVIDER_FLAGS)
        providers.update(loaded.pop("providers", {}) or {})
        return cls(**{**loaded, "providers": providers})

    def provider_enabled(self, provider: str) -> bool:
        return bool(self.providers.get(provider, {}).get("enabled", False))
