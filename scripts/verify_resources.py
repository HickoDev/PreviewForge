"""Real PR/export acceptance with bounded local faults and resumable cleanup."""

import base64
import copy
import json
import secrets
from datetime import UTC, datetime

import platform_local as p
import previews as v
import resources
from reconciler import runtime as r
from reconciler import terraform as tf

from app.aws import Cloud

JOURNAL = r.RUNTIME / "verification-recovery.json"
RESULT = r.RUNTIME / "milestone-5-verification.json"


def api(path, method="GET", body=None):
    args = ["api", "repos/HickoDev/PreviewForge/" + path, "--method", method]
    if body is not None:
        payload = r.RUNTIME / "verification-request.json"
        r.save(payload, body)
        args.extend(["--input", str(payload)])
    output = p.gh(*args)
    return json.loads(output) if output else None


def save(journal):
    r.save(JOURNAL, journal)


def edit(branch, marker):
    path = "contents/previewforge-demo/README.md"
    value = api(path + "?ref=" + branch)
    content = base64.b64decode(value["content"]).decode() + "\n<!-- " + marker + " -->\n"
    return api(
        path,
        "PUT",
        {
            "message": marker,
            "branch": branch,
            "sha": value["sha"],
            "content": base64.b64encode(content.encode()).decode(),
        },
    )["commit"]["sha"]


def open_pr(journal, suffix):
    branch = journal["prefix"] + "-" + suffix
    journal["branches"].append(branch)
    save(journal)
    api("git/refs", "POST", {"ref": "refs/heads/" + branch, "sha": journal["base"]})
    sha = edit(branch, "Milestone 5 export acceptance " + suffix)
    value = api(
        "pulls",
        "POST",
        {
            "title": "Milestone 5 acceptance " + suffix + " (temporary)",
            "head": branch,
            "base": "main",
            "body": "Controlled PreviewForge export acceptance. Builds a private preview, tests isolated S3/SQS resources, then closes without merging.",
        },
    )
    record = {"number": value["number"], "url": value["html_url"], "branch": branch, "sha": sha}
    journal["prs"].append(record)
    save(journal)
    print("Opened acceptance PR " + record["url"], flush=True)
    return record


def wait_record(pr):
    name = "preview-" + str(pr["number"])

    def ready():
        record = resources.current_previews().get(name)
        return record if record and record["sourceSha"] == pr["sha"] else None

    p.wait_for("private CI delivery for " + name, ready, 900)
    v.reconcile(apply=True)
    record = resources.current_previews()[name]
    v.wait_preview(name, record)
    p.k("-n", name, "rollout", "status", "deployment/demo-worker", "--timeout=180s", quiet=True)
    return name, record


def export(port, expected=None):
    code, job = p.http("/exports", method="POST", payload={}, port=port)
    r.require(code == 202, "Export request was not accepted")
    identifier = job["id"]
    p.wait_for(
        "export completion",
        lambda: p.http("/exports/" + identifier, port=port)[1]["status"] == "completed",
        120,
    )
    code, report = p.http("/exports/" + identifier + "/download", port=port)
    r.require(code == 200 and report["export_id"] == identifier, "Report could not be downloaded")
    if expected is not None:
        r.require(report["tasks"] == expected, "Report contains another task snapshot")
    return report


def worker_pod(name):
    pods = p.get("pods", namespace=name)["items"]
    return next(
        x
        for x in pods
        if x["metadata"].get("labels", {}).get("app") == "demo-worker"
        and not x["metadata"].get("deletionTimestamp")
    )


def pause_worker(journal, name):
    pod = worker_pod(name)
    journal["paused"] = {
        "namespace": name,
        "pod": pod["metadata"]["name"],
        "uid": pod["metadata"]["uid"],
    }
    save(journal)
    p.k(
        "-n",
        name,
        "exec",
        pod["metadata"]["name"],
        "--",
        "python",
        "-c",
        "import os,signal; os.kill(1,signal.SIGSTOP)",
        quiet=True,
    )


def resume_worker(journal):
    value = journal.get("paused")
    if not value:
        return
    pod = v.optional("pod", value["pod"], value["namespace"])
    if pod and pod["metadata"]["uid"] == value["uid"]:
        p.k(
            "-n",
            value["namespace"],
            "exec",
            value["pod"],
            "--",
            "python",
            "-c",
            "import os,signal; os.kill(1,signal.SIGCONT)",
            quiet=True,
        )
    journal["paused"] = None
    save(journal)


