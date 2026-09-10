"""Per-environment Terraform state with SDK ownership checks before every mutation."""

import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime

from reconciler import runtime as r

ADDRESSES = {"module.environment.aws_s3_bucket.reports", "module.environment.aws_sqs_queue.exports"}


def directory(environment):
    r.environment_name(environment)
    path = r.RUNTIME / "environments" / environment
    r.require(path.resolve().is_relative_to(r.validate_runtime()), "Terraform path escaped runtime")
    return path


def expected_tags(environment):
    return {
        "project": "previewforge",
        "environment": environment,
        "managed_by": r.OWNER,
        "installation": r.settings()["installation"],
    }


def absent(exc):
    return exc.response.get("ResponseMetadata", {}).get(
        "HTTPStatusCode"
    ) == 404 or exc.response.get("Error", {}).get("Code") in {
        "NoSuchBucket",
        "QueueDoesNotExist",
        "AWS.SimpleQueueService.NonExistentQueue",
    }


def actual(environment):
    from botocore.exceptions import ClientError

    from app.aws import Cloud

    cloud = Cloud(r.ENDPOINT, environment)
    result = {}
    try:
        try:
            cloud.s3.head_bucket(Bucket=cloud.bucket)
            tags = {
                x["Key"]: x["Value"]
                for x in cloud.s3.get_bucket_tagging(Bucket=cloud.bucket)["TagSet"]
            }
            result["bucket"] = {"id": cloud.bucket, "tags": tags}
        except ClientError as exc:
            r.require(
                exc.response.get("Error", {}).get("Code") != "NoSuchTagSet",
                "Refusing an untagged existing report bucket",
            )
            if not absent(exc):
                raise
        try:
            url = cloud.queue_url()
            tags = cloud.sqs.list_queue_tags(QueueUrl=url).get("Tags", {})
            result["queue"] = {"id": url, "tags": tags}
        except ClientError as exc:
            if not absent(exc):
                raise
        for value in result.values():
            r.require(
                all(value["tags"].get(k) == v for k, v in expected_tags(environment).items()),
                f"Refusing resource with unverified ownership in {environment}",
            )
        return result
    finally:
        cloud.close()


def validate_state(environment):
    path = directory(environment) / "terraform.tfstate"
    if not path.exists():
        return set()
    state = json.loads(path.read_text())
    cloud_names = (
        "previewforge-" + environment + "-reports",
        r.ENDPOINT + "/000000000000/previewforge-" + environment + "-exports",
    )
    addresses = set()
    for item in state.get("resources", []):
        address = item.get("module", "") + "." + item["type"] + "." + item["name"]
        r.require(
            item["mode"] == "managed" and address in ADDRESSES,
            "Unexpected Terraform state resource",
        )
        for instance in item.get("instances", []):
            attributes = instance["attributes"]
            # Floci can advertise its Compose origin; only the approved queue path is portable.
            identifier = attributes["id"]
            for origin in (
                "http://floci:4566/",
                "http://localhost:4566/",
                "http://127.0.0.1:4566/",
            ):
                if identifier.startswith(origin):
                    identifier = r.ENDPOINT + "/" + identifier[len(origin) :]
                    break
            expected = cloud_names[0] if item["type"] == "aws_s3_bucket" else cloud_names[1]
            r.require(identifier == expected, "Terraform state refers to another environment")
        addresses.add(address)
    return addresses


def environment_vars():
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AWS_", "TF_"))}
    cache = r.RUNTIME / "provider-cache"
    cache.mkdir(parents=True, exist_ok=True)
    config = r.RUNTIME / "terraform.rc"
    config.write_text('disable_checkpoint = true\nplugin_cache_dir = "' + cache.as_posix() + '"\n')
    env.update(
        {
            "AWS_ACCESS_KEY_ID": "test",
            "AWS_SECRET_ACCESS_KEY": "test",
            "AWS_SESSION_TOKEN": "test",
            "AWS_REGION": "us-east-1",
            "AWS_DEFAULT_REGION": "us-east-1",
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_CONFIG_FILE": os.devnull,
            "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
            "TF_CLI_CONFIG_FILE": str(config),
            "TF_IN_AUTOMATION": "1",
            "CHECKPOINT_DISABLE": "1",
            "NO_PROXY": "127.0.0.1,localhost,floci",
            "no_proxy": "127.0.0.1,localhost,floci",
        }
    )
    return env


