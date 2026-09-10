"""Local preview control: Git desired records, ApplicationSet, owned namespace cleanup."""

import argparse
import json
import os
import re
import secrets
import sys
import time

import platform_local as p
import preview_state as state

OWNER = "previewforge-m3"
LABELS = {"previewforge.io/owner": OWNER, "previewforge.io/lifecycle": "preview"}
PROVIDER = p.RUNTIME / "pr-provider.json"
REMOTE = False
LOCAL_REPO = "git://previewforge-m2-git.argocd.svc.cluster.local:9418/previewforge.git"
REMOTE_REPO = "ssh://git@github.com/HickoDev/PreviewForge.git"


def ensure_transport():
    appset = optional("applicationset", "previewforge-previews")
    if appset:
        expected = REMOTE_REPO if REMOTE else LOCAL_REPO
        state.require(
            appset["spec"]["generators"][0]["git"]["repoURL"] == expected,
            "Desired-state source differs from ApplicationSet; select the correct mode",
        )


def github_records():
    # The laptop uses gh as HickoDev, never a workflow bot or another active account.
    prefix = "repos/" + state.REPOSITORY + "/"
    head = json.loads(p.gh("api", prefix + "git/ref/heads/main"))["object"]["sha"]
    tree = json.loads(p.gh("api", prefix + f"git/trees/{head}?recursive=1"))
    state.require(not tree.get("truncated"), "Truncated remote tree; cleanup stopped")
    import base64

    result = {}
    for item in tree["tree"]:
        if item["type"] != "blob" or not item["path"].startswith(state.PREFIX):
            continue
        state.require(
            re.fullmatch(r"gitops/previews/preview-[1-9][0-9]{0,8}\.json", item["path"]),
            "Unexpected remote record path",
        )
        blob = json.loads(p.gh("api", prefix + "git/blobs/" + item["sha"]))
        state.require(blob["size"] < 16384, "Oversized preview record")
        result[item["path"]] = json.loads(base64.b64decode(blob["content"]))
    return result


def owned(item, name):
    labels = item["metadata"].get("labels", {})
    state.require(re.fullmatch(r"preview-[1-9][0-9]{0,8}", name), "Not a preview name")
    state.require(all(labels.get(k) == v for k, v in LABELS.items()), "Preview ownership mismatch")
    state.require(labels.get("previewforge.io/environment") == name, "Preview identity mismatch")


def optional(kind, name, namespace="argocd", sensitive=False):
    result = p.k(
        "-n",
        namespace,
        "get",
        kind,
        name,
        "--ignore-not-found",
        "-o",
        "json",
        quiet=True,
        sensitive=sensitive,
    )
    return json.loads(result) if result else None


def valid_path(path):
    state.require(
        path == state.STAGING
        or re.fullmatch(r"gitops/previews/preview-[1-9][0-9]{0,8}\.json", path),
        "Refusing to write outside desired records",
    )
    target = p.SOURCE / path
    state.require(
        target.resolve().is_relative_to(p.SOURCE.resolve()), "Record path escaped fixture"
    )
    return target


class LocalStore:
    def head(self):
        return p.local_git("rev-parse", "HEAD")

    def snapshot(self):
        p.require_clean_fixture()
        paths = p.local_git("ls-files", "gitops/previews", state.STAGING).splitlines()
        records = {}
        for path in paths:
            valid_path(path)
            records[path] = json.loads(p.local_git("show", "HEAD:" + path))
        return self.head(), records

    def compare_swap(self, revision, before, after):
        if self.head() != revision:
            return False
        changed = [key for key in before.keys() | after.keys() if before.get(key) != after.get(key)]
        for key in changed:
            target = valid_path(key)
            if key in after:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps(after[key], indent=2) + "\n", encoding="utf-8")
            else:
                target.unlink()
        p.commit("Reconcile local preview desired records", sorted(changed))
        p.publish_local()
        return True


