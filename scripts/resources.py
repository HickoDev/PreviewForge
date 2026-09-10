"""Milestone 5 local Terraform reconciliation and export readiness."""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import platform_local as p
import previews as v

sys.path.insert(0, str(p.ROOT))
sys.path.insert(0, str(p.ROOT / "previewforge-demo"))
from reconciler import runtime as r  # noqa: E402

_cache = (None, {})


def active():
    path = r.RUNTIME / "enabled.json"
    if not path.exists():
        return False
    r.require(
        json.loads(path.read_text()) == {"owner": r.OWNER}, "Unknown resource integration owner"
    )
    return True


def activate_exports():
    """Opt this configured GitHub installation into the tracked export overlay."""
    p.gh(
        "api",
        "repos/HickoDev/PreviewForge/contents/gitops/export-values.yaml?ref=main",
        "--jq",
        ".sha",
    )
    p.k(
        "-n",
        "staging",
        "exec",
        "deployment/demo-api",
        "--",
        "python",
        "-c",
        "import app.worker",
        quiet=True,
    )
    for kind, name in [("application", "staging"), ("applicationset", "previewforge-previews")]:
        value = p.get(kind, name, "argocd")
        spec = value["spec"] if kind == "application" else value["spec"]["template"]["spec"]
        r.require(
            spec["source"]["repoURL"] == v.REMOTE_REPO
            and spec["source"]["path"] == "charts/demo-app"
            and spec["project"] == ("previewforge" if name == "staging" else name),
            "Refusing to change another Argo application",
        )
        files = spec["source"]["helm"]["valueFiles"]
        overlay = "../../gitops/export-values.yaml"
        if overlay in files:
            continue
        patch = {"source": {"helm": {"valueFiles": [*files, overlay]}}}
        if kind == "applicationset":
            patch = {"template": {"spec": patch}}
        p.patch(
            kind,
            name,
            {"metadata": {"resourceVersion": value["metadata"]["resourceVersion"]}, "spec": patch},
            "argocd",
        )
    p.wait_for(
        "Argo CD export worker creation",
        lambda: v.optional("deployment", "demo-worker", "staging"),
        240,
    )
    p.wait_staging()
    p.k(
        "-n", "staging", "rollout", "status", "deployment/demo-worker", "--timeout=180s", quiet=True
    )


def current_previews():
    global _cache
    # Ref polling avoids repeatedly downloading every blob when Git has not changed.
    for _ in range(3):
        sha = p.gh("api", "repos/HickoDev/PreviewForge/git/ref/heads/main", "--jq", ".object.sha")
        if sha == _cache[0]:
            return _cache[1]
        records = v.desired()
        after = p.gh("api", "repos/HickoDev/PreviewForge/git/ref/heads/main", "--jq", ".object.sha")
        if after == sha:
            _cache = (sha, records)
            return records
    raise RuntimeError("Git changed repeatedly during resource reconciliation; retry")


def still_desired(name):
    return name == "staging" or name in current_previews()


def may_delete(name):
    if name in current_previews() or v.optional("application", name):
        return False
    ns = v.optional("namespace", name)
    if ns:
        v.owned(ns, name)
        # Terraform may not remove resources while any namespace workload can use them.
        return not p.get("pods", namespace=name)["items"]
    return True


def run_resources(action, records=None):
    """Called by the existing watcher; keep its Windows/stdlib runtime unchanged."""
    result = subprocess.run(
        [str(r.PYTHON), str(Path(__file__).resolve()), "internal", "--github", "--phase", action],
        input=json.dumps(records or {}),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=900,
    )
    if result.stdout:
        print(result.stdout.strip(), flush=True)
    if result.returncode:
        return [(result.stderr or result.stdout)[-1600:]]
    return []


