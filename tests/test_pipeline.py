from pathlib import Path

from lead_enrichment.pipeline import EnrichmentOptions, run_enrichment


def test_csv_only_pipeline_writes_expected_outputs(tmp_path):
    sample = Path("data/samples/verified_sample.csv")
    result = run_enrichment(
        EnrichmentOptions(
            input_path=sample,
            output_dir=tmp_path,
            mode="csv-only",
        )
    )

    assert len(result.rows) == 3
    assert Path(result.enriched_path).exists()
    assert Path(result.review_path).exists()
    assert Path(result.outreach_ready_path).exists()
    assert result.rows[0].overall_priority == "A"
    assert result.rows[0].compliance_status == "outreach_ready"
    assert result.rows[2].compliance_status == "do_not_contact"
