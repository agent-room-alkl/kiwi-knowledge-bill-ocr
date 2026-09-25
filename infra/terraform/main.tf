terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.15.0"
    }
    azapi = {
      source  = "azure/azapi"
      version = "~> 2.1.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6.0"
    }
  }

  # IMPORTANT: Configure remote state before production use
  # backend "azurerm" {
  #   resource_group_name  = "terraform-state-rg"
  #   storage_account_name = "tfstate<unique>"
  #   container_name       = "tfstate"
  #   key                  = "kiwi-knowledge-bill-ocr.tfstate"
  #   use_azuread_auth     = true
  # }
}

provider "azurerm" {
  features {
    resource_group {
      prevent_deletion_if_contains_resources = true
    }
    key_vault {
      purge_soft_delete_on_destroy = false
    }
  }
  subscription_id = var.subscription_id != "" ? var.subscription_id : null
}

provider "azapi" {
  subscription_id = var.subscription_id != "" ? var.subscription_id : null
}

provider "random" {}

# Required for Key Vault access policy configuration
data "azurerm_client_config" "current" {}

# ===========================
# Random Suffix for Unique Names
# ===========================

resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
  numeric = true
  lower   = true
}

locals {
  suffix = var.unique_suffix != "" ? var.unique_suffix : random_string.suffix.result

  # Resource naming
  resource_group_name   = var.resource_group_name != "" ? var.resource_group_name : "${var.project_name}-rg-${local.suffix}"
  storage_account_name  = lower(replace("${var.project_name}sa${local.suffix}", "/[^a-z0-9]/", ""))
  function_app_name     = "${var.project_name}-func-${local.suffix}"
  app_service_plan_name = "${var.project_name}-asp-${local.suffix}"
  app_insights_name     = "${var.project_name}-ai-${local.suffix}"
  doc_intel_name        = "${var.project_name}-di-${local.suffix}"

  # Storage containers
  containers = var.storage_containers

  # Tags
  common_tags = merge(
    {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
    },
    var.tags
  )
}

# ===========================
# Resource Group
# ===========================

data "azurerm_resource_group" "existing" {
  count = var.use_existing_resource_group ? 1 : 0
  name  = var.resource_group_name
}

resource "azurerm_resource_group" "main" {
  count    = var.use_existing_resource_group ? 0 : 1
  name     = local.resource_group_name
  location = var.location
  tags     = local.common_tags
}

locals {
  resource_group_name_final = var.use_existing_resource_group ? data.azurerm_resource_group.existing[0].name : azurerm_resource_group.main[0].name
  resource_group_id         = var.use_existing_resource_group ? data.azurerm_resource_group.existing[0].id : azurerm_resource_group.main[0].id
}

# ===========================
# Storage Account
# ===========================

resource "azurerm_storage_account" "main" {
  name                     = substr(local.storage_account_name, 0, 24)
  resource_group_name      = local.resource_group_name_final
  location                 = var.location
  account_tier             = var.storage_account_tier
  account_replication_type = var.storage_replication_type

  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false

  tags = local.common_tags
}

resource "azurerm_storage_container" "main" {
  for_each              = toset(local.containers)
  name                  = each.value
  storage_account_name  = azurerm_storage_account.main.name
  container_access_type = "private"
}

# ===========================
# Document Intelligence
# ===========================

resource "azurerm_cognitive_account" "doc_intelligence" {
  name                = local.doc_intel_name
  resource_group_name = local.resource_group_name_final
  location            = var.location
  kind                = "FormRecognizer"
  sku_name            = var.document_intelligence_sku

  custom_subdomain_name = local.doc_intel_name

  tags = local.common_tags
}

# ===========================
# Application Insights
# ===========================

resource "azurerm_application_insights" "main" {
  name                = local.app_insights_name
  resource_group_name = local.resource_group_name_final
  location            = var.location
  application_type    = "web"

  tags = local.common_tags
}

# ===========================
# App Service Plan (Linux)
# ===========================

resource "azurerm_service_plan" "main" {
  name                = local.app_service_plan_name
  resource_group_name = local.resource_group_name_final
  location            = var.location
  os_type             = "Linux"
  sku_name            = var.app_service_plan_sku

  tags = local.common_tags
}

# ===========================
# Function App (Python 3.11)
# ===========================

resource "azurerm_linux_function_app" "main" {
  name                = local.function_app_name
  resource_group_name = local.resource_group_name_final
  location            = var.location

  service_plan_id            = azurerm_service_plan.main.id
  storage_account_name       = azurerm_storage_account.main.name
  storage_account_access_key = azurerm_storage_account.main.primary_access_key

  site_config {
    application_stack {
      python_version = "3.11"
    }

    cors {
      allowed_origins = ["https://portal.azure.com"]
    }

    # Production hardening
    ftps_state          = "FtpsOnly"
    http2_enabled       = true
    minimum_tls_version = "1.2"
  }

  app_settings = {
    # Platform/Deployment-Managed (auto-wired from Terraform)
    "APPLICATIONINSIGHTS_CONNECTION_STRING" = azurerm_application_insights.main.connection_string
    "AzureWebJobsStorage"                   = azurerm_storage_account.main.primary_connection_string
    "AzureWebJobsFeatureFlags"              = "EnableWorkerIndexing"
    "FUNCTIONS_WORKER_RUNTIME"              = "python"
    "WEBSITE_RUN_FROM_PACKAGE"              = "1"

    # Operator-Provided (set via terraform.tfvars)
    "DOCUMENTINTELLIGENCE_ENDPOINT"        = azurerm_cognitive_account.doc_intelligence.endpoint
    "DOCUMENTINTELLIGENCE_KEY"             = var.use_managed_identity ? "" : azurerm_cognitive_account.doc_intelligence.primary_access_key
    "STATEMENTS_STORAGE_CONNECTION_STRING" = azurerm_storage_account.main.primary_connection_string
    "EXTRACT_ALLOWED_BINDERS"              = join(",", local.containers)

    # Optional Container Overrides (operator can customize)
    "REPORTS_CONTAINER" = var.reports_container_override != "" ? var.reports_container_override : "vikas-reports"
    "BATCHES_CONTAINER" = var.batches_container_override != "" ? var.batches_container_override : "vikas-batches"
  }

  identity {
    type = "SystemAssigned"
  }

  tags = local.common_tags

  lifecycle {
    ignore_changes = [
      # Allow manual code deployments without Terraform drift
      app_settings["WEBSITE_RUN_FROM_PACKAGE"],
    ]
  }
}

