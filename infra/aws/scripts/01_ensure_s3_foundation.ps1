param(
    [string]$Region = "ap-south-1",

    [string]$BucketName = (
        "olist-delivery-mlops-" +
        "198233241420-" +
        "ap-south-1"
    ),

    [string]$Profile = "default"
)


$ErrorActionPreference = "Stop"


Write-Host ""
Write-Host "Olist S3 foundation setup"
Write-Host "-------------------------"
Write-Host "Profile : $Profile"
Write-Host "Region  : $Region"
Write-Host "Bucket  : $BucketName"
Write-Host ""


# --------------------------------------------------
# 1. VERIFY THE ACTIVE AWS IDENTITY
# --------------------------------------------------

Write-Host "Checking AWS identity..."

aws sts get-caller-identity `
    --profile $Profile `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "AWS identity verification failed."
}


# --------------------------------------------------
# 2. CHECK WHETHER THE BUCKET EXISTS
# --------------------------------------------------

Write-Host ""
Write-Host "Checking whether the S3 bucket exists..."

aws s3api head-bucket `
    --bucket $BucketName `
    --profile $Profile `
    --no-cli-pager `
    2>$null

if ($LASTEXITCODE -eq 0) {
    Write-Host "Bucket already exists and is accessible."
}
else {
    Write-Host "Bucket does not exist. Creating it..."

    aws s3api create-bucket `
        --bucket $BucketName `
        --region $Region `
        --create-bucket-configuration `
        "LocationConstraint=$Region" `
        --profile $Profile `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "Bucket creation failed."
    }

    Write-Host "Bucket created successfully."
}


# --------------------------------------------------
# 3. BLOCK ALL PUBLIC ACCESS
# --------------------------------------------------

Write-Host ""
Write-Host "Applying S3 public-access protection..."

aws s3api put-public-access-block `
    --bucket $BucketName `
    --public-access-block-configuration `
    "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true" `
    --region $Region `
    --profile $Profile `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Public-access configuration failed."
}


# --------------------------------------------------
# 4. ENABLE OBJECT VERSIONING
# --------------------------------------------------

Write-Host "Enabling S3 object versioning..."

aws s3api put-bucket-versioning `
    --bucket $BucketName `
    --versioning-configuration `
    "Status=Enabled" `
    --region $Region `
    --profile $Profile `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Versioning configuration failed."
}


# --------------------------------------------------
# 5. APPLY PROJECT TAGS
# --------------------------------------------------

Write-Host "Applying project tags..."

aws s3api put-bucket-tagging `
    --bucket $BucketName `
    --tagging `
    'TagSet=[{Key=Project,Value=olist-delivery-mlops},{Key=Environment,Value=dev},{Key=Owner,Value=manthan},{Key=ManagedBy,Value=aws-cli}]' `
    --region $Region `
    --profile $Profile `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Bucket tagging failed."
}


# --------------------------------------------------
# 6. VERIFY THE FINAL CONFIGURATION
# --------------------------------------------------

Write-Host ""
Write-Host "Verifying the S3 configuration..."

$Location = aws s3api get-bucket-location `
    --bucket $BucketName `
    --profile $Profile `
    --query "LocationConstraint" `
    --output text `
    --no-cli-pager

$Versioning = aws s3api get-bucket-versioning `
    --bucket $BucketName `
    --profile $Profile `
    --query "Status" `
    --output text `
    --no-cli-pager

$PublicAccess = aws s3api get-public-access-block `
    --bucket $BucketName `
    --profile $Profile `
    --query "PublicAccessBlockConfiguration" `
    --output json `
    --no-cli-pager


Write-Host ""
Write-Host "S3 foundation completed successfully."
Write-Host "Bucket     : $BucketName"
Write-Host "Region     : $Location"
Write-Host "Versioning : $Versioning"
Write-Host "Public access configuration:"
Write-Host $PublicAccess
