"""Local, trusted assistant setup and diagnostic commands. No NVIDIA calls by default."""

import argparse
import base64
import hashlib
import json
import re
import secrets
import sys
import urllib.error
import urllib.request
from contextlib import contextmanager

import platform_local as p
import previews as v

OWNER = "previewforge-m6"
NAMESPACE = "previewforge-ai"
NAME = "previewforge-assistant"
RUNTIME = p.host.home() / "runtime" / OWNER
POLICY = RUNTIME / "policy.json"
IMAGE = "docker.io/previewforge/assistant"
SHA = re.compile(r"^[a-f0-9]{40}$")
ENVIRONMENT = re.compile(r"^(staging|preview-[1-9][0-9]{0,8})$")


def runtime():
    p.host.require_supported()
    if RUNTIME.name != OWNER:
        raise ValueError("Assistant runtime has an unexpected owner")
    return p.host.private_directory(RUNTIME, p.ROOT)


@contextmanager
def exercise_lock():
    with p.host.lock(p.RUNTIME / "operation.lock"):
        yield


def owned(kind, name, namespace=NAMESPACE):
    obj = v.optional(kind, name, namespace, sensitive=(kind == "secret"))
    if obj and obj["metadata"].get("labels", {}).get("previewforge.io/owner") != OWNER:
        raise ValueError(f"Refusing another owner's {kind}/{name}")
    return obj


def apply_owned(kind, name, spec, namespace=NAMESPACE, api="v1"):
    owned(kind.lower(), name, namespace)
    obj = {
        "apiVersion": api,
        "kind": kind,
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {"previewforge.io/owner": OWNER},
        },
        **spec,
    }
    p.k("apply", "-f", "-", input=json.dumps(obj), quiet=True, sensitive=(kind == "Secret"))


def ensure_namespace():
    owned("namespace", NAMESPACE)
    p.apply(
        {
            "apiVersion": "v1",
            "kind": "Namespace",
            "metadata": {"name": NAMESPACE, "labels": {"previewforge.io/owner": OWNER}},
        }
    )


def read_policy():
    return json.loads(POLICY.read_text()) if POLICY.exists() else {"environments": {}}


def save_policy(value):
    POLICY.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    apply_owned("ConfigMap", "previewforge-ai-policy", {"data": {"policy.json": json.dumps(value)}})


def grant(environment, entry=None, base_revision=None):
    if not ENVIRONMENT.fullmatch(environment):
        raise ValueError("Not an approved environment name")
    ns = p.get("namespace", environment)
    if environment == "staging":
        if ns["metadata"].get("labels", {}).get("previewforge.io/owner") != p.OWNER:
            raise ValueError("Staging namespace ownership mismatch")
    else:
        v.owned(ns, environment)
    app = p.get("application", environment, "argocd")
    if app["spec"]["destination"]["namespace"] != environment:
        raise ValueError("Argo destination mismatch")
    if entry is None:
        if app["spec"]["source"]["repoURL"] != v.REMOTE_REPO:
            raise ValueError("Use configured GitHub environments")
        path = (
            "gitops/staging/image.json"
            if environment == "staging"
            else f"gitops/previews/{environment}.json"
        )
        raw = json.loads(p.gh("api", f"repos/HickoDev/PreviewForge/contents/{path}?ref=main"))
        record = json.loads(base64.b64decode(raw["content"]))
        image = record["image"]
        entry = {
            "source_sha": record["sourceSha"],
            "image": image["repository"] + "@" + image["digest"],
            "repo_url": v.REMOTE_REPO,
            "config_revision": None,
            "diff": "",
        }
        revision = app.get("status", {}).get("sync", {}).get("revision")
        if base_revision:
            from assistant_evidence import configuration_diff

            entry.update(
                config_revision=revision,
                known_good_revision=base_revision,
                diff=configuration_diff(base_revision, revision),
            )
        else:
            previous = read_policy()["environments"].get(environment, {})
            if (
                previous.get("source_sha") == entry["source_sha"]
                and previous.get("config_revision") == revision
            ):
                for key in ("config_revision", "known_good_revision", "diff"):
                    if key in previous:
                        entry[key] = previous[key]
    deployment = p.get("deployment", "demo-api", environment)
    api = next(
        c for c in deployment["spec"]["template"]["spec"]["containers"] if c["name"] == "api"
    )
    if not SHA.fullmatch(entry["source_sha"]) or api["image"] != entry["image"]:
        raise ValueError("Source record and observed deployment image differ; wait for rollout")
    # Roles are namespace-scoped. There are no Secret/exec/attach/mutation permissions.
    rules = [
        {
            "apiGroups": ["apps"],
            "resources": ["deployments"],
            "resourceNames": ["demo-api"],
            "verbs": ["get"],
        },
        {
            "apiGroups": [""],
            "resources": ["services"],
            "resourceNames": ["demo-postgres"],
            "verbs": ["get"],
        },
        {"apiGroups": [""], "resources": ["pods", "events"], "verbs": ["get", "list"]},
        {"apiGroups": [""], "resources": ["pods/log"], "verbs": ["get"]},
    ]
    apply_owned("Role", NAME, {"rules": rules}, environment, "rbac.authorization.k8s.io/v1")
    subject = [{"kind": "ServiceAccount", "name": NAME, "namespace": NAMESPACE}]
    ref = {"apiGroup": "rbac.authorization.k8s.io", "kind": "Role", "name": NAME}
    apply_owned(
        "RoleBinding",
        NAME,
        {"subjects": subject, "roleRef": ref},
        environment,
        "rbac.authorization.k8s.io/v1",
    )
    argo_role = NAME + "-" + environment
    apply_owned(
        "Role",
        argo_role,
        {
            "rules": [
                {
                    "apiGroups": ["argoproj.io"],
                    "resources": ["applications"],
                    "resourceNames": [environment],
                    "verbs": ["get"],
                }
            ]
        },
        "argocd",
        "rbac.authorization.k8s.io/v1",
    )
    apply_owned(
        "RoleBinding",
        argo_role,
        {"subjects": subject, "roleRef": {**ref, "name": argo_role}},
        "argocd",
        "rbac.authorization.k8s.io/v1",
    )
    value = read_policy()
    value["environments"][environment] = {**entry, "namespace_uid": ns["metadata"]["uid"]}
    save_policy(value)
    return entry


