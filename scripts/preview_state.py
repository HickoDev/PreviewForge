"""Validated desired state and conflict-aware updates; no cluster/cloud dependencies."""

import copy
import re
from datetime import UTC, datetime, timedelta

REPOSITORY = "HickoDev/PreviewForge"
LOCAL_IMAGE = "docker.io/previewforge/demo"
REMOTE_IMAGE = "ghcr.io/hickodev/previewforge-demo"
STAGING = "gitops/staging/image.json"
PREFIX = "gitops/previews/"


def require(value, message):
    if not value:
        raise ValueError(message)


def timestamp(value):
    result = datetime.fromisoformat(value)
    require(result.tzinfo is not None, "Timestamp requires a timezone")
    return result


def preview_name(number):
    require(type(number) is int and 0 < number < 1_000_000_000, "Invalid PR number")
    return f"preview-{number}"


def validate_image(record, local=False):
    require(re.fullmatch(r"[a-f0-9]{40}", record.get("sourceSha", "")), "Invalid source SHA")
    image = record["image"]
    require(
        image["repository"] == (LOCAL_IMAGE if local else REMOTE_IMAGE),
        "Unapproved image repository",
    )
    require(re.fullmatch(r"sha256:[a-f0-9]{64}", image["digest"]), "Immutable digest required")
    require(image["pullPolicy"] == ("Never" if local else "IfNotPresent"), "Wrong pull policy")


def validate_record(record, local=False):
    require(record["schemaVersion"] == 1, "Unsupported preview record")
    require(record["repository"] == REPOSITORY, "Wrong repository")
    require(record["environment"] == preview_name(record["pr"]), "Wrong environment identity")
    require(
        timestamp(record["createdAt"])
        <= timestamp(record["updatedAt"])
        < timestamp(record["expiresAt"]),
        "Invalid preview lifetime",
    )
    validate_image(record, local)


def eligible(build, state):
    """Check freshly fetched provider state, never a PR number supplied by an artifact."""
    if build.get("repository") != REPOSITORY or build.get("conclusion") != "success":
        return False
    if not build.get("published") or build.get("sourceSha") != state.get("headSha"):
        return False
    if build.get("event") == "push":
        return state.get("branch") == "main" and state.get("repository") == REPOSITORY
    return (
        build.get("event") == "pull_request"
        and type(build.get("pr")) is int
        and build["pr"] == state.get("number")
        and state.get("state") == "open"
        and state.get("repository") == REPOSITORY
        and state.get("headRepository") == REPOSITORY
        and state.get("author") == "HickoDev"
    )


def update_build(records, build, state, *, local=False, now=None):
    result = copy.deepcopy(records)
    if not eligible(build, state):
        return result
    validate_image(build, local)
    now = now or datetime.now(UTC)
    image = {key: copy.deepcopy(build[key]) for key in ("image", "sourceSha")}
    if build["event"] == "push":
        result[STAGING] = image
        return result
    name = preview_name(build["pr"])
    path = PREFIX + name + ".json"
    old = records.get(path)
    if old:
        validate_record(old, local)
        if old["sourceSha"] == image["sourceSha"] and old["image"] == image["image"]:
            return result
    result[path] = {
        "schemaVersion": 1,
        "repository": REPOSITORY,
        "pr": build["pr"],
        "environment": name,
        **image,
        "createdAt": old["createdAt"] if old else now.isoformat(),
        "updatedAt": now.isoformat(),
        "expiresAt": (now + timedelta(hours=48)).isoformat(),
        "build": {"runId": build["runId"], "attempt": build["attempt"]},
    }
    validate_record(result[path], local)
    return result


def prune_records(records, get_pr, *, local=False, now=None):
    result = copy.deepcopy(records)
    now = now or datetime.now(UTC)
    for path, record in records.items():
        if not path.startswith(PREFIX):
            continue
        validate_record(record, local)
        require(path == PREFIX + record["environment"] + ".json", "Record path mismatch")
        state = get_pr(record["pr"])  # API errors abort; unknown is never treated as closed.
        require(state.get("number") == record["pr"], "Provider returned the wrong PR")
        require(state.get("state") in {"open", "closed"}, "Unknown PR state")
        if (
            state["state"] == "closed"
            or state.get("headRepository") != REPOSITORY
            or state.get("author") != "HickoDev"
            or timestamp(record["expiresAt"]) <= now
        ):
            del result[path]
    return result


def transact(store, change, attempts=5):
    """Retry from the new Git head; change rechecks PR/main state on EVERY attempt."""
    for _ in range(attempts):
        revision, before = store.snapshot()
        after = change(before)
        if before == after:
            return revision, False
        if store.compare_swap(revision, before, after):
            return store.head(), True
    raise RuntimeError("Desired-state writers kept conflicting; safe to retry later")
