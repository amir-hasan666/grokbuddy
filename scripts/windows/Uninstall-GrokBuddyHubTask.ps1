[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$TaskName = 'GrokBuddy Hub',
    [string]$SecretsPath,
    [switch]$RemoveCredentialFile
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not $SecretsPath) {
    $SecretsPath = Join-Path $repoRoot 'var\service\hub-secrets.clixml'
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task -and $PSCmdlet.ShouldProcess($TaskName, 'stop and unregister scheduled task')) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$hubProcesses = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -match '^python(w)?\.exe$' -and
    $_.CommandLine -like '*grokbuddy_composite.py*' -and
    $_.CommandLine -like "*$repoRoot*"
}
foreach ($process in $hubProcesses) {
    if ($PSCmdlet.ShouldProcess("PID $($process.ProcessId)", 'stop repository Hub process')) {
        Stop-Process -Id $process.ProcessId -Force
    }
}

if ($RemoveCredentialFile -and (Test-Path -LiteralPath $SecretsPath) -and
        $PSCmdlet.ShouldProcess($SecretsPath, 'remove DPAPI credential file')) {
    Remove-Item -LiteralPath $SecretsPath -Force
}
