import json
from pathlib import Path

import pytest

from lead_enrichment.exporters.csv_exporter import read_csv_rows, write_csv_rows
from lead_enrichment.providers.tavily_client import TavilyResult, TavilySearchResponse
from lead_enrichment.queue import QUEUE_FIELDS
from lead_enrichment.tavily_research import (
    TavilyResearchOptions,
    plan_tavily_query,
    run_tavily_research,
)


class FakeTavilyClient:
    def __init__(self, credits: int = 1, answer: str | None = None) -> None:
        self.queries: list[str] = []
        self.credits = credits
        self.answer = answer or (
            "Muster Shop GmbH betreibt den Shop muster-shop.de. "
            "Gesch\u00e4ftsf\u00fchrer ist Max Mustermann."
        )

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        search_depth: str = "basic",
        country: str = "germany",
    ) -> TavilySearchResponse:
        del max_results, search_depth, country
        self.queries.append(query)
        return TavilySearchResponse(
            query=query,
            answer=self.answer,
            results=[
                TavilyResult(
                    title="Impressum - Muster Shop",
                    url="https://muster-shop.de/impressum",
                    content="Muster Shop GmbH, Gesch\u00e4ftsf\u00fchrer: Max Mustermann",
                    score=0.91,
                )
            ],
            credits=self.credits,
            raw={"usage": {"credits": self.credits}},
        )


def test_plan_tavily_query_for_ambiguous_entity_and_decision_maker():
    entity_plan = plan_tavily_query(
        {
            "domain": "muster-shop.de",
            "company_name": "Muster Shop GmbH",
            "entity_ambiguous": "true",
        }
    )
    decision_plan = plan_tavily_query(
        {
            "domain": "muster-shop.de",
            "company_name": "Muster Shop GmbH",
            "decision_maker_ambiguous": "true",
        }
    )

    assert '"Muster Shop GmbH"' in entity_plan.query
    assert "Betreiber" in entity_plan.query
    assert "Gesch\u00e4ftsf\u00fchrer" in decision_plan.query
    assert decision_plan.purpose == "decision_maker"


def test_tavily_research_requires_enabled_policy(tmp_path):
    queue_path = tmp_path / "queue.csv"
    write_csv_rows(queue_path, [], QUEUE_FIELDS)

    with pytest.raises(RuntimeError, match="Tavily provider is disabled"):
        run_tavily_research(TavilyResearchOptions(queue_path=queue_path), client=FakeTavilyClient())


def test_tavily_research_writes_summary_and_routes_to_manual_review(tmp_path):
    queue_path = tmp_path / "queue.csv"
    policy_path = write_enabled_policy(tmp_path)
    row = queue_row(
        {
            "lead_quality": "A+",
            "free_enrichment_status": "complete",
            "confidence_score": "0.90",
            "imprint_url": "https://muster-shop.de/impressum",
            "managing_director_name": "Max Mustermann",
            "entity_ambiguous": "true",
            "next_enrichment_step": "tavily_research_ambiguous_entity",
            "provider_recommended": "tavily",
        }
    )
    write_csv_rows(queue_path, [row], QUEUE_FIELDS)
    client = FakeTavilyClient()

    result = run_tavily_research(
        TavilyResearchOptions(queue_path=queue_path, output_dir=tmp_path / "out", policy_path=policy_path),
        client=client,
    )
    rows = read_csv_rows(result.enriched_path)
    review_rows = read_csv_rows(result.review_path)

    assert result.processed_count == 1
    assert result.query_count == 1
    assert result.credit_count == 1
    assert rows[0]["tavily_used"] == "true"
    assert rows[0]["tavily_result_urls"] == "https://muster-shop.de/impressum"
    assert "Muster Shop GmbH" in rows[0]["tavily_answer"]
    assert rows[0]["next_enrichment_step"] == "manual_review"
    assert rows[0]["provider_recommended"] == ""
    assert review_rows[0]["lead_id"] == "lead_1"
    assert client.queries


