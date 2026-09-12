"""Windows/Linux local Kubernetes bootstrap; no remote writes or cloud clients."""

import argparse
import base64
import contextlib
import hashlib
import json
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from http.client import HTTPException
from pathlib import Path

import host

ROOT = Path(__file__).resolve().parents[1]
GITHUB_COMMIT_IDENTITY = {
    "name": "HickoDev",
    "email": "157824011+HickoDev@users.noreply.github.com",
}
OWNER = "previewforge-m2"
RUNTIME = host.home() / "runtime" / OWNER
TOOLS = host.home() / "tools/milestone2"
KUBECONFIG = RUNTIME / "kubeconfig"
SOURCE = RUNTIME / "source"
BARE = RUNTIME / "git/previewforge.git"
NODE = OWNER + "-control-plane"
GIT_CONTAINER = OWNER + "-git"
POSTGRES_IMAGE = (
    "postgres:17.9-alpine@sha256:c7526c0f6c3f30260a563d7bcf8ad778effac59a44f8ffa86678c35418338609"
)
IMAGE_REPOSITORY = "docker.io/previewforge/demo"
LOCK = json.loads((ROOT / "bootstrap/tools.lock.json").read_text())


def run(*args, cwd=None, input=None, timeout=300, quiet=False, sensitive=False):
    result = subprocess.run(
        [str(a) for a in args],
        cwd=cwd,
        input=input,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )
    if result.returncode:
        detail = (
            "[sensitive output omitted]" if sensitive else (result.stdout + result.stderr)[-6000:]
        )
        raise RuntimeError(f"{Path(str(args[0])).name} failed ({result.returncode}): {detail}")
    if not quiet and result.stdout.strip():
        print(result.stdout.strip(), flush=True)
    return result.stdout.strip()


def gh(*args):
    # Account checks precede every GitHub operation, including upstream downloads.
    auth = subprocess.run(
        ["gh", "auth", "status", "--hostname", "github.com"], capture_output=True, text=True
    )
    if auth.returncode or not re.search(
        r"account HickoDev \([^\r\n]+\)\s+- Active account: true",
        auth.stdout + auth.stderr,
    ):
        raise RuntimeError("GitHub downloads require the active gh account HickoDev.")
    return run("gh", *args, quiet=True, timeout=300)


def checked_download(path, expected, fetch):
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        print(f"Downloading pinned {path.name} ...", flush=True)
        data = fetch()
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError(f"Checksum mismatch for {path.name}; refusing to use it.")
        path.write_bytes(data)


def install_tools():
    host.require_supported()
    key = host.platform_key()
    TOOLS.mkdir(parents=True, exist_ok=True)
    spec = LOCK["kind"]["platforms"][key]
    kind_download = TOOLS / spec["asset"]
    if (
        not kind_download.exists()
        or hashlib.sha256(kind_download.read_bytes()).hexdigest() != spec["sha256"]
    ):
        gh(
            "release",
            "download",
            LOCK["kind"]["version"],
            "--repo",
            "kubernetes-sigs/kind",
            "--pattern",
            spec["asset"],
            "--dir",
            TOOLS,
            "--clobber",
        )
    if hashlib.sha256(kind_download.read_bytes()).hexdigest() != spec["sha256"]:
        raise RuntimeError("kind checksum mismatch")
    destination = TOOLS / host.executable("kind")
    shutil.copyfile(kind_download, destination)
    destination.chmod(0o755)
    archive_name = "helm.zip" if sys.platform == "win32" else "helm.tar.gz"
    for name, filename in [("helm", archive_name), ("kubectl", host.executable("kubectl"))]:
        spec = LOCK[name]["platforms"][key]
        checked_download(
            TOOLS / filename,
            spec["sha256"],
            lambda spec=spec: urllib.request.urlopen(spec["url"], timeout=120).read(),
        )
    if sys.platform == "win32":
        with zipfile.ZipFile(TOOLS / archive_name) as archive:
            binary = archive.read("windows-amd64/helm.exe")
    else:
        with tarfile.open(TOOLS / archive_name, "r:gz") as archive:
            binary = archive.extractfile("linux-amd64/helm").read()
    (TOOLS / host.executable("helm")).write_bytes(binary)
    for name in ["helm", "kubectl"]:
        (TOOLS / host.executable(name)).chmod(0o755)
    argo = LOCK["argocd"]
    checked_download(
        TOOLS / "argocd-install.yaml",
        argo["sha256"],
        lambda: (
            gh(
                "api",
                f"repos/argoproj/argo-cd/contents/manifests/install.yaml?ref={argo['commit']}",
                "-H",
                "Accept: application/vnd.github.raw+json",
            )
            + "\n"
        ).encode(),
    )


