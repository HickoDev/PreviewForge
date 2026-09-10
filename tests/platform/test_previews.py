"""Lifecycle, provenance and write-race regressions, without GitHub or a cluster."""

import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import configure_remote  # noqa: E402
import github_delivery as delivery  # noqa: E402
import preview_state as s  # noqa: E402
import previews  # noqa: E402

NOW = datetime(2026, 9, 10, tzinfo=UTC)


def build(number=42, sha="a" * 40):
    return {
        "repository": s.REPOSITORY,
        "event": "pull_request",
        "pr": number,
        "sourceSha": sha,
        "conclusion": "success",
        "published": True,
        "runId": 10,
        "attempt": 1,
        "image": {
            "repository": s.LOCAL_IMAGE,
            "digest": "sha256:" + sha[:1] * 64,
            "pullPolicy": "Never",
        },
    }


def pr(number=42, sha="a" * 40):
    return {
        "number": number,
        "state": "open",
        "headSha": sha,
        "repository": s.REPOSITORY,
        "headRepository": s.REPOSITORY,
        "author": "HickoDev",
    }


def update(records, receipt, provider):
    return s.update_build(records, receipt, provider, local=True, now=NOW)


class Store:
    def __init__(self, records=None):
        self.records = records or {}
        self.revision = 0
        self.on_write = None

    def head(self):
        return self.revision

    def snapshot(self):
        return self.revision, copy.deepcopy(self.records)

    def compare_swap(self, revision, before, after):
        if self.on_write:
            callback, self.on_write = self.on_write, None
            callback(self)
        if revision != self.revision:
            return False
        self.records = copy.deepcopy(after)
        self.revision += 1
        return True


