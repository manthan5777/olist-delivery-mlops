[CmdletBinding()]
param(
    [string]$Region = "ap-south-1",
    [string]$AwsProfile = "default",
    [string]$LoadBalancerName = "olist-delivery-dev-alb",
    [string]$AlbSecurityGroupName = "olist-delivery-dev-alb-sg",
    [string]$ApiTargetGroupName = "olist-delivery-dev-api-tg",
    [string]$FrontendTargetGroupName = "olist-delivery-dev-frontend-tg"
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Olist Delivery - Application Load Balancer"
Write-Host "=========================================="
Write-Host "Load balancer: $LoadBalancerName"
Write-Host "Region:        $Region"
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

$SubnetIdsText = aws ec2 describe-subnets `
    --filters `
        "Name=vpc-id,Values=$VpcId" `
        "Name=state,Values=available" `
    --region $Region `
    --profile $AwsProfile `
    --query "Subnets[].SubnetId" `
    --output text `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect VPC subnets."
}

$SubnetIds = @(
    $SubnetIdsText `
        -split "\s+" |
        Where-Object {
            -not [string]::IsNullOrWhiteSpace($_)
        }
)

if ($SubnetIds.Count -lt 2) {
    throw (
        "Application Load Balancer requires at least two usable subnets. " +
        "Found: $($SubnetIds.Count)"
    )
}

Write-Host "Subnets found: $($SubnetIds.Count)"

foreach ($SubnetId in $SubnetIds) {
    Write-Host "  $SubnetId"
}

# --------------------------------------------------
# Helper: ensure target group
# --------------------------------------------------

function Ensure-TargetGroup {
    param(
        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [int]$Port,

        [Parameter(Mandatory)]
        [string]$HealthPath
    )

    $TargetGroupArn = aws elbv2 describe-target-groups `
        --region $Region `
        --profile $AwsProfile `
        --query "TargetGroups[?TargetGroupName=='$Name'].TargetGroupArn | [0]" `
        --output text `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to inspect target groups."
    }

    if (
        [string]::IsNullOrWhiteSpace($TargetGroupArn) -or
        $TargetGroupArn -eq "None"
    ) {
        Write-Host "Creating target group: $Name"

        $TargetGroupArn = aws elbv2 create-target-group `
            --name $Name `
            --protocol HTTP `
            --port $Port `
            --vpc-id $VpcId `
            --target-type ip `
            --health-check-protocol HTTP `
            --health-check-port traffic-port `
            --health-check-path $HealthPath `
            --health-check-interval-seconds 30 `
            --health-check-timeout-seconds 5 `
            --healthy-threshold-count 2 `
            --unhealthy-threshold-count 2 `
            --matcher "HttpCode=200-399" `
            --tags `
                "Key=Project,Value=olist-delivery-mlops" `
                "Key=Environment,Value=dev" `
                "Key=Owner,Value=manthan" `
                "Key=ManagedBy,Value=aws-cli" `
            --region $Region `
            --profile $AwsProfile `
            --query "TargetGroups[0].TargetGroupArn" `
            --output text `
            --no-cli-pager

        if (
            $LASTEXITCODE -ne 0 -or
            [string]::IsNullOrWhiteSpace($TargetGroupArn)
        ) {
            throw "Unable to create target group '$Name'."
        }
    }
    else {
        Write-Host "Target group already exists: $Name"

        aws elbv2 modify-target-group `
            --target-group-arn $TargetGroupArn `
            --health-check-protocol HTTP `
            --health-check-port traffic-port `
            --health-check-path $HealthPath `
            --health-check-interval-seconds 30 `
            --health-check-timeout-seconds 5 `
            --healthy-threshold-count 2 `
            --unhealthy-threshold-count 2 `
            --matcher "HttpCode=200-399" `
            --region $Region `
            --profile $AwsProfile `
            --no-cli-pager |
        Out-Null

        if ($LASTEXITCODE -ne 0) {
            throw "Unable to synchronize target group '$Name'."
        }
    }

    return $TargetGroupArn.Trim()
}

# --------------------------------------------------
# Create/reuse target groups
# --------------------------------------------------

Write-Host ""
Write-Host "Ensuring target groups"
Write-Host "======================"

$ApiTargetGroupArn = Ensure-TargetGroup `
    -Name $ApiTargetGroupName `
    -Port 8000 `
    -HealthPath "/health"

$FrontendTargetGroupArn = Ensure-TargetGroup `
    -Name $FrontendTargetGroupName `
    -Port 8501 `
    -HealthPath "/_stcore/health"

# --------------------------------------------------
# Create/reuse ALB
# --------------------------------------------------

Write-Host ""
Write-Host "Ensuring Application Load Balancer"
Write-Host "==================================="

$LoadBalancerJson = aws elbv2 describe-load-balancers `
    --region $Region `
    --profile $AwsProfile `
    --query "LoadBalancers[?LoadBalancerName=='$LoadBalancerName'] | [0]" `
    --output json `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect Application Load Balancers."
}

