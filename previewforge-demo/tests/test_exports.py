import json
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from botocore.exceptions import EndpointConnectionError
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.aws import Cloud
from app.config import Settings
from app.exports import dispatch, process_message, repair_reports
from app.main import create_app
from app.models import Export


@pytest.fixture
def cloud():
    if os.environ.get("PREVIEWFORGE_EXPORT_TESTS") != "1":
        pytest.skip("Requires the isolated CI Floci service")
    value = Cloud("http://floci:4566", "test")
    value.s3.create_bucket(Bucket=value.bucket)
    value.sqs.create_queue(QueueName=value.queue)
    yield value
    value.sqs.delete_queue(QueueUrl=value.queue_url())
    objects = value.s3.list_objects_v2(Bucket=value.bucket).get("Contents", [])
    for item in objects:
        value.s3.delete_object(Bucket=value.bucket, Key=item["Key"])
    value.s3.delete_bucket(Bucket=value.bucket)
    value.close()


@pytest.fixture
def export_api(db, cloud):
    with TestClient(
        create_app(
            Settings(exports_enabled=True, floci_endpoint=cloud.endpoint, environment_name="test"),
            db,
            cloud=cloud,
        )
    ) as client:
        yield client


def receive(cloud):
    return cloud.sqs.receive_message(
        QueueUrl=cloud.queue_url(), WaitTimeSeconds=1, VisibilityTimeout=30
    )["Messages"][0]


def acknowledge(cloud, message):
    cloud.sqs.delete_message(QueueUrl=cloud.queue_url(), ReceiptHandle=message["ReceiptHandle"])


def test_export_snapshot_download_and_duplicate_delivery(export_api, db, cloud):
    task = export_api.post("/tasks", json={"title": "Synthetic export task"}).json()
    key = str(uuid4())
    first = export_api.post("/exports", headers={"Idempotency-Key": key})
    assert first.status_code == 202
    assert first.json()["id"] == key
    assert export_api.get(f"/exports/{key}/download").status_code == 409
    export_api.patch(f"/tasks/{task['id']}", json={"status": "done"})
    assert export_api.post("/exports", headers={"Idempotency-Key": key}).json()["id"] == key
    message = receive(cloud)
    assert process_message(db, cloud, message)
    assert process_message(db, cloud, message)  # Redelivery cannot create another logical export.
    acknowledge(cloud, message)
    status = export_api.get(f"/exports/{key}").json()
    assert status["status"] == "completed"
    assert status["download_url"] == f"/exports/{key}/download"
    response = export_api.get(status["download_url"])
    assert response.status_code == 200
    assert response.json()["tasks"] == [task]  # Snapshot is stable after task edits.
    assert response.json()["environment"] == "test"
    assert "attachment" in response.headers["content-disposition"]
    with Session(db) as session:
        assert session.scalar(select(func.count()).select_from(Export)) == 1
    assert len(cloud.s3.list_objects_v2(Bucket=cloud.bucket)["Contents"]) == 1


def test_upload_crash_is_safe_to_retry(export_api, db, cloud):
    identifier = export_api.post("/exports").json()["id"]
    message = receive(cloud)

    def crash():
        raise RuntimeError("Synthetic interruption after S3 upload")

    with pytest.raises(RuntimeError, match="Synthetic interruption"):
        process_message(db, cloud, message, after_upload=crash)
    assert export_api.get(f"/exports/{identifier}").json()["status"] == "pending"
    before = cloud.s3.get_object(Bucket=cloud.bucket, Key=f"exports/{identifier}.json")[
        "Body"
    ].read()
    cloud.sqs.change_message_visibility(
        QueueUrl=cloud.queue_url(), ReceiptHandle=message["ReceiptHandle"], VisibilityTimeout=0
    )
    retry = receive(cloud)
    assert retry["MessageId"] == message["MessageId"]
    assert process_message(db, cloud, retry)
    acknowledge(cloud, retry)
    assert export_api.get(f"/exports/{identifier}/download").content == before


def test_pending_outbox_recovers_after_queue_outage(export_api, db, cloud):
    with patch.object(
        cloud.sqs, "send_message", side_effect=EndpointConnectionError(endpoint_url=cloud.endpoint)
    ):
        response = export_api.post("/exports")
    assert response.status_code == 202
    identifier = response.json()["id"]
    assert dispatch(db, cloud) == 1
    message = receive(cloud)
    assert process_message(db, cloud, message)
    acknowledge(cloud, message)
    assert export_api.get(f"/exports/{identifier}").json()["status"] == "completed"


def test_missing_report_rebuilds_from_durable_snapshot(export_api, db, cloud):
    identifier = export_api.post("/exports").json()["id"]
    message = receive(cloud)
    assert process_message(db, cloud, message)
    acknowledge(cloud, message)
    original = export_api.get(f"/exports/{identifier}/download").content
    cloud.s3.delete_object(Bucket=cloud.bucket, Key=f"exports/{identifier}.json")
    with db.begin() as connection:
        connection.execute(
            update(Export)
            .where(Export.id == UUID(identifier))
            .values(checked_at=datetime.now(UTC) - timedelta(minutes=1))
        )
    repair_reports(db, cloud)
    assert export_api.get(f"/exports/{identifier}").json()["status"] == "pending"
    dispatch(db, cloud)
    message = receive(cloud)
    assert process_message(db, cloud, message)
    acknowledge(cloud, message)
    assert export_api.get(f"/exports/{identifier}/download").content == original


def test_export_errors_and_untrusted_message_are_bounded(export_api, db, cloud):
    assert export_api.get(f"/exports/{uuid4()}").status_code == 404
    assert export_api.post("/exports", headers={"Idempotency-Key": "bad"}).status_code == 422
    assert process_message(
        db, cloud, {"Body": json.dumps({"exportId": str(uuid4()), "environment": "staging"})}
    )
    assert process_message(db, cloud, {"Body": "not json"})
    assert process_message(
        db, cloud, {"Body": json.dumps({"exportId": 123, "environment": "test"})}
    )
    assert process_message(db, cloud, {"Body": "[]"})
    with patch.object(
        cloud.s3, "head_bucket", side_effect=EndpointConnectionError(endpoint_url=cloud.endpoint)
    ):
        assert export_api.get("/health/ready").status_code == 503
        assert export_api.get("/health/live").status_code == 200


@pytest.mark.parametrize(
    "endpoint",
    [
        "",
        "https://s3.amazonaws.com",
        "http://floci.evil:4566",
        "http://127.0.0.1:4566/",
        "http://user:pass@floci:4566",
    ],
)
def test_export_settings_refuse_nonlocal_endpoints(endpoint):
    with pytest.raises(ValueError):
        Settings(exports_enabled=True, floci_endpoint=endpoint)
