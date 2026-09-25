# Foundry-Only Deployment with Existing Backend

## Overview

This guide explains how to deploy ONLY AI Foundry resources (Hub, Project, Key Vault, Azure OpenAI) into an existing resource group that already has a running Function App and backend infrastructure.

**Use Case**: You have an existing deployment with Function App, Storage, Document Intelligence, etc., and want to add AI Foundry capabilities WITHOUT recreating or touching the existing resources.

## Quick Start

### 1. Configure Variables

Copy the example configuration:

```bash
cp terraform.tfvars.foundry-existing-backend-example terraform.tfvars
```

Edit `terraform.tfvars` with your actual resource names:

```hcl
# Core config
subscription_id = "your-subscription-id"
project_name    = "your-project-name"
unique_suffix   = "fnd01"  # NEW suffix for Foundry resources
location        = "australiaeast"

# Use existing resource group
use_existing_resource_group = true
resource_group_name         = "your-existing-rg"

# Use existing backend resources
use_existing_backend               = true
existing_function_app_name         = "your-func-app-name"
existing_storage_account_name      = "yourstorageaccountname"
existing_app_insights_name         = "your-app-insights-name"
existing_document_intelligence_name = "your-di-name"  # optional

# Create Foundry resources
create_ai_foundry_resources = true
foundry_model_name          = "gpt-4o"
foundry_model_version       = "2024-05-13"
foundry_deployment_name     = "gpt-4o"
foundry_model_capacity      = 10
```

### 2. Validate Configuration

```bash
terraform init -backend=false -input=false
terraform validate
```

### 3. Plan (Requires Azure CLI)

```bash
# Authenticate to Azure
az login
az account set --subscription "your-subscription-id"

# Run plan
terraform plan -var-file=terraform.tfvars
```

Or use the automated validation script:

```bash
./validate-foundry-existing-backend.sh
```

### 4. Review Plan

**Expected**: ~5-6 resources to add, 0 to change, 0 to destroy

**Resources that WILL be created:**
- Key Vault (e.g., `yourproject-kv-fnd01`)
- AI Foundry Hub (e.g., `yourproject-aihub-fnd01`)
- AI Foundry Project (e.g., `yourproject-aiproject-fnd01`)
- Azure OpenAI Account (e.g., `yourproject-openai-fnd01`)
- Model Deployment (e.g., `gpt-4o`)

**Resources that will NOT be touched:**
- Existing Storage Account
- Existing Storage Containers
- Existing Document Intelligence
- Existing App Service Plan
- Existing Function App
- Existing Application Insights

**Outputs will reference:**
- Function App URL: `https://your-func-app-name.azurewebsites.net`
- OpenAPI base URL: `https://your-func-app-name.azurewebsites.net/api`

## Variables Reference

### Required Variables (when use_existing_backend=true)

| Variable | Type | Description |
|----------|------|-------------|
| `use_existing_backend` | bool | Must be `true` to enable Foundry-only mode |
| `existing_function_app_name` | string | Name of existing Function App |
| `existing_storage_account_name` | string | Name of existing Storage Account |
| `existing_app_insights_name` | string | Name of existing Application Insights |

### Optional Variables

| Variable | Type | Description |
|----------|------|-------------|
| `existing_document_intelligence_name` | string | Name of existing DI account (for reference in outputs) |
| `existing_app_service_plan_name` | string | Name of existing App Service Plan (for reference) |

### Naming Strategy

When using `use_existing_backend=true`:
- **Existing backend resources**: Use explicit variable names (e.g., `existing_function_app_name`)
- **New Foundry resources**: Use `unique_suffix` to create new names that don't collide

Example:
- Existing Function: `kiwidemo-func-b923ue` (suffix: `b923ue`)
- New Key Vault: `kiwidemo-kv-fnd01` (suffix: `fnd01`)
- New Hub: `kiwidemo-aihub-fnd01` (suffix: `fnd01`)

This ensures no name collisions between existing and new resources.

## How It Works

### Data Sources

When `use_existing_backend=true`, Terraform uses data sources to look up existing resources:

```hcl
data "azurerm_storage_account" "existing" {
  name                = var.existing_storage_account_name
  resource_group_name = local.resource_group_name_final
}

data "azurerm_application_insights" "existing" {
  name                = var.existing_app_insights_name
  resource_group_name = local.resource_group_name_final
}

data "azurerm_linux_function_app" "existing" {
  name                = var.existing_function_app_name
  resource_group_name = local.resource_group_name_final
}
```

### Conditional Resource Creation

Backend resources are gated by `local.create_backend_resources`:

```hcl
locals {
  create_backend_resources = !var.use_existing_backend
}

resource "azurerm_storage_account" "main" {
  count = local.create_backend_resources ? 1 : 0
  # ... configuration
}

resource "azurerm_linux_function_app" "main" {
  count = local.create_backend_resources ? 1 : 0
  # ... configuration
}
```

### AI Hub References

The AI Foundry Hub references existing or created resources via locals:

```hcl
locals {
  storage_account_id = var.use_existing_backend 
    ? data.azurerm_storage_account.existing[0].id 
    : azurerm_storage_account.main[0].id
    
  app_insights_id = var.use_existing_backend 
    ? data.azurerm_application_insights.existing[0].id 
    : azurerm_application_insights.main[0].id
}

resource "azapi_resource" "ai_hub" {
  body = {
    properties = {
      storageAccount      = local.storage_account_id
      applicationInsights = local.app_insights_id
      # ...
    }
  }
}
```

