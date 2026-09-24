# Azure Deployment Guide

**Deploy the NZ bank-statement servicing assessment stack from scratch**

This guide walks you through deploying the complete kiwi-knowledge-bill-ocr system on Azure, including Azure Functions, Document Intelligence, and Azure AI Foundry agent setup.

**Repository:** https://github.com/agent-room-alkl/kiwi-knowledge-bill-ocr  
**Target branch:** `main`  
**Document language:** English

⚠️ **Important:** This guide contains NO secret values. All credentials must be obtained from Azure Portal and configured in your deployment.

---

## Prerequisites

Before starting, ensure you have:

- **Azure CLI** installed and authenticated (`az login`)
- **Azure Functions Core Tools** v4.x (`func --version`)
- **Python 3.11+** with pip
- **Git** configured and authenticated to GitHub
- An **active Azure subscription** with sufficient permissions to create resources
- A unique prefix for naming resources (e.g., your initials or project code)

**Verify your setup:**

```bash
az --version
func --version
python3 --version
git --version
az account show
```

---

## Step 1: Clone the Repository

```bash
git clone https://github.com/agent-room-alkl/kiwi-knowledge-bill-ocr.git
cd kiwi-knowledge-bill-ocr
git checkout main
git pull origin main
```

---

## Step 2: Create Resource Group

Choose a region close to your users (e.g., `australiaeast` for NZ/AU).

```bash
az group create \
  --name rg-kiwi-demo \
  --location australiaeast
```

**Note:** Replace `rg-kiwi-demo` with your preferred resource group name throughout this guide.

---

## Step 3: Create Storage Account and Containers

### 3.1 Create Storage Account

```bash
az storage account create \
  --name rgkiwidemo88cf \
  --resource-group rg-kiwi-demo \
  --location australiaeast \
  --sku Standard_LRS \
  --kind StorageV2
```

⚠️ **Storage account names must be globally unique, 3-24 characters, lowercase letters and numbers only.** Replace `rgkiwidemo88cf` with your unique name.

### 3.2 Get Storage Connection String

```bash
az storage account show-connection-string \
  --name rgkiwidemo88cf \
  --resource-group rg-kiwi-demo \
  --query connectionString \
  --output tsv
```

Save this connection string securely - you'll need it for Function App configuration.

### 3.3 Create Three Required Containers

```bash
STORAGE_CONN="<paste-connection-string-here>"

az storage container create \
  --name vikas-samples \
  --connection-string "$STORAGE_CONN"

az storage container create \
  --name vikas-batches \
  --connection-string "$STORAGE_CONN"

az storage container create \
  --name vikas-reports \
  --connection-string "$STORAGE_CONN"
```

**Container purposes:**
- `vikas-samples`: Input binders containing statement PDFs (used in `EXTRACT_ALLOWED_BINDERS`)
- `vikas-batches`: Stores `batch_id` and `summary_id` intermediate results
- `vikas-reports`: Published Excel and HTML reports

**Note:** For a fresh environment, use your own container names. The names above are examples from the demo deployment.

---

## Step 4: Create Document Intelligence Resource

```bash
az cognitiveservices account create \
  --name kiwi-docs \
  --resource-group rg-kiwi-demo \
  --kind FormRecognizer \
  --sku S0 \
  --location australiaeast \
  --yes
```

### 4.1 Get Document Intelligence Credentials

```bash
az cognitiveservices account show \
  --name kiwi-docs \
  --resource-group rg-kiwi-demo \
  --query properties.endpoint \
  --output tsv

az cognitiveservices account keys list \
  --name kiwi-docs \
  --resource-group rg-kiwi-demo \
  --query key1 \
  --output tsv
```

Save both the **endpoint** and **key1** - you'll configure these as `DOCUMENTINTELLIGENCE_ENDPOINT` and `DOCUMENTINTELLIGENCE_KEY`.

---

## Step 5: Create App Service Plan and Function App

### 5.1 Create App Service Plan

```bash
az functionapp plan create \
  --name kiwi-demo-plan \
  --resource-group rg-kiwi-demo \
  --location australiaeast \
  --sku B1 \
  --is-linux
```

### 5.2 Create Application Insights

```bash
az monitor app-insights component create \
  --app kiwi-demo-insights \
  --location australiaeast \
  --resource-group rg-kiwi-demo
```

### 5.3 Get Application Insights Connection String

