param(
    [string]$Region = "ap-south-1",

    [string]$AwsProfile = "default",

    [string[]]$RepositoryNames = @(
        "olist-delivery/api",
        "olist-delivery/frontend",
        "olist-delivery/worker"
    )
)


$ErrorActionPreference = "Stop"


Write-Host ""
Write-Host "Olist ECR repository setup"
Write-Host "--------------------------"
Write-Host "Profile : $AwsProfile"
Write-Host "Region  : $Region"
Write-Host ""


# --------------------------------------------------
# 1. VERIFY THE ACTIVE AWS IDENTITY
# --------------------------------------------------

Write-Host "Checking AWS identity..."

$AccountId = aws sts get-caller-identity `
    --profile $AwsProfile `
    --query "Account" `
    --output text `
    --no-cli-pager


if ($LASTEXITCODE -ne 0) {
    throw "AWS identity verification failed."
}


Write-Host "AWS account: $AccountId"


# --------------------------------------------------
# 2. CONFIGURE ECR REGISTRY-LEVEL SCANNING
# --------------------------------------------------

Write-Host ""
Write-Host "Configuring basic scan-on-push..."

$ScanningRules = (
    "scanFrequency=SCAN_ON_PUSH," +
    "repositoryFilters=[" +
    "{filter=olist-delivery/*,filterType=WILDCARD}" +
    "]"
)


aws ecr put-registry-scanning-configuration `
    --scan-type BASIC `
    --rules $ScanningRules `
    --region $Region `
    --profile $AwsProfile `
    --no-cli-pager `
    | Out-Null


if ($LASTEXITCODE -ne 0) {
    throw "Unable to configure ECR registry scanning."
}


Write-Host (
    "Images pushed to olist-delivery/* " +
    "will be scanned."
)


# --------------------------------------------------
# 3. ENSURE EACH ECR REPOSITORY EXISTS
# --------------------------------------------------

foreach ($RepositoryName in $RepositoryNames) {
    Write-Host ""
    Write-Host "Repository: $RepositoryName"
    Write-Host "----------------------------------------"

    # Describe all repositories and filter the successful response.
    # This avoids an expected RepositoryNotFoundException.
    $RepositoryQuery = (
        "repositories[?repositoryName==" +
        "'$RepositoryName'" +
        "].repositoryArn | [0]"
    )

    $ExistingRepositoryArn = aws ecr describe-repositories `
        --region $Region `
        --profile $AwsProfile `
        --query $RepositoryQuery `
        --output text `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw (
            "Unable to inspect ECR repository: " +
            $RepositoryName
        )
    }

    $RepositoryExists = (
        -not [string]::IsNullOrWhiteSpace(
            $ExistingRepositoryArn
        ) -and
        $ExistingRepositoryArn -ne "None"
    )

    if ($RepositoryExists) {
        Write-Host "Repository already exists."

        $RepositoryArn = $ExistingRepositoryArn
    }
    else {
        Write-Host "Repository does not exist. Creating it..."

        $RepositoryArn = aws ecr create-repository `
            --repository-name $RepositoryName `
            --image-tag-mutability IMMUTABLE `
            --tags `
            "Key=Project,Value=olist-delivery-mlops" `
            "Key=Environment,Value=dev" `
            "Key=Owner,Value=manthan" `
            "Key=ManagedBy,Value=aws-cli" `
            --region $Region `
            --profile $AwsProfile `
            --query "repository.repositoryArn" `
            --output text `
            --no-cli-pager


        if ($LASTEXITCODE -ne 0) {
            throw (
                "Failed to create ECR repository: " +
                $RepositoryName
            )
        }


        Write-Host "Repository created successfully."
    }


    # --------------------------------------------------
    # 4. ENSURE IMAGE TAGS ARE IMMUTABLE
    # --------------------------------------------------

    Write-Host "Applying immutable image tags..."

    aws ecr put-image-tag-mutability `
        --repository-name $RepositoryName `
        --image-tag-mutability IMMUTABLE `
        --region $Region `
        --profile $AwsProfile `
        --no-cli-pager `
        | Out-Null


    if ($LASTEXITCODE -ne 0) {
        throw (
            "Unable to configure tag immutability for: " +
            $RepositoryName
        )
    }


    # --------------------------------------------------
    # 5. APPLY PROJECT RESOURCE TAGS
    # --------------------------------------------------

    Write-Host "Applying project resource tags..."

    aws ecr tag-resource `
        --resource-arn $RepositoryArn `
        --tags `
        "Key=Project,Value=olist-delivery-mlops" `
        "Key=Environment,Value=dev" `
        "Key=Owner,Value=manthan" `
        "Key=ManagedBy,Value=aws-cli" `
        --region $Region `
        --profile $AwsProfile `
        --no-cli-pager


    if ($LASTEXITCODE -ne 0) {
        throw (
            "Unable to tag ECR repository: " +
            $RepositoryName
        )
    }


    # --------------------------------------------------
    # 6. VERIFY THE REPOSITORY
    # --------------------------------------------------

    Write-Host "Verifying repository..."

    aws ecr describe-repositories `
        --repository-names $RepositoryName `
        --region $Region `
        --profile $AwsProfile `
        --query `
        "repositories[0].{Name:repositoryName,URI:repositoryUri,TagMutability:imageTagMutability}" `
        --output table `
        --no-cli-pager


    if ($LASTEXITCODE -ne 0) {
        throw (
            "Unable to verify ECR repository: " +
            $RepositoryName
        )
    }
}


# --------------------------------------------------
# 7. VERIFY SCANNING FOR THE THREE REPOSITORIES
# --------------------------------------------------

Write-Host ""
Write-Host "Repository scanning configuration:"
Write-Host ""


aws ecr batch-get-repository-scanning-configuration `
    --repository-names $RepositoryNames `
    --region $Region `
    --profile $AwsProfile `
    --query `
    "scanningConfigurations[].{Name:repositoryName,Frequency:scanFrequency,Filter:appliedScanFilters[0].filter,FilterType:appliedScanFilters[0].filterType}" `
    --output table `
    --no-cli-pager


if ($LASTEXITCODE -ne 0) {
    throw "Unable to verify ECR scanning configuration."
}


Write-Host ""
Write-Host "All ECR repositories are configured successfully."
