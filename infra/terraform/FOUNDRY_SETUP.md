# Azure AI Foundry Terraform Setup - Technical Documentation

## Summary

This document explains how Terraform creates Azure AI Foundry infrastructure and what manual steps remain for the `kiwi-knowledge-bill-ocr` project.

## Architecture Overview

### What Terraform Creates

When `create_ai_foundry_resources = true`:

```
Resource Group
├── Storage Account (shared with Function App)
├── Application Insights (shared)
├── Key Vault (for Foundry secrets)
├── AI Foundry Hub (ML Workspace type: Hub)
├── AI Foundry Project (ML Workspace type: Project, linked to Hub)
├── Azure OpenAI Account (Cognitive Services, optional)
└── Model Deployment (under OpenAI account, optional)
```

### Resource Dependencies

```
Hub requires:
  - Storage Account
  - Key Vault (created automatically when create_ai_foundry_resources=true)
  - Application Insights

Project requires:
  - Hub (parent workspace)

Model Deployment requires:
  - Azure OpenAI Cognitive Services account (NOT the ML Project)
```

## Known Issues Fixed

### Issue 1: Model Deployment Parent ID ✅ FIXED

**Original Problem:**
```hcl
resource "azapi_resource" "model_deployment" {
  type      = "Microsoft.CognitiveServices/accounts/deployments@2024-10-01"
  parent_id = azapi_resource.ai_project[0].id  # WRONG!
  ...
}
```

The model deployment was parented under the AI Project (ML workspace), but Azure OpenAI/Cognitive Services deployments must be under a Cognitive Services account.

**Solution:**
Create a separate `azurerm_cognitive_account` with `kind = "OpenAI"` and use `azurerm_cognitive_deployment` resource:

```hcl
resource "azurerm_cognitive_account" "openai" {
  name     = "${var.project_name}-openai-${local.suffix}"
  kind     = "OpenAI"
  sku_name = "S0"
  ...
}

resource "azurerm_cognitive_deployment" "model" {
  name                 = var.foundry_deployment_name
  cognitive_account_id = azurerm_cognitive_account.openai[0].id
  
  model {
    format  = "OpenAI"
    name    = var.foundry_model_name
    version = var.foundry_model_version
  }
  ...
}
```

**Why This Matters:**
- The OpenAI account is a separate Cognitive Services resource
- AI Foundry Projects can *connect* to OpenAI accounts but don't own them
- Deployments must live under the Cognitive Services account, not the ML workspace

### Issue 2: Missing Key Vault ✅ FIXED

**Original Problem:**
```hcl
variable "key_vault_id" {
  description = "Existing Key Vault resource ID for AI Foundry (required if create_ai_foundry_resources is true)"
  default     = ""
}

resource "azapi_resource" "ai_hub" {
  body = {
    properties = {
      keyVault = var.key_vault_id != "" ? var.key_vault_id : null  # Defaults to null!
      ...
    }
  }
}
```

Hub creation would fail or be unreliable without a Key Vault.

**Solution:**
Automatically create a Key Vault when Foundry resources are enabled:

```hcl
resource "azurerm_key_vault" "foundry" {
  count                      = var.create_ai_foundry_resources ? 1 : 0
  name                       = substr("${var.project_name}-kv-${local.suffix}", 0, 24)
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 7
  purge_protection_enabled   = false
  ...
}

resource "azapi_resource" "ai_hub" {
  body = {
    properties = {
      keyVault = azurerm_key_vault.foundry[0].id  # Always present when Hub is created
      ...
    }
  }
}
```

**Why This Matters:**
- AI Foundry Hub requires Key Vault for connection strings and secrets
- Creating it in-module ensures correct configuration
- No manual pre-creation needed

### Issue 3: Agent + Tool Automation ✅ DOCUMENTED

**The Reality:**
Azure AI Foundry does **NOT** provide any API or CLI for:
- Creating agents
- Attaching OpenAPI tools to agents
- Setting agent instructions

**What CAN Be Automated:**
- ✅ Hub creation (azapi provider)
- ✅ Project creation (azapi provider)
- ✅ Azure OpenAI account creation (azurerm provider)
- ✅ Model deployment (azurerm provider)
- ✅ OpenAPI spec generation with Function URL (PowerShell script)
- ✅ Function key retrieval (Azure CLI)