def revoke(environment):
    if not ENVIRONMENT.fullmatch(environment):
        raise ValueError("Invalid environment")
    value = read_policy()
    value["environments"].pop(environment, None)
    save_policy(value)
    for namespace, name in [(environment, NAME), ("argocd", NAME + "-" + environment)]:
        for kind in ("rolebinding", "role"):
            obj = owned(kind, name, namespace)
            if obj:
                p.k("delete", kind, name, "-n", namespace, "--wait=true", quiet=True)


def build_image():
    root = p.ROOT / "ai-assistant"
    inputs = [root / "Dockerfile", root / "requirements.lock"]
    inputs += sorted((root / "app").glob("*.py")) + sorted((root / "evaluations").rglob("*.json"))
    digest = hashlib.sha256()
    for file in inputs:
        if file.is_symlink() or not file.resolve().is_relative_to(root):
            raise ValueError("Unsafe image input")
        digest.update(file.relative_to(root).as_posix().encode() + b"\0" + file.read_bytes())
    tag = IMAGE + ":" + digest.hexdigest()[:40]
    p.run(
        "docker",
        "build",
        "--target",
        "runtime",
        "--tag",
        tag,
        "--build-arg",
        "SOURCE_SHA=" + p.run("git", "rev-parse", "HEAD", quiet=True),
        root,
        timeout=900,
        quiet=True,
    )
    p.run(
        p.TOOLS / p.host.executable("kind"),
        "load",
        "docker-image",
        "--name",
        p.OWNER,
        tag,
        timeout=300,
        quiet=True,
    )
    rows = p.run("docker", "exec", p.NODE, "ctr", "-n", "k8s.io", "images", "ls", quiet=True)
    manifest = next(line.split()[2] for line in rows.splitlines() if line.startswith(tag + " "))
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", manifest):
        raise ValueError("Invalid loaded manifest digest")
    p.run(
        "docker",
        "exec",
        p.NODE,
        "ctr",
        "-n",
        "k8s.io",
        "images",
        "tag",
        "--force",
        tag,
        IMAGE + "@" + manifest,
        quiet=True,
    )
    return manifest