def desired():
    ensure_transport()
    records = github_records() if REMOTE else LocalStore().snapshot()[1]
    result = {}
    for path, record in records.items():
        if path.startswith(state.PREFIX):
            state.validate_record(record, local=not REMOTE)
            state.require(
                path == state.PREFIX + record["environment"] + ".json", "Record path mismatch"
            )
            result[record["environment"]] = record
    return result


def ensure_namespace(record):
    name = record["environment"]
    labels = {**LABELS, "previewforge.io/environment": name}
    current = optional("namespace", name)
    if current:
        owned(current, name)
        state.require(not current["metadata"].get("deletionTimestamp"), "Preview is still deleting")
    else:
        p.k(
            "create",
            "-f",
            "-",
            input=json.dumps(
                {
                    "apiVersion": "v1",
                    "kind": "Namespace",
                    "metadata": {"name": name, "labels": labels},
                }
            ),
            quiet=True,
        )
    secret = optional("secret", "preview-db", name, sensitive=True)
    if secret:
        owned(secret, name)
    else:
        state.require(not p.get("pvc", namespace=name)["items"], "PVC exists without its DB secret")
        # Send the generated value through stdin only. No password enters Git or argv.
        p.k(
            "create",
            "-f",
            "-",
            input=json.dumps(
                {
                    "apiVersion": "v1",
                    "kind": "Secret",
                    "metadata": {"name": "preview-db", "namespace": name, "labels": labels},
                    "type": "Opaque",
                    "stringData": {"db_password": secrets.token_hex(32)},
                }
            ),
            quiet=True,
            sensitive=True,
        )
    if REMOTE:
        copy_registry_secret(name)


def copy_registry_secret(name):
    state.require(
        name == "staging" or re.fullmatch(r"preview-[1-9][0-9]{0,8}", name),
        "Invalid registry-secret destination",
    )
    source = optional("secret", "previewforge-ghcr", "argocd", sensitive=True)
    state.require(
        source and source["type"] == "kubernetes.io/dockerconfigjson",
        "Configure the private read-only GHCR secret in argocd first",
    )
    state.require(
        source["metadata"].get("labels", {}).get("previewforge.io/owner") == OWNER,
        "Registry secret ownership mismatch",
    )
    existing = optional("secret", "previewforge-ghcr", name, sensitive=True)
    if existing:
        state.require(
            existing["metadata"].get("labels", {}).get("previewforge.io/owner") == OWNER,
            "Destination registry secret has another owner",
        )
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
                    "namespace": name,
                    "labels": {"previewforge.io/owner": OWNER, "previewforge.io/environment": name},
                },
                "type": source["type"],
                "data": source["data"],
            }
        ),
        quiet=True,
        sensitive=True,
    )


def wait_preview(name, record):
    def ready():
        app = optional("application", name)
        if not app:
            return False
        owned(app, name)
        status = app.get("status", {})
        params = {x["name"]: x["value"] for x in app["spec"]["source"]["helm"]["parameters"]}
        return (
            params.get("image.digest") == record["image"]["digest"]
            and status.get("sync", {}).get("status") == "Synced"
            and status.get("health", {}).get("status") == "Healthy"
            and status.get("operationState", {}).get("phase") == "Succeeded"
            and not app.get("operation")
            and p.get("deployment", "demo-api", name)["spec"]["template"]["spec"]["containers"][0][
                "image"
            ]
            == record["image"]["repository"] + "@" + record["image"]["digest"]
        )

    p.wait_for(f"{name} synced, healthy and running its intended image", ready, 420)


def plan():
    records = desired()  # Validate all records before considering any deletion.
    namespaces = p.get("namespaces", namespace="argocd")["items"]
    removed = []
    for item in namespaces:
        name = item["metadata"]["name"]
        if item["metadata"].get("labels", {}).get("previewforge.io/owner") != OWNER:
            continue
        owned(item, name)
        if name not in records:
            removed.append({"name": name, "uid": item["metadata"]["uid"]})
    return records, removed


