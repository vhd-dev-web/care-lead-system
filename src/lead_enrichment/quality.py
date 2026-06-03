from __future__ import annotations

from .normalizer import parse_score, split_tokens, truthy
from .scoring import base_fit_score


STRONG_LEVERS = {
    "woocommerce_growth_system",
    "checkout_payment_shipping_review",
    "conversion_path_review",
    "tracking_gap_possible",
    "clarity_heatmap_opportunity",
    "performance_check",
}


def lead_quality(row: dict[str, str]) -> str:
    score = base_fit_score(row)
    lead_type = str(row.get("lead_type", "")).lower()
    exclusion = str(row.get("exclusion_reason", "")).strip()
    is_shop = truthy(row.get("is_shop"))
    is_woocommerce = truthy(row.get("is_woocommerce"))
    has_strong_lever = bool(set(split_tokens(row.get("possible_shop_levers"))) & STRONG_LEVERS)

    if exclusion or lead_type in {"service_provider", "agency", "platform", "publisher", "rejected"}:
        return "C"
    if is_woocommerce and is_shop and score >= 85 and has_strong_lever:
        return "A++"
    if is_woocommerce and score >= 70:
        return "A+"
    if is_shop and score >= 60:
        return "A"
    if lead_type in {"review", "unknown"} or score >= 40:
        return "B"
    return "C"


def quality_rank(value: str) -> int:
    return {"C": 0, "B": 1, "A": 2, "A+": 3, "A++": 4}.get(value, 0)


def is_enrichment_worthy(value: str) -> bool:
    return quality_rank(value) >= quality_rank("A")


def score_from_row(row: dict[str, str]) -> int:
    return max(
        parse_score(row.get("vhd_fit_score")),
        parse_score(row.get("lead_score")),
        parse_score(row.get("input_lead_score")),
    )
