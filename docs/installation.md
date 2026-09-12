# Host setup: Windows and Linux

The application and platform use the same Python commands on Windows x64 and Linux x64. The host adapters select the appropriate binaries, private runtime paths, process locks and permissions. macOS and ARM hosts are not currently supported or verified.

## Prerequisites

| Requirement | Windows x64 | Linux x64 |
| --- | --- | --- |
| Python | Python 3.12 available as `python` | Python 3.12 with `venv`; use `python3` if `python` is unavailable |
| Containers | Docker Desktop running Linux containers/WSL2 | Docker Engine with a local, rootful daemon accessible to your user |
| Compose | Docker Compose plugin 2.24.4+; Compose 5 works | Docker Compose plugin 2.24.4+; Compose 5 works |
| Git | Git on PATH | Git on PATH |
| GitHub CLI | Needed for uncached platform downloads and owner-operated remote delivery | Same; use a current CLI such as the tested 2.90.0 |

Examples throughout the guides use `python`. On Linux, substitute `python3` consistently if that is your Python 3.12 command. Check before starting:

```text
python --version
git --version
docker version
docker compose version
```

The Bash HTTP examples also require `curl`; you can use the browser API documentation instead.

The Docker server must report Linux containers. Commands operate on the selected local Docker daemon; remote Docker hosts, rootless daemons and Podman have not been verified. Keep the same host account, Docker daemon and runtime directory when resuming retained data. WSL with its own Linux installation follows Linux instructions; sharing Windows runtime files or the same named cluster between Windows and WSL operators is not supported.

Install Docker using its [Windows](https://docs.docker.com/desktop/setup/install/windows-install/) or [Linux Engine](https://docs.docker.com/engine/install/) instructions. The platform installs checksum-pinned kind, kubectl, Helm and Terraform privately rather than changing your system PATH. See [kind's platform binaries](https://kind.sigs.k8s.io/docs/user/quick-start/).

## Choose the installation mode

1. **Application only:** follow [Compose setup](setup.md). This needs no GitHub publishing credential and exposes the task API on localhost:8000.
2. **Local Kubernetes learning environment:** follow [kind setup](kubernetes.md), then [synthetic previews](previews.md). Images and Git commits stay local; exports remain disabled in this initial fixture.
3. **Owner-operated GitHub platform:** follow the [activation reference](previews.md#remote-activation-reference), then the [GitHub runbook](remote.md). This requires existing trusted repository records, Argo Git access and private GHCR pulls. Monitoring, exports and diagnostics use this mode.

The full GitHub automation remains bound to **HickoDev/PreviewForge**. Verify `gh auth status --hostname github.com` shows **HickoDev** active before owner operations. The scripts refuse another account; they do not switch accounts. A public fork can run the standalone application but is not automatically enrolled for remote deployments.

## Runtime and credentials

| Location | Windows default | Linux default |
| --- | --- | --- |
| Installation root | `%LOCALAPPDATA%\PreviewForge` | `${XDG_STATE_HOME:-$HOME/.local/state}/previewforge` |
| Runtime | `<installation-root>/runtime/previewforge-m1` through `previewforge-m6` | Same subdirectory names |
| Tools | `<installation-root>/tools/milestone2` and `milestone5` | Same subdirectory names, native Linux binaries |

On Windows, the existing locations are preserved. `PREVIEWFORGE_HOME` optionally selects a dedicated absolute installation root on either OS. It must be outside the checkout and synced folders. Set it consistently before any command. Changing it does not create a separate Docker installation or migrate existing databases; do not point it at a broad home/workspace directory.

Runtime directories restrict access to the current Windows account/SYSTEM or use mode `0700` on Linux. The Compose password file is readable by the container users inside its protected directory; ordinary Linux users cannot traverse that directory. Docker administrators can access Docker-mounted credentials. Kubernetes Secrets are not encrypted merely because their fields are base64-encoded.

Credentials use an interactive hidden prompt on either OS:

```text
python scripts/configure_remote.py registry
python scripts/assistant.py configure-key
```

The first command needs the configured `argocd` namespace and a HickoDev classic PAT with only `read:packages`. The second configures the assistant's NVIDIA Secret and makes no inference call. Review [registry setup](remote.md#credentials-and-delivery-rules) and [NVIDIA setup](assistant.md#configure-your-nvidia-key-after-review) before using them. Never put credentials in shell arguments, shell history or this checkout. Noninteractive input is rejected by the ordinary prompt commands.

PowerShell wrappers remain available for existing Windows users, but they now call the common Python implementation. Python 3.12 is therefore required for normal Compose startup as well as verification.

## Verification scope

Use [the testing guide](testing.md) and the [portability results](results/portability.md) for measured Windows/Linux outcomes and remaining limits. A passing Linux unit suite alone does not verify Kubernetes startup, container mounts, persistence or remote credentials. macOS/ARM support requires separate binary/image selection and live acceptance before it can be claimed.
