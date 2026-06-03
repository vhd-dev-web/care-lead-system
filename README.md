# vhd-lead-system

Zentrales, master-first Lead-System fuer VHD. Das Root-Paket ist als
Monolith installierbar und enthaelt Scraping, Verification/Scoring,
Enrichment, Clay-Handoff, Google-Sheets-Sync und den Master.

## Grundregel

`data/master/leads_master.csv` ist die Wahrheit. Alle Pipeline-Schritte schreiben
Master-Aenderungen ueber `MasterUpdater`. Dateien unter `output/` sind nur
Uebergaben, Reviews, Logs oder Archive.

## Struktur

```text
data/master/leads_master.csv
data/master/Leads_Master.xlsx

output/raw_scrapes/
output/runs/
output/logs/
output/exports/
output/archive/
output/enrichment/
output/lead_to_clay/
```

## Module

- `master_schema.py`: kanonische Master-Spalten und Defaults.
- `master_store.py`: CSV-Lesen/Schreiben fuer den Master.
- `master_updater.py`: einziger Schreibpfad fuer Master-Aenderungen.
- `run_registry.py`: Run-Historie unter `output/runs/run_registry.csv`.
- `import_scrapes.py`: CSV/XLSX-Scrape-Import mit Dedupe ueber `domain_key`.
- `verification_adapter.py`: Import von Verification-Ergebnissen in den Master.
- `enrichment_planner.py`: setzt Firecrawl/Serper/Tavily-Bedarfe im Master.
- `export_master_xlsx.py`: erzeugt die filterbare Arbeitsansicht.
- `lead_to_clay_adapter.py`: CSV-Queue und Clay-Result-Import.
- `google_sheets_adapter.py`: Google-Sheets-Handoff mit `Clay Queue`,
  `Clay Results` und `Sync Log`.
- `pipeline_runner.py`: orchestriert Scrape -> Verify -> Enrich -> Clay.
- `setup_wizard.py`: lokaler Installations-/Obsidian-Onboarding-Wizard.
- `scraper/`: gebuendelter Brave/Google-Scraper und Domain-Verifier.
- `lead_enrichment`: gebuendelter Free-first Enrichment-/Clay-Waterfall.

## Installation

```powershell
python -m pip install -e ".[google]"
```

Ohne Google-Sync reicht:

```powershell
python -m pip install -e .
```

## Obsidian-Setup

Der Installationspunkt fuer Obsidian/Codex liegt in `OBSIDIAN_INSTALL.md`.
Der empfohlene Erstlauf ist:

```powershell
vhd-lead-system setup
```

Wenn noch kein Script-Pfad aktiv ist:

```powershell
python -m vhd_lead_system.cli --root . setup
```

Der Setup-Wizard fragt Provider-Freigaben, API-Keys, Google-Sheets-Zugang und
eine optionale bestehende Lead-Datei ab. Vorhandene Leads werden in
`data/master/leads_master.csv` importiert und per `domain_key` dedupliziert,
damit fruehere Kontakte nicht verloren gehen.

Nach dem Setup kann Obsidian den Standardlauf starten:

```powershell
.\scripts\run_vhd_lead_system.ps1
```

## CLI-Beispiele

```powershell
python -m vhd_lead_system.cli --root . import-scrapes `
  output/raw_scrapes/list_1.csv `
  output/raw_scrapes/list_2.csv `
  output/raw_scrapes/list_3.csv `
  output/raw_scrapes/list_4.csv

python -m vhd_lead_system.cli --root . import-verification output/exports/verification_results.csv
python -m vhd_lead_system.cli --root . import-enrichment-results output/enrichment/enriched_master.csv
python -m vhd_lead_system.cli --root . plan-enrichment
python -m vhd_lead_system.cli --root . export-master-xlsx
python -m vhd_lead_system.cli --root . export-clay-queue --batch-id clay_batch_001
python -m vhd_lead_system.cli --root . import-clay-results output/lead_to_clay/clay_results.csv
```

