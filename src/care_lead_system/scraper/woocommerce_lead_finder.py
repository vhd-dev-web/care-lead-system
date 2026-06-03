#!/usr/bin/env python3
"""
WooCommerce Lead Finder for VHD Erfolg2 Coaching.

Cheap daily workflow:
1. Uses Brave Search API or legacy Google Custom Search within a call budget.
2. Rotates through a large query bank so every run explores a new slice.
3. Deduplicates by domain against output/leads_master.csv.
4. Optionally enriches found domains from public website pages.

Run:
    python woocommerce_lead_finder.py --enrich --budget-calls 80

Secrets:
    Put BRAVE_SEARCH_API_KEY into a local .env file.
    Legacy Google CSE is still supported with GOOGLE_CSE_API_KEY and GOOGLE_CSE_ID.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

from .crawler_support import build_state, load_policy


DEFAULT_SEARCH_ENGINE_ID = "50f46685f0e4d4b78"
DEFAULT_OUTPUT_DIR = Path("output")
DEFAULT_BUDGET_CALLS = 80
DEFAULT_PAGES_PER_QUERY = 1
DEFAULT_DELAY_SECONDS = 1.0
DEFAULT_PROVIDER = "auto"
DEFAULT_QUALIFIED_MIN_SCORE = 35
REQUEST_TIMEOUT_SECONDS = 15
# Realistic browser UA. Many German care-aid provider sites return 403
# to obvious bot user-agents. Used for both API calls (Brave, Google CSE
# do not care about the UA) and HTML page fetches in the optional enrich
# step. We still respect robots.txt and rate limits.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Sent with fetch_page() so the request looks like a real browser, not
# only its UA. Skipped on Brave/Google CSE API calls which expect JSON.
BROWSER_PAGE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

MASTER_FIELDS = [
    "domain",
    "url",
    "company_name",
    "email",
    "phone",
    "title",
    "snippet",
    "country_hint",
    "lead_score",
    "signals",
    "source_query",
    "status",
    "notes",
    "found_at",
    "last_seen_at",
]

RUN_FIELDS = MASTER_FIELDS + ["is_new", "run_id"]

INSTANTLY_FIELDS = ["Email", "First Name", "Last Name", "Company", "Website"]


BLOCKED_DOMAIN_PARTS = [
    "amazon.",
    "arboro.",
    "chip.",
    "conversionboosting.",
    "convert-gmbh.",
    "daswebsite.",
    "designers-inn.",
    "ebay.",
    "elsenmedia.",
    "etsy.",
    "facebook.",
    "fehler7.",
    "fuer-gruender.",
    "github.io",
    "github.",
    "google.",
    "haendlerbund.",
    "hb-ecommerce.",
    "heise.",
    "hosteurope.",
    "ihk.",
    "instagram.",
    "ionos.",
    "it-recht-kanzlei.",
    "itportal24.",
    "janolaw.",
    "kinsta.",
    "linkedin.",
    "linguee.",
    "marketpress.",
    "mbaierl.",
    "mediamarkt.",
    "mollie.",
    "omr.",
    "outvio.",
    "payone.",
    "pinterest.",
    "protectedshops.",
    "pons.",
    "raidboxes.",
    "rtl.",
    "ryte.",
    "secupay.",
    "sevdesk.",
    "shopify.",
    "shopware.com",
    "strato.",
    "stadtbranche.",
    "template",
    "tiktok.",
    "trustedshops.",
    "uptain.",
    "vendidero.",
    "websale.",
    "woocommerce.com",
    "woogency.",
    "wordpress.org",
    "wpbeginner.",
    "wpengine.",
    "youtube.",
]

NON_SHOP_TEXT_TERMS = [
    "agentur",
    "agency",
    "anwalt",
    "blog",
    "buchhaltung",
    "buchhaltungssoftware",
    "cookie",
    "datenschutzerkl",
    "datenschutzerklaerung",
    "datenschutzerklärung",
    "e-commerce agentur",
    "ecommerce agentur",
    "einrichten",
    "erstellen",
    "funktioniert nicht",
    "generator",
    "hosting",
    "hoster",
    "kanzlei",
    "kassensystem",
    "leitfaden",
    "magazin",
    "payment",
    "payment provider",
    "plugin",
    "plugins",
    "pos kassensystem",
    "praxistipp",
    "profis",
    "ratgeber",
    "rechtstexte",
    "rechtssicher",
    "rechtlichen voraussetzungen",
    "software",
    "shopware",
    "shopsystem",
    "template",
    "templates",
    "theme",
    "themes",
    "tutorial",
    "voraussetzungen",
    "webagentur",
    "webdesign",
    "wordpress agentur",
    "woocommerce agentur",
    "zahlungsanbieter",
    "zahlungsmethoden",
]

OWN_DOMAINS = {
    "vhd-coaching-x2.de",
    "www.vhd-coaching-x2.de",
    "vhd-erfolg-x2.de",
    "www.vhd-erfolg-x2.de",
}

COUNTRY_HINTS = {
    ".de": "DE",
    ".at": "AT",
    ".ch": "CH",
}

NICHE_TERMS = [
    "mode",
    "fashion",
    "bekleidung",
    "schuhe",
    "beauty",
    "kosmetik",
    "naturkosmetik",
    "supplements",
    "ernaehrung",
    "kaffee",
    "tee",
    "wein",
    "moebel",
    "interior",
    "garten",
    "fahrrad",
    "sport",
    "outdoor",
    "baby",
    "spielzeug",
    "haustier",
    "tierbedarf",
    "werkzeug",
    "manufaktur",
    "shop",
]

BASE_QUERY_PATTERNS = [
    '"WooCommerce" "Impressum" site:{tld}',
    '"WooCommerce" "Warenkorb" site:{tld}',
    '"WooCommerce" "Kasse" site:{tld}',
    '"WooCommerce" "Checkout" site:{tld}',
    '"powered by WooCommerce" site:{tld}',
    '"In den Warenkorb" "Impressum" site:{tld}',
    '"Zur Kasse" "Impressum" site:{tld}',
    '"Versandkosten" "In den Warenkorb" site:{tld}',
    '"Zahlungsarten" "Warenkorb" site:{tld}',
    '"wp-content/plugins/woocommerce" site:{tld}',
]

NICHE_QUERY_PATTERNS = [
    '"WooCommerce" "{niche}" "Impressum" site:{tld}',
    '"In den Warenkorb" "{niche}" "Impressum" site:{tld}',
    '"Warenkorb" "{niche}" "Versandkosten" site:{tld}',
]

# Negative terms exclude obvious non-WooCommerce shop platforms at the
# search layer. They cut Brave quota usage by filtering Shopify/Shopware
# /Magento/JTL pages out of the result set before they hit the verifier.
# The verifier still performs the authoritative platform check.
BRAVE_NEGATIVE_TERMS = "-shopify -shopware -magento -jtl -prestashop"

BRAVE_BASE_QUERIES = [
    f'"Mein Konto" "Warenkorb" "Kasse" "Impressum" {BRAVE_NEGATIVE_TERMS}',
    f'"Warenkorb" "Kasse" "Impressum" "Versandkosten" {BRAVE_NEGATIVE_TERMS}',
    f'"Mein Konto" "In den Warenkorb" "Impressum" {BRAVE_NEGATIVE_TERMS}',
    f'"In den Warenkorb" Impressum Shop {BRAVE_NEGATIVE_TERMS}',
    f'"Zur Kasse" "Warenkorb" "Impressum" {BRAVE_NEGATIVE_TERMS}',
    f"WooCommerce Impressum Deutschland Shop {BRAVE_NEGATIVE_TERMS}",
    f"WooCommerce Warenkorb Deutschland Shop {BRAVE_NEGATIVE_TERMS}",
    f"WooCommerce Impressum Oesterreich Shop {BRAVE_NEGATIVE_TERMS}",
    f"WooCommerce Warenkorb Oesterreich Shop {BRAVE_NEGATIVE_TERMS}",
    f"WooCommerce Impressum Schweiz Shop {BRAVE_NEGATIVE_TERMS}",
    f"WooCommerce Warenkorb Schweiz Shop {BRAVE_NEGATIVE_TERMS}",
]

BRAVE_NICHE_QUERY_PATTERNS = [
    '"Mein Konto" "Warenkorb" "{niche}" "Impressum" ' + BRAVE_NEGATIVE_TERMS,
    '"In den Warenkorb" {niche} Impressum ' + BRAVE_NEGATIVE_TERMS,
    '"Warenkorb" "Kasse" "{niche}" "Versandkosten" ' + BRAVE_NEGATIVE_TERMS,
    "WooCommerce {niche} Online Shop Deutschland " + BRAVE_NEGATIVE_TERMS,
]

ENRICH_PATHS = ["/", "/impressum", "/impressum.php", "/kontakt", "/kontakt.php"]


@dataclass
class SearchResult:
    domain: str
    url: str
    company_name: str
    email: str
    phone: str
    title: str
    snippet: str
    country_hint: str
    lead_score: int
    signals: str
    source_query: str
    status: str
    notes: str
    found_at: str
    last_seen_at: str


@dataclass
class SearchApiResponse:
    data: dict | None
    status_code: int
    headers: dict[str, str]
    should_stop: bool = False


def load_dotenv(path: Path = Path(".env")) -> None:
    """Small .env loader so the script has no extra dependency."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip().strip('"').strip("'")
        if key and not os.environ.get(key):
            os.environ[key] = value


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def normalize_domain(url_or_domain: str) -> str:
    value = (url_or_domain or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value

    parsed = urlparse(value)
    domain = parsed.netloc.lower().strip()
    domain = domain.split("@")[-1]
    domain = domain.split(":")[0]
    if domain.startswith("www."):
        domain = domain[4:]
    return domain.rstrip(".")


def country_hint_for(domain: str) -> str:
    for suffix, country in COUNTRY_HINTS.items():
        if domain.endswith(suffix):
            return country
    return ""


def is_blocked_domain(domain: str) -> bool:
    if not domain or domain in OWN_DOMAINS:
        return True
    if domain.startswith(("demo.", "dev.", "staging.", "test.")):
        return True
    return any(part in domain for part in BLOCKED_DOMAIN_PARTS)


def looks_like_non_shop(text: str, url: str) -> bool:
    haystack = f"{text} {url}".lower()
    identity_terms = [
        "agentur",
        "agency",
        "blog",
        "einrichten",
        "erstellen",
        "funktioniert nicht",
        "hosting",
        "kanzlei",
        "kassensystem",
        "leitfaden",
        "magazin",
        "payment",
        "plugin",
        "profis",
        "ratgeber",
        "rechtlichen voraussetzungen",
        "rechtssicher",
        "software",
        "shopware",
        "shopsystem",
        "template",
        "theme",
        "tutorial",
        "voraussetzungen",
        "webagentur",
        "webdesign",
        "zahlungsanbieter",
        "zahlungsmethoden",
    ]
    identity_area = text.lower()[:180] + " " + normalize_domain(url).lower()
    if any(term in identity_area for term in identity_terms):
        return True

    shop_terms = ["in den warenkorb", "zur kasse", "versandkosten", "zahlungsarten", "lieferzeit"]
    if any(term in haystack for term in shop_terms):
        return False
    return any(term in haystack for term in NON_SHOP_TEXT_TERMS)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def extract_email(text: str) -> str:
    match = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text or "")
    if not match:
        return ""
    email = match.group(0).strip(".,;:()[]<>").lower()
    if email.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
        return ""
    return email


