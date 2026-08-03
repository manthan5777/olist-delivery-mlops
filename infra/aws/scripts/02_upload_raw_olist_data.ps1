param(
    [string]$Region = "ap-south-1",

    [string]$BucketName = (
        "olist-delivery-mlops-" +
        "198233241420-" +
        "ap-south-1"
    ),

    [string]$Profile = "default",

    [string]$TargetPrefix = "raw/olist"
)


$ErrorActionPreference = "Stop"


# --------------------------------------------------
# 1. FIND THE PROJECT AND LOCAL RAW-DATA DIRECTORY
# --------------------------------------------------

$ProjectRoot = (
    Resolve-Path (
        Join-Path $PSScriptRoot "..\..\.."
    )
).Path

$LocalRawPath = Join-Path `
    $ProjectRoot `
    "data\raw"


Write-Host ""
Write-Host "Olist raw-data upload"
Write-Host "---------------------"
Write-Host "Project root : $ProjectRoot"
Write-Host "Local source : $LocalRawPath"
Write-Host "Bucket       : $BucketName"
Write-Host "S3 prefix    : $TargetPrefix"
Write-Host "Region       : $Region"
Write-Host "Profile      : $Profile"
Write-Host ""


# --------------------------------------------------
# 2. VERIFY THE EXPECTED RAW FILES
# --------------------------------------------------

$ExpectedFiles = @(
    "olist_customers_dataset.csv",
    "olist_orders_dataset.csv",
    "olist_order_items_dataset.csv",
    "olist_order_payments_dataset.csv",
    "olist_products_dataset.csv",
    "olist_sellers_dataset.csv"
)


Write-Host "Checking expected source files..."

$MissingFiles = @()

foreach ($FileName in $ExpectedFiles) {
    $FilePath = Join-Path `
        $LocalRawPath `
        $FileName

    if (-not (Test-Path $FilePath)) {
        $MissingFiles += $FileName
    }
}


if ($MissingFiles.Count -gt 0) {
    throw (
        "Required source files are missing: " +
        ($MissingFiles -join ", ")
    )
}


$SourceFiles = Get-ChildItem `
    -Path $LocalRawPath `
    -File `
    -Filter "*.csv"


$TotalBytes = (
    $SourceFiles |
    Measure-Object `
        -Property Length `
        -Sum
).Sum


Write-Host "Expected files found."
Write-Host "CSV file count : $($SourceFiles.Count)"
Write-Host (
    "Total size     : " +
    "$([math]::Round($TotalBytes / 1MB, 2)) MB"
)


# --------------------------------------------------
# 3. VERIFY AWS IDENTITY
# --------------------------------------------------

Write-Host ""
Write-Host "Checking AWS identity..."

aws sts get-caller-identity `
    --profile $Profile `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "AWS identity verification failed."
}


# --------------------------------------------------
# 4. VERIFY THAT THE BUCKET IS ACCESSIBLE
# --------------------------------------------------

Write-Host ""
Write-Host "Checking S3 bucket access..."

aws s3api head-bucket `
    --bucket $BucketName `
    --region $Region `
    --profile $Profile `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw (
        "The S3 bucket does not exist " +
        "or is not accessible."
    )
}


Write-Host "S3 bucket is accessible."


# --------------------------------------------------
# 5. UPLOAD THE SIX RAW CSV FILES
# --------------------------------------------------

Write-Host ""
Write-Host "Uploading raw Olist CSV files..."


aws s3 sync `
    $LocalRawPath `
    "s3://$BucketName/$TargetPrefix/" `
    --exclude "*" `
    --include "olist_customers_dataset.csv" `
    --include "olist_orders_dataset.csv" `
    --include "olist_order_items_dataset.csv" `
    --include "olist_order_payments_dataset.csv" `
    --include "olist_products_dataset.csv" `
    --include "olist_sellers_dataset.csv" `
    --region $Region `
    --profile $Profile `
    --no-cli-pager


if ($LASTEXITCODE -ne 0) {
    throw "Raw-data upload failed."
}


# --------------------------------------------------
# 6. LIST THE UPLOADED S3 OBJECTS
# --------------------------------------------------

Write-Host ""
Write-Host "Uploaded S3 objects:"
Write-Host ""


aws s3api list-objects-v2 `
    --bucket $BucketName `
    --prefix "$TargetPrefix/" `
    --query `
    "Contents[].{ObjectKey:Key,SizeBytes:Size}" `
    --output table `
    --region $Region `
    --profile $Profile `
    --no-cli-pager


if ($LASTEXITCODE -ne 0) {
    throw "Unable to verify uploaded objects."
}


Write-Host ""
Write-Host "Raw Olist data upload completed successfully."