**What MUST Be Manual:**
- ❌ Agent creation (portal only)
- ❌ OpenAPI tool upload (portal only)
- ❌ Tool authentication (PROJECT CONNECTION in portal)
- ❌ Agent instructions (portal only)

**Solution:**
Created `configure-foundry.ps1` script that:
1. Automates everything that CAN be automated
2. Provides a clear checklist for portal steps
3. Displays all required values (URLs, keys, resource names)
4. Links to detailed setup guide

Integrated into `deploy.ps1` as `-Action configure-foundry`.

## Resource Group Scenarios

### Scenario 1: Fresh Foundry Stack in New RG

```hcl
# terraform.tfvars
use_existing_resource_group = false
create_ai_foundry_resources = true
foundry_model_name          = "gpt-4o"
```

Creates:
- New resource group with all resources
- Function App + Document Intelligence
- AI Foundry Hub + Project + Key Vault
- Azure OpenAI + Model Deployment

**Use Case:** Green-field deployment, Robin creating a new environment from scratch.

### Scenario 2: Add Foundry to Existing Function RG

```hcl
# terraform.tfvars
use_existing_resource_group = true
resource_group_name         = "kiwidemo-rg-b923ue"
create_ai_foundry_resources = true
foundry_model_name          = "gpt-4o"
```

Creates:
- Foundry resources in existing RG
- Function App is already there (Terraform imports or avoids recreating)

**Use Case:** Robin's existing demo RG `kiwidemo-rg-b923ue` with Function `kiwidemo-func-b923ue`.

**Important:** If the Function App already exists, Terraform will try to create it and fail. To avoid:
1. Use a different `unique_suffix` so Function App name doesn't collide
2. Or manually import existing Function App into state (advanced)
3. Or separate the Foundry-only resources into a separate module (future enhancement)

**Recommended Approach for Existing Function:**
Use a separate resource group for Foundry to avoid naming collisions:

```hcl
use_existing_resource_group = false  # Creates new RG for Foundry
create_ai_foundry_resources = true
```

Then manually configure the OpenAPI tool to point at the existing Function App URL.

### Scenario 3: Function Only (No Foundry)

```hcl
# terraform.tfvars
create_ai_foundry_resources = false
```

Creates only:
- Function App infrastructure (Storage, Document Intelligence, App Service Plan, Function App, App Insights)

**Use Case:** Testing Function App in isolation, or using existing manual Foundry setup.

## Terraform Resource Types Used

### Standard Azure Resources (azurerm provider)

| Resource | Type | Notes |
|----------|------|-------|
| Storage Account | `azurerm_storage_account` | Shared by Function and Foundry |
| Key Vault | `azurerm_key_vault` | Created when Foundry enabled |
| Application Insights | `azurerm_application_insights` | Shared by Function and Foundry |
| Document Intelligence | `azurerm_cognitive_account` (kind=FormRecognizer) | For OCR |
| Azure OpenAI | `azurerm_cognitive_account` (kind=OpenAI) | For AI models |
| Model Deployment | `azurerm_cognitive_deployment` | GPT-4o, GPT-4, etc. |
| Function App | `azurerm_linux_function_app` | Python 3.11 |
| App Service Plan | `azurerm_service_plan` | Linux, B1 SKU |

### Preview Resources (azapi provider)

| Resource | Type | API Version | Notes |
|----------|------|-------------|-------|
| AI Foundry Hub | `Microsoft.MachineLearningServices/workspaces` | 2024-10-01-preview | kind=Hub |
| AI Foundry Project | `Microsoft.MachineLearningServices/workspaces` | 2024-10-01-preview | kind=Project |

**Why azapi for Hub/Project?**
- These are preview features not yet in the azurerm provider
- Using azapi allows Terraform to manage them before GA
- API versions may change before GA (monitor Azure updates)

## Variable Configuration

### Minimal Foundry Setup

```hcl
# terraform.tfvars
project_name                = "kiwi-ocr"
location                    = "australiaeast"
create_ai_foundry_resources = true
foundry_model_name          = "gpt-4o"
foundry_model_version       = "2024-05-13"
foundry_deployment_name     = "gpt-4o"
```

### Without Model Deployment

```hcl
create_ai_foundry_resources = true
foundry_model_name          = ""  # Empty = skip model deployment
```

This creates Hub + Project + Key Vault, but no OpenAI account. You can add OpenAI manually or use an existing account.

### Common Model Configurations

