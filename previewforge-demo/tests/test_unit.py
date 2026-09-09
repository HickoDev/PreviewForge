import io
import json
import logging
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.floci_smoke import local_clients, local_queue_url, smoke, validate_endpoint
from app.main import create_app
from app.schemas import TaskCreate, TaskUpdate
from app.telemetry import JsonFormatter


@pytest.mark.parametrize("title", ["", "   ", "x" * 201, None, 123])
def test_reject_invalid_titles(title):
    with pytest.raises(ValidationError):
        TaskCreate(title=title)


def test_title_whitespace_and_status_validation():
    assert TaskCreate(title="  synthetic task  ").title == "synthetic task"
    with pytest.raises(ValidationError):
        TaskUpdate(status="surprise")
    with pytest.raises(ValidationError):
        TaskUpdate(status="done", title="cannot rename here")


@pytest.mark.parametrize(
    "endpoint",
    [
        "",
        "https://s3.amazonaws.com",
        "http://floci.evil:4566",
        "http://floci:4566/",
        "http://user:pass@floci:4566",
        "http://10.0.0.1:4566",
    ],
)
def test_reject_nonlocal_or_missing_endpoint(endpoint):
    with pytest.raises(ValueError):
        validate_endpoint(endpoint)


def test_queue_url_is_local_and_preserves_identity():
    path = "/000000000000/pf-smoke-" + "a" * 32
    assert (
        local_queue_url("http://floci:4566" + path, "http://127.0.0.1:4566")
        == "http://127.0.0.1:4566" + path
    )
    for url in [
        "https://sqs.us-east-1.amazonaws.com" + path,
        "http://floci:4566/arbitrary",
        "http://floci:4566" + path + "?x=y",
    ]:
        with pytest.raises(ValueError):
            local_queue_url(url, "http://127.0.0.1:4566")


def test_sdk_ignores_ambient_aws_credentials_and_endpoints(monkeypatch, tmp_path):
    config = tmp_path / "config"
    config.write_text("this is deliberately not valid AWS configuration")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(config))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(config))
    monkeypatch.setenv("AWS_PROFILE", "unrelated-profile")
    monkeypatch.setenv("AWS_DEFAULT_PROFILE", "unrelated-default-profile")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "synthetic-ambient-canary")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "synthetic-ambient-canary")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "synthetic-ambient-canary")
    monkeypatch.setenv("AWS_ENDPOINT_URL", "https://s3.amazonaws.com")
    s3, sqs = local_clients("http://floci:4566")
    for client in (s3, sqs):
        assert client.meta.endpoint_url == "http://floci:4566"
        credentials = client._request_signer._credentials.get_frozen_credentials()
        assert (credentials.access_key, credentials.secret_key, credentials.token) == (
            "test",
            "test",
            "test",
        )
        client.close()


def test_liveness_survives_database_failure_and_errors_are_sanitized():
    engine = Mock()
    engine.connect.side_effect = OperationalError(
        "SELECT", {}, Exception("synthetic-password-canary")
    )
    # Session asks for a connection through this engine.
    with TestClient(create_app(Settings(source_sha="outage-test-sha"), engine)) as client:
        assert client.get("/health/live").json() == {"status": "alive"}
        ready = client.get("/health/ready")
        assert ready.status_code == 503
        assert ready.json() == {"detail": "Database unavailable"}
        assert "synthetic-password-canary" not in ready.text
        assert client.get("/version").json()["source_sha"] == "outage-test-sha"


def test_structured_logs_exclude_exception_contents():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("test-sanitization")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    try:
        raise ValueError("synthetic-secret-canary")
    except ValueError:
        logger.exception("database_error", extra={"safe_fields": {"status": 503}})
    event = json.loads(stream.getvalue())
    assert event["event"] == "database_error"
    assert "synthetic-secret-canary" not in stream.getvalue()


def test_smoke_cleans_owned_bucket_when_upload_fails(monkeypatch):
    from botocore.exceptions import ClientError

    s3, sqs = Mock(), Mock()
    s3.put_object.side_effect = RuntimeError("synthetic upload failure")
    s3.head_bucket.side_effect = ClientError(
        {"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}}, "HeadBucket"
    )
    monkeypatch.setattr("app.floci_smoke.local_clients", lambda endpoint: (s3, sqs))
    with pytest.raises(RuntimeError, match="synthetic upload failure"):
        smoke("http://floci:4566")
    bucket = s3.create_bucket.call_args.kwargs["Bucket"]
    s3.delete_bucket.assert_called_once_with(Bucket=bucket)
    sqs.delete_queue.assert_not_called()


@pytest.mark.parametrize("service", ["s3", "sqs"])
@pytest.mark.parametrize("created_remotely", [True, False])
def test_smoke_cleans_resources_after_ambiguous_create(monkeypatch, service, created_remotely):
    from botocore.exceptions import ClientError, ReadTimeoutError

    s3, sqs = Mock(), Mock()
    timeout = ReadTimeoutError(endpoint_url="http://floci:4566")
    not_found = ClientError(
        {"Error": {"Code": "404"}, "ResponseMetadata": {"HTTPStatusCode": 404}}, "HeadBucket"
    )
    s3.head_bucket.side_effect = not_found
    if service == "s3":
        s3.create_bucket.side_effect = timeout
        if not created_remotely:
            s3.delete_object.side_effect = not_found
            s3.delete_bucket.side_effect = not_found
    else:
        s3.get_object.return_value = {
            "Body": io.BytesIO(b'{"synthetic":true,"tasks":["smoke test"]}')
        }
        s3.list_objects_v2.return_value = {"Contents": [{"Key": "synthetic-report.json"}]}
        sqs.create_queue.side_effect = timeout
        sqs.list_queues.return_value = {}
        if not created_remotely:
            sqs.delete_queue.side_effect = ClientError(
                {
                    "Error": {"Code": "AWS.SimpleQueueService.NonExistentQueue"},
                    "ResponseMetadata": {"HTTPStatusCode": 400},
                },
                "DeleteQueue",
            )
    monkeypatch.setattr("app.floci_smoke.local_clients", lambda endpoint: (s3, sqs))
    with pytest.raises(ReadTimeoutError):
        smoke("http://floci:4566")
    bucket = s3.create_bucket.call_args.kwargs["Bucket"]
    s3.delete_bucket.assert_called_once_with(Bucket=bucket)
    s3.head_bucket.assert_called_once_with(Bucket=bucket)
    if service == "sqs":
        sqs.delete_queue.assert_called_once_with(
            QueueUrl="http://floci:4566/000000000000/" + bucket
        )
        sqs.list_queues.assert_called_once_with(QueueNamePrefix=bucket)
    else:
        sqs.delete_queue.assert_not_called()
