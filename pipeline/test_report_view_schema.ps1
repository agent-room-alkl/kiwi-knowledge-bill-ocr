$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$schemaPath = Join-Path $root "schemas/report-view.schema.json"
$fixturePath = Join-Path $PSScriptRoot "report_view.valid.fixture.json"

$schema = Get-Content -Raw -LiteralPath $schemaPath
$fixture = Get-Content -Raw -LiteralPath $fixturePath

function Assert-True([bool]$condition, [string]$message) {
    if (-not $condition) {
        throw $message
    }
}

function Test-InvalidMutation([scriptblock]$mutate, [string]$label) {
    $copy = $fixture | ConvertFrom-Json
    & $mutate $copy
    $json = $copy | ConvertTo-Json -Depth 100
    $isValid = $json | Test-Json -Schema $schema -ErrorAction SilentlyContinue
    Assert-True (-not $isValid) "schema accepted invalid fixture mutation: $label"
    Write-Output "ok rejects $label"
}

$isValid = $fixture | Test-Json -Schema $schema -ErrorAction Stop
Assert-True $isValid "complete report-view fixture did not validate"
Write-Output "ok valid complete report-view fixture"

$parsed = $fixture | ConvertFrom-Json
$expectedBlocks = @(
    "meta",
    "observed_cashflow",
    "servicing",
    "category_breakdown",
    "income_sources",
    "recurring_commitments",
    "risk_flags",
    "manual_review",
    "ledger",
    "exceptions"
)
$actualBlocks = @($parsed.PSObject.Properties.Name)
Assert-True ((($actualBlocks | Sort-Object) -join "|") -eq (($expectedBlocks | Sort-Object) -join "|")) "fixture does not contain exactly the ten report-view blocks"
Write-Output "ok exact ten top-level report-view blocks"

Test-InvalidMutation { param($x) $x.meta.masked_account = "12345678" } "unmasked account number"
Test-InvalidMutation { param($x) $x.risk_flags.rows[0].rule_id = "model_guess" } "unknown risk rule id"
Test-InvalidMutation { param($x) $x.ledger[0].vendor_source = "internet" } "unknown vendor source"
Test-InvalidMutation { param($x) $x.ledger[0].subcategory = "invented_subtype" } "unknown subtype"
Test-InvalidMutation { param($x) $x.manual_review.unclear[0].review_type = "business_review" } "review row in wrong manual-review lane"
Test-InvalidMutation { param($x) $x | Add-Member -NotePropertyName extra_block -NotePropertyValue @{} } "unexpected top-level block"

Write-Output "ALL PASS"