Direkte Modulbefehle im Monolith:

```powershell
python -m vhd_lead_system.cli scrape --provider brave --budget-calls 5 --query-limit 5
python -m vhd_lead_system.cli verify --input output/raw_scrapes/qualified_master.csv --mode deep
python -m vhd_lead_system.cli enrich run-waterfall --verified output/runs/verification_YYYY/verified_leads.csv
```

Ein Standardlauf fuer Obsidian/Automation:

```powershell
python -m vhd_lead_system.cli --root . run-pipeline `
  --provider brave `
  --budget-calls 5 `
  --query-limit 5 `
  --verify-workers 2 `
  --sync-google
```

Provider-Enrichment mit Serper/Firecrawl/Tavily laeuft nur, wenn die lokale
Policy in `config/enrichment_policy.json` den jeweiligen Provider aktiviert und
die passenden API-Keys gesetzt sind.

## Phase 2: Google-Sheets-Handoff

Der Google-Sheet-Connector ist ein Adapter. Das Sheet ist nicht die Wahrheit:
`Clay Queue` wird aus dem Master befuellt, `Clay Results` wird in den Master
zurueckimportiert, und `Sync Log` dokumentiert die Uebergaben.

Pflicht-Tabs:

```text
Clay Queue
Clay Results
Sync Log
```

Produktive Nutzung braucht eine Service-Account-Credentials-Datei und ein
Google-Sheet, das mit diesem Service Account geteilt ist.

```powershell
$env:VHD_GOOGLE_SPREADSHEET_ID = "..."
$env:GOOGLE_APPLICATION_CREDENTIALS = "C:\path\to\service-account.json"

python -m vhd_lead_system.cli --root . setup-google-sheet
python -m vhd_lead_system.cli --root . sync-google-clay-queue --batch-id gclay_batch_001
python -m vhd_lead_system.cli --root . import-google-clay-results
```

Alternativ kann die Sheet-ID direkt uebergeben werden:

```powershell
python -m vhd_lead_system.cli --root . --spreadsheet-id "..." sync-google-clay-queue
```

## Upstream-Repo-Integration

Der aktuelle Integrations-Audit liegt in `docs/integration-audit.md`.

Kurzstand:

- `vhd-lead-scraper`: Search- und Verification-CSV-Outputs sind importierbar.
- `vhd-lead-scoring-operator`: Vertrags-/Schema-Repo; noch kein stabiler
  Scorer-Entrypoint.
- `vhd-lead-enrichment`: `enriched_master.csv`, `enrichment_queue.csv` und
  verwandte Outputs sind importierbar.
- `lead-to-clay`: aktueller Stand nutzt dieselben `lead_enrichment`-Queue- und
  Final-Gate-Schemas; diese Outputs sind ueber `import-enrichment-results`
  importierbar. Persoenliche Clay-E-Mail-Resultate bleiben bis zu einer
  expliziten Compliance-/Schema-Entscheidung ausserhalb der Master-Standardfelder.

Wichtig: Die Kernfunktionen sind jetzt im Root-Paket enthalten. Die alten
Einzelrepos dienen nur noch als Ursprung/Referenz fuer bereits konsolidierten
Code, nicht als Runtime-Abhaengigkeit fuer den Standardlauf.

## Clay-Regeln in Phase 1

- `A++`: immer in die Clay-Queue.
- `A+`: in die Queue, wenn Entscheider fehlt oder kein Business-Kontaktweg vorhanden ist.
- `A`: zu Beginn ebenfalls in die Queue.
- `B`/`C`: nicht automatisch.
- `Review`: nur manuell.
- `Reject`: nie.

Wiederholte Queue-Exports duplizieren standardmaessig keine bereits
`queued`, `running`, `partial` oder `done` markierten Leads.

## Tests

```powershell
python -m pytest -q
```
