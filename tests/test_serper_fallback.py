import json
from pathlib import Path

import pytest

from lead_enrichment.exporters.csv_exporter import read_csv_rows, write_csv_rows
from lead_enrichment.providers.base import SearchResult
from lead_enrichment.providers.serper_client import SerperSearchResponse
from lead_enrichment.queue import QUEUE_FIELDS
from lead_enrichment.serper_fallback import (
    SerperFallbackOptions,
    plan_serper_queries,
    run_serper_fallback,
)


class FakeSerperClient:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, *, num: int = 5, gl: str = "de", hl: str = "de") -> SerperSearchResponse:
        del num, gl, hl
        self.queries.append(query)
        if "impressum" in query.lower():
            results = [
                SearchResult(
                    title="Impressum - Muster Shop",
                    link="https://muster-shop.de/impressum",
                    snippet="Muster Shop GmbH Impressum",
                    position=1,
                )
            ]
        elif "Gesch\u00e4ftsf\u00fchrer" in query or "Geschaeftsfuehrer" in query:
            results = [
                SearchResult(
                    title="Muster Shop GmbH",
                    link="https://muster-shop.de/impressum",
                    snippet="Gesch\u00e4ftsf\u00fchrer: Max Mustermann",
                    position=1,
                )
            ]
        else:
            results = []
        return SerperSearchResponse(query=query, results=results, raw={"organic": []})


def test_plan_serper_queries_for_imprint_and_decision_maker():
    imprint_plan = plan_serper_queries(
        {
            "next_enrichment_step": "serper_find_imprint_planned",
            "domain": "muster-shop.de",
            "company_name": "Muster Shop GmbH",
        },
        policy=None,  # type: ignore[arg-type]
    )
    decision_plan = plan_serper_queries(
        {
            "next_enrichment_step": "serper_find_decision_maker_planned",
            "domain": "muster-shop.de",
            "company_name": "Muster Shop GmbH",
        },
        policy=None,  # type: ignore[arg-type]
    )

    assert 'site:muster-shop.de impressum' in imprint_plan.queries
    assert '"Muster Shop GmbH" Impressum' in imprint_plan.queries
    assert 'site:muster-shop.de "Gesch\u00e4ftsf\u00fchrer"' in decision_plan.queries
    assert '"Muster Shop GmbH" Inhaber' in decision_plan.queries


def test_serper_fallback_requires_enabled_policy(tmp_path):
    queue_path = tmp_path / "queue.csv"
    write_csv_rows(queue_path, [], QUEUE_FIELDS)

    with pytest.raises(RuntimeError, match="Serper provider is disabled"):
        run_serper_fallback(SerperFallbackOptions(queue_path=queue_path), client=FakeSerperClient())


def test_serper_fallback_finds_imprint_and_recalculates_to_firecrawl(tmp_path):
    queue_path = tmp_path / "queue.csv"
    policy_path = write_enabled_policy(tmp_path)
    row = queue_row(
        {
            "lead_quality": "A+",
            "free_enrichment_status": "low_confidence",
            "confidence_score": "0.30",
            "next_enrichment_step": "serper_find_imprint_planned",
            "provider_recommended": "serper",
        }
    )
    write_csv_rows(queue_path, [row], QUEUE_FIELDS)

    result = run_serper_fallback(
        SerperFallbackOptions(queue_path=queue_path, output_dir=tmp_path / "out", policy_path=policy_path),
        client=FakeSerperClient(),
    )
    rows = read_csv_rows(result.enriched_path)

    assert result.query_count == 1
    assert rows[0]["imprint_url"] == "https://muster-shop.de/impressum"
    assert rows[0]["serper_used"] == "true"
    assert rows[0]["next_enrichment_step"] == "firecrawl_extract_known_url_planned"


def test_serper_fallback_finds_decision_maker_and_moves_to_review(tmp_path):
    queue_path = tmp_path / "queue.csv"
    policy_path = write_enabled_policy(tmp_path)
    row = queue_row(
        {
            "lead_quality": "A+",
            "free_enrichment_status": "complete",
            "confidence_score": "0.95",
            "imprint_url": "https://muster-shop.de/impressum",
            "next_enrichment_step": "serper_find_decision_maker_planned",
            "provider_recommended": "serper",
        }
    )
    write_csv_rows(queue_path, [row], QUEUE_FIELDS)

    result = run_serper_fallback(
        SerperFallbackOptions(queue_path=queue_path, output_dir=tmp_path / "out", policy_path=policy_path),
        client=FakeSerperClient(),
    )
    rows = read_csv_rows(result.enriched_path)

    assert result.query_count == 1
    assert rows[0]["managing_director_name"] == "Max Mustermann"
    assert rows[0]["managing_director_source"] == "serper_snippet"
    assert rows[0]["next_enrichment_step"] == "compliance_review"


def test_serper_daily_query_limit_caps_queries_not_rows(tmp_path):
    queue_path = tmp_path / "queue.csv"
    policy_path = write_enabled_policy(tmp_path, serper_daily_limit=1)
    rows = [
        queue_row(
            {
                "lead_quality": "A+",
                "free_enrichment_status": "low_confidence",
                "confidence_score": "0.30",
                "next_enrichment_step": "serper_find_imprint_planned",
                "provider_recommended": "serper",
            }
        ),
        queue_row(
            {
                "lead_id": "lead_2",
                "lead_quality": "A+",
                "free_enrichment_status": "low_confidence",
                "confidence_score": "0.30",
                "next_enrichment_step": "serper_find_imprint_planned",
                "provider_recommended": "serper",
            }
        ),
    ]
    write_csv_rows(queue_path, rows, QUEUE_FIELDS)

    result = run_serper_fallback(
        SerperFallbackOptions(queue_path=queue_path, output_dir=tmp_path / "out", policy_path=policy_path),
        client=FakeSerperClient(),
    )

    assert result.processed_count == 1
    assert result.query_count == 1


def write_enabled_policy(tmp_path: Path, serper_daily_limit: int = 10) -> Path:
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps({"providers": {"serper": {"enabled": True}}, "serper_daily_limit": serper_daily_limit}),
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
