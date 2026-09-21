[CmdletBinding()]
param(
    [string]$ConfigPath,
    [string]$SecretsPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$bootstrapLog = Join-Path $repoRoot 'var\service\logs\hub.bootstrap.log'
trap {
    try {
        New-Item -ItemType Directory -Path (Split-Path $bootstrapLog -Parent) -Force | Out-Null
        $safeMessage = [string]$_.Exception.Message
        Add-Content -LiteralPath $bootstrapLog -Value "$(Get-Date -Format o) bootstrap failed: $safeMessage" -Encoding UTF8
    }
    catch {
    }
    exit 1
}
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $repoRoot 'config\grokbuddy.service.json'
}
if (-not $SecretsPath) {
    $SecretsPath = Join-Path $repoRoot 'var\service\hub-secrets.clixml'
}

$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
if ($config.publicBase -ne 'https://grokbuddy.amirhasan.top') {
    throw 'The service PublicBase must be https://grokbuddy.amirhasan.top.'
}

$python = Join-Path $repoRoot '.venv-phase0\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = Join-Path $repoRoot '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $python)) {
    throw 'No repository Python environment was found.'
}
if (-not (Test-Path -LiteralPath $SecretsPath)) {
    throw "DPAPI secret file is missing: $SecretsPath"
}

function Set-ProcessSecret {
    param([string]$Name, [Security.SecureString]$Value)
    if ($null -eq $Value) {
        throw "Required protected value is missing: $Name"
    }
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Value)
    try {
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
        [Environment]::SetEnvironmentVariable($Name, $plain, 'Process')
    }
    finally {
        if ($null -ne $pointer) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        }
        $plain = $null
    }
}

$requiredSecrets = 'GITHUB_WEBHOOK_SECRET', 'GROKBUDDY_MCP_TOKEN', 'GROKBUDDY_GROK_REVIEWER_TOKEN'
$userEnvironmentReady = @($requiredSecrets | Where-Object {
    -not [Environment]::GetEnvironmentVariable($_, 'User')
}).Count -eq 0
if ($userEnvironmentReady) {
    foreach ($name in $requiredSecrets) {
        [Environment]::SetEnvironmentVariable(
            $name,
            [Environment]::GetEnvironmentVariable($name, 'User'),
            'Process'
        )
    }
}
else {
    $protected = Import-Clixml -LiteralPath $SecretsPath
    Set-ProcessSecret -Name 'GITHUB_WEBHOOK_SECRET' -Value $protected.GITHUB_WEBHOOK_SECRET
    Set-ProcessSecret -Name 'GROKBUDDY_MCP_TOKEN' -Value $protected.GROKBUDDY_MCP_TOKEN
    Set-ProcessSecret -Name 'GROKBUDDY_GROK_REVIEWER_TOKEN' -Value $protected.GROKBUDDY_GROK_REVIEWER_TOKEN
}
$env:PUBLIC_BASE = $config.publicBase

$port = [int]$config.port
$existing = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
if ($existing) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 3
        $ready = Invoke-RestMethod -Uri "http://127.0.0.1:$port/ready" -TimeoutSec 3
        if ($health.status -eq 'ok' -and $ready.status -eq 'ready') {
            exit 0
        }
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
    '--grok-reviewer-actor', [string]$config.reviewerActor
)

Add-Content -LiteralPath $statusLog -Value "$(Get-Date -Format o) starting hub" -Encoding UTF8
Push-Location $repoRoot
try {
    & $python @arguments 1>> $stdoutLog 2>> $stderrLog
    $exitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
Add-Content -LiteralPath $statusLog -Value "$(Get-Date -Format o) hub exited code=$exitCode" -Encoding UTF8
exit $exitCode
