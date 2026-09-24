# Azure Deployment Guide - Kiwi Knowledge Bill OCR

Complete guide to deploying the kiwi-knowledge-bill-ocr servicing assessment system on Azure.

## Table of Contents

- [Automated Terraform Path](#automated-terraform-path-recommended) ⭐ **NEW**
- [Manual Deployment Path](#manual-deployment-path)
- [Configuration & Testing](#configuration--testing)
- [Security & Production Hardening](#security--production-hardening)

---

## Automated Terraform Path (Recommended)

**One-click infrastructure-as-code deployment** that creates and wires all Azure resources.

### What Terraform Creates

✅ Resource Group (or attaches to existing)  
✅ Storage Account with containers: `samples`, `batches`, `reports`  
✅ Document Intelligence (FormRecognizer) for OCR  
✅ Application Insights for monitoring  
✅ Linux App Service Plan (Python 3.11 compatible)  
✅ Function App with auto-wired settings  
✅ AI Foundry Hub/Project (optional, preview)  
✅ Model Deployment (optional, if Foundry created)

### Prerequisites

1. **Azure CLI** (authenticated):
   ```bash
   az login
   az account set --subscription "your-subscription-name"
   ```

2. **Terraform** >= 1.5.0:
   ```bash
   terraform --version
   # Install: https://www.terraform.io/downloads
   ```

3. **Azure Functions Core Tools** >= 4.x:
   ```bash
   func --version
   # Install: npm install -g azure-functions-core-tools@4
   ```

### Quick Start

#### 1. Configure Variables

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your environment values
```

Key variables:

```hcl
project_name   = "kiwi-ocr"
unique_suffix  = ""  # Auto-generated if empty
location       = "australiaeast"
environment    = "dev"

# Recommend Standard for production
document_intelligence_sku = "S0"  # F0 (free) or S0
app_service_plan_sku      = "B1"  # B1-B3, S1-S3, P1v2-P3v3

# Use managed identity instead of API keys (production)
use_managed_identity = false  # Set true for production
```

#### 2. Validate and Plan

```bash
terraform init -backend=false
terraform validate
terraform fmt -check
terraform plan -out=tfplan
```

**Review the plan carefully** before applying.

#### 3. Apply Infrastructure

```bash
terraform apply tfplan
```

⚠️ **CONSTRAINT:** Do NOT run against production Azure subscriptions or existing resources without explicit approval.

#### 4. Deploy Function Code

```bash
# Get Function App name
FUNC_APP_NAME=$(terraform output -raw function_app_name)

# Deploy
cd ../../function_app
func azure functionapp publish $FUNC_APP_NAME
```

#### 5. Update OpenAPI Spec

```bash
cd ../infra/terraform
API_BASE_URL=$(terraform output -raw function_api_base_url)
echo "Update foundry/openapi-servicing.json with:"
echo "  servers[0].url = \"$API_BASE_URL\""
```

Edit `foundry/openapi-servicing.json`:

```json
{
  "servers": [
    {
      "url": "https://your-func-app.azurewebsites.net/api",
      "description": "Deployed Function App"
    }
  ]
}
```

#### 6. Configure AI Foundry Agent

**Manual step** (cannot be automated):

1. Go to [Azure AI Portal](https://ai.azure.com)
2. Create or open your Foundry project
3. Create a new agent
4. Add OpenAPI tool:
   - Upload `foundry/openapi-servicing.json` (with updated server URL)
   - Create **PROJECT CONNECTION** with Function key as `x-functions-key`
   - Select the connection for the tool (do NOT paste key into tool)
   - Assign **Foundry User** and **Project Manager** roles
5. Paste agent instructions from `foundry/PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt`

See [foundry/HOW_TO_HANG_TOOLS.md](../foundry/HOW_TO_HANG_TOOLS.md) for detailed OpenAPI setup.

### Windows PowerShell Wrapper

For Windows users:

```powershell
cd infra/terraform

# Validate
.\deploy.ps1 -Action validate

# Plan
.\deploy.ps1 -Action plan

# Apply (with confirmation)
.\deploy.ps1 -Action apply

# Deploy functions
.\deploy.ps1 -Action deploy-functions

# Generate environment-specific OpenAPI spec
.\deploy.ps1 -Action generate-openapi

# View outputs
.\deploy.ps1 -Action outputs
```

The `generate-openapi` action creates `foundry/openapi-servicing-{suffix}.json` with the deployed Function URL. **Do NOT commit this file** - it contains environment-specific URLs.

### Terraform Outputs

View deployment details:

```bash
# All non-sensitive outputs
terraform output

# Specific output
terraform output function_api_base_url

# All outputs including sensitive (connection strings, keys)
terraform output -json

# Sensitive value
terraform output -raw storage_connection_string
```

Key outputs:

- `function_api_base_url` - For OpenAPI spec servers[0].url
- `function_app_name` - For code deployment
- `storage_containers` - Container names (samples, batches, reports)
- `document_intelligence_endpoint` - DI endpoint URL
- `next_steps` - Human-readable deployment summary
- `deployment_summary` - Structured summary object

### Function App Settings

Terraform auto-wires these settings from resource outputs:

#### Platform/Deployment-Managed (4 settings)

1. `APPLICATIONINSIGHTS_CONNECTION_STRING` - Telemetry
2. `AzureWebJobsStorage` - Functions runtime
3. `FUNCTIONS_WORKER_RUNTIME` - Python
4. `WEBSITE_RUN_FROM_PACKAGE` - Deployment mode

#### Operator-Provided (4 settings)

5. `DOCUMENTINTELLIGENCE_ENDPOINT` - DI endpoint URL (NO underscore in name)
6. `DOCUMENTINTELLIGENCE_KEY` - API key (empty if using managed identity)
7. `STATEMENTS_STORAGE_CONNECTION_STRING` - Storage for statements/batches/reports
8. `EXTRACT_ALLOWED_BINDERS` - Input container names (comma-separated, e.g. "vikas-samples")

#### Optional Container Overrides (2 settings)

9. `REPORTS_CONTAINER` - Output reports (default: vikas-reports)
10. `BATCHES_CONTAINER` - Batch storage (default: vikas-batches)

### AI Foundry Resources (Preview)

To create AI Foundry Hub/Project via Terraform:

```hcl
create_ai_foundry_resources = true
key_vault_id                = "/subscriptions/.../vaults/your-kv"
foundry_model_name          = "gpt-4"
foundry_model_version       = "0613"
foundry_deployment_name     = "gpt-4"  # Match model name
foundry_model_capacity      = 10
```

**LIMITATIONS:**

- ⚠️ Foundry Agent creation is **NOT** supported via Terraform
- ⚠️ OpenAPI tool attachment is **NOT** supported via Terraform
- ⚠️ These must be configured manually in the Azure AI Portal

Leave `create_ai_foundry_resources = false` (default) to set up Foundry completely manually.

### Remote State Configuration

**IMPORTANT:** Before production use, configure remote state backend.

Create state storage:

```bash
# Resource group
az group create --name terraform-state-rg --location australiaeast

# Storage account (globally unique name)
az storage account create \
  --name tfstateunique123 \
  --resource-group terraform-state-rg \
  --location australiaeast \
  --sku Standard_LRS \
  --allow-blob-public-access false

# Container
az storage container create \
  --name tfstate \
  --account-name tfstateunique123 \
  --auth-mode login
```

Uncomment in `infra/terraform/main.tf`:

```hcl
terraform {
  backend "azurerm" {
    resource_group_name  = "terraform-state-rg"
    storage_account_name = "tfstateunique123"
    container_name       = "tfstate"
    key                  = "kiwi-knowledge-bill-ocr.tfstate"
    use_azuread_auth     = true
  }
}
```

Migrate state:

```bash
terraform init -migrate-state
```

Grant team members **Storage Blob Data Contributor** role on the state storage account.

### Validation Commands (Safe - No Deployment)

Run these without applying infrastructure:

```bash
cd infra/terraform

# Format check
terraform fmt -check

# Initialize (local state only)
terraform init -backend=false

# Validate configuration
terraform validate

# Plan (dry run)
terraform plan
```

These commands are safe for CI/testing and do NOT create Azure resources.

### Cleanup

⚠️ **DANGER:** Destroys all resources and deletes all data.

```bash
terraform destroy
# Type 'yes' when prompted
```

Or via PowerShell:

```powershell
.\deploy.ps1 -Action destroy
# Type 'DELETE' when prompted
```

### Cost Estimation

Approximate monthly costs (Australia East, AUD):

| Resource | SKU | Monthly Cost |
|----------|-----|--------------|
| App Service Plan | B1 | ~$18 |
| Storage Account | Standard LRS | ~$0.50-5 (usage) |
| Document Intelligence | S0 | $1.50/1000 pages |
| Application Insights | Basic | ~$2.88 (5GB free) |
| **Total baseline** | | **~$25-35** + usage |

Use [Azure Pricing Calculator](https://azure.microsoft.com/pricing/calculator/) for accurate estimates.

### Terraform Troubleshooting

#### "Resource name already exists"

Change `unique_suffix` in `terraform.tfvars` or set to `""` for auto-generation.

#### Document Intelligence quota exceeded

Free tier (F0) has strict limits. Upgrade: `document_intelligence_sku = "S0"`

#### Foundry resources fail to create

Foundry APIs are in preview. Set `create_ai_foundry_resources = false` and configure manually.

#### Function deployment fails

- Check Functions Core Tools: `func --version`
- View logs: `func azure functionapp logstream $FUNC_APP_NAME`

---

## Manual Deployment Path

### 1. Create Resource Group

```bash
az group create --name kiwi-ocr-rg --location australiaeast
```

### 2. Create Storage Account

```bash
az storage account create \
  --name kiwiocr<suffix> \
  --resource-group kiwi-ocr-rg \
  --location australiaeast \
  --sku Standard_LRS \
  --allow-blob-public-access false \
  --min-tls-version TLS1_2
```

**Note:** Replace `<suffix>` with a unique 4-8 character identifier (e.g., `sa7k2m`).

### 3. Create Storage Containers

```bash
# Get storage account key
STORAGE_KEY=$(az storage account keys list \
  --account-name kiwiocr<suffix> \
  --query '[0].value' -o tsv)

# Create containers
for container in samples batches reports; do
  az storage container create \
    --name $container \
    --account-name kiwiocr<suffix> \
    --account-key $STORAGE_KEY
done
```

### 4. Create Document Intelligence

```bash
az cognitiveservices account create \
  --name kiwi-ocr-di-<suffix> \
  --resource-group kiwi-ocr-rg \
  --location australiaeast \
  --kind FormRecognizer \
  --sku S0 \
  --custom-domain kiwi-ocr-di-<suffix> \
  --yes
```

**SKU Options:**
- `F0` - Free tier (1 req/sec, 1000/month)
- `S0` - Standard (15 req/sec, pay-per-use)

### 5. Create Application Insights

```bash
az monitor app-insights component create \
  --app kiwi-ocr-ai-<suffix> \
  --location australiaeast \
  --resource-group kiwi-ocr-rg \
  --application-type web
```

### 6. Create App Service Plan

```bash
az appservice plan create \
  --name kiwi-ocr-asp-<suffix> \
  --resource-group kiwi-ocr-rg \
  --location australiaeast \
  --is-linux \
  --sku B1
```

**SKU Options:**
- `B1` - Basic (1.75GB RAM, $18/month)
- `S1` - Standard (1.75GB RAM, production)
- `P1v2` - Premium (3.5GB RAM, production)

### 7. Create Function App

```bash
# Get connection strings
STORAGE_CONN=$(az storage account show-connection-string \
  --name kiwiocr<suffix> \
  --resource-group kiwi-ocr-rg \
  --query connectionString -o tsv)

APPINSIGHTS_CONN=$(az monitor app-insights component show \
  --app kiwi-ocr-ai-<suffix> \
  --resource-group kiwi-ocr-rg \
  --query connectionString -o tsv)

# Create Function App
az functionapp create \
  --name kiwi-ocr-func-<suffix> \
  --resource-group kiwi-ocr-rg \
  --plan kiwi-ocr-asp-<suffix> \
  --storage-account kiwiocr<suffix> \
  --runtime python \
  --runtime-version 3.11 \
  --functions-version 4 \
  --os-type Linux
```

### 8. Configure Function App Settings

```bash
DI_ENDPOINT=$(az cognitiveservices account show \
  --name kiwi-ocr-di-<suffix> \
  --resource-group kiwi-ocr-rg \
  --query properties.endpoint -o tsv)

DI_KEY=$(az cognitiveservices account keys list \
  --name kiwi-ocr-di-<suffix> \
  --resource-group kiwi-ocr-rg \
  --query key1 -o tsv)

az functionapp config appsettings set \
  --name kiwi-ocr-func-<suffix> \
  --resource-group kiwi-ocr-rg \
  --settings \
    "APPLICATIONINSIGHTS_CONNECTION_STRING=$APPINSIGHTS_CONN" \
    "STATEMENTS_STORAGE_CONNECTION_STRING=$STORAGE_CONN" \
    "DOCUMENTINTELLIGENCE_ENDPOINT=$DI_ENDPOINT" \
    "DOCUMENTINTELLIGENCE_KEY=$DI_KEY" \
    "EXTRACT_ALLOWED_BINDERS=vikas-samples" \
    "REPORTS_CONTAINER=vikas-reports" \
    "BATCHES_CONTAINER=vikas-batches"
```

### 9. Deploy Function Code

```bash
cd function_app
func azure functionapp publish kiwi-ocr-func-<suffix>
```

### 10. Get Function App URL and Key

```bash
# Function App URL
echo "https://kiwi-ocr-func-<suffix>.azurewebsites.net/api"

# Get Function key
func azure functionapp list-functions kiwi-ocr-func-<suffix> --show-keys
```

---

## Configuration & Testing

### Update OpenAPI Spec

Edit `foundry/openapi-servicing.json`:

```json
{
  "servers": [
    {
      "url": "https://kiwi-ocr-func-<suffix>.azurewebsites.net/api"
    }
  ]
}
```

### Configure Foundry Agent

1. Go to [Azure AI Portal](https://ai.azure.com)
2. Create or open a Foundry project
3. Create an agent
4. Add OpenAPI tool:
   - Upload updated `foundry/openapi-servicing.json`
   - Authentication: **Project Connection** (custom keys)
   - Connection name: `function-app-key`
   - Key name: `x-functions-key` (matches OpenAPI `securitySchemes`)
   - Key value: Function key from step 10 above
   - **Assign roles:** Foundry User, Project Manager
   - **Select connection** for the tool (do NOT paste key in tool directly)
5. Paste instructions from `foundry/PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt`
6. **Turn off Code Interpreter** for the agent

See [foundry/HOW_TO_HANG_TOOLS.md](../foundry/HOW_TO_HANG_TOOLS.md) for detailed steps.

### Test Function Endpoints

```bash
FUNC_URL="https://kiwi-ocr-func-<suffix>.azurewebsites.net/api"
FUNC_KEY="your-function-key"

# Test health (if health endpoint exists)
curl -H "x-functions-key: $FUNC_KEY" "$FUNC_URL/health"

# Test extract_and_normalize (with sample file URL)
curl -X POST "$FUNC_URL/extract_and_normalize" \
  -H "Content-Type: application/json" \
  -H "x-functions-key: $FUNC_KEY" \
  -d '{
    "assessment_date": "2024-01-31",
    "binder": "samples"
  }'
```

### View Function Logs

```bash
# Stream live logs
func azure functionapp logstream kiwi-ocr-func-<suffix>

# Or via Azure CLI
az webapp log tail \
  --name kiwi-ocr-func-<suffix> \
  --resource-group kiwi-ocr-rg
```

### Monitor Application Insights

```bash
# Query recent exceptions
az monitor app-insights query \
  --app kiwi-ocr-ai-<suffix> \
  --resource-group kiwi-ocr-rg \
  --analytics-query "exceptions | where timestamp > ago(1h) | limit 10"
```

---

## Security & Production Hardening

### Use Managed Identity (Recommended)

Instead of API keys, use managed identity for Document Intelligence access:

```bash
# Enable system-assigned managed identity
az functionapp identity assign \
  --name kiwi-ocr-func-<suffix> \
  --resource-group kiwi-ocr-rg

# Get principal ID
PRINCIPAL_ID=$(az functionapp identity show \
  --name kiwi-ocr-func-<suffix> \
  --resource-group kiwi-ocr-rg \
  --query principalId -o tsv)

# Grant "Cognitive Services User" role
DI_ID=$(az cognitiveservices account show \
  --name kiwi-ocr-di-<suffix> \
  --resource-group kiwi-ocr-rg \
  --query id -o tsv)

az role assignment create \
  --assignee $PRINCIPAL_ID \
  --role "Cognitive Services User" \
  --scope $DI_ID

# Remove API key from app settings
az functionapp config appsettings delete \
  --name kiwi-ocr-func-<suffix> \
  --resource-group kiwi-ocr-rg \
  --setting-names DOCUMENTINTELLIGENCE_KEY
```

In Terraform: Set `use_managed_identity = true` in `terraform.tfvars`.

### Network Security

#### Private Endpoints (Optional)

```bash
# Create VNet and subnets
az network vnet create \
  --name kiwi-ocr-vnet \
  --resource-group kiwi-ocr-rg \
  --address-prefix 10.0.0.0/16 \
  --subnet-name functions-subnet \
  --subnet-prefix 10.0.1.0/24

# Create private endpoint for Storage
az network private-endpoint create \
  --name storage-pe \
  --resource-group kiwi-ocr-rg \
  --vnet-name kiwi-ocr-vnet \
  --subnet functions-subnet \
  --private-connection-resource-id "/subscriptions/.../storageAccounts/kiwiocr<suffix>" \
  --connection-name storage-connection \
  --group-ids blob
```

#### VNet Integration for Function App

```bash
az functionapp vnet-integration add \
  --name kiwi-ocr-func-<suffix> \
  --resource-group kiwi-ocr-rg \
  --vnet kiwi-ocr-vnet \
  --subnet functions-subnet
```

### Secrets Management with Key Vault

```bash
# Create Key Vault
az keyvault create \
  --name kiwi-ocr-kv-<suffix> \
  --resource-group kiwi-ocr-rg \
  --location australiaeast

# Store Document Intelligence key
az keyvault secret set \
  --vault-name kiwi-ocr-kv-<suffix> \
  --name doc-intelligence-key \
  --value "$DI_KEY"

# Grant Function App access
az keyvault set-policy \
  --name kiwi-ocr-kv-<suffix> \
  --object-id $PRINCIPAL_ID \
  --secret-permissions get list

# Update Function App setting to reference Key Vault
KV_SECRET_URI=$(az keyvault secret show \
  --vault-name kiwi-ocr-kv-<suffix> \
  --name doc-intelligence-key \
  --query id -o tsv)

az functionapp config appsettings set \
  --name kiwi-ocr-func-<suffix> \
  --resource-group kiwi-ocr-rg \
  --settings "DOCUMENTINTELLIGENCE_KEY=@Microsoft.KeyVault(SecretUri=$KV_SECRET_URI)"
```

### Enable HTTPS-Only and TLS 1.2

```bash
az functionapp update \
  --name kiwi-ocr-func-<suffix> \
  --resource-group kiwi-ocr-rg \
  --set httpsOnly=true \
  --set siteConfig.minTlsVersion=1.2
```

### Deployment Slots (Staging)

```bash
# Create staging slot
az functionapp deployment slot create \
  --name kiwi-ocr-func-<suffix> \
  --resource-group kiwi-ocr-rg \
  --slot staging

# Deploy to staging
func azure functionapp publish kiwi-ocr-func-<suffix> --slot staging

# Test staging slot
curl "https://kiwi-ocr-func-<suffix>-staging.azurewebsites.net/api/..."

# Swap to production
az functionapp deployment slot swap \
  --name kiwi-ocr-func-<suffix> \
  --resource-group kiwi-ocr-rg \
  --slot staging
```

### Rollback to Previous Deployment

```bash
# List deployment history
az webapp deployment list \
  --name kiwi-ocr-func-<suffix> \
  --resource-group kiwi-ocr-rg

# Rollback (swap staging back to production)
az functionapp deployment slot swap \
  --name kiwi-ocr-func-<suffix> \
  --resource-group kiwi-ocr-rg \
  --slot staging

# Or view deployment logs
az webapp log deployment list \
  --name kiwi-ocr-func-<suffix> \
  --resource-group kiwi-ocr-rg
```

### Data Privacy & Compliance

#### Synthetic Data for Testing

**IMPORTANT:** The repository contains **synthetic data only**.

- ✅ Use synthetic fixtures from `fixtures/generate_fixtures.py` for development and smoke tests
- ✅ Store production bank statements in controlled private storage under organizational policy
- ✅ The service can process real customer data in production (that's its purpose)
- ❌ DO NOT commit real bank statements, PII, or production data to Git

#### Production Data Storage

- Store real statements in Azure Blob Storage with:
  - Private containers (no public access)
  - Encryption at rest (enabled by default)
  - Access policies restricted to authorized identities
  - Lifecycle policies for automatic deletion after retention period

```bash
# Enable soft delete and versioning
az storage account blob-service-properties update \
  --account-name kiwiocr<suffix> \
  --enable-delete-retention true \
  --delete-retention-days 30 \
  --enable-versioning true

# Set lifecycle management policy (delete after 90 days)
az storage account management-policy create \
  --account-name kiwiocr<suffix> \
  --policy '{
    "rules": [{
      "name": "delete-old-statements",
      "type": "Lifecycle",
      "definition": {
        "filters": {
          "blobTypes": ["blockBlob"],
          "prefixMatch": ["batches/", "reports/"]
        },
        "actions": {
          "baseBlob": {
            "delete": {
              "daysAfterModificationGreaterThan": 90
            }
          }
        }
      }
    }]
  }'
```

---

## Model Deployment & Naming

When configuring AI Foundry model deployments:

✅ **DO:** Name deployment to match the actual model

- Deploying `gpt-4` → deployment name `gpt-4`
- Deploying `gpt-35-turbo` → deployment name `gpt-35-turbo`

❌ **DON'T:** Name a non-gpt-5 deployment `gpt-5`

### OpenAPI Tool Model Support

**IMPORTANT:** OpenAPI tool attachments in AI Foundry require specific model families:

- ✅ Supported: `gpt-4`, `gpt-35-turbo`, `gpt-4-turbo`, `gpt-4o` (OpenAI family)
- ❌ **NOT** supported: Many other models cannot attach OpenAPI tools

Check [Azure AI Foundry documentation](https://learn.microsoft.com/azure/ai-studio/) for current model/region support matrix.

---

## Troubleshooting

### Function App Not Starting

```bash
# Check Function App status
az functionapp show \
  --name kiwi-ocr-func-<suffix> \
  --resource-group kiwi-ocr-rg \
  --query state

# View application settings
az functionapp config appsettings list \
  --name kiwi-ocr-func-<suffix> \
  --resource-group kiwi-ocr-rg

# Restart Function App
az functionapp restart \
  --name kiwi-ocr-func-<suffix> \
  --resource-group kiwi-ocr-rg
```

### Document Intelligence Errors

```bash
# Test Document Intelligence endpoint
DI_ENDPOINT=$(az cognitiveservices account show \
  --name kiwi-ocr-di-<suffix> \
  --resource-group kiwi-ocr-rg \
  --query properties.endpoint -o tsv)

curl "$DI_ENDPOINT/formrecognizer/documentModels?api-version=2023-07-31" \
  -H "Ocp-Apim-Subscription-Key: $DI_KEY"
```

### Storage Access Issues

```bash
# Test storage container access
az storage blob list \
  --container-name samples \
  --account-name kiwiocr<suffix> \
  --account-key $STORAGE_KEY
```

### Foundry Agent Tool Errors

1. **"Authentication failed"**
   - Check PROJECT CONNECTION configuration
   - Verify `x-functions-key` matches Function App key
   - Confirm connection is selected for the tool

2. **"Tool not found" or 404**
   - Verify OpenAPI spec `servers[0].url` matches Function App URL
   - Check Function App is deployed and running
   - Test endpoints directly with curl

3. **"Model does not support OpenAPI tools"**
   - Use supported model family (gpt-4, gpt-35-turbo)
   - Check region supports OpenAPI tools
   - Deployment name should match model name

---

## Related Documentation

- [Terraform Infrastructure README](../infra/terraform/README.md) - Detailed IaC guide
- [How to Hang Tools](../foundry/HOW_TO_HANG_TOOLS.md) - Foundry OpenAPI setup
- [Project README](../README.md) - System overview
- [Azure Functions Documentation](https://learn.microsoft.com/azure/azure-functions/)
- [Document Intelligence Documentation](https://learn.microsoft.com/azure/ai-services/document-intelligence/)
- [Azure AI Foundry Documentation](https://learn.microsoft.com/azure/ai-studio/)

---

**Repository:** [kiwi-knowledge-bill-ocr](https://github.com/agent-room-alkl/kiwi-knowledge-bill-ocr)

**Data:** Synthetic only. No real customer data in repository.

**Support:** For deployment issues, check Azure Portal resource health and Function App logs.
