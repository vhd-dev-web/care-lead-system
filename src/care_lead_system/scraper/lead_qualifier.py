#!/usr/bin/env python3
"""
Domain qualifier for VHD Erfolg2 Coaching lead lists.

This script consumes output/leads_master.csv, visits public pages on each
domain, detects shop/WooCommerce signals, classifies non-shop providers, and
surfaces first possible shop levers for manual review or Loom prioritization.

No search API calls are used.
"""

from __future__ import annotations

import argparse
import csv
import http.client
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .crawler_support import (
    build_state,
    load_policy,
    policy_sleep,
    robots_allowed,
)


DEFAULT_INPUT = Path("output/leads_master.csv")
DEFAULT_OUTPUT_DIR = Path("output/domain_verification")
DEFAULT_TIMEOUT = 5
DEFAULT_WORKERS = 8
# Realistic browser UA. Many German care-aid provider sites
# (sanubi.de, pflegebox.de, etc.) return HTTP 403 to obvious bot
# user-agents, which would silently drop real leads from the verifier.
# We still respect robots.txt and rate limits.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Header set sent with every fetch. UA alone is not enough — some bot
# detectors flag requests that send Chrome's UA but skip the headers a
# real Chrome always sends. Accept-Encoding is deliberately omitted
# because urllib does not decompress responses transparently.
BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

CHECK_PATHS = [
    "/",
    "/impressum",
    "/kontakt",
    "/shop",
    "/warenkorb",
    "/kasse",
]

LIGHT_CHECK_PATHS = ["/"]
DEEP_CHECK_PATHS = CHECK_PATHS

OUT_FIELDS = [
    "domain",
    "source_url",
    "company_name",
    "scoring_mode",
    "lead_type",
    "is_shop",
    "is_woocommerce",
    "detected_platform",
    "detected_platform_signals",
    "is_dach",
    "vhd_fit_score",
    "next_action",
    "exclusion_reason",
    "email",
    "phone",
    "reachable_pages",
    "checked_pages",
    "best_status",
    "avg_response_ms",
    "total_html_kb",
    "http_request_count",
    "robots_status",
    "skipped_by_robots",
    "policy_skip_reason",
    "verified_signals",
    "shop_signals",
    "woocommerce_signals",
    "tracking_signals",
    "legal_trust_signals",
    "possible_shop_levers",
    "input_lead_score",
    "input_signals",
    "checked_at",
]

BLOCKED_DOMAIN_PARTS = [
    "amazon.",
    "chip.",
    "ebay.",
    "etsy.",
    "facebook.",
    "github.",
    "google.",
    "heise.",
    "hosteurope.",
    "instagram.",
    "ionos.",
    "linkedin.",
    "linguee.",
    "mailchimp.",
    "omr.",
    "pinterest.",
    "rtl.",
    "shopify.",
    "shopware.com",
    "strato.",
    "tiktok.",
    "trustedshops.",
    "woocommerce.com",
    "wordpress.org",
    "youtube.",
    "zendesk.",
]

AGENCY_TERMS = [
    "agentur",
    "agency",
    "beratung",
    "consulting",
    "digitalagentur",
    "e-commerce agentur",
    "ecommerce agentur",
    "marketingagentur",
    "seo agentur",
    "webagentur",
    "webdesign",
    "wordpress agentur",
    "woocommerce agentur",
]

FULFILLMENT_TERMS = [
    "3pl",
    "fulfillment",
    "fulfilment",
    "lagerlogistik",
    "logistik",
    "shipping provider",
    "versanddienstleister",
    "warenlager",
]

PAYMENT_TERMS = [
    "checkout provider",
    "payment",
    "payment provider",
    "payment service",
    "psp",
    "zahlungsanbieter",
    "zahlungsmethoden",
    "zahlungsdienstleister",
]

PUBLISHER_TERMS = [
    "guide",
    "leitfaden",
    "magazin",
    "praxistipp",
    "ratgeber",
    "tutorial",
    "verlag",
    "wiki",
]

