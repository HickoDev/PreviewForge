# Testing PreviewForge

Choose a check based on what you want to prove. An application test suite, a running local preview and a real GitHub delivery exercise test different parts of the system. Run commands from the repository root with Python 3.12 and a local Docker daemon running Linux containers.

## Check a running application

For the standalone API, follow [Compose setup](setup.md) and use `http://127.0.0.1:8000`. For staging or a real PR, first follow [GitHub-mode startup](remote.md), keep the watcher running and open the appropriate foreground forward:

```text
# Staging; keep this terminal open.
python scripts/platform_local.py forward
```

In another terminal, create and update one synthetic task:

The following example uses PowerShell. Linux/Bash users can use the [curl equivalents](setup.md#try-the-api), changing the base URL to staging or the selected preview. Swagger `/docs` offers the same operations on both hosts.

```powershell
$apiBase = 'http://127.0.0.1:18000'
Invoke-RestMethod "$apiBase/health/ready"
Invoke-RestMethod "$apiBase/version"
$task = Invoke-RestMethod "$apiBase/tasks" -Method Post -ContentType 'application/json' -Body '{"title":"Documentation smoke check"}'
if ($task.status -ne 'todo') { throw 'New task did not start in todo.' }
$updatedTask = Invoke-RestMethod "$apiBase/tasks/$($task.id)" -Method Patch -ContentType 'application/json' -Body '{"status":"done"}'
if ($updatedTask.status -ne 'done') { throw 'Task status update failed.' }
$tasks = Invoke-RestMethod "$apiBase/tasks?limit=100&offset=0"
$tasks | Select-Object id, title, status
```

Expect HTTP 200 readiness, a version response identifying the selected environment/source, and successful task creation and status update. This leaves one synthetic task; the app has no task-delete endpoint. The list is paginated, so a newly created task need not be in the first page of a large dataset. The demo has no frontend or login flow. Swagger is available at `$apiBase/docs`; its browser assets need internet access.

## Check two previews and their exports

Use two active, successfully delivered application PRs. Replace these example numbers and run each forward in its own terminal:

```text
python scripts/previews.py forward --github --pr 123 --port 18051
python scripts/previews.py forward --github --pr 124 --port 18052
```

1. Open `http://127.0.0.1:18051/docs` and `http://127.0.0.1:18052/docs`. Check `/version` on each: expect `preview-123` and `preview-124`, respectively, with their successful build SHAs. An older working build can remain after a failed update.
2. Repeat the task commands above with each base URL and a distinct synthetic title. Confirm each task belongs to its own preview; checking all tasks may require pagination. Patching the first preview's task ID through the other preview should return 404.
3. Follow the [request, poll and download example](resources.md#start-the-configured-laptop), replacing its staging URL with each preview URL. Expect 202 on submission, eventual `completed` status and a JSON report of that environment's tasks at acceptance time. Looking up the first export ID in the other preview should return 404.
4. Open [monitoring](observability.md). Select each environment at `http://127.0.0.1:13000/d/previewforge`; after traffic and a scrape interval, inspect request rate, source identity and ready replicas. Check `http://127.0.0.1:19090/targets` with a Prometheus forward open. Idle traffic can leave latency/error panels empty.

These checks exercise already deployed environments. To prove a **new real workflow**, an eligible application PR must pass Demo CI, trusted delivery, private image pulls and local Argo readiness. A documentation-only PR does not trigger the application workflow. See [PR eligibility and delivery](remote.md#which-prs-get-an-environment).

## Run isolated suites

These commands do not create GitHub PRs, publish images, invoke NVIDIA or inject faults into staging. Initial Docker builds can download pinned dependencies. Application CI requires Compose **2.24.4+**; Compose 5 works.

```text
# Application lint/format, PostgreSQL integration and Floci export tests.
python scripts/ci.py test

# Platform lifecycle/provenance/ownership regressions using mocks and fixtures.
python -m unittest discover -s tests/platform -v

# Assistant lint/format and tests; the test container has no network.
python scripts/assistant.py test
```

The application command creates a uniquely named temporary Compose project, its own test database and an in-memory Floci instance without publishing Floci's host port. It cleans up its containers/network afterward. The earlier `python scripts/dev.py test` tests the Compose baseline and skips the opt-in Floci export integration cases; use `ci.py test` for the full current application suite.

For the labeled mock evaluation, first run `assistant.py test` above to build its baseline test image, then use [assistant startup](assistant.md#start-and-use-mock-mode) and:

```text
python scripts/assistant.py evaluate
```

This requires the running assistant in mock mode and creates its own localhost forward. Stop a manual assistant forward first, or pass `--port 18082`. `assistant.py up` selects mock mode even if a NVIDIA key exists; do not use it to preserve an intentionally live configuration. Mock results measure the deterministic diagnostic pipeline. They do not establish hosted model quality.

## Run lifecycle and fault exercises deliberately

These are separate acceptance procedures with visible side effects. Stop the preview watcher before exercises that use its operation lock, and follow the linked recovery instructions. The flags below describe authorization required by those commands; listing them here does not run or authorize an exercise.

| Procedure | Command | Effects and recovery |
| --- | --- | --- |
| Compose acceptance | `python scripts/dev.py verify` | Replaces the Compose API, briefly stops its DB, creates/deletes owned smoke resources; [Compose recovery](setup.md#verify) |
| Initial local GitOps | `python scripts/platform_local.py verify` | Local-fixture mode only; changes staging, tests DB/image faults and Git recovery; [details](kubernetes.md#verify-the-working-system) |
| Synthetic previews | `python scripts/previews.py verify` | Local-fixture mode only; creates/removes two previews and updates staging; [details](previews.md#run-the-local-demonstration) |
| Monitoring recovery | `python scripts/monitoring.py verify --allow-faults --allow-github-writes --trials 2` | Real GitHub config commits, temporary DB fault and disposable fixture; [recovery](observability.md#repeatable-exercises) |
| Real PR exports/lifecycle | `python scripts/resources.py verify --github --allow-faults --allow-github-writes` | Creates real PRs, triggers image publication and introduces bounded faults; [recovery](resources.md#verification) |
| Cluster restart | `python scripts/verify_resources_startup.py --allow-faults` | Stops/resumes the owned kind node and Floci; interrupts local services; [details](resources.md#verification) |
| Diagnostic failure | `python scripts/assistant.py verify --allow-faults` | Local Git wrong-port fixture, mock diagnosis, Git recovery and cleanup; [details](assistant.md#tests-and-results) |

Hosted NVIDIA smoke/evaluation is a separate opt-in procedure in the [assistant guide](assistant.md#configure-your-nvidia-key-after-review). It sends minimized synthetic evidence to NVIDIA and can consume account quota.

## Interpret a result

Use a command's exit status and saved report together. Keep the source SHA, image digest, configuration revision and timestamp with acceptance evidence; these identify different parts of a deployment. A passing unit suite does not prove GHCR authentication or laptop startup, and a healthy API does not prove new GitHub delivery.

See the [verification evidence index](README.md#read-the-verification-evidence) for completed runs. Historical reports are not a current health check. Full hosted AI quality acceptance, fresh-laptop remote bootstrap and recovery after losing the kind node remain unverified.
