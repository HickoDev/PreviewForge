import json
import logging
import time
import uuid
from datetime import UTC, datetime

from prometheus_client import CollectorRegistry, Counter, Histogram, Info


class JsonFormatter(logging.Formatter):
    def format(self, record):
        # Never serialize exception details, request bodies, headers or settings.
        return json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": record.levelname,
                "event": record.getMessage(),
                **getattr(record, "safe_fields", {}),
            }
        )


def configure_logging():
    logger = logging.getLogger("previewforge")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger


class TelemetryMiddleware:
    def __init__(self, app, registry: CollectorRegistry):
        self.app = app
        self.logger = configure_logging()
        self.requests = Counter(
            "previewforge_http_requests_total",
            "Completed HTTP requests",
            ["method", "route", "status"],
            registry=registry,
        )
        self.errors = Counter(
            "previewforge_http_errors_total",
            "HTTP errors (4xx and 5xx)",
            ["method", "route", "status"],
            registry=registry,
        )
        self.latency = Histogram(
            "previewforge_http_request_duration_seconds",
            "HTTP request duration",
            ["method", "route"],
            registry=registry,
        )

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = time.perf_counter()
        status = 500
        request_id = uuid.uuid4().hex

        async def capture(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", []).append((b"x-request-id", request_id.encode()))
            await send(message)

        try:
            await self.app(scope, receive, capture)
        finally:
            route = getattr(scope.get("route"), "path", "unmatched")
            method = scope["method"]
            if method not in {"GET", "POST", "PATCH", "PUT", "DELETE", "HEAD", "OPTIONS"}:
                method = "OTHER"
            elapsed = time.perf_counter() - started
            self.requests.labels(method, route, str(status)).inc()
            self.latency.labels(method, route).observe(elapsed)
            if status >= 400:
                self.errors.labels(method, route, str(status)).inc()
            self.logger.info(
                "http_request",
                extra={
                    "safe_fields": {
                        "request_id": request_id,
                        "method": method,
                        "route": route,
                        "status": status,
                        "duration_ms": round(elapsed * 1000, 3),
                    }
                },
            )


def make_registry(settings):
    registry = CollectorRegistry()
    Info("previewforge_build", "Running source and environment", registry=registry).info(
        {
            "source_sha": settings.source_sha,
            "environment": settings.environment_name,
        }
    )
    return registry
