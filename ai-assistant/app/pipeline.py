import hashlib
import json
import time
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import ValidationError

from app.providers import PROMPT_VERSION, ProviderError
from app.redaction import redact, sanitize
from app.schemas import Diagnosis


def validate_output(content, bundle, secrets=()):
    if len(content.encode()) > 16000:
        raise ValueError("Output limit")
    # Reject rather than persist a model response that contains a recognized
    # credential, URL, canary or the exact runtime key/access token.
    if redact(content, secrets) != content:
        raise ValueError("Unsafe output")
    result = Diagnosis.model_validate_json(content)
    if (result.environment, result.source_sha) != (bundle.environment, bundle.source_sha):
        raise ValueError("Wrong response identity")
    evidence = {e.id: e for e in bundle.evidence}
    for fact in result.observed_facts:
        if any(ref not in evidence for ref in fact.evidence_ids):
            raise ValueError("Unknown evidence ID")
        if not any(fact.quote in evidence[ref].excerpt for ref in fact.evidence_ids):
            raise ValueError("Quote is not supported by cited evidence")
    for hypothesis in result.hypotheses:
        if any(ref not in evidence for ref in hypothesis.evidence_ids):
            raise ValueError("Unknown evidence ID")
    if result.status == "diagnosed" and (not result.hypotheses or not result.observed_facts):
        raise ValueError("Diagnosis needs facts and hypotheses")
    if result.status != "diagnosed" and result.hypotheses:
        raise ValueError("Abstention/healthy results cannot contain a cause")
    if result.status == "healthy" and not result.observed_facts:
        raise ValueError("Health must have evidence")
    if not evidence and result.status != "insufficient_evidence":
        raise ValueError("Cannot diagnose missing evidence")
    result.missing_evidence = list(
        dict.fromkeys(bundle.missing_evidence + result.missing_evidence)
    )[:30]
    return result


async def run(bundle, settings, provider):
    started = time.monotonic()
    secrets = (
        settings.nvidia_api_key.get_secret_value(),
        settings.ai_access_token.get_secret_value(),
    )
    bundle = sanitize(bundle, settings, secrets)
    metadata = {
        "request_id": str(uuid4()),
        "timestamp": datetime.now(UTC).isoformat(),
        "environment": bundle.environment,
        "source_sha": bundle.source_sha,
        "observed_image": bundle.image,
        "config_revision": bundle.config_revision,
        "provider": provider.name,
        "model": provider.model,
        "prompt_version": PROMPT_VERSION,
        "evidence_sha256": hashlib.sha256(bundle.model_dump_json().encode()).hexdigest(),
        "attempts": 0,
        "usage": {},
        "usage_note": "Returned usage covers completed responses; timed-out/retried attempts may also consume quota.",
    }
    report = {
        "metadata": metadata,
        "diagnosis": None,
        "error": None,
        "evidence": [e.model_dump(mode="json") for e in bundle.evidence],
        "missing_evidence": bundle.missing_evidence,
    }
    try:
        completion = await provider.complete(bundle)
        metadata.update(attempts=completion.attempts, usage=completion.usage)
        report["diagnosis"] = validate_output(completion.content, bundle, secrets).model_dump(
            mode="json"
        )
    except ProviderError as exc:
        metadata.update(attempts=exc.attempts, usage=exc.usage)
        report["error"] = exc.code
    except (ValueError, ValidationError):
        report["error"] = "invalid_model_output"
    metadata["elapsed_ms"] = round((time.monotonic() - started) * 1000, 2)
    # Only metadata is logged; prompts, evidence and model text are excluded.
    print(
        json.dumps(
            {
                "event": "diagnosis",
                "request_id": metadata["request_id"],
                "provider": metadata["provider"],
                "elapsed_ms": metadata["elapsed_ms"],
                "attempts": metadata["attempts"],
                "error": report["error"],
            }
        ),
        flush=True,
    )
    return report
