"""CI: real Terraform/Floci lifecycle in a disposable runtime and emulator."""

import argparse
import hashlib
import json
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import resources  # noqa: F401 -- establishes the local repository import paths
from reconciler import runtime as r
from reconciler import terraform as tf

from app.aws import Cloud


def check():
    r.require(sys.platform == "linux", "This check runs in the isolated Linux CI container")
    with tempfile.TemporaryDirectory(prefix="previewforge-terraform-ci-") as folder:
        root = Path(folder)
        r.RUNTIME = root / r.OWNER
        r.TF = root / "terraform"
        version = r.LOCK["terraform"]["version"]
        filename = f"terraform_{version}_linux_amd64.zip"
        archive = root / filename
        urllib.request.urlretrieve(
            f"https://releases.hashicorp.com/terraform/{version}/{filename}", archive
        )
        r.require(
            hashlib.sha256(archive.read_bytes()).hexdigest()
            == r.LOCK["terraform"]["archives"][filename],
            "Terraform checksum mismatch",
        )
        with zipfile.ZipFile(archive) as source:
            r.TF.write_bytes(source.read("terraform"))
        r.TF.chmod(0o700)
        r.p.run(r.TF, "fmt", "-check", "-recursive", r.p.ROOT / "terraform", quiet=True)
        r.settings(create=True)
        name = "preview-999999991"
        tf.ensure(name)
        r.require(
            tf.command(name, "plan", "-input=false", "-detailed-exitcode", codes=(0, 2))[0] == 0,
            "Second plan was not empty",
        )
        cloud = Cloud(r.ENDPOINT, name)
        try:
            cloud.s3.put_object(Bucket=cloud.bucket, Key="acceptance.json", Body=b'{"test":true}')
            cloud.sqs.delete_queue(QueueUrl=cloud.queue_url())
            tf.ensure(name)
            r.require(
                set(tf.actual(name)) == {"bucket", "queue"}, "Missing queue was not recreated"
            )
            # Lose the local state file while preserving its ownership record.
            path = tf.directory(name)
            (path / "terraform.tfstate").rename(path / "saved-state.json")
            tf.ensure(name)
            r.require(
                tf.command(name, "plan", "-input=false", "-detailed-exitcode", codes=(0, 2))[0]
                == 0,
                "Imported resources drifted",
            )
            tf.destroy(name, lambda _: True)
            r.require(not tf.actual(name), "SDK saw resources after destroy")
            print(
                json.dumps(
                    {
                        "terraform": version,
                        "checks": [
                            "fmt",
                            "validate",
                            "apply",
                            "second-plan-empty",
                            "missing-queue-repair",
                            "state-import-recovery",
                            "destroy-nonempty-bucket",
                            "SDK-confirmed-absence",
                        ],
                    }
                )
            )
        finally:
            cloud.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--endpoint",
        choices=["http://127.0.0.1:4566", "http://floci:4566"],
        default="http://127.0.0.1:4566",
    )
    r.ENDPOINT = parser.parse_args().endpoint
    check()
