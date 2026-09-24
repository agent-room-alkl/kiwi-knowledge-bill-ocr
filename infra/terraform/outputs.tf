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
      project_name = azapi_resource.ai_project[0].name
      portal_url   = "https://ai.azure.com"
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
    
    2. Get Function App key:
       func azure functionapp list-functions ${azurerm_linux_function_app.main.name} --show-keys
       
    3. Update OpenAPI spec with Function URL:
       Edit foundry/openapi-servicing.json
       Set servers[0].url to: https://${azurerm_linux_function_app.main.default_hostname}/api
    
    4. Configure AI Foundry (if not created via Terraform):
       - Go to https://ai.azure.com
       - Create a new project (or use existing)
       - Create a Foundry agent
       - Add OpenAPI tool: foundry/openapi-servicing.json
       - Set up PROJECT CONNECTION with Function key (x-functions-key)
       - Paste agent instructions from: foundry/PASTE-THIS-INTO-FOUNDRY-AGENT-INSTRUCTIONS.txt
    
    ${var.create_ai_foundry_resources ? "5. MANUAL: Configure Foundry Agent and OpenAPI Tool\n       Terraform cannot create Agents or attach OpenAPI tools.\n       - Portal: https://ai.azure.com\n       - Project: ${azapi_resource.ai_project[0].name}\n       - Add the agent manually\n       - Attach OpenAPI tool from foundry/openapi-servicing.json\n" : ""}
    
    Storage Containers: ${join(", ", local.containers)}
    Document Intelligence Endpoint: ${azurerm_cognitive_account.doc_intelligence.endpoint}
    
    SECURITY NOTES:
    - Function keys are sensitive - retrieve via Azure CLI, never commit
    - Storage connection strings marked sensitive in outputs
    - Use 'terraform output -json' to access sensitive values
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
