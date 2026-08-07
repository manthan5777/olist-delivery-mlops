[CmdletBinding()]
param(
    [string]$Region = "ap-south-1",
    [string]$AwsProfile = "default",
    [string]$ClusterName = "olist-delivery-dev-cluster",
    [string]$EcsSecurityGroupName = "olist-delivery-dev-ecs-sg",
    [string]$ApiTargetGroupName = "olist-delivery-dev-api-tg",
    [string]$FrontendTargetGroupName = "olist-delivery-dev-frontend-tg"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Olist Delivery - ECS Fargate Services"
Write-Host "====================================="
Write-Host "Cluster: $ClusterName"
Write-Host "Region:  $Region"
Write-Host ""

# --------------------------------------------------
# Verify AWS access
# --------------------------------------------------

$CallerArn = aws sts get-caller-identity `
    --profile $AwsProfile `
    --query Arn `
    --output text `
    --no-cli-pager

if (
    $LASTEXITCODE -ne 0 -or
    [string]::IsNullOrWhiteSpace($CallerArn)
) {
    throw "Unable to access AWS using profile '$AwsProfile'."
}

Write-Host "AWS identity verified."

# --------------------------------------------------
# Verify ECS cluster
# --------------------------------------------------

$ClusterStatus = aws ecs describe-clusters `
    --clusters $ClusterName `
    --region $Region `
    --profile $AwsProfile `
    --query "clusters[0].status" `
    --output text `
    --no-cli-pager

if (
    $LASTEXITCODE -ne 0 -or
    $ClusterStatus -ne "ACTIVE"
) {
    throw "ECS cluster '$ClusterName' is not active."
}

Write-Host "ECS cluster verified."

# --------------------------------------------------
# Find default VPC
# --------------------------------------------------

$VpcId = aws ec2 describe-vpcs `
    --filters "Name=is-default,Values=true" `
    --region $Region `
    --profile $AwsProfile `
    --query "Vpcs[0].VpcId" `
    --output text `
    --no-cli-pager

if (
    $LASTEXITCODE -ne 0 -or
    [string]::IsNullOrWhiteSpace($VpcId) -or
    $VpcId -eq "None"
) {
    throw "Unable to find the default VPC."
}

$VpcId = $VpcId.Trim()

# --------------------------------------------------
# Find available subnets
# --------------------------------------------------

$SubnetIdsText = aws ec2 describe-subnets `
    --filters `
        "Name=vpc-id,Values=$VpcId" `
        "Name=state,Values=available" `
    --region $Region `
    --profile $AwsProfile `
    --query "Subnets[].SubnetId" `
    --output text `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect VPC subnets."
}

