# Milestone 1 initial verification results

This is the historical record of the initial local implementation, before the user authorized committing/pushing. See the [Milestone 1 review](milestone-1-review.md) for subsequent fixes and verification.

**Result: all required Milestone 1 checks passed.** Final inventory checked at `2026-09-09 21:43:27 UTC` (22:43 in Tunis). No external blocker remains for this milestone.

The existing remote repository and workspace were empty. The active GitHub CLI account was verified as HickoDev before repository reads and cloning. At this initial verification point, implementation was local and uncommitted; no GitHub write, image publication, public exposure or real cloud provisioning occurred.

## Tested environment

| Item | Observed version/configuration |
| --- | --- |
| Host | Windows 11, PowerShell, WSL2, 16 logical CPUs, approximately 24 GiB RAM |
| Docker | Desktop 4.71.0; Engine 29.4.1; Linux/amd64; approximately 11.5 GiB engine memory |
| Compose | 5.1.3 |
| Host Python | 3.12.10, isolated virtual environment in local AppData |
| Container Python | 3.12.13 slim-bookworm |
| PostgreSQL | 17.9-alpine |
| Floci | 2.0.1 |
| API | FastAPI 0.141.1, SQLAlchemy 2.0.52, Alembic 1.19.2, psycopg 3.3.5 |
| AWS SDK | boto3/botocore 1.43.91, explicit dummy credentials and local endpoints |
| Tests | pytest 9.1.1, httpx 0.28.1, ruff 0.16.6 |

Tooling for later milestones (kind, Helm, Terraform and AWS CLI) was absent at inspection and was not installed. kubectl was available but no cluster/context was changed.

## Acceptance evidence

| Check | Observed result |
| --- | --- |
| Documented one-command startup | `scripts/dev.ps1 up` built the image, initialized PostgreSQL, completed the migration with exit 0 and returned healthy API/Floci |
| Fresh source and fresh storage | Copied candidate Git files into a new local source snapshot with no runtime files; initialized an empty local Git directory; started project `previewforge-m1-acceptance-20260909` with newly created volumes and password |
| Initial data | Fresh API returned exactly `[]`; running the documented seed command twice produced exactly three tasks |
| Task CRUD | Documented PowerShell example and real HTTP acceptance script created, listed and updated tasks against PostgreSQL |
| Input/error handling | Invalid titles/status/IDs/pagination rejected; missing task returned 404; database errors returned sanitized 503 |
| Unit and PostgreSQL integration tests | **23 passed, 2 upstream deprecation warnings, 0 failures, 0 skips, in 0.58 seconds** in the final full verification command; 17 unit cases and 6 PostgreSQL integration tests |
| Migrations | Upgrade, repeated upgrade, schema/model comparison, downgrade and fresh upgrade passed on isolated test PostgreSQL |
| Lint and formatting | ruff check/format checks passed; the host-side HTTP script was also checked |
| Health/version/metrics | HTTP 200 for live/ready/version/metrics/docs/OpenAPI; version was `local-uncommitted` / `local`; request/error counters and latency histogram present |
| API replacement | Container ID changed after forced recreation; the created task retained its `done` status |
| Database outage and recovery | With only this project's PostgreSQL stopped, live/version/metrics stayed 200; ready/tasks returned 503; database restart restored readiness and the task |
| Full shutdown/start persistence | In the clean-source project, documented `down` then `up` retained all four rows (three seeds and one newly created task) |
| Logs and process identity | JSON request events included request IDs and 503 readiness events; raw path/query canaries were absent; API ran as UID 10001 |
| Host Floci SDK | Windows Python S3/SQS smoke passed at `http://127.0.0.1:4566` |
| Application-container Floci SDK | Smoke passed inside the real API container at `http://floci:4566`, using returned/validated queue identities |
| Smoke cleanup | Each successful run confirmed deletion; final independent inventory found **0 smoke buckets and 0 smoke queues** |
| Scope of local exposure | API bound `127.0.0.1:8000`; Floci bound `127.0.0.1:4566`; PostgreSQL had no published host port |
| Credentials | Generated DB password absent from all 34 candidate Git files checked; private env/runtime patterns ignored; ambient AWS profile/credential/endpoint canaries ignored by SDK unit test |

The clean source snapshot exercised startup portability and new storage, using already downloaded images/package caches. It was not a remote-clone test: the remote was empty because committing/pushing had not been performed. Its startup and shutdown checks passed at `2026-09-09T22:41:54+01:00`; its task ID was `a876e646-f953-4ecd-baa5-393f0b7d3570`. The temporary acceptance containers, network and both data volumes were removed afterward, using exact project ownership labels.

