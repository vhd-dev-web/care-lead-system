from __future__ import annotations

from .normalizer import clamp_score, parse_score, split_tokens, truthy


TECHNICAL_LEVERS = {
    "tracking_gap_possible",
    "tracking_check",
    "clarity_heatmap_opportunity",
    "gtm_setup_check",
    "performance_check",
    "product_data_schema_check",
    "woocommerce_growth_system",
    "advanced_email_marketing_stack",
}

CONVERSION_LEVERS = {
    "checkout_payment_shipping_review",
    "conversion_path_review",
    "cart_checkout",
    "checkout",
    "shipping",
    "payment",
}


def base_fit_score(row: dict[str, str]) -> int:
    return max(
        parse_score(row.get("vhd_fit_score")),
        parse_score(row.get("lead_score")),
        parse_score(row.get("input_lead_score")),
    )


def derive_scores(row: dict[str, str]) -> dict[str, int | str]:
    fit = base_fit_score(row)
    levers = set(split_tokens(row.get("possible_shop_levers")))
    signals = set(split_tokens(row.get("signals")) + split_tokens(row.get("input_signals")))
    is_shop = truthy(row.get("is_shop")) or "cart_checkout" in signals or "active_shop" in signals
    is_woocommerce = truthy(row.get("is_woocommerce")) or "woocommerce" in signals
    is_dach = truthy(row.get("is_dach")) or str(row.get("country_hint", "")).upper() in {"DE", "AT", "CH"}

    shop_score = fit
    if is_shop:
        shop_score += 15
    if is_woocommerce:
        shop_score += 15
    if is_dach:
        shop_score += 5

    technical_score = min(100, 20 + 12 * len(levers & TECHNICAL_LEVERS))
    if is_woocommerce:
        technical_score += 12

    conversion_score = min(100, 15 + 15 * len(levers & CONVERSION_LEVERS))
    if "checkout_payment_shipping_review" in levers:
        conversion_score += 15

    potential_score = fit
    if "advanced_email_marketing_stack" in levers:
        potential_score += 12
    if is_woocommerce and is_shop:
        potential_score += 10

    scores = {
        "shop_relevance_score": clamp_score(shop_score),
        "technical_pain_score": clamp_score(technical_score),
        "conversion_pain_score": clamp_score(conversion_score),
        "business_potential_score": clamp_score(potential_score),
    }
    overall_numeric = round(
        scores["shop_relevance_score"] * 0.35
        + scores["technical_pain_score"] * 0.25
        + scores["conversion_pain_score"] * 0.20
        + scores["business_potential_score"] * 0.20
    )
    scores["overall_numeric_score"] = clamp_score(overall_numeric)
    scores["overall_priority"] = priority_for(row, scores["overall_numeric_score"])
    return scores


def priority_for(row: dict[str, str], score: int) -> str:
    lead_type = str(row.get("lead_type", "")).lower()
    exclusion = str(row.get("exclusion_reason", "")).lower()
    if exclusion or lead_type in {"service_provider", "agency", "platform", "publisher"}:
        return "Reject"
    if not truthy(row.get("is_shop")) and not truthy(row.get("is_woocommerce")):
        return "Review" if score >= 45 else "Reject"
    if score >= 75:
        return "A"
    if score >= 55:
        return "B"
    if score >= 40:
        return "C"
    return "Review"


def build_outreach_angle(row: dict[str, str]) -> str:
    levers = set(split_tokens(row.get("possible_shop_levers")))
    if "checkout_payment_shipping_review" in levers:
        return "Checkout-, Zahlungs- und Versandstrecke pruefen; konkrete Reibungspunkte fuer WooCommerce-Wachstum vermuten."
    if "tracking_gap_possible" in levers or "clarity_heatmap_opportunity" in levers:
        return "Tracking- und Heatmap-Setup pruefen; bessere Entscheidungsgrundlage fuer Shop-Optimierung schaffen."
    if "gtm_setup_check" in levers:
        return "Tag-Manager-Setup strukturieren und Tracking sauberer steuerbar machen."
    if "product_data_schema_check" in levers:
        return "Produktdaten und strukturierte Daten als Conversion- und SEO-Hebel pruefen."
    if "performance_check" in levers:
        return "Performance- und Ladezeithebel fuer Shop und Checkout priorisieren."
    if "woocommerce_growth_system" in levers:
        return "WooCommerce-Wachstumssystem mit technischem Conversion-Fokus pruefen."
    return "Shop-Relevanz manuell pruefen und konkreten WooCommerce-Hebel schaerfen."


def desired_decision_maker_role(row: dict[str, str]) -> str:
    priority_hint = str(row.get("overall_priority", ""))
    if priority_hint in {"A", "B"} or truthy(row.get("is_woocommerce")):
        return "Inhaber/Geschaeftsfuehrer oder E-Commerce-Leitung"
    return "Inhaber/Geschaeftsfuehrer"


def technology_stack(row: dict[str, str]) -> str:
    stack: list[str] = []
    if truthy(row.get("is_woocommerce")):
        stack.append("woocommerce")
    if "wordpress" in " ".join(split_tokens(row.get("verified_signals")) + split_tokens(row.get("signals"))):
        stack.append("wordpress")
    for signal in split_tokens(row.get("tracking_signals")):
        if signal not in stack:
            stack.append(signal)
    return "|".join(stack)
