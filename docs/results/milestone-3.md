# Milestone 3: local acceptance and remote delivery preparation

This report records Milestone 3's local verification before remote activation. The platform repository remains `HickoDev/PreviewForge`, with the demo application in its existing subdirectory. At the time of this local run, no workflow or image had been published. The owner subsequently approved remote activation on September 10, 2026; remote verification is in progress and is not claimed by the local results below.

## Changes

- Preview records with repository/PR identity, immutable image digest, source SHA, run metadata and expiry; successful/current/trusted build checks and conflict-aware Git writes.
- Git file ApplicationSet, restricted preview project, per-preview PostgreSQL/PVC, quotas, synthetic seeds and disposable storage distinct from staging's retained PVC.
- Ownership/UID-checked namespace reconciliation, cascading Argo deletion, dry-run orphan planning and idempotent cleanup after missed events or interruptions.
- Portable application CI, isolated test databases, source-labeled build artifacts, trusted artifact-consuming delivery, and scheduled/close reconciliation. Privileged workflows are disabled by a repository-variable gate.
- Local demo/forward/close/verify commands and prepared remote manifests/read-only GitHub polling. Local bootstrap refuses to replace a remote staging source.

## Verified locally

- **27 application tests** passed against an isolated PostgreSQL using the same `ci.py test` entry point used by Demo CI. Lint and formatting passed. Two existing upstream Starlette/AnyIO deprecation warnings remain.
- **26 platform tests** passed: existing bootstrap guards plus build eligibility, concurrent writes, head changes during retry, close races, idempotence, expiry, ownership/UID checks, artifact provenance, non-forced Git writes and main/config-only ancestry.
- All four workflow files passed checksum-verified **Actionlint 1.7.12**. All platform Python files passed Ruff lint/format checks. The older M1 verifier received formatting-only changes to satisfy the shared CI formatter.
- Helm lint passed. Preview rendering enables idempotent seeding and excludes retention annotations. The chart rejected an attempt to render disposable preview resources in staging.
- The live test created two ApplicationSet applications with distinct working PostgreSQL instances and PVs, seeded data and separate task writes. Updating A changed its running digest/source without changing B's pod template or data.
- Failed, unpublished and stale results made no desired-state commit and left the running application functional. A late completion could not recreate a closed preview.
- Closing A removed its Application, workloads, PVC, PV and namespace while B and staging remained usable. A separate successful simulated main build deployed its own SHA while keeping staging's PVC/tasks.
- A missed close event was repaired through desired-state reconciliation; cleanup resumed after the Git commit and was safe to repeat. Dry-run planning made no Git change. Both verification previews were removed at the end.

The final uninterrupted acceptance run ran from `2026-09-09T23:24:29.652618+00:00` to `2026-09-09T23:28:55.275023+00:00` (UTC; September 10 in Tunis). It is recorded in [the raw local results](milestone-3-verification.json). All source/config SHAs there belong to the separate runtime Git fixture. Main delivery is a **synthetic main-build exercise**, not a GitHub merge. Timings are individual observations on the existing Windows/Docker Desktop machine with warm caches, not production benchmarks.

After that run, the exact documented `demo --pr 42`, `forward --pr 42 --port 18042` and `close --pr 42` commands passed. Swagger/OpenAPI, the expected source SHA and three seeded tasks were checked through the command's own loopback forward. Its process tree was stopped, and closing removed preview 42's namespace and storage. The CI build/save entry point also produced a real image/receipt artifact from the clean runtime fixture; artifact validation, Docker load and image-source checks passed without a registry login. Generated remote manifests passed Kubernetes server dry-run validation and were not applied. [Supplemental operating/build results](milestone-3-operation-verification.json) record these checks.

Final inspection found only the retained staging PV and a `Synced`/`Healthy` staging Application. The existing Compose API, PostgreSQL and Floci containers remained healthy. Repository scans found none of the generated M1/staging/preview database passwords or common credential/private-key patterns. Runtime artifacts remain outside Git/OneDrive.

## Findings fixed

1. Argo's JSON Git generator flattened large numeric PR IDs to scientific notation, producing invalid names. The template now uses the validated string environment name. The final run uses nine-digit synthetic PR IDs and succeeds without manual intervention.
2. Comparing a main build to the newest configuration commit would reject valid application builds. Delivery now permits intervening config-only commits, while rejecting newer application changes or diverged history; a regression verifies both paths.
3. Local startup could otherwise replace an approved remote Git source later. Bootstrap and reconciliation now check the selected source before changing applications or namespaces.

The first development run continued successfully after applying the naming fix. It is not the final uninterrupted result used as evidence.

## Remaining / blocked

- Publication and controlled remote verification were subsequently approved by the owner. The original local results below remain separate from remote integration evidence.
- Actions execution on GitHub-hosted Linux, actual CI-run/artifact metadata, GHCR publication/pulls, private Git authentication, real simultaneous PRs, real merge-to-staging delivery and remote missed-event recovery remain untested.
- Argo needs privately configured read-only Git access; the local watcher needs a privately configured GHCR pull Secret. No secret was requested in chat or added to Git. Repository branch/package policies have not been changed.
- Mocked provider/API regressions prove the tested code paths, not real GitHub delivery. Preview namespaces do not provide tested network isolation. Fresh-machine setup and loss/recreation of the kind node were not tested.
- Floci/Terraform integration remains Milestone 5; monitoring dashboards remain Milestone 4; NVIDIA inference remains a later mock-first milestone. Those services were not added here.

## Reproduce

```powershell
python -m unittest discover -s tests/platform -v
python scripts/ci.py test
python scripts/previews.py verify
python scripts/previews.py demo --pr 42
python scripts/previews.py forward --pr 42 --port 18042
# Ctrl+C, then:
python scripts/previews.py close --pr 42
```

See [operation and the concrete remote activation steps](../previews.md). Finish Milestone 3's approved remote acceptance before moving to Milestone 4.
