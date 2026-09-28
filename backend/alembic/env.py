from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings
from app.database.init import POSTGRES_EXTRA
from app.database.session import Base
import app.models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata
# Hand-written performance indexes (HNSW, full-text GIN, composites) live in POSTGRES_EXTRA, not in the ORM metadata.
_RAW_INDEXES = {stmt.split(" ON ")[0].split()[-1] for stmt in POSTGRES_EXTRA}


def include_object(obj, name, type_, reflected, compare_to):
    return not (type_ == "index" and name in _RAW_INDEXES)


def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True, include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
