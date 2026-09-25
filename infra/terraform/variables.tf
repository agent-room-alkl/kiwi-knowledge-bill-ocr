variable "subscription_id" {
  description = "Azure subscription ID. If empty, deploy.ps1 exports ARM_SUBSCRIPTION_ID from az account show."
  type        = string
  default     = ""
}

variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
  default     = "kiwi-ocr"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,20}$", var.project_name))
    error_message = "Project name must be 3-20 characters, lowercase alphanumeric and hyphens only"
  }
}

variable "unique_suffix" {
  description = "Unique suffix for resource names. If empty, a random 6-character suffix is generated"
  type        = string
  default     = ""

  validation {
    condition     = var.unique_suffix == "" || can(regex("^[a-z0-9]{4,8}$", var.unique_suffix))
    error_message = "Suffix must be empty or 4-8 lowercase alphanumeric characters"
  }
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be dev, staging, or prod"
  }
}

variable "location" {
  description = "Azure region for resources"
  type        = string
  default     = "australiaeast"
}

# ===========================
# Resource Group
# ===========================

variable "use_existing_resource_group" {
  description = "Use an existing resource group instead of creating a new one"
  type        = bool
  default     = false
}

variable "resource_group_name" {
  description = "Resource group name. Required if use_existing_resource_group is true"
  type        = string
  default     = ""
}

# ===========================
# Backend Resources (optional reuse)
# ===========================

variable "use_existing_backend" {
  description = "Use existing backend resources (Storage, Function App, App Insights, etc.) instead of creating new ones. Enables Foundry-only deployment into an existing resource group with running infrastructure."
  type        = bool
  default     = false
}

variable "existing_function_app_name" {
  description = "Name of existing Function App. Required when use_existing_backend=true. Used for outputs/OpenAPI URL."
  type        = string
  default     = ""
}

variable "existing_storage_account_name" {
  description = "Name of existing Storage Account. Required when use_existing_backend=true."
  type        = string
  default     = ""
}

variable "existing_app_insights_name" {
  description = "Name of existing Application Insights. Required when use_existing_backend=true. Used by AI Foundry Hub."
  type        = string
  default     = ""
}

variable "existing_document_intelligence_name" {
  description = "Name of existing Document Intelligence account (optional). Specify when use_existing_backend=true if needed for reference."
  type        = string
  default     = ""
}

variable "existing_app_service_plan_name" {
  description = "Name of existing App Service Plan (optional). Specify when use_existing_backend=true if needed for reference."
  type        = string
  default     = ""
}

# ===========================
# Storage Account
# ===========================

variable "storage_account_tier" {
  description = "Storage account tier"
  type        = string
  default     = "Standard"

  validation {
    condition     = contains(["Standard", "Premium"], var.storage_account_tier)
    error_message = "Storage tier must be Standard or Premium"
  }
}

variable "storage_replication_type" {
  description = "Storage replication type"
  type        = string
  default     = "LRS"

  validation {
    condition     = contains(["LRS", "GRS", "RAGRS", "ZRS", "GZRS", "RAGZRS"], var.storage_replication_type)
    error_message = "Invalid replication type"
  }
}

variable "storage_containers" {
  description = "Storage container names for input statements (e.g. vikas-samples). Code also uses vikas-reports and vikas-batches by default."
  type        = list(string)
  default     = ["vikas-samples"]

  validation {
    condition     = length(var.storage_containers) >= 1
    error_message = "At least 1 container required for input statements"
  }
}

variable "reports_container_override" {
  description = "Override the reports container name (optional, defaults to vikas-reports)"
  type        = string
  default     = ""
}

variable "batches_container_override" {
  description = "Override the batches container name (optional, defaults to vikas-batches)"
  type        = string
  default     = ""
}

# ===========================
# Document Intelligence
# ===========================

