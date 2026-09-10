"""Bounded real monitoring exercises with Git recovery and a persistent recovery journal."""

import copy
import json
import re
import secrets
import statistics
import threading
import time
import urllib.error
from contextlib import contextmanager
from datetime import UTC, datetime

import github_delivery as delivery
import monitoring as m
import platform_local as p
import preview_state as s
import previews as v

JOURNAL = p.RUNTIME / "monitoring-recovery.json"
RESULT = p.RUNTIME / "milestone-4-verification.json"


class GitHubCli:
    """Only the already-authorized platform repository, using guarded gh as HickoDev."""

    def __init__(self, message="PreviewForge monitoring exercise"):
        self.message = message
        self.last_commit = None

    def api(self, path, method="GET", body=None):
        args = ["api", "repos/" + s.REPOSITORY + "/" + path, "--method", method]
        if body is not None:
            body = copy.deepcopy(body)
            if path == "git/commits" and method == "POST":
                body["message"] = self.message
            payload = p.RUNTIME / "monitoring-github-request.json"
            payload.write_text(json.dumps(body), encoding="utf-8")
            args.extend(["--input", str(payload)])
        try:
            value = json.loads(p.gh(*args))
        except RuntimeError as exc:
            conflict = re.search(r"HTTP (409|422)", str(exc))
            if method == "PATCH" and path == "git/refs/heads/main" and conflict:
                raise urllib.error.HTTPError(
                    path, int(conflict[1]), "Git ref conflict", {}, None
                ) from exc
            raise
        if path == "git/commits" and method == "POST":
            self.last_commit = value["sha"]
        return value


def current():
    return delivery.GitHubStore(GitHubCli()).snapshot()[1][s.STAGING]


def restore_change(records, expected, replacement):
    if records[s.STAGING] == replacement:
        return records
    s.require(
        records[s.STAGING] == expected, "Staging changed concurrently; preserve the new release"
    )
    result = copy.deepcopy(records)
    result[s.STAGING] = replacement
    return result


def write_image(expected, replacement, message):
    s.validate_image(replacement)
    api = GitHubCli(message)
    revision, changed = s.transact(
        delivery.GitHubStore(api), lambda records: restore_change(records, expected, replacement)
    )
    p.k(
        "-n",
        "argocd",
        "annotate",
        "application",
        "staging",
        "argocd.argoproj.io/refresh=hard",
        "--overwrite",
        quiet=True,
    )
    return api.last_commit if changed else revision


def save(value):
    JOURNAL.write_text(json.dumps(value, indent=2) + "\n")


def alert(name, namespace="staging"):
    return m.query(f'ALERTS{{alertname="{name}",namespace="{namespace}",alertstate="firing"}}')


def api_pod(namespace="staging"):
    return next(
        x
        for x in p.get("pods", namespace=namespace)["items"]
        if x["metadata"].get("labels", {}).get("app") == "demo-api"
        and not x["metadata"].get("deletionTimestamp")
    )


@contextmanager
def traffic(port, path="/tasks", workers=1):
    stop = threading.Event()
    mutex = threading.Lock()
    stats = {"requests": 0, "statusCounts": {}, "workers": workers}

    def generate():
        deadline = time.monotonic() + 360
        while not stop.is_set() and time.monotonic() < deadline:
            try:
                code = str(p.http(path, port=port)[0])
            except Exception:
                code = "connection_error"
            with mutex:
                stats["requests"] += 1
                stats["statusCounts"][code] = stats["statusCounts"].get(code, 0) + 1
            stop.wait(0.2)

    threads = [threading.Thread(target=generate, daemon=True) for _ in range(workers)]
    for worker in threads:
        worker.start()
    try:
        yield stats
    finally:
        stop.set()
        for worker in threads:
            worker.join(timeout=15)
        if any(worker.is_alive() for worker in threads):
            raise RuntimeError("Traffic worker did not stop")


def cleanup_preview(name):
    v.REMOTE = True
    ns = v.optional("namespace", name)
    if not ns:
        return
    v.owned(ns, name)
    s.require(
        ns["metadata"]["labels"].get("previewforge.io/test") == m.OWNER,
        "Refusing to clean another preview",
    )
    app = v.optional("application", name)
    if app:
        s.require(
            app["metadata"]["labels"].get("previewforge.io/test") == m.OWNER,
            "Refusing to delete another Application",
        )
        # ApplicationSet does not own this explicit monitoring fixture.
        p.k("-n", "argocd", "delete", "application", name, "--wait=false", quiet=True)
        p.wait_for(
            "test Application finalizer cleanup", lambda: not v.optional("application", name), 180
        )
    v.delete_namespace({"name": name, "uid": ns["metadata"]["uid"]})


