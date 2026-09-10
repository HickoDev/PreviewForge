# PreviewForge

**A test environment for every pull request.**

PreviewForge is a local self-service GitOps platform being built one milestone at a time. This checkout is the platform repository, `HickoDev/PreviewForge`. Milestone 1 supplies a FastAPI task API, PostgreSQL and Floci for simulated S3/SQS. Milestone 2 adds kind, Helm and Argo CD for persistent local staging.

The demo application lives in `previewforge-demo/` with its own dependencies, tests, migrations and Dockerfile. Keeping it here initially makes a single checkout runnable. It remains a separate logical component; a second remote repository requires discussion before GitHub automation is introduced.

## Run on Windows

Prerequisites: Windows PowerShell 5.1+, Git, and running Docker Desktop with Linux containers/WSL2 and Docker Compose v2.20+ (v5 works). Python **3.12** is additionally needed for the full verification command. First builds need internet access for the pinned public images and packages.

From this repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 up
```

Open [API documentation](http://127.0.0.1:8000/docs), [readiness](http://127.0.0.1:8000/health/ready), [version](http://127.0.0.1:8000/version) or [metrics](http://127.0.0.1:8000/metrics). Only loopback ports 8000 and 4566 are published; PostgreSQL has no host port.

```powershell
# Generate three synthetic example tasks (safe to repeat).
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 seed

# Lint, unit tests and isolated PostgreSQL integration tests.
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 test

# Full acceptance: tests, host/container Floci, HTTP, persistence and DB outage/recovery.
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 verify

# Stop this project's containers; retain its PostgreSQL and Floci volumes.
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 down
```

The wrapper generates a database password under `%LOCALAPPDATA%\PreviewForge\runtime\previewforge-m1\`, outside Git and OneDrive, and mounts it using Compose secrets. It does not read your AWS profiles. Both Floci smoke clients explicitly use `test` credentials, `us-east-1` and an approved local endpoint.

See [setup and API examples](docs/setup.md), [architecture and decisions](docs/architecture.md) and [Milestone 1 review and verification results](docs/results/milestone-1-review.md).

## Local Kubernetes staging

With Python 3.12, Docker Desktop and Git available, run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\platform.ps1 up
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\platform.ps1 forward
```

Open [staging API documentation](http://127.0.0.1:18000/docs). The first command installs pinned tools locally and waits for Argo CD to synchronize staging. The second keeps a loopback port-forward open; Ctrl+C closes it. GitHub downloads use `gh` only after verifying the active account is HickoDev. The separate kubeconfig and database password stay outside Git/OneDrive.

```powershell
# Real local Git commits, immutable image rollout, drift repair and failure recovery.
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\platform.ps1 verify

# Inspect, or stop while retaining the cluster and its data.
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\platform.ps1 status
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\platform.ps1 stop
```

See [Kubernetes setup, ownership and demo instructions](docs/kubernetes.md) and [Milestone 2 review and results](docs/results/milestone-2-review.md). This uses a read-only local Git fixture and locally loaded application images. GitHub PR delivery and image publication remain later work. The Milestone 1 Compose stack can run alongside staging and continues to own Floci.

## Implementation and verification checklist

Milestone 3 adds local ApplicationSet previews and GitHub automation. See [preview operation and remote activation](docs/previews.md) and [local acceptance results](docs/results/milestone-3.md). The owner has approved remote activation; real GitHub/GHCR integration verification is in progress.

```powershell
python scripts/previews.py verify
python scripts/previews.py demo --pr 42
python scripts/previews.py forward --pr 42 --port 18042
# After closing the forward:
python scripts/previews.py close --pr 42
```

- [x] Milestone 1 implementation: API, migrations, container build, Compose, structured request logs and synthetic seed command.
- [x] Milestone 1 verification: clean startup, PostgreSQL CRUD, 27 passing unit/integration tests and migration lifecycle.
- [x] Milestone 1 verification: health/version/metrics, API replacement persistence and database recovery.
- [x] Milestone 1 verification: pinned Floci S3/SQS smoke tests from host and application container, with cleanup confirmed.
- [x] Milestone 2 implementation: kind, Helm, Argo CD and persistent staging with a private local Git fixture.
- [x] Milestone 2 verification: exact image/source rollout from a config commit, drift repair, failure visibility and completed Git recovery.
- [x] Milestone 2 verification: eight offline guard/fixture tests, database/PVC persistence and documented cluster stop/start.
- [x] Milestone 3 implementation: ApplicationSet, validated build records, per-preview databases and owned cleanup/reconciliation.
- [x] Milestone 3 local verification: two previews, isolated data, individual updates, stale/failed-build rejection, main-source staging and complete cleanup.
- [x] Milestone 3 preparation: read-only CI, guarded GHCR delivery, conflict-aware config writes, close/scheduled reconciliation.
- [ ] Milestone 3 remote acceptance: approved workflow/image publication, private Git/GHCR access and two real GitHub PRs.
- [ ] Milestone 4: Prometheus/Grafana dashboards, alerts and measured recovery.
- [ ] Milestone 5: Terraform-managed Floci resources, local reconciler and asynchronous exports.
- [ ] Milestone 6: evidence-backed NVIDIA-hosted NIM diagnostics, starting with mock mode.

`ai-assistant/.env.example` contains design placeholders only. No AI service/provider has been implemented or called, and no NVIDIA key is needed. Live hosted inference will require separate opt-in and privately configured credentials at Milestone 6.

GitHub/GHCR activation is authorized and being verified. The repository and application images must stay private; local services remain bound to loopback. No real cloud resources are provisioned. Floci checks prove the listed emulated API operations, not real AWS deployment or tenant security. Kubernetes namespace/storage separation is not a claim of enforced network isolation.