```hcl
# GPT-4o (latest, recommended)
foundry_model_name       = "gpt-4o"
foundry_model_version    = "2024-05-13"
foundry_deployment_name  = "gpt-4o"

# GPT-4 Turbo
foundry_model_name       = "gpt-4"
foundry_model_version    = "turbo-2024-04-09"
foundry_deployment_name  = "gpt-4-turbo"

# GPT-3.5 Turbo (cost-effective)
foundry_model_name       = "gpt-35-turbo"
foundry_model_version    = "0125"
foundry_deployment_name  = "gpt-35-turbo"
```

**Model Availability:** Check https://learn.microsoft.com/azure/ai-services/openai/concepts/models for region-specific availability.

## Validation Commands

### Format Check
```bash
cd infra/terraform
terraform fmt -check -recursive
```

### Initialize (No Backend)
```bash
terraform init -backend=false
```

### Validate Syntax
```bash
terraform validate
```

### Plan (Dry Run)
```bash
# Requires Azure credentials but does NOT apply changes
terraform plan -var-file=terraform.tfvars -out=tfplan
```

**Note:** Planning requires Azure credentials (`az login`) and may fail if:
- Subscription ID not set
- Region doesn't support Foundry
- Resource names already exist (change `unique_suffix`)

### Plan Without Real Azure
To validate without Azure credentials (syntax/type checking only):
```bash
export ARM_SKIP_PROVIDER_REGISTRATION=true
terraform validate
```

This does **NOT** check:
- Resource availability in region
- Quota limits
- Name uniqueness
- API versions

## Deployment Workflow (End-to-End)

### Step 1: Configure
```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars
```

### Step 2: Validate
```bash
terraform init -backend=false
terraform validate
terraform fmt -check
```

### Step 3: Plan
```bash
terraform plan -var-file=terraform.tfvars -out=tfplan
# Review the plan output
```

### Step 4: Apply (Caution!)
```bash
terraform apply tfplan
```

**DO NOT RUN AGAINST PRODUCTION.** This creates real Azure resources and incurs costs.

### Step 5: Deploy Function Code
```bash
FUNC_APP_NAME=$(terraform output -raw function_app_name)
cd ../../function_app
func azure functionapp publish $FUNC_APP_NAME
```

### Step 6: Configure Foundry
```bash
cd ../infra/terraform
./configure-foundry.ps1
```

Or via deploy.ps1:
```powershell
.\deploy.ps1 -Action configure-foundry
```

### Step 7: Manual Portal Steps
Follow the checklist from `configure-foundry.ps1` output:
1. Open Azure AI Portal (URL from script)
2. Create agent in project
3. Upload OpenAPI spec
4. Create PROJECT CONNECTION with Function key
5. Paste agent instructions
6. Test the agent

## Testing Without Azure

### Syntax Validation (No Azure Needed)
```bash
terraform fmt -check -recursive
terraform init -backend=false
terraform validate
```

These commands validate:
- ✅ HCL syntax
- ✅ Resource type names
- ✅ Variable types
- ✅ Output references
- ✅ Provider versions

These commands DO NOT validate:
- ❌ Azure credentials
- ❌ Resource availability
- ❌ Quota limits
- ❌ Region support
- ❌ API versions (some checks, not comprehensive)

### Mock Plan (Limited)
You can't fully plan without Azure credentials, but you can:
1. Check syntax: `terraform validate`
2. Review resource graph: Look at `depends_on` chains in code
3. Manual review: Read the `.tf` files

## Post-Apply Verification

### Check Resources Created
```bash
# Resource group
az group show --name $(terraform output -raw resource_group_name)

# Function App
az functionapp show \
  --name $(terraform output -raw function_app_name) \
  --resource-group $(terraform output -raw resource_group_name)

# AI Foundry Project (if created)
az ml workspace show \
  --name $(terraform output -raw ai_foundry_project_name) \
  --resource-group $(terraform output -raw resource_group_name)

# Azure OpenAI (if created)
az cognitiveservices account show \
  --name $(terraform output -raw ai_foundry_openai_endpoint | cut -d. -f1 | cut -d/ -f3) \
  --resource-group $(terraform output -raw resource_group_name)
```

### Test Function App
```bash
FUNC_KEY=$(func azure functionapp list-functions $(terraform output -raw function_app_name) --show-keys | grep default | awk '{print $3}')
API_URL=$(terraform output -raw function_api_base_url)

curl -H "x-functions-key: $FUNC_KEY" "$API_URL/health"
```

