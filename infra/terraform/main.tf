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
# Validation for Existing Backend Configuration
# ===========================

locals {
  # Validate that required existing resource names are provided when use_existing_backend=true
  validate_existing_backend = var.use_existing_backend && (
    var.existing_function_app_name == "" ||
    var.existing_storage_account_name == "" ||
    var.existing_app_insights_name == ""
  ) ? tobool("ERROR: When use_existing_backend=true, you must provide existing_function_app_name, existing_storage_account_name, and existing_app_insights_name") : true

  # Validate that use_existing_resource_group is also true when use_existing_backend is true
  validate_rg_with_backend = var.use_existing_backend && !var.use_existing_resource_group ? tobool("ERROR: When use_existing_backend=true, use_existing_resource_group must also be true and resource_group_name must be set") : true

  # Validate that classic Hub/Project and NEW AIServices paths are not both enabled
  # DISABLED for T-37: allow coexistence during migration
  # validate_foundry_paths = var.create_ai_foundry_resources && var.create_foundry_aiservices ? tobool("ERROR: create_ai_foundry_resources (classic Hub/Project) and create_foundry_aiservices (NEW AIServices shape) are mutually exclusive. Enable only one.") : true
  validate_foundry_paths = true
}

# ===========================
# Random Suffix for Unique Names
# ===========================

resource "random_string" "suffix" {
  # Only generate random suffix when not using existing backend or unique_suffix not provided
  count   = var.use_existing_backend && var.unique_suffix != "" ? 0 : 1
  length  = 6
  special = false
  upper   = false
  numeric = true
  lower   = true
}