$LoadBalancer = $LoadBalancerJson | ConvertFrom-Json

if ($null -eq $LoadBalancer) {

    Write-Host "Creating internet-facing ALB."

    $CreateJson = aws elbv2 create-load-balancer `
        --name $LoadBalancerName `
        --type application `
        --scheme internet-facing `
        --ip-address-type ipv4 `
        --subnets $SubnetIds `
        --security-groups $AlbSecurityGroupId `
        --tags `
            "Key=Project,Value=olist-delivery-mlops" `
            "Key=Environment,Value=dev" `
            "Key=Owner,Value=manthan" `
            "Key=ManagedBy,Value=aws-cli" `
        --region $Region `
        --profile $AwsProfile `
        --output json `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create Application Load Balancer."
    }

    $CreateResponse = $CreateJson | ConvertFrom-Json
    $LoadBalancer = $CreateResponse.LoadBalancers |
        Select-Object -First 1

    Write-Host "ALB creation started."
}
else {
    Write-Host "Application Load Balancer already exists."
}

$LoadBalancerArn = $LoadBalancer.LoadBalancerArn

if ([string]::IsNullOrWhiteSpace($LoadBalancerArn)) {
    throw "Unable to determine load balancer ARN."
}

Write-Host "Waiting for ALB to become available."

aws elbv2 wait load-balancer-available `
    --load-balancer-arns $LoadBalancerArn `
    --region $Region `
    --profile $AwsProfile

if ($LASTEXITCODE -ne 0) {
    throw "Application Load Balancer did not become available."
}

# Refresh ALB details after wait.
$LoadBalancerJson = aws elbv2 describe-load-balancers `
    --load-balancer-arns $LoadBalancerArn `
    --region $Region `
    --profile $AwsProfile `
    --output json `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to refresh Application Load Balancer details."
}

$LoadBalancerResponse = $LoadBalancerJson | ConvertFrom-Json
$LoadBalancer = $LoadBalancerResponse.LoadBalancers |
    Select-Object -First 1

$AlbDnsName = $LoadBalancer.DNSName

# --------------------------------------------------
# Create/reuse HTTP listener
# --------------------------------------------------

Write-Host ""
Write-Host "Ensuring HTTP listener"
Write-Host "======================"

$ListenersJson = aws elbv2 describe-listeners `
    --load-balancer-arn $LoadBalancerArn `
    --region $Region `
    --profile $AwsProfile `
    --output json `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect ALB listeners."
}

$Listeners = ($ListenersJson | ConvertFrom-Json).Listeners

$HttpListener = $Listeners |
    Where-Object {
        $_.Port -eq 80 -and
        $_.Protocol -eq "HTTP"
    } |
    Select-Object -First 1

if ($null -eq $HttpListener) {

    Write-Host "Creating HTTP listener on port 80."

    $ListenerJson = aws elbv2 create-listener `
        --load-balancer-arn $LoadBalancerArn `
        --protocol HTTP `
        --port 80 `
        --default-actions `
            "Type=forward,TargetGroupArn=$FrontendTargetGroupArn" `
        --region $Region `
        --profile $AwsProfile `
        --output json `
        --no-cli-pager

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to create HTTP listener."
    }

    $HttpListener = ($ListenerJson | ConvertFrom-Json).Listeners |
        Select-Object -First 1
}
else {
    Write-Host "HTTP listener already exists."

    aws elbv2 modify-listener `
        --listener-arn $HttpListener.ListenerArn `
        --default-actions `
            "Type=forward,TargetGroupArn=$FrontendTargetGroupArn" `
        --region $Region `
        --profile $AwsProfile `
        --output json `
        --no-cli-pager |
    Out-Null

    if ($LASTEXITCODE -ne 0) {
        throw "Unable to synchronize HTTP listener."
    }
}

$ListenerArn = $HttpListener.ListenerArn

# --------------------------------------------------
# Create/update /api/* listener rule
# --------------------------------------------------

Write-Host ""
Write-Host "Ensuring API routing rule"
Write-Host "========================="