### Outputs

Outputs use locals to reference the correct resources:

```hcl
locals {
  function_app_name_final = var.use_existing_backend 
    ? data.azurerm_linux_function_app.existing[0].name 
    : azurerm_linux_function_app.main[0].name
    
  function_app_default_hostname = var.use_existing_backend 
    ? data.azurerm_linux_function_app.existing[0].default_hostname 
    : azurerm_linux_function_app.main[0].default_hostname
}

output "function_app_url" {
  value = "https://${local.function_app_default_hostname}"
}
```

## Validation

### Automated Validation

The `validate-foundry-existing-backend.sh` script performs comprehensive validation:

1. Checks prerequisites (Terraform, Azure CLI)
2. Verifies Azure authentication
3. Confirms existing resources exist
4. Runs Terraform plan
5. Validates plan output:
   - 0 destroy operations ✅
   - Only Foundry resources to add ✅
   - No backend resources in plan ✅
   - Outputs reference existing Function App ✅

Run it:

```bash
./validate-foundry-existing-backend.sh
```

### Manual Validation Checklist

After running `terraform plan`, verify:

- [ ] Plan summary shows `0 to destroy`
- [ ] Plan includes Key Vault, AI Hub, AI Project, OpenAI account, Model deployment
- [ ] Plan does NOT include Storage Account, Function App, App Service Plan, App Insights
- [ ] Output `function_app_url` points to your existing Function App hostname
- [ ] Output `function_api_base_url` = `https://your-func-app.azurewebsites.net/api`

## Example: kiwidemo Scenario

### Existing Resources (in kiwidemo-rg-b923ue)

| Name | Type | Suffix |
|------|------|--------|
| kiwidemo-func-b923ue | Function App | b923ue |
| kiwidemosab923ue | Storage Account | b923ue |
| kiwidemo-ai-b923ue | App Insights | b923ue |
| kiwidemo-di-b923ue | Document Intelligence | b923ue |
| kiwidemo-asp-b923ue | App Service Plan | b923ue |

### Configuration

```hcl
subscription_id                    = "39993ea2-aaaa-499f-af2c-990d41279d3a"
project_name                       = "kiwidemo"
unique_suffix                      = "fnd01"  # NEW suffix
location                           = "australiaeast"
use_existing_resource_group        = true
resource_group_name                = "kiwidemo-rg-b923ue"
use_existing_backend               = true
existing_function_app_name         = "kiwidemo-func-b923ue"
existing_storage_account_name      = "kiwidemosab923ue"
existing_app_insights_name         = "kiwidemo-ai-b923ue"
existing_document_intelligence_name = "kiwidemo-di-b923ue"
create_ai_foundry_resources        = true
foundry_model_name                 = "gpt-4o"
foundry_model_version              = "2024-05-13"
foundry_deployment_name            = "gpt-4o"
foundry_model_capacity             = 10
```

### Expected Plan

```
Plan: 5 to add, 0 to change, 0 to destroy

Resources to add:
  + azurerm_key_vault.foundry[0]
      name: "kiwidemo-kv-fnd01"
  
  + azapi_resource.ai_hub[0]
      name: "kiwidemo-aihub-fnd01"
  
  + azapi_resource.ai_project[0]
      name: "kiwidemo-aiproject-fnd01"
  
  + azurerm_cognitive_account.openai[0]
      name: "kiwidemo-openai-fnd01"
  
  + azurerm_cognitive_deployment.model[0]
      name: "gpt-4o"
```

### Expected Outputs

```
function_app_name         = "kiwidemo-func-b923ue"
function_app_url          = "https://kiwidemo-func-b923ue.azurewebsites.net"
function_api_base_url     = "https://kiwidemo-func-b923ue.azurewebsites.net/api"
storage_account_name      = "kiwidemosab923ue"
ai_foundry_hub_id         = "/subscriptions/.../kiwidemo-aihub-fnd01"
ai_foundry_project_name   = "kiwidemo-aiproject-fnd01"
ai_foundry_key_vault_name = "kiwidemo-kv-fnd01"
```

## Troubleshooting

### Error: "existing_function_app_name is required"

When `use_existing_backend=true`, you must provide all three required variables:
- `existing_function_app_name`
- `existing_storage_account_name`
- `existing_app_insights_name`

### Error: "Resource group not found"

Ensure `use_existing_resource_group=true` and `resource_group_name` is set correctly.

### Error: "use_existing_resource_group must also be true"

The `use_existing_backend` feature requires `use_existing_resource_group=true` because you must have an existing RG to have existing backend resources.

### Plan shows backend resources being created

Check that `use_existing_backend=true` is set in your tfvars file.

### Outputs show wrong Function App URL

Verify `existing_function_app_name` matches your actual Function App name exactly.

### Name collision errors

Ensure `unique_suffix` is different from your existing resource suffix. For example, if existing resources use `b923ue`, use a different suffix like `fnd01` for Foundry resources.

## Related Documentation

- [FOUNDRY_SETUP.md](./FOUNDRY_SETUP.md) - Full Foundry setup guide
- [terraform.tfvars.foundry-existing-backend-example](./terraform.tfvars.foundry-existing-backend-example) - Complete example configuration
- [validate-foundry-existing-backend.sh](./validate-foundry-existing-backend.sh) - Automated validation script

## Support

For issues or questions:
1. Review the validation checklist above
2. Check Troubleshooting section
3. Review FOUNDRY_SETUP.md for general Foundry guidance
4. Examine the validation script output for detailed diagnostics
