[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Get-GrokBuddyCredential.ps1')

$targets = @(
    'GrokBuddy/GITHUB_WEBHOOK_SECRET',
    'GrokBuddy/GROKBUDDY_MCP_TOKEN',
    'GrokBuddy/GROKBUDDY_GROK_REVIEWER_TOKEN',
    'GrokBuddy/GROKBUDDY_TRIGGER_SOURCE_KEY',
    'GrokBuddy/GITHUB_COMMENT_TOKEN'
)
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$config = Get-Content -LiteralPath (Join-Path $repoRoot 'config\grokbuddy.service.json') -Raw |
    ConvertFrom-Json
$wakeUrlEnv = if ($null -ne $config.PSObject.Properties['reviewerWakeWebhookUrlEnv']) {
    [string]$config.reviewerWakeWebhookUrlEnv
}
else { '' }
$wakeKeyEnv = if ($null -ne $config.PSObject.Properties['reviewerWakeWebhookKeyEnv']) {
    [string]$config.reviewerWakeWebhookKeyEnv
}
else { '' }
if ([bool]$wakeUrlEnv -ne [bool]$wakeKeyEnv) {
    throw 'Reviewer wake URL and key environment names must be configured together.'
}
if ($wakeUrlEnv) {
    $targets += @(
        'GrokBuddy/REVIEWER_WAKE_WEBHOOK_URL',
        'GrokBuddy/REVIEWER_WAKE_WEBHOOK_KEY'
    )
}

foreach ($target in $targets) {
    $credential = $null
    $pointer = [IntPtr]::Zero
    $plain = $null
    try {
        $credential = Get-GrokBuddyCredential -Target $target
        if ($target -eq 'GrokBuddy/GROKBUDDY_TRIGGER_SOURCE_KEY') {
            $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($credential)
            try {
                $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
                if ([Text.Encoding]::UTF8.GetByteCount($plain) -lt 32) {
                    throw "credential target is shorter than 32 UTF-8 bytes: $target"
                }
            }
            finally {
                if ($pointer -ne [IntPtr]::Zero) {
                    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
                }
                $plain = $null
            }
        }
        [pscustomobject]@{
            Target = $target
            Status = 'PRESENT'
        }
    }
    catch {
        throw $_.Exception.Message
    }
    finally {
        if ($null -ne $credential) {
            $credential.Dispose()
        }
    }
}
