from __future__ import annotations

import csv
import json
from pathlib import Path

from vhd_lead_system.master_store import MasterStore
from vhd_lead_system.setup_wizard import run_setup_wizard


def test_setup_wizard_creates_local_profile_and_imports_existing_leads(tmp_path: Path) -> None:
    leads_path = tmp_path / "existing_leads.csv"
    with leads_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["domain", "url", "company_name"])
        writer.writeheader()
        writer.writerow(
            {
                "domain": "example-shop.de",
                "url": "https://example-shop.de",
                "company_name": "Example Shop",
            }
        )

    result = run_setup_wizard(
        [
            "--root",
            str(tmp_path),
            "--yes",
            "--allow-brave",
            "--allow-serper",
            "--no-firecrawl",
            "--no-tavily",
            "--existing-leads",
            str(leads_path),
        ]
    )

    assert (tmp_path / ".env").exists()
    assert (tmp_path / "crawler_policy.json").exists()
    assert (tmp_path / "config" / "enrichment_policy.json").exists()
    assert (tmp_path / "config" / "install_profile.json").exists()
    assert (tmp_path / "scripts" / "run_vhd_lead_system.ps1").exists()
    assert (tmp_path / "data" / "master" / "leads_master.csv").exists()
    assert (tmp_path / "data" / "master" / "Leads_Master.xlsx").exists()

    policy = json.loads((tmp_path / "config" / "enrichment_policy.json").read_text(encoding="utf-8"))
    assert policy["providers"]["serper"]["enabled"] is True
    assert policy["providers"]["firecrawl"]["enabled"] is False
    assert policy["providers"]["tavily"]["enabled"] is False

    rows = MasterStore(tmp_path).load_rows()
    assert len(rows) == 1
    assert rows[0]["domain_key"] == "example-shop.de"
    assert result["existing_leads_import"]["result"]["records_created"] == 1


def test_setup_wizard_reimport_dedupes_existing_leads(tmp_path: Path) -> None:
    leads_path = tmp_path / "existing_leads.csv"
    leads_path.write_text(
        "domain,url,company_name\nexample-shop.de,https://example-shop.de,Example Shop\n",
        encoding="utf-8",
    )

    args = [
        "--root",
        str(tmp_path),
        "--yes",
        "--allow-brave",
        "--existing-leads",
        str(leads_path),
    ]
    first = run_setup_wizard(args)
    second = run_setup_wizard(args)

    rows = MasterStore(tmp_path).load_rows()
    assert len(rows) == 1
    assert first["existing_leads_import"]["result"]["records_created"] == 1
    assert second["existing_leads_import"]["result"]["records_created"] == 0