locals {
  # When using existing backend with explicit suffix, use that suffix for NEW Foundry resources
  # Otherwise use provided suffix or generated random
  suffix = var.unique_suffix != "" ? var.unique_suffix : (var.use_existing_backend ? "foundry" : random_string.suffix[0].result)

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

  # Application Insights is optional for the core OCR->classify->xlsx/HTML
  # pipeline. The classic AI Foundry Hub requires an Application Insights resource.
  # The NEW AIServices shape does NOT require Application Insights.
  enable_app_insights = var.enable_application_insights || var.create_ai_foundry_resources

  # Classic Hub/Project can be toggled independently (null = follow create_ai_foundry_resources)
  classic_hub_enabled = coalesce(var.create_classic_foundry_hub, var.create_ai_foundry_resources)

  # Determine whether to create backend resources
  create_backend_resources = !var.use_existing_backend
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
# Data Sources for Existing Backend Resources
# ===========================

data "azurerm_storage_account" "existing" {
  count               = var.use_existing_backend ? 1 : 0
  name                = var.existing_storage_account_name
  resource_group_name = local.resource_group_name_final
}

data "azurerm_application_insights" "existing" {
  count               = var.use_existing_backend ? 1 : 0
  name                = var.existing_app_insights_name
  resource_group_name = local.resource_group_name_final
}

data "azurerm_linux_function_app" "existing" {
  count               = var.use_existing_backend ? 1 : 0
  name                = var.existing_function_app_name
  resource_group_name = local.resource_group_name_final
}

data "azurerm_cognitive_account" "existing_doc_intelligence" {
  count               = var.use_existing_backend && var.existing_document_intelligence_name != "" ? 1 : 0
  name                = var.existing_document_intelligence_name
  resource_group_name = local.resource_group_name_final
}

data "azurerm_service_plan" "existing" {
  count               = var.use_existing_backend && var.existing_app_service_plan_name != "" ? 1 : 0
  name                = var.existing_app_service_plan_name
  resource_group_name = local.resource_group_name_final
}

# ===========================
# Storage Account
# ===========================

resource "azurerm_storage_account" "main" {
  count                    = local.create_backend_resources ? 1 : 0
  name                     = substr(local.storage_account_name, 0, 24)
  resource_group_name      = local.resource_group_name_final
  location                 = var.location
  account_tier             = var.storage_account_tier
  account_replication_type = var.storage_replication_type

  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false

  tags = local.common_tags
}

locals {
  # Reference existing or created storage account
  storage_account_id               = var.use_existing_backend ? data.azurerm_storage_account.existing[0].id : azurerm_storage_account.main[0].id
  storage_account_name_final       = var.use_existing_backend ? data.azurerm_storage_account.existing[0].name : azurerm_storage_account.main[0].name
  storage_account_primary_conn_str = var.use_existing_backend ? data.azurerm_storage_account.existing[0].primary_connection_string : azurerm_storage_account.main[0].primary_connection_string
  storage_account_primary_key      = var.use_existing_backend ? data.azurerm_storage_account.existing[0].primary_access_key : azurerm_storage_account.main[0].primary_access_key
}

resource "azurerm_storage_container" "main" {
  for_each              = local.create_backend_resources ? toset(local.containers) : []
  name                  = each.value
  storage_account_name  = azurerm_storage_account.main[0].name
  container_access_type = "private"
}

# ===========================
# Document Intelligence
# ===========================

resource "azurerm_cognitive_account" "doc_intelligence" {
  count               = local.create_backend_resources ? 1 : 0
  name                = local.doc_intel_name
  resource_group_name = local.resource_group_name_final
  location            = var.location
  kind                = "FormRecognizer"
  sku_name            = var.document_intelligence_sku

  custom_subdomain_name = local.doc_intel_name

  tags = local.common_tags
}

# ===========================
# Application Insights (optional, opt-in)
# ===========================

resource "azurerm_application_insights" "main" {
  count               = local.enable_app_insights && local.create_backend_resources ? 1 : 0
  name                = local.app_insights_name
  resource_group_name = local.resource_group_name_final
  location            = var.location
  application_type    = "web"

  tags = local.common_tags

  lifecycle {
    # Azure auto-links a managed Log Analytics workspace; don't try to null it
    ignore_changes = [workspace_id]
  }
}

locals {
  # Reference existing or created App Insights
  app_insights_id                  = var.use_existing_backend ? data.azurerm_application_insights.existing[0].id : (local.enable_app_insights ? azurerm_application_insights.main[0].id : null)
  app_insights_connection_string   = var.use_existing_backend ? data.azurerm_application_insights.existing[0].connection_string : (local.enable_app_insights ? azurerm_application_insights.main[0].connection_string : null)
  app_insights_instrumentation_key = var.use_existing_backend ? data.azurerm_application_insights.existing[0].instrumentation_key : (local.enable_app_insights ? azurerm_application_insights.main[0].instrumentation_key : null)
}

# ===========================
# App Service Plan (Linux)
# ===========================

resource "azurerm_service_plan" "main" {
  count               = local.create_backend_resources ? 1 : 0
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
  count               = local.create_backend_resources ? 1 : 0
  name                = local.function_app_name
  resource_group_name = local.resource_group_name_final
  location            = var.location

  service_plan_id            = azurerm_service_plan.main[0].id
  storage_account_name       = azurerm_storage_account.main[0].name
  storage_account_access_key = azurerm_storage_account.main[0].primary_access_key

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

  app_settings = merge(
    {
      # Platform/Deployment-Managed (auto-wired from Terraform)
      "AzureWebJobsStorage"      = azurerm_storage_account.main[0].primary_connection_string
      "AzureWebJobsFeatureFlags" = "EnableWorkerIndexing"
      "FUNCTIONS_WORKER_RUNTIME" = "python"
      "WEBSITE_RUN_FROM_PACKAGE" = "1"

      # Operator-Provided (set via terraform.tfvars)
      "DOCUMENTINTELLIGENCE_ENDPOINT"        = azurerm_cognitive_account.doc_intelligence[0].endpoint
      "DOCUMENTINTELLIGENCE_KEY"             = var.use_managed_identity ? "" : azurerm_cognitive_account.doc_intelligence[0].primary_access_key
      "STATEMENTS_STORAGE_CONNECTION_STRING" = azurerm_storage_account.main[0].primary_connection_string
      "EXTRACT_ALLOWED_BINDERS"              = join(",", local.containers)

      # Optional Container Overrides (operator can customize)
      "REPORTS_CONTAINER" = var.reports_container_override != "" ? var.reports_container_override : "vikas-reports"
      "BATCHES_CONTAINER" = var.batches_container_override != "" ? var.batches_container_override : "vikas-batches"
    },
    # Telemetry wiring only when Application Insights is created
    local.enable_app_insights ? {
      "APPLICATIONINSIGHTS_CONNECTION_STRING" = azurerm_application_insights.main[0].connection_string
    } : {}
  )

  identity {
    type = "SystemAssigned"
  }

  tags = local.common_tags

  lifecycle {
    ignore_changes = [
      # Platform/deploy mutates these keys after create; do not ignore the whole app_settings map
      app_settings["WEBSITE_RUN_FROM_PACKAGE"],
      app_settings["AzureWebJobsStorage"],
      app_settings["APPLICATIONINSIGHTS_CONNECTION_STRING"],
      site_config[0].application_insights_connection_string,
      site_config[0].application_insights_key,
    ]
  }
}

locals {
  # Reference existing or created Function App
  function_app_name_final       = var.use_existing_backend ? data.azurerm_linux_function_app.existing[0].name : azurerm_linux_function_app.main[0].name
  function_app_default_hostname = var.use_existing_backend ? data.azurerm_linux_function_app.existing[0].default_hostname : azurerm_linux_function_app.main[0].default_hostname
  function_app_principal_id     = var.use_existing_backend ? data.azurerm_linux_function_app.existing[0].identity[0].principal_id : azurerm_linux_function_app.main[0].identity[0].principal_id
}

# Grant Function App managed identity access to Document Intelligence
resource "azurerm_role_assignment" "func_to_doc_intel" {
  count                = var.use_managed_identity && local.create_backend_resources ? 1 : 0
  scope                = azurerm_cognitive_account.doc_intelligence[0].id
  role_definition_name = "Cognitive Services User"
  principal_id         = azurerm_linux_function_app.main[0].identity[0].principal_id
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

  lifecycle {
    # Hub/Project identities get access policies after create; do not strip them
    ignore_changes = [access_policy]
  }
}

resource "azapi_resource" "ai_hub" {
  count     = local.classic_hub_enabled ? 1 : 0
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
      storageAccount      = local.storage_account_id
      keyVault            = azurerm_key_vault.foundry[0].id
      applicationInsights = local.app_insights_id
    }
    kind = "Hub"
  }

  tags = local.common_tags

  depends_on = [azurerm_key_vault.foundry]
}

