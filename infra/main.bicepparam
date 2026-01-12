using './main.bicep'

param location = 'eastus'

// Workload profiles
param ingressWorkloadProfileName = 'wp-ingress'
param ingressWorkloadProfileType = 'D4'

param gpuWorkloadProfileName = 'wp-gpu'
// IMPORTANT: set this to a valid GPU profile type in your region, and ensure you have quota.
// Example for A100 serverless GPUs: 'Consumption-GPU-NC24-A100'
param gpuWorkloadProfileType = 'Consumption-GPU-NC24-A100'

param gpuMinimumCount = 0
param gpuMaximumCount = 1

param imageRepository = 'rf3-demo'
param imageTag = 'latest'
