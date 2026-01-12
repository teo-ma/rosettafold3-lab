#!/usr/bin/env bash
set -euo pipefail

# Two-phase deployment:
# 1) Deploy base infrastructure (ACR + Log Analytics + ACA Environment), WITHOUT the Container App
# 2) Build & push image to ACR
# 3) Deploy the Container App pinned to the GPU workload profile

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RG="${RG:-rf3-swecentral-rg}"
LOCATION="${LOCATION:-swedencentral}"
BASE_DEPLOYMENT_NAME="${BASE_DEPLOYMENT_NAME:-rf3-base}"
APP_DEPLOYMENT_NAME="${APP_DEPLOYMENT_NAME:-rf3-app}"

CONTAINER_APP_NAME="${CONTAINER_APP_NAME:-rf3-demo}"

UI_CONTAINER_APP_NAME="${UI_CONTAINER_APP_NAME:-rf3-demo-ui}"

IMAGE_REPOSITORY="${IMAGE_REPOSITORY:-rf3-demo}"
IMAGE_TAG="${IMAGE_TAG:-$(date +%Y%m%d%H%M%S)}"

DEPLOY_UI="${DEPLOY_UI:-true}"
DEPLOY_APP="${DEPLOY_APP:-true}"
UI_IMAGE_REPOSITORY="${UI_IMAGE_REPOSITORY:-rf3-demo-ui}"
UI_IMAGE_TAG="${UI_IMAGE_TAG:-$IMAGE_TAG}"

# IMPORTANT: set this to a valid GPU workload profile type in your region.
# Example for A100 serverless GPUs: Consumption-GPU-NC24-A100
GPU_WP_TYPE="${GPU_WP_TYPE:-}"

PARAM_FILE="$ROOT_DIR/infra/main.bicepparam"
TEMPLATE_FILE="$ROOT_DIR/infra/main.bicep"

require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 1
  }
}

require az

echo "==> Using resource group: $RG ($LOCATION)"
az group create -n "$RG" -l "$LOCATION" 1>/dev/null

if [[ "$DEPLOY_APP" != "true" && "$DEPLOY_UI" == "true" ]]; then
  echo "==> UI-only mode (DEPLOY_APP=false): will NOT rebuild/redeploy the model app"

  ACR_NAME="$(az acr list -g "$RG" --query "[0].name" -o tsv)"
  if [[ -z "$ACR_NAME" || "$ACR_NAME" == "null" ]]; then
    echo "ERROR: Could not find an Azure Container Registry in resource group: $RG" >&2
    echo "       Try: az acr list -g $RG -o table" >&2
    exit 1
  fi

  ACR_LOGIN_SERVER="$(az acr show -g "$RG" -n "$ACR_NAME" --query loginServer -o tsv)"
  if [[ -z "$ACR_LOGIN_SERVER" || "$ACR_LOGIN_SERVER" == "null" ]]; then
    echo "ERROR: Could not determine ACR login server for registry: $ACR_NAME" >&2
    exit 1
  fi
  echo "==> ACR: $ACR_NAME ($ACR_LOGIN_SERVER)"

  echo "==> Fetching model Container App FQDN (for RF3_API_BASE_URL)"
  FQDN="$(az containerapp show -g "$RG" -n "$CONTAINER_APP_NAME" --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null || true)"
  if [[ -z "$FQDN" || "$FQDN" == "null" ]]; then
    echo "ERROR: Could not find backend Container App FQDN for: $CONTAINER_APP_NAME" >&2
    echo "       Is it deployed? Try: az containerapp show -g $RG -n $CONTAINER_APP_NAME --query properties.configuration.ingress.fqdn -o tsv" >&2
    exit 1
  fi
  echo "==> Backend URL: https://$FQDN"

  echo "==> Building UI image in Azure (ACR build): $ACR_LOGIN_SERVER/$UI_IMAGE_REPOSITORY:$UI_IMAGE_TAG"
  az acr build --only-show-errors -r "$ACR_NAME" -f "$ROOT_DIR/Dockerfile.ui" -t "$UI_IMAGE_REPOSITORY:$UI_IMAGE_TAG" "$ROOT_DIR" 1>/dev/null

  echo "==> Updating UI Container App image/env (CPU app; no GPU)"
  az containerapp update --only-show-errors \
    -g "$RG" \
    -n "$UI_CONTAINER_APP_NAME" \
    --image "$ACR_LOGIN_SERVER/$UI_IMAGE_REPOSITORY:$UI_IMAGE_TAG" \
    --set-env-vars "RF3_API_BASE_URL=https://$FQDN" \
    1>/dev/null

  echo "==> Fetching Demo UI FQDN"
  UI_FQDN=""
  for _ in {1..30}; do
    UI_FQDN="$(az containerapp show -g "$RG" -n "$UI_CONTAINER_APP_NAME" --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null || true)"
    if [[ -n "$UI_FQDN" && "$UI_FQDN" != "null" ]]; then
      break
    fi
    sleep 2
  done

  if [[ -n "$UI_FQDN" && "$UI_FQDN" != "null" ]]; then
    echo "==> Demo UI URL: https://$UI_FQDN"
  else
    echo "==> UI updated, but FQDN is not available yet. Try:" >&2
    echo "    az containerapp show -g $RG -n $UI_CONTAINER_APP_NAME --query properties.configuration.ingress.fqdn -o tsv" >&2
  fi
  exit 0
