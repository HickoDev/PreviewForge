"""Actual Git -> Argo -> wrong-port deployment -> read-only mock diagnosis -> recovery."""

import json
import re
import shutil
from datetime import UTC, datetime

import assistant as a
import platform_local as p
import previews as v

ENVIRONMENT = "preview-600006"
SERVER = "previewforge-m6-git"
PROJECT = "previewforge-diagnostic-exercise"
REPO = f"git://{SERVER}.argocd.svc.cluster.local:9418/previewforge.git"
JOURNAL = a.RUNTIME / "exercise-recovery.json"


def commit(source, message):
    p.run("git", "-C", source, "add", "charts", quiet=True)
    p.run(
        "git",
        "-C",
        source,
        "-c",
        "user.name=PreviewForge fixture",
        "-c",
        "user.email=fixture@previewforge.invalid",
        "commit",
        "-m",
        message,
        quiet=True,
    )
    return p.run("git", "-C", source, "rev-parse", "HEAD", quiet=True)


def safe_diff(source, good, bad):
    if not a.SHA.fullmatch(good) or not a.SHA.fullmatch(bad):
        raise ValueError("Exact local Git revisions required")
    path = "charts/demo-app/values.yaml"
    for sha in (good, bad):
        size = int(p.run("git", "-C", source, "cat-file", "-s", sha + ":" + path, quiet=True))
        if size > 65536:
            raise ValueError("Configuration blob exceeds evidence limit")
    diff = p.run(
        "git",
        "-C",
        source,
        "diff",
        "--no-ext-diff",
        "--no-textconv",
        "--unified=0",
        good,
        bad,
        "--",
        path,
        quiet=True,
    )
    lines = []
    for line in diff.splitlines():
        match = re.fullmatch(r"([+-])\s*port:\s*(\d{1,5})\s*", line)
        if match and 1 <= int(match[2]) <= 65535:
            lines.append(f"{match[1]} DATABASE_PORT={int(match[2])}")
    return "\n".join(lines)


def recovery():
    if not JOURNAL.exists():
        return
    journal = json.loads(JOURNAL.read_text())
    if journal.get("owner") != a.OWNER or journal.get("namespace") != ENVIRONMENT:
        raise ValueError("Unrecognized assistant recovery journal")
    a.revoke(ENVIRONMENT)
    app = v.optional("application", ENVIRONMENT)
    if app:
        if app["metadata"].get("labels", {}).get("previewforge.io/test") != a.OWNER:
            raise ValueError("Exercise Application ownership changed")
        p.k("delete", "application", ENVIRONMENT, "-n", "argocd", "--wait=false", quiet=True)
        p.wait_for(
            "exercise Application removed", lambda: not v.optional("application", ENVIRONMENT), 180
        )
    ns = v.optional("namespace", ENVIRONMENT)
    if ns:
        if ns["metadata"].get("labels", {}).get("previewforge.io/test") != a.OWNER or (
            journal.get("namespace_uid") and ns["metadata"]["uid"] != journal["namespace_uid"]
        ):
            raise ValueError("Exercise namespace ownership changed")
        v.REMOTE = True
        v.delete_namespace({"name": ENVIRONMENT, "uid": ns["metadata"]["uid"]})
    for kind, name in [("appproject", PROJECT), ("service", SERVER), ("endpointslice", SERVER)]:
        if a.owned(kind, name, "argocd"):
            p.k("delete", kind, name, "-n", "argocd", quiet=True)
    raw = p.run(
        "docker",
        "ps",
        "-a",
        "--filter",
        "name=^/" + SERVER + "$",
        "--format",
        "{{.Names}}",
        quiet=True,
    )
    if raw:
        info = json.loads(p.run("docker", "inspect", SERVER, quiet=True))[0]
        if info["Config"].get("Labels", {}).get("previewforge.owner") != a.OWNER:
            raise ValueError("Exercise Git container ownership mismatch")
        p.run("docker", "rm", "--force", SERVER, quiet=True)
    JOURNAL.unlink()