class Lifecycle(unittest.TestCase):
    def test_local_bootstrap_refuses_to_replace_remote_staging(self):
        with (
            patch.object(previews.p, "install_tools"),
            patch.object(previews.p, "ensure_cluster"),
            patch.object(
                previews.p,
                "k",
                side_effect=[
                    "applications.argoproj.io",
                    json.dumps({"spec": {"source": {"repoURL": previews.REMOTE_REPO}}}),
                ],
            ),
            patch.object(previews.p, "ensure_password") as next_step,
        ):
            with self.assertRaisesRegex(RuntimeError, "remote Git source"):
                previews.p.up()
            next_step.assert_not_called()

    def test_two_previews_and_update_leave_other_and_staging_unchanged(self):
        records = {s.STAGING: {"sentinel": "persistent"}}
        records = update(records, build(), pr())
        records = update(records, build(43), pr(43))
        changed = update(records, build(42, "b" * 40), pr(42, "b" * 40))
        self.assertEqual(
            changed[s.PREFIX + "preview-43.json"], records[s.PREFIX + "preview-43.json"]
        )
        self.assertEqual(changed[s.STAGING], records[s.STAGING])
        self.assertEqual(changed[s.PREFIX + "preview-42.json"]["sourceSha"], "b" * 40)

    def test_failed_unpublished_stale_fork_and_closed_builds_cannot_write(self):
        records = update({}, build(), pr())
        cases = [
            ({"conclusion": "failure"}, {}),
            ({"published": False}, {}),
            ({"sourceSha": "b" * 40}, {}),
            ({}, {"state": "closed"}),
            ({}, {"headRepository": "someone/fork"}),
            ({}, {"author": "someone"}),
        ]
        for receipt, provider in cases:
            with self.subTest(receipt=receipt, provider=provider):
                self.assertEqual(
                    update(records, {**build(), **receipt}, {**pr(), **provider}), records
                )
                self.assertEqual(update({}, {**build(), **receipt}, {**pr(), **provider}), {})

    def test_retry_does_not_change_record_or_extend_expiry(self):
        first = update({}, build(), pr())
        second = s.update_build(first, build(), pr(), local=True, now=NOW + timedelta(hours=1))
        self.assertEqual(first, second)

    def test_concurrent_writers_preserve_both_previews(self):
        store = Store()

        def other_writer(store):
            store.records = update(store.records, build(43), pr(43))
            store.revision += 1

        store.on_write = other_writer
        s.transact(store, lambda records: update(records, build(), pr()))
        self.assertEqual(
            set(store.records), {s.PREFIX + "preview-42.json", s.PREFIX + "preview-43.json"}
        )

    def test_retry_rechecks_close_instead_of_recreating_environment(self):
        store = Store()
        provider = pr()

        def close_during_write(store):
            provider["state"] = "closed"
            store.revision += 1

        store.on_write = close_during_write
        _, changed = s.transact(store, lambda records: update(records, build(), provider))
        self.assertFalse(changed)
        self.assertEqual(store.records, {})

    def test_retry_rechecks_new_head_instead_of_overwriting_new_image(self):
        store = Store()
        provider = pr()

        def new_head(store):
            provider["headSha"] = "b" * 40
            store.records = update(store.records, build(42, "b" * 40), provider)
            store.revision += 1

        store.on_write = new_head
        s.transact(store, lambda records: update(records, build(), provider))
        self.assertEqual(store.records[s.PREFIX + "preview-42.json"]["sourceSha"], "b" * 40)

    def test_missed_close_cleanup_preserves_other_preview_and_staging(self):
        records = update({s.STAGING: {"sentinel": True}}, build(), pr())
        records = update(records, build(43), pr(43))
        after = s.prune_records(
            records,
            lambda n: {**pr(n), "state": "closed" if n == 42 else "open"},
            local=True,
            now=NOW,
        )
        self.assertNotIn(s.PREFIX + "preview-42.json", after)
        self.assertEqual(after[s.PREFIX + "preview-43.json"], records[s.PREFIX + "preview-43.json"])
        self.assertEqual(after[s.STAGING], records[s.STAGING])

    def test_expiry_and_unknown_provider_state(self):
        records = update({}, build(), pr())
        self.assertEqual(s.prune_records(records, pr, local=True, now=NOW + timedelta(days=3)), {})
        with self.assertRaisesRegex(ValueError, "Unknown PR state"):
            s.prune_records(records, lambda n: {"number": n}, local=True, now=NOW)

    def test_main_build_uses_main_commit_and_does_not_delete_previews(self):
        records = update({}, build(), pr())
        receipt = {**build(42, "c" * 40), "event": "push"}
        after = update(
            records, receipt, {"branch": "main", "headSha": "c" * 40, "repository": s.REPOSITORY}
        )
        self.assertEqual(after[s.STAGING]["sourceSha"], "c" * 40)
        self.assertEqual(after[s.PREFIX + "preview-42.json"], records[s.PREFIX + "preview-42.json"])

    def test_mutable_digest_wrong_registry_or_identity_rejected(self):
        record = update({}, build(), pr())[s.PREFIX + "preview-42.json"]
        for changed in (
            {**record, "environment": "staging"},
            {**record, "image": {**record["image"], "digest": "latest"}},
            {**record, "image": {**record["image"], "repository": "evil/app"}},
        ):
            with self.assertRaises(ValueError):
                s.validate_record(changed, local=True)

    def test_namespace_cleanup_rejects_replacement_or_new_desired_record(self):
        item = {
            "metadata": {
                "uid": "replacement",
                "labels": {**previews.LABELS, "previewforge.io/environment": "preview-42"},
            }
        }
        with (
            patch.object(previews, "desired", return_value={}),
            patch.object(previews, "optional", return_value=item),
            patch.object(previews.p, "k") as mutate,
        ):
            with self.assertRaisesRegex(ValueError, "replaced"):
                previews.delete_namespace({"name": "preview-42", "uid": "original"})
            mutate.assert_not_called()
        with patch.object(previews, "desired", return_value={"preview-42": {}}):
            with self.assertRaisesRegex(ValueError, "desired again"):
                previews.delete_namespace({"name": "preview-42", "uid": "original"})

    def test_namespace_cleanup_rejects_staging_or_another_owner(self):
        item = {
            "metadata": {"labels": {**previews.LABELS, "previewforge.io/environment": "staging"}}
        }
        with self.assertRaises(ValueError):
            previews.owned(item, "staging")
        item["metadata"]["labels"]["previewforge.io/owner"] = "someone-else"
        with self.assertRaisesRegex(ValueError, "ownership"):
            previews.owned(item, "preview-42")


