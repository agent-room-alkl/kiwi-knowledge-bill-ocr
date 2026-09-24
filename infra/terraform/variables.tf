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
# AI Foundry
# ===========================

variable "create_ai_foundry_resources" {
  description = "Create AI Foundry Hub and Project resources (preview feature)"
  type        = bool
  default     = false
}

variable "key_vault_id" {
  description = "Existing Key Vault resource ID for AI Foundry (required if create_ai_foundry_resources is true)"
  type        = string
  default     = ""
}

variable "foundry_model_name" {
  description = "AI Foundry model name to deploy (e.g., gpt-4, gpt-35-turbo). Empty to skip model deployment"
  type        = string
  default     = ""
}

variable "foundry_model_version" {
  description = "Model version (e.g., 0613, turbo-2024-04-09)"
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
# Tags
# ===========================

variable "tags" {
  description = "Additional tags to apply to all resources"
  type        = map(string)
  default     = {}
}
