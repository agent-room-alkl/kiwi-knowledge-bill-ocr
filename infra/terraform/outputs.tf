output "resource_group_name" {
  description = "Name of the resource group"
  value       = local.resource_group_name_final
}

output "function_app_name" {
  description = "Name of the Function App"
  value       = local.function_app_name_final
}

output "function_app_url" {
  description = "Function App base URL"
  value       = "https://${local.function_app_default_hostname}"
}

output "function_api_base_url" {
  description = "Function App API base URL (for OpenAPI spec)"
  value       = "https://${local.function_app_default_hostname}/api"
}

output "function_app_principal_id" {
  description = "Function App managed identity principal ID"
  value       = local.function_app_principal_id
}

output "storage_account_name" {
  description = "Name of the storage account"
  value       = local.storage_account_name_final
}

output "storage_containers" {
  description = "Storage container names"
  value = {
    input_containers = local.containers
    reports          = var.reports_container_override != "" ? var.reports_container_override : "vikas-reports"
    batches          = var.batches_container_override != "" ? var.batches_container_override : "vikas-batches"
  }
}

output "storage_connection_string" {
  description = "Storage account connection string"
  value       = local.storage_account_primary_conn_str
  sensitive   = true
}

output "document_intelligence_endpoint" {
  description = "Document Intelligence endpoint URL (null when using existing backend without DI reference)"
  value       = local.create_backend_resources ? azurerm_cognitive_account.doc_intelligence[0].endpoint : (var.existing_document_intelligence_name != "" ? data.azurerm_cognitive_account.existing_doc_intelligence[0].endpoint : null)
}

output "document_intelligence_key" {
  description = "Document Intelligence API key (null when using existing backend without DI reference)"
  value       = local.create_backend_resources ? azurerm_cognitive_account.doc_intelligence[0].primary_access_key : (var.existing_document_intelligence_name != "" ? data.azurerm_cognitive_account.existing_doc_intelligence[0].primary_access_key : null)
  sensitive   = true
}

output "application_insights_instrumentation_key" {
  description = "Application Insights instrumentation key (null when telemetry is disabled)"
  value       = local.app_insights_instrumentation_key
  sensitive   = true
}

output "application_insights_connection_string" {
  description = "Application Insights connection string (null when telemetry is disabled)"
  value       = local.app_insights_connection_string
  sensitive   = true
}

output "ai_foundry_hub_id" {
  description = "AI Foundry Hub resource ID (if created)"
  value       = local.classic_hub_enabled ? azapi_resource.ai_hub[0].id : null
}

output "ai_foundry_project_id" {
  description = "AI Foundry Project resource ID (if created)"
  value       = local.classic_hub_enabled ? azapi_resource.ai_project[0].id : null
}

output "ai_foundry_project_name" {
  description = "AI Foundry Project name (if created)"
  value       = local.classic_hub_enabled ? azapi_resource.ai_project[0].name : null
}

output "ai_foundry_openai_endpoint" {
  description = "Azure OpenAI endpoint URL (if created)"
  value       = var.create_ai_foundry_resources && var.foundry_model_name != "" ? azurerm_cognitive_account.openai[0].endpoint : null
}

output "ai_foundry_openai_key" {
  description = "Azure OpenAI API key (if created)"
  value       = var.create_ai_foundry_resources && var.foundry_model_name != "" ? azurerm_cognitive_account.openai[0].primary_access_key : null
  sensitive   = true
}

output "ai_foundry_model_deployment_name" {
  description = "AI Foundry model deployment name (if created)"
  value       = var.create_ai_foundry_resources && var.foundry_model_name != "" ? azurerm_cognitive_deployment.model[0].name : null
}

output "ai_foundry_portal_url" {
  description = "Azure AI Foundry portal URL (if project created)"
  value       = local.classic_hub_enabled ? "https://ai.azure.com/build/overview?wsid=/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/${local.resource_group_name_final}/providers/Microsoft.MachineLearningServices/workspaces/${try(azapi_resource.ai_project[0].name, "n/a (classic project disabled)")}" : null
}

output "ai_foundry_key_vault_name" {
  description = "Key Vault name for AI Foundry (if created)"
  value       = var.create_ai_foundry_resources ? azurerm_key_vault.foundry[0].name : null
}

# ===========================
# Summary Outputs for Next Steps
# ===========================