$RulesJson = aws elbv2 describe-rules `
    --listener-arn $ListenerArn `
    --region $Region `
    --profile $AwsProfile `
    --output json `
    --no-cli-pager

if ($LASTEXITCODE -ne 0) {
    throw "Unable to inspect listener rules."
}

$Rules = ($RulesJson | ConvertFrom-Json).Rules

$ApiRule = $Rules |
    Where-Object {
        $Rule = $_

        $Rule.Conditions |
            Where-Object {
                $_.Field -eq "path-pattern" -and
                $_.Values -contains "/api/*"
            }
    } |
    Select-Object -First 1

$Conditions = @(
    @{
        Field = "path-pattern"
        PathPatternConfig = @{
            Values = @(
                "/api/*"
            )
        }
    }
)

$Actions = @(
    @{
        Type = "forward"
        TargetGroupArn = $ApiTargetGroupArn
    }
)

# Replicates the local Nginx behavior:
#
# /api/health
#       ↓
# /health
#
# /api/jobs/demo
#       ↓
# /jobs/demo
$Transforms = @(
    @{
        Type = "url-rewrite"
        UrlRewriteConfig = @{
            Rewrites = @(
                @{
                    Regex   = "^/api/(.*)$"
                    Replace = "/`$1"
                }
            )
        }
    }
)

$TemporaryDirectory = [System.IO.Path]::GetTempPath()
$UniqueId = [System.Guid]::NewGuid().ToString("N")
$RuleInputPath = Join-Path `
    $TemporaryDirectory `
    "olist-alb-rule-$UniqueId.json"

$Utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)

try {

    if ($null -eq $ApiRule) {

        Write-Host "Creating /api/* routing rule."

        $RuleInput = @{
            ListenerArn = $ListenerArn
            Priority    = 10
            Conditions  = $Conditions
            Actions     = $Actions
            Transforms  = $Transforms
            Tags        = @(
                @{
                    Key   = "Project"
                    Value = "olist-delivery-mlops"
                },
                @{
                    Key   = "Environment"
                    Value = "dev"
                },
                @{
                    Key   = "ManagedBy"
                    Value = "aws-cli"
                }
            )
        } | ConvertTo-Json -Depth 15

        [System.IO.File]::WriteAllText(
            $RuleInputPath,
            $RuleInput,
            $Utf8WithoutBom
        )

        $RuleInputUri = (
            "file://" +
            ($RuleInputPath -replace '\\', '/')
        )

        aws elbv2 create-rule `
            --cli-input-json $RuleInputUri `
            --region $Region `
            --profile $AwsProfile `
            --output json `
            --no-cli-pager |
        Out-Null

        if ($LASTEXITCODE -ne 0) {
            throw "Unable to create /api/* listener rule."
        }
    }
    else {

        Write-Host "/api/* routing rule already exists."

        $RuleInput = @{
            RuleArn    = $ApiRule.RuleArn
            Conditions = $Conditions
            Actions    = $Actions
            Transforms = $Transforms
        } | ConvertTo-Json -Depth 15

        [System.IO.File]::WriteAllText(
            $RuleInputPath,
            $RuleInput,
            $Utf8WithoutBom
        )

        $RuleInputUri = (
            "file://" +
            ($RuleInputPath -replace '\\', '/')
        )

        aws elbv2 modify-rule `
            --cli-input-json $RuleInputUri `
            --region $Region `
            --profile $AwsProfile `
            --output json `
            --no-cli-pager |
        Out-Null

        if ($LASTEXITCODE -ne 0) {
            throw "Unable to synchronize /api/* listener rule."
        }
    }
}
finally {
    Remove-Item `
        $RuleInputPath `
        -Force `
        -ErrorAction SilentlyContinue
}

# --------------------------------------------------
# Verification
# --------------------------------------------------

Write-Host ""
Write-Host "Application Load Balancer verification"
Write-Host "======================================"

Write-Host "Name: $LoadBalancerName"
Write-Host "State: $($LoadBalancer.State.Code)"
Write-Host "DNS: http://$AlbDnsName"
Write-Host ""

Write-Host "Routing"
Write-Host "======="
Write-Host "Default:"
Write-Host "  /* -> frontend target group :8501"
Write-Host ""
Write-Host "API:"
Write-Host "  /api/* -> URL rewrite -> API target group :8000"
Write-Host ""
Write-Host "Examples:"
Write-Host "  /api/health    -> /health"
Write-Host "  /api/jobs/demo -> /jobs/demo"
Write-Host ""
Write-Host "No ECS tasks are registered with the target groups yet."
Write-Host ""
Write-Host "Application Load Balancer foundation completed successfully."