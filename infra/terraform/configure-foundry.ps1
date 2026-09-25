#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Post-deployment script for AI Foundry agent and tool configuration

.DESCRIPTION
    Automates what can be scripted after Terraform creates the Foundry infrastructure:
    1. Updates OpenAPI spec with the deployed Function App URL
    2. Retrieves Function App key for OpenAPI authentication
    3. Provides step-by-step portal instructions for manual configuration
    
    CANNOT BE FULLY AUTOMATED:
    - Agent creation (no Azure CLI/API support)
    - OpenAPI tool attachment (no Azure CLI/API support)
    - Agent instructions paste (must be done in portal)

.PARAMETER SkipOpenAPIUpdate
    Skip updating the OpenAPI spec file (if already done)

.EXAMPLE
    .\configure-foundry.ps1
    .\configure-foundry.ps1 -SkipOpenAPIUpdate

.NOTES
    Author: Cursor Agent (Agent Room Task T-23)
    Version: 1.0
    Requires: Terraform outputs available, Azure CLI, Azure Functions Core Tools
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$false)]
    [switch]$SkipOpenAPIUpdate
)

$ErrorActionPreference = "Stop"

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "[SUCCESS] $Message" -ForegroundColor Green
}

function Write-Warning-Custom {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Error-Custom {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Write-Step {
    param([string]$Message)
    Write-Host "`n========================================" -ForegroundColor Magenta
    Write-Host "  $Message" -ForegroundColor Magenta
    Write-Host "========================================`n" -ForegroundColor Magenta
}

# Check if Terraform state exists
if (-not (Test-Path ".terraform")) {
    Write-Error-Custom "Terraform not initialized. Run: .\deploy.ps1 -Action init"
    exit 1
}

# Check if Foundry resources were created
Write-Info "Checking if AI Foundry resources were created..."
$foundryProjectName = terraform output -raw ai_foundry_project_name 2>$null
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($foundryProjectName)) {
    Write-Error-Custom "AI Foundry resources not found. Set create_ai_foundry_resources=true in terraform.tfvars and run: .\deploy.ps1 -Action apply"
    exit 1
}

Write-Success "Found AI Foundry Project: $foundryProjectName"

# Get Function App details
Write-Info "Retrieving Function App details from Terraform..."
$funcAppName = terraform output -raw function_app_name 2>$null
$apiBaseUrl = terraform output -raw function_api_base_url 2>$null
$foundryPortalUrl = terraform output -raw ai_foundry_portal_url 2>$null

if ([string]::IsNullOrWhiteSpace($funcAppName) -or [string]::IsNullOrWhiteSpace($apiBaseUrl)) {
    Write-Error-Custom "Failed to get Function App details. Ensure Terraform apply completed successfully"
    exit 1
}

Write-Success "Function App: $funcAppName"
Write-Success "API Base URL: $apiBaseUrl"

# Step 1: Update OpenAPI spec
if (-not $SkipOpenAPIUpdate) {
    Write-Step "STEP 1: Updating OpenAPI Spec"
    
    $openApiTemplatePath = "../../foundry/openapi-servicing.json"
    if (-not (Test-Path $openApiTemplatePath)) {
        Write-Error-Custom "OpenAPI template not found: $openApiTemplatePath"
        exit 1
    }
    
    # Read and parse JSON
    $openApiSpec = Get-Content $openApiTemplatePath -Raw | ConvertFrom-Json
    
    # Get unique suffix for output filename
    $suffix = terraform output -raw unique_suffix 2>$null
    if ([string]::IsNullOrWhiteSpace($suffix)) {
        $suffix = "deployed"
    }
    
    # Update server URL
    $openApiSpec.servers = @(
        @{
            url = $apiBaseUrl
            description = "Deployed Function App (auto-configured for Foundry)"
        }
    )
    
    # Write environment-specific OpenAPI spec
    $outputPath = "../../foundry/openapi-servicing-$suffix.json"
    $openApiSpec | ConvertTo-Json -Depth 100 | Set-Content $outputPath -Encoding UTF8
    
    Write-Success "Generated OpenAPI spec: $outputPath"
    Write-Warning-Custom "DO NOT commit this file to Git (contains environment-specific URL)"
}
else {
    Write-Info "Skipping OpenAPI spec update (use -SkipOpenAPIUpdate to skip)"
}

# Step 2: Get Function key
Write-Step "STEP 2: Retrieving Function App Key"

Write-Info "Fetching Function App master key..."
$funcKey = az functionapp keys list `
    --name $funcAppName `
    --resource-group (terraform output -raw resource_group_name) `
    --query "functionKeys.default" `
    --output tsv 2>$null

if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($funcKey)) {
    Write-Warning-Custom "Could not retrieve Function key via Azure CLI. Retrieve manually with:"
    Write-Host "    func azure functionapp list-functions $funcAppName --show-keys" -ForegroundColor Yellow
    $funcKey = "[RETRIEVE_MANUALLY]"
}
else {
    Write-Success "Function key retrieved (will be displayed in final summary)"
}

# Step 3: Display manual configuration steps
Write-Step "STEP 3: Manual Portal Configuration Required"

Write-Host @"

AI Foundry Agent and OpenAPI tool attachment CANNOT be automated via
Terraform, Azure CLI, or REST API. You must complete these steps manually
in the Azure AI Portal:

"@ -ForegroundColor Yellow

Write-Host "`n=== Portal Configuration Checklist ===`n" -ForegroundColor Cyan

