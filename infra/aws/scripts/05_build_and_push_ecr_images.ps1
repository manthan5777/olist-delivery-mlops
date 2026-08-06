[CmdletBinding()]
param(
    [string]$Region = "ap-south-1",
    [string]$AwsProfile = "default",
    [string]$ImageTag = ""
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Olist Delivery - Build and Push ECR Images"
Write-Host "=========================================="

# Find and enter the Git repository root.
$RepositoryRoot = git rev-parse --show-toplevel

if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($RepositoryRoot)) {
    throw "This script must be run from inside the Git repository."
}

$RepositoryRoot = $RepositoryRoot.Trim()
Set-Location $RepositoryRoot

Write-Host "Repository root: $RepositoryRoot"

# Require committed source so the image tag can identify exact source code.
$GitChanges = git status --porcelain

if ($LASTEXITCODE -ne 0) {
    throw "Unable to read Git working-tree status."
}

if ($GitChanges) {
    throw @"
The Git working tree is not clean.

Commit or discard the current changes before building images.
This protects source-to-image traceability.
"@
}

# Use the current Git commit as the default image tag.
if ([string]::IsNullOrWhiteSpace($ImageTag)) {
    $ImageTag = git rev-parse --short HEAD

    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($ImageTag)) {
        throw "Unable to determine the current Git commit."
    }

    $ImageTag = $ImageTag.Trim()
}

# Validate the Docker image tag.
if ($ImageTag -notmatch "^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$") {
    throw "Invalid Docker image tag: $ImageTag"
}

# Confirm Docker Desktop is running.
$DockerServerVersion = docker version --format "{{.Server.Version}}"

if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($DockerServerVersion)) {
    throw "Docker Desktop is not running or cannot be reached."
}

Write-Host "Docker Engine: $DockerServerVersion"
Write-Host "Image tag: $ImageTag"

# Discover the AWS account instead of hardcoding it.
$AccountId = aws sts get-caller-identity `
    --profile $AwsProfile `
    --query Account `
    --output text `
    --no-cli-pager

if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($AccountId)) {
    throw "Unable to determine the AWS account ID."
}

$AccountId = $AccountId.Trim()
$Registry = "$AccountId.dkr.ecr.$Region.amazonaws.com"

Write-Host "AWS region: $Region"
Write-Host "ECR registry: $Registry"

# Authenticate Docker to the private ECR registry.
$EcrPassword = aws ecr get-login-password `
    --region $Region `
    --profile $AwsProfile

if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($EcrPassword)) {
    throw "Unable to obtain an ECR login password."
}

$EcrPassword |
docker login `
    --username AWS `
    --password-stdin $Registry

if ($LASTEXITCODE -ne 0) {
    throw "Docker authentication to ECR failed."
}

# Dockerfiles and their ECR repository destinations.
$Images = @(
    [PSCustomObject]@{
        Name       = "api"
        Dockerfile = "Dockerfile"
        Repository = "olist-delivery/api"
    },
    [PSCustomObject]@{
        Name       = "frontend"
        Dockerfile = "frontend/Dockerfile"
        Repository = "olist-delivery/frontend"
    },
    [PSCustomObject]@{
        Name       = "worker"
        Dockerfile = "worker/Dockerfile"
        Repository = "olist-delivery/worker"
    }
)

foreach ($Image in $Images) {
    $ImageUri = "$Registry/$($Image.Repository):$ImageTag"

    Write-Host ""
    Write-Host "Building and pushing: $($Image.Name)"
    Write-Host "Dockerfile: $($Image.Dockerfile)"
    Write-Host "Destination: $ImageUri"
    Write-Host "------------------------------------------"

    docker buildx build `
        --platform "linux/amd64" `
        --provenance=false `
        --sbom=false `
        --file $Image.Dockerfile `
        --tag $ImageUri `
        --push `
        .

    if ($LASTEXITCODE -ne 0) {
        throw "Build or push failed for $($Image.Name)."
    }
}

Write-Host ""
Write-Host "Verifying uploaded images"
Write-Host "========================="

foreach ($Image in $Images) {
    aws ecr describe-images `
        --repository-name $Image.Repository `
        --image-ids "imageTag=$ImageTag" `
        --region $Region `
        --profile $AwsProfile `
        --query "imageDetails[0].{Repository:'$($Image.Repository)',Tag:imageTags[0],MediaType:imageManifestMediaType,Digest:imageDigest}" `
        --output table `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "ECR verification failed for $($Image.Repository)."
    }
}

Write-Host ""
Write-Host "Build and push completed successfully."
Write-Host "Image tag: $ImageTag"