def verify():
    a.runtime()
    v.REMOTE = True
    if JOURNAL.exists():
        raise ValueError("Pending exercise recovery; run assistant.py recover first")
    if v.optional("namespace", ENVIRONMENT) or v.optional("application", ENVIRONMENT):
        raise ValueError("Exercise name already exists; preserving it")
    with a.forward():
        if a.http("/health/ready")["mode"] != "mock":
            raise ValueError("This verification requires mock mode")
    p.wait_staging()
    entry = a.grant("staging")
    pvc = p.get("pvc", "demo-postgres")["metadata"]["uid"]
    with p.forward(port=18081):
        before = p.http("/tasks", port=18081)[1]
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "provider": "mock",
        "source_sha": entry["source_sha"],
        "image": entry["image"],
        "staging_pvc": pvc,
        "checks": [],
    }
    output = a.RUNTIME / "milestone-6-cluster.json"

    def passed(name, **details):
        report["checks"].append({"name": name, "at": datetime.now(UTC).isoformat(), **details})
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print("PASS: " + name, flush=True)

    source = a.RUNTIME / ("exercise-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    source.mkdir()
    chart = source / "source/charts/demo-app"
    shutil.copytree(p.ROOT / "charts/demo-app", chart)
    source_git = source / "source"
    p.run("git", "init", "--initial-branch=main", source_git, quiet=True)
    # Only the disposable fixture chart changes the API port; migration and DB
    # continue using 5432. No failure override is added to production templates.
    api = chart / "templates/api.yaml"
    api.write_text(
        api.read_text().replace(
            'include "demo.environment" .', 'include "demo.diagnosticEnvironment" .'
        )
    )
    helpers = chart / "templates/_helpers.tpl"
    helpers.write_text(
        helpers.read_text()
        + '\n{{- define "demo.diagnosticEnvironment" -}}\n{{- $context := dict "Values" (deepCopy .Values) "Release" .Release -}}\n{{- $_ := set $context.Values.database "port" .Values.diagnostic.port -}}\n{{- include "demo.environment" $context -}}\n{{- end -}}\n'
    )
    values = chart / "values.yaml"
    values.write_text(values.read_text() + "\ndiagnostic:\n  port: 5432\n")
    good = commit(source_git, "fixture: known-good API database port")
    bare = source / "git/previewforge.git"
    bare.parent.mkdir()
    p.run("git", "clone", "--bare", source_git, bare, quiet=True)
    journal = {"owner": a.OWNER, "namespace": ENVIRONMENT, "source": str(source)}
    JOURNAL.write_text(json.dumps(journal))
    try:
        p.apply(
            {
                "apiVersion": "v1",
                "kind": "Namespace",
                "metadata": {
                    "name": ENVIRONMENT,
                    "labels": {
                        **v.LABELS,
                        "previewforge.io/environment": ENVIRONMENT,
                        "previewforge.io/test": a.OWNER,
                    },
                },
            }
        )
        v.ensure_namespace({"environment": ENVIRONMENT})
        journal["namespace_uid"] = p.get("namespace", ENVIRONMENT)["metadata"]["uid"]
        JOURNAL.write_text(json.dumps(journal))
        p.run(
            "docker",
            "run",
            "--detach",
            "--name",
            SERVER,
            "--label",
            "previewforge.owner=" + a.OWNER,
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
            f"type=bind,source={bare.parent},target=/git,readonly",
            "--entrypoint",
            "/usr/bin/git",
            p.LOCK["gitServerImage"],
            "-c",
            "safe.directory=/git/previewforge.git",
            "daemon",
            "--reuseaddr",
            "--base-path=/git",
            "--export-all",
            "--strict-paths",
            "--disable=receive-pack",
            "--forbid-override=receive-pack",
            "--listen=0.0.0.0",
            "--port=9418",
            "/git/previewforge.git",
            quiet=True,
        )
        info = json.loads(p.run("docker", "inspect", SERVER, quiet=True))[0]
        address = info["NetworkSettings"]["Networks"]["kind"]["IPAddress"]
        a.apply_owned(
            "Service",
            SERVER,
            {"spec": {"ports": [{"name": "git", "port": 9418, "targetPort": 9418}]}},
            "argocd",
        )
        a.apply_owned(
            "EndpointSlice",
            SERVER,
            {
                "addressType": "IPv4",
                "ports": [{"name": "git", "port": 9418, "protocol": "TCP"}],
                "endpoints": [{"addresses": [address], "conditions": {"ready": True}}],
            },
            "argocd",
            "discovery.k8s.io/v1",
        )
        p.k(
            "label",
            "endpointslice",
            SERVER,
            "-n",
            "argocd",
            "kubernetes.io/service-name=" + SERVER,
            quiet=True,
        )
        a.apply_owned(
            "AppProject",
            PROJECT,
            {
                "spec": {
                    "sourceRepos": [REPO],
                    "destinations": [
                        {"namespace": ENVIRONMENT, "server": "https://kubernetes.default.svc"}
                    ],
                    "clusterResourceWhitelist": [],
                    "namespaceResourceWhitelist": [
                        {"group": "", "kind": x}
                        for x in ("Service", "PersistentVolumeClaim", "ResourceQuota")
                    ]
                    + [{"group": "apps", "kind": x} for x in ("Deployment", "StatefulSet")]
                    + [{"group": "batch", "kind": "Job"}],
                }
            },
            "argocd",
            "argoproj.io/v1alpha1",
        )
        repository, digest = entry["image"].split("@")
        parameters = {
            "environment": ENVIRONMENT,
            "preview.enabled": "true",
            "seed": "true",
            "image.repository": repository,
            "image.digest": digest,
            "image.pullPolicy": "IfNotPresent",
            "imagePullSecrets[0].name": "previewforge-ghcr",
            "database.existingSecret": "preview-db",
            "database.retain": "false",
            "database.storageClass": "previewforge-disposable",
            "exports.enabled": "false",
        }
        p.apply(
            {
                "apiVersion": "argoproj.io/v1alpha1",
                "kind": "Application",
                "metadata": {
                    "name": ENVIRONMENT,
                    "namespace": "argocd",
                    "labels": {
                        **v.LABELS,
                        "previewforge.io/environment": ENVIRONMENT,
                        "previewforge.io/test": a.OWNER,
                    },
                    "finalizers": ["resources-finalizer.argocd.argoproj.io"],
                },
                "spec": {
                    "project": PROJECT,
                    "source": {
                        "repoURL": REPO,
                        "targetRevision": "main",
                        "path": "charts/demo-app",
                        "helm": {
                            "releaseName": "demo",
                            "parameters": [
                                {"name": k, "value": val} for k, val in parameters.items()
                            ],
                        },
                    },
                    "destination": {
                        "server": "https://kubernetes.default.svc",
                        "namespace": ENVIRONMENT,
                    },
                    "syncPolicy": {"automated": {"enabled": True, "prune": True, "selfHeal": True}},
                },
            }
        )
        record = {"image": {"repository": repository, "digest": digest}}
        v.wait_preview(ENVIRONMENT, record)
        passed("known-good isolated GitOps deployment", config_revision=good)
        values.write_text(
            values.read_text().replace("diagnostic:\n  port: 5432", "diagnostic:\n  port: 5433")
        )
        bad = commit(source_git, "fixture: change API port to 5433 while PostgreSQL stays on 5432")
        p.run("git", "--git-dir", bare, "fetch", source_git, "main:main", quiet=True)
        p.k(
            "annotate",
            "application",
            ENVIRONMENT,
            "-n",
            "argocd",
            "argocd.argoproj.io/refresh=hard",
            "--overwrite",
            quiet=True,
        )

        def failed_rollout():
            deployment = p.get("deployment", "demo-api", ENVIRONMENT)
            env = deployment["spec"]["template"]["spec"]["containers"][0]["env"]
            pods = p.get("pods", namespace=ENVIRONMENT)["items"]
            return (
                any(x.get("name") == "DATABASE_PORT" and x.get("value") == "5433" for x in env)
                and any(
                    x.get("reason") == "Unhealthy"
                    for x in p.get("events", namespace=ENVIRONMENT)["items"]
                )
                and any(
                    any(
                        c["name"] == "api" and not c["ready"]
                        for c in pod.get("status", {}).get("containerStatuses", [])
                    )
                    for pod in pods
                )
            )

        p.wait_for("actual wrong-port rollout and failed readiness", failed_rollout, 180)
        diff = safe_diff(source_git, good, bad)
        if "+ DATABASE_PORT=5433" not in diff:
            raise ValueError("Missing actual Git configuration diff")
        a.grant(
            ENVIRONMENT,
            {
                **entry,
                "repo_url": REPO,
                "config_revision": bad,
                "known_good_revision": good,
                "diff": diff,
            },
        )
        with a.forward():

            def diagnosed():
                result = a.http(
                    "/diagnoses", {"environment": ENVIRONMENT, "source_sha": entry["source_sha"]}
                )
                (a.RUNTIME / "last-exercise-diagnosis.json").write_text(
                    json.dumps(result, indent=2) + "\n", encoding="utf-8"
                )
                if not result.get("diagnosis") or not result["diagnosis"]["hypotheses"]:
                    return False
                if result["diagnosis"]["hypotheses"][0]["cause"] != "Database port mismatch":
                    return False
                ids = set(result["diagnosis"]["hypotheses"][0]["evidence_ids"])
                if not {"diff", "log", "service", "deployment"} <= {
                    e["source"] for e in result["evidence"] if e["id"] in ids
                }:
                    return False
                report["wrong_port_diagnosis"] = result
                return True

            p.wait_for("correlated wrong-port diagnosis with Git/log citations", diagnosed, 120)
        passed(
            "real wrong-port failure diagnosed from scoped runtime evidence",
            failing_config_revision=bad,
        )
        # Kubernetes authorizer verifies the actual service account's boundary.
        account = f"system:serviceaccount:{a.NAMESPACE}:{a.NAME}"
        checks = [
            ("get", "pods", ENVIRONMENT, "yes"),
            ("get", "pods/log", ENVIRONMENT, "yes"),
            ("get", "secrets", ENVIRONMENT, "no"),
            ("list", "secrets", a.NAMESPACE, "no"),
            ("create", "pods/exec", ENVIRONMENT, "no"),
            ("create", "pods/attach", ENVIRONMENT, "no"),
            ("patch", "deployments", ENVIRONMENT, "no"),
            ("delete", "pods", ENVIRONMENT, "no"),
            ("get", "pods", "default", "no"),
            ("impersonate", "users", ENVIRONMENT, "no"),
        ]
        permissions = []
        for verb, resource, ns, expected in checks:
            try:
                observed = p.k(
                    "auth", "can-i", verb, resource, "-n", ns, "--as", account, quiet=True
                )
            except RuntimeError as exc:
                if expected != "no" or not re.search(r"failed \(1\): no(?:\s|$)", str(exc)):
                    raise
                observed = "no"
            if observed.strip() != expected:
                raise ValueError("Unexpected assistant RBAC capability")
            permissions.append(
                {"verb": verb, "resource": resource, "namespace": ns, "allowed": observed == "yes"}
            )
        passed("read-only namespace RBAC", permissions=permissions)
        p.run(
            "git",
            "-C",
            source_git,
            "-c",
            "user.name=PreviewForge fixture",
            "-c",
            "user.email=fixture@previewforge.invalid",
            "revert",
            "--no-edit",
            bad,
            quiet=True,
        )
        restored = p.run("git", "-C", source_git, "rev-parse", "HEAD", quiet=True)
        p.run("git", "--git-dir", bare, "fetch", source_git, "main:main", quiet=True)
        p.k(
            "annotate",
            "application",
            ENVIRONMENT,
            "-n",
            "argocd",
            "argocd.argoproj.io/refresh=hard",
            "--overwrite",
            quiet=True,
        )
        v.wait_preview(ENVIRONMENT, record)
        with p.forward(port=18081, namespace=ENVIRONMENT):
            if p.http("/health/ready", port=18081)[0] != 200:
                raise ValueError("Recovered preview is not ready")
        passed("explicit Git revert restored the preview", recovered_config_revision=restored)
    finally:
        recovery()
    with p.forward(port=18081):
        if (
            p.http("/tasks", port=18081)[1] != before
            or p.get("pvc", "demo-postgres")["metadata"]["uid"] != pvc
        ):
            raise ValueError("Staging changed unexpectedly")
    p.wait_staging()
    passed(
        "disposable Application, namespace, PVC/PV, roles and Git server removed; staging tasks preserved",
        task_count=len(before),
    )
    report["completed"] = True
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Saved: " + str(output))
