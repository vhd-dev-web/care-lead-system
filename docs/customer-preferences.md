# Kundenpräferenzen und Lead-Profile

Dieses Repo ist dafür gedacht, Lead-System-Bausteine wiederverwendbar zu machen, ohne Kundenpräferenzen hart im Code zu verdrahten.

## Grundidee

- Scraper und Enrichment liefern strukturierte Roh- und Prüfdaten.
- Scoring-Profile entscheiden, welche Leads A/B/C-Fit sind.
- Provider-Gates begrenzen Kosten und Datenschutzrisiken.
- Outreach-Exports bleiben manuell freigabepflichtig.

## Beispiele für variable Präferenzen

- Zielsystem: WooCommerce, Shopify, WordPress allgemein, lokale Dienstleister etc.
- Region: DACH, einzelne Länder, Städte oder Bundesländer.
- Shop-Reife: Redesign-Potenzial, technische Bottlenecks, Tracking-Lücken, Produktdatenqualität.
- Ausschlüsse: Branchen, Konzernshops, sehr reife Shops, ungeeignete Plattformen.
- Enrichment-Tiefe: Free-only, Suchprovider, Crawling, Research, Clay-Queue.

## Nächster Architektur-Schritt

Die bisherigen Fixes sollten aus `components/vhd-lead-enrichment/` in klar getrennte Bausteine überführt werden:

1. gemeinsame Datenqualitätsregeln,
2. kunden-/profilbasierte Scoring-Regeln,
3. Provider-Budget- und Policy-Layer,
4. Review-/Approval-Gates,
5. Vauex-/Skill-Handoffs für Coachings.
