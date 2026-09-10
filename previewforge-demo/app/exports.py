"""A database outbox closes the gap between accepting a job and sending SQS."""

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Export, Task
from app.schemas import TaskRead

MAX_REPORT_BYTES = 4 * 1024 * 1024


def request_export(engine, cloud, identifier=None):
    identifier = identifier or uuid4()
    with Session(engine) as session:
        job = session.get(Export, identifier)
        if job is None:
            tasks = session.scalars(
                select(Task).order_by(Task.created_at, Task.id).limit(10001)
            ).all()
            if len(tasks) > 10000:
                raise HTTPException(413, "This demo supports at most 10000 tasks per export")
            snapshot = {
                "export_id": str(identifier),
                "environment": cloud.environment,
                "created_at": datetime.now(UTC).isoformat(),
                "tasks": [TaskRead.model_validate(task).model_dump(mode="json") for task in tasks],
            }
            if len(json.dumps(snapshot).encode()) > MAX_REPORT_BYTES:
                raise HTTPException(413, "Report exceeds the 4 MiB demo limit")
            session.execute(
                insert(Export)
                .values(
                    id=identifier,
                    snapshot=snapshot,
                    object_key=f"exports/{identifier}.json",
                )
                .on_conflict_do_nothing(index_elements=[Export.id])
            )
            session.commit()
    # The committed pending row survives lost SQS/HTTP responses; dispatch retries it.
    try:
        dispatch(engine, cloud, identifier)
    except (BotoCoreError, ClientError):
        pass
    with Session(engine) as session:
        return export_status(session.get(Export, identifier))


def export_status(job):
    return {
        "id": str(job.id),
        "status": job.status,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
        "download_url": f"/exports/{job.id}/download" if job.status == "completed" else None,
    }


def dispatch(engine, cloud, identifier=None):
    cutoff = datetime.now(UTC) - timedelta(seconds=30)
    with Session(engine) as session, session.begin():
        query = select(Export).where(Export.status == "pending")
        if identifier is not None:
            query = query.where(Export.id == identifier)
        else:
            query = query.where(or_(Export.enqueued_at.is_(None), Export.enqueued_at < cutoff))
        jobs = session.scalars(
            query.order_by(Export.created_at).limit(10).with_for_update(skip_locked=True)
        ).all()
        if not jobs:
            return 0
        url = cloud.queue_url()
        for job in jobs:
            cloud.sqs.send_message(
                QueueUrl=url,
                MessageBody=json.dumps(
                    {
                        "exportId": str(job.id),
                        "environment": cloud.environment,
                    }
                ),
            )
            job.enqueued_at = datetime.now(UTC)
        return len(jobs)


def missing_object(cloud, key):
    try:
        cloud.s3.head_object(Bucket=cloud.bucket, Key=key)
        return False
    except ClientError as exc:
        if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
            return True
        raise


def repair_reports(engine, cloud):
    """An emulator reset loses objects; durable snapshots allow bounded reconstruction."""
    cutoff = datetime.now(UTC) - timedelta(seconds=30)
    with Session(engine) as session, session.begin():
        jobs = session.scalars(
            select(Export)
            .where(
                Export.status == "completed",
                or_(Export.checked_at.is_(None), Export.checked_at < cutoff),
            )
            .order_by(Export.checked_at.asc().nullsfirst(), Export.id)
            .limit(10)
            .with_for_update(skip_locked=True)
        ).all()
        for job in jobs:
            if missing_object(cloud, job.object_key):
                job.status = "pending"
                job.completed_at = None
                job.enqueued_at = None
            job.checked_at = datetime.now(UTC)


def process_message(engine, cloud, message, after_upload=None):
    try:
        body = json.loads(message["Body"])
        if (
            not isinstance(body, dict)
            or set(body) != {"exportId", "environment"}
            or body["environment"] != cloud.environment
            or not isinstance(body["exportId"], str)
        ):
            raise ValueError("Wrong environment/message fields")
        identifier = UUID(body["exportId"])
    except (ValueError, TypeError, KeyError):
        return True  # Invalid messages cannot choose object keys, endpoints or other databases.
    with Session(engine) as session, session.begin():
        job = session.scalar(
            select(Export).where(Export.id == identifier).with_for_update(skip_locked=True)
        )
        if job is None:
            # A locked job may be in flight in another worker. Do not acknowledge it.
            return session.get(Export, identifier) is None
        if job.status == "completed" and not missing_object(cloud, job.object_key):
            return True
        report = json.dumps(job.snapshot, sort_keys=True, separators=(",", ":")).encode()
        cloud.s3.put_object(
            Bucket=cloud.bucket, Key=job.object_key, Body=report, ContentType="application/json"
        )
        if after_upload:
            after_upload()
        job.status = "completed"
        job.completed_at = datetime.now(UTC)
        job.checked_at = job.completed_at
    return True
