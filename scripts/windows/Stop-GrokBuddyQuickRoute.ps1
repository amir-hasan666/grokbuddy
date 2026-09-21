[CmdletBinding(SupportsShouldProcess)]
param([string]$EvidencePath)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
if (-not $EvidencePath) {
    $EvidencePath = Join-Path $repoRoot 'var\service\quick-route-cleanup.json'
}

$legacy = @(Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -match '(?i)(?:^|\s)tunnel\s+--url(?:\s|=)' -or
    $_.CommandLine -match '(?i)--url(?:\s|=)https?://(?:127\.0\.0\.1|localhost):8788'
})
foreach ($process in $legacy) {
    if ($PSCmdlet.ShouldProcess("cloudflared PID $($process.ProcessId)", 'stop legacy Quick Tunnel process')) {
        Stop-Process -Id $process.ProcessId -Force
    }
}

$remaining = @(
    Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match '(?i)(?:^|\s)tunnel\s+--url(?:\s|=)' }
)
$result = [pscustomobject]@{
    Matched = $legacy.Count
    StoppedProcessIds = @($legacy | Select-Object -ExpandProperty ProcessId)
    RemainingQuickRouteProcesses = $remaining.Count
}
New-Item -ItemType Directory -Path (Split-Path $EvidencePath -Parent) -Force | Out-Null
$result | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $EvidencePath -Encoding UTF8
$result
