[CmdletBinding()]
param(
    [string]$ConfigPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$bootstrapLog = Join-Path $repoRoot 'var\service\logs\hub.bootstrap.log'
function Write-BootstrapFailure {
    param([string]$Message)
    try {
        New-Item -ItemType Directory -Path (Split-Path $bootstrapLog -Parent) -Force | Out-Null
        Add-Content -LiteralPath $bootstrapLog -Value "$(Get-Date -Format o) bootstrap failed: $Message" -Encoding UTF8
    }
    catch {
    }
}

try {
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $repoRoot 'config\grokbuddy.service.json'
}
$config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding utf8 | ConvertFrom-Json
$reviewerRegistryValue = if ($null -ne $config.PSObject.Properties['reviewerRegistryPath']) {
    [string]$config.reviewerRegistryPath
}
else {
    ''
}
if ([string]::IsNullOrWhiteSpace($reviewerRegistryValue)) {
    throw 'The service config must define reviewerRegistryPath.'
}
$reviewerRegistryPath = Join-Path $repoRoot $reviewerRegistryValue
if (-not (Test-Path -LiteralPath $reviewerRegistryPath -PathType Leaf)) {
    throw 'The configured Reviewer registry is missing.'
}
$reviewerRegistry = Get-Content -LiteralPath $reviewerRegistryPath -Raw -Encoding utf8 | ConvertFrom-Json
if ([string]::IsNullOrWhiteSpace([string]$reviewerRegistry.activeReviewer)) {
    throw 'The Reviewer registry must define activeReviewer.'
}
if ([string]$config.reviewerActor -ne [string]$reviewerRegistry.activeReviewer) {
    throw 'The service reviewerActor conflicts with the active Reviewer registry entry.'
}
if ($config.publicBase -ne 'https://grokbuddy.amirhasan.top') {
    throw 'The service PublicBase must be https://grokbuddy.amirhasan.top.'
}
$supervisorEnabled = $true
if ($null -ne $config.PSObject.Properties['supervisorEnabled']) {
    if ($config.supervisorEnabled -isnot [bool]) {
        throw 'supervisorEnabled must be a boolean.'
    }
    $supervisorEnabled = [bool]$config.supervisorEnabled
}
$supervisorIntervalSeconds = if ($null -ne $config.PSObject.Properties['supervisorIntervalSeconds']) {
    [double]$config.supervisorIntervalSeconds
}
else {
    5.0
}
if ($supervisorIntervalSeconds -le 0 -or $supervisorIntervalSeconds -gt 5) {
    throw 'supervisorIntervalSeconds must be greater than 0 and at most 5.'
}
$githubCommentTokenEnv = if ($null -ne $config.PSObject.Properties['githubCommentTokenEnv']) {
    [string]$config.githubCommentTokenEnv
}
else {
    'GITHUB_COMMENT_TOKEN'
}
if ($githubCommentTokenEnv -ne 'GITHUB_COMMENT_TOKEN') {
    throw 'The formal service GitHub Comment token environment name must be GITHUB_COMMENT_TOKEN.'
}
$reviewerWakeWebhookUrlEnv = if ($null -ne $config.PSObject.Properties['reviewerWakeWebhookUrlEnv']) {
    [string]$config.reviewerWakeWebhookUrlEnv
}
else {
    ''
}
$reviewerWakeWebhookKeyEnv = if ($null -ne $config.PSObject.Properties['reviewerWakeWebhookKeyEnv']) {
    [string]$config.reviewerWakeWebhookKeyEnv
}
else {
    ''
}
if ([bool]$reviewerWakeWebhookUrlEnv -ne [bool]$reviewerWakeWebhookKeyEnv) {
    throw 'Reviewer wake URL and key environment names must be configured together.'
}
$reviewerWakeEnabled = [bool]$reviewerWakeWebhookUrlEnv
if ($reviewerWakeEnabled) {
    $environmentNamePattern = '^[A-Z][A-Z0-9_]{0,79}$'
    $reservedEnvironmentNames = @(
        'GITHUB_WEBHOOK_SECRET',
        'GROKBUDDY_MCP_TOKEN',
        'GROKBUDDY_GROK_REVIEWER_TOKEN',
        'GROKBUDDY_TRIGGER_SOURCE_KEY',
        $githubCommentTokenEnv,
        'PUBLIC_BASE'
    )
    if ($reviewerWakeWebhookUrlEnv -notmatch $environmentNamePattern -or
            $reviewerWakeWebhookKeyEnv -notmatch $environmentNamePattern -or
            $reviewerWakeWebhookUrlEnv -eq $reviewerWakeWebhookKeyEnv -or
            $reviewerWakeWebhookUrlEnv -in $reservedEnvironmentNames -or
            $reviewerWakeWebhookKeyEnv -in $reservedEnvironmentNames) {
        throw 'Reviewer wake environment names are invalid.'
    }
}
$reviewerWakeMaxAttempts = if ($null -ne $config.PSObject.Properties['reviewerWakeMaxAttempts']) {
    [int]$config.reviewerWakeMaxAttempts
}
else {
    3
}
if ($reviewerWakeMaxAttempts -lt 1 -or $reviewerWakeMaxAttempts -gt 5) {
    throw 'reviewerWakeMaxAttempts must be between 1 and 5.'
}

$python = Join-Path $repoRoot '.venv-phase0\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = Join-Path $repoRoot '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $python)) {
    throw 'No repository Python environment was found.'
}
function Set-ProcessSecret {
    param(
        [string]$Name,
        [Security.SecureString]$Value,
        [int]$MinimumUtf8Bytes = 1
    )
    if ($null -eq $Value) {
        throw "Required protected value is missing: $Name"
    }
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try {
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        if ([Text.Encoding]::UTF8.GetByteCount($plain) -lt $MinimumUtf8Bytes) {
            throw "Required protected value is too short: $Name"
        }
        [Environment]::SetEnvironmentVariable($Name, $plain, 'Process')
    }
    finally {
        if ($null -ne $pointer) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        }
        $plain = $null
    }
}

