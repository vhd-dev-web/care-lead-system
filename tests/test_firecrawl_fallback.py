import json
from pathlib import Path

import pytest

from lead_enrichment.exporters.csv_exporter import read_csv_rows, write_csv_rows
from lead_enrichment.firecrawl_fallback import (
    FirecrawlFallbackOptions,
    extract_from_markdown,
    known_extraction_url,
    run_firecrawl_fallback,
)
from lead_enrichment.providers.firecrawl_client import FirecrawlScrapeResponse
from lead_enrichment.queue import QUEUE_FIELDS


class FakeFirecrawlClient:
    def __init__(self, markdown: str | None = None) -> None:
        self.urls: list[str] = []
        self.markdown = markdown or (
            "# Impressum\n"
            "Muster Shop GmbH\n"
            "Musterstrasse 12\n"
            "10115 Berlin\n"
            "Gesch\u00e4ftsf\u00fchrer: Max Mustermann\n"
            "Telefon: +49 30 1234567\n"
            "E-Mail: info@muster-shop.de\n"
        )

    def scrape(self, url: str) -> FirecrawlScrapeResponse:
        self.urls.append(url)
        return FirecrawlScrapeResponse(
            url=url,
            source_url=url,
            title="Impressum - Muster Shop",
            status_code=200,
            markdown=self.markdown,
            raw={"success": True},
        )


def test_extract_from_firecrawl_markdown_uses_local_extractors():
    data = extract_from_markdown(
        (
            "Muster Shop GmbH\n"
            "Musterstrasse 12\n"
            "10115 Berlin\n"
            "Gesch\u00e4ftsf\u00fchrer: Max Mustermann\n"
            "Telefon: +49 30 1234567\n"
            "E-Mail: info@muster-shop.de\n"
        ),
        has_known_imprint_url=True,
    )

    assert data.legal_form == "GmbH"
    assert data.legal_name == "Muster Shop GmbH"
    assert data.managing_director_name == "Max Mustermann"
    assert data.general_email == "info@muster-shop.de"
    assert data.confidence_score >= 0.70


def test_firecrawl_fallback_requires_enabled_policy(tmp_path):
    queue_path = tmp_path / "queue.csv"
    write_csv_rows(queue_path, [], QUEUE_FIELDS)

    with pytest.raises(RuntimeError, match="Firecrawl provider is disabled"):
        run_firecrawl_fallback(
            FirecrawlFallbackOptions(queue_path=queue_path),
            client=FakeFirecrawlClient(),
        )


def test_firecrawl_fallback_extracts_known_imprint_and_recalculates_to_clay(tmp_path):
    queue_path = tmp_path / "queue.csv"
    policy_path = write_enabled_policy(tmp_path)
    row = queue_row(
        {
            "lead_quality": "A++",
            "free_enrichment_status": "low_confidence",
            "confidence_score": "0.30",
            "imprint_url": "https://muster-shop.de/impressum",
            "next_enrichment_step": "firecrawl_extract_known_url_planned",
            "provider_recommended": "firecrawl",
        }
    )
    write_csv_rows(queue_path, [row], QUEUE_FIELDS)
    client = FakeFirecrawlClient()

    result = run_firecrawl_fallback(
        FirecrawlFallbackOptions(queue_path=queue_path, output_dir=tmp_path / "out", policy_path=policy_path),
        client=client,
    )
    rows = read_csv_rows(result.enriched_path)
    clay_rows = read_csv_rows(result.clay_queue_path)

    assert result.processed_count == 1
    assert result.page_count == 1
    assert client.urls == ["https://muster-shop.de/impressum"]
    assert rows[0]["firecrawl_used"] == "true"
    assert rows[0]["firecrawl_source_url"] == "https://muster-shop.de/impressum"
    assert rows[0]["managing_director_name"] == "Max Mustermann"
    assert rows[0]["general_email"] == "info@muster-shop.de"
    assert rows[0]["free_enrichment_status"] == "complete"
    assert rows[0]["next_enrichment_step"] == "clay_email_queue_planned"
    assert clay_rows[0]["clay_eligible"] == "true"


def test_firecrawl_daily_limit_caps_pages(tmp_path):
    queue_path = tmp_path / "queue.csv"
    policy_path = write_enabled_policy(tmp_path, firecrawl_daily_limit=1)
    rows = [
        queue_row(
            {
                "lead_id": "lead_1",
                "lead_quality": "A+",
                "free_enrichment_status": "low_confidence",
                "confidence_score": "0.30",
                "imprint_url": "https://muster-shop.de/impressum",
                "next_enrichment_step": "firecrawl_extract_known_url_planned",
                "provider_recommended": "firecrawl",
            }
        ),
        queue_row(
            {
                "lead_id": "lead_2",
                "domain": "zweiter-shop.de",
                "website_url": "https://zweiter-shop.de/",
                "lead_quality": "A+",
                "free_enrichment_status": "low_confidence",
                "confidence_score": "0.30",
                "imprint_url": "https://zweiter-shop.de/impressum",
                "next_enrichment_step": "firecrawl_extract_known_url_planned",
                "provider_recommended": "firecrawl",
            }
        ),
    ]
    write_csv_rows(queue_path, rows, QUEUE_FIELDS)

    result = run_firecrawl_fallback(
        FirecrawlFallbackOptions(queue_path=queue_path, output_dir=tmp_path / "out", policy_path=policy_path),
        client=FakeFirecrawlClient(),
    )

    assert result.processed_count == 1
    assert result.page_count == 1


def test_known_extraction_url_requires_same_domain():
    row = queue_row(
        {
            "domain": "muster-shop.de",
            "imprint_url": "https://directory.example/muster-shop-impressum",
            "contact_url": "https://muster-shop.de/kontakt",
        }
    )

    assert known_extraction_url(row) == "https://muster-shop.de/kontakt"


def write_enabled_policy(tmp_path: Path, firecrawl_daily_limit: int = 10) -> Path:
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "providers": {"firecrawl": {"enabled": True}},
                "firecrawl_daily_limit": firecrawl_daily_limit,
            }
        ),
        encoding="utf-8",
    )
    return policy_path


def queue_row(overrides: dict[str, str]) -> dict[str, str]:
    row = {field: "" for field in QUEUE_FIELDS}
    row.update(
        {
            "lead_id": "lead_1",
            "domain": "muster-shop.de",
            "website_url": "https://muster-shop.de/",
            "company_name": "Muster Shop GmbH",
            "is_woocommerce": "true",
            "why_relevant": "WooCommerce shop with checkout lever.",
            "do_not_contact": "false",
        }
    )
    row.update(overrides)
    return row
