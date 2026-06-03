from __future__ import annotations


def mutmassliche_einwilligung_reason(
    priority: str,
    outreach_angle: str,
    channel: str,
    is_woocommerce: bool,
) -> str:
    if priority not in {"A", "B"}:
        return ""
    shop_context = "WooCommerce shop" if is_woocommerce else "verified shop"
    return (
        f"{shop_context} with documented shop optimization lever: {outreach_angle} "
        "VHD offers technical WooCommerce growth optimization; business-specific relevance exists; "
        f"first contact channel recommended: {channel}."
    )