def k(*args, **kwargs):
    return run(
        TOOLS / host.executable("kubectl"),
        "--kubeconfig",
        KUBECONFIG,
        "--context",
        "kind-" + OWNER,
        *args,
        **kwargs,
    )


def get(kind, name=None, namespace="staging"):
    args = ["-n", namespace, "get", kind]
    if name:
        args.append(name)
    return json.loads(k(*args, "-o", "json", quiet=True))


def apply(obj):
    # Never pass secret values in process arguments or print manifests.
    return k("apply", "-f", "-", input=json.dumps(obj), quiet=True)


def patch(kind, name, value, namespace="staging"):
    return k(
        "-n",
        namespace,
        "patch",
        kind,
        name,
        "--type=merge",
        "--patch",
        json.dumps(value),
        quiet=True,
    )


def wait_for(description, predicate, timeout=300):
    end = time.monotonic() + timeout
    last_error = ""
    next_notice = time.monotonic() + 30
    while time.monotonic() < end:
        try:
            result = predicate()
            if result:
                return result
        except (RuntimeError, urllib.error.URLError, HTTPException, TimeoutError, KeyError) as exc:
            last_error = str(exc)[-500:]
        if time.monotonic() >= next_notice:
            print(f"Waiting: {description} ...", flush=True)
            next_notice += 30
        time.sleep(2)
    raise RuntimeError(f"Timed out: {description}. {last_error}")


def owned_container(name, label):
    result = subprocess.run(["docker", "inspect", name], capture_output=True, text=True)
    if result.returncode:
        return None
    info = json.loads(result.stdout)[0]
    if info["Config"].get("Labels", {}).get(label) != OWNER:
        raise RuntimeError(f"Refusing to change container {name}: ownership does not match.")
    return info


def ensure_cluster():
    info = owned_container(NODE, "io.x-k8s.kind.cluster")
    if info:
        run("docker", "start", NODE)
        run(
            TOOLS / host.executable("kind"),
            "export",
            "kubeconfig",
            "--name",
            OWNER,
            "--kubeconfig",
            KUBECONFIG,
        )
    else:
        if (SOURCE / ".git").exists():
            raise RuntimeError(
                "The retained staging node is missing. Restore the original node/data or "
                "plan an explicit rebuild; refusing to replace persistent staging silently."
            )
        run(
            TOOLS / host.executable("kind"),
            "create",
            "cluster",
            "--name",
            OWNER,
            "--config",
            ROOT / "bootstrap/kind/cluster.yaml",
            "--kubeconfig",
            KUBECONFIG,
            "--wait",
            "180s",
            timeout=900,
        )
    # After a stopped node restarts, the API can briefly answer Forbidden while
    # its RBAC cache loads. Retry the same local context; never change credentials.
    wait_for(
        "local Kubernetes API and node readiness",
        lambda: any(
            condition["type"] == "Ready" and condition["status"] == "True"
            for condition in get("node", NODE)["status"].get("conditions", [])
        ),
        180,
    )
    for namespace in ["argocd", "staging"]:
        apply(
            {
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {
                    "name": namespace,
                    "labels": {"previewforge.io/owner": OWNER},
                },
            }
        )
    apply(
        {
            "apiVersion": "storage.k8s.io/v1",
            "kind": "StorageClass",
            "metadata": {
                "name": "previewforge-retain",
                "labels": {"previewforge.io/owner": OWNER},
            },
            "provisioner": "rancher.io/local-path",
            "reclaimPolicy": "Retain",
            "volumeBindingMode": "WaitForFirstConsumer",
        }
    )


