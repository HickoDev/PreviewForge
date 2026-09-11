# Publishing PreviewForge

This project demonstrates an owner-operated local preview platform. Making its source repository public is a separate action from publishing GHCR packages, exposing Kubernetes services or enabling hosted inference.

## Before changing visibility

1. Review and commit the final local changes, including the working NVIDIA model, architecture artwork and public-source delivery fix. Push them and wait for the applicable GitHub checks. Local checks do not prove that an unpushed revision passed GitHub CI.
2. Rotate any credential that has been shared outside its intended secret store. Configure a replacement NVIDIA key through `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\configure-nvidia.ps1`, then reload it with `python scripts/assistant.py up --allow-live`. Revoke the old key through the provider account. Never put a key in a Git commit, issue, screenshot, shell argument or chat.
3. Review Git history, branches, PR discussions, Actions logs, build artifacts and images. [GitHub makes Actions history and logs visible when a repository becomes public](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/managing-repository-settings/setting-repository-visibility). [Signed-in readers can download workflow artifacts](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/download-workflow-artifacts), so a private GHCR package does not hide copies uploaded as public Actions artifacts. This workflow builds archives from application code and dependencies; runtime secrets are supplied separately in the local cluster.
4. Finish the [email privacy cleanup](results/email-privacy-cleanup.md). The owner authorized the rewrite, and all three published branch histories now use the GitHub `noreply` address. Old PR/commit views and 48 Actions run metadata records still expose the previous email; run deletion and account privacy settings await confirmation. Keep the repository private until the remaining exposure is resolved.
5. Choose a license if releasing the code for reuse as an open-source project. No project license has been selected. Public visibility alone should not be described as an open-source license. See [GitHub's licensing guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository).

The [dated review](results/public-release-review.md) records what was actually checked and what remains pending. It is a point-in-time review, not a guarantee that later changes or dependency releases are safe.

## GitHub settings and delivery

Keep `PREVIEWFORGE_REMOTE_ENABLED=true` and the verified `PREVIEWFORGE_PACKAGE_ID` for the existing owner-operated setup. Public source delivery needs no new secret or visibility variable. The package must remain private and readable by the existing Actions and local pull identities.

After the owner changes repository visibility, review GitHub's public-repository security settings: secret scanning and push protection, dependency alerts, and approval for outside-contributor workflow runs. These settings were not changed by the local review. Fork PR CI uses GitHub-hosted runners and read-only repository permissions; fork builds cannot publish images or create preview environments. Privileged workflows check out trusted `main`, never fork code.

Do not enable arbitrary external PR deployments into this laptop. The current trust boundary deliberately permits only owner-authored, same-repository PRs. Namespaces and separate databases do not enforce network isolation or isolate hostile code from the shared kind node and Floci.

Main protection must account for the automation's GitOps record commits. Enabling a blanket required-PR rule without designing the bot write path can stop delivery. Do not weaken code review protections merely to make a failing deployment pass.

After changing visibility, run an owner-authored application PR through CI and delivery. Verify its source with `/version`, private GHCR pulls, Argo health, CRUD, exports and Prometheus discovery. Keep a second preview open to verify it stays unchanged. Public-repository delivery cannot be claimed as live-tested before that change occurs.

## What the project demonstrates

Accurate post wording:

> I built PreviewForge, a local GitOps preview platform using GitHub Actions, GHCR, kind, Helm, Argo CD and Terraform. Trusted application PRs get separate databases and simulated S3/SQS resources through Floci, with Prometheus/Grafana monitoring and a read-only diagnostic assistant. I verified real PR delivery, independent preview data, background exports and recovery scenarios. NVIDIA-hosted inference passed a smoke test; broader model-quality evaluation is still pending.

The implemented demo is a FastAPI task API. Frontend/login flows, a multi-user self-service portal, real AWS provisioning, enforced tenant network isolation and production capacity/security testing are outside the current implementation. The repository can be shared publicly without claiming those features. Local preview URLs work only on the operator's laptop; use a diagram or recorded demo in the post.
