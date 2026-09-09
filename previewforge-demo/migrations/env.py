from alembic import context

from app.config import Settings
from app.database import make_engine
from app.models import Base

config = context.config
engine = config.attributes.get("engine")
owned = engine is None
if owned:
    engine = make_engine(Settings())
try:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
finally:
    if owned:
        engine.dispose()
