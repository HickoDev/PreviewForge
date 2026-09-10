# Milestone 3: real GitHub/GHCR acceptance

Verified on September 10, 2026, with the owner's approval. The private `HickoDev/PreviewForge` repository supplies both platform configuration and the demo application. GitHub-hosted runners built/published images; the laptop pulled Git and private GHCR images into its existing kind cluster. No second repository, public service, real AWS resource or hosted AI call was introduced.

## Verified behavior

| Check | Evidence |
| --- | --- |
| Main CI, artifact validation, private image publication and initial staging record | [Demo CI](https://github.com/HickoDev/PreviewForge/actions/runs/34463325034), [delivery](https://github.com/HickoDev/PreviewForge/actions/runs/34464156649) |
| Two simultaneous real previews with separate seeded PostgreSQL databases and disposable volumes | [PR #1](https://github.com/HickoDev/PreviewForge/pull/1), [PR #2](https://github.com/HickoDev/PreviewForge/pull/2); HTTP source identity and separate task writes verified |
| Deliberately failing PR update preserves its previous record, running image and saved task | [Expected failed CI](https://github.com/HickoDev/PreviewForge/actions/runs/34464648303); delivery skipped |
| Successful PR #1 update changes its digest and retains data; PR #2's pod template and data stay unchanged | [Updated CI](https://github.com/HickoDev/PreviewForge/actions/runs/34464896502), [delivery](https://github.com/HickoDev/PreviewForge/actions/runs/34464984089) |
| Replay of an older successful PR build cannot roll back the updated preview | [Replayed CI, attempt 2](https://github.com/HickoDev/PreviewForge/actions/runs/34464132553/attempts/2), [expected stale rejection](https://github.com/HickoDev/PreviewForge/actions/runs/34465191165) |
| Missed close event repaired through the real reconciliation workflow | PR #2 close handler was intentionally gated off; [skipped handler](https://github.com/HickoDev/PreviewForge/actions/runs/34465340983), [successful manual reconciliation](https://github.com/HickoDev/PreviewForge/actions/runs/34465353689) |
| Closed PR's replayed build cannot recreate its deleted preview | [Expected rejection](https://github.com/HickoDev/PreviewForge/actions/runs/34465545368); GitHub no longer associated an open PR with the run |
| Merge closes PR #1 and removes its Application, namespace, workloads, PVC and PV | [Close reconciliation](https://github.com/HickoDev/PreviewForge/actions/runs/34465457275); local watcher completed namespace/storage cleanup |
| A separate main build delivers the merge commit to persistent staging | [Main CI](https://github.com/HickoDev/PreviewForge/actions/runs/34465457357), [main delivery](https://github.com/HickoDev/PreviewForge/actions/runs/34465574571) |

The missed-event test temporarily disabled the delivery gate while no build delivery was active, closed PR #2, and confirmed its skipped handler left the record/environment present. The gate was restored in a `finally` block before manually dispatching the same reconciliation workflow used by the schedule. That workflow removed the record; Argo and the running laptop watcher removed the environment. The other preview and staging remained usable.

The final staging source is main merge commit `71ea32bc0c95b14d5fce24b74edad84904631a82`, distinct from PR head `167d28958c270092f87ff28c5cbff9f866766625`. Both the live `/version` response and Kubernetes container image ID were checked. The image is:

```text
ghcr.io/hickodev/previewforge-demo@sha256:5444abc535310a37286b42a20541ad4d845e7f927f30bb5334046b5a2fde7666
```

Staging kept PVC UID `cfda1bb8-cce6-456e-acfc-444de8357872` and the exact task list captured before switching from local Git. Both test previews were removed. GHCR package `14980083` was checked using the owner's read credential: private, owned by HickoDev, and linked to PreviewForge.

## Startup and tests

- **27 application tests** passed on GitHub against isolated PostgreSQL, together with Ruff lint/format and the image build. The merged change adds two API documentation summaries; the deliberately failing test is absent from the final tree.
- **31 platform tests** pass, including package visibility/identity, credential account/scope, canonical API URL, delayed namespace recovery, retained-node startup, lifecycle, provenance and write-race guards. [Platform CI](https://github.com/HickoDev/PreviewForge/actions/runs/34464914807) also passed Ruff and Actionlint.
- The documented remote `forward` command served Swagger and the expected environment on `127.0.0.1`.
- The documented `platform.ps1 stop` / `platform.ps1 start` procedure passed with both previews present. The remote Git source, registry credentials, all three PVC identities and their saved tasks survived.
- The foreground watcher was stopped and restarted. It recovered an Argo sync that had exhausted retries before the namespace existed. Repeated local dry-run/applied cleanup reported no remaining previews.

See [raw remote results](milestone-3-remote-verification.json) for timestamps, records and checks, and [the operating instructions](../remote.md) for exact commands. The earlier [local report](milestone-3.md) remains separate evidence.

## Integration fixes

1. The repository metadata request used a trailing slash that GitHub returned as 404. It now uses the canonical endpoint, with a regression test.
2. The Actions token omitted linked-repository metadata that the owner's classic pull credential returned. Delivery now accepts the explicitly verified package ID when that field is absent, while checking owner, name and private visibility. An available repository association must still match PreviewForge. The pull token remains on the laptop.
3. Argo could exhaust namespace-not-found retries while the local watcher was stopped. After creating prerequisites, the watcher now retries that specific failure for the current image, using a resource-version precondition. Other sync failures remain visible.
4. Resuming the retained node needed a command that preserves the remote Git configuration. `platform.ps1 start` supplies that path and refuses to create a replacement for a missing retained node.

PR #2's first build also caught formatting in its temporary API title. It was corrected before publication. The initial integration failures and deliberate failed/stale/closed replay runs remain in Actions history; the successful delivery links above identify the passing paths.

## Limits

The 48-hour expiry and forced concurrent-write races are covered by offline/local regressions; this run did not wait two days or deliberately force simultaneous Git ref updates. Manual dispatch exercised the real scheduled reconciliation code, but GitHub scheduler timing was not measured. Fresh-laptop installation and recovery from deletion of the kind node were not tested. Namespace/database/storage separation is verified; cross-namespace network isolation is not implemented. Milestones 4–6 remain unstarted.
