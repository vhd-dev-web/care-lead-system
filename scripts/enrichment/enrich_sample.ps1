param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    $env:PYTHONPATH = "src"
    & $Python -m lead_enrichment enrich --mode csv-only --input data\samples\verified_sample.csv --output-dir data\output
}
finally {
    Pop-Location
}
