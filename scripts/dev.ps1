[CmdletBinding()]
param(
    [ValidateSet('up', 'test', 'verify', 'seed', 'down', 'status', 'logs', 'restart-api')]
    [string]$Action = 'up',
    [ValidatePattern('^previewforge-m1(?:-[a-z0-9-]+)?$')]
    [string]$ProjectName = 'previewforge-m1'
)

$ErrorActionPreference = 'Stop'
& python (Join-Path $PSScriptRoot 'dev.py') $Action --project-name $ProjectName
if ($LASTEXITCODE -ne 0) { throw "PreviewForge demo command failed (exit $LASTEXITCODE)." }
