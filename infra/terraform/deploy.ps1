#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Windows PowerShell deployment wrapper for kiwi-knowledge-bill-ocr Terraform infrastructure

.DESCRIPTION
    Automates Terraform init/validate/plan/apply workflow plus Function App code deployment
    and OpenAPI spec generation with environment-specific server URL.

    HARD CONSTRAINTS:
    - Plan/validate only by default
    - DO NOT run -Action apply against production Azure subscriptions
    - Never commits generated OpenAPI files to Git

.PARAMETER Action
    Deployment action to perform:
    - init: Initialize Terraform (local state)
    - validate: Validate Terraform configuration
    - fmt: Format check Terraform files
    - plan: Generate execution plan
    - apply: Apply infrastructure changes (USE WITH CAUTION)
    - deploy-functions: Deploy Function App code
    - generate-openapi: Generate OpenAPI spec with Function URL
    - outputs: Show Terraform outputs
    - destroy: Destroy all resources (USE WITH EXTREME CAUTION)

.PARAMETER VarFile
    Path to terraform.tfvars file (default: terraform.tfvars)

.PARAMETER AutoApprove
    Skip interactive approval for apply/destroy (USE WITH CAUTION)

.EXAMPLE
    .\deploy.ps1 -Action init
    .\deploy.ps1 -Action validate
    .\deploy.ps1 -Action plan
    .\deploy.ps1 -Action apply
    .\deploy.ps1 -Action deploy-functions
    .\deploy.ps1 -Action generate-openapi
    .\deploy.ps1 -Action outputs

.NOTES
    Author: Cursor Agent (Agent Room Task T-19)
    Version: 1.0
    Requires: Terraform >= 1.5.0, Azure CLI, Azure Functions Core Tools
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('init', 'validate', 'fmt', 'plan', 'apply', 'deploy-functions', 'generate-openapi', 'outputs', 'destroy')]
    [string]$Action,

    [Parameter(Mandatory=$false)]
    [string]$VarFile = "terraform.tfvars",

    [Parameter(Mandatory=$false)]
    [switch]$AutoApprove
)

# Set error action preference
$ErrorActionPreference = "Stop"

# Color output functions
function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "[SUCCESS] $Message" -ForegroundColor Green
}

function Write-Warning {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Error-Custom {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

# Check prerequisites
function Test-Prerequisites {
    Write-Info "Checking prerequisites..."

    # Check Terraform
    try {
        $tfVersion = terraform version -json | ConvertFrom-Json
        Write-Success "Terraform $($tfVersion.terraform_version) found"
    }
    catch {
        Write-Error-Custom "Terraform not found. Install from https://www.terraform.io/downloads"
        exit 1
    }

    # Check Azure CLI
    try {
        $azVersion = az version --output json | ConvertFrom-Json
        Write-Success "Azure CLI $($azVersion.'azure-cli') found"
    }
    catch {
        Write-Error-Custom "Azure CLI not found. Install from https://aka.ms/installazurecliwindows"
        exit 1
    }

    # Check Azure CLI authentication
    try {
        $account = az account show --output json | ConvertFrom-Json
        Write-Success "Authenticated to Azure subscription: $($account.name)"
    }
    catch {
        Write-Error-Custom "Not authenticated to Azure. Run: az login"
        exit 1
    }

    # Check Functions Core Tools (only for deploy-functions action)
    if ($Action -eq 'deploy-functions') {
        try {
            $funcVersion = func --version
            Write-Success "Azure Functions Core Tools $funcVersion found"
        }
        catch {
            Write-Error-Custom "Azure Functions Core Tools not found. Install: npm install -g azure-functions-core-tools@4"
            exit 1
        }
    }
}

# Terraform init
function Invoke-TerraformInit {
    Write-Info "Initializing Terraform (local state backend)..."
    terraform init -backend=false
    if ($LASTEXITCODE -ne 0) {
        Write-Error-Custom "Terraform init failed"
        exit $LASTEXITCODE
    }
    Write-Success "Terraform initialized"
}

# Terraform validate
function Invoke-TerraformValidate {
    Write-Info "Validating Terraform configuration..."
    terraform validate
    if ($LASTEXITCODE -ne 0) {
        Write-Error-Custom "Terraform validation failed"
        exit $LASTEXITCODE
    }
    Write-Success "Terraform configuration is valid"
}

# Terraform format check
function Invoke-TerraformFmt {
    Write-Info "Checking Terraform formatting..."
    terraform fmt -check -recursive
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Terraform files are not formatted. Run: terraform fmt -recursive"
        exit $LASTEXITCODE
    }
    Write-Success "Terraform files are properly formatted"
}

# Terraform plan
function Invoke-TerraformPlan {
    Write-Info "Generating Terraform execution plan..."
    
    $varFileArg = ""
    if (Test-Path $VarFile) {
        $varFileArg = "-var-file=$VarFile"
        Write-Info "Using var file: $VarFile"
    }
    else {
        Write-Warning "Var file not found: $VarFile (using defaults + variables.tf)"
    }

    if ($varFileArg) {
        terraform plan -out=tfplan $varFileArg
    }
    else {
        terraform plan -out=tfplan
    }

    if ($LASTEXITCODE -ne 0) {
        Write-Error-Custom "Terraform plan failed"
        exit $LASTEXITCODE
    }
    Write-Success "Terraform plan generated: tfplan"
    Write-Warning "Review the plan above before running -Action apply"
}

# Terraform apply
function Invoke-TerraformApply {
    Write-Warning "============================================"
    Write-Warning "CAUTION: This will create Azure resources"
    Write-Warning "DO NOT run against production subscriptions"
    Write-Warning "============================================"

    if (-not (Test-Path "tfplan")) {
        Write-Error-Custom "No plan file found. Run -Action plan first"
        exit 1
    }

    if (-not $AutoApprove) {
        $confirm = Read-Host "Type 'yes' to apply the plan"
        if ($confirm -ne 'yes') {
            Write-Info "Apply cancelled"
            exit 0
        }
    }

    Write-Info "Applying Terraform plan..."
    terraform apply tfplan
    if ($LASTEXITCODE -ne 0) {
        Write-Error-Custom "Terraform apply failed"
        exit $LASTEXITCODE
    }

    Write-Success "Infrastructure deployed successfully"
    Write-Info "Run -Action outputs to see deployment details"
    Write-Info "Run -Action deploy-functions to deploy Function App code"
}

# Deploy Function App code
function Invoke-DeployFunctions {
    Write-Info "Deploying Function App code..."

    # Get Function App name from Terraform output
    Write-Info "Retrieving Function App name from Terraform..."
    $funcAppName = terraform output -raw function_app_name 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($funcAppName)) {
        Write-Error-Custom "Failed to get Function App name. Run -Action apply first"
        exit 1
    }

    Write-Info "Function App name: $funcAppName"

    # Check if function_app directory exists
    $functionAppPath = "../../function_app"
    if (-not (Test-Path $functionAppPath)) {
        Write-Error-Custom "Function app directory not found: $functionAppPath"
        exit 1
    }

    # Deploy
    Push-Location $functionAppPath
    try {
        Write-Info "Publishing functions to $funcAppName..."
        func azure functionapp publish $funcAppName
        if ($LASTEXITCODE -ne 0) {
            Write-Error-Custom "Function deployment failed"
            exit $LASTEXITCODE
        }
        Write-Success "Functions deployed successfully"
    }
    finally {
        Pop-Location
    }

    Write-Info "Next step: Run -Action generate-openapi to update OpenAPI spec"
}

