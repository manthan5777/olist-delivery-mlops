[CmdletBinding()]
param(
    [string]$Region = "ap-south-1",
    [string]$AwsProfile = "default",
    [string]$SecretName = "olist-delivery/dev/elasticache",
    [string]$UserId = "olist-delivery-app",
    [string]$UserName = "olist-delivery-app",
    [string]$UserGroupId = "olist-delivery-app-group"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Olist Delivery - ElastiCache Access Control"
Write-Host "==========================================="
Write-Host "Region:     $Region"
Write-Host "User:       $UserName"
Write-Host "User group: $UserGroupId"
Write-Host "Secret:     $SecretName"
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
# Project tags
# --------------------------------------------------

$Tags = @(
    @{
        Key   = "Project"
        Value = "olist-delivery-mlops"
    },
    @{
        Key   = "Environment"
        Value = "dev"
    },
    @{
        Key   = "Owner"
        Value = "manthan"
    },
    @{
        Key   = "ManagedBy"
        Value = "aws-cli"
    }
)

$TemporaryDirectory = [System.IO.Path]::GetTempPath()
$UniqueId = [System.Guid]::NewGuid().ToString("N")

$SecretInputPath = Join-Path `
    $TemporaryDirectory `
    "olist-secret-$UniqueId.json"

$UserInputPath = Join-Path `
    $TemporaryDirectory `
    "olist-valkey-user-$UniqueId.json"

$Utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)