def ensure_password():
    password = RUNTIME / "db_password"
    if not password.exists():
        # Do not silently generate a new password for an existing initialized DB.
        if get("pvc")["items"]:
            raise RuntimeError(
                "Staging PVC exists but runtime password is missing; restore the original password."
            )
        password.write_text(secrets.token_hex(32), encoding="utf-8")
    result = k(
        "-n",
        "staging",
        "get",
        "secret",
        "staging-db",
        "--ignore-not-found",
        "-o",
        "json",
        quiet=True,
        sensitive=True,
    )
    if result:
        existing = base64.b64decode(json.loads(result)["data"]["db_password"]).decode()
        if not secrets.compare_digest(existing, password.read_text()):
            raise RuntimeError("Existing staging Secret does not match its runtime password.")
    else:
        k(
            "-n",
            "staging",
            "create",
            "secret",
            "generic",
            "staging-db",
            "--from-file=db_password=" + str(password),
            sensitive=True,
        )


def local_git(*args):
    return run("git", "-C", SOURCE, *args, quiet=True)


def require_clean_fixture():
    if (SOURCE / ".git").exists() and local_git(
        "status", "--porcelain", "--untracked-files=all", "--ignored"
    ):
        raise RuntimeError(
            "The local Git fixture has uncommitted or ignored files. Preserve/commit your "
            "edits and move private files outside the fixture before verification or building."
        )


def commit(message, paths):
    # Commit only this operation's inputs, even if an unrelated file was staged.
    local_git("--literal-pathspecs", "add", "--all", "--", *paths)
    if local_git("--literal-pathspecs", "diff", "--cached", "--name-only", "--", *paths):
        local_git(
            "--literal-pathspecs",
            "-c",
            "user.name=PreviewForge local fixture",
            "-c",
            "user.email=fixture@previewforge.invalid",
            "commit",
            "--only",
            "-m",
            message,
            "--",
            *paths,
        )
    return local_git("rev-parse", "HEAD")


def is_snapshot_input(name):
    path = Path(name)
    parts = path.parts
    if name in {
        "charts/demo-app/Chart.yaml",
        "charts/demo-app/values.yaml",
        "charts/demo-app/values.schema.json",
        "previewforge-demo/Dockerfile",
        "previewforge-demo/.dockerignore",
        "previewforge-demo/requirements.lock",
        "previewforge-demo/alembic.ini",
        "gitops/staging/values.yaml",
        "gitops/preview-values.yaml",
    }:
        return True
    if any(part.startswith(".") or part == "__pycache__" for part in parts):
        return False
    if name.startswith("charts/demo-app/templates/"):
        return path.suffix in {".yaml", ".tpl"}
    return (
        name.startswith(("previewforge-demo/app/", "previewforge-demo/migrations/"))
        and path.suffix == ".py"
    )


