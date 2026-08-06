[CmdletBinding()]
param(
    [string]$Region = "ap-south-1",
    [string]$AwsProfile = "default",
    [string]$LogGroupPrefix = "/olist-delivery/dev",
    [int]$RetentionInDays = 7
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Olist Delivery - ECS CloudWatch Log Groups"
Write-Host "=========================================="
Write-Host "Region:         $Region"
Write-Host "Prefix:         $LogGroupPrefix"
Write-Host "Retention days: $RetentionInDays"
Write-Host ""

# Verify that the AWS profile works.
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

$LogGroups = @(
    "$LogGroupPrefix/api",
    "$LogGroupPrefix/frontend",
    "$LogGroupPrefix/worker"
)

$ResourceTags = (
    "Project=olist-delivery-mlops," +
    "Environment=dev," +
    "Owner=manthan," +
    "ManagedBy=aws-cli"
)

foreach ($LogGroupName in $LogGroups) {
    Write-Host ""
    Write-Host "Processing log group: $LogGroupName"

    $DescribeJson = aws logs describe-log-groups `
        --log-group-name-prefix $LogGroupName `
        --region $Region `
        --profile $AwsProfile `
        --output json `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect CloudWatch log group '$LogGroupName'."
    }

    $DescribeResponse = $DescribeJson | ConvertFrom-Json

    $ExistingLogGroup = $DescribeResponse.logGroups |
        Where-Object {
            $_.logGroupName -eq $LogGroupName
        } |
        Select-Object -First 1

    if ($null -eq $ExistingLogGroup) {
        Write-Host "Creating log group."

        aws logs create-log-group `
            --log-group-name $LogGroupName `
            --log-group-class STANDARD `
            --tags $ResourceTags `
            --region $Region `
            --profile $AwsProfile `
            --no-cli-pager

        if ($LASTEXITCODE -ne 0) {
            throw "Unable to create CloudWatch log group '$LogGroupName'."
        }

        Write-Host "Log group created."
    }
    else {
        Write-Host "Log group already exists."
    }

    # Keep log retention synchronized on every run.
    aws logs put-retention-policy `
        --log-group-name $LogGroupName `
        --retention-in-days $RetentionInDays `
        --region $Region `
        --profile $AwsProfile `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to configure retention for '$LogGroupName'."
    }

    # Retrieve the non-wildcard ARN required by the tagging API.
    $LogGroupArn = aws logs describe-log-groups `
        --log-group-name-prefix $LogGroupName `
        --region $Region `
        --profile $AwsProfile `
        --query "logGroups[?logGroupName=='$LogGroupName'].logGroupArn | [0]" `
        --output text `
        --no-cli-pager

    if (
        $LASTEXITCODE -ne 0 -or
        [string]::IsNullOrWhiteSpace($LogGroupArn) -or
        $LogGroupArn -eq "None"
    ) {
        throw "Unable to determine the ARN for '$LogGroupName'."
    }

    aws logs tag-resource `
        --resource-arn $LogGroupArn `
        --tags $ResourceTags `
        --region $Region `
        --profile $AwsProfile `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to tag CloudWatch log group '$LogGroupName'."
    }

    Write-Host "Retention and tags configured."
}

Write-Host ""
Write-Host "CloudWatch log-group verification"
Write-Host "================================="

aws logs describe-log-groups `
    --log-group-name-prefix "$LogGroupPrefix/" `
    --region $Region `
    --profile $AwsProfile `
    --query `
    "logGroups[].{
        Name:logGroupName,
        Class:logGroupClass,
        RetentionDays:retentionInDays,
        StoredBytes:storedBytes
    }" `
    --output table `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to verify CloudWatch log groups."
}

Write-Host ""
Write-Host "ECS CloudWatch log-group foundation completed successfully."