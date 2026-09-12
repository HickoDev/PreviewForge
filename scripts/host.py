"""Host differences for Windows x64 and Linux x64; no cluster or network operations."""

import contextlib
import getpass
import os
import platform
import subprocess
import sys
import warnings
from pathlib import Path


def platform_key():
    if sys.platform not in {"win32", "linux"} or platform.machine().lower() not in {
        "amd64",
        "x86_64",
    }:
        raise RuntimeError("Supported hosts: Windows x64 and Linux x64; macOS/ARM are untested")
    return "windows-amd64" if sys.platform == "win32" else "linux-amd64"


def require_supported():
    platform_key()
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("Use Python 3.12")
    if not __debug__:
        raise RuntimeError("Remove Python -O/PYTHONOPTIMIZE; verification requires assertions")


def home():
    override = os.environ.get("PREVIEWFORGE_HOME")
    if override:
        path = Path(override).expanduser()
        if not path.is_absolute():
            raise ValueError("PREVIEWFORGE_HOME must be an absolute dedicated directory")
        return validate_runtime(path, Path(__file__).resolve().parents[1])
    if sys.platform == "win32":
        if not os.environ.get("LOCALAPPDATA"):
            raise ValueError("LOCALAPPDATA is required on Windows")
        return Path(os.environ["LOCALAPPDATA"]) / "PreviewForge"
    state = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state")))
    if not state.is_absolute():
        raise ValueError("XDG_STATE_HOME must be absolute")
    return state / "previewforge"


def executable(name):
    return name + (".exe" if sys.platform == "win32" else "")


def venv_python(directory):
    return Path(directory) / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def background_options():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def validate_runtime(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    if (
        path == Path.home().resolve()
        or path == Path(path.anchor)
        or path.is_relative_to(root)
        or root.is_relative_to(path)
        or any(part.lower() in {"onedrive", "dropbox", "google drive"} for part in path.parts)
        or "onedrive" in str(path).lower()
    ):
        raise ValueError("Runtime must be a dedicated directory outside Git and synced folders")
    return path


def private_directory(path, root):
    path = validate_runtime(path, root)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "nt":
        user = subprocess.check_output(["whoami"], text=True).strip()
        result = subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                user + ":(OI)(CI)F",
                "SYSTEM:(OI)(CI)F",
            ],
            capture_output=True,
        )
        if result.returncode:
            raise RuntimeError("Could not restrict private runtime directory permissions")
    else:
        if path.stat().st_uid != os.geteuid():
            raise ValueError("Runtime directory belongs to another user")
        path.chmod(0o700)
    return path


@contextlib.contextmanager
def lock(path, enabled=True):
    if not enabled:
        yield
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError(
                "Another platform command holds the lock; stop the watcher first"
            ) from exc
        try:
            yield
        finally:
            if sys.platform == "win32":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def hidden_prompt(label):
    if not sys.stdin.isatty():
        raise ValueError("Run this command in an interactive terminal for its hidden prompt")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        return getpass.getpass(label).strip()
