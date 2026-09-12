# Windows/Linux portability verification

Verified September 12, 2026 in Tunis (the recorded UTC timestamps fall on September 11). Tests used the uncommitted portability changes over platform commit `ca4a38d4db5bb358a4237018569e3823bba625dd`. The [sanitized evidence](portability-verification.json) records the lifecycle, runtime and restart outcomes.

## What changed

The operational guides now use common Python entry points. Windows PowerShell wrappers delegate to those implementations. The shared host adapter selects native executables, virtual-environment paths, private runtime locations, process flags and operating-system locks. Linux tool archives have checksum pins; Windows keeps its existing installation paths.

Live testing found and fixed a Linux launcher problem: resolving a virtual environment's Python symlink can produce the system interpreter path. Resource startup now checks the active virtual environment through `sys.prefix`, so Terraform's Python dependencies load correctly. The Compose password file also needs to be readable by its container users while its parent runtime directory remains private.

The installation guide distinguishes supported hosts, standalone Compose, synthetic local GitOps and owner-operated GitHub delivery. Bash HTTP/inspection examples accompany the PowerShell examples. The native draw.io diagram and its exports now describe Windows/Linux hosts. Historical milestone reports retain their original test context.

## Test environments

- **Windows:** Windows 11 x64, Python 3.12.10, Docker Desktop using Linux containers; Docker Engine 29.4.1 and Compose 5.1.3.
- **Linux:** Debian 12 x64 control container, Python 3.12.13, Docker Engine 29.4.1 and Compose 5.1.3, with a dedicated nested Docker daemon. The test used separate Docker volumes, filesystem paths, Git fixture, Kubernetes cluster and Terraform state. No ports were published by the outer test containers.
- Linux remote-mode checks consumed the existing owner repository and published images. Existing read-only Git/GHCR credentials were copied privately into the disposable installation; GitHub CLI access was verified as HickoDev. No NVIDIA key was copied.

The Linux daemon and command container shared the workspace, runtime and temporary bind-mount paths. An initial lifecycle attempt failed because their default `/tmp` directories differed. Setting `TMPDIR` to their shared test directory corrected the harness; the full lifecycle rerun passed. Native installations with the CLI and daemon on the same host do not need that harness adjustment. Existing node-image layers were reused, so this was not a cold-download benchmark.

## Results

| Check | Result |
| --- | --- |
| Host regressions | Windows: 72 passed, one POSIX-only test skipped. Linux: all 73 passed, including real process-lock contention/release and private directory permissions. |
| Compose on both hosts | 41 application tests passed; five export integration tests intentionally skipped by the baseline configuration. Actual HTTP, host/container Floci, API replacement persistence and database outage/recovery passed. |
| Complete application suite on Linux | All 46 tests passed, including the Floci export cases, during preview verification. |
| Linux kind / Helm / kubectl / Argo | Pinned native tools installed; real kind node, local Git transport and staging became healthy. |
| Two synthetic Linux previews | Creation, database/PV separation, independent update, stale/failed build rejection, close cleanup, simulated main deployment and missed-close reconciliation all passed. Both synthetic previews were removed. |
| Linux Terraform / private images | Native Terraform startup and venv re-execution passed. Staging and existing PR records 11/12 each received separate buckets/queues and database PVCs; private GHCR images ran successfully. Each API completed and downloaded its own task export. |
| Monitoring on Linux | Chart/configuration checks and seven alert rules passed. Six Prometheus targets were up, including all three application environments. Grafana health and the provisioned dashboard API passed. |
| Assistant on Linux | All 70 offline tests passed. Mock startup, fixture diagnosis, live Kubernetes evidence collection and all 13 mock evaluation cases passed; all references were valid. The ServiceAccount could not read staging Secrets. Hosted inference attempts: zero. |
| Linux retained-service restart | The documented resource startup command restored the stopped kind node and Floci. Tasks, saved report bytes/completion time, staging PVC, Prometheus PVC and container identities were preserved. All five Argo applications returned to Synced/Healthy. |
| Existing Windows installation | Native tool selection, PowerShell wrapper status and resource startup passed. The retained staging, two previews, monitoring and assistant remained Synced/Healthy. |
| Documentation / diagrams | Local links, anchors, Python argument syntax and CLI help checked. Six PowerShell and three Bash blocks parsed; curl task/export requests exercised against the Linux API. draw.io Desktop 30.0.0 regenerated exports; SVG/PDF embedded sources match the three-page native file. |
| Static checks | Python lint/format, Actionlint and diff whitespace checks passed. The redacted secret scan found only the existing labeled synthetic evaluation canary. |

The mock evaluation checks deterministic integration and citation handling; it is not evidence of hosted model quality. Restart timing is one local observation, not a performance or availability guarantee.

## Commands

From the repository root, with Python 3.12 and Docker running:

```text
python -m unittest discover -s tests/platform -v
python scripts/dev.py verify
```

For a separate initial local GitOps installation:

```text
python scripts/previews.py verify
```

For an already configured owner GitHub installation, stop the watcher first:

```text
python scripts/resources.py up --github
python scripts/monitoring.py up
python scripts/monitoring.py check
python scripts/assistant.py test
python scripts/assistant.py up
python scripts/assistant.py evaluate
```

The restart exercise briefly stops that installation's kind node and Floci:

```text
python scripts/verify_resources_startup.py --allow-faults
```

Use `python3` on Linux if that selects Python 3.12. Follow the [installation guide](../installation.md) and [testing guide](../testing.md) for prerequisites, modes, ports and side effects. The disposable test harness itself is not a required installation method.

## Scope and cleanup

The new `Host portability` workflow adds Windows/Linux host tests and a Linux Compose/two-preview acceptance job. Actionlint passed and its underlying commands passed locally; the workflow has not yet run on GitHub because these changes were not pushed during this task.

Linux verification used a containerized root process and rootful daemon. A separate Linux desktop, unprivileged host user, macOS, ARM, rootless Docker, remote Docker daemon and Podman were not tested. macOS/ARM are rejected by the host adapter. Fresh credential issuance and full fresh-laptop remote onboarding were not repeated; the remote checks reused existing owner credentials. New GitHub PR delivery/publication, hosted NVIDIA inference and the full remote fault exercises were not rerun for this change.

The two labeled Linux test containers and four labeled test volumes were removed after their ownership labels were checked, including the copied credentials and disposable cluster/state. Sanitized evidence was saved first. The dedicated Windows Compose acceptance project was stopped with its separate data retained. Existing Windows project data and cluster were preserved. No GitHub writes, image publication, public exposure or real cloud provisioning occurred in this portability run.