PLATFORM_TERMS = [
    "hosting",
    "hoster",
    "plugin",
    "plugins",
    "saas",
    "shopsoftware",
    "shopsystem",
    "software",
    "template",
    "templates",
    "theme",
    "themes",
    "generator",
    "rechtstexte",
]

SHOP_TERMS = [
    "add-to-cart",
    "cart",
    "checkout",
    "in den warenkorb",
    "kasse",
    "mein konto",
    "produkt",
    "produkte",
    "shop",
    "warenkorb",
    "zur kasse",
]

STRONG_COMMERCE_MARKERS = [
    "add-to-cart",
    "cart-empty",
    "in den warenkorb",
    "single_add_to_cart_button",
    "wc-cart",
    "woocommerce-cart",
    "woocommerce-checkout",
    "zur kasse",
]

WOOCOMMERCE_MARKERS = [
    "add-to-cart",
    "single_add_to_cart_button",
    "wc-ajax",
    "wc-cart",
    "wc-block",
    "woocommerce",
    "woocommerce-js",
    "woocommerce-product-gallery",
    "wp-content/plugins/woocommerce",
]

SHOPIFY_MARKERS = [
    "cdn.shopify.com",
    "myshopify.com",
    "shopify-section",
    "shopify-payment-button",
    "shopify.theme",
    "window.shopify",
    "/cdn/shop/files/",
    "data-shopify",
    "shopify-features",
    "shopifycdn.com",
    "shopify_pay",
]

SHOPWARE_MARKERS = [
    "shopware6",
    "/storefront/script/",
    "sw-collapse",
    "sw-product-",
    "sw-page-",
    "window.shopware",
    "var shopware",
    "/themes/storefront/",
]

MAGENTO_MARKERS = [
    "mage-init",
    "mage/cookies",
    "magento_persistent",
    "/static/version",
    "magento-",
    "mage.cookies",
    "var mage =",
    "data-mage-init",
]

JTL_MARKERS = [
    "jtl-shop",
    "jtl_token",
    "/themes/nova/",
    "/themes/evo/",
    "data-jtl-",
    "jtl-vue",
]

GAMBIO_MARKERS = [
    "gx_modules",
    "xt:commerce",
    "gambio-cart",
    "gm_modules",
    "/templates/gambio/",
]

PRESTASHOP_MARKERS = [
    "prestashop",
    "/themes/classic/",
    "var prestashop",
    "data-prestashop",
    "ps_imageslider",
]

# Order matters: WooCommerce is checked first because it is the only
# in-scope target platform. Other platforms get tagged for the master so
# we can revisit them when the agency scope expands.
PLATFORM_MARKERS: list[tuple[str, list[str]]] = [
    ("woocommerce", WOOCOMMERCE_MARKERS),
    ("shopify", SHOPIFY_MARKERS),
    ("shopware", SHOPWARE_MARKERS),
    ("magento", MAGENTO_MARKERS),
    ("jtl", JTL_MARKERS),
    ("gambio", GAMBIO_MARKERS),
    ("prestashop", PRESTASHOP_MARKERS),
]

TARGET_PLATFORM = "woocommerce"

PRODUCT_MARKERS = [
    '"@type":"product"',
    '"@type": "product"',
    "itemtype=\"https://schema.org/product\"",
    "itemtype=\"http://schema.org/product\"",
    "product_meta",
    "schema.org/product",
    "sku",
]

SHIPPING_PAYMENT_MARKERS = [
    "apple pay",
    "klarna",
    "kreditkarte",
    "lastschrift",
    "paypal",
    "rechnung",
    "sofort",
    "stripe",
    "versand",
    "versandkosten",
    "vorkasse",
    "zahlungsarten",
]

