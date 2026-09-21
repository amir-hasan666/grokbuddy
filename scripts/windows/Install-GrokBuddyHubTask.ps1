[CmdletBinding()]
param(
    [string]$TaskName = 'GrokBuddy Hub',
    [string]$SecretsPath,
    [string]$EvidencePath,
    [switch]$UseExistingSecrets,
    [switch]$SecretsOnly,
    [switch]$DoNotStart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not $SecretsPath) {
    $SecretsPath = Join-Path $repoRoot 'var\service\hub-secrets.clixml'
}
if (-not $EvidencePath) {
    $EvidencePath = Join-Path $repoRoot 'var\service\hub-task-install.json'
}
if ($UseExistingSecrets -and $SecretsOnly) {
    throw 'UseExistingSecrets and SecretsOnly cannot be combined.'
}

$required = 'GITHUB_WEBHOOK_SECRET', 'GROKBUDDY_MCP_TOKEN', 'GROKBUDDY_GROK_REVIEWER_TOKEN'
if ($UseExistingSecrets) {
    if (-not (Test-Path -LiteralPath $SecretsPath)) {
        throw "Existing DPAPI secret file is missing: $SecretsPath"
    }
}
else {
    $missing = @($required | Where-Object { -not [Environment]::GetEnvironmentVariable($_, 'Process') })
    if ($missing.Count -gt 0) {
        throw "Required process environment variables are missing: $($missing -join ', ')"
    }
    $secretDirectory = Split-Path $SecretsPath -Parent
    New-Item -ItemType Directory -Path $secretDirectory -Force | Out-Null
    $protected = [pscustomobject]@{}
    foreach ($name in $required) {
        $secure = ConvertTo-SecureString ([Environment]::GetEnvironmentVariable($name, 'Process')) -AsPlainText -Force
        Add-Member -InputObject $protected -NotePropertyName $name -NotePropertyValue $secure
    }
    $protected | Export-Clixml -LiteralPath $SecretsPath -Force
}

if ($SecretsOnly) {
    [pscustomobject]@{ Secrets='DPAPI_CURRENT_USER'; SecretsPath=$SecretsPath; Registered=$false }
    return
}

$launcher = Join-Path $PSScriptRoot 'Start-GrokBuddyHub.ps1'
$windowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$escapedLauncher = $launcher.Replace('"', '""')
$escapedSecrets = $SecretsPath.Replace('"', '""')
$actionArguments = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$escapedLauncher`" -SecretsPath `"$escapedSecrets`""
$action = New-ScheduledTaskAction -Execute $windowsPowerShell -Argument $actionArguments
$trigger = New-ScheduledTaskTrigger -AtLogOn -User ([Security.Principal.WindowsIdentity]::GetCurrent().Name)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RestartCount 10 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

if (-not $DoNotStart) {
    Start-ScheduledTask -TaskName $TaskName
}

$registered = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$result = [pscustomobject]@{
    TaskName = $TaskName
    TaskPath = $registered.TaskPath
    State = [string]$registered.State
    User = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    Trigger = 'AtLogOn'
    RestartCount = 10
    Secrets = 'DPAPI_CURRENT_USER'
    RuntimeSecretSource = 'DPAPI_CURRENT_USER_OR_PRECONFIGURED_ENVIRONMENT'
    SecretsPath = $SecretsPath
    Started = -not $DoNotStart
}
New-Item -ItemType Directory -Path (Split-Path $EvidencePath -Parent) -Force | Out-Null
$result | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $EvidencePath -Encoding UTF8
$result
