# Public release review - 2026-09-10

The local implementation passed the functional checks below. Publication still needs the owner's credential/privacy decisions and a commit/push of the reviewed changes. The repository remains private. This review did not push code, change repository or package visibility, publish images, call NVIDIA, or stop the active previews.

Subsequent owner-authorized work rewrote and pushed the three branch histories to remove the personal commit email. The [separate privacy report](email-privacy-cleanup.md) records that operation and the remaining GitHub-retained exposure. The revisions and decisions below describe the earlier review before that rewrite.

## Scope and fixes

Reviewed local HEAD `491abaaebfbb567b84515e66b0e62b5e4482ab7f` with the existing uncommitted AI and documentation changes. Fetched all five remote branch refs through `gh`-backed credentials after verifying HickoDev; remote main was `df280dd44c06cc0d8050fb1cb0dd34fcf43eb4a9`. The Git scan covered 68 reachable commits, including the demo branches. Existing local work, open PRs #11/#12, databases, watcher and forwards were preserved.

Fixed a public-release incompatibility in `scripts/github_delivery.py`: publication formerly required a private source repository. It now verifies the exact platform repository and permits either source visibility, while retaining the private GHCR package requirement. In public mode an absent or unreadable package stops before image operations; automatic first-package creation is reserved for the original private bootstrap. The new tests cover both source visibilities, public/internal packages, absent packages, unknown visibility and unrelated repositories.

The privileged delivery job also excludes fork workflow runs before starting. Existing Python validation still checks workflow identity, artifact provenance, the current PR head, same-repository ownership, author, completion and package identity. Privileged delivery and close reconciliation check out trusted `main`; ordinary PR tests have read-only permissions and no registry/NVIDIA credentials.

The README now explains all six milestones, the API-only demo, owner-bound automation and remaining AI quality acceptance. Documentation explains the distinction between source visibility, private GHCR and downloadable CI image archives. The updated [architecture diagram](../diagrams/previewforge-architecture-v2.png) removes the private-source wording and preserves the original. It used the built-in image generation tool; the [exact edit prompt](../diagrams/previewforge-architecture-v2.prompt.md) is saved alongside it.

## Results

The [machine-readable summary](public-release-review.json) records the review scope, totals and excluded actions without including raw logs or credentials.

| Check | Result |
| --- | --- |
| Application suite | 46 passed against isolated PostgreSQL and Floci; application lint and formatting passed; disposable CI containers/network cleaned up |
| Platform suite | 63 passed, including the new public-source delivery guards; lint and formatting passed |
| Assistant suite | 70 passed with container networking disabled; lint and formatting passed |
| Python dependency audit | pip-audit 2.10.1 found no known advisories in all 41 distinct locked packages, including runtime/test pins from both projects and platform-marked entries |
| Workflow syntax | Pinned Actionlint 1.7.12 passed all five workflows |
| Helm | Demo staging/preview and assistant lint/render passed; monitoring chart lint/render passed |
| Monitoring configuration | Prometheus configuration valid; all seven alert rules valid; rule tests passed |
| Isolated Terraform/Floci lifecycle | Terraform 1.16.2 formatting/validation, apply, empty second plan, missing-queue repair, lost-state import, nonempty-bucket destruction and SDK-confirmed cleanup passed; isolated containers/network removed |
| Live Argo state | Staging, preview-11, preview-12, observability and assistant all Synced/Healthy |
| Live HTTP and metrics | Three application readiness/version endpoints passed; all three Prometheus API targets up; Grafana database healthy; assistant health responding in configured NVIDIA mode |
| Git/worktree secret scans | Gitleaks 8.30.1 defaults plus an explicit NVIDIA-token rule and two levels of decoding: one known synthetic fixture match, no real credential findings |
| Public text and Actions logs | All 12 PR records, commit metadata and all 86 available completed workflow logs scanned; no credential findings; no issue/review comments existed |
| Retained CI image artifacts | All 19 archives inspected: 274 unique OCI blobs, 531 image configuration/first-party files scanned across image layers; 57 public GPG-fingerprint matches verified against the pinned Python base image; no credential findings |
| Image and screenshot review | Architecture and Grafana screenshots visually inspected; no credentials, personal desktop information or unrelated work visible |

The scanner binary was downloaded through `gh` as HickoDev and verified against GitHub's release asset SHA-256 before execution. Raw logs, archives during inspection, scanner reports and audit tooling stay under `%LOCALAPPDATA%\PreviewForge\runtime\public-review\`, outside the repository and OneDrive. Scan reports redact matched values.

The Git/worktree secret-scanner finding is the explicit `PF_SECRET_CANARY_...` test value in `ai-assistant/evaluations/fixtures/cases.json:317`, introduced by the Milestone 6 commit. Its purpose is to verify that synthetic secret-like evidence is removed before inference. The 57 artifact matches are all the public 40-hex-character `GPG_KEY` signing fingerprint in Python's base-image environment/history, verified against the pinned local base image. Neither category is a live credential. The scanners' nonzero exits for these matches are recorded, not disguised as clean exits. No broad allowlist or history rewrite was added. Artifact inspection covered image configuration and first-party `/app` files from all layers; it did not scan third-party OS file contents.

The 179 passing tests include two upstream TestClient deprecation warnings in each application suite; they do not fail the tests. The Python audit checks published advisories at review time. It does not cover OS packages or every third-party container/tool, establish absence of unknown vulnerabilities, or constitute a penetration test.

Earlier same-session smoke checks created independent demo tasks in PRs #11/#12, completed and downloaded exports from both, confirmed cross-preview export lookup returned 404, and checked exact source SHAs and separate monitoring. The final review repeated read-only health checks while preserving the user's running environments. It did not repeat disruptive cluster stop/start or fault injection; the dated milestone reports retain that earlier evidence.

## Required publication decisions and remaining acceptance

- Commit and push the reviewed changes, then wait for the applicable GitHub checks. These final changes have only been tested locally so far. Public-repository delivery requires one real verification after the visibility change; its new guards were verified locally with mocked GitHub metadata.
- Rotate any previously disclosed NVIDIA key and revoke its predecessor. Rotation has not been independently confirmed by this review; no key was retrieved or printed.
- Decide whether to publish the existing non-noreply author email in Git history. No author identity or history was changed.
- Choose a project license if describing the release as open source. No license has been selected or added automatically.
- GitHub secret-scanning/dependency-alert and branch-protection endpoints were unavailable to this review in the current private repository; their status is not represented as passing. After making the repository public, review available protections and outside-contributor workflow approval. The repository's default workflow token is read-only and cannot approve PRs.
- Full hosted 13-case AI evaluation and human semantic-quality review remain pending. The prior live smoke proves connectivity and one accepted diagnostic response, not general model accuracy. This review made no inference calls.

Use the [publication checklist and suggested post wording](../public-release.md). The project is a local portfolio/learning platform using synthetic data and simulated AWS. It does not implement login/frontend features, a multi-user portal, hostile-tenant isolation, real AWS deployment or production readiness.