def extract_phone(text: str) -> str:
    match = re.search(r"(?:\+49|0049|0)[0-9][0-9\s()./-]{6,20}", text or "")
    if not match:
        return ""
    return clean_text(match.group(0).strip(".,;:()[]<>"))


def strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return clean_text(text)


def detect_signals(text: str, url: str) -> list[str]:
    haystack = f"{text} {url}".lower()
    checks = {
        "woocommerce": ["woocommerce", "wc-cart", "wp-content/plugins/woocommerce"],
        "cart_checkout": ["warenkorb", "kasse", "checkout", "in den warenkorb"],
        "tracking_ads": ["google ads", "ga4", "google tag manager", "gtm", "meta pixel"],
        "product_data": ["produktdaten", "google shopping", "merchant center"],
        "active_shop": ["versandkosten", "zahlungsarten", "lieferzeit", "retoure"],
        "wordpress": ["wordpress", "wp-content"],
        "imprint": ["impressum", "inhaber", "geschaeftsfuehrer", "geschaftsfuhrer"],
    }
    signals = []
    for signal, needles in checks.items():
        if any(needle in haystack for needle in needles):
            signals.append(signal)
    return signals


def score_lead(signals: Iterable[str], email: str, phone: str) -> int:
    weights = {
        "woocommerce": 35,
        "cart_checkout": 20,
        "active_shop": 15,
        "imprint": 10,
        "tracking_ads": 10,
        "product_data": 10,
        "wordpress": 5,
    }
    signal_set = set(signals)
    score = sum(weights.get(signal, 0) for signal in signal_set)
    if email:
        score += 8
    if phone:
        score += 5
    return min(score, 100)


