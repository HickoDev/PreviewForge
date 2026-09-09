# Milestone 2 review

This review covers local Kubernetes/GitOps staging only. The user authorized fixes, a platform commit and a push to `HickoDev/PreviewForge`. Image publication, additional remote repositories and Milestone 3 remain outside this change.

## Findings fixed

1. **Verification could deploy an old snapshot.** Helm lint read the current checkout, but the live test used the existing runtime Git fixture. Verification now refreshes the managed app/chart inputs and staging defaults from this checkout, builds that baseline and waits for Argo CD to deploy it before testing the next revision. Deleted managed inputs are also removed; their previous content stays in fixture Git history.
2. **Fixture commits could include unrelated work.** `git add --all` could sweep staged edits or private files into an automatic fixture commit. Commits now include explicit paths only. Verification/builds refuse uncommitted and ignored files in the fixture. Snapshot selection excludes private chart value files and environment files, and validates copy/deletion paths. A regression uses real temporary Git repositories to prove unrelated staged notes remain uncommitted.
3. **A missing node could trigger an empty replacement.** Startup now refuses to create a new node when the persistent staging fixture already exists but its node is missing. A rebuild needs deliberate data recovery planning.
4. **Build identity needed a guard.** A build now requires a clean fixture whose HEAD equals the supplied source SHA; it cannot label different working-tree contents with an older commit.

The review also checked migration ordering, PVC retention, health probes, loopback access, Git transport, GitHub account guards, failure restoration and the documented operating procedure. The initial implementation evidence, including cluster stop/start persistence, remains in [the original report](milestone-2.md).

## Verification results

- All **8 platform regression tests** passed, including the new fixture and data-preservation guards.
- All **27 application tests** passed, with lint and formatting checks passing. Two existing upstream Starlette/AnyIO deprecation warnings remain.
- The full documented `platform.ps1 verify` run passed: current-checkout baseline deployment, Helm lint and Kubernetes validation, HTTP CRUD and source identity, a second immutable image rollout, drift repair, unavailable-image detection and Git recovery, database outage/readiness behavior, retained task/PVC, structured failure logs and secret exclusion.
- New Python code passed Ruff lint and formatting checks. Commit contents were checked for generated database passwords and common credential/private-key patterns; none were found.

The live acceptance checks ran from `2026-09-09T22:52:11.852533+00:00` to `2026-09-09T22:56:31.028491+00:00` (UTC), after refreshing and deploying the baseline. [Raw review verification results](milestone-2-review-verification.json) record the local fixture commits, image digests and timings. These are local observations with warm caches, not production benchmarks.

The final API reports fixture source `c2a813b8ac4e04a0978cb2c6edcdee4d5c80bd51`. The recovered Git configuration is `36207d2bae56c98680477632614ed7368c4fbb67`. Staging is healthy with automatic reconciliation restored.

The original report's stop/start and documented port-forward checks remain valid; this review reran the full live verifier and application tests. Fresh-machine setup, deletion/recreation of the kind node, remote Git authentication and GitHub PR delivery remain untested.

## Reproduce

```powershell
python -m unittest discover -s tests/platform -v
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 test
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\platform.ps1 verify
```

Verification creates synthetic tasks and local fixture commits, preserving previous committed fixture revisions. The platform repository's main branch and the fixture's source/config commits are different identities. It does not publish an image or exercise a GitHub PR workflow.

## Next milestone

Milestone 3 adds trusted PR tests/builds, immutable images, ApplicationSet-generated preview environments, head-SHA/race checks, per-preview cleanup and main-branch staging updates. Acceptance needs two simultaneous previews, isolated databases, safe updates, stale/failed-build rejection and cleanup that preserves the other preview and staging.

Before remote automation, agree whether the logical demo application stays in this repository or receives a separately approved repository, and obtain explicit approval for GHCR image publication. No second repository or registry publication is implied by this platform commit/push.
