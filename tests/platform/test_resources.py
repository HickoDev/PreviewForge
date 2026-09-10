"""Offline regressions for local-only resource scope and coordinated cleanup."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import resources  # noqa: E402
from reconciler import runtime as r  # noqa: E402
from reconciler import terraform as tf  # noqa: E402


class ResourceGuards(unittest.TestCase):
    def test_close_during_plan_stops_before_apply(self):
        with tempfile.TemporaryDirectory(prefix="previewforge-m5-test-") as folder:
            with (
                patch.object(r, "RUNTIME", Path(folder) / r.OWNER),
                patch.object(tf, "prepare"),
                patch.object(tf, "record"),
                patch.object(tf, "recover_state", return_value={}),
                patch.object(
                    tf, "command", side_effect=[(2, ""), (0, '{"resource_changes": []}')]
                ) as command,
            ):
                checks = iter([True, False])
                with self.assertRaisesRegex(ValueError, "closed during plan"):
                    tf.ensure("preview-42", lambda _: next(checks))
                self.assertEqual(
                    [call.args[1] for call in command.call_args_list], ["plan", "show"]
                )

    def test_runtime_rejects_git_and_cloud_synced_directories(self):
        for root in [r.p.ROOT / r.OWNER, Path("C:/OneDrive/private") / r.OWNER]:
            with (
                patch.object(r, "RUNTIME", root),
                self.assertRaisesRegex(ValueError, "outside Git"),
            ):
                r.validate_runtime()

    def test_plan_refuses_unexpected_resources_and_implicit_deletion(self):
        def plan(address, actions):
            return {"resource_changes": [{"address": address, "change": {"actions": actions}}]}

        address = "module.environment.aws_s3_bucket.reports"
        tf.validate_plan(plan(address, ["create"]))
        tf.validate_plan(plan(address, ["delete"]), destroy=True)
        for value in [
            plan("aws_instance.unrelated", ["create"]),
            plan(address, ["delete"]),
            plan(address, ["delete", "create"]),
        ]:
            with self.assertRaises(ValueError):
                tf.validate_plan(value)

    def test_staging_cannot_enter_preview_cleanup(self):
        with patch.object(tf, "command") as command:
            with self.assertRaisesRegex(ValueError, "restricted to preview"):
                tf.destroy("staging", lambda _: True)
            command.assert_not_called()

    def test_state_cannot_target_another_environment(self):
        with tempfile.TemporaryDirectory(prefix="previewforge-m5-test-") as folder:
            with patch.object(r, "RUNTIME", Path(folder) / r.OWNER):
                path = tf.directory("preview-42")
                path.mkdir(parents=True)
                state = {
                    "resources": [
                        {
                            "mode": "managed",
                            "module": "module.environment",
                            "type": "aws_s3_bucket",
                            "name": "reports",
                            "instances": [{"attributes": {"id": "previewforge-staging-reports"}}],
                        }
                    ]
                }
                (path / "terraform.tfstate").write_text(json.dumps(state))
                with self.assertRaisesRegex(ValueError, "another environment"):
                    tf.validate_state("preview-42")

    def test_closed_environment_stops_before_terraform(self):
        with tempfile.TemporaryDirectory(prefix="previewforge-m5-test-") as folder:
            with (
                patch.object(r, "RUNTIME", Path(folder) / r.OWNER),
                patch.object(tf, "prepare") as prepare,
            ):
                with self.assertRaisesRegex(ValueError, "closed before"):
                    tf.ensure("preview-42", lambda _: False)
                prepare.assert_not_called()

    def test_cleanup_waits_for_desired_records_application_and_pods(self):
        with patch.object(resources, "current_previews", return_value={"preview-42": {}}):
            self.assertFalse(resources.may_delete("preview-42"))
        with (
            patch.object(resources, "current_previews", return_value={}),
            patch.object(resources.v, "optional", return_value={"metadata": {}}),
        ):
            self.assertFalse(resources.may_delete("preview-42"))
        ns = {
            "metadata": {
                "labels": {**resources.v.LABELS, "previewforge.io/environment": "preview-42"}
            }
        }
        with (
            patch.object(resources, "current_previews", return_value={}),
            patch.object(resources.v, "optional", side_effect=[None, ns]),
            patch.object(
                resources.p,
                "get",
                return_value={"items": [{"metadata": {"name": "still-running"}}]},
            ),
        ):
            self.assertFalse(resources.may_delete("preview-42"))

    def test_staging_terraform_failure_does_not_block_closed_namespace_cleanup(self):
        target = {"name": "preview-42", "uid": "owned"}
        with (
            patch.object(resources.v, "REMOTE", True),
            patch.object(resources.v, "plan", return_value=({}, [target])),
            patch.object(resources, "active", return_value=True),
            patch.object(resources.v, "copy_registry_secret"),
            patch.object(
                resources, "run_resources", side_effect=[["staging provisioning failed"], []]
            ),
            patch.object(resources.p, "wait_for"),
            patch.object(resources.v, "delete_namespace") as cleanup,
        ):
            with self.assertRaisesRegex(RuntimeError, "staging provisioning failed"):
                resources.v.reconcile(apply=True)
            cleanup.assert_called_once_with(target)

    def test_dry_run_never_invokes_terraform(self):
        with (
            patch.object(resources.v, "plan", return_value=({}, [])),
            patch.object(resources, "run_resources") as mutate,
        ):
            resources.v.reconcile(apply=False)
            mutate.assert_not_called()