def snapshot():
    require_clean_fixture()
    SOURCE.mkdir(parents=True, exist_ok=True)
    if not (SOURCE / ".git").exists():
        run("git", "init", "--initial-branch=main", SOURCE)
        local_git("config", "core.autocrlf", "false")
    candidates = run(
        "git",
        "-C",
        ROOT,
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
        quiet=True,
    ).split("\0")
    names = {name for name in candidates if is_snapshot_input(name) and (ROOT / name).is_file()}
    previous = {name for name in local_git("ls-files", "-z").split("\0") if is_snapshot_input(name)}
    # Preserve the verifier's committed synthetic release marker between refreshes.
    previous.discard("previewforge-demo/app/release_fixture.py")
    for name in sorted(previous - names):
        target = SOURCE / name
        if not target.resolve().is_relative_to(SOURCE.resolve()):
            raise RuntimeError("Snapshot deletion target escaped the local fixture.")
        target.unlink(missing_ok=True)
    for name in sorted(names):
        src = ROOT / name
        if src.is_symlink() or not src.resolve().is_relative_to(ROOT):
            raise RuntimeError("Snapshot inputs must be ordinary files inside the checkout.")
        target = SOURCE / name
        if not target.resolve().is_relative_to(SOURCE.resolve()):
            raise RuntimeError("Snapshot destination escaped the local fixture.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(src.read_bytes())
    (SOURCE / "fixture-origin.json").write_text(
        json.dumps(
            {
                "platform_head": run("git", "-C", ROOT, "rev-parse", "HEAD", quiet=True),
                "platform_dirty": bool(run("git", "-C", ROOT, "status", "--porcelain", quiet=True)),
                "scope": "allowlisted local source snapshot; no GitHub deployment",
            },
            indent=2,
        )
        + "\n"
    )
    return commit(
        "Snapshot local application and staging chart",
        sorted(names | previous | {"fixture-origin.json"}),
    )


def load_image(source_sha):
    require_clean_fixture()
    if source_sha != local_git("rev-parse", "HEAD"):
        raise RuntimeError("Build source SHA must match the clean fixture HEAD.")
    tag = IMAGE_REPOSITORY + ":" + source_sha
    print(f"Building/loading local source {source_sha} ...", flush=True)
    run(
        "docker",
        "build",
        "--target",
        "runtime",
        "--build-arg",
        "SOURCE_SHA=" + source_sha,
        "--tag",
        tag,
        SOURCE / "previewforge-demo",
        timeout=900,
        quiet=True,
    )
    run(TOOLS / host.executable("kind"), "load", "docker-image", "--name", OWNER, tag, timeout=300)
    # Read the actual imported containerd manifest digest; Docker config IDs are not manifests.
    listing = run("docker", "exec", NODE, "ctr", "-n", "k8s.io", "images", "ls", quiet=True)
    row = next(line.split() for line in listing.splitlines() if line.startswith(tag + " "))
    digest = row[2]
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise RuntimeError("Could not identify the loaded image's manifest digest.")
    reference = IMAGE_REPOSITORY + "@" + digest
    run(
        "docker",
        "exec",
        NODE,
        "ctr",
        "-n",
        "k8s.io",
        "images",
        "tag",
        "--force",
        tag,
        reference,
    )
    return {
        "image": {
            "repository": IMAGE_REPOSITORY,
            "digest": digest,
            "pullPolicy": "Never",
        },
        "sourceSha": source_sha,
    }


def publish_local():
    # This copies refs between two filesystem directories; there is no remote push.
    if not BARE.exists():
        BARE.parent.mkdir(parents=True, exist_ok=True)
        run("git", "clone", "--bare", SOURCE, BARE)
    else:
        run("git", "--git-dir", BARE, "fetch", str(SOURCE), "main:main")
    return local_git("rev-parse", "HEAD")


def deploy_record(record, message):
    (SOURCE / "gitops/staging/image.json").write_text(json.dumps(record, indent=2) + "\n")
    sha = commit(message, ["gitops/staging/image.json"])
    publish_local()
    return sha


def ensure_git_server():
    info = owned_container(GIT_CONTAINER, "previewforge.owner")
    if info:
        mount = next((m for m in info["Mounts"] if m["Destination"] == "/git"), None)
        if not mount or mount["RW"] or info["Config"]["Image"] != LOCK["gitServerImage"]:
            raise RuntimeError("Local Git server must have a read-only repository mount.")
        run("docker", "start", GIT_CONTAINER)
    else:
        run(
            "docker",
            "run",
            "--detach",
            "--name",
            GIT_CONTAINER,
            "--label",
            "previewforge.owner=" + OWNER,
            "--network",
            "kind",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "10001:10001",
            "--mount",
            f"type=bind,source={BARE.parent},target=/git,readonly",
            "--entrypoint",
            "/usr/bin/git",
            LOCK["gitServerImage"],
            "-c",
            "safe.directory=/git/previewforge.git",
            "daemon",
            "--reuseaddr",
            "--base-path=/git",
            "--export-all",
            "--strict-paths",
            "--disable=receive-pack",
            "--forbid-override=receive-pack",
            "--verbose",
            "--listen=0.0.0.0",
            "--port=9418",
            "/git/previewforge.git",
        )
    info = owned_container(GIT_CONTAINER, "previewforge.owner")
    address = info["NetworkSettings"]["Networks"]["kind"]["IPAddress"]
    # Kubernetes DNS does not resolve Docker container aliases. Discover the IP each bootstrap.
    apply(
        {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": GIT_CONTAINER, "namespace": "argocd"},
            "spec": {"ports": [{"name": "git", "port": 9418, "targetPort": 9418}]},
        }
    )
    apply(
        {
            "apiVersion": "discovery.k8s.io/v1",
            "kind": "EndpointSlice",
            "metadata": {
                "name": GIT_CONTAINER,
                "namespace": "argocd",
                "labels": {
                    "kubernetes.io/service-name": GIT_CONTAINER,
                    "endpointslice.kubernetes.io/managed-by": OWNER,
                },
            },
            "addressType": "IPv4",
            "ports": [{"name": "git", "port": 9418, "protocol": "TCP"}],
            "endpoints": [{"addresses": [address], "conditions": {"ready": True}}],
        }
    )


def install_argo():
    print("Installing pinned Argo CD and waiting for its controllers ...", flush=True)
    k(
        "apply",
        "--server-side",
        "-n",
        "argocd",
        "-f",
        TOOLS / "argocd-install.yaml",
        quiet=True,
    )
    # A short polling interval makes local demonstrations quick. No webhook/inbound route.
    apply(
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": "argocd-cm",
                "namespace": "argocd",
                "labels": {
                    "app.kubernetes.io/name": "argocd-cm",
                    "app.kubernetes.io/part-of": "argocd",
                },
            },
            "data": {
                "timeout.reconciliation": "15s",
                "timeout.reconciliation.jitter": "0s",
            },
        }
    )
    for resource in [
        "deployment/argocd-repo-server",
        "deployment/argocd-server",
        "deployment/argocd-redis",
        "statefulset/argocd-application-controller",
    ]:
        k("-n", "argocd", "rollout", "status", resource, "--timeout=600s", timeout=630)