def build_queries(provider: str = "google") -> list[str]:
    queries: list[str] = []
    if provider == "brave":
        queries.extend(BRAVE_BASE_QUERIES)
        for niche in NICHE_TERMS:
            for pattern in BRAVE_NICHE_QUERY_PATTERNS:
                queries.append(pattern.format(niche=niche))
        return list(dict.fromkeys(queries))

    tlds = [".de", ".at", ".ch"]

    for tld in tlds:
        for pattern in BASE_QUERY_PATTERNS:
            queries.append(pattern.format(tld=tld))

    for tld in tlds:
        for niche in NICHE_TERMS:
            for pattern in NICHE_QUERY_PATTERNS:
                queries.append(pattern.format(tld=tld, niche=niche))

    deduped = list(dict.fromkeys(queries))
    return deduped


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"query_cursor": 0}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"query_cursor": 0}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def select_daily_queries(
    queries: list[str],
    state: dict,
    budget_calls: int,
    pages_per_query: int,
    query_limit: int | None,
) -> list[str]:
    if query_limit is not None:
        max_queries = max(1, query_limit)
    else:
        max_queries = max(1, budget_calls // max(1, pages_per_query))
    max_queries = min(max_queries, len(queries))

    start = int(state.get("query_cursor", 0)) % len(queries)
    rotated = queries[start:] + queries[:start]
    selected = rotated[:max_queries]
    state["query_cursor"] = (start + max_queries) % len(queries)
    state["updated_at"] = utc_now()
    return selected


def google_search(
    api_key: str,
    search_engine_id: str,
    query: str,
    start_index: int,
) -> SearchApiResponse:
    params = {
        "key": api_key,
        "cx": search_engine_id,
        "q": query,
        "start": start_index,
        "num": 10,
    }

    url = "https://www.googleapis.com/customsearch/v1"
    full_url = url + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(full_url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = response.read().decode("utf-8", errors="replace")
            return SearchApiResponse(json.loads(payload), response.status, dict(response.headers))
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read().decode("utf-8", errors="replace")
        try:
            error_info = json.loads(body).get("error", {})
            detail = error_info.get("message") or error_info.get("status") or body[:200]
        except json.JSONDecodeError:
            detail = body[:200]
        if status == 403:
            print(f"API access denied: {detail}")
            print("Check Custom Search API, billing, and key restrictions.")
        elif status == 429:
            print(f"Google API quota/rate limit reached: {detail}")
        else:
            print(f"Google API HTTP error {status}: {detail}")
        return SearchApiResponse(None, status, {}, should_stop=status in {403, 429})
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Google API connection error: {exc}")
        return SearchApiResponse(None, 0, {}, should_stop=False)


def brave_search(api_key: str, query: str, offset: int) -> SearchApiResponse:
    params = {
        "q": query,
        "count": 20,
        "offset": offset,
        "country": "de",
        "search_lang": "de",
    }
    url = "https://api.search.brave.com/res/v1/web/search"
    full_url = url + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        full_url,
        headers={
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "X-Subscription-Token": api_key,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            payload = response.read().decode("utf-8", errors="replace")
            return SearchApiResponse(json.loads(payload), response.status, dict(response.headers))
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
            detail = (
                parsed.get("message")
                or parsed.get("error", {}).get("message")
                or parsed.get("error", {}).get("status")
                or body[:200]
            )
        except json.JSONDecodeError:
            detail = body[:200]
        if status in {401, 403}:
            print(f"Brave API access denied: {detail}")
        elif status == 429:
            print(f"Brave API quota/rate limit reached: {detail}")
        else:
            print(f"Brave API HTTP error {status}: {detail}")
        return SearchApiResponse(None, status, dict(exc.headers), should_stop=status in {401, 403, 429})
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"Brave API connection error: {exc}")
        return SearchApiResponse(None, 0, {}, should_stop=False)


def fetch_page(url: str) -> str:
    headers = {"User-Agent": USER_AGENT, **BROWSER_PAGE_HEADERS}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("content-type", "")
            if "text/html" not in content_type:
                return ""
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read(300_000).decode(charset, errors="replace")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError):
        return ""


def enrich_from_site(domain: str, landing_url: str, delay_seconds: float) -> dict[str, str]:
    base_url = landing_url if landing_url.startswith(("http://", "https://")) else f"https://{domain}"
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else f"https://{domain}"

    combined_text = ""
    combined_html = ""
    for path in ENRICH_PATHS:
        url = urljoin(origin, path)
        html = fetch_page(url)
        if not html:
            continue
        combined_html += " " + html.lower()
        combined_text += " " + strip_html(html)
        time.sleep(delay_seconds)

    if not combined_text:
        return {"email": "", "phone": "", "signals": ""}

    signals = detect_signals(combined_html + " " + combined_text, origin)
    return {
        "email": extract_email(combined_text),
        "phone": extract_phone(combined_text),
        "signals": "|".join(sorted(set(signals))),
    }


def result_from_item(item: dict, query: str, now: str) -> SearchResult | None:
    url = item.get("link") or item.get("url") or ""
    domain = normalize_domain(url)
    if is_blocked_domain(domain):
        return None

    raw_title = item.get("title", "")
    raw_snippet = item.get("snippet") or item.get("description") or ""
    extra_snippets = item.get("extra_snippets") or []
    if isinstance(extra_snippets, list):
        raw_snippet = " ".join([raw_snippet, *extra_snippets])
    title = clean_text(strip_html(raw_title))
    snippet = clean_text(strip_html(raw_snippet))
    profile = item.get("profile") if isinstance(item.get("profile"), dict) else {}
    company_name = clean_text(profile.get("name", "")) or title
    text = f"{title} {snippet}"
    if looks_like_non_shop(text, url):
        return None
    email = extract_email(text)
    phone = extract_phone(text)
    signals = detect_signals(text, url)

    return SearchResult(
        domain=domain,
        url=url,
        company_name=company_name,
        email=email,
        phone=phone,
        title=title,
        snippet=snippet,
        country_hint=country_hint_for(domain),
        lead_score=score_lead(signals, email, phone),
        signals="|".join(sorted(set(signals))),
        source_query=query,
        status="new",
        notes="",
        found_at=now,
        last_seen_at=now,
    )


def search_queries(
    provider: str,
    api_key: str,
    search_engine_id: str,
    queries: list[str],
    budget_calls: int,
    pages_per_query: int,
    delay_seconds: float,
    policy: dict | None = None,
    crawler_state=None,
) -> tuple[list[SearchResult], int]:
    seen_domains: set[str] = set()
    results: list[SearchResult] = []
    api_calls = 0
    now = utc_now()

    policy = policy or {}
    brave_daily_limit = int(policy.get("brave_daily_limit") or budget_calls)
    stop_on_low_remaining = bool(policy.get("stop_on_low_brave_remaining", True))
    low_remaining_threshold = int(policy.get("brave_low_remaining_threshold") or 1)

    for index, query in enumerate(queries, start=1):
        if api_calls >= budget_calls:
            break

        print(f"[{index}/{len(queries)}] {query}")
        query_new = 0
        for page in range(pages_per_query):
            if api_calls >= budget_calls:
                break

            if provider == "brave":
                if crawler_state and crawler_state.remaining("brave_search", brave_daily_limit) <= 0:
                    print("Brave daily policy limit reached. Stopping search step.")
                    return results, api_calls
                response = brave_search(api_key, query, offset=page)
                remaining_header = (
                    response.headers.get("X-RateLimit-Remaining")
                    or response.headers.get("x-ratelimit-remaining")
                    or ""
                )
                reset_header = (
                    response.headers.get("X-RateLimit-Reset")
                    or response.headers.get("x-ratelimit-reset")
                    or ""
                )
                if crawler_state:
                    crawler_state.increment_counter("brave_search", 1)
                    crawler_state.record_brave_rate_limit(
                        remaining=remaining_header,
                        reset_seconds=reset_header,
                        status_code=response.status_code,
                        query=query,
                    )
                data = response.data
                items = (data.get("web") or {}).get("results", []) if data else []
            else:
                start_index = 1 + page * 10
                response = google_search(api_key, search_engine_id, query, start_index)
                data = response.data
                items = data.get("items", []) if data else []
            api_calls += 1

            if response.should_stop:
                print("Search provider requested stop/backoff. Stopping search step.")
                return results, api_calls

            if (
                provider == "brave"
                and stop_on_low_remaining
                and remaining_header.isdigit()
                and int(remaining_header) <= low_remaining_threshold
            ):
                print("Brave rate-limit remaining is low. Stopping search step.")
                return results, api_calls

            if not items:
                break

            for item in items:
                result = result_from_item(item, query, now)
                if not result or result.domain in seen_domains:
                    continue
                seen_domains.add(result.domain)
                results.append(result)
                query_new += 1

            time.sleep(delay_seconds)

        print(f"  found {query_new} unique domains in this run")

    return results, api_calls


def load_master(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}

    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        rows = {}
        for row in reader:
            domain = normalize_domain(row.get("domain", ""))
            if domain:
                row["domain"] = domain
                rows[domain] = {field: row.get(field, "") for field in MASTER_FIELDS}
        return rows


def merge_signals(*values: str) -> str:
    signals = set()
    for value in values:
        signals.update(part for part in (value or "").split("|") if part)
    return "|".join(sorted(signals))


def merge_into_master(
    master: dict[str, dict[str, str]],
    results: list[SearchResult],
    run_id_value: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    run_rows: list[dict[str, str]] = []
    new_rows: list[dict[str, str]] = []

    for result in results:
        row = {field: getattr(result, field) for field in MASTER_FIELDS}
        is_new = result.domain not in master

        if is_new:
            master[result.domain] = row
            new_rows.append(row.copy())
        else:
            existing = master[result.domain]
            existing["last_seen_at"] = result.last_seen_at
            existing["url"] = existing.get("url") or result.url
            existing["company_name"] = existing.get("company_name") or result.company_name
            existing["email"] = existing.get("email") or result.email
            existing["phone"] = existing.get("phone") or result.phone
            existing["title"] = existing.get("title") or result.title
            existing["snippet"] = existing.get("snippet") or result.snippet
            existing["country_hint"] = existing.get("country_hint") or result.country_hint
            existing["source_query"] = existing.get("source_query") or result.source_query
            existing["signals"] = merge_signals(existing.get("signals", ""), result.signals)
            existing["lead_score"] = str(
                max(int(existing.get("lead_score") or 0), int(result.lead_score or 0))
            )
            row = existing.copy()

        run_row = row.copy()
        run_row["is_new"] = "yes" if is_new else "no"
        run_row["run_id"] = run_id_value
        run_rows.append(run_row)

    return run_rows, new_rows


def enrich_results(
    results: list[SearchResult],
    delay_seconds: float,
    min_score: int,
    limit: int,
) -> None:
    candidates = [result for result in results if int(result.lead_score or 0) >= min_score]
    if limit > 0:
        candidates = candidates[:limit]

    for index, result in enumerate(candidates, start=1):
        print(f"Enrich [{index}/{len(candidates)}] {result.domain}")
        enriched = enrich_from_site(result.domain, result.url, delay_seconds)
        email = enriched.get("email", "")
        phone = enriched.get("phone", "")
        signals = enriched.get("signals", "")

        if email and not result.email:
            result.email = email
        if phone and not result.phone:
            result.phone = phone
        result.signals = merge_signals(result.signals, signals)
        result.lead_score = score_lead(result.signals.split("|"), result.email, result.phone)


def write_csv(path: Path, rows: Iterable[dict[str, str]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fields})


def append_instantly(path: Path, new_rows: list[dict[str, str]]) -> int:
    leads = [row for row in new_rows if row.get("email")]
    if not leads:
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=INSTANTLY_FIELDS)
        writer.writeheader()
        for row in leads:
            writer.writerow(
                {
                    "Email": row.get("email", ""),
                    "First Name": "",
                    "Last Name": "",
                    "Company": row.get("company_name", ""),
                    "Website": row.get("domain", ""),
                }
            )
    return len(leads)


def qualified_rows(rows: list[dict[str, str]], min_score: int) -> list[dict[str, str]]:
    qualified = []
    for row in rows:
        domain = normalize_domain(row.get("domain", ""))
        if is_blocked_domain(domain):
            continue
        text = " ".join(
            [
                row.get("company_name", ""),
                row.get("title", ""),
                row.get("snippet", ""),
            ]
        )
        if looks_like_non_shop(text, row.get("url", "") or domain):
            continue

        try:
            score = int(row.get("lead_score") or 0)
        except ValueError:
            score = 0
        signals = set((row.get("signals") or "").split("|"))
        has_shop_signal = bool({"active_shop", "cart_checkout", "woocommerce"} & signals)
        if score >= min_score and has_shop_signal:
            qualified.append(row)
    return qualified


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find and dedupe WooCommerce leads.")
    parser.add_argument(
        "--provider",
        choices=["auto", "brave", "google"],
        default=DEFAULT_PROVIDER,
        help="Search provider. Use brave for new setups; google only works for legacy CSE customers.",
    )
    parser.add_argument("--budget-calls", type=int, default=DEFAULT_BUDGET_CALLS)
    parser.add_argument("--pages-per-query", type=int, default=DEFAULT_PAGES_PER_QUERY)
    parser.add_argument("--query-limit", type=int, default=None)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--policy", type=Path, default=Path("crawler_policy.json"))
    parser.add_argument("--state-db", type=Path, default=None)
    parser.add_argument("--qualified-min-score", type=int, default=DEFAULT_QUALIFIED_MIN_SCORE)
    parser.add_argument("--enrich", action="store_true", help="Fetch public site pages for email/phone/signals.")
    parser.add_argument("--enrich-min-score", type=int, default=30)
    parser.add_argument("--enrich-limit", type=int, default=40, help="Maximum candidates to enrich; use 0 for no limit.")
    parser.add_argument("--rebuild-qualified", action="store_true", help="Rebuild qualified_master.csv from the existing master without search calls.")
    parser.add_argument("--create-instantly", action="store_true", help="Create an early Instantly CSV from qualified rows with email. Off by default.")
    parser.add_argument("--dry-run", action="store_true", help="Build query slice without calling a search provider.")
    parser.add_argument("--show-queries", action="store_true", help="Print the selected query slice.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    policy = load_policy(args.policy)
    crawler_state = build_state(policy, args.state_db)

    brave_api_key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    google_api_key = os.environ.get("GOOGLE_CSE_API_KEY", "").strip()
    search_engine_id = os.environ.get("GOOGLE_CSE_ID", DEFAULT_SEARCH_ENGINE_ID).strip()
    provider = args.provider
    if provider == "auto":
        provider = "brave" if brave_api_key else "google"
    api_key = brave_api_key if provider == "brave" else google_api_key

    output_dir = args.output_dir
    master_path = output_dir / "leads_master.csv"
    state_path = output_dir / "search_state.json"
    this_run_id = run_id()
    run_path = output_dir / "runs" / f"run_{this_run_id}.csv"
    new_path = output_dir / "new" / f"new_leads_{this_run_id}.csv"
    qualified_path = output_dir / "qualified" / f"qualified_leads_{this_run_id}.csv"
    qualified_master_path = output_dir / "qualified_master.csv"
    instantly_path = output_dir / "instantly" / f"instantly_import_{this_run_id}.csv"

    if args.rebuild_qualified:
        master = load_master(master_path)
        qualified_master_rows = qualified_rows(list(master.values()), max(0, args.qualified_min_score))
        write_csv(qualified_master_path, qualified_master_rows, MASTER_FIELDS)
        print("Rebuilt qualified master without search calls.")
        print(f"Master rows: {len(master)}")
        print(f"Qualified master rows: {len(qualified_master_rows)}")
        print(f"Qualified master CSV: {qualified_master_path}")
        return 0

    queries = build_queries(provider)
    state = load_state(state_path)
    selected_queries = select_daily_queries(
        queries=queries,
        state=state,
        budget_calls=max(1, args.budget_calls),
        pages_per_query=max(1, args.pages_per_query),
        query_limit=args.query_limit,
    )

    print("WooCommerce Lead Finder - VHD Erfolg2 Coaching")
    print(f"Provider: {provider}")
    print(f"Total query bank: {len(queries)}")
    print(f"Selected queries: {len(selected_queries)}")
    print(f"Budget: {args.budget_calls} search calls")
    if provider == "brave":
        brave_limit = int(policy.get("brave_daily_limit") or args.budget_calls)
        print(f"Brave policy remaining today: {crawler_state.remaining('brave_search', brave_limit)} / {brave_limit}")
    print(f"Output: {output_dir}")

    if args.show_queries:
        print("\nSelected query slice:")
        for query in selected_queries:
            print(f"- {query}")

    if args.dry_run:
        print("\nDry run only. No API calls made and search cursor not advanced.")
        return 0

    if not api_key:
        if provider == "brave":
            print("\nMissing BRAVE_SEARCH_API_KEY. Create a Brave Search API key and add it to .env.")
        else:
            print("\nMissing GOOGLE_CSE_API_KEY. Google CSE now only works for legacy customers.")
        return 2

    results, api_calls = search_queries(
        provider=provider,
        api_key=api_key,
        search_engine_id=search_engine_id,
        queries=selected_queries,
        budget_calls=max(1, args.budget_calls),
        pages_per_query=max(1, args.pages_per_query),
        delay_seconds=max(0.0, args.delay),
        policy=policy,
        crawler_state=crawler_state,
    )

    if args.enrich and results:
        enrich_results(
            results,
            delay_seconds=max(0.0, args.delay),
            min_score=max(0, args.enrich_min_score),
            limit=max(0, args.enrich_limit),
        )

    master = load_master(master_path)
    run_rows, new_rows = merge_into_master(master, results, this_run_id)

    write_csv(master_path, master.values(), MASTER_FIELDS)
    write_csv(run_path, run_rows, RUN_FIELDS)
    write_csv(new_path, new_rows, MASTER_FIELDS)
    qualified_new_rows = qualified_rows(new_rows, max(0, args.qualified_min_score))
    qualified_master_rows = qualified_rows(list(master.values()), max(0, args.qualified_min_score))
    write_csv(qualified_path, qualified_new_rows, MASTER_FIELDS)
    write_csv(qualified_master_path, qualified_master_rows, MASTER_FIELDS)
    instantly_count = 0
    if args.create_instantly:
        instantly_count = append_instantly(instantly_path, qualified_new_rows)
    if results:
        save_state(state_path, state)
    else:
        print("No domains found. Search cursor was not advanced.")

    with_email = sum(1 for row in new_rows if row.get("email"))
    print("\nDone")
    print(f"Search calls used: {api_calls}")
    print(f"Domains found in run: {len(run_rows)}")
    print(f"New domains added: {len(new_rows)}")
    print(f"Qualified new domains: {len(qualified_new_rows)}")
    print(f"New rows with email: {with_email}")
    print(f"Master CSV: {master_path}")
    print(f"Qualified master CSV: {qualified_master_path}")
    print(f"Run CSV: {run_path}")
    print(f"New leads CSV: {new_path}")
    print(f"Qualified CSV: {qualified_path}")
    if args.create_instantly and instantly_count:
        print(f"Instantly CSV: {instantly_path} ({instantly_count} rows)")
    elif args.create_instantly:
        print("Instantly CSV skipped because no qualified rows had email.")
    else:
        print("Instantly export disabled. Use verified/enriched decision-maker data before Instantly.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
