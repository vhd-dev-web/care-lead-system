import json
from pathlib import Path

from lead_enrichment.exporters.csv_exporter import read_csv_rows
from lead_enrichment.orchestrator import (
    WaterfallRunOptions,
    provider_rows_exist,
    run_waterfall,
)
from lead_enrichment.providers.base import SearchResult
from lead_enrichment.providers.serper_client import SerperSearchResponse
from lead_enrichment.sources.website import FetchResult


FIXTURES = Path("tests/fixtures")


class FakeSerperClient:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, *, num: int = 5, gl: str = "de", hl: str = "de") -> SerperSearchResponse:
        del num, gl, hl
        self.queries.append(query)
        return SerperSearchResponse(
            query=query,
            results=[
                SearchResult(
                    title="Impressum - Muster Shop",
                    link="https://muster-shop.de/impressum",
                    snippet="Muster Shop GmbH Impressum",
                    position=1,
                )
            ],
            raw={"organic": []},
        )


class EmptySerperClient:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, *, num: int = 5, gl: str = "de", hl: str = "de") -> SerperSearchResponse:
        del num, gl, hl
        self.queries.append(query)
        return SerperSearchResponse(query=query, results=[], raw={"organic": []})


def fixture_fetcher(url: str) -> FetchResult:
    mapping = {
        "https://muster-shop.de/": FIXTURES / "muster_home.html",
        "https://muster-shop.de/impressum": FIXTURES / "muster_impressum.html",
        "https://muster-shop.de/kontakt": FIXTURES / "muster_kontakt.html",
    }
    if url in mapping:
        return FetchResult(url=url, status=200, html=mapping[url].read_text(encoding="utf-8"))
    return FetchResult(url=url, status=404, html="", error="not found")


def test_run_waterfall_csv_only_control_run_writes_final_exports(tmp_path):
    result = run_waterfall(
        WaterfallRunOptions(
            verified_path=Path("data/samples/verified_sample.csv"),
            output_dir=tmp_path,
            run_website=False,
            run_providers=False,
        )
    )

    summary = json.loads(Path(result.summary_path).read_text(encoding="utf-8"))
    instantly_rows = read_csv_rows(result.final_result.instantly_ready_path)

    assert result.final_result.row_count == 3
    assert result.final_result.instantly_ready_count == 0
    assert instantly_rows == []
    assert summary["run_website"] is False
    assert summary["run_providers"] is False
    assert any(step["name"] == "final_gate" for step in summary["steps"])


def test_run_waterfall_with_fake_website_enrichment(tmp_path):
    input_path = tmp_path / "verified.csv"
    input_path.write_text(
        "\n".join(
            [
                "domain;source_url;company_name;lead_type;is_shop;is_woocommerce;is_dach;vhd_fit_score;possible_shop_levers",
                "muster-shop.de;https://muster-shop.de/;Muster Shop GmbH;shop;true;true;true;75;checkout_payment_shipping_review",
            ]
        ),
        encoding="utf-8",
    )

    result = run_waterfall(
        WaterfallRunOptions(
            verified_path=input_path,
            output_dir=tmp_path / "out",
            run_website=True,
            run_providers=False,
        ),
        fetcher=fixture_fetcher,
    )
    rows = read_csv_rows(result.final_result.enriched_path)

    assert rows[0]["free_enrichment_status"] == "complete"
    assert rows[0]["managing_director_name"] == "Max Mustermann"
    assert rows[0]["compliance_status"] == "outreach_ready"
    assert rows[0]["outreach_channel"] == "call"


def test_run_waterfall_uses_enabled_provider_with_fake_client(tmp_path):
    input_path = tmp_path / "verified.csv"
    policy_path = tmp_path / "policy.json"
    input_path.write_text(
        "\n".join(
            [
                "domain;source_url;company_name;lead_type;is_shop;is_woocommerce;is_dach;vhd_fit_score;possible_shop_levers;free_enrichment_status;confidence_score",
                "muster-shop.de;https://muster-shop.de/;Muster Shop GmbH;shop;true;true;true;75;checkout_payment_shipping_review;complete;0.90",
            ]
        ),
        encoding="utf-8",
    )
    policy_path.write_text(
        json.dumps({"providers": {"serper": {"enabled": True}}, "serper_daily_limit": 3}),
        encoding="utf-8",
    )
    client = FakeSerperClient()

    result = run_waterfall(
        WaterfallRunOptions(
            verified_path=input_path,
            output_dir=tmp_path / "out",
            policy_path=policy_path,
            run_website=False,
            run_providers=True,
            provider_rounds=1,
        ),
        serper_client=client,
    )
    rows = read_csv_rows(result.final_result.enriched_path)

    assert client.queries
    assert rows[0]["imprint_url"] == "https://muster-shop.de/impressum"
    assert any(step.name == "serper_round_1" for step in result.steps)


def test_run_waterfall_enforces_global_serper_budget_across_rounds(tmp_path):
    input_path = tmp_path / "verified.csv"
    policy_path = tmp_path / "policy.json"
    input_path.write_text(
        "\n".join(
            [
                "domain;source_url;company_name;lead_type;is_shop;is_woocommerce;is_dach;vhd_fit_score;possible_shop_levers;free_enrichment_status;confidence_score;imprint_url",
                "muster-shop.de;https://muster-shop.de/;Muster Shop GmbH;shop;true;true;true;90;checkout_payment_shipping_review;complete;0.90;https://muster-shop.de/impressum",
                "zweiter-shop.de;https://zweiter-shop.de/;Zweiter Shop GmbH;shop;true;true;true;90;checkout_payment_shipping_review;complete;0.90;https://zweiter-shop.de/impressum",
            ]
        ),
        encoding="utf-8",
    )
    policy_path.write_text(
        json.dumps(
            {
                "providers": {"serper": {"enabled": True}},
                "serper_daily_limit": 2,
                "max_serper_queries_a_plus_plus_lead": 2,
            }
        ),
        encoding="utf-8",
    )
    client = EmptySerperClient()

    result = run_waterfall(
        WaterfallRunOptions(
            verified_path=input_path,
            output_dir=tmp_path / "out",
            policy_path=policy_path,
            run_website=False,
            run_providers=True,
            provider_rounds=3,
        ),
        serper_client=client,
    )

    assert len(client.queries) == 2
    assert sum((step.counts or {}).get("queries", 0) for step in result.steps) == 2


def test_provider_rows_exist_detects_planned_rows(tmp_path):
    queue_path = tmp_path / "queue.csv"
    queue_path.write_text(
        "lead_id;provider_recommended;next_enrichment_step\n"
        "lead_1;firecrawl;firecrawl_extract_known_url_planned\n",
        encoding="utf-8",
    )

    assert provider_rows_exist(queue_path, "firecrawl")
    assert not provider_rows_exist(queue_path, "serper")