Write-Host "1. Open Azure AI Portal:" -ForegroundColor White
Write-Host "   $foundryPortalUrl`n" -ForegroundColor Green

Write-Host "2. In the project, verify connected resources:" -ForegroundColor White
Write-Host "   - Storage Account: $(terraform output -raw storage_account_name)" -ForegroundColor Gray
Write-Host "   - Key Vault: $(terraform output -raw ai_foundry_key_vault_name)" -ForegroundColor Gray

$openAiEndpoint = terraform output -raw ai_foundry_openai_endpoint 2>$null
if (-not [string]::IsNullOrWhiteSpace($openAiEndpoint)) {
    Write-Host "   - Azure OpenAI: $openAiEndpoint" -ForegroundColor Gray
    $modelDeployment = terraform output -raw ai_foundry_model_deployment_name 2>$null
    Write-Host "   - Model Deployment: $modelDeployment`n" -ForegroundColor Gray
}
else {
    Write-Host "   - Azure OpenAI: [NOT DEPLOYED - set foundry_model_name in tfvars]`n" -ForegroundColor Yellow
}

Write-Host "3. Create a Foundry Agent:" -ForegroundColor White
Write-Host "   - In project, go to 'Agents' -> 'Create new agent'" -ForegroundColor Gray
Write-Host "   - Give it a descriptive name (e.g., 'Kiwi Bill OCR Assistant')" -ForegroundColor Gray
if (-not [string]::IsNullOrWhiteSpace($openAiEndpoint)) {
    Write-Host "   - Select model deployment: $(terraform output -raw ai_foundry_model_deployment_name)`n" -ForegroundColor Gray
}
else {
    Write-Host "   - Select an available model deployment`n" -ForegroundColor Gray
}

Write-Host "4. Attach the OpenAPI tool to the agent:" -ForegroundColor White
Write-Host "   a) In agent settings, go to 'Tools' -> 'Add tool' -> 'OpenAPI'" -ForegroundColor Gray

$suffix = terraform output -raw unique_suffix 2>$null
if ([string]::IsNullOrWhiteSpace($suffix)) { $suffix = "deployed" }
$openApiFile = "foundry/openapi-servicing-$suffix.json"

Write-Host "   b) Upload OpenAPI spec file: $openApiFile" -ForegroundColor Gray
Write-Host "   c) Create PROJECT CONNECTION for authentication:" -ForegroundColor Gray
Write-Host "      - Name: 'kiwi-ocr-function-key' (or similar)" -ForegroundColor Gray
Write-Host "      - Type: 'API Key'" -ForegroundColor Gray
Write-Host "      - Header name: x-functions-key" -ForegroundColor Gray

if ($funcKey -ne "[RETRIEVE_MANUALLY]") {
    Write-Host "      - Key value: $funcKey" -ForegroundColor Green
    Write-Warning-Custom "DO NOT commit this key to Git or share it publicly"
}
else {
    Write-Host "      - Key value: [Run command below to retrieve]`n" -ForegroundColor Yellow
    Write-Host "        func azure functionapp list-functions $funcAppName --show-keys`n" -ForegroundColor Yellow
}

Write-Host "   d) Select the connection for the OpenAPI tool (do NOT paste key into tool)`n" -ForegroundColor Gray

Write-Host "5. Paste agent instructions:" -ForegroundColor White
Write-Host "   - In agent settings, go to 'Instructions'" -ForegroundColor Gray
Write-Host "   - Copy the full content from:" -ForegroundColor Gray
Write-Host "     foundry/PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt" -ForegroundColor Green
Write-Host "   - Paste into the Instructions field and save`n" -ForegroundColor Gray

Write-Host "6. Test the agent:" -ForegroundColor White
Write-Host "   - Use the 'Test' button in the agent interface" -ForegroundColor Gray
Write-Host "   - Try: 'Extract and analyze a sample statement from vikas-samples'" -ForegroundColor Gray
Write-Host "   - Verify the agent can call the extract_and_normalize tool`n" -ForegroundColor Gray

Write-Step "Configuration Summary"

Write-Host "Terraform Resources Created:" -ForegroundColor Cyan
Write-Host "  - Resource Group: $(terraform output -raw resource_group_name)" -ForegroundColor Gray
Write-Host "  - Function App: $funcAppName" -ForegroundColor Gray
Write-Host "  - AI Foundry Project: $foundryProjectName" -ForegroundColor Gray
if (-not [string]::IsNullOrWhiteSpace($openAiEndpoint)) {
    Write-Host "  - Azure OpenAI: $(terraform output -raw ai_foundry_openai_endpoint)" -ForegroundColor Gray
    Write-Host "  - Model: $(terraform output -raw ai_foundry_model_deployment_name)" -ForegroundColor Gray
}
Write-Host ""

Write-Host "Files for Portal Configuration:" -ForegroundColor Cyan
Write-Host "  - OpenAPI Spec: $openApiFile" -ForegroundColor Gray
Write-Host "  - Agent Instructions: foundry/PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt" -ForegroundColor Gray
Write-Host "  - Setup Guide: foundry/HOW_TO_HANG_TOOLS.md" -ForegroundColor Gray
Write-Host ""

Write-Host "Portal URL:" -ForegroundColor Cyan
Write-Host "  $foundryPortalUrl" -ForegroundColor Green
Write-Host ""

Write-Success "Pre-configuration complete. Follow the manual steps above to finish setup."

Write-Host "`nFor detailed setup instructions with screenshots, see:" -ForegroundColor Cyan
Write-Host "  foundry/HOW_TO_HANG_TOOLS.md`n" -ForegroundColor Green