def delete_namespace(target):
    name = target["name"]
    # Re-read current desired Git and cluster identity immediately before deleting.
    state.require(name not in desired(), "Preview became desired again; cleanup stopped")
    item = optional("namespace", name)
    if not item:
        return
    owned(item, name)
    state.require(
        item["metadata"]["uid"] == target["uid"], "Namespace was replaced; cleanup stopped"
    )
    state.require(not optional("application", name), "Argo Application still exists; retry cleanup")
    # kubectl delete does not offer UID preconditions. Use its authenticated raw API
    # with DeleteOptions, which atomically refuses a replacement namespace.
    body = p.RUNTIME / "namespace-delete.json"
    body.write_text(
        json.dumps(
            {
                "apiVersion": "v1",
                "kind": "DeleteOptions",
                "preconditions": {"uid": target["uid"]},
                "propagationPolicy": "Foreground",
            }
        )
    )
    p.k("delete", "--raw", "/api/v1/namespaces/" + name, "-f", body, quiet=True)
    p.wait_for(f"{name} namespace removed", lambda: not optional("namespace", name), 180)
    p.wait_for(
        f"{name} disposable PV removed",
        lambda: (
            not [
                pv
                for pv in p.get("pv", namespace="argocd")["items"]
                if pv["spec"].get("claimRef", {}).get("namespace") == name
            ]
        ),
        180,
    )


def reconcile(apply=False):
    records, removed = plan()
    print(
        json.dumps({"dryRun": not apply, "ensure": sorted(records), "removeNamespaces": removed}),
        flush=True,
    )
    if not apply:
        return
    if REMOTE:
        copy_registry_secret("staging")
    for record in records.values():
        ensure_namespace(record)
    for target in removed:
        name = target["name"]
        # The generator/finalizer deletes the Application and chart resources first.
        p.wait_for(
            f"ApplicationSet cascading deletion of {name}",
            lambda: not optional("application", name),
            420,
        )
        delete_namespace(target)


def up():
    p.up()
    ensure_transport()
    p.k(
        "-n",
        "argocd",
        "rollout",
        "status",
        "deployment/argocd-applicationset-controller",
        "--timeout=180s",
    )
    existing_class = optional("storageclass", "previewforge-disposable")
    if existing_class:
        state.require(
            existing_class["metadata"].get("labels", {}).get("previewforge.io/owner") == OWNER,
            "Disposable StorageClass has another owner",
        )
    p.apply(
        {
            "apiVersion": "storage.k8s.io/v1",
            "kind": "StorageClass",
            "metadata": {
                "name": "previewforge-disposable",
                "labels": {"previewforge.io/owner": OWNER},
            },
            "provisioner": "rancher.io/local-path",
            "reclaimPolicy": "Delete",
            "volumeBindingMode": "WaitForFirstConsumer",
        }
    )
    p.k("apply", "-f", p.ROOT / "gitops/platform/previews.yaml", quiet=True)
    reconcile(apply=True)


def get_fixture_pr(number):
    values = json.loads(PROVIDER.read_text())
    state.require(str(number) in values, "PR state unknown; cleanup stopped")
    return values[str(number)]


