[CmdletBinding()]
param(
    [string]$TaskName = 'GrokBuddy Hub',
    [string]$PublicBase = 'https://grokbuddy.amirhasan.top'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-HttpProbe {
    param([string]$Uri)
    $bodyFile = [IO.Path]::GetTempFileName()
    try {
        $code = & curl.exe -4 --silent --show-error --connect-timeout 2 --max-time 5 --output $bodyFile --write-out '%{http_code}' $Uri 2>$null
        $exitCode = $LASTEXITCODE
        $body = if (Test-Path -LiteralPath $bodyFile) {
            $rawBody = Get-Content -LiteralPath $bodyFile -Raw -ErrorAction SilentlyContinue
            if ($null -eq $rawBody) { '' } else { ([string]$rawBody).Trim() }
        }
        else {
            ''
        }
        return [pscustomobject]@{
            Code = if ($exitCode -eq 0) { [string]$code } else { '000' }
            Body = $body
            CurlExitCode = $exitCode
        }
    }
    finally {
        Remove-Item -LiteralPath $bodyFile -Force -ErrorAction SilentlyContinue
    }
}

$service = Get-Service -Name 'cloudflared' -ErrorAction SilentlyContinue
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$taskInfo = if ($task) { Get-ScheduledTaskInfo -TaskName $TaskName } else { $null }
$listener = @(Get-NetTCPConnection -State Listen -LocalPort 8788 -ErrorAction SilentlyContinue)
if ($listener.Count -eq 0) {
    $netstatLine = netstat.exe -ano -p TCP | Select-String -Pattern ':8788\s+.*LISTENING\s+\d+$' | Select-Object -First 1
    if ($netstatLine -and [string]$netstatLine -match '^\s*TCP\s+(\S+)\s+\S+\s+LISTENING\s+(\d+)\s*$') {
        $listener = @([pscustomobject]@{
            LocalAddress = $Matches[1] -replace ':8788$', ''
            LocalPort = 8788
            OwningProcess = [int]$Matches[2]
        })
    }
}
$result = [ordered]@{
    CheckedAt = (Get-Date -Format o)
    Cloudflared = if ($service) { [ordered]@{ State=[string]$service.Status; StartMode=[string]$service.StartType } } else { $null }
    HubTask = if ($task) {
        [ordered]@{
            State = [string]$task.State
            LastRunTime = $taskInfo.LastRunTime
            LastTaskResult = $taskInfo.LastTaskResult
            HoldsHubProcess = ([string]$task.State -eq 'Running')
            ResultMeaning = if ([string]$task.State -eq 'Running' -and $taskInfo.LastTaskResult -eq 267009) {
                'SCHED_S_TASK_RUNNING (expected for the long-lived launcher)'
            }
            else {
                'Inspect only after the task exits; a healthy long-lived launcher is normally Running.'
            }
        }
    }
    else { $null }
    Port8788 = @($listener | Select-Object LocalAddress,LocalPort,OwningProcess)
    Local = [ordered]@{
        Health = Get-HttpProbe 'http://127.0.0.1:8788/health'
        Ready = Get-HttpProbe 'http://127.0.0.1:8788/ready'
        Root = Get-HttpProbe 'http://127.0.0.1:8788/'
    }
    Public = [ordered]@{
        Health = Get-HttpProbe "$PublicBase/health"
        Ready = Get-HttpProbe "$PublicBase/ready"
        Root = Get-HttpProbe "$PublicBase/"
    }
}
$result | ConvertTo-Json -Depth 6

$ok = $service -and $service.Status -eq 'Running' -and $service.StartType -eq 'Automatic' -and
    $task -and [string]$task.State -eq 'Running' -and $listener.Count -gt 0 -and
    $result.Local.Health.Code -eq '200' -and $result.Local.Health.Body -eq '{"status": "ok"}' -and
    $result.Local.Ready.Code -eq '200' -and $result.Local.Ready.Body -match '"status": "ready"' -and
    $result.Local.Root.Code -eq '404' -and $result.Local.Root.Body -eq '{"error": "not_found"}' -and
    $result.Public.Health.Code -eq '200' -and $result.Public.Ready.Code -eq '200' -and
    $result.Public.Root.Code -eq '404' -and $result.Public.Root.Body -eq '{"error": "not_found"}'
if (-not $ok) {
    exit 1
}
