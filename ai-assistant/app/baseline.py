"""Conservative deterministic comparison, also used by the clearly labeled mock."""

import re

from app.schemas import Diagnosis, Fact, Hypothesis


def diagnose(bundle):
    evidence = bundle.evidence

    def find(pattern, source=None):
        return [
            e
            for e in evidence
            if (not source or e.source == source) and re.search(pattern, e.excerpt)
        ]

    cause = None
    citations = []
    ports = find(r"DATABASE_PORT=\d+", "deployment")
    services = find(r"service_port=\d+", "service")
    errors = find("database connection refused|database operational error", "log")
    diff = find(r"\+ DATABASE_PORT=\d+", "diff")
    if ports and services and errors:
        api_port = re.search(r"DATABASE_PORT=(\d+)", ports[0].excerpt)[1]
        service_port = re.search(r"service_port=(\d+)", services[0].excerpt)[1]
        if api_port != service_port:
            cause = "Database port mismatch"
            diff = [
                e for e in diff if re.search(r"\+ DATABASE_PORT=" + api_port + r"\b", e.excerpt)
            ]
            citations = ports[:1] + services[:1] + errors[:1] + diff[:1]
    for pattern, label in (
        ("missing required variable DATABASE_HOST", "Missing required configuration"),
        ("image pull failed|ImagePullBackOff|ErrImagePull|InvalidImageName", "Image pull failure"),
        ("OOMKilled", "Container exceeded memory limit"),
        ("Floci endpoint unreachable", "Floci endpoint mismatch"),
    ):
        matches = find(pattern)
        if cause is None and matches:
            cause, citations = label, matches[:2]
    healthy = find("ready=true", "deployment")
    unknown_failure = find(
        "ready=false|readiness probe failed|CrashLoopBackOff|database_unavailable"
    )
    status = (
        "diagnosed"
        if cause
        else "healthy"
        if healthy and not unknown_failure
        else "insufficient_evidence"
    )
    if not cause:
        citations = healthy[:1] if status == "healthy" else []
    facts = [
        Fact(
            statement=f"Observed {e.source} evidence: {e.excerpt[:180]}",
            evidence_ids=[e.id],
            quote=e.excerpt[:500],
        )
        for e in citations
    ]
    return Diagnosis(
        status=status,
        environment=bundle.environment,
        source_sha=bundle.source_sha,
        summary=(
            f"Evidence suggests: {cause}."
            if cause
            else "No incident is indicated by the collected readiness evidence."
            if status == "healthy"
            else "There is not enough current, correlated evidence to identify a cause."
        ),
        observed_facts=facts,
        hypotheses=[
            Hypothesis(
                cause=cause,
                evidence_ids=[e.id for e in citations],
                limitations=[
                    "This is a hypothesis; confirm the intended configuration and current runtime state."
                ],
            )
        ]
        if cause
        else [],
        suggested_checks=["Compare the intended database port with the PostgreSQL Service port."]
        if cause == "Database port mismatch"
        else [
            "Inspect the cited condition and compare it with the intended deployment configuration."
        ]
        if cause
        else [],
        missing_evidence=bundle.missing_evidence
        or (
            ["No supported failure signal was collected"]
            if status == "insufficient_evidence"
            else []
        ),
    )