def wait_staging(revision=None):
    def ready():
        app = get("application", "staging", "argocd")
        status = app.get("status", {})
        return (
            status.get("sync", {}).get("status") == "Synced"
            and status.get("health", {}).get("status") == "Healthy"
            and status.get("operationState", {}).get("phase") == "Succeeded"
            and not app.get("operation")
            and (revision is None or status["sync"].get("revision") == revision)
        )

    wait_for("Argo CD staging Synced/Healthy at the intended Git revision", ready, 420)


def up():
    install_tools()
    ensure_cluster()
    argo_exists = k(
        "get", "crd", "applications.argoproj.io", "--ignore-not-found", "-o", "name", quiet=True
    )
    current = (
        k(
            "-n",
            "argocd",
            "get",
            "application",
            "staging",
            "--ignore-not-found",
            "-o",
            "json",
            quiet=True,
        )
        if argo_exists
        else ""
    )
    if (
        current
        and json.loads(current)["spec"]["source"]["repoURL"]
        != "git://previewforge-m2-git.argocd.svc.cluster.local:9418/previewforge.git"
    ):
        raise RuntimeError(
            "Staging uses a remote Git source. Local bootstrap will not replace its configuration."
        )
    ensure_password()
    if not (SOURCE / "gitops/staging/image.json").exists():
        record = load_image(snapshot())
        deploy_record(record, "Deploy initial local staging image by digest")
    else:
        # Ordinary startup preserves the last desired release and synthetic database.
        publish_local()
    # Pull the pinned upstream image through the node's CRI. Importing Docker's
    # partial multi-platform index can fail on missing non-host architecture blobs.
    run("docker", "exec", NODE, "crictl", "pull", POSTGRES_IMAGE, timeout=600, quiet=True)
    ensure_git_server()
    install_argo()
    k("apply", "-f", ROOT / "gitops/platform/staging.yaml")
    wait_staging(local_git("rev-parse", "HEAD"))
    print(
        "Staging is Synced/Healthy. Run python scripts/platform_local.py forward for http://127.0.0.1:18000/docs",
        flush=True,
    )


