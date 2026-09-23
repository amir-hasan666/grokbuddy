[CmdletBinding()]
param(
    [string]$TaskName = 'GrokBuddy Hub',
    [string]$EvidencePath,
    [ValidateRange(1, 300)]
    [int]$ReadyTimeoutSeconds = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not $EvidencePath) {
    $EvidencePath = Join-Path $repoRoot 'var\service\hub-task-restart.json'
}

function Write-RestartEvidence {
    param([object]$Value)
    New-Item -ItemType Directory -Path (Split-Path $EvidencePath -Parent) -Force | Out-Null
    $Value | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $EvidencePath -Encoding UTF8
}

try {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

    $listeners = @(Get-NetTCPConnection -State Listen -LocalPort 8788 -ErrorAction SilentlyContinue)
    $stopped = @()
    foreach ($listener in $listeners) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)"
        $commandLine = [string]$process.CommandLine
        if ($commandLine -notlike '*grokbuddy_composite.py*') {
            throw "Refusing to stop PID $($listener.OwningProcess): it is not grokbuddy_composite.py."
        }
        if ($commandLine -notlike "*$repoRoot*" -and $commandLine -notlike '*scripts\grokbuddy_composite.py*') {
            throw "Refusing to stop PID $($listener.OwningProcess): repository identity is not confirmed."
        }
        Stop-Process -Id $listener.OwningProcess -Force
        $stopped += $listener.OwningProcess
    }

    Start-ScheduledTask -TaskName $TaskName
    $deadline = (Get-Date).AddSeconds($ReadyTimeoutSeconds)
    $ready = $false
    $supervisorCheck = $null
    do {
        Start-Sleep -Milliseconds 500
        try {
            $response = Invoke-RestMethod -Uri 'http://127.0.0.1:8788/ready' -TimeoutSec 2
            $supervisorCheck = if (
                $null -ne $response.checks -and
                $null -ne $response.checks.PSObject.Properties['supervisor']
            ) { [string]$response.checks.supervisor } else { $null }
            $ready = $response.status -eq 'ready' -and $supervisorCheck -eq 'ok'
        }
        catch {
            $ready = $false
            $supervisorCheck = $null
        }
    } until ($ready -or (Get-Date) -ge $deadline)

    if (-not $ready) {
        throw "GrokBuddy Hub did not become ready with supervisor=ok within $ReadyTimeoutSeconds seconds."
    }

    $result = [pscustomobject]@{
        TaskName = $TaskName
        StoppedProcessIds = $stopped
        Ready = $ready
        Supervisor = $supervisorCheck
        ReadyTimeoutSeconds = $ReadyTimeoutSeconds
        Port = 8788
    }
    Write-RestartEvidence $result
    $result
}
catch {
    Write-RestartEvidence ([pscustomobject]@{
        TaskName = $TaskName
        Ready = $false
        ReadyTimeoutSeconds = $ReadyTimeoutSeconds
        Error = $_.Exception.Message
    })
    throw
}