fi

if [[ -z "$GPU_WP_TYPE" ]]; then
  echo "==> Detecting GPU workload profile type in $LOCATION"
  # Prefer A100 serverless GPU profile when available.
  GPU_WP_TYPE="$(az containerapp env workload-profile list-supported --location "$LOCATION" --query "[?name=='Consumption-GPU-NC24-A100'].name | [0]" -o tsv)"
  if [[ -z "$GPU_WP_TYPE" ]]; then
    echo "ERROR: Could not auto-detect A100 GPU workload profile type in $LOCATION." >&2
    echo "       Run: az containerapp env workload-profile list-supported --location $LOCATION -o table" >&2
    exit 1
  fi
  echo "==> Using GPU_WP_TYPE=$GPU_WP_TYPE"
fi

echo "==> Deploying base infrastructure (deployApp=false)"
BASE_ARGS=(
  -g "$RG"
  -n "$BASE_DEPLOYMENT_NAME"
  -f "$TEMPLATE_FILE"
  -p "$PARAM_FILE"
  -p location="$LOCATION" deployApp=false deployUi=false containerAppName="$CONTAINER_APP_NAME" imageRepository="$IMAGE_REPOSITORY" imageTag="$IMAGE_TAG"
)

if [[ -n "$GPU_WP_TYPE" ]]; then
  BASE_ARGS+=( -p gpuWorkloadProfileType="$GPU_WP_TYPE" )
fi

ACR_LOGIN_SERVER_RAW="$(az deployment group create "${BASE_ARGS[@]}" --only-show-errors --query properties.outputs.acrLoginServer.value -o tsv 2>&1)"
ACR_NAME="$(az acr list -g "$RG" --query "[0].name" -o tsv)"
if [[ -z "$ACR_NAME" || "$ACR_NAME" == "null" ]]; then
  echo "ERROR: Could not find an Azure Container Registry in resource group: $RG" >&2
  echo "       Try: az acr list -g $RG -o table" >&2
  exit 1
fi

ACR_LOGIN_SERVER="$(az acr show -g "$RG" -n "$ACR_NAME" --query loginServer -o tsv)"
if [[ -z "$ACR_LOGIN_SERVER" || "$ACR_LOGIN_SERVER" == "null" ]]; then
  echo "ERROR: Could not determine ACR login server for registry: $ACR_NAME" >&2
  exit 1
fi

echo "==> ACR: $ACR_NAME ($ACR_LOGIN_SERVER)"

IMAGE_REF="$ACR_LOGIN_SERVER/$IMAGE_REPOSITORY:$IMAGE_TAG"