```bash
az monitor app-insights component show \
  --app kiwi-demo-insights \
  --resource-group rg-kiwi-demo \
  --query connectionString \
  --output tsv
```

Save this connection string for `APPLICATIONINSIGHTS_CONNECTION_STRING`.

### 5.4 Create Function App

```bash
az functionapp create \
  --name vikas-servicing-fn \
  --resource-group rg-kiwi-demo \
  --plan kiwi-demo-plan \
  --storage-account rgkiwidemo88cf \
  --runtime python \
  --runtime-version 3.11 \
  --functions-version 4 \
  --os-type Linux \
  --app-insights kiwi-demo-insights
```

**Note:** Function App name must be globally unique. Replace `vikas-servicing-fn` with your chosen name.

---

## Step 6: Configure Function App Settings

Configure application settings for your Function App. Never commit these values to git.

The live deployment uses the following settings (separate operator-provided from platform-managed):

```bash
FUNC_APP_NAME="vikas-servicing-fn"
RG_NAME="rg-kiwi-demo"

az functionapp config appsettings set \
  --name "$FUNC_APP_NAME" \
  --resource-group "$RG_NAME" \
  --settings \
    "AzureWebJobsStorage=<paste-storage-connection-string>" \
    "STATEMENTS_STORAGE_CONNECTION_STRING=<paste-storage-connection-string>" \
    "DOCUMENTINTELLIGENCE_ENDPOINT=<paste-DI-endpoint>" \
    "DOCUMENTINTELLIGENCE_KEY=<paste-DI-key>" \
    "APPLICATIONINSIGHTS_CONNECTION_STRING=<paste-appinsights-connection-string>" \
    "EXTRACT_ALLOWED_BINDERS=vikas-samples" \
    "REPORTS_CONTAINER=vikas-reports" \
    "BATCHES_CONTAINER=vikas-batches"
```

### Application Setting Reference

Live observed settings include the following. **Do not blindly overwrite platform-managed settings.**

#### Operator-Provided Settings (Required)

These settings must be configured by you during deployment:

| Setting Name | Description | Example Value |
|---|---|---|
| `STATEMENTS_STORAGE_CONNECTION_STRING` | Statement storage account connection string | `DefaultEndpointsProtocol=https;AccountName=...` |
| `DOCUMENTINTELLIGENCE_ENDPOINT` | Document Intelligence resource endpoint | `https://kiwi-docs.cognitiveservices.azure.com/` |
| `DOCUMENTINTELLIGENCE_KEY` | Document Intelligence API key | `<32-character-hex-key>` |
| `EXTRACT_ALLOWED_BINDERS` | Comma-separated list of allowed container names | `vikas-samples` or `vikas-samples,prod-statements` |

#### Platform/Deployment-Managed Settings

These settings are typically managed by Azure during Function App creation or deployment. Verify they exist but do not overwrite unless explicitly required:

| Setting Name | Description | Managed By |
|---|---|---|
| `AzureWebJobsStorage` | Function App internal storage connection string | Azure (set during Function App creation) |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Application Insights connection string | Azure (set when linking App Insights) |
| `DEPLOYMENT_STORAGE_CONNECTION_STRING` | Deployment storage connection string | Azure deployment process |

#### Optional Override Settings

These settings have runtime defaults and only need to be set if you want to override the defaults:

| Setting Name | Description | Default Value |
|---|---|---|
| `REPORTS_CONTAINER` | Container for published reports | `vikas-reports` |
| `BATCHES_CONTAINER` | Container for batch storage | `vikas-batches` |
| `EXTRACT_URL_ALLOWED_HOSTS` | Comma-separated allowed URL hosts for `file_urls` fallback | `*.blob.core.windows.net` |

**Important:**
- Set the 4 operator-provided settings explicitly
- Verify platform-managed settings exist (they should be auto-configured)
- Only set optional overrides if you need different container names or allowed hosts

⚠️ **Security:** NEVER commit connection strings, keys, or SAS tokens to the repository.

---

## Step 7: Publish the Function App

From your local repository checkout:

```bash
cd function_app
func azure functionapp publish vikas-servicing-fn
```

**Expected output:**
```
Getting site publishing info...
Creating archive for current directory...
Uploading <size> KB...
Deployment successful.
Remote build succeeded!
```

### 7.1 Verify Deployment

```bash
az functionapp function list \
  --name vikas-servicing-fn \
  --resource-group rg-kiwi-demo \
  --output table
```

