from __future__ import annotations

import json
import random
import sqlite3
import time
import urllib.parse
import urllib.robotparser
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_POLICY_PATH = Path("crawler_policy.json")
_ROBOTS_PARSERS: dict[tuple[str, str], tuple[urllib.robotparser.RobotFileParser | None, str]] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def load_policy(path: Path | str = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    policy_path = Path(path)
    defaults = {
        "brave_daily_limit": 100,
        "domain_scoring_daily_limit": 100,
        "deep_scoring_daily_limit": 40,
        "max_parallel_requests": 2,
        "domain_delay_seconds_min": 8,
        "domain_delay_seconds_max": 25,
        "page_delay_seconds_min": 2,
        "page_delay_seconds_max": 5,
        "domain_cooldown_days": 14,
        "robots_txt_enabled": True,
        "stop_status_codes": [403, 429, 503],
        "stop_on_low_brave_remaining": True,
        "brave_low_remaining_threshold": 1,
        "state_db_path": "output/state/pipeline_state.sqlite",
        "bot_user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    }
    if policy_path.exists():
        loaded = json.loads(policy_path.read_text(encoding="utf-8"))
        defaults.update(loaded)
    return defaults


def policy_sleep(policy: dict[str, Any], min_key: str, max_key: str, disabled: bool = False) -> None:
    if disabled:
        return
    min_seconds = float(policy.get(min_key, 0) or 0)
    max_seconds = float(policy.get(max_key, min_seconds) or min_seconds)
    if max_seconds <= 0:
        return
    if max_seconds < min_seconds:
        max_seconds = min_seconds
    time.sleep(random.uniform(min_seconds, max_seconds))


class CrawlerState:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS daily_counters (
                    day TEXT NOT NULL,
                    counter_key TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (day, counter_key)
                );

                CREATE TABLE IF NOT EXISTS domain_checks (
                    domain TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    last_checked_at TEXT NOT NULL,
                    status TEXT,
                    http_status INTEGER,
                    error_code TEXT,
                    request_count INTEGER DEFAULT 0,
                    PRIMARY KEY (domain, mode)
                );

                CREATE TABLE IF NOT EXISTS robots_cache (
                    domain TEXT PRIMARY KEY,
                    fetched_at TEXT NOT NULL,
                    robots_url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    raw_rules TEXT
                );

                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    domain TEXT,
                    provider TEXT,
                    status TEXT,
                    details TEXT
                );

                CREATE TABLE IF NOT EXISTS brave_rate_limits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    remaining TEXT,
                    reset_seconds TEXT,
                    status_code INTEGER,
                    query TEXT
                );
                """
            )

    def get_counter(self, counter_key: str, day: str | None = None) -> int:
        day = day or today_key()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT count FROM daily_counters WHERE day = ? AND counter_key = ?",
                (day, counter_key),
            ).fetchone()
            return int(row["count"]) if row else 0

    def increment_counter(self, counter_key: str, amount: int = 1, day: str | None = None) -> int:
        day = day or today_key()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO daily_counters(day, counter_key, count)
                VALUES (?, ?, ?)
                ON CONFLICT(day, counter_key)
                DO UPDATE SET count = count + excluded.count
                """,
                (day, counter_key, amount),
            )
        return self.get_counter(counter_key, day)

    def remaining(self, counter_key: str, daily_limit: int) -> int:
        return max(0, int(daily_limit) - self.get_counter(counter_key))

    def record_event(
        self,
        event_type: str,
        domain: str = "",
        provider: str = "",
        status: str = "",
        details: dict[str, Any] | str | None = None,
    ) -> None:
        if isinstance(details, dict):
            details_value = json.dumps(details, ensure_ascii=False, sort_keys=True)
        else:
            details_value = details or ""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO events(created_at, event_type, domain, provider, status, details)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (utc_now(), event_type, domain, provider, status, details_value),
            )

    def record_brave_rate_limit(
        self,
        remaining: str,
        reset_seconds: str,
        status_code: int,
        query: str,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO brave_rate_limits(created_at, remaining, reset_seconds, status_code, query)
                VALUES (?, ?, ?, ?, ?)
                """,
                (utc_now(), remaining, reset_seconds, int(status_code), query),
            )

    def get_domain_check(self, domain: str, mode: str) -> sqlite3.Row | None:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM domain_checks WHERE domain = ? AND mode = ?",
                (domain, mode),
            ).fetchone()

    def checked_within_cooldown(self, domain: str, mode: str, cooldown_days: int) -> bool:
        row = self.get_domain_check(domain, mode)
        if not row:
            return False
        try:
            last = datetime.strptime(row["last_checked_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            return False
        age_seconds = (datetime.now(timezone.utc) - last).total_seconds()
        return age_seconds < int(cooldown_days) * 86400

    def record_domain_check(
        self,
        domain: str,
        mode: str,
        status: str,
        http_status: int,
        error_code: str,
        request_count: int,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO domain_checks(domain, mode, last_checked_at, status, http_status, error_code, request_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(domain, mode)
                DO UPDATE SET
                    last_checked_at = excluded.last_checked_at,
                    status = excluded.status,
                    http_status = excluded.http_status,
                    error_code = excluded.error_code,
                    request_count = excluded.request_count
                """,
                (domain, mode, utc_now(), status, int(http_status or 0), error_code, int(request_count or 0)),
            )

    def cache_robots(self, domain: str, robots_url: str, status: str, raw_rules: str = "") -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO robots_cache(domain, fetched_at, robots_url, status, raw_rules)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(domain)
                DO UPDATE SET
                    fetched_at = excluded.fetched_at,
                    robots_url = excluded.robots_url,
                    status = excluded.status,
                    raw_rules = excluded.raw_rules
                """,
                (domain, utc_now(), robots_url, status, raw_rules[:20_000]),
            )


def build_state(policy: dict[str, Any], explicit_path: Path | str | None = None) -> CrawlerState:
    path = explicit_path or policy.get("state_db_path") or "output/state/pipeline_state.sqlite"
    return CrawlerState(path)


def robots_allowed(
    domain: str,
    url: str,
    user_agent: str,
    policy: dict[str, Any],
    state: CrawlerState | None = None,
) -> tuple[bool, str]:
    if not policy.get("robots_txt_enabled", True):
        return True, "disabled"

    parsed = urllib.parse.urlparse(url)
    scheme = parsed.scheme or "https"
    host = (parsed.netloc or domain).lower()
    cache_key = (scheme, host)

    if cache_key in _ROBOTS_PARSERS:
        parser, cached_status = _ROBOTS_PARSERS[cache_key]
        if parser is None:
            return True, cached_status
        allowed = parser.can_fetch(user_agent, url)
        return allowed, "allowed" if allowed else "disallowed"

    robots_url = f"{scheme}://{host}/robots.txt"
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.read()
        allowed = parser.can_fetch(user_agent, url)
        status = "allowed" if allowed else "disallowed"
        _ROBOTS_PARSERS[cache_key] = (parser, "fetched")
        if state:
            state.cache_robots(domain, robots_url, status)
        return allowed, status
    except Exception as exc:  # urllib.robotparser is intentionally broad internally too.
        status = f"unknown:{exc.__class__.__name__}"
        _ROBOTS_PARSERS[cache_key] = (None, status)
        if state:
            state.cache_robots(domain, robots_url, status)
        return True, status