TRACKING_MARKERS = {
    "ga4": ["gtag(", "g-", "google-analytics.com", "googletagmanager.com/gtag/js"],
    "gtm": ["gtm-", "googletagmanager.com/gtm.js"],
    "meta_pixel": ["connect.facebook.net", "fbq("],
    "microsoft_clarity": ["clarity.ms", "clarity("],
    "hotjar": ["hotjar", "hjid"],
    "klaviyo": ["klaviyo"],
    "brevo": ["brevo", "sendinblue"],
    "mailchimp": ["mailchimp"],
}

LEGAL_TRUST_MARKERS = [
    "agb",
    "datenschutz",
    "impressum",
    "retoure",
    "rueckgabe",
    "trusted shops",
    "trustpilot",
    "widerruf",
]


@dataclass
class FetchResult:
    path: str
    url: str
    status: int
    elapsed_ms: int
    html: str
    error: str = ""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_domain(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    parsed = urllib.parse.urlparse(value)
    domain = parsed.netloc.lower().split("@")[-1].split(":")[0]
    if domain.startswith("www."):
        domain = domain[4:]
    return domain.rstrip(".")


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def strip_html(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return clean_text(text)


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


def load_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Input CSV not found: {path}")
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter=";"))


def write_csv(path: Path, rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUT_FIELDS, delimiter=";")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in OUT_FIELDS})


def contains_any(haystack: str, needles: Iterable[str]) -> bool:
    return any(needle in haystack for needle in needles)


def matching_terms(haystack: str, needles: Iterable[str]) -> list[str]:
    return sorted({needle for needle in needles if needle in haystack})


def blocked_domain_reason(domain: str) -> str:
    if domain.startswith(("demo.", "dev.", "staging.", "test.")):
        return "technical_demo_subdomain"
    for part in BLOCKED_DOMAIN_PARTS:
        if part in domain:
            return f"blocked_domain:{part.strip('.')}"
    return ""


def candidate_urls(domain: str, source_url: str = "", mode: str = "deep") -> list[tuple[str, str]]:
    urls: list[tuple[str, str]] = []
    source_domain = normalize_domain(source_url)
    if source_url and source_domain == domain:
        parsed = urllib.parse.urlparse(source_url)
        if parsed.path and parsed.path != "/":
            urls.append((parsed.path, source_url))
    paths = LIGHT_CHECK_PATHS if mode == "light" else DEEP_CHECK_PATHS
    for path in paths:
        urls.append((path, f"https://{domain}{path}"))
    seen = set()
    unique = []
    for path, url in urls:
        if url not in seen:
            seen.add(url)
            unique.append((path, url))
    return unique


def fetch_url(path: str, url: str, timeout: int, user_agent: str) -> FetchResult:
    headers = {"User-Agent": user_agent, **BROWSER_HEADERS}
    request = urllib.request.Request(url, headers=headers)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            content_type = response.headers.get("content-type", "")
            charset = response.headers.get_content_charset() or "utf-8"
            if "text/html" not in content_type:
                return FetchResult(path, response.geturl(), response.status, elapsed_ms, "")
            html = response.read(500_000).decode(charset, errors="replace")
            return FetchResult(path, response.geturl(), response.status, elapsed_ms, html)
    except urllib.error.HTTPError as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return FetchResult(path, url, exc.code, elapsed_ms, "", f"http_{exc.code}")
    except (
        urllib.error.URLError,
        TimeoutError,
        ValueError,
        ConnectionError,
        http.client.RemoteDisconnected,
        ssl.SSLError,
    ) as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return FetchResult(path, url, 0, elapsed_ms, "", exc.__class__.__name__)