**Expected functions:**
- `extract_and_normalize`
- `compute_summary_http`
- `render_report`

### 7.2 Get Function App URL and Key

```bash
# Get the Function App host URL
az functionapp show \
  --name vikas-servicing-fn \
  --resource-group rg-kiwi-demo \
  --query defaultHostName \
  --output tsv

# Get the function key
az functionapp keys list \
  --name vikas-servicing-fn \
  --resource-group rg-kiwi-demo \
  --query functionKeys
```

Save the **default function key** - you'll need it for Foundry agent authentication.

---

## Step 8: Smoke Test the Functions

Test each function endpoint to verify deployment. These requests use empty bodies, so expect **400 validation errors** (not 404 or 500 - those indicate routing or runtime failures).

```bash
FUNC_HOST="<your-func-app>.azurewebsites.net"
FUNC_KEY="<paste-function-key>"

# Test extract_and_normalize
curl -X POST "https://${FUNC_HOST}/api/extract_and_normalize?code=${FUNC_KEY}" \
  -H "Content-Type: application/json" \
  -d '{}' \
  -w "\nHTTP Status: %{http_code}\n"

# Test compute_summary
curl -X POST "https://${FUNC_HOST}/api/compute_summary?code=${FUNC_KEY}" \
  -H "Content-Type: application/json" \
  -d '{}' \
  -w "\nHTTP Status: %{http_code}\n"

# Test render_report
curl -X POST "https://${FUNC_HOST}/api/render_report?code=${FUNC_KEY}" \
  -H "Content-Type: application/json" \
  -d '{}' \
  -w "\nHTTP Status: %{http_code}\n"
```

**✓ Success:** HTTP 400 with JSON error message (e.g., `"supply binder, file_urls or files; extraction has nothing to read"`)  
**✗ Failure:** HTTP 404 (function not found), 500 (runtime error), or connection timeout

---

## Step 9: Azure AI Foundry Setup

### 9.1 Prerequisites for Foundry

Ensure you have the following roles in your Azure AI Foundry project:
- **Foundry User** role (to access the project and chat interface)
- **Foundry Project Manager** role (to create connections and manage project resources)

These roles are required to create PROJECT CONNECTIONS for OpenAPI tool authentication.

### 9.2 Create AI Foundry Project

