# Application setup and operation

## Prerequisites

- Windows x64 or Linux x64; Git available on PATH.
- A local Docker daemon running Linux containers; Docker Compose 2.24.4+.
- Free loopback ports 8000 (API) and 4566 (Floci).
- Python 3.12 on PATH for the common CLI. On Linux, use `python3` if `python` is unavailable.
- Internet for the first pull/install. Images and packages are pinned; subsequent builds use local caches where available.

See [Windows/Linux prerequisites](installation.md). The project does not install/reconfigure Docker, WSL or the machine's Kubernetes context. kind, Helm, Terraform and AWS CLI are unnecessary for this demo; boto3 performs the emulator checks.

The later full application suite, `python scripts/ci.py test`, requires Python 3.12 and Compose **2.24.4+** for its isolated Floci override. The Compose commands on this page use the baseline configuration. See [all test modes](testing.md).

## Get the repository

Use a dedicated project directory and preserve any existing work. For the owner-operated installation, run `gh auth status` and confirm that **HickoDev** is the active GitHub account before cloning:

```text
gh repo clone HickoDev/PreviewForge
cd PreviewForge
```

If the checkout already exists, open its directory instead of cloning over it.

Once the repository is public, readers can clone its HTTPS URL with Git and run this Compose demo without the owner's GitHub credentials:

```text
git clone https://github.com/HickoDev/PreviewForge.git
cd PreviewForge
```

This standalone demo does not configure remote PR delivery. Full-platform GitHub scripts retain their explicit owner/repository checks.

## Start from the repository root

```text
python scripts/dev.py up
```

The script works with absolute paths internally, generates a private password once, builds the API, starts PostgreSQL and Floci, runs Alembic and waits for API readiness. Normal startup uses the `previewforge-m1` Compose project. Windows users can still use `scripts/dev.ps1`; it delegates to this Python implementation.

URLs: `http://127.0.0.1:8000/docs`, `/health/live`, `/health/ready`, `/version`, `/metrics`; Floci health: `http://127.0.0.1:4566/_floci/health`. Swagger UI loads its usual public CDN assets, so the interactive docs page requires browser internet access; the API and `/openapi.json` work locally.

Startup builds only local images. It does not push Git changes or publish images.

## Try the API

PowerShell:

```powershell
$base = 'http://127.0.0.1:8000'
$task = Invoke-RestMethod "$base/tasks" -Method Post -ContentType 'application/json' -Body '{"title":"Try PreviewForge locally"}'
Invoke-RestMethod "$base/tasks"
Invoke-RestMethod "$base/tasks/$($task.id)" -Method Patch -ContentType 'application/json' -Body '{"status":"done"}'
Invoke-RestMethod "$base/version"

python scripts/dev.py seed
```

Bash/curl (replace `TASK_ID` with the ID returned by the first request):

```bash
curl --fail-with-body -sS http://127.0.0.1:8000/tasks -H 'Content-Type: application/json' -d '{"title":"Try PreviewForge locally"}'
curl --fail-with-body -sS http://127.0.0.1:8000/tasks
curl --fail-with-body -sS -X PATCH http://127.0.0.1:8000/tasks/TASK_ID -H 'Content-Type: application/json' -d '{"status":"done"}'
curl --fail-with-body -sS http://127.0.0.1:8000/version
python scripts/dev.py seed
```

The browser's `/docs` page provides the same API operations on either OS.

Statuses are `todo`, `in_progress` and `done`. Titles are trimmed, required and limited to 200 characters. Invalid inputs return 422; updating a missing task returns 404. Listing accepts `?limit=1&offset=0`, with a maximum page size of 100. Updates change status only. The current application has no authentication, frontend or task-delete endpoint; use synthetic data. Exports are disabled in this Compose baseline and enabled in the [configured Kubernetes platform](resources.md).

## Verify

```text
python scripts/dev.py test
python scripts/dev.py verify
```

`test` builds the test image, starts isolated PostgreSQL, checks lint/format and runs pytest. It removes its test database container afterward. It does not publish images.

`verify` also starts the full stack, creates an isolated host virtual environment under the runtime directory, installs hashed dependencies and runs S3/SQS checks from both host Python and inside the actual API container. Each smoke run owns uniquely named `pf-smoke-<uuid>` resources, deletes its object, bucket and queue in cleanup, and checks they are absent. Cleanup also handles a create call whose response was lost. It then exercises the API through real HTTP, checks `/version` against the expected checkout SHA, replaces the API container, briefly stops **this project's** PostgreSQL, checks 503 readiness versus 200 liveness, restores PostgreSQL in a `finally` block and checks that the task survived. It leaves one synthetic acceptance task per run.

Verification must run with Python assertions enabled: `-O` and `PYTHONOPTIMIZE` are rejected rather than allowing checks to be silently skipped.

Keep the terminal open during the database-outage check. If a process is forcibly killed, rerun `up` to restore the stack. An ordinary assertion failure still attempts database recovery and smoke-resource cleanup.

## Inspect, restart and stop

```text
python scripts/dev.py status
python scripts/dev.py logs
python scripts/dev.py restart-api
python scripts/dev.py down
```

`down` removes only containers/network in the selected Compose project and retains named data volumes. Do not delete its runtime password while retaining the PostgreSQL volume: the initialized database still expects that password. Reuse the same runtime directory when bringing retained data back up. The script never prunes Docker or deletes unrelated containers/volumes.

Runtime location: `<installation-root>/runtime/previewforge-m1`; see [Windows/Linux defaults](installation.md#runtime-and-credentials). `PREVIEWFORGE_RUNTIME_DIR` is set by the command for its child processes. The directory contains `db_password` and, after full verification, `host-venv/`; no runtime files belong in synced folders or Git. Commands use per-project subdirectories and reject a runtime path inside the repository or a synced folder.

For an independent local acceptance run, every Python demo command accepts `--project-name previewforge-m1-acceptance` (the PowerShell wrapper retains `-ProjectName`). This selects separate runtime files/volumes. Stop the default stack first because both stacks use the same loopback ports; this is intended for sequential tests, not multi-preview routing.

## Troubleshooting

- Docker engine unavailable: start Docker Desktop on Windows or Docker Engine on Linux, then run `docker version`.
- Port 8000/4566 in use: stop the process/stack you own that uses the port; the script does not terminate other projects.
- Build/download failure: check registry/PyPI connectivity and rerun `up`; downloads use a 120-second socket timeout and a BuildKit package cache so completed downloads can be reused after interruptions. Slow first downloads may still take several minutes.
- Readiness remains unhealthy: run `status` and `logs`; migration errors prevent API startup and database outages return a sanitized 503.
- Python missing/wrong version: install/select Python 3.12 before any demo command. On Linux, try `python3 --version`.
- Floci resources left after an interrupted smoke test: the failing command reports its exact `pf-smoke-<uuid>` identity if cleanup fails. Inspect that identity before any manual deletion; do not delete resources by a broad prefix.

The root Compose service owns the shared Floci instance. The configured Kubernetes platform reuses that container and its volume. Running `python scripts/dev.py down` therefore also interrupts Kubernetes exports until [resource startup](resources.md) resumes Floci.
