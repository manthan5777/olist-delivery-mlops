[CmdletBinding()]
param(
    [string]$Region = "ap-south-1",
    [string]$AwsProfile = "default"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Olist Delivery - ECS Security Groups"
Write-Host "===================================="
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
# Find the default VPC
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
# Helper: create/reuse a security group
# --------------------------------------------------

function Ensure-SecurityGroup {
    param(
        [Parameter(Mandatory)]
        [string]$GroupName,

        [Parameter(Mandatory)]
        [string]$Description
    )

    $GroupId = aws ec2 describe-security-groups `
        --filters `
            "Name=vpc-id,Values=$VpcId" `
            "Name=group-name,Values=$GroupName" `
        --region $Region `
        --profile $AwsProfile `
        --query "SecurityGroups[0].GroupId" `
        --output text `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect security group '$GroupName'."
    }

    if (
        [string]::IsNullOrWhiteSpace($GroupId) -or
        $GroupId -eq "None"
    ) {
        Write-Host "Creating security group: $GroupName"

        $GroupId = aws ec2 create-security-group `
            --group-name $GroupName `
            --description $Description `
            --vpc-id $VpcId `
            --region $Region `
            --profile $AwsProfile `
            --query GroupId `
            --output text `
            --no-cli-pager

        if (
            $LASTEXITCODE -ne 0 -or
            [string]::IsNullOrWhiteSpace($GroupId)
        ) {
            throw "Unable to create security group '$GroupName'."
        }

        $GroupId = $GroupId.Trim()

        Write-Host "Created: $GroupId"
    }
    else {
        $GroupId = $GroupId.Trim()

        Write-Host "Security group already exists: $GroupName"
    }

    aws ec2 create-tags `
        --resources $GroupId `
        --tags `
            "Key=Name,Value=$GroupName" `
            "Key=Project,Value=olist-delivery-mlops" `
            "Key=Environment,Value=dev" `
            "Key=Owner,Value=manthan" `
            "Key=ManagedBy,Value=aws-cli" `
        --region $Region `
        --profile $AwsProfile `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to tag security group '$GroupName'."
    }

    return $GroupId
}

# --------------------------------------------------
# Helper: CIDR ingress rule
# --------------------------------------------------

function Ensure-CidrIngress {
    param(
        [Parameter(Mandatory)]
        [string]$GroupId,

        [Parameter(Mandatory)]
        [int]$Port,

        [Parameter(Mandatory)]
        [string]$Cidr
    )

    $GroupJson = aws ec2 describe-security-groups `
        --group-ids $GroupId `
        --region $Region `
        --profile $AwsProfile `
        --output json `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect security group '$GroupId'."
    }

    $Group = $GroupJson | ConvertFrom-Json

    $RuleExists = $Group.SecurityGroups[0].IpPermissions |
        Where-Object {
            $_.IpProtocol -eq "tcp" -and
            $_.FromPort -eq $Port -and
            $_.ToPort -eq $Port -and
            (
                $_.IpRanges |
                Where-Object {
                    $_.CidrIp -eq $Cidr
                }
            )
        }

    if (-not $RuleExists) {
        Write-Host "Adding TCP $Port from $Cidr to $GroupId"

        aws ec2 authorize-security-group-ingress `
            --group-id $GroupId `
            --protocol tcp `
            --port $Port `
            --cidr $Cidr `
            --region $Region `
            --profile $AwsProfile `
            --no-cli-pager

        if ($LASTEXITCODE -ne 0) {
            throw "Unable to create TCP $Port ingress rule."
        }
    }
    else {
        Write-Host "Ingress rule already exists: TCP $Port from $Cidr"
    }
}

# --------------------------------------------------
# Helper: security-group-to-security-group ingress
# --------------------------------------------------