try {

    # --------------------------------------------------
    # Check whether the Secrets Manager secret exists
    # --------------------------------------------------

    $ExistingSecretJson = aws secretsmanager list-secrets `
        --region $Region `
        --profile $AwsProfile `
        --query "SecretList[?Name=='$SecretName'] | [0]" `
        --output json `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect Secrets Manager."
    }

    $ExistingSecret = $ExistingSecretJson | ConvertFrom-Json

    if ($null -eq $ExistingSecret) {

        Write-Host "Generating ElastiCache application password."

        # ElastiCache RBAC passwords cannot contain:
        # comma, double quote, slash, or @.
        $Password = aws secretsmanager get-random-password `
            --password-length 32 `
            --exclude-characters ',\"/@' `
            --require-each-included-type `
            --region $Region `
            --profile $AwsProfile `
            --query RandomPassword `
            --output text `
            --no-cli-pager

        if (
            $LASTEXITCODE -ne 0 -or
            [string]::IsNullOrWhiteSpace($Password)
        ) {
            throw "Unable to generate ElastiCache password."
        }

        $Password = $Password.Trim()

        $SecretValue = @{
            username = $UserName
            password = $Password
        } | ConvertTo-Json -Compress

        $SecretInput = @{
            Name         = $SecretName
            Description  = "Credentials for Olist Delivery ElastiCache Valkey."
            SecretString = $SecretValue
            Tags         = $Tags
        } | ConvertTo-Json -Depth 10

        [System.IO.File]::WriteAllText(
            $SecretInputPath,
            $SecretInput,
            $Utf8WithoutBom
        )

        $SecretInputUri = (
            "file://" +
            ($SecretInputPath -replace '\\', '/')
        )

        Write-Host "Creating Secrets Manager secret."

        aws secretsmanager create-secret `
            --cli-input-json $SecretInputUri `
            --region $Region `
            --profile $AwsProfile `
            --output json `
            --no-cli-pager |
        Out-Null

        if ($LASTEXITCODE -ne 0) {
            throw "Unable to create Secrets Manager secret."
        }

        Write-Host "Secrets Manager secret created."
    }
    else {
        Write-Host "Secrets Manager secret already exists."

        $SecretValue = aws secretsmanager get-secret-value `
            --secret-id $SecretName `
            --region $Region `
            --profile $AwsProfile `
            --query SecretString `
            --output text `
            --no-cli-pager

        if (
            $LASTEXITCODE -ne 0 -or
            [string]::IsNullOrWhiteSpace($SecretValue)
        ) {
            throw "Unable to retrieve the ElastiCache secret."
        }

        $SecretObject = $SecretValue | ConvertFrom-Json
        $Password = $SecretObject.password

        if ([string]::IsNullOrWhiteSpace($Password)) {
            throw "ElastiCache password is missing from the secret."
        }
    }

    # --------------------------------------------------
    # Check whether the Valkey application user exists
    # --------------------------------------------------

    $ExistingUserJson = aws elasticache describe-users `
        --region $Region `
        --profile $AwsProfile `
        --query "Users[?UserId=='$UserId'] | [0]" `
        --output json `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect ElastiCache users."
    }

    $ExistingUser = $ExistingUserJson | ConvertFrom-Json

    if ($null -eq $ExistingUser) {

        Write-Host "Creating ElastiCache Valkey application user."

        # The application only needs access to Olist job keys and
        # the exact commands currently used by FastAPI and the worker.
        $AccessString = (
            "on " +
            "~olist:* " +
            "+ping " +
            "+hset " +
            "+hgetall " +
            "+expire " +
            "+lpush " +
            "+brpop"
        )

        $UserInput = @{
            UserId       = $UserId
            UserName     = $UserName
            Engine       = "valkey"
            AccessString = $AccessString
            AuthenticationMode = @{
                Type      = "password"
                Passwords = @(
                    $Password
                )
            }
            Tags = $Tags
        } | ConvertTo-Json -Depth 10

        [System.IO.File]::WriteAllText(
            $UserInputPath,
            $UserInput,
            $Utf8WithoutBom
        )

        $UserInputUri = (
            "file://" +
            ($UserInputPath -replace '\\', '/')
        )

        aws elasticache create-user `
            --cli-input-json $UserInputUri `
            --region $Region `
            --profile $AwsProfile `
            --output json `
            --no-cli-pager |
        Out-Null

        if ($LASTEXITCODE -ne 0) {
            throw "Unable to create ElastiCache user '$UserId'."
        }

        Write-Host "ElastiCache user creation started."
    }
    else {
        Write-Host "ElastiCache application user already exists."
    }

    # --------------------------------------------------
    # Wait for the user to become ACTIVE
    # --------------------------------------------------

    Write-Host "Waiting for ElastiCache user to become active."

    $UserReady = $false

    for ($Attempt = 1; $Attempt -le 30; $Attempt++) {

        $UserStatus = aws elasticache describe-users `
            --user-id $UserId `
            --region $Region `
            --profile $AwsProfile `
            --query "Users[0].Status" `
            --output text `
            --no-cli-pager

        if ($LASTEXITCODE -ne 0) {
            throw "Unable to read ElastiCache user status."
        }

        if ($UserStatus -eq "active") {
            $UserReady = $true
            break
        }

        if ($UserStatus -eq "deleting") {
            throw "ElastiCache user is unexpectedly being deleted."
        }

        Start-Sleep -Seconds 5
    }

    if (-not $UserReady) {
        throw "ElastiCache user did not become active in time."
    }

    Write-Host "ElastiCache user is active."

    # --------------------------------------------------
    # Check whether the user group exists
    # --------------------------------------------------

    $ExistingGroupJson = aws elasticache describe-user-groups `
        --region $Region `
        --profile $AwsProfile `
        --query "UserGroups[?UserGroupId=='$UserGroupId'] | [0]" `
        --output json `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect ElastiCache user groups."
    }

    $ExistingGroup = $ExistingGroupJson | ConvertFrom-Json

    if ($null -eq $ExistingGroup) {

        Write-Host "Creating ElastiCache user group."

        aws elasticache create-user-group `
            --user-group-id $UserGroupId `
            --engine valkey `
            --user-ids $UserId `
            --tags `
                "Key=Project,Value=olist-delivery-mlops" `
                "Key=Environment,Value=dev" `
                "Key=Owner,Value=manthan" `
                "Key=ManagedBy,Value=aws-cli" `
            --region $Region `
            --profile $AwsProfile `
            --output json `
            --no-cli-pager |
        Out-Null

        if ($LASTEXITCODE -ne 0) {
            throw "Unable to create ElastiCache user group."
        }

        Write-Host "ElastiCache user-group creation started."
    }
    else {
        Write-Host "ElastiCache user group already exists."
    }

    # --------------------------------------------------
    # Wait for user group to become ACTIVE
    # --------------------------------------------------

    Write-Host "Waiting for ElastiCache user group to become active."

    $GroupReady = $false

    for ($Attempt = 1; $Attempt -le 30; $Attempt++) {

        $GroupStatus = aws elasticache describe-user-groups `
            --user-group-id $UserGroupId `
            --region $Region `
            --profile $AwsProfile `
            --query "UserGroups[0].Status" `
            --output text `
            --no-cli-pager

        if ($LASTEXITCODE -ne 0) {
            throw "Unable to read ElastiCache user-group status."
        }

        if ($GroupStatus -eq "active") {
            $GroupReady = $true
            break
        }

        if ($GroupStatus -eq "deleting") {
            throw "ElastiCache user group is unexpectedly being deleted."
        }

        Start-Sleep -Seconds 5
    }

    if (-not $GroupReady) {
        throw "ElastiCache user group did not become active in time."
    }

    Write-Host "ElastiCache user group is active."
}
finally {

    # Temporary files may contain the generated password.
    # Always remove them when the script exits.
    Remove-Item `
        $SecretInputPath, `
        $UserInputPath `
        -Force `
        -ErrorAction SilentlyContinue
}

# --------------------------------------------------
# Verification
# --------------------------------------------------

Write-Host ""
Write-Host "ElastiCache user verification"
Write-Host "============================="

aws elasticache describe-users `
    --user-id $UserId `
    --region $Region `
    --profile $AwsProfile `
    --query `
    "Users[0].{
        UserId:UserId,
        UserName:UserName,
        Engine:Engine,
        Status:Status,
        Authentication:Authentication.Type,
        AccessString:AccessString
    }" `
    --output table `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to verify ElastiCache user."
}

Write-Host ""
Write-Host "ElastiCache user-group verification"
Write-Host "==================================="

aws elasticache describe-user-groups `
    --user-group-id $UserGroupId `
    --region $Region `
    --profile $AwsProfile `
    --query `
    "UserGroups[0].{
        UserGroupId:UserGroupId,
        Engine:Engine,
        Status:Status,
        Users:UserIds
    }" `
    --output table `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to verify ElastiCache user group."
}

Write-Host ""
Write-Host "Secrets Manager verification"
Write-Host "============================"

aws secretsmanager describe-secret `
    --secret-id $SecretName `
    --region $Region `
    --profile $AwsProfile `
    --query `
    "{
        Name:Name,
        ARN:ARN,
        LastChangedDate:LastChangedDate
    }" `
    --output table `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to verify Secrets Manager secret."
}

Write-Host ""
Write-Host "Password value was intentionally not displayed."
Write-Host ""
Write-Host "ElastiCache access-control foundation completed successfully."