import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError

from app import fixtures
from app.baseline import diagnose
from app.config import Settings
from app.main import create_app
from app.pipeline import run, validate_output
from app.providers import (
    Completion,
    MockProvider,
    NvidiaProvider,
    ProviderError,
    messages,
    retry_delay,
)
from app.redaction import redact, sanitize, signals


def test_actual_application_json_logging_envelope_is_safely_projected():
    event = {
        "event": "database_unavailable",
        "database_port": 5433,
        "connection_refused": True,
        "secret": "PF_SECRET_CANARY_NESTED",
    }
    line = "2026-09-10T00:00:00Z " + json.dumps(
        {"timestamp": "2026-09-10T00:00:00Z", "level": "WARNING", "event": json.dumps(event)}
    )
    assert (
        signals("log", line)
        == "database_unavailable\ndatabase connection refused\ndatabase_port=5433"
    )
    assert "PF_SECRET_CANARY" not in signals("log", line)


def settings(**kwargs):
    return Settings(_env_file=None, **kwargs)


def bundle(name="wrong-port"):
    return sanitize(fixtures.load(name), settings())


def live(**kwargs):
    return settings(
        ai_mode="nvidia",
        ai_live_requests_enabled=True,
        nvidia_api_key=SecretStr("test-runtime-credential"),
        **kwargs,
    )


def completion(content=None, **kwargs):
    value = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": content or diagnose(bundle()).model_dump_json()},
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }
    value.update(kwargs)
    return httpx.Response(200, json=value)


@pytest.mark.parametrize("case", fixtures.cases(), ids=lambda c: c["id"])
def test_labeled_mock_pipeline(case):
    report = asyncio.run(run(fixtures.load(case["id"]), settings(), MockProvider()))
    assert report["error"] is None
    result = report["diagnosis"]
    assert result["status"] == case["expected"]["status"]
    assert [h["cause"] for h in result["hypotheses"]] == case["expected"]["causes"]
    assert report["metadata"]["attempts"] == 0
    assert "PF_SECRET_CANARY" not in json.dumps(report)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"ai_mode": "other"},
        {"nvidia_base_url": "https://example.com/v1"},
        {"nvidia_base_url": "http://integrate.api.nvidia.com/v1"},
        {"nvidia_base_url": "https://integrate.api.nvidia.com.evil/v1"},
        {"nvidia_base_url": "https://user@integrate.api.nvidia.com/v1"},
        {"ai_max_attempts": 3},
        {"ai_request_budget_seconds": 121},
        {"ai_max_concurrent_requests": 3},
        {"ai_live_requests_enabled": True},
    ],
)
def test_configuration_boundaries(kwargs):
    with pytest.raises(ValidationError):
        settings(**kwargs)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda x: x.update(source_sha="d" * 40),
        lambda x: x.update(environment="preview-43"),
        lambda x: x.update(extra="unknown"),
        lambda x: x["observed_facts"][0].update(evidence_ids=["log-999"]),
        lambda x: x["observed_facts"][0].update(quote="invented quote"),
        lambda x: x["hypotheses"][0].update(evidence_ids=["log-999"]),
        lambda x: x.update(status="healthy"),
        lambda x: x.update(summary="password=PF_SECRET_CANARY_OUTPUT_001"),
    ],
)
def test_rejects_invalid_or_unsupported_model_output(mutation):
    value = diagnose(bundle()).model_dump(mode="json")
    mutation(value)
    with pytest.raises(ValueError):
        validate_output(json.dumps(value), bundle())


def test_minimization_secret_canaries_and_runtime_secrets():
    source = fixtures.load("secret-canary")
    source.evidence[0].excerpt += "\nprivate-runtime-test-key"
    clean = sanitize(source, settings(), ["private-runtime-test-key"])
    text = json.dumps(messages(clean))
    assert "PF_SECRET_CANARY" not in text
    assert "private-runtime-test-key" not in text
    assert "postgresql://" not in text
    assert "DATABASE_PORT=5433" in text
    assert "execute kubectl" not in json.dumps(messages(bundle("prompt-injection")))
    assert (
        redact("Authorization=secretvalue nvapi-abcdefghijklmnopqrstuvwxyz")
        == "[REDACTED] [REDACTED]"
    )


def test_stale_cross_environment_and_revision_evidence_omitted():
    value = fixtures.load("wrong-port")
    value.evidence[0].timestamp = datetime.now(UTC) - timedelta(hours=1)
    value.evidence[1].environment = "preview-43"
    value.evidence[2].revision = "e" * 40
    clean = sanitize(value, settings())
    assert [e.id for e in clean.evidence] == ["log-1"]
    assert len(clean.missing_evidence) == 3


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "invalid_credentials_or_access"),
        (403, "invalid_credentials_or_access"),
        (404, "model_or_request_rejected"),
        (400, "model_or_request_rejected"),
        (302, "redirect_rejected"),
        (418, "provider_rejected"),
    ],
)
def test_permanent_http_errors_never_retry_or_leak_response(status, code):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            status,
            headers={"Location": "https://attacker.invalid"},
            text="PF_SECRET_CANARY_RESPONSE",
        )

    provider = NvidiaProvider(live(), httpx.MockTransport(respond))
    report = asyncio.run(run(bundle(), live(), provider))
    assert report["error"] == code
    assert len(calls) == 1
    assert report["metadata"]["attempts"] == 1
    assert report["diagnosis"] is None
    assert "PF_SECRET_CANARY" not in json.dumps(report)


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transient_retry_budget_and_headers(status):
    calls = []

    def respond(request):
        calls.append(request)
        assert str(request.url) == "https://integrate.api.nvidia.com/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-runtime-credential"
        payload = json.loads(request.content)
        assert "test-runtime-credential" not in json.dumps(payload)
        assert payload["stream"] is False and "tools" not in payload
        return (
            httpx.Response(status, headers={"Retry-After": "0"})
            if len(calls) == 1
            else completion()
        )

    provider = NvidiaProvider(live(), httpx.MockTransport(respond))
    result = asyncio.run(provider.complete(bundle()))
    assert result.attempts == 2
    assert result.usage["total_tokens"] == 150