class ArtifactProvenance(unittest.TestCase):
    def test_repository_metadata_uses_canonical_endpoint(self):
        github = object.__new__(delivery.GitHub)
        github.token = "test-token"
        response = Mock()
        response.__enter__ = Mock(return_value=io.StringIO('{"private": true}'))
        response.__exit__ = Mock(return_value=False)
        with patch.object(delivery.urllib.request, "urlopen", return_value=response) as request:
            self.assertTrue(github.api("")["private"])
        self.assertEqual(
            request.call_args.args[0].full_url,
            "https://api.github.com/repos/HickoDev/PreviewForge",
        )

    def test_registry_configuration_rejects_wrong_account_or_broad_scope(self):
        for text in (
            "account someone-else (GH_TOKEN)\n  - Active account: true\n  - Token scopes: 'read:packages'",
            "account HickoDev (GH_TOKEN)\n  - Active account: true\n  - Token scopes: 'repo', 'read:packages'",
        ):
            with (
                patch.object(configure_remote.p, "gh"),
                patch.object(configure_remote.sys, "stdin", io.StringIO("ghp_" + "a" * 36)),
                patch.object(
                    configure_remote.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess([], 0, text, ""),
                ),
                patch.object(configure_remote.p, "k") as mutate,
            ):
                with self.assertRaises(ValueError):
                    configure_remote.registry()
                mutate.assert_not_called()

    def test_public_or_unrelated_registry_package_is_rejected(self):
        github = Mock()
        github.api.return_value = {
            "visibility": "public",
            "repository": {"full_name": s.REPOSITORY},
        }
        with self.assertRaisesRegex(ValueError, "non-private"):
            delivery.private_package(github)
        github.api.return_value = {
            "visibility": "private",
            "repository": {"full_name": "HickoDev/another-project"},
        }
        with self.assertRaisesRegex(ValueError, "must belong"):
            delivery.private_package(github)
        github.api.return_value = {"visibility": "private"}
        with self.assertRaises(delivery.PackagePending):
            delivery.private_package(github)
        github.api.return_value = {
            "visibility": "private",
            "repository": {"full_name": s.REPOSITORY},
        }
        delivery.private_package(github)

    def test_main_build_survives_config_commits_but_not_a_newer_app_commit(self):
        github = object.__new__(delivery.GitHub)
        receipt = {**build(), "event": "push"}
        files = [{"filename": "gitops/previews/preview-43.json"}]

        def api(path):
            if path == "git/ref/heads/main":
                return {"object": {"sha": "b" * 40}}
            if path.startswith("compare/"):
                return {"status": "ahead", "total_commits": 1, "commits": [{"sha": "b" * 40}]}
            return {"files": files}

        github.api = api
        self.assertTrue(s.eligible(receipt, github.current(receipt)))
        files[0]["filename"] = "previewforge-demo/app/main.py"
        self.assertFalse(s.eligible(receipt, github.current(receipt)))

    def test_delivery_validates_run_provenance_and_live_pr_state(self):
        run = {
            "path": delivery.CI_PATH,
            "name": "Demo CI",
            "id": 10,
            "run_attempt": 1,
            "repository": {"full_name": s.REPOSITORY},
            "head_repository": {"full_name": s.REPOSITORY},
            "status": "completed",
            "conclusion": "success",
            "event": "pull_request",
            "head_sha": "a" * 40,
            "pull_requests": [{"number": 42}],
        }
        github = Mock()
        github.api.return_value = run
        github.current.return_value = pr()
        self.assertEqual(delivery.validate_run(github, 10)["sourceSha"], "a" * 40)
        github.current.return_value = {**pr(), "state": "closed"}
        with self.assertRaisesRegex(ValueError, "stale, closed or untrusted"):
            delivery.validate_run(github, 10)
        github.current.return_value = pr()
        for field, value in [
            ("path", "other.yml"),
            ("conclusion", "failure"),
            ("head_repository", {"full_name": "other/fork"}),
        ]:
            github.api.return_value = {**run, field: value}
            with self.assertRaises(ValueError):
                delivery.validate_run(github, 10)

    def test_github_writer_uses_base_tree_and_never_force_pushes(self):
        github = Mock()
        github.api.side_effect = [
            {"tree": {"sha": "base-tree"}},
            {"sha": "new-tree"},
            {"sha": "new-commit"},
            {},
        ]
        store = delivery.GitHubStore(github)
        before = {s.STAGING: {"sentinel": True}}
        after = update(before, build(), pr())
        self.assertTrue(store.compare_swap("parent", before, after))
        tree_call = github.api.call_args_list[1]
        self.assertEqual(tree_call.args[2]["base_tree"], "base-tree")
        self.assertEqual(
            [x["path"] for x in tree_call.args[2]["tree"]], [s.PREFIX + "preview-42.json"]
        )
        self.assertEqual(
            github.api.call_args.args,
            ("git/refs/heads/main", "PATCH", {"sha": "new-commit", "force": False}),
        )

    def artifact(self, sha="a" * 40, extra=False):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("image.tar", b"synthetic image bytes")
            archive.writestr(
                "receipt.json", json.dumps({"sourceSha": sha, "tag": "previewforge-demo:" + sha})
            )
            if extra:
                archive.writestr("../executable.py", "do not extract")
        output.seek(0)
        return output

    def test_only_expected_artifact_identity_and_paths_are_accepted(self):
        with tempfile.TemporaryDirectory(prefix="previewforge-artifact-test-") as folder:
            target = Path(folder)
            path, tag = delivery.unpack_artifact(self.artifact(), target, "a" * 40)
            self.assertEqual(path.read_bytes(), b"synthetic image bytes")
            self.assertEqual(tag, "previewforge-demo:" + "a" * 40)
            with self.assertRaisesRegex(ValueError, "source identity"):
                delivery.unpack_artifact(self.artifact("b" * 40), target, "a" * 40)
            with self.assertRaisesRegex(ValueError, "Unexpected artifact"):
                delivery.unpack_artifact(self.artifact(extra=True), target, "a" * 40)

    def test_privileged_delivery_refuses_local_execution(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(ValueError, "only in GitHub Actions"):
                delivery.GitHub()


if __name__ == "__main__":
    unittest.main()