output "deployment_summary" {
  description = "Deployment summary with key information"
  value = {
    function_app = {
      name     = local.function_app_name_final
      url      = "https://${local.function_app_default_hostname}"
      api_base = "https://${local.function_app_default_hostname}/api"
    }
    storage = {
      account    = local.storage_account_name_final
      containers = local.containers
    }
    document_intelligence = local.create_backend_resources ? {
      name     = azurerm_cognitive_account.doc_intelligence[0].name
      endpoint = azurerm_cognitive_account.doc_intelligence[0].endpoint
      } : (var.existing_document_intelligence_name != "" ? {
        name     = var.existing_document_intelligence_name
        endpoint = data.azurerm_cognitive_account.existing_doc_intelligence[0].endpoint
    } : null)
    ai_foundry = var.create_ai_foundry_resources ? {
      project_name     = local.classic_hub_enabled ? azapi_resource.ai_project[0].name : null
      portal_url       = "https://ai.azure.com"
      openai_endpoint  = var.foundry_model_name != "" ? azurerm_cognitive_account.openai[0].endpoint : null
      model_deployment = var.foundry_model_name != "" ? azurerm_cognitive_deployment.model[0].name : null
    } : null
  }
}

output "next_steps" {
  description = "Manual steps required after Terraform deployment"
  value       = <<-EOT
    ===========================
    DEPLOYMENT COMPLETE
    ===========================
    
    Function App API Base URL: https://${local.function_app_default_hostname}/api
    
    NEXT STEPS:
    
    ${!var.use_existing_backend ? "1. Deploy Function App code:\n       cd ../function_app\n       func azure functionapp publish ${local.function_app_name_final}\n    \n    2. Get Function App key (SECURE - DO NOT COMMIT):\n       Option A: Azure Functions Core Tools\n         func azure functionapp list-functions ${local.function_app_name_final} --show-keys\n       Option B: Azure CLI\n         az functionapp keys list --name ${local.function_app_name_final} --resource-group ${local.resource_group_name_final} --query functionKeys.default -o tsv\n       Option C: Store in Key Vault (recommended for production)\n         az keyvault secret set --vault-name <vault-name> --name function-key --value <key-from-above>\n       \n    3. Generate OpenAPI spec with correct Function URL:\n       Option A: PowerShell script (Windows)\n         cd infra/terraform\n         .\\deploy.ps1 -Action generate-openapi\n         # Creates foundry/openapi-servicing-<suffix>.json with correct server URL\n         # DO NOT COMMIT THIS FILE\n       Option B: Manual (cross-platform)\n         Run: pwsh infra/terraform/configure-foundry.ps1\n         Or edit foundry/openapi-servicing.json manually:\n           Set servers[0].url = \"https://${local.function_app_default_hostname}/api\"\n    " : "NOTE: Using EXISTING backend resources (use_existing_backend=true)\n    - Function App: ${local.function_app_name_final}\n    - Storage Account: ${local.storage_account_name_final}\n    - App Insights: ${var.existing_app_insights_name}\n    \n    1. Get Function App key (if not already retrieved):\n       az functionapp keys list --name ${local.function_app_name_final} --resource-group ${local.resource_group_name_final} --query functionKeys.default -o tsv\n    \n    2. OpenAPI spec should already point to: https://${local.function_app_default_hostname}/api\n    "}
    ${var.create_ai_foundry_resources ? "AI FOUNDRY CONFIGURATION (MANUAL STEPS REQUIRED):\n       \n       Terraform has created:\n       - AI Foundry Hub: ${try(azapi_resource.ai_hub[0].name, "n/a (classic hub disabled)")}\n       - AI Foundry Project: ${try(azapi_resource.ai_project[0].name, "n/a (classic project disabled)")}\n       - Key Vault: ${azurerm_key_vault.foundry[0].name}\n       ${var.foundry_model_name != "" ? "- Azure OpenAI: ${azurerm_cognitive_account.openai[0].name}\n       - Model Deployment: ${azurerm_cognitive_deployment.model[0].name} (${var.foundry_model_name})\n       \n       MANUAL PORTAL STEPS:\n       a) Go to Azure AI Portal: https://ai.azure.com\n       b) Open project: ${try(azapi_resource.ai_project[0].name, "n/a (classic project disabled)")}\n       c) In project, go to 'Connected resources' and add the OpenAI connection:\n          - Resource: ${azurerm_cognitive_account.openai[0].name}\n          - API key from: terraform output -raw ai_foundry_openai_key\n       d) Create a Foundry Agent in the project\n       e) Attach OpenAPI tool to the agent:\n          - Upload: foundry/openapi-servicing.json (with updated Function URL)\n          - Create PROJECT CONNECTION with Function key as 'x-functions-key'\n          - Get key: az functionapp keys list --name ${local.function_app_name_final} --resource-group ${local.resource_group_name_final} --query functionKeys.default -o tsv\n       f) Paste agent instructions from: foundry/PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt\n       \n       See: foundry/HOW_TO_HANG_TOOLS.md for detailed steps\n" : "- Classic Azure OpenAI account: skipped (foundry_model_name empty)\n       \n       MANUAL PORTAL STEPS:\n       a) Go to: https://ai.azure.com/nextgen\n       b) Open the AIServices project (terraform output aiservices_project_name)\n       c) Create a Foundry Agent\n       d) Attach OpenAPI tool:\n          - Upload: foundry/openapi-servicing.json (with updated Function URL)\n          - CREATE PROJECT CONNECTION with Function key as 'x-functions-key'\n       e) Paste agent instructions from: foundry/PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt\n"}" : "Configure AI Foundry (if not created via Terraform):\n       - Go to https://ai.azure.com/nextgen\n       - Create a new project (or use existing)\n       - Create a Foundry agent\n       - Add OpenAPI tool: foundry/openapi-servicing.json\n       - Set up PROJECT CONNECTION with Function key (x-functions-key)\n       - Paste agent instructions from: foundry/PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt"}
    
    
    ${var.create_foundry_aiservices ? "NEW MICROSOFT FOUNDRY (visible in Azure Foundry / ai.azure.com/nextgen):\n       - AIServices: ${try(azapi_resource.aiservices_account[0].name, "pending apply")}\n       - Project: ${try(azapi_resource.aiservices_project[0].name, "pending apply")}\n       - Model: gpt-4o\n" : ""}
    Storage Containers: ${join(", ", local.containers)}
    ${local.create_backend_resources || var.existing_document_intelligence_name != "" ? "Document Intelligence Endpoint: ${local.create_backend_resources ? azurerm_cognitive_account.doc_intelligence[0].endpoint : data.azurerm_cognitive_account.existing_doc_intelligence[0].endpoint}" : ""}
    ${var.create_ai_foundry_resources ? "Key Vault: ${azurerm_key_vault.foundry[0].name}" : ""}
    
    SECURITY NOTES:
    - Function keys are SENSITIVE - retrieve via Azure CLI or Key Vault, NEVER commit to Git
    - Function keys must NOT appear in terraform outputs, committed files, or OpenAPI specs
    - Generated openapi-servicing-<suffix>.json is environment-specific - DO NOT COMMIT
    - Storage connection strings marked sensitive in outputs
    - Use 'terraform output -json' to access sensitive values (storage keys, Document Intelligence key)
    - Configure remote state backend before production use
    EOT
}