def close_pr(pr):
    value = api("pulls/" + str(pr["number"]))
    r.require(value["head"]["ref"] == pr["branch"], "Acceptance PR branch changed")
    if value["state"] == "open":
        api("pulls/" + str(pr["number"]), "PATCH", {"state": "closed"})
    name = "preview-" + str(pr["number"])
    p.wait_for("Git cleanup for " + name, lambda: name not in resources.current_previews(), 300)


def recover():
    if not JOURNAL.exists():
        print("No Milestone 5 recovery is pending.", flush=True)
        return
    journal = json.loads(JOURNAL.read_text())
    r.require(
        journal.get("owner") == r.OWNER and journal["prefix"].startswith("acceptance/m5-"),
        "Unknown acceptance journal",
    )
    resume_worker(journal)
    # Discover a PR even if the process exited just after GitHub accepted its creation.
    for branch in journal["branches"]:
        r.require(branch.startswith(journal["prefix"] + "-"), "Unowned acceptance branch")
        for pr in api("pulls?state=all&head=HickoDev:" + branch):
            close_pr({"number": pr["number"], "branch": branch})
    v.reconcile(apply=True)
    for branch in journal["branches"]:
        refs = api("git/matching-refs/heads/" + branch)
        if any(x["ref"] == "refs/heads/" + branch for x in refs):
            api("git/refs/heads/" + branch, "DELETE")
    JOURNAL.unlink()
    print("Acceptance PRs, namespaces, resources and temporary branches cleaned up.", flush=True)


