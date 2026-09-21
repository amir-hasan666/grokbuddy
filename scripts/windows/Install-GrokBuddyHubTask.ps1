[CmdletBinding()]
param(
    [string]$TaskName = 'GrokBuddy Hub',
    [string]$EvidencePath,
    [switch]$DoNotStart
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not $EvidencePath) {
    $EvidencePath = Join-Path $repoRoot 'var\service\hub-task-install.json'
}

& (Join-Path $PSScriptRoot 'Test-GrokBuddyCredentialStore.ps1')

$launcher = Join-Path $PSScriptRoot 'Start-GrokBuddyHub.ps1'
$windowsPowerShell = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$escapedLauncher = $launcher.Replace('"', '""')
$actionArguments = "-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$escapedLauncher`""
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
    RuntimeSecretSource = 'WINDOWS_CREDENTIAL_MANAGER'
    CredentialType = 'CRED_TYPE_GENERIC'
    Started = -not $DoNotStart
}
New-Item -ItemType Directory -Path (Split-Path $EvidencePath -Parent) -Force | Out-Null
$result | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $EvidencePath -Encoding UTF8
$result
