import base64
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import assistant as a
import assistant_evidence as evidence


class AssistantBoundaries(unittest.TestCase):
    def test_private_key_is_only_sent_on_stdin_and_never_printed(self):
        marker = "PF_SECRET_CANARY_PRIVATE_SETUP"
        output = io.StringIO()
        with (
            patch.object(a, "runtime"),
            patch.object(a, "ensure_namespace"),
            patch.object(a, "owned"),
            patch.object(a.sys.stdin, "isatty", return_value=True),
            patch.object(a.getpass, "getpass", return_value=marker),
            patch.object(a.p, "k") as kube,
            redirect_stdout(output),
        ):
            a.configure_key()
        self.assertNotIn(marker, output.getvalue())
        args, kwargs = kube.call_args
        self.assertNotIn(marker, str(args))
        self.assertTrue(kwargs["sensitive"])
        obj = json.loads(kwargs["input"])
        self.assertEqual(obj["metadata"]["namespace"], "previewforge-ai")
        self.assertEqual(base64.b64decode(obj["data"]["api-key"]).decode(), marker)
        self.assertIn("--server-side", args)

    def test_noninteractive_key_input_is_rejected(self):
        with (
            patch.object(a, "runtime"),
            patch.object(a, "ensure_namespace"),
            patch.object(a.sys.stdin, "isatty", return_value=False),
            patch.object(a.getpass, "getpass") as prompt,
        ):
            with self.assertRaises(ValueError):
                a.configure_key()
            prompt.assert_not_called()

    def test_git_projection_only_extracts_database_ports(self):
        yaml = "service:\n  port: 1234\ndatabase:\n  password: PF_SECRET_CANARY_GIT\n  port: 5433\n"
        self.assertEqual(evidence.port_value("charts/demo-app/values.yaml", yaml), 5433)
        self.assertIsNone(
            evidence.port_value("charts/demo-app/values.yaml", "service:\n  port: 1234\n")
        )
        self.assertEqual(
            evidence.port_value(
                "previewforge-demo/app/config.py", "    database_port: int = 5432\n"
            ),
            5432,
        )
        self.assertIsNone(
            evidence.port_value("charts/demo-app/values.yaml", "database:\n  port: 99999\n")
        )

    def test_git_diff_rejects_revision_injection_before_git(self):
        with patch.object(evidence.p, "run") as run:
            with self.assertRaises(ValueError):
                evidence.configuration_diff("--output=/tmp/unsafe", "a" * 40)
            run.assert_not_called()

    def test_environment_path_injection_cannot_grant_permissions(self):
        with patch.object(a.p, "get") as read:
            with self.assertRaises(ValueError):
                a.grant("../../kube-system")
            read.assert_not_called()

    def test_unowned_objects_are_not_modified(self):
        with (
            patch.object(
                a.v,
                "optional",
                return_value={"metadata": {"labels": {"previewforge.io/owner": "another-project"}}},
            ),
            patch.object(a.p, "k") as kube,
        ):
            with self.assertRaises(ValueError):
                a.apply_owned("ConfigMap", "previewforge-ai-policy", {"data": {}})
            kube.assert_not_called()


if __name__ == "__main__":
    unittest.main()