def command(environment, *args, codes=(0,), timeout=300):
    result = subprocess.run(
        [str(r.TF), "-chdir=" + str(directory(environment)), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment_vars(),
        timeout=timeout,
    )
    log = directory(environment) / "last-terraform.log"
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode not in codes:
        raise RuntimeError(
            f"Terraform {args[0]} failed for {environment}; see {log}: "
            + (result.stdout + result.stderr)[-1800:]
        )
    return result.returncode, result.stdout


def prepare(environment):
    path = directory(environment)
    path.mkdir(parents=True, exist_ok=True)
    ownership = path / "owner.json"
    identity = {"environment": environment, **r.settings()}
    if ownership.exists():
        r.require(
            json.loads(ownership.read_text()) == identity, "Terraform directory has another owner"
        )
    else:
        r.require(
            not (path / "terraform.tfstate").exists(),
            "State without an ownership record requires review",
        )
        r.save(ownership, identity)
    validate_state(environment)
    sources = r.p.ROOT / "terraform"
    module = r.RUNTIME / "environments/modules/environment-resources"
    module.mkdir(parents=True, exist_ok=True)
    for target, source_dir in [
        (module, sources / "modules/environment-resources"),
        (path, sources / "environments"),
    ]:
        approved = {x.name for x in source_dir.glob("*.tf")}
        r.require(
            all(x.name in approved for x in target.glob("*.tf"))
            and not list(target.glob("*.tf.json")),
            "Unexpected Terraform configuration in private runtime",
        )
    for source in (sources / "modules/environment-resources").glob("*.tf"):
        shutil.copyfile(source, module / source.name)
    for source in (sources / "environments").glob("*.tf"):
        shutil.copyfile(source, path / source.name)
    provider_lock = sources / "environments/.terraform.lock.hcl"
    if provider_lock.exists():
        shutil.copyfile(provider_lock, path / provider_lock.name)
    r.save(
        path / "local.auto.tfvars.json",
        {
            "endpoint": r.ENDPOINT,
            "environment": environment,
            "installation": r.settings()["installation"],
        },
    )
    fingerprint = hashlib.sha256(
        b"".join(x.read_bytes() for x in sorted(sources.rglob("*.tf")))
        + (provider_lock.read_bytes() if provider_lock.exists() else b"")
    ).hexdigest()
    initialized = path / "initialized.sha256"
    if not initialized.exists() or initialized.read_text() != fingerprint:
        args = ["init", "-input=false", "-no-color"]
        if provider_lock.exists():
            args.append("-lockfile=readonly")
        command(environment, *args, timeout=600)
        command(environment, "validate", "-no-color")
        initialized.write_text(fingerprint)


def validate_plan(plan, destroy=False):
    for item in plan.get("resource_changes", []):
        r.require(item["address"] in ADDRESSES, "Plan contains an unexpected resource")
        actions = item["change"]["actions"]
        r.require(
            actions in (["no-op"], ["delete"])
            if destroy
            else actions in (["no-op"], ["create"], ["update"]),
            "Plan would replace/delete resources outside an explicit cleanup",
        )


def record(environment, phase, **details):
    r.save(
        directory(environment) / "status.json",
        {
            "environment": environment,
            "phase": phase,
            "at": datetime.now(UTC).isoformat(),
            **details,
        },
    )


def recover_state(environment):
    present = actual(environment)
    tracked = validate_state(environment)
    for kind, address in [
        ("bucket", "module.environment.aws_s3_bucket.reports"),
        ("queue", "module.environment.aws_sqs_queue.exports"),
    ]:
        if kind in present and address not in tracked:
            command(
                environment, "import", "-input=false", "-no-color", address, present[kind]["id"]
            )
    return present


def ensure(environment, still_desired=lambda _: True, after_apply=None):
    with r.lock(directory(environment) / "operation.lock"):
        r.require(still_desired(environment), "Environment closed before provisioning")
        prepare(environment)
        record(environment, "provisioning")
        present = recover_state(environment)
        code, _ = command(
            environment,
            "plan",
            "-input=false",
            "-no-color",
            "-detailed-exitcode",
            "-out=change.tfplan",
            codes=(0, 2),
        )
        plan = json.loads(command(environment, "show", "-json", "change.tfplan")[1])
        validate_plan(plan)
        r.require(still_desired(environment), "Environment closed during plan; apply stopped")
        if code == 2:
            command(environment, "apply", "-input=false", "-no-color", "change.tfplan")
        if after_apply:
            after_apply()
        observed = actual(environment)
        r.require(set(observed) == {"bucket", "queue"}, "SDK did not confirm both resources")
        outputs = json.loads(command(environment, "output", "-json")[1])["resources"]["value"]
        record(
            environment,
            "ready",
            changed=code == 2,
            resources=outputs,
            repairedMissingResources=sorted({"bucket", "queue"} - present.keys()),
        )
        return outputs


def destroy(environment, may_delete):
    r.require(
        environment not in {"staging", "local", "test"},
        "Automatic cleanup is restricted to preview environments",
    )
    with r.lock(directory(environment) / "operation.lock"):
        r.require(may_delete(environment), "Environment still desired or workers still exist")
        prepare(environment)
        recover_state(environment)
        validate_state(environment)
        record(environment, "deleting")
        command(environment, "plan", "-destroy", "-input=false", "-no-color", "-out=delete.tfplan")
        validate_plan(
            json.loads(command(environment, "show", "-json", "delete.tfplan")[1]), destroy=True
        )
        r.require(may_delete(environment), "Environment became desired before cleanup")
        command(environment, "apply", "-input=false", "-no-color", "delete.tfplan")
        r.require(not actual(environment), "SDK still sees resources after Terraform cleanup")
        record(
            environment, "deleted"
        )  # Keep state and ownership evidence, including partial failures.


def owned_environments():
    parent = r.RUNTIME / "environments"
    if not parent.exists():
        return []
    result = []
    for path in parent.iterdir():
        if path.is_dir() and (path / "owner.json").exists():
            r.environment_name(path.name)
            r.require(
                json.loads((path / "owner.json").read_text())
                == {"environment": path.name, **r.settings()},
                "Unknown Terraform state owner",
            )
            result.append(path.name)
    return sorted(result)
