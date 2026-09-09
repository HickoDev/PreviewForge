# Milestone 2 verification

Verified on 2026-09-09 using Windows x64, Python 3.12.10, Docker Desktop/WSL2 and a dedicated single-node kind cluster. This is local Kubernetes with a local Git fixture, not a GitHub PR deployment.

## Delivered

- Pinned kind configuration and checksum-verified local tool installation.
- Helm chart for the API, PostgreSQL StatefulSet, retained PVC, migration Job, internal Services and resource quota.
- Argo CD bootstrap, restricted staging AppProject and persistent staging Application with automatic sync, self-heal and bounded retries that refresh to newer Git revisions.
- A read-only local Git daemon, immutable application image loading and a source SHA baked into each image.
- PowerShell startup/inspection/forwarding/stop commands, offline regression tests and live acceptance tests.

This report records the initial implementation run. The subsequent [review report](milestone-2-review.md) records review fixes and their verification. The verifier makes real commits only inside its separate runtime Git fixture; platform GitHub publication is a separately authorized action. No second remote repository was created and no image was published. Existing Milestone 1 application code was preserved; its Dockerfile now also accepts a source identity at build time.

## Acceptance results

| Handoff acceptance | Verified evidence |
| --- | --- |
| Application runs on kind and reaches PostgreSQL | HTTP task create/update/list, database readiness, successful migration and healthy staging pods |
| Deployment-config commit changes the image | Argo CD automatically deployed a different loaded manifest digest after a local configuration commit |
| `/version` confirms the expected commit | Exact baked source SHA and `staging` environment checked against the intended image |
| Controlled live drift is reconciled from Git | A manual replica count of two returned to the Git value of one |
| Application failures and database readiness are observable | Missing-image migration pod reported `ErrImageNeverPull`; database outage returned readiness/task 503 with liveness 200, failure logs/metrics and no ready API Service endpoint |

Additional verified behavior:

- A recovery commit completed a successful Argo sync after the unavailable image's bounded migration failure; the preceding API stayed ready throughout.
- The API was not restarted merely because PostgreSQL was unavailable. Restoring PostgreSQL reused the same PVC and retained the task.
- Documented `stop` followed by `up` preserved the kind node, PVC, task and deployed source. The normal kubeconfig hash and Milestone 1 container IDs were unchanged.
- The exact documented `forward` command served Swagger, OpenAPI and the expected source identity on `127.0.0.1:18000`. Its test process tree was stopped afterward; staging remains running.
- Helm lint and Kubernetes server validation passed; the chart rejected a mutable application image reference.
- Three offline regression tests passed: incomplete sync detection, refusing an inactive HickoDev account and rejecting a container with another owner.
- Milestone 1's 27 application tests and lint/format checks passed. The same two upstream Starlette/AnyIO deprecation warnings remain.
- New Python lint/format checks passed. Repository files were checked for generated passwords and common credential/private-key patterns; none were found. Runtime files stay outside Git/OneDrive.
- The actual guarded Argo manifest download path matched the pinned SHA-256 checksum.

## Recorded run

The final full GitOps run started at `2026-09-09T22:34:23.042973+00:00` and completed at `2026-09-09T22:38:23.873491+00:00`. These are UTC times. The separate stop/start test completed at `2026-09-09T22:41:16.376921+00:00`.

| Measurement | Seconds |
| --- | ---: |
| Build and load second application image | 8.234 |
| Configuration commit to verified running release | 31.797 |
| Replica drift repair | 2.328 |
| Bad-image exercise and completed Git recovery | 173.797 |
| Database outage/recovery exercise | 19.000 |
| Documented cluster stop/start and persistence check | 61.734 |

These are individual local observations, **n=1 per final scenario**, with warm image caches. The bad-image exercise includes the deliberately configured two-minute migration deadline. They are not production benchmarks or a reliability percentage.

Final source SHA: `d4297b10b0c9825f234a20a01743bf98ea995596`.

Deployment-config commit: `c1332252f5d0b539dc7f390e96bdb3fe7e2c2eb2`.

Recovery-config commit: `6fe7f32853808039849697dfc9bff0e2bfa8c685`.

Final image: `docker.io/previewforge/demo@sha256:68ac3b6b5336f30caea12ea0a872655214a94df5668a40d8a5a3d98d28b883f0`.

These identifiers belong to the local fixture. The image repository spelling is only a local containerd name: the application was loaded directly, with pull policy `Never`, and was not published to Docker Hub. Full reviewed timestamps and identifiers are in [the raw results](milestone-2-verification.json).

## Issues found and fixed during implementation

1. Docker's partial multi-platform PostgreSQL image could not be imported by kind. Bootstrap now pulls the digest directly through the node's CRI; application builds are still loaded locally.
2. Argo's settings ConfigMap requires its identification labels. Bootstrap now preserves those labels when setting the polling interval.
3. A static HTTP Git server worked with the Git CLI but failed Argo's ref lookup. The final implementation uses the actual Git protocol with a read-only daemon and disabled receive-pack.
4. `Synced`/`Healthy` alone did not prove that a blocked hook had recovered. Verification now requires a completed successful sync and no pending operation. Retry refresh allows a newer recovery revision to replace the obsolete revision on retry. The earlier development operation was repaired manually before the final, fully automatic acceptance run; that earlier run is not counted as verified recovery.
5. A restarted Kubernetes API briefly rejected requests while its permissions initialized. Bootstrap now retries readiness against the same private context. The subsequent documented stop/start test passed.

Initial uncached Argo pulls exceeded the original five-minute readiness wait. Bootstrap now allows ten minutes for those components and can resume a partial installation. No credentials were changed to resolve any of these failures.

## Reproduce

From the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\platform.ps1 up
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\platform.ps1 verify
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\platform.ps1 forward
```

Open `http://127.0.0.1:18000/docs` while forwarding. See [the operating guide](../kubernetes.md) for inspection commands, local config commits and storage ownership.

Tested versions: kind **0.33.0**, Kubernetes/kubectl **1.35.8**, host Helm **4.2.4**, Argo CD **3.5.2** (bundled Helm **4.2.1**), PostgreSQL **17.9**, and the existing Python **3.12.13** application base image. Pins and hashes are in `bootstrap/tools.lock.json`, the kind config, chart and Dockerfile.

## Remaining / untested

- GitHub Actions, GHCR publication, real PR previews, ApplicationSet lifecycle and remote Git authentication are Milestone 3. Installing the upstream ApplicationSet controller does not implement those workflows.
- Prometheus/Grafana dashboards and a measured release-recovery suite are Milestone 4. This milestone exposes metrics and inspects Kubernetes/Argo status.
- Kubernetes-to-Floci SDK routing, Terraform resources and exports are Milestone 5. Compose remains the sole Floci owner; no competing emulator was started.
- The AI service remains placeholder configuration in mock mode; no NVIDIA inference or key access occurred.
- Enforced network isolation, disaster recovery, deletion/recreation of the kind node, fresh-machine prerequisites and other operating systems were not tested. A retained PVC does not protect against deleting the node that contains its bytes.
- Argo CD's UI/admin login was not part of acceptance; its server was verified ready, and reconciliation was inspected through Kubernetes.

Milestone 3 has not started.
