import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.models import Task
from app.seed import DEMO_TITLES, seed

pytestmark = pytest.mark.integration


def test_create_list_update_persisted_in_postgres(client, db):
    created = client.post("/tasks", json={"title": "  Synthetic acceptance task  "})
    assert created.status_code == 201
    task = created.json()
    assert task["title"] == "Synthetic acceptance task"
    assert task["status"] == "todo"
    assert task["created_at"]
    assert client.get("/tasks").json() == [task]
    for status in ("in_progress", "done"):
        patched = client.patch(f"/tasks/{task['id']}", json={"status": status})
        assert patched.status_code == 200
        assert patched.json()["status"] == status
    with db.connect() as connection:
        assert (
            connection.execute(
                select(Task.status).where(Task.id == uuid.UUID(task["id"]))
            ).scalar_one()
            == "done"
        )


def test_validation_missing_task_and_pagination(client):
    assert client.post("/tasks", json={"title": " "}).status_code == 422
    assert client.post("/tasks", json={"title": "x", "surprise": True}).status_code == 422
    assert client.patch(f"/tasks/{uuid.uuid4()}", json={"status": "done"}).status_code == 404
    assert client.patch("/tasks/not-a-uuid", json={"status": "done"}).status_code == 422
    assert client.patch(f"/tasks/{uuid.uuid4()}", json={"status": "invalid"}).status_code == 422
    assert client.get("/tasks?limit=101").status_code == 422
    assert client.get("/tasks?offset=-1").status_code == 422
    for i in range(3):
        assert client.post("/tasks", json={"title": f"synthetic {i}"}).status_code == 201
    assert [task["title"] for task in client.get("/tasks?limit=1&offset=1").json()] == [
        "synthetic 1"
    ]


def test_health_identity_and_bounded_metrics(client):
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").json() == {"status": "ready", "database": "connected"}
    assert client.get("/version").json() == {"source_sha": "test-sha", "environment": "test"}
    task_id = str(uuid.uuid4())
    client.patch(f"/tasks/{task_id}", json={"status": "done"})
    client.get("/untrusted-path-canary?secret=synthetic-canary")
    metrics = client.get("/metrics")
    assert "text/plain" in metrics.headers["content-type"]
    for expected in [
        "previewforge_http_requests_total",
        "previewforge_http_errors_total",
        "previewforge_http_request_duration_seconds_bucket",
        "previewforge_build_info",
        'route="/tasks/{task_id}"',
        'route="unmatched"',
    ]:
        assert expected in metrics.text
    for forbidden in [task_id, "untrusted-path-canary", "synthetic-canary"]:
        assert forbidden not in metrics.text


def test_seed_is_repeatable_without_overwriting_edits(db, client):
    seed(db)
    task = client.get("/tasks").json()[0]
    client.patch(f"/tasks/{task['id']}", json={"status": "done"})
    seed(db)
    with db.connect() as connection:
        assert connection.execute(select(func.count()).select_from(Task)).scalar_one() == len(
            DEMO_TITLES
        )
        assert (
            connection.execute(
                select(Task.status).where(Task.id == uuid.UUID(task["id"]))
            ).scalar_one()
            == "done"
        )


def test_database_constraints(db):
    with pytest.raises(IntegrityError), db.begin() as connection:
        connection.execute(
            text("INSERT INTO tasks (id, title, status) VALUES (:id, 'synthetic', 'invalid')"),
            {"id": uuid.uuid4()},
        )


def test_migrations_repeatable_and_match_models(db):
    config = Config("alembic.ini")
    config.attributes["engine"] = db
    command.upgrade(config, "head")
    command.check(config)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    with db.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0002_exports"
        )
