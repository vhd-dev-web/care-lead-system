param(
    [string]$Queue = "data/output/enrichment_queue.csv",
    [string]$OutputDir = "data/output",
    [string]$ClayResults = ""
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "src"

$argsList = @(
    "-m", "lead_enrichment", "finalize",
    "--queue", $Queue,
    "--output-dir", $OutputDir
)

if ($ClayResults -ne "") {
    $argsList += @("--clay-results", $ClayResults)
}

python @argsList
