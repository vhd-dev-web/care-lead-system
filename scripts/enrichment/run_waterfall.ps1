param(
    [Parameter(Mandatory = $true)]
    [string]$Verified,
    [string]$Review = "",
    [string]$OutputDir = "data/output",
    [string]$Policy = "config/enrichment_policy.json",
    [int]$Limit = 0,
    [switch]$SkipWebsite,
    [switch]$SkipProviders,
    [int]$ProviderRounds = 3,
    [string]$ClayResults = ""
)

$ErrorActionPreference = "Stop"
$env:PYTHONPATH = "src"

$argsList = @(
    "-m", "lead_enrichment", "run-waterfall",
    "--verified", $Verified,
    "--output-dir", $OutputDir,
    "--policy", $Policy,
    "--provider-rounds", "$ProviderRounds"
)

if ($Review -ne "") {
    $argsList += @("--review", $Review)
}

if ($Limit -gt 0) {
    $argsList += @("--limit", "$Limit")
}

if ($SkipWebsite) {
    $argsList += "--skip-website"
}

if ($SkipProviders) {
    $argsList += "--skip-providers"
}

if ($ClayResults -ne "") {
    $argsList += @("--clay-results", $ClayResults)
}

python @argsList
