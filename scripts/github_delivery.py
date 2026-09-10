"""Trusted default-branch delivery code. Remote writes require the disabled-by-default workflow."""

import argparse
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import preview_state as state

CI_PATH = ".github/workflows/demo-ci.yml"


class PackagePending(ValueError):
    """Package association is unavailable and its ID has not been approved."""


class GitHub:
    def __init__(self):
        # Local development uses gh as HickoDev. This adapter is ONLY for the
        # repository-scoped Actions token in the reviewed, explicitly enabled workflow.
        state.require(
            os.environ.get("GITHUB_ACTIONS") == "true",
            "Remote delivery runs only in GitHub Actions",
        )
        state.require(
            os.environ.get("GITHUB_REPOSITORY") == state.REPOSITORY, "Wrong Actions repository"
        )
        self.token = os.environ["GH_TOKEN"]

    def api(self, path, method="GET", body=None, global_path=False):
        request = urllib.request.Request(
            "https://api.github.com/"
            + ("" if global_path else "repos/" + state.REPOSITORY + ("/" if path else ""))
            + path,
            data=None if body is None else json.dumps(body).encode(),
            method=method,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)

    def pr(self, number):
        state.preview_name(number)
        pr = self.api(f"pulls/{number}")
        return {
            "number": pr["number"],
            "state": pr["state"],
            "headSha": pr["head"]["sha"],
            "repository": pr["base"]["repo"]["full_name"],
            "headRepository": (pr["head"].get("repo") or {}).get("full_name"),
            "author": pr["user"]["login"],
        }

    def current(self, build):
        if build["event"] == "pull_request":
            return self.pr(build["pr"])
        head = self.api("git/ref/heads/main")["object"]["sha"]
        if head != build["sourceSha"]:
            # Configuration commits must neither rebuild the app nor invalidate an
            # in-flight main build. Reject a newer APP change or diverged history.
            comparison = self.api(f"compare/{build['sourceSha']}...{head}")
            if comparison["status"] != "ahead" or comparison["total_commits"] > 100:
                return {"headSha": head}
            for commit in comparison["commits"]:
                files = self.api("commits/" + commit["sha"])["files"]
                if len(files) >= 300 or any(
                    build_input(f["filename"]) or build_input(f.get("previous_filename", ""))
                    for f in files
                ):
                    return {"headSha": head}
        return {"branch": "main", "repository": state.REPOSITORY, "headSha": build["sourceSha"]}


def build_input(path):
    return path.startswith("previewforge-demo/") or path in {
        "compose.yaml",
        "scripts/ci.py",
        CI_PATH,
    }


class GitHubStore:
    def __init__(self, github):
        self.github = github

    def head(self):
        return self.github.api("git/ref/heads/main")["object"]["sha"]

    def snapshot(self):
        head = self.head()
        tree = self.github.api(f"git/trees/{head}?recursive=1")
        state.require(
            not tree.get("truncated"), "Truncated Git tree; refuse partial reconciliation"
        )
        records = {}
        for item in tree["tree"]:
            path = item["path"]
            if item["type"] == "blob" and (path == state.STAGING or path.startswith(state.PREFIX)):
                state.require(
                    path == state.STAGING
                    or re.fullmatch(r"gitops/previews/preview-[1-9][0-9]{0,8}\.json", path),
                    "Unexpected preview path",
                )
                blob = self.github.api("git/blobs/" + item["sha"])
                state.require(blob["size"] < 16384, "Oversized record")
                records[path] = json.loads(base64.b64decode(blob["content"]))
        return head, records

    def compare_swap(self, revision, before, after):
        entries = []
        for path in sorted(before.keys() | after.keys()):
            if before.get(path) == after.get(path):
                continue
            item = {"path": path, "mode": "100644", "type": "blob"}
            if path in after:
                item["content"] = json.dumps(after[path], indent=2) + "\n"
            else:
                item["sha"] = None
            entries.append(item)
        commit = self.github.api("git/commits/" + revision)
        tree = self.github.api(
            "git/trees", "POST", {"base_tree": commit["tree"]["sha"], "tree": entries}
        )
        updated = self.github.api(
            "git/commits",
            "POST",
            {
                "message": "Reconcile PreviewForge desired environments",
                "tree": tree["sha"],
                "parents": [revision],
            },
        )
        try:
            self.github.api("git/refs/heads/main", "PATCH", {"sha": updated["sha"], "force": False})
            return True
        except urllib.error.HTTPError as exc:
            if exc.code in {409, 422} and self.head() != revision:
                return False
            raise


