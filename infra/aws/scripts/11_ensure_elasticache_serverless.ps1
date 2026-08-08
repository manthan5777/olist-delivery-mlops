[CmdletBinding()]
param(
    [string]$Region = "ap-south-1",
    [string]$AwsProfile = "default",
    [string]$CacheName = "olist-delivery-dev-cache",
    [string]$UserGroupId = "olist-delivery-app-group",
    [string]$CacheSecurityGroupName = "olist-delivery-dev-cache-sg"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Olist Delivery - ElastiCache Serverless Valkey"
Write-Host "=============================================="
Write-Host "Cache:  $CacheName"
Write-Host "Region: $Region"
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

Write-Host "Default VPC: $VpcId"

# --------------------------------------------------
# Find available subnets
# --------------------------------------------------

$SubnetJson = aws ec2 describe-subnets `
    --filters `
        "Name=vpc-id,Values=$VpcId" `
        "Name=state,Values=available" `
    --region $Region `
    --profile $AwsProfile `
    --query `
    "Subnets[].{
        Id:SubnetId,
        AZ:AvailabilityZone
    }" `
    --output json `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect VPC subnets."
}

$SubnetObjects = $SubnetJson |
    ConvertFrom-Json |
    Sort-Object AZ

$SubnetIds = @(
    $SubnetObjects |
        Select-Object -ExpandProperty Id
)

if ($SubnetIds.Count -lt 2) {
    throw "At least two available subnets are required."
}

Write-Host "Subnets selected:"

foreach ($Subnet in $SubnetObjects) {
    Write-Host "  $($Subnet.AZ) -> $($Subnet.Id)"
}

# --------------------------------------------------
# Find cache security group
# --------------------------------------------------

$CacheSecurityGroupId = aws ec2 describe-security-groups `
    --filters `
        "Name=vpc-id,Values=$VpcId" `
        "Name=group-name,Values=$CacheSecurityGroupName" `
    --region $Region `
    --profile $AwsProfile `
    --query "SecurityGroups[0].GroupId" `
    --output text `
    --no-cli-pager

if (
    $LASTEXITCODE -ne 0 -or
    [string]::IsNullOrWhiteSpace($CacheSecurityGroupId) -or
    $CacheSecurityGroupId -eq "None"
) {
    throw "Unable to find cache security group '$CacheSecurityGroupName'."
}

$CacheSecurityGroupId = $CacheSecurityGroupId.Trim()

Write-Host "Cache security group: $CacheSecurityGroupId"

# --------------------------------------------------
# Verify Valkey user group
# --------------------------------------------------

$UserGroupJson = aws elasticache describe-user-groups `
    --region $Region `
    --profile $AwsProfile `
    --query `
    "UserGroups[?UserGroupId=='$UserGroupId'] | [0]" `
    --output json `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect ElastiCache user groups."
}

$UserGroup = $UserGroupJson | ConvertFrom-Json

if ($null -eq $UserGroup) {
    throw "ElastiCache user group '$UserGroupId' does not exist."
}

if ($UserGroup.Status -ne "active") {
    throw (
        "ElastiCache user group '$UserGroupId' " +
        "is not active. Current status: $($UserGroup.Status)"
    )
}

Write-Host "Valkey user group verified."

# --------------------------------------------------
# Check whether serverless cache already exists
# --------------------------------------------------

$ExistingCacheJson = aws elasticache describe-serverless-caches `
    --region $Region `
    --profile $AwsProfile `
    --query `
    "ServerlessCaches[?ServerlessCacheName=='$CacheName'] | [0]" `
    --output json `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect ElastiCache Serverless caches."
}

$ExistingCache = $ExistingCacheJson | ConvertFrom-Json

if ($null -eq $ExistingCache) {

    Write-Host ""
    Write-Host "Creating ElastiCache Serverless Valkey cache."
    Write-Host ""

    # Development usage ceilings.
    # No Minimum values are configured because minimum pre-scaling
    # can create baseline metered usage.
    $UsageLimits = (
        "DataStorage={Maximum=1,Unit=GB}," +
        "ECPUPerSecond={Maximum=1000}"
    )

    aws elasticache create-serverless-cache `
        --serverless-cache-name $CacheName `
        --description "Development Valkey cache for Olist Delivery MLOps" `
        --engine valkey `
        --cache-usage-limits $UsageLimits `
        --security-group-ids $CacheSecurityGroupId `
        --user-group-id $UserGroupId `
        --subnet-ids $SubnetIds `
        --network-type ipv4 `
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
        throw "Unable to create ElastiCache Serverless cache."
    }

    Write-Host "Cache creation started."
}
else {
    Write-Host ""
    Write-Host "ElastiCache Serverless cache already exists."
}

# --------------------------------------------------
# Wait for cache to become AVAILABLE
# --------------------------------------------------

Write-Host ""
Write-Host "Waiting for cache to become available."

$CacheReady = $false

for ($Attempt = 1; $Attempt -le 60; $Attempt++) {

    $Status = aws elasticache describe-serverless-caches `
        --serverless-cache-name $CacheName `
        --region $Region `
        --profile $AwsProfile `
        --query "ServerlessCaches[0].Status" `
        --output text `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to read cache status."
    }

    Write-Host "Attempt $Attempt - status: $Status"

    if ($Status -eq "available") {
        $CacheReady = $true
        break
    }

    if ($Status -eq "create-failed") {
        throw "ElastiCache Serverless cache creation failed."
    }

    if ($Status -eq "deleting") {
        throw "ElastiCache Serverless cache is being deleted."
    }

    Start-Sleep -Seconds 10
}

if (-not $CacheReady) {
    throw "ElastiCache cache did not become available in time."
}

# --------------------------------------------------
# Verification
# --------------------------------------------------

Write-Host ""
Write-Host "ElastiCache Serverless verification"
Write-Host "==================================="

aws elasticache describe-serverless-caches `
    --serverless-cache-name $CacheName `
    --region $Region `
    --profile $AwsProfile `
    --query `
    "ServerlessCaches[0].{
        Name:ServerlessCacheName,
        Status:Status,
        Engine:Engine,
        EngineVersion:FullEngineVersion,
        Endpoint:Endpoint.Address,
        Port:Endpoint.Port,
        UserGroup:UserGroupId,
        SecurityGroups:SecurityGroupIds,
        Subnets:SubnetIds,
        StorageEncryption:StorageEncryptionType,
        UsageLimits:CacheUsageLimits
    }" `
    --output json `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to verify the ElastiCache Serverless cache."
}

Write-Host ""
Write-Host "Connection architecture"
Write-Host "======================="
Write-Host "API ECS task    ----\"
Write-Host "                    +--> TLS --> ElastiCache Valkey"
Write-Host "Worker ECS task ----/"
Write-Host ""
Write-Host "The cache endpoint is private inside the VPC."
Write-Host "Application credentials remain in Secrets Manager."
Write-Host ""
Write-Host "ElastiCache Serverless Valkey foundation completed successfully."