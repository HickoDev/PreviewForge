# Milestone 1 setup and operation

## Prerequisites

- Windows PowerShell 5.1 or newer; Git available on PATH.
- Docker Desktop running Linux containers using WSL2; Docker Compose v2.20+.
- Free loopback ports 8000 (API) and 4566 (Floci).
- Python 3.12 on PATH for host-side verification. Normal container startup/tests do not need a host Python installation.
- Internet for the first pull/install. Images and packages are pinned; subsequent builds use local caches where available.

Docker Desktop already worked on the implementation machine. The project does not install/reconfigure Docker, WSL or the machine's Kubernetes context. kind, Helm, Terraform and AWS CLI are unnecessary for this milestone; boto3 performs the emulator checks.

The later full application suite, `python scripts/ci.py test`, requires Python 3.12 and Compose **2.24.4+** for its isolated Floci override. The Compose commands on this page use the baseline configuration. See [all test modes](testing.md).

## Get the repository

Use a dedicated project directory and preserve any existing work. For the owner-operated installation, run `gh auth status` and confirm that **HickoDev** is the active GitHub account before cloning:

```powershell
gh repo clone HickoDev/PreviewForge
Set-Location .\PreviewForge
```

If the checkout already exists, open its directory instead of cloning over it.

Once the repository is public, readers can clone its HTTPS URL with Git and run this Compose demo without the owner's GitHub credentials:

```powershell
git clone https://github.com/HickoDev/PreviewForge.git
Set-Location .\PreviewForge
```

This standalone demo does not configure remote PR delivery. Full-platform GitHub scripts retain their explicit owner/repository checks.

## Start from the repository root

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 up
```

`Bypass` applies to that child PowerShell process; it does not change your stored execution policy. The script works with absolute paths internally, generates a private password once, builds the API, starts PostgreSQL and Floci, runs Alembic and waits for API readiness. Normal startup uses the `previewforge-m1` Compose project.

URLs: `http://127.0.0.1:8000/docs`, `/health/live`, `/health/ready`, `/version`, `/metrics`; Floci health: `http://127.0.0.1:4566/_floci/health`. Swagger UI loads its usual public CDN assets, so the interactive docs page requires browser internet access; the API and `/openapi.json` work locally.

Startup builds only local images. It does not push Git changes or publish images.

## Try the API

```powershell
$base = 'http://127.0.0.1:8000'
$task = Invoke-RestMethod "$base/tasks" -Method Post -ContentType 'application/json' -Body '{"title":"Try PreviewForge locally"}'
Invoke-RestMethod "$base/tasks"
Invoke-RestMethod "$base/tasks/$($task.id)" -Method Patch -ContentType 'application/json' -Body '{"status":"done"}'
Invoke-RestMethod "$base/version"

powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 seed
```

Statuses are `todo`, `in_progress` and `done`. Titles are trimmed, required and limited to 200 characters. Invalid inputs return 422; updating a missing task returns 404. Listing accepts `?limit=1&offset=0`, with a maximum page size of 100. Updates change status only. The current application has no authentication, frontend or task-delete endpoint; use synthetic data. Exports are disabled in this Compose baseline and enabled in the [configured Kubernetes platform](resources.md).

## Verify

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 test
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 verify
```

`test` builds the test image, starts isolated PostgreSQL, checks lint/format and runs pytest. It removes its test database container afterward. It does not publish images.

`verify` also starts the full stack, creates an isolated host virtual environment under the runtime directory, installs hashed dependencies and runs S3/SQS checks from both Windows Python and inside the actual API container. Each smoke run owns uniquely named `pf-smoke-<uuid>` resources, deletes its object, bucket and queue in cleanup, and checks they are absent. Cleanup also handles a create call whose response was lost. It then exercises the API through real HTTP, checks `/version` against the expected checkout SHA, replaces the API container, briefly stops **this project's** PostgreSQL, checks 503 readiness versus 200 liveness, restores PostgreSQL in a `finally` block and checks that the task survived. It leaves one synthetic acceptance task per run.

Verification must run with Python assertions enabled: `-O` and `PYTHONOPTIMIZE` are rejected rather than allowing checks to be silently skipped.

Keep the terminal open during the database-outage check. If a process is forcibly killed, rerun `up` to restore the stack. An ordinary assertion failure still attempts database recovery and smoke-resource cleanup.

## Inspect, restart and stop

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 status
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 logs
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 restart-api
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 down
```

`down` removes only containers/network in the selected Compose project and retains named data volumes. Do not delete its runtime password while retaining the PostgreSQL volume: the initialized database still expects that password. Reuse the same runtime directory when bringing retained data back up. The script never prunes Docker or deletes unrelated containers/volumes.

Runtime location: `%LOCALAPPDATA%\PreviewForge\runtime\previewforge-m1\`. `PREVIEWFORGE_RUNTIME_DIR` is set by the wrapper to that validated location. It contains `db_password` and, after full verification, `host-venv/`; no runtime files belong in OneDrive or Git. The wrapper uses per-project subdirectories and rejects a runtime path inside the repository or OneDrive.

For an independent local acceptance run, every command accepts `-ProjectName previewforge-m1-acceptance`. This selects separate runtime files/volumes. Stop the default stack first because both stacks use the same loopback ports; this is intended for sequential tests, not multi-preview routing.

## Troubleshooting

- Docker engine unavailable: start Docker Desktop, confirm Linux-container mode, then run `docker version`.
- Port 8000/4566 in use: stop the process/stack you own that uses the port; the script does not terminate other projects.
- Build/download failure: check registry/PyPI connectivity and rerun `up`; downloads use a 120-second socket timeout and a BuildKit package cache so completed downloads can be reused after interruptions. Slow first downloads may still take several minutes.
- Readiness remains unhealthy: run `status` and `logs`; migration errors prevent API startup and database outages return a sanitized 503.
- Python missing/wrong version: install/select Python 3.12 before `verify`; `up` and `test` run Python inside containers.
- Floci resources left after an interrupted smoke test: the failing command reports its exact `pf-smoke-<uuid>` identity if cleanup fails. Inspect that identity before any manual deletion; do not delete resources by a broad prefix.

The root Compose service owns the shared Floci instance. The configured Kubernetes platform reuses that container and its volume. Running `dev.ps1 down` therefore also interrupts Kubernetes exports until [resource startup](resources.md) resumes Floci.
