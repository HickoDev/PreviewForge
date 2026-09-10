[CmdletBinding()]
param(
    [ValidateSet('up', 'start', 'verify', 'status', 'forward', 'stop', 'publish-local')]
    [string]$Action = 'up'
)
$ErrorActionPreference = 'Stop'
& python (Join-Path $PSScriptRoot 'platform_local.py') $Action
if ($LASTEXITCODE -ne 0) { throw "Milestone 2 command failed (exit $LASTEXITCODE)." }
