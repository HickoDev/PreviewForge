import uuid

from sqlalchemy.dialects.postgresql import insert

from app.config import Settings
from app.database import make_engine
from app.models import Task

DEMO_TITLES = ["Explore the API docs", "Create a synthetic task", "Watch the local metrics"]


def seed(engine):
    with engine.begin() as connection:
        for title in DEMO_TITLES:
            connection.execute(
                insert(Task)
                .values(
                    id=uuid.uuid5(uuid.NAMESPACE_URL, f"previewforge:demo:{title}"),
                    title=title,
                )
                .on_conflict_do_nothing(index_elements=[Task.id])
            )


if __name__ == "__main__":
    engine = make_engine(Settings())
    try:
        seed(engine)
        print("Synthetic demo tasks seeded (safe to repeat).")
    finally:
        engine.dispose()
