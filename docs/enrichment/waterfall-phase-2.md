# Waterfall Phase 2

Phase 2 adds free website/imprint enrichment. It does not call Serper, Firecrawl, Tavily, or Clay.

## Command

```powershell
python -m lead_enrichment free-website-enrich --queue data/output/enrichment_queue.csv --limit 5
```

## Input

```text
data/output/enrichment_queue.csv
```

Only rows with:

```text
next_enrichment_step = free_website_enrichment
```

are processed.

## Pages

The default known public pages are:

```text
/
/impressum
/imprint
/kontakt
/contact
/datenschutz
/ueber-uns
/team
```

## Extracted Fields

```text
legal_name
legal_form
address
managing_director_name
managing_director_source
general_email
phone_main
imprint_url
contact_url
confidence_score
imprint_parse_status
free_enrichment_source_urls
website_pages_checked
```

## Outputs

```text
data/output/enriched_master.csv
data/output/enrichment_review.csv
data/output/clay_queue.csv
data/output/enrichment_queue.csv
```

The queue is rewritten with the updated waterfall decision. If an A++ lead becomes Clay-eligible after the free website pass, it appears in `clay_queue.csv`, but no Clay API call is made.
