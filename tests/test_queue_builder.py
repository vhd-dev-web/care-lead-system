from pathlib import Path

from lead_enrichment.exporters.csv_exporter import read_csv_rows
from lead_enrichment.queue import QueueBuildOptions, build_enrichment_queue


def test_prepare_queue_from_sample_writes_queue_and_empty_clay_queue(tmp_path):
    result = build_enrichment_queue(
        QueueBuildOptions(
            verified_path=Path("data/samples/verified_sample.csv"),
            output_dir=tmp_path,
        )
    )

    queue_rows = read_csv_rows(result.queue_path)
    clay_rows = read_csv_rows(result.clay_queue_path)

    assert result.row_count == 3
    assert result.clay_row_count == 0
    assert len(queue_rows) == 3
    assert clay_rows == []
    assert queue_rows[0]["lead_quality"] == "A+"
    assert queue_rows[0]["next_enrichment_step"] == "free_website_enrichment"
    assert queue_rows[2]["next_enrichment_step"] == "store_only"


def test_prepare_queue_writes_clay_queue_only_when_waterfall_reaches_clay(tmp_path):
    input_path = tmp_path / "verified.csv"
    input_path.write_text(
        "\n".join(
            [
                "domain;source_url;company_name;lead_type;is_shop;is_woocommerce;is_dach;vhd_fit_score;possible_shop_levers;free_enrichment_status;imprint_url;confidence_score;managing_director_name",
                "a-shop.de;https://a-shop.de/;A Shop GmbH;shop;true;true;true;90;woocommerce_growth_system|checkout_payment_shipping_review;complete;https://a-shop.de/impressum;0.95;Max Mustermann",
            ]
        ),
        encoding="utf-8",
    )

    result = build_enrichment_queue(
        QueueBuildOptions(
            verified_path=input_path,
            output_dir=tmp_path / "out",
        )
    )
    clay_rows = read_csv_rows(result.clay_queue_path)

    assert result.clay_row_count == 1
    assert clay_rows[0]["lead_quality"] == "A++"
    assert clay_rows[0]["clay_eligible"] == "true"
    assert clay_rows[0]["next_enrichment_step"] == "clay_email_queue_planned"
