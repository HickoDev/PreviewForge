"""Portable Compose demo commands. Runtime credentials remain outside the checkout."""

import argparse
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

import host

ROOT = Path(__file__).resolve().parents[1]


def run(*args, cwd=ROOT, timeout=900):
    subprocess.run([str(a) for a in args], cwd=cwd, check=True, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["up", "test", "verify", "seed", "down", "status", "logs", "restart-api"]
    )
    parser.add_argument("--project-name", default="previewforge-m1")
    args = parser.parse_args()
    host.require_supported()
    if not re.fullmatch(r"previewforge-m1(?:-[a-z0-9-]+)?", args.project_name):
        parser.error("Use previewforge-m1 or a previewforge-m1-<suffix> project name")
    runtime = host.validate_runtime(host.home() / "runtime" / args.project_name, ROOT)
    os.environ["PREVIEWFORGE_RUNTIME_DIR"] = runtime.as_posix()
    os.environ["PREVIEWFORGE_COMPOSE_PROJECT"] = args.project_name
    head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"], cwd=ROOT, capture_output=True, text=True
    )
    sha = head.stdout.strip() if head.returncode == 0 else "local-uncommitted"
    if head.returncode == 0 and subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT):
        sha += "-dirty"
    os.environ["PREVIEWFORGE_SOURCE_SHA"] = sha

    def compose(*parts):
        run(
            "docker",
            "compose",
            "--project-name",
            args.project_name,
            "--file",
            ROOT / "compose.yaml",
            *parts,
        )

    def initialize():
        host.private_directory(runtime, ROOT)
        password = runtime / "db_password"
        if not password.exists():
            existing = subprocess.run(
                ["docker", "volume", "inspect", args.project_name + "_postgres-data"],
                capture_output=True,
            )
            if existing.returncode == 0:
                raise RuntimeError(
                    "Database volume exists but its password is missing; restore the original runtime"
                )
            with password.open("x", encoding="utf-8") as stream:
                stream.write(secrets.token_hex(32))
        # Compose binds the file into UID 10001/70 containers. Its 0700 parent
        # protects it on Linux; a 0600 file would be unreadable inside those containers.
        if os.name != "nt":
            password.chmod(0o444)

    def start():
        initialize()
        compose("up", "--build", "--detach", "--wait", "--wait-timeout", "180", "api", "floci")
        print("API docs: http://127.0.0.1:8000/docs\nFloci: http://127.0.0.1:4566")

    def test():
        initialize()
        compose("--profile", "test", "build", "tests")
        try:
            compose(
                "--profile", "test", "up", "--detach", "--wait", "--wait-timeout", "120", "test-db"
            )
            for command in (
                ["ruff", "check", "--no-cache", "."],
                ["ruff", "format", "--check", "--no-cache", "."],
                [],
            ):
                compose("--profile", "test", "run", "--rm", "--no-deps", "tests", *command)
        finally:
            compose("--profile", "test", "rm", "--stop", "--force", "test-db")

    with host.lock(runtime / "operation.lock", enabled=args.action not in {"status", "logs"}):
        if args.action == "up":
            start()
        elif args.action == "test":
            test()
        elif args.action == "verify":
            start()
            test()
            venv = runtime / "host-venv"
            python = host.venv_python(venv)
            if not python.exists():
                run(sys.executable, "-m", "venv", venv)
            run(
                python,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--timeout",
                "120",
                "--require-hashes",
                "-r",
                ROOT / "previewforge-demo/requirements.lock",
            )
            run(
                python,
                "-m",
                "app.floci_smoke",
                "--endpoint",
                "http://127.0.0.1:4566",
                cwd=ROOT / "previewforge-demo",
            )
            compose(
                "exec",
                "-T",
                "api",
                "python",
                "-m",
                "app.floci_smoke",
                "--endpoint",
                "http://floci:4566",
            )
            run(
                python,
                ROOT / "scripts/verify.py",
                "--compose",
                ROOT / "compose.yaml",
                "--project",
                args.project_name,
                "--expected-sha",
                sha,
            )
        elif args.action == "seed":
            compose("exec", "-T", "api", "python", "-m", "app.seed")
        elif args.action == "down":
            compose("--profile", "test", "down", "--remove-orphans")
        elif args.action == "status":
            compose("ps", "--all")
        elif args.action == "logs":
            compose("logs", "--tail", "50", "api", "migrate", "floci")
        else:
            compose("restart", "api")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
