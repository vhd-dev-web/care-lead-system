from lead_enrichment.quality import lead_quality


def test_a_plus_plus_requires_woocommerce_high_score_shop_and_strong_lever():
    row = {
        "lead_type": "shop",
        "is_shop": "true",
        "is_woocommerce": "true",
        "vhd_fit_score": "90",
        "possible_shop_levers": "woocommerce_growth_system|checkout_payment_shipping_review",
    }

    assert lead_quality(row) == "A++"


def test_quality_steps_down_for_lower_scores_and_non_woocommerce():
    assert (
        lead_quality(
            {
                "lead_type": "shop",
                "is_shop": "true",
                "is_woocommerce": "true",
                "vhd_fit_score": "74",
                "possible_shop_levers": "tracking_gap_possible",
            }
        )
        == "A+"
    )
    assert (
        lead_quality(
            {
                "lead_type": "shop",
                "is_shop": "true",
                "is_woocommerce": "false",
                "vhd_fit_score": "62",
            }
        )
        == "A"
    )
    assert lead_quality({"lead_type": "review", "vhd_fit_score": "45"}) == "B"


def test_rejected_or_provider_like_leads_are_c_quality():
    row = {"lead_type": "service_provider", "is_shop": "false", "vhd_fit_score": "90"}

    assert lead_quality(row) == "C"
