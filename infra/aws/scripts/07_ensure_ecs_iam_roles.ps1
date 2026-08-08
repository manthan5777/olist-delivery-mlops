[CmdletBinding()]
param(
    [string]$Region = "ap-south-1",
    [string]$AwsProfile = "default",
    [string]$ExecutionRoleName = "olist-delivery-ecs-execution-role",
    [string]$TaskRoleName = "olist-delivery-ecs-task-role"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Olist Delivery - ECS IAM Roles"
Write-Host "=============================="
Write-Host "Execution role: $ExecutionRoleName"
Write-Host "Task role:      $TaskRoleName"
Write-Host "Region:         $Region"
Write-Host ""

# Verify AWS access and discover the account ID.
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

Write-Host "AWS identity verified."

function Get-IamRoleArn {
    param(
        [Parameter(Mandatory)]
        [string]$RoleName
    )

    $RoleArn = aws iam list-roles `
        --profile $AwsProfile `
        --query "Roles[?RoleName=='$RoleName'].Arn | [0]" `
        --output text `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect IAM role '$RoleName'."
    }

    if (
        [string]::IsNullOrWhiteSpace($RoleArn) -or
        $RoleArn -eq "None"
    ) {
        return $null
    }

    return $RoleArn.Trim()
}

function Ensure-IamRole {
    param(
        [Parameter(Mandatory)]
        [string]$RoleName,

        [Parameter(Mandatory)]
        [string]$TrustPolicyPath,

        [Parameter(Mandatory)]
        [string]$Description
    )

    $RoleArn = Get-IamRoleArn -RoleName $RoleName
    $TrustPolicyUri = "file://$($TrustPolicyPath -replace '\\', '/')"

    if ([string]::IsNullOrWhiteSpace($RoleArn)) {
        Write-Host "Creating IAM role: $RoleName"

        aws iam create-role `
            --role-name $RoleName `
            --assume-role-policy-document $TrustPolicyUri `
            --description $Description `
            --tags `
                "Key=Project,Value=olist-delivery-mlops" `
                "Key=Environment,Value=dev" `
                "Key=Owner,Value=manthan" `
                "Key=ManagedBy,Value=aws-cli" `
            --profile $AwsProfile `
            --output json `
            --no-cli-pager |
        Out-Null

        if ($LASTEXITCODE -ne 0) {
            throw "Unable to create IAM role '$RoleName'."
        }

        aws iam wait role-exists `
            --role-name $RoleName `
            --profile $AwsProfile `
            --no-cli-pager

        if ($LASTEXITCODE -ne 0) {
            throw "IAM role '$RoleName' did not become available."
        }

        Write-Host "IAM role created: $RoleName"
    }
    else {
        Write-Host "IAM role already exists: $RoleName"

        # Keep the role's trust relationship synchronized with this script.
        aws iam update-assume-role-policy `
            --role-name $RoleName `
            --policy-document $TrustPolicyUri `
            --profile $AwsProfile `
            --no-cli-pager

        if ($LASTEXITCODE -ne 0) {
            throw "Unable to update the trust policy for '$RoleName'."
        }
    }

    # Ensure tags exist even when the role was created earlier.
    aws iam tag-role `
        --role-name $RoleName `
        --tags `
            "Key=Project,Value=olist-delivery-mlops" `
            "Key=Environment,Value=dev" `
            "Key=Owner,Value=manthan" `
            "Key=ManagedBy,Value=aws-cli" `
        --profile $AwsProfile `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to tag IAM role '$RoleName'."
    }
}

$TemporaryDirectory = [System.IO.Path]::GetTempPath()
$UniqueId = [System.Guid]::NewGuid().ToString("N")

$ExecutionTrustPolicyPath = Join-Path `
    $TemporaryDirectory `
    "ecs-execution-trust-$UniqueId.json"

$TaskTrustPolicyPath = Join-Path `
    $TemporaryDirectory `
    "ecs-task-trust-$UniqueId.json"

try {
    # ECS/Fargate assumes this role to pull images and write logs.
    $ExecutionTrustPolicy = @{
        Version = "2012-10-17"
        Statement = @(
            @{
                Sid       = "EcsTasksTrust"
                Effect    = "Allow"
                Principal = @{
                    Service = "ecs-tasks.amazonaws.com"
                }
                Action = "sts:AssumeRole"
            }
        )
    }

    # Application containers assume this role.
    # Source conditions restrict assumptions to ECS resources in this account.
    $TaskTrustPolicy = @{
        Version = "2012-10-17"
        Statement = @(
            @{
                Sid       = "EcsTasksTrust"
                Effect    = "Allow"
                Principal = @{
                    Service = "ecs-tasks.amazonaws.com"
                }
                Action    = "sts:AssumeRole"
                Condition = @{
                    StringEquals = @{
                        "aws:SourceAccount" = $AccountId
                    }
                    ArnLike = @{
                        "aws:SourceArn" = "arn:aws:ecs:${Region}:${AccountId}:*"
                    }
                }
            }
        )
    }

    $Utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)

    $ExecutionTrustJson = $ExecutionTrustPolicy |
        ConvertTo-Json -Depth 10

    $TaskTrustJson = $TaskTrustPolicy |
        ConvertTo-Json -Depth 10

    [System.IO.File]::WriteAllText(
        $ExecutionTrustPolicyPath,
        $ExecutionTrustJson,
        $Utf8WithoutBom
    )

    [System.IO.File]::WriteAllText(
        $TaskTrustPolicyPath,
        $TaskTrustJson,
        $Utf8WithoutBom
    )

    Ensure-IamRole `
        -RoleName $ExecutionRoleName `
        -TrustPolicyPath $ExecutionTrustPolicyPath `
        -Description "Allows ECS Fargate to pull Olist images and write logs."

    Ensure-IamRole `
        -RoleName $TaskRoleName `
        -TrustPolicyPath $TaskTrustPolicyPath `
        -Description "Runtime role for Olist Delivery application containers."

    $ExecutionPolicyArn = (
        "arn:aws:iam::aws:policy/service-role/" +
        "AmazonECSTaskExecutionRolePolicy"
    )

    Write-Host ""
    Write-Host "Attaching ECS execution policy."

    aws iam attach-role-policy `
        --role-name $ExecutionRoleName `
        --policy-arn $ExecutionPolicyArn `
        --profile $AwsProfile `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to attach the ECS task execution policy."
    }
}
finally {
    Remove-Item `
        $ExecutionTrustPolicyPath, `
        $TaskTrustPolicyPath `
        -Force `
        -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Execution role verification"
Write-Host "==========================="

aws iam get-role `
    --role-name $ExecutionRoleName `
    --profile $AwsProfile `
    --query "Role.{Name:RoleName,Arn:Arn,Created:CreateDate}" `
    --output table `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to verify execution role '$ExecutionRoleName'."
}

aws iam list-attached-role-policies `
    --role-name $ExecutionRoleName `
    --profile $AwsProfile `
    --query "AttachedPolicies[].{PolicyName:PolicyName,PolicyArn:PolicyArn}" `
    --output table `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to verify execution-role policies."
}

Write-Host ""
Write-Host "Application task role verification"
Write-Host "=================================="

aws iam get-role `
    --role-name $TaskRoleName `
    --profile $AwsProfile `
    --query "Role.{Name:RoleName,Arn:Arn,Created:CreateDate}" `
    --output table `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to verify task role '$TaskRoleName'."
}

Write-Host ""
Write-Host "The application task role intentionally has no permissions yet."
Write-Host "Permissions will be added only when required."
Write-Host ""
Write-Host "ECS IAM role foundation completed successfully."