output "openapi_spec_path" {
  description = "Path to OpenAPI spec file that needs the Function URL"
  value       = "foundry/openapi-servicing.json"
}

output "agent_instructions_path" {
  description = "Path to agent instructions file for Foundry"
  value       = "foundry/PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt"
}

# ===========================
# NEW Microsoft Foundry Shape Outputs (AIServices + Project)
# ===========================

output "aiservices_account_id" {
  description = "AIServices account resource ID (NEW Foundry shape, if created)"
  value       = var.create_foundry_aiservices ? azapi_resource.aiservices_account[0].id : null
}

output "aiservices_account_name" {
  description = "AIServices account name (NEW Foundry shape, if created)"
  value       = var.create_foundry_aiservices ? azapi_resource.aiservices_account[0].name : null
}

output "aiservices_account_endpoint" {
  description = "AIServices account endpoint URL (NEW Foundry shape, if created)"
  value       = var.create_foundry_aiservices ? (try(azapi_resource.aiservices_account[0].output.properties.endpoint, null) != null ? azapi_resource.aiservices_account[0].output.properties.endpoint : "https://${azapi_resource.aiservices_account[0].name}.cognitiveservices.azure.com/") : null
}

output "aiservices_project_id" {
  description = "AIServices project resource ID (NEW Foundry shape, if created)"
  value       = var.create_foundry_aiservices ? azapi_resource.aiservices_project[0].id : null
}

output "aiservices_project_name" {
  description = "AIServices project name (NEW Foundry shape, if created)"
  value       = var.create_foundry_aiservices ? azapi_resource.aiservices_project[0].name : null
}

output "aiservices_gpt4o_deployment_name" {
  description = "GPT-4o deployment name under AIServices account (NEW Foundry shape, if created)"
  value       = var.create_foundry_aiservices ? azapi_resource.aiservices_gpt4o_deployment[0].name : null
}

output "aiservices_portal_url" {
  description = "Azure AI Foundry nextgen portal URL for the project (NEW Foundry shape, if created)"
  value       = var.create_foundry_aiservices ? "https://ai.azure.com/nextgen/project${azapi_resource.aiservices_project[0].id}" : null
}
