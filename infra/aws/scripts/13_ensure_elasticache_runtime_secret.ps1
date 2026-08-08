[CmdletBinding()]
param(
    [string]$Region = "ap-south-1",
    [string]$AwsProfile = "default",
    [string]$CacheName = "olist-delivery-dev-cache",
    [string]$SecretName = "olist-delivery/dev/elasticache"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Olist Delivery - ElastiCache Runtime Secret"
Write-Host "==========================================="
Write-Host "Cache:  $CacheName"
Write-Host "Secret: $SecretName"
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
# Get the ElastiCache endpoint
# --------------------------------------------------

$CacheJson = aws elasticache describe-serverless-caches `
    --serverless-cache-name $CacheName `
    --region $Region `
    --profile $AwsProfile `
    --output json `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect ElastiCache Serverless cache."
}

$CacheResponse = $CacheJson | ConvertFrom-Json
$Cache = $CacheResponse.ServerlessCaches |
    Select-Object -First 1

if ($null -eq $Cache) {
    throw "ElastiCache cache '$CacheName' does not exist."
}

if ($Cache.Status -ne "available") {
    throw "ElastiCache cache is not available. Status: $($Cache.Status)"
}

$CacheEndpoint = $Cache.Endpoint.Address
$CachePort = $Cache.Endpoint.Port

if (
    [string]::IsNullOrWhiteSpace($CacheEndpoint) -or
    $null -eq $CachePort
) {
    throw "Unable to determine the ElastiCache endpoint."
}

Write-Host "ElastiCache endpoint verified."
Write-Host "Port: $CachePort"

# --------------------------------------------------
# Retrieve existing credentials
# --------------------------------------------------

$SecretString = aws secretsmanager get-secret-value `
    --secret-id $SecretName `
    --region $Region `
    --profile $AwsProfile `
    --query SecretString `
    --output text `
    --no-cli-pager

if (
    $LASTEXITCODE -ne 0 -or
    [string]::IsNullOrWhiteSpace($SecretString)
) {
    throw "Unable to retrieve Secrets Manager secret."
}

$SecretObject = $SecretString | ConvertFrom-Json

$UserName = $SecretObject.username
$Password = $SecretObject.password

if (
    [string]::IsNullOrWhiteSpace($UserName) -or
    [string]::IsNullOrWhiteSpace($Password)
) {
    throw "Username or password is missing from the secret."
}

Write-Host "Existing Valkey credentials retrieved securely."

# --------------------------------------------------
# Construct TLS Redis URL
# --------------------------------------------------

$EncodedUserName = [System.Uri]::EscapeDataString($UserName)
$EncodedPassword = [System.Uri]::EscapeDataString($Password)

$RedisUrl = [string]::Format(
    "rediss://{0}:{1}@{2}:{3}/0",
    $EncodedUserName,
    $EncodedPassword,
    $CacheEndpoint,
    $CachePort
)

# --------------------------------------------------
# Update the same secret
# --------------------------------------------------

$UpdatedSecret = @{
    username  = $UserName
    password  = $Password
    host      = $CacheEndpoint
    port      = [int]$CachePort
    redis_url = $RedisUrl
} | ConvertTo-Json -Compress

$TemporaryDirectory = [System.IO.Path]::GetTempPath()
$UniqueId = [System.Guid]::NewGuid().ToString("N")

$SecretValuePath = Join-Path `
    $TemporaryDirectory `
    "olist-runtime-secret-$UniqueId.txt"

$Utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)

try {
    [System.IO.File]::WriteAllText(
        $SecretValuePath,
        $UpdatedSecret,
        $Utf8WithoutBom
    )

    $SecretValueUri = (
        "file://" +
        ($SecretValuePath -replace '\\', '/')
    )

    Write-Host "Updating Secrets Manager runtime configuration."

    aws secretsmanager put-secret-value `
        --secret-id $SecretName `
        --secret-string $SecretValueUri `
        --region $Region `
        --profile $AwsProfile `
        --output json `
        --no-cli-pager |
    Out-Null

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to update Secrets Manager secret."
    }
}
finally {
    # This temporary file contains credentials.
    # Always remove it.
    Remove-Item `
        $SecretValuePath `
        -Force `
        -ErrorAction SilentlyContinue
}

# --------------------------------------------------
# Safe verification
# --------------------------------------------------

$VerificationString = aws secretsmanager get-secret-value `
    --secret-id $SecretName `
    --region $Region `
    --profile $AwsProfile `
    --query SecretString `
    --output text `
    --no-cli-pager

if (
    $LASTEXITCODE -ne 0 -or
    [string]::IsNullOrWhiteSpace($VerificationString)
) {
    throw "Unable to verify the updated secret."
}

$VerificationObject = $VerificationString | ConvertFrom-Json

Write-Host ""
Write-Host "Runtime secret verification"
Write-Host "==========================="
Write-Host "username present:  $(-not [string]::IsNullOrWhiteSpace($VerificationObject.username))"
Write-Host "password present:  $(-not [string]::IsNullOrWhiteSpace($VerificationObject.password))"
Write-Host "host present:      $(-not [string]::IsNullOrWhiteSpace($VerificationObject.host))"
Write-Host "port present:      $($null -ne $VerificationObject.port)"
Write-Host "redis_url present: $(-not [string]::IsNullOrWhiteSpace($VerificationObject.redis_url))"

Write-Host ""
Write-Host "Redis URL scheme: rediss://"
Write-Host "Redis URL value was intentionally not displayed."
Write-Host ""
Write-Host "ElastiCache runtime secret completed successfully."