def verify():
    r.require(not JOURNAL.exists(), "Run resources.py recover --github --allow-github-writes first")
    r.require(resources.active(), "Run resources.py up --github first")
    journal = {
        "owner": r.OWNER,
        "prefix": "acceptance/m5-" + secrets.token_hex(5),
        "base": api("git/ref/heads/main")["object"]["sha"],
        "branches": [],
        "prs": [],
        "paused": None,
    }
    save(journal)
    result = {"at": datetime.now(UTC).isoformat(), "checks": [], "prs": []}

    def checked(name, **details):
        result["checks"].append({"name": name, **details})
        r.save(RESULT, result)
        print("PASS: " + name, flush=True)

    try:
        with p.forward():
            baseline = p.http("/tasks")[1]
            staging_report = export(18000, baseline)
        pvc_uid = p.get("pvc", "data-demo-postgres-0")["metadata"]["uid"]
        prs = [open_pr(journal, "a"), open_pr(journal, "b")]
        result["prs"] = copy.deepcopy(prs)
        pairs = [wait_record(pr) for pr in prs]
        names = [x[0] for x in pairs]
        resources_before = {name: tf.ensure(name) for name in ["staging", *names]}
        r.require(
            len({x["bucket"] for x in resources_before.values()}) == 3, "Report buckets collide"
        )
        checked("three isolated resource sets", resources=resources_before)
        reports = []
        for index, name in enumerate(names):
            port = 18051 + index
            with p.forward(namespace=name, port=port):
                r.require(p.http("/tasks", port=port)[1] == [], "Preview database was not empty")
                code, task = p.http(
                    "/tasks",
                    method="POST",
                    payload={"title": journal["prefix"] + "-" + str(index)},
                    port=port,
                )
                r.require(code == 201, "Could not create isolated task")
                reports.append(export(port, [task]))
        checked("two real PR exports and isolated task snapshots")
        cloud = Cloud(r.ENDPOINT, names[0])
        try:
            with p.forward(namespace=names[0], port=18051):
                pause_worker(journal, names[0])
                try:
                    code, job = p.http("/exports", method="POST", payload={}, port=18051)
                    r.require(code == 202, "Crash test request failed")
                    try:
                        p.k(
                            "-n",
                            names[0],
                            "exec",
                            "deployment/demo-api",
                            "--",
                            "python",
                            "-m",
                            "app.worker",
                            "--once",
                            "--crash-after-upload",
                            quiet=True,
                            timeout=45,
                        )
                    except RuntimeError as exc:
                        r.require("73" in str(exc), "Worker did not reach the injected crash")
                    else:
                        raise RuntimeError("Worker failed to crash after uploading")
                    key = "exports/" + job["id"] + ".json"
                    cloud.s3.head_object(Bucket=cloud.bucket, Key=key)
                    r.require(
                        p.http("/exports/" + job["id"], port=18051)[1]["status"] == "pending",
                        "Crash unexpectedly committed the job",
                    )
                finally:
                    resume_worker(journal)
                p.wait_for(
                    "redelivery after process crash",
                    lambda: p.http("/exports/" + job["id"], port=18051)[1]["status"] == "completed",
                    120,
                )
                objects = cloud.s3.list_objects_v2(Bucket=cloud.bucket, Prefix=key).get(
                    "Contents", []
                )
                r.require(len(objects) == 1, "Crash retry created duplicate reports")
                checked(
                    "real worker process exits 73 after upload; redelivery completes one report"
                )
                pause_worker(journal, names[0])
                try:
                    tf.actual(names[0])  # Ownership checked before the scoped fault.
                    for page in cloud.s3.get_paginator("list_objects_v2").paginate(
                        Bucket=cloud.bucket
                    ):
                        for obj in page.get("Contents", []):
                            cloud.s3.delete_object(Bucket=cloud.bucket, Key=obj["Key"])
                    cloud.s3.delete_bucket(Bucket=cloud.bucket)
                    cloud.sqs.delete_queue(QueueUrl=cloud.queue_url())

                    def interrupted():
                        raise RuntimeError("injected interruption after Terraform apply")

                    try:
                        tf.ensure(names[0], resources.still_desired, after_apply=interrupted)
                    except RuntimeError as exc:
                        r.require(
                            "injected interruption" in str(exc), "Unexpected provisioning error"
                        )
                    tf.ensure(names[0], resources.still_desired)
                finally:
                    resume_worker(journal)
                report_id = reports[0]["export_id"]
                p.wait_for(
                    "report reconstruction after resource reset",
                    lambda: p.http("/exports/" + report_id + "/download", port=18051)[0] == 200,
                    120,
                )
                r.require(
                    p.http("/exports/" + report_id + "/download", port=18051)[1] == reports[0],
                    "Rebuilt report changed",
                )
                checked(
                    "scoped Floci resource reset and interrupted reconciliation recover saved reports"
                )
            prs[0]["sha"] = edit(prs[0]["branch"], "Milestone 5 acceptance update")
            save(journal)
            _, updated = wait_record(prs[0])
            r.require(
                updated["image"]["digest"] != pairs[0][1]["image"]["digest"],
                "PR update did not roll out a new image",
            )
            r.require(
                resources.current_previews()[names[1]] == pairs[1][1], "Other PR record changed"
            )
            r.require(
                {name: tf.ensure(name) for name in ["staging", *names]} == resources_before,
                "PR update replaced resources",
            )
            checked("real PR update changes only its image and preserves resource identities")
            # Restart the owned emulator without removing its persistent volume.
            r.inspect_floci()
            p.run("docker", "restart", r.FLOCI, quiet=True)
            r.bootstrap_floci()
            v.reconcile(apply=True)
            for index, name in enumerate(names):
                with p.forward(namespace=name, port=18051 + index):
                    r.require(
                        p.http(
                            "/exports/" + reports[index]["export_id"] + "/download",
                            port=18051 + index,
                        )[1]
                        == reports[index],
                        "Emulator restart lost a report",
                    )
            checked("persistent Floci restart and route refresh preserve both previews")
            close_pr(prs[0])
            p.wait_for(
                "Application removal before cloud cleanup",
                lambda: not v.optional("application", names[0]),
                240,
            )
            ns = v.optional("namespace", names[0])
            if ns:
                v.delete_namespace({"name": names[0], "uid": ns["metadata"]["uid"]})
            r.require(resources.may_delete(names[0]), "Workers still exist at cloud cleanup")
            tf.actual(names[0])
            cloud.sqs.delete_queue(QueueUrl=cloud.queue_url())
            tf.record(names[0], "cleanup_error", error="injected interruption after queue deletion")
            v.reconcile(apply=True)
            r.require(not tf.actual(names[0]), "Partial cleanup did not finish")
            with p.forward(namespace=names[1], port=18052):
                export(18052, reports[1]["tasks"])
            with p.forward():
                r.require(p.http("/tasks")[1] == baseline, "Staging tasks changed")
                r.require(
                    p.http("/exports/" + staging_report["export_id"] + "/download")[1]
                    == staging_report,
                    "Staging report changed",
                )
            r.require(
                p.get("pvc", "data-demo-postgres-0")["metadata"]["uid"] == pvc_uid,
                "Staging PVC changed",
            )
            checked(
                "close stops workloads before cloud deletion; partial cleanup retries; other PR and staging survive"
            )
        finally:
            cloud.close()
    finally:
        recover()
    result["completed"] = True
    r.save(RESULT, result)
    print("Milestone 5 acceptance passed; results: " + str(RESULT), flush=True)
