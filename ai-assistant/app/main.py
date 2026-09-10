import asyncio
import hmac

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app import fixtures
from app.collectors import CollectionError, KubernetesCollector, policy
from app.config import Settings
from app.pipeline import run
from app.providers import MockProvider, NvidiaProvider
from app.schemas import DiagnosisRequest


def create_app(settings=None, provider=None, collector=None):
    settings = settings or Settings()
    app = FastAPI(title="PreviewForge diagnostic assistant", version="0.1.0")
    active = 0

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        # Pydantic's default HTTP errors may echo user-supplied secrets.
        return JSONResponse({"detail": "Invalid request fields"}, status_code=422)

    @app.get("/health/live")
    @app.get("/health/ready")
    async def health():
        return {
            "status": "ready",
            "mode": settings.ai_mode,
            "live_enabled": settings.ai_live_requests_enabled,
            "collector": settings.ai_collector,
        }

    @app.get("/fixtures")
    async def fixture_list():
        return {
            "environment": "preview-42",
            "source_sha": fixtures.SHA,
            "cases": [{"id": c["id"], "split": c["split"]} for c in fixtures.cases()],
        }

    @app.get("/environments")
    async def environments():
        return (
            {
                name: {"source_sha": value["source_sha"], "image": value["image"]}
                for name, value in policy(settings).get("environments", {}).items()
            }
            if settings.ai_collector == "kubernetes"
            else {}
        )

    @app.post(
        "/diagnoses",
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": DiagnosisRequest.model_json_schema(),
                        "example": {
                            "environment": "preview-42",
                            "source_sha": fixtures.SHA,
                            "fixture": "wrong-port",
                            "allow_live": False,
                        },
                    }
                },
            }
        },
    )
    async def diagnose(request: Request):
        nonlocal active
        if active >= settings.ai_max_concurrent_requests:
            raise HTTPException(429, "Diagnostic concurrency limit reached")
        active += 1
        try:
            raw = bytearray()
            try:
                async with asyncio.timeout(5):
                    async for chunk in request.stream():
                        raw.extend(chunk)
                        if len(raw) > 4096:
                            raise HTTPException(413, "Request exceeds 4096 bytes")
                query = DiagnosisRequest.model_validate_json(raw)
            except (ValidationError, ValueError):
                raise HTTPException(422, "Invalid request fields") from None
            if settings.ai_mode == "nvidia":
                expected = settings.ai_access_token.get_secret_value()
                supplied = request.headers.get("Authorization", "")
                if not query.allow_live or not settings.ai_live_requests_enabled:
                    raise HTTPException(
                        403, "Live inference requires explicit service and request opt-in"
                    )
                if not expected or not hmac.compare_digest(supplied, "Bearer " + expected):
                    raise HTTPException(401, "Local diagnostic access token required")
            elif query.allow_live:
                raise HTTPException(409, "Service is in mock mode")
            if query.fixture:
                try:
                    bundle = fixtures.load(query.fixture)
                except ValueError:
                    raise HTTPException(404, "Unknown synthetic fixture") from None
                if (query.environment, query.source_sha) != (bundle.environment, bundle.source_sha):
                    raise HTTPException(409, "Fixture identity mismatch")
            elif settings.ai_collector != "kubernetes":
                raise HTTPException(
                    409, "Select a synthetic fixture or configure the Kubernetes collector"
                )
            else:
                try:
                    async with asyncio.timeout(30):
                        bundle = await (collector or KubernetesCollector(settings)).collect(query)
                except (
                    CollectionError,
                    httpx.HTTPError,
                    ValueError,
                    KeyError,
                    StopIteration,
                    OSError,
                ):
                    raise HTTPException(
                        409,
                        "Evidence unavailable or deployment identity changed; refresh authorization and retry",
                    ) from None
            selected = provider or (
                MockProvider() if settings.ai_mode == "mock" else NvidiaProvider(settings)
            )
            return await run(bundle, settings, selected)
        except TimeoutError:
            raise HTTPException(504, "Diagnostic collection/request budget exceeded") from None
        finally:
            active -= 1

    return app
