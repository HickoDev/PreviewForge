# Commit email privacy cleanup - 2026-09-10

The three published branch histories now use the owner's GitHub `noreply` address. **Email removal is not complete across GitHub's retained history.** The repository remains private.

## Completed and verified

- Prepared a rewrite of all 79 commits, including copies of the PR references. Every source tree is identical to its original. Pushed only the three writable branches using an atomic push with exact old-SHA leases.
- Cloned the branches again from GitHub and verified all 66 reachable commits contain no former email in their author, committer or message fields. GitHub-owned PR references cannot be updated by this push.
- Set this checkout's local Git email to `157824011+HickoDev@users.noreply.github.com`. The public GitHub profile has no displayed email.
- Fixed the monitoring and resource verification helpers locally to specify the same private identity for API-created commits. The platform suite passed 65 tests; Ruff lint and formatting passed. These helper fixes remain uncommitted alongside the earlier review changes.
- Preserved the working files and index exactly during branch alignment. Original history and working-copy backups remain outside Git and OneDrive under `%LOCALAPPDATA%\PreviewForge\runtime\email-privacy\`. Local editor snapshots and reflogs were preserved too.
- Paused all five workflows for the metadata rewrite and restored them afterward. No new image build or publication was requested. There are no new CI results for the rewritten commit IDs; earlier test reports describe their original revisions.
- PRs #11 and #12 remain open, each with one commit and one changed file. Both preview readiness/version endpoints returned HTTP 200. All five Argo applications were Synced/Healthy, and staging plus both previews were up in Prometheus.

The deployed images and desired-state `sourceSha` values still identify the original build commits. Those images were not rebuilt or relabeled. Their source trees match the rewritten commits, but their SHA strings differ. Historical milestone reports retain their original provenance.

## Still required before claiming the email is hidden

1. Confirm the account options **Keep my email addresses private** and **Block command line pushes that expose my email** at [GitHub email settings](https://github.com/settings/emails). The current CLI authorization cannot change these account settings.
2. Decide whether to delete the 48 historical Actions runs whose metadata contains the email. Deletion permanently removes their logs and associated artifacts. The logs and metadata are backed up privately; complete image archives are not retained locally. **No runs have been deleted; approval is pending.**
3. Resolve GitHub-retained history: PR #1 and #2 commit lists and a direct lookup of an old commit still expose the email. Fourteen PR references across twelve PRs were affected at rewrite time. A private Support request draft is saved in the cleanup runtime directory as `github-support-draft.txt`; it has not been sent. GitHub controls these references and cached views, and support eligibility for email removal is not guaranteed. See [GitHub's history-removal guidance](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).
4. Commit and push the reviewed helper fixes with the other pending review changes. This cleanup pushed rewritten metadata only, preserving the original published source trees.

Other existing clones should be replaced or carefully realigned before pushing; merging old history can reintroduce the address. Do not publish the private backup bundles or Support draft. See the [machine-readable verification](email-privacy-cleanup.json) for the checked branch heads and live results.