# Grant Function App managed identity access to Document Intelligence
resource "azurerm_role_assignment" "func_to_doc_intel" {
  count                = var.use_managed_identity ? 1 : 0
  scope                = azurerm_cognitive_account.doc_intelligence.id
  role_definition_name = "Cognitive Services User"
  principal_id         = azurerm_linux_function_app.main.identity[0].principal_id
}

# ===========================
# Azure AI Foundry (Preview - Best Effort)
# ===========================

# Note: Azure AI Foundry Hub/Project resources are supported via azapi provider
# Agent and OpenAPI Tool attachments must be configured manually in the portal
# See: https://learn.microsoft.com/en-us/azure/ai-studio/

# Key Vault for AI Foundry (required when create_ai_foundry_resources = true)
resource "azurerm_key_vault" "foundry" {
  count                      = var.create_ai_foundry_resources ? 1 : 0
  name                       = substr("${var.project_name}-kv-${local.suffix}", 0, 24)
  resource_group_name        = local.resource_group_name_final
  location                   = var.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  soft_delete_retention_days = 7
  purge_protection_enabled   = false

  access_policy {
    tenant_id = data.azurerm_client_config.current.tenant_id
    object_id = data.azurerm_client_config.current.object_id

    key_permissions = [
      "Get", "List", "Create", "Delete", "Update", "Recover", "Purge", "GetRotationPolicy"
    ]

    secret_permissions = [
      "Get", "List", "Set", "Delete", "Recover", "Purge"
    ]

    certificate_permissions = [
      "Get", "List", "Create", "Delete", "Update", "Recover", "Purge"
    ]
  }

  tags = local.common_tags
}

resource "azapi_resource" "ai_hub" {
  count     = var.create_ai_foundry_resources ? 1 : 0
  type      = "Microsoft.MachineLearningServices/workspaces@2024-10-01-preview"
  name      = "${var.project_name}-aihub-${local.suffix}"
  location  = var.location
  parent_id = local.resource_group_id

  identity {
    type = "SystemAssigned"
  }

  body = {
    properties = {
      description         = "AI Foundry Hub for ${var.project_name}"
      friendlyName        = "${var.project_name} AI Hub"
      kind                = "Hub"
      storageAccount      = azurerm_storage_account.main.id
      keyVault            = azurerm_key_vault.foundry[0].id
      applicationInsights = azurerm_application_insights.main.id
    }
    kind = "Hub"
  }

  tags = local.common_tags

  depends_on = [azurerm_key_vault.foundry]
}

resource "azapi_resource" "ai_project" {
  count     = var.create_ai_foundry_resources ? 1 : 0
  type      = "Microsoft.MachineLearningServices/workspaces@2024-10-01-preview"
  name      = "${var.project_name}-aiproject-${local.suffix}"
  location  = var.location
  parent_id = local.resource_group_id

  identity {
    type = "SystemAssigned"
  }

  body = {
    properties = {
      description   = "AI Foundry Project for ${var.project_name}"
      friendlyName  = "${var.project_name} AI Project"
      kind          = "Project"
      hubResourceId = azapi_resource.ai_hub[0].id
    }
    kind = "Project"
  }

  tags = local.common_tags

  depends_on = [azapi_resource.ai_hub]
}

# Azure OpenAI / Cognitive Services account for model deployments
# This is separate from the AI Foundry Hub/Project - it provides the actual AI models
resource "azurerm_cognitive_account" "openai" {
  count               = var.create_ai_foundry_resources && var.foundry_model_name != "" ? 1 : 0
  name                = "${var.project_name}-openai-${local.suffix}"
  resource_group_name = local.resource_group_name_final
  location            = var.location
  kind                = "OpenAI"
  sku_name            = "S0"

  custom_subdomain_name = "${var.project_name}-openai-${local.suffix}"

  tags = local.common_tags
}

# Model deployment under the Cognitive Services account
# Note: This creates the model deployment, but connecting it to the Foundry Project
# must be done manually in the Azure AI Portal
resource "azurerm_cognitive_deployment" "model" {
  count                = var.create_ai_foundry_resources && var.foundry_model_name != "" ? 1 : 0
  name                 = var.foundry_deployment_name
  cognitive_account_id = azurerm_cognitive_account.openai[0].id

  model {
    format  = "OpenAI"
    name    = var.foundry_model_name
    version = var.foundry_model_version
  }

  sku {
    name     = "Standard"
    capacity = var.foundry_model_capacity
  }

  depends_on = [azurerm_cognitive_account.openai]
}
