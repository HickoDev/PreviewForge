# GitHub delivery on the configured laptop

The `HickoDev/PreviewForge` repository drives the local kind cluster. A trusted application PR runs CI on GitHub, publishes to a private GHCR package, and writes its immutable digest to Git. Argo CD reads that record over SSH and deploys it locally. Nothing connects inbound from GitHub to the laptop. The current delivery implementation supports private or public source with a private package; real acceptance used a private repository. See [publication status](public-release.md) before changing visibility.

This runbook resumes the existing owner-operated installation. It assumes Python 3.12 on a supported host, Git, a local Docker daemon running Linux containers, `gh` with **HickoDev active**, the retained kind node/runtime files, and configured Git/registry credentials. The [activation reference](previews.md#remote-activation-reference) describes the original credential/manifests setup; a complete fresh-laptop bootstrap or lost-node restore has not been verified. For a standalone first run, use [Compose setup](setup.md).

## Start and inspect

Start your local Docker daemon with Linux containers. Stop an existing watcher with Ctrl+C before running setup commands. From the PreviewForge checkout, resume the existing cluster, Floci and Terraform resources, then run the local reconciler:

```text
python scripts/resources.py up --github
python scripts/previews.py watch --github --apply
```

Keep the watcher running. If monitoring needs setup, run `python scripts/monitoring.py up` between `resources.py up --github` and starting the watcher; it uses the same operation lock. An already installed monitoring stack resumes with the node. In a second terminal:

```text
python scripts/previews.py status --github
python scripts/platform_local.py forward
```

Open `http://127.0.0.1:18000/docs` or `http://127.0.0.1:18000/version` for staging. Ctrl+C stops a foreground command. To open an active PR preview, replace `123` with its real PR number:

```text
python scripts/previews.py forward --github --pr 123 --port 18042
```

Open `http://127.0.0.1:18042/docs`. The command refuses PRs without a desired record. Acceptance PRs are closed after testing, so their forwards intentionally stop working.

`resources.py up` resumes the retained node and preserves its current Git source. It refuses to create a replacement if the node is missing. It brings up export dependencies before waiting for the API. The older platform/local-preview `up`, `verify`, and `demo` commands use the synthetic local Git fixture; they refuse to overwrite remote staging. See [local mode](previews.md) for that separate demonstration and [exports](resources.md) for Milestone 5 operations.

## Recovery and shutdown

Stop the watcher before another local command that changes cluster resources. A dry run and an applied reconciliation are:

```text
python scripts/previews.py reconcile --github
python scripts/previews.py reconcile --github --apply
```

Then restart `watch --github --apply`. It recovers an Argo sync that exhausted retries because its namespace did not yet exist. It leaves unrelated sync failures visible for investigation. A GitHub authentication/API error aborts that reconciliation pass instead of treating unknown state as an empty environment list. A one-shot command exits with an error; the watcher reports the failure and retries after 15 seconds. It can resume when access is restored.

To stop the cluster while retaining staging data, first stop forwards and the watcher, then run:

```text
python scripts/platform_local.py stop
```

Resume with `resources.py up --github` and the watcher command above. This procedure uses the existing node and locally configured credentials; rebuilding a lost node or configuring a fresh laptop is a separate operation.

## Credentials and delivery rules

- Every laptop GitHub operation in the scripts verifies that the active `gh` account is **HickoDev**. A separate read-only SSH deploy key allows Argo to read only this repository.
- The laptop's private GHCR pull credential is a HickoDev classic PAT with only `read:packages`. It is stored in the owned Kubernetes Secret and never sent to Actions. To rotate it, run `python scripts/configure_remote.py registry`, enter it at the hidden prompt, then restart/reconcile the watcher.
- Actions uses its short-lived repository token. `PREVIEWFORGE_REMOTE_ENABLED=true` enables publication and record cleanup. `PREVIEWFORGE_PACKAGE_ID` pins the package verified through the owner's read credential: GitHub's Actions response can omit the linked repository field. Package name, owner and private visibility are checked; an available repository association must match PreviewForge. No personal token is stored in a repository variable.
- Only successful builds for the current open PR head, authored by HickoDev in this repository, receive previews. Failed updates retain their last working image. Old or closed-PR build completions cannot deploy.
- PR close/merge removes its record. Scheduled reconciliation and manual workflow dispatch recover missed close events and expire records after 48 hours. Argo removes workloads/storage, then the laptop watcher removes the owned namespace and its Terraform-managed Floci bucket/queue. Local cleanup resumes when the laptop reconnects.
- A merge starts a separate main build. Staging reports that main commit's SHA, which differs from the PR head. Configuration commits do not trigger another image build.

The GHCR package remains private even when the source repository is public. Delivery checks repository identity and package visibility before image operations, and checks the package again after push. A public repository must already have the verified private package; an absent or unreadable package fails closed. Forks are excluded by both the delivery job condition and trusted Python provenance checks. Public CI image artifacts are accessible separately from GHCR; no credentials belong in those images. See [publication checks and limits](public-release.md).

API forwards bind only to `127.0.0.1`. Separate databases and storage have been verified; enforced network isolation between namespaces is not implemented.

## Which PRs get an environment

Open or update an owner-authored PR from a branch inside `HickoDev/PreviewForge`. **Demo CI** currently watches `previewforge-demo/**`, `compose.yaml`, `scripts/ci.py` and `.github/workflows/demo-ci.yml`. A documentation-only PR does not trigger a new application image or preview. Forks and PRs from other authors do not receive environments under the current trust policy.

Follow the PR's **Demo CI** check, then the separate **Deliver approved demo image** run in the Actions tab. Delivery must complete before its desired record is available. With the laptop watcher running, use `previews.py status --github` and the forward command above. Check `/version` for the expected environment and successful source build; a green CI check alone does not prove local readiness.

Two active PRs use two foreground forwards on different ports. See [the two-preview commands](resources.md#start-the-configured-laptop) and [the testing guide](testing.md) for task, export and monitoring checks. A preview URL is a local address, not an automatically published website.

See [Milestone 3 results](results/milestone-3.md) for acceptance evidence. GitHub documents [container authentication and publication](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry) and [package permissions](https://docs.github.com/en/packages/learn-github-packages/about-permissions-for-github-packages).
