param(
    [string]$Queue = "data\output\enrichment_queue.csv",
    [string]$Python = "python",
    [int]$Limit = 5
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    $env:PYTHONPATH = "src"
    $argsList = @(
        "-m", "lead_enrichment", "free-website-enrich",
        "--queue", $Queue,
        "--output-dir", "data\output"
    )
    if ($Limit -gt 0) {
        $argsList += @("--limit", "$Limit")
    }
    & $Python @argsList
}
finally {
    Pop-Location
}