def test_tavily_research_can_prefill_missing_decision_maker(tmp_path):
    queue_path = tmp_path / "queue.csv"
    policy_path = write_enabled_policy(tmp_path)
    row = queue_row(
        {
            "lead_quality": "A+",
            "free_enrichment_status": "complete",
            "confidence_score": "0.90",
            "imprint_url": "https://muster-shop.de/impressum",
            "decision_maker_ambiguous": "true",
            "next_enrichment_step": "tavily_research_ambiguous_entity",
            "provider_recommended": "tavily",
        }
    )
    write_csv_rows(queue_path, [row], QUEUE_FIELDS)

    result = run_tavily_research(
        TavilyResearchOptions(queue_path=queue_path, output_dir=tmp_path / "out", policy_path=policy_path),
        client=FakeTavilyClient(),
    )
    rows = read_csv_rows(result.enriched_path)

    assert rows[0]["managing_director_name"] == "Max Mustermann"
    assert rows[0]["managing_director_source"] == "tavily_research"
    assert rows[0]["next_enrichment_step"] == "manual_review"


def test_tavily_research_structures_english_run_by_answer(tmp_path):
    queue_path = tmp_path / "queue.csv"
    policy_path = write_enabled_policy(tmp_path)
    row = queue_row(
        {
            "company_name": "Das BilderbuchCafé",
            "decision_maker_ambiguous": "true",
            "next_enrichment_step": "tavily_research_decision_maker",
            "provider_recommended": "tavily",
        }
    )
    write_csv_rows(queue_path, [row], QUEUE_FIELDS)
    client = FakeTavilyClient(
        answer=(
            "Das BilderbuchCafé is a coffee and ice cream shop. "
            "The shop is run by Thomas Friedrich and offers in-store pickup."
        )
    )

    result = run_tavily_research(
        TavilyResearchOptions(queue_path=queue_path, output_dir=tmp_path / "out", policy_path=policy_path),
        client=client,
    )
    rows = read_csv_rows(result.enriched_path)

    assert rows[0]["managing_director_name"] == "Thomas Friedrich"
    assert rows[0]["managing_director_source"] == "tavily_research"


def test_tavily_daily_credit_limit_caps_queries(tmp_path):
    queue_path = tmp_path / "queue.csv"
    policy_path = write_enabled_policy(tmp_path, tavily_daily_limit=1)
    rows = [
        queue_row(
            {
                "lead_id": "lead_1",
                "entity_ambiguous": "true",
                "next_enrichment_step": "tavily_research_ambiguous_entity",
                "provider_recommended": "tavily",
            }
        ),
        queue_row(
            {
                "lead_id": "lead_2",
                "domain": "zweiter-shop.de",
                "website_url": "https://zweiter-shop.de/",
                "entity_ambiguous": "true",
                "next_enrichment_step": "tavily_research_ambiguous_entity",
                "provider_recommended": "tavily",
            }
        ),
    ]
    write_csv_rows(queue_path, rows, QUEUE_FIELDS)

    result = run_tavily_research(
        TavilyResearchOptions(queue_path=queue_path, output_dir=tmp_path / "out", policy_path=policy_path),
        client=FakeTavilyClient(),
    )

    assert result.processed_count == 1
    assert result.query_count == 1
    assert result.credit_count == 1


def write_enabled_policy(tmp_path: Path, tavily_daily_limit: int = 5) -> Path:
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "providers": {"tavily": {"enabled": True}},
                "tavily_daily_limit": tavily_daily_limit,
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
            "lead_quality": "A+",
            "free_enrichment_status": "complete",
            "confidence_score": "0.90",
            "imprint_url": "https://muster-shop.de/impressum",
            "is_woocommerce": "true",
            "why_relevant": "WooCommerce shop with checkout lever.",
            "do_not_contact": "false",
        }
    )
    row.update(overrides)
    return row
