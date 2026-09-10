"""Protect staging and other previews during explicit monitoring exercises."""

import sys
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import monitoring as m  # noqa: E402
import verify_monitoring as verify  # noqa: E402


class MonitoringGuards(unittest.TestCase):
    def test_recovery_preserves_new_release_and_unrelated_records(self):
        records = {
            verify.s.STAGING: {"image": "bad"},
            "gitops/previews/preview-42.json": {"keep": True},
        }
        after = verify.restore_change(records, {"image": "bad"}, {"image": "good"})
        self.assertEqual(
            after["gitops/previews/preview-42.json"], records["gitops/previews/preview-42.json"]
        )
        self.assertEqual(records[verify.s.STAGING], {"image": "bad"})
        self.assertEqual(verify.restore_change(after, {"image": "bad"}, {"image": "good"}), after)
        with self.assertRaisesRegex(ValueError, "concurrently"):
            verify.restore_change(
                {verify.s.STAGING: {"image": "new release"}}, {"image": "bad"}, {"image": "good"}
            )

    def test_cleanup_refuses_real_preview_without_test_marker(self):
        ns = {
            "metadata": {"labels": {**verify.v.LABELS, "previewforge.io/environment": "preview-42"}}
        }
        with (
            patch.object(verify.v, "optional", return_value=ns),
            patch.object(verify.p, "k") as mutate,
        ):
            with self.assertRaisesRegex(ValueError, "another preview"):
                verify.cleanup_preview("preview-42")
            mutate.assert_not_called()

    def test_cli_git_conflict_remains_retryable(self):
        with patch.object(
            verify.p, "gh", side_effect=RuntimeError("gh: not fast forward (HTTP 422)")
        ):
            with self.assertRaises(urllib.error.HTTPError) as error:
                verify.GitHubCli().api("git/refs/heads/main", "PATCH")
            self.assertEqual(error.exception.code, 422)

    def test_setup_preserves_namespace_owned_by_someone_else(self):
        staging = {"spec": {"source": {"repoURL": verify.v.REMOTE_REPO}}}
        ns = {"metadata": {"labels": {"previewforge.io/owner": "someone-else"}}}
        with (
            patch.object(m.p, "get", return_value=staging),
            patch.object(m.v, "optional", return_value=ns),
            patch.object(m.p, "apply") as mutate,
        ):
            with self.assertRaisesRegex(ValueError, "another owner"):
                m.up()
            mutate.assert_not_called()
