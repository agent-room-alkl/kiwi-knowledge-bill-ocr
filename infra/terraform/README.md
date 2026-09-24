# Terraform Infrastructure for Kiwi Knowledge Bill OCR

One-click Azure infrastructure deployment for the kiwi-knowledge-bill-ocr servicing assessment system.

## What This Creates

- **Resource Group** (or attaches to existing)
- **Storage Account** with configurable input containers (e.g., `vikas-samples`)
- **Document Intelligence** (FormRecognizer) for OCR
- **Application Insights** for monitoring
- **Linux App Service Plan** (Python 3.11 compatible)
- **Function App** (Python 3.11) with auto-wired settings
- **AI Foundry Hub/Project** (optional, preview feature)
- **Model Deployment** (optional, if Foundry resources created)

Note: The Function App also uses `vikas-reports` and `vikas-batches` containers by default (configurable).

## Prerequisites

1. **Azure CLI** authenticated with sufficient permissions:
   ```bash
   az login
   az account set --subscription "your-subscription-name-or-id"
   ```

2. **Terraform** >= 1.5.0:
   ```bash
   terraform --version
   ```

3. **Azure Functions Core Tools** (for code deployment):
   ```bash
   npm install -g azure-functions-core-tools@4
   # or: brew install azure-functions-core-tools@4
   ```

4. **PowerShell** (for Windows deployment script) or Bash

**Note:** The azurerm provider 4.x requires `subscription_id` to be explicitly set. The `deploy.ps1` script automatically exports `ARM_SUBSCRIPTION_ID` from `az account show` for you. If running Terraform commands manually, ensure `ARM_SUBSCRIPTION_ID` environment variable is set.

## Quick Start

### 1. Configure Variables

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your values
```

Key variables to customize:

- `project_name` - Base name for resources (default: `kiwi-ocr`)
- `unique_suffix` - 4-8 char suffix for global uniqueness (auto-generated if empty)
- `location` - Azure region (default: `australiaeast`)
- `environment` - `dev`, `staging`, or `prod`
- `app_service_plan_sku` - Function App plan size (default: `B1`)

### 2. Initialize Terraform

```bash
terraform init -backend=false
```

**Note:** Remote state backend is disabled by default for initial testing. See [Remote State Configuration](#remote-state-configuration) before production use.

### 3. Validate Configuration

```bash
terraform validate
terraform fmt -check
```

### 4. Plan Deployment

```bash
terraform plan -out=tfplan
```

Review the plan carefully. This is a **DRY RUN** - no resources are created yet.

### 5. Apply Infrastructure (DO NOT RUN AGAINST PRODUCTION)

```bash
terraform apply tfplan
```

**HARD CONSTRAINT:** Do NOT run `terraform apply` against any real Azure subscription, especially existing Kiwi/Subport resources.

### 6. Deploy Function Code

After Terraform completes:

```bash
# Get Function App name from Terraform output
FUNC_APP_NAME=$(terraform output -raw function_app_name)

# Deploy from function_app directory
cd ../../function_app
func azure functionapp publish $FUNC_APP_NAME
```

### 7. Update OpenAPI Spec

```bash
# Get API base URL
API_BASE_URL=$(terraform output -raw function_api_base_url)

