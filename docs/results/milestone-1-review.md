# Milestone 1 review

Reviewed on 2026-09-09 after the user authorized fixes, a commit and a push to `HickoDev/PreviewForge`. Scope remains Milestone 1; no Kubernetes, CI publishing, Terraform or AI implementation was added.

## Findings and fixes

1. **Tests depended on an uncommitted checkout.** The outage unit test inherited the Compose `SOURCE_SHA` value but asserted `local-uncommitted`. It would fail after the first commit. It now supplies and checks an explicit fixture SHA.
2. **A lost creation response could leave smoke resources behind.** The smoke client previously recorded ownership only after a successful response. It now records its unique resource identity before sending the create call, attempts cleanup after timeouts, tolerates only known missing-resource responses, and independently checks absence. Four new regression cases cover S3/SQS timeouts with and without a remotely created resource.
3. **Version verification accepted any nonempty SHA.** The wrapper now passes the expected checkout identity to the HTTP verifier. The verifier checks it before changing containers, after API replacement and after database recovery.
4. **Python optimization could silently remove acceptance assertions.** The smoke and HTTP acceptance entrypoints now reject optimized Python execution before testing or modifying resources.

Setup instructions now describe cloning the authorized repository into a dedicated workspace and starting from the repository root. The earlier [initial verification report](milestone-1.md) is explicitly historical, preserving its original measurements and local cleanup limitation.

## Verification

The documented command completed with exit 0 after these fixes:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\dev.ps1 verify
```

- **27 passing pytest cases:** 21 unit cases and 6 PostgreSQL integration tests. The same two upstream Starlette/httpx/AnyIO deprecation warnings remain visible; there are no test failures or skips.
- ruff lint and formatting checks passed for application/test code; the host HTTP script was also checked.
- Host Floci smoke passed with resource `pf-smoke-2122278190d64b1ea2323c1f05375334`; cleanup was verified.
- Application-container Floci smoke passed with resource `pf-smoke-0fdd29fffd0f474fb50a6147da9e712f`; cleanup was verified.
- Real HTTP CRUD, validation, health, version, metrics and OpenAPI/docs checks passed.
- Task `94ec5b08-a7b0-423f-8469-58a94758f866` retained its status through API container replacement and PostgreSQL outage/recovery.
- Readiness/task requests returned 503 during the database outage; liveness/version/metrics remained available, then readiness recovered.
- Structured log sanitization and the non-root API process check passed.
- Negative checks confirmed that a deliberately incorrect SHA exits before container replacement/database disruption, and that both verification entrypoints reject `python -O`.

The full command above ran before the first commit, so its expected identity was `local-uncommitted`. A committed checkout uses its actual SHA; any local modifications add `-dirty`. The same documented command validates that identity without depending on an uncommitted repository.

The initial clean-source/fresh-database startup and full `down`/`up` persistence results remain recorded in the [initial report](milestone-1.md). The runtime architecture and dependency pins did not change in this review. These are local container and AWS-emulator results, not real AWS or GitHub-to-preview deployment evidence.

## Remaining scope

Milestone 2 and later work still await explicit direction. The AI file is placeholder-only: no mock provider or hosted NVIDIA call has been implemented. No image publication, public service exposure, cloud provisioning or second remote repository is authorized by this review.