$SubnetIds = @(
    $SubnetIdsText `
        -split "\s+" |
        Where-Object {
            -not [string]::IsNullOrWhiteSpace($_)
        }
)

if ($SubnetIds.Count -lt 2) {
    throw "At least two usable subnets are required."
}

Write-Host "Subnets verified: $($SubnetIds.Count)"

# --------------------------------------------------
# Find ECS security group
# --------------------------------------------------

$EcsSecurityGroupId = aws ec2 describe-security-groups `
    --filters `
        "Name=vpc-id,Values=$VpcId" `
        "Name=group-name,Values=$EcsSecurityGroupName" `
    --region $Region `
    --profile $AwsProfile `
    --query "SecurityGroups[0].GroupId" `
    --output text `
    --no-cli-pager

if (
    $LASTEXITCODE -ne 0 -or
    [string]::IsNullOrWhiteSpace($EcsSecurityGroupId) -or
    $EcsSecurityGroupId -eq "None"
) {
    throw "Unable to find ECS security group."
}

$EcsSecurityGroupId = $EcsSecurityGroupId.Trim()

Write-Host "ECS security group verified."

# --------------------------------------------------
# Get target-group ARNs
# --------------------------------------------------

$ApiTargetGroupArn = aws elbv2 describe-target-groups `
    --region $Region `
    --profile $AwsProfile `
    --query `
    "TargetGroups[?TargetGroupName=='$ApiTargetGroupName'].TargetGroupArn | [0]" `
    --output text `
    --no-cli-pager

if (
    $LASTEXITCODE -ne 0 -or
    [string]::IsNullOrWhiteSpace($ApiTargetGroupArn) -or
    $ApiTargetGroupArn -eq "None"
) {
    throw "Unable to find API target group."
}

$ApiTargetGroupArn = $ApiTargetGroupArn.Trim()

$FrontendTargetGroupArn = aws elbv2 describe-target-groups `
    --region $Region `
    --profile $AwsProfile `
    --query `
    "TargetGroups[?TargetGroupName=='$FrontendTargetGroupName'].TargetGroupArn | [0]" `
    --output text `
    --no-cli-pager

if (
    $LASTEXITCODE -ne 0 -or
    [string]::IsNullOrWhiteSpace($FrontendTargetGroupArn) -or
    $FrontendTargetGroupArn -eq "None"
) {
    throw "Unable to find frontend target group."
}

$FrontendTargetGroupArn = $FrontendTargetGroupArn.Trim()

Write-Host "ALB target groups verified."

# --------------------------------------------------
# Get latest task-definition ARNs
# --------------------------------------------------

function Get-LatestTaskDefinitionArn {
    param(
        [Parameter(Mandatory)]
        [string]$Family
    )

    $TaskDefinitionArn = aws ecs describe-task-definition `
        --task-definition $Family `
        --region $Region `
        --profile $AwsProfile `
        --query "taskDefinition.taskDefinitionArn" `
        --output text `
        --no-cli-pager

    if (
        $LASTEXITCODE -ne 0 -or
        [string]::IsNullOrWhiteSpace($TaskDefinitionArn) -or
        $TaskDefinitionArn -eq "None"
    ) {
        throw "Unable to find task definition '$Family'."
    }

    return $TaskDefinitionArn.Trim()
}

$ApiTaskDefinitionArn = Get-LatestTaskDefinitionArn `
    -Family "olist-delivery-dev-api"

$FrontendTaskDefinitionArn = Get-LatestTaskDefinitionArn `
    -Family "olist-delivery-dev-frontend"

$WorkerTaskDefinitionArn = Get-LatestTaskDefinitionArn `
    -Family "olist-delivery-dev-worker"

Write-Host "Task definitions verified."

# --------------------------------------------------
# Shared network configuration
# --------------------------------------------------

$NetworkConfiguration = @{
    awsvpcConfiguration = @{
        subnets        = $SubnetIds
        securityGroups = @(
            $EcsSecurityGroupId
        )

        # Development architecture:
        # public subnet + Internet Gateway, no NAT gateway.
        assignPublicIp = "ENABLED"
    }
}

$CapacityProviderStrategy = @(
    @{
        capacityProvider = "FARGATE"
        weight           = 1
        base             = 1
    }
)

$DeploymentConfiguration = @{
    maximumPercent        = 200
    minimumHealthyPercent = 0

    deploymentCircuitBreaker = @{
        enable   = $true
        rollback = $true
    }
}

$ServiceTags = @(
    @{
        key   = "Project"
        value = "olist-delivery-mlops"
    },
    @{
        key   = "Environment"
        value = "dev"
    },
    @{
        key   = "Owner"
        value = "manthan"
    },
    @{
        key   = "ManagedBy"
        value = "aws-cli"
    }
)

# --------------------------------------------------
# Helper: create/update an ECS service
# --------------------------------------------------

function Ensure-EcsService {
    param(
        [Parameter(Mandatory)]
        [string]$ServiceName,

        [Parameter(Mandatory)]
        [string]$TaskDefinitionArn,

        [string]$TargetGroupArn = "",

        [string]$ContainerName = "",

        [int]$ContainerPort = 0
    )

    Write-Host ""
    Write-Host "Service: $ServiceName"
    Write-Host "----------------------------------------"

    $ServiceArn = aws ecs describe-services `
        --cluster $ClusterName `
        --services $ServiceName `
        --region $Region `
        --profile $AwsProfile `
        --query "services[0].serviceArn" `
        --output text `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect ECS service '$ServiceName'."
    }

    $ServiceExists = (
        -not [string]::IsNullOrWhiteSpace($ServiceArn) -and
        $ServiceArn -ne "None"
    )

    $TemporaryDirectory = [System.IO.Path]::GetTempPath()
    $UniqueId = [System.Guid]::NewGuid().ToString("N")

    $ServiceInputPath = Join-Path `
        $TemporaryDirectory `
        "$ServiceName-$UniqueId.json"

    $Utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)

    try {

        if (-not $ServiceExists) {

            Write-Host "Creating ECS Fargate service."

            $CreateInput = @{
                cluster          = $ClusterName
                serviceName      = $ServiceName
                taskDefinition   = $TaskDefinitionArn
                desiredCount     = 1
                platformVersion  = "LATEST"

                capacityProviderStrategy = $CapacityProviderStrategy
                networkConfiguration     = $NetworkConfiguration
                deploymentConfiguration  = $DeploymentConfiguration

                enableECSManagedTags = $true
                propagateTags        = "SERVICE"

                tags = $ServiceTags
            }

            if (
                -not [string]::IsNullOrWhiteSpace($TargetGroupArn)
            ) {
                $CreateInput.loadBalancers = @(
                    @{
                        targetGroupArn = $TargetGroupArn
                        containerName  = $ContainerName
                        containerPort  = $ContainerPort
                    }
                )

                # Give Python and the ML model time to initialize
                # before ALB health checks can cause replacement.
                $CreateInput.healthCheckGracePeriodSeconds = 180
            }

            $CreateJson = $CreateInput |
                ConvertTo-Json -Depth 20

            [System.IO.File]::WriteAllText(
                $ServiceInputPath,
                $CreateJson,
                $Utf8WithoutBom
            )

            $ServiceInputUri = (
                "file://" +
                ($ServiceInputPath -replace '\\', '/')
            )

            $CreateResult = aws ecs create-service `
                --cli-input-json $ServiceInputUri `
                --region $Region `
                --profile $AwsProfile `
                --output json `
                --no-cli-pager

            if ($LASTEXITCODE -ne 0) {
                throw "Unable to create ECS service '$ServiceName'."
            }

            $CreatedService = (
                $CreateResult |
                ConvertFrom-Json
            ).service

            $ServiceArn = $CreatedService.serviceArn

            Write-Host "ECS service creation started."
        }
        else {

            Write-Host "ECS service already exists."
            Write-Host "Synchronizing service configuration."

            $UpdateInput = @{
                cluster          = $ClusterName
                service          = $ServiceName
                taskDefinition   = $TaskDefinitionArn
                desiredCount     = 1
                platformVersion  = "LATEST"

                capacityProviderStrategy = $CapacityProviderStrategy
                networkConfiguration     = $NetworkConfiguration
                deploymentConfiguration  = $DeploymentConfiguration

                enableECSManagedTags = $true
                propagateTags        = "SERVICE"
                forceNewDeployment   = $true
            }

            if (
                -not [string]::IsNullOrWhiteSpace($TargetGroupArn)
            ) {
                $UpdateInput.loadBalancers = @(
                    @{
                        targetGroupArn = $TargetGroupArn
                        containerName  = $ContainerName
                        containerPort  = $ContainerPort
                    }
                )

                $UpdateInput.healthCheckGracePeriodSeconds = 180
            }

            $UpdateJson = $UpdateInput |
                ConvertTo-Json -Depth 20

            [System.IO.File]::WriteAllText(
                $ServiceInputPath,
                $UpdateJson,
                $Utf8WithoutBom
            )

            $ServiceInputUri = (
                "file://" +
                ($ServiceInputPath -replace '\\', '/')
            )

            aws ecs update-service `
                --cli-input-json $ServiceInputUri `
                --region $Region `
                --profile $AwsProfile `
                --output json `
                --no-cli-pager |
            Out-Null

            if ($LASTEXITCODE -ne 0) {
                throw "Unable to update ECS service '$ServiceName'."
            }

            Write-Host "New deployment started."
        }
    }
    finally {
        Remove-Item `
            $ServiceInputPath `
            -Force `
            -ErrorAction SilentlyContinue
    }

    return $ServiceArn
}

