[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Get-GrokBuddyCredential.ps1')

$targets = @(
    'GrokBuddy/GITHUB_WEBHOOK_SECRET',
    'GrokBuddy/GROKBUDDY_MCP_TOKEN',
    'GrokBuddy/GROKBUDDY_GROK_REVIEWER_TOKEN',
    'GrokBuddy/GROKBUDDY_TRIGGER_SOURCE_KEY'
)

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
