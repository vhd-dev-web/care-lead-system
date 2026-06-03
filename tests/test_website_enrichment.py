from pathlib import Path

from lead_enrichment.exporters.csv_exporter import read_csv_rows, write_csv_rows
from lead_enrichment.queue import QUEUE_FIELDS
from lead_enrichment.sources.website import FetchResult
from lead_enrichment.website_enrichment import (
    WebsiteEnrichmentOptions,
    extract_public_website_data,
    run_free_website_enrichment,
)


FIXTURES = Path("tests/fixtures")


def fixture_fetcher(url: str) -> FetchResult:
    mapping = {
        "https://muster-shop.de/": FIXTURES / "muster_home.html",
        "https://muster-shop.de/impressum": FIXTURES / "muster_impressum.html",
        "https://muster-shop.de/kontakt": FIXTURES / "muster_kontakt.html",
    }
    if url in mapping:
        return FetchResult(url=url, status=200, html=mapping[url].read_text(encoding="utf-8"))
    return FetchResult(url=url, status=404, html="", error="not found")


def test_extract_public_website_data_from_known_public_pages():
    data = extract_public_website_data(
        "muster-shop.de",
        {},
        policy=short_policy(),
        fetcher=fixture_fetcher,
    )

    assert data.legal_form == "GmbH"
    assert data.legal_name == "Muster Shop GmbH"
    assert data.address == "Musterstrasse 12, 10115 Berlin"
    assert data.managing_director_name == "Max Mustermann"
    assert data.general_email == "info@muster-shop.de"
    assert data.phone_main == "+49 30 1234567"
    assert data.imprint_url == "https://muster-shop.de/impressum"
    assert data.confidence_score >= 0.70
    assert data.parse_status == "complete"


def test_run_free_website_enrichment_updates_queue_and_clay_queue(tmp_path):
    queue_path = tmp_path / "enrichment_queue.csv"
    row = {field: "" for field in QUEUE_FIELDS}
    row.update(
        {
            "lead_id": "lead_1",
            "domain": "muster-shop.de",
            "website_url": "https://muster-shop.de/",
            "company_name": "Muster Shop GmbH",
            "lead_quality": "A++",
            "is_woocommerce": "true",
            "why_relevant": "WooCommerce shop with checkout lever.",
            "next_enrichment_step": "free_website_enrichment",
            "do_not_contact": "false",
        }
    )
    write_csv_rows(queue_path, [row], QUEUE_FIELDS)

    result = run_free_website_enrichment(
        WebsiteEnrichmentOptions(queue_path=queue_path, output_dir=tmp_path / "out"),
        fetcher=fixture_fetcher,
    )
    enriched_rows = read_csv_rows(result.enriched_path)
    clay_rows = read_csv_rows(result.clay_queue_path)

    assert result.processed_count == 1
    assert result.clay_row_count == 1
    assert enriched_rows[0]["free_enrichment_status"] == "complete"
    assert enriched_rows[0]["managing_director_name"] == "Max Mustermann"
    assert enriched_rows[0]["next_enrichment_step"] == "clay_email_queue_planned"
    assert clay_rows[0]["clay_eligible"] == "true"


def short_policy():
    from lead_enrichment.policy import EnrichmentPolicy

    return EnrichmentPolicy(website_pages_per_domain=4)