def validate_run(github, run_id):
    state.require(re.fullmatch(r"[1-9][0-9]*", str(run_id)), "Invalid workflow run ID")
    run = github.api(f"actions/runs/{run_id}")
    state.require(run["path"] == CI_PATH and run["name"] == "Demo CI", "Wrong CI workflow")
    state.require(run["repository"]["full_name"] == state.REPOSITORY, "Wrong workflow repository")
    state.require(
        run["head_repository"]["full_name"] == state.REPOSITORY, "Fork builds cannot deploy"
    )
    state.require(
        run["status"] == "completed" and run["conclusion"] == "success", "Build did not succeed"
    )
    state.require(run["event"] in {"pull_request", "push"}, "Unsupported build event")
    build = {
        "repository": state.REPOSITORY,
        "event": run["event"],
        "conclusion": "success",
        "sourceSha": run["head_sha"],
        "runId": run["id"],
        "attempt": run["run_attempt"],
        "published": True,  # eligibility probe; no record is written until push succeeds
    }
    if run["event"] == "pull_request":
        prs = run.get("pull_requests", [])
        state.require(len(prs) == 1, "CI run must identify exactly one PR")
        build["pr"] = prs[0]["number"]
    else:
        state.require(run["head_branch"] == "main", "Only main builds update staging")
    state.require(
        state.eligible(build, github.current(build)), "Build is stale, closed or untrusted"
    )
    return build


def unpack_artifact(archive, destination, source_sha):
    with zipfile.ZipFile(archive) as bundle:
        entries = {item.filename: item for item in bundle.infolist()}
        state.require(
            set(entries) == {"image.tar", "receipt.json"} and len(bundle.infolist()) == 2,
            "Unexpected artifact files",
        )
        state.require(
            entries["receipt.json"].file_size < 4096
            and entries["image.tar"].file_size < 1_000_000_000,
            "Artifact too large",
        )
        receipt = json.loads(bundle.read("receipt.json"))
        tag = "previewforge-demo:" + source_sha
        state.require(
            receipt == {"sourceSha": source_sha, "tag": tag}, "Artifact source identity mismatch"
        )
        # Copy exact names, never extract arbitrary paths or execute artifact scripts.
        path = destination / "image.tar"
        with bundle.open("image.tar") as src, path.open("wb") as dst:
            while chunk := src.read(1024 * 1024):
                dst.write(chunk)
    return path, tag


