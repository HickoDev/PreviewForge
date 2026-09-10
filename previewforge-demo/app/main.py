from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import make_engine
from app.models import Task
from app.schemas import TaskCreate, TaskRead, TaskUpdate
from app.telemetry import TelemetryMiddleware, make_registry


def get_session(request: Request):
    with Session(request.app.state.engine) as session:
        yield session


Database = Annotated[Session, Depends(get_session)]


def create_app(settings: Settings | None = None, engine=None):
    settings = settings or Settings()
    db_engine = engine if engine is not None else make_engine(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        db_engine.dispose()

    app = FastAPI(title="PreviewForge Task API", version="0.1.0", lifespan=lifespan)
    app.state.engine = db_engine
    registry = make_registry(settings)
    app.add_middleware(TelemetryMiddleware, registry=registry)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return JSONResponse(status_code=503, content={"detail": "Database unavailable"})

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
        return {"status": "ready", "database": "connected"}

    @app.get("/version", summary="Show deployed source and environment")
    def version():
        return {"source_sha": settings.source_sha, "environment": settings.environment_name}

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(registry), headers={"Content-Type": CONTENT_TYPE_LATEST})

    return app
