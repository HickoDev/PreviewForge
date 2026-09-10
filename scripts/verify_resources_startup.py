"""Verify the documented M5 startup command after stopping the retained local services."""

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime

import platform_local as p
import resources
from reconciler import runtime as r


def verify():
    r.require(resources.active(), "Run resources.py up --github first")
    r.require(
        not (r.RUNTIME / "verification-recovery.json").exists(), "Recover the PR exercise first"
    )
    result = {"startedAt": datetime.now(UTC).isoformat()}
    with p.forward():
        baseline = p.http("/tasks")[1]
        code, job = p.http("/exports", method="POST", payload={})
        r.require(code == 202, "Export was not accepted")
        identifier = job["id"]
        p.wait_for(
            "pre-restart report",
            lambda: p.http("/exports/" + identifier)[1]["status"] == "completed",
            120,
        )
        completed = p.http("/exports/" + identifier)[1]["completed_at"]
        report = p.http("/exports/" + identifier + "/download")[1]
    pvc = p.get("pvc", "demo-postgres")["metadata"]["uid"]
    monitoring = {
        x["metadata"]["name"]: x["metadata"]["uid"]
        for x in p.get("pvc", namespace="observability")["items"]
    }
    node = p.owned_container(p.NODE, "io.x-k8s.kind.cluster")
    floci = r.inspect_floci()
    r.require(node and floci, "Both retained PreviewForge containers are required")
    journal = r.RUNTIME / "startup-recovery.json"
    r.save(
        journal,
        {
            "owner": r.OWNER,
            "startedAt": result["startedAt"],
            "restoreCommand": "python scripts/resources.py up --github",
        },
    )
    resumed = False
    try:
        with r.lock(p.RUNTIME / "operation.lock"):
            p.run("docker", "stop", p.NODE, quiet=True)
            p.run("docker", "stop", r.FLOCI, quiet=True)
        print(
            "Retained kind and Floci stopped; running the documented startup command.", flush=True
        )
        started = time.monotonic()
        p.run(sys.executable, "-u", p.ROOT / "scripts/resources.py", "up", "--github", timeout=900)
        resumed = True
        result["startupSeconds"] = round(time.monotonic() - started, 2)
        with p.forward():
            r.require(p.http("/health/ready")[0] == 200, "Resumed API is not ready")
            r.require(p.http("/tasks")[1] == baseline, "Staging tasks changed across restart")
            r.require(
                p.http("/exports/" + identifier + "/download")[1] == report,
                "Saved report changed across restart",
            )
            r.require(
                p.http("/exports/" + identifier)[1]["completed_at"] == completed,
                "Report had to be rebuilt after ordinary restart",
            )
        r.require(p.get("pvc", "demo-postgres")["metadata"]["uid"] == pvc, "Staging PVC changed")
        r.require(
            {
                x["metadata"]["name"]: x["metadata"]["uid"]
                for x in p.get("pvc", namespace="observability")["items"]
            }
            == monitoring,
            "Monitoring PVC changed",
        )
        r.require(
            p.owned_container(p.NODE, "io.x-k8s.kind.cluster")["Id"] == node["Id"]
            and r.inspect_floci()["Id"] == floci["Id"],
            "A retained container was replaced",
        )
        result.update(
            {
                "completedAt": datetime.now(UTC).isoformat(),
                "passed": True,
                "stagingPvcUid": pvc,
                "monitoringPvcUids": monitoring,
                "taskCount": len(baseline),
                "exportId": identifier,
                "reportSha256": hashlib.sha256(
                    json.dumps(report, sort_keys=True).encode()
                ).hexdigest(),
                "reportRebuilt": False,
                "containersPreserved": True,
            }
        )
        r.save(r.RUNTIME / "milestone-5-startup.json", result)
        journal.unlink()
        print(json.dumps(result), flush=True)
    finally:
        if not resumed:
            print("Restoring the retained services after the interrupted check.", flush=True)
            p.run(
                sys.executable, "-u", p.ROOT / "scripts/resources.py", "up", "--github", timeout=900
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-faults", action="store_true")
    r.require(
        parser.parse_args().allow_faults,
        "This check briefly stops the owned cluster and Floci; use --allow-faults",
    )
    verify()
