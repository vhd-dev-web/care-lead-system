param(
    [string]$Verified = "data\input\verified_master.csv",
    [string]$Review = "data\input\review_master.csv",
    [string]$Python = "python",
    [int]$Limit = 0
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Push-Location $repoRoot
try {
    $env:PYTHONPATH = "src"
    $argsList = @(
        "-m", "lead_enrichment", "prepare-queue",
        "--verified", $Verified,
        "--output-dir", "data\output"
    )
    if (Test-Path $Review) {
        $argsList += @("--review", $Review)
    }
    if ($Limit -gt 0) {
        $argsList += @("--limit", "$Limit")
    }
    & $Python @argsList
}
finally {
    Pop-Location
}