def fetch_domain_pages(
    domain: str,
    source_url: str,
    timeout: int,
    mode: str,
    policy: dict,
    crawler_state=None,
    no_sleep: bool = False,
) -> tuple[list[FetchResult], str, str]:
    urls = candidate_urls(domain, source_url, mode)
    results: list[FetchResult] = []
    robots_statuses = []
    skipped_by_robots = []
    user_agent = str(policy.get("bot_user_agent") or USER_AGENT)
    for path, url in urls:
        allowed, robots_status = robots_allowed(domain, url, user_agent, policy, crawler_state)
        robots_statuses.append(f"{path}:{robots_status}")
        if not allowed:
            skipped_by_robots.append(path)
            continue
        results.append(fetch_url(path, url, timeout, user_agent))
        policy_sleep(policy, "page_delay_seconds_min", "page_delay_seconds_max", disabled=no_sleep)
        if results[-1].status in set(policy.get("stop_status_codes", [403, 429, 503])):
            break
    if not any(fetch.path == "/" and fetch.html for fetch in results):
        url = f"http://{domain}/"
        allowed, robots_status = robots_allowed(domain, url, user_agent, policy, crawler_state)
        robots_statuses.append(f"http:/:{robots_status}")
        if allowed:
            results.append(fetch_url("http:/", url, timeout, user_agent))
        else:
            skipped_by_robots.append("http:/")
    return results, "|".join(robots_statuses), "|".join(skipped_by_robots)


def detect_platform(html: str) -> tuple[str, list[str]]:
    """Detect the e-commerce platform a shop runs on.

    Returns the first matching platform name plus the list of markers
    that triggered the match. WooCommerce is checked before alternatives
    so a hybrid setup (rare) still counts as in-target.
    """
    haystack = (html or "").lower()
    for name, markers in PLATFORM_MARKERS:
        matched = [marker for marker in markers if marker.lower() in haystack]
        if matched:
            return name, matched
    return "", []


def classify_lead(
    domain: str,
    text: str,
    html: str,
    is_shop: bool,
    confirmed_woocommerce_shop: bool,
    detected_platform: str = "",
) -> tuple[str, str]:
    if detected_platform and detected_platform != TARGET_PLATFORM:
        return "non_target_platform", f"platform_{detected_platform}"
    domain_reason = blocked_domain_reason(domain)
    if domain_reason:
        return "rejected", domain_reason

    if confirmed_woocommerce_shop:
        return "shop", ""

    identity_area = (domain + " " + text[:2500]).lower()
    if contains_any(identity_area, AGENCY_TERMS):
        return ("review", "shop_or_agency_mixed") if is_shop else ("agency", "service_provider_agency")
    if contains_any(identity_area, FULFILLMENT_TERMS):
        return ("review", "shop_or_fulfillment_mixed") if is_shop else ("fulfillment_provider", "service_provider_fulfillment")
    if contains_any(identity_area, PAYMENT_TERMS):
        return ("review", "shop_or_payment_mixed") if is_shop else ("payment_provider", "service_provider_payment")
    if contains_any(identity_area, PLATFORM_TERMS):
        return ("review", "shop_or_platform_mixed") if is_shop else ("platform_provider", "service_provider_platform")
    if contains_any(identity_area, PUBLISHER_TERMS):
        return ("review", "shop_or_publisher_mixed") if is_shop else ("publisher", "publisher_or_content_site")
    if is_shop:
        return "shop", ""
    return "unknown", "not_enough_shop_signals"


def detect_tracking(html: str) -> list[str]:
    found = []
    for name, needles in TRACKING_MARKERS.items():
        if any(needle in html for needle in needles):
            found.append(name)
    return sorted(found)