$credentialLog = Join-Path $repoRoot 'var\service\logs\hub.credential.log'
New-Item -ItemType Directory -Path (Split-Path $credentialLog -Parent) -Force | Out-Null
. (Join-Path $PSScriptRoot 'Get-GrokBuddyCredential.ps1')
$credentialMappings = [ordered]@{
    'GrokBuddy/GITHUB_WEBHOOK_SECRET' = 'GITHUB_WEBHOOK_SECRET'
    'GrokBuddy/GROKBUDDY_MCP_TOKEN' = 'GROKBUDDY_MCP_TOKEN'
    'GrokBuddy/GROKBUDDY_GROK_REVIEWER_TOKEN' = 'GROKBUDDY_GROK_REVIEWER_TOKEN'
    'GrokBuddy/GROKBUDDY_TRIGGER_SOURCE_KEY' = 'GROKBUDDY_TRIGGER_SOURCE_KEY'
}
if ($supervisorEnabled) {
    $credentialMappings['GrokBuddy/GITHUB_COMMENT_TOKEN'] = $githubCommentTokenEnv
}
if ($reviewerWakeEnabled) {
    $credentialMappings['GrokBuddy/REVIEWER_WAKE_WEBHOOK_URL'] = $reviewerWakeWebhookUrlEnv
    $credentialMappings['GrokBuddy/REVIEWER_WAKE_WEBHOOK_KEY'] = $reviewerWakeWebhookKeyEnv
}
foreach ($target in $credentialMappings.Keys) {
    $credential = $null
    try {
        $credential = Get-GrokBuddyCredential -Target $target
        $minimumBytes = if ($target -eq 'GrokBuddy/GROKBUDDY_TRIGGER_SOURCE_KEY') { 32 } else { 1 }
        Set-ProcessSecret -Name $credentialMappings[$target] -Value $credential -MinimumUtf8Bytes $minimumBytes
        Add-Content -LiteralPath $credentialLog -Value "$(Get-Date -Format o) PRESENT: $target" -Encoding UTF8
    }
    catch {
        $safeMessage = if ($_.Exception.Message -like '*too short*') {
            "credential target invalid: $target"
        }
        else {
            "credential target missing: $target"
        }
        Add-Content -LiteralPath $credentialLog -Value "$(Get-Date -Format o) $safeMessage" -Encoding UTF8
        throw $safeMessage
    }
    finally {
        if ($null -ne $credential) {
            $credential.Dispose()
        }
    }
}
$env:PUBLIC_BASE = $config.publicBase

