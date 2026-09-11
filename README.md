# PreviewForge

**A test environment for every pull request.**

PreviewForge is a local GitOps platform that turns a trusted application pull request into a running Kubernetes environment. GitHub Actions tests and builds the application, GHCR stores its image, and Argo CD deploys it into kind. Each preview gets its own PostgreSQL database and Terraform-managed Floci S3 bucket and SQS queue. Prometheus and Grafana show its health; a separate read-only assistant offers evidence-backed diagnostics using mock mode or opt-in NVIDIA-hosted inference.

Built across six milestones, it demonstrates real GitHub delivery with local infrastructure. It is a portfolio and learning project: AWS is simulated, application data is synthetic, and services are accessed through localhost forwards. The demo is an interactive task API, without a frontend or login system. The [verification checklist](#implementation-and-verification-checklist) distinguishes completed tests from the remaining AI quality evaluation.

[Documentation index](docs/README.md) · [Architecture diagram and design](docs/architecture.md) · [Testing guide](docs/testing.md) · [Public release review](docs/results/public-release-review.md)

The demo application lives in `previewforge-demo/` with its own dependencies, tests, migrations and Dockerfile. Keeping it here makes a single checkout runnable. GitHub automation uses this one platform repository, `HickoDev/PreviewForge`.

The Compose demo below runs independently. Full platform automation is intentionally bound to **HickoDev/PreviewForge** and the **HickoDev** account. A fork does not automatically deploy or receive credentials; adapting the owner/repository checks requires a separate configuration review. The current delivery policy accepts only the owner's same-repository application PRs.

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

## Local Kubernetes staging (initial local mode)

This section is for the local Git fixture. If GitHub/GHCR delivery is already configured, use [Real PR environments](#real-pr-environments) below; local bootstrap refuses to replace that installation's Git source.

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

See [Kubernetes setup, ownership and demo instructions](docs/kubernetes.md) and [Milestone 2 review and results](docs/results/milestone-2-review.md). This uses a read-only local Git fixture and locally loaded application images. For the configured GitHub/GHCR mode, use the resume commands below instead of local `up` or `verify`. The Milestone 1 Compose stack can run alongside staging and continues to own Floci.

## Real PR environments

Milestone 3 connects real GitHub PRs and private GHCR images to local Argo CD previews. See [GitHub-mode startup and recovery](docs/remote.md), [local simulation](docs/previews.md), and [acceptance results](docs/results/milestone-3.md).

On the configured laptop, with Docker Desktop running:

```powershell
python scripts/resources.py up --github
python scripts/previews.py watch --github --apply
```

Keep that terminal running. In another terminal:

```powershell
python scripts/previews.py status --github
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\platform.ps1 forward
```

Open `http://127.0.0.1:18000/docs` for staging. Forward an active PR with `python scripts/previews.py forward --github --pr 123 --port 18042`, replacing `123` with its PR number. The two acceptance PRs are closed after verification.

## Monitoring

With the configured cluster running, open the environment dashboard. Stop the preview watcher with Ctrl+C before `monitoring.py up`, because both commands use the same operation lock. Restart the watcher in its own terminal after setup:

```powershell
python scripts/monitoring.py up
python scripts/monitoring.py forward --service grafana
```

Use **http://127.0.0.1:13000/d/previewforge** and select staging or a running preview. In another terminal, `python scripts/monitoring.py forward --service prometheus` opens **http://127.0.0.1:19090/alerts**. Both forwards bind only to this computer. See [startup, alerts and controlled recovery exercises](docs/observability.md) and [Milestone 4 results](docs/results/milestone-4.md).

## Task exports

Staging and each preview have a separate Terraform-managed Floci bucket and queue. In the API documentation, run `POST /exports`, check `GET /exports/{id}`, then download the completed report from `GET /exports/{id}/download`. A worker saves a snapshot of that environment's tasks as JSON. Accepted jobs survive queue outages and worker retries through a PostgreSQL outbox.

Use `python scripts/resources.py status --github` to inspect resource reconciliation. To see the current Terraform plan, stop the watcher, run `python scripts/resources.py plan --github --environment staging`, then restart the watcher. State stays outside Git and OneDrive. Closing a PR removes its workloads before cleaning up its emulated AWS resources.

See [startup, report commands and recovery](docs/resources.md) and [Milestone 5 acceptance results](docs/results/milestone-5.md).

## Deployment diagnostics

Milestone 6 adds a separate, read-only diagnostic API. It collects bounded evidence from approved environments, correlates the deployed image and configuration, and returns cited facts, hypotheses or an explicit abstention. Mock mode works without a key:

```powershell
python scripts/assistant.py up
python scripts/assistant.py diagnose --fixture wrong-port
python scripts/assistant.py diagnose --environment staging
python scripts/assistant.py forward
```

The final command opens **http://127.0.0.1:18080/docs**. See [startup and private NVIDIA key setup](docs/assistant.md) and [Milestone 6 results](docs/results/milestone-6.md). Hosted inference remains opt-in. A [live NVIDIA smoke test](docs/results/milestone-6-live.md) passed with Nemotron 3 Super; the full hosted evaluation and human model-quality review remain pending.

## Implementation and verification checklist

Test counts below describe the recorded milestone runs, not the current size of each suite. See the [testing guide](docs/testing.md) for current commands and the linked reports for dated evidence.

- [x] Milestone 1 implementation: API, migrations, container build, Compose, structured request logs and synthetic seed command.
- [x] Milestone 1 verification: clean startup, task creation/listing/status updates in PostgreSQL, 27 passing unit/integration tests and migration lifecycle.
- [x] Milestone 1 verification: health/version/metrics, API replacement persistence and database recovery.
- [x] Milestone 1 verification: pinned Floci S3/SQS smoke tests from host and application container, with cleanup confirmed.
- [x] Milestone 2 implementation: kind, Helm, Argo CD and persistent staging with a private local Git fixture.
- [x] Milestone 2 verification: exact image/source rollout from a config commit, drift repair, failure visibility and completed Git recovery.
- [x] Milestone 2 verification: eight offline guard/fixture tests, database/PVC persistence and documented cluster stop/start.
- [x] Milestone 3 implementation: ApplicationSet, validated build records, per-preview databases and owned cleanup/reconciliation.
- [x] Milestone 3 local verification: two previews, isolated data, individual updates, stale/failed-build rejection, main-source staging and complete cleanup.
- [x] Milestone 3 automation: read-only CI, guarded GHCR delivery, conflict-aware config writes, close/scheduled reconciliation.
- [x] Milestone 3 remote acceptance: two real PRs, private Git/GHCR delivery, failed/stale/closed-build rejection, missed-event cleanup and merge-to-staging delivery.
- [x] Milestone 4 implementation: Prometheus/Grafana, automatic workload discovery, eight dashboard panels and seven alert rules.
- [x] Milestone 4 verification: two live fault/recovery/preview-cleanup trials, retained metric history and data across restart, and working terminal startup/stop commands.
- [x] Milestone 5: Terraform-managed Floci resources, local reconciler and asynchronous exports.
- [x] Milestone 5 verification: real PR exports/update/cleanup, process-crash redelivery, resource reset, interrupted reconciliation, state recovery and documented startup.
- [x] Milestone 6 implementation: separate diagnostic API, scoped collectors, filtered evidence, citation/schema validation, mock provider and bounded NVIDIA HTTP adapter.
- [x] Milestone 6 mock verification: offline tests, labeled evaluation, actual GitOps wrong-port diagnosis, read-only RBAC, Git recovery and owned cleanup.
- [x] Milestone 6 live connection: private NVIDIA key setup and a passing hosted Nemotron 3 Super smoke test.
- [ ] Milestone 6 model-quality acceptance: full hosted evaluation and human semantic review.

Mock inference makes no hosted calls. NVIDIA credentials belong only to the trusted assistant namespace; use the hidden local setup prompt after reviewing Milestone 6. The model cannot execute commands or change deployments.

GitHub/GHCR delivery is enabled with the owner's approval. Source repository visibility is independent of the GHCR package: delivery supports private or public source while requiring a verified private registry package. In a public repository, Actions logs and downloadable build artifacts are public project material too; images and logs must contain no credentials. See the [publication checklist](docs/public-release.md) before changing visibility. Local services remain bound to loopback. No real cloud resources are provisioned. Floci checks prove the listed emulated API operations, not real AWS deployment or tenant security. Kubernetes namespace/storage separation is not a claim of enforced network isolation.
