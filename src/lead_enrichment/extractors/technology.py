from __future__ import annotations

from ..normalizer import split_tokens, truthy


def detect_woocommerce(row: dict[str, str], html: str = "") -> bool:
    text = " ".join(split_tokens(row.get("woocommerce_signals")) + split_tokens(row.get("verified_signals")))
    return truthy(row.get("is_woocommerce")) or "woocommerce" in text or "wp-content/plugins/woocommerce" in html.lower()


def detect_wordpress(row: dict[str, str], html: str = "") -> bool:
    text = " ".join(split_tokens(row.get("verified_signals")) + split_tokens(row.get("signals")))
    return "wordpress" in text or "wp-content" in html.lower()