def recover(_trials=1):
    if not JOURNAL.exists():
        print("No monitoring recovery is pending.")
        return
    journal = json.loads(JOURNAL.read_text())
    s.require(journal.get("owner") == m.OWNER, "Unknown recovery journal")
    if journal.get("dbPaused"):
        s.require(
            p.get("namespace", "staging")["metadata"]["labels"].get("previewforge.io/owner")
            == p.OWNER,
            "Staging ownership changed",
        )
        p.k("-n", "staging", "scale", "statefulset/demo-postgres", "--replicas=1", quiet=True)
        p.patch(
            "application",
            "staging",
            {"spec": {"syncPolicy": {"automated": journal["dbPolicy"]}}},
            "argocd",
        )
        journal["dbPaused"] = False
        save(journal)
    if journal.get("badImage"):
        sha = write_image(
            journal["badImage"],
            journal["baseline"],
            "revert: restore known-good staging image after monitoring exercise",
        )
        p.wait_staging(sha)
        journal["badImage"] = None
        save(journal)
    if journal.get("previewName"):
        cleanup_preview(journal["previewName"])
        journal["previewName"] = None
        save(journal)
    p.wait_staging()
    JOURNAL.unlink()
    print("Monitoring exercise recovery completed.")


def verify(trials=2):
    s.require(not JOURNAL.exists(), "Pending recovery exists; run monitoring.py recover first")
    v.REMOTE = True
    v.ensure_transport()
    m.wait_ready()
    p.wait_staging()
    baseline = current()
    s.validate_image(baseline)
    pvc = p.get("pvc", "demo-postgres")["metadata"]["uid"]
    with p.forward(port=18045):
        tasks = p.http("/tasks", port=18045)[1]
        s.require(
            p.http("/version", port=18045)[1]["source_sha"] == baseline["sourceSha"],
            "Staging is not running the Git image",
        )
        s.require(
            p.http("/test/failure", port=18045)[0] == 404, "Failure exercise must default off"
        )
    journal = {
        "owner": m.OWNER,
        "baseline": baseline,
        "badImage": None,
        "dbPaused": False,
        "previewName": None,
    }
    save(journal)
    report = {
        "startedAt": datetime.now(UTC).isoformat(),
        "trials": trials,
        "checks": [],
        "baseline": baseline,
        "stagingPvcUid": pvc,
    }

    def passed(name, **details):
        report["checks"].append({"name": name, "at": datetime.now(UTC).isoformat(), **details})
        RESULT.write_text(json.dumps(report, indent=2) + "\n")
        print("PASS: " + name, flush=True)

    try:
        with m.forward(), m.forward("grafana", 13000):
            p.wait_for(
                "live workload metrics",
                lambda: m.query(
                    'kube_deployment_status_replicas_available{namespace="staging",deployment="demo-api"}'
                ),
                120,
            )
            dashboard = m.http("/api/dashboards/uid/previewforge", 13000)["dashboard"]
            s.require(len(dashboard["panels"]) == 8, "Expected eight provisioned dashboard panels")
            with p.forward(port=18045), traffic(18045):
                p.wait_for(
                    "application rate metrics",
                    lambda: m.query(
                        'sum(rate(previewforge_http_requests_total{namespace="staging",route="/tasks"}[1m])) > 0'
                    ),
                    90,
                )
                for panel in dashboard["panels"]:
                    if panel["title"] == "Active alerts":
                        continue
                    expression = panel["targets"][0]["expr"].replace("$namespace", "staging")
                    s.require(m.query(expression), "Dashboard has no live data: " + panel["title"])
            passed(
                "Provisioned Grafana dashboard and all seven non-alert panels query live Prometheus data"
            )
            for trial in range(1, trials + 1):
                bad = copy.deepcopy(baseline)
                bad["image"]["digest"] = "sha256:" + "0" * 64
                journal["badImage"] = bad
                save(journal)
                started = time.monotonic()
                committed = datetime.now(UTC).isoformat()
                bad_sha = write_image(
                    baseline, bad, "test: deliberately unavailable staging image for monitoring"
                )
                try:
                    p.wait_for(
                        "image-pull alert firing",
                        lambda: alert("PreviewForgeImagePullFailure"),
                        240,
                    )
                    detected = round(time.monotonic() - started, 3)
                    p.wait_for(
                        "Git release alert firing",
                        lambda: alert("PreviewForgeReleaseOutOfSync"),
                        120,
                    )
                    with p.forward(port=18045):
                        s.require(
                            p.http("/health/ready", port=18045)[0] == 200,
                            "Old API must remain available",
                        )
                        s.require(
                            p.http("/version", port=18045)[1]["source_sha"]
                            == baseline["sourceSha"],
                            "Unexpected serving version",
                        )
                finally:
                    recovery_start = time.monotonic()
                    recovery_at = datetime.now(UTC).isoformat()
                    recovery_sha = write_image(
                        bad,
                        baseline,
                        "revert: restore known-good staging image after monitoring exercise",
                    )
                    p.wait_staging(recovery_sha)
                    journal["badImage"] = None
                    save(journal)
                p.wait_for(
                    "release alerts resolved",
                    lambda: (
                        not alert("PreviewForgeImagePullFailure")
                        and not alert("PreviewForgeReleaseOutOfSync")
                    ),
                    150,
                )
                passed(
                    "Failed release detected and recovered through Git",
                    trial=trial,
                    committedAt=committed,
                    recoveryStartedAt=recovery_at,
                    badCommit=bad_sha,
                    recoveryCommit=recovery_sha,
                    detectionSeconds=detected,
                    recoverySeconds=round(time.monotonic() - recovery_start, 3),
                )

                pod = api_pod()
                restarts = pod["status"]["containerStatuses"][0]["restartCount"]
                journal["dbPolicy"] = p.get("application", "staging", "argocd")["spec"][
                    "syncPolicy"
                ]["automated"]
                journal["dbPaused"] = True
                save(journal)
                started = time.monotonic()
                outage_at = datetime.now(UTC).isoformat()
                with (
                    p.forward("pod/" + pod["metadata"]["name"], port=18045),
                    # A failed database connection can take three seconds. Six bounded
                    # clients keep completed request traffic above the alert's 1 rps floor.
                    traffic(18045, workers=6) as counts,
                ):
                    try:
                        p.patch(
                            "application",
                            "staging",
                            {"spec": {"syncPolicy": {"automated": {"enabled": False}}}},
                            "argocd",
                        )
                        p.k(
                            "-n",
                            "staging",
                            "scale",
                            "statefulset/demo-postgres",
                            "--replicas=0",
                            quiet=True,
                        )
                        p.wait_for(
                            "API readiness failure",
                            lambda: p.http("/health/ready", port=18045)[0] == 503,
                            90,
                        )
                        s.require(
                            p.http("/health/live", port=18045)[0] == 200, "DB outage broke liveness"
                        )
                        for name in (
                            "PreviewForgeDatabaseUnavailable",
                            "PreviewForgeApiUnavailable",
                            "PreviewForgeHighErrorRate",
                        ):
                            p.wait_for(name, lambda name=name: alert(name), 120)
                        detected = round(time.monotonic() - started, 3)
                    finally:
                        recovery_start = time.monotonic()
                        recovery_at = datetime.now(UTC).isoformat()
                        p.k(
                            "-n",
                            "staging",
                            "scale",
                            "statefulset/demo-postgres",
                            "--replicas=1",
                            quiet=True,
                        )
                        p.patch(
                            "application",
                            "staging",
                            {"spec": {"syncPolicy": {"automated": journal["dbPolicy"]}}},
                            "argocd",
                        )
                        journal["dbPaused"] = False
                        save(journal)
                        p.wait_for(
                            "database/API recovery",
                            lambda: p.http("/health/ready", port=18045)[0] == 200,
                            120,
                        )
                    s.require(p.http("/tasks", port=18045)[1] == tasks, "Database tasks changed")
                    s.require(
                        api_pod()["status"]["containerStatuses"][0]["restartCount"] == restarts,
                        "API restarted during DB outage",
                    )
                    p.wait_for(
                        "database alerts resolved",
                        lambda: (
                            not any(
                                alert(n)
                                for n in (
                                    "PreviewForgeDatabaseUnavailable",
                                    "PreviewForgeApiUnavailable",
                                    "PreviewForgeHighErrorRate",
                                )
                            )
                        ),
                        150,
                    )
                passed(
                    "Database outage detected; liveness, saved tasks and PVC survive recovery",
                    trial=trial,
                    startedAt=outage_at,
                    recoveryStartedAt=recovery_at,
                    detectionSeconds=detected,
                    recoverySeconds=round(time.monotonic() - recovery_start, 3),
                    traffic=counts,
                )

                name = "preview-" + str(800_000_000 + secrets.randbelow(90_000_000))
                s.require(
                    not v.optional("namespace", name) and not v.optional("application", name),
                    "Fixture name already exists",
                )
                journal["previewName"] = name
                save(journal)
                p.k(
                    "create",
                    "-f",
                    "-",
                    input=json.dumps(
                        {
                            "apiVersion": "v1",
                            "kind": "Namespace",
                            "metadata": {
                                "name": name,
                                "labels": {
                                    **v.LABELS,
                                    "previewforge.io/environment": name,
                                    "previewforge.io/test": m.OWNER,
                                },
                            },
                        }
                    ),
                    quiet=True,
                )
                v.ensure_namespace({"environment": name})
                template = p.get("applicationset", "previewforge-previews", "argocd")["spec"][
                    "template"
                ]
                app = {
                    "apiVersion": "argoproj.io/v1alpha1",
                    "kind": "Application",
                    **copy.deepcopy(template),
                }
                app["metadata"].update(
                    {
                        "name": name,
                        "namespace": "argocd",
                        "labels": {
                            **v.LABELS,
                            "previewforge.io/environment": name,
                            "previewforge.io/test": m.OWNER,
                        },
                    }
                )
                app["spec"]["destination"]["namespace"] = name
                app["spec"]["source"]["helm"]["parameters"] = [
                    {"name": key, "value": value}
                    for key, value in {
                        "environment": name,
                        "image.repository": baseline["image"]["repository"],
                        "image.digest": baseline["image"]["digest"],
                        "image.pullPolicy": "IfNotPresent",
                        "imagePullSecrets[0].name": "previewforge-ghcr",
                        "failureExercise.enabled": "true",
                        "exports.enabled": "false",
                    }.items()
                ]
                p.apply(app)
                v.wait_preview(name, baseline)
                with (
                    p.forward(namespace=name, port=18046),
                    traffic(18046, "/test/failure") as counts,
                ):
                    s.require(
                        p.http("/test/failure", port=18046)[0] == 503,
                        "Test facility was not enabled",
                    )
                    p.wait_for(
                        "preview error-rate alert",
                        lambda: alert("PreviewForgeHighErrorRate", name),
                        120,
                    )
                    s.require(
                        not alert("PreviewForgeHighErrorRate", "staging"),
                        "Preview alert leaked into staging",
                    )
                started = time.monotonic()
                cleanup_preview(name)
                journal["previewName"] = None
                save(journal)
                p.wait_for(
                    "deleted preview metrics disappear",
                    lambda: (
                        not m.query(f'up{{job="previewforge-api",namespace="{name}"}}')
                        and not m.query(
                            f'kube_deployment_status_replicas_available{{namespace="{name}"}}'
                        )
                        and not alert("PreviewForgeHighErrorRate", name)
                    ),
                    150,
                )
                s.require(
                    p.get("pvc", "demo-postgres")["metadata"]["uid"] == pvc, "Staging PVC changed"
                )
                passed(
                    "Explicit local preview fixture discovered, isolated alert fires, complete cleanup removes live metrics",
                    trial=trial,
                    namespace=name,
                    cleanupSeconds=round(time.monotonic() - started, 3),
                    traffic=counts,
                    fixtureMode="Existing private main image; manually created Argo Application, no GitHub PR",
                )
            s.require(
                not m.query('ALERTS{alertstate="firing",alertname=~"PreviewForge.*"}'),
                "Unresolved monitoring alert",
            )
            passed("No active firing PreviewForge alerts after all recoveries")
        report["completedAt"] = datetime.now(UTC).isoformat()
        report["measurements"] = {}
        for field in ("detectionSeconds", "recoverySeconds", "cleanupSeconds"):
            for name in {x["name"] for x in report["checks"] if field in x}:
                values = [x[field] for x in report["checks"] if x["name"] == name]
                report["measurements"][name + ":" + field] = {
                    "n": len(values),
                    "raw": values,
                    "median": statistics.median(values),
                    "min": min(values),
                    "max": max(values),
                }
        RESULT.write_text(json.dumps(report, indent=2) + "\n")
    except Exception as exc:
        report["failedAt"] = datetime.now(UTC).isoformat()
        report["failure"] = str(exc)
        RESULT.write_text(json.dumps(report, indent=2) + "\n")
        raise
    finally:
        recover()
