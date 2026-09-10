# Milestone 5 results — 2026-09-10

**Passed:** Terraform-managed Floci resources, asynchronous exports and the real preview lifecycle. Staging remains running with its original three tasks. Acceptance PRs and their local resources were cleaned up. No real AWS resources or NVIDIA calls were involved.

The platform is still the single private `HickoDev/PreviewForge` repository. GitHub builds/publishes private images and records desired deployments; the laptop provisions Floci resources and runs Kubernetes. The application changes were delivered to staging from source `79a64d6c752601d2f1afaee22743fe1682eedd70`, image digest `sha256:88dd7c59a89e7182ba92a4a377c75040f6da59cb5730387afa4b00241e766d1b`.

## Verified behavior

| Check | Result |
| --- | --- |
| Application CI | 39 passing tests against PostgreSQL and isolated Floci, including idempotency, duplicate delivery, outbox retry and missing-object repair |
| Platform regressions | 50 passing tests, including local-only state/plan guards, close-during-plan protection, process ownership and preservation of new PR work |
| Terraform on Windows and Linux | Formatting/validation, apply, unchanged second plan, refresh, missing-queue repair, owned state import and nonempty-bucket destroy passed; boto3 independently confirmed resource existence/absence |
| Three environments | Staging, PR #9 and PR #10 had distinct buckets, queues and local state directories |
| Real exports | Both previews exported their three seed tasks plus their own unique task through POST → SQS → worker → S3 → API download |
| Real worker crash | A worker process exited **73 after uploading**, before database commit/acknowledgment. The job remained pending; redelivery completed it with one logical report/object |
| Resource loss and interruption | PR #9's owned bucket and queue were removed. Terraform recreated them; an injected interruption immediately after apply was recovered by another reconciliation. The worker reconstructed the same report from its PostgreSQL snapshot |
| Real PR update | Updating #9 produced a new private image while retaining its resources; #10's desired record/resources were unchanged |
| Emulator restart | Restarting the persistent shared Floci container refreshed its recorded route/state and preserved both previews' reports |
| Close and partial cleanup | #9's Application, namespace and storage disappeared before cloud cleanup. An interruption after queue deletion left the bucket to be cleaned on retry. #10 and staging still served reports |
| Final cleanup | #9 and #10 closed without merging; temporary branches, namespaces, disposable storage, buckets and queues were removed |
| Documented startup | After stopping the retained kind node and Floci, `python scripts/resources.py up --github` restored actual API/database/export readiness. Containers, PVCs, tasks and the saved report were preserved |
| PowerShell example and API docs | The exact documented request/poll/download block produced a local JSON report containing staging's three tasks; export routes were present in the running OpenAPI document |

The process-crash test also passed separately on staging; [its recorded proof](milestone-5-worker-crash.json) contains the export ID and observed outcomes. Terraform lifecycle checks passed both in an isolated local Linux container and [GitHub Platform CI](https://github.com/HickoDev/PreviewForge/actions/runs/34481646478). Monitoring configuration and its five Prometheus alert scenarios remain in that pipeline.

[API/example evidence](milestone-5-api.json) records the running source and downloaded report ID. Successful [private image delivery](https://github.com/HickoDev/PreviewForge/actions/runs/34483166847) includes the workflow's enforced package-visibility check.

## Real PR evidence

- [PR #9](https://github.com/HickoDev/PreviewForge/pull/9): initial source `339e5b0e9e32686f3faadfa16d84a1f13edd0e46`, image `sha256:4ab6c5f24a76f4fdfe7715404505be9c1b249bce8cf7da0ae0e045b93ec4c14c`; [initial CI](https://github.com/HickoDev/PreviewForge/actions/runs/34481751737).
- Its update used source `4b46aea2c0a4f64e853ff2f8994bc60d3b393e6b`, image `sha256:53e0b12e4d21cb291ddcd242f06a587073fcf21f1b256cdd2e6ee4f607257e1b`; [update CI](https://github.com/HickoDev/PreviewForge/actions/runs/34483042521).
- [PR #10](https://github.com/HickoDev/PreviewForge/pull/10): source `7d0ede568c2756ffad72d7169845af7b18e882f4`, image `sha256:048350afa6c705b8d6c8445d2164c39e27b6056eda608f80a0c5f9ed86720d7f`; [CI](https://github.com/HickoDev/PreviewForge/actions/runs/34481765659).

The [raw lifecycle result](milestone-5.json) records UTC checkpoint times, resource names, source commits and image digests. These are acceptance-exercise timings, including repeated checks and CI waits, not deployment-performance benchmarks.

## Startup evidence and environment

The [startup result](milestone-5-startup.json) records a **74.14-second** startup command on this configured laptop. This is one retained-cluster observation, not a first-install or performance guarantee.

- Windows, Python 3.12, Docker Desktop Engine 29.4.1; Docker reports 16 CPUs and 12,388,065,280 bytes of memory.
- One retained kind node; Terraform **1.16.2**, AWS provider **6.9.0**, Floci **2.0.1** at the committed image digest.
- Staging PVC remained `cfda1bb8-cce6-456e-acfc-444de8357872`; its three pre-existing tasks were unchanged.
- Prometheus PVC remained `4c4d3d40-290b-45b7-9199-f40da25513aa`.
- The saved report remained downloadable with the same completion timestamp, so ordinary restart did not require report reconstruction.

## Issues found and corrected

Initial testing exposed an AWS provider compatibility issue: 6.64.0's queue importer rejects local emulator URLs. Version 6.9.0 supports the required imports and is pinned with verified Windows/Linux checksums. Existing experimental staging state was backed up locally and the same owned resources imported; its data was preserved. See the [newer provider's parser](https://github.com/hashicorp/terraform-provider-aws/blob/v6.64.0/internal/service/sqs/queue.go).

Acceptance checks were corrected to account for the previews' existing seed tasks, container PID 1 signal handling, and SQS messages already leased to a waiting consumer. The final fault test verifies that the selected worker is stopped and waits for message visibility before requiring exit 73. Earlier diagnostic PRs #3–#8 were closed and their owned resources removed. The startup command also now brings dependencies up before waiting for actual HTTP readiness.

## Scope and commands

This verifies Floci API emulation, not AWS IAM, production availability or enforced network isolation. The reset exercise removed one disposable preview's resources; it did **not** erase the shared Floci volume. State and ownership records remain outside Git, OneDrive and the emulator volume. NVIDIA inference and Milestone 6 remain unimplemented.

Use [the tested startup and export commands](../resources.md). For a full repeat, stop the normal watcher first:

```powershell
python scripts/ci.py test
python -m unittest discover -s tests/platform -v
python scripts/resources.py verify --github --allow-faults --allow-github-writes
python scripts/verify_resources_startup.py --allow-faults
```
