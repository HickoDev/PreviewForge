from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.aws import Cloud
from app.config import Settings
from app.database import make_engine
from app.exports import export_status, request_export
from app.models import Export, Task
from app.schemas import TaskCreate, TaskRead, TaskUpdate
from app.telemetry import TelemetryMiddleware, make_registry


def get_session(request: Request):
    with Session(request.app.state.engine) as session:
        yield session


Database = Annotated[Session, Depends(get_session)]


def create_app(settings: Settings | None = None, engine=None, cloud=None):
    settings = settings or Settings()
    db_engine = engine if engine is not None else make_engine(settings)
    export_cloud = (
        (cloud or Cloud(settings.floci_endpoint, settings.environment_name))
        if settings.exports_enabled
        else None
    )

    @asynccontextmanager
    async def lifespan(app):
        yield
        db_engine.dispose()
        if export_cloud:
            export_cloud.close()

    app = FastAPI(title="PreviewForge Task API", version="0.1.0", lifespan=lifespan)
    app.state.engine = db_engine
    registry = make_registry(settings)
    app.add_middleware(TelemetryMiddleware, registry=registry)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return JSONResponse(status_code=503, content={"detail": "Database unavailable"})

    @app.exception_handler(BotoCoreError)
    @app.exception_handler(ClientError)
    async def cloud_error(request, exc):
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Local export storage or queue unavailable; retry after reconciliation"
            },
        )

    def require_exports():
        if export_cloud is None:
            raise HTTPException(404, "Exports are not enabled in this environment")

    @app.post("/exports", status_code=202, include_in_schema=settings.exports_enabled)
    def new_export(idempotency_key: Annotated[UUID | None, Header()] = None):
        require_exports()
        return request_export(db_engine, export_cloud, idempotency_key)

    @app.get("/exports/{export_id}", include_in_schema=settings.exports_enabled)
    def get_export(export_id: UUID, session: Database):
        require_exports()
        job = session.get(Export, export_id)
        if job is None:
            raise HTTPException(404, "Export not found")
        return export_status(job)

    @app.get("/exports/{export_id}/download", include_in_schema=settings.exports_enabled)
    def download_export(export_id: UUID, session: Database):
        require_exports()
        job = session.get(Export, export_id)
        if job is None:
            raise HTTPException(404, "Export not found")
        if job.status != "completed":
            raise HTTPException(409, "Export is still pending")
        body = export_cloud.s3.get_object(Bucket=export_cloud.bucket, Key=job.object_key)["Body"]

        def chunks():
            try:
                yield from body.iter_chunks(chunk_size=65536)
            finally:
                body.close()

        return StreamingResponse(
            chunks(),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="tasks-{export_id}.json"',
            },
        )

    @app.post("/tasks", response_model=TaskRead, status_code=201)
    def create_task(payload: TaskCreate, session: Database):
        task = Task(title=payload.title)
        session.add(task)
        session.commit()
        session.refresh(task)
        return task

    @app.get("/tasks", response_model=list[TaskRead])
    def list_tasks(
        session: Database,
        limit: Annotated[int, Query(ge=1, le=100)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ):
        return session.scalars(
            select(Task).order_by(Task.created_at, Task.id).offset(offset).limit(limit)
        ).all()

    @app.patch("/tasks/{task_id}", response_model=TaskRead)
    def update_task(task_id: UUID, payload: TaskUpdate, session: Database):
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        task.status = payload.status.value
        task.updated_at = datetime.now(UTC)
        session.commit()
        session.refresh(task)
        return task

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready", summary="Check API and database readiness")
    def ready(session: Database):
        session.execute(text("SELECT 1"))
        session.execute(select(Task.id).limit(1))
        if export_cloud:
            session.execute(select(Export.id).limit(1))
            export_cloud.ready()
            return {"status": "ready", "database": "connected", "exports": "ready"}
        return {"status": "ready", "database": "connected"}

    @app.get("/version", summary="Show deployed source and environment")
    def version():
        return {"source_sha": settings.source_sha, "environment": settings.environment_name}

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(registry), headers={"Content-Type": CONTENT_TYPE_LATEST})

    @app.get("/test/failure", include_in_schema=settings.enable_failure_exercise)
    def failure_exercise():
        """Controlled monitoring exercise; disabled unless explicitly enabled in configuration."""
        if not settings.enable_failure_exercise:
            raise HTTPException(status_code=404, detail="Failure exercise disabled")
        raise HTTPException(status_code=503, detail="Controlled PreviewForge failure exercise")

    return app