# --------------------------------------------------
# API service
# --------------------------------------------------

$ApiServiceArn = Ensure-EcsService `
    -ServiceName "olist-delivery-dev-api-service" `
    -TaskDefinitionArn $ApiTaskDefinitionArn `
    -TargetGroupArn $ApiTargetGroupArn `
    -ContainerName "api" `
    -ContainerPort 8000

# --------------------------------------------------
# Frontend service
# --------------------------------------------------

$FrontendServiceArn = Ensure-EcsService `
    -ServiceName "olist-delivery-dev-frontend-service" `
    -TaskDefinitionArn $FrontendTaskDefinitionArn `
    -TargetGroupArn $FrontendTargetGroupArn `
    -ContainerName "frontend" `
    -ContainerPort 8501

# --------------------------------------------------
# Worker service
# --------------------------------------------------

$WorkerServiceArn = Ensure-EcsService `
    -ServiceName "olist-delivery-dev-worker-service" `
    -TaskDefinitionArn $WorkerTaskDefinitionArn

# --------------------------------------------------
# Wait for services to stabilize
# --------------------------------------------------

$ServiceNames = @(
    "olist-delivery-dev-api-service",
    "olist-delivery-dev-frontend-service",
    "olist-delivery-dev-worker-service"
)

Write-Host ""
Write-Host "Waiting for ECS services to stabilize."
Write-Host "This can take several minutes."
Write-Host ""

aws ecs wait services-stable `
    --cluster $ClusterName `
    --services $ServiceNames `
    --region $Region `
    --profile $AwsProfile

if ($LASTEXITCODE -ne 0) {
    throw "One or more ECS services did not reach a stable state."
}

# --------------------------------------------------
# Verification
# --------------------------------------------------

Write-Host ""
Write-Host "ECS service verification"
Write-Host "========================"

aws ecs describe-services `
    --cluster $ClusterName `
    --services $ServiceNames `
    --region $Region `
    --profile $AwsProfile `
    --query `
    "services[].{
        Service:serviceName,
        Status:status,
        Desired:desiredCount,
        Running:runningCount,
        Pending:pendingCount,
        TaskDefinition:taskDefinition
    }" `
    --output table `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to verify ECS services."
}

Write-Host ""
Write-Host "Expected running tasks"
Write-Host "======================"
Write-Host "API:      1"
Write-Host "Frontend: 1"
Write-Host "Worker:   1"
Write-Host ""
Write-Host "The Fargate application deployment is now running."