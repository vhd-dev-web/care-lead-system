from lead_enrichment.dedupe import dedupe_rows


def test_dedupe_rows_merges_by_normalized_domain_and_keeps_better_score():
    rows = [
        {"domain": "https://www.shop.de/a", "vhd_fit_score": "30", "possible_shop_levers": "tracking_check"},
        {"domain": "shop.de", "vhd_fit_score": "80", "possible_shop_levers": "checkout_payment_shipping_review"},
    ]

    result = dedupe_rows(rows)

    assert len(result) == 1
    assert result[0]["domain"] == "shop.de"
    assert result[0]["vhd_fit_score"] == "80"
    assert "tracking_check" in result[0]["possible_shop_levers"]
    assert "checkout_payment_shipping_review" in result[0]["possible_shop_levers"]