def up(live=False, model="nvidia/nemotron-3-super-120b-a12b", local_chart=False):
    runtime()
    ensure_namespace()
    grant("staging")
    if not re.fullmatch(r"[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+", model):
        raise ValueError("Invalid NVIDIA model ID")
    if live and not owned("secret", "previewforge-nvidia"):
        raise ValueError("Configure the NVIDIA key privately first")
    if live and not owned("secret", "previewforge-ai-access"):
        token = secrets.token_urlsafe(40)
        apply_owned(
            "Secret", "previewforge-ai-access", {"type": "Opaque", "stringData": {"token": token}}
        )
    digest = build_image()
    revision_input = POLICY.read_bytes()
    if live:
        for secret_name in ("previewforge-nvidia", "previewforge-ai-access"):
            revision_input += owned("secret", secret_name)["metadata"]["resourceVersion"].encode()
    values = {
        "image.digest": digest,
        "mode": "nvidia" if live else "mock",
        "liveEnabled": str(live).lower(),
        "model": model,
        "policyRevision": hashlib.sha256(revision_input).hexdigest()[:16],
    }
    if local_chart:
        if v.optional("application", NAME):
            raise ValueError("Argo already owns the assistant; use ordinary up")
        args = []
        for name, value in values.items():
            args.extend(["--set", name + "=" + value])
        rendered = p.run(
            p.TOOLS / p.host.executable("helm"),
            "template",
            "assistant",
            p.ROOT / "charts/ai-assistant",
            "--namespace",
            NAMESPACE,
            *args,
            quiet=True,
        )
        p.k("apply", "-n", NAMESPACE, "-f", "-", input=rendered, quiet=True)
    else:
        owned("application", NAME, "argocd")
        owned("appproject", NAME, "argocd")
        # Apply the completed manifest once, including its machine-local digest,
        # so Argo never sees an intermediate empty image reference.
        rendered = p.k(
            "create",
            "--dry-run=client",
            "--validate=false",
            "-f",
            p.ROOT / "gitops/platform/assistant.yaml",
            "-o",
            "json",
            quiet=True,
        )
        # kubectl emits concatenated JSON documents for multi-document YAML,
        # rather than consistently wrapping them in a Kubernetes List.
        objects = []
        decoder = json.JSONDecoder()
        remaining = rendered.strip()
        while remaining:
            obj, end = decoder.raw_decode(remaining)
            objects.extend(obj["items"] if obj.get("kind") == "List" else [obj])
            remaining = remaining[end:].lstrip()
        for obj in objects:
            if obj["kind"] == "Application":
                obj["spec"]["source"]["helm"]["parameters"] = [
                    {"name": k, "value": val} for k, val in values.items()
                ]
            p.apply(obj)

    def rolled_out():
        deployment = v.optional("deployment", NAME, NAMESPACE)
        if not deployment:
            return False
        status = deployment.get("status", {})
        return (
            deployment["spec"]["template"]["spec"]["containers"][0]["image"] == IMAGE + "@" + digest
            and deployment["spec"].get("replicas") == 1
            and status.get("observedGeneration", 0) >= deployment["metadata"]["generation"]
            and status.get("updatedReplicas") == 1
            and status.get("availableReplicas") == 1
        )

    p.wait_for("assistant intended image ready", rolled_out, 180)
    p.k("rollout", "status", "deployment/" + NAME, "-n", NAMESPACE, "--timeout=180s", quiet=True)
    with forward() as _:
        p.wait_for(
            "assistant HTTP readiness",
            lambda: http("/health/ready")["mode"] == ("nvidia" if live else "mock"),
            90,
        )
    if not local_chart:

        def synced():
            status = p.get("application", NAME, "argocd").get("status", {})
            return (
                status.get("sync", {}).get("status") == "Synced"
                and status.get("health", {}).get("status") == "Healthy"
            )

        p.wait_for("assistant Argo Synced/Healthy", synced, 120)
    print(
        "Assistant ready in "
        + (
            "NVIDIA mode; each request still requires --allow-live."
            if live
            else "mock mode. No hosted inference calls enabled."
        )
    )


@contextmanager
def forward(port=18080):
    if not 1024 <= port <= 65535:
        raise ValueError("Use a non-privileged local port")
    with p.forward("service/" + NAME, port, NAMESPACE, target_port=8080) as process:
        yield process


def http(path, payload=None, live=False, port=18080):
    headers = {"Content-Type": "application/json"}
    if live:
        obj = owned("secret", "previewforge-ai-access")
        if not obj:
            raise ValueError("Live diagnostic access token is not configured")
        headers["Authorization"] = "Bearer " + base64.b64decode(obj["data"]["token"]).decode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}" + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers=headers,
    )
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            request, timeout=125
        ) as response:
            raw = response.read(131073)
            if len(raw) > 131072:
                raise ValueError("Diagnostic response exceeds limit")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Diagnostic HTTP {exc.code}; check mode, environment authorization and source SHA"
        ) from None


