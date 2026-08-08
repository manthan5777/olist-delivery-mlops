[CmdletBinding()]
param(
    [string]$Region = "ap-south-1",
    [string]$AwsProfile = "default",
    [string]$ExecutionRoleName = "olist-delivery-ecs-execution-role",
    [string]$SecretName = "olist-delivery/dev/elasticache",
    [string]$PolicyName = "olist-delivery-elasticache-secret-access"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Olist Delivery - ECS Secrets Manager Access"
Write-Host "==========================================="
Write-Host "Execution role: $ExecutionRoleName"
Write-Host "Secret:         $SecretName"
Write-Host "Region:         $Region"
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
# Verify ECS execution role
# --------------------------------------------------

$ExecutionRoleArn = aws iam list-roles `
    --profile $AwsProfile `
    --query "Roles[?RoleName=='$ExecutionRoleName'].Arn | [0]" `
    --output text `
    --no-cli-pager

if (
    $LASTEXITCODE -ne 0 -or
    [string]::IsNullOrWhiteSpace($ExecutionRoleArn) -or
    $ExecutionRoleArn -eq "None"
) {
    throw "Unable to find IAM role '$ExecutionRoleName'."
}

$ExecutionRoleArn = $ExecutionRoleArn.Trim()

Write-Host "Execution role verified."

# --------------------------------------------------
# Find exact Secrets Manager secret ARN
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

Write-Host "Secrets Manager secret verified."

# --------------------------------------------------
# Build least-privilege IAM policy
# --------------------------------------------------

$PolicyDocument = @{
    Version = "2012-10-17"
    Statement = @(
        @{
            Sid      = "ReadOlistDeliveryElastiCacheSecret"
            Effect   = "Allow"
            Action   = @(
                "secretsmanager:GetSecretValue"
            )
            Resource = $SecretArn
        }
    )
}

$TemporaryDirectory = [System.IO.Path]::GetTempPath()
$UniqueId = [System.Guid]::NewGuid().ToString("N")

$PolicyPath = Join-Path `
    $TemporaryDirectory `
    "olist-ecs-secret-policy-$UniqueId.json"

$Utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)

try {
    $PolicyJson = $PolicyDocument |
        ConvertTo-Json -Depth 10

    [System.IO.File]::WriteAllText(
        $PolicyPath,
        $PolicyJson,
        $Utf8WithoutBom
    )

    $PolicyUri = (
        "file://" +
        ($PolicyPath -replace '\\', '/')
    )

    # put-role-policy is idempotent:
    # it creates the policy if missing or replaces the policy
    # with this desired definition if it already exists.
    Write-Host ""
    Write-Host "Applying least-privilege secret-access policy."

    aws iam put-role-policy `
        --role-name $ExecutionRoleName `
        --policy-name $PolicyName `
        --policy-document $PolicyUri `
        --profile $AwsProfile `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to apply Secrets Manager access policy."
    }
}
finally {
    Remove-Item `
        $PolicyPath `
        -Force `
        -ErrorAction SilentlyContinue
}

# --------------------------------------------------
# Verification
# --------------------------------------------------

Write-Host ""
Write-Host "Secret-access policy verification"
Write-Host "================================="

aws iam get-role-policy `
    --role-name $ExecutionRoleName `
    --policy-name $PolicyName `
    --profile $AwsProfile `
    --query `
    "PolicyDocument.Statement[0].{
        Effect:Effect,
        Action:Action,
        Resource:Resource
    }" `
    --output json `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to verify the inline IAM policy."
}

Write-Host ""
Write-Host "Expected permission"
Write-Host "==================="
Write-Host "Role:   $ExecutionRoleName"
Write-Host "Action: secretsmanager:GetSecretValue"
Write-Host "Secret: $SecretName"
Write-Host ""
Write-Host "No wildcard Secrets Manager access was granted."
Write-Host ""
Write-Host "ECS secret-access foundation completed successfully."