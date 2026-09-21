[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'Get-GrokBuddyCredential.ps1')

$targets = @(
    'GrokBuddy/GITHUB_WEBHOOK_SECRET',
    'GrokBuddy/GROKBUDDY_MCP_TOKEN',
    'GrokBuddy/GROKBUDDY_GROK_REVIEWER_TOKEN'
)

foreach ($target in $targets) {
    $credential = $null
    try {
        $credential = Get-GrokBuddyCredential -Target $target
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
