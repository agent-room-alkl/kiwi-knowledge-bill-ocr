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

output "ai_foundry_key_vault_name" {
  description = "Key Vault name for AI Foundry (if created)"
  value       = var.create_ai_foundry_resources ? azurerm_key_vault.foundry[0].name : null
}

output "ai_foundry_ai_services_name" {
  description = "AI Services account name (if created)"
  value       = var.create_ai_foundry_resources ? azurerm_cognitive_account.ai_services[0].name : null
}

output "ai_foundry_ai_services_endpoint" {
  description = "AI Services endpoint (if created)"
  value       = var.create_ai_foundry_resources ? azurerm_cognitive_account.ai_services[0].endpoint : null
}

output "ai_foundry_model_deployment_name" {
  description = "AI Foundry model deployment name (if created)"
  value       = var.create_ai_foundry_resources && var.foundry_model_name != "" ? azapi_resource.model_deployment[0].name : null
}

output "ai_foundry_portal_url" {
  description = "Azure AI Foundry portal URL (if project created)"
  value       = var.create_ai_foundry_resources ? "https://ai.azure.com/resource/providers/Microsoft.MachineLearningServices/workspaces/${azapi_resource.ai_project[0].name}" : null
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
      project_name         = azapi_resource.ai_project[0].name
      hub_name             = azapi_resource.ai_hub[0].name
      key_vault_name       = azurerm_key_vault.foundry[0].name
      ai_services_name     = azurerm_cognitive_account.ai_services[0].name
      ai_services_endpoint = azurerm_cognitive_account.ai_services[0].endpoint
      model_deployment     = var.foundry_model_name != "" ? azapi_resource.model_deployment[0].name : null
      portal_url           = "https://ai.azure.com"
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
    
    ${var.create_ai_foundry_resources ? "4. MANUAL: Configure AI Foundry Agent and OpenAPI Tool\n       Terraform creates the Hub, Project, AI Services, and model deployment,\n       but CANNOT create Agents or attach OpenAPI tools via API.\n       \n       Portal: https://ai.azure.com\n       Project: ${azapi_resource.ai_project[0].name}\n       AI Services Endpoint: ${azurerm_cognitive_account.ai_services[0].endpoint}\n       Model Deployment: ${var.foundry_model_name != "" ? azapi_resource.model_deployment[0].name : "none (set foundry_model_name)"}\n       \n       Steps in Azure AI Portal:\n       a) Navigate to project ${azapi_resource.ai_project[0].name}\n       b) Create a new agent\n       c) Add OpenAPI tool:\n          - Upload the generated openapi-servicing-<suffix>.json (from step 3)\n          - Create PROJECT CONNECTION with Function key as 'x-functions-key' header\n          - Select the connection for the tool (do not paste key into tool spec)\n       d) Paste agent instructions from: foundry/PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt\n       \n       See: foundry/HOW_TO_HANG_TOOLS.md\n" : "4. Configure AI Foundry (manual - Terraform did not create Hub/Project):\n       - Go to https://ai.azure.com\n       - Create a new Hub and Project\n       - Create a Foundry agent\n       - Add OpenAPI tool using generated spec from step 3\n       - Set up PROJECT CONNECTION with Function key (x-functions-key)\n       - Paste agent instructions from: foundry/PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt\n"}
    
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
