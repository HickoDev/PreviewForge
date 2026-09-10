"""Local monitoring setup and forwarding; remote fault exercises require explicit flags."""

import argparse
import contextlib
import json
import secrets
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

import platform_local as p
import previews as v

OWNER = "previewforge-m4"
NAMESPACE = "observability"
CHART = p.ROOT / "observability"


def image():
    # Read the pinned chart image without a host YAML dependency.
    return next(
        line.split(": ", 1)[1].strip()
        for line in (CHART / "values.yaml").read_text().splitlines()
        if line.startswith("  prometheus:")
    )


def http(path, port=19090, payload=None):
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}" + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
        request, timeout=15
    ) as r:
        data = r.read().decode()
        return json.loads(data) if "json" in r.headers.get("Content-Type", "") else data


@contextlib.contextmanager
def forward(service="prometheus", port=19090):
    if service not in {"prometheus", "grafana"} or not 1024 <= port <= 65535:
        raise ValueError("Use prometheus/grafana and a non-privileged local port")
    target, ready = (9090, "/-/ready") if service == "prometheus" else (3000, "/api/health")
    path = p.RUNTIME / f"monitoring-forward-{port}.log"
    with path.open("w") as log:
        process = subprocess.Popen(
            [
                str(p.TOOLS / "kubectl.exe"),
                "--kubeconfig",
                str(p.KUBECONFIG),
                "--context",
                "kind-" + p.OWNER,
                "-n",
                NAMESPACE,
                "port-forward",
                "--address",
                "127.0.0.1",
                "service/" + service,
                f"{port}:{target}",
            ],
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:

            def alive():
                if process.poll() is not None:
                    raise ValueError("Monitoring forward exited; check its runtime log/port")
                if f"Forwarding from 127.0.0.1:{port}" not in path.read_text():
                    return False
                return bool(http(ready, port))

            p.wait_for("local monitoring forward", alive, 45)
            yield process
        finally:
            process.terminate()
            process.wait(timeout=10)


def query(expression):
    result = http("/api/v1/query?" + urllib.parse.urlencode({"query": expression}))
    if result["status"] != "success":
        raise ValueError("Prometheus query failed")
    return result["data"]["result"]


def wait_ready():
    def ready():
        app = p.get("application", "observability", "argocd")
        status = app.get("status", {})
        return (
            status.get("sync", {}).get("status") == "Synced"
            and status.get("health", {}).get("status") == "Healthy"
            and status.get("operationState", {}).get("phase") == "Succeeded"
            and not app.get("operation")
        )

    p.wait_for("monitoring Synced/Healthy", ready, 420)


def up():
    staging = p.get("application", "staging", "argocd")
    if staging["spec"]["source"]["repoURL"] != v.REMOTE_REPO:
        raise ValueError("Monitoring activation requires the configured remote Milestone 3 cluster")
    current = v.optional("namespace", NAMESPACE)
    if current and current["metadata"].get("labels", {}).get("previewforge.io/owner") != OWNER:
        raise ValueError("Observability namespace has another owner")
    p.apply(
        {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": NAMESPACE, "labels": {"previewforge.io/owner": OWNER}},
        }
    )
    secret = v.optional("secret", "previewforge-grafana", NAMESPACE, sensitive=True)
    if secret:
        if secret["metadata"].get("labels", {}).get("previewforge.io/owner") != OWNER:
            raise ValueError("Grafana secret has another owner")
    else:
        p.k(
            "create",
            "-f",
            "-",
            input=json.dumps(
                {
                    "apiVersion": "v1",
                    "kind": "Secret",
                    "metadata": {
                        "name": "previewforge-grafana",
                        "namespace": NAMESPACE,
                        "labels": {"previewforge.io/owner": OWNER},
                    },
                    "type": "Opaque",
                    "stringData": {"admin-password": secrets.token_urlsafe(48)},
                }
            ),
            quiet=True,
            sensitive=True,
        )
    existing = v.optional("application", "observability")
    if existing and existing["spec"]["project"] != "previewforge-observability":
        raise ValueError("Observability Application belongs to another project")
    p.k("apply", "-f", p.ROOT / "gitops/platform/observability.yaml", quiet=True)
    wait_ready()
    print("Monitoring ready. Run: python scripts/monitoring.py forward --service grafana")


def check():
    helm = shutil.which("helm") or str(p.TOOLS / "helm.exe")
    p.run(helm, "lint", CHART, "--namespace", NAMESPACE)
    p.run(helm, "template", "monitoring", CHART, "--namespace", NAMESPACE, quiet=True)
    for args in (
        ("check", "rules", "/work/alerts/rules.yml"),
        ("test", "rules", "/work/tests/rules.test.yml"),
    ):
        p.run(
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "/bin/promtool",
            "-v",
            str(CHART) + ":/work:ro",
            image(),
            *args,
            timeout=180,
        )
    p.run(
        "docker",
        "run",
        "--rm",
        "--entrypoint",
        "/bin/promtool",
        "-v",
        str(CHART / "prometheus/prometheus.yml") + ":/etc/prometheus/prometheus.yml:ro",
        "-v",
        str(CHART / "alerts/rules.yml") + ":/etc/prometheus/rules.yml:ro",
        image(),
        "check",
        "config",
        "--syntax-only",
        "/etc/prometheus/prometheus.yml",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "check", "status", "forward", "verify", "recover"])
    parser.add_argument("--service", choices=["grafana", "prometheus"], default="grafana")
    parser.add_argument("--port", type=int)
    parser.add_argument("--allow-faults", action="store_true")
    parser.add_argument("--allow-github-writes", action="store_true")
    parser.add_argument("--trials", type=int, default=2)
    args = parser.parse_args()
    if args.action == "forward":
        port = args.port or (13000 if args.service == "grafana" else 19090)
        with forward(args.service, port) as process:
            suffix = "/d/previewforge" if args.service == "grafana" else "/alerts"
            print(f"http://127.0.0.1:{port}{suffix} (Ctrl+C to stop)", flush=True)
            process.wait()
        return
    if args.action == "check":
        check()
        return
    if args.action == "status":
        p.k("-n", "argocd", "get", "application", "observability")
        p.k("-n", NAMESPACE, "get", "pods,services,pvc")
        return
    import msvcrt

    with (p.RUNTIME / "operation.lock").open("a+b") as lock:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        if args.action == "up":
            up()
        else:
            if not args.allow_faults or not args.allow_github_writes:
                raise ValueError("Exercises require --allow-faults --allow-github-writes")
            if not 1 <= args.trials <= 3:
                raise ValueError("Use 1-3 bounded trials")
            from verify_monitoring import recover, verify

            (recover if args.action == "recover" else verify)(args.trials)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
