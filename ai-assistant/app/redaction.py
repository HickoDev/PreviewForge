"""Project-specific projection first; redaction is an additional layer, not DLP."""

import json
import re
from datetime import UTC, datetime

from app.schemas import Bundle

SECRET = re.compile(
    r"(?i)(?:nvapi-[\w-]+|(?:sk|ghp|github_pat)-?[A-Za-z0-9_]{12,}|"
    r"PF_SECRET_CANARY_[A-Za-z0-9_]+|Bearer\s+[^\s\"']+|"
    r"[a-z][a-z0-9+.-]*://[^\s\"']+|"
    r"(?:password|passwd|api[_-]?key|authorization|secret|token)\s*[=:]\s*[^\s,;]+)"
)


def redact(text, secrets=()):
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return SECRET.sub("[REDACTED]", text)


def signals(source, text):
    """Never forward arbitrary log/diff/event prose. Emit recognized signals only.

    This deliberately loses unfamiliar diagnostics. An omission is preferable
    to forwarding a connection string, source code or embedded instruction.
    """
    result = []
    for line in text[:32768].splitlines():
        if source == "diff":
            match = re.fullmatch(
                r"([+-])\s*(?:DATABASE_PORT[=:]|port:)\s*[\"']?(\d{1,5})[\"']?\s*", line
            )
            if match and 1 <= int(match[2]) <= 65535:
                result.append(f"{match[1]} DATABASE_PORT={int(match[2])}")
            continue
        lower = line.lower()
        if "database_unavailable" in line:
            # Only select four application-controlled telemetry fields.
            try:
                obj = json.loads(line[line.index("{") :])
                if (
                    isinstance(obj, dict)
                    and isinstance(obj.get("event"), str)
                    and obj["event"].startswith("{")
                ):
                    # PreviewForge's JSON formatter can wrap a structured event
                    # string. Unwrap one level, then apply the same field allowlist.
                    obj = json.loads(obj["event"])
                if not isinstance(obj, dict):
                    continue
                if obj.get("event") == "database_unavailable":
                    result.append("database_unavailable")
                    if obj.get("connection_refused") is True:
                        result.append("database connection refused")
                    elif obj.get("error_type") == "OperationalError":
                        result.append("database operational error")
                    port = obj.get("database_port")
                    if type(port) is int and 1 <= port <= 65535:
                        result.append(f"database_port={port}")
            except (ValueError, TypeError):
                pass
        # Controlled fixture and Kubernetes event signals, without their text.
        for pattern, output in (
            (
                r"(?:database|postgres).*connection refused|connection refused.*(?:database|postgres)",
                "database connection refused",
            ),
            (
                r"missing required (?:variable|configuration).*DATABASE_HOST",
                "missing required variable DATABASE_HOST",
            ),
            (r"ImagePullBackOff|ErrImagePull|InvalidImageName", "image pull failed"),
            (r"OOMKilled", "OOMKilled"),
            (
                r"(?:floci|aws).*endpoint.*(?:refused|unreachable|mismatch)",
                "Floci endpoint unreachable",
            ),
            (r"readiness probe failed", "readiness probe failed"),
        ):
            if re.search(pattern, line, re.IGNORECASE):
                result.append(output)
        if "ignore" in lower or "system prompt" in lower or "execute" in lower:
            result.append("untrusted instruction-like text omitted")
    return "\n".join(dict.fromkeys(result))[:3000]


def sanitize(bundle: Bundle, settings, secrets=(), now=None):
    now = now or datetime.now(UTC)
    clean = []
    missing = list(bundle.missing_evidence)
    size = 0
    seen = set()
    for item in bundle.evidence:
        if item.id in seen:
            raise ValueError("Duplicate evidence identity")
        seen.add(item.id)
        age = (now - item.timestamp).total_seconds() if item.timestamp.tzinfo else float("inf")
        if (item.environment, item.source_sha) != (
            bundle.environment,
            bundle.source_sha,
        ) or not -30 <= age <= settings.ai_max_age_seconds:
            missing.append(f"{item.id}: stale or mismatched evidence omitted")
            continue
        if item.revision and item.revision != bundle.config_revision:
            missing.append(f"{item.id}: configuration revision mismatch omitted")
            continue
        excerpt = (
            signals(item.source, item.excerpt)
            if item.source in {"log", "diff", "event"}
            else item.excerpt
        )
        excerpt = redact(excerpt, secrets)
        if not excerpt:
            missing.append(f"{item.id}: unrecognized text omitted")
            continue
        if size + len(excerpt) > settings.ai_max_evidence_chars:
            missing.append("Evidence truncated at the configured character budget")
            break
        size += len(excerpt)
        clean.append(item.model_copy(update={"excerpt": excerpt}))
    return bundle.model_copy(
        update={"evidence": clean, "missing_evidence": list(dict.fromkeys(missing))[:30]}
    )
