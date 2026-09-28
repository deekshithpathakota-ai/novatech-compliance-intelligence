from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, Session
from sqlalchemy.types import TypeDecorator

from app.config import get_settings

settings = get_settings()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )


class EmbeddingType(TypeDecorator):
    """pgvector `vector(n)` on PostgreSQL, JSON list elsewhere (SQLite dev/test fallback)."""

    impl = JSON
    cache_ok = True

    def __init__(self, dim: int):
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return list(map(float, value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return list(value)


_engine_kwargs: dict = {"pool_pre_ping": True, "future": True}
if settings.database_url.startswith("sqlite"):
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # Small pool: one API instance + the in-process scan scheduler. pre_ping + recycle survive idle-connection drops
    # on managed Postgres; connect_timeout makes an unreachable database fail fast with a 503 instead of hanging.
    _engine_kwargs.update(pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow,
                          pool_recycle=settings.db_pool_recycle_seconds, pool_timeout=15,
                          connect_args={"connect_timeout": 10})

engine = create_engine(settings.database_url, **_engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
