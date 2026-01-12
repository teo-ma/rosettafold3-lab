targetScope = 'resourceGroup'

@description('Azure region for all resources')
param location string = resourceGroup().location

@description('Deploy the Container App resource (set false for a first pass before building/pushing the image)')
param deployApp bool = true

@description('Deploy the separate demo UI Container App (lightweight; no GPU)')
param deployUi bool = false

@description('Log Analytics workspace name')
param logAnalyticsName string = 'rf3-la-${uniqueString(resourceGroup().id)}'

@description('Container Apps managed environment name')
param managedEnvName string = 'rf3-acaenv-${uniqueString(resourceGroup().id)}'

@description('Azure Container Registry name (must be globally unique, 5-50 lowercase alphanumerics)')
param acrName string = 'rf3acr${toLower(uniqueString(resourceGroup().id))}'

@description('Container App name')
param containerAppName string = 'rf3-demo'

@description('Demo UI Container App name')
param uiContainerAppName string = 'rf3-demo-ui'

@description('ACR repository name (without login server)')
param imageRepository string = 'rf3-demo'

@description('UI image repository name (without login server)')
param uiImageRepository string = 'rf3-demo-ui'

@description('Image tag')
param imageTag string = 'latest'

@description('UI image tag')
param uiImageTag string = 'latest'

@description('Backend API base URL for the demo UI to proxy to (example: https://rf3-demo.<suffix>.swedencentral.azurecontainerapps.io)')
param uiBackendBaseUrl string = ''

@description('Workload profile name used by ingress (must be set to an existing workload profile name in the environment)')
param ingressWorkloadProfileName string = 'wp-ingress'

@description('Workload profile type used by ingress (example: D4). Ingress cannot run on Consumption/Flex and requires >=2 nodes.')
param ingressWorkloadProfileType string = 'D4'

@description('Workload profile name used by general web apps (cannot be the same as ingressWorkloadProfileName)')
param webWorkloadProfileName string = 'wp-web'

@description('Workload profile type used by general web apps (example: D4).')
param webWorkloadProfileType string = 'D4'

@description('Minimum node count for the web workload profile')
param webMinimumCount int = 1

@description('Maximum node count for the web workload profile')
param webMaximumCount int = 2

@description('GPU workload profile name for RF3 workloads')
param gpuWorkloadProfileName string = 'wp-gpu'

@description('GPU workload profile type (example: Consumption-GPU-NC24-A100 for serverless A100, depending on region availability)')
param gpuWorkloadProfileType string

@description('Minimum instance count for GPU workload profile')
param gpuMinimumCount int = 0

@description('Maximum instance count for GPU workload profile')
param gpuMaximumCount int = 1

var isConsumptionGpuProfile = startsWith(toLower(gpuWorkloadProfileType), 'consumption')
var gpuWorkloadProfile = isConsumptionGpuProfile
  ? {
      name: gpuWorkloadProfileName
      workloadProfileType: gpuWorkloadProfileType
    }
  : {
      name: gpuWorkloadProfileName
      workloadProfileType: gpuWorkloadProfileType
      minimumCount: gpuMinimumCount
      maximumCount: gpuMaximumCount
    }

var imageFullName = '${acr.properties.loginServer}/${imageRepository}:${imageTag}'
var uiImageFullName = '${acr.properties.loginServer}/${uiImageRepository}:${uiImageTag}'

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' = {
  name: logAnalyticsName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

// Shared key is retrieved at deploy time
var logAnalyticsSharedKey = listKeys(logAnalytics.id, '2020-08-01').primarySharedKey

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  sku: {
    name: 'Standard'
  }
  properties: {
    adminUserEnabled: true
  }
}

var acrCreds = listCredentials(acr.id, '2019-12-01-preview')
var acrUsername = acrCreds.username
var acrPassword = acrCreds.passwords[0].value

resource managedEnv 'Microsoft.App/managedEnvironments@2025-10-02-preview' = {
  name: managedEnvName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalyticsSharedKey
      }
    }
    ingressConfiguration: {
      workloadProfileName: ingressWorkloadProfileName
    }
    workloadProfiles: [
      {
        name: ingressWorkloadProfileName
        workloadProfileType: ingressWorkloadProfileType
        minimumCount: 2
        maximumCount: 10
      }
      {
        name: webWorkloadProfileName
        workloadProfileType: webWorkloadProfileType
        minimumCount: webMinimumCount
        maximumCount: webMaximumCount
      }
      gpuWorkloadProfile
    ]
  }
}

resource containerApp 'Microsoft.App/containerApps@2025-10-02-preview' = if (deployApp) {
  name: containerAppName
  location: location
  properties: {
    environmentId: managedEnv.id
    workloadProfileName: gpuWorkloadProfileName
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8080
        transport: 'auto'
      }
      secrets: [
        {
          name: 'acr-password'
          value: acrPassword
        }
      ]
      registries: [
        {
          server: acr.properties.loginServer
          username: acrUsername
          passwordSecretRef: 'acr-password'
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'rf3'
          image: imageFullName
          env: [
            {
              name: 'RF3_CKPT_PATH'
              value: '/models/rf3.ckpt'
            }
            {
              name: 'RF3_WORKDIR'
              value: '/tmp/rf3-demo'
            }
          ]
          resources: {
            cpu: 8
            memory: '32Gi'
            gpu: 1
          }
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8080
              }
              initialDelaySeconds: 10
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 6
            }
          ]
          volumeMounts: [
            {
              volumeName: 'models'
              mountPath: '/models'
            }
          ]
        }
      ]
      volumes: [
        {
          name: 'models'
          storageType: 'EmptyDir'
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
      }
    }
  }
}

resource uiContainerApp 'Microsoft.App/containerApps@2025-10-02-preview' = if (deployUi) {
  name: uiContainerAppName
  location: location
  properties: {
    environmentId: managedEnv.id
    workloadProfileName: webWorkloadProfileName
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8080
        transport: 'auto'
      }
      secrets: [
        {
          name: 'acr-password'
          value: acrPassword
        }
      ]
      registries: [
        {
          server: acr.properties.loginServer
          username: acrUsername
          passwordSecretRef: 'acr-password'
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'ui'
          image: uiImageFullName
          env: [
            {
              name: 'RF3_API_BASE_URL'
              value: uiBackendBaseUrl
            }
          ]
          resources: {
            cpu: 1
            memory: '1Gi'
          }
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/health'
                port: 8080
              }
              initialDelaySeconds: 10
              periodSeconds: 10
              timeoutSeconds: 5
              failureThreshold: 6
            }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 2
      }
    }
  }
}

output acrLoginServer string = acr.properties.loginServer
output image string = imageFullName
output uiImage string = uiImageFullName
output managedEnvironmentId string = managedEnv.id
output containerAppName string = containerAppName
output uiContainerAppName string = uiContainerAppName