1. Navigate to **Azure AI Foundry** at https://ai.azure.com
2. Select your subscription and create a new **AI Hub** (if you don't have one)
3. Create a new **Project** under that hub:
   - Name: `kiwi-knowage-proj` (or your preferred name)
   - Region: Same as your Function App (e.g., `australiaeast`)

### 9.3 Deploy Chat Model

1. In your AI Foundry project, go to **Deployments** → **+ Create deployment**
2. **Choose a model and region that supports OpenAPI tools** (e.g., `gpt-4o`, `gpt-4-turbo`, or newer models in supported regions)
3. Configure:
   - Deployment name: Use a name consistent with the model you selected (e.g., `gpt-4o-deployment` for `gpt-4o`)
   - **Do NOT** name a non-gpt-5 deployment `gpt-5` - keep the deployment name aligned with the actual model
   - Model version: Latest available
   - Tokens per minute rate limit: Set according to your needs
4. **Deploy** and wait for the deployment to complete
5. Verify the deployment shows OpenAPI/function-calling support in the model capabilities

### 9.4 Create the Agent

1. In your AI Foundry project, go to **Agents** → **+ Create agent**
2. Configure:
   - Name: `vikas-agent-demo` (or your preferred name)
   - Model deployment: Select the deployment you created above
   - Description: "NZ bank statement servicing assessment agent"

### 9.5 Paste Agent Instructions

**⚠️ CRITICAL STEP:** The agent instructions define how the model classifies transactions and calls the functions.

1. Open the file `foundry/PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt` in your repository
2. **Copy the entire contents** of that file
3. In the agent configuration, go to the **Instructions** section
4. **Paste** the instructions into the text field
5. **Save** the agent

**When to re-paste instructions:**
- ✓ **DO re-paste** when updating the repository if `PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt` has changed
- ✗ **DON'T re-paste** if the file content is unchanged - keep existing tested instructions

The instruction file is byte-identical to `foundry/prompt-foundry-v2.md` on the `main` branch.

---

## Step 10: Attach Custom OpenAPI Service

This step connects your Foundry agent to the three Azure Functions you deployed.

### 10.1 Update OpenAPI Specification

1. Open `foundry/openapi-servicing.json` in your repository
2. Find the `servers` section (around line 10):

```json
"servers": [
  {
    "url": "https://vikas-servicing-fn-a3cacpaqhccgc7dy.australiaeast-01.azurewebsites.net/api"
  }
]
```

3. Replace the URL with your Function App URL:

```json
"servers": [
  {
    "url": "https://<your-func-app>.azurewebsites.net/api"
  }
]
```

**Note:** Include the `/api` path prefix. This is the route prefix configured in the Function App.

### 10.2 Create Custom Service in Foundry

1. In your AI Foundry agent, go to **Tools** or **Actions**
2. Click **+ Add** or **+ Add tool**
3. Select **Custom OpenAPI service** or **OpenAPI specified tool**
4. Configure:
   - **Name:** `vikas_servicing`
   - **Description:** `Extract NZ bank statements, compute servicing totals in code, render Excel and HTML reports. The model classifies only; never invents Part 1 numbers.`
   - **OpenAPI Specification:** Copy the **entire contents** of your updated `foundry/openapi-servicing.json` and paste it

### 10.3 Configure Authentication with PROJECT CONNECTION

Microsoft Foundry requires a **PROJECT CONNECTION** to authenticate OpenAPI tools. You cannot paste the Function key directly into the tool configuration.

The OpenAPI spec defines a security scheme `functionsKey`:

```json
"securitySchemes": {
  "functionsKey": {
    "type": "apiKey",
    "name": "x-functions-key",
    "in": "header"
  }
}
```

**Steps to create and use a PROJECT CONNECTION:**

1. In your AI Foundry project, go to **Settings** → **Connections** (or **Connected resources**)
2. Click **+ New connection** or **+ Add connection**
3. Select **Custom API** or **API key connection**
4. Configure the connection:
   - **Connection name:** `vikas-servicing-key` (or your preferred name)
   - **Key name:** `x-functions-key` (must match the OpenAPI security scheme exactly)
   - **Key value:** Paste your Function App default function key from Step 7.2
5. **Save** the connection

**Attach the connection to your OpenAPI tool:**

1. Return to your agent's **Tools** or **Actions** configuration
2. Find the `vikas_servicing` OpenAPI tool you created
3. In the **Authentication** section:
   - **Authentication type:** Select **Connection** or **Use connection**
   - **Select connection:** Choose `vikas-servicing-key` (the connection you created above)
4. **Save** the tool configuration

**Important:**
- The custom key name in the connection (`x-functions-key`) must match the `name` field in the OpenAPI `securitySchemes`
- **Do NOT** paste the Function key directly into the tool configuration - always use a PROJECT CONNECTION
- Verify your model and region support OpenAPI tools - older models or certain regions may not support function calling

**Alternative for production:** Use Managed Identity authentication if your Foundry project and Function App support it.

### 10.4 Verify Tool Attachment

1. Save the custom service
2. Confirm the tool shows **three operations**:
   - `extract_and_normalize`
   - `compute_summary`
   - `render_report`
3. Check that each operation displays parameter schemas correctly

**Additional reference:** See `foundry/HOW_TO_HANG_TOOLS.md` for detailed attachment instructions.

---

## Step 11: End-to-End Test

### 11.1 Upload Test Statements

Upload sample statement PDFs to your `vikas-samples` container (or whichever container you configured in `EXTRACT_ALLOWED_BINDERS`):

```bash
# Using Azure CLI
az storage blob upload \
  --container-name vikas-samples \
  --file ./path/to/statement.pdf \
  --name statement.pdf \
  --connection-string "$STORAGE_CONN"
```

**Important - PII and Data Handling:**
- **For smoke testing and Git/public repo use:** Use synthetic/test statements only. Never upload files containing real customer names or personal information to Git or public repositories.
- **For production use:** Real customer PII and production bank statements must only be stored in controlled private Azure storage under your organization's data governance policies. The service is designed to process real customer data in production environments with appropriate security controls.
- **This guide covers:** Deployment and smoke testing with synthetic data. Production data handling should follow your organization's compliance requirements.

### 11.2 Test Chat - Excel Output

In the Foundry agent chat interface:

**Prompt:**
```
Use binder vikas-samples and run the assessment.
```

**Optional with assessment date:**
```
Use binder vikas-samples, assessment_date 2026-09-24, and run the assessment.
```

**Expected behavior:**
1. Agent calls `extract_and_normalize` with `binder: "vikas-samples"`
2. Agent classifies the `classification_worklist` entries
3. Agent calls `compute_summary` with `batch_id` and classifications
4. Agent calls `render_report` with `summary_id`
5. Agent returns a **download URL** for `lender-assessment.xlsx`

### 11.3 Test Chat - HTML Output

**Prompt:**
```
Use binder vikas-samples and run the assessment in HTML format.
```

Or explicitly:
```
Use binder vikas-samples, format=html, and run the assessment.
```

**Expected behavior:**
- Same flow as above
- Agent calls `render_report` with `summary_id` and `format: "html"`
- Agent returns a **download URL** for `lender-assessment.html`

### 11.4 Test Chat - Both Formats

**Prompt:**
```
Use binder vikas-samples, format=both, and run the assessment.
```

**Expected behavior:**
- Agent calls `render_report` with `summary_id` and `format: "both"`
- Agent returns **two download URLs**: one for xlsx and one for html

---

## Step 12: Troubleshooting

### Common Issues

#### 401 Unauthorized
- **Cause:** Incorrect or missing Function key in Foundry authentication
- **Fix:** Verify the `x-functions-key` header value matches your Function App key from Step 7.2

#### 404 Not Found
- **Cause:** Function routes not deployed or incorrect OpenAPI server URL
- **Fix:** 
  - Verify functions deployed: `az functionapp function list --name <app> --resource-group <rg> --output table`
  - Check OpenAPI `servers[0].url` matches your Function App host

#### 400 Bad Request - "supply binder, file_urls or files"
- **Cause:** Agent not passing `binder` parameter correctly
- **Fix:** Re-check agent instructions match `PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt`

#### 500 Internal Server Error - "DOCUMENTINTELLIGENCE_ENDPOINT not configured"
- **Cause:** Missing Document Intelligence settings
- **Fix:** Verify all 7 app settings from Step 6 are configured

#### Tool not called / agent tries to do OCR itself
- **Cause:** Instructions not pasted, or Code Interpreter still enabled
- **Fix:** 
  - Re-paste instructions from `PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt`
  - Disable Code Interpreter in agent settings

#### Batch/summary truncated errors
- **Cause:** Agent passing `canonical` or `summary` instead of `batch_id`/`summary_id`
- **Fix:** Instructions already handle this; re-paste if error persists

### Viewing Function Logs

```bash
# Stream live logs
az functionapp log tail \
  --name vikas-servicing-fn \
  --resource-group rg-kiwi-demo

# View recent invocations in Application Insights
az monitor app-insights query \
  --app kiwi-demo-insights \
  --resource-group rg-kiwi-demo \
  --analytics-query "requests | where timestamp > ago(1h) | order by timestamp desc | take 20"
```

### Rollback to Previous Deployment

If a deployment fails:

1. Find the previous deployment ID:
```bash
az webapp log deployment list \
  --name vikas-servicing-fn \
  --resource-group rg-kiwi-demo \
  --query "[].{id:id, status:status, active:active, receivedTime:receivedTime}" \
  --output table
```

2. Re-deploy the last known-good commit:
```bash
git checkout <previous-commit-sha>
cd function_app
func azure functionapp publish vikas-servicing-fn
```

3. If Foundry instructions changed, restore previous version (only if PASTE file changed in the failed release)

---

## Privacy and Security Rules

### ⚠️ Never Commit Secrets

The following must **NEVER** be committed to git or public repositories:
- Connection strings (storage, Application Insights)
- API keys (Document Intelligence, Function keys)
- SAS tokens
- Real customer PII, names, or personal information
- Real bank statement files containing customer data

### Local-Only Content and Data Governance

- Folder `from vikas/` (if present on your local machine) is **local-only**. Never commit, push, or upload.
- **For Git/public repos:** Do not commit files containing real human names, customer PII, or statement-derived personal data.
- **For production deployments:** Real customer data belongs only in controlled private Azure storage under your organization's data governance and compliance policies (not in Git).
- `VIKAS-ATTACHMENTS-ANALYSIS.md` is host-private analysis and was removed in PR #6 - do not re-add.

### Rebuilding Merchant Memory

If you need to rebuild safe brand memory:
```bash
python3 pipeline/build_merchant_memory.py
```

This generates `function_app/merchant_memory.json` with safe fallback merchant classifications (no PII).

---

## Completion Checklist

Use this checklist to confirm your deployment is complete:

- [ ] Resource group created
- [ ] Storage account created with three containers (`samples`, `batches`, `reports`)
- [ ] Document Intelligence resource created and credentials obtained
- [ ] Function App created with App Service Plan and Application Insights
- [ ] All 7 application settings configured
- [ ] Functions published successfully (`func azure functionapp publish`)
- [ ] Smoke tests pass (HTTP 400 on empty body, not 404/500)
- [ ] AI Foundry project created with model deployed
- [ ] Foundry agent created with instructions pasted from `PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt`
- [ ] OpenAPI service attached with correct server URL and Function key auth
- [ ] End-to-end test produces xlsx download URL
- [ ] End-to-end test produces html download URL (when `format=html` or `format=both`)
- [ ] Test statements uploaded to samples container
- [ ] No secrets committed to repository

---

## What Gets Deployed

This diagram shows the complete architecture:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              USER / FOUNDRY CHAT                         │
└─────────────────────┬───────────────────────────────────────────────────┘
                      │
                      ▼
         ┌────────────────────────────┐
         │   Azure AI Foundry Agent   │
         │  ┌──────────────────────┐  │
         │  │ Model Deployment     │  │  ← Instructions from
         │  │ (gpt-4o, etc)        │  │    PASTE-THIS-INTO-FOUNDRY-
         │  └──────────────────────┘  │    AGENT-INSTRUCTIONS.txt
         │  ┌──────────────────────┐  │
         │  │ OpenAPI Custom Tool  │  │  ← openapi-servicing.json
         │  │ (vikas_servicing)    │  │
         │  └──────────────────────┘  │
         └────────────┬───────────────┘
                      │ Function-key auth (x-functions-key header)
                      │ ⚠️ NEVER commit keys to git
                      ▼
         ┌────────────────────────────┐
         │  Azure Function App        │
         │  /api prefix               │
         │                            │
         │  ┌──────────────────────┐  │
         │  │ extract_and_normalize│  │ ──┐
         │  └──────────────────────┘  │   │
         │  ┌──────────────────────┐  │   │
         │  │ compute_summary      │  │   │ HTTP endpoints
         │  └──────────────────────┘  │   │
         │  ┌──────────────────────┐  │   │
         │  │ render_report        │  │ ──┘
         │  └──────────────────────┘  │
         └────────┬──────────┬────────┘
                  │          │
                  │          └─────────────────────────┐
                  │                                    │
                  ▼                                    ▼
    ┌──────────────────────────┐       ┌──────────────────────────┐
    │ Document Intelligence    │       │ Blob Storage             │
    │ (prebuilt-layout OCR)    │       │                          │
    │                          │       │ • vikas-samples          │
    │ DOCUMENTINTELLIGENCE_    │       │   (input binders/PDFs)   │
    │   ENDPOINT + KEY         │       │ • vikas-batches          │
    └──────────────────────────┘       │   (batch_id, summary_id) │
                                       │ • vikas-reports          │
                                       │   (published xlsx/HTML)  │
                                       │                          │
                                       │ STATEMENTS_STORAGE_      │
                                       │   CONNECTION_STRING      │
                                       └──────────────────────────┘

DATA FLOW:
  Control/Request: User → Agent → Functions → DI/Blob
  Data/Response:   DI/Blob → Functions → Agent → xlsx/HTML download URL

SECRETS: Never commit to git
  - Function keys (x-functions-key for OpenAPI auth)
  - Storage connection strings
  - Document Intelligence keys
  - SAS tokens
```

---

## Additional Resources

- **OpenAPI Specification:** `foundry/openapi-servicing.json`
- **Agent Instructions:** `foundry/PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt`
- **Tool Attachment Guide:** `foundry/HOW_TO_HANG_TOOLS.md`
- **Repository README:** `README.md`
- **Classification Taxonomy:** `schemas/taxonomy.md`
- **Canonical Transaction Schema:** `schemas/canonical-transaction.schema.json`
- **Report View Schema:** `schemas/report-view.schema.json`

---

**Document version:** 2026-09-24  
**Covers:** Tasks T-16 (Markdown runbook)  
**Related deliverables:** `docs/AZURE_DEPLOYMENT_GUIDE.html` (T-17 with embedded SVG diagram T-18)
