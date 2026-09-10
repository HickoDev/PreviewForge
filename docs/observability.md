# Monitoring and recovery

Milestone 4 uses Prometheus 3.14.0, Grafana 13.2.1 and kube-state-metrics 2.20.0, pinned to registry digests in `observability/values.yaml`. A small Helm chart keeps the installed components and permissions visible. Argo CD owns the monitoring workloads/configuration; local bootstrap owns the namespace and generated Grafana credential.

## Start on the configured Windows laptop

Start Docker Desktop, then run from PreviewForge:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\platform.ps1 start
python scripts/monitoring.py up
python scripts/monitoring.py forward --service grafana
```

Open **http://127.0.0.1:13000/d/previewforge**. Choose staging or a running preview in the Environment selector. The dashboard is provisioned from Git and available to local viewers without entering an administrator password. Its panels show request rate, histogram p95 latency, server error ratio, source SHA, API/database ready replicas, Argo synchronization and firing alerts. An idle environment can have no latency/error ratio; that is not proof of health. Version and workload panels work without generated traffic.

In another terminal, open Prometheus:

```powershell
python scripts/monitoring.py forward --service prometheus
```

Use **http://127.0.0.1:19090/alerts** for pending/firing rules, or `/targets` for scrape health. Ctrl+C stops each forward. All Services are ClusterIP; these commands bind only to loopback. No email/chat receiver or public tunnel is configured. Stop/start of the retained kind node resumes monitoring; no reinstall is required.

Keep `python scripts/previews.py watch --github --apply` running for ordinary real PR lifecycle operations. Stop that watcher before running a monitoring exercise: both use the same local operation lock.

## Repeatable exercises

These commands deliberately change staging configuration in **real GitHub commits**, pause its database temporarily, and create/delete owned local preview fixtures. Use them when staging is available for a synthetic failure demonstration and no new application build is being delivered:

```powershell
python scripts/monitoring.py check
python scripts/monitoring.py verify --allow-faults --allow-github-writes --trials 2
```

The exercise publishes an unavailable image digest in staging's Git record, waits for image-pull and Git synchronization alerts, then commits the saved known-good image and waits for Argo recovery. It never force-pushes. The migration hook blocks the bad image before it replaces the working API; this is explicit Git recovery, not automatic Deployment rollback.

It also pauses automated sync, scales only staging's PostgreSQL to zero, generates task traffic with six bounded clients, and observes database/API availability and server-error alerts. Concurrent clients keep completed traffic above the alert's one-request-per-second floor while database connections time out. A `finally` block restores the database and its original Argo policy. Liveness, saved tasks and PVC identity are checked. A short-lived local Argo preview fixture uses the already-published main image, enables `/test/failure`, and tests per-environment alerts and complete cleanup. This fixture is explicitly synthetic and does not open a GitHub PR; real PR delivery remains covered by Milestone 3.

`/test/failure` returns 404 and is hidden from Swagger by default. `failureExercise.enabled=true` enables its deliberate 503 response; request inputs cannot enable it. Regular health/task endpoints are unchanged.

If the process is forcibly interrupted, restore from its non-secret journal:

```powershell
python scripts/monitoring.py recover --allow-faults --allow-github-writes
```

The journal and raw results are under `%LOCALAPPDATA%\PreviewForge\runtime\previewforge-m2\`. Recovery refuses to overwrite an unexpected newer staging image or delete an unmarked preview. Inspect such a conflict before retrying. Do not run Git/DB fault exercises concurrently with an application release.

## Data and permission boundaries

Prometheus discovers labeled API pods and scrapes their pod addresses even when readiness fails. This keeps database-outage errors visible. Health/metrics requests are excluded from business request rates. The error alert requires at least one business request per second and a sustained server-error ratio above 5%; separate workload and telemetry alerts cover missing traffic/metrics.

Workload collectors may list/watch pods, Deployments and StatefulSets on this dedicated kind cluster; they cannot read Secrets, logs or execute commands. Only staging/preview numeric series are retained from those collectors. Grafana has no Kubernetes service-account token, outbound analytics/update checks are disabled, and its random administrator password is generated directly into an owned Kubernetes Secret.

Prometheus uses a separate 2 GiB PVC with Retain policy, 24-hour time retention and a 1 GB TSDB size limit. It preserves history across pod/node restarts; deleted previews can remain in historical queries until retention expires. Grafana's editable state is disposable because dashboards/datasources are provisioned from Git. Each component restarts only for changes to its own configuration. Prometheus stores metrics, not logs. Namespace network isolation, Alertmanager notification delivery, canary automation and production capacity sizing are outside this milestone.

Sources checked during implementation: [Prometheus Kubernetes discovery/configuration](https://prometheus.io/docs/prometheus/latest/configuration/configuration/), [alert rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/), [Grafana provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/), [anonymous Viewer access](https://grafana.com/docs/grafana/latest/setup-grafana/configure-access/configure-authentication/anonymous-auth/), [workload metrics](https://github.com/kubernetes/kube-state-metrics), and [Argo CD metrics](https://argo-cd.readthedocs.io/en/stable/operator-manual/metrics/).

Live verification is in progress; the results report will distinguish completed checks from limitations.
