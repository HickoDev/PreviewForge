"""Host paths, mutual exclusion and private prompts are part of runtime safety."""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import host
import platform_local as p


class HostSupport(unittest.TestCase):
    def test_windows_keeps_existing_runtime_location(self):
        with (
            patch.dict(os.environ, {"PREVIEWFORGE_HOME": ""}),
            patch.object(host.sys, "platform", "win32"),
        ):
            with patch.dict(
                os.environ, {"LOCALAPPDATA": str(Path(tempfile.gettempdir()) / "local")}
            ):
                self.assertEqual(host.home(), Path(os.environ["LOCALAPPDATA"]) / "PreviewForge")
                self.assertEqual(host.executable("kubectl"), "kubectl.exe")

    def test_linux_selects_xdg_location_and_native_tools(self):
        with tempfile.TemporaryDirectory() as folder:
            with (
                patch.dict(os.environ, {"PREVIEWFORGE_HOME": "", "XDG_STATE_HOME": folder}),
                patch.object(host.sys, "platform", "linux"),
            ):
                self.assertEqual(host.home(), Path(folder) / "previewforge")
                self.assertEqual(host.executable("kubectl"), "kubectl")
                self.assertEqual(host.venv_python(Path(folder)), Path(folder) / "bin/python")

    def test_runtime_rejects_checkout_and_broad_directories(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "checkout"
            for path in [
                root,
                root / "private",
                Path(folder),
                Path.home(),
                Path(folder) / "OneDrive/runtime",
            ]:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    host.validate_runtime(path, root)
            self.assertEqual(
                host.validate_runtime(Path(folder) / "private", root),
                (Path(folder) / "private").resolve(),
            )

    def test_unverified_platform_is_rejected(self):
        for system, machine in [("darwin", "x86_64"), ("linux", "aarch64")]:
            with (
                patch.object(host.sys, "platform", system),
                patch.object(host.platform, "machine", return_value=machine),
            ):
                with self.assertRaisesRegex(RuntimeError, "untested"):
                    host.platform_key()

    def test_noninteractive_prompt_never_falls_back_to_echo(self):
        with (
            patch.object(host.sys.stdin, "isatty", return_value=False),
            patch.object(host.getpass, "getpass") as prompt,
        ):
            with self.assertRaises(ValueError):
                host.hidden_prompt("Secret: ")
            prompt.assert_not_called()

    def test_keyring_and_linux_config_auth_are_accepted_only_for_hickodev(self):
        for source in ["keyring", "/home/demo/.config/gh/hosts.yml"]:
            response = subprocess.CompletedProcess(
                [], 0, f"account HickoDev ({source})\n  - Active account: true\n", ""
            )
            with (
                patch.object(p.subprocess, "run", return_value=response),
                patch.object(p, "run", return_value="ok") as call,
            ):
                self.assertEqual(p.gh("api", "user"), "ok")
                call.assert_called_once()

    def test_lock_excludes_another_process_and_releases_after_crash(self):
        with tempfile.TemporaryDirectory() as folder:
            lock = Path(folder) / "operation.lock"
            code = "import sys; sys.path.insert(0,sys.argv[1]); import host; from pathlib import Path\nwith host.lock(Path(sys.argv[2])):\n print('locked',flush=True)\n sys.stdin.read()"
            process = subprocess.Popen(
                [sys.executable, "-u", "-c", code, str(p.ROOT / "scripts"), str(lock)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                self.assertEqual(process.stdout.readline().strip(), "locked")
                with self.assertRaisesRegex(RuntimeError, "holds the lock"):
                    with host.lock(lock):
                        self.fail("Concurrent lock was acquired")
                process.kill()
                process.wait(timeout=10)
                with host.lock(lock):
                    pass
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
                for stream in [process.stdin, process.stdout, process.stderr]:
                    stream.close()

    @unittest.skipIf(os.name == "nt", "POSIX directory modes")
    def test_linux_private_runtime_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            path = host.private_directory(Path(folder) / "private", Path(folder) / "checkout")
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)