function Ensure-SecurityGroupIngress {
    param(
        [Parameter(Mandatory)]
        [string]$GroupId,

        [Parameter(Mandatory)]
        [int]$Port,

        [Parameter(Mandatory)]
        [string]$SourceGroupId
    )

    $GroupJson = aws ec2 describe-security-groups `
        --group-ids $GroupId `
        --region $Region `
        --profile $AwsProfile `
        --output json `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect security group '$GroupId'."
    }

    $Group = $GroupJson | ConvertFrom-Json

    $RuleExists = $Group.SecurityGroups[0].IpPermissions |
        Where-Object {
            $_.IpProtocol -eq "tcp" -and
            $_.FromPort -eq $Port -and
            $_.ToPort -eq $Port -and
            (
                $_.UserIdGroupPairs |
                Where-Object {
                    $_.GroupId -eq $SourceGroupId
                }
            )
        }

    if (-not $RuleExists) {
        Write-Host (
            "Adding TCP $Port from security group " +
            "$SourceGroupId to $GroupId"
        )

        aws ec2 authorize-security-group-ingress `
            --group-id $GroupId `
            --protocol tcp `
            --port $Port `
            --source-group $SourceGroupId `
            --region $Region `
            --profile $AwsProfile `
            --no-cli-pager

        if ($LASTEXITCODE -ne 0) {
            throw "Unable to create TCP $Port security-group rule."
        }
    }
    else {
        Write-Host (
            "Ingress rule already exists: TCP $Port " +
            "from $SourceGroupId"
        )
    }
}

# --------------------------------------------------
# Create security groups
# --------------------------------------------------

Write-Host ""
Write-Host "Ensuring security groups"
Write-Host "========================"

$AlbSecurityGroupId = Ensure-SecurityGroup `
    -GroupName "olist-delivery-dev-alb-sg" `
    -Description "Public ALB security group for Olist Delivery"

$EcsSecurityGroupId = Ensure-SecurityGroup `
    -GroupName "olist-delivery-dev-ecs-sg" `
    -Description "ECS Fargate task security group for Olist Delivery"

$CacheSecurityGroupId = Ensure-SecurityGroup `
    -GroupName "olist-delivery-dev-cache-sg" `
    -Description "Redis or Valkey security group for Olist Delivery"

# --------------------------------------------------
# ALB inbound traffic
# Internet -> ALB
# --------------------------------------------------

Ensure-CidrIngress `
    -GroupId $AlbSecurityGroupId `
    -Port 80 `
    -Cidr "0.0.0.0/0"

# --------------------------------------------------
# ALB -> ECS tasks
# --------------------------------------------------

Ensure-SecurityGroupIngress `
    -GroupId $EcsSecurityGroupId `
    -Port 8000 `
    -SourceGroupId $AlbSecurityGroupId

Ensure-SecurityGroupIngress `
    -GroupId $EcsSecurityGroupId `
    -Port 8501 `
    -SourceGroupId $AlbSecurityGroupId

# --------------------------------------------------
# ECS tasks -> Redis / Valkey
# --------------------------------------------------

Ensure-SecurityGroupIngress `
    -GroupId $CacheSecurityGroupId `
    -Port 6379 `
    -SourceGroupId $EcsSecurityGroupId

# --------------------------------------------------
# Verification
# --------------------------------------------------

Write-Host ""
Write-Host "Security-group verification"
Write-Host "==========================="

$SecurityGroupIds = @(
    $AlbSecurityGroupId,
    $EcsSecurityGroupId,
    $CacheSecurityGroupId
)

$VerificationJson = aws ec2 describe-security-groups `
    --group-ids $SecurityGroupIds `
    --region $Region `
    --profile $AwsProfile `
    --output json `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to verify security groups."
}

$Verification = $VerificationJson | ConvertFrom-Json

$Verification.SecurityGroups |
    Select-Object `
        GroupName,
        GroupId,
        VpcId |
    Format-Table -AutoSize

Write-Host ""
Write-Host "Expected traffic"
Write-Host "================"
Write-Host "Internet -> ALB:      TCP 80"
Write-Host "ALB -> API:           TCP 8000"
Write-Host "ALB -> Frontend:      TCP 8501"
Write-Host "ECS -> Redis/Valkey:  TCP 6379"

Write-Host ""
Write-Host "ECS security-group foundation completed successfully."