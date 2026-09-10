"""Read-only Kubernetes HTTP collector with fixed routes and field projection."""

import json
import re
import ssl
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.schemas import Bundle, Evidence

TOKEN = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
CA = Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
SAFE_REASONS = {
    "Running",
    "Completed",
    "Error",
    "OOMKilled",
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "ErrImagePull",
    "InvalidImageName",
    "ContainerCreating",
    "CreateContainerConfigError",
}


class CollectionError(Exception):
    pass


def policy(settings):
    raw = settings.ai_policy_file.read_bytes()
    if len(raw) > 65536:
        raise CollectionError("Policy exceeds limit")
    return json.loads(raw)


class KubernetesCollector:
    def __init__(self, settings, transport=None, token_file=TOKEN, ca_file=CA):
        self.settings = settings
        self.transport = transport
        self.token_file = token_file
        self.ca_file = ca_file

    async def collect(self, request):
        rules = policy(self.settings)
        entry = rules.get("environments", {}).get(request.environment)
        if not entry or entry["source_sha"] != request.source_sha:
            raise CollectionError("Environment/source is not authorized; refresh its policy")
        env = request.environment
        config_revision = entry.get("config_revision")
        now = datetime.now(UTC)
        result = []
        missing = []
        counts = {}
        verify = (
            ssl.create_default_context(cafile=str(self.ca_file)) if not self.transport else True
        )

        def add(source, text, timestamp=now, revision=None):
            counts[source] = counts.get(source, 0) + 1
            result.append(
                Evidence(
                    id=f"{source}-{counts[source]}",
                    source=source,
                    timestamp=timestamp,
                    environment=env,
                    source_sha=request.source_sha,
                    revision=revision,
                    excerpt=text[:3000],
                )
            )

        async with httpx.AsyncClient(
            base_url="https://kubernetes.default.svc",
            verify=verify,
            trust_env=False,
            follow_redirects=False,
            transport=self.transport,
            timeout=5,
        ) as client:

            async def get(path, params=None, text=False):
                # Routes are constructed exclusively below; request/model text
                # never chooses a Kubernetes path, verb, credential or URL.
                async with client.stream(
                    "GET",
                    path,
                    params=params,
                    headers={"Authorization": "Bearer " + self.token_file.read_text().strip()},
                ) as response:
                    if response.status_code != 200:
                        raise CollectionError("Read-only evidence unavailable")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > (16384 if text else 524288):
                            raise CollectionError("Evidence response exceeds limit")
                    return raw.decode("utf-8", errors="replace") if text else json.loads(raw)

            path = f"/apis/apps/v1/namespaces/{env}/deployments/demo-api"
            deployment = await get(path)
            labels = deployment["metadata"].get("labels", {})
            if (
                labels.get("app.kubernetes.io/part-of") != "previewforge"
                or labels.get("previewforge.io/environment") != env
            ):
                raise CollectionError("Deployment ownership mismatch")
            if env != "staging" and labels.get("previewforge.io/owner") != "previewforge-m3":
                raise CollectionError("Preview ownership mismatch")
            spec = deployment["spec"]["template"]["spec"]
            container = next(c for c in spec["containers"] if c["name"] == "api")
            if container["image"] != entry["image"]:
                raise CollectionError("Deployment image differs from the authorized commit")
            status = deployment.get("status", {})
            desired = deployment["spec"].get("replicas", 1)
            ready = (
                desired > 0
                and status.get("observedGeneration", 0) >= deployment["metadata"]["generation"]
                and status.get("updatedReplicas", 0) == desired
                and status.get("replicas", 0) == desired
                and status.get("availableReplicas", 0) == desired
            )
            # No unrestricted env values, Secret references, volumes or pod specs.
            fields = [f"ready={str(ready).lower()}"]
            for item in container.get("env", []):
                if (
                    item["name"] == "DATABASE_PORT"
                    and re.fullmatch(r"[0-9]{1,5}", item.get("value", ""))
                    and 1 <= int(item["value"]) <= 65535
                ):
                    fields.append("DATABASE_PORT=" + item["value"])
            add("deployment", "\n".join(fields))
            try:
                service = await get(f"/api/v1/namespaces/{env}/services/demo-postgres")
                if service["metadata"].get("labels", {}).get("previewforge.io/environment") != env:
                    raise CollectionError("Service ownership mismatch")
                for port in service["spec"].get("ports", []):
                    if port.get("name") == "postgres" and type(port.get("port")) is int:
                        add("service", f"service_port={port['port']}")
            except CollectionError:
                missing.append("PostgreSQL Service evidence unavailable")
            try:
                argo = await get(f"/apis/argoproj.io/v1alpha1/namespaces/argocd/applications/{env}")
                if argo["spec"]["destination"]["namespace"] != env:
                    raise CollectionError("Argo destination mismatch")
                source = argo["spec"]["source"]
                if (
                    source["repoURL"] != entry["repo_url"]
                    or source.get("path") != "charts/demo-app"
                ):
                    raise CollectionError("Argo source mismatch")
                state = argo.get("status", {})
                sync = state.get("sync", {})
                revision = sync.get("revision")
                if entry.get("config_revision") and revision != entry["config_revision"]:
                    raise CollectionError(
                        "Argo has not observed the authorized configuration revision"
                    )
                sync_status = sync.get("status", "Unknown")
                health = state.get("health", {}).get("status", "Unknown")
                if sync_status not in {"Synced", "OutOfSync", "Unknown"} or health not in {
                    "Healthy",
                    "Progressing",
                    "Degraded",
                    "Missing",
                    "Suspended",
                    "Unknown",
                }:
                    raise CollectionError("Unknown Argo state")
                add(
                    "argocd",
                    f"sync={sync_status}; health={health}",
                    revision=revision if re.fullmatch(r"[a-f0-9]{40}", revision or "") else None,
                )
                if config_revision is None and re.fullmatch(r"[a-f0-9]{40}", revision or ""):
                    config_revision = revision
            except CollectionError:
                missing.append(
                    "Argo identity/status unavailable or configuration revision mismatch; Git diff omitted"
                )
            else:
                if entry.get("diff") and entry.get("config_revision"):
                    add("diff", entry["diff"], revision=entry["config_revision"])
                else:
                    missing.append(
                        "No bounded configuration diff was registered for this deployment"
                    )
            pods = await get(
                f"/api/v1/namespaces/{env}/pods",
                {"labelSelector": f"app=demo-api,previewforge.io/environment={env}", "limit": 9},
            )
            if pods.get("metadata", {}).get("continue") or len(pods["items"]) > 8:
                missing.append("Pod collection truncated at eight pods")
            for pod in pods["items"][:8]:
                meta = pod["metadata"]
                name = meta["name"]
                if (
                    not NAME.fullmatch(name)
                    or meta.get("deletionTimestamp")
                    or meta.get("labels", {}).get("previewforge.io/environment") != env
                    or meta.get("labels", {}).get("app") != "demo-api"
                ):
                    continue
                api = next((c for c in pod["spec"]["containers"] if c["name"] == "api"), {})
                if api.get("image") != entry["image"]:
                    missing.append("A pod from another image was omitted")
                    continue
                statuses = [
                    c
                    for c in pod.get("status", {}).get("containerStatuses", [])
                    if c["name"] == "api"
                ]
                state_lines = []
                for state in statuses:
                    state_lines.append(
                        f"ready={str(state.get('ready') is True).lower()}; restarts={int(state.get('restartCount', 0))}"
                    )
                    for value in state.get("state", {}).values():
                        if value.get("reason") in SAFE_REASONS:
                            state_lines.append(value["reason"])
                    previous_state = state.get("lastState", {}).get("terminated", {})
                    if previous_state.get("reason") in SAFE_REASONS:
                        try:
                            finished = datetime.fromisoformat(
                                previous_state["finishedAt"].replace("Z", "+00:00")
                            )
                            age = (now - finished).total_seconds()
                        except (ValueError, KeyError, TypeError):
                            age = float("inf")
                        if -30 <= age <= self.settings.ai_max_age_seconds:
                            state_lines.append(previous_state["reason"])
                        else:
                            missing.append("Historical container termination omitted")
                if state_lines:
                    add("pod", "\n".join(state_lines))
                try:
                    events = await get(
                        f"/api/v1/namespaces/{env}/events",
                        {"fieldSelector": "involvedObject.uid=" + meta["uid"], "limit": 20},
                    )
                    for event in events["items"][:20]:
                        if event.get("involvedObject", {}).get("uid") != meta["uid"]:
                            continue
                        stamp = (
                            event.get("lastTimestamp")
                            or event.get("eventTime")
                            or event["metadata"].get("creationTimestamp")
                        )
                        if stamp:
                            add("event", event.get("message", ""), timestamp=stamp)
                        else:
                            missing.append("An event without a timestamp was omitted")
                except CollectionError:
                    missing.append("Some pod events unavailable")
                # Do not invent logs for containers that have never started.
                running = any("running" in s.get("state", {}) for s in statuses)
                previous = any("terminated" in s.get("lastState", {}) for s in statuses)
                if running or previous:
                    try:
                        logs = await get(
                            f"/api/v1/namespaces/{env}/pods/{name}/log",
                            {
                                "container": "api",
                                "sinceSeconds": 300,
                                "tailLines": 40,
                                "limitBytes": 8192,
                                "timestamps": "true",
                                "previous": str(not running and previous).lower(),
                            },
                            text=True,
                        )
                        add("log", logs)
                    except CollectionError:
                        missing.append("Some application logs unavailable")
            # Detect a rollout racing collection before sending anything hosted.
            latest = await get(path)
            if (
                latest["metadata"].get("uid") != deployment["metadata"].get("uid")
                or latest["metadata"]["generation"] != deployment["metadata"]["generation"]
            ):
                raise CollectionError("Deployment changed during collection; retry")
        if len(result) > 40:
            missing.append("Evidence truncated at forty entries")
        return Bundle(
            environment=env,
            source_sha=request.source_sha,
            image=entry["image"],
            config_revision=config_revision,
            evidence=result[:40],
            missing_evidence=missing[:30],
        )
