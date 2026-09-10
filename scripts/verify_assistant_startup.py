"""Verify independent task exports with AI stopped, then the documented assistant startup."""

import json
import time
from datetime import UTC, datetime

import assistant as a
import platform_local as p


def verify():
    with a.exercise_lock():
        with a.forward():
            if a.http("/health/ready")["mode"] != "mock":
                raise ValueError("Startup verification requires mock mode")
        app = a.owned("application", a.NAME, "argocd")
        if not app:
            raise ValueError("First complete the ordinary Argo assistant startup")
        pvc = p.get("pvc", "demo-postgres")["metadata"]["uid"]
        report = {"started_at": datetime.now(UTC).isoformat(), "staging_pvc": pvc}
        try:
            p.patch(
                "application",
                a.NAME,
                {"spec": {"syncPolicy": {"automated": {"enabled": False}}}},
                "argocd",
            )
            p.k("scale", "deployment/" + a.NAME, "-n", a.NAMESPACE, "--replicas=0", quiet=True)
            p.wait_for(
                "assistant stopped", lambda: not p.get("pods", namespace=a.NAMESPACE)["items"], 90
            )
            with p.forward(port=18081):
                tasks = p.http("/tasks", port=18081)[1]
                if p.http("/health/ready", port=18081)[0] != 200:
                    raise ValueError("Staging was not ready with assistant stopped")
                status, job = p.http("/exports", method="POST", port=18081)
                if status != 202:
                    raise ValueError("Export was not accepted with assistant stopped")
                p.wait_for(
                    "export completes independently of AI",
                    lambda: p.http("/exports/" + job["id"], port=18081)[1]["status"] == "completed",
                    60,
                )
                exported = p.http("/exports/" + job["id"] + "/download", port=18081)[1]
                if exported["tasks"] != tasks:
                    raise ValueError("Export differs from staging tasks")
                report.update(
                    assistant_stopped=True,
                    export_completed_without_ai=True,
                    export_id=job["id"],
                    task_count=len(tasks),
                )
            started = time.monotonic()
            p.run("python", p.ROOT / "scripts/assistant.py", "up", timeout=600)
            report["startup_seconds"] = round(time.monotonic() - started, 2)
            with a.forward():
                health = a.http("/health/ready")
                if health["mode"] != "mock" or health["live_enabled"]:
                    raise ValueError("Startup did not preserve mock mode")
                schema = a.http("/openapi.json")
                if "requestBody" not in schema["paths"]["/diagnoses"]["post"]:
                    raise ValueError("Swagger diagnosis input is missing")
                entry = a.read_policy()["environments"]["staging"]
                result = a.http(
                    "/diagnoses", {"environment": "staging", "source_sha": entry["source_sha"]}
                )
                if result["error"] or result["diagnosis"]["status"] != "healthy":
                    raise ValueError("Staging diagnosis failed after startup")
                report["staging_diagnosis"] = result
            with p.forward(port=18081):
                if p.http("/tasks", port=18081)[1] != tasks:
                    raise ValueError("Staging tasks changed")
            if p.get("pvc", "demo-postgres")["metadata"]["uid"] != pvc:
                raise ValueError("Staging PVC changed")
            report.update(completed_at=datetime.now(UTC).isoformat(), passed=True)
            output = a.RUNTIME / "milestone-6-startup.json"
            output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(
                "PASS: AI-independent export, documented startup, Swagger and live scoped mock diagnosis"
            )
            print("Saved: " + str(output))
        finally:
            # Restore availability even if an assertion or Ctrl+C interrupts this
            # AI-only test; no staging controller/workload is modified.
            p.patch(
                "application",
                a.NAME,
                {"spec": {"syncPolicy": {"automated": {"enabled": True}}}},
                "argocd",
            )
            p.k("scale", "deployment/" + a.NAME, "-n", a.NAMESPACE, "--replicas=1", quiet=True)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-faults", action="store_true")
    args = parser.parse_args()
    if not args.allow_faults:
        parser.error("Use --allow-faults to stop only the owned assistant during verification")
    verify()
