# Milestone 6: NVIDIA connection verification — 2026-09-10

The user authorized configuring their NVIDIA credential and making live diagnostic requests. The key was entered through the existing hidden prompt and stored in the owned `previewforge-nvidia` Kubernetes Secret in `previewforge-ai`. It was not placed in repository files, command arguments or application logs. Rotation uses the same hidden setup command followed by `up --allow-live`.

## Corrections found during live testing

- The original `meta/llama-3.3-70b-instruct` returned HTTP 410. Its [NVIDIA catalog page](https://build.nvidia.com/meta/llama-3_3-70b-instruct) marks the hosted endpoint deprecated, although the API reference is still available. HTTP 410 now reports `model_unavailable` and stops the evaluation.
- An explicitly selected `mistralai/mistral-nemotron` request timed out at the existing 90-second limit. That model was not retained as the default.
- The replacement is `nvidia/nemotron-3-super-120b-a12b`, through the same fixed NVIDIA endpoint. The adapter uses its [documented non-thinking mode](https://build.nvidia.com/nvidia/nemotron-3-super-120b-a12b/modelcard), temperature 1.0 and top_p 0.95, retaining the 1,500-token cap. These options apply only to this exact model. There is no automatic model/provider fallback.
- Initial Nemotron responses included both a valid output and rejected outputs. A diagnostic inspection identified a contradictory abstention containing a hypothesis. Prompt version `previewforge-diagnosis-v2` explicitly defines the relationships between status, facts and hypotheses. Validation remains strict; rejected answers are not converted into successes.
- The smoke/evaluation CLI previously returned zero for some provider or validation failures. It now saves the sanitized report and exits nonzero for those errors or a mismatch with the labeled expectation. Unavailable/rejected models stop a full evaluation after its first case.

Earlier failed smoke reports remain in the private runtime directory. They are part of the observed result, not successful model trials. Raw provider responses and reasoning are not saved.

## Successful application smoke test

The ordinary `python scripts/assistant.py up --allow-live` startup completed with Argo Synced/Healthy. The subsequent `python scripts/assistant.py live-smoke --allow-live` exited zero on 2026-09-10 at 18:18:54 UTC. See the [sanitized smoke report](milestone-6-live-smoke.json).

| Observation | Result |
| --- | --- |
| Provider/model | NVIDIA / `nvidia/nemotron-3-super-120b-a12b` |
| Prompt | `previewforge-diagnosis-v2` |
| Fixture | `wrong-port`, synthetic `preview-42`; no running preview was changed |
| Result | `diagnosed`, `Database port mismatch`, matching the labeled expectation |
| References | Four factual observations with valid exact quotes; hypothesis cites deployment, Service, diff and log evidence |
| Request | `51c4b174-d202-4007-b1f0-33babd46ea0f` |
| Attempts / latency | Two HTTP attempts; 8,906 ms local HTTP round trip |
| Returned usage | 1,333 prompt tokens + 566 completion tokens = 1,899; usage from the earlier attempt is unknown |

Inspection found the four factual observations supported by their excerpts. The hypothesis includes reasonable limitations and suggests human checks. However, the summary states causation too definitively compared with the hypothesis's uncertainty. Structural validation and the correct labeled cause therefore establish a connection smoke pass, not semantic-quality acceptance. The report intentionally keeps human review pending.

The private key and local access token were checked against the saved report before copying it into the repository. Neither appeared in raw or base64 form; no secret canary appeared. A separate check found the NVIDIA key absent from repository files and assistant logs. No credential was committed.

Final checks found staging, observability and the assistant Synced/Healthy. The assistant reported NVIDIA mode with live opt-in enabled; staging returned HTTP 200 and retained its three tasks. The check's loopback forwards were closed afterward.

## Local regression verification

- 70 assistant tests passed with container networking disabled, including HTTP 410 handling and model-specific request settings.
- 60 platform tests passed, including hidden key handling and success/failure evaluation exit behavior.
- Assistant/platform lint and formatting passed; the assistant Helm chart passed lint and rendering.

The two existing TestClient dependency deprecation warnings remain; they do not fail the tests. These local changes have not been submitted to GitHub CI in this verification session.

## Remaining acceptance

The full 13-case hosted evaluation and human semantic review remain pending. One fixture cannot establish model reliability or improvement over the deterministic baseline. A timed-out request can consume quota without returning usage. This connection check does not introduce a new PR, inject a cluster fault, publish an image or provision cloud resources.

From the PreviewForge repository, after configuring a valid key:

```powershell
python scripts/assistant.py up --allow-live
python scripts/assistant.py live-smoke --allow-live
```

For the separate bounded evaluation, when ready:

```powershell
python scripts/assistant.py live-evaluate --allow-live --trials 1
```
