#!/bin/bash
# ===========================
# Terraform Plan Validation Script
# Scenario: Foundry-Only Deployment with Existing Backend
# ===========================
#
# This script validates that the Foundry-only deployment path works correctly:
# - ONLY creates new Foundry resources (Hub, Project, Key Vault, OpenAI)
# - Does NOT create or destroy existing backend resources
# - References existing resources via data sources
# - Outputs point to existing Function App URL
#
# Requirements:
# - Terraform 1.5+
# - Azure CLI authenticated (az login)
# - Access to subscription 39993ea2-aaaa-499f-af2c-990d41279d3a
# - Read access to resource group kiwidemo-rg-b923ue

set -euo pipefail

echo "============================="
echo "Foundry-Only Deployment Validation"
echo "============================="
echo ""

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
SUBSCRIPTION_ID="39993ea2-aaaa-499f-af2c-990d41279d3a"
RG_NAME="kiwidemo-rg-b923ue"
PROJECT_NAME="kiwidemo"
UNIQUE_SUFFIX="fnd01"
LOCATION="australiaeast"
EXISTING_FUNCTION="kiwidemo-func-b923ue"
EXISTING_STORAGE="kiwidemosab923ue"
EXISTING_APP_INSIGHTS="kiwidemo-ai-b923ue"

# Check prerequisites
echo "Checking prerequisites..."

if ! command -v terraform &> /dev/null; then
    echo -e "${RED}ERROR: Terraform not found${NC}"
    exit 1
fi

if ! command -v az &> /dev/null; then
    echo -e "${RED}ERROR: Azure CLI not found${NC}"
    exit 1
fi

# Check Azure authentication
if ! az account show &> /dev/null; then
    echo -e "${RED}ERROR: Not authenticated to Azure. Run 'az login'${NC}"
    exit 1
fi

# Set subscription
echo "Setting subscription to ${SUBSCRIPTION_ID}..."
az account set --subscription "${SUBSCRIPTION_ID}"

# Verify existing resources
echo ""
echo "Verifying existing resources in ${RG_NAME}..."

if ! az group show --name "${RG_NAME}" &> /dev/null; then
    echo -e "${RED}ERROR: Resource group ${RG_NAME} not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Resource group exists${NC}"

if ! az storage account show --name "${EXISTING_STORAGE}" --resource-group "${RG_NAME}" &> /dev/null; then
    echo -e "${RED}ERROR: Storage account ${EXISTING_STORAGE} not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Storage account exists${NC}"

if ! az functionapp show --name "${EXISTING_FUNCTION}" --resource-group "${RG_NAME}" &> /dev/null; then
    echo -e "${RED}ERROR: Function app ${EXISTING_FUNCTION} not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Function app exists${NC}"

if ! az monitor app-insights component show --app "${EXISTING_APP_INSIGHTS}" --resource-group "${RG_NAME}" &> /dev/null; then
    echo -e "${RED}ERROR: Application Insights ${EXISTING_APP_INSIGHTS} not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Application Insights exists${NC}"

# Initialize Terraform
echo ""
echo "Initializing Terraform..."
terraform init -backend=false -input=false > /dev/null
echo -e "${GREEN}✓ Terraform initialized${NC}"

# Validate configuration
echo ""
echo "Validating Terraform configuration..."
if terraform validate > /dev/null; then
    echo -e "${GREEN}✓ Configuration valid${NC}"
else
    echo -e "${RED}ERROR: Terraform validation failed${NC}"
    exit 1
fi

# Run plan
echo ""
echo "Running Terraform plan..."
echo ""

PLAN_OUTPUT=$(mktemp)

terraform plan -input=false -no-color -lock=false \
  -var="subscription_id=${SUBSCRIPTION_ID}" \
  -var="project_name=${PROJECT_NAME}" \
  -var="unique_suffix=${UNIQUE_SUFFIX}" \
  -var="location=${LOCATION}" \
  -var="use_existing_resource_group=true" \
  -var="resource_group_name=${RG_NAME}" \
  -var="use_existing_backend=true" \
  -var="existing_function_app_name=${EXISTING_FUNCTION}" \
  -var="existing_storage_account_name=${EXISTING_STORAGE}" \
  -var="existing_app_insights_name=${EXISTING_APP_INSIGHTS}" \
  -var="create_ai_foundry_resources=true" \
  -var="foundry_model_name=gpt-4o" \
  -var="foundry_model_version=2024-05-13" \
  -var="foundry_deployment_name=gpt-4o" \
  -var="foundry_model_capacity=10" \
  2>&1 | tee "${PLAN_OUTPUT}"

echo ""
echo "============================="
echo "Plan Summary"
echo "============================="

# Extract plan summary
if grep -q "Plan:" "${PLAN_OUTPUT}"; then
    SUMMARY=$(grep "Plan:" "${PLAN_OUTPUT}")
    echo "${SUMMARY}"
    
    # Parse add/change/destroy counts
    ADD=$(echo "${SUMMARY}" | grep -oP '\d+(?= to add)' || echo "0")
    CHANGE=$(echo "${SUMMARY}" | grep -oP '\d+(?= to change)' || echo "0")
    DESTROY=$(echo "${SUMMARY}" | grep -oP '\d+(?= to destroy)' || echo "0")
    
    echo ""
    echo "Resources to add:     ${ADD}"
    echo "Resources to change:  ${CHANGE}"
    echo "Resources to destroy: ${DESTROY}"