echo "==> Building image in Azure (ACR build): $IMAGE_REF"
az acr build --only-show-errors -r "$ACR_NAME" -t "$IMAGE_REPOSITORY:$IMAGE_TAG" "$ROOT_DIR" 1>/dev/null

echo "==> Deploying/Updating Container App (deployApp=true)"
APP_ARGS=(
  -g "$RG"
  -n "$APP_DEPLOYMENT_NAME"
  -f "$TEMPLATE_FILE"
  -p "$PARAM_FILE"
  -p location="$LOCATION" deployApp=true deployUi=false containerAppName="$CONTAINER_APP_NAME" imageRepository="$IMAGE_REPOSITORY" imageTag="$IMAGE_TAG"
)

if [[ -n "$GPU_WP_TYPE" ]]; then
  APP_ARGS+=( -p gpuWorkloadProfileType="$GPU_WP_TYPE" )
fi

az deployment group create "${APP_ARGS[@]}" --only-show-errors 1>/dev/null

echo "==> Fetching Container App FQDN"
FQDN=""
for _ in {1..30}; do
  FQDN="$(az containerapp show -g "$RG" -n "$CONTAINER_APP_NAME" --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null || true)"
  if [[ -n "$FQDN" && "$FQDN" != "null" ]]; then
    break
  fi
  sleep 2
done

if [[ -n "$FQDN" && "$FQDN" != "null" ]]; then
  echo "==> Deployed. URL: https://$FQDN"
  echo "    Health:  curl -fsS https://$FQDN/health"

  if [[ "$DEPLOY_UI" == "true" ]]; then
    echo "==> Building UI image in Azure (ACR build): $ACR_LOGIN_SERVER/$UI_IMAGE_REPOSITORY:$UI_IMAGE_TAG"
    az acr build --only-show-errors -r "$ACR_NAME" -f "$ROOT_DIR/Dockerfile.ui" -t "$UI_IMAGE_REPOSITORY:$UI_IMAGE_TAG" "$ROOT_DIR" 1>/dev/null

    echo "==> Deploying/Updating Demo UI Container App (deployUi=true)"
    UI_ARGS=(
      -g "$RG"
      -n "${APP_DEPLOYMENT_NAME}-ui"
      -f "$TEMPLATE_FILE"
      -p "$PARAM_FILE"
      -p location="$LOCATION" deployApp=false deployUi=true \
         uiContainerAppName="$UI_CONTAINER_APP_NAME" uiImageRepository="$UI_IMAGE_REPOSITORY" uiImageTag="$UI_IMAGE_TAG" \
         uiBackendBaseUrl="https://$FQDN"
    )
    if [[ -n "$GPU_WP_TYPE" ]]; then
      UI_ARGS+=( -p gpuWorkloadProfileType="$GPU_WP_TYPE" )
    fi
    az deployment group create "${UI_ARGS[@]}" --only-show-errors 1>/dev/null

    echo "==> Fetching Demo UI FQDN"
    UI_FQDN=""
    for _ in {1..30}; do
      UI_FQDN="$(az containerapp show -g "$RG" -n "$UI_CONTAINER_APP_NAME" --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null || true)"
      if [[ -n "$UI_FQDN" && "$UI_FQDN" != "null" ]]; then
        break
      fi
      sleep 2
    done

    if [[ -n "$UI_FQDN" && "$UI_FQDN" != "null" ]]; then
      echo "==> Demo UI URL: https://$UI_FQDN"
    else
      echo "==> Demo UI deployed, but FQDN is not available yet. Try:" >&2
      echo "    az containerapp show -g $RG -n $UI_CONTAINER_APP_NAME --query properties.configuration.ingress.fqdn -o tsv" >&2
    fi
  fi
else
  echo "==> Deployed, but FQDN is not available yet. Try:" >&2
  echo "    az containerapp show -g $RG -n $CONTAINER_APP_NAME --query properties.configuration.ingress.fqdn -o tsv" >&2
fi
