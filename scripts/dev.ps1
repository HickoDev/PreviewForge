[CmdletBinding()]
param(
    [ValidateSet('up', 'test', 'verify', 'seed', 'down', 'status', 'logs', 'restart-api')]
    [string]$Action = 'up',
    [ValidatePattern('^previewforge-m1(?:-[a-z0-9-]+)?$')]
    [string]$ProjectName = 'previewforge-m1'
)

$ErrorActionPreference = 'Stop'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$composeFile = Join-Path $repoRoot 'compose.yaml'
$runtimeBase = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'PreviewForge\runtime'
$runtimePath = [IO.Path]::GetFullPath((Join-Path $runtimeBase $ProjectName))
if ($runtimePath -match '(?i)OneDrive' -or $runtimePath.StartsWith($repoRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Runtime files must be outside the repository and cloud-synced folders.'
}
$env:PREVIEWFORGE_RUNTIME_DIR = $runtimePath.Replace('\', '/')
$env:PREVIEWFORGE_COMPOSE_PROJECT = $ProjectName
$env:PREVIEWFORGE_SOURCE_SHA = 'local-uncommitted'
$sourceHead = git -C $repoRoot rev-parse --verify --quiet HEAD
if ($LASTEXITCODE -eq 0) {
    $env:PREVIEWFORGE_SOURCE_SHA = $sourceHead.Trim()
    $sourceChanges = git -C $repoRoot status --porcelain
    if ($sourceChanges) { $env:PREVIEWFORGE_SOURCE_SHA += '-dirty' }
}

function Invoke-Compose {
    & docker compose --project-name $ProjectName --file $composeFile @args
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose failed (exit $LASTEXITCODE)." }
}

function Initialize-Runtime {
    New-Item -ItemType Directory -Path $runtimePath -Force | Out-Null
    $passwordFile = Join-Path $runtimePath 'db_password'
    if (-not (Test-Path -LiteralPath $passwordFile)) {
        $randomBytes = New-Object byte[] 32
        $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
        try { $generator.GetBytes($randomBytes) } finally { $generator.Dispose() }
        $password = [BitConverter]::ToString($randomBytes).Replace('-', '').ToLowerInvariant()
        [IO.File]::WriteAllText($passwordFile, $password, (New-Object Text.UTF8Encoding($false)))
    }
}

function Start-Stack {
    Initialize-Runtime
    Invoke-Compose up --build --detach --wait --wait-timeout 180 api floci
    Write-Host 'API docs: http://127.0.0.1:8000/docs'
    Write-Host 'Readiness: http://127.0.0.1:8000/health/ready'
    Write-Host 'Floci: http://127.0.0.1:4566 (dummy credentials only)'
}

function Test-Stack {
    Initialize-Runtime
    Invoke-Compose --profile test build tests
    try {
        Invoke-Compose --profile test up --detach --wait --wait-timeout 120 test-db
        Invoke-Compose --profile test run --rm --no-deps tests ruff check --no-cache .
        Invoke-Compose --profile test run --rm --no-deps tests ruff format --check --no-cache .
        Invoke-Compose --profile test run --rm --no-deps tests
    } finally {
        Invoke-Compose --profile test rm --stop --force test-db
    }
}

switch ($Action) {
    'up' { Start-Stack }
    'test' { Test-Stack }
    'verify' {
        & python -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)'
        if ($LASTEXITCODE -ne 0) { throw 'Select Python 3.12 on PATH before host verification.' }
        Start-Stack
        Test-Stack
        $hostVenv = Join-Path $runtimePath 'host-venv'
        $hostPython = Join-Path $hostVenv 'Scripts\python.exe'
        if (-not (Test-Path -LiteralPath $hostPython)) {
            & python -m venv $hostVenv
            if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 is required for host verification.' }
        }
        & $hostPython -m pip install --disable-pip-version-check --timeout 120 --require-hashes -r (Join-Path $repoRoot 'previewforge-demo\requirements.lock')
        if ($LASTEXITCODE -ne 0) { throw 'Host verification dependency installation failed.' }
        Push-Location (Join-Path $repoRoot 'previewforge-demo')
        try {
            & $hostPython -m app.floci_smoke --endpoint http://127.0.0.1:4566
            if ($LASTEXITCODE -ne 0) { throw 'Host Floci smoke test failed.' }
        } finally { Pop-Location }
        Invoke-Compose exec -T api python -m app.floci_smoke --endpoint http://floci:4566
        & $hostPython (Join-Path $PSScriptRoot 'verify.py') --compose $composeFile --project $ProjectName --expected-sha $env:PREVIEWFORGE_SOURCE_SHA
        if ($LASTEXITCODE -ne 0) { throw 'HTTP/container acceptance checks failed.' }
    }
    'seed' { Invoke-Compose exec -T api python -m app.seed }
    'down' { Invoke-Compose --profile test down --remove-orphans }
    'status' { Invoke-Compose ps --all }
    'logs' { Invoke-Compose logs --tail 50 api migrate floci }
    'restart-api' { Invoke-Compose restart api }
}
