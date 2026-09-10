"""Bounded labeled evaluation. Live outputs still require human semantic review."""

import json
import statistics
import time
from datetime import UTC, datetime

import assistant as a
import platform_local as p


def score(case, report):
    diagnosis = report.get("diagnosis")
    expected = case["expected"]
    if not diagnosis:
        return {
            "matched_expected": False,
            "valid_references": False,
            "supported_cause": False,
            "abstained": False,
            "unsupported_statements": None,
            "human_review": "provider_or_validation_error",
        }
    sources = {e["id"]: e for e in report["evidence"]}
    ids = [
        ref
        for item in diagnosis["observed_facts"] + diagnosis["hypotheses"]
        for ref in item["evidence_ids"]
    ]
    references = all(ref in sources for ref in ids)
    quotes = all(
        any(f["quote"] in sources[ref]["excerpt"] for ref in f["evidence_ids"] if ref in sources)
        for f in diagnosis["observed_facts"]
    )
    causes = [h["cause"] for h in diagnosis["hypotheses"]]
    cited_sources = {
        sources[ref]["source"]
        for h in diagnosis["hypotheses"]
        for ref in h["evidence_ids"]
        if ref in sources
    }
    supported = (
        causes == expected["causes"]
        and set(expected["required_sources"]) <= cited_sources
        and references
    )
    mock = report["metadata"]["provider"] == "mock"
    # Mock fact statements reproduce selected evidence verbatim by construction.
    # Do not use exact quotes/valid IDs as a semantic truth score for a real LLM.
    extractive = all(
        f["statement"].startswith("Observed ")
        and any(
            f["statement"]
            == f"Observed {sources[ref]['source']} evidence: {sources[ref]['excerpt'][:180]}"
            for ref in f["evidence_ids"]
            if ref in sources
        )
        for f in diagnosis["observed_facts"]
    )
    return {
        "matched_expected": diagnosis["status"] == expected["status"] and supported,
        "valid_references": references and quotes,
        "supported_cause": supported,
        "abstained": diagnosis["status"] == "insufficient_evidence",
        "unsupported_statements": 0 if mock and extractive and supported else None,
        "human_review": "extractive_mock_checked"
        if mock
        else "pending: compare every factual claim and suggested check with cited excerpts and the labeled expectation",
    }


def evaluate(action="evaluate", trials=1, port=18080):
    if not 1 <= trials <= 2:
        raise ValueError("Use one or two bounded trials")
    live = action != "evaluate"
    cases = json.loads((p.ROOT / "ai-assistant/evaluations/fixtures/cases.json").read_text())
    if action == "live-smoke":
        cases = [c for c in cases if c["id"] == "wrong-port"]
        trials = 1
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "mode": "nvidia" if live else "mock",
        "planned_cases": len(cases) * trials,
        "cases": [],
        "scope": "Small synthetic fixture evaluation. Mock uses the deterministic baseline; it measures plumbing, not model quality. Live claims need human review.",
    }
    output = a.runtime() / (action + "-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".json")
    # Capture a local baseline independently of any model provider or key.
    script = "import json; from app.fixtures import cases,load; from app.redaction import sanitize; from app.config import Settings; from app.baseline import diagnose; print(json.dumps({c['id']:diagnose(sanitize(load(c['id']),Settings(ai_mode='mock',ai_live_requests_enabled=False))).model_dump(mode='json') for c in cases()}))"
    baseline = json.loads(
        p.run(
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "previewforge-ai-tests",
            "python",
            "-c",
            script,
            quiet=True,
        )
    )
    with a.forward(port):
        health = a.http("/health/ready", port=port)
        if health["mode"] != report["mode"]:
            raise ValueError("Service mode differs from the requested evaluation")
        stop = False
        for trial in range(1, trials + 1):
            for case in cases:
                started = time.monotonic()
                result = a.http(
                    "/diagnoses",
                    {
                        "environment": "preview-42",
                        "source_sha": "a" * 40,
                        "fixture": case["id"],
                        "allow_live": live,
                    },
                    live,
                    port,
                )
                row = {
                    "id": case["id"],
                    "version": case["version"],
                    "split": case["split"],
                    "trial": trial,
                    "expected": case["expected"],
                    "scores": score(case, result),
                    "baseline": baseline[case["id"]],
                    "round_trip_ms": round((time.monotonic() - started) * 1000, 2),
                    "report": result,
                }
                report["cases"].append(row)
                output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                print(
                    f"{case['id']}: {result['error'] or result['diagnosis']['status']}; attempts={result['metadata']['attempts']}",
                    flush=True,
                )
                if result["error"] in {
                    "missing_key",
                    "invalid_credentials_or_access",
                    "rate_limited",
                    "model_or_request_rejected",
                    "provider_unavailable",
                    "provider_timeout",
                }:
                    stop = True
                    break
            if stop:
                break
    times = [c["round_trip_ms"] for c in report["cases"]]
    report["summary"] = {
        "completed_cases": len(times),
        "matched_expected": sum(c["scores"]["matched_expected"] for c in report["cases"]),
        "valid_references": sum(c["scores"]["valid_references"] for c in report["cases"]),
        "abstentions": sum(c["scores"]["abstained"] for c in report["cases"]),
        "attempts": sum(c["report"]["metadata"]["attempts"] for c in report["cases"]),
        "latency_ms": {"median": statistics.median(times), "min": min(times), "max": max(times)},
        "unsupported_statements": None
        if live
        else sum(c["scores"]["unsupported_statements"] or 0 for c in report["cases"]),
        "human_review_pending": live,
    }
    report["completed_at"] = datetime.now(UTC).isoformat()
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Saved sanitized evaluation: " + str(output))
    if stop:
        raise RuntimeError(
            "Evaluation stopped on provider/access/quota failure; inspect the sanitized report"
        )
    return report, output
