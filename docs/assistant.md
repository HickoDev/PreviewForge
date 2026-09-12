# Milestone 6: deployment diagnostics

See [Windows/Linux prerequisites and runtime locations](installation.md) for `<installation-root>`. Commands use `python`; substitute `python3` on Linux if needed.

The assistant explains a selected synthetic PreviewForge API deployment using its immutable image identity, Argo status, safe configuration fields, pod state, recent events and application logs. Every factual observation cites an evidence ID and an exact excerpt. Hypotheses remain suggestions for a person to check. It has no deployment, rollback, Terraform, shell, exec or GitHub-writing capability.

**Implemented and mock-tested. Hosted calls require a privately configured key and explicit live opt-in; see the [live verification record](results/milestone-6-live.md) for tested behavior and remaining acceptance.** Mock mode uses the deterministic baseline; it does not run or simulate a real language model.

## Start and use mock mode

Prerequisites are the configured Python 3.12 / Docker / kind setup on a supported host from [Milestone 5](resources.md). Run from the PreviewForge folder, with your local Docker daemon running. Stop an existing preview watcher before `resources.py up --github`; restart it in a separate terminal after setup for ordinary PR lifecycle operations:

```text
python scripts/resources.py up --github
python scripts/assistant.py up
python scripts/assistant.py diagnose --fixture wrong-port
python scripts/assistant.py diagnose --environment staging
```

`up` builds trusted platform code, loads its immutable manifest into the retained kind node and configures Argo CD to reconcile `charts/ai-assistant`. It defaults to mock mode even if a NVIDIA Secret exists. It publishes no assistant image; the image must be loaded on each replacement kind node. GitHub uses the existing platform repository. The local chart option is a development bootstrap, and refuses to compete once Argo owns the service.

For the API documentation:

```text
python scripts/assistant.py forward
```

Open **http://127.0.0.1:18080/docs**. The `POST /diagnoses` example runs the synthetic wrong-port case. `/fixtures` lists the available cases; `/environments` shows authorized source SHAs. Ctrl+C closes the forward. Diagnostic CLI commands create and close their own forward, so stop a manual forward first, or use `--port 18082`.

To diagnose a running PR, replace `123` with its number:

```text
python scripts/assistant.py diagnose --environment preview-123
```

The trusted CLI verifies namespace ownership, reads the desired record through `gh` as **HickoDev**, checks the observed image and grants narrowly scoped read permissions. The API accepts only the registered environment/source. It rejects another image or a rollout that changes while evidence is collected. Mounted policy updates can take about a minute; after authorizing a new preview, wait and retry if the API reports HTTP 409. For an exact source assertion, add `--source-sha <40-character-source-sha>`.

For a bounded Git comparison, add `--base-revision <known-good-config-commit>`. Both commits must already exist in this checkout. The failing revision is taken from Argo's observed configuration revision. Only approved configuration files and numeric database-port changes are projected; arbitrary file paths and repository archives are never sent. When no supported diff is registered, the report explicitly records that limitation. Source image commits and configuration commits are separate identities.

Remove diagnostic authorization with `python scripts/assistant.py revoke --environment preview-123`. Closing a PR deletes its namespace-scoped Role/RoleBinding along with its environment; revoke also removes its named Argo read binding and private policy entry. Diagnostic availability is independent of the ordinary preview watcher.

## Configure your NVIDIA key after review

The default is **`nvidia/nemotron-3-super-120b-a12b`**, hosted at NVIDIA's existing HTTPS endpoint. Its [catalog example](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b) documents chat completion requests. The [model card](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b/modelcard) documents its context, license and non-thinking option. For this exact model, the adapter sends `chat_template_kwargs.enable_thinking=false`, temperature `1.0` and `top_p=0.95`, with the existing 1,500-token response limit. Other model selections retain the generic request settings; model-specific options are never sent indiscriminately.