# Update foundry/openapi-servicing.json
# Set: servers[0].url = "$API_BASE_URL"
```

See [../foundry/openapi-servicing.json](../../foundry/openapi-servicing.json)

### 8. Configure AI Foundry Agent

**Manual step** (cannot be automated):

1. Go to [Azure AI Portal](https://ai.azure.com)
2. Create or open your Foundry project
3. Create an agent
4. Add OpenAPI tool:
   - Upload `foundry/openapi-servicing.json` with the updated server URL
   - Create PROJECT CONNECTION with Function key as `x-functions-key`
   - Select the connection for the tool (do not paste key into tool)
5. Paste agent instructions from `foundry/PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt`

See [../../foundry/HOW_TO_HANG_TOOLS.md](../../foundry/HOW_TO_HANG_TOOLS.md) for detailed steps.

## Windows PowerShell Deployment Script

For Windows users, a PowerShell wrapper is provided:

```powershell
.\deploy.ps1 -Action plan
.\deploy.ps1 -Action apply
.\deploy.ps1 -Action deploy-functions
.\deploy.ps1 -Action generate-openapi
.\deploy.ps1 -Action destroy
```

See [deploy.ps1](./deploy.ps1) for details.

## Function App Settings

### Platform/Deployment-Managed (4 settings, auto-wired by Terraform)

1. `APPLICATIONINSIGHTS_CONNECTION_STRING` - Application Insights telemetry
2. `AzureWebJobsStorage` - Functions runtime storage
3. `FUNCTIONS_WORKER_RUNTIME` - Python runtime
4. `WEBSITE_RUN_FROM_PACKAGE` - Code deployment mode

### Operator-Provided (4 settings, wire from Azure resources)

These are set by Terraform based on the resources it creates:

5. `DOCUMENTINTELLIGENCE_ENDPOINT` - Document Intelligence service endpoint (NO underscore in name)
6. `DOCUMENTINTELLIGENCE_KEY` - API key (or empty string if using managed identity)
7. `STATEMENTS_STORAGE_CONNECTION_STRING` - Storage account connection for statements/batches/reports
8. `EXTRACT_ALLOWED_BINDERS` - Comma-separated container names for input (e.g., "vikas-samples")

### Optional Overrides (2 settings, with defaults)

9. `REPORTS_CONTAINER` - Output reports container (default: `vikas-reports`)
10. `BATCHES_CONTAINER` - Canonical batch storage container (default: `vikas-batches`)

### Optional URL Allowlist (1 setting)

11. `EXTRACT_URL_ALLOWED_HOSTS` - SSRF protection (default: `.blob.core.windows.net`)

**Note:** The code reads these exact names from `function_app/extract_normalize.py`. Do not rename them without updating the Python code.

## Managed Identity (Recommended for Production)

Set `use_managed_identity = true` in `terraform.tfvars` to:

- Grant Function App system-assigned managed identity
- Assign "Cognitive Services User" role to Document Intelligence
- Remove API key from app settings

## AI Foundry Resources (Preview)

To create AI Foundry Hub/Project via Terraform:

```hcl
create_ai_foundry_resources = true
key_vault_id                = "/subscriptions/.../vaults/your-kv"
foundry_model_name          = "gpt-4"
foundry_model_version       = "0613"
foundry_deployment_name     = "gpt-4"
```

**LIMITATIONS:**

- AI Foundry Agent creation is NOT supported via Terraform
- OpenAPI tool attachment is NOT supported via Terraform
- These must be configured manually in the Azure AI Portal after deployment

Leave `create_ai_foundry_resources = false` (default) to configure Foundry completely manually.

## Remote State Configuration

**IMPORTANT:** Before production use, configure remote state in `main.tf`:

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

Create the state storage account:

```bash
# Create resource group for state
az group create --name terraform-state-rg --location australiaeast

# Create storage account (name must be globally unique)
az storage account create \
  --name tfstateunique \
  --resource-group terraform-state-rg \
  --location australiaeast \
  --sku Standard_LRS \
  --allow-blob-public-access false

# Create container
az storage container create \
  --name tfstate \
  --account-name tfstateunique \
  --auth-mode login
```

Grant team members "Storage Blob Data Contributor" role on the storage account.

Re-initialize Terraform:

```bash
terraform init -migrate-state
```

## Outputs

After deployment, view outputs:

```bash
# Non-sensitive outputs
terraform output

# All outputs including sensitive (connection strings, keys)
terraform output -json

# Specific output
terraform output function_api_base_url
terraform output -raw storage_connection_string
```

Key outputs:

- `function_api_base_url` - Use in OpenAPI spec
- `storage_containers` - Container names
- `document_intelligence_endpoint` - DI endpoint
- `next_steps` - Human-readable deployment summary
- `openapi_spec_path` - Where to update the Function URL
- `agent_instructions_path` - Foundry agent instructions file

## Cleaning Up

**WARNING:** This destroys all resources. Data in storage will be DELETED.

```bash
terraform destroy
```

Or via PowerShell:

```powershell
.\deploy.ps1 -Action destroy
```

## Validation Commands (No Real Deployment)

Validate the configuration without applying:

```bash
# Format check
terraform fmt -check

