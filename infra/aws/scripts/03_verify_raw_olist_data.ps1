param(
    [string]$Region = "ap-south-1",

    [string]$BucketName = (
        "olist-delivery-mlops-" +
        "198233241420-" +
        "ap-south-1"
    ),

    [string]$Profile = "default",

    [string]$Prefix = "raw/olist/"
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
Write-Host "Olist raw-data verification"
Write-Host "---------------------------"
Write-Host "Local source : $LocalRawPath"
Write-Host "Bucket       : $BucketName"
Write-Host "S3 prefix    : $Prefix"
Write-Host "Region       : $Region"
Write-Host "Profile      : $Profile"
Write-Host ""


# --------------------------------------------------
# 2. READ LOCAL CSV FILE METADATA
# --------------------------------------------------

$LocalFiles = @(
    Get-ChildItem `
        -Path $LocalRawPath `
        -File `
        -Filter "*.csv" |
    Sort-Object Name
)


if ($LocalFiles.Count -eq 0) {
    throw "No local CSV files were found."
}


# --------------------------------------------------
# 3. READ S3 OBJECT METADATA
# --------------------------------------------------

Write-Host "Reading S3 object metadata..."

$S3JsonLines = aws s3api list-objects-v2 `
    --bucket $BucketName `
    --prefix $Prefix `
    --region $Region `
    --profile $Profile `
    --query "Contents[].{Key:Key,Size:Size}" `
    --output json `
    --no-cli-pager


if ($LASTEXITCODE -ne 0) {
    throw "Unable to list S3 objects."
}


# AWS CLI output arrives in PowerShell as multiple text lines.
# Join those lines into one valid JSON string before parsing.
$S3JsonText = $S3JsonLines -join [Environment]::NewLine

$ParsedS3Objects = ConvertFrom-Json `
    -InputObject $S3JsonText


# Copy every parsed JSON record into a normal flat array.
$S3Objects = @()

foreach ($Object in $ParsedS3Objects) {
    $S3Objects += $Object
}


# --------------------------------------------------
# 4. INDEX S3 OBJECTS BY FILE NAME
# --------------------------------------------------

$S3FilesByName = @{}

foreach ($S3Object in $S3Objects) {
    $FileName = [System.IO.Path]::GetFileName(
        $S3Object.Key
    )

    if (-not [string]::IsNullOrWhiteSpace($FileName)) {
        $S3FilesByName[$FileName] = [int64]$S3Object.Size
    }
}


# --------------------------------------------------
# 5. COMPARE EACH LOCAL FILE WITH S3
# --------------------------------------------------

$Results = foreach ($LocalFile in $LocalFiles) {
    $FileName = $LocalFile.Name
    $LocalSize = [int64]$LocalFile.Length

    if (-not $S3FilesByName.ContainsKey($FileName)) {
        [PSCustomObject]@{
            FileName   = $FileName
            LocalBytes = $LocalSize
            S3Bytes    = $null
            Status     = "MISSING IN S3"
        }

        continue
    }

    $S3Size = [int64]$S3FilesByName[$FileName]

    $Status = if ($LocalSize -eq $S3Size) {
        "MATCH"
    }
    else {
        "SIZE MISMATCH"
    }

    [PSCustomObject]@{
        FileName   = $FileName
        LocalBytes = $LocalSize
        S3Bytes    = $S3Size
        Status     = $Status
    }
}


$LocalFileNames = @(
    $LocalFiles |
    Select-Object -ExpandProperty Name
)

$ExtraS3Objects = @(
    $S3FilesByName.Keys |
    Where-Object {
        $_ -notin $LocalFileNames
    }
)


# --------------------------------------------------
# 6. DISPLAY SUMMARY
# --------------------------------------------------

Write-Host ""
Write-Host "File-by-file comparison:"
Write-Host ""

$Results |
Format-Table `
    FileName,
    LocalBytes,
    S3Bytes,
    Status `
    -AutoSize


$LocalTotalBytes = (
    $LocalFiles |
    Measure-Object `
        -Property Length `
        -Sum
).Sum

$S3TotalBytes = (
    $S3Objects |
    Measure-Object `
        -Property Size `
        -Sum
).Sum


Write-Host ""
Write-Host "Summary"
Write-Host "-------"
Write-Host "Local file count : $($LocalFiles.Count)"
Write-Host "S3 object count  : $($S3Objects.Count)"
Write-Host "Local total bytes: $LocalTotalBytes"
Write-Host "S3 total bytes   : $S3TotalBytes"


# --------------------------------------------------
# 7. DETERMINE FINAL VERIFICATION RESULT
# --------------------------------------------------

$FailedFiles = @(
    $Results |
    Where-Object {
        $_.Status -ne "MATCH"
    }
)


if ($ExtraS3Objects.Count -gt 0) {
    Write-Host ""
    Write-Host "Unexpected S3 objects:"

    $ExtraS3Objects |
    ForEach-Object {
        Write-Host " - $_"
    }
}


if (
    $FailedFiles.Count -gt 0 -or
    $ExtraS3Objects.Count -gt 0 -or
    $LocalFiles.Count -ne $S3Objects.Count -or
    $LocalTotalBytes -ne $S3TotalBytes
) {
    throw "Raw-data verification FAILED."
}


Write-Host ""
Write-Host "Raw-data verification PASSED."
