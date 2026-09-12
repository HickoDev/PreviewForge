"""Private local runtime, pinned tools, process locks and shared Floci routing."""

import contextlib
import hashlib
import ipaddress
import json
import os
import re
import secrets
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

import platform_local as p

OWNER = "previewforge-m5"
BASE = Path(os.environ.get("PREVIEWFORGE_RUNTIME_DIR", str(p.RUNTIME.parent)))
RUNTIME = BASE / OWNER
TOOLS = p.TOOLS.parent / "milestone5"
PYTHON = p.host.venv_python(TOOLS / "venv")
TF = TOOLS / p.host.executable("terraform")
LOCK = json.loads((p.ROOT / "bootstrap/milestone5-tools.lock.json").read_text())
FLOCI = "previewforge-m1-floci-1"
NAMESPACE = "previewforge-system"
ENDPOINT = "http://127.0.0.1:4566"
POD_ENDPOINT = "http://floci.previewforge-system.svc.cluster.local:4566"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def environment_name(value):
    require(
        re.fullmatch(r"staging|local|test|preview-[1-9][0-9]{0,8}", value),
        "Invalid export environment",
    )
    return value


def validate_runtime():
    path = RUNTIME.resolve()
    require(
        path.name == OWNER
        and "onedrive" not in str(path).lower()
        and not path.is_relative_to(p.ROOT.resolve())
        and path != Path.home(),
        "Keep the dedicated Milestone 5 runtime outside Git and cloud-synced folders",
    )
    return path


def save(path, value):
    require(path.resolve().is_relative_to(validate_runtime()), "Runtime write escaped its root")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def settings(create=False):
    path = validate_runtime() / "installation.json"
    if not path.exists():
        require(create, "Run resources.py up first")
        save(path, {"owner": OWNER, "installation": secrets.token_hex(16)})
    result = json.loads(path.read_text())
    require(result.get("owner") == OWNER, "Runtime belongs to another installation")
    return result


@contextlib.contextmanager
def lock(path):
    with p.host.lock(path):
        yield


def install():
    validate_runtime()
    p.host.require_supported()
    p.host.private_directory(RUNTIME, p.ROOT)
    TOOLS.mkdir(parents=True, exist_ok=True)
    version = LOCK["terraform"]["version"]
    filename = f"terraform_{version}_{p.host.platform_key().replace('-', '_')}.zip"
    archive = TOOLS / filename
    if (
        not archive.exists()
        or hashlib.sha256(archive.read_bytes()).hexdigest()
        != LOCK["terraform"]["archives"][filename]
    ):
        urllib.request.urlretrieve(
            f"https://releases.hashicorp.com/terraform/{version}/{filename}", archive
        )
    require(
        hashlib.sha256(archive.read_bytes()).hexdigest() == LOCK["terraform"]["archives"][filename],
        "Terraform checksum mismatch",
    )
    with zipfile.ZipFile(archive) as source:
        binary = source.read(p.host.executable("terraform"))
        if not TF.exists() or TF.read_bytes() != binary:
            TF.write_bytes(binary)
        TF.chmod(0o755)
    dependencies = p.ROOT / "previewforge-demo/requirements.lock"
    digest = hashlib.sha256(dependencies.read_bytes()).hexdigest()
    marker = TOOLS / "requirements.sha256"
    if not PYTHON.exists():
        p.run(sys.executable, "-m", "venv", TOOLS / "venv")
    if not marker.exists() or marker.read_text() != digest:
        p.run(
            PYTHON,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--require-hashes",
            "-r",
            dependencies,
            timeout=600,
        )
        marker.write_text(digest)


def inspect_floci():
    result = subprocess.run(
        ["docker", "inspect", FLOCI], capture_output=True, text=True, timeout=30
    )
    if result.returncode:
        require("No such" in result.stderr, "Cannot inspect the Floci container")
        return None
    value = json.loads(result.stdout)[0]
    labels = value["Config"].get("Labels", {})
    require(
        labels.get("com.docker.compose.project") == "previewforge-m1"
        and labels.get("com.docker.compose.service") == "floci",
        "Floci container has another owner",
    )
    require(
        value["Config"]["Image"] == LOCK["floci"],
        "Unexpected shared Floci image; preserve it and review",
    )
    return value


def bootstrap_floci():
    inspect_floci()
    p.run(
        "docker",
        "compose",
        "--file",
        p.ROOT / "bootstrap/floci/compose.yaml",
        "up",
        "--detach",
        "--wait",
        "--wait-timeout",
        "120",
        "floci",
        timeout=180,
    )
    value = inspect_floci()
    ports = value["HostConfig"]["PortBindings"]["4566/tcp"]
    require(
        ports == [{"HostIp": "127.0.0.1", "HostPort": "4566"}],
        "Floci must publish only loopback port 4566",
    )
    return value


def route_floci():
    require(
        p.owned_container(p.NODE, "io.x-k8s.kind.cluster"),
        "Retained PreviewForge kind node is required",
    )
    value = inspect_floci()
    require(value and value["State"]["Running"], "Start the shared Floci container first")
    if "kind" not in value["NetworkSettings"]["Networks"]:
        p.run("docker", "network", "connect", "kind", FLOCI)
        value = inspect_floci()
    address = value["NetworkSettings"]["Networks"]["kind"]["IPAddress"]
    network = json.loads(p.run("docker", "network", "inspect", "kind", quiet=True))[0]
    require(
        any(
            ipaddress.ip_address(address) in ipaddress.ip_network(x["Subnet"])
            for x in network["IPAM"]["Config"]
            if ":" not in x["Subnet"]
        ),
        "Floci IP is not in the local kind network",
    )
    import previews as v

    for kind, name in [
        ("namespace", NAMESPACE),
        ("service", "floci"),
        ("endpointslice", "previewforge-floci"),
    ]:
        current = v.optional(kind, name, NAMESPACE)
        if current:
            require(
                current["metadata"].get("labels", {}).get("previewforge.io/owner") == OWNER,
                "Floci routing resource has another owner",
            )
    labels = {"previewforge.io/owner": OWNER}
    p.apply(
        {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": NAMESPACE, "labels": labels}}
    )
    p.apply(
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": "floci", "namespace": NAMESPACE, "labels": labels},
            "spec": {
                "type": "ClusterIP",
                "ports": [{"name": "http", "port": 4566, "targetPort": 4566}],
            },
        }
    )
    p.apply(
        {
            "apiVersion": "discovery.k8s.io/v1",
            "kind": "EndpointSlice",
            "metadata": {
                "name": "previewforge-floci",
                "namespace": NAMESPACE,
                "labels": {
                    **labels,
                    "kubernetes.io/service-name": "floci",
                    "endpointslice.kubernetes.io/managed-by": "previewforge-m5",
                },
            },
            "addressType": "IPv4",
            "ports": [{"name": "http", "protocol": "TCP", "port": 4566}],
            "endpoints": [{"addresses": [address], "conditions": {"ready": True}}],
        }
    )
    previous = RUNTIME / "emulator.json"
    before = json.loads(previous.read_text()) if previous.exists() else {}
    result = {
        "containerId": value["Id"],
        "address": address,
        "startedAt": value["State"]["StartedAt"],
    }
    save(previous, result)
    if before != result:
        print(
            "Refreshed the owned Floci pod route; Terraform refresh will check actual resources.",
            flush=True,
        )