# Initialize (local state only)
terraform init -backend=false

# Validate syntax
terraform validate

# Plan (dry run)
terraform plan
```

These commands are safe to run and are included in the CI/test workflow.

## Security Considerations

### Secrets Management

- **Function keys:** Retrieve via Azure CLI, NEVER commit to Git
  ```bash
  func azure functionapp list-functions $FUNC_APP_NAME --show-keys
  ```
- **Connection strings:** Marked `sensitive = true` in outputs
- **State files:** May contain sensitive data - use remote encrypted state
- **tfvars:** Add `terraform.tfvars` to `.gitignore` (already included)

### Network Security

Consider adding (not included in this template):

- Virtual Network integration for Function App
- Private endpoints for Storage and Document Intelligence
- Network Security Groups
- Azure Firewall rules

### Identity and Access

- Use managed identity (`use_managed_identity = true`) instead of API keys
- Apply least-privilege RBAC roles
- Enable Azure AD authentication for Function App (add `auth_settings` block)

## Cost Estimation

Approximate monthly costs (australiaeast, as of 2024):

| Resource | SKU | Est. Cost (AUD/month) |
|----------|-----|------------------------|
| App Service Plan | B1 | ~$18 |
| Function App | Included in plan | $0 |
| Storage Account | Standard LRS | ~$0.50-5 (usage-based) |
| Document Intelligence | S0 | $1.50/1000 pages |
| Application Insights | Basic | ~$2.88 (first 5GB free) |
| AI Foundry | Variable | Model-dependent |

**Total baseline:** ~$25-35/month + usage costs

Use [Azure Pricing Calculator](https://azure.microsoft.com/pricing/calculator/) for accurate estimates.

## Troubleshooting

### `terraform init` fails

- Check Azure CLI authentication: `az account show`
- Verify subscription access: `az account list`
- Check Terraform version: `terraform --version`

### `terraform apply` fails: "resource name already exists"

- Change `unique_suffix` in `terraform.tfvars`
- Or set `unique_suffix = ""` to generate a new random suffix

### Function deployment fails

- Ensure Functions Core Tools are installed: `func --version`
- Check Function App is running: `az functionapp show -n $FUNC_APP_NAME -g $RG_NAME`
- View logs: `func azure functionapp logstream $FUNC_APP_NAME`

### Document Intelligence "quota exceeded"

- Free tier (F0) has strict limits (1 req/sec, 1000/month)
- Upgrade to S0 in `terraform.tfvars`: `document_intelligence_sku = "S0"`

### AI Foundry resources fail to create

- Foundry APIs are in preview and may not be available in all regions
- Check region support: https://learn.microsoft.com/azure/ai-studio/
- Fallback: Set `create_ai_foundry_resources = false` and configure manually

## Support

This Terraform configuration is designed for the [kiwi-knowledge-bill-ocr](../../README.md) project.

For issues:

1. Check [Azure Terraform Provider docs](https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs)
2. Validate configuration: `terraform validate`
3. Review plan output: `terraform plan`
4. Check Azure Portal for resource status

## Files in This Directory

- `main.tf` - Main infrastructure resources
- `variables.tf` - Input variable definitions
- `outputs.tf` - Output values
- `terraform.tfvars.example` - Example configuration (copy to `terraform.tfvars`)
- `README.md` - This file
- `deploy.ps1` - Windows PowerShell deployment script
- `.terraform/` - Terraform cache (generated, not committed)
- `terraform.tfstate*` - State files (generated, not committed, sensitive)
- `tfplan` - Plan file (generated, not committed)

## Related Documentation

- [Azure Deployment Guide](../../docs/AZURE_DEPLOYMENT_GUIDE.md) - Manual deployment steps
- [How to Hang Tools](../../foundry/HOW_TO_HANG_TOOLS.md) - Foundry agent setup
- [Project README](../../README.md) - Project overview
- [Azure Functions docs](https://learn.microsoft.com/azure/azure-functions/)
- [Document Intelligence docs](https://learn.microsoft.com/azure/ai-services/document-intelligence/)
- [Azure AI Foundry docs](https://learn.microsoft.com/azure/ai-studio/)
