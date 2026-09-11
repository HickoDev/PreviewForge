# PreviewForge documentation

PreviewForge creates local Kubernetes test environments for trusted application PRs. Start with the [project overview](../README.md), then choose the guide that matches your installation.

## Choose a starting point

| What you want to do | Start here | Scope |
| --- | --- | --- |
| Try the application from a checkout | [Compose setup](setup.md) | API and PostgreSQL on localhost:8000; Floci smoke checks; exports disabled |
| Learn local Kubernetes/GitOps | [Initial kind setup](kubernetes.md), then [synthetic previews](previews.md) | Local Git commits and locally loaded images; separate from GitHub delivery |
| Resume the configured owner laptop | [GitHub-mode runbook](remote.md) | Real GitHub/GHCR delivery, retained kind node, watcher and per-environment exports |
| Check an application or the platform | [Testing guide](testing.md) | Interactive checks, isolated suites and explicitly disruptive exercises |
| Understand the components and flows | [Architecture](architecture.md) | Ownership, deployment identities, local/cloud boundaries and editable diagrams |

All commands assume the repository root unless a guide says otherwise. The full platform scripts are bound to **HickoDev/PreviewForge** and verify **HickoDev** before laptop GitHub operations. A fork does not automatically get remote previews. The configured-laptop runbook is a resume procedure; a complete fresh-laptop remote setup and lost-node recovery have not been verified.

## Component guides

| Guide | What it explains |
| --- | --- |
| [Resources and exports](resources.md) | Terraform state and ownership, shared Floci, the PostgreSQL outbox, worker retries and preview cleanup |
| [Monitoring](observability.md) | Grafana/Prometheus URLs, environment selection, alert signals, recovery exercises and retained history |
| [Assistant](assistant.md) | Mock diagnostics, scoped evidence, private key setup, optional NVIDIA requests and evaluation limits |
| [Diagrams and symbols](diagrams/README.md) | Native draw.io source, three architecture pages, reusable symbols and SVG/PNG/PDF export |
| [Publication checklist](public-release.md) | Remaining privacy/release decisions and accurate descriptions of the implemented project |

Ordinary setup commands can share an operation lock with the preview watcher. Follow each guide's terminal order: finish setup, then keep the watcher and individual localhost forwards running in separate terminals. Closing a forward closes that URL; it does not delete its environment.

## Read the verification evidence

The [README checklist](../README.md#implementation-and-verification-checklist) tracks implementation and acceptance. Detailed reports record the result at the time of each milestone:

| Milestone | Recorded evidence |
| --- | --- |
| 1 — Application and Compose | [Review](results/milestone-1-review.md) |
| 2 — kind and Argo staging | [Review](results/milestone-2-review.md) |
| 3 — PR lifecycle | [Local/remote overview](results/milestone-3.md), [real delivery](results/milestone-3-remote.md) |
| 4 — Observability | [Monitoring and recovery](results/milestone-4.md) |
| 5 — Terraform and exports | [Resource/export acceptance](results/milestone-5.md) |
| 6 — Diagnostics | [Mock and cluster acceptance](results/milestone-6.md), [hosted smoke](results/milestone-6-live.md) |

Files under `results/` are historical evidence, not live status pages or current startup instructions. Early reports saying a later milestone had not started describe that earlier point in time. Their test counts and source/image identities belong to those runs. Some recorded source SHAs predate the [email privacy rewrite](results/email-privacy-cleanup.md); image identities were preserved rather than relabeled. For current operation, use the guides above.

All six implementations exist. Full hosted AI evaluation and human review remain pending. The [dated release review](results/public-release-review.md) records broader checks and their limits; it does not certify later edits or current service health.
