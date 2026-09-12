"""Configure private GHCR pull credentials from stdin, never from argv or Git."""

import base64
import json
import os
import re
import subprocess
import sys

import platform_local as p
import previews as v


def registry(*, interactive=False):
    # Verify the normal active account before accepting any additional credential.
    p.gh("auth", "status", "--active", "--hostname", "github.com")
    token = (
        p.host.hidden_prompt("GHCR read-only token (hidden): ")
        if interactive
        else sys.stdin.read().strip()
    )
    if not re.fullmatch(r"ghp_[A-Za-z0-9]{30,}", token):
        raise ValueError("Use a personal access token (classic), entered only at the hidden prompt")
    environment = {**os.environ, "GH_TOKEN": token}
    auth = subprocess.run(
        ["gh", "auth", "status", "--active", "--hostname", "github.com"],
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )
    details = auth.stdout + auth.stderr
    if auth.returncode or not re.search(
        r"account HickoDev \(GH_TOKEN\)\s+- Active account: true", details
    ):
        raise ValueError("The supplied token must authenticate as HickoDev")
    scopes = re.search(r"Token scopes:([^\n]+)", details)
    values = set(re.findall(r"'([^']+)'", scopes.group(1))) if scopes else set()
    if values != {"read:packages"}:
        raise ValueError(
            "Use a separate token with ONLY read:packages; broader credentials are refused"
        )
    existing = v.optional("secret", "previewforge-ghcr", "argocd", sensitive=True)
    if existing and existing["metadata"].get("labels", {}).get("previewforge.io/owner") != v.OWNER:
        raise ValueError("Existing registry secret has another owner")
    docker_config = {
        "auths": {"ghcr.io": {"auth": base64.b64encode(("HickoDev:" + token).encode()).decode()}}
    }
    p.k(
        "apply",
        "-f",
        "-",
        input=json.dumps(
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {
                    "name": "previewforge-ghcr",
                    "namespace": "argocd",
                    "labels": {"previewforge.io/owner": v.OWNER},
                },
                "type": "kubernetes.io/dockerconfigjson",
                "data": {
                    ".dockerconfigjson": base64.b64encode(
                        json.dumps(docker_config).encode()
                    ).decode()
                },
            }
        ),
        quiet=True,
        sensitive=True,
    )
    print(
        "Configured the HickoDev read-only GHCR credential in the local cluster. No token was printed or saved to Git."
    )


if __name__ == "__main__":
    try:
        if sys.argv[1:] not in (["registry"], ["registry", "--stdin"]):
            raise ValueError(
                "Run python scripts/configure_remote.py registry for the hidden prompt"
            )
        registry(interactive=sys.argv[1:] == ["registry"])
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
