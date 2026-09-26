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
    - configure-foundry: Run post-deployment Foundry configuration helper
    - outputs: Show Terraform outputs
    - destroy: Destroy all resources (USE WITH EXTREME CAUTION)
    - all: One-click orchestration - runs init/validate/plan, then apply/deploy-functions/generate-openapi/outputs with a yes/no confirmation gate before each state-changing step (use -AutoApprove for fully unattended)

.PARAMETER VarFile
    Path to terraform.tfvars file (default: terraform.tfvars)

.PARAMETER AutoApprove
    Skip interactive approval for apply/destroy (USE WITH CAUTION)

.PARAMETER AllowDestroy
    Only meaningful with -Action all. Explicitly permit a plan that deletes/replaces resources.
    Without it, -Action all aborts on any planned destroy (and refuses outright under -AutoApprove).

.EXAMPLE
    .\deploy.ps1 -Action init
    .\deploy.ps1 -Action validate
    .\deploy.ps1 -Action plan
    .\deploy.ps1 -Action apply
    .\deploy.ps1 -Action deploy-functions
    .\deploy.ps1 -Action generate-openapi
    .\deploy.ps1 -Action configure-foundry
    .\deploy.ps1 -Action outputs
    .\deploy.ps1 -Action all
    .\deploy.ps1 -Action all -AutoApprove

.NOTES
    Author: Cursor Agent (Agent Room Task T-19)
    Version: 1.0
    Requires: Terraform >= 1.5.0, Azure CLI, Azure Functions Core Tools
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet('init', 'validate', 'fmt', 'plan', 'apply', 'deploy-functions', 'generate-openapi', 'configure-foundry', 'outputs', 'destroy', 'all')]
    [string]$Action,

    [Parameter(Mandatory=$false)]
    [string]$VarFile = "terraform.tfvars",

    [Parameter(Mandatory=$false)]
    [switch]$AutoApprove,

    [Parameter(Mandatory=$false)]
    [switch]$AllowDestroy
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
        
        # Export ARM_SUBSCRIPTION_ID for azurerm provider 4.x
        $env:ARM_SUBSCRIPTION_ID = $account.id
        $env:ARM_TENANT_ID = $account.tenantId
        Write-Info "Exported ARM_SUBSCRIPTION_ID=$($account.id)"
        Write-Info "Exported ARM_TENANT_ID=$($account.tenantId)"
    }
    catch {
        Write-Error-Custom "Not authenticated to Azure. Run: az login"
        exit 1
    }

    # Check Functions Core Tools (for deploy-functions and the all-in-one orchestration)
    if ($Action -eq 'deploy-functions' -or $Action -eq 'all') {
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

# Inspect the saved plan for resources that will be deleted or replaced.
# Returns an array of resource addresses whose planned actions include 'delete'
# (a replacement shows both 'delete' and 'create', so this covers replacements too).
function Get-PlanDestroyAddresses {
    if (-not (Test-Path "tfplan")) {
        return @()
    }

    $planJsonRaw = terraform show -json tfplan
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($planJsonRaw)) {
        Write-Error-Custom "Failed to read plan JSON (terraform show -json tfplan)"
        exit 1
    }

    try {
        $plan = $planJsonRaw | ConvertFrom-Json
    }
    catch {
        Write-Error-Custom "Failed to parse plan JSON: $_"
        exit 1
    }

    $addresses = @()
    foreach ($rc in $plan.resource_changes) {
        if ($rc.change.actions -contains 'delete') {
            $addresses += $rc.address
        }
    }
    return ,$addresses
}

