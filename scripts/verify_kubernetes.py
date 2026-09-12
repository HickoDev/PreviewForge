"""Live acceptance against the one owned kind cluster; restores faults in finally."""

import json
import sys
import time
import uuid
from datetime import UTC, datetime

import platform_local as p


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def pod(component):
    pods = p.get("pods")["items"]
    return next(
        item
        for item in pods
        if item["metadata"].get("labels", {}).get("app") == f"demo-{component}"
        and not item["metadata"].get("deletionTimestamp")
    )


def is_ready(item):
    return any(
        c["type"] == "Ready" and c["status"] == "True" for c in item["status"].get("conditions", [])
    )


def record():
    return json.loads((p.SOURCE / "gitops/staging/image.json").read_text())


def assert_version(expected):
    status, version = p.http("/version", port=18001)
    check(
        status == 200
        and version == {"environment": "staging", "source_sha": expected["sourceSha"]},
        "Running /version does not match the committed source snapshot.",
    )
    deployed = p.get("deployment", "demo-api")["spec"]["template"]["spec"]["containers"][0]["image"]
    check(
        deployed == expected["image"]["repository"] + "@" + expected["image"]["digest"],
        "Deployment does not use the intended immutable image digest.",
    )
    return version


def verify():
    p.require_clean_fixture()
    # The local Git server must deploy the checkout being reviewed, not an old
    # snapshot whose Helm templates happened to pass a separate lint command.
    baseline = p.load_image(p.snapshot())
    baseline_revision = p.deploy_record(baseline, "Verify the current checkout on staging")
    p.wait_staging(baseline_revision)
    results = {
        "started_at": datetime.now(UTC).isoformat(),
        "scope": "local kind + local Git fixture",
        "checks": [],
    }

    def passed(name, started, **details):
        results["checks"].append(
            {
                "name": name,
                "finished_at": datetime.now(UTC).isoformat(),
                "seconds": round(time.monotonic() - started, 3),
                **details,
            }
        )
        print("PASS: " + name, flush=True)

    started = time.monotonic()
    p.run(sys.executable, "-m", "unittest", "discover", "-s", p.ROOT / "tests/platform")
    p.run(
        p.TOOLS / p.host.executable("helm"),
        "lint",
        p.ROOT / "charts/demo-app",
        "--strict",
        "--set",
        "image.digest=" + record()["image"]["digest"],
    )
    rendered = p.run(
        p.TOOLS / p.host.executable("helm"),
        "template",
        "demo",
        p.ROOT / "charts/demo-app",
        "--namespace",
        "staging",
        "--set",
        "image.digest=" + record()["image"]["digest"],
        quiet=True,
    )
    p.k(
        "-n",
        "staging",
        "apply",
        "--dry-run=server",
        "-f",
        "-",
        input=rendered,
        quiet=True,
    )
    try:
        p.run(
            p.TOOLS / p.host.executable("helm"),
            "template",
            "demo",
            p.ROOT / "charts/demo-app",
            "--set",
            "image.digest=latest",
            quiet=True,
        )
    except RuntimeError as exc:
        check(
            "image.digest must be sha256" in str(exc),
            "Invalid-image chart test failed for an unexpected reason.",
        )
    else:
        raise RuntimeError("Chart accepted a mutable image reference.")
    passed(
        "Offline guard regressions, Helm lint, Kubernetes validation, mutable-image rejection",
        started,
    )

    initial = record()
    started = time.monotonic()
    with p.forward(port=18001):
        assert_version(initial)
        status, task = p.http(
            "/tasks",
            "POST",
            {"title": "Milestone 2 acceptance " + uuid.uuid4().hex},
            port=18001,
        )
        check(status == 201, "Task creation failed.")
        status, changed = p.http("/tasks/" + task["id"], "PATCH", {"status": "done"}, port=18001)
        check(status == 200 and changed["status"] == "done", "Task update failed.")
        check(
            p.http("/health/ready", port=18001)
            == (200, {"status": "ready", "database": "connected"}),
            "Readiness failed.",
        )
        check(p.http("/docs", port=18001)[0] == 200, "API docs failed.")
        check(
            "previewforge_http_requests_total" in p.http("/metrics", port=18001)[1],
            "Metrics missing.",
        )
    passed(
        "PostgreSQL CRUD, readiness, docs, metrics and exact source/image identity",
        started,
        task_id=task["id"],
        initial=initial,
    )

    # A real source commit in the disposable LOCAL fixture, followed by a config-only commit.
    # This never commits to or pushes the user's platform checkout.
    started = time.monotonic()
    (p.SOURCE / "previewforge-demo/app/release_fixture.py").write_text(
        '# Synthetic local release marker for the GitOps demonstration.\nRELEASE = "'
        + uuid.uuid4().hex
        + '"\n'
    )
    source_sha = p.commit(
        "Create second local application source revision for GitOps acceptance",
        ["previewforge-demo/app/release_fixture.py"],
    )
    updated = p.load_image(source_sha)
    check(
        updated["image"]["digest"] != initial["image"]["digest"],
        "Second build reused the original digest.",
    )
    build_seconds = round(time.monotonic() - started, 3)
    committed_at = datetime.now(UTC).isoformat()
    started = time.monotonic()
    config_sha = p.deploy_record(updated, "Update staging to the second local image digest")
    p.wait_staging(config_sha)
    with p.forward(port=18001):
        version = assert_version(updated)
        check(
            any(
                row["id"] == task["id"] and row["status"] == "done"
                for row in p.http("/tasks", port=18001)[1]
            ),
            "Task did not survive the image rollout.",
        )
    passed(
        "Git configuration commit automatically rolled out a different image",
        started,
        committed_at=committed_at,
        config_sha=config_sha,
        source_sha=source_sha,
        build_and_load_seconds=build_seconds,
        digest=updated["image"]["digest"],
        version=version,
    )

    started = time.monotonic()
    p.patch("deployment", "demo-api", {"spec": {"replicas": 2}})
    p.wait_for(
        "Argo CD repairs live replica drift",
        lambda: p.get("deployment", "demo-api")["spec"]["replicas"] == 1,
        90,
    )
    p.wait_staging(config_sha)
    passed("Argo CD self-heal restored the Git replica count", started)

    # A missing loaded image blocks the migration before an unhealthy API can replace the working one.
    started = time.monotonic()
    bad = json.loads(json.dumps(updated))
    bad["image"]["digest"] = "sha256:" + "0" * 64
    try:
        bad_sha = p.deploy_record(bad, "Exercise a deliberately unavailable local image")

        def blocked_image():
            for item in p.get("pods")["items"]:
                for state in item["status"].get("containerStatuses", []):
                    waiting = state.get("state", {}).get("waiting", {})
                    if waiting.get("reason") == "ErrImageNeverPull":
                        return {
                            "pod": item["metadata"]["name"],
                            "reason": waiting["reason"],
                        }
            return None

        failure = p.wait_for("visible blocked release (ErrImageNeverPull)", blocked_image, 180)
        with p.forward(port=18001):
            assert_version(updated)
            check(
                p.http("/health/ready", port=18001)[0] == 200,
                "Blocked release disturbed the working API.",
            )
    finally:
        recovery_sha = p.deploy_record(updated, "Restore the known-good staging image in Git")
        # The in-flight sync finishes its bounded migration deadline, then the
        # controller reconciles the recovery commit. No direct workload repair.
        p.wait_staging(recovery_sha)
    passed(
        "Unavailable image observed; known-good API retained; Git recovery completed",
        started,
        bad_config_sha=bad_sha,
        recovery_config_sha=recovery_sha,
        observed=failure,
    )

    started = time.monotonic()
    api = pod("api")
    db_uid = pod("postgres")["metadata"]["uid"]
    pvc = p.get("pvc", "demo-postgres")
    check(pvc["status"]["phase"] == "Bound", "Database PVC is not bound.")
    pv = p.get("pv", pvc["spec"]["volumeName"])
    check(
        pv["spec"]["persistentVolumeReclaimPolicy"] == "Retain",
        "Staging PV must be retained.",
    )
    api_restarts = api["status"]["containerStatuses"][0]["restartCount"]
    # Temporarily pause automated sync so self-heal does not erase the intended DB outage.
    # The finally block always restores replicas and the original automated policy.
    original_policy = p.get("application", "staging", "argocd")["spec"]["syncPolicy"]["automated"]
    try:
        p.patch(
            "application",
            "staging",
            {"spec": {"syncPolicy": {"automated": {"enabled": False}}}},
            "argocd",
        )
        with p.forward("pod/" + api["metadata"]["name"], port=18001):
            p.k("-n", "staging", "scale", "statefulset/demo-postgres", "--replicas=0")
            p.wait_for(
                "database pod stopped",
                lambda: (
                    not any(
                        item["metadata"].get("labels", {}).get("app") == "demo-postgres"
                        for item in p.get("pods")["items"]
                    )
                ),
                90,
            )
            p.wait_for("API removed from ready endpoints", lambda: not is_ready(pod("api")), 60)
            check(
                p.http("/health/ready", port=18001)[0] == 503,
                "DB outage must produce readiness 503.",
            )
            check(
                p.http("/tasks", port=18001)[0] == 503,
                "DB outage must produce tasks 503.",
            )
            check(
                p.http("/health/live", port=18001)[0] == 200,
                "DB outage must not break liveness.",
            )
            slices = p.get("endpointslices")["items"]
            check(
                not any(
                    ep.get("conditions", {}).get("ready")
                    for item in slices
                    if item["metadata"]["labels"].get("kubernetes.io/service-name") == "demo-api"
                    for ep in item.get("endpoints", [])
                ),
                "Unready API still has a ready service endpoint.",
            )
            check(
                'status="503"' in p.http("/metrics", port=18001)[1],
                "Failure metric is missing.",
            )
            check(
                pod("api")["status"]["containerStatuses"][0]["restartCount"] == api_restarts,
                "Database outage restarted the API.",
            )
    finally:
        try:
            p.k("-n", "staging", "scale", "statefulset/demo-postgres", "--replicas=1")
        finally:
            p.patch(
                "application",
                "staging",
                {"spec": {"syncPolicy": {"automated": original_policy}}},
                "argocd",
            )
        p.wait_staging(recovery_sha)
    with p.forward(port=18001):
        p.wait_for(
            "database HTTP recovery",
            lambda: p.http("/health/ready", port=18001)[0] == 200,
            120,
        )
        check(
            any(row["id"] == task["id"] for row in p.http("/tasks", port=18001)[1]),
            "Database replacement lost the task.",
        )
        assert_version(updated)
    check(pod("postgres")["metadata"]["uid"] != db_uid, "Database pod was not replaced.")
    check(
        p.get("pvc", "demo-postgres")["metadata"]["uid"] == pvc["metadata"]["uid"],
        "PVC was replaced.",
    )
    passed(
        "Database outage/readiness failure, liveness, recovery and persistent volume reuse",
        started,
    )

    logs = p.k("-n", "staging", "logs", "deployment/demo-api", "--tail=100", quiet=True)
    check(
        '"status": 503' in logs and '"event": "http_request"' in logs,
        "Structured failure logs are missing.",
    )
    check(
        (p.RUNTIME / "db_password").read_text() not in logs,
        "Database password found in logs.",
    )
    check(
        p.get("deployment", "demo-api")["spec"]["template"]["spec"]["automountServiceAccountToken"]
        is False,
        "API should not receive cluster credentials.",
    )
    results["status"] = "passed"
    results["completed_at"] = datetime.now(UTC).isoformat()
    (p.RUNTIME / "verification.json").write_text(json.dumps(results, indent=2) + "\n")
    print(
        "PASS: structured failure logs, secret exclusion and no application service-account token",
        flush=True,
    )
    print(
        "All Milestone 2 live checks passed. Results: " + str(p.RUNTIME / "verification.json"),
        flush=True,
    )
