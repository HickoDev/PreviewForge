import base64
import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import nullcontext, redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import assistant as a
import assistant_evidence as evidence
import evaluate_assistant as evaluation


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


class EvaluationExitStatus(unittest.TestCase):
    def setUp(self):
        recorded = json.loads(
            (a.p.ROOT / "docs/results/milestone-6-evaluation.json").read_text(encoding="utf-8")
        )["cases"][0]
        self.report = copy.deepcopy(recorded["report"])
        self.report["metadata"].update(provider="nvidia", attempts=1)
        self.baseline = {"wrong-port": recorded["baseline"]}

    def exercise(self, destination, result, action="live-smoke"):
        with (
            patch.object(a, "runtime", return_value=Path(destination)),
            patch.object(a, "forward", return_value=nullcontext()),
            patch.object(a, "http", side_effect=[{"mode": "nvidia"}, result]) as http,
            patch.object(evaluation.p, "run", return_value=json.dumps(self.baseline)),
            redirect_stdout(io.StringIO()),
        ):
            try:
                return evaluation.evaluate(action)
            finally:
                self.assertEqual(http.call_count, 2)

    def test_successful_live_smoke_saves_validated_report(self):
        with tempfile.TemporaryDirectory() as destination:
            report, output = self.exercise(destination, self.report)
            self.assertEqual(report["summary"]["matched_expected"], 1)
            self.assertTrue(output.exists())

    def test_unavailable_provider_stops_full_evaluation_after_one_case(self):
        for error in ("model_unavailable", "provider_rejected", "redirect_rejected"):
            with self.subTest(error=error), tempfile.TemporaryDirectory() as destination:
                result = {**self.report, "diagnosis": None, "error": error}
                with self.assertRaisesRegex(RuntimeError, "stopped on provider"):
                    self.exercise(destination, result, "live-evaluate")
                saved = json.loads(next(Path(destination).glob("*.json")).read_text())
                self.assertEqual(saved["planned_cases"], 13)
                self.assertEqual(saved["summary"]["completed_cases"], 1)
                self.assertEqual(saved["cases"][0]["report"]["error"], error)

    def test_invalid_output_makes_smoke_fail_after_saving_report(self):
        with tempfile.TemporaryDirectory() as destination:
            result = {**self.report, "diagnosis": None, "error": "invalid_model_output"}
            with self.assertRaisesRegex(RuntimeError, "failed on output validation"):
                self.exercise(destination, result)
            self.assertEqual(len(list(Path(destination).glob("*.json"))), 1)

    def test_wrong_diagnosis_makes_smoke_fail(self):
        self.report["diagnosis"].update(status="insufficient_evidence", hypotheses=[])
        with tempfile.TemporaryDirectory() as destination:
            with self.assertRaisesRegex(RuntimeError, "did not match labeled expectations"):
                self.exercise(destination, self.report)


if __name__ == "__main__":
    unittest.main()