def configure_key():
    runtime()
    ensure_namespace()
    # getpass refuses chat/argv input. A key is never written to a local env file.
    if not sys.stdin.isatty():
        raise ValueError("Run this command yourself in an interactive terminal")
    key = p.host.hidden_prompt(
        "NVIDIA API key (hidden; stored only in the trusted local Kubernetes Secret): "
    ).strip()
    if not key or len(key) > 2048 or re.search(r"\s", key):
        raise ValueError("Invalid key format")
    owned("secret", "previewforge-nvidia")
    # Server-side apply avoids embedding a duplicate value in last-applied annotations.
    p.k(
        "apply",
        "--server-side",
        "--field-manager=previewforge-key-setup",
        "-f",
        "-",
        input=json.dumps(
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {
                    "name": "previewforge-nvidia",
                    "namespace": NAMESPACE,
                    "labels": {"previewforge.io/owner": OWNER},
                },
                "type": "Opaque",
                "data": {"api-key": base64.b64encode(key.encode()).decode()},
            }
        ),
        quiet=True,
        sensitive=True,
    )
    print("Key configured privately. It has not been validated and hosted calls remain opt-in.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "up",
            "forward",
            "status",
            "authorize",
            "revoke",
            "diagnose",
            "configure-key",
            "test",
            "evaluate",
            "live-smoke",
            "live-evaluate",
            "verify",
            "recover",
        ],
    )
    parser.add_argument("--environment", default="staging")
    parser.add_argument("--source-sha")
    parser.add_argument(
        "--base-revision",
        help="Optional exact known-good Git configuration commit for a bounded port diff",
    )
    parser.add_argument("--fixture")
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="Send minimized synthetic evidence to NVIDIA; account limits and terms apply",
    )
    parser.add_argument("--model", default="nvidia/nemotron-3-super-120b-a12b")
    parser.add_argument(
        "--local-chart",
        action="store_true",
        help="Development bootstrap before the chart is pushed",
    )
    parser.add_argument("--allow-faults", action="store_true")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--trials", type=int, default=1)
    args = parser.parse_args()
    if args.action == "test":
        p.run(
            "docker",
            "build",
            "--target",
            "test",
            "--tag",
            "previewforge-ai-tests",
            p.ROOT / "ai-assistant",
            timeout=600,
            quiet=True,
        )
        p.run("docker", "run", "--rm", "--network", "none", "previewforge-ai-tests", timeout=180)
        return
    runtime()
    if args.action == "up":
        up(args.allow_live, args.model, args.local_chart)
    elif args.action == "configure-key":
        configure_key()
    elif args.action == "authorize":
        grant(args.environment, base_revision=args.base_revision)
        print(
            "Authorized "
            + args.environment
            + "; allow up to 60 seconds for the mounted policy refresh."
        )
    elif args.action == "revoke":
        revoke(args.environment)
    elif args.action == "forward":
        with forward(args.port) as process:
            print(f"http://127.0.0.1:{args.port}/docs (Ctrl+C to stop)", flush=True)
            p.wait_forward(process)
    elif args.action == "status":
        with forward(args.port):
            print(
                json.dumps(
                    {
                        "health": http("/health/ready", port=args.port),
                        "environments": http("/environments", port=args.port),
                    },
                    indent=2,
                )
            )
    elif args.action in {"evaluate", "live-evaluate", "live-smoke"}:
        if args.action != "evaluate" and not args.allow_live:
            raise ValueError(
                "Hosted tests require --allow-live; minimized synthetic fixtures leave the laptop and consume account quota"
            )
        from evaluate_assistant import evaluate

        evaluate(args.action, args.trials, args.port)
    elif args.action == "verify":
        if not args.allow_faults:
            raise ValueError("The disposable wrong-port exercise requires --allow-faults")
        from verify_assistant import verify

        with exercise_lock():
            verify()
    elif args.action == "recover":
        from verify_assistant import recovery

        with exercise_lock():
            recovery()
    else:
        if args.fixture:
            query = {
                "environment": "preview-42",
                "source_sha": "a" * 40,
                "fixture": args.fixture,
                "allow_live": args.allow_live,
            }
        else:
            entry = grant(args.environment, base_revision=args.base_revision)
            query = {
                "environment": args.environment,
                "source_sha": args.source_sha or entry["source_sha"],
                "allow_live": args.allow_live,
            }
        with forward(args.port):
            report = http("/diagnoses", query, args.allow_live, args.port)
        destination = runtime() / ("diagnosis-" + report["metadata"]["request_id"] + ".json")
        destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        print("Saved sanitized report: " + str(destination))
        if report["error"]:
            raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