$port = [int]$config.port
$existing = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
if ($existing) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 3
        $ready = Invoke-RestMethod -Uri "http://127.0.0.1:$port/ready" -TimeoutSec 3
        $supervisorCheck = if (
            $null -ne $ready.checks -and
            $null -ne $ready.checks.PSObject.Properties['supervisor']
        ) { [string]$ready.checks.supervisor } else { $null }
        $supervisorReady = (-not $supervisorEnabled) -or $supervisorCheck -eq 'ok'
        if ($health.status -eq 'ok' -and $ready.status -eq 'ready' -and $supervisorReady) {
            exit 0
        }
        throw "Port $port is occupied by a GrokBuddy Hub that is not production-ready."
    }
    catch {
        throw "Port $port is already occupied by a process that is not a ready GrokBuddy Hub."
    }
}

$logRoot = Join-Path $repoRoot 'var\service\logs'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$stdoutLog = Join-Path $logRoot 'hub.stdout.log'
$stderrLog = Join-Path $logRoot 'hub.stderr.log'
$statusLog = Join-Path $logRoot 'hub.service.log'
$runtimeDir = Join-Path $repoRoot ([string]$config.runtimeDir)
$contractsDir = Join-Path $repoRoot ([string]$config.contractsDir)
$entrypoint = Join-Path $repoRoot 'scripts\grokbuddy_composite.py'

$arguments = @(
    $entrypoint,
    '--runtime-dir', $runtimeDir,
    '--contracts-dir', $contractsDir,
    '--host', [string]$config.host,
    '--port', [string]$port,
    '--public-base-url', [string]$config.publicBase,
    '--reviewer-registry', $reviewerRegistryPath,
    '--github-comment-token-env', $githubCommentTokenEnv,
    '--supervisor-interval-seconds', [string]$supervisorIntervalSeconds
)
if (-not $supervisorEnabled) {
    $arguments += '--disable-supervisor'
}
if ($reviewerWakeEnabled) {
    $arguments += @(
        '--reviewer-wake-webhook-url-env', $reviewerWakeWebhookUrlEnv,
        '--reviewer-wake-webhook-key-env', $reviewerWakeWebhookKeyEnv,
        '--reviewer-wake-max-attempts', [string]$reviewerWakeMaxAttempts
    )
}
}
catch {
    Write-BootstrapFailure -Message ([string]$_.Exception.Message)
    exit 1
}

Add-Content -LiteralPath $statusLog -Value "$(Get-Date -Format o) starting hub" -Encoding UTF8
try {
    $hubProcess = Start-Process `
        -FilePath $python `
        -ArgumentList $arguments `
        -WorkingDirectory $repoRoot `
        -RedirectStandardOutput $stdoutLog `
        -RedirectStandardError $stderrLog `
        -NoNewWindow `
        -PassThru `
        -Wait
    $exitCode = [int]$hubProcess.ExitCode
}
catch {
    $safeMessage = [string]$_.Exception.Message
    Add-Content -LiteralPath $statusLog -Value "$(Get-Date -Format o) hub process launch failed: $safeMessage" -Encoding UTF8
    exit 1
}
Add-Content -LiteralPath $statusLog -Value "$(Get-Date -Format o) hub exited code=$exitCode" -Encoding UTF8
exit $exitCode
