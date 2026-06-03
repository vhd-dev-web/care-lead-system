param(
    [string]$Input = "data\input\verified_master.csv",
    [string]$Python = "python",
    [int]$Limit = 30
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    $env:PYTHONPATH = "src"
    & $Python -m lead_enrichment enrich --mode csv-only --input $Input --output-dir data\output --limit $Limit
}
finally {
    Pop-Location
}
