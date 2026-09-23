[CmdletBinding()]
param(
    [string]$RuntimeDir,

    [Parameter(Mandatory)]
    [string]$ContractsDir
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if ([string]::IsNullOrWhiteSpace($RuntimeDir)) {
    $serviceConfigPath = Join-Path $repoRoot 'config\grokbuddy.service.json'
    $serviceConfig = Get-Content -LiteralPath $serviceConfigPath -Raw | ConvertFrom-Json
    $configuredRuntimeDir = [string]$serviceConfig.runtimeDir
    if ([string]::IsNullOrWhiteSpace($configuredRuntimeDir)) {
        throw 'config/grokbuddy.service.json must define runtimeDir.'
    }
    $RuntimeDir = [IO.Path]::GetFullPath((Join-Path $repoRoot $configuredRuntimeDir))
}

$python = Join-Path $repoRoot '.venv-phase0\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $python = Join-Path $repoRoot '.venv\Scripts\python.exe'
}
if (-not (Test-Path -LiteralPath $python)) {
    throw 'No repository Python environment was found.'
}

. (Join-Path $PSScriptRoot 'Get-GrokBuddyCredential.ps1')
$credential = $null
$pointer = [IntPtr]::Zero
try {
    $credential = Get-GrokBuddyCredential -Target 'GrokBuddy/GROKBUDDY_TRIGGER_SOURCE_KEY'
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($credential)
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    if ([Text.Encoding]::UTF8.GetByteCount($plain) -lt 32) {
        throw 'credential target is shorter than 32 UTF-8 bytes: GrokBuddy/GROKBUDDY_TRIGGER_SOURCE_KEY'
    }
    [Environment]::SetEnvironmentVariable('GROKBUDDY_TRIGGER_SOURCE_KEY', $plain, 'Process')
    $plain = $null

    $entrypoint = Join-Path $repoRoot 'scripts\grokbuddy_ingress_mcp.py'
    & $python $entrypoint --runtime-dir $RuntimeDir --contracts-dir $ContractsDir
    exit $LASTEXITCODE
}
finally {
    [Environment]::SetEnvironmentVariable('GROKBUDDY_TRIGGER_SOURCE_KEY', $null, 'Process')
    if ($pointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
    if ($null -ne $credential) {
        $credential.Dispose()
    }
}
