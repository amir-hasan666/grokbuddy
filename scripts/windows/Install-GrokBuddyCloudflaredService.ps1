[CmdletBinding()]
param(
    [string]$CloudflaredPath = 'C:\Program Files (x86)\cloudflared\cloudflared.exe',
    [string]$TokenPath = 'C:\ProgramData\cloudflared\token'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Run this script from an elevated PowerShell session.'
}
if (-not (Test-Path -LiteralPath $CloudflaredPath)) {
    throw "cloudflared executable was not found: $CloudflaredPath"
}

$service = Get-Service -Name 'cloudflared' -ErrorAction SilentlyContinue
if (-not $service) {
    if (-not (Test-Path -LiteralPath $TokenPath)) {
        throw "Named Tunnel token file was not found: $TokenPath"
    }
    $token = (Get-Content -LiteralPath $TokenPath -Raw).Trim()
    if (-not $token) {
        throw 'Named Tunnel token file is empty.'
    }
    & $CloudflaredPath service install $token
    $token = $null
    if ($LASTEXITCODE -ne 0) {
        throw "cloudflared service install failed with exit code $LASTEXITCODE."
    }
}

Set-Service -Name 'cloudflared' -StartupType Automatic
& sc.exe failure cloudflared reset= 86400 actions= restart/5000/restart/15000/restart/60000 | Out-Null
Start-Service -Name 'cloudflared'
$serviceInfo = Get-CimInstance Win32_Service -Filter "Name='cloudflared'"
if ($serviceInfo.PathName -match '(?i)--token\s') {
    throw 'Unsafe cloudflared service command line contains an inline token.'
}
if ($serviceInfo.PathName -notmatch '(?i)--token-file') {
    throw 'cloudflared service is not configured with --token-file.'
}

[pscustomobject]@{
    Name = $serviceInfo.Name
    State = $serviceInfo.State
    StartMode = $serviceInfo.StartMode
    CredentialMode = 'token-file'
    Recovery = 'restart/5s,restart/15s,restart/60s'
}
