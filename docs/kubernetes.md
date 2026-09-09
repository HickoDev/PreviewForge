# Milestone 2: local Kubernetes and GitOps

This milestone runs the real task API and PostgreSQL on a single-node kind cluster. Argo CD reads a local Git repository, renders the Helm chart, runs migrations and reconciles persistent staging. It does not yet implement GitHub Actions or PR previews.

## Start on Windows

Prerequisites: Windows x64, Python 3.12, Git, Docker Desktop with Linux containers/WSL2, internet for first downloads, and GitHub CLI authenticated with **HickoDev** for pinned upstream downloads. The bootstrap verifies that account before each GitHub operation. It never switches accounts. Allow approximately 4 GiB of spare Docker memory plus disk space for the node and application images.

From the platform repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\platform.ps1 up
```

The command installs checksum-verified kind, Helm and kubectl into `%LOCALAPPDATA%\PreviewForge\tools\milestone2\`. It does not change your PATH. It creates `previewforge-m2`, installs pinned Argo CD, builds/loads the initial application image and waits for staging to become `Synced` and `Healthy`. Initial downloads can take several minutes; cached startup is faster.

All private runtime files live under `%LOCALAPPDATA%\PreviewForge\runtime\previewforge-m2\`: a dedicated kubeconfig, database password, local Git fixture and verification output. Every Kubernetes command explicitly selects this kubeconfig and context. Your normal kubeconfig is not modified. Do not delete the runtime password while keeping the database.

Open a terminal for forwarding:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\platform.ps1 forward
```

