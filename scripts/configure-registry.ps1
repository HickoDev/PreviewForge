[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Write-Host 'Use a HickoDev personal access token (classic) with ONLY read:packages.'
Write-Host 'The hidden prompt sends it directly to the local Kubernetes Secret; it is not saved in Git or command history.'
$pfSecureToken = Read-Host 'GHCR read-only token (hidden)' -AsSecureString
$pfTokenPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($pfSecureToken)
try {
    $pfPlainToken = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pfTokenPointer)
    $pfPlainToken | & python (Join-Path $PSScriptRoot 'configure_remote.py') registry --stdin
    if ($LASTEXITCODE -ne 0) { throw 'Private registry configuration failed.' }
} finally {
    $pfPlainToken = $null
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pfTokenPointer)
    $pfSecureToken.Dispose()
}
