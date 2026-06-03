"""Tests for the platform detection in the lead qualifier.

These guard the policy decision that during the first 4-6 weeks only
WooCommerce leads enter the Clay queue, while shops on other platforms
still get tagged in the master so we can revisit them later.
"""

from __future__ import annotations

import pytest

from care_lead_system.scraper.lead_qualifier import (
    PLATFORM_MARKERS,
    TARGET_PLATFORM,
    classify_lead,
    detect_platform,
)
from care_lead_system.verification_adapter import grade_from_verification_row


WOOCOMMERCE_HTML = """
<html><body>
<div class="woocommerce-product-gallery">
<form class="cart"><button class="single_add_to_cart_button">Kaufen</button></form>
<script src="/wp-content/plugins/woocommerce/assets/js/frontend/cart.js"></script>
</div></body></html>
"""

SHOPIFY_HTML = """
<html><body>
<script src="https://cdn.shopify.com/s/files/1/0123/4567/assets/theme.js"></script>
<div class="shopify-section" data-shopify="hero"></div>
<form action="/cart/add" class="shopify-payment-button"></form>
</body></html>
"""

SHOPWARE_HTML = """
<html><body>
<link rel="stylesheet" href="/storefront/script/all.js">
<div class="sw-collapse sw-product-name">Produkt</div>
<script>window.shopware = {csrf: '...'};</script>
</body></html>
"""

MAGENTO_HTML = """
<html><body>
<script type="text/x-magento-init">{"*": {"mage/cookies": {}}}</script>
<link href="/static/version1234567/frontend/Magento/luma/" />
<div data-mage-init='{"product":{}}'></div>
</body></html>
"""

JTL_HTML = """
<html><body>
<link rel="stylesheet" href="/themes/nova/Default/css/main.css" />
<div class="jtl-shop"><input name="jtl_token" value="abc" /></div>
</body></html>
"""

GAMBIO_HTML = """
<html><body>
<script src="/gx_modules/header/header.js"></script>
<div class="gambio-cart"></div>
</body></html>
"""

NEUTRAL_HTML = """
<html><body><h1>Bio Tee aus Hessen</h1>
<p>Wir liefern fairen Tee. Versandkosten ab 5 Euro. Zur Kasse.</p>
</body></html>
"""


def test_detect_platform_woocommerce() -> None:
    name, signals = detect_platform(WOOCOMMERCE_HTML)
    assert name == "woocommerce"
    assert signals  # at least one marker hit


def test_detect_platform_shopify() -> None:
    name, signals = detect_platform(SHOPIFY_HTML)
    assert name == "shopify"
    assert any("shopify" in marker for marker in signals)


def test_detect_platform_shopware() -> None:
    name, _signals = detect_platform(SHOPWARE_HTML)
    assert name == "shopware"


def test_detect_platform_magento() -> None:
    name, _signals = detect_platform(MAGENTO_HTML)
    assert name == "magento"


def test_detect_platform_jtl() -> None:
    name, _signals = detect_platform(JTL_HTML)
    assert name == "jtl"


def test_detect_platform_gambio() -> None:
    name, _signals = detect_platform(GAMBIO_HTML)
    assert name == "gambio"


def test_detect_platform_unknown_returns_empty() -> None:
    name, signals = detect_platform(NEUTRAL_HTML)
    assert name == ""
    assert signals == []


def test_detect_platform_is_case_insensitive() -> None:
    upper = SHOPIFY_HTML.upper()
    name, _ = detect_platform(upper)
    assert name == "shopify"


def test_target_platform_is_woocommerce() -> None:
    """If this flips, all downstream filters break — guard against silent edits."""
    assert TARGET_PLATFORM == "woocommerce"


def test_platform_markers_contain_all_expected_platforms() -> None:
    names = {name for name, _ in PLATFORM_MARKERS}
    assert {"woocommerce", "shopify", "shopware", "magento", "jtl", "gambio", "prestashop"} <= names


def test_classify_lead_rejects_shopify_even_when_shop_signals_present() -> None:
    """Shopify shops have cart/checkout signals — make sure they still get rejected."""
    lead_type, reason = classify_lead(
        domain="example-fashion.de",
        text="warenkorb kasse versandkosten impressum",
        html=SHOPIFY_HTML,
        is_shop=True,
        confirmed_woocommerce_shop=False,
        detected_platform="shopify",
    )
    assert lead_type == "non_target_platform"
    assert reason == "platform_shopify"


def test_classify_lead_accepts_woocommerce() -> None:
    lead_type, reason = classify_lead(
        domain="example-shop.de",
        text="warenkorb kasse versandkosten impressum",
        html=WOOCOMMERCE_HTML,
        is_shop=True,
        confirmed_woocommerce_shop=True,
        detected_platform="woocommerce",
    )
    assert lead_type == "shop"
    assert reason == ""


def test_classify_lead_without_platform_falls_back_to_heuristics() -> None:
    """If detect_platform returned nothing, behaviour must equal the pre-change path."""
    lead_type, _reason = classify_lead(
        domain="example-shop.de",
        text="warenkorb kasse versandkosten impressum",
        html="<html></html>",
        is_shop=True,
        confirmed_woocommerce_shop=False,
        detected_platform="",
    )
    # Falls through to the original heuristics: a shop without strong
    # platform signals stays a "shop" (not rejected for missing platform).
    assert lead_type == "shop"


@pytest.mark.parametrize(
    "platform",
    ["shopify", "shopware", "magento", "jtl", "gambio", "prestashop"],
)
def test_grade_from_verification_row_rejects_non_woocommerce_platforms(platform: str) -> None:
    row = {
        "vhd_fit_score": "85",
        "is_shop": "yes",
        "is_woocommerce": "no",
        "detected_platform": platform,
        "possible_shop_levers": "checkout_payment_shipping_review",
    }
    assert grade_from_verification_row(row) == "Reject"


def test_grade_from_verification_row_accepts_woocommerce_high_score() -> None:
    row = {
        "vhd_fit_score": "85",
        "is_shop": "yes",
        "is_woocommerce": "yes",
        "detected_platform": "woocommerce",
        "possible_shop_levers": "checkout_payment_shipping_review",
    }
    assert grade_from_verification_row(row) == "A++"
