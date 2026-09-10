"""The same isolated application tests run locally and on GitHub's Linux runner."""

import argparse
import json
import os
import re
import secrets
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, cwd=ROOT, **kwargs)


def test():
    project = "previewforge-ci-" + secrets.token_hex(6)
    # Random per-run project name and tmpfs test DB; existing M1/staging data are untouched.
    with tempfile.TemporaryDirectory(prefix=project + "-") as directory:
        password = Path(directory) / "db_password"
        password.write_text(secrets.token_hex(32))
        env = {
            **os.environ,
            "PREVIEWFORGE_RUNTIME_DIR": Path(directory).as_posix(),
            "PREVIEWFORGE_COMPOSE_PROJECT": project,
        }
        compose = [
            "docker",
            "compose",
            "--project-name",
            project,
            "--file",
            ROOT / "compose.yaml",
            "--profile",
            "test",
        ]
        try:
            run(*compose, "build", "tests", env=env)
            run(*compose, "up", "--detach", "--wait", "--wait-timeout", "120", "test-db", env=env)
            for command in (
                ["ruff", "check", "--no-cache", "."],
                ["ruff", "format", "--check", "--no-cache", "."],
                [],
            ):
                run(*compose, "run", "--rm", "--no-deps", "tests", *command, env=env)
        finally:
            run(*compose, "down", "--remove-orphans", env=env)


def build(source_sha, output):
    if not re.fullmatch(r"[a-f0-9]{40}", source_sha):
        raise ValueError("An exact source commit is required")
    head = run("git", "rev-parse", "HEAD", capture_output=True, text=True).stdout.strip()
    dirty = run("git", "status", "--porcelain", capture_output=True, text=True).stdout.strip()
    if source_sha != head or dirty:
        raise ValueError("Build needs a clean checkout at the exact source SHA")
    output = Path(output).resolve()
    if output.is_relative_to(ROOT):
        raise ValueError("Keep build artifacts outside the checkout")
    output.mkdir(parents=True, exist_ok=True)
    tag = "previewforge-demo:" + source_sha
    run(
        "docker",
        "build",
        "--target",
        "runtime",
        "--build-arg",
        "SOURCE_SHA=" + source_sha,
        "--tag",
        tag,
        ROOT / "previewforge-demo",
    )
    run("docker", "save", "--output", output / "image.tar", tag)
    (output / "receipt.json").write_text(json.dumps({"sourceSha": source_sha, "tag": tag}) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["test", "build"])
    parser.add_argument("--source-sha")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.action == "test":
        test()
    else:
        if not args.source_sha or not args.output:
            parser.error("build requires --source-sha and --output")
        build(args.source_sha, args.output)
