from lead_enrichment.clay import assess_clay_eligibility


def test_clay_eligibility_requires_a_plus_plus_decision_maker_and_missing_email():
    result = assess_clay_eligibility(
        {
            "lead_quality": "A++",
            "is_woocommerce": "true",
            "company_name": "Muster GmbH",
            "managing_director_name": "Max Mustermann",
            "why_relevant": "WooCommerce shop with checkout lever.",
            "personal_email": "",
            "do_not_contact": "false",
        }
    )

    assert result.eligible


def test_clay_eligibility_rejects_non_a_plus_plus_and_existing_personal_email():
    assert not assess_clay_eligibility({"lead_quality": "A+"}).eligible
    assert not assess_clay_eligibility(
        {
            "lead_quality": "A++",
            "is_woocommerce": "true",
            "company_name": "Muster GmbH",
            "managing_director_name": "Max Mustermann",
            "why_relevant": "WooCommerce shop with checkout lever.",
            "personal_email": "max@example.com",
        }
    ).eligible