### Test Agent (Manual)
1. Go to Azure AI Portal: `terraform output ai_foundry_portal_url`
2. Open the project
3. Create and test agent with OpenAPI tool

## Troubleshooting

### Validation Errors

**"Resource type not found"**
- Run `terraform init` to download providers
- Check provider versions in `main.tf` match available versions

**"Invalid reference"**
- Check variable names in `variables.tf`
- Check output names in `outputs.tf`
- Ensure resources exist before referencing (check `count` conditions)

### Plan/Apply Errors

**"Region does not support AI Foundry"**
- Change `location` to: `australiaeast`, `eastus2`, or `westeurope`
- Or set `create_ai_foundry_resources = false`

**"Key Vault name already exists"**
- Key Vault names are globally unique
- Change `unique_suffix` in `terraform.tfvars`
- Or leave `unique_suffix = ""` to generate random

**"Model not available in region"**
- Check model availability: https://learn.microsoft.com/azure/ai-services/openai/concepts/models
- Try `gpt-35-turbo` (widely available)
- Or set `foundry_model_name = ""` to skip model deployment

**"Insufficient quota"**
- Request quota increase in Azure Portal
- Or use a different model with available quota
- Or deploy in a different region

### Runtime Errors

**Function App 404 errors**
- Deploy code: `func azure functionapp publish $FUNC_APP_NAME`
- Check runtime: Should be Python 3.11
- Check app setting: `AzureWebJobsFeatureFlags = "EnableWorkerIndexing"`

**Agent cannot call Function**
- Verify OpenAPI spec has correct URL
- Verify PROJECT CONNECTION is selected (not pasted key)
- Test Function App directly with curl (see Post-Apply Verification)
- Check Function App logs: `func azure functionapp logstream $FUNC_APP_NAME`

## Security Notes

### Secrets in State
Terraform state contains:
- Storage connection strings
- Function App keys
- Document Intelligence keys
- Azure OpenAI keys

**DO NOT commit** `terraform.tfstate` or `terraform.tfstate.backup`.

### Remote State (Production)
Before production use, configure remote state:
```hcl
terraform {
  backend "azurerm" {
    resource_group_name  = "terraform-state-rg"
    storage_account_name = "tfstateunique"
    container_name       = "tfstate"
    key                  = "kiwi-knowledge-bill-ocr.tfstate"
    use_azuread_auth     = true
  }
}
```

### Key Rotation
After demo/testing:
1. Rotate Function App keys
2. Rotate Storage account keys
3. Update OpenAPI tool authentication in Foundry portal

## Cost Implications

### Foundry Resources

| Resource | SKU | Est. Cost (AUD/month) |
|----------|-----|------------------------|
| Key Vault | Standard | ~$0.15 (first 10k ops free) |
| AI Foundry Hub | N/A | Free (charges come from linked resources) |
| AI Foundry Project | N/A | Free (charges come from linked resources) |
| Azure OpenAI (GPT-4o) | S0 | Usage-based (~$0.015/1k tokens) |

**Total additional for Foundry:** ~$0.15/month + model usage.

### Existing Function App Costs
See main README for Function App cost breakdown (~$25-35/month baseline).

## Next Steps / Future Enhancements

### Separate Modules
Split into:
- `modules/function-app/` - Function infrastructure
- `modules/ai-foundry/` - Foundry infrastructure

This allows:
- Separate state files
- Independent lifecycle
- Easier existing Function App integration

### Agent Automation
If Azure releases Agent APIs:
- Add agent creation to Terraform
- Add tool attachment to Terraform
- Remove manual portal steps

### Remote State
Add remote state configuration for team use:
- Azure Storage backend
- State locking
- Team access controls

### CI/CD Integration
- GitHub Actions workflow for validation
- Automated plan on PR
- Manual approval for apply
- Separate workflows for Function code deployment

## References

- [Azure AI Foundry Documentation](https://learn.microsoft.com/azure/ai-studio/)
- [Azure OpenAI Models](https://learn.microsoft.com/azure/ai-services/openai/concepts/models)
- [Terraform azurerm Provider](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs)
- [Terraform azapi Provider](https://registry.terraform.io/providers/azure/azapi/latest/docs)
- [Azure ML Workspace API](https://learn.microsoft.com/rest/api/azureml/)