def possible_levers(
    is_shop: bool,
    is_woocommerce: bool,
    product_schema: bool,
    tracking: list[str],
    shipping_payment: bool,
    legal_trust: bool,
    avg_response_ms: int,
    total_html_kb: int,
) -> list[str]:
    if not is_shop:
        return []

    levers = []
    if is_woocommerce:
        levers.append("woocommerce_growth_system")
    else:
        levers.append("platform_check_needed")
    if not tracking:
        levers.append("tracking_gap_possible")
    else:
        levers.append("tracking_stack_visible")
        tracking_set = set(tracking)
        if "gtm" in tracking_set and "microsoft_clarity" not in tracking_set:
            levers.append("tracking_check")
            levers.append("clarity_heatmap_opportunity")
        if "ga4" in tracking_set and "gtm" not in tracking_set:
            levers.append("tracking_check")
            levers.append("gtm_setup_check")
        if {"klaviyo", "mailchimp"} & tracking_set:
            levers.append("advanced_email_marketing_stack")
            levers.append("reputation_first_approach")
    if not product_schema:
        levers.append("product_data_schema_check")
    if shipping_payment:
        levers.append("checkout_payment_shipping_review")
    else:
        levers.append("checkout_shipping_info_check")
    if not legal_trust:
        levers.append("trust_legal_surface_check")
    if avg_response_ms >= 1200 or total_html_kb >= 900:
        levers.append("performance_check")
    levers.append("conversion_path_review")
    return list(dict.fromkeys(levers))


def score_fit(
    lead_type: str,
    is_shop: bool,
    is_woocommerce: bool,
    is_dach: bool,
    email: str,
    phone: str,
    product_schema: bool,
    shipping_payment: bool,
    tracking: list[str],
    legal_trust: bool,
    avg_response_ms: int,
) -> int:
    score = 0
    if is_shop:
        score += 30
    if is_woocommerce:
        score += 25
    if is_dach:
        score += 10
    if email:
        score += 8
    if phone:
        score += 5
    if product_schema:
        score += 8
    if shipping_payment:
        score += 7
    if tracking:
        score += 5
    if legal_trust:
        score += 4
    if avg_response_ms >= 1200:
        score += 3

    if lead_type not in {"shop", "review"}:
        score = min(score, 25)
    if lead_type == "review":
        score = min(score, 55)
    return min(score, 100)


def next_action(lead_type: str, score: int, is_woocommerce: bool) -> str:
    if lead_type != "shop":
        return "reject" if lead_type not in {"review", "unknown"} else "manual_review"
    if score >= 70:
        return "loom_candidate"
    if score >= 50:
        return "manual_review_high"
    if is_woocommerce:
        return "manual_review_woocommerce"
    return "manual_review_low"


