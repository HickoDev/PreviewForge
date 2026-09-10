# PreviewForge demo application

This logical application component contains the task API, Alembic migrations, deterministic synthetic seeds, PostgreSQL tests and its Dockerfile. The platform repository currently includes it so one checkout can run Milestone 1; no separate remote has been created.

Run the root [startup and verification procedure](../docs/setup.md). Compose deliberately lives at the platform root so PostgreSQL/Floci have one local owner. There is no worker/export API yet; that arrives with Terraform integration in Milestone 5.

The runtime image runs as UID 10001 with a read-only root filesystem in Compose. The test image adds pytest/httpx/ruff. Application dependencies and test dependencies are separately pinned with hashes.

<!-- Milestone 5 export acceptance a -->
