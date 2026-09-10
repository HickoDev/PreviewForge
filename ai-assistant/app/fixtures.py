import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.schemas import Bundle, Evidence

FIXTURES = Path(__file__).resolve().parents[1] / "evaluations/fixtures"
SHA = "a" * 40


def cases():
    return json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))


def load(name):
    case = next((c for c in cases() if c["id"] == name), None)
    if case is None:
        raise ValueError("Unknown fixture")
    now = datetime.now(UTC)
    evidence = [
        Evidence(
            id=e["id"],
            source=e["source"],
            timestamp=now - timedelta(seconds=e.get("age_seconds", 0)),
            environment=e.get("environment", "preview-42"),
            source_sha=e.get("source_sha", SHA),
            excerpt=e["excerpt"],
            revision="b" * 40 if e["source"] == "diff" else None,
        )
        for e in case["evidence"]
    ]
    return Bundle(
        environment="preview-42",
        source_sha=SHA,
        image="synthetic-fixture@sha256:" + "c" * 64,
        config_revision="b" * 40,
        evidence=evidence,
    )