Then visit [staging Swagger](http://127.0.0.1:18000/docs), [readiness](http://127.0.0.1:18000/health/ready), [version](http://127.0.0.1:18000/version) and [metrics](http://127.0.0.1:18000/metrics). Ctrl+C closes the forward; staging continues running. Port 18000 binds only to loopback. All application/database Services are ClusterIP; there is no Ingress or public load balancer.

Milestone 1 Compose can remain running on loopback ports 8000/4566. Its PostgreSQL is separate from staging. Compose continues to own the sole Floci instance; Milestone 2 does not start another emulator. Kubernetes-to-Floci SDK wiring remains for the AWS integration milestone.

## Verify the working system

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\platform.ps1 verify
```

This includes `up`, refreshes the managed application/chart inputs and staging defaults from the current checkout into the local Git fixture, builds that baseline, and then tests the actual cluster. Previous committed fixture revisions remain in local Git history. Uncommitted or ignored files in the fixture cause verification to stop before changing it; keep private files outside that directory.

1. Eight offline guard/fixture regressions, Helm lint, Kubernetes server validation and rejection of a mutable application image reference.
2. HTTP task create/update, docs, readiness, metrics and exact source/image identity.
3. A new source commit in the local fixture, a locally built image, and a separate deployment-config commit. Argo CD must poll Git and roll out that new digest without a `kubectl apply` to the application workloads.
4. Manual replica drift that Argo CD must restore to the Git value.
5. An unavailable image that blocks the migration while the prior API stays healthy, followed by a recovery commit in Git.
6. A temporary PostgreSQL outage: API readiness/tasks return 503, liveness remains 200, and Kubernetes removes the API from ready Service endpoints. Restoring PostgreSQL must reuse its PVC and retain the task.
7. Structured failure logs, metrics and absence of the generated database password in API logs.

The verifier uses loopback port 18001 and closes its own forwards. It leaves one synthetic task and a healthy second release. Exact local source/config commits, digests, UTC timestamps and timings are saved in `verification.json` under the runtime directory. These are local fixture commits, not GitHub PR or main-branch deployments. Build/load time is measured separately from Git reconciliation.

The outage test temporarily pauses staging's automated synchronization so self-heal does not immediately undo the intended database fault. A `finally` block restores the original automation setting and database replica count. Keep the terminal open during verification. After a forced termination, run `up`; the Application manifest restores automated reconciliation. Python `-O`/`PYTHONOPTIMIZE` are rejected.

An application's `Healthy` status can describe the still-working API while a sync hook is blocked. Verification also requires the synchronization operation to have succeeded and no pending operation. Bounded retries have `refresh: true`, so recovery can pick up a newer Git revision after the failed migration's deadline instead of retrying the obsolete image.

## See what Kubernetes and Argo CD are doing

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\platform.ps1 status

$pfRuntime = Join-Path $env:LOCALAPPDATA 'PreviewForge\runtime\previewforge-m2'
$pfKubectl = Join-Path $env:LOCALAPPDATA 'PreviewForge\tools\milestone2\kubectl.exe'
& $pfKubectl --kubeconfig "$pfRuntime\kubeconfig" --context kind-previewforge-m2 -n staging get pods,svc,pvc,jobs
& $pfKubectl --kubeconfig "$pfRuntime\kubeconfig" --context kind-previewforge-m2 -n staging get events --sort-by=.lastTimestamp
& $pfKubectl --kubeconfig "$pfRuntime\kubeconfig" --context kind-previewforge-m2 -n staging logs deployment/demo-api --tail=30
& $pfKubectl --kubeconfig "$pfRuntime\kubeconfig" --context kind-previewforge-m2 -n staging logs job/demo-migrate
& $pfKubectl --kubeconfig "$pfRuntime\kubeconfig" --context kind-previewforge-m2 -n argocd get application staging
```

`/health/live` asks whether the API process is alive. `/health/ready` additionally checks the database and schema. A database outage should remove the pod from traffic, not repeatedly restart a healthy API process. Kubernetes pod conditions, events, Argo status, request logs and `/metrics` provide this milestone's visibility. Prometheus/Grafana dashboards remain Milestone 4.

## Where desired state lives

The platform's reusable chart is `charts/demo-app/`. `gitops/staging/values.yaml` holds non-secret staging defaults. `gitops/platform/staging.yaml` defines the restricted Argo project and Application.

On the first startup, bootstrap copies an explicit allowlist of application build inputs, the chart and staging defaults into the runtime `source/` Git repository. It records the platform checkout HEAD and dirty status in `fixture-origin.json`, commits that snapshot locally, then bakes that source commit into the application image. It loads the image directly into kind and records the imported **manifest digest**, not the Docker configuration ID, in `gitops/staging/image.json` in the fixture.

A second local commit records that image choice. A read-only Git daemon serves a bare copy of this repository on the Docker `kind` network, with no host port. It uses the pinned Argo CD image's Git executable; the repository mount is read-only and receive-pack (push) is disabled. A Kubernetes Service/EndpointSlice maps its discovered container IP; no changing Docker IP is hardcoded. Argo CD polls every 15 seconds. No GitHub token is placed in the cluster. The unauthenticated `git://` transport is intended only for this trusted local network.

Ordinary `up` preserves the last desired fixture release and database. It does not overwrite the fixture with edits from the platform checkout. To try a deployment configuration change, edit `source/gitops/staging/values.yaml` in the runtime directory, commit it locally, then publish it to the local bare repository:

```powershell
$pfSource = Join-Path $env:LOCALAPPDATA 'PreviewForge\runtime\previewforge-m2\source'
# Example: edit replicas in $pfSource\gitops\staging\values.yaml first.
git -C $pfSource add gitops/staging/values.yaml
git -C $pfSource -c user.name='PreviewForge local fixture' -c user.email=fixture@previewforge.invalid commit -m 'Change local staging configuration'
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\platform.ps1 publish-local
```

`publish-local` copies Git refs between two filesystem directories. It does not push to GitHub or rebuild the application. `verify` refreshes the managed fixture inputs from this checkout and creates a second source/image revision. Fixture commits include only the files belonging to that operation, and builds require a clean fixture at the declared source SHA. Later GitHub integration will replace this local transport with the approved remote workflow.

## Storage and ownership

- Bootstrap owns the dedicated cluster, Argo CD installation, staging namespace, retention StorageClass, database Secret and local Git transport.
- Argo CD owns the chart's API, database StatefulSet, Services, migration Job, quota and PVC declaration. Helm renders templates; bootstrap never performs a competing `helm install` of the demo app.
- PostgreSQL and its PVC share a sync wave because local storage uses `WaitForFirstConsumer`. The migration job runs after database readiness and before the API rollout. Its two-minute deadline bounds a failed migration; the most recent job stays available for inspection.
- Staging PVC annotations disable Argo pruning/deletion, and the PV reclaim policy is `Retain`. Deleting the Argo Application does not cascade into staging workloads. This is deliberate persistent staging behavior; disposable preview cleanup has different requirements and is not implemented yet.
- API/migrations run as UID 10001 with read-only root filesystems, dropped capabilities and no mounted Kubernetes service-account token. PostgreSQL runs as its image's UID 70. Resources and namespace quotas bound this small demo.
- The default kind CNI is used. Namespace separation is not a verified tenant security boundary; no NetworkPolicy isolation is claimed.

To stop only this milestone while retaining its node, volumes and Git fixture:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\platform.ps1 stop
# Later:
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\platform.ps1 up
```

There is intentionally no destructive cluster-delete shortcut. If a retained fixture exists but its node is missing, startup refuses to create a replacement silently. A `Retain` policy does not protect data from deleting the kind node/container: the volume's bytes still live inside that node. Use PostgreSQL backups before intentionally rebuilding/removing the cluster. This milestone verifies pod replacement and stop/start persistence, not disaster recovery or high availability.

## Pinned dependencies and sources

`bootstrap/tools.lock.json` contains tool/archive checksums and the Argo manifest revision/hash. `bootstrap/kind/cluster.yaml` pins the kind node digest. The application base image and PostgreSQL retain Milestone 1's digest pins. Update pins intentionally and repeat live verification.

- [kind quick start and image loading](https://kind.sigs.k8s.io/docs/user/quick-start/)
- [Argo CD installation](https://argo-cd.readthedocs.io/en/stable/operator-manual/installation/)
- [Argo CD sync waves](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-waves/)
- [Argo CD automated synchronization and self-heal](https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/)
- [Kubernetes persistent volume retention](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)

Troubleshooting: use `status` and the inspection commands above. `ErrImageNeverPull` means a referenced digest has not been loaded into this node; a mutable tag or a Docker image ID is not a substitute. A blocked migration prevents the new API release. A download/checksum failure stops bootstrap without accepting an unverified tool. Re-run `up` after fixing connectivity. If runtime secrets are missing while a PVC exists, restore the original password rather than generating a replacement for an initialized database.
