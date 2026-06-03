from lead_enrichment.policy import EnrichmentPolicy
from lead_enrichment.waterfall import decide_next_step


def test_low_quality_lead_is_stored_without_external_enrichment():
    decision = decide_next_step({"lead_quality": "B"})

    assert decision.next_step == "store_only"
    assert not decision.requires_external_provider


def test_a_lead_runs_free_website_enrichment_first():
    decision = decide_next_step({"lead_quality": "A+", "free_enrichment_status": ""})

    assert decision.next_step == "free_website_enrichment"
    assert decision.status == "queued_free_enrichment"


def test_missing_imprint_plans_serper_when_provider_disabled():
    decision = decide_next_step({"lead_quality": "A", "free_enrichment_status": "complete"})

    assert decision.next_step == "serper_find_imprint_planned"
    assert decision.provider == "serper"
    assert decision.status == "provider_disabled"


def test_low_confidence_known_url_plans_firecrawl():
    decision = decide_next_step(
        {
            "lead_quality": "A",
            "free_enrichment_status": "complete",
            "imprint_url": "https://shop.de/impressum",
            "confidence_score": "0.65",
        }
    )

    assert decision.next_step == "firecrawl_extract_known_url_planned"
    assert decision.provider == "firecrawl"


def test_ambiguous_entity_plans_tavily_when_provider_enabled():
    policy = EnrichmentPolicy(providers={"tavily": {"enabled": True}})
    decision = decide_next_step(
        {
            "lead_quality": "A",
            "free_enrichment_status": "complete",
            "imprint_url": "https://shop.de/impressum",
            "confidence_score": "0.90",
            "managing_director_name": "Max Mustermann",
            "entity_ambiguous": "true",
        },
        policy,
    )

    assert decision.next_step == "tavily_research_ambiguous_entity"
    assert decision.status == "queued_provider_enrichment"


def test_ambiguous_entity_routes_to_manual_review_after_tavily():
    policy = EnrichmentPolicy(providers={"tavily": {"enabled": True}})
    decision = decide_next_step(
        {
            "lead_quality": "A",
            "free_enrichment_status": "complete",
            "imprint_url": "https://shop.de/impressum",
            "confidence_score": "0.90",
            "managing_director_name": "Max Mustermann",
            "entity_ambiguous": "true",
            "tavily_used": "true",
        },
        policy,
    )

    assert decision.next_step == "manual_review"
    assert decision.status == "queued_manual_review"


def test_a_plus_plus_complete_lead_is_planned_for_clay_queue_when_disabled():
    decision = decide_next_step(
        {
            "lead_quality": "A++",
            "free_enrichment_status": "complete",
            "imprint_url": "https://shop.de/impressum",
            "confidence_score": "0.95",
            "managing_director_name": "Max Mustermann",
            "company_name": "Muster GmbH",
            "is_woocommerce": "true",
            "why_relevant": "WooCommerce shop with checkout lever.",
        }
    )

    assert decision.next_step == "clay_email_queue_planned"
    assert decision.provider == "clay"
