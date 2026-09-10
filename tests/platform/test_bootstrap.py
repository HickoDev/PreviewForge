"""Offline regressions for account/ownership guards and completed-sync detection."""

import json
import subprocess
import sys
import tempfile
import unittest
from http.client import RemoteDisconnected
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import platform_local as platform  # noqa: E402


class BootstrapGuards(unittest.TestCase):
    def test_resume_waits_for_http_readiness_after_kubernetes_reports_ready(self):
        with (
            patch.object(platform, "owned_container", return_value=True),
            patch.object(platform, "install_tools"),
            patch.object(platform, "ensure_cluster"),
            patch.object(
                platform,
                "get",
                return_value={
                    "spec": {
                        "source": {"repoURL": "ssh://git@github.com/HickoDev/PreviewForge.git"}
                    }
                },
            ),
            patch.object(platform, "wait_staging"),
            patch.object(platform, "k"),
            patch.object(platform, "forward"),
            patch.object(platform.time, "sleep"),
            patch.object(
                platform, "http", side_effect=[RemoteDisconnected(), (503, {}), (200, {})]
            ) as readiness,
            patch("builtins.print"),
        ):
            platform.start()
            self.assertEqual(readiness.call_count, 3)
            self.assertTrue(
                all(call.args[0] == "/health/ready" for call in readiness.call_args_list)
            )

    def test_dirty_fixture_stops_verification_before_mutations(self):
        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(platform, "local_git", return_value="?? private.env"),
        ):
            with self.assertRaisesRegex(RuntimeError, "uncommitted or ignored files"):
                platform.require_clean_fixture()

    def test_missing_retained_node_is_not_replaced(self):
        with (
            patch.object(Path, "exists", return_value=True),
            patch.object(platform, "owned_container", return_value=None),
            patch.object(platform, "run") as operation,
        ):
            with self.assertRaisesRegex(RuntimeError, "retained staging node is missing"):
                platform.ensure_cluster()
            operation.assert_not_called()

    def test_build_rejects_a_source_label_that_does_not_match_head(self):
        with (
            patch.object(platform, "require_clean_fixture"),
            patch.object(platform, "local_git", return_value="actual-head"),
            patch.object(platform, "run") as operation,
        ):
            with self.assertRaisesRegex(RuntimeError, "source SHA must match"):
                platform.load_image("wrong-label")
            operation.assert_not_called()

    def test_healthy_application_with_running_hook_is_not_complete(self):
        app = {
            "status": {
                "sync": {"status": "Synced", "revision": "new-commit"},
                "health": {"status": "Healthy"},
                "operationState": {"phase": "Running"},
            }
        }

        def inspect_predicate(description, predicate, timeout):
            self.assertFalse(predicate())
            app["status"]["operationState"]["phase"] = "Failed"
            self.assertFalse(predicate())
            app["status"]["operationState"]["phase"] = "Succeeded"
            app["operation"] = {"sync": {}}
            self.assertFalse(predicate())
            del app["operation"]
            self.assertTrue(predicate())
            app["status"]["sync"]["revision"] = "old-commit"
            self.assertFalse(predicate())

        with (
            patch.object(platform, "get", return_value=app),
            patch.object(platform, "wait_for", side_effect=inspect_predicate),
        ):
            platform.wait_staging("new-commit")

    def test_inactive_hickodev_does_not_authorize_a_github_operation(self):
        auth = subprocess.CompletedProcess(
            ["gh", "auth", "status"],
            0,
            "account HickoDev (keyring)\n  - Active account: false\n"
            "account Rayenne10 (keyring)\n  - Active account: true\n",
            "",
        )
        with (
            patch.object(platform.subprocess, "run", return_value=auth),
            patch.object(platform, "run") as operation,
        ):
            with self.assertRaisesRegex(RuntimeError, "active gh account HickoDev"):
                platform.gh("api", "repos/kubernetes-sigs/kind/releases/latest")
            operation.assert_not_called()

    def test_wrong_container_owner_cannot_be_changed(self):
        response = subprocess.CompletedProcess(
            ["docker", "inspect"],
            0,
            json.dumps([{"Config": {"Labels": {"previewforge.owner": "another-project"}}}]),
            "",
        )
        with patch.object(platform.subprocess, "run", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "ownership does not match"):
                platform.owned_container(platform.GIT_CONTAINER, "previewforge.owner")


class FixtureGitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="previewforge-review-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "checkout"
        self.source = Path(self.temp.name) / "fixture"
        self.root.mkdir()
        self.source.mkdir()
        platform.run("git", "init", "--initial-branch=main", self.root, quiet=True)
        platform.run(
            "git",
            "-C",
            self.root,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@previewforge.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "Initial",
            quiet=True,
        )
        for name, value in [("ROOT", self.root), ("SOURCE", self.source)]:
            patcher = patch.object(platform, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, name, text):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def test_snapshot_refreshes_real_inputs_and_excludes_private_chart_files(self):
        self.write("previewforge-demo/app/main.py", "RELEASE = 1\n")
        self.write("charts/demo-app/Chart.yaml", "name: demo-app\n")
        self.write("charts/demo-app/.env", "SYNTHETIC_SECRET=not-for-git\n")
        self.write("charts/demo-app/values.private.yaml", "password: synthetic\n")
        first = platform.snapshot()
        self.assertEqual(
            (self.source / "previewforge-demo/app/main.py").read_text(), "RELEASE = 1\n"
        )
        self.assertFalse((self.source / "charts/demo-app/.env").exists())
        self.assertFalse((self.source / "charts/demo-app/values.private.yaml").exists())
        self.write("previewforge-demo/app/main.py", "RELEASE = 2\n")
        second = platform.snapshot()
        self.assertNotEqual(first, second)
        self.assertEqual(
            (self.source / "previewforge-demo/app/main.py").read_text(), "RELEASE = 2\n"
        )
        # Deleting an owned input in the checkout must also remove it from the fixture.
        (self.root / "previewforge-demo/app/main.py").unlink()
        platform.snapshot()
        self.assertFalse((self.source / "previewforge-demo/app/main.py").exists())
        self.assertIn(
            "RELEASE = 2", platform.local_git("show", second + ":previewforge-demo/app/main.py")
        )

    def test_scoped_commit_preserves_unrelated_staged_work(self):
        self.write("previewforge-demo/app/main.py", "RELEASE = 1\n")
        platform.snapshot()
        (self.source / "notes.txt").write_text("User notes\n")
        platform.local_git("add", "notes.txt")
        (self.source / "previewforge-demo/app/main.py").write_text("RELEASE = 2\n")
        platform.commit("Only the source change", ["previewforge-demo/app/main.py"])
        self.assertNotIn("notes.txt", platform.local_git("ls-tree", "--name-only", "HEAD"))
        self.assertIn("notes.txt", platform.local_git("diff", "--cached", "--name-only"))


if __name__ == "__main__":
    unittest.main()
