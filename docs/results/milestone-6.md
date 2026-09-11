# Milestone 6 results — 2026-09-10

**Initial mock verification record. No hosted inference call was made during the checks recorded below. Subsequent user-authorized key configuration and hosted tests are recorded separately in [live verification](milestone-6-live.md).**

The trusted FastAPI assistant runs separately in `previewforge-ai`, with its own immutable local image and Helm chart. The task API, worker, PostgreSQL, Floci resources, preview watcher and monitoring do not depend on it. The NVIDIA adapter uses the documented HTTPS chat endpoint, a configurable model, bounded retries and validated structured results; it has no tools or write credentials.

## Review and corrections

The initial review found staging's export worker in CrashLoopBackOff. Kubernetes recorded five-second exec probe timeouts. Its heartbeat command imported the AWS SDK, ORM and FastAPI, adding substantial work under a CPU quota. The fix keeps the probe in the standard library, handles missing/partial heartbeat files and writes heartbeat updates atomically. The same application commit adds selected database-error telemetry without connection strings or exception text.

Application source **`8266a4ac0736af9c02f9c64ef1afb311f3e8c614`**, image **`sha256:c99b7c32e4e656794c49af424a16caa7073b5daa361034cef4ddf20b1f80bd92`**, was delivered through successful [Demo CI](https://github.com/HickoDev/PreviewForge/actions/runs/34490164626) and [private GHCR delivery](https://github.com/HickoDev/PreviewForge/actions/runs/34490289484). The replacement worker remained healthy with zero restarts during subsequent assistant work.

Initial diagnostic exercises exposed two gaps: the application's JSON formatter nests its database event, and a wrong Kubernetes Service port can cause a timeout rather than an explicit refusal. The collector now unwraps one bounded event level and selects only approved fields. The baseline correlates observed database operational errors with the differing configured and Service ports. It does not relabel a timeout as a refusal. Regression cases cover both formats/signals. The earlier exercises abstained and their owned resources were cleaned up before the final successful run.

## Verification

| Check | Result |
| --- | --- |
| Application regressions | 46 tests passed against PostgreSQL and isolated Floci; lint and formatting passed |
| Platform regressions | 56 tests passed, including private key stdin handling, no key output, Git field projection and ownership guards |
| Assistant offline tests | 67 tests passed with container networking disabled and socket connections rejected in the test suite |
| Provider failure tests | Missing key/opt-in, invalid credentials/access, redirects, rate limits, Retry-After, network/time budget, server errors, malformed/partial/oversized output and usage accounting passed through mocked HTTP |
| Evidence boundaries | Wrong environment/source/image, stale evidence, old OOM state, unsupported quotes/IDs, runtime-secret/canary redaction and prompt injection checks passed |
| Mock API and evaluation | 13/13 labeled cases matched expected outcomes; 13/13 had valid references; four abstained; zero hosted attempts |
| Real cluster diagnosis | Actual Git configuration change from 5432 to 5433 yielded a cited database-port-mismatch hypothesis using Deployment, Service, Git diff and real application logs |
| Kubernetes RBAC | Allowed pod/log reads in the authorized namespace; denied Secret reads, exec/attach, workload mutation, impersonation and unrelated namespace reads |
| Recovery and cleanup | Explicit Git revert restored readiness. Test Application, namespace, PVC/PV, diagnostic roles and local Git server were removed. Staging's three tasks and PVC were preserved |
| Private key setup | Tested with a synthetic value and mocked Kubernetes write; value passed only via stdin and was absent from output/arguments. A real key was neither requested nor configured |
| Documented startup | With the assistant stopped, staging still completed an SQS/S3 export. `python scripts/assistant.py up` restored the assistant in mock mode in 19.23 seconds; Argo was Synced/Healthy, Swagger accepted a diagnosis body, and staging diagnosis/tasks/PVC were preserved |

The [raw cluster result](milestone-6-cluster.json) includes source/image identity, timestamps, permissions, the actual sanitized diagnosis and evidence. The successful run used disposable **`preview-600006`** and a read-only local Git server. It did not create a new remote repository, PR or assistant registry package. It did not provision Floci resources for this API-only failure fixture.

Configuration commits in the local exercise were:

- Known-good: `db673353e9de0d5a38d3c3cd15b971517c162aea`.
- Wrong port: `3be07d352f0ed35b51e8f6b52f28ae29eb9444a2`.
- Explicit recovery revert: `cbd1591262c783e5c60d8bccd87e08295dda4480`.

These configuration commits are separate from the application image's source SHA. Staging's PVC remained **`cfda1bb8-cce6-456e-acfc-444de8357872`**.

The [startup and independence result](milestone-6-startup.json) records one retained-service startup observation, not a fresh-install benchmark. The normal GitHub-backed assistant Application, staging and monitoring were all Synced/Healthy at completion. The worker had zero restarts after 41 minutes of this observation. The initial startup test also caught Windows kubectl emitting concatenated JSON documents for a multi-document manifest; setup now handles that output before applying the complete Argo configuration.

[Assistant CI](https://github.com/HickoDev/PreviewForge/actions/runs/34494610218) passed the offline tests, lint, formatting and runtime image build for the implementation commit. The assistant image is loaded into kind locally and is not published to a registry.

## Evaluation interpretation

The [13-case raw evaluation](milestone-6-evaluation.json) records each labeled expectation, deterministic baseline, mock report, references, abstention, latency and attempts. Seven development cases cover wrong port, missing configuration, image pull failure, OOM, Floci endpoint, healthy deployment and missing evidence. Six variations cover another port/operational-error log, stale evidence, instruction injection, secret canaries, cross-environment/source evidence and unexplained readiness failure.

The mock deliberately uses the deterministic baseline. Its **13/13** matching result proves pipeline behavior, not LLM accuracy or an improvement over deterministic diagnosis. Extractive mock facts introduced zero unsupported statements in these cases. Live statement correctness remains a human-review field; valid IDs and exact quotes do not prove a model's interpretation.

This single mock evaluation observed a **63 ms median** HTTP round trip, **47–78 ms range**, across **13 cases** on the configured local cluster. This is not a hosted-model latency measurement or production benchmark. Windows, Python 3.12 and Docker Desktop's retained kind cluster were used; no GPU was required.

## Remaining live acceptance and limitations

At the initial mock checkpoint, the candidate `meta/llama-3.3-70b-instruct` interface had only been checked against its API reference. Subsequent live testing found that hosted model unavailable; see [the replacement and actual live results](milestone-6-live.md). Full acceptance requires the bounded 13-case hosted evaluation and review of supported/unsupported statements. A single smoke case does not establish model quality.

Collection intentionally omits unfamiliar log/configuration text; the first version focuses on API deployment diagnostics and numeric database-port diffs. This is not a general log chatbot or an autonomous remediation agent. No claim of production-grade redaction, real AWS behavior or enforced network isolation is made.

See [the exact startup, diagnosis, evaluation, recovery and hidden key setup commands](../assistant.md).