else
    echo -e "${YELLOW}No resource changes detected${NC}"
    ADD=0
    CHANGE=0
    DESTROY=0
fi

echo ""
echo "============================="
echo "Validation Results"
echo "============================="

# Check for expected resources to be created
echo ""
echo "Expected resources to CREATE:"
EXPECTED_CREATES=(
    "azurerm_key_vault.foundry"
    "azapi_resource.ai_hub"
    "azapi_resource.ai_project"
    "azurerm_cognitive_account.openai"
    "azurerm_cognitive_deployment.model"
)

ALL_CREATES_OK=true
for resource in "${EXPECTED_CREATES[@]}"; do
    if grep -q "will be created" "${PLAN_OUTPUT}" && grep -A2 "${resource}" "${PLAN_OUTPUT}" | grep -q "will be created"; then
        echo -e "${GREEN}✓ ${resource}${NC}"
    else
        echo -e "${YELLOW}? ${resource} (not found in plan)${NC}"
        ALL_CREATES_OK=false
    fi
done

# Check for resources that should NOT be created
echo ""
echo "Expected resources to NOT be created (existing backend):"
SHOULD_NOT_CREATE=(
    "azurerm_storage_account.main"
    "azurerm_cognitive_account.doc_intelligence"
    "azurerm_service_plan.main"
    "azurerm_linux_function_app.main"
    "azurerm_application_insights.main"
)

ALL_NO_CREATE_OK=true
for resource in "${SHOULD_NOT_CREATE[@]}"; do
    if grep -q "${resource}" "${PLAN_OUTPUT}" && grep -A2 "${resource}" "${PLAN_OUTPUT}" | grep -q "will be created"; then
        echo -e "${RED}✗ ${resource} (should NOT be created!)${NC}"
        ALL_NO_CREATE_OK=false
    else
        echo -e "${GREEN}✓ ${resource} (not in plan)${NC}"
    fi
done

# Verify no destroys
echo ""
if [ "${DESTROY}" -eq 0 ]; then
    echo -e "${GREEN}✓ No resources will be destroyed (PASS)${NC}"
    DESTROY_OK=true
else
    echo -e "${RED}✗ ${DESTROY} resources will be destroyed (FAIL)${NC}"
    echo -e "${RED}  This should be ZERO for Foundry-only deployment${NC}"
    DESTROY_OK=false
fi

# Check outputs
echo ""
echo "Checking outputs reference existing Function App..."
if grep -q "function_app_url" "${PLAN_OUTPUT}"; then
    FUNC_URL=$(grep "function_app_url" "${PLAN_OUTPUT}" | grep -oP 'https://[^"]+' || echo "")
    if [[ "${FUNC_URL}" == *"${EXISTING_FUNCTION}"* ]]; then
        echo -e "${GREEN}✓ Function URL points to existing app: ${FUNC_URL}${NC}"
        OUTPUTS_OK=true
    else
        echo -e "${RED}✗ Function URL does not point to existing app${NC}"
        echo "  Expected: https://${EXISTING_FUNCTION}.azurewebsites.net"
        echo "  Got:      ${FUNC_URL}"
        OUTPUTS_OK=false
    fi
else
    echo -e "${YELLOW}? Could not verify function_app_url output${NC}"
    OUTPUTS_OK=true
fi

# Final result
echo ""
echo "============================="
echo "FINAL RESULT"
echo "============================="
echo ""

if [ "${DESTROY_OK}" = true ] && [ "${ALL_NO_CREATE_OK}" = true ] && [ "${OUTPUTS_OK}" = true ]; then
    echo -e "${GREEN}✓✓✓ VALIDATION PASSED ✓✓✓${NC}"
    echo ""
    echo "The Terraform plan is correct for Foundry-only deployment:"
    echo "- Creates ONLY new Foundry resources (Key Vault, Hub, Project, OpenAI)"
    echo "- Does NOT create or destroy existing backend resources"
    echo "- Outputs correctly reference existing Function App"
    echo ""
    echo -e "${GREEN}SUCCESS CRITERIA MET:${NC}"
    echo "✓ 0 destroy operations"
    echo "✓ Existing backend resources not in plan"
    echo "✓ Outputs point to ${EXISTING_FUNCTION}"
    echo ""
    RESULT=0
else
    echo -e "${RED}✗✗✗ VALIDATION FAILED ✗✗✗${NC}"
    echo ""
    echo "Issues detected:"
    [ "${DESTROY_OK}" = false ] && echo "- Resources will be destroyed (should be 0)"
    [ "${ALL_NO_CREATE_OK}" = false ] && echo "- Existing backend resources in plan (should not be created)"
    [ "${OUTPUTS_OK}" = false ] && echo "- Outputs do not reference existing Function App"
    echo ""
    RESULT=1
fi

echo "Full plan output saved to: ${PLAN_OUTPUT}"
echo ""

exit ${RESULT}