def reconcile_phase(phase, records):
    from reconciler import terraform as tf

    errors = []
    if phase == "ensure":
        r.route_floci()
        names = ["staging", *sorted(records)]
        for name in names:
            try:
                tf.ensure(name, still_desired)
            except Exception as exc:
                tf.record(name, "error", error=str(exc)[-1000:])
                errors.append(f"{name}: {exc}")
    else:
        for name in tf.owned_environments():
            if not name.startswith("preview-") or name in current_previews():
                continue
            status = tf.directory(name) / "status.json"
            if (
                status.exists()
                and json.loads(status.read_text()).get("phase") == "deleted"
                and not tf.actual(name)
            ):
                continue
            try:
                tf.destroy(name, may_delete)
                if name in current_previews():
                    tf.ensure(name, still_desired)
            except Exception as exc:
                tf.record(name, "cleanup_error", error=str(exc)[-1000:])
                errors.append(f"{name}: {exc}")
    if errors:
        raise RuntimeError("; ".join(errors))
    print(json.dumps({"resourcePhase": phase, "status": "reconciled"}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=["up", "reconcile", "watch", "status", "plan", "verify", "recover", "internal"],
    )
    parser.add_argument("--github", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--environment", default="staging")
    parser.add_argument("--phase", choices=["ensure", "cleanup"])
    parser.add_argument("--allow-faults", action="store_true")
    parser.add_argument("--allow-github-writes", action="store_true")
    args = parser.parse_args()
    v.REMOTE = args.github
    r.validate_runtime()
    r.require(
        args.github, "Milestone 5 integrates the configured GitHub-mode cluster; use --github"
    )
    if args.action == "up":
        with r.lock(r.RUNTIME / "setup.lock"):
            r.install()
    r.require(r.PYTHON.exists() and r.TF.exists(), "Run resources.py up --github first")
    if Path(sys.executable).resolve() != r.PYTHON.resolve():
        raise SystemExit(
            subprocess.call([str(r.PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])
        )
    if args.action == "internal":
        r.require(args.phase and active(), "Resource integration is not enabled")
        reconcile_phase(args.phase, json.load(sys.stdin))
        return
    if args.action == "status":
        from reconciler import terraform as tf

        for name in tf.owned_environments():
            path = tf.directory(name) / "status.json"
            print(path.read_text() if path.exists() else name + ": pending")
        return
    with r.lock(p.RUNTIME / "operation.lock"):
        if args.action == "up":
            r.require(
                p.owned_container(p.NODE, "io.x-k8s.kind.cluster"),
                "Restore the retained PreviewForge node; refusing to create a replacement",
            )
            r.bootstrap_floci()
            p.ensure_cluster()
        v.ensure_transport()
        if args.action == "up":
            r.settings(create=True)
            r.route_floci()
            r.save(r.RUNTIME / "enabled.json", {"owner": r.OWNER})
            v.reconcile(apply=True)
            activate_exports()
            print(
                "Local resources reconciled. Keep previews.py watch --github --apply running for PR lifecycle changes."
            )
        elif args.action == "plan":
            from reconciler import terraform as tf

            with r.lock(tf.directory(args.environment) / "operation.lock"):
                tf.prepare(args.environment)
                tf.actual(args.environment)
                _, result = tf.command(args.environment, "plan", "-input=false", "-no-color")
                print(result)
        elif args.action == "recover":
            r.require(
                args.allow_github_writes,
                "Recovery closes the recorded acceptance PRs; use --allow-github-writes",
            )
            from verify_resources import recover

            recover()
        elif args.action == "verify":
            r.require(
                args.allow_faults and args.allow_github_writes,
                "Verification requires --allow-faults --allow-github-writes",
            )
            from verify_resources import verify

            verify()
        else:
            if args.action == "watch":
                r.require(args.apply, "watch requires --apply")
            while True:
                try:
                    v.reconcile(apply=args.apply)
                except Exception as exc:
                    if args.action != "watch":
                        raise
                    print("Reconciliation will retry: " + str(exc)[-1600:], flush=True)
                if args.action != "watch":
                    break
                time.sleep(15)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