Final full-command evidence:

```text
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 verify
23 passed, 2 warnings in 0.58s
Host smoke:      pf-smoke-1ee413b807114dd483377d2afe0df0d7 — passed, cleanup verified
Container smoke: pf-smoke-e18ff9b132934ea3acdf090b1e6771aa — passed, cleanup verified
HTTP/container acceptance task: 91924e11-3d76-4572-bc8f-a338f809a27f
HTTP CRUD, validation, docs, health, version and metrics: PASS
API container replacement / task persistence: PASS
Database outage / recovery / task persistence: PASS
Structured/sanitized request logs and non-root process: PASS
Command exit: 0
```

The local API container's final image identifier was `sha256:aa859635a5951c0d152ec08ccc4ca96b27d423b3ac61911e9a5885d538a1ceb5`. This is a locally built image identifier, not a published GHCR reference or source commit.

## Exact emulated operations exercised

- S3: create bucket, apply ownership tags, put/get/list object with byte-for-byte content comparison, delete object, delete bucket, confirm bucket absence with a 404 response.
- SQS: create tagged queue, retrieve/validate queue URL, send/receive message, verify visibility hiding, reset visibility to exercise redelivery, verify the same message ID, delete the message, verify no message remains, delete queue and confirm absence by name.
- Failure cleanup unit test: a failed S3 upload still deletes the uniquely owned bucket.

These results establish the tested Floci subset, not real AWS behavior, IAM enforcement, tenant security or cloud performance.

## Issues found and addressed

1. The first image build hit pip's short network read timeout while downloading botocore. A 120-second socket timeout and BuildKit package cache allowed the retry to finish. Cold builds still depend on network availability; these downloads were unusually slow.
2. An empty botocore profile name caused `ProfileNotFound`. The SDK factory now disables the profile lookup chain and uses null config/credential files plus explicit dummy credentials. Host/container smoke tests and the unit test with unrelated ambient profile/configuration canaries passed after the fix.
3. A preliminary manual fresh-database assertion wrapped PowerShell's returned empty array in another array and miscounted it. Checking the direct response confirmed `[]`; the corrected acceptance procedure passed. No application change was needed for that assertion.

The final suite emits two upstream test-client deprecation warnings concerning httpx and an AnyIO portal alias. They are visible, not suppressed; the pinned combination passes all tests. No performance benchmark or production reliability claim is inferred from the pytest duration or these few local runs.

## Remaining / not tested

- Milestones 2–6 have not started: no kind/Helm/Argo CD deployment, GitHub preview automation, Prometheus/Grafana server, Terraform lifecycle, export worker or AI diagnostic service.
- NVIDIA configuration is placeholder-only. Neither mock-provider behavior nor live inference exists yet; no NVIDIA key or request was used.
- No remote clone containing these new files, image publication, public routing or real AWS access was tested or authorized during this initial run.
- This procedure was verified on Windows/PowerShell with Linux containers, not native Linux/macOS shells. HTTP tests verified the Swagger page and OpenAPI document; browser interaction with Swagger's external CDN assets was not automated.

The main `previewforge-m1` stack remains healthy for review. The migration service is correctly exited with code 0; the disposable test database is removed. Use the [documented commands](../setup.md) to inspect or stop it. Milestone 2 requires the user's review before work begins.

## Optional temporary-file cleanup limitation

Automatic approval review rejected deletion of the temporary acceptance source/runtime files, reporting only `blocked by policy`. A narrower attempt using verified absolute paths was also rejected. No user approval is needed to run the application, and this did not block any Milestone 1 acceptance check.

These local artifacts remain outside Git/OneDrive:

- `%LOCALAPPDATA%\PreviewForge\acceptance\milestone1-20260909\` — temporary source snapshot, no running service.
- `%LOCALAPPDATA%\PreviewForge\runtime\previewforge-m1-acceptance-20260909\` — the temporary project's generated database password file; its database volume has already been removed.
- Local image tag `previewforge-m1-acceptance-20260909-api:local` — the combined optional cleanup command was rejected before it ran.

All temporary acceptance containers, networks and volumes were successfully removed before that optional file-cleanup rejection. All Floci smoke resources were also deleted and their absence verified. The normal `previewforge-m1` runtime/password/volumes are intentionally retained for the running demo.