variable "document_intelligence_sku" {
  description = "Document Intelligence SKU"
  type        = string
  default     = "S0"

  validation {
    condition     = contains(["F0", "S0"], var.document_intelligence_sku)
    error_message = "SKU must be F0 (free) or S0 (standard)"
  }
}

# ===========================
# App Service Plan
# ===========================

variable "app_service_plan_sku" {
  description = "App Service Plan SKU for Function App"
  type        = string
  default     = "B1"

  validation {
    condition     = can(regex("^(B[1-3]|S[1-3]|P[1-3]v[2-3]|EP[1-3]|Y1)$", var.app_service_plan_sku))
    error_message = "Must be a valid App Service Plan SKU (B1-B3, S1-S3, P1v2-P3v3, EP1-EP3, Y1)"
  }
}

# ===========================
# Function App Settings
# ===========================

variable "use_managed_identity" {
  description = "Use managed identity for Document Intelligence access instead of API key"
  type        = bool
  default     = false
}

# ===========================
# Observability (optional)
# ===========================

variable "enable_application_insights" {
  description = "Create Application Insights for Function App telemetry. Not required for the core OCR->classify->xlsx/HTML pipeline; opt in when you want telemetry. Automatically forced on when create_ai_foundry_resources = true, because the AI Foundry Hub requires an Application Insights resource."
  type        = bool
  default     = false
}

# ===========================
# AI Foundry
# ===========================

variable "create_ai_foundry_resources" {
  description = "Create AI Foundry Hub, Project, and Azure OpenAI resources (preview feature - CLASSIC Hub/Project shape)"
  type        = bool
  default     = false
}

variable "create_classic_foundry_hub" {
  description = "Create ONLY the classic AI Foundry Hub + Project (MachineLearningServices workspaces). null (default) = follow create_ai_foundry_resources. Set false to remove the classic Hub/Project while keeping Key Vault, App Insights and the Azure OpenAI account/deployment."
  type        = bool
  nullable    = true
  default     = null
}

variable "foundry_model_name" {
  description = "AI Foundry model name to deploy (e.g., gpt-4, gpt-35-turbo, gpt-4o). Empty to skip model deployment"
  type        = string
  default     = ""
}

variable "foundry_model_version" {
  description = "Model version (e.g., 0613, turbo-2024-04-09, 2024-05-13 for gpt-4o)"
  type        = string
  default     = "0613"
}

variable "foundry_deployment_name" {
  description = "Deployment name for the model (should match model name for consistency)"
  type        = string
  default     = "gpt-4"
}

variable "foundry_model_capacity" {
  description = "Model deployment capacity (TPM in thousands)"
  type        = number
  default     = 10
}

# ===========================
# AI Foundry - NEW Microsoft Foundry Shape (AIServices + Project)
# ===========================

variable "create_foundry_aiservices" {
  description = "Create NEW Microsoft Foundry shape: AIServices account with allowProjectManagement=true + child project resource (appears in ai.azure.com/nextgen portal). Mutually exclusive with classic Hub/Project path."
  type        = bool
  default     = false
}

variable "foundry_aiservices_sku" {
  description = "SKU for AIServices account deployments. Standard supports model version 2024-11-20 in australiaeast. Use GlobalStandard for model version 2024-05-13."
  type        = string
  default     = "Standard"

  validation {
    condition     = contains(["Standard", "GlobalStandard"], var.foundry_aiservices_sku)
    error_message = "SKU must be Standard or GlobalStandard"
  }
}

variable "foundry_aiservices_model_version" {
  description = "GPT-4o model version for AIServices deployment. Use 2024-11-20 with Standard SKU or 2024-05-13 with GlobalStandard SKU."
  type        = string
  default     = "2024-11-20"
}

variable "foundry_aiservices_model_capacity" {
  description = "Model deployment capacity for AIServices (TPM in thousands)"
  type        = number
  default     = 10
}

# ===========================
# Tags
# ===========================

variable "tags" {
  description = "Additional tags to apply to all resources"
  type        = map(string)
  default     = {}
}
