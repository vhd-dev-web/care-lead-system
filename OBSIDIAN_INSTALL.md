# Obsidian Installation

Diese Datei ist der Installationspunkt fuer Obsidian/Codex. Ziel: Das
Lead-System wird einmal lokal eingerichtet und danach per einem Skript als
Standardlauf gestartet.

## 1. Paket installieren

```powershell
python -m pip install -e ".[google]"
```

Ohne Google-Sheets-Sync reicht:

```powershell
python -m pip install -e .
```

Wenn der normale `python`-Befehl nicht auf die richtige Python-Installation
zeigt, setze vor dem Lauf:

```powershell
$env:VHD_LEAD_PYTHON = "C:\Pfad\zu\python.exe"
```

## 2. Setup-Wizard starten

```powershell
vhd-lead-system setup
```

Der Wizard fragt:

- Darf Brave Search fuer neue Scrape-Leads laufen?
- Duerfen Serper, Firecrawl und Tavily fuer Enrichment-Fallbacks laufen?
- Soll Google Sheets fuer die Clay Queue und Clay Results genutzt werden?
- Welche API-Keys oder Service-Account-Pfade sollen in `.env` stehen?
- Gibt es bereits eine CSV/XLSX-Datei mit Leads, die in den Master importiert
  werden soll?

Vorhandene Leads werden ueber den Master-Updater importiert und per
`domain_key` dedupliziert. Eine Datei mit den 57 bereits gefundenen Kontakten
sollte hier als bestehende Lead-Datei angegeben werden, damit sie nicht neben
dem System liegen bleibt.

## 3. Was der Wizard schreibt

```text
.env
crawler_policy.json
config/enrichment_policy.json
config/install_profile.json
scripts/run_vhd_lead_system.ps1
data/master/leads_master.csv
data/master/Leads_Master.xlsx
```

`.env`, lokale Policies und Output-Dateien sind in `.gitignore` eingetragen.
Secrets und persoenliche Laufprofile werden nicht ins Repo gepusht.

## 4. Standardlauf aus Obsidian

Nach dem Setup kann Obsidian/Codex den Standardlauf so starten:

```powershell
.\scripts\run_vhd_lead_system.ps1
```

Der Lauf fuehrt aus:

```text
scrape -> master import -> verify -> enrichment -> master xlsx -> Clay Queue -> optional Google Sheets sync
```

Der Master bleibt die Wahrheit:

```text
data/master/leads_master.csv
```

Google Sheets ist nur die Clay-Uebergabe und Rueckgabe. Clay-Ergebnisse werden
spaeter wieder in den Master importiert.

### Google-Sheets-Sync (Clay Queue Handoff)

Der Pipeline-Lauf schreibt die Clay-Queue automatisch in den festen Tab
`Clay Queue` deines Sheets, wenn in `.env` folgende Werte gesetzt sind:

```text
VHD_GOOGLE_SPREADSHEET_ID=<spreadsheet-id-aus-der-sheet-url>
GOOGLE_APPLICATION_CREDENTIALS=<absoluter-pfad-zur-service-account.json>
```

Voraussetzungen einmalig:

1. In der Google Cloud Console ein Projekt waehlen, **Google Sheets API**
   aktivieren.
2. Service-Account anlegen, JSON-Key herunterladen, ausserhalb des Repos
   ablegen (z.B. `C:\Users\<user>\.secrets\...json`).
3. Das Sheet mit der Service-Account-E-Mail (`...@<projekt>.iam.gserviceaccount.com`)
   als **Bearbeiter** teilen, "Benachrichtigen" deaktivieren.
4. Einmalig die Tabs anlegen:

```powershell
vhd-lead-system setup-google-sheet
```

Das legt die festen Tabs `Clay Queue`, `Clay Results`, `Sync Log` an. Bei
jedem Pipeline-Lauf wird der `Clay Queue`-Tab geleert und mit der aktuellen
Queue ueberschrieben - **keine neuen Tabellenblaetter pro Lauf**.

Verhalten der Pipeline:

- Ist `VHD_GOOGLE_SPREADSHEET_ID` gesetzt, laeuft der Sync automatisch.
- `--sync-google` erzwingt den Sync, `--no-sync-google` unterdrueckt ihn.
- Ohne Spreadsheet-ID wird der Schritt mit Status `skipped` markiert.

## 5. Nicht-interaktiver Setup-Lauf

Fuer einen schnellen Start mit Brave, ohne Provider-Enrichment:

```powershell
vhd-lead-system setup --yes --allow-brave --no-serper --no-firecrawl --no-tavily
```

Mit bestehender Lead-Datei:

```powershell
vhd-lead-system setup --yes --allow-brave --existing-leads "C:\Pfad\leads.csv"
```

Mit Google Sheets:

```powershell
vhd-lead-system setup --yes --allow-brave --allow-google-sheets `
  --spreadsheet-id "GOOGLE_SHEET_ID" `
  --google-credentials "C:\Pfad\service-account.json"
```