# Terraform apply
function Invoke-TerraformApply {
    param([switch]$SkipConfirm)

    Write-Warning "============================================"
    Write-Warning "CAUTION: This will create Azure resources"
    Write-Warning "DO NOT run against production subscriptions"
    Write-Warning "============================================"

    if (-not (Test-Path "tfplan")) {
        Write-Error-Custom "No plan file found. Run -Action plan first"
        exit 1
    }

    if (-not $AutoApprove -and -not $SkipConfirm) {
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
    Write-Info "Run -Action configure-foundry to set up AI Foundry (if create_ai_foundry_resources=true)"
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

# One-click orchestration: run the whole pipeline with confirmation gates
function Invoke-All {
    Write-Info "============================================"
    Write-Info "ONE-CLICK ORCHESTRATION (-Action all)"
    Write-Info "Sequence: init -> validate -> plan -> [confirm] apply -> [confirm] deploy-functions -> [confirm] generate-openapi -> outputs"
    if ($AutoApprove) {
        Write-Warning "-AutoApprove is set: all confirmation gates are SKIPPED (fully unattended). This WILL create billable Azure resources."
    }
    Write-Info "============================================"

    # 1-3. Always-safe steps (no resources created)
    Invoke-TerraformInit
    Invoke-TerraformValidate
    Invoke-TerraformPlan

    # 4. Destroy guard: the plan must not delete/replace resources unless explicitly allowed.
    $destroyAddresses = Get-PlanDestroyAddresses
    if ($destroyAddresses.Count -gt 0) {
        Write-Error-Custom "This plan will DELETE or REPLACE $($destroyAddresses.Count) resource(s):"
        foreach ($addr in $destroyAddresses) {
            Write-Host "  - $addr" -ForegroundColor Red
        }
        if ($AutoApprove -and -not $AllowDestroy) {
            Write-Error-Custom "Refusing to apply a plan with destroys under -AutoApprove. Re-run with -AllowDestroy to explicitly permit these deletions."
            exit 1
        }
        if (-not $AllowDestroy) {
            $destroyConfirm = Read-Host "These resources will be DESTROYED. Type 'DESTROY' to proceed, anything else to abort"
            if ($destroyConfirm -ne 'DESTROY') {
                Write-Info "Aborted before apply due to planned destroys. No changes were applied."
                return
            }
        }
        else {
            Write-Warning "-AllowDestroy is set: proceeding with the deletions listed above."
        }
    }
    else {
        Write-Success "Destroy check: plan contains 0 resources to delete/replace."
    }

    # 5. Gate: apply (creates billable resources)
    $doApply = $AutoApprove
    if (-not $AutoApprove) {
        Write-Warning "Target subscription: $env:ARM_SUBSCRIPTION_ID"
        Write-Warning "Review the plan above and confirm it targets the correct subscription."
        $ans = Read-Host "Apply this plan now? This CREATES billable Azure resources. Type 'yes' to apply, anything else to stop"
        $doApply = ($ans -eq 'yes')
    }
    if (-not $doApply) {
        Write-Info "Stopped before apply. No resources were created. Re-run '-Action all' (or '-Action apply') when ready."
        return
    }
    Invoke-TerraformApply -SkipConfirm

    # 5. Gate: deploy Function App code
    $doFunctions = $AutoApprove
    if (-not $AutoApprove) {
        $ans = Read-Host "Deploy Function App code now? Type 'yes' to deploy, anything else to skip"
        $doFunctions = ($ans -eq 'yes')
    }
    if ($doFunctions) {
        Invoke-DeployFunctions
    }
    else {
        Write-Warning "Skipped function deployment. Run '-Action deploy-functions' later when ready."
    }

    # 6. Gate: generate OpenAPI spec with the deployed Function URL
    $doOpenApi = $AutoApprove
    if (-not $AutoApprove) {
        $ans = Read-Host "Generate OpenAPI spec with the Function URL now? Type 'yes' to generate, anything else to skip"
        $doOpenApi = ($ans -eq 'yes')
    }
    if ($doOpenApi) {
        Invoke-GenerateOpenAPI
    }
    else {
        Write-Warning "Skipped OpenAPI generation. Run '-Action generate-openapi' later when ready."
    }

    # 7. Show outputs
    Show-Outputs

    Write-Success "One-click orchestration finished."
    Write-Info "Reminder: the Foundry agent + OpenAPI tool wiring is a manual step in https://ai.azure.com (cannot be automated by Terraform)."
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
    'configure-foundry' {
        Write-Info "Running Foundry configuration helper..."
        & "$PSScriptRoot\configure-foundry.ps1"
        if ($LASTEXITCODE -ne 0) {
            Write-Error-Custom "Foundry configuration helper failed"
            exit $LASTEXITCODE
        }
    }
    'outputs' {
        Show-Outputs
    }
    'destroy' {
        Invoke-TerraformDestroy
    }
    'all' {
        Invoke-All
    }
}

Write-Success "Action '$Action' completed successfully"