The original `meta/llama-3.3-70b-instruct` returned HTTP 410 during live verification. Its [catalog entry](https://build.nvidia.com/meta/llama-3_3-70b-instruct) marks the hosted endpoint deprecated, even though its API reference remains online. The adapter reports `model_unavailable` and stops; it never silently changes model or provider.

Before live use, open the [NVIDIA API Catalog](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b) in your browser, confirm that your account can invoke the model, and review the current model terms and account quota. Follow NVIDIA's [hosted API key setup](https://docs.api.nvidia.com/nim/re/docs/api-quickstart). A registry-download key does not by itself establish hosted inference access; see the [NGC account/key guide](https://docs.nvidia.com/ngc/latest/ngc-user-guide.html). No permanent free quota or production entitlement is assumed.

Run this command yourself in an interactive terminal:

```text
python scripts/assistant.py configure-key
```

Enter the key at the hidden prompt. **Never paste it into chat or a command argument.** The script sends it through stdin into the owned `previewforge-nvidia` Secret in `previewforge-ai`. It does not save the key in Git, OneDrive, an environment file, logs or shell history, and makes no inference call. Kubernetes Secret values are base64-encoded, not inherently encrypted. No preview receives this Secret.

Then explicitly enable hosted mode and run one synthetic smoke case:

```text
python scripts/assistant.py up --allow-live
python scripts/assistant.py live-smoke --allow-live
```

Enabling hosted mode alone does not call NVIDIA. Each diagnostic request additionally needs explicit live opt-in and a separate local access token. The CLI supplies that token privately; application previews do not have it. The smoke test sends a small sanitized synthetic fixture to NVIDIA and allows at most two HTTP attempts. Reported usage covers returned completions; retries/timeouts can consume additional quota without returning usage. A provider failure is separate from an AI abstention.

Smoke/evaluation commands save the sanitized report and return a nonzero exit status for provider errors, invalid output or a mismatch with the labeled expectation. Retired/rejected models stop the run after the first failing case. A successful exit still does not replace review of the model's factual claims.

If the smoke passes and your account has sufficient quota, run the bounded evaluation:

```text
python scripts/assistant.py live-evaluate --allow-live --trials 1
```

This plans **13 logical requests**, at most **26 HTTP attempts**, serially, with a 90-second budget per inference. It stops on authentication/access, quota/rate-limit, timeout or provider-unavailable errors. You can interrupt it with Ctrl+C; each completed case is saved. Repeat trials are opt-in and capped at two. No hosted evaluation runs in CI. Review every live factual claim against its cited excerpt; valid JSON and correct IDs alone do not establish truth. The saved report leaves semantic review pending for real model answers.

To use another catalog model, pass `--model vendor/model-id` to `up --allow-live` after checking that model's parameters, context size and account access. There is no provider/model fallback. JSON mode, tools and reasoning output are not assumed. Responses requiring asynchronous 202 polling are currently reported as provider rejection; the client does not follow arbitrary polling URLs.

To rotate the key, rerun the hidden setup command and `up --allow-live`; the Secret resource version forces the service to reload its environment. Return to offline inference with `python scripts/assistant.py up`.

## What evidence can leave the laptop

Only evidence from explicitly authorized synthetic project environments is eligible. The service reads selected deployment fields, API pod status, namespace events and at most five minutes / forty lines / 8 KiB of logs per selected pod. Only recognized diagnostic signals survive log/event filtering. Pod environment variables are not dumped; the numeric `DATABASE_PORT` field is specifically allowed. There are no task contents, raw database URLs, Secret objects, kubeconfigs, Terraform state, career files or general repository reads in the provider pipeline.

Each evidence item has an environment, source SHA, timestamp and ID; applicable configuration revisions are correlated separately. Stale, mismatched and unknown evidence is omitted with a note. Inputs, concurrency, collection duration, evidence size, prompt bytes, output bytes/tokens and attempts are bounded. The 32,000-byte serialized prompt ceiling is a conservative size guard, not a measured token count.

The collector uses an in-cluster ServiceAccount and namespace-scoped Roles, including named Argo Application reads. It cannot get Secrets, exec/attach, impersonate or mutate workloads. Kubernetes clients and NVIDIA clients use separate credentials. HTTPS requests are restricted to `integrate.api.nvidia.com`, with redirects and environment proxies disabled. No NVIDIA or local access credential is placed in prompt text.

Filtering, field allowlists, synthetic-only inputs and canary tests reduce exposure; regex redaction is not a general data-loss prevention guarantee. This kind cluster still does not claim enforced network isolation. The live diagnostic API requires its own local token to prevent ordinary previews from invoking paid/limited inference through an internal Service.

## Tests and results

```text
python scripts/assistant.py test
python -m unittest discover -s tests/platform -v
python scripts/assistant.py evaluate
```

`test` builds the `previewforge-ai-tests` image used by the evaluation baseline. `evaluate` additionally requires the running assistant in mock mode; it refuses a service configured for NVIDIA. Start mock mode using the commands above, and stop a manual assistant forward before evaluation or use `--port 18082`.

Tests run in a container with **`--network none`**, and the test suite additionally rejects socket connections. Mocked HTTP cases cover missing keys, invalid credentials, inaccessible models, redirects, rate limits, Retry-After, timeouts, server errors, excessive bodies, malformed/truncated output, invalid citations, wrong identities and prompt/secret injection. Dependencies and the Python base image are pinned and hash-checked.

The evaluation contains seven development cases and six separately labeled variations. Their expected results are committed for review. Mock and deterministic baseline share logic, so matching scores show correct integration, not improvement over the baseline or independent model generalization. Live unsupported-statement counts require human review. No small-sample production accuracy or latency percentile is claimed.

For the real Kubernetes failure exercise, stop the normal preview watcher first, then run:

```text
python scripts/assistant.py verify --allow-faults
```

It uses a read-only local Git fixture and the already published demo image in disposable `preview-600006`: healthy config → actual Git port change → failed readiness/log evidence → cited mock diagnosis → explicit Git revert → cleanup. This is a real local GitOps failure test, not a new GitHub PR or NVIDIA evaluation. It preserves staging and does not provision Floci resources for this API-only fixture. After interruption, use `python scripts/assistant.py recover` to remove only owned exercise resources.

`python scripts/verify_assistant_startup.py --allow-faults` separately stops only the assistant, verifies a staging export completes without AI, and runs the ordinary startup command again. It restores the assistant in a `finally` block. Staging and monitoring remain running.

Private reports, policies and recovery journals live under `<installation-root>/runtime/previewforge-m6`, with Windows access restricted to your account/SYSTEM and Linux directory permissions set to `0700`. Prompts/raw provider responses are not logged or saved. Reports include sanitized evidence, validation outcomes, source/config identities, provider/model, prompt version, evidence hash, request IDs, latency and returned usage. Only reviewed synthetic results are copied into [the milestone report](results/milestone-6.md).
