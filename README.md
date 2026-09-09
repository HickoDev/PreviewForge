# PreviewForge

**A test environment for every pull request.**

PreviewForge is a local self-service GitOps platform being built one milestone at a time. This checkout is the platform repository, `HickoDev/PreviewForge`. Milestone 1 supplies the real application that later milestones will deploy: a FastAPI task API, PostgreSQL and Floci for simulated S3/SQS.

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

## Implementation and verification checklist

- [x] Milestone 1 implementation: API, migrations, container build, Compose, structured request logs and synthetic seed command.
- [x] Milestone 1 verification: clean startup, PostgreSQL CRUD, 27 passing unit/integration tests and migration lifecycle.
- [x] Milestone 1 verification: health/version/metrics, API replacement persistence and database recovery.
- [x] Milestone 1 verification: pinned Floci S3/SQS smoke tests from host and application container, with cleanup confirmed.
- [ ] Milestone 2: kind, Helm, Argo CD and persistent staging.
- [ ] Milestone 3: GitHub Actions, immutable GHCR images, ApplicationSet, PR previews and cleanup.
- [ ] Milestone 4: Prometheus/Grafana dashboards, alerts and measured recovery.
- [ ] Milestone 5: Terraform-managed Floci resources, local reconciler and asynchronous exports.
- [ ] Milestone 6: evidence-backed NVIDIA-hosted NIM diagnostics, starting with mock mode.

`ai-assistant/.env.example` contains design placeholders only. No AI service/provider has been implemented or called, and no NVIDIA key is needed. Live hosted inference will require separate opt-in and privately configured credentials at Milestone 6.

No Kubernetes cluster, GitHub workflow, published image, real cloud resource or public service is part of Milestone 1. Floci checks prove the listed emulated API operations, not real AWS deployment or tenant security. Milestone 2 starts only after review.