def main():
    global REMOTE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=[
            "up",
            "verify",
            "demo",
            "close",
            "reconcile",
            "prune",
            "watch",
            "render-remote",
            "forward",
            "status",
        ],
    )
    parser.add_argument(
        "--github",
        action="store_true",
        help="Read remote records using gh as HickoDev; requires configured remote Argo manifests",
    )
    parser.add_argument(
        "--apply", action="store_true", help="Apply an otherwise dry-run reconciliation"
    )
    parser.add_argument("--pr", type=int)
    parser.add_argument("--port", type=int, default=18042)
    args = parser.parse_args()
    REMOTE = args.github
    state.require(
        not REMOTE or args.action in {"reconcile", "watch", "forward", "status"},
        "This command is local-only",
    )
    state.require(
        sys.platform == "win32" and sys.version_info[:2] == (3, 12), "Use Windows Python 3.12"
    )
    state.require(__debug__, "Remove Python -O/PYTHONOPTIMIZE")
    state.require(
        os.environ.get("LOCALAPPDATA") and "onedrive" not in str(p.RUNTIME).lower(),
        "Unsafe runtime",
    )
    p.RUNTIME.mkdir(parents=True, exist_ok=True)
    import msvcrt

    with (p.RUNTIME / "operation.lock").open("a+b") as lock:
        lock.seek(0)
        if args.action not in {"forward", "status"}:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        if args.action == "up":
            up()
        elif args.action == "verify":
            up()
            from verify_previews import verify

            verify()
        elif args.action == "demo":
            up()
            import ci
            from verify_previews import provider, receipt, save_provider

            state.preview_name(args.pr)
            ci.test()
            image = p.load_image(p.snapshot())
            save_provider({args.pr: provider(args.pr, image)})
            state.transact(
                LocalStore(),
                lambda records: state.update_build(
                    records, receipt(args.pr, image), get_fixture_pr(args.pr), local=True
                ),
            )
            reconcile(apply=True)
            wait_preview(state.preview_name(args.pr), image)
            print(
                f"Local synthetic PR ready. Forward with: python scripts/previews.py forward --pr {args.pr}"
            )
        elif args.action == "close":
            from verify_previews import save_provider

            value = get_fixture_pr(args.pr)
            value["state"] = "closed"
            save_provider({args.pr: value})
            path = state.PREFIX + state.preview_name(args.pr) + ".json"

            def close_one(records):
                selected = {path: records[path]} if path in records else {}
                retained = state.prune_records(selected, get_fixture_pr, local=True)
                return {**{key: value for key, value in records.items() if key != path}, **retained}

            state.transact(LocalStore(), close_one)
            reconcile(apply=True)
        elif args.action == "render-remote":
            # Reviewable output only: no GitHub writes, credentials or cluster mutation.
            for filename in ("staging.yaml", "previews.yaml"):
                manifest = (
                    (p.ROOT / "gitops/platform" / filename)
                    .read_text()
                    .replace(LOCAL_REPO, REMOTE_REPO)
                )
                if filename == "staging.yaml":
                    manifest = manifest.replace(
                        "      releaseName: demo",
                        "      releaseName: demo\n      parameters:\n        - {name: 'imagePullSecrets[0].name', value: previewforge-ghcr}",
                    )
                else:
                    manifest = manifest.replace(
                        "          parameters:",
                        "          parameters:\n            - {name: 'imagePullSecrets[0].name', value: previewforge-ghcr}",
                    )
                print(manifest + "\n---")
        elif args.action == "watch":
            state.require(args.apply, "watch requires --apply; use reconcile for a dry run")
            while True:
                reconcile(apply=True)
                time.sleep(15)
        elif args.action == "reconcile":
            reconcile(apply=args.apply)
        elif args.action == "prune":
            store = LocalStore()

            def change(records):
                return state.prune_records(records, get_fixture_pr, local=True)

            if args.apply:
                state.transact(store, change)
                reconcile(apply=True)
            else:
                _, before = store.snapshot()
                after = change(before)
                print(
                    json.dumps(
                        {"dryRun": True, "removeRecords": sorted(before.keys() - after.keys())}
                    )
                )
        elif args.action == "forward":
            name = state.preview_name(args.pr)
            state.require(name in desired(), "Preview is not desired")
            print(f"{name}: http://127.0.0.1:{args.port}/docs (Ctrl+C to stop)", flush=True)
            with p.forward(namespace=name, port=args.port) as process:
                process.wait()
        else:
            p.k("-n", "argocd", "get", "applicationsets,applications")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
