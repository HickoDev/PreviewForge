"""Isolated S3/SQS acceptance check. Only explicit local endpoints are allowed."""

import argparse
import json
import os
import re
import uuid
from urllib.parse import urlsplit, urlunsplit

import boto3
import botocore.session
from botocore.config import Config
from botocore.exceptions import ClientError

ALLOWED_ENDPOINTS = {"http://127.0.0.1:4566", "http://localhost:4566", "http://floci:4566"}


def validate_endpoint(endpoint: str) -> str:
    if endpoint not in ALLOWED_ENDPOINTS:
        raise ValueError("An explicit approved local Floci endpoint is required")
    return endpoint


def local_queue_url(queue_url: str, endpoint: str) -> str:
    """Floci advertises its Compose hostname; host clients retain the queue path."""
    validate_endpoint(endpoint)
    parsed = urlsplit(queue_url)
    validate_endpoint(urlunsplit((parsed.scheme, parsed.netloc, "", "", "")))
    if (
        parsed.query
        or parsed.fragment
        or not re.fullmatch(r"/000000000000/pf-smoke-[a-f0-9]{32}", parsed.path)
    ):
        raise ValueError("Unexpected smoke-test queue URL")
    return endpoint + parsed.path


def local_clients(endpoint: str):
    validate_endpoint(endpoint)
    # Disable the profile lookup chain itself, including AWS_PROFILE/AWS_DEFAULT_PROFILE.
    core = botocore.session.Session(session_vars={"profile": (None, None, None, None)})
    core.set_config_variable("config_file", os.devnull)
    core.set_config_variable("credentials_file", os.devnull)
    core.set_credentials("test", "test", "test")
    session = boto3.Session(botocore_session=core, region_name="us-east-1")
    config = Config(
        region_name="us-east-1",
        connect_timeout=3,
        read_timeout=5,
        retries={"mode": "standard", "total_max_attempts": 2},
        s3={"addressing_style": "path"},
        proxies={},
        ignore_configured_endpoint_urls=True,
    )
    return tuple(
        session.client(service, endpoint_url=endpoint, config=config) for service in ("s3", "sqs")
    )


def delete_if_present(operation, **kwargs):
    """A lost create response may mean the uniquely named resource never existed."""
    try:
        operation(**kwargs)
    except ClientError as exc:
        if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
            return
        if exc.response.get("Error", {}).get("Code") in {
            "NoSuchBucket",
            "NoSuchKey",
            "QueueDoesNotExist",
            "AWS.SimpleQueueService.NonExistentQueue",
        }:
            return
        raise


def smoke(endpoint: str):
    if not __debug__:
        raise RuntimeError(
            "Smoke verification requires Python assertions; remove -O/PYTHONOPTIMIZE"
        )
    s3, sqs = local_clients(endpoint)
    name = "pf-smoke-" + uuid.uuid4().hex
    key = "synthetic-report.json"
    body = b'{"synthetic":true,"tasks":["smoke test"]}'
    bucket_attempted = False
    queue_url = None
    cleanup_errors = []
    try:
        # Remember ownership intent before the call: the server may create the
        # resource even when the SDK never receives the response.
        bucket_attempted = True
        s3.create_bucket(Bucket=name)
        s3.put_bucket_tagging(
            Bucket=name,
            Tagging={
                "TagSet": [
                    {"Key": "project", "Value": "previewforge"},
                    {"Key": "purpose", "Value": "smoke"},
                ]
            },
        )
        s3.put_object(Bucket=name, Key=key, Body=body, ContentType="application/json")
        response = s3.get_object(Bucket=name, Key=key)
        with response["Body"] as stream:
            assert stream.read() == body, "S3 content mismatch"
        assert key in [item["Key"] for item in s3.list_objects_v2(Bucket=name).get("Contents", [])]
        queue_url = endpoint + "/000000000000/" + name
        result = sqs.create_queue(
            QueueName=name, tags={"project": "previewforge", "purpose": "smoke"}
        )
        assert local_queue_url(result["QueueUrl"], endpoint) == queue_url
        assert local_queue_url(sqs.get_queue_url(QueueName=name)["QueueUrl"], endpoint) == queue_url
        sqs.send_message(QueueUrl=queue_url, MessageBody=body.decode())
        first = sqs.receive_message(QueueUrl=queue_url, WaitTimeSeconds=1, VisibilityTimeout=30)[
            "Messages"
        ][0]
        assert first["Body"] == body.decode()
        assert not sqs.receive_message(QueueUrl=queue_url, WaitTimeSeconds=0).get("Messages")
        sqs.change_message_visibility(
            QueueUrl=queue_url, ReceiptHandle=first["ReceiptHandle"], VisibilityTimeout=0
        )
        second = sqs.receive_message(QueueUrl=queue_url, WaitTimeSeconds=1)["Messages"][0]
        assert second["MessageId"] == first["MessageId"], "Expected redelivery"
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=second["ReceiptHandle"])
        assert not sqs.receive_message(QueueUrl=queue_url, WaitTimeSeconds=0).get("Messages")
    finally:
        # Only delete the exact resources created by this invocation, even after failure.
        if queue_url:
            try:
                delete_if_present(sqs.delete_queue, QueueUrl=queue_url)
                assert not sqs.list_queues(QueueNamePrefix=name).get("QueueUrls"), "Queue remains"
            except Exception as exc:
                cleanup_errors.append(f"queue {name}: {type(exc).__name__}")
        if bucket_attempted:
            try:
                delete_if_present(s3.delete_object, Bucket=name, Key=key)
                delete_if_present(s3.delete_bucket, Bucket=name)
                try:
                    s3.head_bucket(Bucket=name)
                except ClientError as exc:
                    assert exc.response["ResponseMetadata"]["HTTPStatusCode"] == 404
                else:
                    raise AssertionError("Bucket remains")
            except Exception as exc:
                cleanup_errors.append(f"bucket {name}: {type(exc).__name__}")
        s3.close()
        sqs.close()
        if cleanup_errors:
            raise RuntimeError("Smoke cleanup incomplete: " + "; ".join(cleanup_errors))
    return {"status": "passed", "endpoint": endpoint, "resource": name, "cleanup": "verified"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    args = parser.parse_args()
    print(json.dumps(smoke(args.endpoint)))