def start():
    """Resume the retained cluster without replacing its local or remote Git source."""
    if not owned_container(NODE, "io.x-k8s.kind.cluster"):
        raise RuntimeError("No retained PreviewForge node; use initial setup or restore its data.")
    install_tools()
    ensure_cluster()
    app = get("application", "staging", "argocd")
    if app["spec"]["source"]["repoURL"].startswith("git://previewforge-m2-git."):
        ensure_git_server()
    wait_staging()
    k("-n", "staging", "rollout", "status", "deployment/demo-api", "--timeout=180s")
    # After a node restart, Kubernetes can briefly report readiness from before
    # shutdown. Probe the running API and its database before declaring success.
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    with forward(port=port):
        wait_for(
            "resumed API/database readiness",
            lambda: http("/health/ready", port=port)[0] == 200,
            120,
        )
    print("Retained staging resumed. Start the remote preview watcher if GitHub mode is active.")


@contextlib.contextmanager
def forward(resource="service/demo-api", port=18000, namespace="staging", target_port=8000):
    args = [
        str(TOOLS / host.executable("kubectl")),
        "--kubeconfig",
        str(KUBECONFIG),
        "--context",
        "kind-" + OWNER,
        "-n",
        namespace,
        "port-forward",
        "--address",
        "127.0.0.1",
        resource,
        f"{port}:{target_port}",
    ]
    log = (RUNTIME / f"port-forward-{port}.log").open("w")
    process = subprocess.Popen(args, stdout=log, stderr=log, **host.background_options())
    try:

        def alive():
            if process.poll() is not None:
                raise RuntimeError("Port-forward exited; see its runtime log (port may be in use).")
            # Do not accidentally test another process already listening on this port.
            if (
                f"Forwarding from 127.0.0.1:{port}"
                not in (RUNTIME / f"port-forward-{port}.log").read_text()
            ):
                return False
            return http("/health/live", port=port)[0] == 200

        wait_for("loopback port-forward", alive, 30)
        yield process
    finally:
        process.terminate()
        process.wait(timeout=10)
        log.close()


def wait_forward(process):
    # An infinite Popen.wait() delays Python's Ctrl+C handling on Windows.
    while process.poll() is None:
        time.sleep(0.25)


def http(path, method="GET", payload=None, port=18000):
    body = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        response = urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            request, timeout=10
        )
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        data = response.read().decode()
        return response.status, json.loads(data) if data.startswith(("{", "[")) else data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action", choices=["up", "start", "verify", "status", "forward", "stop", "publish-local"]
    )
    args = parser.parse_args()
    host.require_supported()
    host.private_directory(RUNTIME, ROOT)
    with host.lock(RUNTIME / "operation.lock", enabled=args.action not in {"status", "forward"}):
        if args.action == "up":
            up()
        elif args.action == "start":
            start()
        elif args.action == "verify":
            require_clean_fixture()
            up()
            from verify_kubernetes import verify

            verify()
        elif args.action == "status":
            k("-n", "argocd", "get", "applications")
            k("-n", "staging", "get", "pods,services,pvc,jobs")
        elif args.action == "forward":
            print("API: http://127.0.0.1:18000/docs (Ctrl+C stops forwarding)", flush=True)
            with forward() as process:
                wait_forward(process)
        elif args.action == "publish-local":
            publish_local()
            wait_staging(local_git("rev-parse", "HEAD"))
        elif args.action == "stop":
            for name, label in [
                (GIT_CONTAINER, "previewforge.owner"),
                (NODE, "io.x-k8s.kind.cluster"),
            ]:
                if owned_container(name, label):
                    run("docker", "stop", name)
            print(
                "Stopped only Milestone 2 containers. Cluster, Git and database storage retained."
            )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted.")
        sys.exit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
