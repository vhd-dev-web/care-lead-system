param(
    [string]$Queue = "data/output/enrichment_queue.csv",
    [string]$OutputDir = "data/output",
    [string]$Policy = "config/enrichment_policy.json",
    [int]$Limit = 5
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "src"

python -m lead_enrichment firecrawl-fallback `
    --queue $Queue `
    --output-dir $OutputDir `
    --policy $Policy `
    --limit $Limit