def test_retry_after_longer_than_budget_stops_without_early_retry():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "300"})

    with pytest.raises(ProviderError, match="rate_limited"):
        asyncio.run(NvidiaProvider(live(), httpx.MockTransport(respond)).complete(bundle()))
    assert len(calls) == 1
    assert retry_delay("Thu, 01 Jan 2099 00:00:00 GMT", 1) > 100


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError])
def test_network_errors_are_bounded(error):
    calls = []

    def respond(request):
        calls.append(request)
        raise error("PF_SECRET_CANARY_NETWORK_ERROR")

    config = live(ai_request_budget_seconds=1)
    with pytest.raises(ProviderError):
        asyncio.run(NvidiaProvider(config, httpx.MockTransport(respond)).complete(bundle()))
    assert len(calls) == 1


def test_total_timeout_includes_slow_response():
    async def slow(request):
        await asyncio.sleep(5)
        return completion()

    with pytest.raises(ProviderError, match="provider_timeout"):
        asyncio.run(
            NvidiaProvider(live(ai_request_budget_seconds=1), httpx.MockTransport(slow)).complete(
                bundle()
            )
        )


@pytest.mark.parametrize(
    "response,code",
    [
        (httpx.Response(200, text="not JSON"), "malformed_provider_response"),
        (httpx.Response(200, json={"choices": []}), "malformed_provider_response"),
        (httpx.Response(200, content=b"x" * 40000), "response_too_large"),
        (
            httpx.Response(
                200,
                json={"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]},
            ),
            "incomplete_or_tool_output",
        ),
    ],
)
def test_provider_envelope_validation(response, code):
    with pytest.raises(ProviderError, match=code):
        asyncio.run(
            NvidiaProvider(live(), httpx.MockTransport(lambda r: response)).complete(bundle())
        )


def test_malformed_diagnosis_is_error_not_abstention():
    config = live()
    report = asyncio.run(
        run(
            bundle(),
            config,
            NvidiaProvider(config, httpx.MockTransport(lambda r: completion("{partial"))),
        )
    )
    assert report["error"] == "invalid_model_output"
    assert report["diagnosis"] is None
    assert report["metadata"]["usage"]["total_tokens"] == 150


@pytest.mark.parametrize(
    "config,code",
    [
        (settings(ai_mode="nvidia"), "live_disabled"),
        (settings(ai_mode="nvidia", ai_live_requests_enabled=True), "missing_key"),
    ],
)
def test_missing_key_and_disabled_mode_make_zero_calls(config, code):
    def forbidden(request):
        raise AssertionError("Must not call NVIDIA")

    with pytest.raises(ProviderError, match=code):
        asyncio.run(NvidiaProvider(config, httpx.MockTransport(forbidden)).complete(bundle()))


def test_http_api_and_input_limits():
    with TestClient(create_app(settings())) as client:
        assert client.get("/health/ready").json()["mode"] == "mock"
        query = {"environment": "preview-42", "source_sha": fixtures.SHA, "fixture": "wrong-port"}
        response = client.post("/diagnoses", json=query)
        assert response.status_code == 200
        assert response.json()["diagnosis"]["status"] == "diagnosed"
        assert (
            client.post("/diagnoses", json={**query, "url": "https://evil.invalid"}).status_code
            == 422
        )
        assert (
            client.post("/diagnoses", json={**query, "environment": "preview-43"}).status_code
            == 409
        )
        assert (
            client.post("/diagnoses", json={**query, "fixture": "../../secrets"}).status_code == 422
        )
        assert client.post("/diagnoses", json={**query, "allow_live": True}).status_code == 409
        assert client.post("/diagnoses", content=b"x" * 5000).status_code == 413
        assert (
            "PF_SECRET_CANARY"
            not in client.post("/diagnoses", json={"bad": "PF_SECRET_CANARY_INPUT"}).text
        )


def test_live_requires_service_opt_in_request_opt_in_and_access_token():
    config = live(ai_access_token=SecretStr("private-local-access"))
    query = {"environment": "preview-42", "source_sha": fixtures.SHA, "fixture": "wrong-port"}
    with TestClient(create_app(config, provider=MockProvider())) as client:
        assert client.post("/diagnoses", json=query).status_code == 403
        assert client.post("/diagnoses", json={**query, "allow_live": True}).status_code == 401
        assert (
            client.post(
                "/diagnoses",
                json={**query, "allow_live": True},
                headers={"Authorization": "Bearer private-local-access"},
            ).status_code
            == 200
        )


def test_concurrency_rejects_instead_of_unbounded_queue():
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()

        class Slow(MockProvider):
            async def complete(self, value):
                entered.set()
                await release.wait()
                return Completion(diagnose(value).model_dump_json())

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(settings(), provider=Slow())),
            base_url="http://test",
        ) as client:
            query = {
                "environment": "preview-42",
                "source_sha": fixtures.SHA,
                "fixture": "wrong-port",
            }
            first = asyncio.create_task(client.post("/diagnoses", json=query))
            await entered.wait()
            assert (await client.post("/diagnoses", json=query)).status_code == 429
            release.set()
            assert (await first).status_code == 200

    asyncio.run(scenario())
