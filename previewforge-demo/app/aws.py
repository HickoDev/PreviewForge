"""Only the explicitly supported local Floci routes, independent of AWS profiles."""

import re
from urllib.parse import urlsplit

from app.floci_smoke import local_clients

ENDPOINTS = {
    "http://127.0.0.1:4566",
    "http://localhost:4566",
    "http://floci:4566",
    "http://floci.previewforge-system.svc.cluster.local:4566",
}


def environment_name(value):
    if not re.fullmatch(r"staging|local|test|preview-[1-9][0-9]{0,8}", value):
        raise ValueError("Invalid export environment")
    return value


def resource_names(environment):
    name = "previewforge-" + environment_name(environment)
    return name + "-reports", name + "-exports"


class Cloud:
    def __init__(self, endpoint, environment):
        if endpoint not in ENDPOINTS:
            raise ValueError("Exports require an explicit approved local Floci endpoint")
        self.endpoint = endpoint
        self.environment = environment_name(environment)
        self.bucket, self.queue = resource_names(environment)
        self.s3, self.sqs = local_clients(endpoint)

    def queue_url(self):
        returned = self.sqs.get_queue_url(QueueName=self.queue)["QueueUrl"]
        parsed = urlsplit(returned)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        path = "/000000000000/" + self.queue
        if origin not in ENDPOINTS or parsed.path != path or parsed.query or parsed.fragment:
            raise ValueError("Floci returned an unexpected queue identity or origin")
        # Host and pod clients have different approved routes to the same queue.
        return self.endpoint + path

    def ready(self):
        self.s3.head_bucket(Bucket=self.bucket)
        self.sqs.get_queue_attributes(QueueUrl=self.queue_url(), AttributeNames=["QueueArn"])

    def close(self):
        self.s3.close()
        self.sqs.close()
