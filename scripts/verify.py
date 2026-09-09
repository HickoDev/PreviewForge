"""Real HTTP checks, API recreation/persistence and a bounded PostgreSQL outage."""

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://127.0.0.1:8000"


def request(path, method="GET", body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        response = urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        content = response.read().decode()
        return response.status, content


def wait_ready():
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            if request("/health/ready")[0] == 200:
                return
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            pass
        time.sleep(1)
    raise AssertionError("API did not become ready within 90 seconds")


def find_task(task_id):
    offset = 0
    while True:
        status, body = request(f"/tasks?limit=100&offset={offset}")
        assert status == 200
        tasks = json.loads(body)
        for task in tasks:
            if task["id"] == task_id:
                return task
        if len(tasks) < 100:
            raise AssertionError("Acceptance task not found")
        offset += 100


def main():
    if not __debug__:
        raise RuntimeError(
            "Acceptance verification requires Python assertions; remove -O/PYTHONOPTIMIZE"
        )
    parser = argparse.ArgumentParser()
    parser.add_argument("--compose", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()

    def compose(*arguments, capture=False):
        return subprocess.run(
            [
                "docker",
                "compose",
                "--file",
                args.compose,
                "--project-name",
                args.project,
                *arguments,
            ],
            check=True,
            text=True,
            capture_output=capture,
            timeout=180,
        )

    wait_ready()
    expected_version = {"source_sha": args.expected_sha, "environment": "local"}
    assert json.loads(request("/version")[1]) == expected_version, (
        "Wrong deployed source SHA"
    )
    for path in ["/docs", "/openapi.json", "/health/live", "/health/ready", "/version"]:
        assert request(path)[0] == 200, path
    status, body = request(
        "/tasks", "POST", {"title": "Synthetic acceptance " + uuid.uuid4().hex[:8]}
    )
    assert status == 201
    task = json.loads(body)
    assert find_task(task["id"])["status"] == "todo"
    status, body = request("/tasks/" + task["id"], "PATCH", {"status": "done"})
    assert status == 200 and json.loads(body)["status"] == "done"
    assert request("/tasks", "POST", {"title": " "})[0] == 422
    metrics = request("/metrics")[1]
    for name in [
        "previewforge_http_requests_total",
        "previewforge_http_errors_total",
        "previewforge_http_request_duration_seconds_bucket",
        "previewforge_build_info",
    ]:
        assert name in metrics
    version = json.loads(request("/version")[1])
    assert version == expected_version
    print("PASS: HTTP CRUD, validation, docs, health, version and metrics", flush=True)

    before = compose("ps", "-q", "api", capture=True).stdout.strip()
    compose("up", "--detach", "--no-deps", "--force-recreate", "api")
    wait_ready()
    after = compose("ps", "-q", "api", capture=True).stdout.strip()
    assert before != after
    assert json.loads(request("/version")[1]) == expected_version
    assert find_task(task["id"])["status"] == "done"
    print("PASS: task survived replacement of the API container", flush=True)

    try:
        compose("stop", "db")
        assert request("/health/live")[0] == 200
        ready_status, ready_body = request("/health/ready")
        assert ready_status == 503
        assert json.loads(ready_body) == {"detail": "Database unavailable"}
        assert request("/tasks")[0] == 503
        assert request("/version")[0] == 200
        assert request("/metrics")[0] == 200
        print(
            "PASS: database outage gives readiness/task 503 while liveness stays 200",
            flush=True,
        )
    finally:
        compose("start", "db")
        wait_ready()
    assert find_task(task["id"])["status"] == "done"
    print("PASS: database recovery and retained task", flush=True)
    assert json.loads(request("/version")[1]) == expected_version
    request("/unknown-synthetic-log-canary?token=synthetic-query-canary")
    logs = compose("logs", "--no-log-prefix", "api", capture=True).stdout
    assert "synthetic-log-canary" not in logs and "synthetic-query-canary" not in logs
    events = [json.loads(line) for line in logs.splitlines() if line.startswith("{")]
    assert any(
        event.get("status") == 503 and event.get("route") == "/health/ready"
        for event in events
    )
    assert all(
        "request_id" in event
        for event in events
        if event.get("event") == "http_request"
    )
    assert (
        compose("exec", "-T", "api", "id", "-u", capture=True).stdout.strip() == "10001"
    )
    print(
        "PASS: structured/sanitized request logs and non-root API process", flush=True
    )
    print(
        json.dumps(
            {
                "status": "passed",
                "task_id": task["id"],
                "version": json.loads(request("/version")[1]),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
