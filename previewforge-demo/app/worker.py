"""Bounded SQS consumer with an outbox and repair of reports lost in an emulator reset."""

import argparse
import json
import os
import signal
import threading
import time
from pathlib import Path

from app.aws import Cloud
from app.config import Settings
from app.database import make_engine
from app.exports import dispatch, process_message, repair_reports

HEARTBEAT = Path("/tmp/previewforge-worker.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=["run", "health"], default="run")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--crash-after-upload",
        action="store_true",
        help="Acceptance exercise only; exit before committing or acknowledging",
    )
    args = parser.parse_args()
    if args.action == "health":
        value = json.loads(HEARTBEAT.read_text())
        raise SystemExit(0 if time.time() - value["loop" if args.live else "healthy"] < 60 else 1)
    settings = Settings()
    if not settings.exports_enabled:
        raise ValueError("Worker requires exports to be enabled explicitly")
    cloud = Cloud(settings.floci_endpoint, settings.environment_name)
    engine = make_engine(settings)
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    healthy = 0
    try:
        while not stop.is_set():
            try:
                cloud.ready()
                repair_reports(engine, cloud)
                dispatch(engine, cloud)
                url = cloud.queue_url()
                messages = cloud.sqs.receive_message(
                    QueueUrl=url, WaitTimeSeconds=2, MaxNumberOfMessages=1, VisibilityTimeout=30
                ).get("Messages", [])
                for message in messages:
                    crash = (lambda: os._exit(73)) if args.crash_after_upload else None
                    if process_message(engine, cloud, message, after_upload=crash):
                        cloud.sqs.delete_message(
                            QueueUrl=url, ReceiptHandle=message["ReceiptHandle"]
                        )
                        print(
                            json.dumps(
                                {
                                    "event": "export_message_handled",
                                    "environment": cloud.environment,
                                }
                            ),
                            flush=True,
                        )
                healthy = time.time()
            except Exception as exc:
                # SDK and database exception text may include request/connection details.
                print(
                    json.dumps({"event": "worker_retry", "error_type": type(exc).__name__}),
                    flush=True,
                )
                if args.once:
                    raise SystemExit(1) from None
            HEARTBEAT.write_text(json.dumps({"loop": time.time(), "healthy": healthy}))
            if args.once:
                break
            stop.wait(1)
    finally:
        cloud.close()
        engine.dispose()


if __name__ == "__main__":
    main()