resource "azapi_resource" "ai_project" {
  count     = local.classic_hub_enabled ? 1 : 0
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

  lifecycle {
    # Azure assigns Microsoft.DefaultV2 after create
    ignore_changes = [rai_policy_name]
  }
}

# ===========================
# NEW Microsoft Foundry Shape: AIServices + Project (API 2025-06-01)
# ===========================

# This section implements the NEW Microsoft Foundry architecture visible in ai.azure.com/nextgen:
# - Parent: Microsoft.CognitiveServices/accounts kind=AIServices with allowProjectManagement=true
# - Child: Microsoft.CognitiveServices/accounts/projects (nested under AIServices account)
# - Deployments: Microsoft.CognitiveServices/accounts/deployments (under AIServices account)
#
# This shape is DIFFERENT from the classic Hub/Project path above (MachineLearningServices workspaces).
# Use create_foundry_aiservices=true to enable this path (default: true).
#
# IMPORTANT: `kind` must be at the TOP LEVEL of the azapi body, NOT inside body.properties.
# Placing `kind` inside properties causes azapi schema validation failures.
#
# Region: var.location (default australiaeast)
# Model: gpt-4o with version 2024-11-20 (Standard SKU) or 2024-05-13 (GlobalStandard SKU)
# API Version: 2025-06-01 for all resources in this section
#
# Gating: When create_foundry_aiservices=false, terraform plan produces NO changes to existing state.
# The classic Hub/Project path can be independently disabled when this path is enabled.

# AIServices account with allowProjectManagement=true (parent resource)
resource "azapi_resource" "aiservices_account" {
  count                     = var.create_foundry_aiservices ? 1 : 0
  type                      = "Microsoft.CognitiveServices/accounts@2025-06-01"
  name                      = "${var.project_name}-aiservices-${local.suffix}"
  location                  = var.location
  parent_id                 = local.resource_group_id
  schema_validation_enabled = false

  identity {
    type = "SystemAssigned"
  }

  body = {
    kind = "AIServices"
    properties = {
      customSubDomainName    = "${var.project_name}-aiservices-${local.suffix}"
      allowProjectManagement = true
      publicNetworkAccess    = "Enabled"
      networkAcls = {
        defaultAction = "Allow"
      }
    }
    sku = {
      name = "S0"
    }
  }

  tags = local.common_tags
}

# Project resource (child of AIServices account)
resource "azapi_resource" "aiservices_project" {
  count                     = var.create_foundry_aiservices ? 1 : 0
  type                      = "Microsoft.CognitiveServices/accounts/projects@2025-06-01"
  name                      = "${var.project_name}-proj-${local.suffix}"
  location                  = var.location
  parent_id                 = azapi_resource.aiservices_account[0].id
  schema_validation_enabled = false

  identity {
    type = "SystemAssigned"
  }

  body = {
    properties = {
      friendlyName = "${var.project_name} Foundry Project"
    }
  }

  tags = local.common_tags

  depends_on = [azapi_resource.aiservices_gpt4o_deployment]
}

# GPT-4o deployment under the AIServices account
resource "azapi_resource" "aiservices_gpt4o_deployment" {
  count                     = var.create_foundry_aiservices ? 1 : 0
  type                      = "Microsoft.CognitiveServices/accounts/deployments@2025-06-01"
  name                      = "gpt-4o"
  parent_id                 = azapi_resource.aiservices_account[0].id
  schema_validation_enabled = false

  body = {
    properties = {
      model = {
        format  = "OpenAI"
        name    = "gpt-4o"
        version = var.foundry_aiservices_model_version
      }
    }
    sku = {
      name     = var.foundry_aiservices_sku
      capacity = var.foundry_aiservices_model_capacity
    }
  }

  depends_on = [azapi_resource.aiservices_account]

  lifecycle {
    # Azure assigns rai_policy_name after create
    ignore_changes = [body.properties.raiPolicyName]
  }
}
