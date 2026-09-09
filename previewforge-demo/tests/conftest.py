import os

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import Settings
from app.database import make_engine
from app.main import create_app


@pytest.fixture(scope="session")
def database_engine():
    # Tests must never silently fall back to the development database.
    if (
        os.environ.get("DATABASE_NAME") != "previewforge_test"
        or os.environ.get("DATABASE_HOST") != "test-db"
    ):
        pytest.fail("Integration tests require the isolated Compose test-db / previewforge_test")
    engine = make_engine(Settings())
    config = Config("alembic.ini")
    config.attributes["engine"] = engine
    command.upgrade(config, "head")
    yield engine
    engine.dispose()


@pytest.fixture
def db(database_engine):
    with database_engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE tasks"))
    yield database_engine


@pytest.fixture
def client(db):
    with TestClient(
        create_app(Settings(source_sha="test-sha", environment_name="test"), db)
    ) as client:
        yield client
