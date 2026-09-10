# GitHub delivery on the configured laptop

The private `HickoDev/PreviewForge` repository now drives the local kind cluster. A trusted PR runs CI on GitHub, publishes a private GHCR image, and writes its immutable digest to Git. Argo CD reads that record over SSH and deploys it locally. Nothing connects inbound from GitHub to the laptop.

## Start and inspect

Start Docker Desktop with Linux containers. From the PreviewForge checkout, resume the existing cluster, Floci and Terraform resources, then run the local reconciler:

```powershell
python scripts/resources.py up --github
python scripts/previews.py watch --github --apply
```

Keep the watcher running. In a second terminal:

```powershell
python scripts/previews.py status --github
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\platform.ps1 forward
```

Open `http://127.0.0.1:18000/docs` or `http://127.0.0.1:18000/version` for staging. Ctrl+C stops a foreground command. To open an active PR preview, replace `123` with its real PR number:

```powershell
python scripts/previews.py forward --github --pr 123 --port 18042
```

Open `http://127.0.0.1:18042/docs`. The command refuses PRs without a desired record. Acceptance PRs are closed after testing, so their forwards intentionally stop working.

`resources.py up` resumes the retained node and preserves its current Git source. It refuses to create a replacement if the node is missing. It brings up export dependencies before waiting for the API. The older platform/local-preview `up`, `verify`, and `demo` commands use the synthetic local Git fixture; they refuse to overwrite remote staging. See [local mode](previews.md) for that separate demonstration and [exports](resources.md) for Milestone 5 operations.

## Recovery and shutdown

Stop the watcher before another local command that changes cluster resources. A dry run and an applied reconciliation are:

```powershell
python scripts/previews.py reconcile --github
python scripts/previews.py reconcile --github --apply
```

Then restart `watch --github --apply`. It recovers an Argo sync that exhausted retries because its namespace did not yet exist. It leaves unrelated sync failures visible for investigation. GitHub authentication/API errors stop reconciliation instead of treating unknown state as an empty environment list.

To stop the cluster while retaining staging data, first stop forwards and the watcher, then run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\platform.ps1 stop
```

Resume with `resources.py up --github` and the watcher command above. This procedure uses the existing node and locally configured credentials; rebuilding a lost node or configuring a fresh laptop is a separate operation.

## Credentials and delivery rules

- Every laptop GitHub operation in the scripts verifies that the active `gh` account is **HickoDev**. A separate read-only SSH deploy key allows Argo to read only this repository.
- The laptop's private GHCR pull credential is a HickoDev classic PAT with only `read:packages`. It is stored in the owned Kubernetes Secret and never sent to Actions. To rotate it, run `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\configure-registry.ps1`, enter it at the hidden prompt, then restart/reconcile the watcher.
- Actions uses its short-lived repository token. `PREVIEWFORGE_REMOTE_ENABLED=true` enables publication and record cleanup. `PREVIEWFORGE_PACKAGE_ID` pins the package verified through the owner's read credential: GitHub's Actions response can omit the linked repository field. Package name, owner and private visibility are checked; an available repository association must match PreviewForge. No personal token is stored in a repository variable.
- Only successful builds for the current open PR head, authored by HickoDev in this repository, receive previews. Failed updates retain their last working image. Old or closed-PR build completions cannot deploy.
- PR close/merge removes its record. Scheduled reconciliation and manual workflow dispatch recover missed close events and expire records after 48 hours. Argo removes workloads/storage, then the laptop watcher removes the owned namespace and its Terraform-managed Floci bucket/queue. Local cleanup resumes when the laptop reconnects.
- A merge starts a separate main build. Staging reports that main commit's SHA, which differs from the PR head. Configuration commits do not trigger another image build.

Repository and package remain private. API forwards bind only to `127.0.0.1`. Separate databases and storage have been verified; enforced network isolation between namespaces is not implemented.

See [Milestone 3 results](results/milestone-3.md) for acceptance evidence. GitHub documents [container authentication and publication](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry) and [package permissions](https://docs.github.com/en/packages/learn-github-packages/about-permissions-for-github-packages).