def qualify_row(
    row: dict[str, str],
    timeout: int,
    mode: str,
    policy: dict,
    crawler_state=None,
    force: bool = False,
    no_sleep: bool = False,
) -> dict[str, str]:
    domain = normalize_domain(row.get("domain") or row.get("url") or "")
    checked_at = utc_now()
    source_url = row.get("url") or row.get("source_url", "")
    input_lead_score = row.get("lead_score") or row.get("input_lead_score", "")
    input_signals = row.get("signals") or row.get("input_signals", "")
    if not domain:
        return {
            "domain": "",
            "source_url": source_url,
            "scoring_mode": mode,
            "lead_type": "rejected",
            "is_shop": "no",
            "is_woocommerce": "no",
            "exclusion_reason": "missing_domain",
            "policy_skip_reason": "missing_domain",
            "checked_at": checked_at,
        }
    if (
        crawler_state
        and not force
        and crawler_state.checked_within_cooldown(
            domain,
            mode,
            int(policy.get("domain_cooldown_days") or 14),
        )
    ):
        return {
            "domain": domain,
            "source_url": source_url,
            "company_name": row.get("company_name", ""),
            "scoring_mode": mode,
            "lead_type": "skipped",
            "is_shop": "no",
            "is_woocommerce": "no",
            "is_dach": "yes" if domain.endswith((".de", ".at", ".ch")) else "no",
            "vhd_fit_score": "0",
            "next_action": "skip",
            "exclusion_reason": "domain_cooldown",
            "policy_skip_reason": "domain_cooldown",
            "input_lead_score": input_lead_score,
            "input_signals": input_signals,
            "checked_at": checked_at,
        }

    domain_reason = blocked_domain_reason(domain)
    if domain_reason:
        if crawler_state:
            crawler_state.record_domain_check(domain, mode, "rejected", 0, domain_reason, 0)
        return {
            "domain": domain,
            "source_url": source_url,
            "company_name": row.get("company_name", ""),
            "scoring_mode": mode,
            "lead_type": "rejected",
            "is_shop": "no",
            "is_woocommerce": "no",
            "is_dach": "yes" if domain.endswith((".de", ".at", ".ch")) else "no",
            "vhd_fit_score": "0",
            "next_action": "reject",
            "exclusion_reason": domain_reason,
            "policy_skip_reason": domain_reason,
            "input_lead_score": input_lead_score,
            "input_signals": input_signals,
            "checked_at": checked_at,
        }

    fetches, robots_status, skipped_by_robots = fetch_domain_pages(
        domain,
        source_url,
        timeout,
        mode,
        policy,
        crawler_state,
        no_sleep=no_sleep,
    )
    html_pages = [fetch.html for fetch in fetches if fetch.html]
    html = "\n".join(html_pages).lower()
    text = strip_html("\n".join(html_pages)).lower()
    reachable = [fetch for fetch in fetches if fetch.html and 200 <= fetch.status < 400]
    checked_pages = [f"{fetch.path}:{fetch.status}" for fetch in fetches]
    response_times = [fetch.elapsed_ms for fetch in fetches if fetch.status]
    avg_response_ms = int(sum(response_times) / len(response_times)) if response_times else 0
    total_html_kb = int(sum(len(page.encode("utf-8", errors="ignore")) for page in html_pages) / 1024)
    best_status = min((fetch.status for fetch in fetches if fetch.status), default=0)
    request_count = len(fetches)
    stop_statuses = set(int(code) for code in policy.get("stop_status_codes", [403, 429, 503]))
    stop_errors = [str(fetch.status) for fetch in fetches if fetch.status in stop_statuses]

    shop_terms = matching_terms(text + " " + html, SHOP_TERMS)
    woocommerce_terms = matching_terms(html, WOOCOMMERCE_MARKERS)
    product_terms = matching_terms(html, PRODUCT_MARKERS)
    shipping_payment_terms = matching_terms(text, SHIPPING_PAYMENT_MARKERS)
    legal_terms = matching_terms(text, LEGAL_TRUST_MARKERS)
    tracking_terms = detect_tracking(html)
    strong_commerce_terms = matching_terms(text + " " + html, STRONG_COMMERCE_MARKERS)
    cart_paths = {"/warenkorb", "/kasse", "/checkout", "/cart"}
    reachable_cart_paths = [fetch.path for fetch in reachable if fetch.path in cart_paths]
    high_confidence_commerce_terms = {
        "add-to-cart",
        "single_add_to_cart_button",
        "wc-cart",
        "woocommerce-cart",
        "woocommerce-checkout",
    } & set(strong_commerce_terms)

    email = row.get("email", "") or extract_email(text)
    phone = row.get("phone", "") or extract_phone(text)
    country_hint = (row.get("country_hint") or "").upper()
    is_dach = country_hint in {"DE", "AT", "CH"} or domain.endswith((".de", ".at", ".ch"))
    is_woocommerce = bool(woocommerce_terms)
    is_shop = bool(reachable) and bool(
        strong_commerce_terms
        or product_terms
        or reachable_cart_paths
        or (shipping_payment_terms and legal_terms and {"warenkorb", "kasse"} & set(shop_terms))
    )
    confirmed_woocommerce_shop = bool(
        is_shop
        and is_woocommerce
        and (reachable_cart_paths or high_confidence_commerce_terms)
    )
    detected_platform, detected_platform_signals = detect_platform(html)

    lead_type, exclusion_reason = classify_lead(
        domain=domain,
        text=text,
        html=html,
        is_shop=is_shop,
        confirmed_woocommerce_shop=confirmed_woocommerce_shop,
        detected_platform=detected_platform,
    )
    score = score_fit(
        lead_type=lead_type,
        is_shop=is_shop,
        is_woocommerce=is_woocommerce,
        is_dach=is_dach,
        email=email,
        phone=phone,
        product_schema=bool(product_terms),
        shipping_payment=bool(shipping_payment_terms),
        tracking=tracking_terms,
        legal_trust=bool(legal_terms),
        avg_response_ms=avg_response_ms,
    )
    levers = possible_levers(
        is_shop=is_shop,
        is_woocommerce=is_woocommerce,
        product_schema=bool(product_terms),
        tracking=tracking_terms,
        shipping_payment=bool(shipping_payment_terms),
        legal_trust=bool(legal_terms),
        avg_response_ms=avg_response_ms,
        total_html_kb=total_html_kb,
    )

    verified_signals = []
    if is_shop:
        verified_signals.append("shop")
    if is_woocommerce:
        verified_signals.append("woocommerce")
    if is_dach:
        verified_signals.append("dach")
    if email:
        verified_signals.append("email")
    if phone:
        verified_signals.append("phone")
    shop_signal_values = sorted(set(shop_terms + strong_commerce_terms + reachable_cart_paths))
    status_value = "checked"
    error_code = ""
    if stop_errors:
        status_value = "stopped"
        error_code = "http_" + stop_errors[0]
    if crawler_state:
        crawler_state.record_domain_check(
            domain=domain,
            mode=mode,
            status=status_value,
            http_status=best_status,
            error_code=error_code,
            request_count=request_count,
        )

    return {
        "domain": domain,
        "source_url": source_url,
        "company_name": row.get("company_name", ""),
        "scoring_mode": mode,
        "lead_type": lead_type,
        "is_shop": "yes" if is_shop else "no",
        "is_woocommerce": "yes" if is_woocommerce else "no",
        "detected_platform": detected_platform,
        "detected_platform_signals": "|".join(detected_platform_signals),
        "is_dach": "yes" if is_dach else "no",
        "vhd_fit_score": str(score),
        "next_action": next_action(lead_type, score, is_woocommerce),
        "exclusion_reason": exclusion_reason,
        "email": email,
        "phone": phone,
        "reachable_pages": "|".join(fetch.path for fetch in reachable),
        "checked_pages": "|".join(checked_pages),
        "best_status": str(best_status),
        "avg_response_ms": str(avg_response_ms),
        "total_html_kb": str(total_html_kb),
        "http_request_count": str(request_count),
        "robots_status": robots_status,
        "skipped_by_robots": skipped_by_robots,
        "policy_skip_reason": "",
        "verified_signals": "|".join(verified_signals),
        "shop_signals": "|".join(shop_signal_values),
        "woocommerce_signals": "|".join(woocommerce_terms),
        "tracking_signals": "|".join(tracking_terms),
        "legal_trust_signals": "|".join(legal_terms),
        "possible_shop_levers": "|".join(levers),
        "input_lead_score": input_lead_score,
        "input_signals": input_signals,
        "checked_at": checked_at,
    }


