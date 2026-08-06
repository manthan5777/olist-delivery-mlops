[CmdletBinding()]
param(
    [string]$Region = "ap-south-1",
    [string]$AwsProfile = "default",
    [string]$ClusterName = "olist-delivery-dev-cluster"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Olist Delivery - ECS Cluster Foundation"
Write-Host "======================================="
Write-Host "Cluster: $ClusterName"
Write-Host "Region:  $Region"
Write-Host ""

# Confirm that the AWS profile is working.
$CallerArn = aws sts get-caller-identity `
    --profile $AwsProfile `
    --query Arn `
    --output text `
    --no-cli-pager

if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($CallerArn)) {
    throw "Unable to access AWS using profile '$AwsProfile'."
}

Write-Host "AWS identity verified."

# Ensure the ECS service-linked IAM role exists before cluster creation.
$ServiceLinkedRoleName = "AWSServiceRoleForECS"

$ServiceLinkedRoleArn = aws iam list-roles `
    --profile $AwsProfile `
    --query "Roles[?RoleName=='$ServiceLinkedRoleName'].Arn | [0]" `
    --output text `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect IAM roles."
}

$ServiceLinkedRoleExists = (
    -not [string]::IsNullOrWhiteSpace($ServiceLinkedRoleArn) -and
    $ServiceLinkedRoleArn -ne "None"
)

if (-not $ServiceLinkedRoleExists) {
    Write-Host "Creating ECS service-linked role."

    aws iam create-service-linked-role `
        --aws-service-name "ecs.amazonaws.com" `
        --profile $AwsProfile `
        --output json `
        --no-cli-pager |
    Out-Null

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create the ECS service-linked role."
    }

    aws iam wait role-exists `
        --role-name $ServiceLinkedRoleName `
        --profile $AwsProfile `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "The ECS service-linked role did not become available."
    }

    # Give IAM time to propagate the new role to ECS.
    Write-Host "Waiting for the new IAM role to become assumable."
    Start-Sleep -Seconds 20

    Write-Host "ECS service-linked role created."
}
else {
    Write-Host "ECS service-linked role already exists."
}

# Check whether the ECS cluster already exists.
$ClusterResponseJson = aws ecs describe-clusters `
    --clusters $ClusterName `
    --region $Region `
    --profile $AwsProfile `
    --output json `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect ECS clusters."
}

$ClusterResponse = $ClusterResponseJson | ConvertFrom-Json
$ExistingCluster = $ClusterResponse.clusters | Select-Object -First 1

if (
    $null -eq $ExistingCluster -or
    $ExistingCluster.status -ne "ACTIVE"
) {
    Write-Host "Creating ECS cluster: $ClusterName"

    $CreateResponseJson = aws ecs create-cluster `
        --cluster-name $ClusterName `
        --capacity-providers FARGATE `
        --default-capacity-provider-strategy `
            "capacityProvider=FARGATE,weight=1,base=1" `
        --settings `
            "name=containerInsights,value=disabled" `
        --tags `
            "key=Project,value=olist-delivery-mlops" `
            "key=Environment,value=dev" `
            "key=Owner,value=manthan" `
            "key=ManagedBy,value=aws-cli" `
        --region $Region `
        --profile $AwsProfile `
        --output json `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create ECS cluster '$ClusterName'."
    }

    $CreateResponse = $CreateResponseJson | ConvertFrom-Json
    $ClusterArn = $CreateResponse.cluster.clusterArn

    Write-Host "ECS cluster created."
}
else {
    $ClusterArn = $ExistingCluster.clusterArn

    Write-Host "ECS cluster already exists."
}

if ([string]::IsNullOrWhiteSpace($ClusterArn)) {
    throw "Unable to determine the ECS cluster ARN."
}

# Ensure that the cluster uses the Fargate capacity provider.
aws ecs put-cluster-capacity-providers `
    --cluster $ClusterName `
    --capacity-providers FARGATE `
    --default-capacity-provider-strategy `
        "capacityProvider=FARGATE,weight=1,base=1" `
    --region $Region `
    --profile $AwsProfile `
    --no-cli-pager `
    --output json |
Out-Null

if ($LASTEXITCODE -ne 0) {
    throw "Unable to configure the Fargate capacity provider."
}

# Ensure that the project tags exist even when the cluster already existed.
aws ecs tag-resource `
    --resource-arn $ClusterArn `
    --tags `
        "key=Project,value=olist-delivery-mlops" `
        "key=Environment,value=dev" `
        "key=Owner,value=manthan" `
        "key=ManagedBy,value=aws-cli" `
    --region $Region `
    --profile $AwsProfile `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to apply tags to the ECS cluster."
}

Write-Host ""
Write-Host "ECS cluster verification"
Write-Host "========================"

aws ecs describe-clusters `
    --clusters $ClusterName `
    --include TAGS SETTINGS `
    --region $Region `
    --profile $AwsProfile `
    --query `
    "clusters[0].{
        Name:clusterName,
        Status:status,
        RunningTasks:runningTasksCount,
        PendingTasks:pendingTasksCount,
        ActiveServices:activeServicesCount,
        CapacityProviders:capacityProviders,
        DefaultStrategy:defaultCapacityProviderStrategy,
        Settings:settings,
        Tags:tags
    }" `
    --output json `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to verify the ECS cluster."
}

Write-Host ""
Write-Host "ECS cluster foundation completed successfully."