def publish(github, build):
    state.require(github.api("")["private"], "Publication requires the private platform repository")
    private_package(github, allow_missing=True)
    artifacts = github.api(f"actions/runs/{build['runId']}/artifacts?per_page=100")
    name = f"demo-image-{build['attempt']}"
    matches = [x for x in artifacts["artifacts"] if x["name"] == name and not x["expired"]]
    state.require(len(matches) == 1, "Missing or ambiguous build artifact")
    artifact = matches[0]
    state.require(
        artifact["workflow_run"]["head_sha"] == build["sourceSha"], "Artifact provenance mismatch"
    )
    state.require(artifact["size_in_bytes"] < 1_000_000_000, "Artifact too large")

    # Obtain the signed download location without forwarding Authorization to its host.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    request = urllib.request.Request(
        f"https://api.github.com/repos/{state.REPOSITORY}/actions/artifacts/{artifact['id']}/zip",
        headers={
            "Authorization": "Bearer " + github.token,
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        urllib.request.build_opener(NoRedirect()).open(request, timeout=60)
        raise ValueError("Expected signed artifact redirect")
    except urllib.error.HTTPError as exc:
        state.require(exc.code == 302, "Artifact download failed")
        location = exc.headers["Location"]
    state.require(location.startswith("https://"), "Artifact download must use HTTPS")
    destination = Path(os.environ["RUNNER_TEMP"]) / "previewforge-delivery"
    destination.mkdir(exist_ok=True)
    with urllib.request.urlopen(location, timeout=120) as response:
        data = response.read(1_000_000_001)
    state.require(len(data) <= 1_000_000_000, "Artifact download exceeds limit")
    state.require(
        artifact.get("digest") == "sha256:" + hashlib.sha256(data).hexdigest(),
        "Artifact download checksum does not match GitHub's recorded digest",
    )
    archive, tag = unpack_artifact(io.BytesIO(data), destination, build["sourceSha"])
    subprocess.run(["docker", "load", "--input", str(archive)], check=True, capture_output=True)
    info = json.loads(subprocess.check_output(["docker", "image", "inspect", tag]))[0]
    state.require(
        info["Config"]["Labels"]["org.opencontainers.image.revision"] == build["sourceSha"],
        "Image revision label mismatch",
    )
    state.require(
        [value for value in info["Config"]["Env"] if value.startswith("SOURCE_SHA=")]
        == ["SOURCE_SHA=" + build["sourceSha"]],
        "Image runtime source mismatch",
    )
    state.require(
        state.eligible(build, github.current(build)), "Build became stale before publication"
    )
    reference = state.REMOTE_IMAGE + ":" + build["sourceSha"]
    subprocess.run(["docker", "tag", tag, reference], check=True)
    subprocess.run(
        [
            "docker",
            "login",
            "ghcr.io",
            "--username",
            os.environ["GITHUB_ACTOR"],
            "--password-stdin",
        ],
        input=github.token,
        text=True,
        capture_output=True,
        check=True,
    )
    try:
        output = subprocess.run(
            ["docker", "push", reference], check=True, capture_output=True, text=True
        )
        matches = re.findall(r"digest: (sha256:[a-f0-9]{64})", output.stdout + output.stderr)
        state.require(len(matches) == 1, "Registry did not report one manifest digest")
    finally:
        subprocess.run(["docker", "logout", "ghcr.io"], check=True, capture_output=True)
    # A successful push is insufficient: verify actual package visibility before delivery.
    for attempt in range(6):
        try:
            private_package(github)
            break
        except (urllib.error.HTTPError, PackagePending) as exc:
            if (isinstance(exc, urllib.error.HTTPError) and exc.code != 404) or attempt == 5:
                raise
            time.sleep(2)
    build["image"] = {
        "repository": state.REMOTE_IMAGE,
        "digest": matches[0],
        "pullPolicy": "IfNotPresent",
    }
    return build


def private_package(github, allow_missing=False):
    try:
        package = github.api(
            "users/HickoDev/packages/container/previewforge-demo", global_path=True
        )
    except urllib.error.HTTPError as exc:
        if allow_missing and exc.code == 404:
            return
        raise
    state.require(
        package["visibility"] == "private", "Refusing publication to a non-private package"
    )
    state.require(
        package.get("name") == "previewforge-demo"
        and package.get("owner", {}).get("login") == "HickoDev",
        "Unexpected package identity",
    )
    if not package.get("repository"):
        # GITHUB_TOKEN can omit repository metadata that a classic read:packages
        # token returns. Pin the ID only after the owner verifies its association;
        # the pull credential stays on the laptop, never in Actions.
        approved = os.environ.get("PREVIEWFORGE_PACKAGE_ID", "")
        if not approved:
            raise PackagePending("Verify the package association and configure its approved ID")
        state.require(
            str(package.get("id")) == approved, "Package ID differs from approved package"
        )
        return
    state.require(
        package.get("repository", {}).get("full_name") == state.REPOSITORY,
        "Package must belong to the PreviewForge repository",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["deliver", "reconcile"])
    args = parser.parse_args()
    github = GitHub()
    store = GitHubStore(github)
    if args.action == "deliver":
        build = publish(github, validate_run(github, os.environ["BUILD_RUN_ID"]))
        revision, changed = state.transact(
            store, lambda records: state.update_build(records, build, github.current(build))
        )
    else:
        revision, changed = state.transact(
            store, lambda records: state.prune_records(records, github.pr)
        )
    print(json.dumps({"changed": changed, "configurationRevision": revision}))


if __name__ == "__main__":
    main()
