Set-StrictMode -Version Latest

if (-not ('GrokBuddy.WindowsCredentialManager.NativeMethods' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

namespace GrokBuddy.WindowsCredentialManager
{
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct NativeCredential
    {
        public UInt32 Flags;
        public UInt32 Type;
        public string TargetName;
        public string Comment;
        public System.Runtime.InteropServices.ComTypes.FILETIME LastWritten;
        public UInt32 CredentialBlobSize;
        public IntPtr CredentialBlob;
        public UInt32 Persist;
        public UInt32 AttributeCount;
        public IntPtr Attributes;
        public string TargetAlias;
        public string UserName;
    }

    public static class NativeMethods
    {
        [DllImport("Advapi32.dll", EntryPoint = "CredReadW", CharSet = CharSet.Unicode, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        public static extern bool CredRead(
            string target,
            UInt32 type,
            UInt32 flags,
            out IntPtr credentialPointer);

        [DllImport("Advapi32.dll", SetLastError = false)]
        public static extern void CredFree(IntPtr buffer);
    }
}
'@
}

function Get-GrokBuddyCredential {
    [CmdletBinding()]
    [OutputType([Security.SecureString])]
    param(
        [Parameter(Mandatory)]
        [ValidateNotNullOrEmpty()]
        [string]$Target
    )

    $credentialPointer = [IntPtr]::Zero
    $secureValue = $null
    try {
        $found = [GrokBuddy.WindowsCredentialManager.NativeMethods]::CredRead(
            $Target,
            1,
            0,
            [ref]$credentialPointer
        )
        if (-not $found -or $credentialPointer -eq [IntPtr]::Zero) {
            throw 'credential unavailable'
        }

        $nativeCredential = [Runtime.InteropServices.Marshal]::PtrToStructure(
            $credentialPointer,
            [type][GrokBuddy.WindowsCredentialManager.NativeCredential]
        )
        $blobSize = [int]$nativeCredential.CredentialBlobSize
        if ($blobSize -le 0 -or $nativeCredential.CredentialBlob -eq [IntPtr]::Zero -or ($blobSize % 2) -ne 0) {
            throw 'credential unavailable'
        }

        $characterCount = [int]($blobSize / 2)
        while ($characterCount -gt 0 -and
                [Runtime.InteropServices.Marshal]::ReadInt16($nativeCredential.CredentialBlob, (($characterCount - 1) * 2)) -eq 0) {
            $characterCount--
        }
        if ($characterCount -eq 0) {
            throw 'credential unavailable'
        }

        $secureValue = New-Object Security.SecureString
        for ($index = 0; $index -lt $characterCount; $index++) {
            $codeUnit = [uint16][Runtime.InteropServices.Marshal]::ReadInt16(
                $nativeCredential.CredentialBlob,
                ($index * 2)
            )
            $secureValue.AppendChar([char]$codeUnit)
        }
        $secureValue.MakeReadOnly()
        return $secureValue
    }
    catch {
        if ($null -ne $secureValue) {
            $secureValue.Dispose()
        }
        throw "credential target missing: $Target"
    }
    finally {
        if ($credentialPointer -ne [IntPtr]::Zero) {
            [GrokBuddy.WindowsCredentialManager.NativeMethods]::CredFree($credentialPointer)
        }
    }
}