# Generate OpenAPI spec with Function URL
function Invoke-GenerateOpenAPI {
    Write-Info "Generating OpenAPI spec with Function URL..."

    # Get API base URL from Terraform output
    $apiBaseUrl = terraform output -raw function_api_base_url 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($apiBaseUrl)) {
        Write-Error-Custom "Failed to get Function API URL. Run -Action apply first"
        exit 1
    }

    Write-Info "API Base URL: $apiBaseUrl"

    # Read template OpenAPI spec
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
            description = "Deployed Function App (generated by Terraform deploy.ps1)"
        }
    )

    # Write environment-specific OpenAPI spec (DO NOT commit this)
    $outputPath = "../../foundry/openapi-servicing-$suffix.json"
    $openApiSpec | ConvertTo-Json -Depth 100 | Set-Content $outputPath -Encoding UTF8

    Write-Success "Generated OpenAPI spec: $outputPath"
    Write-Warning "DO NOT commit this file to Git (contains environment-specific URL)"
    Write-Info "Use this file to configure your Foundry agent OpenAPI tool"

    # Display next steps
    Write-Info ""
    Write-Info "Next steps:"
    Write-Info "1. Go to https://ai.azure.com"
    Write-Info "2. Open your Foundry project"
    Write-Info "3. Add OpenAPI tool using: $outputPath"
    Write-Info "4. Create PROJECT CONNECTION with Function key (x-functions-key)"
    Write-Info "5. Paste agent instructions from: foundry/PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt"
}

# Show Terraform outputs
function Show-Outputs {
    Write-Info "Terraform outputs:"
    terraform output
    if ($LASTEXITCODE -ne 0) {
        Write-Error-Custom "Failed to retrieve outputs. Run -Action apply first"
        exit $LASTEXITCODE
    }

    Write-Info ""
    Write-Info "For sensitive outputs (connection strings, keys), run:"
    Write-Info "  terraform output -json"
}

# Terraform destroy
function Invoke-TerraformDestroy {
    Write-Warning "============================================"
    Write-Warning "DANGER: This will DESTROY all resources"
    Write-Warning "All data in storage will be DELETED"
    Write-Warning "============================================"

    if (-not $AutoApprove) {
        $confirm = Read-Host "Type 'DELETE' to destroy all resources"
        if ($confirm -ne 'DELETE') {
            Write-Info "Destroy cancelled"
            exit 0
        }
    }

    Write-Info "Destroying infrastructure..."
    
    $varFileArg = ""
    if (Test-Path $VarFile) {
        $varFileArg = "-var-file=$VarFile"
    }

    if ($AutoApprove) {
        if ($varFileArg) {
            terraform destroy -auto-approve $varFileArg
        }
        else {
            terraform destroy -auto-approve
        }
    }
    else {
        if ($varFileArg) {
            terraform destroy $varFileArg
        }
        else {
            terraform destroy
        }
    }

    if ($LASTEXITCODE -ne 0) {
        Write-Error-Custom "Terraform destroy failed"
        exit $LASTEXITCODE
    }

    Write-Success "All resources destroyed"
}

# Main execution
Write-Info "Kiwi Knowledge Bill OCR - Terraform Deployment Script"
Write-Info "Action: $Action"
Write-Info ""

Test-Prerequisites

switch ($Action) {
    'init' {
        Invoke-TerraformInit
    }
    'validate' {
        Invoke-TerraformValidate
    }
    'fmt' {
        Invoke-TerraformFmt
    }
    'plan' {
        Invoke-TerraformInit
        Invoke-TerraformValidate
        Invoke-TerraformPlan
    }
    'apply' {
        Invoke-TerraformApply
    }
    'deploy-functions' {
        Invoke-DeployFunctions
    }
    'generate-openapi' {
        Invoke-GenerateOpenAPI
    }
    'outputs' {
        Show-Outputs
    }
    'destroy' {
        Invoke-TerraformDestroy
    }
}

Write-Success "Action '$Action' completed successfully"
