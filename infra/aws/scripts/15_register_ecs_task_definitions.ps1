[CmdletBinding()]
param(
    [string]$Region = "ap-south-1",
    [string]$AwsProfile = "default",
    [string]$ImageTag = "bcd54c7",
    [string]$LoadBalancerName = "olist-delivery-dev-alb",
    [string]$ExecutionRoleName = "olist-delivery-ecs-execution-role",
    [string]$TaskRoleName = "olist-delivery-ecs-task-role",
    [string]$SecretName = "olist-delivery/dev/elasticache"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Olist Delivery - ECS Task Definitions"
Write-Host "====================================="
Write-Host "Region:    $Region"
Write-Host "Image tag: $ImageTag"
Write-Host ""

# --------------------------------------------------
# Verify AWS access and discover account
# --------------------------------------------------

$AccountId = aws sts get-caller-identity `
    --profile $AwsProfile `
    --query Account `
    --output text `
    --no-cli-pager

if (
    $LASTEXITCODE -ne 0 -or
    [string]::IsNullOrWhiteSpace($AccountId)
) {
    throw "Unable to determine the AWS account ID."
}

$AccountId = $AccountId.Trim()
$Registry = "$AccountId.dkr.ecr.$Region.amazonaws.com"

Write-Host "AWS identity verified."

# --------------------------------------------------
# Verify IAM roles
# --------------------------------------------------

$ExecutionRoleArn = aws iam get-role `
    --role-name $ExecutionRoleName `
    --profile $AwsProfile `
    --query "Role.Arn" `
    --output text `
    --no-cli-pager

if (
    $LASTEXITCODE -ne 0 -or
    [string]::IsNullOrWhiteSpace($ExecutionRoleArn) -or
    $ExecutionRoleArn -eq "None"
) {
    throw "Unable to find ECS execution role."
}

$ExecutionRoleArn = $ExecutionRoleArn.Trim()

$TaskRoleArn = aws iam get-role `
    --role-name $TaskRoleName `
    --profile $AwsProfile `
    --query "Role.Arn" `
    --output text `
    --no-cli-pager

if (
    $LASTEXITCODE -ne 0 -or
    [string]::IsNullOrWhiteSpace($TaskRoleArn) -or
    $TaskRoleArn -eq "None"
) {
    throw "Unable to find ECS task role."
}

$TaskRoleArn = $TaskRoleArn.Trim()

Write-Host "ECS IAM roles verified."

# --------------------------------------------------
# Verify ECR images
# --------------------------------------------------

$Repositories = @(
    "olist-delivery/api",
    "olist-delivery/frontend",
    "olist-delivery/worker"
)

foreach ($RepositoryName in $Repositories) {

    $ImageDigest = aws ecr describe-images `
        --repository-name $RepositoryName `
        --image-ids "imageTag=$ImageTag" `
        --region $Region `
        --profile $AwsProfile `
        --query "imageDetails[0].imageDigest" `
        --output text `
        --no-cli-pager

    if (
        $LASTEXITCODE -ne 0 -or
        [string]::IsNullOrWhiteSpace($ImageDigest) -or
        $ImageDigest -eq "None"
    ) {
        throw (
            "ECR image '${RepositoryName}:${ImageTag}' " +
            "does not exist."
        )
    }

    Write-Host "Verified image: $RepositoryName`:$ImageTag"
}

# --------------------------------------------------
# Get ALB DNS name
# --------------------------------------------------

$AlbDnsName = aws elbv2 describe-load-balancers `
    --region $Region `
    --profile $AwsProfile `
    --query `
    "LoadBalancers[?LoadBalancerName=='$LoadBalancerName'].DNSName | [0]" `
    --output text `
    --no-cli-pager

if (
    $LASTEXITCODE -ne 0 -or
    [string]::IsNullOrWhiteSpace($AlbDnsName) -or
    $AlbDnsName -eq "None"
) {
    throw "Unable to determine ALB DNS name."
}

$AlbDnsName = $AlbDnsName.Trim()

$ApiBaseUrl = "http://$AlbDnsName/api"

Write-Host "ALB verified."
Write-Host "Frontend API path: $ApiBaseUrl"

# --------------------------------------------------
# Get Secrets Manager ARN
# --------------------------------------------------

$SecretArn = aws secretsmanager list-secrets `
    --region $Region `
    --profile $AwsProfile `
    --query "SecretList[?Name=='$SecretName'].ARN | [0]" `
    --output text `
    --no-cli-pager

if (
    $LASTEXITCODE -ne 0 -or
    [string]::IsNullOrWhiteSpace($SecretArn) -or
    $SecretArn -eq "None"
) {
    throw "Unable to find Secrets Manager secret '$SecretName'."
}

$SecretArn = $SecretArn.Trim()

# ECS JSON-key reference:
# secret-arn:json-key:version-stage:version-id
$RedisUrlSecretReference = "${SecretArn}:redis_url::"

Write-Host "Runtime secret verified."

# --------------------------------------------------
# Helper: register task definition
# --------------------------------------------------

function Register-OlistTaskDefinition {
    param(
        [Parameter(Mandatory)]
        [string]$Family,

        [Parameter(Mandatory)]
        [string]$ContainerName,

        [Parameter(Mandatory)]
        [string]$ImageUri,

        [Parameter(Mandatory)]
        [string]$Cpu,

        [Parameter(Mandatory)]
        [string]$Memory,

        [Parameter(Mandatory)]
        [string]$LogGroup,

        [int]$ContainerPort = 0,

        [array]$Environment = @(),

        [array]$Secrets = @()
    )

    Write-Host ""
    Write-Host "Registering: $Family"
    Write-Host "------------------------------"

    $ContainerDefinition = @{
        name      = $ContainerName
        image     = $ImageUri
        essential = $true

        logConfiguration = @{
            logDriver = "awslogs"
            options = @{
                "awslogs-group"         = $LogGroup
                "awslogs-region"        = $Region
                "awslogs-stream-prefix" = "ecs"
            }
        }
    }

    if ($ContainerPort -gt 0) {
        $ContainerDefinition.portMappings = @(
            @{
                containerPort = $ContainerPort
                hostPort      = $ContainerPort
                protocol      = "tcp"
            }
        )
    }

    if ($Environment.Count -gt 0) {
        $ContainerDefinition.environment = $Environment
    }

    if ($Secrets.Count -gt 0) {
        $ContainerDefinition.secrets = $Secrets
    }

    $TaskDefinition = @{
        family                  = $Family
        taskRoleArn             = $TaskRoleArn
        executionRoleArn        = $ExecutionRoleArn
        networkMode             = "awsvpc"
        requiresCompatibilities = @(
            "FARGATE"
        )
        cpu                     = $Cpu
        memory                  = $Memory

        runtimePlatform = @{
            operatingSystemFamily = "LINUX"
            cpuArchitecture       = "X86_64"
        }

        containerDefinitions = @(
            $ContainerDefinition
        )
    }

    $TemporaryDirectory = [System.IO.Path]::GetTempPath()
    $UniqueId = [System.Guid]::NewGuid().ToString("N")

    $TaskDefinitionPath = Join-Path `
        $TemporaryDirectory `
        "$Family-$UniqueId.json"

    $Utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)

    try {
        $TaskDefinitionJson = $TaskDefinition |
            ConvertTo-Json -Depth 20

        [System.IO.File]::WriteAllText(
            $TaskDefinitionPath,
            $TaskDefinitionJson,
            $Utf8WithoutBom
        )

        $TaskDefinitionUri = (
            "file://" +
            ($TaskDefinitionPath -replace '\\', '/')
        )

        $RegisteredJson = aws ecs register-task-definition `
            --cli-input-json $TaskDefinitionUri `
            --region $Region `
            --profile $AwsProfile `
            --output json `
            --no-cli-pager

        if ($LASTEXITCODE -ne 0) {
            throw "Unable to register task definition '$Family'."
        }

        $Registered = $RegisteredJson | ConvertFrom-Json

        $Revision = $Registered.taskDefinition.revision
        $TaskDefinitionArn = (
            $Registered.taskDefinition.taskDefinitionArn
        )

        Write-Host "Registered revision: $Revision"

        return [PSCustomObject]@{
            Family = $Family
            Revision = $Revision
            Arn = $TaskDefinitionArn
        }
    }
    finally {
        Remove-Item `
            $TaskDefinitionPath `
            -Force `
            -ErrorAction SilentlyContinue
    }
}

# --------------------------------------------------
# Common Redis secret
# --------------------------------------------------

$RedisSecret = @(
    @{
        name      = "REDIS_URL"
        valueFrom = $RedisUrlSecretReference
    }
)

# --------------------------------------------------
# Register API task definition
# --------------------------------------------------

$ApiResult = Register-OlistTaskDefinition `
    -Family "olist-delivery-dev-api" `
    -ContainerName "api" `
    -ImageUri "$Registry/olist-delivery/api:$ImageTag" `
    -Cpu "256" `
    -Memory "1024" `
    -ContainerPort 8000 `
    -LogGroup "/olist-delivery/dev/api" `
    -Secrets $RedisSecret

# --------------------------------------------------
# Register frontend task definition
# --------------------------------------------------

$FrontendEnvironment = @(
    @{
        name  = "API_BASE_URL"
        value = $ApiBaseUrl
    }
)

$FrontendResult = Register-OlistTaskDefinition `
    -Family "olist-delivery-dev-frontend" `
    -ContainerName "frontend" `
    -ImageUri "$Registry/olist-delivery/frontend:$ImageTag" `
    -Cpu "256" `
    -Memory "512" `
    -ContainerPort 8501 `
    -LogGroup "/olist-delivery/dev/frontend" `
    -Environment $FrontendEnvironment

# --------------------------------------------------
# Register worker task definition
# --------------------------------------------------

$WorkerResult = Register-OlistTaskDefinition `
    -Family "olist-delivery-dev-worker" `
    -ContainerName "worker" `
    -ImageUri "$Registry/olist-delivery/worker:$ImageTag" `
    -Cpu "256" `
    -Memory "512" `
    -LogGroup "/olist-delivery/dev/worker" `
    -Secrets $RedisSecret

# --------------------------------------------------
# Verification
# --------------------------------------------------

Write-Host ""
Write-Host "ECS task-definition verification"
Write-Host "================================"

$Results = @(
    $ApiResult,
    $FrontendResult,
    $WorkerResult
)

$Results |
    Select-Object `
        Family,
        Revision,
        Arn |
    Format-Table -AutoSize

Write-Host ""
Write-Host "Runtime configuration"
Write-Host "====================="
Write-Host "API"
Write-Host "  CPU:       256 units (.25 vCPU)"
Write-Host "  Memory:    1024 MiB"
Write-Host "  Port:      8000"
Write-Host "  REDIS_URL: Secrets Manager"
Write-Host ""
Write-Host "Frontend"
Write-Host "  CPU:          256 units (.25 vCPU)"
Write-Host "  Memory:       512 MiB"
Write-Host "  Port:         8501"
Write-Host "  API_BASE_URL: $ApiBaseUrl"
Write-Host ""
Write-Host "Worker"
Write-Host "  CPU:       256 units (.25 vCPU)"
Write-Host "  Memory:    512 MiB"
Write-Host "  REDIS_URL: Secrets Manager"
Write-Host ""
Write-Host "No Fargate tasks were started by this script."
Write-Host ""
Write-Host "ECS task definitions registered successfully."
