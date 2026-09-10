# Milestone 4 review and verification — 2026-09-10

Milestone 4 is implemented and verified on the configured Windows/Python 3.12/Docker Desktop laptop. Prometheus and Grafana run in the existing dedicated kind cluster, deployed by Argo CD from the private platform repository. Staging is restored, all temporary monitoring previews are deleted, and no firing PreviewForge alerts remain after recovery.

The preceding [Milestone 3 review](milestone-3-final-review.md) was committed and pushed as `30dd463`. The monitoring implementation is `cdd6de8`; review fixes are `352cb4d`, `b716768` and `111d775`. The application used for these exercises is source `cdd6de85bc5916123a8007ef59f52b55a9c4afc4`, at private GHCR digest `sha256:19fd6a7d2de28984d0aac1a97b27482e026f5f5c8d3daee1a2e6ebfbffb4cefa`.

## Verified behavior

- Eight provisioned dashboard panels show business request rate, histogram p95 latency, server-error ratio, running source, API/database ready replicas, Argo synchronization and firing alerts. All seven non-alert queries returned live data; the browser rendering was inspected after restart and the display fixes.
- Seven Prometheus alert rules cover failed image pulls, unsynchronized releases, API/database availability, sustained business errors, API scraping and missing workload/deployment telemetry. Alerts are evaluated locally; no notification receiver is configured.
- Two complete trials each committed an unavailable staging image to real GitHub, detected image-pull and synchronization alerts, then committed the known-good image and waited for completed Argo recovery and cleared alerts. The migration hook blocked the bad image while the existing API continued serving the expected source.
- Both database outages produced database/API/error-rate alerts. Readiness returned 503 while liveness remained 200. The API did not restart during either outage; the same three tasks and staging PVC survived recovery, and automated synchronization was restored.
- Two explicitly synthetic local Argo preview fixtures used the already-published private main image. Their error alerts were isolated from staging. Their Applications, namespaces, PVCs and PVs were deleted, and their live API/workload metrics and error alerts disappeared. Historical samples remain subject to retention.
- The documented `platform.ps1 stop`, `platform.ps1 start` and `monitoring.py up` commands completed on the retained cluster. Staging's three tasks, source version and PVC identity were preserved. Prometheus returned the identical historical query result from before restart using the same PVC. Four scrape targets were healthy afterward.
- The documented Grafana, Prometheus and staging forward commands served their local endpoints. Ctrl+C stopped each and released its port. A dashboard-only change preserved the Prometheus pod UID.
- Eight live Kubernetes authorization checks confirmed the collectors could list pods but could not read Secrets, read pod logs or execute commands. A concurrent setup attempt was refused by the exercise lock. Tracked files contained none of the configured registry token, Argo private key or Grafana password values.

Evidence: [raw trial records](milestone-4.json), [startup and persistence record](milestone-4-startup.json), and [dashboard screenshot](milestone-4-dashboard.png). The raw trial file contains source/digest identity, UTC timestamps, fault/recovery commit IDs, traffic status counts and individual durations.

## Measurements

Two complete consecutive trials, on one local laptop with cached images. Times are seconds; these are demonstration observations, not production performance estimates.

| Measurement | n | Trial 1 | Trial 2 | Median | Range |
| --- | ---: | ---: | ---: | ---: | --- |
| Bad-release detection | 2 | 61.235 | 58.218 | 59.727 | 58.218–61.235 |
| Git recovery and alert resolution | 2 | 136.500 | 132.250 | 134.375 | 132.250–136.500 |
| Database-outage detection | 2 | 54.313 | 58.797 | 56.555 | 54.313–58.797 |
| Database recovery and alert resolution | 2 | 60.984 | 61.328 | 61.156 | 60.984–61.328 |
| Preview cleanup and live-metric removal | 2 | 55.828 | 52.578 | 54.203 | 52.578–55.828 |

Release detection starts before writing the bad Git record and ends when the image-pull alert is observed firing; the synchronization alert is also required before recovery. Database detection includes setup/forwarding and waits for all three outage alerts. Recovery starts before restoration and includes alert-window settling. Cleanup starts before Application deletion and ends after owned storage/namespace cleanup and disappearance of live series. These are not measurements of uninterrupted HTTP downtime: the bad-image trial kept the old API available.

The separate stop/start acceptance took 70.437 seconds including monitoring setup, HTTP/query checks and browser capture. Staging PVC: `cfda1bb8-cce6-456e-acfc-444de8357872`. Prometheus PVC: `4c4d3d40-290b-45b7-9199-f40da25513aa`.

## Tests and fixes found

- **29 application tests passed**, including enabled/disabled failure exercises, plus lint/format checks. [Demo CI](https://github.com/HickoDev/PreviewForge/actions/runs/34469357949) and [private image delivery](https://github.com/HickoDev/PreviewForge/actions/runs/34469452852) passed for the application source above.
- **36 platform tests passed**, covering existing lifecycle/provenance guards, protected recovery/cleanup and resumed HTTP readiness. [Platform CI on the final code commit](https://github.com/HickoDev/PreviewForge/actions/runs/34472773162) passed. Ruff and Actionlint passed. Helm lint/rendering, Prometheus configuration/rule validation and **five alert-rule scenarios** passed, including low/no traffic and missing telemetry.
- The first live attempt timed out waiting for the business-error alert: one sequential client completed at most about 0.69 requests/second during database connection timeouts, below the deliberate 1 request/second floor. Recovery completed. The generator now uses six bounded clients; the threshold was retained. That incomplete attempt is excluded from the two complete trials above.
- Stop/start testing caught stale Kubernetes readiness immediately after node resume, then a transient closed forwarding connection. Resume now waits for actual HTTP readiness; bounded waits retry transient HTTP protocol errors. A regression covers connection closure, 503 and eventual 200. The complete startup procedure subsequently passed.
- Real terminal testing caught delayed Ctrl+C handling in Windows' blocking child-process wait. A shared interruptible wait now serves monitoring, staging and PR forwards. Grafana/Prometheus/staging termination was verified live; a new real PR was not opened for this small shared-helper change.
- Browser review corrected the error chart's percentage scale, unavailable-replica colors, table fields, duplicate source rows and source-column width. Dashboard edits no longer restart Prometheus.

## Scope and limits

Milestone 4's preview fixtures were local Argo Applications, not new GitHub PRs. The existing real PR/GHCR workflow remains the Milestone 3 implementation; its two-real-PR acceptance is recorded separately. This milestone exercised real Git configuration writes and pulls of the existing private image.

No Alertmanager/email/chat delivery, canary/Argo Rollouts controller, production load test, enforced namespace network isolation or fresh-machine bootstrap test is claimed. Metrics history is retained for up to the configured 24-hour/1 GB limits, not backed up against deletion of the whole kind node. The secret check covered the known configured credential values, not an exhaustive audit of all repository history. No public service, new remote repository, real AWS resource or NVIDIA inference was introduced.

See [exact startup and exercise commands](../observability.md). Milestone 5—Terraform-managed Floci resources, a local reconciler and asynchronous exports—has not started.
