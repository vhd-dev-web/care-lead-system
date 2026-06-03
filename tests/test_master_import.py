from __future__ import annotations

import csv

from care_lead_system.import_scrapes import import_scrape_files
from care_lead_system.master_schema import MASTER_COLUMNS
from care_lead_system.master_store import MasterStore
from care_lead_system.verification_adapter import import_verification_results


def write_csv(path, rows):
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_four_scrape_inputs_import_into_one_master_without_duplicate_domains(tmp_path):
    files = []
    payloads = [
        [{"url": "https://www.acme-shop.de/products", "shop_name": "Acme Shop", "country": "DE", "language": "de"}],
        [{"domain": "acme-shop.de", "company_name": "Acme GmbH", "lead_grade": "A"}],
        [{"website_url": "https://beispiel.at", "shop_name": "Beispiel Shop", "lead_grade": "B"}],
        [{"domain": "cool-shop.ch", "shop_name": "Cool Shop", "lead_grade": "A++"}],
    ]
    for index, rows in enumerate(payloads, start=1):
        path = tmp_path / f"scrape_{index}.csv"
        write_csv(path, rows)
        files.append(path)

    first_result = import_scrape_files(files, root_dir=tmp_path)
    second_result = import_scrape_files(files, root_dir=tmp_path)

    store = MasterStore(tmp_path)
    rows = store.load_rows()
    domains = {row["domain_key"] for row in rows}
    acme = next(row for row in rows if row["domain_key"] == "acme-shop.de")

    assert first_result["records_created"] == 3
    assert second_result["records_created"] == 0
    assert len(rows) == 3
    assert domains == {"acme-shop.de", "beispiel.at", "cool-shop.ch"}
    assert acme["source_lists"] == "scrape_1|scrape_2"
    assert acme["duplicate_status"] == "canonical"
    assert acme["canonical_lead_id"] == acme["lead_id"]
    assert store.master_xlsx_path.exists()
    assert (tmp_path / "output" / "runs" / "run_registry.csv").exists()

    header = store.master_csv_path.read_text(encoding="utf-8").splitlines()[0].split(",")
    for column in [
        "verification_status",
        "shop_relevance_score",
        "enrichment_stage",
        "firecrawl_status",
        "serper_status",
        "tavily_status",
        "clay_status",
    ]:
        assert column in header
        assert column in MASTER_COLUMNS


def test_verification_adapter_updates_master_through_domain_key(tmp_path):
    scrape = tmp_path / "scrape.csv"
    verify = tmp_path / "verification.csv"
    write_csv(scrape, [{"domain": "https://www.woo-shop.de", "shop_name": "Woo"}])
    write_csv(
        verify,
        [
            {
                "domain": "woo-shop.de",
                "domain_alive": "true",
                "is_shop": "true",
                "is_woocommerce": "true",
                "verification_score": "91",
                "evidence_url": "https://woo-shop.de/",
            }
        ],
    )

    import_scrape_files([scrape], root_dir=tmp_path, write_xlsx=False)
    result = import_verification_results(verify, root_dir=tmp_path)

    row = MasterStore(tmp_path).load_rows()[0]
    assert result["records_updated"] == 1
    assert row["verification_status"] == "done"
    assert row["is_woocommerce"] == "true"
    assert row["verification_score"] == "91"