def split_outputs(rows: list[dict[str, str]], verified_min_score: int) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    verified = []
    review = []
    rejected = []
    for row in rows:
        lead_type = row.get("lead_type", "")
        if lead_type == "skipped":
            continue
        score = int(row.get("vhd_fit_score") or 0)
        if lead_type == "shop" and score >= verified_min_score:
            verified.append(row)
        elif lead_type in {"shop", "review", "unknown"} and row.get("next_action") != "reject":
            review.append(row)
        else:
            rejected.append(row)
    return verified, review, rejected


def policy_skip_row(row: dict[str, str], mode: str, reason: str) -> dict[str, str]:
    domain = normalize_domain(row.get("domain") or row.get("url") or "")
    input_lead_score = row.get("lead_score") or row.get("input_lead_score", "")
    input_signals = row.get("signals") or row.get("input_signals", "")
    return {
        "domain": domain,
        "source_url": row.get("url") or row.get("source_url", ""),
        "company_name": row.get("company_name", ""),
        "scoring_mode": mode,
        "lead_type": "skipped",
        "is_shop": "no",
        "is_woocommerce": "no",
        "is_dach": "yes" if domain.endswith((".de", ".at", ".ch")) else "no",
        "vhd_fit_score": "0",
        "next_action": "skip",
        "exclusion_reason": reason,
        "policy_skip_reason": reason,
        "input_lead_score": input_lead_score,
        "input_signals": input_signals,
        "checked_at": utc_now(),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify shop leads from a CSV without search API calls.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--policy", type=Path, default=Path("crawler_policy.json"))
    parser.add_argument("--state-db", type=Path, default=None)
    parser.add_argument("--mode", choices=["light", "deep"], default="deep")
    parser.add_argument("--limit", type=int, default=0, help="Only process the first N rows; 0 means all.")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--verified-min-score", type=int, default=60)
    parser.add_argument("--force", action="store_true", help="Ignore per-domain cooldown.")
    parser.add_argument("--no-sleep", action="store_true", help="Disable policy sleeps for test runs.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    policy = load_policy(args.policy)
    crawler_state = build_state(policy, args.state_db)
    rows = load_rows(args.input)
    if args.offset:
        rows = rows[args.offset :]
    if args.limit:
        rows = rows[: args.limit]

    total = len(rows)
    print(f"Domain qualifier")
    print(f"Mode: {args.mode}")
    print(f"Input rows: {total}")
    print(f"Output dir: {args.output_dir}")
    if not rows:
        return 0

    counter_key = "domain_scoring_deep" if args.mode == "deep" else "domain_scoring_light"
    daily_limit = int(
        policy.get("deep_scoring_daily_limit")
        if args.mode == "deep"
        else policy.get("domain_scoring_daily_limit")
    )
    print(f"Policy remaining today: {crawler_state.remaining(counter_key, daily_limit)} / {daily_limit}")

    results: list[dict[str, str]] = []
    max_workers = max(1, min(int(args.workers), int(policy.get("max_parallel_requests") or args.workers)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for row in rows:
            domain = normalize_domain(row.get("domain") or row.get("url") or "")
            if (
                crawler_state
                and domain
                and not args.force
                and crawler_state.checked_within_cooldown(
                    domain,
                    args.mode,
                    int(policy.get("domain_cooldown_days") or 14),
                )
            ):
                results.append(policy_skip_row(row, args.mode, "domain_cooldown"))
                continue
            if crawler_state.remaining(counter_key, daily_limit) <= 0:
                results.append(policy_skip_row(row, args.mode, "daily_scoring_limit_reached"))
                continue
            crawler_state.increment_counter(counter_key, 1)
            future = executor.submit(
                qualify_row,
                row,
                max(3, args.timeout),
                args.mode,
                policy,
                crawler_state,
                args.force,
                args.no_sleep,
            )
            futures[future] = row
            policy_sleep(policy, "domain_delay_seconds_min", "domain_delay_seconds_max", disabled=args.no_sleep)

        for index, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            completed = index + (total - len(futures))
            if completed % 10 == 0 or completed == total:
                print(f"Checked {completed}/{total}")

    results.sort(key=lambda row: int(row.get("vhd_fit_score") or 0), reverse=True)
    verified, review, rejected = split_outputs(results, max(0, args.verified_min_score))

    write_csv(args.output_dir / "verification_all.csv", results)
    write_csv(args.output_dir / "verified_leads.csv", verified)
    write_csv(args.output_dir / "review_leads.csv", review)
    write_csv(args.output_dir / "rejected_leads.csv", rejected)

    print("\nDone")
    print(f"All checked: {len(results)}")
    print(f"Verified shops: {len(verified)}")
    print(f"Review leads: {len(review)}")
    print(f"Rejected: {len(rejected)}")
    print(f"Verified CSV: {args.output_dir / 'verified_leads.csv'}")
    print(f"Review CSV: {args.output_dir / 'review_leads.csv'}")
    print(f"Rejected CSV: {args.output_dir / 'rejected_leads.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
