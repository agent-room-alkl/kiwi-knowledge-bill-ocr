output "resource_group_name" {
  description = "Name of the resource group"
  value       = local.resource_group_name_final
}

output "function_app_name" {
  description = "Name of the Function App"
  value       = azurerm_linux_function_app.main.name
}

output "function_app_url" {
  description = "Function App base URL"
  value       = "https://${azurerm_linux_function_app.main.default_hostname}"
}

output "function_api_base_url" {
  description = "Function App API base URL (for OpenAPI spec)"
  value       = "https://${azurerm_linux_function_app.main.default_hostname}/api"
}

output "function_app_principal_id" {
  description = "Function App managed identity principal ID"
  value       = azurerm_linux_function_app.main.identity[0].principal_id
}

output "storage_account_name" {
  description = "Name of the storage account"
  value       = azurerm_storage_account.main.name
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
  value       = azurerm_storage_account.main.primary_connection_string
  sensitive   = true
}

output "document_intelligence_endpoint" {
  description = "Document Intelligence endpoint URL"
  value       = azurerm_cognitive_account.doc_intelligence.endpoint
}

output "document_intelligence_key" {
  description = "Document Intelligence API key"
  value       = azurerm_cognitive_account.doc_intelligence.primary_access_key
  sensitive   = true
}

output "application_insights_instrumentation_key" {
  description = "Application Insights instrumentation key"
  value       = azurerm_application_insights.main.instrumentation_key
  sensitive   = true
}

output "application_insights_connection_string" {
  description = "Application Insights connection string"
  value       = azurerm_application_insights.main.connection_string
  sensitive   = true
}

output "ai_foundry_hub_id" {
  description = "AI Foundry Hub resource ID (if created)"
  value       = var.create_ai_foundry_resources ? azapi_resource.ai_hub[0].id : null
}

output "ai_foundry_project_id" {
  description = "AI Foundry Project resource ID (if created)"
  value       = var.create_ai_foundry_resources ? azapi_resource.ai_project[0].id : null
}

output "ai_foundry_project_name" {
  description = "AI Foundry Project name (if created)"
  value       = var.create_ai_foundry_resources ? azapi_resource.ai_project[0].name : null
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
  value       = var.create_ai_foundry_resources ? "https://ai.azure.com/build/overview?wsid=/subscriptions/${data.azurerm_client_config.current.subscription_id}/resourceGroups/${local.resource_group_name_final}/providers/Microsoft.MachineLearningServices/workspaces/${azapi_resource.ai_project[0].name}" : null
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
      name     = azurerm_linux_function_app.main.name
      url      = "https://${azurerm_linux_function_app.main.default_hostname}"
      api_base = "https://${azurerm_linux_function_app.main.default_hostname}/api"
    }
    storage = {
      account    = azurerm_storage_account.main.name
      containers = local.containers
    }
    document_intelligence = {
      name     = azurerm_cognitive_account.doc_intelligence.name
      endpoint = azurerm_cognitive_account.doc_intelligence.endpoint
    }
    ai_foundry = var.create_ai_foundry_resources ? {
      project_name     = azapi_resource.ai_project[0].name
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
    
    Function App API Base URL: https://${azurerm_linux_function_app.main.default_hostname}/api
    
    NEXT STEPS:
    
    1. Deploy Function App code:
       cd ../function_app
       func azure functionapp publish ${azurerm_linux_function_app.main.name}
    
    2. Get Function App key (SECURE - DO NOT COMMIT):
       Option A: Azure Functions Core Tools
         func azure functionapp list-functions ${azurerm_linux_function_app.main.name} --show-keys
       Option B: Azure CLI
         az functionapp keys list --name ${azurerm_linux_function_app.main.name} --resource-group ${local.resource_group_name_final} --query functionKeys.default -o tsv
       Option C: Store in Key Vault (recommended for production)
         az keyvault secret set --vault-name <vault-name> --name function-key --value <key-from-above>
       
    3. Generate OpenAPI spec with correct Function URL:
       Option A: PowerShell script (Windows)
         cd infra/terraform
         .\deploy.ps1 -Action generate-openapi
         # Creates foundry/openapi-servicing-<suffix>.json with correct server URL
         # DO NOT COMMIT THIS FILE
       Option B: Manual (cross-platform)
         Run: pwsh infra/terraform/configure-foundry.ps1
         Or edit foundry/openapi-servicing.json manually:
           Set servers[0].url = "https://${azurerm_linux_function_app.main.default_hostname}/api"
    
    ${var.create_ai_foundry_resources ? "4. Configure AI Foundry Agent and OpenAPI Tool (MANUAL STEPS REQUIRED):\n       \n       Terraform has created:\n       - AI Foundry Hub: ${azapi_resource.ai_hub[0].name}\n       - AI Foundry Project: ${azapi_resource.ai_project[0].name}\n       - Key Vault: ${azurerm_key_vault.foundry[0].name}\n       ${var.foundry_model_name != "" ? "- Azure OpenAI: ${azurerm_cognitive_account.openai[0].name}\n       - Model Deployment: ${azurerm_cognitive_deployment.model[0].name} (${var.foundry_model_name})\n       \n       MANUAL PORTAL STEPS:\n       a) Go to Azure AI Portal: https://ai.azure.com\n       b) Open project: ${azapi_resource.ai_project[0].name}\n       c) In project, go to 'Connected resources' and add the OpenAI connection:\n          - Resource: ${azurerm_cognitive_account.openai[0].name}\n          - API key from: terraform output -raw ai_foundry_openai_key\n       d) Create a Foundry Agent in the project\n       e) Attach OpenAPI tool to the agent:\n          - Upload: foundry/openapi-servicing.json (with updated Function URL)\n          - Create PROJECT CONNECTION with Function key as 'x-functions-key'\n          - Get key: func azure functionapp list-functions ${azurerm_linux_function_app.main.name} --show-keys\n       f) Paste agent instructions from: foundry/PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt\n       \n       See: foundry/HOW_TO_HANG_TOOLS.md for detailed steps\n" : "- OpenAI endpoint: ${azurerm_cognitive_account.openai[0].endpoint}\n       - Model: ${var.foundry_model_name}\n       \n       MANUAL PORTAL STEPS:\n       a) Go to: https://ai.azure.com\n       b) Open project: ${azapi_resource.ai_project[0].name}\n       c) Create a Foundry Agent\n       d) Attach OpenAPI tool:\n          - Upload: foundry/openapi-servicing.json (with updated Function URL)\n          - CREATE PROJECT CONNECTION with Function key as 'x-functions-key'\n       e) Paste agent instructions from: foundry/PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt\n"}" : "4. Configure AI Foundry (if not created via Terraform):\n       - Go to https://ai.azure.com\n       - Create a new project (or use existing)\n       - Create a Foundry agent\n       - Add OpenAPI tool: foundry/openapi-servicing.json\n       - Set up PROJECT CONNECTION with Function key (x-functions-key)\n       - Paste agent instructions from: foundry/PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt"}
    
    
    Storage Containers: ${join(", ", local.containers)}
    Document Intelligence Endpoint: ${azurerm_cognitive_account.doc_intelligence.endpoint}
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
